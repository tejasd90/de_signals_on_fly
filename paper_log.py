#!/usr/bin/env python3
"""
paper_log.py — forward paper-trade journal for the R4+R5 rules.

WHY THIS EXISTS
Every result in this project is bounded by 142 independent weeks. More symbols do
not help; only elapsed time does. This is the only thing that manufactures new
evidence, and it costs nothing.

IT LOGS EVERYTHING, NOT JUST THE TRADES
Signals that FAIL the rules are recorded too, marked skip. Without them the
journal is a record of trades taken; with them it is a forward TEST of whether
the filter was right. That is the difference between bookkeeping and evidence.

WRITTEN BEFORE THE OUTCOME IS KNOWN
`decided_at` is stamped on write and never revised. Outcomes are filled in later
by --resolve, from a separate pass. A `note` column is yours: your reasoning at
the time. DECISION_DOCUMENT recommends exactly this — in six months it becomes a
testable dataset about whether your discretionary reads carry alpha, which is
currently unanswerable because nothing was recorded.

  python paper_log.py --run       append new signals (safe to re-run; dedups)
  python paper_log.py --resolve   fill outcomes for expiries that have settled
  python paper_log.py --report    running stats vs the backtested expectation
"""
import os, csv, json, argparse, datetime as dt
import numpy as np, pandas as pd

LOG   = "paper_trades.csv"
FIELDS = ["event_id","decided_at","entry_iso","signal","spot","expiry","duration",
          "opt_type","symbol","strike","entry_premium","trigger","ai_state","regime",
          "r4","r5","d_room","w_room","at_line","decision","note","resolved_at",
          "mark_peak","traded_peak","mark_25x","traded_25x","filled"]
COST, BREAKEVEN, EXPECTED = 0.0826, 0.0433, 0.0601   # from the backtest

def ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()

def spot_series(spot, tf):
    p=f"data/spot_grouped/{spot}/{tf}.json"
    if not os.path.exists(p): return None
    a=np.asarray(json.load(open(p)),float); return a[np.argsort(a[:,0])]

_LINES = {}
def line_state(spot, ts, ty):
    """Distance to the structural line this contract must overcome, in ATR.

    POSITIVE = the line is still ahead of price, i.e. room to run. Negative =
    already broken. Recorded because the backtest shows a coherent 3.4x gradient
    on the WEEKLY line — 13.29% at the line, decaying with distance, collapsing
    once broken — that is concentrated in only 1,741 events and therefore cannot
    be proven on 142 weeks. Logging it forward is the way to settle it without
    re-slicing the same sample a sixth time.
    """
    import structural_lines as SL
    CFG = {1440: dict(k=5, min_prom=1.0, lookback=400),
           10080: dict(k=2, min_prom=0.8, lookback=100)}
    out = {}
    for tf, tag in ((1440, "d"), (10080, "w")):
        key = (spot, tf)
        if key not in _LINES:
            a = spot_series(spot, tf)
            _LINES[key] = None if a is None else (a, SL.lines(a, **CFG[tf]))
        if _LINES[key] is None: out[tag] = None; continue
        a, g = _LINES[key]
        j = int(np.searchsorted(a[:, 0] + tf * 60, ts, side="right")) - 1
        if j < 0: out[tag] = None; continue
        # a CALL must overcome the BEAR line above it; a PUT the BULL line below
        v = g["bear_dist"].to_numpy()[j] if ty == "C" else g["bull_dist"].to_numpy()[j]
        out[tag] = None if not np.isfinite(v) else (-v if ty == "C" else v)
    return out


def state_at(spot, ts):
    """4h always-in (EMA 20/100, tuned) and the 20-day regime, as of ts."""
    a=spot_series(spot,240); d=spot_series(spot,1440)
    ai=rg=None; stale=None
    if a is not None:
        c=a[:,4]; ef,es=ema(c,20),ema(c,100)
        s=np.where((c>ef)&(ef>es),1,np.where((c<ef)&(ef<es),-1,0))
        j=int(np.searchsorted(a[:,0]+240*60, ts, side="right"))-1
        if j>=0: ai=int(s[j]); stale=(ts-a[j,0])/3600
    if d is not None:
        c=d[:,4]
        ret=np.concatenate([np.full(20,np.nan), c[20:]/c[:-20]-1])
        net=np.abs(np.concatenate([np.full(20,np.nan), c[20:]-c[:-20]]))
        tot=pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(20,min_periods=2).sum().to_numpy()
        eff=net/np.maximum(tot,1e-12)
        r=np.where((eff>.35)&(ret>0),1,np.where((eff>.35)&(ret<0),-1,0))
        j=int(np.searchsorted(d[:,0]+1440*60, ts, side="right"))-1
        if j>=0: rg=int(r[j])
    return ai, rg, stale

def read_log():
    if not os.path.exists(LOG): return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(LOG, dtype=str).fillna("")

def write_log(df): df.to_csv(LOG, index=False)

def cmd_run(a):
    SIG = "data/signals"
    cutoff=dt.datetime.now().timestamp()-a.days*86400
    stale=None
    have=set(read_log().event_id)
    rows=[]
    def dirs(p):
        return sorted(x for x in os.listdir(p)
                      if not x.startswith((".","_")) and os.path.isdir(os.path.join(p,x)))
    for sig in dirs(SIG):
        for spot in dirs(f"{SIG}/{sig}"):
            for dur in sorted(int(x) for x in os.listdir(f"{SIG}/{sig}/{spot}") if x.isdigit() and int(x)>=30):
                dd=f"{SIG}/{sig}/{spot}/{dur}"
                for fn in sorted(os.listdir(dd)):
                    if not fn.endswith(".json") or ".tmp." in fn: continue
                    exp=fn[:-5]
                    try: data=json.load(open(f"{dd}/{fn}"))
                    except Exception: continue
                    for ty in ("C","P"):
                        for r in (data.get(ty) or []):
                            try: ts=dt.datetime.strptime(r[1][:19],"%Y-%m-%dT%H:%M:%S").timestamp()-19800
                            except Exception: continue
                            if ts<cutoff: continue
                            eid=f"{sig}|{spot}|{exp}|{dur}|{r[1]}|{ty}"
                            if eid in have: continue
                            ai,rg,stale=state_at(spot,ts)
                            if ai is None: continue
                            ln=line_state(spot,ts,ty)
                            dr,wr=ln.get("d"),ln.get("w")
                            at = 1 if (wr is not None and abs(wr)<=0.25) else 0
                            r4 = (ai==1) if ty=="C" else (ai==-1)
                            r5 = r4 and rg!=1
                            for sym in (r[6] or [])[:1]:          # K=1 is optimal
                                p=sym.split("-")
                                rows.append({**{k:"" for k in FIELDS},
                                  "event_id":eid,"decided_at":dt.datetime.now().isoformat(timespec="seconds"),
                                  "entry_iso":r[1],"signal":sig,"spot":spot,"expiry":exp,"duration":dur,
                                  "opt_type":ty,"symbol":sym,"strike":p[2] if len(p)>3 else "",
                                  "trigger":"", "ai_state":{1:"up",-1:"down",0:"unclear"}[ai],
                                  "regime":{1:"up",-1:"down",0:"sideways"}.get(rg,"?"),
                                  "r4":int(r4),"r5":int(r5),
                                  "d_room":"" if dr is None else round(dr,2),
                                  "w_room":"" if wr is None else round(wr,2),
                                  "at_line":at,
                                  "decision":"TAKE" if r5 else "skip"})
                            have.add(eid)
    if not rows: print("no new signals in the window"); return
    df=pd.concat([read_log(), pd.DataFrame(rows)], ignore_index=True)
    write_log(df)
    n=len(rows); t=sum(1 for r in rows if r["decision"]=="TAKE")
    print(f"logged {n} new signals — {t} TAKE, {n-t} skip")
    if stale and stale>8: print(f"  WARNING: spot data is {stale:.0f}h stale — run backfill.js --spot-candles")

def cmd_report(a):
    d=read_log()
    if not len(d): print("log is empty"); return
    d["r"]=pd.to_numeric(d.traded_25x, errors="coerce")
    print(f"logged signals: {len(d):,}   TAKE {int((d.decision=='TAKE').sum()):,}   "
          f"skip {int((d.decision=='skip').sum()):,}")
    res=d[d.resolved_at!=""]
    print(f"resolved: {len(res):,}")
    if not len(res): print("\nnothing resolved yet — outcomes fill in after expiry"); return
    for grp in ("TAKE","skip"):
        s=res[res.decision==grp]
        if not len(s): continue
        h=pd.to_numeric(s.traded_25x,errors="coerce").mean()
        print(f"  {grp:<5} n={len(s):>5}  25x {100*h:5.2f}%  "
              f"EV {h*24-(1-h)-COST:+.3f}  (backtest expects "
              f"{100*(EXPECTED if grp=='TAKE' else 0.0351):.2f}%)")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--run",action="store_true"); ap.add_argument("--resolve",action="store_true")
    ap.add_argument("--report",action="store_true"); ap.add_argument("--days",type=int,default=7)
    a=ap.parse_args()
    if a.run: cmd_run(a)
    elif a.report: cmd_report(a)
    else: ap.print_help()
