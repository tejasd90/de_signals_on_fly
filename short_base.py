"""Baseline seller P&L by moneyness x tte, after bid-side haircut and fees.

m = how far OTM the SOLD option is, % of spot (negative = ITM).
pnl is per 1 coin of notional, in % of spot -- comparable across strikes and
assets. Significance is clustered by expiry: every strike of one expiry shares
one S_T, so they are one observation, not hundreds.
"""
import numpy as np, pandas as pd
GST, FEE, CAP = 1.18, 0.0001, 0.035

def mbucket(m):
    return pd.cut(m, [-99,-5,-2,-0.75,-0.25,0.25,0.75,2,5,99],
                  labels=["ITM>5","ITM2-5","ITM.75-2","ITM.25-.75","ATM","OTM.25-.75","OTM.75-2","OTM2-5","OTM>5"])
def tbucket(t): return pd.cut(t, [0,24,72,200], labels=["<=1d","1-3d","3-8d"])

def costs():
    s = pd.read_csv("data/spread_snapshot.csv")
    s = s[(s.bid > 0) & (s.ask > 0) & (s.mark > 0)]
    s["m"] = np.where(s.typ=="C", (s.K-s.S)/s.S, (s.S-s.K)/s.S)*100
    s["sell_cost"] = ((s.mark - s.bid)/s.mark).clip(0, 1)     # seller hits the bid
    s["mb"], s["tb"] = mbucket(s.m), tbucket(s.tte_h)
    return s.groupby(["mb","tb"], observed=True).sell_cost.median().rename("hc"), s

def load():
    P = pd.read_parquet("data/short_panel.parquet")
    P["m"] = np.where(P.typ=="C", (P.K-P.S0)/P.S0, (P.S0-P.K)/P.S0)*100
    P["mb"], P["tb"] = mbucket(P.m), tbucket(P.tte_h)
    hc, _ = costs()
    P = P.join(hc, on=["mb","tb"]); P["hc"] = P.hc.fillna(hc.max())
    fee_in  = np.minimum(FEE*P.S0, CAP*P.prem)*GST
    fee_out = np.where(P.payoff > 0, np.minimum(FEE*P.S_T, CAP*P.payoff)*GST, 0)
    P["gross"] = (P.prem - P.payoff)/P.S0*100                        # at mark, no costs
    P["net"]   = (P.prem*(1-P.hc) - P.payoff - fee_in - fee_out)/P.S0*100
    P["win"]   = P.net > 0
    P = P[P.prem >= 0.0005*P.S0]                                     # drop sub-tick dust (<0.05% of spot)
    return P

def clustered(P, col="net"):
    g = P.groupby(["asset","expiry"])[col].mean()
    return g.mean(), g.std()/np.sqrt(len(g))*1.0, len(g)

if __name__ == "__main__":
    hc, s = costs()
    print("seller haircut (mark-bid)/mark, live snapshot medians:")
    print(hc.unstack().round(3).to_string(), "\n")
    P = load()
    print(f"{len(P):,} trades\n")
    rows = []
    for (tb, mb), g in P.groupby(["tb","mb"], observed=True):
        mu, se, n = clustered(g)
        rows.append(dict(tte=tb, money=mb, n_exp=n, trades=len(g), win=g.win.mean()*100,
                         gross=g.gross.mean(), net=mu, t=mu/se if se else np.nan,
                         prem=(g.prem/g.S0*100).mean(), worst=g.net.min()))
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("per-trade, % of spot notional (net = after bid haircut + fees, clustered by expiry):")
    print(R.round(3).to_string(index=False))
    print("\nby asset x year, ATM and OTM.25-2, all tte:")
    P["yr"] = pd.to_datetime(P.entry_t, unit="s").dt.year
    sub = P[P.mb.isin(["ATM","OTM.25-.75","OTM.75-2"])]
    for (a, y, tb), g in sub.groupby(["asset","yr","tb"], observed=True):
        mu, se, n = clustered(g); print(f"  {a} {y} {tb:>5}: net {mu:+.3f}%  t={mu/se:+.1f}  n_exp={n}  win {g.win.mean():.0%}")
