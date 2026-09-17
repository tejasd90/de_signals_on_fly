#!/usr/bin/env python3
"""
Pass 2: at each (spot, ts, type), fit log(premium at matched moneyness) against
log(tte) ACROSS the live expiries. Emit per-expiry features.

term_resid_*  is the headline: this expiry's deviation from the board's own term
              structure. Positive = this expiry is RICH vs its neighbours,
              negative = CHEAP. No within-expiry feature can see this.
"""
import glob,numpy as np,pandas as pd
d=pd.concat([pd.read_parquet(f) for f in sorted(glob.glob("term_parts/*.parquet"))],
            ignore_index=True)
print(f"in: {len(d):,}")
for c in ["p0","p2.5","p5","p10"]:
    print(f"  coverage {c}: {d[c].notna().mean()*100:5.1f}%")
d["lt"]=np.log(np.maximum(d["tte"],1e-6))
d=d.sort_values(["spot","typ","ts"]).reset_index(drop=True)
key=(d.spot.astype(str)+"|"+d.typ.astype(str)+"|"+d.ts.astype(str)).to_numpy()
_,start=np.unique(key,return_index=True); start=np.sort(start)
ends=np.append(start[1:],len(d))
cols={}
for m in ["p0","p5"]:
    cols[f"term_slope_{m}"]=np.full(len(d),np.nan)
    cols[f"term_resid_{m}"]=np.full(len(d),np.nan)
    cols[f"term_r2_{m}"]=np.full(len(d),np.nan)
cols["term_nexp"]=np.full(len(d),np.nan)
cols["term_ttrank"]=np.full(len(d),np.nan)
cols["skew_term_slope"]=np.full(len(d),np.nan)
cols["skew_term_resid"]=np.full(len(d),np.nan)
lt=d["lt"].to_numpy(); sk=d["skew"].to_numpy()   # d.lt is DataFrame.lt()
P={m:d[m].to_numpy() for m in ["p0","p5"]}
for a,b in zip(start,ends):
    n=b-a
    cols["term_nexp"][a:b]=n
    x=lt[a:b]
    cols["term_ttrank"][a:b]=np.argsort(np.argsort(x))/max(n-1,1)
    if n>=3:
        for m in ["p0","p5"]:
            y=np.log(np.maximum(P[m][a:b],1e-12)); ok=np.isfinite(y)&np.isfinite(x)&(P[m][a:b]>0)
            if ok.sum()>=3 and np.std(x[ok])>1e-9:
                s,c0=np.polyfit(x[ok],y[ok],1)
                r=y-(s*x+c0); sd=np.nanstd(r[ok])
                cols[f"term_slope_{m}"][a:b]=s
                cols[f"term_resid_{m}"][a:b]=r/max(sd,1e-9)
                cols[f"term_r2_{m}"][a:b]=1-np.nanvar(r[ok])/max(np.nanvar(y[ok]),1e-12)
        ys=sk[a:b]; ok=np.isfinite(ys)&np.isfinite(x)
        if ok.sum()>=3 and np.std(x[ok])>1e-9:
            s,c0=np.polyfit(x[ok],ys[ok],1)
            r=ys-(s*x+c0)
            cols["skew_term_slope"][a:b]=s
            cols["skew_term_resid"][a:b]=r/max(np.nanstd(r[ok]),1e-9)
for k,v in cols.items(): d[k]=v
out=d[["spot","expiry","ts","typ","tte"]+list(cols)].copy()
out.replace([np.inf,-np.inf],np.nan,inplace=True)
out.to_parquet("term_features.parquet",index=False)
print(f"\nwrote term_features.parquet  {len(out):,} rows x {len(cols)} features")
print(out[list(cols)].describe().T[["count","mean","std","min","max"]].to_string(
      float_format=lambda v:f"{v:,.3f}"))
