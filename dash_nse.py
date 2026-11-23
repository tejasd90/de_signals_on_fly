"""NSE/BSE index-option signal review for the dashboard (page /nse).

Data on this machine (data/nse, not in git):
  signals.parquet   every raw firing with its outcome (nse/signals_run.js -> nse/signals_to_parquet.py)
  spot/<NAME>.json.gz   index history, grouped (nse/fetch_spot.js)
  cache/<expiry>/<SYM>_<token>.json.gz   option candles, copied from the VM the first time a chart is opened
  vm.json           {"host": ..., "user": ..., "key": ...}   where the VM is; never committed (the repo is public)
The 1-minute data never comes here; one grouped contract file is about 15 KB.
"""
import os, re, json, gzip, glob, subprocess, threading
import pandas as pd
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "data", "nse")
NAMES = ("NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "BANKEX")
DURS = ("5", "10", "15", "25", "60", "75", "125", "1d", "1w")
_lock = threading.Lock()
_mem = {}

def _signals():
    """The firings table, read once: stored view only (15:30-15:40 as its own bar), traded trigger bars only."""
    with _lock:
        if "sig" not in _mem:
            t = pq.read_table(os.path.join(ROOT, "signals.parquet"), filters=[("view", "=", "separate"), ("vol", ">", 0)],
                              columns=["expiry", "name", "sym", "type", "strike", "dur", "signal", "ts", "entry", "vol", "spot", "peak", "peakTs", "x", "xEnd"])
            _mem["sig"] = t.to_pandas()
        return _mem["sig"]

def expiries(name):
    d = _signals()
    d = d[(d["name"] == name) & (d["entry"] >= 1)]
    g = d.groupby("expiry", observed=True).agg(n=("x", "size"), best=("x", "max"),
                                                 n100=("x", lambda s: int((s >= 100).sum()))).reset_index()
    g["expiry"] = g["expiry"].astype(str)
    return g.sort_values("expiry", ascending=False).to_dict("records")

def firings(name, expiry):
    """One row per contract, timeframe and bar; the signals that fired on that bar are joined."""
    d = _signals()
    d = d[(d["name"] == name) & (d["expiry"] == expiry)]
    if d.empty: return []
    g = d.groupby(["sym", "dur", "ts"], observed=True).agg(
        type=("type", "first"), strike=("strike", "first"), entry=("entry", "first"), vol=("vol", "first"), spot=("spot", "first"),
        peak=("peak", "first"), peakTs=("peakTs", "first"), x=("x", "first"), xEnd=("xEnd", "first"),
        signals=("signal", lambda s: ",".join(sorted(set(map(str, s)))))).reset_index()
    for c in ("dur", "type"): g[c] = g[c].astype(str)
    return g.sort_values(["ts", "dur", "strike"]).to_dict("records")

def _vm():
    with open(os.path.join(ROOT, "vm.json")) as f: return json.load(f)

def contract(expiry, sym):
    """Grouped candles of one contract, all timeframes. Copied from the VM once, then served from the cache."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry) or not re.fullmatch(r"[A-Z0-9]{6,40}", sym): raise ValueError("bad expiry or symbol")
    cdir = os.path.join(ROOT, "cache", expiry)
    hit = glob.glob(os.path.join(cdir, sym + "_*.json.gz"))
    if not hit:
        os.makedirs(cdir, exist_ok=True)
        vm = _vm()
        r = subprocess.run(["scp", "-q", "-i", os.path.expanduser(vm["key"]), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                            f"{vm['user']}@{vm['host']}:F:/nse/grouped/{expiry}/{sym}_*.json.gz", cdir + "/"], capture_output=True, text=True, timeout=90)
        hit = glob.glob(os.path.join(cdir, sym + "_*.json.gz"))
        if not hit: raise RuntimeError("could not copy the contract from the VM: " + (r.stderr.strip()[:200] or "no file"))
    with gzip.open(hit[0], "rt") as f: return json.load(f)

def spot(name, dur, t0, t1):
    """Index bars of one timeframe between two IST timestamps (inclusive of the days)."""
    if name not in NAMES or dur not in DURS: raise ValueError("bad name or timeframe")
    with _lock:
        key = ("spot", name)
        if key not in _mem:
            with gzip.open(os.path.join(ROOT, "spot", name + ".json.gz"), "rt") as f: _mem[key] = json.load(f)["c"]
        rows = _mem[key].get(dur, [])
    a, b = t0[:10], t1[:10] + "U"
    return [r[:5] for r in rows if a <= r[0] <= b]

def stock_moves():
    """Every monthly expiry's per-stock option runs (nse/stock_option_moves.js), as one object keyed by expiry."""
    with _lock:
        if "moves" not in _mem:
            out = {}
            for f in sorted(glob.glob(os.path.join(ROOT, "stock_moves", "20*.json"))):
                with open(f) as fh: out[os.path.basename(f)[:-5]] = json.load(fh)
            if not out: raise RuntimeError("no files in data/nse/stock_moves")
            _mem["moves"] = out
        return _mem["moves"]

def _ssh(cmd, timeout=60):
    vm = _vm()
    r = subprocess.run(["ssh", "-i", os.path.expanduser(vm["key"]), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                        f"{vm['user']}@{vm['host']}", cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError("VM not reachable or command failed: " + r.stderr.strip()[:200])
    return r.stdout

def _cdir(): return os.path.join(ROOT, "contracts")

def contract_expiries(refresh=False):
    """Expiry folders of combined_js on the VM. The list is kept locally (data/nse/contracts); refresh asks the VM for new ones."""
    os.makedirs(_cdir(), exist_ok=True)
    have = {f[:10] for f in os.listdir(_cdir()) if f.endswith(".json.gz")}
    if refresh:
        for d in _ssh("cmd /c dir /b /ad F:\\minute\\combined_js").split():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d not in have:
                contract_names(d, force=True); have.add(d)
    return sorted(have)

def contract_names(expiry, force=False):
    """File names (without .json) of one expiry: <SYMBOL>_<instrument token>."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry): raise ValueError("bad expiry")
    f = os.path.join(_cdir(), expiry + ".json.gz")
    if force or not os.path.exists(f):
        names = sorted(n[:-5] for n in _ssh(f"cmd /c dir /b F:\\minute\\combined_js\\{expiry}", timeout=180).split() if n.endswith(".json") and not n.startswith("._"))
        if not names: raise RuntimeError("no files for that expiry on the VM")
        os.makedirs(_cdir(), exist_ok=True)
        with gzip.open(f, "wt") as fh: json.dump(names, fh)
    with gzip.open(f, "rt") as fh: names = json.load(fh)
    settle = {}
    for n in NAMES:                                   # index close on expiry day, to mark the nearest strike
        try:
            spot(n, "1d", expiry, expiry)
            for r in _mem[("spot", n)]["1d"]:
                if r[0][:10] == expiry: settle[n] = r[4]
        except Exception: pass
    sn = os.path.join(ROOT, "spot_names.json")       # the `name` column of his Kite instruments files (NFO/BFO), where known
    spot_names = json.load(open(sn)) if os.path.exists(sn) else []
    return {"expiry": expiry, "names": names, "settle": settle, "spot_names": spot_names}
