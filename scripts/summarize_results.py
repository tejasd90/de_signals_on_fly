#!/usr/bin/env python3
"""
summarize_results.py (v2 - Fixed KeyError)
------------------------------------------
Scans local data/multibaggers and data/trades JSON files to extract 
total counts, Call/Put splits, and hit rates across 5x, 10x, 20x, 50x, 100x multiples.
"""

import os
import glob
import json

def summarize_multibaggers(data_dir="./data"):
    mb_dir = os.path.join(data_dir, "multibaggers")
    if not os.path.exists(mb_dir):
        print(f"Directory not found: {mb_dir}")
        return

    json_files = glob.glob(os.path.join(mb_dir, "**", "*.json"), recursive=True)
    json_files = [f for f in json_files if not f.endswith("_summary.json")]
    
    if not json_files:
        print("No multibagger JSON files found.")
        return

    total_expiries = len(json_files)
    total_trades = 0
    c_count = 0
    p_count = 0
    
    thresholds = [5, 10, 20, 50, 100]
    counts = {t: 0 for t in thresholds}

    for fpath in json_files:
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
                rows = data.get("rows", data) if isinstance(data, dict) else data
                if not isinstance(rows, list):
                    continue
                for r in rows:
                    total_trades += 1
                    ratio = r.get("ratio", r.get("peakRatio", 0))
                    opt_type = r.get("type", r.get("option_type", ""))
                    if opt_type == 'C': c_count += 1
                    elif opt_type == 'P': p_count += 1
                    
                    for t in thresholds:
                        if ratio >= t:
                            counts[t] += 1
        except Exception:
            continue

    print("=" * 60)
    print("           MULTIBAGGERS GROUND-TRUTH SUMMARY           ")
    print("=" * 60)
    print(f"Total Expiries Processed : {total_expiries}")
    print(f"Total Multibagger Trades : {total_trades:,} (Calls: {c_count:,}, Puts: {p_count:,})")
    print("-" * 60)
    print(f"  >=  5x Peak Moves      : {counts[5]:,} trades")
    print(f"  >= 10x Peak Moves      : {counts[10]:,} trades")
    print(f"  >= 20x Peak Moves      : {counts[20]:,} trades")
    print(f"  >= 50x Peak Moves      : {counts[50]:,} trades")
    print(f"  >=100x Peak Moves      : {counts[100]:,} trades")
    print("=" * 60)

def summarize_trades(data_dir="./data"):
    tr_dir = os.path.join(data_dir, "trades")
    if not os.path.exists(tr_dir):
        return

    json_files = glob.glob(os.path.join(tr_dir, "**", "*.json"), recursive=True)
    valid_files = [f for f in json_files if not f.endswith("_summary.json")]
    print(f"\nFound {len(valid_files)} partitioned trade window files in {tr_dir}.")

if __name__ == "__main__":
    summarize_multibaggers()
    summarize_trades()
