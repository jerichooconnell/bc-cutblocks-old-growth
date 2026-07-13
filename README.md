# BC Cutblocks in Old Growth

Interactive map of current (already logged) and proposed cutblocks that
overlap high-site-index old growth in British Columbia's Coastal Western
Hemlock (CWH), Coastal Douglas-fir (CDF), and Interior Cedar-Hemlock (ICH)
biogeoclimatic zones.

Live: https://jerichooconnell.github.io/bc-cutblocks-old-growth/

Companion site (remaining old growth, no cutblock overlay):
https://jerichooconnell.github.io/bc-large-stature-forest/

## What it shows

- **Current cutblocks** — polygons from BC's air-photo-verified Consolidated
  Cutblocks layer that fall on old-growth-capable, high-site-index ground.
- **Proposed cutblocks** — BC Forest Tenure cutblocks not yet disturbed and
  not retired, with a planned harvest date roughly within the current
  decade, that overlap *currently standing* old growth.
- **Productivity tier toggle** — filters both layers to a minimum
  site-index percentile (75th / 85th / 95th), computed per BEC zone, so you
  can isolate the highest-productivity (biggest-tree-capable) stands at
  risk.
- Each cutblock is colored by its productivity tier (a light→dark ramp
  within its status color) and shows its exact site index, BEC zone, and
  harvest/planned-harvest date on click.

## Data sources (BC Data Catalogue WFS)

All fetched from `https://openmaps.gov.bc.ca/geo/pub/wfs`, province-wide:

- `WHSE_FOREST_VEGETATION.VEG_CONSOLIDATED_CUT_BLOCKS_SP` — current/already-logged cutblocks
- `WHSE_FOREST_TENURE.FTEN_CUT_BLOCK_POLY_SVW` — proposed cutblocks (tenure/cutting authorities)
- `WHSE_FOREST_VEGETATION.VEG_COMP_LYR_R1_POLY` (VRI) — old-growth land base, BEC zone, site index

## Methodology

"Old growth" uses the same definition as the companion large-stature site:
VRI stands with `PROJ_AGE_1 > 150` and `SITE_INDEX` at or above the 75th
percentile for their BEC zone (computed separately per zone from the full
forest-capable land base).

Because a cutblock's own attributes don't carry BEC zone or site index, each
cutblock is spatially joined against a VRI reference layer to inherit those
values. A cutblock overlapping more than one VRI stand is tagged with the
highest site index among the stands it touches.

Two different reference populations are used, because "was this old growth"
means something different for a block that's already been cut versus one
that hasn't:

- **Current cutblocks** are joined against the *historical* old-growth-capable
  baseline (current old growth **union** stands carrying an explicit harvest
  record — `HARVEST_DATE` / opening indicators — on equivalently high-site
  ground). A logged stand's present-day VRI age no longer reads "old", so
  only this historical baseline can identify that the ground *was*
  old-growth-capable before it was cut.
- **Proposed cutblocks** are joined against *currently standing* old growth
  (`PROJ_AGE_1 > 150` today). This is the real question for a block that
  hasn't been logged yet: does it overlap old growth that still exists.

**Proposed-cutblock filtering.** `FTEN_CUT_BLOCK_POLY_SVW`'s
`BLOCK_STATUS_CODE` / `HARVEST_AUTH_STATUS_CODE` abbreviations are not
reliably documented enough to trust as a "not yet harvested" signal, so
"proposed" instead uses the catalogue's own documented
`DISTURBANCE_START_DATE` field (null = ground disturbance hasn't started)
plus `RETIREMENT_DATE IS NULL` (excludes cancelled/closed authorities). The
raw not-yet-disturbed set also includes some multi-decade-stale unclosed
permits and administrative placeholder planned-harvest dates (e.g. year
2100, used as a far-future sentinel rather than a real date) — these are
dropped by requiring `PLANNED_HARVEST_DATE` be blank or within roughly the
current decade.

## Performance techniques

- Leaflet canvas rendering (`preferCanvas: true`).
- Cutblock polygons simplified to 10m tolerance before export.
- Color encodes productivity tier via a light/mid/dark shade ramp per status
  color (current vs. proposed), not opacity — opacity blends inconsistently
  against a varying satellite basemap.

## Rebuilding the data

Pipeline scripts (not included in this repo) live alongside the
`yew_project` / `bc-large-stature-forest` working tree:

1. `01_fetch_cutblocks.py` — pages both WFS layers to local GeoJSON, with
   retry (the BC WFS endpoint intermittently returns a 200 OK wrapping a
   connection-pool exception instead of a real HTTP error).
2. `02_join_old_growth.py` — spatial-joins cutblocks against the two VRI
   reference populations, keeping the highest-site-index match per block.
3. `03_export.py` — reprojects/simplifies to EPSG:4326 GeoJSON and computes
   `stats.json`.
