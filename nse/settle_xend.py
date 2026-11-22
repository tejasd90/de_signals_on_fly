"""Replace xEnd in signals.parquet by settlement value / entry (intrinsic value at the index close of expiry day).
The value written by signals_run.js is last close / entry, which is stale for contracts that stopped trading.
  python nse/settle_xend.py data/nse/signals.parquet data/nse/spot"""
import sys, os, gzip, json
import numpy as np, pandas as pd
pq, spot = sys.argv[1], sys.argv[2]
df = pd.read_parquet(pq)
if 'xEndLast' not in df: df['xEndLast'] = df['xEnd']
close = {}
for n in df['name'].astype(str).unique():
    f = os.path.join(spot, n + '.json.gz')
    if os.path.exists(f):
        for r in json.load(gzip.open(f, 'rt'))['c']['1d']: close[(n, r[0][:10])] = r[4]
st = np.array([close.get(k, np.nan) for k in zip(df['name'].astype(str), df['expiry'].astype(str))])
intr = np.where(df['type'].astype(str) == 'C', st - df['strike'], df['strike'] - st).clip(min=0)
df['settle'] = st
df['xEnd'] = np.where(df['entry'] > 0, np.round(intr / df['entry'], 2), 0.0)
df.loc[np.isnan(st), 'xEnd'] = np.nan
df.to_parquet(pq, compression='zstd')
m = df[(df['view'] == 'separate') & (df['vol'] > 0) & (df['entry'] >= 1)]
print(len(df), 'rows; no index close for', int(np.isnan(st).sum()))
print('mean value at expiry per Rs 1, settlement vs stale last close:')
print(m.groupby(['signal', 'type'], observed=True)[['xEnd', 'xEndLast']].mean().round(3))
