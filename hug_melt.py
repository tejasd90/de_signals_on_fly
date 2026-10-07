"""Tejas's points 1-3 (2026-10-07) as one mechanism: price HUGS a line after a move into it
(point 1); while it waits, the attacking side's option premiums MELT; once they have melted
enough, defenders give up and attackers buy cheap, the line breaks and the move runs to where
the cheap options pay ~1:50 (point 3); a push made while premiums are still rich is thwarted and
leaves a HURDLE (point 2).

Lines: levels.all_levels on 1h candles (BTC, ETH), confirmed (>=3 rejections) horizontal and
trendlines, used only between confirmation and their own break.
HUG bar: close on the holding side (above a support / below a resistance) within HUG_ATR of the
line. Episode = consecutive hug bars (1-bar gaps allowed). It ends in a BREAK (a close beyond
the line by > BREAK_ATR) or a BOUNCE (close back out beyond LEAVE_ATR). Per bar only the nearest
line counts, so overlapping lines are not double counted.
IMPULSE: move toward the line over the 10 bars before the episode, in ATR.

  A  hazard: P(break within the next 2 bars | hugging for h hours), impulse vs no impulse
  B  melt:   same, split by the change in implied vol since the hug began (4h ATM straddle IV,
             1-3d tenor, data/short_straddles.parquet) -- falling IV = premiums melting
             beyond time decay
  C  target: after a break, the max move over 24h divided by the 1:50 required move on the
             attacking side at the break bar (immediate expiry, data/dashreq, mult=50 via
             the stored 1:100 numbers rescaled below)
  D  rich:   episode outcome (break vs bounce) by IV percentile at the episode start
Everything is causal: features use bars up to the decision bar; outcomes start after it.
"""
import numpy as np, pandas as pd, warnings, json, glob, os
import levels as LV
from wedge import line_at
warnings.filterwarnings("ignore")
HUG_ATR, BREAK_ATR, LEAVE_ATR, IMP_ATR = 0.5, 0.25, 1.0, 1.5

def episodes(asset, tf=60):
    """Bar by bar. Every active line's signed distance d (in ATR, >0 = holding side). An episode
    starts when some line is within [0, HUG_ATR]; it then follows THE LINE IT IS HUGGING (switching
    only to another line hugged on the same side). A break or bounce is judged against that line,
    however far the candle goes. (v1 picked the nearest line at each bar, so a candle that broke
    the hugged line by > 2 ATR made it disappear and the episode read as a "bounce" off a lower
    line: the 7 Oct 06:30 break, and the strongest breaks generally, were misfiled.)"""
    conf, arr = LV.all_levels(asset, tf)
    h, l, c = arr[:, 2], arr[:, 3], arr[:, 4]; A = LV.atr(h, l, c); n = len(arr)
    active = {}                                  # bar -> {li: d}
    for li, L in enumerate(conf):
        s = 1 if L["kind"] == "S" else -1
        i0 = L["confirmed_i"] + 1; i1 = L["break_i"] if L.get("break_i") else n - 1
        for i in range(i0, min(i1, n)):                  # up to, not including, the break bar
            if not np.isfinite(A[i]) or A[i] <= 0: continue
            v = line_at(L, arr, i)
            if np.isfinite(v) and v > 0: active.setdefault(i, {})[li] = (s, s * (c[i] - v) / A[i])
    rows, ep = [], None
    for i in range(n):
        lines = active.get(i, {})
        if ep is not None:
            cur = lines.get(ep["li"])
            if cur is None:                      # the line's life ended
                L = conf[ep["li"]]
                if L.get("break_i") is not None and L["break_i"] <= i:   # ...at its own recorded break (review D2)
                    ep["end"], ep["end_i"] = "break", L["break_i"]
                else:
                    ep["end"] = "open"
                rows.append(ep); ep = None
            else:
                d = cur[1]
                if d < -BREAK_ATR: ep["end"], ep["end_i"] = "break", i; rows.append(ep); ep = None; continue
                if d > LEAVE_ATR:  ep["end"], ep["end_i"] = "bounce", i; rows.append(ep); ep = None; continue
                hug = [(abs(dd), li) for li, (ss, dd) in lines.items() if ss == ep["side"] and 0 <= dd <= HUG_ATR]
                if hug:
                    ep["bars"].append(i); ep["li"] = min(hug)[1] if 0 > d or d > HUG_ATR else ep["li"]
                continue
        hug = [(abs(dd), li, ss) for li, (ss, dd) in lines.items() if 0 <= dd <= HUG_ATR]
        if hug:
            _, li, s = min(hug)
            # the move INTO the line: from the far-side extreme of the previous 6 bars (his
            # "downmove followed by a tight range"), not net travel over 10 bars, which on 7 Oct
            # reached back past the 21:00 drop to the earlier rise and read negative
            far = h[i-6:i].max() if s == 1 else l[i-6:i].min()
            imp = s * (far - c[i]) / A[i] if i >= 6 else np.nan
            ep = dict(asset=asset, li=li, side=s, start=i, bars=[i], imp=imp, end=None, end_i=None)
    return rows, arr, A

def iv_series(asset):
    T = pd.read_parquet("data/short_straddles.parquet")
    T = T[(T.asset == asset) & (T.tb.astype(str) == "1-3d")].groupby("t").iv.median().sort_index()
    return T

def boot_rate(x, n=2000):
    x = np.asarray(x, float); rng = np.random.default_rng(0)
    b = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return x.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)

out_hz, out_ep = [], []
for asset in ("BTC", "ETH"):
    eps, arr, A = episodes(asset)
    ts = arr[:, 0].astype(np.int64); c = arr[:, 4]; h = arr[:, 2]; l = arr[:, 3]
    iv = iv_series(asset); ivt = iv.index.to_numpy(); ivv = iv.to_numpy()
    def iv_at(t):                                 # last 4h straddle whose entry closed by t
        k = np.searchsorted(ivt, t, side="right") - 1
        return ivv[k] if k >= 0 and t - ivt[k] <= 8*3600 else np.nan
    ivpct = iv.rank(pct=True)                     # descriptive split only (not causal) -> see causal below
    for e in eps:
        if e["end"] == "open": continue
        start_t = ts[e["start"]] + 3600; iv0 = iv_at(start_t)
        for k, i in enumerate(e["bars"]):
            t = ts[i] + 3600
            brk = e["end"] == "break" and 0 < e["end_i"] - i <= 2
            out_hz.append(dict(asset=asset, h=k, imp=e["imp"], brk=brk, dlogiv=np.log(iv_at(t) / iv0) if iv0 and iv0 > 0 else np.nan,
                               t=t, side=e["side"]))
        # causal IV percentile at the start: vs the previous 180 days of this asset's straddle IV
        hist = iv[(iv.index < start_t) & (iv.index >= start_t - 180*86400)]
        p0 = (hist < iv0).mean() if len(hist) > 50 and np.isfinite(iv0) else np.nan
        rec = dict(asset=asset, side=e["side"], start_t=start_t, dur=len(e["bars"]), imp=e["imp"], end=e["end"], ivpct=p0)
        if e["end"] == "break":
            b = e["end_i"]; bt = ts[b] + 3600; s = e["side"]
            fut = range(b + 1, min(b + 25, len(c)))
            ext = max((s * (c[b] - l[j]) / c[b] if s == 1 else (h[j] - c[b]) / c[b]) for j in fut) * 100 if len(fut) else np.nan
            rec.update(break_t=bt, ext24=ext)
        out_ep.append(rec)
H = pd.DataFrame(out_hz); E = pd.DataFrame(out_ep)
H["yr"] = pd.to_datetime(H.t, unit="s").dt.year
print(f"episodes: {len(E)} (break {int((E.end=='break').sum())}, bounce {int((E.end=='bounce').sum())}); hug-hours {len(H):,}\n")

print("A. P(break within 2 bars | hugging h hours)  -- rising with h = 'the hug is a countdown'")
H["hb"] = pd.cut(H.h, [-1, 0, 2, 5, 11, 23, 1e9], labels=["0h", "1-2h", "3-5h", "6-11h", "12-23h", "24h+"])
H["impulse"] = np.where(H.imp >= IMP_ATR, "after a move INTO the line", "no impulse")
print(H.pivot_table(index="hb", columns="impulse", values="brk", aggfunc=["mean", "size"], observed=True).round(3).to_string())
for lab, g in H.groupby("impulse"):
    a, b = g[g.h == 0].brk, g[g.h >= 3].brk
    m0, l0, h0 = boot_rate(a); m3, l3, h3 = boot_rate(b)
    print(f"   {lab:<28} first hour {m0:.3f} [{l0:.3f},{h0:.3f}]  vs hugging 3h+ {m3:.3f} [{l3:.3f},{h3:.3f}]  (n {len(a)} / {len(b)})")

print("\nB. Same, split by implied-vol change since the hug began (falling IV = premiums melting beyond time decay)")
Hb = H.dropna(subset=["dlogiv"]).copy()
Hb["melt"] = pd.cut(Hb.dlogiv, [-9, -0.08, -0.02, 0.02, 9], labels=["IV down >8%", "down 2-8%", "flat", "IV up"])
print(Hb.pivot_table(index="hb", columns="melt", values="brk", aggfunc="mean", observed=True).round(3).to_string())
for lab, g in Hb[Hb.h >= 3].groupby("melt", observed=True):
    m, lo, hi = boot_rate(g.brk)
    print(f"   hugging >=3h, {lab:<12}: P(break next 2 bars) {m:.3f}  [{lo:.3f},{hi:.3f}]  n={len(g)}")

print("\nD. Episode outcome by IV percentile at the hug start (causal, vs prior 180 days)")
Ed = E.dropna(subset=["ivpct"]).copy(); Ed["ivq"] = pd.cut(Ed.ivpct, [-.01, 1/3, 2/3, 1.01], labels=["IV low", "IV mid", "IV high (rich)"])
for lab, g in Ed.groupby("ivq", observed=True):
    m, lo, hi = boot_rate(g.end == "break")
    print(f"   {lab:<15} P(episode ends in a BREAK) {m:.3f}  [{lo:.3f},{hi:.3f}]  n={len(g)}")
E.to_parquet("data/hug_episodes.parquet"); H.to_parquet("data/hug_hours.parquet")
