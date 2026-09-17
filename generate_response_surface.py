#!/usr/bin/env python3
"""
generate_response_surface.py
----------------------------
Queries local 'options_analytics.db' via DuckDB to construct a 2D Response Surface
Matrix mapping Standardized Moneyness (X-axis) against Time-to-Expiry (Y-axis).

Calculates cell counts, 5x, 10x, 20x, and 50x probability hit rates to locate
broad high-probability plateaus across the options surface.
"""

import duckdb
import pandas as pd
import numpy as np

def main():
    db_path = "./options_analytics.db"
    print(f"Connecting to DuckDB Database: {db_path}...")
    conn = duckdb.connect(db_path)

    # SQL query to bin rows by Standardized Moneyness and DTE_hours
    # and calculate total count, 5x, 10x, 20x, 50x hit rates.
    query = """
    WITH binned_data AS (
        SELECT 
            CASE 
                WHEN DTE_hours < 6 THEN '01. <6h (Intraday)'
                WHEN DTE_hours >= 6 AND DTE_hours < 24 THEN '02. 6h-24h (1 Day)'
                WHEN DTE_hours >= 24 AND DTE_hours < 72 THEN '03. 24h-72h (1-3 Days)'
                WHEN DTE_hours >= 72 AND DTE_hours < 168 THEN '04. 72h-168h (3-7 Days)'
                WHEN DTE_hours >= 168 AND DTE_hours < 360 THEN '05. 168h-360h (1-2 Wks)'
                ELSE '06. >360h (>2 Weeks)'
            END AS dte_bin,

            CASE 
                WHEN standardized_moneyness < -3.0 THEN '1. Deep ITM (< -3.0)'
                WHEN standardized_moneyness >= -3.0 AND standardized_moneyness < -1.0 THEN '2. ITM (-3.0 to -1.0)'
                WHEN standardized_moneyness >= -1.0 AND standardized_moneyness <= 1.0 THEN '3. Near ATM (-1.0 to +1.0)'
                WHEN standardized_moneyness > 1.0 AND standardized_moneyness <= 3.0 THEN '4. Near OTM (+1.0 to +3.0)'
                WHEN standardized_moneyness > 3.0 AND standardized_moneyness <= 6.0 THEN '5. OTM (+3.0 to +6.0)'
                WHEN standardized_moneyness > 6.0 AND standardized_moneyness <= 10.0 THEN '6. Deep OTM (+6.0 to +10.0)'
                ELSE '7. Extreme OTM (> +10.0)'
            END AS moneyness_bin,

            opt_pct_return,
            close_opt
        FROM features_table
        WHERE close_opt >= 1.0 -- Standard tradeability floor
    )
    SELECT 
        dte_bin,
        moneyness_bin,
        COUNT(*) as total_candles,
        ROUND(AVG(CASE WHEN opt_pct_return >= 4.0 THEN 1.0 ELSE 0.0 END) * 100, 3) as pct_5x,
        ROUND(AVG(CASE WHEN opt_pct_return >= 9.0 THEN 1.0 ELSE 0.0 END) * 100, 3) as pct_10x,
        ROUND(AVG(CASE WHEN opt_pct_return >= 19.0 THEN 1.0 ELSE 0.0 END) * 100, 3) as pct_20x,
        ROUND(AVG(CASE WHEN opt_pct_return >= 49.0 THEN 1.0 ELSE 0.0 END) * 100, 3) as pct_50x
    FROM binned_data
    GROUP BY dte_bin, moneyness_bin
    ORDER BY dte_bin, moneyness_bin;
    """

    print("\nExecuting Response Surface Aggregation Query across 22M+ rows...")
    df_res = conn.execute(query).df()
    conn.close()

    if df_res.empty:
        print("No data found!")
        return

    print("\n" + "="*80)
    print("      RESPONSE SURFACE MATRIX: 10x+ HIT RATE (%) BY DTE & MONEYNESS")
    print("="*80)
    
    # Pivot for 10x Hit Rate Matrix (%)
    pivot_10x = df_res.pivot(index='dte_bin', columns='moneyness_bin', values='pct_10x').fillna(0.0)
    print("\n--- 10x+ Hit Rate Surface Matrix (%) ---")
    print(pivot_10x.to_string())

    # Pivot for 50x Hit Rate Matrix (%)
    pivot_50x = df_res.pivot(index='dte_bin', columns='moneyness_bin', values='pct_50x').fillna(0.0)
    print("\n--- 50x+ Hit Rate Surface Matrix (%) ---")
    print(pivot_50x.to_string())

    # Pivot for Total Candle Volume per Cell
    pivot_count = df_res.pivot(index='dte_bin', columns='moneyness_bin', values='total_candles').fillna(0)
    print("\n--- Sample Density Matrix (Total Candles) ---")
    print(pivot_count.astype(int).to_string())

    print("\n" + "="*80)
    print("Response Surface Generation Complete!")
    print("="*80)

if __name__ == "__main__":
    main()
