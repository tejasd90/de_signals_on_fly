#!/usr/bin/env python3
"""
FUNDING CARRY — the whole question with no model in it.

Cadence check said the rate is set every 8h (changes land on hour mod 8 == 0),
so the quoted number is a per-8h percent and annualised carry = rate*3*365.
That inference still wants one confirmation against a real funding payment.

The trade needs a LONG LEG. Delta India lists exactly four spot pairs
(BTC/ETH/SOL/XRP, all quoted in INR) and ZERO dated futures, so only those four
perps can actually be hedged on-venue. Everything else is a naked short.
"""
import glob, os, numpy as np, pandas as pd
HEDGEABLE = {"BTCUSD":"BTC_INR","ETHUSD":"ETH_INR","SOLUSD":"SOL_INR","XRPUSD":"XRP_INR"}
rows=[]
for p in sorted(glob.glob("data/funding/*.parquet")):
    s=os.path.basename(p)[:-8]; d=pd.read_parquet(p)
    f=d.rate.to_numpy(float); t=d.ts.to_numpy()
    if len(f)<2000: continue
    yrs=(t.max()-t.min())/(365*86400)
    # 8h settlements only, to avoid counting the same rate 8 times
    m=(t%(8*3600))==0
    f8=f[m] if m.sum()>100 else f[::8]
    rows.append(dict(sym=s, years=yrs, n8=len(f8),
        mean=f8.mean(), med=np.median(f8), pos=(f8>0).mean(),
        clamp=(np.abs(f8-0.01)<1e-9).mean(),
        ann=f8.mean()*3*365, p05=np.percentile(f8,5), p95=np.percentile(f8,95),
        sd=f8.std(), hedge=HEDGEABLE.get(s,"")))
R=pd.DataFrame(rows).sort_values("ann",ascending=False)
print(f"{len(R)} symbols with >=2000 hourly funding candles\n")
print("="*96)
print("THE FOUR YOU CAN ACTUALLY HEDGE ON DELTA (spot pair exists)")
print("="*96)
h=R[R.hedge!=""]
print(f"{'perp':>10}{'spot leg':>10}{'yrs':>6}{'mean/8h':>10}{'% pos':>7}"
      f"{'% at clamp':>12}{'GROSS %/yr':>12}{'sd':>9}")
for _,r in h.iterrows():
    print(f"{r.sym:>10}{r.hedge:>10}{r.years:>6.1f}{r['mean']:>10.4f}{r.pos*100:>6.0f}%"
          f"{r.clamp*100:>11.0f}%{r.ann:>12.1f}{r.sd:>9.4f}")
print("\n" + "="*96)
print("TOP 15 BY CARRY — and whether a hedge exists")
print("="*96)
print(f"{'perp':>14}{'yrs':>6}{'mean/8h':>10}{'% pos':>7}{'% clamp':>9}"
      f"{'GROSS %/yr':>12}{'hedge?':>10}")
for _,r in R.head(15).iterrows():
    print(f"{r.sym:>14}{r.years:>6.1f}{r['mean']:>10.4f}{r.pos*100:>6.0f}%"
          f"{r.clamp*100:>8.0f}%{r.ann:>12.1f}{'YES' if r.hedge else 'no':>10}")
print(f"\n  universe: median carry {R.ann.median():.1f}%/yr, "
      f"{(R.ann>0).mean()*100:.0f}% of symbols positive, "
      f"{(R.ann>20).sum()} above 20%/yr")
print(f"  of the {(R.ann>20).sum()} above 20%/yr, "
      f"{((R.ann>20)&(R.hedge!='')).sum()} are hedgeable on Delta")

print("\n" + "="*96)
print("PERSISTENCE — does last quarter's carry predict next quarter's?")
print("="*96)
pairs=[]
for p in sorted(glob.glob("data/funding/*.parquet")):
    s=os.path.basename(p)[:-8]; d=pd.read_parquet(p)
    t=d.ts.to_numpy(); f=d.rate.to_numpy(float)
    m=(t%(8*3600))==0
    if m.sum()<400: continue
    t,f=t[m],f[m]
    q=(t//(90*86400))
    g=pd.DataFrame({"q":q,"f":f}).groupby("q").f.mean()
    for i in range(len(g)-1): pairs.append((g.iloc[i],g.iloc[i+1]))
P=np.array(pairs)
print(f"  {len(P)} symbol-quarter pairs   corr(this Q, next Q) = "
      f"{np.corrcoef(P[:,0],P[:,1])[0,1]:.3f}")
hi=P[P[:,0]>np.percentile(P[:,0],80)]
lo=P[P[:,0]<np.percentile(P[:,0],20)]
print(f"  top-quintile carry this Q -> next Q mean {hi[:,1].mean()*3*365:>6.1f}%/yr")
print(f"  bot-quintile carry this Q -> next Q mean {lo[:,1].mean()*3*365:>6.1f}%/yr")

print("\n" + "="*96)
print("NET OF EVERYTHING, for the hedgeable four (1 year hold, gross -> in pocket)")
print("="*96)
print("  assumptions: 0.05% taker each leg in AND out = 0.20% one-off;")
print("               capital = 100% spot + 25% margin buffer on the short;")
print("               Indian VDA tax 30% + 4% cess = 31.2% on the gain.")
print(f"\n{'perp':>10}{'gross %':>10}{'-fees':>9}{'/1.25 cap':>11}{'after tax':>11}"
      f"{'vs 7% FD':>10}")
for _,r in h.iterrows():
    g=r.ann; net=g-0.20; roi=net/1.25; tax=roi*(1-0.312)
    print(f"{r.sym:>10}{g:>10.1f}{net:>9.1f}{roi:>11.1f}{tax:>11.1f}"
          f"{tax-7.0:>+10.1f}")
R.to_csv("runs/funding_carry.csv",index=False)
print("\n  saved runs/funding_carry.csv")
