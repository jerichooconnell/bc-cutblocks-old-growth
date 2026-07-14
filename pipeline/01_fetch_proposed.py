"""
Fetch current FOM "Proposed" cutblocks + the small admin-boundary layers
(NR region, NR district, TFL) from the BC Data Catalogue WFS. Runs in CI on
a schedule -- this is the only WFS traffic the periodic job does (the old-
growth reference is frozen and committed, see pipeline/reference/).

The WFS endpoint intermittently returns HTTP 200 wrapping an
ows:ExceptionReport instead of a real error status, so retries are judged by
parsing the body, not the status code.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse

WFS = "https://openmaps.gov.bc.ca/geo/pub/wfs"
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = f"{ROOT}/raw"
os.makedirs(RAW_DIR, exist_ok=True)

LAYERS = {
    "fom_proposed": {
        "typeName": "pub:WHSE_FOREST_TENURE.FOM_CUTBLOCK_SP",
        "propertyName": "FOM_ID,CUT_BLOCK_ID,NAME,FSP_HOLDER_NAME,LIFECYCLE_STATUS,CREATE_DATE,PLANNED_DEVELOPMENT_DATE,PLANNED_AREA,SHAPE",
        "cql_filter": "LIFECYCLE_STATUS='Proposed'",
        "sortBy": "OBJECTID",
        "paged": True,
    },
    "nr_regions": {
        "typeName": "pub:WHSE_ADMIN_BOUNDARIES.ADM_NR_REGIONS_SPG",
        "propertyName": "REGION_NAME,SHAPE",
        "cql_filter": None,
        "sortBy": "OBJECTID",
        "paged": False,
    },
    "nr_districts": {
        "typeName": "pub:WHSE_ADMIN_BOUNDARIES.ADM_NR_DISTRICTS_SPG",
        "propertyName": "DISTRICT_NAME,SHAPE",
        "cql_filter": None,
        "sortBy": "OBJECTID",
        "paged": False,
    },
    "tfl": {
        "typeName": "pub:WHSE_ADMIN_BOUNDARIES.FADM_TFL_ALL_SP",
        "propertyName": "FOREST_FILE_ID,LICENCEE,SHAPE",
        "cql_filter": None,
        "sortBy": "OBJECTID",
        "paged": False,
    },
}

PAGE_SIZE = 5000


def fetch_page(type_name, property_name, cql_filter, sort_by, start_index, max_attempts=15):
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": type_name, "outputFormat": "json",
        "count": str(PAGE_SIZE), "startIndex": str(start_index),
        "srsName": "EPSG:3005", "propertyName": property_name, "sortBy": sort_by,
    }
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    url = WFS + "?" + urllib.parse.urlencode(params)

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                body = resp.read()
            data = json.loads(body)
            if "features" not in data:
                raise ValueError(f"no features key: {str(data)[:200]}")
            return data["features"]
        except Exception as e:
            wait = min(3 * attempt, 30)
            print(f"    attempt {attempt} failed ({e}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"giving up on startIndex={start_index} after {max_attempts} attempts")


def fetch_layer(name, spec):
    print(f"fetching {name} ({spec['typeName']})...")
    t0 = time.time()
    all_features = []
    if not spec["paged"]:
        all_features = fetch_page(spec["typeName"], spec["propertyName"], spec["cql_filter"], spec["sortBy"], 0)
    else:
        start = 0
        while True:
            feats = fetch_page(spec["typeName"], spec["propertyName"], spec["cql_filter"], spec["sortBy"], start)
            all_features.extend(feats)
            print(f"  startIndex={start}: got {len(feats)} ({time.time()-t0:.0f}s)", flush=True)
            if len(feats) < PAGE_SIZE:
                break
            start += PAGE_SIZE

    out_path = f"{RAW_DIR}/{name}.geojson"
    with open(out_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": all_features}, f)
    print(f"  saved {out_path}: {len(all_features):,} features ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    which = sys.argv[1:] or list(LAYERS.keys())
    for name in which:
        fetch_layer(name, LAYERS[name])
