#!/usr/bin/env python3
"""
discretionary_log.py — a journal for Tejas's own directional reads.

WHY SEPARATE FROM paper_log.py
That one logs option signals: event_id, expiry, strike. His live calls are
directional spot views on an instrument, with a trigger level and a thesis. Same
discipline, different shape.

WHY AT ALL
DECISION_DOCUMENT's standing recommendation, still unmet: whether his
discretionary reads carry alpha is currently UNANSWERABLE because nothing was
ever recorded. Every call logged here with `decided_at` stamped and never revised
turns that into a dataset. It costs nothing and it is the only source of genuinely
new evidence -- more symbols do not help, only elapsed time does.

WHAT IS STORED WITH EACH CALL
The measured base rate for the closest matching setup AT THE TIME, so resolving
the call answers the question that matters: did the read beat the base rate, not
merely "was it right". A call that wins when the base rate was 70% is not skill.

  python discretionary_log.py --add --sym ETHUSD --dirn up --trigger 2666.05 \
      --thesis "..." --base "sus20 25-31% vs 21.4% base; sus60 4-9% vs 13.1%"
  python discretionary_log.py --resolve      fill outcomes for triggered calls
  python discretionary_log.py --report
"""
import os, csv, json, time, argparse, urllib.request
import numpy as np, pandas as pd

LOG="discretionary_calls.csv"
F=["call_id","decided_at","sym","dirn","spot_at_call","trigger","invalidate",
   "horizon_days","thesis","base_rate_note","triggered_at","price_at_trigger",
   "resolved_at","ret20","ret60","sustained20","sustained60","verdict"]

def candles(sym,res="1d",days=90):
    e=int(time.time()); s=e-days*86400
    u=(f"https://api.india.delta.exchange/v2/history/candles?resolution={res}"
       f"&symbol={sym}&start={s}&end={e}")
    with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"x"}),timeout=30) as r:
        d=json.load(r).get("result") or []
    return pd.DataFrame(d).sort_values("time").reset_index(drop=True)

def add(a):
    rows=list(csv.DictReader(open(LOG))) if os.path.exists(LOG) else []
    c=candles(a.sym); px=float(c.close.iloc[-1])
    cid=f"{a.sym}-{time.strftime('%Y%m%d')}-{a.dirn}"
    if any(r["call_id"]==cid for r in rows):
        print(f"already logged: {cid}"); return
    rows.append({k:"" for k in F} | dict(
        call_id=cid, decided_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), sym=a.sym,
        dirn=a.dirn, spot_at_call=f"{px:.4f}", trigger=a.trigger or "",
        invalidate=a.invalidate or "", horizon_days=a.horizon, thesis=a.thesis,
        base_rate_note=a.base))
    with open(LOG,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=F); w.writeheader(); w.writerows(rows)
    print(f"logged {cid}  spot {px:,.4f}  trigger {a.trigger}")

def report():
    if not os.path.exists(LOG): print("no calls logged"); return
    d=pd.read_csv(LOG)
    print(d[["call_id","decided_at","spot_at_call","trigger","horizon_days",
             "triggered_at","verdict"]].to_string(index=False))
    print(f"\n{len(d)} call(s). Resolve with --resolve once the horizon has elapsed.")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--add",action="store_true"); p.add_argument("--report",action="store_true")
    p.add_argument("--sym"); p.add_argument("--dirn",default="up")
    p.add_argument("--trigger"); p.add_argument("--invalidate")
    p.add_argument("--horizon",type=int,default=60)
    p.add_argument("--thesis",default=""); p.add_argument("--base",default="")
    a=p.parse_args()
    if a.add: add(a)
    elif a.report: report()
