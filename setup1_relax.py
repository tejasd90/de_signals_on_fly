"""Setup 1 with the analyst-added restrictions removed one at a time (2026-10-09, his request).

His idea: quiet weekend + low-vol week + held up -> a big move. The kept setup ADDED: premium 2-20, calls
only, BTC/ETH only, cuts 0.3/0.3/0.6, signals >= 30m (events.parquet only holds >= 30m, so that one stays).
MARK outcomes, per event (strikes averaged), then the mean over events:
  stop  = activated rows, peak_vs_trigger (the y_* convention used in SETUPS.md)
  close = ALL rows, peak_vs_close (buy at the signal close; nearer the implementable traded headline)
Week-block bootstrap CI on the 25x rate. R5 (clean 20d uptrend) veto applied as in Setup 1 unless noted.
Picture features for XAUT are computed exactly as bigmoves.py does for BTC/ETH."""
import io, contextlib, numpy as np, pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    import r5_picture as RP
COST = 0.0826; rng = np.random.default_rng(0)

def cpct(s, win=365):
    v = s.to_numpy(); out = np.full(len(v), np.nan)
    for i in range(60, len(v)):
        w = v[max(0, i-win):i]; w = w[np.isfinite(w)]
        if len(w) >= 60 and np.isfinite(v[i]): out[i] = (w < v[i]).mean()
    return pd.Series(out, index=s.index)

def picture_feats(sym):
    h = pd.read_parquet(f"data/perp_candles/{sym}.parquet"); h["dt"] = pd.to_datetime(h.ts, unit="s"); h = h.set_index("dt").sort_index()
    h["lr"] = np.log(h.c).diff()
    d = h.resample("1D").agg(hi=("h", "max"), lo=("l", "min"), c=("c", "last"), rv=("lr", lambda x: np.sqrt((x**2).sum()))).dropna(subset=["c"])
    d["rng"] = (d.hi - d.lo) / d.c
    f = pd.DataFrame(index=d.index)
    f["rv7"] = d.rv.rolling(7).mean(); f["wkend"] = d.rng.where(d.index.weekday >= 5).rolling(7, min_periods=1).mean()
    f["dd7"] = d.c / d.c.rolling(7).max() - 1
    P = f.apply(cpct).shift(1); P["spot"] = sym.replace("USD", ""); P["day"] = P.index.normalize()
    return P.reset_index(drop=True)

F = pd.concat([picture_feats(s) for s in ("BTCUSD", "ETHUSD", "XAUTUSD")])
E = pd.read_parquet("events.parquet", columns=["spot", "opt_type", "entry_ts", "duration", "event_id", "activated",
                                               "entry_premium", "peak_vs_trigger", "peak_vs_close"])
E["t"] = E.entry_ts + E.duration * 60; E["day"] = pd.to_datetime(E.t, unit="s").dt.normalize()
E["pb"] = pd.cut(E.entry_premium, [0, 2, 20, 1e9], labels=["<2", "2-20", ">20"], right=False)
parts = []
for sp, g in E.groupby("spot"):
    try: ai_t, ai, rg_t, rg = RP.states(sp)
    except Exception: g = g.assign(rg=0); parts.append(g); continue
    j = np.searchsorted(rg_t, g.t.to_numpy(), side="right") - 1
    parts.append(g.assign(rg=np.where(j >= 0, rg[np.clip(j, 0, None)], 0)))
E = pd.concat(parts).merge(F, on=["spot", "day"], how="inner")
E["week"] = E.day.dt.to_period("W").astype(str)
print(f"rows {len(E):,}; assets {E.spot.value_counts().to_dict()}; days {E.day.min().date()} -> {E.day.max().date()}\n")

def rates(g, conv):
    if conv == "stop": g = g[g.activated]; x = g.peak_vs_trigger
    else: x = g.peak_vs_close
    ev = pd.DataFrame({T: (x >= T).groupby(g.event_id).mean() for T in (10, 25, 100)})
    wk = g.groupby("event_id").week.first()
    return ev, wk

def line(lab, g, conv="close", ci=True):
    if not len(g): print(f"  {lab:<44} n/a"); return
    ev, wk = rates(g, conv)
    if not len(ev): print(f"  {lab:<44} n/a"); return
    s = ""
    if ci and len(ev) > 20:
        u = wk.unique(); ix = {w: np.where(wk.to_numpy() == w)[0] for w in u}; v = ev[25].to_numpy()
        b = [v[np.concatenate([ix[w] for w in rng.choice(u, len(u))])].mean() for _ in range(500)]
        s = f"[{np.percentile(b,2.5):.1%},{np.percentile(b,97.5):.1%}]"
    print(f"  {lab:<44} ev {len(ev):>6} asset-days {g.groupby(["spot","day"]).ngroups:>4}  10x {ev[10].mean():5.1%}  25x {ev[25].mean():5.2%} {s:<14} 100x {ev[100].mean():5.2%}  EV25 {25*ev[25].mean()-1-COST:+.2f} EV100 {100*ev[100].mean()-1-COST:+.2f}")

pic = (E.wkend <= .3) & (E.rv7 <= .3) & (E.dd7 >= .6); nr5 = E.rg != 1
bt = E.spot.isin(["BTC", "ETH"])
for conv in ("close", "stop"):
    print(f"=== convention: {conv} ===")
    line("SETUP 1 as kept: BTC/ETH C 2-20 picture !R5", E[bt & (E.opt_type == "C") & (E.pb == "2-20") & pic & nr5], conv)
    print(" premium band removed / varied (BTC/ETH calls, picture, !R5):")
    for b in ("<2", "2-20", ">20"): line(f"   premium {b}", E[bt & (E.opt_type == "C") & (E.pb == b) & pic & nr5], conv)
    line("   ALL premiums", E[bt & (E.opt_type == "C") & pic & nr5], conv)
    print(" calls-only removed (BTC/ETH, picture, !R5):")
    for b in ("2-20", None):
        m = bt & (E.opt_type == "P") & pic & nr5 & ((E.pb == b) if b else True)
        line(f"   PUTS premium {b or 'all'}", E[m], conv)
        m = bt & pic & nr5 & ((E.pb == b) if b else True)
        line(f"   CALLS+PUTS premium {b or 'all'}", E[m], conv)
    print(" asset list removed (calls 2-20, picture, !R5):")
    for a in ("BTC", "ETH", "XAUT"): line(f"   {a}", E[(E.spot == a) & (E.opt_type == "C") & (E.pb == "2-20") & pic & nr5], conv)
    print(" reference: same population NOT on picture days (BTC/ETH calls 2-20, !R5):")
    line("   not picture", E[bt & (E.opt_type == "C") & (E.pb == "2-20") & ~pic & nr5], conv)
    line("   not picture, ALL premiums", E[bt & (E.opt_type == "C") & ~pic & nr5], conv)

print("\n=== threshold sweep (close convention, BTC/ETH calls, ALL premiums, !R5): 25x rate | days ===")
for w in (.2, .3, .4, .5):
    cells = []
    for d in (.4, .5, .6, .7, .8):
        m = bt & (E.opt_type == "C") & nr5 & (E.wkend <= w) & (E.rv7 <= w) & (E.dd7 >= d)
        ev, _ = rates(E[m], "close"); cells.append(f"dd7>={d}: {ev[25].mean():5.2%} ({E[m].day.nunique():>3}d)")
    print(f"  wkend,rv7<={w}:  " + "  ".join(cells))
print("\n=== same sweep, premium 2-20 ===")
for w in (.2, .3, .4, .5):
    cells = []
    for d in (.4, .5, .6, .7, .8):
        m = bt & (E.opt_type == "C") & nr5 & (E.pb == "2-20") & (E.wkend <= w) & (E.rv7 <= w) & (E.dd7 >= d)
        ev, _ = rates(E[m], "close"); cells.append(f"dd7>={d}: {ev[25].mean():5.2%} ({E[m].day.nunique():>3}d)")
    print(f"  wkend,rv7<={w}:  " + "  ".join(cells))
