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
          "r4","r5","d_room","w_room","at_line","decision","picture","note","resolved_at",
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

_PIC = {}
def picture_on(spot, ts):
    """His quiet-before-the-storm picture for the UTC day containing ts (docs/ML/PICTURE_CALLS.md):
    quiet weekend & low-vol week & price held near its 7-day high, as causal percentiles of the previous
    365 days, known at the PREVIOUS day's close. Built from data/spot_candles 1h (MARK); the backtest used
    perp traded candles -- percentiles of volatility are insensitive to that."""
    if spot not in _PIC:
        import glob
        rows = []
        for f in sorted(glob.glob(f"data/spot_candles/{spot}/60/*")):
            if os.path.basename(f).startswith("."): continue
            try: rows += json.load(open(f))
            except Exception: pass
        if not rows: _PIC[spot] = None; return None
        h = pd.DataFrame([r[:5] for r in rows], columns=["t","o","h","l","c"]).drop_duplicates("t").sort_values("t")
        h["dt"] = pd.to_datetime(h.t, unit="s"); h = h.set_index("dt"); h["lr"] = np.log(h.c).diff()
        d = h.resample("1D").agg(hi=("h","max"), lo=("l","min"), c=("c","last"), rv=("lr", lambda x: np.sqrt((x**2).sum()))).dropna()
        d["rng"] = (d.hi - d.lo) / d.c
        f = pd.DataFrame(index=d.index)
        f["rv7"] = d.rv.rolling(7).mean()
        f["wkend"] = d.rng.where(d.index.weekday >= 5).rolling(7, min_periods=1).mean()
        f["dd7"] = d.c / d.c.rolling(7).max() - 1
        def cp(s, win=365):
            v = s.to_numpy(); out = np.full(len(v), np.nan)
            for i in range(60, len(v)):
                w = v[max(0, i-win):i]; w = w[np.isfinite(w)]
                if len(w) >= 60 and np.isfinite(v[i]): out[i] = (w < v[i]).mean()
            return pd.Series(out, index=s.index)
        P = f.apply(cp).shift(1)
        _PIC[spot] = ((P.wkend <= 0.3) & (P.rv7 <= 0.3) & (P.dd7 >= 0.6))
    ser = _PIC[spot]
    if ser is None: return None
    day = pd.Timestamp(int(ts), unit="s").normalize()
    return bool(ser.get(day, False))

def read_log():
    if not os.path.exists(LOG): return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(LOG, dtype=str).fillna("")

def write_log(df): df.to_csv(LOG, index=False)

def cmd_run(a):
    SIG = "data/signals"
    cutoff=dt.datetime.now().timestamp()-(a.hours*3600 if a.hours else a.days*86400)
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
                            if ts+dur*60<cutoff: continue     # judged on the trigger CLOSE
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
                                  "decision":"TAKE" if r5 else "skip",
                                  "picture":int(spot in ("BTC","ETH") and ty=="C" and bool(picture_on(spot, ts+dur*60)))})   # tested on BTC/ETH only
                            have.add(eid)
    if not rows: print("no new signals in the window"); return
    df=pd.concat([read_log(), pd.DataFrame(rows)], ignore_index=True)
    write_log(df)
    n=len(rows); t=sum(1 for r in rows if r["decision"]=="TAKE")
    print(f"logged {n} new signals — {t} TAKE, {n-t} skip")
    if stale and stale>8: print(f"  WARNING: spot data is {stale:.0f}h stale — run backfill.js --spot-candles")

API = "https://api.india.delta.exchange/v2/history/candles"
def _candles(sym, a, b, step=300, chunk=1500):
    """5m candles over [a, b], chunked (one-shot calls silently cap ~4000 rows)."""
    import urllib.request, time
    out = {}
    t = a
    while t < b:
        e = min(b, t + step*chunk)
        u = f"{API}?symbol={sym}&resolution=5m&start={int(t)}&end={int(e)}"
        for k in range(4):
            try:
                with urllib.request.urlopen(u, timeout=45) as r:
                    for c in json.load(r).get("result") or []: out[int(c["time"])] = c
                break
            except Exception: time.sleep(1 + 2*k)
        t = e
    return [out[k] for k in sorted(out)]

def _resolve_one(row):
    """Entry = MARK close of the trigger candle (the backtest's peak_vs_close convention).
    Trigger = MARK high of that candle (stop-entry level). Peaks are taken strictly AFTER
    the trigger candle closes, up to settlement, on both MARK and TRADED prints."""
    dur = int(row["duration"])
    t0 = int(dt.datetime.strptime(row["entry_iso"][:19], "%Y-%m-%dT%H:%M:%S").timestamp()) - 19800
    t1 = t0 + dur*60
    settle = int(dt.datetime.strptime(row["expiry"], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) + 12*3600
    mk = _candles("MARK:" + row["symbol"], t0, settle)
    tr = _candles(row["symbol"], t1, settle)
    trig = [c for c in mk if t0 <= int(c["time"]) < t1]
    if not trig: return None
    entry = float(trig[-1]["close"]); hi_trig = max(float(c["high"]) for c in trig)
    if entry <= 0: return None
    after_m = [float(c["high"]) for c in mk if int(c["time"]) >= t1]
    after_t = [float(c["high"]) for c in tr if int(c["time"]) >= t1 and (c.get("volume") or 0) > 0]
    mp = max(after_m)/entry if after_m else 0.0
    tp = max(after_t)/entry if after_t else 0.0
    return {"entry_premium": round(entry, 6), "trigger": round(hi_trig, 6),
            "mark_peak": round(mp, 3), "traded_peak": round(tp, 3),
            "mark_25x": int(mp >= 25), "traded_25x": int(tp >= 25),
            "filled": int(bool(after_t) and max(after_t) > hi_trig),
            "resolved_at": dt.datetime.now().isoformat(timespec="seconds")}

def cmd_resolve(a):
    from concurrent.futures import ThreadPoolExecutor
    d = read_log()
    if not len(d): print("log is empty"); return
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    settled = d.expiry.map(lambda e: dt.datetime.strptime(e, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() + 13*3600 < now)
    todo = d[(d.resolved_at == "") & settled]
    if a.take_only: todo = todo[todo.decision == "TAKE"]
    if not len(todo): print("nothing to resolve"); return
    print(f"resolving {len(todo)} rows", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_resolve_one, [r for _, r in todo.iterrows()]))
    n = 0
    for i, r in zip(todo.index, res):
        if r is None: d.at[i, "resolved_at"] = "unresolvable"; continue
        for k, v in r.items(): d.at[i, k] = str(v)
        n += 1
    write_log(d); print(f"resolved {n}, unresolvable {sum(r is None for r in res)}")

def _forward(d, max_lag_h=3):
    """Forward = logged within max_lag_h of the trigger candle's close, so the outcome
    cannot have been visible. decided_at is local (IST) naive; entry_iso carries +0530.
    The 2,541 rows written on 2026-09-17 for 08-16 Sep expiries fail this."""
    dec = pd.to_datetime(d.decided_at).dt.tz_localize("Asia/Kolkata")
    close = pd.to_datetime(d.entry_iso.str[:19]).dt.tz_localize("Asia/Kolkata") + pd.to_timedelta(pd.to_numeric(d.duration), unit="m")
    return (dec - close) <= pd.Timedelta(hours=max_lag_h)

def cmd_report(a):
    d=read_log()
    if not len(d): print("log is empty"); return
    d["r"]=pd.to_numeric(d.traded_25x, errors="coerce")
    print(f"logged signals: {len(d):,}   TAKE {int((d.decision=='TAKE').sum()):,}   "
          f"skip {int((d.decision=='skip').sum()):,}")
    d["forward"]=_forward(d)
    print(f"forward (logged <=3h after the signal closed): {int(d.forward.sum()):,}   backfilled: {int((~d.forward).sum()):,}")
    res=d[(d.resolved_at!="")&(d.resolved_at!="unresolvable")]
    print(f"resolved: {len(res):,}")
    if not len(res): print("\nnothing resolved yet — outcomes fill in after expiry"); return
    def targets(x, lab, bt):
        """traded hit rate and EV at 25x / 50x / 100x (resting sell at the target, total loss otherwise)"""
        pk=pd.to_numeric(x.traded_peak,errors="coerce")
        cells=[]
        for T in (25,50,100):
            p=(pk>=T).mean(); cells.append(f"{T}x {100*p:5.2f}% EV {T*p-1-COST:+.2f}")
        print(f"  {lab:<30} n={len(x):>4} ({x.expiry.nunique()} expiries)  " + "  |  ".join(cells) + f"   backtest: {bt}")
    if "picture" in d.columns:
        pf=res[(res.forward)&(res.picture=="1")]
        if len(pf):
            print("  forward, traded prices, by target (docs/ML/SETUPS.md):")
            targets(pf, "PICTURE-CALL", "25x 12.06% / 50x 8.95% / 100x 5.47%")
            pr=pf[pf.regime!="up"]
            if len(pr): targets(pr, "PICTURE-CALL & not R5", "25x 13.56% / 50x 10.45% / 100x 6.57%")
    for fw, grp in [(f, g) for f in (True, False) for g in ("TAKE","skip")]:
        s=res[(res.decision==grp)&(res.forward==fw)]
        if not len(s): continue
        h=pd.to_numeric(s.traded_25x,errors="coerce").mean(); m=pd.to_numeric(s.mark_25x,errors="coerce").mean()
        ev=pd.to_numeric(s.event_id.str.rsplit("|",n=1).str[0],errors="coerce") if False else None
        n_exp=s.expiry.nunique()
        print(f"  {'FORWARD' if fw else 'backfill':<8} {grp:<5} n={len(s):>5} ({n_exp} expiries)  "
              f"25x traded {100*h:5.2f}%  mark {100*m:5.2f}%  EV(traded) {h*24-(1-h)-COST:+.3f}  "
              f"(backtest: {100*(EXPECTED if grp=='TAKE' else 0.0351):.2f}%)")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--run",action="store_true"); ap.add_argument("--resolve",action="store_true")
    ap.add_argument("--report",action="store_true"); ap.add_argument("--days",type=int,default=7)
    ap.add_argument("--hours",type=float,default=None,help="--run: only signals whose trigger closed within this many hours (forward logging)")
    ap.add_argument("--take-only",action="store_true",help="--resolve: only TAKE rows")
    a=ap.parse_args()
    if a.run: cmd_run(a)
    elif a.resolve: cmd_resolve(a)
    elif a.report: cmd_report(a)
    else: ap.print_help()
