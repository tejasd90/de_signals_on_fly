#!/usr/bin/env python3
"""
step3_tune.py — find the tuning your signals need.

This is the one that produces the answer. It:

  1. trains a logistic baseline and LightGBM on purged walk-forward folds
  2. compares feature ARMS so you can see what each group of features is worth
  3. reports precision at low recall (the metric that matters for 25:1 payoffs)
  4. measures which features are INERT via permutation importance
  5. extracts TUNED THRESHOLDS from the fitted model and writes a config block

    python3 step3_tune.py --data dataset.csv
    python3 step3_tune.py --data dataset.csv --arms context,signals,both

VALIDATION: splits are by TIME and grouped by EPISODE. No episode ever appears in
both train and test, and test is always later than train. Random k-fold on this
data reports ~0.95 AUC and is entirely fake.

METRIC: precision at low recall, not accuracy. Catching 15% of moves at 70%
precision is an excellent system; chasing 90% recall drags precision to noise.
"""

import argparse, json, os, sys, time, warnings
from datetime import datetime

_T0 = time.time()


def log(msg, end="\n"):
    el = time.time() - _T0
    print(f"[{datetime.now().strftime('%H:%M:%S')} "
          f"+{int(el)//60:02d}:{int(el)%60:02d}] {msg}", end=end, flush=True)
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, average_precision_score
import lightgbm as lgb

warnings.filterwarnings("ignore")

# columns that are outcomes or identifiers, never inputs
# Fields query_lang.js marks `outcome: true` — known only AFTER the trade.
# Feeding any of them to the model is pure leakage and yields AUC 1.000.
OUTCOMES = {"ratio", "univratio", "state", "brokeout", "holdcandles",
            "peakafter"}

# episode_id is the CV grouping key and rises with time — a model given it
# learns "earlier data had more positives". Raw price levels are
# non-stationary: BTC at 30k and at 100k are different worlds, and a tree will
# split on "spotPrice < 67000", which is a DATE RANGE, not a signal.
NONSTATIONARY = {"episodeid", "spotprice", "entryprice", "triggerprice",
                 "patternhigh", "patternlow", "avgprice", "logvalue"}
LEAK = ({"_peak", "label", "episode_id", "_episode_time", "_ts_hours", "_w",
         "symbol", "timestamp", "entryts", "expiry", "strike", "mbratio",
         "peakratio", "maxratio", "peak", "forwardratio", "signalvalue",
         "univsymbol", "_key", "signal"} | OUTCOMES | NONSTATIONARY)

# arm definitions by column-name matching
CONTEXT_HINTS = ["tte", "dte", "expiry", "moneyness", "distance", "duration",
                 "strike", "spot", "cheapness", "days", "vol"]
SIGNAL_HINTS = ["ratio", "seq", "jump", "equal", "univ", "state", "squeeze",
                "stairs", "wall", "body", "step"]


def classify_columns(df):
    num = df.select_dtypes(include=[np.number]).columns
    # Any column starting with "_" is internal (label, weight, episode time).
    # `_w` is derived from the label, so including it is direct leakage — and
    # name-normalising underscores away made it slip past the LEAK set.
    feats = [c for c in num
             if not c.startswith("_")
             and c.lower().replace("_", "") not in LEAK]
    ctx, sig, other = [], [], []
    # discovery tables use explicit prefixes; honour them before name hints,
    # otherwise every spot_* shape feature is misfiled as "context" and the
    # arm comparison stops meaning anything
    if any(c.startswith(("opt_", "spot_", "surf_")) for c in feats):
        surf = []
        for c in feats:
            if c.startswith("opt_"):
                sig.append(c)
            elif c.startswith("spot_"):
                other.append(c)
            elif c.startswith("surf_"):
                surf.append(c)
            else:
                ctx.append(c)      # tteHours, stdMoneyness, cheapness, spotVol
        return ctx, sig, other + surf
    for c in feats:
        lc = c.lower()
        if any(h in lc for h in CONTEXT_HINTS):
            ctx.append(c)
        elif any(h in lc for h in SIGNAL_HINTS):
            sig.append(c)
        else:
            other.append(c)
    return ctx, sig, other


def purged_folds(df, n_folds=5, embargo_frac=0.01):
    """
    Time-ordered folds, split on EPISODE boundaries, with an embargo gap.
    Returns list of (train_idx, test_idx).
    """
    ep = df.groupby("episode_id")["_episode_time"].min().sort_values()
    eps = ep.index.to_numpy()
    n = len(eps)
    if n < n_folds * 4:
        n_folds = max(2, n // 4)
    bounds = np.linspace(0, n, n_folds + 1).astype(int)
    embargo = max(1, int(n * embargo_frac))

    folds = []
    for i in range(1, n_folds):          # first block is train-only
        tr_end = bounds[i]
        te_end = bounds[i + 1]
        tr_eps = set(eps[: max(0, tr_end - embargo)])
        te_eps = set(eps[tr_end:te_end])
        if not tr_eps or not te_eps:
            continue
        tr = df.index[df["episode_id"].isin(tr_eps)].to_numpy()
        te = df.index[df["episode_id"].isin(te_eps)].to_numpy()
        folds.append((tr, te))
    return folds


def precision_at_recall(y, p, w, target_recall=0.15):
    """Weighted precision when flagging enough to catch target_recall of
    positives. Weights are mandatory: step1 keeps all positives and samples
    negatives, so unweighted precision describes the sample, not the market."""
    pos = w[y == 1].sum()
    if pos <= 0:
        return float("nan"), float("nan")
    order = np.argsort(-p)
    yv, wv = y[order], w[order]
    cum_tp = np.cumsum(wv * yv)
    cum_n = np.cumsum(wv)
    need = target_recall * pos
    idx = np.argmax(cum_tp >= need)
    if cum_tp[idx] < need:
        return float("nan"), float("nan")
    return cum_tp[idx] / cum_n[idx], cum_n[idx] / w.sum()


def evaluate(df, cols, name, seed=0):
    if not cols:
        return None
    X = df[cols].to_numpy(dtype=float)
    y = df["label"].to_numpy()
    w = df["_w"].to_numpy(dtype=float)
    folds = purged_folds(df)
    if not folds:
        print(f"  {name}: not enough episodes to build folds")
        return None

    res = {"name": name, "n_features": len(cols),
           "auc": [], "ap": [], "p15": [], "p05": [], "flag_rate": [],
           "lr_auc": []}
    oof = np.full(len(df), np.nan)

    for tr, te in folds:
        ytr, yte = y[tr], y[te]
        if ytr.sum() < 5 or yte.sum() < 1:
            continue

        # --- logistic baseline
        lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                           LogisticRegression(max_iter=2000, C=0.1,
                                              class_weight="balanced"))
        lr.fit(X[tr], ytr, logisticregression__sample_weight=w[tr])
        res["lr_auc"].append(roc_auc_score(
            yte, lr.predict_proba(X[te])[:, 1], sample_weight=w[te]))

        # --- LightGBM, deliberately small: few hundred episodes
        m = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.03, num_leaves=7,
            max_depth=3, min_child_samples=30,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.7,
            reg_lambda=5.0, class_weight="balanced",
            random_state=seed, verbose=-1)
        m.fit(X[tr], ytr, sample_weight=w[tr])
        p = m.predict_proba(X[te])[:, 1]
        oof[te] = p

        res["auc"].append(roc_auc_score(yte, p, sample_weight=w[te]))
        res["ap"].append(average_precision_score(yte, p, sample_weight=w[te]))
        pr15, fr = precision_at_recall(yte, p, w[te], 0.15)
        pr05, _ = precision_at_recall(yte, p, w[te], 0.05)
        res["p15"].append(pr15); res["p05"].append(pr05); res["flag_rate"].append(fr)

    if not res["auc"]:
        return None
    res["oof"] = oof
    res["base_rate"] = np.average(y, weights=w)
    return res



def conviction_matrix(y, p, w, peaks, base_targets=(2, 5, 10, 25, 50, 100)):
    """
    Rank by model score, then report the hit rate at each target multiple for
    the top X% by conviction. Better than precision-at-fixed-recall: it maps
    straight onto "how selective should I be", which is the actual decision.

    Weighted throughout — step1 keeps all positives and samples negatives, so
    unweighted rates describe the sample, not the market.

    A row where every target column reads ~100% is a BUG SIGNATURE, not a
    result. Check whether the selected rows share one value of one feature.
    """
    order = np.argsort(-p)
    yv, wv, pk = y[order], w[order], peaks[order]
    cw = np.cumsum(wv)
    total = cw[-1]
    rows = []
    for pct in (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 100.0):
        k = int(np.searchsorted(cw, total * pct / 100.0)) + 1
        k = min(k, len(yv))
        ws = wv[:k]
        if ws.sum() <= 0:
            continue
        rates = [float(ws[(pk[:k] >= t)].sum() / ws.sum()) for t in base_targets]
        rows.append(("all" if pct == 100.0 else f"top {pct}%",
                     k, float(ws.sum()), rates))
    return rows, base_targets


def print_conviction(rows, targets, label=""):
    print("\n" + "=" * 78)
    print(f"CONVICTION MATRIX — out-of-sample hit rate by selectivity {label}")
    print("=" * 78)
    hdr = f"{'select':10}{'rows':>9}" + "".join(f"{str(t)+'x':>10}" for t in targets)
    print(hdr); print("-" * len(hdr))
    for name, k, _, rates in rows:
        print(f"{name:10}{k:>9,}" + "".join(f"{r*100:>9.2f}%" for r in rates))
    print("-" * len(hdr))
    print("Compare each row against 'all' — that is the lift from being")
    print("selective. Rows reading ~100% across every column indicate a broken")
    print("label, not a discovery.")


def fmt(v):
    v = [x for x in v if np.isfinite(x)]
    return f"{np.mean(v):.3f}" if v else "  -  "


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--arms",
                    default="context,signals,spot_shape,surface,both,all")
    ap.add_argument("--recall", type=float, default=0.15)
    ap.add_argument("--out-config", default="tuned_config.json")
    ap.add_argument("--target", default=None,
                    help="pick which label_* column to train on, e.g. 10 or 25."
                         " discover_build emits several from one pass.")
    ap.add_argument("--pooled", action="store_true",
                    help="train one model over all signals (not recommended)")
    args = ap.parse_args()

    log("=" * 68)
    log("STEP 3 — tuning")
    log("=" * 68)
    log(f"PHASE 1/5  loading {args.data}")

    df_all = (pd.read_parquet(args.data)
          if args.data.endswith(".parquet") or os.path.isdir(args.data)
          else pd.read_csv(args.data)).reset_index(drop=True)
    if "_w" not in df_all.columns:
        df_all["_w"] = 1.0

    lab_cols = sorted(c for c in df_all.columns if c.startswith("label_"))
    if lab_cols:
        log(f"  available targets: "
            + ", ".join(c.replace('label_', '').replace('_0', '') + "x"
                        for c in lab_cols))
    if args.target is not None:
        key = f"label_{str(float(args.target)).replace('.', '_')}"
        if key not in df_all.columns:
            sys.exit(f"ERROR: no column {key}. Available: {lab_cols}")
        df_all["label"] = df_all[key]
        log(f"  training on {key}")
    elif lab_cols:
        log(f"  training on default 'label' column "
            f"(pass --target to switch)")

    # every label_* column is an outcome — never a feature
    for c in lab_cols:
        LEAK.add(c.lower().replace("_", ""))

    # Run PER SIGNAL. ratio1/seqLength/etc. mean different things in each
    # signal; pooled they cancel to noise. Step 2 shows green_stairs strength
    # ranks at rho +0.44 while otm_wall ranks nothing — one model over both
    # cannot represent that.
    groups = []
    if "signal" in df_all.columns and not args.pooled:
        if df_all["signal"].notna().any():
            groups = [(str(s), g.reset_index(drop=True))
                      for s, g in df_all.groupby("signal", observed=True)]
            groups = [(s, g) for s, g in groups if len(g) >= 500]
        else:
            log("  ! 'signal' column is entirely null — treating as one model")
    if not groups:
        # Never fall through with an empty list: the training loop would run
        # zero times and the script would exit clean having done nothing.
        groups = [("(pooled)", df_all)]

    for sig_name, df in groups:
        print("\n\n" + "#" * 72)
        print(f"# SIGNAL: {sig_name}   ({len(df):,} rows)")
        print("#" * 72)
        run_one(df, args, sig_name)


def run_one(df, args, sig_name):
    if "label" not in df or "episode_id" not in df:
        sys.exit("ERROR: dataset must come from step1 (needs label + episode_id).")

    if "_episode_time" not in df.columns and "_ts_hours" in df.columns:
        df["_episode_time"] = df["_ts_hours"]        # step1 v3 column name

    if df["episode_id"].dtype == object:
        df["episode_id"] = pd.factorize(df["episode_id"])[0]

    ctx, sig, other = classify_columns(df)
    dropped = sorted(c for c in df.columns
                     if c.startswith("_")
                     or c.lower().replace("_", "") in LEAK)
    print(f"\nexcluded as outcome/id (never features): {dropped}")
    print(f"\nrows {len(df):,} | episodes {df['episode_id'].nunique():,} | "
          f"positive episodes {df.groupby('episode_id')['label'].max().sum():,}")
    print(f"\ncontext features ({len(ctx)}): {ctx}")
    print(f"signal features  ({len(sig)}): {sig}")
    if other:
        print(f"unclassified ({len(other)}): {other}   → included in 'all'")

    arms = {"context": ctx, "signals": sig, "both": ctx + sig,
            "all": ctx + sig + other}
    if any(c.startswith("spot_") for c in other):
        arms["spot_shape"] = ctx + [c for c in other if c.startswith("spot_")]
    if any(c.startswith("surf_") for c in other):
        # THE SURFACE ARM: context + where this strike sits on the chain
        arms["surface"] = ctx + [c for c in other if c.startswith("surf_")]
    wanted = [a.strip() for a in args.arms.split(",")]

    log("PHASE 2/5  building purged walk-forward folds")
    folds_dbg = purged_folds(df)
    print()
    log("=" * 68)
    log("VALIDATION SETUP — purged walk-forward")
    print("=" * 72)
    print(f"{'fold':6}{'train rows':>12}{'test rows':>11}{'train eps':>11}"
          f"{'test eps':>10}{'   test period':>28}")
    print("-" * 84)
    for fi, (tr, te) in enumerate(folds_dbg, 1):
        t0 = df.loc[te, "_episode_time"].min() / 24
        t1 = df.loc[te, "_episode_time"].max() / 24
        d0 = pd.Timestamp("1970-01-01") + pd.Timedelta(days=float(t0))
        d1 = pd.Timestamp("1970-01-01") + pd.Timedelta(days=float(t1))
        print(f"{fi:<6}{len(tr):>12,}{len(te):>11,}"
              f"{df.loc[tr,'episode_id'].nunique():>11,}"
              f"{df.loc[te,'episode_id'].nunique():>10,}"
              f"   {d0.date()} .. {d1.date()}")
    print("\nEvery test block is LATER in time than its training data, and no")
    print("episode appears in both. All scores below are out-of-sample.")

    log(f"PHASE 3/5  training arms ({len(wanted)} x "
        f"{len(folds_dbg)} folds x 2 models)")
    print()
    log("=" * 68)
    log("ARM COMPARISON — purged walk-forward, mean across folds")
    print("=" * 72)
    hdr = (f"{'arm':12}{'feats':>7}{'AUC':>8}{'AvgPrec':>9}"
           f"{'P@5%rec':>9}{'P@15%rec':>10}{'flag%':>8}{'logregAUC':>11}"
           f"{'time':>7}")
    print(hdr); print("-" * len(hdr))

    results = {}
    for a in wanted:
        if a not in arms:
            continue
        _ta = time.time()
        r = evaluate(df, arms[a], a)
        _el = time.time() - _ta
        if r is None:
            print(f"{a:12}  (skipped — too few features or episodes)")
            continue
        results[a] = r
        print(f"{a:12}{r['n_features']:>7}{fmt(r['auc']):>8}{fmt(r['ap']):>9}"
              f"{fmt(r['p05']):>9}{fmt(r['p15']):>10}"
              f"{np.mean(r['flag_rate'])*100:>7.1f}%{fmt(r['lr_auc']):>11}"
              f"{_el:>7.1f}s")

    if not results:
        sys.exit("\nNo arm could be evaluated. Check feature columns.")

    base = np.average(df["label"], weights=df["_w"])

    # conviction matrix on out-of-fold predictions of the best arm
    best_now = max(results, key=lambda k: np.mean(results[k]["p15"])
                   if np.isfinite(np.mean(results[k]["p15"])) else -1)
    oof = results[best_now]["oof"]
    m = np.isfinite(oof)
    if m.sum() > 100 and "_peak" in df.columns:
        rows_, tg = conviction_matrix(
            df["label"].to_numpy()[m], oof[m], df["_w"].to_numpy()[m],
            pd.to_numeric(df["_peak"], errors="coerce").to_numpy()[m])
        print_conviction(rows_, tg, f"(arm '{best_now}', {sig_name})")
    print(f"\nbase rate (flag everything): {base*100:.2f}%  "
          f"← weighted; precision must beat this")

    # ---- interpretation --------------------------------------------------
    print("\n" + "=" * 72)
    print("WHAT THIS MEANS")
    print("=" * 72)
    if "context" in results and "signals" in results:
        c = np.mean(results["context"]["p15"])
        s = np.mean(results["signals"]["p15"])
        b = np.mean(results["both"]["p15"]) if "both" in results else np.nan
        print(f"\ncontext-only precision @15% recall : {c:.3f}")
        print(f"signals-only                       : {s:.3f}")
        if np.isfinite(b):
            print(f"both                               : {b:.3f}")
        print()
        if s > c * 1.15:
            print("→ Your signals carry information BEYOND context alone.")
            print("  The structure is real. Tuned thresholds below.")
        elif np.isfinite(b) and b > c * 1.15:
            print("→ Signals add value only in COMBINATION with context.")
            print("  That's the conditional-threshold case: the pattern works "
                  "under some conditions,")
            print("  not others. Exactly what the tuned thresholds below encode.")
        else:
            print("→ Signals add little over context (tteHours, moneyness).")
            print("  Most predictive power is in WHICH contract, not WHICH "
                  "pattern.")
            print("  That is still tradeable — it just means selection beats "
                  "timing here.")

    # ---- best arm: importance + thresholds -------------------------------
    best = max(results, key=lambda k: np.mean(results[k]["p15"])
               if np.isfinite(np.mean(results[k]["p15"])) else -1)
    cols = arms[best]
    log(f"PHASE 4/5  permutation importance on arm '{best}' "
        f"({len(cols)} features x 5 shuffles)")
    print()
    log("=" * 68)
    log(f"FEATURE IMPORTANCE — arm '{best}'")
    print("=" * 72)

    X = df[cols].to_numpy(dtype=float)
    y = df["label"].to_numpy()
    model = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.03, num_leaves=7, max_depth=3,
        min_child_samples=30, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.7, reg_lambda=5.0, class_weight="balanced",
        random_state=0, verbose=-1)
    model.fit(X, y)

    # permutation importance on the last fold's test set
    folds = purged_folds(df)
    tr, te = folds[-1]
    m2 = lgb.LGBMClassifier(**model.get_params())
    m2.fit(X[tr], y[tr])
    base_auc = roc_auc_score(y[te], m2.predict_proba(X[te])[:, 1])
    rng = np.random.default_rng(0)
    drops = []
    for j, c in enumerate(cols):
        if len(cols) > 40 and j % 20 == 0:
            log(f"    feature {j}/{len(cols)} ...", end="\r")
        d = []
        for _ in range(5):
            Xp = X[te].copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            d.append(base_auc - roc_auc_score(y[te], m2.predict_proba(Xp)[:, 1]))
        drops.append(np.mean(d))
    imp = pd.DataFrame({"feature": cols, "auc_drop": drops}) \
            .sort_values("auc_drop", ascending=False)

    print(f"\n{'feature':28}{'AUC drop when shuffled':>24}")
    print("-" * 52)
    for _, r in imp.iterrows():
        flag = "  ← INERT, drop it" if r.auc_drop <= 0.001 else ""
        print(f"{r.feature:28}{r.auc_drop:>24.4f}{flag}")

    inert = imp[imp.auc_drop <= 0.001]["feature"].tolist()
    if inert:
        print(f"\n{len(inert)} of {len(cols)} features are inert — removing them "
              f"will not hurt, and makes the model easier to read.")

    # ---- tuned thresholds ------------------------------------------------
    log("PHASE 5/5  out-of-sample threshold ranges")
    print()
    log("=" * 68)
    log("TUNED THRESHOLDS")
    print("=" * 72)
    print("Bins are fitted on TRAINING folds only; the rate shown is measured")
    print("on the HELD-OUT fold. A range that only works in-sample is noise —")
    print("the 'test' column is the one to trust.\n")

    config = {}
    live = imp[imp.auc_drop > 0.001]["feature"].tolist()[:12]
    tr_i, te_i = folds_dbg[-1]
    dtr, dte = df.loc[tr_i], df.loc[te_i]

    for c in live:
        a = dtr[[c, "label", "_w"]].apply(pd.to_numeric, errors="coerce").dropna()
        b = dte[[c, "label", "_w"]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(a) < 200 or len(b) < 100 or a[c].nunique() < 8:
            continue
        try:
            _, edges = pd.qcut(a[c], 6, retbins=True, duplicates="drop")
        except ValueError:
            continue
        edges[0], edges[-1] = -np.inf, np.inf

        def rate(d):
            g = pd.cut(d[c], edges)
            out_ = {}
            for k, gg in d.groupby(g, observed=True):
                w_ = gg["_w"].to_numpy()
                if w_.sum() <= 0:
                    continue
                out_[k] = (w_[(gg["label"] == 1).to_numpy()].sum() / w_.sum(),
                           len(gg))
            return out_

        rtr, rte = rate(a), rate(b)
        keys = [k for k in rtr if k in rte and rte[k][1] >= 20]
        if not keys:
            continue

        base_te = np.average(b["label"], weights=b["_w"])
        best_k = max(keys, key=lambda k: rtr[k][0])      # chosen on TRAIN
        print(f"{c}")
        print(f"    {'range':30}{'train':>9}{'TEST':>9}{'n test':>9}")
        for k in keys:
            mark = "  <- picked on train" if k == best_k else ""
            print(f"    {str(k):30}{rtr[k][0]*100:>8.2f}%"
                  f"{rte[k][0]*100:>8.2f}%{rte[k][1]:>9,}{mark}")
        lift = rte[best_k][0] / max(base_te, 1e-9)
        held = "HOLDS" if lift > 1.15 else "does NOT hold"
        print(f"    -> out-of-sample lift {lift:.2f}x over base "
              f"({base_te*100:.2f}%)  [{held}]\n")
        config[c] = {"best_low": float(best_k.left),
                     "best_high": float(best_k.right),
                     "train_rate": float(rtr[best_k][0]),
                     "test_rate": float(rte[best_k][0]),
                     "test_lift": float(lift),
                     "holds_out_of_sample": bool(lift > 1.15)}

    out = {"arm": best, "base_rate": float(base),
           "precision_at_15pct_recall": float(np.mean(results[best]["p15"])),
           "inert_features": inert, "thresholds": config}
    cfg_path = (args.out_config if sig_name == "(pooled)"
                else args.out_config.replace(".json", f"_{sig_name}.json"))
    out["signal"] = sig_name
    json.dump(out, open(cfg_path, "w"), indent=2)
    print(f"wrote {cfg_path}")
    print("\nUse the ranges above as config thresholds. Where two features both")
    print("show lift, require BOTH — that is the conditional tuning a single")
    print("hand-picked threshold cannot express.")


if __name__ == "__main__":
    main()
