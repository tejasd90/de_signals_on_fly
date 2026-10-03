"""Two of Tejas's untested early observations (context/Claude_Conversation_001.pdf).

A. p17: "a sharp fall in premiums, especially around 2-3 days to expiry and near market close".
   Direction-neutral decay: an equidistant strangle (+-2% OTM, strikes fixed over each hour)
   hourly log-change, MARK, 60m. Averaged by IST hour of day x days to expiry. A smooth
   theta curve would decay faster as expiry nears; a CLIFF would show as one hour (or one
   DTE band) far below its neighbours. Spot moves add noise but are symmetric for a strangle.

B. p365: "market is in 3 modes positionally: 1. one side melt, other sideways (50-60%);
   2. both sides melt (30-40%); 3. one side melt, other multibagger (5-10%)".
   For every expiry with >= 7 days of life: a 5%-OTM call and put chosen 7 days before
   expiry, held to expiry. Per side: MB = peak >= 10x; MELT = ends <= 0.2x and never
   reached 2x; else SIDEWAYS. Then the frequency of each mode.
"""
import json, os, re, glob, numpy as np, pandas as pd
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")

def spot(asset):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)):
                if r[4] is not None: m[int(r[0]) + 3600] = float(r[4])     # keyed by close time
        except Exception: pass
    return m

def load(asset, e):
    d = f"data/candles/{asset}/{e}/60"; C, P = {}, {}
    if not os.path.isdir(d): return C, P
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if not m: continue
        try: rows = json.load(open(os.path.join(d, fn)))
        except Exception: continue
        (C if m.group(1) == "C" else P)[float(m.group(3))] = {int(r[0]) + 3600: (float(r[2]), float(r[4])) for r in rows if r[4] is not None}
    return C, P

A, B = [], []
for asset in ("BTC", "ETH"):
    sp = spot(asset)
    for e in sorted(os.listdir(f"data/candles/{asset}")):
        if e.startswith(".") or e < "2024-01-01" or pd.Timestamp(e) > pd.Timestamp.now() - pd.Timedelta(days=1): continue
        C, P = load(asset, e)
        if len(C) < 5 or len(P) < 5: continue
        kc, kp = np.array(sorted(C)), np.array(sorted(P)); exp_t = int(pd.Timestamp(e).timestamp()) + 43200
        # A: hourly strangle decay over the last 10 days
        for t in range(exp_t - 10*86400, exp_t, 3600):
            S = sp.get(t - 3600)
            if S is None: continue
            Kc = kc[np.abs(kc - S*1.02).argmin()]; Kp = kp[np.abs(kp - S*0.98).argmin()]
            try: v0 = C[Kc][t - 3600][1] + P[Kp][t - 3600][1]; v1 = C[Kc][t][1] + P[Kp][t][1]
            except KeyError: continue
            if v0 > 0 and v1 > 0:
                A.append((asset, e, (exp_t - t)/86400, ((t//3600) + 5.5) % 24 - 0.5, np.log(v1/v0)))   # IST hour the bar ENDS in
        # B: three modes, entered 7 days out
        t0 = exp_t - 7*86400; S0 = sp.get(t0)
        if S0 is None: continue
        sides = []
        for book, ks, sgn in ((C, kc, 1), (P, kp, -1)):
            k = ks[np.abs(ks - S0*(1 + sgn*0.05)).argmin()]; ser = book[k]
            if t0 not in ser or ser[t0][1] <= 0: sides = []; break
            e0 = ser[t0][1]; fut = [ser[x] for x in sorted(ser) if x > t0]
            if not fut: sides = []; break
            pk = max(h for h, _ in fut)/e0; fin = fut[-1][1]/e0
            sides.append("MB" if pk >= 10 else "MELT" if (fin <= 0.2 and pk < 2) else "SIDE")
        if len(sides) == 2:
            B.append((asset, e, 0, "+".join(sorted(sides))))

A = pd.DataFrame(A, columns=["asset", "expiry", "dte", "hour_ist", "lr"])
A["band"] = pd.cut(A.dte, [0, 1, 2, 3, 5, 10], labels=["0-1d", "1-2d", "2-3d", "3-5d", "5-10d"])
print("A. strangle (+-2% OTM) mean hourly log-change, %, by IST hour (bar ending) x days to expiry")
tab = A.pivot_table(index=A.hour_ist.round().astype(int) % 24, columns="band", values="lr", aggfunc="mean", observed=True)*100
print(tab.round(2).to_string())
print("\n   per-band mean, and the worst hour as a multiple of that band's median hour:")
for b in tab.columns:
    col = tab[b]; print(f"   {b}: mean {col.mean():+.2f}%/h   worst hour {col.idxmin():>2}:00 IST {col.min():+.2f}%  ({col.min()/col.median():.1f}x median)")
B = pd.DataFrame(B, columns=["asset", "expiry", "age", "mode"])
print(f"\nB. three modes, {len(B)} expiries with >=7d life, 5% OTM pair entered 7 days out")
lab = {"MELT+SIDE": "1. one melts, other sideways", "MELT+MELT": "2. both melt",
       "MB+MELT": "3. one melts, other multibagger", "SIDE+SIDE": "(both sideways)", "MB+SIDE": "(MB + sideways)", "MB+MB": "(both MB)"}
print(B["mode"].map(lab).value_counts(normalize=True).mul(100).round(1).to_string())
B["yr"] = B.expiry.str[:4]
print("\n   mode 3 (melt + multibagger) by year:", (B.assign(m3=B["mode"].str.contains("MB")).groupby("yr").m3.mean()*100).round(1).to_dict())
