"""
ONE-TIME, LOCAL-ONLY script. Not run in CI.

Rebuilds the frozen "standing old growth" reference layer that the periodic
GitHub Actions job joins fresh proposed cutblocks against. The original
cached VRI extraction (land_base_raw.gpkg, from an earlier session) is gone;
this rebuilds it from the same source the rest of this project already uses
locally -- the full province-wide VRI geodatabase at
data/VEG_COMP_LYR_R1_POLY_2024.gdb (6,872,386 features, EPSG:3005) -- rather
than re-pulling ~1.1M rows over the flaky BC WFS endpoint.

Forest-capable definition mirrors scripts/preprocessing/apply_forestry_mask.py's
convention (BCLCS_LEVEL_1 != 'N' i.e. vegetated) plus SITE_INDEX IS NOT NULL,
matching this project's documented "forest-capable, SITE_INDEX not null"
criterion. Old growth = PROJ_AGE_1 > 150, no site-index floor (site index
instead sets a productivity tier), same definition used throughout this site.

Run with: /home/jericho/anaconda3/envs/yew_pytorch/bin/python 00_build_reference.py
"""
import json
import os
import time
import geopandas as gpd
import pyogrio

GDB = "/home/jericho/yew_project/data/VEG_COMP_LYR_R1_POLY_2024.gdb"
LAYER = "VEG_COMP_LYR_R1_POLY"
ZONES = ["CWH", "CDF", "ICH"]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference")
HA = 1e-4

t0 = time.time()
print("reading VRI geodatabase (filtered)...")
where = (
    "BEC_ZONE_CODE IN ('CWH','CDF','ICH') "
    "AND BCLCS_LEVEL_1 = 'V' "
    "AND SITE_INDEX IS NOT NULL"
)
vri = pyogrio.read_dataframe(
    GDB, layer=LAYER, where=where,
    columns=["BEC_ZONE_CODE", "SITE_INDEX", "PROJ_AGE_1", "BCLCS_LEVEL_1"],
)
vri = gpd.GeoDataFrame(vri, geometry="geometry", crs="EPSG:3005")
print(f"  {len(vri):,} forest-capable rows ({time.time()-t0:.0f}s)")

p75, p85_map, p95_map = {}, {}, {}
for z in ZONES:
    sub = vri.loc[vri.BEC_ZONE_CODE == z, "SITE_INDEX"]
    p75[z] = float(sub.quantile(0.75))
    p85_map[z] = float(sub.quantile(0.85))
    p95_map[z] = float(sub.quantile(0.95))
vri["p75"] = vri["BEC_ZONE_CODE"].map(p75)
vri["p85"] = vri["BEC_ZONE_CODE"].map(p85_map)
vri["p95"] = vri["BEC_ZONE_CODE"].map(p95_map)

standing = vri[vri["PROJ_AGE_1"] > 150].copy()
print(f"standing old growth (age>150): {len(standing):,} ({time.time()-t0:.0f}s)")

standing["tier"] = 0
standing.loc[standing["SITE_INDEX"] >= standing["p75"], "tier"] = 1
standing.loc[standing["SITE_INDEX"] >= standing["p85"], "tier"] = 2
standing.loc[standing["SITE_INDEX"] >= standing["p95"], "tier"] = 3
standing["SITE_INDEX"] = standing["SITE_INDEX"].astype("float64").round(1)

standing_ha_zone = standing.groupby("BEC_ZONE_CODE").geometry.apply(lambda g: g.area.sum() * HA)
reference_stats = {
    "p75": p75, "p85": p85_map, "p95": p95_map,
    "standing_ha": {z: round(float(standing_ha_zone.get(z, 0.0)), 1) for z in ZONES},
    "built_from": "VEG_COMP_LYR_R1_POLY_2024.gdb (local, one-time)",
}
print("reference_stats:", json.dumps(reference_stats, indent=2))

standing_ref = standing[["BEC_ZONE_CODE", "SITE_INDEX", "tier", "geometry"]].reset_index(drop=True)
# Simplify hard (75m) for a committed-to-git artifact -- this layer is only
# used for spatial overlay against cutblocks, never displayed directly, and
# at 10m tolerance the raw GPKG was 349MB (over GitHub's 100MB file limit).
# GeoParquet+zstd on top of the 75m simplification gets this to ~64MB.
standing_ref["geometry"] = standing_ref.geometry.simplify(75, preserve_topology=True)

os.makedirs(OUT_DIR, exist_ok=True)
standing_ref.to_parquet(f"{OUT_DIR}/standing_old_growth.parquet", compression="zstd")
with open(f"{OUT_DIR}/reference_stats.json", "w") as f:
    json.dump(reference_stats, f, indent=2)

print(f"done ({time.time()-t0:.0f}s total)")
