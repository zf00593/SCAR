import os
import json
import time
from itertools import product
from datetime import datetime

import pandas as pd
import requests


# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_URL = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
OUTPUT_DIR = "data/statxplore"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# =============================================================================
# STAT-XPLORE CLIENT
# =============================================================================

class StatXploreClient:
    """
    Client for the DWP Stat-Xplore REST API.
    """

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Accept-Language": "en",
        })
        if api_key:
            self.session.headers.update({"APIKey": api_key})

    def get(self, path):
        url = f"{BASE_URL}{path}"
        response = self.session.get(url)
        print(f"GET {url}")
        print(f"Status: {response.status_code}")
        response.raise_for_status()
        return response.json()

    def get_schema(self, schema_id):
        url = f"{BASE_URL}/schema/{schema_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def query_table(self, database, dimensions, measures):
        payload = {
            "database": database,
            "measures": measures,
            "dimensions": dimensions,
        }
        
        print("\n" + "=" * 80)
        print("STAT-XPLORE TABLE QUERY")
        print("=" * 80)
        print(json.dumps(payload, indent=2))
        
        url = f"{BASE_URL}/table"
        response = self.session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"\nHTTP status: {response.status_code}")
        response.raise_for_status()
        return response.json()


# =============================================================================
# SCHEMA HELPERS
# =============================================================================

def save_json(data, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {path}")


def get_field_items(field):
    items = field.get("items", [])
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append({
                "id": item.get("id"),
                "label": item.get("label", item.get("name", "")),
                "uri": item.get("uri", item.get("id")),
            })
        else:
            result.append({
                "id": item,
                "label": str(item),
                "uri": item,
            })
    return result


def flatten_cube(values, dimensions, depth=0, prefix=None):
    if prefix is None:
        prefix = []
    if not isinstance(values, list):
        return [(prefix, values)]
    rows = []
    for index, child in enumerate(values):
        rows.extend(flatten_cube(child, dimensions, depth + 1, prefix + [index]))
    return rows


def parse_table_response(response):
    """
    Convert a Stat-Xplore /table response into a pandas DataFrame.
    """
    fields = response.get("fields", [])
    cubes = response.get("cubes", {})
    
    if not fields:
        raise RuntimeError("Stat-Xplore returned no dimension fields.")
    if not cubes:
        raise RuntimeError("Stat-Xplore returned no cubes.")
    
    # Build dimension metadata
    dimension_items = []
    for field in fields:
        label = field.get("label", field.get("id", "Unknown"))
        uri = field.get("uri", field.get("id"))
        items = get_field_items(field)
        dimension_items.append({
            "label": label,
            "uri": uri,
            "items": items
        })
    
    # Build all possible coordinate combinations
    item_lists = [dimension["items"] for dimension in dimension_items]
    combinations = list(product(*[range(len(items)) for items in item_lists]))
    
    # Parse every cube
    data = []
    for measure_uri, cube in cubes.items():
        if not isinstance(cube, dict):
            continue
        values = cube.get("values")
        if values is None:
            continue
        
        flattened = flatten_cube(values, dimension_items)
        value_map = {tuple(indexes): value for indexes, value in flattened}
        
        for coordinate in combinations:
            row = {}
            for dimension_number, item_index in enumerate(coordinate):
                dimension = dimension_items[dimension_number]
                items = dimension["items"]
                if item_index >= len(items):
                    continue
                item = items[item_index]
                row[dimension["label"]] = item["label"]
                row[f"{dimension['label']}__URI"] = item["uri"]
            
            row[measure_uri] = value_map.get(coordinate)
            data.append(row)
    
    df = pd.DataFrame(data)
    
    # Clean duplicate rows generated by multiple cubes
    if not df.empty:
        dimension_labels = [dimension["label"] for dimension in dimension_items]
        uri_columns = [f"{label}__URI" for label in dimension_labels]
        measure_columns = [col for col in df.columns if col not in dimension_labels and col not in uri_columns]
        
        if measure_columns:
            group_columns = dimension_labels + uri_columns
            df = df.groupby(group_columns, dropna=False, as_index=False)[measure_columns].first()
    
    return df


# =============================================================================
# RECURSIVE FIELD DISCOVERY
# =============================================================================

def recursively_find_children(client, schema_id, seen=None):
    if seen is None:
        seen = set()
    if schema_id in seen:
        return []
    seen.add(schema_id)
    
    try:
        schema = client.get_schema(schema_id)
    except Exception as e:
        print(f"Could not retrieve {schema_id}: {e}")
        return []
    
    results = []
    for child in schema.get("children", []):
        child_type = child.get("type")
        child_id = child.get("id")
        if not child_id:
            continue
        if child_type in ("FIELD", "MEASURE", "COUNT"):
            results.append(child)
        elif child_type == "GROUP":
            results.extend(recursively_find_children(client, child_id, seen))
    
    return results


def find_database_fields(client, database_id):
    """Recursively discover all fields/measures below a database."""
    objects = recursively_find_children(client, database_id)
    
    fields = [obj for obj in objects if obj.get("type") == "FIELD"]
    measures = [obj for obj in objects if obj.get("type") == "MEASURE"]
    counts = [obj for obj in objects if obj.get("type") == "COUNT"]
    
    return {"fields": fields, "measures": measures, "counts": counts}


def find_by_text(items, text):
    text = text.lower()
    matches = []
    for item in items:
        item_id = str(item.get("id", ""))
        label = str(item.get("label", ""))
        if text in item_id.lower() or text in label.lower():
            matches.append(item)
    return matches


def get_field_uri(discovered, search_term):
    """Find field URI by searching labels/IDs."""
    all_objects = discovered["fields"] + discovered["measures"] + discovered["counts"]
    matches = find_by_text(all_objects, search_term)
    
    if matches:
        # Prefer fields over measures
        for m in matches:
            if m.get("type") == "FIELD":
                return m.get("id")
        return matches[0].get("id")
    
    # Try alternate search terms
    alternates = {
        "ethnic": "HARMONISED_ETHNIC",
        "geography": "GVTREGN_LON",
        "region": "GVTREGN_LON",
        "sex": "SEX",
        "gender": "SEX",
        "age": "AGEBAND"
    }
    
    for alt_term, alt_id in alternates.items():
        if alt_term in search_term.lower():
            # Check if the alt_id exists
            for obj in all_objects:
                if alt_id in obj.get("id", ""):
                    return obj.get("id")
    
    return None


# =============================================================================
# DATA EXTRACTION FUNCTIONS
# =============================================================================

def fetch_dataset(client, database_id, dimension_ids, measure_ids, label_prefix=""):
    """
    Generic function to fetch any dataset.
    """
    print(f"\n{'='*80}")
    print(f"FETCHING {database_id}")
    print(f"{'='*80}")
    
    # Discover fields to verify they exist
    discovered = find_database_fields(client, database_id)
    
    # Build dimensions list
    dimensions = []
    for dim_id in dimension_ids:
        if dim_id:
            dimensions.append([dim_id])
    
    if not dimensions:
        print(f"⚠ No valid dimensions found for {database_id}")
        return pd.DataFrame()
    
    # Build measures list
    measures = [m.get("id") for m in discovered["measures"] if m.get("id")]
    if not measures and discovered["counts"]:
        # Use count if no measures
        measures = [discovered["counts"][0].get("id")]
    
    if not measures:
        print(f"⚠ No measures found for {database_id}")
        return pd.DataFrame()
    
    # Use only first measure to avoid complexity
    measures = measures[:1]
    
    try:
        response = client.query_table(
            database=database_id,
            dimensions=dimensions,
            measures=measures
        )
        
        df = parse_table_response(response)
        
        if not df.empty:
            filename = f"{database_id.replace(':', '_')}_{label_prefix}.csv"
            path = os.path.join(OUTPUT_DIR, filename)
            df.to_csv(path, index=False)
            print(f"✓ Saved {len(df)} rows to {path}")
            
            # Also save as clean name
            clean_name = database_id.replace('str:database:', '')
            clean_path = os.path.join(OUTPUT_DIR, f"{clean_name}_{label_prefix}.csv")
            df.to_csv(clean_path, index=False)
            print(f"✓ Also saved as {clean_path}")
            
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        print(f"✗ Error fetching {database_id}: {e}")
        return pd.DataFrame()


# =============================================================================
# SPECIFIC DATASET QUERIES WITH ETHNICITY
# =============================================================================

def fetch_hbai_with_ethnicity(client):
    """
    Fetch HBAI_ADMIN data with ethnicity, region, sex, age.
    """
    print("\n" + "="*80)
    print("FETCHING HBAI_ADMIN WITH ETHNICITY")
    print("="*80)
    
    database_id = "str:database:HBAI_ADMIN"
    
    # Discover fields
    discovered = find_database_fields(client, database_id)
    
    # Find specific field URIs
    region_uri = get_field_uri(discovered, "region")
    sex_uri = get_field_uri(discovered, "sex")
    age_uri = get_field_uri(discovered, "age")
    ethnicity_uri = get_field_uri(discovered, "ethnic")
    year_uri = get_field_uri(discovered, "year")
    
    print(f"\nFound field URIs:")
    print(f"  Region: {region_uri}")
    print(f"  Sex: {sex_uri}")
    print(f"  Age: {age_uri}")
    print(f"  Ethnicity: {ethnicity_uri}")
    print(f"  Year: {year_uri}")
    
    # Build dimensions with year for multi-year averaging
    dimensions = []
    if year_uri:
        dimensions.append([year_uri])
    if region_uri:
        dimensions.append([region_uri])
    if sex_uri:
        dimensions.append([sex_uri])
    if age_uri:
        dimensions.append([age_uri])
    if ethnicity_uri:
        dimensions.append([ethnicity_uri])
    
    # Get measures
    measures = []
    for m in discovered["measures"]:
        if "income" in m.get("label", "").lower() or "housing" in m.get("label", "").lower():
            measures.append(m.get("id"))
    
    if not measures:
        measures = [discovered["measures"][0].get("id")] if discovered["measures"] else []
    
    if not measures:
        measures = [discovered["counts"][0].get("id")] if discovered["counts"] else []
    
    print(f"\nMeasures to fetch: {measures}")
    
    if not dimensions:
        print("⚠ No dimensions found for HBAI_ADMIN")
        return pd.DataFrame()
    
    try:
        response = client.query_table(
            database=database_id,
            dimensions=dimensions,
            measures=measures[:1]  # Use first measure
        )
        
        df = parse_table_response(response)
        
        if not df.empty:
            path = os.path.join(OUTPUT_DIR, "HBAI_ADMIN_ethnicity.csv")
            df.to_csv(path, index=False)
            print(f"✓ Saved {len(df)} rows to {path}")
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        print(f"✗ Error fetching HBAI_ADMIN: {e}")
        return pd.DataFrame()


def fetch_all_datasets(client):
    """
    Fetch all relevant datasets with ethnicity, region, sex, age.
    """
    results = {}
    
    # Dataset configurations
    datasets = [
        {
            "id": "str:database:HBAI_ADMIN",
            "label": "HBAI_ADMIN",
            "search_terms": ["ethnic", "region", "sex", "age", "year"],
            "measures_keywords": ["income", "housing"]
        },
        {
            "id": "str:database:HBAI_SURVEY",
            "label": "HBAI_SURVEY",
            "search_terms": ["ethnic", "region", "sex", "age", "year"],
            "measures_keywords": ["income", "housing"]
        },
        {
            "id": "str:database:FRSPP",
            "label": "FRS_INDIVIDUAL",
            "search_terms": ["ethnic", "geograph", "sex", "age", "year"],
            "measures_keywords": ["income"]
        },
        {
            "id": "str:database:FRSAD",
            "label": "FRS_ADULT",
            "search_terms": ["ethnic", "geograph", "sex", "age", "year"],
            "measures_keywords": ["income"]
        },
        {
            "id": "str:database:FRSHH",
            "label": "FRS_HOUSEHOLD",
            "search_terms": ["ethnic", "geograph", "age", "year"],
            "measures_keywords": ["income"]
        },
        {
            "id": "str:database:hb_new",
            "label": "HOUSING_BENEFIT",
            "search_terms": ["geograph", "gender", "age"],
            "measures_keywords": ["award", "amount"]
        },
        {
            "id": "str:database:UC_Households",
            "label": "UC_HOUSEHOLDS",
            "search_terms": ["geograph", "family"],
            "measures_keywords": ["payment"]
        },
        {
            "id": "str:database:UC_Monthly",
            "label": "UC_PEOPLE",
            "search_terms": ["geograph", "gender", "age"],
            "measures_keywords": []
        },
    ]
    
    for config in datasets:
        print("\n" + "="*80)
        print(f"PROCESSING: {config['label']}")
        print("="*80)
        
        # Discover fields
        discovered = find_database_fields(client, config["id"])
        
        # Find dimension URIs
        dimension_uris = []
        for term in config["search_terms"]:
            uri = get_field_uri(discovered, term)
            if uri:
                dimension_uris.append(uri)
                print(f"  Found {term}: {uri}")
        
        # Find measure URIs
        measure_uris = []
        for m in discovered["measures"]:
            label = m.get("label", "").lower()
            for keyword in config["measures_keywords"]:
                if keyword in label:
                    measure_uris.append(m.get("id"))
                    break
        
        if not measure_uris and discovered["measures"]:
            measure_uris = [discovered["measures"][0].get("id")]
        
        if not measure_uris and discovered["counts"]:
            measure_uris = [discovered["counts"][0].get("id")]
        
        print(f"  Measures: {measure_uris}")
        
        if not dimension_uris:
            print(f"⚠ No dimensions found for {config['label']}")
            results[config['label']] = pd.DataFrame()
            continue
        
        if not measure_uris:
            print(f"⚠ No measures found for {config['label']}")
            results[config['label']] = pd.DataFrame()
            continue
        
        # Build dimensions
        dimensions = [[uri] for uri in dimension_uris]
        
        try:
            response = client.query_table(
                database=config["id"],
                dimensions=dimensions,
                measures=measure_uris[:1]  # Use first measure
            )
            
            df = parse_table_response(response)
            
            if not df.empty:
                clean_name = config["label"]
                path = os.path.join(OUTPUT_DIR, f"{clean_name}_ethnicity.csv")
                df.to_csv(path, index=False)
                print(f"✓ Saved {len(df)} rows to {path}")
                results[config['label']] = df
            else:
                results[config['label']] = pd.DataFrame()
                
        except Exception as e:
            print(f"✗ Error fetching {config['label']}: {e}")
            results[config['label']] = pd.DataFrame()
        
        # Be respectful to API
        time.sleep(1)
    
    return results


# =============================================================================
# COMBINE DATASETS
# =============================================================================

def combine_datasets(results):
    """
    Combine all extracted datasets into a single file with source tracking.
    """
    print("\n" + "="*80)
    print("COMBINING DATASETS")
    print("="*80)
    
    combined = []
    
    for name, df in results.items():
        if not df.empty:
            df_copy = df.copy()
            df_copy['SOURCE_DATASET'] = name
            combined.append(df_copy)
            print(f"  Adding {name}: {len(df)} rows")
    
    if combined:
        combined_df = pd.concat(combined, ignore_index=True)
        path = os.path.join(OUTPUT_DIR, "COMBINED_ALL_DATASETS.csv")
        combined_df.to_csv(path, index=False)
        print(f"\n✓ Combined dataset saved: {len(combined_df)} rows to {path}")
        return combined_df
    
    print("⚠ No data to combine")
    return pd.DataFrame()


# =============================================================================
# CREATE MANIFEST
# =============================================================================

def create_manifest(results):
    """
    Create a manifest file describing all extracted datasets.
    """
    manifest = []
    
    for name, df in results.items():
        if not df.empty:
            manifest.append({
                'dataset': name,
                'rows': len(df),
                'columns': len(df.columns),
                'column_names': ', '.join(df.columns[:15]),
                'file': f"{name}_ethnicity.csv",
                'extracted_at': datetime.now().isoformat()
            })
    
    if manifest:
        manifest_df = pd.DataFrame(manifest)
        path = os.path.join(OUTPUT_DIR, "_manifest_ethnicity.csv")
        manifest_df.to_csv(path, index=False)
        print(f"✓ Manifest saved to {path}")
        return manifest_df
    
    return pd.DataFrame()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("="*80)
    print("STAT-XPLORE ETHNICITY DATA EXTRACTION")
    print("="*80)
    
    # Get API key
    api_key = os.environ.get("STATXPLORE_KEY")
    if not api_key:
        raise RuntimeError("STATXPLORE_KEY environment variable is not set.")
    
    client = StatXploreClient(api_key=api_key)
    
    # Test authentication
    print("\nTesting authentication...")
    try:
        root_schema = client.get_schema("str:folder:ffrs")
        print("✓ Authentication successful.")
        save_json(root_schema, "root_schema.json")
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return
    
    # Fetch all datasets
    results = fetch_all_datasets(client)
    
    # Combine datasets
    combined = combine_datasets(results)
    
    # Create manifest
    manifest = create_manifest(results)
    
    # Print summary
    print("\n" + "="*80)
    print("EXTRACTION COMPLETE")
    print("="*80)
    
    print("\nExtracted datasets:")
    for name, df in results.items():
        status = f"{len(df):,} rows" if not df.empty else "⚠ Empty"
        print(f"  {name}: {status}")
    
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("\nFiles created:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith('.csv'):
            size = os.path.getsize(os.path.join(OUTPUT_DIR, f))
            size_kb = size / 1024
            print(f"  - {f} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
