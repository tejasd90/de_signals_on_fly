"""Assemble dashboard payloads: candles, price-action events, option-requirement grid.

THE EXPIRY SLOT RULE (his spec): for every bar, three slots --
  immediate   the nearest expiry still alive
  next        the one after that
  weekly      the nearest FRIDAY expiry not already taken by the two above
                ("if next one is weekly, then this will be for next weekly")

Checked against the live chain on 2026-10-01, where expiries are
01 Oct (Thu), 02 Oct (Fri), 03 Oct (Sat), 09 Oct (Fri):
  immediate = 01 Oct, next = 02 Oct -- which IS the Friday weekly -- so the third
  slot rolls to 09 Oct. Exactly the case the rule was written for.

ROLLOVER CONSISTENCY: slots are resolved per bar from the expiries alive AT THAT
BAR, so scrolling into the past shows the expiries that were actually live then,
not today's.
"""
import os, re, glob, json
import numpy as np, pandas as pd

REQ = "data/dashreq"

# Level detection runs over whatever load_tf returns. At 15m that is 96,433 bars,
# which yields ~970 horizontal levels and then scans each across the whole series
# -- about 93M Python operations, and it hung the endpoint. The dashboard never
# shows more than a few thousand bars, and a "level" drawn from 2024 on a 15m
# chart is not a thing anyone trades, so detection is windowed to the view plus
# a margin for context.
import contextlib
import levels as _LV

@contextlib.contextmanager
def windowed(tail):
    """Truncate load_tf to the last `tail` bars for the duration of the block."""
    orig = _LV.load_tf
    def patched(spot, tf):
        a = orig(spot, tf)
        return a if a is None or tail is None or len(a) <= tail else a[-tail:]
    _LV.load_tf = patched
    try:
        import wedge as _W
        worig = getattr(_W, "load_tf", None)
        if worig is not None: _W.load_tf = patched
        yield
    finally:
        _LV.load_tf = orig
        try:
            import wedge as _W
            if worig is not None: _W.load_tf = worig
        except Exception: pass

def _exp_date(name):          # BTC_60_2026-09-16.parquet -> Timestamp
    return pd.Timestamp(name.rsplit("_", 1)[1].replace(".parquet", ""))

# A 2-day contract has only 2 DAILY bars, so build_expiry skips it at res 1440 --
# which left the 1d view with ~140 expiries instead of 986, losing the immediate
# and next slots, the two that matter most. So the requirement is computed at a
# FINE resolution and aligned to whatever candle resolution is being viewed.
SOURCE_RES = {"1440": "240", "240": "240", "60": "60", "15": "15"}

def load_req(asset, res, t0=None, t1=None):
    """Long table: one row per (ts, expiry) with both percentages for C and P.

    WINDOWED. The first version loaded every expiry file for the asset (750+ at
    15m) and made the endpoint hang. Only expiries that were ALIVE during the
    requested window can contribute, so filter by filename date before reading:
    an expiry matters if it falls between the window start and ~70 days past its
    end (contracts are listed at most ~38 days before expiry, plus slack).
    """
    lo = pd.Timestamp(t0, unit="s") - pd.Timedelta(days=1) if t0 else None
    hi = pd.Timestamp(t1, unit="s") + pd.Timedelta(days=70) if t1 else None
    fr = []
    src = SOURCE_RES.get(str(res), str(res))
    for fp in sorted(glob.glob(f"{REQ}/{asset}_{src}_*.parquet")):
        e = _exp_date(os.path.basename(fp))
        if lo is not None and e < lo: continue
        if hi is not None and e > hi: continue
        try: d = pd.read_parquet(fp)
        except Exception: continue
        if not len(d): continue
        d["expiry"] = e
        fr.append(d)
    if not fr: return None
    t = pd.concat(fr, ignore_index=True)
    if t0 is not None: t = t[t.ts >= t0]
    if t1 is not None: t = t[t.ts <= t1]
    return t.sort_values(["ts", "expiry"]) if len(t) else None

def assign_slots(t):
    """Per bar, label each live expiry immediate / next / weekly.

    VECTORISED. The first version looped over every ts group in Python and made
    the 15m endpoint hang. Rank within each bar instead:
      immediate = rank 0, next = rank 1,
      weekly    = the first FRIDAY among rank >= 2, i.e. the nearest Friday not
                  already consumed by the two slots above -- which is exactly his
                  "if next one is weekly, then this will be for next weekly".
    """
    if t is None or not len(t): return pd.DataFrame()
    t = t.sort_values(["ts", "expiry"]).copy()
    t["rank"] = t.groupby("ts").cumcount()
    t["is_fri"] = t.expiry.dt.dayofweek == 4
    imm = t[t["rank"] == 0].assign(slot="immediate")
    nxt = t[t["rank"] == 1].assign(slot="next")
    fri = t[(t["rank"] >= 2) & t.is_fri]
    wk  = fri.groupby("ts", as_index=False).first().assign(slot="weekly") if len(fri) else fri
    out = pd.concat([x for x in (imm, nxt, wk) if len(x)], ignore_index=True)
    if not len(out): return pd.DataFrame()
    out["expiry"] = out.expiry.dt.date.astype(str)
    out["ts"] = out.ts.astype("int64")
    keep = ["ts","slot","expiry","tte_d","spot","c_now","c_exp","p_now","p_exp",
            "c_k_now","c_k_exp","p_k_now","p_k_exp"]
    return out[keep].sort_values(["ts","slot"]).reset_index(drop=True)

def candles(asset, res):
    rows = []
    for p in sorted(glob.glob(f"data/spot_candles/{asset}/{res}/*")):
        if os.path.basename(p).startswith("."): continue
        try: rows.extend(json.load(open(p)))
        except Exception: pass
    if not rows: return None
    a = np.asarray([r[:5] for r in rows], float)
    a = a[np.argsort(a[:, 0])]
    _, k = np.unique(a[:, 0], return_index=True)
    a = a[np.sort(k)]
    return pd.DataFrame(a, columns=["ts", "o", "h", "l", "c"])

def events(asset, res, tail=None):
    """Price-action points: swings, level rejections, line breaks, wedge breaks.

    IMPORTANCE is the dot size. Labelled honestly in the description: the audit
    (AUDIT_2026-09-30.md) found breaks arrive AFTER the move 62-74% of the time,
    so these are DESCRIPTIVE markers, not entry signals, and the UI says so.
    """
    import levels as LV
    try:
        from wedge import find_wedges
    except Exception:
        find_wedges = lambda *a, **k: []
    tf = int(res)
    with windowed(tail):
        try: conf, arr = LV.all_levels(asset, tf)
        except Exception: return pd.DataFrame()
        if arr is None: return pd.DataFrame()
        try: wd = {w["break_i"]: w for w in find_wedges(asset, tf)}
        except Exception: wd = {}
    out = []
    for L in conf:
        kind = L["kind"]; typ = L["type"]
        for rts in L.get("rejects", [])[:40]:
            out.append(dict(ts=int(rts), price=float(L.get("price", np.nan)),
                            imp=min(float(L.get("n_rej", 3)), 8.0), kind="rejection",
                            desc=f"{typ} {kind}-level rejection, {L.get('n_rej')} touches"))
        bi = L.get("break_i")
        if bi:
            age = (bi - L["anchor"][0]) * tf / 1440.0 if typ == "trendline" else None
            w = wd.get(bi)
            d = f"{typ} {kind}-line BREAK"
            if age: d += f", line age {age:.0f}d"
            if w: d += f", WEDGE (squeeze {w['squeeze']:.2f})"
            d += " — descriptive: breaks follow the move 62–74% of the time"
            out.append(dict(ts=int(arr[bi, 0]), price=float(arr[bi, 4]),
                            imp=8.0 if w else (6.0 if (age or 0) >= 100 else 4.0),
                            kind="wedge" if w else "break", desc=d))
    if not out: return pd.DataFrame()
    e = pd.DataFrame(out).dropna(subset=["price"])
    return e.sort_values("ts")

def payload(asset, res, limit=1500):
    c = candles(asset, res)
    if c is None: return {"error": f"no candles for {asset}/{res}"}
    c = c.tail(limit)
    t0, t1 = int(c.ts.min()), int(c.ts.max())
    r = load_req(asset, res, t0, t1)
    slots = assign_slots(r)
    # Align the (finer-resolution) requirement rows onto the candle timestamps,
    # so the heatmap joins exactly even when the two grids differ.
    # Matched on CLOSE times: a candle shows the requirement as of its own close (for a
    # daily candle built from 4h rows, the 20:00-24:00 row), or the latest available
    # inside a still-forming candle. Matching on open times showed a daily candle the
    # requirement from 4 hours into its day.
    if len(slots):
        step = int(np.median(np.diff(c.ts.to_numpy()))) if len(c) > 2 else 86400
        src_step = int(SOURCE_RES.get(str(res), str(res))) * 60
        cc = c[["ts"]].astype("int64").assign(close=lambda d: d.ts + step).sort_values("close")
        aligned = []
        for name, g in slots.groupby("slot"):
            g = g.astype({"ts": "int64"}).rename(columns={"ts": "src_ts"})
            g["close"] = g.src_ts + src_step
            m = pd.merge_asof(cc, g.sort_values("close"), on="close", direction="backward", tolerance=step)
            m["slot"] = name
            aligned.append(m.dropna(subset=["expiry"]).drop(columns=["close", "src_ts"]))
        slots = pd.concat(aligned, ignore_index=True) if aligned else slots

    tail = max(limit * 3, 1500)
    e = events(asset, res, tail=tail)
    if len(e):
        e = e[e.ts >= t0]
        e = attach_req_to_events(e, slots)
    return {
        "asset": asset, "res": res,
        "candles": c.to_dict("list"),
        "events": (e.replace({np.nan: None}).to_dict("records") if len(e) else []),
        "req": (slots.to_dict("records") if len(slots) else []),
        "proximity": proximity(asset, res, tail=tail),
    }

if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    r = sys.argv[2] if len(sys.argv) > 2 else "60"
    p = payload(a, r, limit=200)
    print({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in p.items()})
    if p.get("req"): print("sample req rows:"); [print(" ", x) for x in p["req"][:6]]
    if p.get("events"): print("sample events:"); [print(" ", x) for x in p["events"][:3]]


# ---------------------------------------------------------------- proximity --
def proximity(asset, res, tail=None):
    """Active levels/lines, how far price is from each, and the STATE.

    His point: *"give when the price is APPROACHING a price action point... so
    that I can process the information and make casewise decisions on how to act
    BEFORE the price confirmed."*

    That is the right response to the audit. AUDIT_2026-09-30.md found the break
    arrives AFTER the option is already running 62-74% of the time, so a confirmed
    break is structurally late. The only way to be early is to watch the approach.

    States, measured in ATR so they scale with regime:
      APPROACHING   0.4 - 1.5 ATR away and closing
      TESTING       within 0.4 ATR  (the wick is in it right now)
      CONFIRMED     the level has already broken or rejected
    """
    import levels as LV
    try: from wedge import line_at, find_wedges
    except Exception: return []
    tf = int(res)
    with windowed(tail):
        try: conf, arr = LV.all_levels(asset, tf)
        except Exception: return []
        if arr is None or len(arr) < 30: return []
        try: wd0 = {w["break_i"]: w for w in find_wedges(asset, tf)}
        except Exception: wd0 = {}
    h, l, c = arr[:, 2], arr[:, 3], arr[:, 4]
    A = LV.atr(h, l, c)
    i = len(arr) - 1
    px, atr = float(c[i]), float(A[i]) if np.isfinite(A[i]) and A[i] > 0 else float(c[i]) * 0.01
    wd = wd0

    out = []
    for L in conf:
        typ, kind = L["type"], L["kind"]
        if typ == "trendline":
            try: lvl = float(line_at(L, arr, i))
            except Exception: continue
            age = (i - L["anchor"][0]) * tf / 1440.0
        else:
            lvl = float(L.get("price", np.nan)); age = None
        if not np.isfinite(lvl) or lvl <= 0: continue
        d_atr = (px - lvl) / atr
        broken = bool(L.get("break_i"))
        a = abs(d_atr)
        if broken:                      state, weight = "CONFIRMED", 1.0
        elif a <= 0.4:                  state, weight = "TESTING", 0.85
        elif a <= 1.5:                  state, weight = "APPROACHING", 0.5
        else:                           continue      # too far to matter
        label = f"{typ} {kind}"
        if age is not None: label += f" (age {age:.0f}d)"
        if L.get("break_i") in wd: label += " WEDGE"
        out.append(dict(kind=typ, side=kind, level=lvl, price=px,
                        dist_pct=100.0*(lvl/px - 1.0), dist_atr=float(d_atr),
                        n_rej=int(L.get("n_rej", 0)), age_d=age,
                        state=state, weight=weight, label=label,
                        above=bool(lvl > px)))
    out.sort(key=lambda r: abs(r["dist_atr"]))
    return out[:14]


def attach_req_to_events(ev, req):
    """What a 1:100 would have needed AT each price-action point.

    His framing: *"capture what multibagger could option buying offer from
    important price action points, but observe this from charts."* So every dot
    carries the required move that was live when it printed -- the chart answers
    "if I had acted here, how far did spot have to go".
    """
    if not len(ev) or req is None or not len(req): return ev
    r = req[req.slot == "immediate"][["ts", "c_now", "p_now", "c_exp", "p_exp"]]
    if not len(r): return ev
    e = ev.sort_values("ts").copy()
    m = pd.merge_asof(e, r.sort_values("ts"), on="ts", direction="backward",   # never a LATER requirement (review D8)
                      tolerance=int(res_seconds_guess(e)))
    for col in ("c_now", "p_now", "c_exp", "p_exp"):
        if col in m: e[col] = m[col].to_numpy()
    return e

def res_seconds_guess(e):
    if len(e) < 3: return 86400
    d = np.diff(np.sort(e.ts.unique()))
    return max(int(np.median(d)) * 3, 3600) if len(d) else 86400
