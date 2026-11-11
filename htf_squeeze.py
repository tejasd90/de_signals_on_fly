"""His 11 Nov 2026 hypothesis: the PARABOLIC otm_red_squeeze on HIGH timeframes (6h, 12h, 1d, 1w) predicts 1:100.

His points, tested as stated:
  1. the decay into the squeeze is a parabola, ideally bounded from above AND below (highs and lows both on one);
  2. the squeeze must not be part of a spot move in the opposite direction ("counter-trend set-up, false flat");
  3. otm_wall / green_stairs on smaller timeframes help as part of the bigger squeeze;
  4. priority by timeframe, context, strength, with-trend.

`build` scans every BTC/ETH contract's 1h MARK candles, rebuilds the 4h/6h/8h/12h/1d/1w bars (00:00 UTC anchored, as
Delta's; 1w from Monday) and re-implements signals/otm_red_squeeze.js bar for bar. Rows written (data/htf_squeeze/):
  kind 'g'  every closed GREEN bar that follows >= 1 red bar, on an option that is OTM and cheap (<= spot/300);
            is_sq marks the ones the JS signal fires on (>= 3 reds with strictly shrinking bodies, containment,
            OTM at pattern start, spot/mean(lows, trigger close) >= 1000). The rest are the natural controls.
  kind 'r'  a 15% random sample of all other closed bars on OTM cheap options (the "any moment" baseline).
Every feature uses bars closed at or before the trigger close. Entry = trigger close. Outcome = later 1h highs to
the contract's last bar / entry (x_max), last close / entry (x_end). MARK prices: multiples are upper bounds.

Arc = from the highest high of the previous 30 bars to the trigger. Quadratics are fitted to the highs and to the
lows, on price / arc high (what the eye sees) and on log price (decelerating even in % terms).
"""
import sys, os, json, glob, zlib, time, numpy as np, pandas as pd
from multiprocessing import Pool
TFS = (240, 360, 480, 720, 1440, 10080); LB = 30; CHEAP = 300; MIN_TTE_H = 1.5; RAND = 0.15
OUT = os.environ.get("HTF_OUT", "data/htf_squeeze")
_S = {}

def spot(asset):
    if asset in _S: return _S[asset]
    rows = []
    for f in sorted(glob.glob(f"data/spot_candles/{asset}/60/*")):
        try: rows += [r[:5] for r in json.load(open(f)) if None not in r[:5]]
        except Exception: pass
    a = np.array(rows, dtype=float); _, ix = np.unique(a[:, 0], return_index=True); a = a[ix]
    lr = pd.Series(np.diff(np.log(a[:, 4]), prepend=np.nan))
    _S[asset] = dict(tc=a[:, 0].astype(np.int64) + 3600, t=a[:, 0].astype(np.int64), o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4],
                     s30=lr.rolling(720, min_periods=240).std().values, s7=lr.rolling(168, min_periods=100).std().values)
    return _S[asset]

def at(S, T, key="c"):
    """value of the last hourly spot bar closed at or before T (NaN if none within 3h)"""
    T = np.atleast_1d(T); i = np.searchsorted(S["tc"], T, "right") - 1
    ok = (i >= 0) & (T - S["tc"][np.clip(i, 0, None)] <= 3 * 3600)
    return np.where(ok, S[key][np.clip(i, 0, None)], np.nan)

def quad(y):
    """a, r2, vertex (bars after the last point; negative = already past) of a quadratic through y"""
    n = len(y); x = np.arange(n, dtype=float)
    a, b, c = np.polyfit(x, y, 2); fit = a * x * x + b * x + c
    ss = ((y - y.mean()) ** 2).sum(); r2 = 1 - ((y - fit) ** 2).sum() / ss if ss > 0 else np.nan
    return a, r2, (-b / (2 * a) - (n - 1)) if a != 0 else np.nan

def contract(path, asset, exp_ts, S):
    sym = os.path.basename(path)[:-5]; p = sym.split("-")
    if len(p) != 4 or p[0] not in "CP": return []
    side = p[0]; strike = float(p[2]); dr = 1 if side == "C" else -1
    try: raw = json.load(open(path))
    except Exception: return []
    a = np.array([r[:5] for r in raw if None not in r[:5]], dtype=float)
    if len(a) < 6: return []
    a = a[np.argsort(a[:, 0])]; a = a[a[:, 0] < exp_ts]
    if len(a) < 6: return []
    ts = a[:, 0].astype(np.int64); o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    sufmax = np.maximum.accumulate(h[::-1])[::-1]; n1 = len(ts); out = []
    rng = np.random.default_rng(zlib.crc32(sym.encode()))
    for d in TFS:
        w = d * 60; b = (ts - 4 * 86400) // w if d == 10080 else ts // w
        ub, fi = np.unique(b, return_index=True); nb = len(ub)
        if nb < 3: continue
        li = np.r_[fi[1:] - 1, n1 - 1]
        O = o[fi]; C = c[li]; H = np.maximum.reduceat(h, fi); L = np.minimum.reduceat(l, fi)
        to = ub * w + (4 * 86400 if d == 10080 else 0); tc = to + w
        Sc = at(S, tc); tte = (exp_ts - tc) / 3600
        otm = (strike > Sc) if side == "C" else (strike < Sc)
        ok = (tc <= ts[-1] + 3600) & (tte >= MIN_TTE_H) & np.isfinite(Sc) & (C > 0) & (li + 1 < n1)
        cheap = np.where(C > 0, Sc / np.where(C > 0, C, 1), 0)
        if not (ok & (cheap >= CHEAP)).any(): continue
        Ol, Cl, Hl, Ll = O.tolist(), C.tolist(), H.tolist(), L.tolist()
        red = []; nred = 0
        for i in range(nb):
            oi, ci = Ol[i], Cl[i]; kind = None; seq = []
            if i == 0: nred = 1 if ci < oi else 0; continue
            if ci == oi: red = []; nred = 0
            elif ci < oi:
                bd = oi - ci
                if not red or bd < Ol[red[-1]] - Cl[red[-1]]: red.append(i)
                else: red = [i]
                nred += 1
            else:
                seq = red; nr = nred; red = []; nred = 0
                if nr >= 1: kind = "g"
            if not ok[i] or cheap[i] < CHEAP: continue
            if kind is None:
                if not otm[i] or rng.random() >= RAND: continue
                kind = "r"
            k0 = li[i] + 1; e = ci
            r = dict(asset=asset, sym=sym, side=side, strike=strike, tf=d, kind=kind, t_close=int(tc[i]), tte_h=tte[i],
                     entry=e, spot=Sc[i], mny=dr * (strike / Sc[i] - 1) * 100, cheap=cheap[i], otm_now=bool(otm[i]),
                     x_max=sufmax[k0] / e, x_end=c[-1] / e, x_24=h[k0:k0 + 24].max() / e)
            for K in (5, 25):
                hit = h[k0:] >= K * e
                r[f"t{K}_h"] = float(np.argmax(hit) + 1) if hit.any() else np.nan
            if i + 3 < nb and li[i + 3] + 1 < n1:
                cw = Cl[i + 3]
                r.update(held3=min(Ll[i + 1:i + 4]) >= Ll[i], ran3=max(Hl[i + 1:i + 4]) >= 2 * e, entry_w=cw,
                         xw_max=sufmax[li[i + 3] + 1] / cw if cw > 0 else np.nan, xw_end=c[-1] / cw if cw > 0 else np.nan)
            s30 = at(S, tc[i], "s30")[0]; s7 = at(S, tc[i], "s7")[0]
            r["quiet"] = s7 / s30 if s30 > 0 else np.nan
            sp20 = at(S, tc[i] - 20 * w)[0]
            r["trend20"] = dr * np.log(Sc[i] / sp20) / (s30 * np.sqrt(20 * d / 60)) if s30 > 0 and sp20 > 0 else np.nan
            ia, ib = np.searchsorted(S["t"], to[i]), np.searchsorted(S["t"], tc[i])
            if ib > ia:
                so, sc_, sh, sl = S["o"][ia], S["c"][ib - 1], S["h"][ia:ib].max(), S["l"][ia:ib].min()
                r["opp_big"] = bool(sh > sl and abs(sc_ - so) / (sh - sl) >= 0.6 and dr * (sc_ - so) < 0)
            j0 = max(0, i - LB); jp = j0 + int(np.argmax(H[j0:i])); n = i - jp + 1
            r.update(arc_len=n, depth=e / H[jp])
            sa = at(S, to[jp])[0]
            if s30 > 0 and sa > 0:
                r["z_arc"] = dr * np.log(Sc[i] / sa) / (s30 * np.sqrt((tc[i] - to[jp]) / 3600))
            if n >= 5 and L[jp:i + 1].min() > 0:
                yh, yl = H[jp:i + 1] / H[jp], L[jp:i + 1] / H[jp]
                for nm, y in (("hi", yh), ("lo", yl), ("lhi", np.log(yh)), ("llo", np.log(yl))):
                    r[f"a_{nm}"], r[f"r2_{nm}"], r[f"vx_{nm}"] = quad(y)
            if kind == "g":
                P = seq if len(seq) >= 3 else list(range(i - nr, i))
                f0 = P[0]; k = len(P)
                r.update(n_red=nr, n_dec=len(seq), pat_h=(tc[i] - to[f0]) / 3600)
                s0 = at(S, to[f0])[0]
                if s30 > 0 and s0 > 0:
                    r["fav_pat"] = dr * np.log(Sc[i] / s0) * 100
                    r["z_pat"] = dr * np.log(Sc[i] / s0) / (s30 * np.sqrt((tc[i] - to[f0]) / 3600))
                    sb = at(S, 2 * to[f0] - tc[i])[0]
                    if sb > 0: r["z_pre"] = dr * np.log(s0 / sb) / (s30 * np.sqrt((tc[i] - to[f0]) / 3600))
                if k >= 3:
                    hr, lr_ = np.array([Hl[q] for q in P]), np.array([Ll[q] for q in P])
                    r.update(hi_par=bool((np.diff(hr) < 0).all() and (np.diff(hr, 2) > 0).all()),
                             lo_par=bool((np.diff(lr_) < 0).all() and (np.diff(lr_, 2) > 0).all()))
                    b0, b1 = Ol[P[0]] - Cl[P[0]], Ol[P[-1]] - Cl[P[-1]]
                    r.update(ratio1=b0 / b1 if b1 > 0 else np.nan, ratio2=b0 / (ci - oi))
                if len(seq) >= 3:
                    ss = Sc[f0]; avg = (sum(Ll[q] for q in seq) + Ll[i] + ci) / (len(seq) + 2)
                    contain = Hl[i] < Hl[f0] and ci < Cl[f0]
                    otm0 = bool(np.isfinite(ss) and ((strike > ss) if side == "C" else (strike < ss)))
                    sv = ss / avg if avg > 0 and np.isfinite(ss) else 0
                    r.update(sigval=sv, contain=bool(contain), otm0=otm0, is_sq=bool(contain and otm0 and sv >= 1000))
                if not (otm[i] or r.get("otm0")): continue
            out.append(r)
    return out

def job(args):
    asset, expiry = args; S = spot(asset)
    exp_ts = int(pd.Timestamp(expiry + " 12:00", tz="UTC").timestamp()); rows = []
    for f in glob.glob(f"data/candles/{asset}/{expiry}/60/*.json"): rows += contract(f, asset, exp_ts, S)
    if not rows: return None
    D = pd.DataFrame(rows); D["expiry"] = expiry
    for col in D.columns:
        if D[col].dtype == np.float64: D[col] = D[col].astype(np.float32)
    return D

def build(only=None):
    os.makedirs(OUT, exist_ok=True)
    jobs = [(a, e) for a in ("BTC", "ETH") for e in sorted(os.listdir(f"data/candles/{a}")) if os.path.isdir(f"data/candles/{a}/{e}/60")]
    if only: jobs = [j for j in jobs if j[1] in only]
    print(f"{len(jobs)} expiry dirs", flush=True); buf = []; part = 0; n = 0
    def flush():
        nonlocal buf, part
        if buf:
            pd.concat(buf, ignore_index=True).to_parquet(f"{OUT}/part-{part:04d}.parquet"); part += 1; buf = []
    with Pool(4) as p:
        for k, D in enumerate(p.imap_unordered(job, jobs, chunksize=4)):
            if D is not None: buf.append(D); n += len(D)
            if (k + 1) % 100 == 0: flush(); print(f"  {k + 1}/{len(jobs)} dirs, {n:,} rows", flush=True)
    flush(); print(f"wrote {n:,} rows in {part} parts")

if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]: build(set(sys.argv[2:]) or None)

# ───────────────────────── analysis ─────────────────────────
# Definitions fixed BEFORE looking at outcomes (11 Nov 2026):
#   PAR   both-bounded parabola: arc >= 5 bars, quadratics through highs AND lows both convex (a > 0), both R2 >= 0.9
#   NCT   not counter-trend: spot did not move against the option by more than 0.5 sigma over the pattern (z_pat >= -0.5)
#   CT    counter-trend: z_pat < -1
#   LTF   an otm_wall or green_stairs fired on <= 60m on the same strike during the trigger bar
#   WT    with-trend: spot moved the option's way by > 0.5 sigma over the previous 20 bars
#   QUIET 7d realised vol below 0.8 x the 30d
# Primary outcome: later high >= 25x entry (MARK). Also 10x / 100x, and value kept: 25 if 25x else min(x_end, 25).
COST = 0.0826; HTF = (360, 480, 720, 1440, 10080); SPLIT = "2026-01-01"

def load():
    D = pd.concat((pd.read_parquet(f) for f in sorted(glob.glob(f"{OUT}/part-*.parquet"))), ignore_index=True)
    D["is_sq"] = D.is_sq.eq(True)
    for K in (5, 10, 25, 100): D[f"h{K}"] = D.x_max >= K
    D["v25"] = np.where(D.h25, 25, np.minimum(D.x_end, 25))
    D["ev"] = D.asset + D.side + D.expiry + D.tf.astype(str) + "_" + D.t_close.astype(str)
    D["PAR"] = (D.arc_len >= 5) & (D.a_hi > 0) & (D.a_lo > 0) & (D.r2_hi >= 0.9) & (D.r2_lo >= 0.9)
    D["PARLOG"] = (D.arc_len >= 5) & (D.a_lhi > 0) & (D.a_llo > 0) & (D.r2_lhi >= 0.9) & (D.r2_llo >= 0.9)
    D["NCT"] = D.z_pat >= -0.5; D["CT"] = D.z_pat < -1
    D["WT"] = D.trend20 > 0.5; D["QUIET"] = D.quiet < 0.8
    D["floor"] = D.entry >= np.where(D.asset == "BTC", 2.0, 0.2)
    D["st"] = (D.asset + D.side + pd.cut(D.tte_h, [0, 12, 36, 72, 168, 400, 1e5], labels=False).astype(str)
               + pd.cut(D.mny, [-1e3, 0, 2, 5, 10, 20, 1e3], labels=False).astype(str)
               + pd.cut(np.log10(D.cheap), [0, 3, 3.5, 4, 5, 9], labels=False).astype(str))
    return D

def ltf(D):
    """otm_wall / green_stairs on <= 60m, same strike, trigger candle closing inside the HTF trigger bar"""
    E = pd.concat([pd.read_parquet("events.parquet", columns=["signal", "symbol", "duration", "entry_ts"]),
                   pd.read_parquet("data/events_lowtf.parquet", columns=["signal", "symbol", "duration", "entry_ts"])])
    E = E[E.signal.isin(["otm_wall", "green_stairs"]) & (E.duration <= 60)]
    E["tc"] = E.entry_ts + E.duration * 60
    T = {s: np.sort(g.tc.values) for s, g in E.groupby("symbol")}
    n = np.zeros(len(D), int)
    for s, ix in D.groupby("sym").indices.items():
        if s not in T: continue
        t = T[s]; hi = D.t_close.values[ix]; lo = hi - D.tf.values[ix] * 60
        n[ix] = np.searchsorted(t, hi, "right") - np.searchsorted(t, lo, "right")
    D["LTF"] = n > 0
    return D

def rates(g):
    return dict(n=len(g), ev=g.ev.nunique(), exp=g.expiry.nunique(), h5=g.h5.mean() * 100, h10=g.h10.mean() * 100,
                h25=g.h25.mean() * 100, h100=g.h100.mean() * 100, v25=g.v25.mean())

def matched(A, B, col="h25", nboot=1000, seed=0):
    """mean(col) in A minus mean in B reweighted to A's strata; 95% CI resampling expiry dates (BTC and ETH together)"""
    k = np.intersect1d(A.st.unique(), B.st.unique()); A = A[A.st.isin(k)]; B = B[B.st.isin(k)]
    if len(A) < 30 or len(B) < 30: return None
    u = np.union1d(A.expiry.unique(), B.expiry.unique()); ei = {e: i for i, e in enumerate(u)}; si = {s_: i for i, s_ in enumerate(k)}
    def tab(X):
        n = np.zeros((len(u), len(k))); s_ = np.zeros_like(n)
        e = X.expiry.map(ei).values; t = X.st.map(si).values
        np.add.at(n, (e, t), 1); np.add.at(s_, (e, t), X[col].values.astype(float)); return n, s_
    nA, sA = tab(A); nB, sB = tab(B)
    def diff(W):
        a_n, a_s, b_n, b_s = W @ nA, W @ sA, W @ nB, W @ sB
        okm = (a_n > 0) & (b_n > 0); a_n = a_n * okm
        ma = (a_s * okm).sum(1) / a_n.sum(1); mb = (a_n * np.where(okm, b_s / np.where(b_n > 0, b_n, 1), 0)).sum(1) / a_n.sum(1)
        return ma, mb
    ma, mb = diff(np.ones((1, len(u))))
    W = np.random.default_rng(seed).multinomial(len(u), np.ones(len(u)) / len(u), nboot).astype(float)
    ba, bb = diff(W); lo, hi = np.nanpercentile(ba - bb, [2.5, 97.5])
    return ma[0], mb[0], ma[0] - mb[0], lo, hi, len(A), len(B)

def show(name, m, pct=True):
    if m is None: print(f"  {name:<44} too few"); return
    k = 100 if pct else 1
    print(f"  {name:<44} {m[0] * k:6.2f} vs {m[1] * k:6.2f}  diff {m[2] * k:+6.2f} [{m[3] * k:+.2f}, {m[4] * k:+.2f}]  n {m[5]:,} / {m[6]:,}")

def analyse():
    pd.set_option("display.width", 220)
    D = ltf(load()); G = D[D.kind == "g"]; R = D[D.kind == "r"]
    print(f"rows {len(D):,}; green-after-red {len(G):,}; squeeze rows {G.is_sq.sum():,}; expiries {D.expiry.nunique()}")
    print("\n=== 1. the squeeze by timeframe (all rows; MARK) ===")
    print(pd.DataFrame({tf: rates(g) for tf, g in G[G.is_sq].groupby("tf")}).T.round(2).to_string())
    print("\n=== 2. squeeze vs the same kind of option without it (matched on asset x side x tte x moneyness x cheapness) ===")
    for tf in TFS:
        A = G[G.is_sq & (G.tf == tf)]
        for col in ("h10", "h25", "h100"):
            show(f"tf {tf} {col}: squeeze vs other green-after-red", matched(A, G[~G.is_sq & (G.tf == tf)], col))
            show(f"tf {tf} {col}: squeeze vs random bar", matched(A, R[R.tf == tf], col))
    H = G[G.is_sq & G.tf.isin(HTF)]
    print(f"\n=== 3. his conditions inside the 6h+ squeeze ({len(H):,} rows, {H.ev.nunique():,} events, {H.expiry.nunique()} expiries) ===")
    for c in ("PAR", "PARLOG", "hi_par", "lo_par", "NCT", "CT", "LTF", "WT", "QUIET", "held3", "opp_big"):
        m = H[c].eq(True)
        print(f" {c}: on {m.mean():.0%}")
        for col in ("h10", "h25", "h100"): show(f"   {col} on vs off (matched)", matched(H[m], H[~m], col))
        show("   value kept (v25) on vs off", matched(H[m], H[~m], "v25"), pct=False)
        for nm, sub in (("≤2025", H[H.expiry < SPLIT]), ("2026", H[H.expiry >= SPLIT]), ("floor", H[H.floor])):
            mm = sub[c].eq(True); show(f"   h25 {nm}", matched(sub[mm], sub[~mm], "h25"))
    print("\n=== 4. the stack ===")
    for nm, m in (("squeeze 6h+", H.is_sq), ("+ NCT", H.NCT), ("+ PAR", H.PAR), ("+ PAR + NCT", H.PAR & H.NCT),
                  ("+ PAR + NCT + LTF", H.PAR & H.NCT & H.LTF), ("+ PAR + NCT + WT", H.PAR & H.NCT & H.WT),
                  ("+ PAR + NCT + QUIET", H.PAR & H.NCT & H.QUIET), ("+ CT (his 'false flat')", H.CT)):
        for lab, sub in (("all", H[m]), ("floor", H[m & H.floor])):
            r = rates(sub); print(f"  {nm:<28} {lab:<6} n {r['n']:>6,} ev {r['ev']:>5,} exp {r['exp']:>4}  5x {r['h5']:5.1f}  10x {r['h10']:5.1f}  25x {r['h25']:5.2f}  100x {r['h100']:5.2f}  v25 {r['v25']:.3f}")
    print("\n=== 5. by timeframe x conditions (25x %, rows / events) ===")
    for tf in HTF:
        h = H[H.tf == tf]
        print(f"  tf {tf:>5}: " + " | ".join(f"{nm} {s.h25.mean() * 100:5.2f} ({len(s)}/{s.ev.nunique()})" for nm, s in
              (("all", h), ("NCT", h[h.NCT]), ("PAR", h[h.PAR]), ("PAR+NCT", h[h.PAR & h.NCT]), ("CT", h[h.CT]))))

def context():
    """Is the context lift specific to the squeeze, or does any cheap OTM option get it? And the hold, entered causally."""
    D = load(); D = D[D.tf.isin(HTF)]
    D["mon"] = D.expiry.str[:7]
    pops = (("squeeze", D[(D.kind == "g") & D.is_sq]), ("green after >=3 reds, no squeeze", D[(D.kind == "g") & ~D.is_sq & (D.n_red >= 3)]),
            ("green after 1-2 reds", D[(D.kind == "g") & (D.n_red < 3)]), ("random bar", D[D.kind == "r"]))
    print("=== context on vs off, per population (6h-1w), matched; 25x and 100x ===")
    for c in ("NCT", "CT", "WT", "QUIET", "opp_big"):
        print(f" {c}")
        for nm, P in pops:
            if c in ("NCT", "CT") and nm == "random bar": continue
            m = P[c].eq(True) if c != "NCT" else P.NCT & P.z_pat.notna()
            off = ~m & P.z_pat.notna() if c in ("NCT", "CT") else ~m
            show(f"   {nm[:30]} h25", matched(P[m], P[off], "h25")); show(f"   {nm[:30]} h100", matched(P[m], P[off], "h100"))
    print("\n=== the stack, per population: NCT + WT, NCT + QUIET, WT + QUIET (rates, rows/events/expiries) ===")
    for nm, P in pops:
        for lab, m in (("all", P.h25 > -1), ("WT", P.WT), ("QUIET", P.QUIET), ("WT+QUIET", P.WT & P.QUIET), ("NCT+WT", P.NCT & P.WT),
                       ("NCT+QUIET", P.NCT & P.QUIET), ("NCT+WT+QUIET", P.NCT & P.WT & P.QUIET)):
            r = rates(P[m]); print(f"  {nm[:30]:<32} {lab:<13} n {r['n']:>7,} ev {r['ev']:>6,} exp {r['exp']:>4}  10x {r['h10']:5.1f}  25x {r['h25']:5.2f}  100x {r['h100']:5.2f}  v25 {r['v25']:.3f}")
    S = pops[0][1]
    print("\n=== squeeze: by year and by side ===")
    for lab, m in (("all", S.h25 > -1), ("NCT", S.NCT), ("CT", S.CT), ("NCT+WT", S.NCT & S.WT), ("NCT+QUIET", S.NCT & S.QUIET)):
        print(f"  {lab:<10} " + " | ".join(f"{y} {g.h25.mean() * 100:5.2f}/{g.h100.mean() * 100:4.2f} ({len(g)},{g.expiry.nunique()}e)" for y, g in S[m].groupby(S.expiry.str[:4]))
              + " || " + " | ".join(f"{k} {g.h25.mean() * 100:5.2f}/{g.h100.mean() * 100:4.2f}" for k, g in S[m].groupby("side")))
    print("\n=== squeeze: the wait-and-hold entered causally (buy at the close of bar 3 if no low under the trigger low) ===")
    W = S[S.held3.notna()].copy(); W["hw25"] = W.xw_max >= 25; W["hw100"] = W.xw_max >= 100
    W["vw25"] = np.where(W.hw25, 25, np.minimum(W.xw_end, 25)); h = W.held3.eq(True)
    print(f"  rows with 3 later bars {len(W):,}; held {h.mean():.0%}; already doubled in the wait {W.ran3.eq(True).mean():.0%}")
    print(f"  buy now (all): 25x {W.h25.mean():.2%} 100x {W.h100.mean():.2%} value {W.v25.mean():.3f}")
    print(f"  held, buy after the wait: 25x {W[h].hw25.mean():.2%} 100x {W[h].hw100.mean():.2%} value {W[h].vw25.mean():.3f} (n {h.sum():,})")
    print(f"  broke, buy after the wait: 25x {W[~h].hw25.mean():.2%} 100x {W[~h].hw100.mean():.2%} value {W[~h].vw25.mean():.3f}")
    print("\n=== month-block bootstrap of the two headline contrasts (squeeze rows) ===")
    S2 = S.assign(expiry=S.mon)
    for c in ("NCT", "WT", "QUIET"):
        m = S2[c].eq(True)
        for col in ("h25", "h100"): show(f"  {c} {col} (months)", matched(S2[m], S2[~m], col))

FEATS = dict(
    base=["asset_c", "side_c", "tf", "tte_h", "mny", "lcheap"],
    context=["quiet", "trend20", "z_arc", "depth", "arc_len", "opp_big_f"],
    pattern=["kind_g", "n_red", "n_dec", "is_sq_f", "sigval", "contain_f", "ratio1", "ratio2", "hi_par_f", "lo_par_f", "a_hi", "r2_hi", "vx_hi",
             "a_lo", "r2_lo", "vx_lo", "a_lhi", "r2_lhi", "a_llo", "r2_llo", "z_pat", "z_pre", "fav_pat", "pat_h"])

def ml(target="h25"):
    """Walk-forward gradient boosting: does anything beyond tte/moneyness/cheapness rank the 6h+ moments?
    Train only on rows whose contract expired before the test block starts; test on triggers inside the block."""
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    D = load(); D = D[D.tf.isin(HTF)].copy()
    D["asset_c"] = (D.asset == "BTC").astype(int); D["side_c"] = (D.side == "C").astype(int); D["lcheap"] = np.log10(D.cheap)
    D["kind_g"] = (D.kind == "g").astype(int)
    for c in ("opp_big", "is_sq", "contain", "hi_par", "lo_par"): D[c + "_f"] = D[c].eq(True).astype(float)
    D["exp_ts"] = (pd.to_datetime(D.expiry).astype("int64") // 10**9 + 43200)
    cuts = [pd.Timestamp(x, tz="UTC").timestamp() for x in ("2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01", "2026-12-01")]
    sets = (("base", FEATS["base"]), ("base+context", FEATS["base"] + FEATS["context"]), ("all", FEATS["base"] + FEATS["context"] + FEATS["pattern"]))
    P = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        tr = D[D.exp_ts < a]; te = D[(D.t_close >= a) & (D.t_close < b)].copy()
        for nm, f in sets:
            m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.7,
                                   subsample_freq=1, colsample_bytree=0.7, verbose=-1, random_state=0)
            m.fit(tr[f], tr[target]); te["p_" + nm] = m.predict_proba(te[f])[:, 1]
            if nm == "all": imp = pd.Series(m.booster_.feature_importance("gain"), f).sort_values(ascending=False)
        te["fold"] = pd.Timestamp(a, unit="s").strftime("%Y-%m"); P.append(te)
        print(f"fold {te.fold.iloc[0]}: train {len(tr):,} test {len(te):,} base rate {te[target].mean():.2%}  " +
              "  ".join(f"{nm} AUC {roc_auc_score(te[target], te['p_' + nm]):.3f}" for nm, _ in sets), flush=True)
    P = pd.concat(P); print("last-fold gain importance:", ", ".join(f"{k} {v / imp.sum():.0%}" for k, v in imp.head(12).items()))
    print(f"\npooled out-of-sample, {len(P):,} rows, base {target} {P[target].mean():.2%}, 100x {P.h100.mean():.2%}")
    for nm, _ in sets:
        s = P["p_" + nm]; print(f" {nm}: AUC {roc_auc_score(P[target], s):.3f}")
        for q in (0.10, 0.05, 0.01, 0.002):
            thr = P.groupby("fold")[s.name].transform(lambda x: x.quantile(1 - q)); t = P[s >= thr]
            print(f"   top {q:.1%}: n {len(t):>6,} ev {t.ev.nunique():>5,} exp {t.expiry.nunique():>4}  10x {t.h10.mean():6.2%}  25x {t.h25.mean():6.2%}  100x {t.h100.mean():6.2%}  "
                  f"value {t.v25.mean():.2f}  floor-only 25x {t[t.floor].h25.mean():6.2%}  months with a hit {t[t.h25].expiry.str[:7].nunique()}/{t.expiry.str[:7].nunique()}")
    P[["asset", "sym", "side", "tf", "kind", "t_close", "expiry", "entry", "x_max", "x_end", "is_sq", "fold", "p_base", "p_base+context", "p_all"]].to_parquet("data/htf_squeeze_ml.parquet")

def staged():
    """His smaller-timeframe point: an otm_wall / green_stairs on <= 60m that FOLLOWS a 6h+ squeeze on the same strike
    (trigger candle closing within one higher-timeframe bar after the squeeze closes) vs the same signals elsewhere.
    Outcome from the low-timeframe trigger close (events.parquet peak_vs_close), same OTM + cheap universe."""
    c = ["signal", "spot", "expiry", "duration", "symbol", "opt_type", "entry_ts", "entry_premium", "spot_at_entry", "moneyness_pct", "peak_vs_close"]
    E = pd.concat([pd.read_parquet("events.parquet", columns=c), pd.read_parquet("data/events_lowtf.parquet", columns=c)], ignore_index=True)
    E = E[E.signal.isin(["otm_wall", "green_stairs"]) & (E.duration <= 60) & E.spot.isin(["BTC", "ETH"])].copy()
    E["tc"] = E.entry_ts + E.duration * 60; E["mny"] = np.where(E.opt_type == "C", 1, -1) * E.moneyness_pct
    E["cheap"] = E.spot_at_entry / E.entry_premium
    E["tte_h"] = (pd.to_datetime(E.expiry).astype("int64") // 10**9 + 43200 - E.tc) / 3600
    E = E[(E.mny > 0) & (E.cheap >= CHEAP) & (E.tte_h >= MIN_TTE_H) & np.isfinite(E.cheap)].copy()
    E["st"] = (E.spot + E.opt_type + pd.cut(E.tte_h, [0, 12, 36, 72, 168, 400, 1e5], labels=False).astype(str)
               + pd.cut(E.mny, [-1e3, 0, 2, 5, 10, 20, 1e3], labels=False).astype(str)
               + pd.cut(np.log10(E.cheap), [0, 3, 3.5, 4, 5, 9], labels=False).astype(str) + (E.duration > 20).astype(str))
    for K in (5, 10, 25, 100): E[f"h{K}"] = E.peak_vs_close >= K
    D = load(); S = D[(D.kind == "g") & D.is_sq & D.tf.isin(HTF)]
    def mark(S, name):
        f = np.zeros(len(E), bool); gi = E.groupby("symbol").indices
        for (sym, tf), g in S.groupby(["sym", "tf"]):
            if sym not in gi: continue
            ix = gi[sym]; t = np.sort(g.t_close.values); tc = E.tc.values[ix]; j = np.searchsorted(t, tc, "left") - 1
            f[ix] |= (j >= 0) & (tc - t[np.maximum(j, 0)] <= tf * 60)
        E[name] = f
    mark(S, "F"); mark(S[S.NCT], "F_nct"); mark(S[S.NCT & S.QUIET], "F_nq"); mark(S[S.tf >= 720], "F_12")
    print(f"low-timeframe wall/stairs on cheap OTM options: {len(E):,} rows, {E.expiry.nunique()} expiries; following a 6h+ squeeze {E.F.mean():.1%}")
    for nm in ("F", "F_nct", "F_nq", "F_12"):
        A, B = E[E[nm]], E[~E.F]
        print(f" {nm}: n {len(A):,} exp {A.expiry.nunique()}  10x {A.h10.mean():.2%} 25x {A.h25.mean():.2%} 100x {A.h100.mean():.2%} | others 10x {B.h10.mean():.2%} 25x {B.h25.mean():.2%} 100x {B.h100.mean():.2%}")
        for col in ("h10", "h25", "h100"): show(f"   {nm} vs no squeeze before, {col}", matched(A, B, col))
    for sg in ("otm_wall", "green_stairs"):
        G = E[E.signal == sg]; show(f" {sg} only: after squeeze vs not, h25", matched(G[G.F], G[~G.F], "h25"))

def ladder(nsim=20000, seed=0):
    """His ladder as I read it: stake 2k for 10x (20k); then 4k for 20x (80k); 16k for 20x (320k); 80k for 20x (1.6m).
    A miss returns what the option is worth at expiry. Rungs 2-4 are funded only from the previous win; when that
    runs out, back to rung 1 with fresh 2k stakes. Trades are drawn at random from the population's real outcomes."""
    D = load(); D = D[D.tf.isin(HTF)]; S = D[(D.kind == "g") & D.is_sq]
    print("=== months with at least one hit (6h+ squeeze, BTC; event = one firing, any strike) ===")
    B = S[S.asset == "BTC"].assign(mon=pd.to_datetime(S.t_close, unit="s").dt.strftime("%Y-%m"))
    for lab, P in (("all strikes", B), ("entry >= $2", B[B.floor])):
        e = P.groupby(["mon", "ev"]).agg(h25=("h25", "max"), h100=("h100", "max")).reset_index().groupby("mon").agg(ev=("ev", "size"), h25=("h25", "sum"), h100=("h100", "sum"))
        print(f"  {lab}: months {len(e)}; firings/month median {e.ev.median():.0f}; months with a 25x {(e.h25 > 0).sum()} ({(e.h25 > 0).mean():.0%}), "
              f"with a 100x {(e.h100 > 0).sum()} ({(e.h100 > 0).mean():.0%}); paying firings/month median {e.h25.median():.0f} (25x), {e.h100.median():.0f} (100x)")
    R = ((2, 10), (4, 20), (16, 20), (80, 20)); rng = np.random.default_rng(seed)
    print("\n=== the ladder (stakes in thousand rupees; costs 8.26% per stake) ===")
    for lab, P in (("squeeze 6h+, all", S), ("squeeze, not counter-trend", S[S.NCT]), ("squeeze NCT + quiet", S[S.NCT & S.QUIET]), ("squeeze NCT + with-trend", S[S.NCT & S.WT]),
                   ("squeeze NCT + quiet, floor", S[S.NCT & S.QUIET & S.floor]), ("random bar, quiet", D[(D.kind == "r") & D.QUIET]), ("random bar", D[D.kind == "r"])):
        xm, xe = P.x_max.values, np.nan_to_num(P.x_end.values); fresh = out = tops = trades = 0.0; first = []
        for _ in range(nsim // 20):
            rung, bank, n = 0, 0.0, 0
            for _ in range(400):                                   # ~ one campaign of up to 400 trades
                st, tg = R[rung]; i = rng.integers(len(xm)); n += 1
                if rung == 0: fresh += st * (1 + COST)
                else: bank -= st * (1 + COST)
                if xm[i] >= tg:
                    bank += st * tg
                    if rung == 3: out += bank; tops += 1; first.append(n); break
                    rung += 1
                else:
                    bank += st * min(xe[i], tg)
                    if rung and bank < R[rung][0] * (1 + COST): out += bank; rung, bank = 0, 0.0
            else: out += bank
            trades += n
        c = nsim // 20
        print(f"  {lab:<28} hit 10x {np.mean(xm >= 10):5.1%} 20x {np.mean(xm >= 20):5.1%} | campaigns reaching 1.6m within 400 trades {tops / c:5.1%}"
              f" (median {np.median(first) if first else float('nan'):.0f} trades) | fresh money in {fresh / c:7.0f}k, money out {out / c:7.0f}k per campaign, ratio {out / fresh:.2f}")

def traded(n=3000):
    """With-trend vs counter-trend on TRADED prices. Sample of green-after-red bars (6h+, entry above the floor):
    trend20 > 0.5 vs trend20 < -1. fill = the first traded 1h close after the bar closed (within 6h, else no fill);
    hit = a later traded high >= K x fill. Value at expiry uses the final mark (= settlement) over the fill.
    Writes data/htf_squeeze_traded.parquet."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    API = "https://api.india.delta.exchange/v2/history/candles"
    D = load(); D = D[D.tf.isin(HTF) & (D.kind == "g") & D.floor & D.trend20.notna()]
    S = pd.concat([D[D.trend20 > 0.5].sample(n, random_state=0), D[D.trend20 < -1].sample(n, random_state=0)]).reset_index(drop=True)
    def one(r):
        settle = int(pd.Timestamp(r.expiry).timestamp()) + 43200; cs = None
        for k in range(4):
            try:
                with urllib.request.urlopen(f"{API}?symbol={r.sym}&resolution=1h&start={int(r.t_close)}&end={settle}", timeout=40) as f:
                    cs = json.load(f).get("result") or []
                break
            except Exception: time.sleep(1 + 2 * k)
        if cs is None: return (np.nan, np.nan, -1)
        cs = sorted((c for c in cs if (c.get("volume") or 0) > 0 and int(c["time"]) >= int(r.t_close)), key=lambda c: int(c["time"]))
        if not cs or int(cs[0]["time"]) > r.t_close + 6 * 3600: return (np.nan, np.nan, len(cs))
        fill = float(cs[0]["close"]); return (fill, max([float(c["high"]) for c in cs[1:]] or [fill]), len(cs))
    with ThreadPoolExecutor(max_workers=8) as ex: res = list(ex.map(one, S.itertuples()))
    S["fill"], S["thigh"], S["nbars"] = zip(*res)
    S.to_parquet("data/htf_squeeze_traded.parquet"); print(f"wrote {len(S):,}; api failures {(S.nbars < 0).sum()}")

def traded_show():
    S = pd.read_parquet("data/htf_squeeze_traded.parquet"); S = S[S.nbars >= 0].copy(); S["grp"] = np.where(S.trend20 > 0.5, "with-trend", "counter-trend")
    S["got"] = S.fill.notna(); S["xt"] = S.thigh / S.fill
    for K in (5, 10, 25, 100): S[f"t{K}"] = (S.xt >= K) & S.got
    S["vt25"] = np.where(S.t25, 25, np.minimum(S.x_end * S.entry / S.fill, 25))
    for g, P in S.groupby("grp"):
        F = P[P.got]
        print(f"{g:<14} n {len(P):,} exp {P.expiry.nunique()}  fill within 6h {P.got.mean():.0%}  fill/mark median {(F.fill / F.entry).median():.2f} | "
              f"MARK 10x {P.h10.mean():.2%} 25x {P.h25.mean():.2%} 100x {P.h100.mean():.2%} value {P.v25.mean():.2f} | "
              f"TRADED (filled rows) 10x {F.t10.mean():.2%} 25x {F.t25.mean():.2%} 100x {F.t100.mean():.2%} value {F.vt25.mean():.2f}; mark on the same rows 25x {F.h25.mean():.2%}")
    A, B = S[(S.grp == "with-trend") & S.got], S[(S.grp == "counter-trend") & S.got]
    for col in ("t5", "t10", "t25", "t100", "vt25", "h25"): show(f"  with vs counter, {col}", matched(A, B, col), pct=col != "vt25")
    for nm, m in (("squeeze rows only", S.is_sq), ("<=2025", S.expiry < SPLIT), ("2026", S.expiry >= SPLIT)):
        for col in ("t10", "t25", "vt25"): show(f"  {nm}: with vs counter, {col}", matched(A[m.reindex(A.index)], B[m.reindex(B.index)], col), pct=col != "vt25")

def robust():
    """How solid are QUIET and the trend effect: dose-response, by year, concentration, floor; then with-trend
    (>0.5) vs counter-trend (<-1) by side, asset, timeframe, time left and year."""
    D = load(); D = D[D.tf.isin(HTF)].copy(); D["yr"] = D.expiry.str[:4]; D["mon"] = D.expiry.str[:7]
    R = D[D.kind == "r"]; S = D[(D.kind == "g") & D.is_sq]; G = D[D.kind == "g"]
    print("=== dose-response: quiet ratio (7d vol / 30d vol), random bars and all green-after-red bars ===")
    for nm, P in (("random", R), ("green-after-red", G)):
        P = P[P.quiet.notna()]; b = pd.cut(P.quiet, [0, .6, .8, 1, 1.25, 9])
        t = P.groupby(b, observed=True).agg(n=("h25", "size"), exp=("expiry", "nunique"), h10=("h10", "mean"), h25=("h25", "mean"), h100=("h100", "mean"), v25=("v25", "mean"))
        print(nm); print((t.assign(h10=t.h10 * 100, h25=t.h25 * 100, h100=t.h100 * 100)).round(2).to_string())
        print(" by year, 25x/100x:"); print(P.groupby([b, "yr"], observed=True).apply(lambda g: f"{g.h25.mean()*100:.2f}/{g.h100.mean()*100:.2f} ({g.expiry.nunique()}e)").unstack().to_string())
    print("\n=== dose-response: trend20 (in the option's direction) ===")
    for nm, P in (("random", R), ("green-after-red", G)):
        P = P[P.trend20.notna()]; b = pd.cut(P.trend20, [-9, -1, -.5, 0, .5, 1, 9])
        t = P.groupby(b, observed=True).agg(n=("h25", "size"), h10=("h10", "mean"), h25=("h25", "mean"), h100=("h100", "mean"), v25=("v25", "mean"))
        print(nm); print((t.assign(h10=t.h10 * 100, h25=t.h25 * 100, h100=t.h100 * 100)).round(2).to_string())
        print(" by year, 25x/100x:"); print(P.groupby([b, "yr"], observed=True).apply(lambda g: f"{g.h25.mean()*100:.2f}/{g.h100.mean()*100:.2f}").unstack().to_string())
    print("\n=== concentration of the hits (squeeze, NCT + QUIET; and NCT + WT) ===")
    for lab, P in (("NCT+QUIET", S[S.NCT & S.QUIET]), ("NCT+WT", S[S.NCT & S.WT]), ("all squeeze", S)):
        for col in ("h25", "h100"):
            h = P[P[col]]; m = h.groupby("mon").size().sort_values(ascending=False); e = h.groupby("expiry").size().sort_values(ascending=False)
            print(f"  {lab} {col}: {len(h)} hit rows, {h.ev.nunique()} firings, {h.expiry.nunique()} expiries, {h.mon.nunique()} months; top 3 months hold {m.head(3).sum() / max(len(h), 1):.0%} ({', '.join(m.head(3).index)}); top expiry {e.iloc[0] / len(h):.0%}")
    print("\n=== quiet / with-trend, matched, by period, pooled over ALL bars (random + green-after-red) ===")
    A = D[D.quiet.notna() & D.trend20.notna()]
    for per, P in (("<=2025", A[A.expiry < "2026-01-01"]), ("2026", A[A.expiry >= "2026-01-01"]), ("2024", A[A.yr == "2024"]), ("2025", A[A.yr == "2025"])):
        for c in ("QUIET", "WT"):
            for col in ("h25", "h100", "v25"): show(f"  {per} {c} {col}", matched(P[P[c]], P[~P[c]], col), pct=col != "v25")
    print("\n=== floor only (entry >= $2 BTC / $0.2 ETH), all bars ===")
    F = A[A.floor]
    for c in ("QUIET", "WT"):
        for col in ("h10", "h25", "h100", "v25"): show(f"  {c} {col}", matched(F[F[c]], F[~F[c]], col), pct=col != "v25")
    show("  QUIET & WT vs neither, h25", matched(F[F.QUIET & F.WT], F[~F.QUIET & ~F.WT], "h25"))
    D = D[D.trend20.notna()].copy()
    D["tb"] = pd.cut(D.trend20, [-9, -1, 0, .5, 9], labels=["against<-1", "-1..0", "0..0.5", "with>0.5"])
    print("=== trend bucket by side / asset / timeframe / time left: 25x / 100x / value kept (all bars 6h+) ===")
    for by in ("side", "asset", "tf", pd.cut(D.tte_h, [0, 24, 72, 168, 1e5], labels=["<1d", "1-3d", "3-7d", ">7d"]), "floor"):
        t = D.groupby([by, "tb"], observed=True).apply(lambda g: f"{g.h25.mean()*100:5.2f}/{g.h100.mean()*100:4.2f}/{g.v25.mean():.2f} ({len(g)//1000}k,{g.expiry.nunique()}e)").unstack()
        print(t.to_string(), "\n")
    W, C = D[D.trend20 > 0.5], D[D.trend20 < -1]
    print("=== with-trend vs counter-trend (>0.5 vs <-1), matched ===")
    for lab, m in (("all", D.h25 > -1), ("calls", D.side == "C"), ("puts", D.side == "P"), ("BTC", D.asset == "BTC"), ("ETH", D.asset == "ETH"),
                   ("2024", D.yr == "2024"), ("2025", D.yr == "2025"), ("2026", D.yr == "2026"), ("floor", D.floor), ("tte>=24h", D.tte_h >= 24), ("squeeze", D.is_sq)):
        for col in ("h25", "h100", "v25"): show(f"  {lab} {col}", matched(W[m.reindex(W.index)], C[m.reindex(C.index)], col), pct=col != "v25")
    print("\n=== with-trend: value kept by year x side, with floor (mark; cost 0.0826 not taken) ===")
    F = D[D.floor & (D.trend20 > 0.5)]
    print(F.groupby(["yr", "side"]).apply(lambda g: f"n {len(g):,} exp {g.expiry.nunique()} 25x {g.h25.mean()*100:.2f} v25 {g.v25.mean():.2f} top-expiry share of value {g.groupby('expiry').v25.sum().max() / g.v25.sum():.0%}").to_string())

if __name__ == "__main__" and sys.argv[1:2] != ["build"]:
    {"context": context, "ml": ml, "staged": staged, "ladder": ladder, "traded": traded, "traded_show": traded_show, "robust": robust}.get(sys.argv[1] if len(sys.argv) > 1 else "", analyse)()
