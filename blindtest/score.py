"""Score the blind chart test (run only after he has finished; prints outcomes).
Per chart, his decision is read from data/responses.jsonl:
  call   -> did the premium reach his target, and 5/10/25/100x, measured from the 5m close at his cursor to
            settlement (max later high / close); a 'false hit' if it missed his target
  leave / expired_no_call -> 'miss' if a >= 10x was still available after the point he left (max over
            later t of (later high / close_t)), else a 'correct leave'
Also: candles and steps before each call, time of the call relative to the move (bars before the peak),
whether my rising-parabola detector (premium_base4, any tf) had fired before his call, and his notes.
Group ratios were enriched (A 40 / B 30 / C 30); rates are shown raw and should be read as
discrimination (hits among calls vs among leaves), not as a real-world hit rate."""
import json, os, numpy as np, pandas as pd
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
K = json.load(open(f"{D}/key.json")); M = {m["id"]: m for m in json.load(open(f"{D}/manifest.json"))}
ev = [json.loads(l) for l in open(f"{D}/responses.jsonl")]
dec = {}
for e in ev:
    if e["action"] in ("call", "leave", "expired_no_call"): dec[e["chart"]] = e
rows = []
for cid, e in dec.items():
    if M[cid]["practice"]: continue
    c = json.load(open(f"{D}/charts/{cid}.json")); p = np.array(c["prem"], float)
    i = np.searchsorted(p[:, 0], e["cursor"]) - 1                      # last 5m bar fully before the cursor
    cl, h = p[:, 4], p[:, 2]
    after = h[i + 1:].max() / cl[i] if i + 1 < len(p) else 1.0
    fut = np.maximum.accumulate(h[::-1])[::-1]
    avail = np.max(fut[i + 2:] / np.maximum(cl[i + 1:-1], 1e-9)) if i + 2 < len(p) else 1.0
    k = K[cid]
    rows.append(dict(chart=cid, grp=k["grp"], typ=k["typ"], action=e["action"], target=e.get("target"), note=e.get("note", ""),
                     steps=e["steps"], candles=e["candles"], tf=e["tf"], tte_h=(c["settle"] - e["cursor"]) / 3600,
                     mult_from_call=after, best_after=avail,
                     hrs_to_peak=(p[i + 1 + np.argmax(h[i + 1:]), 0] - e["cursor"]) / 3600 if i + 1 < len(p) else np.nan))
R = pd.DataFrame(rows)
if R.empty: raise SystemExit("no scored decisions yet")
R["tgt"] = R.target.str.replace("x+", "", regex=False).str.replace("x", "", regex=False).astype(float)
calls, leaves = R[R.action == "call"], R[R.action != "call"]
print(f"decisions {len(R)}: calls {len(calls)}, leaves {len(leaves)} (of which ran to expiry {(R.action == 'expired_no_call').sum()})\n")
if len(calls):
    print("CALLS: hit his own target", f"{(calls.mult_from_call >= calls.tgt).mean():.0%}",
          " | from the call: " + "  ".join(f"{T}x {(calls.mult_from_call >= T).mean():.0%}" for T in (5, 10, 25, 100)))
    print("  by target:", calls.groupby("target").apply(lambda g: f"{(g.mult_from_call >= g.tgt).mean():.0%} of {len(g)}").to_dict())
print("LEAVES: >=10x still available after leaving (misses)", f"{(leaves.best_after >= 10).mean():.0%}" if len(leaves) else "-")
print("\nDiscrimination, same yardstick for both (buy at the decision point, best later high):")
for T in (5, 10, 25, 100):
    print(f"  >= {T}x   calls {(calls.mult_from_call >= T).mean():.0%}   leaves {(leaves.mult_from_call >= T).mean():.0%}" if len(calls) and len(leaves) else "  -")
print("\nBy sampling group (A had a >=10x available from the start):")
print(R.groupby("grp").apply(lambda g: pd.Series({"n": len(g), "called": (g.action == "call").mean(),
      "call>=10x": ((g.action == "call") & (g.mult_from_call >= 10)).sum(), "missed>=10x": ((g.action != "call") & (g.best_after >= 10)).sum()})).to_string())
print("\nCandles moved before a call: median", calls.candles.median() if len(calls) else "-", " | tf at call:", calls.tf.value_counts().to_dict() if len(calls) else "-")
R.to_csv(f"{D}/scored.csv", index=False); print(f"\nper-chart table -> {D}/scored.csv")
