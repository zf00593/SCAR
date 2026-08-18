import os
import json
import time
from itertools import product

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
            self.session.headers.update({
                "APIKey": api_key,
            })

    # -------------------------------------------------------------------------
    # GET
    # -------------------------------------------------------------------------

    def get(self, path):
        url = f"{BASE_URL}{path}"

        response = self.session.get(url)

        print(f"GET {url}")
        print(f"Status: {response.status_code}")

        response.raise_for_status()

        return response.json()

    # -------------------------------------------------------------------------
    # SCHEMA
    # -------------------------------------------------------------------------

    def get_schema(self, schema_id):
        """
        Retrieve a schema object.

        schema_id can be:

            str:database:FRSPP
            str:group:FRSPP:X_Ethnicity
            str:field:FRSPP:...
        """

        url = f"{BASE_URL}/schema/{schema_id}"

        response = self.session.get(url)

        response.raise_for_status()

        return response.json()

    # -------------------------------------------------------------------------
    # TABLE QUERY
    # -------------------------------------------------------------------------

    def query_table(self, database, dimensions, measures):
        """
        Execute a Stat-Xplore table query.

        dimensions must be a list of lists:

            [
                ["field_uri"],
                ["field_uri"]
            ]

        measures must be:

            ["measure_uri"]
        """

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
            headers={
                "Content-Type": "application/json"
            }
        )

        print(f"\nHTTP status: {response.status_code}")

        response.raise_for_status()

        result = response.json()

        return result


# =============================================================================
# SCHEMA HELPERS
# =============================================================================

def save_json(data, filename):
    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Saved: {path}")


def inspect_schema(client, schema_id, filename=None):
    """
    Print a schema and return it.
    """

    print("\n" + "=" * 80)
    print(f"SCHEMA")
    print(schema_id)
    print("=" * 80)

    schema = client.get_schema(schema_id)

    if filename:
        save_json(schema, filename)

    return schema


def recursively_find_children(client, schema_id, seen=None):
    """
    Recursively walk a schema.

    This is important because FRS ethnicity/geography are exposed as
    GROUP objects at the database level.

    Returns all FIELD and MEASURE objects found below the supplied schema.
    """

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
            results.extend(
                recursively_find_children(
                    client,
                    child_id,
                    seen
                )
            )

    return results


def find_by_text(items, text):
    """
    Search schema objects by ID or label.
    """

    text = text.lower()

    matches = []

    for item in items:
        item_id = str(item.get("id", ""))
        label = str(item.get("label", ""))

        if text in item_id.lower() or text in label.lower():
            matches.append(item)

    return matches


# =============================================================================
# DATABASE INSPECTION
# =============================================================================

def inspect_database(client, database_id):
    """
    Inspect a database and recursively discover fields/measures.
    """

    print("\n" + "=" * 80)
    print("INSPECTING DATABASE")
    print(database_id)
    print("=" * 80)

    schema = client.get_schema(database_id)

    filename = f"{database_id.replace(':', '_')}_schema_full.json"
    save_json(schema, filename)

    direct_fields = []
    direct_measures = []
    groups = []

    for child in schema.get("children", []):

        child_type = child.get("type")

        if child_type == "FIELD":
            direct_fields.append(child)

        elif child_type == "MEASURE":
            direct_measures.append(child)

        elif child_type == "GROUP":
            groups.append(child)

    print(f"\nDirect fields:   {len(direct_fields)}")
    print(f"Direct measures: {len(direct_measures)}")
    print(f"Groups:          {len(groups)}")

    print("\nDIRECT FIELDS")
    print("-" * 80)

    for field in direct_fields:
        print(field["id"])
        print(f"    {field.get('label', '')}")

    print("\nDIRECT MEASURES")
    print("-" * 80)

    for measure in direct_measures:
        print(measure["id"])
        print(f"    {measure.get('label', '')}")

    print("\nGROUPS")
    print("-" * 80)

    for group in groups:
        print(group["id"])
        print(f"    {group.get('label', '')}")

    return schema


# =============================================================================
# CUBE PARSER
# =============================================================================

def get_field_items(field):
    """
    Get the values/items belonging to a dimension field.

    In a table response, fields contain an `items` collection.
    """

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
    """
    Recursively flatten Stat-Xplore cube values.

    Example cube:

        [
            [
                [100, 200],
                [300, 400]
            ]
        ]

    becomes:

        [
            [100],
            [200],
            [300],
            [400]
        ]

    where each row contains one cell value.

    Returns tuples:

        (dimension_indexes, value)
    """

    if prefix is None:
        prefix = []

    # Reached a scalar value
    if not isinstance(values, list):

        return [
            (
                prefix,
                values
            )
        ]

    rows = []

    for index, child in enumerate(values):

        rows.extend(
            flatten_cube(
                child,
                dimensions,
                depth + 1,
                prefix + [index]
            )
        )

    return rows


def parse_table_response(response):
    """
    Convert a Stat-Xplore /table response into a pandas DataFrame.

    This handles the actual response structure:

        {
            "fields": [...],
            "cubes": {
                "measure_uri": {
                    "values": [...]
                }
            }
        }
    """

    print("\n" + "=" * 80)
    print("PARSING STAT-XPLORE RESPONSE")
    print("=" * 80)

    save_json(
        response,
        "last_table_response.json"
    )

    fields = response.get("fields", [])
    cubes = response.get("cubes", {})

    print(f"Fields: {len(fields)}")
    print(f"Cubes:  {len(cubes)}")

    if not fields:
        raise RuntimeError(
            "Stat-Xplore returned no dimension fields."
        )

    if not cubes:
        raise RuntimeError(
            "Stat-Xplore returned no cubes."
        )

    # -------------------------------------------------------------------------
    # Build dimension metadata
    # -------------------------------------------------------------------------

    dimension_items = []

    for field in fields:

        label = field.get("label", field.get("id", "Unknown"))
        uri = field.get("uri", field.get("id"))

        items = get_field_items(field)

        print(f"\nDimension:")
        print(f"  Label: {label}")
        print(f"  URI:   {uri}")
        print(f"  Items: {len(items)}")

        dimension_items.append({
            "label": label,
            "uri": uri,
            "items": items
        })

    # -------------------------------------------------------------------------
    # Build all possible coordinate combinations
    # -------------------------------------------------------------------------

    item_lists = [
        dimension["items"]
        for dimension in dimension_items
    ]

    combinations = list(product(*[
        range(len(items))
        for items in item_lists
    ]))

    print(f"\nExpected table cells: {len(combinations)}")

    # -------------------------------------------------------------------------
    # Parse every cube
    # -------------------------------------------------------------------------

    data = []

    for measure_uri, cube in cubes.items():

        print("\n" + "-" * 80)
        print(f"MEASURE: {measure_uri}")
        print("-" * 80)

        if not isinstance(cube, dict):
            print(
                f"WARNING: cube is {type(cube).__name__}, "
                "not a dictionary"
            )
            continue

        values = cube.get("values")

        if values is None:
            print("WARNING: cube contains no values")
            continue

        print(
            f"Cube value structure received."
        )

        flattened = flatten_cube(
            values,
            dimension_items
        )

        value_map = {
            tuple(indexes): value
            for indexes, value in flattened
        }

        # ---------------------------------------------------------------------
        # Generate rows
        # ---------------------------------------------------------------------

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

            row[measure_uri] = value_map.get(
                coordinate
            )

            data.append(row)

    df = pd.DataFrame(data)

    # -------------------------------------------------------------------------
    # Clean duplicate rows generated by multiple cubes
    # -------------------------------------------------------------------------

    if not df.empty:

        dimension_labels = [
            dimension["label"]
            for dimension in dimension_items
        ]

        uri_columns = [
            f"{label}__URI"
            for label in dimension_labels
        ]

        measure_columns = [
            column
            for column in df.columns
            if column not in dimension_labels
            and column not in uri_columns
        ]

        # Group measure columns onto the same dimension rows
        if measure_columns:

            group_columns = dimension_labels + uri_columns

            df = (
                df.groupby(
                    group_columns,
                    dropna=False,
                    as_index=False
                )[measure_columns]
                .first()
            )

    print("\n" + "=" * 80)
    print("PARSER RESULT")
    print("=" * 80)

    print(f"Rows:    {len(df)}")
    print(f"Columns: {len(df.columns)}")

    print("\nColumns:")

    for column in df.columns:
        print(f"  {column}")

    if not df.empty:

        print("\nPreview:")
        print(
            df.head(20).to_string(index=False)
        )

    return df


# =============================================================================
# FRSPP TEST
# =============================================================================

def test_frsp_query(client):
    """
    Run a known-good FRSPP query.

    This verifies that table querying + cube parsing works.
    """

    print("\n" + "=" * 80)
    print("RUNNING FRSPP DATA TEST")
    print("=" * 80)

    database = "str:database:FRSPP"

    dimensions = [
        [
            "str:field:FRSPP:V_F_FRSPP:YEAR"
        ],
        [
            "str:field:FRSPP:V_F_FRSPP:AGEBAND"
        ],
        [
            "str:field:FRSPP:V_F_FRSPP:SEX"
        ],
    ]

    measures = [
        "str:count:FRSPP:V_F_FRSPP"
    ]

    response = client.query_table(
        database=database,
        dimensions=dimensions,
        measures=measures
    )

    save_json(
        response,
        "FRSPP_test_response.json"
    )

    df = parse_table_response(response)

    filename = os.path.join(
        OUTPUT_DIR,
        "FRSPP_test.csv"
    )

    df.to_csv(
        filename,
        index=False
    )

    print("\n" + "=" * 80)
    print("FRSPP TEST COMPLETE")
    print("=" * 80)

    print(f"Rows: {len(df)}")
    print(f"Saved: {filename}")

    return df


# =============================================================================
# FIND FIELDS INSIDE GROUPS
# =============================================================================

def find_database_fields(client, database_id):
    """
    Recursively discover all fields/measures below a database.

    This is the important part for FRS because fields such as Ethnicity
    and Geography are hidden inside GROUP objects.
    """

    print("\n" + "=" * 80)
    print("RECURSIVELY DISCOVERING FIELDS")
    print(database_id)
    print("=" * 80)

    objects = recursively_find_children(
        client,
        database_id
    )

    fields = [
        obj for obj in objects
        if obj.get("type") == "FIELD"
    ]

    measures = [
        obj for obj in objects
        if obj.get("type") == "MEASURE"
    ]

    counts = [
        obj for obj in objects
        if obj.get("type") == "COUNT"
    ]

    print(f"\nFields discovered:   {len(fields)}")
    print(f"Measures discovered: {len(measures)}")
    print(f"Counts discovered:   {len(counts)}")

    print("\nALL FIELDS")
    print("-" * 80)

    for field in fields:

        print(
            f"{field.get('id')}\n"
            f"    {field.get('label', '')}"
        )

    print("\nALL MEASURES")
    print("-" * 80)

    for measure in measures:

        print(
            f"{measure.get('id')}\n"
            f"    {measure.get('label', '')}"
        )

    return {
        "fields": fields,
        "measures": measures,
        "counts": counts,
    }


# =============================================================================
# SEARCH
# =============================================================================

def search_database(client, database_id, search_term):
    """
    Search recursively through a database's schema.
    """

    discovered = find_database_fields(
        client,
        database_id
    )

    all_objects = (
        discovered["fields"]
        + discovered["measures"]
        + discovered["counts"]
    )

    matches = find_by_text(
        all_objects,
        search_term
    )

    print("\n" + "=" * 80)
    print(f"SEARCH RESULTS: {search_term}")
    print("=" * 80)

    if not matches:

        print("No matches.")

        return []

    for item in matches:

        print(
            f"\nID:\n"
            f"{item.get('id')}\n"
            f"\nLABEL:\n"
            f"{item.get('label', '')}\n"
            f"\nTYPE:\n"
            f"{item.get('type', '')}"
        )

    return matches


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 80)
    print("STAT-XPLORE API DATA EXTRACTION")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    api_key = os.environ.get(
        "STATXPLORE_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "STATXPLORE_KEY is not set."
        )

    client = StatXploreClient(
        api_key=api_key
    )

    print("\nTesting authentication...")

    # Root schema
    root_schema = client.get_schema(
        "str:folder:ffrs"
    )

    print("Authentication successful.")
    print("Root schema retrieved.")

    save_json(
        root_schema,
        "root_schema.json"
    )

    # -------------------------------------------------------------------------
    # FRSPP
    # -------------------------------------------------------------------------

    inspect_database(
        client,
        "str:database:FRSPP"
    )

    # -------------------------------------------------------------------------
    # Recursively discover FRSPP fields
    # -------------------------------------------------------------------------

    frspp_objects = find_database_fields(
        client,
        "str:database:FRSPP"
    )

    # Search for ethnicity
    ethnicity_matches = search_database(
        client,
        "str:database:FRSPP",
        "ethnic"
    )

    # Search for geography
    geography_matches = search_database(
        client,
        "str:database:FRSPP",
        "geograph"
    )

    # -------------------------------------------------------------------------
    # Known-good test
    # -------------------------------------------------------------------------

    df = test_frsp_query(
        client
    )

    # -------------------------------------------------------------------------
    # Save discovered fields
    # -------------------------------------------------------------------------

    discovered = {
        "FRSPP": frspp_objects
    }

    save_json(
        discovered,
        "discovered_fields.json"
    )

    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()