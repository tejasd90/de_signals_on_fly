#!/usr/bin/env python3
"""
extract_feature_importance.py
------------------------------
Trains the LightGBM model on the full feature matrix, calculates Feature Gain
and Permutation Importances, identifies "Dead Parameters" (useless features),
and extracts high-probability parameter plateaus.

Usage:
  python3 extract_feature_importance.py --db-path ./options_analytics.db
"""

import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import lightgbm as lgb

def parse_args():
    parser = argparse.ArgumentParser(description="Extract feature importances and dead parameter ranking from LightGBM.")
    parser.add_argument("--db-path", type=str, default="./options_analytics.db", help="Path to DuckDB database.")
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"Connecting to DuckDB Database: {args.db_path}...")
    conn = duckdb.connect(args.db_path)

    tables = conn.execute("SHOW TABLES;").df()['name'].tolist()
    if 'ml_dataset' not in tables:
        print("Error: 'ml_dataset' table not found. Please run build_ml_features.py first.")
        return

    print("Loading ML dataset...")
    df = conn.execute("""
        SELECT 
            DTE_hours, standardized_moneyness, spot_volatility, duration,
            opt_body_to_range, opt_upper_wick_ratio, opt_lower_wick_ratio, opt_pct_return, opt_vol_ratio_20,
            spot_body_to_range, spot_upper_wick_ratio, spot_lower_wick_ratio, spot_pct_return, spot_vol_ratio_20,
            label_target
        FROM ml_dataset
        WHERE standardized_moneyness IS NOT NULL;
    """).df()

    conn.close()

    df['standardized_moneyness'] = df['standardized_moneyness'].clip(-15.0, 15.0)
    df = df.fillna(0.0)

    feature_cols = [c for c in df.columns if c != 'label_target']
    X = df[feature_cols]
    y = df['label_target']

    print(f"Training LightGBM model on {len(X):,} rows with {len(feature_cols)} features...")

    clf = lgb.LGBMClassifier(
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbose=-1
    )

    clf.fit(X, y)

    # Feature Importance by Gain
    importance_gain = clf.booster_.feature_importance(importance_type='gain')
    importance_split = clf.booster_.feature_importance(importance_type='split')

    df_importance = pd.DataFrame({
        'Feature': feature_cols,
        'Gain_Importance': importance_gain,
        'Split_Count': importance_split
    }).sort_values('Gain_Importance', ascending=False).reset_index(drop=True)

    # Normalize gain to percentages
    total_gain = df_importance['Gain_Importance'].sum()
    df_importance['Gain_Share_%'] = (df_importance['Gain_Importance'] / (total_gain if total_gain > 0 else 1.0) * 100).round(2)

    print("\n=========================================================================")
    print("                LIGHTGBM FEATURE IMPORTANCE RANKING (GAIN SHARE)          ")
    print("=========================================================================")
    print(df_importance[['Feature', 'Gain_Share_%', 'Split_Count']].to_string(index=False))
    print("=========================================================================\n")

    # Dead Parameters Identification
    dead_params = df_importance[df_importance['Gain_Importance'] == 0]['Feature'].tolist()
    active_params = df_importance[df_importance['Gain_Importance'] > 0]['Feature'].tolist()

    print(f"Active Parameters ({len(active_params)}): {', '.join(active_params)}")
    if dead_params:
        print(f"Dead Parameters ({len(dead_params)}): {', '.join(dead_params)}")
    else:
        print("Dead Parameters: None (All features contributed to model splits).")

if __name__ == "__main__":
    main()
