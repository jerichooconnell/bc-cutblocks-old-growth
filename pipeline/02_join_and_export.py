"""
Join freshly-fetched proposed cutblocks (pipeline/raw/fom_proposed.geojson)
against the frozen standing-old-growth reference (pipeline/reference/), attach
admin-boundary info, and write data/proposed_cutblocks.geojson + data/stats.json.

Runs in CI on every scheduled fetch. Exits non-zero if the reference files
are missing (they're committed, not fetched -- see pipeline/00_build_reference.py
for how to regenerate them, which must be run locally against the full VRI
geodatabase, not in CI).
"""
import json
import os
import sys
import time
import geopandas as gpd

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(ROOT)
RAW_DIR = f"{ROOT}/raw"
REF_DIR = f"{ROOT}/reference"
ZONES = ["CWH", "CDF", "ICH"]
HA = 1e-4
MIN_OVERLAP_HA = 0.5  # drop boundary-touching slivers

t0 = time.time()

ref_parquet = f"{REF_DIR}/standing_old_growth.parquet"
ref_stats_path = f"{REF_DIR}/reference_stats.json"
if not os.path.exists(ref_parquet) or not os.path.exists(ref_stats_path):
    sys.exit(
        f"missing frozen reference at {REF_DIR} -- rebuild locally with "
        f"00_build_reference.py against the full VRI geodatabase, then commit it."
    )

with open(ref_stats_path) as f:
    ref = json.load(f)

print("loading frozen standing-old-growth reference...")
standing_ref = gpd.read_parquet(ref_parquet)
print(f"  {len(standing_ref):,} rows ({time.time()-t0:.0f}s)")

print("loading freshly-fetched proposed cutblocks...")
with open(f"{RAW_DIR}/fom_proposed.geojson") as f:
    gj = json.load(f)
cutblocks = gpd.GeoDataFrame.from_features(gj["features"], crs="EPSG:3005")
cutblocks = cutblocks[cutblocks.geometry.notna() & ~cutblocks.geometry.is_empty].copy()
print(f"  {len(cutblocks):,} rows ({time.time()-t0:.0f}s)")


def best_match_join(cutblocks, ref):
    """
    Actual clipped overlap area (gpd.overlay), not the cutblock's full
    footprint on any intersection -- see pipeline README for why.
    The exported geometry stays the cutblock's own full polygon.
    """
    cutblocks = cutblocks.reset_index(drop=True)
    cutblocks["_cb_idx"] = cutblocks.index

    candidates = gpd.sjoin(cutblocks[["_cb_idx", "geometry"]], ref, how="inner", predicate="intersects")
    candidate_ids = candidates["_cb_idx"].unique()
    print(f"  sjoin candidates: {len(candidate_ids):,} of {len(cutblocks):,} ({time.time()-t0:.0f}s)")
    subset = cutblocks[cutblocks["_cb_idx"].isin(candidate_ids)][["_cb_idx", "geometry"]].copy()

    overlay = gpd.overlay(subset, ref, how="intersection", keep_geom_type=False)
    overlay["frag_ha"] = overlay.geometry.area * HA
    overlap_ha = overlay.groupby("_cb_idx")["frag_ha"].sum()
    overlap_ha = overlap_ha[overlap_ha >= MIN_OVERLAP_HA]
    best_tier = (
        overlay.sort_values("SITE_INDEX", ascending=False)
        .drop_duplicates("_cb_idx", keep="first")
        .set_index("_cb_idx")[["BEC_ZONE_CODE", "SITE_INDEX", "tier"]]
    )

    keep_ids = overlap_ha.index
    result = cutblocks[cutblocks["_cb_idx"].isin(keep_ids)].set_index("_cb_idx")
    result["area_ha"] = overlap_ha.reindex(result.index).round(2)
    result[["BEC_ZONE_CODE", "SITE_INDEX", "tier"]] = best_tier.reindex(result.index)
    result = result.reset_index(drop=True)
    print(f"  {len(result):,} cutblocks with >= {MIN_OVERLAP_HA}ha genuine overlap ({time.time()-t0:.0f}s)")
    return result


proposed = best_match_join(cutblocks, standing_ref)

print("attaching admin boundaries...")
regions = gpd.read_file(f"{RAW_DIR}/nr_regions.geojson").set_crs("EPSG:3005", allow_override=True)
districts = gpd.read_file(f"{RAW_DIR}/nr_districts.geojson").set_crs("EPSG:3005", allow_override=True)
tfls = gpd.read_file(f"{RAW_DIR}/tfl.geojson").set_crs("EPSG:3005", allow_override=True)

centroids = gpd.GeoDataFrame(proposed[[]].copy(), geometry=proposed.geometry.centroid, crs=proposed.crs)
centroids["_idx"] = centroids.index


def attach(centroids, admin_df, cols, rename=None):
    joined = gpd.sjoin(centroids, admin_df[cols + ["geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("_idx")
    joined = joined.set_index("_idx")[cols]
    if rename:
        joined = joined.rename(columns=rename)
    return joined


region_join = attach(centroids, regions, ["REGION_NAME"])
district_join = attach(centroids, districts, ["DISTRICT_NAME"])
tfl_join = attach(centroids, tfls, ["FOREST_FILE_ID", "LICENCEE"], rename={"FOREST_FILE_ID": "TFL", "LICENCEE": "TFL_LICENCEE"})
proposed = proposed.join(region_join).join(district_join).join(tfl_join)
print(f"  region matched: {proposed['REGION_NAME'].notna().sum():,}, "
      f"district matched: {proposed['DISTRICT_NAME'].notna().sum():,}, "
      f"TFL matched: {proposed['TFL'].notna().sum():,}")

proposed["geometry"] = proposed.geometry.simplify(10, preserve_topology=True)

proposed_cols = [
    "BEC_ZONE_CODE", "SITE_INDEX", "tier", "area_ha",
    "NAME", "FSP_HOLDER_NAME", "CREATE_DATE", "PLANNED_DEVELOPMENT_DATE", "PLANNED_AREA",
    "REGION_NAME", "DISTRICT_NAME", "TFL", "TFL_LICENCEE",
    "geometry",
]
proposed_out = proposed[proposed_cols].copy().to_crs(4326)

os.makedirs(f"{SITE_ROOT}/data", exist_ok=True)
out_geojson = f"{SITE_ROOT}/data/proposed_cutblocks.geojson"
if os.path.exists(out_geojson):
    os.remove(out_geojson)
proposed_out.to_file(out_geojson, driver="GeoJSON")
print(f"saved {out_geojson} ({len(proposed_out):,} features)")

stats = {"zones": {}, "site_index_tiers": {z: {"p75": round(ref["p75"][z], 1), "p85": round(ref["p85"][z], 1), "p95": round(ref["p95"][z], 1)} for z in ZONES}}
total_proposed_ha = total_proposed_count = total_standing_ha = 0.0
for z in ZONES:
    pz = proposed[proposed.BEC_ZONE_CODE == z]
    proposed_ha = round(float(pz["area_ha"].sum()), 1)
    standing_ha = ref["standing_ha"][z]
    stats["zones"][z] = {
        "proposed_ha": proposed_ha,
        "proposed_count": int(len(pz)),
        "standing_ha": standing_ha,
        "proposed_pct_of_standing": round(100 * proposed_ha / standing_ha, 1) if standing_ha > 0 else None,
    }
    total_proposed_ha += proposed_ha
    total_proposed_count += len(pz)
    total_standing_ha += standing_ha

stats["total_proposed_ha"] = round(total_proposed_ha, 1)
stats["total_proposed_count"] = int(total_proposed_count)
stats["total_standing_ha"] = round(total_standing_ha, 1)
stats["total_proposed_pct_of_standing"] = round(100 * total_proposed_ha / total_standing_ha, 1) if total_standing_ha > 0 else None
stats["updated"] = time.strftime("%Y-%m-%d", time.gmtime())

with open(f"{SITE_ROOT}/data/stats.json", "w") as f:
    json.dump(stats, f, indent=2)
print(json.dumps(stats, indent=2))
print(f"done ({time.time()-t0:.0f}s total)")
