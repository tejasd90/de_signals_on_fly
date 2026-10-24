"""His 2 Oct claim, re-tested on data the 2 Oct study never saw, and on the 5-20m signals it never had.

Exact words (2 Oct 10:30 IST): "the lower timeframes do wait after the signals (a few candles in their respective
timeframes) and then give breakout, whereas in higher timeframes either don't give the breakout or they don't wait.
... But the condition is that it should HOLD over the wait period, SL should not get hit at least for some
strikes. So the hold over wait period seems more reliable."

TF_REPEAT_HOLD.md (expiries to 16 Sep, 30m+, MARK) found: waiting 3 candles and buying only if held cuts the loss
(more value left at expiry) on 30m-3h, does NOT raise the 25x rate, nothing on 4h+.

Rows: tf_hold.work() on events.parquet (30m+) and data/events_lowtf.parquet (5-20m, build_events --min-duration 5
--max-duration 20). Periods: IS = expiries <= 2026-09-16 (35% sample, as before), OOS = 2026-09-17 .. latest settled
(all rows). Rule: SL = trigger candle's low, W = 3 candles, HELD = no low below SL; entry at close of candle W.
"Some strikes" version: an EVENT (one signal firing, several strikes) counts as held if ANY strike held; we then buy
the strikes that held. Value = 25 if the later high reaches 25x entry, else min(final close / entry, 25), before the
8.26% round-trip cost. CIs: expiry-block bootstrap."""
import sys, numpy as np, pandas as pd
from multiprocessing import Pool
from tf_hold import work
CUT = "2026-09-16"; W = 3

def rows(path, frac_is):
    d = pd.read_parquet(path, columns=["signal", "spot", "expiry", "duration", "symbol", "entry_ts", "event_id", "opt_type"])
    d = d[d.spot.isin(["BTC", "ETH"])]
    d = pd.concat([d[d.expiry <= CUT].sample(frac=frac_is, random_state=0), d[d.expiry > CUT]])
    d["f"] = "data/candles/" + d.spot + "/" + d.expiry + "/" + d.duration.astype(str) + "/" + d.symbol + ".json"
    jobs = [(f, list(zip(g.entry_ts, g.index))) for f, g in d.groupby("f")]
    with Pool(4) as p: res = [x for part in p.imap_unordered(work, jobs, chunksize=200) for x in part]
    R = pd.DataFrame(res).set_index("idx").join(d[["signal", "spot", "expiry", "duration", "event_id", "opt_type"]])
    return R

def boot(g, col_a, mask_a, col_b, mask_b, n=500):
    ex = g.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}
    a, ma, b, mb = g[col_a].values, mask_a.values, g[col_b].values, mask_b.values
    rng = np.random.default_rng(0); out = []
    for _ in range(n):
        s = np.concatenate([ix[e] for e in rng.choice(u, len(u))])
        out.append(a[s][ma[s]].mean() - b[s][mb[s]].mean())
    return np.nanpercentile(out, [2.5, 50, 97.5])

if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        R = pd.concat([rows("events.parquet", 0.35), rows("data/events_lowtf.parquet", 0.15)])
        R.to_parquet("data/tf_hold_oos.parquet"); print(f"wrote {len(R):,}"); sys.exit()
    R = pd.read_parquet("data/tf_hold_oos.parquet")
    R = R[R[f"held_{W}"].notna()].copy()
    R["held"] = R[f"held_{W}"].astype(bool)
    R["anyheld"] = R.groupby("event_id").held.transform("max")
    R["period"] = np.where(R.expiry <= CUT, "IS", "OOS")
    R["grp"] = pd.cut(R.duration, [0, 20, 60, 180, 2000], labels=["5-20m", "30-60m", "90-180m", "4h-1d"])
    print(f"rows {len(R):,}  OOS expiries {R[R.period == 'OOS'].expiry.nunique()} ({R[R.period == 'OOS'].expiry.min()} .. {R.expiry.max()})")
    T = lambda m: m.mean()
    fmt = lambda x: f"{x[1]:+.3f} [{x[0]:+.3f},{x[2]:+.3f}]"
    for by in (["period", "grp"], ["period", "grp", "opt_type"]):
        print(f"\n=== by {' / '.join(by)} === value before cost (25 cap); 25x / 100x rates; 'held-now' CI by expiry")
        for key, g in R.groupby(by, observed=True):
            if len(g) < 300: continue
            h = g.held; t = pd.Series(True, index=g.index)
            ci = boot(g, f"v25_{W}", h, "v25_0", t)
            print(f"  {' '.join(map(str, key)):<22} n {len(g):>7,}  held {h.mean():.0%}  "
                  f"now {g.v25_0.mean():.3f} 25x {g.h25_0.mean():.2%} 100x {g.h100_0.mean():.2%} | "
                  f"held {g.loc[h, f'v25_{W}'].mean():.3f} 25x {g.loc[h, f'h25_{W}'].mean():.2%} 100x {g.loc[h, f'h100_{W}'].mean():.2%} | "
                  f"broke {g.loc[~h, f'v25_{W}'].mean():.3f} 25x {g.loc[~h, f'h25_{W}'].mean():.2%} | held-now {fmt(ci)}  "
                  f"ran-in-wait {g[f'ran_{W}'].mean():.0%}")
    print(f"\n=== OOS by signal (30m-3h and 5-20m) ===")
    O = R[(R.period == "OOS") & R.grp.isin(["5-20m", "30-60m", "90-180m"])]
    for key, g in O.groupby(["signal", "grp"], observed=True):
        if len(g) < 300: continue
        h = g.held; ci = boot(g, f"v25_{W}", h, "v25_0", pd.Series(True, index=g.index))
        print(f"  {key[0]:<16} {key[1]:<8} n {len(g):>6,} held {h.mean():.0%}  now {g.v25_0.mean():.3f} -> held {g.loc[h, f'v25_{W}'].mean():.3f}  "
              f"25x {g.h25_0.mean():.2%} -> {g.loc[h, f'h25_{W}'].mean():.2%}  CI {fmt(ci)}")
    print("\n=== 'at least for some strikes': event held on ANY strike, buy the strikes that held vs all strikes now ===")
    for key, g in R.groupby(["period", "grp"], observed=True):
        m = g.anyheld & g.held
        print(f"  {' '.join(map(str, key)):<16} events held-any {g.groupby('event_id').anyheld.first().mean():.0%}  "
              f"value {g.loc[m, f'v25_{W}'].mean():.3f} vs now {g.v25_0.mean():.3f}; events none-held {g.loc[~g.anyheld, f'v25_{W}'].mean():.3f}")
