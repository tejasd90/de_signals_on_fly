# Docs

Two trees, different jobs.

- **`docs/`** — *running the project*. Fetching instruments and candles,
  generating signals and patterns, the marker system, the viewers, and how to
  diagnose a pipeline that looks stuck or empty. Operational.
- **`docs/ML/`** — *the research*. Labels, features, models, controls, and what
  was measured. Evidential. Start at [`ML/README.md`](ML/README.md).

If you are asking "why is this viewer empty" you want this tree. If you are
asking "does this strategy make money" you want `ML/`.

---

## This tree

| doc | what it covers |
|---|---|
| [`RUNBOOK.md`](RUNBOOK.md) | **The end-to-end sequence.** Steps 0-7 node, steps 8-10 python. Step 0 (loosen thresholds before extracting) is a correctness requirement, not an optimisation. |
| [`01-running.md`](01-running.md) | Concepts, the two-marker design, diagnosing states A-K, every command, the viewers and their past/future split, troubleshooting. The longest and most useful doc here. |
| [`02-architecture.md`](02-architecture.md) | Code and data layout, the two-marker design, the merged range format, duration sourcing, rate limits. |
| [`03-signals.md`](03-signals.md) | The four hand-built signals and their parameters. |
| [`04-pseudocode.md`](04-pseudocode.md) | Signal logic in pseudocode. |
| [`05-query-tool.md`](05-query-tool.md) | The expression query language and `serve_query.js`. |
| [`06-decisions.md`](06-decisions.md) | Design decisions for the node pipeline. |
| [`07-bugs-found.md`](07-bugs-found.md) | Bugs found and fixed, with the symptom that exposed each. |
| [`08-open-questions.md`](08-open-questions.md) | Historical. **All four sections are answered** in [`ML/DECISION_DOCUMENT.md`](ML/DECISION_DOCUMENT.md) §8.3. |

---

## The viewers, at a glance

Nine HTTP viewers, each on its own port, each binding `0.0.0.0` and printing its
LAN address. Override with `--port`.

| port | command | shows | expiries |
|---|---|---|---|
| 3100 | `serve_signals.js` | strength x payoff matrix, expiry grid | past |
| 3200 | `serve_live.js` | live tape, EMA convergence, volatility map | future |
| 3300 | `serve_multibaggers.js` | ground truth: every move that existed | past |
| 3400 | `serve_trades.js` | trade calendar, all durations stacked | past |
| 3500 | `serve_signals_cal.js` | signal calendar, all durations stacked | past |
| 3600 | `serve_calibrate.js` | fixed-form successes/failures | past |
| 3700 | `serve_query.js` | expression query with holdout | past |
| 3800 | `serve_grids.js` | point-in-time heatmaps; expiry × time or expiry × strike (30m+ only) | **future** |
| 3900 | `serve_grids_past.js` | settled-expiry heatmaps; expiry × time or expiry × strike, with payoff shading (30m+ only) | **past** |
| 4000 | `serve_setups.js` | price-action setup review, one sheet per expiry — starts from a SETUP, not a signal | **past** |

**An empty viewer is almost always the past/future split, not a bug.**
3800 and 3900 are siblings asking opposite questions — see
[`01-running.md`](01-running.md) §Viewers.

Both grid viewers let you **click a cell** for a floating panel showing the spot
price action at that firing, tiered so it is clear which parts were measured to
predict (one) and which were measured not to (the rest). See §Click a square in
`01-running.md`.

Both grid viewers carry a **Layout** toggle: *expiry × time* ("where in a
contract's life does this fire") and *expiry × strike* ("a move happened — what
did it do to the board"). The strike layout is computed by the shared
`surface.js`, a node port of `build_surfaces.py`. Payoff shading exists on 3900
only, because 3800's forward window has not elapsed yet. Both default to hiding
contracts marked **below 2.0 at entry** — see §Min premium in `01-running.md`
before reading anything into a signal that appears to fire the wrong way.

Both grid viewers also apply a **30-minute minimum signal duration**
(`MIN_DURATION_MINUTES`), which hides the 5m/10m/15m/20m rows. It is a display
filter only — those signals are still written to disk and still shown by
`serve_signals.js`, `serve_signals_cal.js` and `serve_query.js`.

---

## Data layout

```
data/
  instruments/     live + expired product metadata
  candles/         option MARK candles        26 GB   (options retired as an earner)
  spot_candles/    underlying candles
  perp_candles/    220 Delta perpetuals, ts/o/h/l/c/v, TRADED with real volume   67 MB
  funding/         funding-rate history
  signals/         signal output per signal/spot/duration/expiry
  patterns/        patterns.js output        9.6 GB
  multibaggers/    ground truth moves
  trades/          trades.js output
  live/            live_runner.js output
  markers/         completion markers
```

`data/perp_candles/` is the entire input to all current futures research and
`fetch_perps.py` rebuilds it from the API in ~2.5 minutes. The large
directories belong to closed hypotheses.
