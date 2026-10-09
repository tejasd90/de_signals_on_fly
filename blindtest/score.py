"""Score the blind chart test (run only after he has finished; prints outcomes).

Each chart is a strike ladder; his decision is read from data/responses.jsonl.
- Multiple per strike: max later high (15m MARK, to settlement) / the 15m close just before his decision.
- CALL: the hit rate at T is the share of HIS PICKED strikes reaching T (equal money in each); also
  whether his own target was reached.
- LEAVE / ran to expiry: the same measure over the 5 base strikes from the leave point (what an
  equal-weight ladder bought there would have done), plus 'missed' = some base strike still offered
  >= 10x from a later entry.
Discrimination = calls vs leaves on the same yardstick. Groups were enriched (A 40 / B 30 / C 30), so raw
rates are not real-world hit rates.
Also: steps / candles / the (hidden) timeframe at the decision and the path of timeframe changes,
extra strikes requested, his call note and his running notes (each tagged with timeframe and candles)."""
import json, os, numpy as np, pandas as pd
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
K = json.load(open(f"{D}/key.json")); M = {m["id"]: m for m in json.load(open(f"{D}/manifest.json"))}
dec, notes, tfs = {}, {}, {}
for l in open(f"{D}/responses.jsonl"):
    e = json.loads(l)
    if e["action"] in ("call", "leave", "expired_no_call"): dec[e["chart"]] = e
    if e["action"] == "note": notes.setdefault(e["chart"], []).append(f"[{e['tf']}, {e['candles']} candles in] {e['text']}")
    if e["action"] == "tf": tfs.setdefault(e["chart"], []).append(e["to"])
TS = (5, 10, 25, 100); rows = []
for cid, e in dec.items():
    if M[cid]["practice"]: continue
    c = json.load(open(f"{D}/charts/{cid}.json"))
    def mult(j):
        p = np.array(c["strikes"][j]["rows"], float); i = np.searchsorted(p[:, 0], e["cursor"]) - 1
        if i < 0 or i + 1 >= len(p): return 1.0, 1.0
        cl, h = p[:, 4], p[:, 2]; fut = np.maximum.accumulate(h[::-1])[::-1]
        later = np.max(fut[i + 2:] / np.maximum(cl[i + 1:-1], 1e-9)) if i + 2 < len(p) else 1.0
        return float(h[i + 1:].max() / max(cl[i], 1e-9)), float(later)
    picks = e["strikes"] if e["action"] == "call" else list(range(5))
    m = [mult(j) for j in picks]; now = [x[0] for x in m]
    k = K[cid]
    r = dict(chart=cid, grp=k["grp"], asset=k["asset"], expiry=k["expiry"], typ=k["typ"], action=e["action"], target=e.get("target"),
             picks=picks if e["action"] == "call" else None, extra=e.get("extra", 0), steps=e["steps"], candles=e["candles"], tf=e["tf"],
             tte_h=(c["settle"] - e["cursor"]) / 3600, mult_each=[round(x, 2) for x in now], best_later=max(x[1] for x in m), note=e.get("note", ""),
             running_notes=" | ".join(notes.get(cid, [])), tf_path=">".join(tfs.get(cid, [])))
    for T in TS: r[f"h{T}"] = float(np.mean([x >= T for x in now]))
    if e.get("target"): r["own"] = float(np.mean([x >= float(e["target"].rstrip("x+")) for x in now]))
    rows.append(r)
R = pd.DataFrame(rows)
if R.empty: raise SystemExit("no scored decisions yet")
calls, leaves = R[R.action == "call"], R[R.action != "call"]
print(f"decisions {len(R)}: calls {len(calls)}, leaves {len(leaves)} (ran to expiry {(R.action == 'expired_no_call').sum()})\n")
print("Same yardstick (share of strikes reaching T, bought at the decision point):")
for T in TS:
    print(f"  >= {T:>3}x   calls {calls[f'h{T}'].mean() if len(calls) else float('nan'):6.1%}   leaves (5-strike ladder) {leaves[f'h{T}'].mean() if len(leaves) else float('nan'):6.1%}")
if len(calls):
    print(f"\nCalls reaching HIS OWN target: {calls.own.mean():.0%}   by target: " +
          ", ".join(f"{t} {g.own.mean():.0%} of {len(g)}" for t, g in calls.groupby("target")))
    print(f"Calls with >= 1 picked strike reaching 10x: {(calls.mult_each.apply(max) >= 10).mean():.0%}")
if len(leaves): print(f"Leaves where a base strike still offered >= 10x later (misses): {(leaves.best_later >= 10).mean():.0%}")
print("\nBy sampling group (A: a >= 10x was available on the ladder from the start):")
print(R.groupby("grp").apply(lambda g: pd.Series({"n": len(g), "called": round((g.action == "call").mean(), 2),
      "calls_h10": round(g[g.action == "call"].h10.mean(), 3) if (g.action == "call").any() else np.nan,
      "missed10": int(((g.action != "call") & (g.best_later >= 10)).sum())}), include_groups=False).to_string())
if len(calls):
    print(f"\nAt the call: median candles moved {calls.candles.median():.0f}, timeframe {calls.tf.value_counts().to_dict()}, "
          f"median tte {calls.tte_h.median():.1f}h, extra strikes asked {calls.extra.mean():.1f} on average")
R.to_csv(f"{D}/scored.csv", index=False); print(f"\nper-chart table -> {D}/scored.csv")
