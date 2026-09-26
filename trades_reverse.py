#!/usr/bin/env python3
"""
trades_reverse.py — reverse search against MERGED MARKET EVENTS, not contracts.

`data/multibaggers` is per-contract, so one move is counted dozens of times and
"did a 100x happen" collapses to "was the day violent". `trades.js` instead
merges moves across instruments into events, each carrying:
    maxRatio, count (how many contracts participated), holdCandles, and a
    DIRECTION (C or P)

Direction is the new lever. The level system knows whether a RESISTANCE or a
SUPPORT line broke, so for the first time we can ask whether the break pointed
the same way as the move that followed, rather than merely coinciding with it.

Events are deduped across the duration files (the same move appears under 5m,
10m, ... 1440m) by (spot, direction, start time, winning symbol).
"""
import glob, json, os
import numpy as np, pandas as pd
import events_browser as EB

def load_events(min_ratio=100):
    seen=set(); rows=[]
    for spot in ("BTC","ETH"):
        for fp in glob.glob(f"data/trades/{spot}/*/*.json"):
            if fp.endswith("_summary.json"): continue
            try: d=json.load(open(fp))
            except Exception: continue
            for side in ("C","P"):
                for e in d.get(side) or []:
                    if e.get("maxRatio",0) < min_ratio: continue
                    key=(spot,side,e.get("startMs"),e.get("maxSymbol"))
                    if key in seen: continue
                    seen.add(key)
                    rows.append(dict(spot=spot, side=side,
                        day=pd.Timestamp(e["startTs"]).tz_localize(None).normalize(),
                        ratio=e["maxRatio"], count=e.get("count",1),
                        hold=e.get("holdCandles",np.nan),
                        dist=e.get("distancePct",np.nan),
                        dur=d.get("duration"), expiry=d.get("expiry")))
    return pd.DataFrame(rows)

if __name__=="__main__":
    B=EB.break_table()
    B["day"]=pd.to_datetime(B.day)
    for T in (100,200,500):
        E=load_events(T)
        if E.empty: continue
        # collapse to one row per (spot, day, side): the biggest event
        G=E.groupby(["spot","day","side"]).agg(ratio=("ratio","max"),
             events=("ratio","size"), count=("count","max"), hold=("hold","median")).reset_index()
        # what broke that day on that spot, in each direction?
        bk=B.groupby(["spot","day","kind"]).agg(n=("tf","size"),age=("age","max"),
             wedge=("wedge","sum")).reset_index()
        up=bk[bk["kind"]=="R"].set_index(["spot","day"])
        dn=bk[bk["kind"]=="S"].set_index(["spot","day"])
        G=G.set_index(["spot","day"])
        G["R_n"]=up.n.reindex(G.index).fillna(0); G["R_age"]=up.age.reindex(G.index)
        G["S_n"]=dn.n.reindex(G.index).fillna(0); G["S_age"]=dn.age.reindex(G.index)
        G=G.reset_index()
        # a CALL event wants a resistance break; a PUT event wants a support break
        G["same_dir"]  = np.where(G.side=="C", G.R_n>0, G.S_n>0)
        G["opp_dir"]   = np.where(G.side=="C", G.S_n>0, G.R_n>0)
        G["same_old"]  = np.where(G.side=="C", G.R_age>=100, G.S_age>=100)
        G["any_break"] = (G.R_n+G.S_n)>0
        print(f"{'='*78}\nMERGED MARKET EVENTS reaching >={T}x   n={len(G):,} "
              f"(spot x day x side)   calls {int((G.side=='C').sum())}, puts {int((G.side=='P').sum())}")
        print(f"  a break of ANY kind that day        {100*G.any_break.mean():>6.1f}%")
        print(f"  a break in the SAME direction       {100*G.same_dir.mean():>6.1f}%")
        print(f"  a break in the OPPOSITE direction   {100*G.opp_dir.mean():>6.1f}%")
        print(f"  an OLD line broke, same direction   {100*G.same_old.fillna(False).mean():>6.1f}%")
        print(f"  NOTHING broke                       {100*(~G.any_break).mean():>6.1f}%")
        for s,lab in (("C","call events"),("P","put events")):
            g=G[G.side==s]
            if len(g)<20: continue
            print(f"    {lab:<12} same-dir {100*g.same_dir.mean():>5.1f}%  "
                  f"opp-dir {100*g.opp_dir.mean():>5.1f}%  "
                  f"old same-dir {100*g.same_old.fillna(False).mean():>5.1f}%  "
                  f"median participants {g['count'].median():.0f}")
        print()
