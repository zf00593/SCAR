import pandas as pd

# Files
data_file = "data\\religion.csv"
lookup_file = "data\\LA_region_lookup.xlsx"
output_file = "data\\religion_with_region.csv"

# Read main dataset
df = pd.read_csv(data_file)

# Read lookup file  <-- this creates the lookup variable
lookup = pd.read_excel(
    lookup_file,
    skiprows=4
)

# Check what columns were imported
print(lookup.columns)

# Rename columns
lookup = lookup.rename(columns={
    "LA code": "Lower tier local authorities Code",
    "Region name": "geography"
})

# Clean codes
df["Lower tier local authorities Code"] = (
    df["Lower tier local authorities Code"]
    .astype(str)
    .str.strip()
)
print('LOokup')
print(lookup.head())

lookup["Lower tier local authorities Code"] = (
    lookup["Lower tier local authorities Code"]
    .astype(str)
    .str.strip()
)

# Merge
df = df.merge(
    lookup[
        [
            "Lower tier local authorities Code",
            "geography"
        ]
    ],
    on="Lower tier local authorities Code",
    how="left"
)

# Check missing
missing = (
    df.loc[
        df["geography"].isna(),
        [
            "Lower tier local authorities Code",
            "Lower tier local authorities"
        ]
    ]
    .drop_duplicates()
)

if not missing.empty:
    print("Missing mappings:")
    print(missing.to_string(index=False))
else:
    print("All mapped successfully")

# Save
df.to_csv(output_file, index=False)

print(f"Saved {output_file}")