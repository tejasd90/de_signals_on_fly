#!/usr/bin/env python3
"""
step1_prepare.py — build the labelled dataset.  (v3: streaming, out-of-core)

v2 accumulated every row as a Python dict before handing it to pandas. A row
with 37 keys costs ~3.6 KB as a dict, so 10M rows needed ~36 GB before pandas
started. That is the OOM.

v3 never holds more than one file in memory:

    pass 1  each JSON file -> typed DataFrame -> downcast -> append to a
            Parquet shard.  Peak memory = one file.
    pass 2  DuckDB assigns episode ids with a SQL window function and samples
            rows per episode, spilling to disk as needed. Never loads the
            whole table.

Output is Parquet, not CSV (a 10M-row CSV is both huge and slow to re-read).

Usage, from the repo root:

    python3 step1_prepare.py --patterns data/patterns --target 25

    # filters
    python3 step1_prepare.py --patterns data/patterns --signal red_squeeze \
                             --spot BTC --duration 60 --target 25

    # ground-truth label instead of the in-row peakAfter
    python3 step1_prepare.py --patterns data/patterns \
                             --multibaggers data/multibaggers --target 25

ROW SAMPLING (--max-rows-per-episode, default 50)
Rows inside one episode are near-duplicate views of the same move. Keeping all
of them costs memory and adds no information. Sampling to 50 per episode
preserves every episode and every label while cutting the table by 10-50x.
Set 0 to keep everything.
"""

import argparse, json, os, shutil, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings(
    "ignore", message=".*DataFrame concatenation with empty or all-NA.*")

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    sys.exit("ERROR: pyarrow required.  pip install pyarrow duckdb")
try:
    import duckdb
except ImportError:
    sys.exit("ERROR: duckdb required.  pip install pyarrow duckdb")


# columns worth keeping — everything else is dropped during streaming
KEEP = [
    "signal", "spot", "expiry", "duration", "symbol", "type", "strike",
    "entryTs", "entryPrice", "tteHours", "spotPrice", "distancePct", "otm",
    "seqLength", "patternHigh", "patternLow", "triggerPrice",
    "ratio1", "ratio2", "firstBody", "lastBody", "triggerBody",
    "avgPrice", "cheapness", "dist", "logValue", "logJump", "equalSteps",
    "signalValue", "ratio", "univRatio", "state", "brokeOut", "holdCandles",
    "peakAfter",
]
CATEGORICAL = {"signal", "spot", "expiry", "type", "state"}


def walk_json(root):
    if os.path.isfile(root):
        yield root
        return
    if not os.path.isdir(root):
        sys.exit(f"ERROR: not found: {root}\n"
                 f"       From the repo root this is usually: data/patterns")
    for dirpath, _, names in os.walk(root):
        if os.path.basename(dirpath) == "_done":
            continue
        for n in sorted(names):
            if n.endswith(".json") and ".tmp" not in n:
                yield os.path.join(dirpath, n)


def to_hours(series):
    """entryTs is an ISO string; also accept epoch s/ms.
    pandas <3 parses to ns, pandas 3.x to us — never assume the unit."""
    s = pd.to_datetime(series, errors="coerce", utc=True)
    if s.notna().mean() > 0.8:
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        return (s - epoch).dt.total_seconds() / 3600.0
    n = pd.to_numeric(series, errors="coerce")
    mx = n.max()
    if pd.notna(mx) and mx > 1e12:
        return n / 3.6e6
    return n / 3600.0


def shrink(df):
    """Downcast to FIXED widths.

    Never downcast per-shard to the smallest type that fits THAT shard: one
    shard sees duration=60 (int8), another sees 180 (int16), and DuckDB takes
    its schema from the first file it reads -> cast error. Fixed int32/float32
    keeps every shard schema-identical.
    """
    for c in df.columns:
        if c in CATEGORICAL or df[c].dtype == object:
            if c not in ("entryTs", "symbol"):
                df[c] = df[c].astype("category")
            continue
        if pd.api.types.is_bool_dtype(df[c]):
            continue
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].astype("float32")
        elif pd.api.types.is_integer_dtype(df[c]):
            df[c] = df[c].astype("int32")
    return df


def stream_patterns(root, shard_dir, signal, spot, duration, batch_files=200):
    """Pass 1: JSON tree -> Parquet shards. Peak memory = one batch."""
    os.makedirs(shard_dir, exist_ok=True)
    buf, nfiles, nrows, nshard, nskip = [], 0, 0, 0, 0
    matched_files = 0

    def flush():
        nonlocal buf, nshard
        if not buf:
            return
        df = pd.concat(buf, ignore_index=True)
        buf = []
        df["_ts_hours"] = to_hours(df["entryTs"])
        df = df[df["_ts_hours"].notna()]
        if df.empty:
            return
        df = shrink(df)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       os.path.join(shard_dir, f"part-{nshard:05d}.parquet"),
                       compression="zstd")
        nshard += 1

    for path in walk_json(root):
        parts = os.path.normpath(path).split(os.sep)
        if signal and signal not in parts:
            continue
        if spot and spot not in parts:
            continue
        if duration and str(duration) not in parts:
            continue
        matched_files += 1
        try:
            data = json.load(open(path))
        except Exception:
            nskip += 1
            continue
        if isinstance(data, dict):
            data = data.get("rows") or data.get("signals") or []
        if not isinstance(data, list) or not data:
            continue

        df = pd.DataFrame(data)
        keep = [c for c in KEEP if c in df.columns]
        if not keep:
            continue
        df = df[keep]
        buf.append(df)
        nfiles += 1
        nrows += len(df)

        if nfiles % batch_files == 0:
            flush()
            print(f"  {nfiles:,} files, {nrows:,} rows -> {nshard} shards",
                  end="\r", flush=True)
    flush()
    print(f"  {nfiles:,} files, {nrows:,} rows -> {nshard} shards" + " " * 20)
    if nskip:
        print(f"  ({nskip} unreadable files skipped)")
    if matched_files == 0:
        sys.exit(f"ERROR: no files matched under {root}"
                 + (f" for signal={signal}" if signal else "")
                 + (f", spot={spot}" if spot else "")
                 + (f", duration={duration}" if duration else ""))
    if nrows == 0:
        sys.exit(f"ERROR: matched {matched_files} files but they contained no "
                 f"rows. Has patterns.js run for this range?")
    return nrows


def stream_multibaggers(root, out_path):
    recs, n = [], 0
    for path in walk_json(root):
        try:
            payload = json.load(open(path))
        except Exception:
            continue
        spot = os.path.basename(os.path.dirname(path))
        expiry = os.path.splitext(os.path.basename(path))[0]
        items = None
        if isinstance(payload, dict):
            for k in ("instruments", "results", "rows", "trades",
                      "multibaggers", "best"):
                if isinstance(payload.get(k), list):
                    items = payload[k]
                    break
            if items is None:
                cand = {k: v for k, v in payload.items() if isinstance(v, dict)}
                if cand:
                    items = [dict(v, symbol=k) for k, v in cand.items()]
        elif isinstance(payload, list):
            items = payload
        for it in (items or []):
            if isinstance(it, dict) and "ratio" in it:
                recs.append((spot, expiry, it.get("symbol"), it.get("ratio")))
                n += 1
    if not recs:
        sys.exit(f"ERROR: no ratio records found under {root}")
    df = pd.DataFrame(recs, columns=["spot", "expiry", "symbol", "mb_ratio"])
    df.to_parquet(out_path, index=False)
    print(f"  {n:,} multibagger records")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", default="data/patterns")
    ap.add_argument("--multibaggers", default=None)
    ap.add_argument("--signal", default=None)
    ap.add_argument("--spot", default=None)
    ap.add_argument("--duration", default=None)
    ap.add_argument("--target", type=float, default=25.0)
    ap.add_argument("--episode-hours", type=float, default=24.0,
                    help="bucket width in hours; rows on one underlying inside "
                         "one bucket are ONE event")
    ap.add_argument("--episode-key", choices=["time", "expiry"], default="time",
                    help="'time' = fixed hour buckets; 'expiry' = one episode "
                         "per (underlying, expiry)")
    ap.add_argument("--min-entry-price", type=float, default=0.0,
                    help="tradeability floor: drop signals on options cheaper "
                         "than this. Sub-tick premiums make 25x meaningless.")
    ap.add_argument("--max-rows-per-episode", type=int, default=50,
                    help="0 = keep all. Rows in one episode are near-duplicates.")
    ap.add_argument("--memory-limit", default="6GB",
                    help="DuckDB memory cap; it spills to disk beyond this")
    ap.add_argument("--threads", type=int, default=4,
                    help="DuckDB threads; lower uses less memory")
    ap.add_argument("--chunk-episodes", type=int, default=200,
                    help="episodes processed per output part; lower = less "
                         "memory")
    ap.add_argument("--work-dir", default="_prep")
    ap.add_argument("--out", default="dataset.parquet")
    args = ap.parse_args()

    print("=" * 70)
    print("STEP 1 — build labelled dataset (streaming)")
    print("=" * 70)

    shard_dir = os.path.join(args.work_dir, "shards")
    if os.path.exists(shard_dir):
        shutil.rmtree(shard_dir)
    os.makedirs(args.work_dir, exist_ok=True)

    print(f"\npass 1: streaming {args.patterns} -> parquet shards")
    total_rows = stream_patterns(args.patterns, shard_dir, args.signal,
                                 args.spot, args.duration)

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{os.path.join(args.work_dir, 'tmp')}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET threads={args.threads}")

    src = os.path.join(shard_dir, "*.parquet").replace("\\", "/")
    cols = [d[0] for d in con.execute(
        f"SELECT * FROM read_parquet('{src}', union_by_name=true) LIMIT 0").description]
    print(f"\ncolumns kept: {cols}")

    for c in ("spot", "_ts_hours"):
        if c not in cols:
            sys.exit(f"ERROR: expected column '{c}'. Found: {cols}")

    if "signal" in cols:
        print("\nrows per signal:")
        for s, n in con.execute(
                f"SELECT signal, count(*) c FROM read_parquet('{src}', union_by_name=true) "
                f"GROUP BY signal ORDER BY c DESC").fetchall():
            print(f"  {str(s):22} {n:>12,}")

    # ---- label -----------------------------------------------------------
    if args.multibaggers:
        print(f"\nreading {args.multibaggers}")
        mbp = stream_multibaggers(args.multibaggers,
                                  os.path.join(args.work_dir, "mb.parquet"))
        join_keys = [k for k in ("spot", "expiry", "symbol") if k in cols]
        on = " AND ".join(f"p.{k}=m.{k}" for k in join_keys)
        base = (f"SELECT p.*, m.mb_ratio AS _peak FROM read_parquet('{src}', union_by_name=true) p "
                f"LEFT JOIN (SELECT DISTINCT {','.join(join_keys)}, mb_ratio "
                f"FROM read_parquet('{mbp}', union_by_name=true)) m ON {on}")
        matched = con.execute(
            f"SELECT count(_peak) FROM ({base})").fetchone()[0]
        print(f"  joined on {join_keys}: {matched:,}/{total_rows:,} matched "
              f"({matched/max(total_rows,1)*100:.1f}%)")
        if matched == 0:
            sys.exit("ERROR: join matched nothing. Check that expiry/symbol "
                     "strings agree between the two trees.")
    else:
        # `ratio` = "Peak high after entry / entry close" -> the MULTIPLE.
        # `peakAfter` = "Highest price after the signal candle" -> an absolute
        # PRICE. Using peakAfter as the label asks "did the price reach 25?",
        # which a Rs.250 option satisfies trivially and a Rs.0.06 option never
        # can. That produces a hit rate that rises monotonically with premium
        # and measures nothing.
        if "ratio" in cols:
            base = (f"SELECT *, ratio AS _peak FROM "
                    f"read_parquet('{src}', union_by_name=true)")
            print("\nlabel source: ratio  (peak high after entry / entry close)")
        elif "peakAfter" in cols and "entryPrice" in cols:
            base = (f"SELECT *, CASE WHEN entryPrice > 0 THEN "
                    f"peakAfter / entryPrice END AS _peak FROM "
                    f"read_parquet('{src}', union_by_name=true)")
            print("\nlabel source: peakAfter / entryPrice  (computed multiple)")
            print("  note: `ratio` column absent — using the computed form")
        else:
            sys.exit("ERROR: need a 'ratio' column, or 'peakAfter' + "
                     "'entryPrice'. Found: " + str(cols))

    # ---- episodes + sampling, entirely in DuckDB -------------------------
    print("\npass 2: assigning episodes (DuckDB, spills to disk)")

    # Episodes are FIXED TIME BUCKETS per underlying, not gaps in firing.
    # Gap-based grouping assumed signals fire sparsely. With ~200 instruments
    # across many simultaneously-live expiries they fire continuously, so no
    # 24h silence ever occurs and every row on one underlying collapses into a
    # single "episode". Fixed buckets are robust to firing density.
    if args.episode_key == "expiry" and "expiry" in cols:
        ep_key = "spot || '#' || expiry"
    else:
        ep_key = (f"spot || '#' || CAST(CAST(FLOOR(_ts_hours / "
                  f"{args.episode_hours}) AS BIGINT) AS VARCHAR)")
    print(f"  episode key: {ep_key}")

    # ---- diagnostic: is the label driven by sub-tick premiums? ----------
    if "entryPrice" in cols:
        print("\n" + "=" * 70)
        print("LABEL SANITY CHECK — hit rate by entry premium")
        print("=" * 70)
        diag = con.execute(f"""
            SELECT bucket, count(*) n, avg(hit)*100 pct, median(entryPrice) med
            FROM (
                SELECT entryPrice,
                       CASE WHEN _peak >= {args.target} THEN 1 ELSE 0 END hit,
                       CASE WHEN entryPrice < 0.1  THEN '1. < 0.1'
                            WHEN entryPrice < 0.5  THEN '2. 0.1-0.5'
                            WHEN entryPrice < 1    THEN '3. 0.5-1'
                            WHEN entryPrice < 5    THEN '4. 1-5'
                            WHEN entryPrice < 20   THEN '5. 5-20'
                            ELSE '6. >= 20' END bucket
                FROM ({base}) WHERE _peak IS NOT NULL
            ) GROUP BY bucket ORDER BY bucket
        """).fetchall()
        print(f"{'premium':14}{'rows':>14}{'median':>10}{str(int(args.target))+'x hit':>10}")
        print("-" * 48)
        for b, n, pct, med in diag:
            print(f"{b:14}{n:>14,}{med:>10.2f}{pct:>9.1f}%")
        cheap = sum(n for b, n, _, _ in diag if b[0] in "123")
        tot = sum(n for _, n, _, _ in diag)
        if tot and cheap / tot > 0.4:
            print(f"\n!! {cheap/tot*100:.0f}% of rows are on options under 1.0.")
            print("   At that premium a 25x move is tick size and spread, not a")
            print("   tradeable outcome. Use --min-entry-price to exclude them;")
            print("   otherwise the label measures rounding, not edge.")

    price_filter = (f" AND entryPrice >= {args.min_entry_price}"
                    if args.min_entry_price > 0 and "entryPrice" in cols else "")
    if price_filter:
        print(f"\napplying tradeability floor: entryPrice >= "
              f"{args.min_entry_price}")

    con.execute(f"""
        CREATE OR REPLACE VIEW labelled AS
        SELECT *, CASE WHEN _peak >= {args.target} THEN 1 ELSE 0 END AS label
        FROM ({base}) WHERE _peak IS NOT NULL{price_filter}
    """)

    con.execute(f"""
        CREATE OR REPLACE VIEW with_ep AS
        SELECT *, {ep_key} AS episode_id
        FROM labelled
    """)

    n_rows, n_eps, pos_rows, pos_eps = con.execute("""
        SELECT count(*), count(DISTINCT episode_id), sum(label),
               count(DISTINCT CASE WHEN label=1 THEN episode_id END)
        FROM with_ep
    """).fetchone()

    print("\n" + "-" * 70)
    print(f"rows                  : {n_rows:,}")
    print(f"independent episodes  : {n_eps:,}")
    print(f"inflation factor      : {n_rows/max(n_eps,1):.1f}x")
    print(f"\npositive rows         : {int(pos_rows or 0):,}"
          f"  ({(pos_rows or 0)/max(n_rows,1)*100:.1f}%)")
    print(f"positive EPISODES     : {int(pos_eps or 0):,}"
          f"  ({(pos_eps or 0)/max(n_eps,1)*100:.1f}%)")
    print("-" * 70)
    print("\nWhat these mean:")
    print("  rows     — one signal on one contract at one time. This is what")
    print("             trains: each row is a real decision you could have made.")
    print("  episodes — the unit of INDEPENDENCE, used to group cross-validation")
    print("             folds so the same market move never spans train and test.")
    print("  Effective sample size sits between the two. If positive episodes is")
    print("  small, the model has seen few distinct market conditions however")
    print("  many rows there are.")

    # ---- sample rows per episode, in CHUNKS ------------------------------
    # A single window function partitioned over 13.6M rows exhausts memory
    # during COPY. Episode ids are deterministic buckets, so the work splits
    # cleanly: process a slice of buckets at a time and write one parquet part
    # per slice. Peak memory is bounded by slice size, not table size.
    out = args.out
    if out.endswith(".csv"):
        print("\nnote: writing parquet instead of csv — smaller and faster")
        out = out[:-4] + ".parquet"
    out_dir = out[:-8] if out.endswith(".parquet") else out
    out_dir = out_dir + "_parts"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    k = args.max_rows_per_episode
    spots = [r[0] for r in con.execute(
        "SELECT DISTINCT spot FROM with_ep ORDER BY 1").fetchall()]

    kept = kept_pos = 0
    part = 0
    for sp in spots:
        lo, hi = con.execute(
            f"SELECT min(_ts_hours), max(_ts_hours) FROM with_ep "
            f"WHERE spot = ?", [sp]).fetchone()
        if lo is None:
            continue
        width = args.episode_hours * args.chunk_episodes
        edges = np.arange(lo, hi + width, width)
        for i in range(len(edges) - 1):
            a, b = float(edges[i]), float(edges[i + 1])
            sel = (f"SELECT * FROM with_ep WHERE spot = '{sp}' "
                   f"AND _ts_hours >= {a} AND _ts_hours < {b}")
            if k and k > 0:
                # Keep EVERY positive; sample only negatives. At a ~1% base
                # rate, sampling both classes at k=50 loses most positive
                # episodes outright. `_w` restores unbiasedness: each kept
                # negative stands for (negatives in episode / negatives kept).
                sel = (f"""
                    SELECT * EXCLUDE (rn, n_neg), CASE
                        WHEN label = 1 THEN 1.0
                        ELSE GREATEST(1.0, n_neg::DOUBLE / {k})
                    END AS _w
                    FROM (
                        SELECT *,
                          row_number() OVER (PARTITION BY episode_id, label
                                             ORDER BY random()) rn,
                          count(*) FILTER (WHERE label = 0)
                              OVER (PARTITION BY episode_id) n_neg
                        FROM ({sel})
                    )
                    WHERE label = 1 OR rn <= {k}
                """)
            n_here = con.execute(f"SELECT count(*) FROM ({sel})").fetchone()[0]
            if not n_here:
                continue
            p = os.path.join(out_dir, f"part-{part:05d}.parquet")
            con.execute(f"COPY ({sel}) TO '{p}' "
                        f"(FORMAT PARQUET, COMPRESSION ZSTD)")
            kept += n_here
            kept_pos += con.execute(
                f"SELECT count(*) FROM read_parquet('{p}') WHERE label=1"
            ).fetchone()[0]
            part += 1
            print(f"  wrote {part} parts, {kept:,} rows", end="\r", flush=True)
    print(f"  wrote {part} parts, {kept:,} rows" + " " * 20)

    ds = os.path.join(out_dir, "*.parquet").replace("\\", "/")
    kept_eps, kept_pos_eps = con.execute(
        f"SELECT count(DISTINCT episode_id), "
        f"count(DISTINCT CASE WHEN label=1 THEN episode_id END) "
        f"FROM read_parquet('{ds}', union_by_name=true)").fetchone()

    if k and k > 0:
        print(f"\nsampled to <= {k} rows per episode: "
              f"{n_rows:,} -> {kept:,} rows ({n_rows/max(kept,1):.1f}x smaller)")
        wpos, wtot = con.execute(
            f"SELECT sum(_w) FILTER (WHERE label=1), sum(_w) "
            f"FROM read_parquet('{ds}', union_by_name=true)").fetchone()
        print(f"  positive rate     {(pos_rows or 0)/max(n_rows,1)*100:5.2f}% "
              f"-> {(wpos or 0)/max(wtot or 1,1)*100:5.2f}% weighted "
              f"({kept_pos/max(kept,1)*100:.1f}% raw)")
        print(f"    all positives kept; negatives sampled and weighted via `_w`,")
        print(f"    so weighted stats match the full data. Use _w downstream.")
        print(f"  episodes          {n_eps:,} -> {kept_eps:,}   "
              f"(positive {int(pos_eps or 0):,} -> {int(kept_pos_eps or 0):,})")
        lost = int(pos_eps or 0) - int(kept_pos_eps or 0)
        if lost > 0:
            print(f"  ! {lost} positive episode(s) lost to sampling. Raise "
                  f"--max-rows-per-episode if that is a large fraction.")

    size_mb = sum(os.path.getsize(os.path.join(out_dir, f))
                  for f in os.listdir(out_dir)) / 1e6
    print(f"\nwrote {out_dir}/  ({part} parts, {kept:,} rows, {size_mb:.1f} MB)")
    out = out_dir

    if (pos_eps or 0) < 30:
        print("\n!! Under 30 positive episodes — any model will overfit.")
        print("   Try --target 10, a wider range, or drop the filters.")
    elif (pos_eps or 0) < 100:
        print("\n!  Under 100 positive episodes — treat step 3 as indicative.")
    else:
        print("\nOK — enough positive episodes to train on.")

    print(f"\nshards kept in {shard_dir} (delete when done)")
    print(f"\nnext:  python3 step2_baseline.py --data {out}")


if __name__ == "__main__":
    main()
