#!/usr/bin/env python3
"""Explore CSV files in the data directory."""
import pandas as pd
import os

data_dir = "data"
csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]

for csv_file in sorted(csv_files):
    file_path = os.path.join(data_dir, csv_file)
    print(f"\n{'='*80}")
    print(f"FILE: {csv_file}")
    print(f"{'='*80}")
    
    try:
        # Read full file to get shape
        df_full = pd.read_csv(file_path)
        print(f"Shape: {df_full.shape} (rows, columns)")
        print(f"\nColumns ({len(df_full.columns)}): {list(df_full.columns)}")
        print(f"\nData types:")
        print(df_full.dtypes)
        print(f"\nFirst 3 rows:")
        print(df_full.head(3).to_string())
    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
