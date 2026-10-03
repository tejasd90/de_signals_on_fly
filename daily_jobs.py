"""Once-a-day housekeeping, called from the dashboard loop (dash_server.py). Idempotent:
a marker per UTC date means repeated calls within a day do nothing.

1. Forward-test snapshot: `paper_log.py --report` appended, dated, to logs/forward_report.log.
   Only FORWARD rows are evidence (logged <=3h after the signal closed).
2. Journal watch: pulls github.com/tejasd90/market_observatios into data/market_observatios
   and appends any commits since the last check to logs/journal_new.log, so new entries get
   scored once their horizon passes. Scoring itself stays manual (docs/ML/JOURNAL_SCORECARD.md).
3. Research refresh: settled expiries of the last 3 days -> node backfill.js (MARK candles at
   every duration + signals) -> build_events.py (events.parquet). Skipped below MIN_FREE_GB,
   because each expiry adds ~10-60 MB on a nearly full disk.
"""
import datetime as dt, os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
NODE = shutil.which("node") or "/opt/homebrew/opt/node@20/bin/node"
MIN_FREE_GB = 4.0
JOURNAL = os.path.join(HERE, "data", "market_observatios")

def run(argv, log, timeout, env=None):
    with open(os.path.join(HERE, "logs", log), "a") as f:
        f.write(f"\n===== {dt.datetime.now().isoformat(timespec='seconds')}  {' '.join(argv)}\n"); f.flush()
        r = subprocess.run(argv, cwd=HERE, stdout=f, stderr=subprocess.STDOUT, timeout=timeout,
                           env=dict(os.environ, **(env or {})))
    return r.returncode

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    marker = os.path.join(HERE, "data", f".daily_jobs_{today}")
    if os.path.exists(marker): return
    open(marker, "w").close()
    for old in os.listdir(os.path.join(HERE, "data")):
        if old.startswith(".daily_jobs_") and old != os.path.basename(marker):
            os.remove(os.path.join(HERE, "data", old))
    py = sys.executable
    run([py, "paper_log.py", "--report"], "forward_report.log", 300)
    # journal
    if os.path.isdir(os.path.join(JOURNAL, ".git")):
        before = subprocess.run(["git", "-C", JOURNAL, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", JOURNAL, "pull", "-q"], capture_output=True, timeout=120)
    else:
        before = None
        subprocess.run(["git", "clone", "-q", "https://github.com/tejasd90/market_observatios", JOURNAL], capture_output=True, timeout=300)
    rng = f"{before}..HEAD" if before else "-20"
    new = subprocess.run(["git", "-C", JOURNAL, "log", "--format=%h %ad %s", "--date=iso", rng],
                         capture_output=True, text=True).stdout.strip()
    if new:
        with open(os.path.join(HERE, "logs", "journal_new.log"), "a") as f:
            f.write(f"\n===== {today}: new journal commits to score\n{new}\n")
    # research refresh
    free = shutil.disk_usage(HERE).free / 1e9
    if free < MIN_FREE_GB:
        with open(os.path.join(HERE, "logs", "research_refresh.log"), "a") as f:
            f.write(f"\n===== {today}: SKIPPED, {free:.1f} GB free < {MIN_FREE_GB}\n")
        return
    frm, to = (today - dt.timedelta(days=3)).isoformat(), (today - dt.timedelta(days=1)).isoformat()
    env = {"DE_QUIET_LOGS": "1", "DE_NO_LOG_DIR": "1", "TZ": "Asia/Kolkata"}
    if run([NODE, "backfill.js", "--from", frm, "--to", to], "research_refresh.log", 3*3600, env) == 0:
        run([py, "build_events.py"], "research_refresh.log", 3*3600)

if __name__ == "__main__":
    main()
