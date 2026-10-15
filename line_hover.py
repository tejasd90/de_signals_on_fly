"""His 15 Oct points on the BTC/ETH rising lines (from mid-Aug) that broke at 07:45 IST:
  (1) price HOVERED at the trendline for many hours before the break -> hovering should signal a break;
  (2) importance of a break: can it be ranked in advance (age, touches, timeframe), and does it follow through
      without the line being reclaimed?
  (3) since nobody knows how long the hover lasts, trade the NEXT or NEXT-TO-NEXT expiry.

Lines: levels.trendlines (>= 3 touches, causal confirmation) on BTC/ETH MARK, 4h and 6h. Ascending support (S)
breaks DOWN, descending resistance (R) breaks UP. Usable only after confirmation.
Episode: price comes within TOL_ATR x ATR of a confirmed line (a close within the band). It ends with
  break   a close beyond the line, or
  reject  a close AWAY_ATR x ATR away on the right side.
Hover = hours from the episode's first in-band close to its end. Episodes are deduped across near-identical
lines (same spot / side / end bar).
Expiry choice: at the moment a hover reaches H hours (causal: decided before the outcome) and at the break
close, buy the first-OTM option on the break side for expiry ranks 1/2/3 (the 3 nearest settling > 6h later);
record the best later high and the value 48h later / at settlement (15m MARK)."""
import os, re, json, sys, numpy as np, pandas as pd
from levels import load_tf, atr, trendlines, TOL_ATR, AWAY_ATR
TFS = (240, 360); HOVER_H = (12, 24, 48)

def episodes(spot, tf):
    a = load_tf(spot, tf); t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]
    A = atr(h, l, c); A = np.where(A > 0, A, np.nan); n = len(c); out = []
    for L in trendlines(a, A, tf, max_span=400):
        i2, m, kind = L["anchor"][1], L["slope"], L["kind"]
        ext = h if kind == "R" else l; line = lambda x: ext[i2] + m * (x - i2)
        start, k = None, L["confirmed_i"] + 1
        while k < n:
            if not np.isfinite(A[k]): k += 1; continue
            lv = line(k); d = (c[k] - lv) / A[k]          # signed distance in ATR
            beyond = d < 0 if kind == "S" else d > 0
            away = d >= AWAY_ATR if kind == "S" else d <= -AWAY_ATR
            if start is None and abs(d) <= TOL_ATR and not beyond: start = k
            if start is not None and (beyond or away):
                out.append(dict(spot=spot, tf=tf, kind=kind, start_t=t[start], end_t=t[k] + tf * 60,
                                hover_h=(t[k] + tf * 60 - t[start]) / 3600, outcome="break" if beyond else "reject",
                                touches=L["n_rej"], age_d=(t[k] - t[L["anchor"][0]]) / 86400, line=lv, close=c[k]))
                if beyond: break
                start = None
            k += 1
    E = pd.DataFrame(out)
    return E.sort_values("hover_h", ascending=False).drop_duplicates(["spot", "kind", "end_t", "outcome"]).sort_values("end_t"), a

def follow(E, a):
    """For breaks: move in the break direction 24/48/96h later and whether the line was reclaimed within 48h."""
    t, c = a[:, 0], a[:, 4]; rows = []
    for _, e in E[E.outcome == "break"].iterrows():
        i = np.searchsorted(t, e.end_t - 1)                # bar whose close is the break
        sgn = -1 if e.kind == "S" else 1; r = {}
        for H in (24, 48, 96):
            j = np.searchsorted(t, e.end_t + H * 3600 - 1)
            r[f"f{H}"] = sgn * np.log(c[min(j, len(c) - 1)] / e.close) * 100 if j < len(c) else np.nan
        j48 = np.searchsorted(t, e.end_t + 48 * 3600)
        seg = c[i:j48]                                     # i is already the first bar after the break
        r["reclaimed48"] = bool(((seg > e.line) if e.kind == "S" else (seg < e.line)).any()) if len(seg) else np.nan
        rows.append({**e.to_dict(), **r})
    return pd.DataFrame(rows)

# ---- options: expiry rank 1/2/3 ----------------------------------------------------------------------------------
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
_EXP = {}
def expiries(asset):
    if asset not in _EXP:
        _EXP[asset] = sorted(e for e in os.listdir(f"data/candles/{asset}") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e)
                             and os.path.isdir(f"data/candles/{asset}/{e}/15"))
    return _EXP[asset]

def option_outcome(asset, T, spot, typ):
    """First-OTM option of type typ for the 3 nearest expiries settling > 6h after T."""
    out = {}
    exps = [e for e in expiries(asset) if pd.Timestamp(e).timestamp() + 43200 > T + 6 * 3600][:3]
    for rank, e in enumerate(exps, 1):
        d = f"data/candles/{asset}/{e}/15"; ks = []
        for fn in os.listdir(d):
            m = SYM.match(fn)
            if m and m.group(1) == typ: ks.append((float(m.group(3)), fn))
        ks = sorted(k for k in ks if (k[0] < spot if typ == "P" else k[0] > spot))
        if not ks: continue
        K, fn = ks[-1] if typ == "P" else ks[0]
        try: r = np.array([[x[0], x[2], x[4]] for x in json.load(open(f"{d}/{fn}")) if x[4] is not None], float)
        except Exception: continue
        settle = pd.Timestamp(e).timestamp() + 43200; r = r[r[:, 0] + 900 <= settle]
        i = np.searchsorted(r[:, 0], T) - 1               # last 15m bar closed by T
        if i < 0 or i + 1 >= len(r) or r[i, 2] <= 0: continue
        p = r[i, 2]; j48 = min(np.searchsorted(r[:, 0], T + 48 * 3600), len(r) - 1)
        out[rank] = dict(expiry=e, tte_h=(settle - T) / 3600, prem=p, prem_pct=100 * p / spot, best=r[i + 1:, 1].max() / p,
                         v48=r[j48, 2] / p, settle_x=r[-1, 2] / p)
    return out

def opt_table(events, asset_col="spot"):
    rows = []
    for _, e in events.iterrows():
        typ = "P" if e.kind == "S" else "C"
        for rank, o in option_outcome(e[asset_col], e.at_t, e.px, typ).items():
            rows.append(dict(spot=e[asset_col], at_t=e.at_t, what=e.what, kind=e.kind, rank=rank, **o))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    E, F, EV = [], [], []
    for spot in ("BTC", "ETH"):
        for tf in TFS:
            e, a = episodes(spot, tf); E.append(e); F.append(follow(e, a))
            t, c = a[:, 0], a[:, 4]
            for _, x in e.iterrows():                       # causal decision moments
                if x.outcome == "break":
                    EV.append(dict(spot=spot, tf=tf, kind=x.kind, what="break", at_t=x.end_t, px=x.close))
                for H in HOVER_H:
                    if x.hover_h > H:                       # still hovering H hours in, outcome not yet known
                        T = x.start_t + H * 3600; j = np.searchsorted(t, T - tf * 60, side="right") - 1
                        EV.append(dict(spot=spot, tf=tf, kind=x.kind, what=f"hover{H}h", at_t=T, px=c[j]))
    E = pd.concat(E); F = pd.concat(F); EV = pd.DataFrame(EV).drop_duplicates(["spot", "kind", "what", "at_t"])
    E.to_parquet("data/line_hover_episodes.parquet"); F.to_parquet("data/line_hover_breaks.parquet")
    O = opt_table(EV); O.to_parquet("data/line_hover_options.parquet")
    print(f"episodes {len(E):,} (breaks {(E.outcome == 'break').sum()}, rejects {(E.outcome == 'reject').sum()})")
