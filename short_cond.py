"""Does any condition make option SELLING pay? Three tests, one yardstick.

Yardstick: EXCESS net P&L over the unconditional mean of the same cell
(asset x type x moneyness x tte), in % of spot. Unconditional selling nets ~0
after the bid haircut and fees (short_base.py), so a condition is worth
something only if its excess is positive, survives a week-block bootstrap, and
holds in both halves of time.

Entry is the first 4h panel bar AT OR AFTER the event's bar close, so the trade
never sees the bar that defined the event.

1. approach  -- his slant-vs-side idea in the seller frame. At a level break:
                steep approach   -> "won't push much further": sell OTM beyond (call on an up-break)
                sideways approach-> "won't fall back much":    sell OTM behind (put on an up-break)
2. opposite  -- a premium signal fires on a call -> sell the put, and vice versa.
3. iv/rv     -- straddle sold when implied (from the premium) is rich vs trailing realised.
"""
import numpy as np, pandas as pd, warnings
import levels as LV
from short_base import load
from short_panel import spot_series
warnings.filterwarnings("ignore")
H4 = 14400
P = load()
P = P[P.tb.isin(["<=1d","1-3d"])]
P["cell"] = P.groupby(["asset","typ","mb","tb"], observed=True).net.transform("mean")
P["ex"] = P.net - P.cell
SLIGHT = ["OTM.25-.75","OTM.75-2"]
key = P.set_index(["asset","entry_t","typ"]).sort_index()

def trades_for(asset, t_event, typ, mbs=SLIGHT):
    t = int(np.ceil(t_event / H4) * H4)
    try: g = key.loc[(asset, t, typ)]
    except KeyError: return None
    g = g[g.mb.isin(mbs)]
    return None if g.empty else (t, g.ex.mean(), g.net.mean(), g.win.mean())

def report(lab, E):
    """E: DataFrame with columns t, ex, net, win (one row per event)."""
    if len(E) < 20: print(f"  {lab:<46}{len(E):>6}  too few"); return
    wk = (E.t // (7*86400)).to_numpy(); u = np.unique(wk)
    ix = {w: np.where(wk == w)[0] for w in u}; rng = np.random.default_rng(0); bs = []
    for _ in range(2000):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))]); bs.append(E.ex.to_numpy()[s].mean())
    bs = np.array(bs); mid = np.median(E.t)
    h1, h2 = E[E.t < mid].ex.mean(), E[E.t >= mid].ex.mean()
    print(f"  {lab:<46}{len(E):>6}{E.win.mean():>7.0%}{E.net.mean():>+9.3f}{E.ex.mean():>+9.3f}"
          f"   CI[{np.percentile(bs,2.5):+.3f},{np.percentile(bs,97.5):+.3f}] P<=0 {(bs<=0).mean():.3f}"
          f"   halves {h1:+.3f} / {h2:+.3f}")

HDR = f"  {'':<46}{'events':>6}{'win':>7}{'net%':>9}{'excess':>9}"

# ---------- 1. approach ----------
print("\n1. APPROACH INTO A BROKEN LEVEL (seller frame)\n" + HDR)
rows = []
for spot in ("BTC","ETH"):
    for tf in (1440, 360, 240):
        conf, arr = LV.all_levels(spot, tf)
        if arr is None: continue
        h, l, c = arr[:,2], arr[:,3], arr[:,4]; A = LV.atr(h, l, c); N = 10
        for L in conf:
            i = L["break_i"]
            if not i or i < N+2 or A[i] <= 0: continue
            up = L["kind"] == "R"                                 # resistance broken = up-break
            net = (1 if up else -1)*(c[i-1]-c[i-1-N])/A[i]
            rows.append(dict(spot=spot, tf=tf, up=up, travel=net, t=int(arr[i,0]) + tf*60))
B = pd.DataFrame(rows).drop_duplicates(["spot","t","up"])
q1, q3 = B.travel.quantile(.25), B.travel.quantile(.75)
def run(sel, beyond):
    out = []
    for r in sel.itertuples():
        typ = ("C" if r.up else "P") if beyond else ("P" if r.up else "C")
        x = trades_for(r.spot, r.t, typ)
        if x: out.append(dict(zip(["t","ex","net","win"], x)))
    return pd.DataFrame(out)
print(f"  ({len(B)} breaks; travel q25 {q1:+.2f} ATR, q75 {q3:+.2f} ATR)")
report("STEEP -> sell BEYOND the level (his claim)",   run(B[B.travel >= q3], True))
report("SIDE  -> sell BEHIND the level (his claim)",   run(B[B.travel <= q1], False))
report("steep -> sell behind (reverse, control)",      run(B[B.travel >= q3], False))
report("side  -> sell beyond (reverse, control)",      run(B[B.travel <= q1], True))
report("any break -> sell behind (follow the break)",  run(B, False))
report("any break -> sell beyond (fade the break)",    run(B, True))

# ---------- 2. opposite of premium signals ----------
print("\n2. SELL THE OPPOSITE SIDE OF HIS PREMIUM SIGNALS\n" + HDR)
S = pd.read_parquet("events.parquet", columns=["signal","spot","opt_type","entry_ts","duration"]).drop_duplicates()
S["entry_ts"] = S.entry_ts + S.duration*60      # entry_ts is the trigger candle's OPEN; act after its close
for sig, g in S.groupby("signal"):
    out = []
    for r in g.drop_duplicates(["spot","opt_type","entry_ts"]).itertuples():
        x = trades_for(r.spot, r.entry_ts, "P" if r.opt_type == "C" else "C")
        if x: out.append(dict(zip(["t","ex","net","win"], x), asset=r.spot))
    E = pd.DataFrame(out).drop_duplicates(["t","asset"]) if out else pd.DataFrame()
    report(f"{sig}: sell opposite", E)

# ---------- 3. implied vs realised ----------
print("\n3. SHORT STRADDLE BY IMPLIED/REALISED (quintile cut on first half only)")
st = []
for a in ("BTC","ETH"):
    sp = pd.Series(spot_series(a)).sort_index()
    r2 = np.log(sp).diff()**2
    rv24 = np.sqrt(r2.rolling(24).sum()*365)                 # annualised, ending at bar open+1h
    rv120 = np.sqrt(r2.rolling(120).sum()*365/5)
    Q = P[(P.asset == a)]
    Q = Q.assign(dist=(Q.K-Q.S0).abs())
    Q = Q.loc[Q.groupby(["entry_t","expiry","typ"]).dist.idxmin()]
    for (t, e), g in Q.groupby(["entry_t","expiry"]):
        if set(g.typ) != {"C","P"} or g.K.nunique() != 1: continue
        S0, tte = g.S0.iloc[0], g.tte_h.iloc[0]/(365*24)
        iv = g.prem.sum()/(0.8*S0*np.sqrt(tte))
        b = t - 3600                                          # last bar fully closed at entry
        if b not in rv24.index: continue
        st.append(dict(asset=a, t=t, tb=g.tb.iloc[0], iv=iv, rv24=rv24[b], rv120=rv120[b],
                       net=g.net.sum(), ex=g.ex.sum(), win=g.net.sum() > 0))
T = pd.DataFrame(st).dropna(); T["ratio"] = T.iv/T.rv120; T["ratio24"] = T.iv/T.rv24
print(f"  {len(T):,} straddles; median IV {T.iv.median():.2f}, RV5d {T.rv120.median():.2f}; "
      f"unconditional straddle net {T.net.mean():+.3f}%")
mid = T.t.median()
for feat in ("ratio","ratio24","iv"):
    cuts = T[T.t < mid][feat].quantile([.2,.4,.6,.8]).to_numpy()
    T["q"] = np.searchsorted(cuts, T[feat])
    print(f"\n  by {feat} quintile\n" + HDR)
    for q in range(5): report(f"{feat} Q{q+1}", T[T.q == q][["t","ex","net","win"]])
T.to_parquet("data/short_straddles.parquet")
