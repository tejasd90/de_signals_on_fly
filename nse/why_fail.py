"""Why index-option firings fail: what the index had to do, and what it did.

  python nse/why_fail.py data/nse/signals.parquet data/nse/spot [--out data/nse/why_fail.parquet]

Per firing (stored view, traded bar, entry >= Rs 1, out of the money at the trigger):
  need   = distance from the index to the strike, % of index, at the trigger
  sig    = need / (daily volatility of the last 20 sessions x sqrt(sessions left)); "how many normal moves away"
  mfe    = furthest the index went TOWARDS the strike between the trigger bar's end and expiry, %
  end    = where it settled, % towards (+) or away (-)
  trend  = index return over the 5 sessions before the trigger, signed so + means "already going the option's way"
Index path from 5-minute index bars. Descriptive: no control group here (that is baseline_report.py).
"""
import sys, os, gzip, json
import numpy as np, pandas as pd

src, spotdir = sys.argv[1], sys.argv[2]
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'data/nse/why_fail.parquet'
NAMES = ['NIFTY', 'SENSEX', 'BANKNIFTY']
MIN = {'5': 5, '10': 10, '15': 15, '25': 25, '60': 60, '75': 75, '125': 125}
ts64 = lambda s: pd.to_datetime(s.str.slice(0, 19)).to_numpy('datetime64[m]')

d = pd.read_parquet(src, filters=[('view', '=', 'separate'), ('vol', '>', 0), ('entry', '>=', 1)])
d = d[d['name'].isin(NAMES)].copy()
for c in ('name', 'type', 'dur', 'signal', 'expiry'): d[c] = d[c].astype(str)
parts = []
for name in NAMES:
    sp = json.load(gzip.open(os.path.join(spotdir, name + '.json.gz'), 'rt'))['c']
    s5 = pd.DataFrame(sp['5'], columns=list('tohlcvi')[:len(sp['5'][0])]); t5 = ts64(s5['t']); hi = s5['h'].to_numpy(); lo = s5['l'].to_numpy(); cl = s5['c'].to_numpy()
    s1 = pd.DataFrame(sp['1d'], columns=list('tohlcvi')[:len(sp['1d'][0])]); day = ts64(s1['t']).astype('datetime64[D]'); dc = s1['c'].to_numpy()
    vol20 = pd.Series(dc).pct_change().rolling(20).std().shift(1).to_numpy()            # known before the day opens
    f = d[d['name'] == name].copy()
    t = ts64(f['ts']); tday = t.astype('datetime64[D]')
    end = t.copy()
    for k, m in MIN.items(): end[(f['dur'] == k).to_numpy()] += np.timedelta64(m, 'm')
    is_d = (f['dur'] == '1d').to_numpy(); end[is_d] = tday[is_d] + np.timedelta64(15 * 60 + 30, 'm')
    is_w = (f['dur'] == '1w').to_numpy(); end[is_w] = tday[is_w] + np.timedelta64(4, 'D') + np.timedelta64(15 * 60 + 30, 'm')   # week bars start Monday
    exp = pd.to_datetime(f['expiry']).to_numpy('datetime64[D]')
    i0 = np.searchsorted(t5, end, 'left')                                               # first 5m index bar after the trigger bar closed
    i1 = np.searchsorted(t5, exp + np.timedelta64(1, 'D'), 'left')                      # one past the last bar of expiry day
    ok = (i1 > i0) & f['spot'].notna().to_numpy()
    f = f[ok]; i0 = i0[ok]; i1 = i1[ok]; tday = tday[ok]; exp = exp[ok]; endt = end[ok]
    S0 = f['spot'].to_numpy(); K = f['strike'].to_numpy(float); call = (f['type'] == 'C').to_numpy()
    mx = np.empty(len(f)); mn = np.empty(len(f))
    order = np.argsort(i1, kind='stable'); b = 0
    while b < len(order):                                                               # per expiry: running max/min backwards from expiry close
        e = b; j1 = i1[order[b]]
        while e < len(order) and i1[order[e]] == j1: e += 1
        idx = order[b:e]; a = i0[idx].min()
        rmx = np.maximum.accumulate(hi[a:j1][::-1])[::-1]; rmn = np.minimum.accumulate(lo[a:j1][::-1])[::-1]
        mx[idx] = rmx[i0[idx] - a]; mn[idx] = rmn[i0[idx] - a]; b = e
    settle = cl[i1 - 1]
    sgn = np.where(call, 1.0, -1.0)
    f['need'] = sgn * (K - S0) / S0 * 100
    f['mfe'] = np.where(call, mx - S0, S0 - mn) / S0 * 100
    f['end'] = sgn * (settle - S0) / S0 * 100
    di = np.searchsorted(day, tday, 'left')                                             # position of the trigger day in the daily series
    left = np.searchsorted(day, exp, 'left') - di + 1                                   # sessions left, counting the trigger day
    f['sess'] = left
    f['sig'] = f['need'] / (vol20[np.clip(di, 0, len(dc) - 1)] * 100 * np.sqrt(np.maximum(left, 1)))
    p5 = dc[np.clip(di - 6, 0, len(dc) - 1)]; p1 = dc[np.clip(di - 1, 0, len(dc) - 1)]
    f['trend5'] = sgn * (p1 / p5 - 1) * 100                                             # five sessions ending the day before
    f['hour'] = pd.Series(endt).dt.hour.to_numpy() + pd.Series(endt).dt.minute.to_numpy() / 60
    f['dow'] = pd.Series(tday).dt.dayofweek.to_numpy()
    parts.append(f[f['need'] > 0])
w = pd.concat(parts, ignore_index=True)
w.to_parquet(out, compression='zstd')

def tab(t, col, edges, labels, title):
    g = t.groupby(pd.cut(t[col], edges, labels=labels, right=False), observed=True)
    r = pd.DataFrame({'firings': g.size(), '>=10x %': g['x'].apply(lambda s: (s >= 10).mean() * 100).round(2), '>=25x %': g['x'].apply(lambda s: (s >= 25).mean() * 100).round(2),
                      'end value/Rs1': g['xEnd'].mean().round(3), 'expiries': g['expiry'].nunique()})
    print('\n' + title); print(r.to_string())

sq = w[w['signal'].isin(['otm_red_squeeze', 'otm_red_squeeze_c2c'])].drop_duplicates(['sym', 'dur', 'ts'])
print(f"squeeze firings (either variant), NIFTY+SENSEX+BANKNIFTY, out of the money, entry >= Rs 1: {len(sq)} in {sq['expiry'].nunique()} expiries")
print(f">=10x {(sq['x'] >= 10).mean() * 100:.2f}%   >=25x {(sq['x'] >= 25).mean() * 100:.2f}%   >=100x {(sq['x'] >= 100).mean() * 100:.2f}%")
reached = sq['mfe'] >= sq['need']; way = sq['mfe'] >= 0.5 * sq['need']
print('\nWHAT THE INDEX DID AFTER THE FIRING')
for lab, m in (('index never got halfway to the strike', ~way), ('got halfway or more, never touched the strike', way & ~reached), ('touched the strike before expiry', reached)):
    s = sq[m]; print(f"  {lab:<48} {len(s) / len(sq) * 100:>5.1f}% of firings   >=10x {(s['x'] >= 10).mean() * 100:>5.2f}%   >=25x {(s['x'] >= 25).mean() * 100:>5.2f}%   expired with value {(s['end'] > s['need']).mean() * 100:>5.1f}%")
tab(sq, 'sig', [0, 0.5, 1, 1.5, 2, 3, 5, 99], ['<0.5', '0.5-1', '1-1.5', '1.5-2', '2-3', '3-5', '5+'], 'BY DISTANCE TO THE STRIKE, in normal moves for the time left')
tab(sq, 'sess', [1, 2, 3, 4, 6, 11, 21, 99], ['expiry day', '1 before', '2 before', '3-4', '5-9', '10-19', '20+'], 'BY SESSIONS LEFT')
tab(sq, 'entry', [1, 2, 5, 10, 20, 50, 1e9], ['1-2', '2-5', '5-10', '10-20', '20-50', '50+'], 'BY ENTRY PRICE')
tab(sq, 'trend5', [-99, -3, -1.5, -0.5, 0.5, 1.5, 3, 99], ['against >3%', 'against 1.5-3', 'against 0.5-1.5', 'flat', 'with 0.5-1.5', 'with 1.5-3', 'with >3%'], "BY THE INDEX'S PREVIOUS 5 SESSIONS (with = already moving the option's way)")
tab(sq[sq['dur'].isin(list(MIN))], 'hour', [9, 10, 11, 12, 13, 14, 15, 16], ['9-10', '10-11', '11-12', '12-13', '13-14', '14-15', '15+'], 'BY TIME OF DAY (intraday timeframes, bar close)')
tab(sq, 'dow', [0, 1, 2, 3, 4, 5], ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], 'BY WEEKDAY')
for nm in NAMES:
    s = sq[sq['name'] == nm]; print(f"\n{nm}: {len(s)} firings, >=10x {(s['x'] >= 10).mean() * 100:.2f}%, touched strike {(s['mfe'] >= s['need']).mean() * 100:.1f}%, median distance {s['sig'].median():.2f} normal moves")
