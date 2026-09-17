#!/usr/bin/env python3
"""
rules_test.py — Phase 2 of docs/ML/CONTEXT_PLAN.md.

Each Brooks rule as an explicit predicate, measured against the controls this
project has learned to apply. No model.

EXPECTANCY
A fixed take-profit at T, total loss otherwise, minus a round-trip cost:
    EV(T) = P(peak >= T) * (T - 1) - (1 - P(peak >= T)) - COST
P(peak >= T) is a real fill probability: a limit order at T fills whenever the
peak reaches T. COST = 8.26% of premium, the measured Delta round trip for an
option under the 3.5%-of-premium cap (fees_table.py).

TWO NUMBERS, ALWAYS
dEV per trade AND profit per week. DECISION_DOCUMENT trap #10: four regime
filters raised EV per trade and every one of them LOST on profit per week by
discarding opportunities. A rule that improves EV while halving the trade count
is usually not an improvement.

THE DIRECTION CONTROL — the one that matters here
Phase 1 found always-in agreement worth a 2.4x lift, perfectly mirrored between
calls and puts. That symmetry is the signature of directional BETA, not skill:
calls pay when spot rises, puts when it falls. So every rule is also measured
WITHIN buckets of REALISED forward spot return. Conditioning on a future
quantity is illegitimate for trading and exactly right for a control — it asks
"given what the market then did, did the rule still add anything?" A rule whose
lift vanishes inside the buckets was reading direction, not price action.

Significance is a PAIRED bootstrap over 142 weekly blocks — the unit of
independence, never rows.
"""
import numpy as np, pandas as pd, json, os

COST, SPOT_DIR = 0.0826, "data/spot_candles"
TARGETS = [10, 25]

def fwd_spot_return(spot, ts, hours=72):
    d = os.path.join(SPOT_DIR, spot, "60"); rows = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or ".tmp." in fn: continue
        try: rows.extend(json.load(open(os.path.join(d, fn))))
        except Exception: pass
    a = np.asarray([r[:5] for r in rows], float); a = a[np.argsort(a[:, 0])]
    t, c = a[:, 0], a[:, 4]
    i = np.searchsorted(t, ts, side="right") - 1
    j = np.minimum(i + hours, len(c) - 1)
    out = np.full(len(ts), np.nan)
    ok = i >= 0
    out[ok] = c[j[ok]] / c[i[ok]] - 1
    return out

def ev(hit, T):   # hit = P(peak >= T)
    return hit * (T - 1) - (1 - hit) - COST

def block_boot(df, mask, T, n=2000, seed=0):
    """Paired bootstrap over weeks: resample WEEKS, recompute dEV and
    dProfit/week on each draw. Paired because both arms come from the same
    resampled weeks."""
    rng = np.random.default_rng(seed)
    wk = df.week.to_numpy(); y = df[f"h{T}"].to_numpy(); m = mask.to_numpy()
    weeks = np.unique(wk); W = len(weeks)
    idx = {w: np.where(wk == w)[0] for w in weeks}
    dev, dpw = [], []
    for _ in range(n):
        pick = rng.choice(weeks, W, replace=True)
        sel = np.concatenate([idx[w] for w in pick])
        yy, mm = y[sel], m[sel]
        if mm.sum() < 30 or (~mm).sum() < 30: continue
        e_on, e_off = ev(yy[mm].mean(), T), ev(yy.mean(), T)
        dev.append(e_on - e_off)
        dpw.append(e_on * mm.sum() / W - e_off * len(yy) / W)
    return np.array(dev), np.array(dpw)

def report(df, name, mask, T):
    on, base = df[mask], df
    if len(on) < 200: print(f"  {name:<44} (too few: {len(on)})"); return
    h_on, h_off = on[f"h{T}"].mean(), base[f"h{T}"].mean()
    e_on, e_off = ev(h_on, T), ev(h_off, T)
    W = df.week.nunique()
    pw_on, pw_off = e_on * len(on) / W, e_off * len(base) / W
    dev, dpw = block_boot(df, mask, T)
    if len(dev) == 0: print(f"  {name:<44} (bootstrap empty)"); return
    p = (dev <= 0).mean()
    star = "**" if p < 0.05 and np.median(dpw) > 0 else ("*" if p < 0.05 else "")
    print(f"  {name:<44} keep {100*len(on)/len(base):5.1f}%  "
          f"hit {100*h_on:5.2f}% vs {100*h_off:5.2f}%  "
          f"dEV {np.median(dev):+7.3f} [{np.percentile(dev,5):+.3f},{np.percentile(dev,95):+.3f}]  "
          f"dProfit/wk {np.median(dpw):+8.2f}  P(dEV<=0) {p:.3f} {star}")

if __name__ == "__main__":
    cols = ['spot','opt_type','entry_ts','event_id','activated','entry_premium','y_10x','y_25x',
            'cx240_always_in','cx240_range_pos_20','cx240_bull_broken','cx240_bear_broken',
            'cx240_efficiency_20','cx240_ema20_run','cx240_bars_since_ma','cx1440_always_in',
            'cx240_chan_overshoot','cx60_always_in','cx240_is_spike','cx240_bo_failrate']
    parts = []
    for s in ['BTC','ETH']:
        d = pd.read_parquet(f'events_ctx/{s}.parquet', columns=cols)
        d = d[d.activated & d.entry_premium.between(2, 20)]
        d['fwd'] = fwd_spot_return(s, d.entry_ts.to_numpy())
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    e = d.groupby('event_id').agg(
        ty=('opt_type','first'), ts=('entry_ts','first'), fwd=('fwd','first'),
        h10=('y_10x','mean'), h25=('y_25x','mean'),
        ai=('cx240_always_in','first'), ai_d=('cx1440_always_in','first'),
        ai_h=('cx60_always_in','first'), rpos=('cx240_range_pos_20','first'),
        bull_br=('cx240_bull_broken','first'), bear_br=('cx240_bear_broken','first'),
        eff=('cx240_efficiency_20','first'), run=('cx240_ema20_run','first'),
        ovr=('cx240_chan_overshoot','first'), spike=('cx240_is_spike','first'),
        bofail=('cx240_bo_failrate','first')).reset_index()
    e['week'] = ((e.ts + 19800)//604800).astype(int)
    e['year'] = pd.to_datetime(e.ts, unit='s').dt.year
    e = e.dropna(subset=['fwd'])
    bull = e.ty == 'C'
    print(f"events {len(e):,}  weeks {e.week.nunique()}  "
          f"base hit10 {100*e.h10.mean():.2f}%  hit25 {100*e.h25.mean():.2f}%\n")

    RULES = {
      "R4  agrees with 4h always-in":      np.where(bull, e.ai==1, e.ai==-1),
      "R4d agrees with 1d always-in":      np.where(bull, e.ai_d==1, e.ai_d==-1),
      "R4x agrees on 1h+4h+1d":            np.where(bull,(e.ai==1)&(e.ai_d==1)&(e.ai_h==1),
                                                         (e.ai==-1)&(e.ai_d==-1)&(e.ai_h==-1)),
      "R1  opposing trend line broken":    np.where(bull, e.bear_br==1, e.bull_br==1),
      "R2  at favourable range extreme":   np.where(bull, e.rpos>=0.75, e.rpos<=0.25),
      "R2b at Brooks fade extreme":        np.where(bull, e.rpos<=0.25, e.rpos>=0.75),
      "R6  not in a spike bar":            (e.spike==0).to_numpy(),
      "eff low (range context)":           (e.eff<0.35).to_numpy(),
      "eff high (trend context)":          (e.eff>=0.35).to_numpy(),
      "R7  channel line overshoot":        (e.ovr>0).to_numpy(),
      "R10 R4 AND R1 (two reasons)":       (np.where(bull,e.ai==1,e.ai==-1) &
                                            np.where(bull,e.bear_br==1,e.bull_br==1)),
    }
    for T in TARGETS:
        print(f"=== TARGET {T}x — raw, no direction control ===")
        for nm, m in RULES.items(): report(e, nm, pd.Series(m, index=e.index), T)
        print()

    print("=== DIRECTION CONTROL: same rules WITHIN realised-forward-return buckets ===")
    e['fb'] = pd.qcut(e.fwd, 5, labels=['big down','down','flat','up','big up'])
    for nm in ["R4  agrees with 4h always-in", "R1  opposing trend line broken",
               "R2  at favourable range extreme"]:
        m = pd.Series(RULES[nm], index=e.index)
        print(f"\n  {nm}")
        for b in e.fb.cat.categories:
            s = e[e.fb == b]
            mm = m[e.fb == b]
            if mm.sum() < 200 or (~mm).sum() < 200: continue
            print(f"    {b:<9} n={len(s):6,}  hit25 on {100*s[mm].h25.mean():5.2f}%  "
                  f"off {100*s[~mm].h25.mean():5.2f}%  lift {s[mm].h25.mean()/max(s[~mm].h25.mean(),1e-9):5.2f}x")
