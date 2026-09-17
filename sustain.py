#!/usr/bin/env python3
"""
sustain.py — Tejas's idea: after the initial move, the thing that matters is
whether it SUSTAINS.

"Sometimes the explosion is immediate, but often it comes later, and in those
cases the price does not go much down — it sustains, which is a sign of a
not-immediate but imminent follow-through. If it does not sustain, the momentum
fades and it eventually fails."

CATEGORICALLY DIFFERENT FROM EVERYTHING ELSE TESTED
Every feature so far is computed at or BEFORE entry. This is measured AFTER it.
That is not lookahead as long as it is used to decide HOLD or CUT rather than
whether to enter — it is a management rule, and this project has never tested
one. The only prior post-entry work was the stop study.

THE TEST
At bar K after entry, split events by how much of the move was given back, then
ask what the option did FROM BAR K ONWARDS. If the claim holds, events that held
their ground should have a much better remaining peak than those that faded —
and the split must be visible at K, not only in hindsight.

Entry convention is the trigger (the signal bar's high), matching the pipeline:
these are stop-entries, so `slHit` means the trade never filled.
"""
import os, json, argparse
from collections import defaultdict
import numpy as np, pandas as pd

CAN = "data/candles"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--K", type=int, default=6, help="bars after entry to judge")
    ap.add_argument("--out", default="sustain.parquet")
    a = ap.parse_args()

    ev = pd.read_parquet("events.parquet",
          columns=['signal','spot','expiry','duration','symbol','opt_type','entry_ts',
                   'event_id','activated','entry_premium','trigger_price','y_25x'])
    ev = ev[ev.activated & ev.entry_premium.between(2, 20)]
    print(f"events in scope: {len(ev):,} rows", flush=True)

    buckets = defaultdict(list)
    for r in ev.itertuples():
        buckets[(r.spot, r.expiry, r.duration)].append(r)

    out = []
    for (spot, exp, dur), rows in buckets.items():
        cdir = os.path.join(CAN, spot, exp, str(dur))
        if not os.path.isdir(cdir): continue
        by_sym = defaultdict(list)
        for r in rows: by_sym[r.symbol].append(r)
        for sym, rs in by_sym.items():
            try: arr = np.asarray(json.load(open(os.path.join(cdir, sym + ".json"))), float)
            except Exception: continue
            if arr.ndim != 2 or len(arr) < 3: continue
            t, hi, lo, cl = arr[:,0], arr[:,2], arr[:,3], arr[:,4]
            for r in rs:
                j = int(np.searchsorted(t, r.entry_ts, side="right")) - 1
                if j < 0 or t[j] - r.entry_ts > dur*60: continue
                trig = r.trigger_price
                if not (trig > 0): continue
                K = a.K
                if j + 1 + K >= len(t): continue
                win_lo = lo[j+1:j+1+K]; win_hi = hi[j+1:j+1+K]
                fwd    = hi[j+1+K:]
                if len(win_lo) < K or len(fwd) == 0: continue
                out.append(dict(
                    event_id=r.event_id, signal=r.signal, spot=spot, ty=r.opt_type,
                    duration=dur, entry_ts=r.entry_ts, y25=r.y_25x,
                    # how much was given back in the first K bars
                    drawdown=float(win_lo.min())/trig,
                    # what it had already made by bar K
                    run_k=float(win_hi.max())/trig,
                    close_k=float(cl[j+K])/trig,
                    # what was STILL to come, measured from bar K onward
                    peak_after=float(fwd.max())/trig,
                    peak_full=float(max(win_hi.max(), fwd.max()))/trig))
    d = pd.DataFrame(out)
    d.to_parquet(a.out, index=False)
    print(f"wrote {a.out}: {len(d):,} rows (K={a.K})")

if __name__ == "__main__":
    main()
