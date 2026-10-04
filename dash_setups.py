"""Price-action SETUP review, merged into the main dashboard (was serve_setups.js on :4000).

Source: data/setup_review/{asset}/{expiry}.json, built by build_setup_review.py. A setup
belongs to every expiry alive within 30 days of it, so the same setup appears in many
expiry files. Each copy carries only THAT expiry's nearby option signals.

Two views:
  window(asset, t0, t1)  every setup inside the visible chart range, de-duplicated across
                         expiries, with the signals of all those expiries merged. Feeds
                         the setup markers on the price-action pane.
  sheet(asset, expiry)   the per-expiry review the :4000 viewer showed. Feeds the table.

Chart deep links are the same as chart_url.js: the chart app on :3000/de, IST wall
clock, 40 candles of lead-in, 30 minutes past settlement. The host is a placeholder the
page swaps for location.hostname, so links work from a phone on the LAN too.
"""
import json, os, glob, datetime as dt

BASE = "data/setup_review"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CHART_BASE = "http://__CHART_HOST__:3000/de"

def _ist(ms):
    return dt.datetime.fromtimestamp(ms / 1000, IST).strftime("%Y-%m-%dT%H:%M:00+0530")

def settle_ms(expiry):
    return int(dt.datetime.fromisoformat(expiry).replace(hour=12, tzinfo=dt.timezone.utc).timestamp() * 1000)

def chart_url(expiry, symbol, start_ms, duration):
    frm = _ist(start_ms - 40 * duration * 60000)
    to = _ist(settle_ms(expiry) + 30 * 60000)
    return f"{CHART_BASE}/{expiry}/{symbol}/{frm}/{to}/{duration}"

def _sig_ms(iso):
    """Signal times are IST wall clock with +0530 (e.g. 2026-10-02T04:10:00+0530)."""
    try: return int(dt.datetime.fromisoformat(iso.replace("+0530", "+05:30")).timestamp() * 1000)
    except Exception: return None

def _decorate(asset, expiry, s):
    s = dict(s)
    s["tsIso"] = dt.datetime.fromtimestamp(s["ts"], IST).strftime("%Y-%m-%d %H:%M")
    sigs = []
    for g in s.get("signals") or []:
        g = dict(g); ms = _sig_ms(g.get("iso", ""))
        g["expiry"] = expiry
        g["url"] = {sym: chart_url(expiry, sym, ms, g["dur"]) for sym in g.get("syms", [])} if ms else {}
        sigs.append(g)
    s["signals"] = sigs
    return s

def expiries(asset):
    d = os.path.join(BASE, asset)
    return sorted((f[:-5] for f in os.listdir(d) if f.endswith(".json")), reverse=True) if os.path.isdir(d) else []

def sheet(asset, expiry):
    fp = os.path.join(BASE, asset, f"{expiry}.json")
    try: d = json.load(open(fp))
    except Exception: return {"spot": asset, "expiry": expiry, "setups": []}
    d["setups"] = [_decorate(asset, expiry, s) for s in d.get("setups", [])]
    return d

def window(asset, t0, t1):
    """Setups with t0 <= ts <= t1, one per (ts, tf, name, dir), signals merged across the
    expiries alive then. Only expiry files that can contain such setups are opened:
    an expiry holds setups from the 30 days before it, so expiry in [t0, t1 + 31d]."""
    lo = dt.datetime.fromtimestamp(t0, dt.timezone.utc).date().isoformat()
    hi = (dt.datetime.fromtimestamp(t1, dt.timezone.utc) + dt.timedelta(days=31)).date().isoformat()
    merged = {}
    for fp in sorted(glob.glob(os.path.join(BASE, asset, "*.json"))):
        e = os.path.basename(fp)[:-5]
        if not (lo <= e <= hi): continue
        try: d = json.load(open(fp))
        except Exception: continue
        for s in d.get("setups", []):
            if not (t0 <= s["ts"] <= t1): continue
            k = (s["ts"], s["tf"], s["name"], s["dir"])
            ds = _decorate(asset, e, s)
            if k not in merged:
                merged[k] = ds; continue
            m = merged[k]
            m["signals"] = m["signals"] + ds["signals"]
    out = []
    for m in merged.values():
        m["signals"].sort(key=lambda g: -g.get("ratio", 0))
        m["n_signals"] = len(m["signals"])
        m["best_ratio"] = max([g.get("ratio", 0) for g in m["signals"]], default=0.0)
        m["signals"] = m["signals"][:8]
        out.append(m)
    return sorted(out, key=lambda r: r["ts"])
