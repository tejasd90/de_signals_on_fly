#!/usr/bin/env python3
"""
liq_example.py — what actually moves a liquidation price on Delta.

Params from /v2/products, verified 2026-09-16:
  ETHUSD  contract_value 0.01 ETH   initial_margin 0.5%   maintenance_margin 0.25%

Delta's rule (User Guide, Margin Explainer):
    at the liquidation price,  Position Margin - Unrealised PnL = Maintenance Margin

So for a long:   liq = entry - (margin - MM% * size * entry) / size
Everything below is that one line applied to each step of Tejas's scenario.
"""
CV   = 0.01      # ETH per lot
MM   = 0.0025    # 0.25% maintenance margin
LEV  = 50
def liq_long(size_lots, avg, margin):
    """Price at which margin - loss == maintenance margin."""
    eth = size_lots * CV
    # margin - eth*(avg - P) = MM * eth * P   ->  P = (margin - eth*avg) / (MM*eth - eth)
    return (margin - eth*avg) / (eth*(MM - 1))

def show(tag, size, avg, margin, note=""):
    p = liq_long(size, avg, margin)
    print(f"{tag:<44} size {size:>4}  avg {avg:>8,.2f}  margin ${margin:>8,.2f}"
          f"  liq {p:>8,.2f}  ({(p/avg-1)*100:+.2f}%)  {note}")

print("Tejas's premise: 200 lots @ 2500, 50x  ->  'liquidation 2% down = 2450'\n")
size, avg = 200, 2500.0
m0 = size*CV*avg/LEV
show("1. opening position", size, avg, m0)
print(f"   naive 1/leverage guess would be {avg*(1-1/LEV):,.2f}")
print(f"   -> real liq is {liq_long(size,avg,m0)-avg*(1-1/LEV):+.2f} HIGHER, i.e. you are")
print( "      liquidated BEFORE the margin is gone, because MM is held back.\n")

print("Now: buy 50 @ 2550, then sell those 50 @ 2600.\n")
print("--- convention A: weighted average (what a netting perp engine does) ---")
navg = (200*2500 + 50*2550)/250
m_add = m0 + 50*CV*2550/LEV                      # same 50x on the add
show("2. after adding 50 @ 2550", 250, navg, m_add, "avg rose")
pnl = 50*CV*(2600-navg)
show("3a. sold 50 @ 2600, ISOLATED (pnl to wallet)", 200, navg, m_add-50*CV*navg/LEV,
     f"realised +${pnl:,.2f} NOT in margin")
show("3b. sold 50 @ 2600, CROSS (pnl joins equity)", 200, navg, m_add-50*CV*navg/LEV+pnl,
     f"realised +${pnl:,.2f} IS in equity")

print("\n--- convention B: strict FIFO (closes the oldest lots first) ---")
favg = (150*2500 + 50*2550)/200
fpnl = 50*CV*(2600-2500)
show("3c. FIFO, ISOLATED", 200, favg, m_add-50*CV*2500/LEV, f"realised +${fpnl:,.2f}")
show("3d. FIFO, CROSS",    200, favg, m_add-50*CV*2500/LEV+fpnl, f"realised +${fpnl:,.2f}")

print(f"\nBaseline to compare against: liq was {liq_long(200,2500.0,m0):,.2f} before any of this.")
