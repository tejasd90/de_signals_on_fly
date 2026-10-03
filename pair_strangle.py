"""Tejas, 2026-10-03: watch an EQUIDISTANT OTM pair (e.g. 83000C / 81000P with spot 82000).
Normally both decay, or one decays more than the other gains. When the rising leg gains MORE
than the falling leg decays, and holds, "an explosion could be imminent".

Measured on MARK option candles, 1h. At each hour t (6h <= tte <= 72h):
  strikes locked at t0 = t - L hours: K_c nearest S0*(1+D), K_p nearest S0*(1-D)
  pair   = (C_t + P_t) / (C_t0 + P_t0)            > 1 means the gain beat the decay
  held   = pair stayed >= 1 on each of the last H hourly closes
Outcomes from t onward (to min(t+24h, expiry)):
  boom2  = spot travels >= 2% from S_t at any point
  mb10   = a fresh ~2%-OTM option (either side, chosen at t) reaches 10x before expiry
The question is NOT whether pair>1 predicts a move (spot already moved during the lookback,
which is what made one leg gain). It is whether it adds over the controls the market and an
ATR model already have: trailing |spot move| over the same L hours, trailing 24h realised
vol, the pair's own price as a fraction of spot (implied move), tte, hour of day.
Logistic regression, train on the first half of expiries, test on the second, AUC with and
without the pair features.
"""
import json, os, re, glob, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
D, L, HOLD = 0.01, 6, 3

def spot(asset):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)):
                if r[4] is not None: m[int(r[0])] = (float(r[2]), float(r[3]), float(r[4]))
        except Exception: pass
    return m

def expiry_rows(asset, e, sp):
    d = f"data/candles/{asset}/{e}/60"
    if not os.path.isdir(d): return []
    exp_t = int(pd.Timestamp(e).timestamp()) + 43200
    C, P = {}, {}
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if not m: continue
        try: rows = json.load(open(os.path.join(d, fn)))
        except Exception: continue
        s = {int(r[0]) + 3600: (float(r[2]), float(r[4])) for r in rows if r[4] is not None}   # keyed by bar CLOSE
        (C if m.group(1) == "C" else P)[float(m.group(3))] = s
    if len(C) < 5 or len(P) < 5: return []
    kc, kp = np.array(sorted(C)), np.array(sorted(P))
    out = []
    for t in range(exp_t - 72*3600, exp_t - 6*3600 + 1, 3600):
        t0 = t - L*3600
        if (t0 - 3600) not in sp or (t - 3600) not in sp: continue
        S0, St = sp[t0 - 3600][2], sp[t - 3600][2]
        Kc = kc[np.abs(kc - S0*(1+D)).argmin()]; Kp = kp[np.abs(kp - S0*(1-D)).argmin()]
        try:
            pair = [C[Kc][x][1] + P[Kp][x][1] for x in range(t0, t + 1, 3600)]
        except KeyError: continue
        if pair[0] <= 0: continue
        r = np.array(pair) / pair[0]
        # trailing realised vol over 24h of hourly spot closes
        cl = [sp.get(x - 3600, (0, 0, np.nan))[2] for x in range(t - 24*3600, t + 1, 3600)]
        rv = np.nanstd(np.diff(np.log(cl))) * np.sqrt(24*365)
        # outcomes
        hz = range(t, min(t + 24*3600, exp_t) + 1, 3600)
        hh = [sp[x][0] for x in hz if x in sp]; ll = [sp[x][1] for x in hz if x in sp]
        if not hh: continue
        boom = max(max(hh)/St - 1, 1 - min(ll)/St) >= 0.02
        mb = False
        for book, ks, sgn in ((C, kc, 1), (P, kp, -1)):
            k = ks[np.abs(ks - St*(1 + sgn*0.02)).argmin()]
            ser = book[k]
            if t not in ser or ser[t][1] <= 0: continue
            fut = [ser[x][0] for x in ser if x > t]
            if fut and max(fut) >= 10*ser[t][1]: mb = True
        out.append(dict(asset=asset, expiry=e, t=t, tte=(exp_t - t)/3600, hour=(t//3600) % 24,
                        pair=r[-1], held=bool((r[-HOLD:] >= 1).all()), pmax=r.max(),
                        mv=abs(St/S0 - 1), rv=rv, impl=pair[-1]/St, boom=boom, mb10=mb))
    return out

if __name__ == "__main__":
    rows = []
    for a in ("BTC", "ETH"):
        sp = spot(a)
        for e in sorted(os.listdir(f"data/candles/{a}")):
            if e < "2024-01-01": continue
            rows += expiry_rows(a, e, sp)
        print(a, len(rows), flush=True)
    R = pd.DataFrame(rows).dropna(); R.to_parquet("data/pair_strangle.parquet")
    print(f"{len(R):,} pair-hours, {R.expiry.nunique()} expiries; pair>1 {(R.pair>1).mean():.1%}, held {R.held.mean():.1%}")
    print(f"base rates: boom2 {R.boom.mean():.1%}, mb10 {R.mb10.mean():.1%}\n")
    # raw view, within trailing-move terciles (the thing that mechanically lifts one leg)
    R["mvq"] = pd.qcut(R.mv, 3, labels=["small move", "mid move", "big move"])
    print(f"{'trailing spot move':<14}{'':<12}{'n':>8}{'boom2':>8}{'mb10':>8}")
    for q, g in R.groupby("mvq", observed=True):
        for lab, s in (("pair>1&held", g[g.held]), ("pair>1 only", g[(g.pair > 1) & ~g.held]), ("pair<=1", g[g.pair <= 1])):
            print(f"{q:<14}{lab:<12}{len(s):>8}{s.boom.mean():>8.1%}{s.mb10.mean():>8.1%}")
    # incremental value
    R["lpair"] = np.log(R.pair); R["lpmax"] = np.log(R.pmax); R["sin"] = np.sin(2*np.pi*R.hour/24); R["cos"] = np.cos(2*np.pi*R.hour/24)
    base = ["mv", "rv", "impl", "tte", "sin", "cos"]; full = base + ["lpair", "lpmax", "held"]
    cut = sorted(R.expiry.unique())[len(R.expiry.unique())//2]
    tr, te = R[R.expiry < cut], R[R.expiry >= cut]
    for y in ("boom", "mb10"):
        res = []
        for cols in (base, full):
            X = tr[cols].astype(float); mu, sd = X.mean(), X.std() + 1e-9
            m = LogisticRegression(max_iter=2000).fit((X - mu)/sd, tr[y])
            res.append(roc_auc_score(te[y], m.predict_proba((te[cols].astype(float) - mu)/sd)[:, 1]))
        # bootstrap the AUC gain over test expiries
        rng = np.random.default_rng(0); ex = te.expiry.unique(); gains = []
        Xb = te[base].astype(float); Xf = te[full].astype(float)
        mb_ = LogisticRegression(max_iter=2000).fit((tr[base]-tr[base].mean())/(tr[base].std()+1e-9), tr[y])
        mf_ = LogisticRegression(max_iter=2000).fit((tr[full].astype(float)-tr[full].astype(float).mean())/(tr[full].astype(float).std()+1e-9), tr[y])
        pb = mb_.predict_proba((Xb-tr[base].mean())/(tr[base].std()+1e-9))[:, 1]
        pf = mf_.predict_proba((Xf-tr[full].astype(float).mean())/(tr[full].astype(float).std()+1e-9))[:, 1]
        idx = {e: np.where(te.expiry.values == e)[0] for e in ex}; yy = te[y].values
        for _ in range(300):
            s = np.concatenate([idx[e] for e in rng.choice(ex, len(ex))])
            if yy[s].min() == yy[s].max(): continue
            gains.append(roc_auc_score(yy[s], pf[s]) - roc_auc_score(yy[s], pb[s]))
        print(f"\n{y}: test AUC controls only {res[0]:.4f}  + pair features {res[1]:.4f}  gain {res[1]-res[0]:+.4f}"
              f"  CI [{np.percentile(gains,2.5):+.4f},{np.percentile(gains,97.5):+.4f}]")
