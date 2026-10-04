# Dashboard: price action + 1:100, past and live (http://127.0.0.1:8777)

One page, merged on 2026-10-04 from:
- **:8777** `dash_server.py` + `dashboard.html`: candles, price-action points, the 1:100 grid, live panels (built 2026-10-01);
- **:4000** `serve_setups.js`: the per-expiry price-action SETUP review (Brooks setups + nearby option signals, built 2026-09-18).

`serve_setups.js` still runs on its own, but everything it showed is now in the setup-review drawer here.

Runs as the LaunchAgent `com.tejas.de-dashboard` (see `ops/launchd/`). It starts at login, restarts if it dies, and refreshes data every 15 minutes.

URL options, which make views bookmarkable:
- `?asset=ETH&res=240`: pick the asset and timeframe;
- `&drawer=1`: open the setup review on load;
- `&selftest`: run the in-page browser test.

## What is on the page

| area | what | source |
|---|---|---|
| top pane | candles (perp MARK) | `data/spot_candles` |
| middle pane | price-action points: level rejections (grey), line breaks (blue), wedge breaks (purple), dot size = importance, hover = description + the 1:100 requirement live at that moment. **Brooks setups** ▲ long / ▼ short (4h/1d): green hit target, red stopped, grey unresolved, orange ring = a ≥10x option signal fired within 3 bars; hover = expectation, measured win rate, result, signals | `levels.py`, `wedge.py`, `data/setup_review` |
| bottom pane | the 1:100 grid. Per candle: CALL now, CALL exp, PUT now, PUT exp, for the immediate / next / weekly expiry live AT THAT CANDLE. Coloured by required-move class, numbers printed, hover for strike, spot and time to expiry | `data/dashreq` (`dash_build.py`, `optreq.py`) |
| right panel | live: levels being APPROACHED (light) / TESTED (semi-bold) / CONFIRMED (bold); move needed for 1:100 right now, from the live chain | `dash_api.proximity`, Delta tickers |
| drawer | setup review for one expiry (defaults to the immediate expiry): filters (all / with signals / hit target / 10x+), signals with chart links to :3000/de; clicking a row centres the chart on it | `dash_setups.py` |

## Requirements, and where each is met

His spec of 2026-10-01 (pair of dashboards, past + live, combined), the 21 Sep / 25 Sep
price-action-points requests, and the :4000 setup review:

| # | requirement | met by | tested by |
|---|---|---|---|
| 1 | past and live in ONE view | one time axis, so scrolling left walks into history | selftest: pan |
| 2 | loop updating data; live chart refreshed every 15 min; lightweight | server loop every 15m; page auto-refresh every 15m, which keeps a panned view and slides forward when you are at the live edge | selftest: refresh keeps view |
| 3 | PA graph like a volume pane, dots sized by importance, hover description | middle pane on the SAME x axis as the candles | selftest: shared axis |
| 4 | 1:100 bars under each candle: CALL and PUT, 3 expiry parts (immediate / next / weekly-or-next-weekly), now % and expiry % | bottom grid, 3 slot rows × (CALL now, CALL exp, PUT now, PUT exp); the "6-cell" layout chosen on 2026-10-01 | API: slot rule recomputed independently; numbers re-solved from raw candles |
| 5 | expiry dates labelled on the left, consistent on rollover and when scrolling into the past | slots resolved per candle from the expiries live then; left labels follow the right-most visible candle | API: slot rule; selftest: labels roll on pan |
| 6 | numbers written on the bars, visible at all times | printed whenever a cell is ≥ 20 px wide; the first view is sized so they are (6–45 candles depending on width); zoom out and colours remain, hover still shows every number | selftest: numbers on default view, hidden when unreadable, back on zoom-in |
| 7 | min move for 1:100 across all strikes, now (chain IV) and at expiry (intrinsic) | `optreq.required_moves`, live from tickers `mark_iv` | API: re-solve at random cells |
| 8 | approaching / testing / confirmed in the live panel | right panel | API: thresholds |
| 9 | each PA point carries the 1:100 requirement live when it printed | hover | API: event value = immediate slot at that candle |
| 10 | :4000 setup review: setups per expiry, measured win rate, spot result, MFE, nearby signals, best multiple, filters, chart links | drawer; also as markers on the chart | API: row counts, direction match, links identical to chart_url.js; selftest: filters, row click, links |

## Testing

- **API / data:** `venv/bin/python test_dashboard.py` with the server up. It checks all 8 asset × resolution views and recomputes independently rather than re-reading the API: the slot rule, the 1:100 numbers from raw option candles, grid alignment, events, setups and chart links. Responses are parsed strictly, like a browser (NaN is rejected). Bad inputs must return 400.
- **Browser:** open `/?selftest&asset=..&res=..`. The page drives itself (pan, zoom, refresh, latest, drawer, filters, row click) and posts PASS/FAIL to `logs/selftest.txt`. It was run headless in Chrome on all 8 views and at 900, 1280, 1600 and 1920 px: 27/27 checks pass on each.

## Bugs found and fixed while merging (2026-10-04)

| bug | effect | fix |
|---|---|---|
| grid on its own index x-axis | panning or zooming the candles did not move the 1:100 grid | grid cells placed on the candles' time axis |
| time-to-expiry from the bar OPEN while prices are the bar CLOSE | every row had one extra bar of time value (4h on 4h bars); implied vol behind "now" biased low; the bar closing at settlement showed a dead contract as "immediate" | tte from the close; all 7,946 grid caches rebuilt |
| daily view aligned on open times | a daily candle showed the requirement from 4h into its day | aligned on close times |
| NaN in API JSON | browsers rejected the payload: 4h / 1d / some 1h views never loaded (Python's json reader hid it) | NaN/Infinity become null; strict parsing in tests |
| `update_spot.py` fetched the plain symbol (TRADED) into the MARK store, filed by UTC date | from 26 Sep, 17–79% of each day's spot bars were traded prices; bars between 18:30 and 24:00 UTC sat in two files and readers picked one arbitrarily | MARK: prefix, IST day files; `--repair-since 2026-09-25` rewrote the period (0 duplicates, 0 traded bars after) |
| grid caches keyed only on option-file times | spot repairs and the catch-up left stale grids | `dash_build.py --force-since` |
| numbers unreadable / overlapping; price and date labels clipped; drawer overlapping the chart; queued pans dropped; refresh could lose the view; no input validation | — | see `dashboard.html` comments; parameters whitelisted (asset, res, expiry, limit) |

## Limits

- **Twelve numbers per candle** (3 expiries × 4) only fit when a candle is about 100 px wide, so the readable view is the most recent 6–45 candles depending on screen width. Further out the colours carry it, and hover gives exact values.
- **MARK prices** throughout (`de-signals-mark-price-blocker`).
- **Plotly from cdn.plot.ly**, so the first load needs internet.
- **Disk:** the loop stops topping up live option candles below 1 GB free. The daily research refresh needs 4 GB.
