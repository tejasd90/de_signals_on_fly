#!/usr/bin/env python3
"""weekend_trap.py -- are weekend breakouts traps? (promised 7 Oct, REVIEW_2026-10-15 open item)

His words, 7 Oct journal: "The reaching till 87-88k upmove was a trap. Trap often happen during weekends, I was
wrong to consider that as a genuine move. However I did realize this after it transitioned immediately into the
range on Monday morning 0530 candle."  4 Oct: "Although it is weekend (slight possibility that it is BECAUSE of
weekend so as to trap, although I doubt it)".

DATA  BTC/ETH perp MARK candles (no volume), 1h and 4h break bars; every outcome is read on 1h closes.
      Incomplete last bars are dropped. IST = UTC+5:30.

BREAK EVENTS (decision time T = close of the break bar; everything used is closed by T)
  nbar   close above the highest HIGH (below the lowest LOW) of the previous N bars, N = 24/72/168 hours of bars
         (72h is the headline). Level = that prior extreme. One event per direction per 24h: a raw break within
         24h of the previous raw break in the same direction is the same move and is skipped.
  tline  first close beyond a CONFIRMED levels.trendlines line (>= 3 touches, confirmed_i >= anchor2 + 5,
         break after confirmation). Rising support breaks DOWN, falling resistance breaks UP. The level after
         the break keeps following the line. Duplicate lines (same spot/tf/side/break bar) are counted once.
  weekend  T - 1s falls on Saturday or Sunday IST (i.e. the break bar closed between Sat 00:00 and Mon 00:00 IST).

(a) OUTCOMES from T, 1h closes
  rev24/48/72  any 1h close back on the other side of the broken level within 24/48/72h ("back inside").
  net24/48/96  move in the break direction from the break close to the 1h close 24/48/96h later, % and in
               ATR(14) of the break timeframe.
  Control: weekday breaks, re-weighted to the weekend breaks' mix of direction x vol regime (ATR/price,
  causal percentile vs the prior 180 days, tertiles) x break size (close beyond level in ATR, tertiles).

(b) HIS TRIGGER, weekend breaks only.  Monday session = Mon 05:30-11:30 IST = Mon 00:00-06:00 UTC (six 1h bars).
  EXTENDS = some Monday-session 1h HIGH exceeds every high since the break (up-breaks; LOW below every low for
  down-breaks), i.e. a new extreme in the break direction. NOT EXTENDING is the trap signal. Decision D = Mon 06:00
  UTC, when the session's last bar has closed. Outcomes from D: back inside within 24/48/72h (among those still
  beyond the level at D) and the FADE trade = move AGAINST the break direction from the D close at 24/48/96h.
  Weekday analog: weekday breaks with the next 00:00-06:00 UTC session judged the same way, to see whether
  "no extension -> reversion" is weekend-specific or just what failing breaks do.

CIs: weekly block bootstrap (weeks of T, IST), 2000 draws, 90% intervals. Halves split at the midpoint date.
"""
import time, numpy as np, pandas as pd
from levels import load_tf, atr, trendlines
from fastboot import week_codes, boot_diff, boot_mean

SPOTS = ("BTC", "ETH"); TFS = (60, 240); LOOKS = (24, 72, 168); COOL_H = 24
IST = 19800; NOW = time.time()

def load(spot, tf):
    a = load_tf(spot, tf); return a[a[:, 0] + tf * 60 <= NOW]

def ist_dow(T):            # weekday (Mon=0) of the IST instant just before T
    return pd.to_datetime(np.asarray(T, float) - 1 + IST, unit="s").dayofweek.values

def vol_pct(A, c, tf):
    """causal percentile of ATR/price vs the previous 180 days of the same series"""
    x = pd.Series(A / c); w = int(180 * 1440 / tf)
    return x.rolling(w, min_periods=w // 4).apply(lambda v: (v[:-1] < v[-1]).mean(), raw=True).to_numpy()

def nbar_events(a, A, VP, tf, look_h):
    t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]; N = look_h * 60 // tf; cool = COOL_H * 60 // tf
    hi = pd.Series(h).rolling(N).max().shift(1).to_numpy(); lo = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    out = []
    for sgn, raw, lev in ((1, c > hi, hi), (-1, c < lo, lo)):
        idx = np.where(raw)[0]; last = -10**9
        for i in idx:
            if i - last > cool and np.isfinite(A[i]) and A[i] > 0:
                out.append(dict(i=i, sgn=sgn, level=lev[i], slope=0.0, t_anchor=t[i]))
            last = i
    return out

def tline_events(a, A, tf):
    t, h, l = a[:, 0], a[:, 2], a[:, 3]; out = {}
    for L in trendlines(a, A, tf, max_span=400):
        b = L["break_i"]
        if b is None or b <= L["confirmed_i"]: continue
        i2 = L["anchor"][1]; ext = h if L["kind"] == "R" else l
        sgn = 1 if L["kind"] == "R" else -1
        out.setdefault((sgn, b), dict(i=b, sgn=sgn, level=ext[i2] + L["slope"] * (b - i2),
                                      slope=L["slope"] / (tf * 60), t_anchor=t[b]))   # slope per second
    return list(out.values())

def outcomes(ev, a, A, VP, tf, h1, spot, kind, look):
    t, c = a[:, 0], a[:, 4]; t1, H1, L1, C1 = h1[:, 0], h1[:, 2], h1[:, 3], h1[:, 4]; T1c = t1 + 3600
    rows = []
    for e in ev:
        i, s = e["i"], e["sgn"]; T = t[i] + tf * 60; px = c[i]
        lvl = lambda tt: e["level"] + e["slope"] * (tt - e["t_anchor"])          # line value at time tt
        j0 = np.searchsorted(T1c, T + 3600)                                       # first 1h bar closing after T
        if j0 + 96 >= len(t1): continue
        r = dict(spot=spot, tf=tf, kind=kind, look=look, tdec=T, sgn=s, px=px, A=A[i], vp=VP[i],
                 excess=s * (px - lvl(T)) / A[i], dow=int(ist_dow([T])[0]))
        r["weekend"] = r["dow"] >= 5
        jj = lambda TT: np.searchsorted(T1c, TT)                                  # 1h bar closing at TT
        for Hh in (24, 48, 72):
            seg = slice(j0, jj(T + Hh * 3600) + 1)
            r[f"rev{Hh}"] = bool((s * (C1[seg] - lvl(T1c[seg])) < 0).any())
        for Hh in (24, 48, 96):
            k = jj(T + Hh * 3600)
            r[f"net{Hh}"] = s * (C1[k] / px - 1) * 100; r[f"netA{Hh}"] = s * (C1[k] - px) / A[i]
        # next "Monday-style" session: 00:00-06:00 UTC. Weekend breaks -> Monday; weekday -> next day's 00 UTC.
        day0 = np.floor(T / 86400) * 86400
        if r["weekend"]:
            S = day0 + 86400 * ((7 - pd.Timestamp(day0, unit="s").dayofweek) % 7 or 7)
        else:
            S = day0 + 86400 if T > day0 else day0
        D = S + 6 * 3600; js, jd = jj(S + 3600), jj(D)
        if jd + 96 < len(t1) and T1c[js] == S + 3600 and T1c[jd] == D:
            pre = slice(j0, js)                                                    # 1h bars between T and S
            ext_pre = max(a[i, 2], H1[pre].max() if js > j0 else -np.inf) if s > 0 else \
                      min(a[i, 3], L1[pre].min() if js > j0 else np.inf)
            sess = slice(js, jd + 1)
            r["gap_h"] = (S - T) / 3600
            r["extends"] = bool(H1[sess].max() > ext_pre) if s > 0 else bool(L1[sess].min() < ext_pre)
            r["sess_rangeA"] = (H1[sess].max() - L1[sess].min()) / A[i]
            r["beyond_at_D"] = bool(s * (C1[jd] - lvl(D)) > 0)
            r["rev_before_D"] = bool((s * (C1[j0:jd + 1] - lvl(T1c[j0:jd + 1])) < 0).any())
            for Hh in (24, 48, 72):
                seg = slice(jd + 1, jj(D + Hh * 3600) + 1)
                r[f"Drev{Hh}"] = bool((s * (C1[seg] - lvl(T1c[seg])) < 0).any())
            for Hh in (24, 48, 96):
                k = jj(D + Hh * 3600)
                r[f"fade{Hh}"] = -s * (C1[k] / C1[jd] - 1) * 100; r[f"fadeA{Hh}"] = -s * (C1[k] - C1[jd]) / A[i]
        rows.append(r)
    return rows

def build():
    rows = []
    for spot in SPOTS:
        h1 = load(spot, 60)
        for tf in TFS:
            a = h1 if tf == 60 else load(spot, tf)
            A = atr(a[:, 2], a[:, 3], a[:, 4]); A = np.where(A > 0, A, np.nan); VP = vol_pct(A, a[:, 4], tf)
            for look in LOOKS:
                rows += outcomes(nbar_events(a, A, VP, tf, look), a, A, VP, tf, h1, spot, "nbar", look)
            rows += outcomes(tline_events(a, A, tf), a, A, VP, tf, h1, spot, "tline", 0)
    E = pd.DataFrame(rows)
    E["date"] = pd.to_datetime(E["tdec"] + IST, unit="s")
    E["week"] = (E["date"] - pd.to_timedelta(E["date"].dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    E["volT"] = pd.cut(E["vp"], [-1, 1 / 3, 2 / 3, 2], labels=False)
    E["excT"] = E.groupby(["tf", "kind", "look"])["excess"].transform(lambda x: pd.qcut(x, 3, labels=False, duplicates="drop"))
    return E

# ---- statistics ----------------------------------------------------------------------------------------------------
def matched_boot(D, y, n=2000, seed=0):
    """weekend rate, weekday rate re-weighted to the weekend strata mix, and the bootstrap of the difference."""
    D = D.dropna(subset=[y, "volT", "excT"])
    st = (D.sgn.map({1: 0, -1: 1}) * 9 + D.volT.astype(int) * 3 + D.excT.astype(int)).values
    code, nw = week_codes(D.week.values); v = D[y].astype(float).values; wk = D.weekend.values
    def sums(m):
        S = np.zeros((nw, 18)); C = np.zeros((nw, 18))
        np.add.at(S, (code[m], st[m]), v[m]); np.add.at(C, (code[m], st[m]), 1); return S, C
    SW, CW = sums(wk); SD, CD = sums(~wk)
    def stat(sw, cw, sd, cd):
        rd = np.divide(sd, cd, out=np.full_like(sd, np.nan), where=cd > 0)
        w = np.where(cd > 0, cw, 0); rw = (sw * (cd > 0)).sum(-1) / w.sum(-1)
        return rw, np.nansum(rd * w, -1) / w.sum(-1)
    rw, rm = stat(SW.sum(0), CW.sum(0), SD.sum(0), CD.sum(0))
    pick = np.random.default_rng(seed).integers(0, nw, size=(n, nw))
    bw, bm = stat(SW[pick].sum(1), CW[pick].sum(1), SD[pick].sum(1), CD[pick].sum(1))
    d = bw - bm; d = d[np.isfinite(d)]
    return dict(n_we=int(wk.sum()), n_wd=int((~wk).sum()), we=rw, wd_raw=v[~wk].mean(), wd_matched=rm,
                diff=rw - rm, lo=np.quantile(d, .05), hi=np.quantile(d, .95), p=(d <= 0).mean())

def diff_ci(D, y, sel):
    D = D.dropna(subset=[y]); code, nw = week_codes(D.week.values); s = D.eval(sel).values if isinstance(sel, str) else sel
    b = boot_diff(D[y].astype(float).values, code, nw, s)
    return dict(nA=int(s.sum()), nB=int((~s).sum()), A=D[y][s].mean(), B=D[y][~s].mean(),
                diff=D[y][s].mean() - D[y][~s].mean(), lo=np.quantile(b, .05), hi=np.quantile(b, .95), p=(b <= 0).mean())

def mean_ci(D, y):
    D = D.dropna(subset=[y]); code, nw = week_codes(D.week.values)
    b = boot_mean(D[y].astype(float).values, code, nw)
    return dict(n=len(D), mean=D[y].mean(), lo=np.quantile(b, .05), hi=np.quantile(b, .95), med=D[y].median())

if __name__ == "__main__":
    E = build(); E.to_parquet("data/weekend_trap_events.parquet")
    mid = E.tdec.min() + (E.tdec.max() - E.tdec.min()) / 2
    print(f"events {len(E):,}; halves split at {pd.Timestamp(mid + IST, unit='s').date()}")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    sets = {"1h 72h-high/low": "tf==60 and kind=='nbar' and look==72", "4h 72h-high/low": "tf==240 and kind=='nbar' and look==72",
            "1h 24h": "tf==60 and kind=='nbar' and look==24", "1h 168h": "tf==60 and kind=='nbar' and look==168",
            "4h 24h": "tf==240 and kind=='nbar' and look==24", "4h 168h": "tf==240 and kind=='nbar' and look==168",
            "1h trendline": "tf==60 and kind=='tline'", "4h trendline": "tf==240 and kind=='tline'"}
    print("\n(a) weekend vs matched weekday")
    out = []
    for name, q in sets.items():
        for sp in ("BTC", "ETH", "pooled"):
            D = E.query(q) if sp == "pooled" else E.query(q + f" and spot=='{sp}'")
            for y in ("rev24", "rev48", "rev72", "net24", "net48", "net96", "netA48"):
                r = matched_boot(D, y); out.append(dict(set=name, spot=sp, y=y, **r))
            for half, hq in (("H1", f"tdec<{mid}"), ("H2", f"tdec>={mid}")):
                for y in ("rev48", "net48"):
                    r = matched_boot(D.query(hq), y); out.append(dict(set=name, spot=sp + "-" + half, y=y, **r))
    R = pd.DataFrame(out); R.to_csv("data/weekend_trap_a.csv", index=False)
    print(R[R.y.isin(["rev48", "net48", "rev24", "net96"])].round(3).to_string())
    print("\nby IST weekday, pooled 1h+4h 72h breaks: rev48 / net48 / n")
    D = E.query("kind=='nbar' and look==72")
    print(D.groupby("dow").agg(n=("rev48", "size"), rev48=("rev48", "mean"), net48=("net48", "mean"),
                               netA48=("netA48", "mean")).round(3).to_string())
    print("\n(b) his trigger: weekend breaks, Monday session extends vs not")
    out = []
    for name, q in sets.items():
        for sp in ("BTC", "ETH", "pooled"):
            for grp in ("weekend", "not weekend"):
                D = E.query(q + f" and {grp}").dropna(subset=["extends"])
                if sp != "pooled": D = D[D.spot == sp]
                if len(D) < 10 or D.extends.all() or (~D.extends.astype(bool)).all(): continue
                Db = D[D.beyond_at_D.astype(bool)]
                for y, DD in (("Drev48", Db), ("Drev72", Db), ("fade24", D), ("fade48", D), ("fade96", D),
                              ("fadeA48", D), ("rev_before_D", D)):
                    if len(DD) < 10 or DD.extends.all() or (~DD.extends.astype(bool)).all(): continue
                    r = diff_ci(DD, y, ~DD.extends.astype(bool).values)
                    out.append(dict(set=name, spot=sp, grp=grp, y=y, **r))
    R = pd.DataFrame(out).rename(columns={"nA": "n_noext", "nB": "n_ext", "A": "noext", "B": "ext"})
    R.to_csv("data/weekend_trap_b.csv", index=False)
    print(R.round(3).to_string())
    print("\nfade after a NON-extending Monday (weekend breaks), mean with 90% CI")
    for name in ("1h 72h-high/low", "4h 72h-high/low", "1h trendline", "4h trendline"):
        D = E.query(sets[name] + " and weekend").dropna(subset=["extends"]); D = D[~D.extends.astype(bool)]
        for y in ("fade24", "fade48", "fade96", "fadeA48"):
            print(name, y, {k: round(v, 3) for k, v in mean_ci(D, y).items()})
    print("\ncase: breaks 3-7 Oct 2026")
    print(E[(E.tdec > pd.Timestamp("2026-10-02").timestamp()) & (E.tdec < pd.Timestamp("2026-10-08").timestamp())]
          [["spot", "tf", "kind", "look", "date", "sgn", "px", "weekend", "extends", "rev48", "net48", "fade48"]].to_string())
    print("\nTRADER RULE: break still beyond its level at Mon 11:30 IST AND the Monday session made no new extreme -> fade")
    print("(weekday analog = weekday break, next 05:30-11:30 IST session judged the same way)")
    out = []
    for name in ("1h 24h", "1h 72h-high/low", "4h 24h", "4h 72h-high/low", "1h trendline", "4h trendline"):
        D = E.query(sets[name]).dropna(subset=["extends"])
        D = D[(~D.extends.astype(bool)) & D.beyond_at_D.astype(bool)]
        for grp, G in (("weekend", D[D.weekend]), ("weekday", D[~D.weekend])):
            for sp in ("pooled", "BTC", "ETH", "H1", "H2"):
                S = G if sp == "pooled" else G[G.spot == sp] if sp in ("BTC", "ETH") else \
                    G[G.tdec < mid] if sp == "H1" else G[G.tdec >= mid]
                if len(S) < 5: continue
                r = dict(set=name, grp=grp, part=sp)
                for y in ("fade24", "fade48", "fade96", "fadeA48"):
                    m = mean_ci(S, y); r.update({"n": m["n"], y: m["mean"], y + "_lo": m["lo"], y + "_hi": m["hi"]})
                r["win48"] = (S.fade48 > 0).mean(); out.append(r)
    R = pd.DataFrame(out); R.to_csv("data/weekend_trap_rule.csv", index=False); print(R.round(2).to_string())
