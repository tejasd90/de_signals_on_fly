#!/usr/bin/env python3
"""
r4_control.py — close the moneyness/tte control on R4, and test whether the
HIGHER timeframe is the one that matters.

CONTROL
Phase 2 held premium, option type and realised direction fixed. Not held: how
far OTM the contract sat, and how long it had to live. Both drive payoff
independently of any signal — the whole project's history is cheapness
masquerading as edge. R4 is only established if it survives inside joint
(type x realised direction x OTM distance x time-to-expiry) cells.

TIMEFRAME HIERARCHY (Tejas's hypothesis)
"If a price action fails, some other price action on a higher timeframe is
holding." Testable directly: when the 1h and 1d always-in reads DISAGREE, which
one predicts the outcome? If the higher timeframe dominates, following the daily
should pay and following the hourly should not.
"""
import numpy as np, pandas as pd, json, os
exec(open('rules_test.py').read().split('if __name__')[0])   # fwd_spot_return, ev

EXPIRY_UTC_HOUR = 12      # Delta settles 17:30 IST = 12:00 UTC

cols = ['spot','opt_type','expiry','entry_ts','event_id','activated','entry_premium',
        'moneyness_pct','y_10x','y_25x','cx60_always_in','cx240_always_in','cx1440_always_in']
parts = []
for s in ['BTC','ETH']:
    d = pd.read_parquet(f'events_ctx/{s}.parquet', columns=cols)
    d = d[d.activated & d.entry_premium.between(2, 20)]
    d['fwd'] = fwd_spot_return(s, d.entry_ts.to_numpy())
    parts.append(d)
d = pd.concat(parts, ignore_index=True)
d['exp_ts'] = pd.to_datetime(d.expiry).astype('int64')//10**9 + EXPIRY_UTC_HOUR*3600
d['tte_h']  = (d.exp_ts - d.entry_ts)/3600.0
# distance OTM in the contract's own direction: positive = further out of the money
d['otm']    = np.where(d.opt_type=='C', d.moneyness_pct, -d.moneyness_pct)

e = d.groupby('event_id').agg(
    ty=('opt_type','first'), ts=('entry_ts','first'), fwd=('fwd','first'),
    otm=('otm','first'), tte=('tte_h','first'),
    h10=('y_10x','mean'), h25=('y_25x','mean'),
    ai1=('cx60_always_in','first'), ai4=('cx240_always_in','first'),
    ai24=('cx1440_always_in','first')).reset_index().dropna(subset=['fwd','otm','tte'])
bull = e.ty=='C'
e['agree4'] = np.where(bull, e.ai4==1,  e.ai4==-1)
e['agree1'] = np.where(bull, e.ai1==1,  e.ai1==-1)
e['agree24']= np.where(bull, e.ai24==1, e.ai24==-1)
e['fb']  = pd.qcut(e.fwd, 3, labels=['down','flat','up'])
e['ob']  = pd.qcut(e.otm, 3, labels=['near','mid','far'])
e['tb']  = pd.qcut(e.tte, 3, labels=['short','mid','long'])
print(f"events {len(e):,}  weeks {((e.ts+19800)//604800).nunique()}  base hit25 {100*e.h25.mean():.2f}%\n")

print("=== R4 inside joint (type x direction x OTM x tte) cells — the full control ===")
for tgt in ['h25','h10']:
    lifts=[]; small=0
    for (ty,fb,ob,tb), s in e.groupby(['ty','fb','ob','tb'], observed=True):
        on, off = s[s.agree4], s[~s.agree4]
        if len(on)<120 or len(off)<120: small+=1; continue
        if off[tgt].mean() <= 0: continue
        lifts.append(on[tgt].mean()/off[tgt].mean())
    lifts=np.array(lifts)
    print(f"  {tgt}: {len(lifts)} cells (skipped {small} thin)  median lift {np.median(lifts):.2f}x  "
          f"above 1.0: {(lifts>1).sum()}/{len(lifts)}  p25 {np.percentile(lifts,25):.2f}x  p75 {np.percentile(lifts,75):.2f}x")

print("\n=== is R4 just an OTM/tte proxy? how agreement shifts those two ===")
print(e.groupby('agree4').agg(n=('otm','size'), otm_median=('otm','median'),
      tte_median=('tte','median')).round(2).to_string())

print("\n=== TIMEFRAME HIERARCHY: which always-in matters, 1h / 4h / 1d ===")
for nm,c in [('1h',  'agree1'), ('4h','agree4'), ('1d','agree24')]:
    on,off = e[e[c]], e[~e[c]]
    print(f"  agree with {nm:<3} always-in: keep {100*len(on)/len(e):5.1f}%  "
          f"hit25 {100*on.h25.mean():5.2f}% vs {100*off.h25.mean():5.2f}%  lift {on.h25.mean()/off.h25.mean():.2f}x")

print("\n=== WHEN 1h AND 1d DISAGREE — whose side pays? ===")
conf = e[e.agree1 != e.agree24]
print(f"  {len(conf):,} events ({100*len(conf)/len(e):.1f}%) where the hourly and daily reads conflict")
a = conf[conf.agree24 &~conf.agree1]   # daily says take it, hourly says no
b = conf[conf.agree1 &~conf.agree24]   # hourly says take it, daily says no
print(f"    follow the DAILY  (1d agrees, 1h does not): n={len(a):6,}  hit25 {100*a.h25.mean():5.2f}%")
print(f"    follow the HOURLY (1h agrees, 1d does not): n={len(b):6,}  hit25 {100*b.h25.mean():5.2f}%")
print(f"    both agree                                : n={len(e[e.agree1&e.agree24]):6,}  hit25 {100*e[e.agree1&e.agree24].h25.mean():5.2f}%")
print(f"    neither agrees                            : n={len(e[~e.agree1&~e.agree24]):6,}  hit25 {100*e[~e.agree1&~e.agree24].h25.mean():5.2f}%")
