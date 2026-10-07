"""Target-multiple matrix for the current rules (2026-10-07). His call signals, activated, premium 2-20.
EV per unit at target T = P(peak >= T) * T - 1 - 0.0826, i.e. a resting sell at T and a total loss
otherwise -- the same convention as the break-evens (4.33% at 25x, 1.08% at 100x, 0.54% at 200x).
MARK: peak_vs_close from events.parquet (max over all strikes rows, averaged per event).
TRADED: picture_traded.parquet (every picture-day row + a same-size random sample of other days):
peak = traded high after the first traded fill, divided by that fill."""
import numpy as np, pandas as pd, io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import r5_picture as RP            # gives ev with ai, rg, pic per event
COST = 0.0826; TS = [2, 5, 10, 25, 50, 100, 200, 500]
E = pd.read_parquet("events.parquet", columns=["event_id", "peak_vs_close"])
pk = E[E.event_id.isin(RP.ev.event_id)]
ev = RP.ev.copy()
for T in TS:
    ev[f"m{T}"] = ev.event_id.map((pk.peak_vs_close >= T).groupby(pk.event_id).mean())
Tr = pd.read_parquet("data/picture_traded.parquet")
Tr["x"] = Tr.thigh / Tr.fill
for T in TS:
    ev[f"t{T}"] = ev.event_id.map((Tr.x >= T).groupby(Tr.event_id).mean())
rules = {"all calls": ev.ai.notna(), "A+ (R4 & not R5)": (ev.ai == 1) & (ev.rg != 1),
         "picture": ev.pic, "picture & not R5": ev.pic & (ev.rg != 1)}
for src, pre in (("MARK", "m"), ("TRADED", "t")):
    print(f"\n{src}: hit rate / EV per unit at each target")
    print(f"  {'rule':<20}{'n':>7}" + "".join(f"{str(T)+'x':>16}" for T in TS))
    for lab, m in rules.items():
        g = ev[m]; cells = []
        for T in TS:
            x = g[f"{pre}{T}"].dropna()
            if len(x) < 50: cells.append(f"{'—':>16}"); continue
            p = x.mean(); cells.append(f"{p:>7.2%} {T*p-1-COST:>+7.2f}")
        n = g[f"{pre}2"].notna().sum()
        print(f"  {lab:<20}{n:>7}" + "".join(cells))
print("\nbreak-even hit rate:", "  ".join(f"{T}x {(1+COST)/T:.2%}" for T in TS))
