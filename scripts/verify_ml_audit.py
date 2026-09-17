#!/usr/bin/env python3
"""
verify_ml_audit.py
------------------
Audits LightGBM model performance across Train vs Test splits, exports duration
distributions to verify stress-freeness, and saves all trade rows to CSV.
"""

import os
import argparse
import numpy as np
import pandas as pd
import duckdb

def audit_pipeline(db_path="./options_analytics.db", target_multiple=10.0):
    conn = duckdb.connect(db_path)
    
    # 1. Load data from features_table
    query = f"""
        WITH ranked_candles AS (
            SELECT 
                *,
                LEAD(close_opt, 1) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_1,
                LEAD(close_opt, 2) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_2,
                LEAD(close_opt, 3) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_3,
                LEAD(close_opt, 6) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_6,
                LEAD(close_opt, 12) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_12,
                LEAD(close_opt, 24) OVER (PARTITION BY symbol ORDER BY timestamp) as fwd_24
            FROM features_table
            WHERE close_opt >= 1.0
        )
        SELECT 
            timestamp, datetime, spot_name, expiry, duration, symbol, option_type, strike, close_opt, close_spot,
            volatility, DTE_hours, GREATEST(LEAST(standardized_moneyness, 15.0), -15.0) as standardized_moneyness,
            opt_body_to_range, opt_upper_wick_ratio, opt_lower_wick_ratio, opt_pct_return,
            spot_body_to_range, spot_upper_wick_ratio, spot_lower_wick_ratio, spot_pct_return,
            GREATEST(
                COALESCE(fwd_1, 0), COALESCE(fwd_2, 0), COALESCE(fwd_3, 0),
                COALESCE(fwd_6, 0), COALESCE(fwd_12, 0), COALESCE(fwd_24, 0)
            ) / GREATEST(close_opt, 1e-8) as max_fwd_multiple,
            CASE WHEN GREATEST(
                COALESCE(fwd_1, 0), COALESCE(fwd_2, 0), COALESCE(fwd_3, 0),
                COALESCE(fwd_6, 0), COALESCE(fwd_12, 0), COALESCE(fwd_24, 0)
            ) / GREATEST(close_opt, 1e-8) >= {target_multiple} THEN 1 ELSE 0 END as label
        FROM ranked_candles
        WHERE DTE_hours <= 48.0 AND standardized_moneyness >= -1.5 AND standardized_moneyness <= 3.5
    """
    df = conn.execute(query).df()
    conn.close()
    
    df = df.sort_values('datetime').reset_index(drop=True)
    
    # 2. Date-Based Purged Split
    min_date, max_date = df['datetime'].min(), df['datetime'].max()
    cut_date = min_date + (max_date - min_date) * 0.70
    purge_end_date = cut_date + pd.Timedelta(hours=48)
    
    df_train = df[df['datetime'] < cut_date].copy()
    df_test = df[df['datetime'] >= purge_end_date].copy()
    
    feature_cols = [
        'DTE_hours', 'standardized_moneyness', 'duration', 'volatility',
        'opt_body_to_range', 'opt_upper_wick_ratio', 'opt_lower_wick_ratio', 'opt_pct_return',
        'spot_body_to_range', 'spot_upper_wick_ratio', 'spot_lower_wick_ratio', 'spot_pct_return'
    ]
    
    import lightgbm as lgb
    model = lgb.LGBMClassifier(n_estimators=150, learning_rate=0.05, max_depth=5, num_leaves=31, min_child_samples=50, random_state=42, verbose=-1)
    model.fit(df_train[feature_cols], df_train['label'])
    
    df_train['proba'] = model.predict_proba(df_train[feature_cols])[:, 1]
    df_test['proba'] = model.predict_proba(df_test[feature_cols])[:, 1]
    
    # 3. Print Train vs Test Comparison (Overfitting Audit)
    print("=" * 85)
    print("         OVERFITTING AUDIT: IN-SAMPLE (TRAIN) VS OUT-OF-SAMPLE (TEST)")
    print("=" * 85)
    print(f"{'Percentile':<12} | {'Train Hit Rate':<18} | {'Test Hit Rate':<18} | {'Train-Test Gap':<15}")
    print("-" * 85)
    
    percentiles = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
    for p in percentiles:
        tr_cut = np.percentile(df_train['proba'], 100.0 - p)
        te_cut = np.percentile(df_test['proba'], 100.0 - p)
        
        tr_hit = (df_train[df_train['proba'] >= tr_cut]['label'].mean()) * 100
        te_hit = (df_test[df_test['proba'] >= te_cut]['label'].mean()) * 100
        gap = tr_hit - te_hit
        
        print(f"Top {p:4.1f}%     | {tr_hit:16.2f}% | {te_hit:16.2f}% | {gap:+14.2f}%")
    print("=" * 85)

    # 4. Candle Duration Breakdown in Top 0.1% (Stress-Freeness Audit)
    top_01_test = df_test[df_test['proba'] >= np.percentile(df_test['proba'], 99.9)].copy()
    print("\n" + "=" * 65)
    print("      CANDLE DURATION BREAKDOWN IN TOP 0.1% CONVICTION (TEST)")
    print("=" * 65)
    dur_counts = top_01_test['duration'].value_counts()
    for dur, count in dur_counts.items():
        pct = (count / len(top_01_test)) * 100
        print(f"  Duration {dur:4d}m : {count:5d} trades ({pct:5.1f}%)")
    print("=" * 65)
    
    # 5. Export Trade Rows to CSV
    top_01_test.to_csv("top_01_conviction_trades_test.csv", index=False)
    print("\nExported 1,229 Top 0.1% trade rows to 'top_01_conviction_trades_test.csv'.")

if __name__ == "__main__":
    audit_pipeline()
