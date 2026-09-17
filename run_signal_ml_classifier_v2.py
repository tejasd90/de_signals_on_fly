#!/usr/bin/env python3
"""
run_signal_ml_classifier_v2.py
------------------------------
Automated ML Joint Conviction & Target Multiple Matrix Generator.

Computes the entire joint distribution of out-of-sample hit rates, trade counts, 
and Net Expected Values (+EV) across ALL target multiples (2x, 5x, 10x, 20x, 25x, 50x, 100x)
and ALL conviction percentiles (Top 0.1% to 20%) in a single execution pass.
"""

import os
import argparse
import numpy as np
import pandas as pd
import duckdb

def parse_args():
    parser = argparse.ArgumentParser(description="Automated Joint Distribution ML Matrix Generator")
    parser.add_argument("--db-path", type=str, default="./options_analytics.db", help="Path to DuckDB database.")
    return parser.parse_args()

def check_lightgbm():
    try:
        import lightgbm as lgb
        return True
    except ImportError:
        return False

def load_analytical_features(conn):
    print("Connecting to DuckDB and loading candidate features...")
    query = """
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
            WHERE close_opt >= 1.0  -- Filter tick-floor dust
        )
        SELECT 
            timestamp,
            datetime,
            spot_name,
            expiry,
            duration,
            symbol,
            option_type,
            strike,
            close_opt,
            close_spot,
            volatility,
            DTE_hours,
            GREATEST(LEAST(standardized_moneyness, 15.0), -15.0) as standardized_moneyness,
            opt_body_to_range,
            opt_upper_wick_ratio,
            opt_lower_wick_ratio,
            opt_pct_return,
            spot_body_to_range,
            spot_upper_wick_ratio,
            spot_lower_wick_ratio,
            spot_pct_return,
            -- Actual max forward multiple achieved over next 24 candles
            GREATEST(
                COALESCE(fwd_1, 0), COALESCE(fwd_2, 0), COALESCE(fwd_3, 0),
                COALESCE(fwd_6, 0), COALESCE(fwd_12, 0), COALESCE(fwd_24, 0)
            ) / GREATEST(close_opt, 1e-8) as max_fwd_multiple
        FROM ranked_candles
    """
    df = conn.execute(query).df()
    return df

def run_joint_distribution_analysis(df):
    print("\n" + "="*80)
    print("      JOINT CONVICTION vs. MULTIBAGGER TARGET DISTRIBUTION MATRIX")
    print("="*80)
    
    feature_cols = [
        'DTE_hours', 'standardized_moneyness', 'duration',
        'volatility', 'opt_body_to_range', 'opt_upper_wick_ratio',
        'opt_lower_wick_ratio', 'opt_pct_return', 'spot_body_to_range',
        'spot_upper_wick_ratio', 'spot_lower_wick_ratio', 'spot_pct_return'
    ]
    
    # 1. Binary Label for training classifier (Target 10.0x for primary objective)
    df['label_10x'] = (df['max_fwd_multiple'] >= 10.0).astype(int)
    
    # 2. Response Surface Veto Gate Filter
    surface_mask = (df['DTE_hours'] <= 48.0) & (df['standardized_moneyness'] >= -1.5) & (df['standardized_moneyness'] <= 3.5)
    df_surface = df[surface_mask].copy()
    
    total_raw = len(df)
    total_surf = len(df_surface)
    print(f"Total Candidate Database Rows : {total_raw:,}")
    print(f"Retained in Surface Pocket    : {total_surf:,} ({total_surf/total_raw*100:.1f}%)")
    
    # 3. Purged Walk-Forward Split (70/30)
    df_surface = df_surface.sort_values('datetime').reset_index(drop=True)
    min_date = df_surface['datetime'].min()
    max_date = df_surface['datetime'].max()
    time_span = max_date - min_date
    cut_date = min_date + time_span * 0.70
    purge_end_date = cut_date + pd.Timedelta(hours=48)
    
    train_mask = df_surface['datetime'] < cut_date
    test_mask = df_surface['datetime'] >= purge_end_date
    
    df_train = df_surface[train_mask]
    df_test = df_surface[test_mask].copy()
    
    X_train, y_train = df_train[feature_cols], df_train['label_10x']
    X_test = df_test[feature_cols]
    
    print(f"Train Period : {min_date} to {cut_date} ({len(df_train):,} rows - {len(df_train)/total_surf*100:.1f}%)")
    print(f"Purge Buffer : {cut_date} to {purge_end_date} (48h boundary purge)")
    print(f"Test Period  : {purge_end_date} to {max_date} ({len(df_test):,} rows - {len(df_test)/total_surf*100:.1f}%)")
    
    # 4. Train Model
    has_lgb = check_lightgbm()
    if has_lgb:
        import lightgbm as lgb
        print("\nTraining LightGBM Classifier...")
        model = lgb.LGBMClassifier(
            n_estimators=150, learning_rate=0.05, max_depth=5,
            num_leaves=31, min_child_samples=50, subsample=0.8,
            colsample_bytree=0.8, random_state=42, verbose=-1
        )
        model.fit(X_train, y_train)
        preds_proba = model.predict_proba(X_test)[:, 1]
    else:
        from sklearn.ensemble import RandomForestClassifier
        print("\nTraining Random Forest Classifier...")
        model = RandomForestClassifier(n_estimators=100, max_depth=6, min_samples_leaf=50, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)
        preds_proba = model.predict_proba(X_test)[:, 1]
        
    df_test['pred_proba'] = preds_proba
    
    # 5. Build Joint Distribution Matrix
    percentiles = [0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 100.0]
    target_multiples = [2.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0]
    
    print("\n" + "="*95)
    print("           OUT-OF-SAMPLE HIT RATE MATRIX (%) BY CONVICTION vs TARGET MULTIPLE")
    print("="*95)
    header = f"{'Conviction %':<12} | {'Trades':<8} | " + " | ".join([f"{m:>6.0f}x" for m in target_multiples])
    print(header)
    print("-" * len(header))
    
    n_test = len(df_test)
    for p in percentiles:
        if p == 100.0:
            sub = df_test
            p_label = "Unconditioned"
        else:
            cutoff = np.percentile(preds_proba, 100.0 - p)
            sub = df_test[df_test['pred_proba'] >= cutoff]
            p_label = f"Top {p}%"
            
        n_sub = len(sub)
        row_str = f"{p_label:<12} | {n_sub:<8,} | "
        hit_rates = []
        for m in target_multiples:
            hits = (sub['max_fwd_multiple'] >= m).sum()
            rate = (hits / n_sub * 100.0) if n_sub > 0 else 0.0
            hit_rates.append(f"{rate:>5.2f}%")
        print(row_str + " | ".join(hit_rates))
        
    print("="*95)

    print("\n" + "="*95)
    print("           NET EXPECTED VALUE (+EV) MATRIX (Return per 1.0 Unit Risk)")
    print("="*95)
    header_ev = f"{'Conviction %':<12} | {'Trades':<8} | " + " | ".join([f"{m:>6.0f}x" for m in target_multiples])
    print(header_ev)
    print("-" * len(header_ev))
    
    for p in percentiles:
        if p == 100.0:
            sub = df_test
            p_label = "Unconditioned"
        else:
            cutoff = np.percentile(preds_proba, 100.0 - p)
            sub = df_test[df_test['pred_proba'] >= cutoff]
            p_label = f"Top {p}%"
            
        n_sub = len(sub)
        row_str = f"{p_label:<12} | {n_sub:<8,} | "
        ev_vals = []
        for m in target_multiples:
            hits = (sub['max_fwd_multiple'] >= m).sum()
            win_rate = (hits / n_sub) if n_sub > 0 else 0.0
            # Net EV: Win pays (m - 1.0) net, Loss costs -1.0
            ev = (win_rate * (m - 1.0)) - ((1.0 - win_rate) * 1.0)
            sign = "+" if ev >= 0 else ""
            ev_vals.append(f"{sign}{ev:>5.2f}x")
        print(row_str + " | ".join(ev_vals))
    print("="*95)

def main():
    args = parse_args()
    if not os.path.exists(args.db_path):
        print(f"Error: Database file not found at {args.db_path}")
        return
        
    conn = duckdb.connect(args.db_path)
    df = load_analytical_features(conn)
    run_joint_distribution_analysis(df)
    conn.close()

if __name__ == "__main__":
    main()
