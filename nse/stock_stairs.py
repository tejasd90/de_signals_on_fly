"""Green stairs on stocks: daily, weekly and monthly bars, against ordinary bars of the same month.
Decisions and results: docs/ML/STOCK_STAIRS.md.

  python nse/stock_stairs.py data/nse/stocks_1d.parquet [--out data/nse/stock_stairs]

Per bar (stock x period) it writes: trailing stair run, 3-bar momentum, eligibility, and what the stock did after
(entry = next day's open). Then prints signal bars against (a) all eligible bars of the same month and
(b) eligible bars of the same month and the same 3-bar-momentum decile. Intervals: 90%, bootstrap over months.
"""
import sys, os
import numpy as np, pandas as pd

SRC = sys.argv[1]
OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'data/nse/stock_stairs'
MIN_TV = 1e7          # median traded value of the last 60 sessions, rupees (1 crore)
MIN_PRICE = 10.0
MAX_LOCKED = 0.10     # share of the last 60 sessions with high == low (circuit-locked or one-price days)
MAX_ZERO_VOL = 0.05
JUMP = 0.25           # a daily close-to-close move beyond this is treated as a data / corporate-action break
Y1, Y2 = 252, 504

def fwd_roll(a, n, fn):
    """fn over a[i+1 .. i+n] (strictly after i); NaN where the window is incomplete."""
    s = pd.Series(a[::-1])
    r = getattr(s.rolling(n, min_periods=n), fn)().to_numpy()[::-1]
    out = np.full(len(a), np.nan); out[:-1] = r[1:]
    return out

def one(sym, x, g):
    d = g['d'].to_numpy(); o = g['o'].to_numpy('float64'); h = g['h'].to_numpy('float64'); l = g['l'].to_numpy('float64')
    c = g['c'].to_numpy('float64'); v = g['v'].to_numpy('float64'); n = len(c)
    if n < 80: return None
    ret = np.zeros(n); ret[1:] = c[1:] / c[:-1] - 1
    jump = (np.abs(ret) > JUMP).astype(float)
    s = pd.Series
    tv = s(c * v).rolling(60, min_periods=60).median().to_numpy()
    locked = s((h == l).astype(float)).rolling(60, min_periods=60).mean().to_numpy()
    zero = s((v <= 0).astype(float)).rolling(60, min_periods=60).mean().to_numpy()
    jback = s(jump).rolling(60, min_periods=60).max().to_numpy()
    # outcomes for an entry at the OPEN of day e: close 1y/2y later, highest close on the way, any break on the way
    c1 = pd.Series(c).shift(-Y1).to_numpy(); c2 = pd.Series(c).shift(-Y2).to_numpy()
    mx1 = fwd_roll(c, Y1, 'max'); mx2 = fwd_roll(c, Y2, 'max'); mn1 = fwd_roll(c, Y1, 'min')
    j1 = fwd_roll(jump, Y1, 'max'); j2 = fwd_roll(jump, Y2, 'max')
    out = []
    for tf in ('D', 'W', 'M'):
        if tf == 'D': key = np.arange(n)
        elif tf == 'W': key = ((d.astype('datetime64[D]').astype(int) + 3) // 7)          # Monday-based weeks
        else: key = d.astype('datetime64[M]').astype(int)
        last = np.r_[np.nonzero(key[1:] != key[:-1])[0], n - 1]                             # index of each bar's last day
        first = np.r_[0, last[:-1] + 1]
        bo = o[first]; bc = c[last]
        green = bc > bo
        body = (bc - bo) / np.where(bo > 0, bo, np.nan)
        pg = np.r_[False, green[:-1]]; pb = np.r_[np.nan, body[:-1]]
        start = green & (~pg | (body < pb))                                                  # a green bar that begins a new stair
        grp = np.cumsum(start | ~green)
        run = np.where(green, pd.Series(np.ones(len(grp))).groupby(grp).cumsum().to_numpy(), 0).astype(int)
        mom3 = np.full(len(bc), np.nan); mom3[2:] = bc[2:] / bo[:-2] - 1
        e = last + 1; ok = e < n; ee = np.where(ok, e, n - 1)                               # entry day = next session
        ent = np.where(ok, o[ee], np.nan)
        elig = ok & (tv[last] >= MIN_TV) & (bc >= MIN_PRICE) & (locked[last] <= MAX_LOCKED) & (zero[last] <= MAX_ZERO_VOL) & (jback[last] == 0) & (ent > 0)
        # the entry day's own close counts, so windows start at e-1 (strictly after the bar)
        f = pd.DataFrame({'sym': sym, 'x': x, 'tf': tf, 'd': d[last], 'run': run, 'mom3': mom3.astype('float32'), 'elig': elig, 'entry': ent.astype('float32'),
                          'r1': (c1[ee] / ent - 1).astype('float32'), 'r2': (c2[ee] / ent - 1).astype('float32'),
                          'mx1': (mx1[last] / ent - 1).astype('float32'), 'mx2': (mx2[last] / ent - 1).astype('float32'),
                          'mn1': (mn1[last] / ent - 1).astype('float32'), 'j1': j1[last], 'j2': j2[last]})
        out.append(f[f['elig']].drop(columns='elig'))
    return pd.concat(out, ignore_index=True)

def build():
    df = pd.read_parquet(SRC).sort_values(['x', 'sym', 'd'])
    parts = []
    for (x, sym), g in df.groupby(['x', 'sym'], observed=True, sort=False):
        r = one(sym, x, g)
        if r is not None and len(r): parts.append(r)
    b = pd.concat(parts, ignore_index=True)
    for col in ('sym', 'x', 'tf'): b[col] = b[col].astype('category')
    b.to_parquet(OUT + '_bars.parquet', compression='zstd')
    return b

rng = np.random.default_rng(11)
def compare(b, mask, cols, by):
    """signal mean minus control mean inside each cell of `by`, weighted by signal count; bootstrap over months."""
    t = b.assign(sig=mask)
    g = t.groupby(by + ['sig'], observed=True)[cols].agg(['sum', 'count'])
    res = {}
    for col in cols:
        w = g[col].unstack('sig')
        if ('sum', True) not in w.columns: return None
        w = w[(w[('count', True)] > 0) & (w[('count', False)] > 0)]
        ns = w[('count', True)].to_numpy(); sm = w[('sum', True)].to_numpy(); cm = (w[('sum', False)] / w[('count', False)]).to_numpy() * ns
        mon = w.index.get_level_values(0); codes, _ = pd.factorize(mon); k = codes.max() + 1
        A = np.zeros((k, 3)); np.add.at(A, codes, np.c_[ns, sm, cm])
        tot = A.sum(0); idx = rng.integers(0, k, (1000, k)); B = A[idx].sum(1); B = B[B[:, 0] > 0]
        dd = (B[:, 1] - B[:, 2]) / B[:, 0]
        res[col] = (tot[1] / tot[0], tot[2] / tot[0], np.percentile(dd, 5), np.percentile(dd, 95), int(tot[0]), k)
    return res

def report(b):
    b = b.copy()
    b['m'] = b['d'].values.astype('datetime64[M]')
    b['x2'] = (b['r1'] >= 1).astype(float); b['t2'] = (b['mx1'] >= 1).astype(float); b['h1'] = (b['r1'] <= -0.5).astype(float)
    b['x3'] = (b['r2'] >= 2).astype(float); b['t5'] = (b['mx2'] >= 4).astype(float); b['r1c'] = b['r1'].clip(upper=9)
    one_y = b[(b['j1'] == 0) & b['r1'].notna()]
    two_y = b[(b['j2'] == 0) & b['r2'].notna()]
    names = {'r1c': 'mean 1y return', 'x2': 'P(2x at 1y)', 't2': 'P(touched 2x in 1y)', 'h1': 'P(-50% at 1y)', 'x3': 'P(3x at 2y)', 't5': 'P(touched 5x in 2y)'}
    for tf, tfn in (('M', 'MONTHLY'), ('W', 'WEEKLY'), ('D', 'DAILY')):
        for label, rule in (('run reaches 3', lambda t: t['run'] == 3), ('run reaches 4', lambda t: t['run'] == 4), ('run of 5 or more', lambda t: t['run'] >= 5)):
            print(f"\n{tfn} bars, {label}")
            for cname, by in (('same month', ['m']), ('same month and momentum decile', ['m', 'q'])):
                rows = []
                for frame, cols in ((one_y, ['r1c', 'x2', 't2', 'h1']), (two_y, ['x3', 't5'])):
                    t = frame[frame['tf'] == tf]
                    if 'q' in by:
                        t = t[t['mom3'].notna()].copy()
                        t['q'] = t.groupby('m')['mom3'].transform(lambda s: pd.qcut(s.rank(method='first'), 10, labels=False) if len(s) >= 50 else -1)
                        t = t[t['q'] >= 0]
                    r = compare(t, rule(t).to_numpy(), cols, by)
                    if r: rows += [(names[c],) + r[c] for c in cols]
                print(f"  against ordinary bars of the {cname}:")
                for nm, sv, cv, lo, hi, n, k in rows:
                    flag = '*' if lo > 0 else ('-' if hi < 0 else ' ')
                    print(f"    {nm:<22} signal {sv * 100:>7.2f}%  control {cv * 100:>7.2f}%  diff [{lo * 100:>+6.2f}, {hi * 100:>+6.2f}]{flag}  n={n} over {k} months")

if __name__ == '__main__':
    b = pd.read_parquet(OUT + '_bars.parquet') if os.path.exists(OUT + '_bars.parquet') and '--rebuild' not in sys.argv else build()
    print(len(b), 'eligible bars,', b['sym'].nunique(), 'symbols')
    report(b)
