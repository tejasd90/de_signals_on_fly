"""Tables from nse/stock_option_moves.js output.  python nse/stock_option_moves_report.py data/nse/stock_moves [--csv out.csv]"""
import sys, os, glob, json
import pandas as pd
src = sys.argv[1]
rows = []
for f in sorted(glob.glob(os.path.join(src, '20*.json'))):
    e = os.path.basename(f)[:-5]
    for rank, r in enumerate(json.load(open(f)), 1): rows.append(dict(r, expiry=e, rank=rank))
d = pd.DataFrame(rows)
if '--csv' in sys.argv: d.to_csv(sys.argv[sys.argv.index('--csv') + 1], index=False)
n = d.groupby('expiry').size()
print('monthly expiries:', len(n), '| stocks per expiry: median', int(n.median()), '| short months:', {k: int(v) for k, v in n[n < 0.8 * n.median()].items()})
full = d[d['expiry'].isin(n[n >= 0.8 * n.median()].index)]
print('\nPER EXPIRY: top 5 stocks by best option multiple (stock range % over the series in brackets)')
for e, g in d.groupby('expiry'):
    print(e, ' | '.join(f"{r['name']} {r['best']:.0f}x{r['bestSide']} [{r.get('range', float('nan')):.0f}%]" for _, r in g.head(5).iterrows()), f"| median stock {g['best'].median():.0f}x")
g = full.groupby('name')
t = pd.DataFrame({'months': g.size(), 'median best': g['best'].median().round(1), 'months >=10x': (g['best'].apply(lambda s: (s >= 10).mean()) * 100).round(0),
                  'months >=25x': (g['best'].apply(lambda s: (s >= 25).mean()) * 100).round(0), 'months >=50x': (g['best'].apply(lambda s: (s >= 50).mean()) * 100).round(0),
                  'top-10 finishes': g['rank'].apply(lambda s: (s <= 10).sum()), 'median rank': g['rank'].median(), 'median range %': g['range'].median().round(1),
                  'contracts >=10x per month': g['n10'].mean().round(1)})
t = t[t['months'] >= 12]
print('\nALL TIME, stocks with 12+ months, sorted by median best multiple: top 30'); print(t.sort_values('median best', ascending=False).head(30).to_string())
print('\nbottom 15'); print(t.sort_values('median best').head(15).to_string())
print('\noverall: median of best multiple per stock-month', d['best'].median(), '| share of stock-months with a contract >=10x', round((d['best'] >= 10).mean() * 100, 1), '% >=25x', round((d['best'] >= 25).mean() * 100, 1), '% >=100x', round((d['best'] >= 100).mean() * 100, 1), '%')
print('best side: calls', round((d['bestSide'] == 'C').mean() * 100), '%')
print('correlation of best multiple with stock range (log-log):', round(pd.concat([d['best'].clip(lower=1), d['range'].clip(lower=1)], axis=1).apply(lambda s: __import__('numpy').log(s)).corr().iloc[0, 1], 2))
print('how persistent is a stock\'s rank from one month to the next (rank correlation):', round(full.sort_values('expiry').assign(prev=lambda x: x.groupby('name')['rank'].shift())[['rank', 'prev']].corr(method='spearman').iloc[0, 1], 2))
