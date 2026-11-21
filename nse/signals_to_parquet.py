"""Signal JSON files (nse/signals_run.js output) -> one parquet.  python nse/signals_to_parquet.py <signals dir> <out.parquet>"""
import sys, json, glob, os
import pandas as pd
src, out = sys.argv[1], sys.argv[2]
parts = []
for f in sorted(glob.glob(os.path.join(src, '*', '*.json'))):
    rows = json.load(open(f))
    if not rows: continue
    d = pd.DataFrame(rows)
    for c in ('name', 'type', 'dur', 'view', 'signal', 'expiry'): d[c] = d[c].astype('category')
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
for c in ('name', 'type', 'dur', 'view', 'signal', 'expiry'): df[c] = df[c].astype(str).astype('category')
df['seq'] = pd.to_numeric(df['seq'], errors='coerce').astype('float32')
df['signalValue'] = pd.to_numeric(df['signalValue'], errors='coerce')
df.to_parquet(out, compression='zstd')
print(len(df), 'rows', os.path.getsize(out) // 1_000_000, 'MB'); print(df.dtypes); print(df.head(3).T)
