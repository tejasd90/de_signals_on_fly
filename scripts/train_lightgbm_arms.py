#!/usr/bin/env python3
"""
train_lightgbm_arms.py
----------------------
Trains LightGBM Models across 4 Feature Arms utilizing a Date-Purged
Walk-Forward Cross-Validation scheme. Compares model performance to answer whether
structural candle patterns add predictive lift over baseline market context.

Usage:
  python3 train_lightgbm_arms.py --db-path ./options_analytics.db
"""

import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, precision_score, average_precision_score

def parse_args():
    parser = argparse.ArgumentParser(description="Train LightGBM feature arms with Purged Walk-Forward CV.")
    parser.add_argument("--db-path", type=str, default="./options_analytics.db", help="Path to DuckDB database.")
    return parser.parse_args()

def define_feature_arms():
    arm0_context = ['DTE_hours', 'standardized_moneyness', 'duration']
    
    arm1_agnostic = arm0_context + [
        'spot_volatility',
        'opt_body_to_range', 'opt_upper_wick_ratio', 'opt_lower_wick_ratio', 'opt_pct_return',
        'spot_body_to_range', 'spot_upper_wick_ratio', 'spot_lower_wick_ratio', 'spot_pct_return'
    ]
    
    arm2_structural = arm0_context + [
        'opt_vol_ratio_20', 'spot_vol_ratio_20', 'opt_pct_return', 'spot_pct_return'
    ]
    
    arm3_full = list(set(arm1_agnostic + arm2_structural))
    
    return {
        "Arm 0: Context Only (Baseline)": arm0_context,
        "Arm 1: Context + Agnostic Shapes": arm1_agnostic,
        "Arm 2: Context + Pattern Dynamics": arm2_structural,
        "Arm 3: Full Feature Stack": arm3_full
    }

def main():
    args = parse_args()
    print(f"Connecting to DuckDB Database: {args.db_path}...")
    conn = duckdb.connect(args.db_path)

    tables = conn.execute("SHOW TABLES;").df()['name'].tolist()
    if 'ml_dataset' not in tables:
        print("Error: 'ml_dataset' table not found. Please run build_ml_features.py first.")
        return

    print("Loading ML dataset into memory...")
    df = conn.execute("""
        SELECT 
            datetime, expiry, duration, symbol,
            DTE_hours, standardized_moneyness, spot_volatility,
            opt_body_to_range, opt_upper_wick_ratio, opt_lower_wick_ratio, opt_pct_return, opt_vol_ratio_20,
            spot_body_to_range, spot_upper_wick_ratio, spot_lower_wick_ratio, spot_pct_return, spot_vol_ratio_20,
            fwd_max_multiple, label_target
        FROM ml_dataset
        WHERE standardized_moneyness IS NOT NULL
        ORDER BY datetime;
    """).df()

    conn.close()

    if df.empty:
        print("Error: Dataset is empty.")
        return

    # Clean infinity and NaN values
    df['standardized_moneyness'] = df['standardized_moneyness'].clip(-15.0, 15.0)
    df = df.fillna(0.0)

    # Date-Based Walk-Forward Purged Split (70% Train / 30% Test chronologically)
    dates = sorted(df['datetime'].unique())
    split_idx = int(len(dates) * 0.7)
    split_date = dates[split_idx]

    # Enforce 48-hour purge buffer around boundary to prevent lookahead leakage
    purge_buffer_start = pd.to_datetime(split_date) - pd.Timedelta(hours=48)
    purge_buffer_end = pd.to_datetime(split_date) + pd.Timedelta(hours=48)

    train_df = df[df['datetime'] < purge_buffer_start].copy()
    test_df = df[df['datetime'] > purge_buffer_end].copy()

    print("\n=============================================================")
    print("      PURGED WALK-FORWARD CROSS-VALIDATION SPLIT SUMMARY     ")
    print("=============================================================")
    print(f"Train Period : {train_df['datetime'].min()} to {train_df['datetime'].max()} ({len(train_df):,} rows)")
    print(f"Purge Buffer : {purge_buffer_start} to {purge_buffer_end} (Purged)")
    print(f"Test Period  : {test_df['datetime'].min()} to {test_df['datetime'].max()} ({len(test_df):,} rows)")
    print(f"Base 10x Target Hit Rate (Train): {train_df['label_target'].mean()*100:.3f}%")
    print(f"Base 10x Target Hit Rate (Test) : {test_df['label_target'].mean()*100:.3f}%")
    print("=============================================================\n")

    feature_arms = define_feature_arms()
    results = []

    print("Training LightGBM models across Feature Arms...\n")

    for arm_name, features in feature_arms.items():
        X_train = train_df[features]
        y_train = train_df['label_target']
        X_test = test_df[features]
        y_test = test_df['label_target']

        # LightGBM Classifier with strong regularization to handle financial noise
        clf = lgb.LGBMClassifier(
            n_estimators=150,
            learning_rate=0.03,
            num_leaves=31,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )

        clf.fit(X_train, y_train)

        # Predict probabilities on test set
        preds_prob = clf.predict_proba(X_test)[:, 1]

        # Calculate metrics
        auc_score = roc_auc_score(y_test, preds_prob) if len(np.unique(y_test)) > 1 else 0.5
        pr_auc = average_precision_score(y_test, preds_prob) if len(np.unique(y_test)) > 1 else 0.0

        # Measure Precision@Top 5% Predictions
        top_5_pct_cutoff = np.percentile(preds_prob, 95)
        top_5_preds = (preds_prob >= top_5_pct_cutoff).astype(int)
        precision_top_5 = precision_score(y_test, top_5_preds, zero_division=0)

        # Compute Multiple Lift over base rate
        base_rate = y_test.mean()
        multiple_lift = (precision_top_5 / base_rate) if base_rate > 0 else 1.0

        results.append({
            "Feature Arm": arm_name,
            "Features": len(features),
            "ROC-AUC": round(auc_score, 4),
            "PR-AUC": round(pr_auc, 4),
            "Precision @ Top 5%": f"{precision_top_5*100:.2f}%",
            "Multiple Lift": f"{multiple_lift:.2f}x"
        })

    df_results = pd.DataFrame(results)
    
    print("=========================================================================================")
    print("                      LIGHTGBM MULTI-ARM EVALUATION RESULTS                              ")
    print("=========================================================================================")
    print(df_results.to_string(index=False))
    print("=========================================================================================\n")

if __name__ == "__main__":
    main()
