"""His 1-minute scalping idea (2026-10-13): after a 1m candle closes, does price rise +1% (or +2%) before it
falls 0.25% from that close? And a "quick" version: the target must be reached within a short window.
"Earn Rs 1k a thousand times." Data: Delta BTCUSD / ETHUSD TRADED perp 1m candles with volume.

Labels (from the close c_i, scanning bars i+1 onwards, first passage on highs/lows):
  L1  +1% before -0.25%, within 1 day (otherwise timeout)    L2  same with +2%
  Q1  +1% before -0.25%, within 30 min                       Q2  +2% before -0.25%, within 60 min
  A bar touching both levels counts as the STOP (1m bars cannot tell the order).
Features (known at the close of bar i): the last 25 candles (returns, ranges, wicks, volume, each
normalised by the trailing day), plus 5m-1d returns, volatility regime, distance from recent highs/lows,
volume regime, hour, weekday. LightGBM, pooled BTC + ETH, monthly walk-forward (expanding, >= 8 months),
1-day embargo, trained on every 5th minute.
Trading simulation (out of sample, non-overlapping, one position per asset): buy at the NEXT bar's open;
TP by limit (maker 0.02% + GST), stop and timeout by market (taker 0.05% + GST) plus 0.01% stop slippage, and
a stop gapped through fills at that bar's open. Threshold: the top q of the TRAINING scores (causal).
"""
import numpy as np, pandas as pd, lightgbm as lgb, sys, warnings
warnings.filterwarnings("ignore")
TAKER, MAKER, SLIP = 0.0005 * 1.18, 0.0002 * 1.18, 0.0001
CFG = {"L1": (0.01, 0.0025, 1440), "L2": (0.02, 0.0025, 1440), "Q1": (0.01, 0.0025, 30), "Q2": (0.02, 0.0025, 60)}

def sparse(a, fn, K):
    st = [a]
    for k in range(1, K + 1):
        p = st[-1]; s = 1 << (k - 1); q = p.copy(); q[:-s] = fn(p[:-s], p[s:]); st.append(q)
    return st
def first_cross(st, thr, i, H, up):
    """first j in (i, i+H] with h_j >= thr (up) or l_j <= thr (down); n (=none) if never. Binary lifting."""
    n = len(st[0]); lim = np.minimum(i + H, n - 1); pos = i.copy()
    for k in range(len(st) - 1, -1, -1):
        cand = pos + 1; ok = cand + (1 << k) - 1 <= lim
        v = st[k][np.minimum(cand, n - 1)]
        safe = (v < thr) if up else (v > thr)
        pos = np.where(ok & safe, pos + (1 << k), pos)
    j = pos + 1; jj = np.minimum(j, n - 1)
    hit = (j <= lim) & ((st[0][jj] >= thr) if up else (st[0][jj] <= thr))
    return np.where(hit, j, n)

def load(sym):
    d = pd.read_parquet(f"data/{sym}_1m.parquet").sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    full = pd.DataFrame({"ts": np.arange(d.ts.iloc[0], d.ts.iloc[-1] + 60, 60)})        # regular grid; gaps = flat, zero volume
    d = full.merge(d, on="ts", how="left"); d["c"] = d.c.ffill()
    for k in ("o", "h", "l"): d[k] = d[k].fillna(d.c)
    d["v"] = d.v.fillna(0); return d

def features(d):
    c, h, l, o, v = (d[k].to_numpy(float) for k in ("c", "h", "l", "o", "v")); lc = np.log(c)
    r = np.r_[0, np.diff(lc)]; rs = pd.Series(r)
    rv = rs.rolling(1440, min_periods=300).std().to_numpy() + 1e-6
    rng = (h - l) / c; mr = pd.Series(rng).rolling(1440, min_periods=300).mean().to_numpy() + 1e-6
    mv = pd.Series(v).rolling(1440, min_periods=300).mean().to_numpy() + 1e-9
    F = {}
    for k in range(25):
        F[f"r{k}"] = np.roll(r, k) / rv; F[f"v{k}"] = np.log1p(np.roll(v, k) / mv)
        if k < 10: F[f"g{k}"] = np.roll(rng, k) / mr
    for k in range(3):
        hh, ll, oo, cc = (np.roll(x, k) for x in (h, l, o, c)); R = np.maximum(hh - ll, 1e-9)
        F[f"uw{k}"] = (hh - np.maximum(oo, cc)) / R; F[f"lw{k}"] = (np.minimum(oo, cc) - ll) / R; F[f"bd{k}"] = (cc - oo) / R
    for n in (5, 15, 25, 60, 240, 1440):
        F[f"ret{n}"] = (lc - np.roll(lc, n)) / (rv * np.sqrt(n))
    for n in (25, 240, 1440):
        F[f"dhi{n}"] = (np.log(pd.Series(h).rolling(n).max().to_numpy()) - lc) / rv
        F[f"dlo{n}"] = (lc - np.log(pd.Series(l).rolling(n).min().to_numpy())) / rv
    F["rv25"] = rs.rolling(25).std().to_numpy() / rv; F["rv240"] = rs.rolling(240).std().to_numpy() / rv; F["rv1440"] = rv
    F["rvd"] = rs.rolling(1440 * 7, min_periods=1440).std().to_numpy() / rv
    F["vol25"] = np.log1p(pd.Series(v).rolling(25).mean().to_numpy() / mv); F["vol240"] = np.log1p(pd.Series(v).rolling(240).mean().to_numpy() / mv)
    F["up25"] = pd.Series((r > 0).astype(float)).rolling(25).mean().to_numpy(); F["zv25"] = pd.Series((v == 0).astype(float)).rolling(25).mean().to_numpy()
    t = pd.to_datetime(d.ts, unit="s"); F["hour"] = t.dt.hour.to_numpy(); F["dow"] = t.dt.dayofweek.to_numpy(); F["minute"] = t.dt.minute.to_numpy()
    X = pd.DataFrame(F).astype("float32"); X.iloc[:1440 * 7] = np.nan
    return X

def outcomes(d, a, b, H):
    c, h, l, o = (d[k].to_numpy(float) for k in ("c", "h", "l", "o")); n = len(c); K = int(np.ceil(np.log2(H + 1)))
    sth, stl = sparse(h, np.maximum, K), sparse(l, np.minimum, K)
    i = np.arange(n); jt = first_cross(sth, c * (1 + a), i, H, True); js = first_cross(stl, c * (1 - b), i, H, False)
    y = (jt < js) & (jt < n)                                         # TP strictly first (same bar -> stop)
    e = np.r_[o[1:], c[-1]]                                          # next bar's open
    sl_px = np.minimum(c * (1 - b), o[np.minimum(js, n - 1)])        # gap through the stop -> that bar's open
    tout = c[np.minimum(i + H, n - 1)]
    pnl = np.where(y, c * (1 + a) / e - 1 - TAKER - MAKER,
          np.where(js < n, sl_px / e - 1 - TAKER - TAKER - SLIP, tout / e - 1 - 2 * TAKER))
    end = np.where(y, jt, np.where(js < n, js, np.minimum(i + H, n - 1)))
    valid = i + H < n
    return y.astype(np.int8), pnl.astype("float32"), end, valid

def simulate(ts, score, thr, pnl, end, mask):
    """non-overlapping: take a signal only after the previous trade has exited."""
    out, free = [], -1
    idx = np.flatnonzero(mask & (score >= thr))
    for i in idx:
        if i <= free: continue
        out.append((ts[i], pnl[i])); free = end[i]
    return out

if __name__ == "__main__":
    cfgs = sys.argv[1:] or list(CFG)
    D = {s: load(s) for s in ("btc", "eth")}
    X = {s: features(D[s]) for s in D}
    for name in cfgs:
        a, b, H = CFG[name]
        Y = {s: outcomes(D[s], a, b, H) for s in D}
        rows = []
        for s in D:
            y, pnl, end, valid = Y[s]
            rows.append(pd.DataFrame({"asset": s, "i": np.arange(len(y)), "ts": D[s].ts.to_numpy(), "y": y, "pnl": pnl, "end": end, "valid": valid}))
        M = pd.concat(rows, ignore_index=True); M["mo"] = pd.to_datetime(M.ts, unit="s").dt.to_period("M")
        XX = pd.concat([X["btc"], X["eth"]], ignore_index=True); XX["is_eth"] = (M.asset == "eth").astype("float32").to_numpy()
        ok = M.valid & XX.notna().all(axis=1).to_numpy()
        be = (b + 2 * TAKER + SLIP) / (a - TAKER - MAKER + b + 2 * TAKER + SLIP)
        print(f"\n===== {name}: +{a:.0%} before -{b:.2%} within {H} min | base rate {M.y[ok].mean():.2%} | break-even win rate ~{be:.1%}", flush=True)
        months = sorted(M.mo[ok].unique()); res, aucs, ev_all = [], [], []
        from sklearn.metrics import roc_auc_score
        for mo in months[8:]:
            t0 = mo.start_time.value // 10**9
            tr = ok & (M.ts.to_numpy() < t0 - H * 60) & (M.i.to_numpy() % 5 == 0)
            te = ok & (M.mo == mo).to_numpy()
            if te.sum() < 1000: continue
            m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=500, subsample=0.8, subsample_freq=1,
                                   colsample_bytree=0.7, verbose=-1).fit(XX[tr], M.y[tr])
            ptr = m.predict_proba(XX[tr])[:, 1]; pte = m.predict_proba(XX[te])[:, 1]
            aucs.append((str(mo), roc_auc_score(M.y[te], pte) if M.y[te].nunique() > 1 else np.nan, M.y[te].mean()))
            sc = np.full(len(M), -1.0); sc[np.flatnonzero(te)] = pte
            for q in (0.05, 0.01, 0.002):
                thr = np.quantile(ptr, 1 - q)
                for s in ("btc", "eth"):
                    sel = (M.asset == s).to_numpy(); off = np.flatnonzero(sel)[0]
                    y, pnl, end, valid = Y[s]
                    tr_ = simulate(D[s].ts.to_numpy(), sc[sel], thr, pnl, end, te[sel])
                    res += [dict(cfg=name, q=q, asset=s, mo=str(mo), ts=t, pnl=p) for t, p in tr_]
            # random-entry baseline: every 60th valid minute, non-overlapping
            for s in ("btc", "eth"):
                sel = (M.asset == s).to_numpy(); y, pnl, end, valid = Y[s]
                rnd = np.zeros(sel.sum(), bool); tem = te[sel]; rnd[np.flatnonzero(tem)[::60]] = True
                res += [dict(cfg=name, q="random", asset=s, mo=str(mo), ts=t, pnl=p) for t, p in simulate(D[s].ts.to_numpy(), np.ones(sel.sum()), 0.5, pnl, end, rnd)]
            print(f"  {mo}: AUC {aucs[-1][1]:.3f} base {aucs[-1][2]:.2%}", flush=True)
        R = pd.DataFrame(res); R["q"] = R.q.astype(str); R.to_parquet(f"data/scalp_{name}.parquet"); pd.DataFrame(aucs, columns=["mo", "auc", "base"]).to_csv(f"data/scalp_{name}_auc.csv", index=False)
