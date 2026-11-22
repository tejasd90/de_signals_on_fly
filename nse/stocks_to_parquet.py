"""Daily stock candle files (nse/fetch_stocks.js) -> one parquet.  python nse/stocks_to_parquet.py <dir with 1d/NSE, 1d/BSE> <out.parquet>"""
import sys, os, glob, gzip, json
import numpy as np, pandas as pd
src, out = sys.argv[1], sys.argv[2]
parts = []
for x in ('NSE', 'BSE'):
    for f in sorted(glob.glob(os.path.join(src, '1d', x, '*.json.gz'))):
        j = json.load(gzip.open(f, 'rt'))
        if not j['rows']: continue
        a = np.array([r[1:6] for r in j['rows']], dtype='float64')
        parts.append(pd.DataFrame({'sym': j['s'], 'x': x, 'd': pd.to_datetime([r[0][:10] for r in j['rows']]),
                                   'o': a[:, 0].astype('float32'), 'h': a[:, 1].astype('float32'), 'l': a[:, 2].astype('float32'),
                                   'c': a[:, 3].astype('float32'), 'v': a[:, 4]}))
df = pd.concat(parts, ignore_index=True)
df['sym'] = df['sym'].astype('category'); df['x'] = df['x'].astype('category')
df.to_parquet(out, compression='zstd')
print(len(df), 'rows', df['sym'].nunique(), 'symbols', os.path.getsize(out) // 1_000_000, 'MB')
