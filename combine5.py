#!/usr/bin/env python3
"""
combine5.py — can the five failed "stored energy" features combine?

The five, each null on its own:
  comp    5-bar / 20-bar mean range before the break   (squeeze)
  ttr     prior 10-bar range in ATR                    (tight range)
  overlap mean bar-overlap before the break            (absorption)
  travel  net directional move INTO the level, ATR     (energy spent)
  effic   |net| / summed path into the level           (chop vs trend)

Order of operations, deliberately:
  1. CORRELATION first. If they all measure the same thing, combining cannot
     help and nothing else is worth running.
  2. ONE pre-specified composite (equal-weight z-average, sign-aligned to
     Tejas's thesis: calm+unspent = high). A single test, no search.
  3. A model with a TIME split — fit on 2024-25, score 2026 untouched. Any
     in-sample gain from five features is meaningless; only the held-out year
     counts.
"""
import numpy as np, pandas as pd
import levels as LV

def features(N=10):
    rows=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr=LV.all_levels(spot,tf)
            if arr is None: continue
            o,h,l,c=arr[:,1],arr[:,2],arr[:,3],arr[:,4]; A=LV.atr(h,l,c)
            rng=h-l
            comp=(pd.Series(rng).rolling(5,min_periods=3).mean()/
                  pd.Series(rng).rolling(20,min_periods=5).mean()).to_numpy()
            ov=np.concatenate([[np.nan],(np.minimum(h[1:],h[:-1])-np.maximum(l[1:],l[:-1]))/
                               np.maximum(rng[1:],1e-12)])
            ov=np.clip(ov,0,1)
            ovm=pd.Series(ov).rolling(N,min_periods=3).mean().to_numpy()
            hi=pd.Series(h).rolling(N,min_periods=3).max().to_numpy()
            lo=pd.Series(l).rolling(N,min_periods=3).min().to_numpy()
            dif=np.abs(np.diff(c,prepend=c[0]))
            for L in conf:
                i=L["break_i"]
                if not i or i<N+22 or A[i]<=0: continue
                sgn=1.0 if L["kind"]=="R" else -1.0
                net=sgn*(c[i-1]-c[i-1-N])/A[i]
                tot=dif[i-N:i].sum()/A[i]
                rows.append(dict(day=pd.Timestamp(arr[i,0],unit="s").normalize(),
                    comp=comp[i-1], ttr=(hi[i-1]-lo[i-1])/A[i], overlap=ovm[i-1],
                    travel=net, effic=abs(net)/max(tot,1e-9),
                    age=(i-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" else np.nan))
    return pd.DataFrame(rows)

if __name__=="__main__":
    F=features()
    G=F.groupby("day").agg(comp=("comp","min"),ttr=("ttr","min"),overlap=("overlap","max"),
                           travel=("travel","min"),effic=("effic","min"),age=("age","max"))
    cal=pd.read_csv("daily_break_profile.csv",index_col=0,parse_dates=True).join(G,rsuffix="_f")
    cal["week"]=cal.index.isocalendar().week.astype(str)+"-"+cal.index.year.astype(str)
    C=["comp","ttr","overlap","travel","effic"]
    brk=cal[cal.n_breaks>0].dropna(subset=C)
    print(f"break days with all five measured: {len(brk)}\n")
    print("1. ARE THEY THE SAME THING?  (Spearman)")
    print(brk[C].corr(method="spearman").round(2).to_string())
    ev=np.linalg.eigvalsh(brk[C].corr().values)
    print(f"\n   effective independent dimensions (participation ratio): "
          f"{(ev.sum()**2)/(ev**2).sum():.2f} of 5")

    base=(cal.n100_3>0).mean()
    rng_=np.random.default_rng(0); wks=cal.week.unique(); idx={w:np.where(cal.week==w)[0] for w in wks}
    def boot(m):
        y=(cal.n100_3.values>0); dr=[]
        for _ in range(2500):
            sel=np.concatenate([idx[w] for w in rng_.choice(wks,len(wks),replace=True)])
            mm=m[sel]; yy=y[sel]
            if mm.sum()<5 or (~mm).sum()<5: continue
            dr.append(yy[mm].mean()-yy[~mm].mean())
        dr=np.array(dr); return (np.median(dr),(dr<=0).mean())
    def mk(ix):
        m=np.zeros(len(cal),bool); m[cal.index.get_indexer(ix)]=True; return m
    z=lambda s:(s-s.mean())/s.std()
    # sign-aligned so HIGH = calm and unspent, exactly Tejas's thesis
    brk=brk.assign(score=(-z(brk.comp)-z(brk.ttr)+z(brk.overlap)-z(brk.travel)-z(brk.effic))/5)
    print(f"\n2. ONE PRE-SPECIFIED COMPOSITE (equal weight, high = calm & unspent)")
    print(f"   base P(100x within 0-3d) = {100*base:.1f}%")
    for lab,ix in (("composite top 25%",brk[brk.score>=brk.score.quantile(.75)].index),
                   ("composite bottom 25%",brk[brk.score<=brk.score.quantile(.25)].index),
                   ("age>=100d (reference)",brk[brk.age>=100].index)):
        m=mk(ix); d,p=boot(m)
        print(f"   {lab:<26}{m.sum():>5} days  {100*(cal[m].n100_3>0).mean():>5.1f}%  "
              f"lift {100*d:>+5.1f}pp  P {p:.3f}")

    print(f"\n3. MODEL WITH A TIME SPLIT — fit 2024-25, score 2026 untouched")
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        brk2=brk.join(cal[["n100_3"]],rsuffix="_y")
        brk2["y"]=(brk2.n100_3>0).astype(int)
        tr=brk2[brk2.index<"2026-01-01"]; te=brk2[brk2.index>="2026-01-01"]
        for name,cols in (("five energy features",C),("age only",["age"]),
                          ("five + age",C+["age"])):
            a=tr.dropna(subset=cols+["y"]); b=te.dropna(subset=cols+["y"])
            if len(a)<80 or len(b)<40: continue
            m=LogisticRegression(max_iter=2000).fit(a[cols],a.y)
            auc_in=roc_auc_score(a.y,m.predict_proba(a[cols])[:,1])
            auc_out=roc_auc_score(b.y,m.predict_proba(b[cols])[:,1])
            print(f"   {name:<24} train AUC {auc_in:.3f}   HELD-OUT 2026 AUC {auc_out:.3f}"
                  f"   (n train {len(a)}, test {len(b)})")
        print("   (0.50 = no skill. Only the held-out column means anything.)")
    except ImportError:
        print("   sklearn unavailable")
