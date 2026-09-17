#!/usr/bin/env python3
"""
Python Data Preprocessor & DuckDB Analytical Database Builder (Version 2)
-------------------------------------------------------------------------
This script walks through your local Node.js 'crypto_v2' data directory,
aligns option candles with spot candles, extracts high-duration candles (e.g., 60m, 240m, 1440m),
calculates scale-free mathematical features (normalized moneyness, realized volatility),
and appends them into a high-performance local DuckDB analytical database.

This v2 update resolves datatype errors caused by None/null values in raw volume or price columns,
and adds support for a --from-date filter to easily discard inconsistent older data.

Usage:
  python3 build_analytical_db_v2.py --data-dir ./data --db-path ./options_analytics.db --spot BTC,ETH --from-date 2024-03-01
"""

import os
import glob
import json
import argparse
import math
import numpy as np
import pandas as pd
import duckdb

def parse_args():
    parser = argparse.ArgumentParser(description="Build clean Parquet/DuckDB dataset from Node.js raw candles.")
    parser.add_argument("--data-dir", type=str, default="./data", help="Path to Node.js data/ directory.")
    parser.add_argument("--db-path", type=str, default="./options_analytics.db", help="Path to write DuckDB file.")
    parser.add_argument("--spot", type=str, default="BTC,ETH", help="Comma-separated spots to process.")
    parser.add_argument("--durations", type=str, default="60,240,1440", help="Option candle durations to process.")
    parser.add_argument("--from-date", type=str, default=None, help="Process only expiries on or after this date (YYYY-MM-DD).")
    return parser.parse_args()

def calculate_realized_volatility(df_spot, window=24):
    """
    Calculates rolling historical realized volatility (sigma) from spot close prices.
    Uses log returns over the specified lookback window.
    """
    # Coerce to numeric, handle potential NaNs safely
    closes = pd.to_numeric(df_spot['close'], errors='coerce').ffill().bfill().fillna(1.0).values
    log_returns = np.diff(np.log(np.maximum(closes, 1e-8)))
    # Pad first element to keep array length matching
    log_returns = np.insert(log_returns, 0, 0.0)
    
    # Calculate rolling standard deviation of log returns
    rolling_std = pd.Series(log_returns).rolling(window).std().fillna(0.0).values
    # Annualize the volatility (assuming hourly candles: 24 * 365 = 8760 periods/year)
    annualized_vol = rolling_std * math.sqrt(8760)
    # Floor at 10% to prevent division-by-zero or extreme values in quiet periods
    annualized_vol = np.clip(annualized_vol, 0.10, 5.0)
    return annualized_vol

def extract_agnostic_features(df, prefix=""):
    """
    Vectorized feature extraction over OHLCV candles.
    Generates scale-invariant features like body-to-range ratios and wicks.
    """
    df = df.copy()
    # Robust coercion to numeric to clean any None/null/string anomalies
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce').ffill().bfill().fillna(0.0)

    features = {}
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    open_p = df['open'].values
    
    # Range and body sizes
    candle_range = np.maximum(high - low, 1e-8)
    body = np.abs(close - open_p)
    
    # Feature 1: Body to full range ratio
    features[prefix + 'body_to_range'] = body / candle_range
    
    # Feature 2: Upper and Lower wicks normalized by range
    max_oc = np.maximum(open_p, close)
    min_oc = np.minimum(open_p, close)
    features[prefix + 'upper_wick_ratio'] = (high - max_oc) / candle_range
    features[prefix + 'lower_wick_ratio'] = (min_oc - low) / candle_range
    
    # Feature 3: Return momentum (pct change)
    features[prefix + 'pct_return'] = (close - open_p) / np.maximum(open_p, 1e-8)
    
    # Feature 4: Rolling volume ratios
    vol = df['volume'].values
    rolling_vol_mean = pd.Series(vol).rolling(20).mean().values
    features[prefix + 'vol_ratio_20'] = vol / np.maximum(rolling_vol_mean, 1e-8)
    
    # Ensure no floating NaNs or infs can enter the database
    df_features = pd.DataFrame(features, index=df.index)
    df_features = df_features.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    
    return df_features

def process_expiry(spot, expiry_dir, db_conn, target_durations):
    """
    Processes all option symbols for a single settled expiry date.
    Aligns with spot candles and appends the feature matrix to the DuckDB database.
    """
    expiry_date = os.path.basename(expiry_dir)
    print(f"  Processing Expiry: {expiry_date} ...")
    
    # Expiry settlement time (Standard falls to 17:30 IST / 12:00 UTC)
    # We can parse the exact timestamp format (e.g. 2025-11-28T17:30:00+0530)
    try:
        expiry_ts = pd.to_datetime(expiry_date + "T12:00:00Z").tz_localize(None)
    except:
        return
        
    for dur_str in target_durations:
        dur_mins = int(dur_str)
        option_dur_dir = os.path.join(expiry_dir, dur_str)
        if not os.path.exists(option_dur_dir):
            continue
            
        # 1. Load spot candles for this duration
        # Spot candles live in data/spot_candles/{SPOT}/{duration}/{YYYY-MM-DD}
        spot_dur_dir = os.path.join("data", "spot_candles", spot, dur_str)
        if not os.path.exists(spot_dur_dir):
            # If spot candles of target duration don't exist, we skip
            continue
            
        spot_files = sorted(glob.glob(os.path.join(spot_dur_dir, "*")))
        if not spot_files:
            continue
            
        # Compile spot candles into a single dataframe
        spot_list = []
        for sf in spot_files:
            try:
                with open(sf, 'r') as f:
                    data = json.load(f)
                    # data is format [[time, o, h, l, c, v], ...]
                    spot_list.extend(data)
            except Exception as e:
                pass
                
        if not spot_list:
            continue
            
        df_spot = pd.DataFrame(spot_list, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Clean spot columns for any None or NaN values
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df_spot[col] = pd.to_numeric(df_spot[col], errors='coerce').ffill().bfill().fillna(0.0)
            
        df_spot['datetime'] = pd.to_datetime(df_spot['timestamp'], unit='s')
        df_spot = df_spot.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        # Calculate Spot Realized Volatility (sigma)
        df_spot['volatility'] = calculate_realized_volatility(df_spot, window=24)
        
        # Extract spot candle features
        df_spot_features = extract_agnostic_features(df_spot, prefix="spot_")
        df_spot = pd.concat([df_spot, df_spot_features], axis=1)
        
        # 2. Iterate through all option symbols for this expiry
        symbol_paths = glob.glob(os.path.join(option_dur_dir, "*.json"))
        for sym_path in symbol_paths:
            symbol = os.path.basename(sym_path).replace(".json", "")
            
            # Parse symbol parts (e.g. C-BTC-95000-251128 or similar format)
            # Standard parts: [type, spot_name, strike, expiry]
            parts = symbol.split('-')
            if len(parts) < 3:
                continue
            option_type = parts[0] # 'C' or 'P'
            try:
                strike = float(parts[2])
            except ValueError:
                continue
                
            try:
                with open(sym_path, 'r') as f:
                    opt_data = json.load(f)
            except:
                continue
                
            if not opt_data:
                continue
                
            df_opt = pd.DataFrame(opt_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Clean option columns for any None or NaN values
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df_opt[col] = pd.to_numeric(df_opt[col], errors='coerce').ffill().bfill().fillna(0.0)
                
            df_opt['datetime'] = pd.to_datetime(df_opt['timestamp'], unit='s')
            df_opt = df_opt.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            # Align option candles with spot candles on timestamp
            df_merged = pd.merge(df_opt, df_spot, on='timestamp', suffixes=('_opt', '_spot'))
            if df_merged.empty:
                continue
                
            # Calculate Time-to-Expiry (TTE) in hours
            df_merged['DTE_hours'] = (expiry_ts - df_merged['datetime_opt']).dt.total_seconds() / 3600.0
            # Keep only rows where DTE is positive and spot volatility is positive
            df_merged = df_merged[(df_merged['DTE_hours'] > 0) & (df_merged['volatility'] > 0)].copy()
            if df_merged.empty:
                continue
                
            # Calculate Standardized Moneyness: ln(K/S) / (sigma * sqrt(T))
            # Standardizing time T in years: DTE_hours / 8760
            T_years = df_merged['DTE_hours'] / 8760.0
            df_merged['standardized_moneyness'] = np.log(strike / df_merged['close_spot']) / (df_merged['volatility'] * np.sqrt(T_years))
            
            # Calculate Option-level scale-free features
            df_opt_features = extract_agnostic_features(df_merged.rename(columns={
                'open_opt': 'open', 'high_opt': 'high', 'low_opt': 'low', 'close_opt': 'close', 'volume_opt': 'volume'
            }), prefix="opt_")
            df_merged = pd.concat([df_merged, df_opt_features], axis=1)
            
            # Add metadata columns
            df_merged['spot_name'] = spot
            df_merged['expiry'] = expiry_date
            df_merged['duration'] = dur_mins
            df_merged['symbol'] = symbol
            df_merged['option_type'] = option_type
            df_merged['strike'] = strike
            
            # Clean up column names for database storage
            cols_to_keep = [
                'timestamp', 'datetime_opt', 'spot_name', 'expiry', 'duration', 'symbol', 'option_type', 'strike',
                'open_opt', 'high_opt', 'low_opt', 'close_opt', 'volume_opt',
                'close_spot', 'volatility', 'DTE_hours', 'standardized_moneyness',
                'opt_body_to_range', 'opt_upper_wick_ratio', 'opt_lower_wick_ratio', 'opt_pct_return', 'opt_vol_ratio_20',
                'spot_body_to_range', 'spot_upper_wick_ratio', 'spot_lower_wick_ratio', 'spot_pct_return', 'spot_vol_ratio_20'
            ]
            
            # Subset and rename
            df_db = df_merged[cols_to_keep].rename(columns={
                'datetime_opt': 'datetime',
                'open_opt': 'open_opt',
                'high_opt': 'high_opt',
                'low_opt': 'low_opt',
                'close_opt': 'close_opt',
                'volume_opt': 'volume_opt'
            })
            
            # Append DataFrame to DuckDB table
            db_conn.execute("INSERT INTO features_table SELECT * FROM df_db")

def main():
    args = parse_args()
    spots = args.spot.split(',')
    target_durations = args.durations.split(',')
    
    print(f"Initializing DuckDB Analytical Database: {args.db_path} ...")
    db_conn = duckdb.connect(args.db_path)
    
    # Create master analytical table
    db_conn.execute("""
        CREATE TABLE IF NOT EXISTS features_table (
            timestamp BIGINT,
            datetime TIMESTAMP,
            spot_name VARCHAR,
            expiry VARCHAR,
            duration INTEGER,
            symbol VARCHAR,
            option_type VARCHAR,
            strike DOUBLE,
            open_opt DOUBLE,
            high_opt DOUBLE,
            low_opt DOUBLE,
            close_opt DOUBLE,
            volume_opt DOUBLE,
            close_spot DOUBLE,
            volatility DOUBLE,
            DTE_hours DOUBLE,
            standardized_moneyness DOUBLE,
            opt_body_to_range DOUBLE,
            opt_upper_wick_ratio DOUBLE,
            opt_lower_wick_ratio DOUBLE,
            opt_pct_return DOUBLE,
            opt_vol_ratio_20 DOUBLE,
            spot_body_to_range DOUBLE,
            spot_upper_wick_ratio DOUBLE,
            spot_lower_wick_ratio DOUBLE,
            spot_pct_return DOUBLE,
            spot_vol_ratio_20 DOUBLE
        )
    """)
    
    # Walk directory to find expiries
    # Format: data/candles/{SPOT}/{expiry}/{duration}/{symbol}.json
    for spot in spots:
        spot_candles_dir = os.path.join(args.data_dir, "candles", spot)
        if not os.path.exists(spot_candles_dir):
            print(f"Warning: Spot candles directory not found: {spot_candles_dir}")
            continue
            
        expiry_dirs = sorted(glob.glob(os.path.join(spot_candles_dir, "*")))
        print(f"Found {len(expiry_dirs)} expiries for Spot: {spot}")
        
        processed_count = 0
        skipped_count = 0
        for exp_dir in expiry_dirs:
            if os.path.isdir(exp_dir):
                expiry_date = os.path.basename(exp_dir)
                if args.from_date and expiry_date < args.from_date:
                    skipped_count += 1
                    continue
                process_expiry(spot, exp_dir, db_conn, target_durations)
                processed_count += 1
                
        if args.from_date:
            print(f"Summary for {spot}: Processed {processed_count} expiries, skipped {skipped_count} expiries (before {args.from_date})")
                
    # Close connection and show metrics
    row_count = db_conn.execute("SELECT COUNT(*) FROM features_table").fetchone()[0]
    print("\n-------------------------------------------------------------")
    print(f"Database Compilation Complete!")
    print(f"Total rows ingested: {row_count:,}")
    print(f"DuckDB database saved successfully to: {args.db_path}")
    print("-------------------------------------------------------------")
    db_conn.close()

if __name__ == "__main__":
    main()
