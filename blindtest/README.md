# Blind chart test

Tests HIS eye for the premium parabola (and later his other signals), not a detector. Designed by him
2026-10-09: he steps forward from a start point until he has multibagger conviction (or leaves). The
moment he calls is the measurement.

- `build_set.py`: picks 100 scored charts plus 3 practice charts and fetches 5m MARK option + underlying
  candles from Delta. Writes `data/` (git-ignored: it holds the answer key).
- `server.py`: run `venv/bin/python blindtest/server.py`, then open http://127.0.0.1:8790.
  - It sends bars only up to his cursor.
  - It logs every action to `data/responses.jsonl` and can be resumed (`data/session.json`).
- `score.py`: run only after he finishes.

**Shown:** option premium and underlying candles, no axis values, no dates, no strike, no asset.
`data/config.json {"meta": false}` also hides the strip: call/put, % OTM, time to expiry, weekday and IST
time. That is on by default because he always knows these live.

**Controls:**
- timeframe 5m / 15m / 1h / 4h (keys 1–4);
- step +1 / +3 / +10 candles of the current timeframe (→, Shift+→, ↑);
- view 60 / 150 / 400 / all;
- CONVICTION (C) with a target (5x / 10x / 25x / 50x / 100x+) and an optional note;
- Leave (L), Next (N).

No outcome is shown until the end.

**Sample** (ratio hidden from him):
- **A, 40:** a ≥ 10x was available after the start;
- **B, 30:** no ≥ 10x, but my rising-parabola detector fired;
- **C, 30:** no ≥ 10x.

B and C are matched to A on type, moneyness and contract life. All expiries are BTC/ETH, 2024-01 →
2026-08 (none he lived through recently). The start is 40% into the contract's life, with ≤ 7 days left
and ≤ 7 days of history.
