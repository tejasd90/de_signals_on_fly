"""
Price action ON THE PREMIUM SERIES, not on the underlying.

Every feature in this project so far reads spot: trendlines, ATR, wedges,
always-in. The option enters only as a payoff to be scored. So his five named
signals -- premium rebounce, premium holding, stairs, wall, red squeeze -- were
never representable, because they describe the OPTION CHART's own behaviour.
Four of the five charts he sent were option charts.

That gap matters more than it looks: docs record that Delta serves historical OI
but NOT historical IV. The premium series is the only surviving record of IV. An
option that refuses to decay while time passes and spot moves against it is an
option whose IV is being bid -- information no spot feature can carry.

Operationalised over a window of H bars ending at the entry bar (never past it):
  hold     spot moved ADVERSELY and time ran, yet premium did not fall. IV proxy.
  rebounce premium bounced >=REB off its window low, still short of the high.
  stairs   >=2 up-legs, each a higher high, separated by quiet stretches.
  wall     a level touched >=3x near the window high and never cleared.
  squeeze  premium's own range contracting, majority red candles.

VECTORISED per contract. The first version called a per-entry feature function
10.3M times on 16-element slices and, together with an O(N)-per-week bootstrap,
ran 3h before being killed. Features are now computed for every bar of a contract
in one pass; the bootstrap lives in fastboot.py.
"""
import json, os, re, glob, sys
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
from datetime import datetime, timezone
from fastboot import week_codes, boot_diff

COST = 0.0826
RES = "15"
STEP = 4
MIN_PREM = 0.05
H = 16
REB = 0.25
CACHE = "data/premium_pa_cache2.npz"
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
NAMES = ["hold", "rebounce", "stairs", "wall", "squeeze"]

def load_spot(a):
    m = {}
    for p in glob.glob(f"data/spot_candles/{a}/{RES}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def contract_feats(o, h, l, c, sp, typ):
    """(T,5) bool array; row i uses bars [i-H+1 .. i] only. Rows < H-1 are False."""
    T = len(c)
    F = np.zeros((T, 5), bool)
    if T < H: return F
    W  = swv(c,  H)          # (T-H+1, H)
    Wh = swv(h,  H); Wl = swv(l, H); Wo = swv(o, H); Ws = swv(sp, H)
    end = np.arange(H - 1, T)
    good = np.isfinite(W).all(1) & np.isfinite(Ws).all(1) & (W[:, 0] > 0) & (Ws[:, 0] > 0)

    sm = (Ws[:, -1] - Ws[:, 0]) / Ws[:, 0] * 100
    adverse = -sm if typ == "C" else sm
    pchg = (W[:, -1] - W[:, 0]) / W[:, 0]
    hold = (adverse > 0.15) & (pchg > -0.02)

    lo = np.nanmin(Wl, 1); hi = np.nanmax(Wh, 1)
    kmin = np.nanargmin(Wl, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        reb = (lo > 0) & (kmin < H - 2) & (W[:, -1] / lo - 1 >= REB) & (W[:, -1] < hi * 0.98)

    with np.errstate(invalid="ignore", divide="ignore"):
        rng = (Wh - Wl) / np.maximum(W, 1e-9)
    med = np.median(rng, 1, keepdims=True)
    quiet = rng < med
    runmax = np.maximum.accumulate(Wh, axis=1)
    prev = np.concatenate([np.full((len(Wh), 1), -np.inf), runmax[:, :-1]], 1)
    prev_quiet = np.concatenate([np.zeros((len(Wh), 1), bool), quiet[:, :-1]], 1)
    stairs = ((Wh > prev) & prev_quiet & ~quiet).sum(1) >= 2

    with np.errstate(invalid="ignore", divide="ignore"):
        wall = ((np.abs(Wh - hi[:, None]) / np.maximum(hi[:, None], 1e-9) < 0.03).sum(1) >= 3) & (W[:, -1] < hi)

    r0 = rng[:, :H // 2].mean(1); r1 = rng[:, H // 2:].mean(1)
    red = (W < Wo).mean(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        squeeze = (r0 > 0) & (r1 / r0 < 0.7) & (red > 0.5)

    for k, v in enumerate((hold, reb, stairs, wall, squeeze)):
        F[end, k] = np.where(good, np.nan_to_num(v).astype(bool), False)
    return F

def scan():
    wks, dte, otms, sr, typs, feats, sret = [], [], [], [], [], [], []
    for asset in ("BTC", "ETH"):
        spot = load_spot(asset)
        if not spot: continue
        for day in sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith(".")):
            dd = f"data/candles/{asset}/{day}/{RES}"
            if not os.path.isdir(dd): continue
            for fn in os.listdir(dd):
                m = SYM.match(fn)
                if not m: continue
                typ, _, strike, _ = m.groups(); strike = float(strike)
                try: rr = json.load(open(os.path.join(dd, fn)))
                except Exception: continue
                if len(rr) < H + 6: continue
                a = np.array(rr, dtype=object)
                ts = a[:, 0].astype(np.int64)
                def col(j):
                    v = a[:, j]
                    return np.array([np.nan if x is None else float(x) for x in v])
                o, hh, ll, cc = col(1), col(2), col(3), col(4)
                sp = np.array([spot.get(int(t), np.nan) for t in ts])
                if not np.isfinite(cc[-1]): continue
                F = contract_feats(o, hh, ll, cc, sp, typ)
                idx = np.arange(H, len(cc) - 1, STEP)
                if len(idx) == 0: continue
                e = cc[idx]; s0 = sp[idx]
                ok = np.isfinite(e) & (e >= MIN_PREM) & np.isfinite(s0)
                idx = idx[ok]
                if len(idx) == 0: continue
                e, s0 = cc[idx], sp[idx]
                otm = (s0 - strike) / s0 * 100 if typ == "P" else (strike - s0) / s0 * 100
                wks.append(np.array([datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%GW%V") for t in ts[idx]]))
                dte.append((ts[-1] - ts[idx]) / 3600.0)
                otms.append(otm); sr.append(cc[-1] / e)
                typs.append(np.full(len(idx), typ))
                feats.append(F[idx])
                # DIRECTION CONTROL. Realised spot move from entry to the contract's
                # last bar. If a signal's edge is just exposure to a favourable spot
                # move, it dies once this is held fixed.
                s_end = sp[np.isfinite(sp)][-1] if np.isfinite(sp).any() else np.nan
                sret.append(s_end / s0 - 1.0)
        print(f"{asset}: {sum(len(x) for x in wks):,} entries", file=sys.stderr)
    return (np.concatenate(wks), np.concatenate(dte).astype(np.float32),
            np.concatenate(otms).astype(np.float32), np.concatenate(sr).astype(np.float32),
            np.concatenate(typs), np.concatenate(feats),
            np.concatenate(sret).astype(np.float32))

def report(wk, ev, F, title, mask):
    n = int(mask.sum())
    if n < 500: print(f"\n{title}: too few ({n})"); return
    code, nw = week_codes(wk[mask]); e = ev[mask]; f = F[mask]
    print(f"\n{title}   n={n:,}  weeks={nw}  base EV={e.mean():+.4f}")
    print(f"  {'signal':<10}{'fires':>9}{'rate':>8}{'EV':>10}{'dEV':>10}{'P(dEV>0)':>10}{'win%':>8}")
    for k, nm in enumerate(NAMES):
        s = f[:, k]
        if s.sum() < 200:
            print(f"  {nm:<10}{int(s.sum()):>9,}{'--':>8}"); continue
        d = boot_diff(e, code, nw, s, 2000, seed=k + 1)
        print(f"  {nm:<10}{int(s.sum()):>9,}{s.mean()*100:>7.1f}%{e[s].mean():>10.4f}"
              f"{e[s].mean()-e[~s].mean():>10.4f}{(d>0).mean():>10.3f}{(e[s]>0).mean()*100:>7.1f}%")

if __name__ == "__main__":
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        wk, dte, otm, sr, typ, F, sret = (z["wk"], z["dte"], z["otm"], z["sr"],
                                          z["typ"], z["F"], z["sret"])
        print(f"cache: {len(wk):,} entries", file=sys.stderr)
    else:
        wk, dte, otm, sr, typ, F, sret = scan()
        np.savez_compressed(CACHE, wk=wk, dte=dte, otm=otm, sr=sr, typ=typ, F=F, sret=sret)
        print(f"cached -> {CACHE}", file=sys.stderr)
    ev = sr - 1 - COST
    report(wk, ev, F, "=== ALL ===", np.ones(len(ev), bool))
    report(wk, ev, F, "=== OTM 2-15% ===", (otm >= 2) & (otm <= 15))
    report(wk, ev, F, "=== OTM 2-15%, PUTS ===", (otm >= 2) & (otm <= 15) & (typ == "P"))
    report(wk, ev, F, "=== OTM 2-15%, CALLS ===", (otm >= 2) & (otm <= 15) & (typ == "C"))
    report(wk, ev, F, "=== OTM 2-15%, >=12h to expiry ===", (otm >= 2) & (otm <= 15) & (dte >= 12))

    # ---- DIRECTION CONTROL ----------------------------------------------
    # The positive half of the result lives entirely in CALLS, whose base EV is
    # +0.236 -- that is 2024-2026 bull drift, not skill. Hold the realised spot
    # move fixed: inside a narrow band of forward spot return, a genuine signal
    # still separates, a trend-follower does not.
    base = (otm >= 2) & (otm <= 15)
    qs = np.nanquantile(sret[base], [0.2, 0.4, 0.6, 0.8])
    print("\n\n############ DIRECTION CONTROL: within buckets of realised spot move ############")
    print(f"spot-return quintile cuts: {np.round(qs*100,2)} %")
    edges = np.concatenate([[-np.inf], qs, [np.inf]])
    for t in ("C", "P"):
        for b in range(5):
            m = base & (typ == t) & (sret >= edges[b]) & (sret < edges[b+1])
            report(wk, ev, F, f"=== {'CALLS' if t=='C' else 'PUTS'} | spot move quintile {b+1} "
                              f"[{edges[b]*100:+.1f}%,{edges[b+1]*100:+.1f}%) ===", m)
