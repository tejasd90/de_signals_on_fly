#!/usr/bin/env python3
"""
r9_and_tolerance.py — two things Tejas raised.

1. OVERSHOOT TOLERANCE. Brooks: everything overshoots or undershoots by a few
   ticks, so a break must not be declared on an exact touch. Phase 2 tested
   `close < trendline` — a hard binary on a 1-tick penetration. That labels noise
   as a break, and may be why R1 came back null. The stored `*_dist` columns are
   already the distance from the line in ATR units, so a tolerance is just a
   different threshold on them: no recompute needed. Swept here.

2. R9, THE TRAP RULE. Brooks: "In strong trends, with-trend signal bars look bad
   and countertrend ones look good, and that is exactly how traders get trapped."
   Formally: for a COUNTERTREND signal in a STRONG trend, signal strength should
   carry a NEGATIVE sign. This is the rule promised in CONTEXT_PLAN Phase 2 and
   never built. It is the formal version of Tejas's own observation that his
   skip example had the HIGHER strength.

   Strength is ranked WITHIN each signal — raw values run 15..800,000 for
   red_squeeze and 1,000+ for the OTM signals, so a pooled threshold would just
   be a signal-identity dummy.
"""
import numpy as np, pandas as pd, json, os
exec(open('rules_test.py').read().split('if __name__')[0])   # fwd_spot_return, ev, block_boot, report

cols = ['spot','opt_type','entry_ts','event_id','activated','entry_premium','signal',
        'signal_value','y_10x','y_25x','cx240_always_in','cx240_bull_dist','cx240_bear_dist',
        'cx240_efficiency_20','cx240_ema20_run','cx240_bull_r2','cx240_bear_r2']
parts=[]
for s in ['BTC','ETH']:
    d=pd.read_parquet(f'events_ctx/{s}.parquet',columns=cols)
    d=d[d.activated & d.entry_premium.between(2,20)]
    parts.append(d)
d=pd.concat(parts,ignore_index=True)
e=d.groupby('event_id').agg(
    ty=('opt_type','first'), ts=('entry_ts','first'), sig=('signal','first'),
    sv=('signal_value','first'), h10=('y_10x','mean'), h25=('y_25x','mean'),
    ai=('cx240_always_in','first'), bd=('cx240_bull_dist','first'),
    rd=('cx240_bear_dist','first'), eff=('cx240_efficiency_20','first'),
    run=('cx240_ema20_run','first'), br2=('cx240_bull_r2','first'),
    sr2=('cx240_bear_r2','first')).reset_index()
e['week']=((e.ts+19800)//604800).astype(int)
bull = e.ty=='C'
e['agree'] = np.where(bull, e.ai==1, e.ai==-1)
print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%\n")

print("=== 1. R1 with an OVERSHOOT TOLERANCE (break must exceed the line by X ATR) ===")
print("   for a CALL the relevant break is the BEAR line giving way, and vice versa")
for tol in [0.0, 0.1, 0.25, 0.5, 1.0]:
    m = np.where(bull, e.rd > tol, e.bd < -tol)
    m = pd.Series(m, index=e.index)
    if m.sum() < 500: print(f"   tol {tol:>4} ATR: too few ({m.sum()})"); continue
    report(e, f"R1 tol={tol} ATR", m, 25)

print("\n=== 2. R9 THE TRAP RULE ===")
# strength ranked inside each signal, so the test is not a signal dummy
e['sv_q'] = e.groupby('sig').sv.rank(pct=True)
e['strong_trend'] = (e.eff >= 0.35) | (e.run.abs() >= 8)
print("  Brooks predicts: countertrend + strong trend + HIGH strength = the trap (worst cell)\n")
print(f"  {'context':<34}{'strength':<12}{'n':>8}{'hit25':>9}{'hit10':>9}")
for ct,label in [(False,'with-trend (agrees)'),(True,'countertrend (disagrees)')]:
    for st,tl in [(True,'strong trend'),(False,'range/weak')]:
        s = e[(e.agree != ct) if False else ((~e.agree)==ct) & (e.strong_trend==st)]
        if len(s)<500: continue
        for lo,hi,nm in [(0.0,0.5,'weak half'),(0.5,0.9,'strong'),(0.9,1.01,'top 10%')]:
            q = s[(s.sv_q>=lo)&(s.sv_q<hi)]
            if len(q)<200: continue
            print(f"  {label+' / '+tl:<34}{nm:<12}{len(q):>8,}{100*q.h25.mean():>8.2f}%{100*q.h10.mean():>8.2f}%")
    print()

print("=== R9 as a testable filter: skip countertrend+strong-trend+high-strength ===")
trap = (~e.agree) & e.strong_trend & (e.sv_q>=0.5)
report(e, "R9 skip the trap cell", pd.Series(~trap, index=e.index), 25)
report(e, "R4 alone (for comparison)", pd.Series(e.agree.to_numpy(), index=e.index), 25)
report(e, "R4 AND not-trap", pd.Series((e.agree & ~trap).to_numpy(), index=e.index), 25)
