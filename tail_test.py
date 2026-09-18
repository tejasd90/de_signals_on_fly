#!/usr/bin/env python3
"""
tail_test.py — Tejas's channel-line claim, measured at the TAIL target.

TWO CHANGES FROM rules_test.py, both from his four dated episodes.

1. TARGET. Everything in this project targeted 25x. All four of his episodes are
   100x-9,000x, verified on traded prices with real volume. A rule can be
   invisible at 25x and real in the far tail, so 100x is tested alongside.

2. PREMIUM BAND. rules_test.py filters entry_premium to [2, 20]. His episodes
   entered at 0.064, 0.30, 0.45, 0.50, 0.58 -- almost all BELOW that floor, so
   the old band structurally excluded the contracts that produced the tails.
   Measured: the 2-20 band is BELOW break-even at 100x (1.012% vs 1.083% needed)
   while premium < 2 runs 1.14-1.21%. Both bands are reported.

THE CLAIM UNDER TEST, in his words:
   "a strong indication of immediate breakout-breakdown is channel line break.
    Trendlines breaking only break the trend, but channel line breaks are
    breakouts."
So CL and TL are run head to head, same direction convention, same events. If he
is right, CL carries tail probability that TL does not.

DIRECTION CONVENTION
A call needs spot UP, a put needs spot DOWN:
   upside   bull_cl_break (above bull channel line) · bear_tl_break (above bear trend line)
   downside bear_cl_break (below bear channel line) · bull_tl_break (below bull trend line)

CONTROLS ARE INHERITED, NOT RELAXED
Paired weekly block bootstrap (weeks are the unit of independence), dEV AND
profit/week together (trap #10), and the realised-forward-return control that
catches a rule which is only reading direction. Event level uses the MEAN across
strikes, never the max -- the max embeds a strike oracle that cannot be traded.
"""
import numpy as np, pandas as pd, argparse
from rules_test import ev, block_boot, report, fwd_spot_return, COST

def load(band, tf=240):
    d = pd.read_parquet("events.parquet", columns=[
        "spot","opt_type","entry_ts","event_id","activated","entry_premium",
        "peak_vs_trigger","peak_vs_close"])
    d = d[d.activated & d.spot.isin(["BTC","ETH"])].copy()
    d["r"] = d.peak_vs_trigger.fillna(d.peak_vs_close)
    d = d.dropna(subset=["r","entry_premium"])
    d = d[d.entry_premium.between(*band)]
    for T in (25, 100):
        d[f"y{T}"] = (d.r >= T).astype(float)
    cl = pd.read_parquet("events_cl.parquet")
    keep = ["spot","entry_ts"] + [c for c in cl.columns if c.startswith(f"cz{tf}_")]
    d = d.merge(cl[keep], on=["spot","entry_ts"], how="left")
    ren = {c: c.replace(f"cz{tf}_","") for c in d.columns if c.startswith(f"cz{tf}_")}
    d = d.rename(columns=ren)
    parts = []
    for s in ("BTC","ETH"):
        x = d[d.spot == s].copy()
        x["fwd"] = fwd_spot_return(s, x.entry_ts.to_numpy())
        parts.append(x)
    d = pd.concat(parts, ignore_index=True)
    agg = {"ty":("opt_type","first"), "ts":("entry_ts","first"), "fwd":("fwd","first"),
           "h25":("y25","mean"), "h100":("y100","mean"), "prem":("entry_premium","first")}
    for c in ["bull_cl_break","bear_cl_break","bull_tl_break","bear_tl_break",
              "bull_chan_w","bear_chan_w","quiet_ratio","hairy_10",
              "qbreak_up_20","qbreak_dn_20","qwidth_20","bull_cl_dist","bear_cl_dist"]:
        if c in d.columns: agg[c] = (c, "first")
    e = d.groupby("event_id").agg(**agg).reset_index()
    e["week"] = ((e.ts + 19800)//604800).astype(int)
    return e.dropna(subset=["fwd"])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", type=int, default=240)
    a = ap.parse_args()
    for band in [(0.1, 2.0), (2.0, 20.0)]:
        e = load(band, a.tf)
        bull = (e.ty == "C").to_numpy()
        print(f"\n{'='*104}")
        print(f"PREMIUM {band[0]}-{band[1]}   {a.tf}m context   events {len(e):,}  weeks {e.week.nunique()}  "
              f"base hit25 {100*e.h25.mean():.2f}%  hit100 {100*e.h100.mean():.3f}%")
        print(f"break-even hit: 25x {100*(1+COST)/25:.2f}%   100x {100*(1+COST)/100:.3f}%")
        print('='*104)
        R = {
          "CL  channel line broken (his claim)":
              np.where(bull, e.bull_cl_break==1, e.bear_cl_break==1),
          "TL  trend line broken (already dead at 25x)":
              np.where(bull, e.bear_tl_break==1, e.bull_tl_break==1),
          "CL and NOT TL  (the distinction)":
              np.where(bull, (e.bull_cl_break==1)&(e.bear_tl_break!=1),
                             (e.bear_cl_break==1)&(e.bull_tl_break!=1)),
          "TL and NOT CL":
              np.where(bull, (e.bear_tl_break==1)&(e.bull_cl_break!=1),
                             (e.bull_tl_break==1)&(e.bear_cl_break!=1)),
          "QB  quiet-range break in our direction":
              np.where(bull, e.qbreak_up_20==1, e.qbreak_dn_20==1),
          "QB and quiet first (contraction then break)":
              np.where(bull, (e.qbreak_up_20==1)&(e.quiet_ratio<0.9),
                             (e.qbreak_dn_20==1)&(e.quiet_ratio<0.9)),
          "CLEAN  not hairy (low bar overlap)": (e.hairy_10 < 0.45).to_numpy(),
          "CL + CLEAN": np.where(bull, e.bull_cl_break==1, e.bear_cl_break==1) & (e.hairy_10<0.45).to_numpy(),
        }
        for T in (25, 100):
            print(f"\n--- TARGET {T}x ---")
            for nm, m in R.items():
                report(e, nm, pd.Series(m, index=e.index), T)
        # direction control on whatever looked alive
        print(f"\n--- DIRECTION CONTROL at 100x (buckets of REALISED forward spot return) ---")
        e["fb"] = pd.qcut(e.fwd, 5, labels=["big down","down","flat","up","big up"])
        for nm in ["CL  channel line broken (his claim)", "QB  quiet-range break in our direction"]:
            m = pd.Series(R[nm], index=e.index)
            print(f"  {nm}")
            for b in e.fb.cat.categories:
                s = e[e.fb==b]; mm = m[e.fb==b]
                if mm.sum() < 150 or (~mm).sum() < 150: continue
                on, off = s[mm].h100.mean(), s[~mm].h100.mean()
                print(f"    {b:<9} n={len(s):6,}  hit100 on {100*on:5.3f}%  off {100*off:5.3f}%  "
                      f"lift {on/max(off,1e-9):5.2f}x")
