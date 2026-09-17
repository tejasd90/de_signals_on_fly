"""
Exact simulator for the two-broker grid, Tejas's rules verbatim:
  A opens 1 LONG at every grid level crossed (up OR down)
  B opens 1 SHORT at every grid level crossed (up OR down)
  a leg books at +TP in its own direction; losers stay open
  constant size (no martingale)

Grid in LOG space => constant % spacing, the only way to compare a 2450 asset
with BTC running 30k -> 120k. P&L unit = fraction of ONE leg's notional.

Unrealised is tracked every bar in O(1) using
  sum_A (e^{x-e}-1) = e^x * sum_A e^{-e} - nA
so the equity curve includes floating loss, which is the number grid backtests
habitually drop (DECISION_DOCUMENT trap #5).
"""
import heapq, math, numpy as np, pandas as pd, glob, sys

def run_grid(px, d_pct=0.004, tp_pct=0.02, fee_pct=0.0004, cap=None):
    dl = math.log1p(d_pct); up = math.log1p(tp_pct)
    lp = np.log(np.asarray(px, float))
    A, B = [], []                 # A: min-heap entry logpx; B: max-heap (negated)
    SA = SB = 0.0                 # SA=sum e^{-entry}, SB=sum e^{+entry}
    realized = 0.0; fills = 0
    li = int(math.floor(lp[0]/dl)); peak = 0; worst = 0.0
    for x in lp:
        ni = int(math.floor(x/dl))
        if ni != li:
            step = 1 if ni > li else -1
            for k in range(li+step, ni+step, step):
                if cap and len(A)+len(B) >= 2*cap: break
                e = k*dl
                heapq.heappush(A, e);  SA += math.exp(-e)
                heapq.heappush(B, -e); SB += math.exp(e)
                fills += 2
            li = ni
        while A and A[0] <= x - up:
            e = heapq.heappop(A); SA -= math.exp(-e); realized += tp_pct; fills += 1
        while B and -B[0] >= x + up:
            e = -heapq.heappop(B); SB -= math.exp(e);  realized += tp_pct; fills += 1
        eq = realized + (math.exp(x)*SA - len(A)) + (SB*math.exp(-x) - len(B)) - fills*fee_pct
        worst = min(worst, eq); peak = max(peak, len(A)+len(B))
    x = lp[-1]
    unreal = (math.exp(x)*SA - len(A)) + (SB*math.exp(-x) - len(B))
    return dict(realized=realized, unreal=unreal, gross=realized+unreal,
                net=realized+unreal-fills*fee_pct, fees=fills*fee_pct, fills=fills,
                open_legs=len(A)+len(B), peak=peak, worst_eq=worst)

def fmt(tag, r, extra=""):
    roc = r['net']/r['peak'] if r['peak'] else 0
    print(f"{tag:<26} net {r['net']:+8.2f} = realized {r['realized']:+8.2f} "
          f"{r['unreal']:+8.2f} unreal {-r['fees']:+7.2f} fees | peak legs {r['peak']:5d} "
          f"| ret/peak-notional {roc*100:+6.2f}% | worst eq {r['worst_eq']:+8.2f} {extra}")

if __name__ == "__main__":
    leg = list(np.arange(2400, 2461, 1.0)); path = []
    for _ in range(20): path += leg + leg[::-1]
    print("=== the idealised path you described ===")
    fmt("oscillate 2400-2460 x20", run_grid(path))

    print("\n=== same vol, same length, but a random walk (200 seeds) ===")
    sd = np.diff(np.log(path)).std(); rng = np.random.default_rng(0)
    t = np.array([run_grid(2430*np.exp(np.cumsum(rng.normal(0,sd,len(path)))))['net']
                  for _ in range(200)])
    print(f"   net mean {t.mean():+.2f}  median {np.median(t):+.2f}  "
          f"p5 {np.percentile(t,5):+.2f}  p95 {np.percentile(t,95):+.2f}  P(>0) {(t>0).mean():.2f}")

    print("\n=== real Delta perps, hourly closes, 2.5y, d=0.4% tp=2% maker 0.04% ===")
    for s in ["BTCUSD","ETHUSD","SOLUSD","XRPUSD","DOGEUSD"]:
        f = f"data/perp_candles/{s}.parquet"
        try: dfr = pd.read_parquet(f)
        except Exception: continue
        c = dfr.sort_values(dfr.columns[0])["c"].to_numpy()
        fmt(f"{s} ({len(c)}h)", run_grid(c))

    print("\n=== control: same symbols, returns SHUFFLED (kills mean reversion) ===")
    for s in ["BTCUSD","ETHUSD","SOLUSD"]:
        c = pd.read_parquet(f"data/perp_candles/{s}.parquet").sort_values("ts")["c"].to_numpy() \
            if "ts" in pd.read_parquet(f"data/perp_candles/{s}.parquet").columns else None
        dfr = pd.read_parquet(f"data/perp_candles/{s}.parquet")
        c = dfr.sort_values(dfr.columns[0])["c"].to_numpy()
        r = np.diff(np.log(c)); rng = np.random.default_rng(1)
        outs = []
        for _ in range(30):
            sh = rng.permutation(r)
            outs.append(run_grid(c[0]*np.exp(np.cumsum(np.r_[0, sh])))['net'])
        outs = np.array(outs)
        print(f"   {s:<10} shuffled net mean {outs.mean():+8.2f}  p5 {np.percentile(outs,5):+8.2f}"
              f"  p95 {np.percentile(outs,95):+8.2f}")
