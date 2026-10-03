# Always-on services (macOS LaunchAgents)

Copies of what is installed in `~/Library/LaunchAgents/`. Paths are absolute to this checkout.

| label | runs | what |
|---|---|---|
| `com.tejas.de-dashboard` | `venv/bin/python dash_server.py --interval 15` | dashboard on :8777, and every 15m: spot update, near-dated option MARK top-up (skipped below 3 GB free), grid rebuild, spot_grouped export, `paper_log.py --run --hours 3`, `paper_log.py --resolve` |
| `com.tejas.de-live-signals` | `node live_runner.js` (DE_QUIET_LOGS=1) | live signal engine for future expiries; quiet logging so it cannot fill the disk |

Install: `cp ops/launchd/*.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.tejas.de-*.plist`
Stop: `launchctl unload -w ~/Library/LaunchAgents/com.tejas.de-<name>.plist`
Logs: `logs/dashboard.log`, `logs/live_runner.log`.
