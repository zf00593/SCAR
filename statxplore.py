import pandas as pd
import requests
import json
import time
from datetime import datetime
import os

# Create data/statxplore directory
OUTPUT_DIR = 'data/statxplore'
os.makedirs(OUTPUT_DIR, exist_ok=True)

class StatXploreClient:
    """
    Client for DWP Stat-Xplore API
    """
    def __init__(self, api_key=None):
        self.base_url = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({'Authorization': f'Bearer {api_key}'})
    
    def get_schema(self, database_id):
        """Get schema for a database"""
        url = f"{self.base_url}/schema/{database_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def query_table(self, database_id, dimensions, measures, filters=None):
        """
        Query a table from Stat-Xplore
        
        Parameters:
        - database_id: e.g., 'HBAI_ADMIN'
        - dimensions: list of dimension IDs (fields)
        - measures: list of measure IDs
        - filters: dict of dimension filters
        """
        url = f"{self.base_url}/table/{database_id}"
        
        payload = {
            "dimensions": dimensions,
            "measures": measures,
            "filters": filters or {}
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def fetch_yearly_data(self, database_id, dimensions, measures, years, filters=None):
        """
        Fetch data for multiple years and combine
        """
        all_data = []
        
        for year in years:
            year_filters = filters.copy() if filters else {}
            year_filters['YEAR'] = year
            
            try:
                data = self.query_table(database_id, dimensions, measures, year_filters)
                df = self._parse_response(data)
                df['YEAR'] = year
                all_data.append(df)
                time.sleep(0.5)  # Be respectful to API
            except Exception as e:
                print(f"Error fetching year {year}: {e}")
                continue
        
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()
    
    def _parse_response(self, response):
        """
        Parse Stat-Xplore table response into DataFrame
        """
        rows = []
        
        # Assuming response has 'rows' structure
        for row in response.get('rows', []):
            row_data = {}
            
            # Extract dimension values
            for dim in row.get('dimensions', []):
                row_data[dim['id']] = dim['value']
            
            # Extract measure values
            for measure in row.get('measures', []):
                row_data[measure['id']] = measure['value']
            
            rows.append(row_data)
        
        return pd.DataFrame(rows)


def fetch_hbai_with_ethnicity(client, years):
    """
    Fetch HBAI data with ethnicity, region, sex, age
    Note: Requires three-year averaging
    """
    print("Fetching HBAI_ADMIN data...")
    
    dimensions = [
        'GVTREGN_LON',      # Region
        'SEX',              # Sex
        'AGEBAND_CHLOW',    # Age band
        'ETHNICITY'         # Ethnicity (check exact field name)
    ]
    
    measures = [
        'S_OE_BHC',         # Net income before housing costs
        'S_OE_AHC',         # Net income after housing costs
        'S_OE_HC'           # Housing costs
    ]
    
    # Fetch data for each year
    df = client.fetch_yearly_data(
        database_id='HBAI_ADMIN',
        dimensions=dimensions,
        measures=measures,
        years=years
    )
    
    if not df.empty:
        # Calculate three-year averages
        df_avg = df.groupby(
            ['GVTREGN_LON', 'SEX', 'AGEBAND_CHLOW', 'ETHNICITY']
        )[measures].mean().reset_index()
        
        df_avg['AVERAGE_PERIOD'] = f"{years[0]}-{years[-1]}"
        df_avg['AVERAGE_TYPE'] = '3-year average'
        
        # Save to file
        filename = os.path.join(OUTPUT_DIR, 'HBAI_ADMIN_ethnicity_3yr_avg.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for HBAI_ADMIN")
    return pd.DataFrame()


def fetch_frs_with_ethnicity(client, years):
    """
    Fetch FRS data with ethnicity
    """
    print("Fetching FRS Individual data...")
    
    # FRS Individual dataset has ethnicity
    dimensions = [
        'GVTREGN_LON',      # Region
        'SEX',              # Sex
        'AGEBAND',          # Age band
        'HARMONISED_ETHNIC' # Harmonised Ethnic Group
    ]
    
    measures = [
        'PIPERSONAL_INC',   # Personal income
        'PIHOUSEHOLD_INC'   # Household income
    ]
    
    df = client.fetch_yearly_data(
        database_id='FRSPP',  # Individual dataset
        dimensions=dimensions,
        measures=measures,
        years=years
    )
    
    if not df.empty:
        # Calculate three-year averages
        df_avg = df.groupby(
            ['GVTREGN_LON', 'SEX', 'AGEBAND', 'HARMONISED_ETHNIC']
        )[measures].mean().reset_index()
        
        df_avg['AVERAGE_PERIOD'] = f"{years[0]}-{years[-1]}"
        df_avg['AVERAGE_TYPE'] = '3-year average'
        
        # Save to file
        filename = os.path.join(OUTPUT_DIR, 'FRS_INDIVIDUAL_ethnicity_3yr_avg.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for FRS Individual")
    return pd.DataFrame()


def fetch_frs_adult_with_ethnicity(client, years):
    """
    Fetch FRS Adult dataset with ethnicity
    """
    print("Fetching FRS Adult data...")
    
    dimensions = [
        'GVTREGN_LON',      # Region
        'SEX',              # Sex
        'AGEBAND',          # Age band
        'HARMONISED_ETHNIC' # Harmonised Ethnic Group
    ]
    
    measures = [
        'ADULT_INCOME_EMPLOYMENT',
        'ADULT_INCOME_ALL_SOURCES'
    ]
    
    df = client.fetch_yearly_data(
        database_id='FRSAD',  # Adult dataset
        dimensions=dimensions,
        measures=measures,
        years=years
    )
    
    if not df.empty:
        df_avg = df.groupby(
            ['GVTREGN_LON', 'SEX', 'AGEBAND', 'HARMONISED_ETHNIC']
        )[measures].mean().reset_index()
        
        df_avg['AVERAGE_PERIOD'] = f"{years[0]}-{years[-1]}"
        df_avg['AVERAGE_TYPE'] = '3-year average'
        
        filename = os.path.join(OUTPUT_DIR, 'FRS_ADULT_ethnicity_3yr_avg.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for FRS Adult")
    return pd.DataFrame()


def fetch_frs_household_with_ethnicity(client, years):
    """
    Fetch FRS Household dataset with ethnicity
    """
    print("Fetching FRS Household data...")
    
    dimensions = [
        'GVTREGN_LON',      # Region
        'AGEBAND',          # Age band of head
        'ETHNICITY'         # Ethnicity of head
    ]
    
    measures = [
        'HOUSEHOLD_INCOME_ALL_SOURCES',
        'HOUSEHOLD_INCOME_EMPLOYMENT'
    ]
    
    df = client.fetch_yearly_data(
        database_id='FRSHH',  # Household dataset
        dimensions=dimensions,
        measures=measures,
        years=years
    )
    
    if not df.empty:
        df_avg = df.groupby(
            ['GVTREGN_LON', 'AGEBAND', 'ETHNICITY']
        )[measures].mean().reset_index()
        
        df_avg['AVERAGE_PERIOD'] = f"{years[0]}-{years[-1]}"
        df_avg['AVERAGE_TYPE'] = '3-year average'
        
        filename = os.path.join(OUTPUT_DIR, 'FRS_HOUSEHOLD_ethnicity_3yr_avg.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for FRS Household")
    return pd.DataFrame()


def fetch_pensioner_income_with_ethnicity(client, years):
    """
    Fetch Pensioner Income data with ethnicity
    """
    print("Fetching Pensioner Income data...")
    
    dimensions = [
        'gvtregn',      # Region
        'sexhd',        # Sex
        'agehd',        # Age
        'eth'           # Ethnicity
    ]
    
    measures = [
        'pinincbu',     # Net income before housing costs
        'pinahcbu'      # Net income after housing costs
    ]
    
    df = client.fetch_yearly_data(
        database_id='PI_ADMIN',
        dimensions=dimensions,
        measures=measures,
        years=years
    )
    
    if not df.empty:
        df_avg = df.groupby(
            ['gvtregn', 'sexhd', 'agehd', 'eth']
        )[measures].mean().reset_index()
        
        df_avg['AVERAGE_PERIOD'] = f"{years[0]}-{years[-1]}"
        df_avg['AVERAGE_TYPE'] = '3-year average'
        
        filename = os.path.join(OUTPUT_DIR, 'PENSIONER_INCOME_ethnicity_3yr_avg.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for Pensioner Income")
    return pd.DataFrame()


def fetch_housing_benefit(client, months):
    """
    Fetch Housing Benefit data
    """
    print("Fetching Housing Benefit data...")
    
    dimensions = [
        'GEOGRAPHY',
        'SINGLE_GEN',       # Gender (single claimants)
        'FAMILY_PUB',       # Family type
        'AGE_BAND'
    ]
    
    measures = ['LAHBAMT']  # Weekly award amount
    
    # HB is monthly
    all_data = []
    for month in months:
        try:
            # For HB, we need to use the date field
            df = client.fetch_yearly_data(
                database_id='hb_new',
                dimensions=dimensions + ['NEW_DATE_NAME'],
                measures=measures,
                years=[month]  # HB uses months
            )
            if not df.empty:
                all_data.append(df)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error fetching month {month}: {e}")
    
    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        # Aggregate to averages
        df_avg = df.groupby(
            ['GEOGRAPHY', 'SINGLE_GEN', 'FAMILY_PUB', 'AGE_BAND']
        )['LAHBAMT'].mean().reset_index()
        
        df_avg['PERIOD'] = f"{months[0]}-{months[-1]}"
        
        filename = os.path.join(OUTPUT_DIR, 'HOUSING_BENEFIT_average.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for Housing Benefit")
    return pd.DataFrame()


def fetch_uc_households(client, months):
    """
    Fetch Universal Credit Household data
    """
    print("Fetching Universal Credit Household data...")
    
    dimensions = [
        'GEOGRAPHY',
        'hnfamily_type'
    ]
    
    measures = ['HNTOTAL_PAYMENT_AMOUNT']
    
    all_data = []
    for month in months:
        try:
            df = client.fetch_yearly_data(
                database_id='UC_Households',
                dimensions=dimensions + ['DATE_NAME'],
                measures=measures,
                years=[month]
            )
            if not df.empty:
                all_data.append(df)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error fetching month {month}: {e}")
    
    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        df_avg = df.groupby(
            ['GEOGRAPHY', 'hnfamily_type']
        )['HNTOTAL_PAYMENT_AMOUNT'].mean().reset_index()
        
        df_avg['PERIOD'] = f"{months[0]}-{months[-1]}"
        
        filename = os.path.join(OUTPUT_DIR, 'UNIVERSAL_CREDIT_HOUSEHOLDS_average.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for Universal Credit")
    return pd.DataFrame()


def fetch_uc_people(client, months):
    """
    Fetch Universal Credit People data
    """
    print("Fetching Universal Credit People data...")
    
    dimensions = [
        'GEOGRAPHY',
        'GENDER_CODE',
        'AGE_CODE',
        'EMPLOYMENT_CODE'
    ]
    
    df = client.fetch_yearly_data(
        database_id='UC_Monthly',
        dimensions=dimensions + ['DATE_NAME'],
        measures=[],  # Count is default
        years=months
    )
    
    if not df.empty:
        # Get count from the data
        if 'COUNT' in df.columns:
            df_avg = df.groupby(
                ['GEOGRAPHY', 'GENDER_CODE', 'AGE_CODE', 'EMPLOYMENT_CODE']
            )['COUNT'].mean().reset_index()
        else:
            # Count is implicit
            df_avg = df.groupby(
                ['GEOGRAPHY', 'GENDER_CODE', 'AGE_CODE', 'EMPLOYMENT_CODE']
            ).size().reset_index(name='AVG_COUNT')
        
        df_avg['PERIOD'] = f"{months[0]}-{months[-1]}"
        
        filename = os.path.join(OUTPUT_DIR, 'UNIVERSAL_CREDIT_PEOPLE_average.csv')
        df_avg.to_csv(filename, index=False)
        print(f"  ✓ Saved {len(df_avg)} rows to {filename}")
        
        return df_avg
    
    print("  ⚠ No data returned for Universal Credit People")
    return pd.DataFrame()


def verify_field_names(client):
    """
    Helper function to verify actual field names in schemas
    """
    print("\n" + "=" * 60)
    print("VERIFYING FIELD NAMES")
    print("=" * 60)
    
    databases = ['HBAI_ADMIN', 'FRSPP', 'FRSAD', 'FRSHH', 'PI_ADMIN', 'hb_new', 'UC_Households', 'UC_Monthly']
    
    field_info = {}
    
    for db in databases:
        try:
            schema = client.get_schema(db)
            field_info[db] = {
                'fields': [],
                'measures': [],
                'groups': []
            }
            
            for child in schema.get('children', []):
                if child['type'] == 'FIELD':
                    field_info[db]['fields'].append({
                        'id': child['id'],
                        'label': child['label']
                    })
                elif child['type'] == 'MEASURE':
                    field_info[db]['measures'].append({
                        'id': child['id'],
                        'label': child['label'],
                        'functions': child.get('functions', [])
                    })
                elif child['type'] == 'GROUP':
                    field_info[db]['groups'].append({
                        'id': child['id'],
                        'label': child['label']
                    })
            
            print(f"\n{db}:")
            print(f"  Fields: {len(field_info[db]['fields'])}")
            print(f"  Measures: {len(field_info[db]['measures'])}")
            print(f"  Groups: {len(field_info[db]['groups'])}")
            
            # Show ethnicity-related fields
            ethnic_fields = [f for f in field_info[db]['fields'] 
                           if 'ethn' in f['id'].lower() or 'ethn' in f['label'].lower()]
            if ethnic_fields:
                print(f"  Ethnicity fields: {ethnic_fields}")
            
            time.sleep(0.3)
            
        except Exception as e:
            print(f"Error fetching schema for {db}: {e}")
    
    # Save field info
    with open(os.path.join(OUTPUT_DIR, '_schema_fields.json'), 'w') as f:
        json.dump(field_info, f, indent=2, default=str)
    print(f"\n✓ Schema information saved to {OUTPUT_DIR}/_schema_fields.json")
    
    return field_info


def create_combined_dataset(datasets):
    """
    Create a combined dataset from all extracted data
    """
    print("\n" + "=" * 60)
    print("CREATING COMBINED DATASET")
    print("=" * 60)
    
    combined_df = pd.DataFrame()
    
    for name, df in datasets.items():
        if not df.empty:
            # Add source column
            df_copy = df.copy()
            df_copy['SOURCE'] = name
            
            # Try to standardize column names for merging
            # This is complex due to different schemas
            # For now, just collect everything
            
            if combined_df.empty:
                combined_df = df_copy
            else:
                # Find common columns for merging
                common_cols = set(combined_df.columns).intersection(set(df_copy.columns))
                if common_cols:
                    # Merge on common columns
                    combined_df = pd.merge(
                        combined_df, df_copy, 
                        on=list(common_cols), 
                        how='outer',
                        suffixes=('', f'_{name}')
                    )
                else:
                    # Just concatenate
                    combined_df = pd.concat([combined_df, df_copy], ignore_index=True)
    
    if not combined_df.empty:
        filename = os.path.join(OUTPUT_DIR, 'COMBINED_DATASET.csv')
        combined_df.to_csv(filename, index=False)
        print(f"✓ Combined dataset saved: {len(combined_df)} rows")
        return combined_df
    
    print("⚠ No data to combine")
    return pd.DataFrame()


def main():
    # Initialize client
    api_key = os.environ.get('STATXPLORE_KEY')
    if not api_key:
        print("⚠ WARNING: STATXPLORE_KEY environment variable not set")
        print("  Please set it with: export STATXPLORE_KEY='your_key'")
        print("  Continuing with unauthenticated access (may have limitations)")
    
    client = StatXploreClient(api_key)
    
    # First, verify field names
    field_info = verify_field_names(client)
    
    # Define years for three-year averages
    years = ['2021/22', '2022/23', '2023/24']  # Adjust as needed
    months = ['2023-01', '2023-02', '2023-03']  # For monthly data
    
    print("\n" + "=" * 60)
    print("STARTING DATA EXTRACTION")
    print("=" * 60)
    print(f"Years (3-year average): {years}")
    print(f"Months: {months}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 60)
    
    # Fetch all datasets
    datasets = {}
    
    # 1. HBAI with ethnicity
    datasets['HBAI_ADMIN'] = fetch_hbai_with_ethnicity(client, years)
    
    # 2. FRS datasets with ethnicity
    datasets['FRS_INDIVIDUAL'] = fetch_frs_with_ethnicity(client, years)
    datasets['FRS_ADULT'] = fetch_frs_adult_with_ethnicity(client, years)
    datasets['FRS_HOUSEHOLD'] = fetch_frs_household_with_ethnicity(client, years)
    
    # 3. Pensioner Income with ethnicity
    datasets['PENSIONER_INCOME'] = fetch_pensioner_income_with_ethnicity(client, years)
    
    # 4. Housing Benefit
    datasets['HOUSING_BENEFIT'] = fetch_housing_benefit(client, months)
    
    # 5. Universal Credit
    datasets['UNIVERSAL_CREDIT_HOUSEHOLDS'] = fetch_uc_households(client, months)
    datasets['UNIVERSAL_CREDIT_PEOPLE'] = fetch_uc_people(client, months)
    
    # Create combined dataset
    combined = create_combined_dataset(datasets)
    datasets['COMBINED'] = combined
    
    # Create manifest
    print("\n" + "=" * 60)
    print("CREATING MANIFEST")
    print("=" * 60)
    
    manifest = []
    for name, df in datasets.items():
        if not df.empty:
            manifest.append({
                'dataset': name,
                'rows': len(df),
                'columns': len(df.columns),
                'column_names': ', '.join(df.columns[:10]) + ('...' if len(df.columns) > 10 else ''),
                'file': f"{name.replace('_', '_')}.csv",
                'saved_at': datetime.now().isoformat()
            })
    
    if manifest:
        manifest_df = pd.DataFrame(manifest)
        manifest_filename = os.path.join(OUTPUT_DIR, '_manifest.csv')
        manifest_df.to_csv(manifest_filename, index=False)
        print(f"✓ Manifest saved to {manifest_filename}")
        print(f"\nTotal datasets extracted: {len(manifest)}")
        
        # Print summary
        print("\n" + "-" * 60)
        print("EXTRACTION SUMMARY")
        print("-" * 60)
        for entry in manifest:
            print(f"  {entry['dataset']}: {entry['rows']:,} rows")
    else:
        print("⚠ No data was extracted")
    
    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Data saved to: {OUTPUT_DIR}/")
    print("Files:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith('.csv'):
            print(f"  - {f}")


if __name__ == "__main__":
    main()
