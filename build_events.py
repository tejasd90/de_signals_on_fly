#!/usr/bin/env python3
"""
build_events.py — Phase 0 of docs/ML/CONTEXT_PLAN.md.

ONE ROW PER STRIKE-FIRING: a signal fired, on one contract, at one moment.
This is the population the context study grades. It has never been built —
every prior ML table in this project was signal-FREE (disc_final's `signal`
column is 100% NULL).

UNIT, AND WHY IT MATTERS
A merged range covers several strikes at once (otm_wall averages 9.4 of them,
the others 2.2-4.0). A row here is one STRIKE, but every row carries `event_id`
and `merged_count` so analysis can collapse back to the merged firing. Weight by
event, not by row, whenever the four signals are pooled — otherwise otm_wall is
silently over-weighted ~2.4x (HANDOFF 3.2's inflation trap in miniature).

OUTCOME IS A MULTIPLE, NOT A PRICE
max(high) AFTER the signal bar, divided by an entry price. Using an absolute
price would be HANDOFF 3.1, which cost two full runs.

TWO ENTRY CONVENTIONS COEXIST IN THIS REPO — both are carried here
  query_lang.js   `ratio` = peak / entry CLOSE
  otm_common.js   `signalRatio` = peak / triggerPrice = the signal bar's HIGH
They differ by a median 11% on this data because high >= close. The TRIGGER one
is the tradeable one: every signal here activates as a STOP-ENTRY above the
signal bar's high, which is why `signalState` is 'slHit' when the high is never
exceeded. `slHit` does not mean a stop-loss was taken — it means THE TRADE NEVER
FILLED. Those rows are not trades and must be excluded from any expectancy.
  peak_vs_close   the query_lang convention, for continuity with older numbers
  peak_vs_trigger the tradeable one
  activated       did price ever exceed the trigger; False = no fill

MERGED-RANGE IMPRECISION
The stored format keeps only the LATEST trigger timestamp across the strikes it
merged, so every strike in an event shares one entry time. That is exact for a
1-strike event and loosest for otm_wall, which merges 9.4 strikes on average.
Inherent to the stored format; `patterns.js` is the unmerged path if it ever
matters enough to rebuild.

MARK PRICES — deliberate, and it bounds what this table can claim
Outcomes come from the stored MARK candles. CONTEXT_PLAN Phase 0 asked for
traded prints; that needs an API fetch per contract and there are ~400k firings,
so it is not feasible for the full table. The measured haircut is ~23% on fill
probability (median capture 96.4% on a 50-instrument spot check), and it applies
roughly uniformly. Since every claim in this study is RELATIVE — does context A
beat context B — a uniform haircut cancels. Absolute returns from this table are
not quotable. Validate the surviving contexts on traded prints later, on the
much smaller set that survives.

No column starts with `label` or `_` (the disc_final trap). Outcome columns are
`y_*` so a prefix filter on 'y_' is unambiguous.
"""
import argparse, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd

SIG_DIR, CAN_DIR, SPOT_DIR = "data/signals", "data/candles", "data/spot_candles"
IST = 19800

def iso_to_ts(s):
    """'2026-08-19T19:30:00+0530' -> unix seconds. Handles the +0530 form that
    python's fromisoformat rejects on 3.9."""
    try:
        base, off = s[:-5], s[-5:]
        import datetime as dt
        d = dt.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
        sign = 1 if off[0] == '+' else -1
        secs = int(off[1:3]) * 3600 + int(off[3:5]) * 60
        return int(d.replace(tzinfo=dt.timezone.utc).timestamp()) - sign * secs
    except Exception:
        return None

def load_spot(spot):
    d = os.path.join(SPOT_DIR, spot, "60")
    if not os.path.isdir(d): return None
    rows = []
    # Spot candle files are named by DATE with no extension, unlike option
    # candles which are `{symbol}.json`. Filtering on .json here returned zero
    # files, so spot_at_entry and moneyness_pct came out 100% NaN and nothing
    # noticed until moneyness was first needed. Fixed 2026-09-16.
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or ".tmp." in fn: continue
        try: rows.extend(json.load(open(os.path.join(d, fn))))
        except Exception: pass
    if not rows: return None
    a = np.asarray(rows, float); a = a[np.argsort(a[:, 0])]
    _, k = np.unique(a[:, 0], return_index=True)
    return a[np.sort(k)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-duration", type=int, default=30)
    ap.add_argument("--horizon-bars", type=int, default=72)
    ap.add_argument("--limit-expiries", type=int, default=0)
    ap.add_argument("--out", default="events.parquet")
    a = ap.parse_args()

    signals = sorted(d for d in os.listdir(SIG_DIR) if not d.startswith("."))
    spots_seen = {}
    # (spot, expiry, duration) -> list of firing dicts, so each candle file is
    # opened exactly once no matter how many firings land on it.
    buckets = defaultdict(list)
    n_ev = 0

    for sig in signals:
        for spot in sorted(d for d in os.listdir(os.path.join(SIG_DIR, sig))
                           if not d.startswith(".") and not d.startswith("_")):
            base = os.path.join(SIG_DIR, sig, spot)
            durs = sorted(int(x) for x in os.listdir(base)
                          if x.isdigit() and int(x) >= a.min_duration)
            for du in durs:
                ddir = os.path.join(base, str(du))
                files = sorted(f for f in os.listdir(ddir)
                               if f.endswith(".json") and ".tmp." not in f)
                if a.limit_expiries: files = files[-a.limit_expiries:]
                for fn in files:
                    exp = fn[:-5]
                    try: data = json.load(open(os.path.join(ddir, fn)))
                    except Exception: continue
                    for typ in ("C", "P"):
                        for r in (data.get(typ) or []):
                            ts = iso_to_ts(r[1])
                            if ts is None: continue
                            n_ev += 1
                            eid = f"{sig}|{spot}|{exp}|{du}|{r[1]}|{typ}"
                            for sym in (r[6] or []):
                                buckets[(spot, exp, du)].append(dict(
                                    signal=sig, spot=spot, expiry=exp, duration=du,
                                    symbol=sym, opt_type=typ, entry_ts=ts,
                                    entry_iso=r[1], event_id=eid,
                                    merged_count=int(r[2] or 0),
                                    signal_value=float(r[3] or 0),
                                    ratio_oracle=float(r[4] or 0),
                                    state=r[5] or "",
                                ))
    print(f"scanned {n_ev:,} merged firings -> {sum(len(v) for v in buckets.values()):,} "
          f"strike-firings across {len(buckets):,} (spot,expiry,duration) groups", flush=True)

    out, done = [], 0
    for (spot, exp, du), rows in buckets.items():
        if spot not in spots_seen: spots_seen[spot] = load_spot(spot)
        sp = spots_seen[spot]
        cdir = os.path.join(CAN_DIR, spot, exp, str(du))
        by_sym = defaultdict(list)
        for r in rows: by_sym[r["symbol"]].append(r)

        for sym, rs in by_sym.items():
            p = os.path.join(cdir, sym + ".json")
            try: arr = np.asarray(json.load(open(p)), float)
            except Exception: continue
            if arr.ndim != 2 or len(arr) < 2: continue
            t, hi, cl = arr[:, 0], arr[:, 2], arr[:, 4]
            parts = sym.split("-")
            strike = float(parts[2]) if len(parts) > 3 else np.nan

            for r in rs:
                j = int(np.searchsorted(t, r["entry_ts"], side="right")) - 1
                if j < 0 or abs(t[j] - r["entry_ts"]) > du * 60: continue
                entry = cl[j]
                if not (entry > 0): continue
                fwd = hi[j + 1:]
                if len(fwd) == 0: continue
                pk_full = float(fwd.max())
                pk_h = float(fwd[:a.horizon_bars].max())
                k = int(np.argmax(fwd)) + 1
                trig = float(hi[j])
                spx = np.nan
                if sp is not None:
                    i = int(np.searchsorted(sp[:, 0], r["entry_ts"], side="right")) - 1
                    if i >= 0: spx = float(sp[i, 4])
                pf = pk_full / entry
                pt = pk_full / trig if trig > 0 else np.nan
                out.append({**r, "strike": strike, "entry_premium": float(entry),
                            "trigger_price": trig, "activated": bool(pk_full > trig),
                            "spot_at_entry": spx,
                            "moneyness_pct": (strike - spx) / spx * 100 if spx == spx else np.nan,
                            "peak_vs_close": pf, "peak_vs_trigger": pt,
                            "peak_72b": pk_h / entry,
                            "bars_to_peak": k, "n_fwd_bars": int(len(fwd)),
                            "y_2x": pt >= 2, "y_5x": pt >= 5,
                            "y_10x": pt >= 10, "y_25x": pt >= 25})
        done += 1
        if done % 2000 == 0: print(f"  {done:,}/{len(buckets):,} groups", flush=True)

    df = pd.DataFrame(out)
    bad = [c for c in df.columns if c.startswith("label") or c.startswith("_")]
    assert not bad, f"forbidden column names: {bad}"
    df.to_parquet(a.out, index=False)
    print(f"\nwrote {a.out}: {len(df):,} rows x {len(df.columns)} cols")
    print(f"distinct events {df.event_id.nunique():,}  contracts {df.symbol.nunique():,}")

if __name__ == "__main__":
    main()
