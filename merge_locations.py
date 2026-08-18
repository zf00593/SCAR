import pandas as pd

# Files
data_file = "C:\\Users\\Administrator\\Documents\\SCAR\\data\\TS030-2021-3.csv"
mapping_file = "C:\\Users\\Administrator\\Documents\\SCAR\\data\\location_mapping.csv"
output_file = "religion_per_region.csv"

# Read the files
df = pd.read_csv(data_file)
print(df.head())
mapping = pd.read_csv(mapping_file)
print(mapping.head())

# Remove accidental spaces
df["Lower tier local authorities"] = (
    df["Lower tier local authorities"]
    .astype(str)
    .str.strip()
)

mapping["Local area"] = (
    mapping["Local area"]
    .astype(str)
    .str.strip()
)

# Merge geography
df = df.merge(
    mapping,
    left_on="Lower tier local authorities",
    right_on="Local area",
    how="left"
)

# Rename region column
df.rename(
    columns={"High-level region": "geography"},
    inplace=True
)

# Remove duplicate name column
df.drop(columns=["Local area"], inplace=True)

# Check unmapped authorities
unmapped = (
    df.loc[
        df["geography"].isna(),
        "Lower tier local authorities"
    ]
    .drop_duplicates()
)

if len(unmapped) > 0:
    print("WARNING: These authorities were not mapped:")
    print(unmapped.to_string(index=False))
else:
    print("All authorities successfully mapped.")

# Save
df.to_csv(output_file, index=False)

print(f"Saved to {output_file}")