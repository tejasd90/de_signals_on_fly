"""What does his hurdle rule pay in OPTIONS, and do hurdle-based exits / re-entry help?

Events: a 1m CLOSE beyond a hurdle (hurdle_test.levels on 1m TRADED perp candles, only levels price
had left by >= 1.5 ATR), and the same for ordinary slow-rolling peaks as the control.
Trade:  5 minutes after the break close, buy the option ~0.75% OTM in the break direction on the
        nearest expiry with >= 3h left (5m MARK option candles are stored for the last 48h of every
        expiry). Premium must be >= 0.03% of spot, so dust marks are excluded. 8.26% round-trip cost
        per entry (as premium_pa.py).
Exits:
  2h      sell at the 5m close 2 hours later
  expiry  hold to settlement (intrinsic at 12:00 UTC)
  hurdle  his rules: TARGET = the nearest older hurdle on the same side ahead of price (book out
          when the 1m high/low reaches it); TRAP = a 1m close back through the broken hurdle by
          > 0.25 ATR (out at the next 5m option close); otherwise out after 6h. RE-ENTRY: after a
          trap exit, a new 1m close beyond the same hurdle re-enters (same strike, at most 2
          re-entries, not within 3h of expiry). Return = sum of P&L over all entries / first stake.
"""
import json, os, re, sys, numpy as np, pandas as pd
from hurdle_test import load, levels
COST = 0.0826

def opt_series(asset, expiry, sym):
    f = f"data/candles/{asset}/{expiry}/5/{sym}.json"
    if not os.path.exists(f): return None
    r = json.load(open(f))
    return {int(x[0]) + 300: float(x[4]) for x in r if x[4] is not None}      # keyed by bar CLOSE

def strikes(asset, expiry, typ):
    d = f"data/candles/{asset}/{expiry}/5"
    if not os.path.isdir(d): return []
    return sorted(float(f.split("-")[2]) for f in os.listdir(d) if f.startswith(typ + "-"))

def expiries(asset):
    return sorted(e for e in os.listdir(f"data/candles/{asset}") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e))

def run(asset, TGT_ATR=0.5, USE_TRAP=True, REENTER=True, HOLD_H=6):
    d = load(asset, "1"); t = d.t.to_numpy().astype(np.int64); h, l, c = d.h.to_numpy(), d.l.to_numpy(), d.c.to_numpy()
    L, _ = levels(d, "1", K=10, M=20, E_H=12)
    away = L.sgn * (L.level - c[L.known.to_numpy()]) / L.atr >= 1.5
    L = L[away].reset_index(drop=True)
    exps = expiries(asset); exp_ts = np.array([pd.Timestamp(e).timestamp() + 43200 for e in exps])
    hurdles = L[L.kind == "hurdle"]
    out = []
    for r in L.itertuples():
        s, lv, a = r.sgn, r.level, r.atr
        # first 1m CLOSE beyond the level after it became known (within 3 days)
        seg = np.arange(r.known + 1, min(len(c), r.known + 1 + 3*1440))
        hit = seg[s * (c[seg] - lv) > 0.1 * a]
        if not len(hit): continue
        k = hit[0]; tb = t[k] + 60                                      # break bar close
        te = (tb // 300 + 1) * 300                                      # next 5m option close
        S = c[k]; typ = "C" if s == 1 else "P"
        j = np.searchsorted(exp_ts, te + 3*3600)
        if j >= len(exps): continue
        e, settle = exps[j], int(exp_ts[j])
        ks = strikes(asset, e, typ)
        if not ks: continue
        K = min(ks, key=lambda x: abs(x - S * (1 + s * 0.0075)))
        sym = f"{typ}-{asset}-{int(K)}-{pd.Timestamp(e).strftime('%d%m%y')}"
        ser = opt_series(asset, e, sym)
        if not ser or te not in ser or ser[te] < 0.0003 * S: continue
        p0 = ser[te]
        def val(ts):                                                    # option mark at/just before ts
            keys = [x for x in ser if x <= ts]
            return ser[max(keys)] if keys else np.nan
        # spot at settlement (1m close of the bar ending 12:00 UTC)
        ks_ = np.searchsorted(t, settle - 60)
        ST = c[ks_] if ks_ < len(t) and t[ks_] == settle - 60 else np.nan
        intrinsic = max(0.0, s * (ST - K)) if np.isfinite(ST) else np.nan
        r2h = val(min(te + 7200, settle)) / p0 - 1 - COST
        rexp = intrinsic / p0 - 1 - COST if np.isfinite(intrinsic) else np.nan
        # hurdle exits + re-entry
        ahead = hurdles[(hurdles.sgn == s) & (hurdles.known < k) & (s * (hurdles.level - S) > TGT_ATR * a)]
        target = (ahead.level.min() if s == 1 else ahead.level.max()) if len(ahead) else np.nan
        pnl, entries, i, entry_ts, entry_p = 0.0, 1, k, te, p0
        stop_ts = min(settle - 3600, te + HOLD_H*3600)
        while True:
            ex_ts, ex_p = None, None
            m = np.searchsorted(t, entry_ts)                             # first 1m bar after entry
            for q in range(m, len(t)):
                tq = t[q] + 60
                if tq >= stop_ts: break
                if np.isfinite(target) and s * ((h[q] if s == 1 else l[q]) - target) >= 0:
                    ex_ts = (tq // 300 + 1) * 300; why = "target"; break
                if USE_TRAP and s * (lv - c[q]) > 0.25 * a:             # closed back through: trap
                    ex_ts = (tq // 300 + 1) * 300; why = "trap"; break
            if ex_ts is None: ex_ts = stop_ts; why = "time"
            ex_p = val(min(ex_ts, settle))
            pnl += ex_p / entry_p - 1 - COST                    # each entry stakes one unit
            if why != "trap" or entries > 2 or not REENTER: break
            # re-entry: a fresh 1m close beyond the hurdle after the trap exit
            q0 = np.searchsorted(t, ex_ts)
            again = [q for q in range(q0, min(len(t), q0 + 6*60)) if s * (c[q] - lv) > 0.1 * a]
            if not again: break
            ne = ((t[again[0]] + 60) // 300 + 1) * 300
            if ne >= settle - 3*3600 or ne not in ser: break
            entries += 1; entry_ts, entry_p = ne, ser[ne]
        out.append(dict(asset=asset, kind=r.kind, t=tb, r2h=r2h, rexp=rexp, rhurdle=pnl / entries, entries=entries,
                        has_target=np.isfinite(target), tte_h=(settle - te) / 3600,
                        peak=max(v for ts_, v in ser.items() if te <= ts_ <= settle) / p0))
    return pd.DataFrame(out)

def summ(F, col):
    x = F[col].dropna().to_numpy(); rng = np.random.default_rng(0)
    b = [rng.choice(x, len(x)).mean() for _ in range(2000)] if len(x) else [np.nan]
    return f"{x.mean():+.3f} [{np.percentile(b,2.5):+.3f},{np.percentile(b,97.5):+.3f}] win {np.mean(x>0):.0%}"

if __name__ == "__main__":
    R = pd.concat([run(a) for a in ("BTC", "ETH")], ignore_index=True)
    R.to_parquet("data/hurdle_options.parquet")
    for kind, g in R.groupby("kind"):
        print(f"\n== {kind}: {len(g)} option trades (BTC {int((g.asset=='BTC').sum())}, ETH {int((g.asset=='ETH').sum())}); "
              f"median tte {g.tte_h.median():.0f}h; mark peak >=10x {np.mean(g.peak>=10):.1%}")
        for col, lab in (("r2h", "hold 2h"), ("rexp", "hold to expiry"), ("rhurdle", "hurdle target/trap + re-entry")):
            print(f"   {lab:<32} {summ(g, col)}")
        g2 = g[g.has_target]
        print(f"   (with a target hurdle ahead, n={len(g2)})  hurdle exits {summ(g2,'rhurdle')}   vs hold 2h {summ(g2,'r2h')}")
    R["half"] = np.where(R.t < R.t.median(), "1st", "2nd")
    print("\nby half (mean return, hurdle breaks vs control):")
    print(R.pivot_table(index="half", columns="kind", values=["r2h", "rhurdle", "rexp"], aggfunc="mean").round(3).to_string())
