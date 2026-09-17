# Signal tuning pipeline

Three scripts. Run in order. Each prints its verdict and tells you the next command.

## Install

```bash
pip install pandas numpy scikit-learn lightgbm scipy pyarrow duckdb
```

## Run

```bash
# 1. build the labelled dataset
python3 step1_prepare.py --patterns data/patterns --target 25 --out dataset.parquet

# 2. does the signal beat random?
python3 step2_baseline.py --data dataset.parquet --random random_entries.csv

# 3. the tuning
python3 step3_tune.py --data dataset.parquet
```

Filter to one signal, underlying, or duration:

```bash
python3 step1_prepare.py --patterns data/patterns --signal red_squeeze \
                         --spot BTC --duration 60 --target 25
```

`patterns.js` rows already carry `peakAfter`, so the label needs no join. To use
`multibaggers.js` ground truth instead:

```bash
python3 step1_prepare.py --patterns data/patterns \
                         --multibaggers out/multibaggers.json \
                         --target 25 --out dataset.parquet
```

If the scripts can't find a column they need, they print every column they *did*
find and stop. Rename or pass the right file; they don't guess.

`--random` in step 2 is optional. Without it you still get the internal check —
whether `signalValue` ranks outcomes at all. With it you get the real answer.
To generate it: sample random timestamps from the same OTM/DTE population your
signals fire on, run the same forward scan `multibaggers.js` already does, and
save a file with a peak-ratio column.

---

## What each step does

**step1 is streaming and out-of-core.** It never holds more than one batch of
files in memory: JSON files become Parquet shards, then DuckDB assigns episodes
with a SQL window function, spilling to disk. Peak memory is flat in row count.
Measured: 588 MB of JSON, 672k rows, **0.79 GB peak, 19s**.

`--max-rows-per-episode` (default 50) samples rows within each episode. Rows in
one episode are near-duplicate views of the same move, so this cuts the table
10-50x with no information loss. Sampling is purely random so the base rate stays
unbiased — the script prints the before/after positive rate so you can check.
Set `0` to keep everything. `--memory-limit` (default 4GB) caps DuckDB.

**step1** walks `data/patterns/{signal}/{spot}/{duration}/{expiry}.json`, joins to ground truth, applies the label
(`peakRatio >= target`), and collapses near-duplicate rows into independent
episodes.

The episode collapsing is the part that matters. One real move produces many
rows — consecutive timestamps, and many strikes that all paid off in the same
move. Those are one event seen many ways. On a fixture matching your schema the inflation
was **41x**: 3,297 rows, 80 episodes.

Episodes key on `spot` (the underlying), **not** `symbol` (the option contract) —
twenty strikes firing on one BTC move are one event, not twenty. If those duplicates land in both train and
test, scores look excellent and mean nothing. Step 1 prints the inflation factor
so you can see it.

**step2** compares your signal's forward-return distribution against random
entries on the same population. Deep OTM options near expiry are lottery tickets;
some fraction reach 25x with no pattern at all. This tells you whether 20% is
edge or base convexity. It reports the full distribution and a Mann-Whitney test,
not just the mean, because the tail is fat and means mislead.

**step3** is the tuning. It trains a logistic baseline and LightGBM on purged
walk-forward folds, compares feature arms, measures which features are inert, and
extracts the value ranges where the hit rate is actually highest.

---

## Reading step 3

**Arm comparison.** `context` = tteHours, moneyness, duration. `signals` = your
pattern features. `both` = both.

- signals > context → your patterns carry information beyond contract selection
- both ≫ either → the pattern works under some conditions and not others. That's
  the conditional threshold a single hand-picked number can't express
- context ≈ both → most of the power is in *which contract*, not *which pattern*.
  Still tradeable; it just means selection beats timing

**Precision at 15% recall** is the number to watch, not AUC. Of the setups
flagged when catching 15% of the winners, what fraction worked. Compare it to the
base rate printed underneath — that's what flagging everything gets you.

**Permutation importance** shows AUC drop when a feature is shuffled. Near zero
or negative means inert: it contributes nothing and can be dropped. Expect many
of the ~40 derived parameters to land here — most are the same few quantities
re-expressed, and collinear features dilute each other.

**Tuned thresholds** gives, per live feature, the hit rate in each sixth of its
range, with the best marked. That's your config value, read off the data.

Where two features both show lift, require **both**. That conjunction is the
conditional tuning that a flat threshold cannot represent.

---

## Honest limitations

**Small samples miss real effects.** On the test fixture I generated `ratio1`
with a genuine effect on the outcome, and permutation importance still marked it
inert — because with ~90 positive episodes, weak-but-real signals get lost. If a
feature you trust comes back inert, that's evidence it's weak, not proof it's
worthless. Re-check after more data.

**Under 30 positive episodes, don't trust the output.** Step 1 warns you. Lower
`--target` to 10 to get more positives and see whether the structure holds at a
smaller multiple — if it does, the 25x version is likely real but under-sampled.

**Model settings are deliberately conservative** — depth 3, 7 leaves, heavy
regularisation. At a few hundred episodes, a bigger model memorises. Don't raise
them to make the numbers look better.

**Every number here is out-of-sample by construction** — test folds are always
later in time than train, and no episode spans both. If the numbers look
disappointing, they're honest. Random k-fold on this data reports ~0.95 AUC and
is entirely fake.
