#!/usr/bin/env python3
"""
build_ml_features.py
--------------------
Reads from local DuckDB 'options_analytics.db', calculates forward-looking
target labels (Modified Triple-Barrier / Forward Payoff Multiples), builds
multi-arm feature matrices, and writes a clean 'ml_dataset' table into DuckDB.

Usage:
  python3 build_ml_features.py --db-path ./options_analytics.db --target-multiple 10.0
"""

import os
import argparse
import duckdb
import pandas as pd
import numpy as np

def parse_args():
    parser = argparse.ArgumentParser(description="Build ML feature dataset from DuckDB analytics database.")
    parser.add_argument("--db-path", type=str, default="./options_analytics.db", help="Path to DuckDB database.")
    parser.add_argument("--target-multiple", type=float, default=10.0, help="Target payoff multiple for binary label (e.g. 10.0 for 10x).")
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"Connecting to DuckDB Database: {args.db_path}...")
    conn = duckdb.connect(args.db_path)

    print("Checking database schema and table availability...")
    tables = conn.execute("SHOW TABLES;").df()['name'].tolist()
    if 'features_table' not in tables:
        print("Error: 'features_table' not found in database. Please run build_analytical_db_v2.py first.")
        return

    print("Building ML feature dataset and forward-looking target labels...")
    
    # Create ml_dataset table in DuckDB
    # Calculates forward 24-candle peak return and binary label (target >= target_multiple)
    conn.execute(f"""
        DROP TABLE IF EXISTS ml_dataset;
        
        CREATE TABLE ml_dataset AS
        WITH forward_peaks AS (
            SELECT 
                timestamp,
                datetime,
                spot_name,
                expiry,
                duration,
                symbol,
                option_type,
                strike,
                open_opt,
                high_opt,
                low_opt,
                close_opt,
                close_spot,
                volatility as spot_volatility,
                DTE_hours,
                standardized_moneyness,
                opt_body_to_range,
                opt_upper_wick_ratio,
                opt_lower_wick_ratio,
                opt_pct_return,
                opt_vol_ratio_20,
                spot_body_to_range,
                spot_upper_wick_ratio,
                spot_lower_wick_ratio,
                spot_pct_return,
                spot_vol_ratio_20,
                -- Compute forward 24-candle peak price using window functions
                MAX(high_opt) OVER (
                    PARTITION BY symbol, duration 
                    ORDER BY timestamp 
                    ROWS BETWEEN 1 FOLLOWING AND 24 FOLLOWING
                ) as fwd_peak_high,
                -- Compute forward 24-candle minimum low (for stop-loss check)
                MIN(low_opt) OVER (
                    PARTITION BY symbol, duration 
                    ORDER BY timestamp 
                    ROWS BETWEEN 1 FOLLOWING AND 24 FOLLOWING
                ) as fwd_min_low
            FROM features_table
            WHERE close_opt >= 1.0 -- Filter out sub-1 satoshi tick-floor dust
        )
        SELECT 
            *,
            -- Forward Peak Multiple achieved from Close
            CASE WHEN close_opt > 0 THEN fwd_peak_high / close_opt ELSE 0.0 END as fwd_max_multiple,
            -- Binary Label: Achieved target multiple (e.g. >= 10x) AND did not drop >50% immediately
            CASE 
                WHEN close_opt > 0 AND (fwd_peak_high / close_opt) >= {args.target_multiple} 
                     AND (fwd_min_low / close_opt) >= 0.5 
                THEN 1 ELSE 0 
            END as label_target
        FROM forward_peaks
        WHERE fwd_peak_high IS NOT NULL;
    """)

    # Print summary metrics of generated dataset
    dataset_summary = conn.execute("""
        SELECT 
            COUNT(*) as total_samples,
            SUM(label_target) as positive_samples,
            ROUND(AVG(label_target) * 100, 4) as positive_pct,
            MIN(datetime) as min_date,
            MAX(datetime) as max_date
        FROM ml_dataset;
    """).df()

    print("\n=============================================================")
    print("              ML DATASET GENERATION COMPLETE                 ")
    print("=============================================================")
    print(dataset_summary.to_string(index=False))
    print("=============================================================\n")

    conn.close()

if __name__ == "__main__":
    main()
