#!/usr/bin/env python3
"""
levels.py — price-action levels that have been REJECTED at least 3 times, and
what happens to options when one finally breaks.

THE IDEA (Tejas)
A level that has turned price away three or more times is a level the market has
repeatedly agreed on. Breaking it should be a bigger event than breaking a level
nobody has defended. Each option expiry then becomes "can it break?", and the
expiry that does should carry the outsized multiples.

His own example: the descending line off the Oct-2025 high. Nobody could know it
in October; the Feb-2026 touch made it two; the June-2026 rejection made it
three and CONFIRMED it. That confirmation timing is the whole point — a level is
only tradeable from the moment its third rejection completes, never earlier, and
this code enforces that.

THREE LEVEL TYPES
  horizontal  swing highs/lows clustered within a tolerance band (range edges,
              old support/resistance)
  trendline   convex-hull line on major swings (the structural kind — see
              structural_lines.py for why least-squares on 4 local swings was
              wrong)
  channel     the parallel return line of a trendline

REJECTION vs BREAK, deliberately asymmetric
  rejection = price came within TOL of the level, did NOT close beyond it, and
              then moved at least AWAY_ATR away. Lenient on overshoot: a wick
              through is still a rejection.
  break     = a CLOSE beyond the level. Wicks never count.

Levels are built on data/spot_candles (MARK:BTCUSD) because that is the series
the whole option pipeline references — see de-signals-spot-is-mark.
"""
import os, json, argparse
import numpy as np, pandas as pd

TOL_ATR   = 0.60     # how close counts as a touch
AWAY_ATR  = 1.20     # how far it must travel back to call it a rejection
MIN_REJ   = 3
CONFIRM   = 3        # swing confirmation lag, bars

def load_tf(spot, tf):
    d=os.path.join("data/spot_candles",spot,str(tf))
    if not os.path.isdir(d): return None
    rows=[]
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or ".tmp." in fn: continue
        try: rows.extend(json.load(open(os.path.join(d,fn))))
        except Exception: pass
    if len(rows)<200: return None
    a=np.asarray([r[:5] for r in rows],float); a=a[np.argsort(a[:,0])]
    _,k=np.unique(a[:,0],return_index=True)
    return a[np.sort(k)]

def atr(h,l,c,n=14):
    pc=np.concatenate([[c[0]],c[:-1]])
    tr=np.maximum(h-l,np.maximum(abs(h-pc),abs(l-pc)))
    return pd.Series(tr).rolling(n,min_periods=2).mean().to_numpy()

def swings(h,l,k=5,prom=1.0,A=None):
    n=len(h); sh=np.zeros(n,bool); sl=np.zeros(n,bool)
    for j in range(k,n-k):
        wh=h[j-k:j+k+1]; wl=l[j-k:j+k+1]
        a=A[j] if A is not None and np.isfinite(A[j]) and A[j]>0 else 1.0
        if h[j]==wh.max() and (h[j]-wh.min())/a>=prom: sh[j]=True
        if l[j]==wl.min() and (wl.max()-l[j])/a>=prom: sl[j]=True
    return sh,sl

def horizontal_levels(a, tf):
    """Cluster major swings into horizontal levels; count rejections causally."""
    ts,o,h,l,c=a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    sh,sl=swings(h,l,k=5,prom=1.0,A=A)
    seeds=[]
    for j in np.where(sh)[0]: seeds.append((j,h[j],"R"))
    for j in np.where(sl)[0]: seeds.append((j,l[j],"S"))
    seeds.sort()
    used=np.zeros(len(seeds),bool); levels=[]
    for i,(j,px,kind) in enumerate(seeds):
        if used[i]: continue
        grp=[(j,px)]
        for i2,(j2,px2,k2) in enumerate(seeds):
            if i2<=i or used[i2] or k2!=kind: continue
            if abs(px2-px)<=TOL_ATR*A[j2]: grp.append((j2,px2)); used[i2]=True
        used[i]=True
        if len(grp)<2: continue
        # LOOK-AHEAD FIX. The price used to be the mean of EVERY touch in the
        # cluster, including touches that occur after confirmation and even
        # after the break -- i.e. the level was fitted with its own future. The
        # level is now anchored on the FIRST MIN_REJ touches only, which is all
        # a trader could know at the moment it becomes tradeable.
        grp=sorted(grp)
        anchor=grp[:MIN_REJ]
        levels.append(dict(kind=kind, price=float(np.mean([p for _,p in anchor])),
                           anchor_i=int(anchor[-1][0]),
                           seeds=[jj for jj,_ in grp], tf=tf))
    return levels, A

def count_rejections(a, A, level):
    """Walk forward; record every touch that failed and then travelled away.
    Returns the bar index at which the MIN_REJ-th rejection completed, so the
    level is only 'confirmed' from that bar onward — never retroactively."""
    ts,o,h,l,c=a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    P=level["price"]; kind=level["kind"]
    rejects=[]; n=len(c); armed=False; touch_i=None
    i=level.get("anchor_i",0)          # nothing before the anchor is knowable
    while i<n:
        if not np.isfinite(A[i]): i+=1; continue
        near = (abs(h[i]-P)<=TOL_ATR*A[i]) if kind=="R" else (abs(l[i]-P)<=TOL_ATR*A[i])
        beyond = (c[i]>P) if kind=="R" else (c[i]<P)
        if beyond:                                   # a close through ends the level
            return rejects, i
        if near and not armed: armed=True; touch_i=i
        if armed:
            away = (P-c[i])/A[i] if kind=="R" else (c[i]-P)/A[i]
            if away>=AWAY_ATR:
                rejects.append(touch_i); armed=False; touch_i=None
        i+=1
    return rejects, None

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--tf",type=int,default=1440)
    a_=ap.parse_args()
    for spot in ("BTC","ETH"):
        arr=load_tf(spot,a_.tf)
        if arr is None: print(f"{spot}: no data"); continue
        lv,A=horizontal_levels(arr,a_.tf)
        conf=[]
        for L in lv:
            rej,brk=count_rejections(arr,A,L)
            if len(rej)>=MIN_REJ:
                ci=rej[MIN_REJ-1]                      # confirmed here, not before
                L2=dict(L); L2.update(n_rej=len(rej), confirmed_i=ci,
                        confirmed_ts=int(arr[ci,0]),
                        break_i=brk, break_ts=int(arr[brk,0]) if brk else None,
                        rejects=[int(arr[r,0]) for r in rej])
                conf.append(L2)
        print(f"{spot} {a_.tf}m: {len(lv)} candidate levels -> "
              f"{len(conf)} confirmed with >={MIN_REJ} rejections, "
              f"{sum(1 for x in conf if x['break_i'])} of which later broke")
        for L in sorted(conf,key=lambda x:-x["n_rej"])[:6]:
            bt=pd.Timestamp(L["break_ts"],unit="s").date() if L["break_ts"] else "unbroken"
            print(f"    {L['kind']} {L['price']:>10,.1f}  {L['n_rej']} rejections  "
                  f"confirmed {pd.Timestamp(L['confirmed_ts'],unit='s').date()}  broke {bt}")

# ─── trendlines with >=3 touches ─────────────────────────────────────────────
def trendlines(a, A, tf, min_touch=MIN_REJ, max_span=500):
    """Classic 3-point trendline: anchor on two major swings, keep the line only
    if a THIRD (or later) swing also touches it without price closing through.
    Descending lines anchor on highs, ascending on lows."""
    ts,o,h,l,c=a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    n=len(c); sh,sl=swings(h,l,k=5,prom=1.0,A=A)
    out=[]
    for kind,idx,ext,sgn in (("R",np.where(sh)[0],h,-1),("S",np.where(sl)[0],l,+1)):
        for ii in range(len(idx)):
            for jj in range(ii+1,len(idx)):
                i1,i2=idx[ii],idx[jj]
                if i2-i1<10 or i2-i1>max_span: continue
                m=(ext[i2]-ext[i1])/(i2-i1)
                if kind=="R" and m>0: continue          # a resistance line descends
                if kind=="S" and m<0: continue
                line=lambda x: ext[i2]+m*(x-i2)
                # no CLOSE may violate the line between the anchors
                seg=np.arange(i1,i2+1)
                viol=(c[seg]>line(seg)+TOL_ATR*A[seg]) if kind=="R" else (c[seg]<line(seg)-TOL_ATR*A[seg])
                if viol.any(): continue
                touches=[int(i1),int(i2)]; brk=None
                for x in range(i2+CONFIRM, n):
                    if not np.isfinite(A[x]): continue
                    lv=line(x)
                    if lv<=0: break
                    beyond=(c[x]>lv) if kind=="R" else (c[x]<lv)
                    if beyond: brk=x; break
                    near=(abs(h[x]-lv)<=TOL_ATR*A[x]) if kind=="R" else (abs(l[x]-lv)<=TOL_ATR*A[x])
                    if near and (not touches or x-touches[-1]>=CONFIRM): touches.append(int(x))
                if len(touches)>=min_touch:
                    ci=touches[min_touch-1]
                    out.append(dict(kind=kind,type="trendline",tf=tf,
                        anchor=(int(i1),int(i2)), slope=float(m),
                        price_at_break=float(line(brk)) if brk else float(line(n-1)),
                        n_rej=len(touches), confirmed_i=int(ci),
                        confirmed_ts=int(ts[ci]), break_i=brk,
                        break_ts=int(ts[brk]) if brk else None,
                        rejects=[int(ts[t]) for t in touches]))
    # Dedupe on the CONFIRMATION bar, using only the anchor span -- keyed on
    # break_i and ranked by n_rej it was selecting among candidates with
    # knowledge of how each one turned out.
    best={}
    for L in out:
        k=(L["kind"],L["confirmed_i"])
        if k not in best or (L["anchor"][1]-L["anchor"][0])>(best[k]["anchor"][1]-best[k]["anchor"][0]):
            best[k]=L
    return list(best.values())

def all_levels(spot, tf):
    arr=load_tf(spot,tf)
    if arr is None: return [],None
    lv,A=horizontal_levels(arr,tf)
    conf=[]
    for L in lv:
        rej,brk=count_rejections(arr,A,L)
        if len(rej)>=MIN_REJ:
            L=dict(L); L.update(type="horizontal", n_rej=len(rej),
                confirmed_i=rej[MIN_REJ-1], confirmed_ts=int(arr[rej[MIN_REJ-1],0]),
                break_i=brk, break_ts=int(arr[brk,0]) if brk else None,
                rejects=[int(arr[r,0]) for r in rej],
                price_at_break=L["price"])
            conf.append(L)
    conf+=trendlines(arr,A,tf)
    for L in conf: L["spot"]=spot
    return conf, arr
