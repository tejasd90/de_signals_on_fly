"""Is the U-shape two regimes, or just noise?

Q1 (lowest score) pays as well as Q5 (highest) while having 21.7% big-move days
vs Q5's 42.0%. The explanation offered was: Q1 marks a well-worn quiet range, so
options there are CHEAP, and a move when it comes pays more per rupee of premium.
That is a story until it is measured.

Direct test: OTM options on Q1 days should cost LESS, relative to spot, than on
Q5 days. Premium/spot for a fixed moneyness band is a serviceable IV proxy (Delta
serves no historical IV -- see de-signals-delta-oi-iv).

If Q1 premiums are NOT cheaper, the two-regime story is wrong and the U is
more likely an artifact to be explained some other way.
"""
import json, os, re, glob, sys
import numpy as np, pandas as pd
from datetime import datetime, timezone

RES = "240"
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
OUT = "data/day_premium_level.parquet"

def load_spot(a):
    m = {}
    for p in glob.glob(f"data/spot_candles/{a}/{RES}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def build():
    rec = []
    for asset in ("BTC", "ETH"):
        spot = load_spot(asset)
        if not spot: continue
        for day in sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith(".")):
            dd = f"data/candles/{asset}/{day}/{RES}"
            if not os.path.isdir(dd): continue
            for fn in os.listdir(dd):
                m = SYM.match(fn)
                if not m: continue
                typ, _, strike, _ = m.groups(); strike = float(strike)
                try: rr = json.load(open(os.path.join(dd, fn)))
                except Exception: continue
                for r in rr:
                    if r[4] is None: continue
                    sp = spot.get(int(r[0]))
                    if not sp: continue
                    otm = (sp-strike)/sp*100 if typ == "P" else (strike-sp)/sp*100
                    if not (4 <= otm <= 8): continue          # narrow band: fixes moneyness
                    rec.append((asset,
                                datetime.fromtimestamp(int(r[0]), tz=timezone.utc).strftime("%Y-%m-%d"),
                                float(r[4]) / sp * 100))
        print(f"{asset}: {len(rec):,}", file=sys.stderr)
    d = pd.DataFrame(rec, columns=["spot","day","prem_pct"])
    g = d.groupby(["spot","day"]).agg(prem_pct=("prem_pct","median"), n=("prem_pct","size")).reset_index()
    g["day"] = pd.to_datetime(g.day); g.to_parquet(OUT); return g

if __name__ == "__main__":
    g = build() if not os.path.exists(OUT) else pd.read_parquet(OUT)
    import warnings; warnings.filterwarnings("ignore")
    from sklearn.linear_model import LogisticRegression
    from pascore_eval import load, add_age, cols_for
    BEST = ("harmonic", 500, 0.002)
    J = add_age(load()); J = J[np.isfinite(J.y)]
    cut = J.index[int(len(J)*0.6)]; cols = cols_for(*BEST)
    tr, te = J[J.index < cut], J[J.index >= cut]
    Xtr, Xte = tr[cols].to_numpy(), te[cols].to_numpy()
    a, b = np.isfinite(Xtr).all(1), np.isfinite(Xte).all(1)
    mu, sd = Xtr[a].mean(0), Xtr[a].std(0)+1e-9
    mdl = LogisticRegression(max_iter=2000, C=0.5).fit((Xtr[a]-mu)/sd, tr.y.to_numpy()[a])
    T = te[b].copy(); T["score"] = mdl.predict_proba((Xte[b]-mu)/sd)[:,1]
    T = T.reset_index().rename(columns={T.reset_index().columns[0]: "day"})
    T["day"] = pd.to_datetime(T["day"])
    M = T.merge(g[g.n >= 4], on=["spot","day"], how="inner")
    M["q"] = pd.qcut(M.score, 5, labels=False, duplicates="drop")
    print(f"\nheld-out days with premium data: {len(M)}")
    print(f"{'quintile':<9}{'days':>6}{'median prem/spot %':>21}{'P(100x day)':>13}")
    for q, gg in M.groupby("q"):
        print(f"Q{int(q)+1:<8}{len(gg):>6}{gg.prem_pct.median():>20.3f}%{gg.y.mean()*100:>12.1f}%")
    q1 = M[M.q == 0].prem_pct; q5 = M[M.q == M.q.max()].prem_pct
    from scipy.stats import mannwhitneyu
    u = mannwhitneyu(q1, q5, alternative="less")
    print(f"\nQ1 median {q1.median():.3f}%  vs Q5 median {q5.median():.3f}%")
    print(f"Mann-Whitney, H1 = Q1 options are CHEAPER than Q5:  p={u.pvalue:.4f}")
    print("  (small p supports the two-regime story; large p refutes it)")
