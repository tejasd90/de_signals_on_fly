#!/usr/bin/env python3
"""
inspect_database.py
-------------------
Connects to options_analytics.db to verify data schema integrity,
inspect the distribution of engineered features, and extract 
unconditioned option candle base-rate returns.
"""

import duckdb
import pandas as pd

def main():
    db_path = "./options_analytics.db"
    print(f"Connecting to DuckDB Database: {db_path}...")
    conn = duckdb.connect(db_path)

    # 1. Dataset Integrity Check
    print("\n=== [1/3] Dataset Integrity Check ===")
    integrity_query = """
        SELECT 
            COUNT(*) as total_rows,
            COUNT(DISTINCT symbol) as unique_symbols,
            COUNT(DISTINCT expiry) as unique_expiries,
            COUNT(DISTINCT duration) as unique_durations,
            MIN(datetime) as earliest_date,
            MAX(datetime) as latest_date
        FROM features_table;
    """
    df_integrity = conn.execute(integrity_query).df()
    print(df_integrity.to_string(index=False))

    # 2. Mathematical Sanitization & Feature Distribution Check
    print("\n=== [2/3] Feature Distribution Summary ===")
    dist_query = """
        SELECT 
            MIN(standardized_moneyness) as min_moneyness,
            AVG(standardized_moneyness) as avg_moneyness,
            MAX(standardized_moneyness) as max_moneyness,
            
            MIN(volatility) as min_spot_vol,
            AVG(volatility) as avg_spot_vol,
            MAX(volatility) as max_spot_vol,
            
            AVG(opt_body_to_range) as avg_opt_body_ratio,
            AVG(opt_vol_ratio_20) as avg_opt_vol_ratio
        FROM features_table
        WHERE standardized_moneyness IS NOT NULL;
    """
    df_dist = conn.execute(dist_query).df()
    print(df_dist.to_string(index=False))

    # 3. Base-Rate Option Return Profile (Unconditioned Single-Candle Returns)
    print("\n=== [3/3] Single-Candle Option Base-Rate Returns ===")
    return_query = """
        SELECT 
            COUNT(*) as total_candles,
            SUM(CASE WHEN opt_pct_return >= 1.0 THEN 1 ELSE 0 END) as count_2x,
            ROUND(SUM(CASE WHEN opt_pct_return >= 1.0 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100, 4) as pct_2x,
            
            SUM(CASE WHEN opt_pct_return >= 4.0 THEN 1 ELSE 0 END) as count_5x,
            ROUND(SUM(CASE WHEN opt_pct_return >= 4.0 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100, 4) as pct_5x,
            
            SUM(CASE WHEN opt_pct_return >= 9.0 THEN 1 ELSE 0 END) as count_10x,
            ROUND(SUM(CASE WHEN opt_pct_return >= 9.0 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100, 4) as pct_10x
        FROM features_table
        WHERE volume_opt > 0; -- Only analyze candles with active transaction volume
    """
    df_return = conn.execute(return_query).df()
    print(df_return.to_string(index=False))

    conn.close()
    print("\nInspection complete!")

if __name__ == "__main__":
    main()