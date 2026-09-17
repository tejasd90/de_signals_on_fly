#!/usr/bin/env python3
"""
build_price_action.py — a sidecar the grid viewers can read.

Turns the 273 context features in events_ctx2/ into ~10 short, legible labels
per signal, written one file per expiry so node can load a cache line rather
than a parquet:

    data/price_action/{spot}/{expiry}.json   { "<event_id>": {"l":[codes], "r":ratio} }
    data/price_action/_stats.json            per-code: n, hit25, maxratio, text, tier

WHY A SIDECAR AND NOT A JS PORT
Porting 273 features to node would duplicate the logic and guarantee drift. The
same argument that made surface.js shared. Python computes, node renders.

WHY THE COLOUR IS A HIT RATE, NOT THE MAX
Shading by max ratio was the original request. It cannot work: DECISION_DOCUMENT
established that the max operator does the work, not the signal, and the biggest
ratios here sit on 0.55-premium contracts that are one tick of noise. Every label
co-occurs with one of those eventually, so a max-shaded panel would glow
uniformly and say nothing. The colour is therefore P(25x) among TRADEABLE events
— filled, entry premium >= 2 — and the max is printed as text beside it.

TIERS, so the panel does not overclaim
  measured  the one rule that survived controls (always-in agreement)
  context   real, descriptive, and measured NOT to add anything on top of it
  structure bar mechanics, no shading at all
"""
import os, json, argparse
import numpy as np, pandas as pd

OUT = "data/price_action"

VOCAB = {
 "ai+": ("4h always-in agrees with the signal",        "measured"),
 "ai-": ("4h always-in AGAINST the signal",            "measured"),
 "ai0": ("4h always-in unclear",                       "measured"),
 # `tlb` (least-squares trend line) was REMOVED 2026-09-17. It fitted the last
 # 4 local swings and on ETH daily reported a bear line sloping +0.101 — a
 # rising line labelled as falling — and flagged breaks that never happened.
 # Replaced by hull-based structural lines on daily and weekly.
 "tlD": ("DAILY structural trend line broken in our favour",  "structure"),
 "tlW": ("WEEKLY structural line broken — measured HARMFUL, the move is priced", "structure"),
 "tlA": ("price within 0.5 ATR of the daily structural line (a test)", "structure"),
 "rg+": ("at the favourable end of the 20-bar range",  "context"),
 "rg-": ("at the wrong end of the 20-bar range",       "context"),
 "reR": ("range regime (low efficiency)",              "context"),
 "reT": ("trending regime (high efficiency)",          "context"),
 "p3":  ("three-push move in our direction",           "context"),
 "wdg": ("wedge — pushes converging",                  "context"),
 "exh": ("exhaustion bar (>2x average range)",         "context"),
 "clx": ("consecutive climax bars",                    "context"),
 "tst": ("testing a prior swing extreme",              "context"),
 "lg2": ("second entry (H2/L2)",                       "structure"),
 "lg1": ("first entry (H1/L1)",                        "structure"),
 "mg":  ("micro gap in our direction",                 "structure"),
 "mc":  ("micro channel, 4+ bars",                     "structure"),
 # Tejas's two axes. BOTH were measured and BOTH were found not to add on top of
 # R4 — culmination pays less, and energy is inverted (loudest quintile is the
 # worst). Shown anyway, in their own tiers, because "what was there" is worth
 # seeing even when it does not predict. The UI labels the tiers accordingly.
 "cul": ("CULMINATION — rejection / failed breakout / exhaustion", "role"),
 "acm": ("ACCUMULATION — small, overlapping, subordinate bar",     "role"),
 "n1":  ("energy Q1 — quietest",                       "energy"),
 "n2":  ("energy Q2",                                  "energy"),
 "n3":  ("energy Q3 — middling",                       "energy"),
 "n4":  ("energy Q4",                                  "energy"),
 "n5":  ("energy Q5 — loudest",                        "energy"),
 # The RAW 4h read, so the panel shows what the market was doing and not only
 # the verdict relative to this contract.
 "aiU": ("4h always-in: UP (a forced position would be LONG)",  "state"),
 "aiD": ("4h always-in: DOWN (a forced position would be SHORT)","state"),
 "aiN": ("4h always-in: UNCLEAR — Brooks' own answer for a range","state"),
 # R5: the 20-day regime. Measured to ADD on top of the agreement check.
 "t2U": ("20-day trend: clean UPTREND — R4 collapses here, stand aside", "regime"),
 "t2D": ("20-day trend: clean downtrend",                "regime"),
 "t2S": ("20-day trend: sideways — the best regime for both calls and puts","regime"),
}

def structural_axes(d, spot):
    """Hull-based structural trend lines on daily and weekly, joined causally.

    Replaces the least-squares lines, which were not merely weak but WRONG —
    see structural_lines.py. These find the real multi-month lines: on ETH they
    pick up the 372-day daily line and flag the break on the day it broke.

    R1 says a break does not predict (daily P~0.7, weekly significantly
    harmful), so these sit in the `structure` tier, not a predictive one. They
    are here so the panel shows real structure when a past case is examined."""
    import json as _json
    import structural_lines as SL
    CFG = {1440: dict(k=5, min_prom=1.0, lookback=400),
           10080: dict(k=2, min_prom=0.8, lookback=100)}
    call = (d.opt_type == "C").to_numpy()
    res = {}
    for tf, tag in ((1440, "D"), (10080, "W")):
        fp = f"data/spot_grouped/{spot}/{tf}.json"
        if not os.path.exists(fp):
            res[tag] = (np.zeros(len(d), bool), np.zeros(len(d), bool)); continue
        a = np.asarray(_json.load(open(fp)), float)
        g = SL.lines(a, **CFG[tf])
        j = np.searchsorted(a[:, 0] + tf * 60, d.entry_ts.to_numpy(), side="right") - 1
        ok = j >= 0
        bd = np.full(len(d), np.nan); bu = np.full(len(d), np.nan)
        bd[ok] = g["bear_dist"].to_numpy()[j[ok]]
        bu[ok] = g["bull_dist"].to_numpy()[j[ok]]
        # for a CALL the favourable break is the BEAR line giving way
        rel = np.where(call, bd, bu)
        broke = np.where(call, rel > 0.25, rel < -0.25)
        near  = np.abs(rel) <= 0.5
        res[tag] = (np.nan_to_num(broke, nan=0).astype(bool),
                    np.nan_to_num(near,  nan=0).astype(bool))
    return res


def trend20(spot):
    """The 20-DAY regime label from de-signals-regime-filter, rebuilt. Distinct
    from always-in on both axes: 20 days rather than 4 hours, and a pooled veto
    rather than a direction match. Measured to ADD on top of R4 (dEV +0.150,
    P=0.001) because a clean daily uptrend is bad for deep-OTM buying whichever
    side you are on — a different mechanism from direction."""
    import significance as S
    a = S.load_tf_grouped(spot, 1440)
    if a is None: return None, None
    ts, c = a[:, 0], a[:, 4]
    ret = np.concatenate([np.full(20, np.nan), c[20:] / c[:-20] - 1])
    net = np.abs(np.concatenate([np.full(20, np.nan), c[20:] - c[:-20]]))
    tot = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(20, min_periods=2).sum().to_numpy()
    eff = net / np.maximum(tot, 1e-12)
    return ts, np.where((eff > 0.35) & (ret > 0), 1,
                 np.where((eff > 0.35) & (ret < 0), -1, 0)).astype(float)


def own_tf_axes(d, spot):
    """Structural role and energy at the signal's OWN timeframe.

    Both were tested (docs/ML/CONTEXT_PLAN.md): culmination pays LESS, and energy
    is inverted and monotone — the loudest quintile is the worst. They are shown
    in the panel anyway, tiered so the UI says which ones were measured to
    predict and which were measured not to."""
    import significance as S
    call = (d.opt_type == "C").to_numpy()
    culm = np.full(len(d), np.nan); acc = np.full(len(d), np.nan)
    nrg  = np.full(len(d), np.nan)
    for dur in S.DURS:
        m = (d.duration == dur).to_numpy()
        if not m.any(): continue
        a = S.load_tf_grouped(spot, dur)
        if a is None: continue
        g = S.sig_features(a)
        ts, o, h, l, c = a[:,0], a[:,1], a[:,2], a[:,3], a[:,4]
        rng = np.maximum(h-l, 1e-12); body = np.abs(c-o)
        A = S.atr_(h,l,c); A = np.where(A>0, A, np.nan)
        hi20 = pd.Series(h).rolling(20,min_periods=2).max().shift(1).to_numpy()
        lo20 = pd.Series(l).rolling(20,min_periods=2).min().shift(1).to_numpy()
        cp = (c-l)/rng
        avg = pd.Series(rng).rolling(10,min_periods=3).mean().to_numpy()
        exh = (rng/np.maximum(avg,1e-12) > 2.0) & (body/rng > 0.6)
        d3  = pd.Series(np.sign(c-o)).rolling(3,min_periods=3).sum().shift(1).to_numpy()
        cu_up = ((l<lo20)&(cp>0.65)) | ((l<lo20)&(c>lo20)) | ((c>o)&(body/A>1.0)&(d3<=-2)) | exh
        cu_dn = ((h>hi20)&(cp<0.35)) | ((h>hi20)&(c<hi20)) | ((c<o)&(body/A>1.0)&(d3>= 2)) | exh
        ov = np.concatenate([[np.nan],
             (np.minimum(h[1:],h[:-1])-np.maximum(l[1:],l[:-1]))/np.maximum(rng[1:],1e-12)])
        inside = np.concatenate([[0.],((h[1:]<=h[:-1])&(l[1:]>=l[:-1])).astype(float)])
        ac = (np.nan_to_num((rng/A<0.7).astype(float)) +
              np.nan_to_num(np.clip(ov,0,1)) + inside)/3.0
        zs = []
        for col in S.COMPONENTS:
            v = g[col].to_numpy(); mu, sd = np.nanmean(v), np.nanstd(v)
            zs.append(np.clip((v-mu)/(sd if sd>0 else 1), -4, 4))
        score = np.nanmean(np.vstack(zs), axis=0)
        j = np.searchsorted(ts + dur*60, d.loc[m,"entry_ts"].to_numpy(), side="right")-1
        ok = j >= 0
        idx = np.where(m)[0][ok]; jj = j[ok]
        culm[idx] = np.where(call[idx], cu_up[jj], cu_dn[jj]).astype(float)
        acc[idx]  = ac[jj]
        nrg[idx]  = score[jj]
    return culm, acc, nrg


def labels_for(d):
    """Vectorised label construction. `d` is one spot's event rows."""
    call = (d.opt_type == "C").to_numpy()
    def pk(a, b=None): return d[a].to_numpy() if b is None else np.where(call, d[a], d[b])
    ai   = d.cx240_always_in.to_numpy()
    agree = np.where(call, ai == 1, ai == -1)
    against = np.where(call, ai == -1, ai == 1)
    brk  = np.where(call, d.cx240_bear_dist, d.cx240_bull_dist)
    rpos = d.cx240_range_pos_20.to_numpy()
    eff  = d.cx240_efficiency_20.to_numpy()
    leg  = np.where(call, d.cy240_h_count, d.cy240_l_count)
    cols = {
      "ai+": agree, "ai-": against, "ai0": (~agree) & (~against),
      "rg+": np.where(call, rpos >= 0.75, rpos <= 0.25),
      "rg-": np.where(call, rpos <= 0.25, rpos >= 0.75),
      "reR": eff < 0.35, "reT": eff >= 0.35,
      "p3":  np.where(call, d.cy240_push3_up, d.cy240_push3_dn) == 1,
      "wdg": np.where(call, d.cy240_wedge_up, d.cy240_wedge_dn) == 1,
      "exh": d.cy240_is_exhaustion.to_numpy() == 1,
      "clx": d.cy240_consec_climax.to_numpy() >= 2,
      "tst": np.abs(np.where(call, d.cy240_test_hi, d.cy240_test_lo)) < 0.5,
      "lg2": leg == 2, "lg1": leg == 1,
      "mg":  np.where(call, d.cy240_micro_gap_up, d.cy240_micro_gap_dn) == 1,
      "mc":  np.where(call, d.cy240_micro_up, d.cy240_micro_dn) >= 4,
    }
    return {k: np.nan_to_num(v, nan=0).astype(bool) for k, v in cols.items()}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--src", default="events_ctx2")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    stats = {k: dict(n=0, hit=0, mx=0.0, text=v[0], tier=v[1]) for k, v in VOCAB.items()}

    for spot in ["BTC", "ETH", "XAUT"]:
        fp = os.path.join(a.src, f"{spot}.parquet")
        if not os.path.exists(fp): continue
        d = pd.read_parquet(fp)
        L = labels_for(d)
        culm, acc, nrg = own_tf_axes(d, spot)
        L["cul"] = np.nan_to_num(culm, nan=0) > 0
        L["acm"] = (np.nan_to_num(acc, nan=0) >= 0.55) & ~L["cul"]
        qs = np.nanquantile(nrg, [.2,.4,.6,.8]) if np.isfinite(nrg).any() else [0,0,0,0]
        b = np.digitize(nrg, qs)
        for k in range(5):
            L[f"n{k+1}"] = np.isfinite(nrg) & (b == k)
        # raw 4h direction, independent of which contract this is
        st = structural_axes(d, spot)
        L["tlD"], nearD = st["D"][0], st["D"][1]
        L["tlW"] = st["W"][0]
        L["tlA"] = nearD & ~L["tlD"]
        ai = d.cx240_always_in.to_numpy()
        L["aiU"] = ai == 1; L["aiD"] = ai == -1; L["aiN"] = ai == 0
        # 20-day regime (R5)
        tts, tlab = trend20(spot)
        if tts is None:
            for k in ("t2U","t2D","t2S"): L[k] = np.zeros(len(d), bool)
        else:
            j = np.searchsorted(tts + 86400, d.entry_ts.to_numpy(), side="right") - 1
            v = np.full(len(d), np.nan); ok = j >= 0; v[ok] = tlab[j[ok]]
            L["t2U"] = v == 1; L["t2D"] = v == -1; L["t2S"] = v == 0
        codes = list(VOCAB)
        # stats are computed on the TRADEABLE population only
        # Same population the rule study used: filled, premium 2-20. Widening it
        # to all premiums flattens every label to ~1.0-1.7% because expensive
        # contracts cannot reach 25x whatever the context, and the colour then
        # carries no information. Stated in the legend so the basis is explicit.
        tr = (d.activated & d.entry_premium.between(2, 20)).to_numpy()
        y25 = (d.y_25x.to_numpy() > 0); rat = d.peak_vs_trigger.to_numpy()
        for k in codes:
            m = L[k] & tr
            stats[k]["n"] += int(m.sum())
            stats[k]["hit"] += int((y25 & m).sum())
            if m.any(): stats[k]["mx"] = max(stats[k]["mx"], float(np.nanmax(rat[m])))

        # one row per EVENT, labels are constant within an event
        idx = ~d.event_id.duplicated().to_numpy()
        ev = d.loc[idx, ["event_id", "expiry", "ratio_oracle"]].copy()
        mat = np.vstack([L[k][idx] for k in codes]).T
        ev["l"] = [",".join(c for c, f in zip(codes, row) if f) for row in mat]
        os.makedirs(os.path.join(OUT, spot), exist_ok=True)
        n = 0
        for exp, g in ev.groupby("expiry"):
            obj = {r.event_id: {"l": r.l.split(",") if r.l else [],
                                "r": round(float(r.ratio_oracle or 0), 3)}
                   for r in g.itertuples()}
            with open(os.path.join(OUT, spot, f"{exp}.json"), "w") as f:
                json.dump(obj, f, separators=(",", ":"))
            n += len(obj)
        print(f"  {spot}: {n:,} events -> {ev.expiry.nunique():,} files", flush=True)

    for k, v in stats.items():
        v["hit25"] = round(v["hit"] / v["n"], 5) if v["n"] else None
        v["mx"] = round(v["mx"], 1); v.pop("hit")
    json.dump(stats, open(os.path.join(OUT, "_stats.json"), "w"), indent=1)
    print(f"\nwrote {OUT}/_stats.json")
    for k, v in sorted(stats.items(), key=lambda x: -(x[1]["hit25"] or 0)):
        print(f"  {k:<5}{str(v['tier']):<10}n={v['n']:>8,}  hit25 "
              f"{100*(v['hit25'] or 0):5.2f}%  max {v['mx']:>8.1f}x  {v['text']}")
