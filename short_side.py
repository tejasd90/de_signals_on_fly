"""Rule B split by break side (docs sweep B2): channel work says down-breaks cascade,
up-breaks get faded. Predicts: sell the CALL after a down-break pays, sell the PUT
after an up-break less so."""
import io, contextlib, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
with contextlib.redirect_stdout(io.StringIO()):
    import short_cond as SC
import levels as LV
rows = []
for spot in ("BTC","ETH"):
    for tf in (1440, 360, 240):
        conf, arr = LV.all_levels(spot, tf)
        for L in conf:
            i = L["break_i"]
            if L["type"] != "trendline" or not i or i < L["anchor"][1] + 5: continue
            rows.append(dict(spot=spot, up=L["kind"] == "R", t=int(arr[i,0]) + tf*60))
B = pd.DataFrame(rows).drop_duplicates()
print(SC.HDR)
for up, g in B.groupby("up"):
    out = []
    for r in g.itertuples():
        x = SC.trades_for(r.spot, r.t, "P" if r.up else "C")
        if x: out.append(dict(zip(["t","ex","net","win"], x)))
    SC.report(("UP-break -> sell PUT" if up else "DOWN-break -> sell CALL"), pd.DataFrame(out))
