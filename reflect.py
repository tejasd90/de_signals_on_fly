"""The reflection half of his light-box, tested separately.

v1 (lightbox.py) was pure absorption and came back null. But his model had light
REBOUNDING inside the box, so shadowed regions get indirect illumination -- a
candle buried in a range still receives light that bounced off other candles and
off the walls. That is a genuinely different object and was never tested.

The principled version is the two-flux (Kubelka-Munk) model, the standard
treatment for a scattering medium. Along each price row, track a forward flux F
travelling right and a backward flux B travelling left. At each candle body:

    F_out = tau*F_in + rho*B_in          tau = 1 - alpha - rho
    B_out = tau*B_in + rho*F_in

Solved by iterating the two sweeps to convergence. Box walls are mirrors with
reflectivity WALL, which is what makes it "closed" -- light that escapes right
comes back.

Total illumination at a body = F + B there. Pure absorption is the rho=0 case, so
this strictly generalises v1 and the comparison is clean: if rho>0 adds nothing
over rho=0, reflection is discardable.
"""
import numpy as np, pandas as pd
from levels import load_tf

CELL = 0.0025
ALPHAS = (0.10, 0.50)
RHOS   = (0.0, 0.2, 0.4)          # rho=0 IS the v1 pure-absorption case
WALL   = 0.9                       # closed box: near-mirror end walls
SWEEPS = 12

def two_flux(B_occ, alpha, rho, wall=WALL, sweeps=SWEEPS):
    """B_occ: (n_bars, n_cells) body occupancy. Returns F+B at each bar/cell."""
    n, K = B_occ.shape
    tau = max(1.0 - alpha - rho, 0.0)
    T = np.where(B_occ > 0, tau, 1.0)
    R = np.where(B_occ > 0, rho, 0.0)
    F = np.zeros((n, K)); Bk = np.zeros((n, K))
    for _ in range(sweeps):
        # forward sweep: light entering from the left wall
        f = np.ones(K)
        for i in range(n):
            f = T[i]*f + R[i]*Bk[i]
            F[i] = f
        # backward sweep: right wall reflects
        b = F[-1]*wall
        for i in range(n-1, -1, -1):
            b = T[i]*b + R[i]*F[i]
            Bk[i] = b
    return F + Bk

def features(spot, tf=1440):
    arr = load_tf(spot, tf)
    if arr is None: return None
    o, h, l, c = arr[:,1], arr[:,2], arr[:,3], arr[:,4]
    lo_edge = np.log(l.min()) - 0.5
    K = int((np.log(h.max()) + 0.5 - lo_edge)/CELL) + 1
    k0 = np.floor((np.log(np.minimum(o,c)) - lo_edge)/CELL).astype(int)
    k1 = np.maximum(np.floor((np.log(np.maximum(o,c)) - lo_edge)/CELL).astype(int), k0)
    Bo = np.zeros((len(c), K), np.float32)
    for j in range(len(c)): Bo[j, k0[j]:k1[j]+1] = 1.0

    cols = {}
    for a in ALPHAS:
        for r in RHOS:
            I = two_flux(Bo, a, r)
            v = np.array([I[i, k0[i]:k1[i]+1].mean() for i in range(len(c))])
            cols[f"rf|a{a}|r{r}"] = v
    d = pd.DataFrame(cols)
    d["day"] = pd.to_datetime(arr[:,0], unit="s").normalize(); d["spot"] = spot
    g = d.groupby(["spot","day"]).last().reset_index()
    fc = [x for x in g.columns if x.startswith("rf|")]
    g[fc] = g.groupby("spot")[fc].shift(1)      # known BEFORE the day asked about
    return g

if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from pascore_futures import build

    F = pd.concat([features(s) for s in ("BTC","ETH")])
    M = build().sort_values(["spot","day"]).merge(F, on=["spot","day"], how="inner")
    g = M.groupby("spot")
    M["v_absret"] = g["absret"].transform(lambda s: s.shift(1).rolling(5).mean())
    M["v_range"]  = g["rangeatr"].transform(lambda s: s.shift(1).rolling(5).mean())
    M["v_atrpct"] = M.atr_prev / M.c
    BASE = ["v_absret","v_range","v_atrpct"]
    RF = [c for c in M.columns if c.startswith("rf|")]
    M = M.dropna(subset=BASE+RF+["rangeatr","mfe"])
    cut = M.day.quantile(0.6); tr, te = M[M.day<cut], M[M.day>=cut]
    print(f"train {len(tr)}  held-out {len(te)}\n")

    def fit(feats, ytr):
        X, Y = tr[feats].to_numpy(), te[feats].to_numpy()
        mu, sd = X.mean(0), X.std(0)+1e-9
        m = LogisticRegression(max_iter=4000, C=0.5).fit((X-mu)/sd, ytr)
        return m.predict_proba((Y-mu)/sd)[:,1]

    print(f"{'target':<10}{'side':<7}{'base':>7}{'rho=0 (v1)':>12}{'rho>0 (refl)':>14}"
          f"{'refl gain':>11}   per-asset")
    for tgt in ("rangeatr","mfe"):
        for side in ("QUIET","BIG"):
            q = tr[tgt].quantile(1/3 if side=="QUIET" else 2/3)
            ytr = (tr[tgt]<q).astype(int) if side=="QUIET" else (tr[tgt]>q).astype(int)
            yte = ((te[tgt]<q) if side=="QUIET" else (te[tgt]>q)).astype(int).to_numpy()
            z  = [c for c in RF if c.endswith("|r0.0")]
            nz = [c for c in RF if not c.endswith("|r0.0")]
            ab = roc_auc_score(yte, fit(BASE, ytr))
            a0 = roc_auc_score(yte, fit(BASE+z, ytr))
            s1 = fit(BASE+z+nz, ytr); a1 = roc_auc_score(yte, s1)
            s0 = fit(BASE+z, ytr)
            per = []
            for spot in ("BTC","ETH"):
                m_ = (te.spot==spot).to_numpy()
                if m_.sum()>60 and len(np.unique(yte[m_]))>1:
                    per.append(f"{spot} {roc_auc_score(yte[m_],s1[m_])-roc_auc_score(yte[m_],s0[m_]):+.3f}")
            print(f"{tgt:<10}{side:<7}{ab:>7.3f}{a0:>12.3f}{a1:>14.3f}{a1-a0:>+11.3f}   " + "  ".join(per))
