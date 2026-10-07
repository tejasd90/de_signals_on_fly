"""Should R5 step aside on picture days? (2026-10-07)

R4 = 4h always-in agrees (calls need 4h UP: close > EMA20 > EMA100, as paper_log.state_at).
R5 = skip when the daily chart has been in a CLEAN 20-day uptrend (efficiency > 0.35 and 20d return > 0).
Picture = quiet weekend & low-vol week & held up, known at the previous close (bigmoves.py).
Population: his CALL signals, activated, premium 2-20, one row per event, settled expiries 2024 -> 3 Oct 2026.
Outcome: y_25x on MARK for every event; TRADED 25x where picture_traded.py fetched prints (all picture-day
rows + a same-size random sample of other days, so traded rates per cell are estimates).
EV per unit at a 25x target with no recovery otherwise: 25*p - 1 - 0.0826 (as paper_log).
"""
import json, numpy as np, pandas as pd
COST = 0.0826

def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()
def grouped(spot, tf):
    a = np.asarray(json.load(open(f"data/spot_grouped/{spot}/{tf}.json")), float); return a[np.argsort(a[:, 0])]

def states(spot):
    a = grouped(spot, 240); c = a[:, 4]; ef, es = ema(c, 20), ema(c, 100)
    ai = np.where((c > ef) & (ef > es), 1, np.where((c < ef) & (ef < es), -1, 0)); ai_t = a[:, 0] + 240*60
    d = grouped(spot, 1440); c = d[:, 4]
    ret = np.r_[np.full(20, np.nan), c[20:] / c[:-20] - 1]; net = np.abs(np.r_[np.full(20, np.nan), c[20:] - c[:-20]])
    tot = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(20, min_periods=2).sum().to_numpy()
    eff = net / np.maximum(tot, 1e-12)
    rg = np.where((eff > .35) & (ret > 0), 1, np.where((eff > .35) & (ret < 0), -1, 0)); rg_t = d[:, 0] + 1440*60
    return ai_t, ai, rg_t, rg

R = pd.read_parquet("data/bigmoves_precursors.parquet")
R["spot"] = R.sym.str.replace("USD", ""); R["day"] = pd.to_datetime(R.day).dt.normalize()
R["pic"] = (R.wkend <= 0.3) & (R.rv7 <= 0.3) & (R.dd7 >= 0.6)
E = pd.read_parquet("events.parquet", columns=["spot", "opt_type", "entry_ts", "duration", "event_id", "activated", "entry_premium", "y_25x"])
E = E[E.activated & (E.opt_type == "C") & E.entry_premium.between(2, 20)]
E["close_t"] = E.entry_ts + E.duration*60
ev = E.groupby("event_id").agg(spot=("spot", "first"), t=("close_t", "first"), y25=("y_25x", "mean")).reset_index()
ev["day"] = pd.to_datetime(ev.t, unit="s").dt.normalize()
parts = []
for sp, g in ev.groupby("spot"):
    ai_t, ai, rg_t, rg = states(sp)
    i = np.searchsorted(ai_t, g.t.to_numpy(), side="right") - 1; j = np.searchsorted(rg_t, g.t.to_numpy(), side="right") - 1
    g = g.assign(ai=np.where(i >= 0, ai[np.clip(i, 0, None)], 0), rg=np.where(j >= 0, rg[np.clip(j, 0, None)], 0))
    parts.append(g)
ev = pd.concat(parts).merge(R[["spot", "day", "pic"]], on=["spot", "day"])
T = pd.read_parquet("data/picture_traded.parquet").groupby("event_id").y25_tr.mean()
ev["y25_tr"] = ev.event_id.map(T)
ev["week"] = ev.day.dt.to_period("W").astype(str)
weeks = ev.week.nunique()
rng = np.random.default_rng(0)

def stat(g, col="y25"):
    x = g[col].dropna()
    if not len(x): return "  n/a"
    wk = g.loc[x.index, "week"].to_numpy(); u = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in u}
    b = [x.to_numpy()[np.concatenate([ix[w] for w in rng.choice(u, len(u))])].mean() for _ in range(2000)]
    p = x.mean()
    return f"{p:6.2%} [{np.percentile(b,2.5):.2%},{np.percentile(b,97.5):.2%}]  EV {25*p-1-COST:+.2f}  n {len(x):>5} ({len(x)/weeks:.1f}/wk)"

print(f"{len(ev):,} call events over {weeks} weeks; R4 up {np.mean(ev.ai==1):.0%}, R5 clean uptrend {np.mean(ev.rg==1):.0%}, picture {ev.pic.mean():.0%}\n")
print("25x rate by cell (MARK)  [week-block CI]")
for lab, m in (("all calls", ev.ai.notna()),
               ("R4 up, R5 NOT vetoing (current A+ TAKE)", (ev.ai == 1) & (ev.rg != 1)),
               ("R4 up, R5 VETOING (clean uptrend)", (ev.ai == 1) & (ev.rg == 1)),
               ("   ...and a PICTURE day", (ev.ai == 1) & (ev.rg == 1) & ev.pic),
               ("   ...not a picture day", (ev.ai == 1) & (ev.rg == 1) & ~ev.pic),
               ("R5 VETOING, any R4, PICTURE", (ev.rg == 1) & ev.pic),
               ("PICTURE, any R4/R5", ev.pic),
               ("PICTURE and R4 up", ev.pic & (ev.ai == 1)),
               ("PICTURE and R4 NOT up", ev.pic & (ev.ai != 1))):
    print(f"  {lab:<44} {stat(ev[m])}")
print("\nDecision rules compared")
rules = {"A+ now: R4 & not R5": (ev.ai == 1) & (ev.rg != 1),
         "A+ with R5 lifted on picture days": (ev.ai == 1) & ((ev.rg != 1) | ev.pic),
         "picture only": ev.pic,
         "A+ now OR picture": ((ev.ai == 1) & (ev.rg != 1)) | ev.pic}
for lab, m in rules.items():
    print(f"  {lab:<36} MARK {stat(ev[m])}")
    print(f"  {'':<36} TRADED {stat(ev[m], 'y25_tr')}   (traded rows: all picture days + a sample of others)")
ev["yr"] = ev.day.dt.year
print("\nBy year, 25x MARK: A+ now | R5-vetoed picture days | picture only")
for y, g in ev.groupby("yr"):
    a = g[(g.ai == 1) & (g.rg != 1)].y25; b = g[(g.ai == 1) & (g.rg == 1) & g.pic].y25; c = g[g.pic].y25
    print(f"  {y}: {a.mean():.2%} (n {len(a)}) | {b.mean():.2%} (n {len(b)}) | {c.mean():.2%} (n {len(c)})")

print("\nThe reverse combination: picture days WITH R5's veto")
for lab, m in (("picture & NOT R5 (R5 keeps its veto)", ev.pic & (ev.rg != 1)),
               ("picture & NOT R5 & R4 up", ev.pic & (ev.rg != 1) & (ev.ai == 1))):
    print(f"  {lab:<40} MARK {stat(ev[m])}")
    print(f"  {'':<40} TRADED {stat(ev[m], 'y25_tr')}")
    g = ev[m]
    print("     by year:", {y: f"{x.y25.mean():.1%} (n {len(x)})" for y, x in g.groupby(g.day.dt.year)})
