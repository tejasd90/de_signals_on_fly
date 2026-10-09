# Blind chart test

Tests HIS eye for the premium parabola (later: his other signals), not a detector. Designed by him
2026-10-09: he steps forward from a start point until he has multibagger conviction, or leaves. The
moment he calls is the measurement.

**Each chart is a strike ladder,** because live he decides from several strikes:
- the underlying on top, with 30 days of history;
- the 5 nearest-OTM strikes at the start;
- up to 3 further-OTM strikes on request (each request is logged).

**Timeframes:** 1h / 4h / 12h at all times. 15m only on expiry day (the IST date of settlement). No 5m.

**Shown:** bare candles, with no axis values, dates, strikes or asset. `data/config.json` switches:
- `"meta"`: call/put, each strike's live % OTM, and premium as % of the underlying (on by default);
- `"time"`: time to expiry and the weekday / IST clock (on by default).

The settings must stay fixed for the whole test.

**Controls:**
- step +1 / +3 / +10 candles (→, Shift+→, ↑);
- view 40 / 100 / 250 / all;
- more strikes (M);
- CONVICTION (C): pick strike(s) + a target (5x … 100x+) + an optional note;
- Leave (L), Next (N).

No outcomes are shown until the end.

**Sample** (100 scored + 3 practice; the ratio is hidden from him):
- **A, 40:** some strike on the ladder offered ≥ 10x after the start;
- **B, 30:** none did, but my rising-parabola detector fired;
- **C, 30:** none did.

B and C are matched to A on call/put and expiry life. BTC/ETH expiries 2024-01 → 2026-08. The start is
40% into the expiry's life, with ≤ 7 days left.

**Files:**
- `build_set.py`: picks the sample and fetches 15m MARK candles from Delta into `data/` (git-ignored:
  it holds the answer key).
- `server.py`: run `venv/bin/python blindtest/server.py`, then open http://127.0.0.1:8790. It sends only
  bars before his cursor and logs every action to `data/responses.jsonl` (resumable via
  `data/session.json`).
- `score.py`: run only after he finishes. Calls vs leaves on the same yardstick (the share of strikes
  reaching T, bought at the decision point), his own target, misses, and steps/timeframe at the call.
