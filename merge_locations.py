import pandas as pd

# Files
#data_file = "data\\religion.csv"

def religion_mapping():
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
    

def ethnicity_mapping():
        

    # Files
    data_file = "data\\ethnic.csv"
    lookup_file = "data\\LA_region_lookup.xlsx"
    output_file = "data\\ethnicity_with_region.csv"


    # ==========================================
    # 1. Load your ethnicity data
    # ==========================================

    df = pd.read_csv(data_file)

    print("Main data columns:")
    print(df.columns.tolist())


    # ==========================================
    # 2. Load ONS lookup WITHOUT headers
    # ==========================================

    lookup_raw = pd.read_excel(
        lookup_file,
        header=None
    )


    # ==========================================
    # 3. Find the row containing "LA code"
    # ==========================================

    header_row = None

    for i in range(len(lookup_raw)):

        row = lookup_raw.iloc[i].astype(str).str.strip().tolist()

        if "LA code" in row:
            header_row = i
            break


    if header_row is None:
        raise ValueError(
            "Could not find the 'LA code' row in the lookup file."
        )

    print(f"Lookup header found on row {header_row}")


    # ==========================================
    # 4. Extract the actual lookup table
    # ==========================================

    lookup = lookup_raw.iloc[header_row + 1:].copy()

    # Based on the ONS file:
    #
    # Column 0 = LA code
    # Column 1 = LA name
    # Column 2 = Region code
    # Column 3 = Region name

    lookup = lookup.iloc[:, [0, 3]]

    lookup.columns = [
        "Lower tier local authorities Code",
        "geography"
    ]


    # ==========================================
    # 5. Clean the codes
    # ==========================================

    df["Lower tier local authorities Code"] = (
        df["Lower tier local authorities Code"]
        .astype(str)
        .str.strip()
    )

    lookup["Lower tier local authorities Code"] = (
        lookup["Lower tier local authorities Code"]
        .astype(str)
        .str.strip()
    )

    lookup["geography"] = (
        lookup["geography"]
        .astype(str)
        .str.strip()
    )


    # ==========================================
    # 6. Remove blank rows
    # ==========================================

    lookup = lookup[
        lookup["Lower tier local authorities Code"].notna()
    ]

    lookup = lookup[
        lookup["Lower tier local authorities Code"] != "nan"
    ]


    # ==========================================
    # 7. Check the lookup BEFORE merging
    # ==========================================

    print("\nSample lookup:")
    print(lookup.head(10).to_string(index=False))


    # ==========================================
    # 8. Merge using LA CODE
    # ==========================================

    df = df.merge(
        lookup,
        on="Lower tier local authorities Code",
        how="left"
    )


    # ==========================================
    # 9. Check unmapped authorities
    # ==========================================

    unmapped = (
        df.loc[
            df["geography"].isna(),
            [
                "Lower tier local authorities Code",
                "Lower tier local authorities"
            ]
        ]
        .drop_duplicates()
        .sort_values("Lower tier local authorities Code")
    )

    if not unmapped.empty:

        print("\nWARNING - UNMAPPED AUTHORITIES:")
        print(unmapped.to_string(index=False))

    else:

        print("\nAll local authorities successfully mapped!")


    # ==========================================
    # 10. Check the actual result
    # ==========================================

    print("\nResult sample:")
    print(
        df[
            [
                "Lower tier local authorities Code",
                "Lower tier local authorities",
                "geography"
            ]
        ]
        .drop_duplicates()
        .head(20)
        .to_string(index=False)
    )


    # ==========================================
    # 11. Save
    # ==========================================

    df.to_csv(
        output_file,
        index=False
    )

    print(f"\nSaved to: {output_file}")
    
#ethnicity_mapping()


def sex_mapping():
        

    # Files
    data_file = "data\\sex.csv"
    lookup_file = "data\\LA_region_lookup.xlsx"
    output_file = "data\\sex_with_region.csv"


    # ==========================================
    # 1. Load your sex data
    # ==========================================

    df = pd.read_csv(data_file)

    print("Main data columns:")
    print(df.columns.tolist())


    # ==========================================
    # 2. Load ONS lookup WITHOUT headers
    # ==========================================

    lookup_raw = pd.read_excel(
        lookup_file,
        header=None
    )


    # ==========================================
    # 3. Find the row containing "LA code"
    # ==========================================

    header_row = None

    for i in range(len(lookup_raw)):

        row = lookup_raw.iloc[i].astype(str).str.strip().tolist()

        if "LA code" in row:
            header_row = i
            break


    if header_row is None:
        raise ValueError(
            "Could not find the 'LA code' row in the lookup file."
        )

    print(f"Lookup header found on row {header_row}")


    # ==========================================
    # 4. Extract the actual lookup table
    # ==========================================

    lookup = lookup_raw.iloc[header_row + 1:].copy()

    # Based on the ONS file:
    #
    # Column 0 = LA code
    # Column 1 = LA name
    # Column 2 = Region code
    # Column 3 = Region name

    lookup = lookup.iloc[:, [0, 3]]

    lookup.columns = [
        "Lower tier local authorities Code",
        "geography"
    ]


    # ==========================================
    # 5. Clean the codes
    # ==========================================

    df["Lower tier local authorities Code"] = (
        df["Lower tier local authorities Code"]
        .astype(str)
        .str.strip()
    )

    lookup["Lower tier local authorities Code"] = (
        lookup["Lower tier local authorities Code"]
        .astype(str)
        .str.strip()
    )

    lookup["geography"] = (
        lookup["geography"]
        .astype(str)
        .str.strip()
    )


    # ==========================================
    # 6. Remove blank rows
    # ==========================================

    lookup = lookup[
        lookup["Lower tier local authorities Code"].notna()
    ]

    lookup = lookup[
        lookup["Lower tier local authorities Code"] != "nan"
    ]


    # ==========================================
    # 7. Check the lookup BEFORE merging
    # ==========================================

    print("\nSample lookup:")
    print(lookup.head(10).to_string(index=False))


    # ==========================================
    # 8. Merge using LA CODE
    # ==========================================

    df = df.merge(
        lookup,
        on="Lower tier local authorities Code",
        how="left"
    )


    # ==========================================
    # 9. Check unmapped authorities
    # ==========================================

    unmapped = (
        df.loc[
            df["geography"].isna(),
            [
                "Lower tier local authorities Code",
                "Lower tier local authorities"
            ]
        ]
        .drop_duplicates()
        .sort_values("Lower tier local authorities Code")
    )

    if not unmapped.empty:

        print("\nWARNING - UNMAPPED AUTHORITIES:")
        print(unmapped.to_string(index=False))

    else:

        print("\nAll local authorities successfully mapped!")


    # ==========================================
    # 10. Check the actual result
    # ==========================================

    print("\nResult sample:")
    print(
        df[
            [
                "Lower tier local authorities Code",
                "Lower tier local authorities",
                "geography"
            ]
        ]
        .drop_duplicates()
        .head(20)
        .to_string(index=False)
    )


    # ==========================================
    # 11. Save
    # ==========================================

    df.to_csv(
        output_file,
        index=False
    )

    print(f"\nSaved to: {output_file}")
    
#sex_mapping()




def nomis_ashe_workplace_region_mapping():

    # ============================================================
    # FILES
    # ============================================================

    data_file = "data\\nomis_ashe_resident_cities.csv"
    lookup_file = "data\\LA_region_lookup.xlsx"
    output_file = "data\\nomis_ashe_resident_cities.csv"


    # ============================================================
    # 1. LOAD NOMIS ASHE WORKPLACE DATA
    # ============================================================

    df = pd.read_csv(data_file)

    print("Main data columns:")
    print(df.columns.tolist())


    # ============================================================
    # 2. LOAD ONS LA -> REGION LOOKUP
    #
    # We deliberately load without headers because the ONS file
    # has several rows above the actual lookup table.
    # ============================================================

    lookup_raw = pd.read_excel(
        lookup_file,
        header=None
    )


    # ============================================================
    # 3. FIND THE HEADER ROW
    #
    # Look for the row containing "LA code".
    # ============================================================

    header_row = None

    for i in range(len(lookup_raw)):

        row = (
            lookup_raw.iloc[i]
            .astype(str)
            .str.strip()
            .tolist()
        )

        if "LA code" in row:
            header_row = i
            break


    if header_row is None:
        raise ValueError(
            "Could not find the 'LA code' row in the lookup file."
        )

    print(f"\nLookup header found on row {header_row}")


    # ============================================================
    # 4. EXTRACT THE ACTUAL LOOKUP TABLE
    #
    # Based on the ONS lookup:
    #
    # Column 0 = LA code
    # Column 1 = LA name
    # Column 2 = Region code
    # Column 3 = Region name
    # ============================================================

    lookup = lookup_raw.iloc[header_row + 1:].copy()

    lookup = lookup.iloc[:, [0, 2, 3]]

    lookup.columns = [
        "GEOGRAPHY_CODE",
        "GEOGRAPHY_CODE_REGION_CODE",
        "GEOGRAPHY_CODE_REGION"
    ]


    # ============================================================
    # 5. CLEAN THE CODES
    # ============================================================

    df["GEOGRAPHY_CODE"] = (
        df["GEOGRAPHY_CODE"]
        .astype(str)
        .str.strip()
    )

    lookup["GEOGRAPHY_CODE"] = (
        lookup["GEOGRAPHY_CODE"]
        .astype(str)
        .str.strip()
    )

    lookup["GEOGRAPHY_CODE_REGION_CODE"] = (
        lookup["GEOGRAPHY_CODE_REGION_CODE"]
        .astype(str)
        .str.strip()
    )

    lookup["GEOGRAPHY_CODE_REGION"] = (
        lookup["GEOGRAPHY_CODE_REGION"]
        .astype(str)
        .str.strip()
    )


    # ============================================================
    # 6. REMOVE BLANK LOOKUP ROWS
    # ============================================================

    lookup = lookup[
        lookup["GEOGRAPHY_CODE"].notna()
    ]

    lookup = lookup[
        lookup["GEOGRAPHY_CODE"] != "nan"
    ]

    lookup = lookup[
        lookup["GEOGRAPHY_CODE"] != ""
    ]


    # ============================================================
    # 7. REMOVE DUPLICATE LA CODES
    #
    # Each local authority should map to one region.
    # ============================================================

    lookup = lookup.drop_duplicates(
        subset=["GEOGRAPHY_CODE"]
    )


    # ============================================================
    # 8. CHECK THE LOOKUP
    # ============================================================

    print("\nSample lookup:")

    print(
        lookup.head(20).to_string(index=False)
    )


    # ============================================================
    # 9. MERGE REGION INFORMATION INTO NOMIS DATA
    #
    # IMPORTANT:
    # We merge using the Nomis GEOGRAPHY_CODE.
    #
    # Example:
    #
    # E06000005 -> North East -> E12000001
    # ============================================================

    df = df.merge(
        lookup[
            [
                "GEOGRAPHY_CODE",
                "GEOGRAPHY_CODE_REGION",
                "GEOGRAPHY_CODE_REGION_CODE"
            ]
        ],
        on="GEOGRAPHY_CODE",
        how="left",
        validate="many_to_one"
    )


    # ============================================================
    # 10. CHECK FOR UNMAPPED GEOGRAPHIES
    # ============================================================

    unmapped = (
        df.loc[
            df["GEOGRAPHY_CODE_REGION"].isna(),
            [
                "GEOGRAPHY_CODE",
                "GEOGRAPHY_NAME"
            ]
        ]
        .drop_duplicates()
        .sort_values("GEOGRAPHY_CODE")
    )


    if not unmapped.empty:

        print("\nWARNING - UNMAPPED GEOGRAPHIES:")

        print(
            unmapped.to_string(index=False)
        )

    else:

        print(
            "\nAll Nomis workplace geographies successfully mapped!"
        )


    # ============================================================
    # 11. SHOW THE ACTUAL RESULT
    # ============================================================

    print("\nResult sample:")

    print(
        df[
            [
                "GEOGRAPHY_CODE",
                "GEOGRAPHY_NAME",
                "GEOGRAPHY_CODE_REGION",
                "GEOGRAPHY_CODE_REGION_CODE"
            ]
        ]
        .drop_duplicates()
        .head(30)
        .to_string(index=False)
    )


    # ============================================================
    # 12. CHECK HOW MANY UNIQUE REGIONS WE HAVE
    # ============================================================

    print("\nRegions found:")

    print(
        df[
            [
                "GEOGRAPHY_CODE_REGION_CODE",
                "GEOGRAPHY_CODE_REGION"
            ]
        ]
        .drop_duplicates()
        .sort_values("GEOGRAPHY_CODE_REGION_CODE")
        .to_string(index=False)
    )


    # ============================================================
    # 13. SAVE
    # ============================================================

    df.to_csv(
        output_file,
        index=False
    )

    print(
        f"\nSaved to: {output_file}"
    )


# ================================================================
# RUN
# ================================================================

nomis_ashe_workplace_region_mapping()