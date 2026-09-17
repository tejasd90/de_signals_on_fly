#!/usr/bin/env python3
"""
r1_retest.py — re-test Brooks' "single most important rule" with trend lines that
are actually trend lines.

R1 was reported not significant (P=0.252) and collapsing under control. That
verdict is suspect: brooks_context.py fitted least squares to the last 4 fractal
swings, which on ETH daily at the July 2026 breakout produced a bear line with
slope +0.101 spanning 30 days. It was measuring breaks of local regressions, not
of structure. structural_lines.py fixes that — convex hull on major swings,
longest descending segment — and finds the real 372-day line, breaking on the
day it actually broke.

DIRECTION. For a CALL the relevant event is the BEAR line giving way; for a PUT
it is the BULL line. Tested with an overshoot tolerance, per Tejas's point that
a break must not be declared on an exact touch.
"""
import json, numpy as np, pandas as pd
import structural_lines as SL
exec(open('rules_test.py').read().split('if __name__')[0])   # ev, block_boot, report

CFG = {1440: dict(k=5, min_prom=1.0, lookback=400),
       10080: dict(k=2, min_prom=0.8, lookback=100)}

def struct_for(spot, tf):
    a = np.asarray(json.load(open(f'data/spot_grouped/{spot}/{tf}.json')), float)
    return a[:, 0], SL.lines(a, **CFG[tf])

cols = ['spot','opt_type','entry_ts','event_id','activated','entry_premium',
        'y_25x','y_10x','cx240_always_in']
parts = []
for sp in ['BTC','ETH']:
    d = pd.read_parquet(f'events_ctx2/{sp}.parquet', columns=cols)
    d = d[d.activated & d.entry_premium.between(2,20)]
    for tf in (1440, 10080):
        ts, g = struct_for(sp, tf)
        j = np.searchsorted(ts + tf*60, d.entry_ts.to_numpy(), side='right') - 1
        ok = j >= 0
        for c in ['bear_dist','bull_dist','bear_broken','bull_broken','bear_span','bull_span']:
            v = np.full(len(d), np.nan); v[ok] = g[c].to_numpy()[j[ok]]
            d[f'{"d" if tf==1440 else "w"}_{c}'] = v
    parts.append(d)
d = pd.concat(parts, ignore_index=True)
e = d.groupby('event_id').agg(
    ty=('opt_type','first'), ts=('entry_ts','first'), h25=('y_25x','mean'),
    h10=('y_10x','mean'), ai=('cx240_always_in','first'),
    **{c:(c,'first') for c in d.columns if c.startswith(('d_','w_'))}).reset_index()
e['week'] = ((e.ts+19800)//604800).astype(int)
call = (e.ty=='C').to_numpy()
e['agree'] = np.where(call, e.ai==1, e.ai==-1)
ag = pd.Series(e.agree.to_numpy(), index=e.index)
print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%")
print(f"structural line present: daily {100*e.d_bear_dist.notna().mean():.1f}%  "
      f"weekly {100*e.w_bear_dist.notna().mean():.1f}%\n")

# for a CALL the bear line must break; for a PUT the bull line
for tag, pre in (("DAILY","d"), ("WEEKLY","w")):
    print(f"=== R1 on the {tag} structural line ===")
    for tol in (0.0, 0.25, 0.5, 1.0):
        brk = np.where(call, e[f'{pre}_bear_dist'] > tol, e[f'{pre}_bull_dist'] < -tol)
        m = pd.Series(np.nan_to_num(brk, nan=0).astype(bool), index=e.index)
        if m.sum() < 400: print(f"  tol {tol}: too few ({int(m.sum())})"); continue
        report(e, f"R1 structural, tol={tol} ATR", m, 25)
    print("  --- marginal to R4 ---")
    for tol in (0.0, 0.5):
        brk = np.where(call, e[f'{pre}_bear_dist'] > tol, e[f'{pre}_bull_dist'] < -tol)
        m = pd.Series(np.nan_to_num(brk, nan=0).astype(bool), index=e.index)
        if (m&ag).sum() < 300: continue
        report(e[ag], f"R1 structural tol={tol} [marginal]", m[ag], 25)
    print()
report(e, "R4 alone (benchmark)", ag, 25)
