#!/usr/bin/env python3
"""
rules_all.py — every Brooks rule from Brooks/*.md that this data can test.

TWO TESTS PER RULE, and the second is the one that matters:
  STANDALONE  rule vs taking everything        — is it informative at all?
  MARGINAL    (R4 AND rule) vs R4 alone        — does it ADD to what already works?

R4 is established (dEV +0.520, survives type x direction x OTM x tte controls).
A rule that merely re-expresses R4 will look good standalone and add nothing
marginally. Only the marginal column can justify a second rule.

Excluded as unbuildable from this data, rather than faked: intrabar behaviour,
volume rules, and session/day-type rules (crypto is 24/7).
"""
import numpy as np, pandas as pd, json, os
exec(open('rules_test.py').read().split('if __name__')[0])   # ev, block_boot

T = 25
def stat(e, m, base_mask=None):
    """Return (keep%, hit%, dEV, P) of m against base_mask (default: everything)."""
    b = e if base_mask is None else e[base_mask]
    s = e[m] if base_mask is None else e[m & base_mask]
    if len(s) < 300 or len(b) < 300: return None
    dev, _ = block_boot(b.assign(**{f"h{T}": b[f"h{T}"]}),
                        pd.Series(m[b.index].to_numpy(), index=b.index), T, n=800)
    if len(dev) == 0: return None
    return (100*len(s)/len(b), 100*s[f"h{T}"].mean(), 100*b[f"h{T}"].mean(),
            np.median(dev), (dev <= 0).mean())

cols = None
parts = []
for sp in ['BTC','ETH']:
    d = pd.read_parquet(f'events_ctx2/{sp}.parquet')
    d = d[d.activated & d.entry_premium.between(2,20)]
    parts.append(d)
d = pd.concat(parts, ignore_index=True)
call = d.opt_type == 'C'
g = {}
def pick(name, up, dn):      # choose the call- or put-relevant version
    g[name] = np.where(call, d[up], d[dn])
pick('ai',   'cx240_always_in','cx240_always_in')
pick('ai_h', 'cx60_always_in','cx60_always_in')
pick('ai_d', 'cx1440_always_in','cx1440_always_in')
pick('brk',  'cx240_bear_dist','cx240_bull_dist')       # tolerance applied below
pick('rpos', 'cx240_range_pos_20','cx240_range_pos_20')
pick('leg',  'cy240_h_count','cy240_l_count')
pick('push3','cy240_push3_up','cy240_push3_dn')
pick('wedge','cy240_wedge_up','cy240_wedge_dn')
pick('mgap', 'cy240_micro_gap_up','cy240_micro_gap_dn')
pick('bo',   'cy240_bo_up','cy240_bo_dn')
pick('micro','cy240_micro_up','cy240_micro_dn')
pick('test', 'cy240_test_hi','cy240_test_lo')
for k in ['cy240_is_ttr_20','cy240_is_exhaustion','cy240_consec_climax','cy240_final_flag',
          'cy240_bo_strength','cy240_follow_through','cy240_closes_above_20',
          'cy240_stairs_shrink','cy240_doji_rate_10','cy240_bar_vs_avg',
          'cx240_efficiency_20','cx240_chan_overshoot','cy240_pull_depth','cy240_mm_dist']:
    g[k.split('_',1)[1]] = d[k].to_numpy()

e = pd.DataFrame(g)
e['event_id']=d.event_id.values; e['ts']=d.entry_ts.values
e['h25']=d.y_25x.values; e['call']=call.values
e = e.groupby('event_id').first().reset_index()
e['week']=((e.ts+19800)//604800).astype(int)
e['agree']=np.where(e.call, e.ai==1, e.ai==-1)
print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%")
print(f"R4 baseline: keeps {100*e.agree.mean():.1f}%, hit25 {100*e[e.agree].h25.mean():.2f}%\n")

R = {
 "R4  always-in agrees (4h)":        e.agree.to_numpy(),
 "R4x agrees on 1h+4h+1d":           (e.agree & np.where(e.call,(e.ai_h==1)&(e.ai_d==1),(e.ai_h==-1)&(e.ai_d==-1))).to_numpy(),
 "R1  trend line broken (1 ATR)":    np.where(e.call, e.brk>1.0, e.brk<-1.0),
 "R2  favourable range extreme":     np.where(e.call, e.rpos>=0.75, e.rpos<=0.25),
 "R2b Brooks fade at extreme":       np.where(e.call, e.rpos<=0.25, e.rpos>=0.75),
 "R5  second entry (H2/L2)":         (e.leg==2).to_numpy(),
 "R5b first entry only (H1/L1)":     (e.leg==1).to_numpy(),
 "TTR tight range - skip it":        (e.is_ttr_20==0).to_numpy(),
 "BO  breakout in our direction":    (e.bo==1).to_numpy(),
 "BO+ strong breakout body":         (e.bo_strength>1.0).to_numpy(),
 "BO- weak breakout - avoid":        (e.bo_strength<=1.0).to_numpy(),
 "MG  micro gap (strength)":         (e.mgap==1).to_numpy(),
 "FT  3-bar follow-through":         np.where(e.call, e.follow_through>=2, e.follow_through<=-2),
 "CA  closes above many prior":      np.where(e.call, e.closes_above_20>=15, e.closes_above_20<=5),
 "EX  exhaustion bar present":       (e.is_exhaustion==1).to_numpy(),
 "CL  3 consecutive climaxes":       (e.consec_climax>=2).to_numpy(),
 "P3  three-push in our favour":     (e.push3==1).to_numpy(),
 "WG  wedge (converging pushes)":    (e.wedge==1).to_numpy(),
 "SS  shrinking stairs":             (e.stairs_shrink<0.8).to_numpy(),
 "FF  final flag":                   (e.final_flag==1).to_numpy(),
 "MC  micro channel >=4 bars":       (e.micro>=4).to_numpy(),
 "TE  testing prior extreme":        (np.abs(e.test)<0.5).to_numpy(),
 "OS  channel line overshoot":       (e.chan_overshoot>0).to_numpy(),
 "PD  shallow pullback (strength)":  (e.pull_depth<2.0).to_numpy(),
 "MM  near measured-move target":    (np.abs(e.mm_dist)<1.0).to_numpy(),
 "RG  range context (low eff)":      (e.efficiency_20<0.35).to_numpy(),
 "TR  trend context (high eff)":     (e.efficiency_20>=0.35).to_numpy(),
 "DJ  many dojis (choppy)":          (e.doji_rate_10>=0.5).to_numpy(),
 "BB  big bar vs average":           (e.bar_vs_avg>1.5).to_numpy(),
}
print(f"{'rule':<34}{'STANDALONE':>34}   {'MARGINAL to R4':>30}")
print(f"{'':<34}{'keep':>7}{'hit':>8}{'dEV':>9}{'P':>8}   {'keep':>7}{'hit':>8}{'dEV':>9}{'P':>8}")
agree = e.agree.to_numpy()
for nm, m in R.items():
    m = pd.Series(np.nan_to_num(m, nan=0).astype(bool), index=e.index)
    a = stat(e, m)
    b = stat(e, m, pd.Series(agree, index=e.index))
    fa = f"{a[0]:6.1f}%{a[1]:7.2f}%{a[3]:+9.3f}{a[4]:8.3f}" if a else f"{'--':>32}"
    fb = f"{b[0]:6.1f}%{b[1]:7.2f}%{b[3]:+9.3f}{b[4]:8.3f}" if b else f"{'--':>32}"
    print(f"{nm:<34}{fa}   {fb}")
