"""His 15 Oct wish: an indicator that says 'the market is playing inside a range and has not printed a new price for
a long time' (stay out), and flags when a new price (close) appears (look again).
NEW PRICE at hour t = the hourly close is above the highest, or below the lowest, of the previous N hourly closes.
STALE = hours since the last new price. Outcome over the next 24h: biggest excursion from the close
(max(|high/close-1|, |low/close-1|)), share with an excursion >= 3% (what makes cheap options pay), and the
continuation share after a new price (moved further the same way by >= 1%). BTC/ETH MARK hourly, 2024 onward."""
import time, numpy as np, pandas as pd
from levels import load_tf
def table(spot, N, live=False):
    a = load_tf(spot, 60); a = a[a[:, 0] + 3600 <= time.time()]     # closed bars only (the newest file holds the forming bar)
    t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]; s = pd.Series(c)
    hi = s.shift(1).rolling(N).max().to_numpy(); lo = s.shift(1).rolling(N).min().to_numpy()
    up, dn = c > hi, c < lo; new = up | dn
    last = pd.Series(np.where(new, np.arange(len(c)), np.nan)).ffill().to_numpy(); stale = np.arange(len(c)) - last
    H = 24; fh = pd.Series(h[::-1]).rolling(H, min_periods=H).max().to_numpy()[::-1]; fl = pd.Series(l[::-1]).rolling(H, min_periods=H).min().to_numpy()[::-1]
    fh = np.r_[fh[1:], np.nan]; fl = np.r_[fl[1:], np.nan]
    exc = np.maximum(fh / c - 1, 1 - fl / c) * 100
    cont = np.where(up, fh / c - 1 >= 0.01, np.where(dn, 1 - fl / c >= 0.01, np.nan))
    rng = (hi / lo - 1) * 100
    D = pd.DataFrame(dict(spot=spot, t=t, stale=stale, new=new, exc=exc, cont=cont, rng=rng, c=c, hi=hi, lo=lo))
    return D if live else D.dropna(subset=["exc", "stale"])
if __name__ == "__main__":
    for N in (24, 72):
        D = pd.concat([table(s, N) for s in ("BTC", "ETH")]); D = D[D.t >= pd.Timestamp("2024-03-01").timestamp()]
        D["b"] = pd.cut(D.stale, [-1, 0, 6, 24, 48, 96, 1e9], labels=["new price now", "1-6h", "6-24h", "1-2d", "2-4d", ">4d"])
        print(f"\nN = {N}h lookback. Next 24h: median biggest excursion, share >= 3%, share of all hours")
        for b, g in D.groupby("b", observed=True):
            print(f"  {b:14s} hours {len(g)/len(D):5.1%}  excursion median {g.exc.median():.2f}%  >=3%: {(g.exc >= 3).mean():5.1%}"
                  + (f"   continued >= 1% same way: {g.cont.mean():.0%}" if b == "new price now" else ""))
        q = D.groupby("spot").rng.transform(lambda x: x.rank(pct=True))
        for lab, m in [("narrow range (bottom third) AND stale > 24h", (q < 1/3) & (D.stale > 24)), ("everything else", ~((q < 1/3) & (D.stale > 24)))]:
            g = D[m]; print(f"  {lab:45s} hours {m.mean():5.1%}  excursion {g.exc.median():.2f}%  >=3%: {(g.exc >= 3).mean():5.1%}")
        for s in ("BTC", "ETH"):
            x = table(s, N, live=True).iloc[-1]; print(f"  NOW {s} ({pd.Timestamp(x.t + 3600, unit='s', tz='UTC').tz_convert('Asia/Kolkata'):%d %b %H:%M} IST): {int(x.stale)}h since a new {N}h close; range {x.lo:,.1f} - {x.hi:,.1f} ({x.rng:.1f}%), last close {x.c:,.1f}")

def state(spot, N=72):
    """Live state for the dashboard: hours since the last new N-hour close, the range, and the verdict."""
    D = table(spot, N, live=True).dropna(subset=["stale", "rng"])
    x = D.iloc[-1]; pct = float((D.rng < x.rng).mean())
    stale, narrow = int(x.stale), pct < 1 / 3
    nw = D[D.stale == 0]; last_new = last_ts = None
    if len(nw): last_new = "up" if nw.iloc[-1].c > nw.iloc[-1].hi else "down"; last_ts = int(nw.iloc[-1].t) + 3600
    verdict = "NEW PRICE" if stale == 0 else ("STAY OUT" if narrow and stale > 24 else "INSIDE RANGE")
    return dict(spot=spot, N=N, close_ts=int(x.t) + 3600, close=float(x.c), hi=float(x.hi), lo=float(x.lo),
                range_pct=float(x.rng), range_pctile=pct, stale_h=stale, narrow=narrow, verdict=verdict,
                last_new=last_new, last_new_ts=last_ts)
