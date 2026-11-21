"""Signal bars against matched ordinary bars (nse/baseline.js output).

  python nse/baseline_report.py <baseline dir> [--out file.json]

Match: same expiry, index, timeframe, side, days-to-expiry bucket, out-of-the-money bucket and price bucket.
The control for a signal in a cell is every traded bar of that cell where THIS signal did not fire.
Only out-of-the-money bars with trigger close >= Rs 1. Firings in cells with no control bar are left out (coverage is shown).
Intervals: 90%, bootstrap over expiries (bars within one expiry are not independent).
"""
import sys, os, json, glob
import numpy as np

src = sys.argv[1]
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
DL = {'5': '5m', '10': '10m', '15': '15m', '25': '25m', '60': '1h', '75': '75m', '125': '125m', '1d': '1d', '1w': '1w'}
# rec[(signal, name, dur, side)][expiry] = [nf, f10, f25, f100, fEnd, c10, c25, c100, cEnd, nf_all]   (c* = expected from controls)
rec = {}
for f in sorted(glob.glob(os.path.join(src, '*.json'))):
    e = os.path.basename(f)[:-5]
    for name, cells in json.load(open(f)).items():
        for key, cell in cells.items():
            dur, side, tte, mny, px = key.split('|')
            if mny == 'itm' or px == '0': continue
            a = cell['a']
            for sig, s in cell['s'].items():
                r = rec.setdefault((sig, name, dur, side), {}).setdefault(e, np.zeros(10))
                r[9] += s[0]
                nc = a[0] - s[0]
                if nc <= 0: continue
                r[0] += s[0]; r[1] += s[1]; r[2] += s[2]; r[3] += s[4]; r[4] += s[5]
                r[5] += s[0] * (a[1] - s[1]) / nc; r[6] += s[0] * (a[2] - s[2]) / nc; r[7] += s[0] * (a[4] - s[4]) / nc; r[8] += s[0] * (a[5] - s[5]) / nc

rng = np.random.default_rng(7)
def summarise(keys):
    per = {}
    for k in keys:
        for e, v in rec[k].items(): per[e] = per.get(e, 0) + v
    if not per: return None
    M = np.array(list(per.values())); t = M.sum(0)
    if t[0] < 1: return None
    idx = rng.integers(0, len(M), (2000, len(M)))
    B = M[idx].sum(1); ok = B[:, 0] > 0; B = B[ok]
    def pair(i, j):
        d = (B[:, i] - B[:, j]) / B[:, 0] * 100
        return [round(t[i] / t[0] * 100, 2), round(t[j] / t[0] * 100, 2), round(float(np.percentile(d, 5)), 2), round(float(np.percentile(d, 95)), 2)]
    dEnd = (B[:, 4] - B[:, 8]) / B[:, 0]
    return {'expiries': len(M), 'firings': int(t[0]), 'coverage': round(t[0] / t[9] * 100, 1) if t[9] else 0,
            'p10': pair(1, 5), 'p25': pair(2, 6), 'p100': pair(3, 7),
            'end': [round(t[4] / t[0], 3), round(t[8] / t[0], 3), round(float(np.percentile(dEnd, 5)), 3), round(float(np.percentile(dEnd, 95)), 3)]}

def line(label, s):
    if not s: return
    star = lambda p: '*' if p[2] > 0 else ('-' if p[3] < 0 else ' ')
    print(f"{label:<44}{s['expiries']:>5}{s['firings']:>9}  " + '  '.join(f"{s[k][0]:>6.2f} vs {s[k][1]:>6.2f} [{s[k][2]:>+6.2f},{s[k][3]:>+6.2f}]{star(s[k])}" for k in ('p10', 'p25', 'p100')) +
          f"   {s['end'][0]:>6.3f} vs {s['end'][1]:>6.3f} [{s['end'][2]:>+7.3f},{s['end'][3]:>+7.3f}]{star(s['end'])}")

hdr = f"{'':<44}{'exp':>5}{'firings':>9}  {'>=10x % signal vs control [diff 90%]':<38}{'>=25x':<38}{'>=100x':<38}   hold to expiry (x of entry)"
sigs = sorted({k[0] for k in rec}); names = ['NIFTY', 'SENSEX', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'BANKEX', 'NIFTYNXT50']
res = {}
for title, groups in [
    ('BY SIGNAL AND SIDE, all indices and timeframes', [(f"{s} {sd}", lambda k, s=s, sd=sd: k[0] == s and k[3] == sd) for s in sigs for sd in 'CP']),
    ('BY SIGNAL AND INDEX', [(f"{s} {n}", lambda k, s=s, n=n: k[0] == s and k[1] == n) for s in sigs for n in names]),
    ('BY SIGNAL AND TIMEFRAME', [(f"{s} {DL[d]}", lambda k, s=s, d=d: k[0] == s and k[2] == d) for s in sigs for d in DL]),
    ('NIFTY BY SIGNAL, TIMEFRAME AND SIDE', [(f"NIFTY {s} {DL[d]} {sd}", lambda k, s=s, d=d, sd=sd: k[0] == s and k[1] == 'NIFTY' and k[2] == d and k[3] == sd) for s in sigs for d in DL for sd in 'CP']),
]:
    print('\n' + title); print(hdr)
    for label, pred in groups:
        s = summarise([k for k in rec if pred(k)]); line(label, s)
        if s: res[label] = s
if out: json.dump(res, open(out, 'w'), indent=1)
