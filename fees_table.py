#!/usr/bin/env python3
"""
fees_table.py — Delta Exchange India cost model, lots x move.

Rates verified 2026-09-16 against /v2/products (taker/maker_commission_rate,
contract_value) and Delta's published fee schedule. Change RATES here rather
than editing numbers inline anywhere else.

The one thing to internalise: fees are charged on NOTIONAL, and notional does
not care how far price moved. So the break-even move is a CONSTANT number of
points, identical at 1 lot and at 1000 lots.
"""
BTC = 76005.20           # live spot, 2026-09-16
CV  = 0.001              # BTCUSD contract_value: 1 lot = 0.001 BTC
GST = 1.18               # 18% GST on the fee itself

FUT_MAKER, FUT_TAKER = 0.0002, 0.0005     # 0.02% / 0.05%
OPT_RATE             = 0.0001             # 0.010% of notional
OPT_CAP_PREMIUM      = 0.035              # capped at 3.5% of premium

LOTS  = [1, 10, 100, 1000]
MOVES = [1, 10, 100, 1000]                # points = USD of BTC price

def fut_fee(lots, price, rate):
    return lots * CV * price * rate * GST

def row(lots, rate):
    out = []
    for mv in MOVES:
        gross = lots * CV * mv
        fee   = fut_fee(lots, BTC, rate) + fut_fee(lots, BTC + mv, rate)   # in + out
        out.append((gross, fee, gross - fee))
    return out

def money(x):
    return f"{x:>10,.2f}" if abs(x) >= 0.005 else f"{x:>10.4f}"

print(f"BTC {BTC:,.0f}   1 lot = {CV} BTC = ${CV*BTC:,.2f} notional   1 point = $1 of BTC\n")

for label, rate in (("MAKER 0.02%", FUT_MAKER), ("TAKER 0.05%", FUT_TAKER)):
    be = 2 * rate * BTC * GST
    print(f"=== FUTURES, {label} (incl 18% GST) — break-even move {be:,.1f} points, "
          f"at EVERY lot size ===")
    print(f"{'lots':>6} {'notional':>14} " + "".join(f"{str(m)+'pt net':>13}" for m in MOVES))
    for L in LOTS:
        cells = row(L, rate)
        print(f"{L:>6} {L*CV*BTC:>13,.0f}$ " + "".join(money(n) + "   " for _, _, n in cells))
    print(f"{'':>6} {'round-trip fee':>14} " +
          "".join(f"{fut_fee(L,BTC,rate)*2:>10,.2f}   " for L in LOTS) + "  <- per lot column")
    print()

print("=== the same thing as a break-even, which is what actually matters ===")
for label, rate in (("maker", FUT_MAKER), ("taker", FUT_TAKER)):
    be = 2 * rate * BTC * GST
    print(f"  {label:>5}: need {be:>6,.1f} BTC points ({be/BTC*100:.3f}%) to break even. "
          f"A {MOVES[-1]}-point winner keeps {(1 - be/MOVES[-1])*100:>5.1f}% of its gross.")
print()

print("=== LEVERAGE: the fee is fixed, your margin is not ===")
print(f"{'leverage':>9} {'margin/lot':>12} {'round-trip taker fee':>22} {'as % of margin':>16}")
for lev in (1, 5, 10, 25, 50, 100, 200):
    margin = CV * BTC / lev
    f = fut_fee(1, BTC, FUT_TAKER) * 2
    print(f"{lev:>8}x {margin:>11,.3f}$ {f:>21,.4f}$ {f/margin*100:>15.2f}%")

# ── OPTIONS ───────────────────────────────────────────────────────────────────
#
# fee = min( 0.010% x NOTIONAL , 3.5% x PREMIUM ) , then +18% GST.
# Notional uses the underlying, so for a cheap OTM option the notional-based fee
# would dwarf the premium — the cap is the only reason buying them is viable.

def opt_fee(lots, premium, spot=BTC):
    by_notional = OPT_RATE        * lots * CV * spot
    by_premium  = OPT_CAP_PREMIUM * lots * CV * premium
    return min(by_notional, by_premium) * GST, by_premium < by_notional

cap_at = OPT_RATE / OPT_CAP_PREMIUM * BTC
print()
print("=== OPTIONS: where the 3.5%-of-premium cap binds ===")
print(f"  cap binds whenever premium < {cap_at:,.0f}  (= {OPT_RATE}/{OPT_CAP_PREMIUM} x spot)")
print(f"  i.e. for essentially every OTM contract this project looks at.\n")
print(f"{'premium':>10} {'cost/lot':>11} {'fee/lot':>11} {'basis':>12} {'round trip':>12} {'% of premium':>14}")
for prem in (0.5, 5, 50, 200, 217, 500, 2000, 6000):
    f, capped = opt_fee(1, prem)
    cost = CV * prem
    print(f"{prem:>10,.1f} {cost:>10,.4f}$ {f:>10,.5f}$ {('3.5% prem' if capped else '0.01% notl'):>12}"
          f" {2*f:>11,.5f}$ {2*f/cost*100:>13.2f}%")

print()
print("=== OPTIONS, lots x premium move — entry premium 50 (a typical OTM strike) ===")
ENTRY = 50.0
print(f"{'lots':>6} {'premium paid':>14} " + "".join(f"{'+'+str(m)+'pt net':>14}" for m in MOVES))
for L in LOTS:
    paid = L * CV * ENTRY
    cells = []
    for mv in MOVES:
        gross = L * CV * mv
        fee   = opt_fee(L, ENTRY)[0] + opt_fee(L, ENTRY + mv)[0]
        cells.append(gross - fee)
    print(f"{L:>6} {paid:>13,.3f}$ " + "".join(f"{c:>13,.3f}$ " for c in cells))

print()
print("=== the option break-even, stated as a multiple ===")
for prem in (0.5, 5, 50, 200, 2000):
    f_in, _  = opt_fee(1, prem)
    # exit fee scales with the exit premium; solve premium_out for net zero
    # gross = CV*(p_out - p_in);  fee_out = 3.5%*CV*p_out*GST while capped
    k = OPT_CAP_PREMIUM * GST
    p_out = (prem + f_in / CV) / (1 - k) if prem < cap_at else prem + (f_in*2)/CV
    print(f"  premium {prem:>7,.1f} -> break even at {p_out:>9,.3f} "
          f"({p_out/prem:>6.3f}x, a {(p_out/prem-1)*100:>5.2f}% move)")
