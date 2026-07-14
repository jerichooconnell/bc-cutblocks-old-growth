# BC Cutblocks in Old Growth

Interactive map of proposed cutblocks that overlap standing old growth in
British Columbia's Coastal Western Hemlock (CWH), Coastal Douglas-fir (CDF),
and Interior Cedar-Hemlock (ICH) biogeoclimatic zones.

Live: https://jerichooconnell.github.io/bc-cutblocks-old-growth/

Companion site (remaining old growth, no cutblock overlay):
https://jerichooconnell.github.io/bc-large-stature-forest/

## What it shows

- **Proposed cutblocks** — from BC's Forest Operations Map
  (`FOM_CUTBLOCK_SP`, `LIFECYCLE_STATUS='Proposed'`) that overlap
  *currently standing* old growth (`PROJ_AGE_1 > 150`, any productivity).
- **Productivity tier filter** — site index (a proxy for how big/valuable
  the trees on a stand can get) buckets each old-growth stand into a tier
  relative to its own BEC zone's forest-capable land base: 0 = below the
  75th percentile, 1/2/3 = at or above the 75th/85th/95th percentile. This
  does **not** gate which cutblocks are shown — it's a filter/display
  dimension on top of the age-only old-growth definition.
- Searchable/filterable list (name, licensee, BEC zone, NR region, NR
  district, TFL) in the left panel, kept in sync with what's drawn on the
  map via a single shared filter predicate.
- Click any cutblock for its site index, licensee, planned area, posted/
  planned-development dates, region, district, and TFL.
- **Statement of Intent boundaries** (optional layer, off by default) — the
  traditional-territory boundaries First Nations have registered with the
  BC Treaty Commission to enter treaty negotiations. Shown as dashed
  outlines for geographic context; not joined against cutblocks or old
  growth in any way, and boundaries frequently overlap between neighbouring
  nations (that's expected — it's a claim/negotiation area, not a legal
  land designation).

## Data sources (BC Data Catalogue WFS)

Fetched from `https://openmaps.gov.bc.ca/geo/pub/wfs`, province-wide:

- `WHSE_FOREST_TENURE.FOM_CUTBLOCK_SP` — proposed cutblocks. Refreshed
  weekly (see below). `LIFECYCLE_STATUS='Proposed'` is a clean, documented
  field — unlike `FTEN_CUT_BLOCK_POLY_SVW`'s ambiguous status-code
  abbreviations, which were tried first and let through blocks that had
  mostly already been cut.
- `WHSE_ADMIN_BOUNDARIES.ADM_NR_REGIONS_SPG` / `ADM_NR_DISTRICTS_SPG` /
  `FADM_TFL_ALL_SP` — small admin-boundary layers, refetched every run,
  joined by cutblock centroid to attach region/district/TFL (the cutblock
  layer itself doesn't carry these).
- `REG_LEGAL_AND_ADMIN_BOUNDARIES.QSOI_BC_REGIONS` — Statement of Intent
  boundaries (59 features province-wide), fetched once and committed
  (`data/soi_boundaries.geojson`) since these boundaries change rarely; not
  part of the weekly refresh.
- `WHSE_FOREST_VEGETATION.VEG_COMP_LYR_R1_POLY` (VRI) — old-growth land
  base, BEC zone, site index. **Not** fetched by the periodic job (see
  below) — it's frozen and committed.

## Methodology

"Old growth" = VRI stands with `PROJ_AGE_1 > 150` on forest-capable land
(`BCLCS_LEVEL_1='V'`, `SITE_INDEX IS NOT NULL`) in CWH/CDF/ICH — no site-index
floor. Site index instead sets each stand's productivity *tier* relative to
its own BEC zone's percentile distribution (see above).

A cutblock's own attributes don't carry BEC zone or site index, so each
cutblock is spatially joined against the VRI old-growth reference to inherit
those values. The join uses the actual **clipped overlap area**
(`geopandas.overlay`, not `intersects`) — crediting a cutblock's full
footprint on any touch, rather than just the overlapping fragment, was an
early bug that produced "proposed" totals exceeding the amount of old growth
that exists. Overlaps under 0.5 ha are dropped as boundary slivers. A
cutblock overlapping more than one VRI stand inherits the highest site index
among the stands it touches (displayed geometry stays the cutblock's own
full polygon, not the clipped fragment).

## Automated weekly updates

`.github/workflows/update-cutblocks.yml` runs every Monday (plus
`workflow_dispatch` for manual runs), and:

1. `pipeline/01_fetch_proposed.py` — re-fetches FOM proposed cutblocks +
   the three admin-boundary layers from the WFS (with retry — the endpoint
   intermittently returns HTTP 200 wrapping an `ows:ExceptionReport`
   instead of a real error status).
2. `pipeline/02_join_and_export.py` — joins the fresh cutblocks against
   `pipeline/reference/standing_old_growth.parquet` (the frozen VRI
   reference, see below), attaches admin boundaries, and writes
   `data/proposed_cutblocks.geojson` + `data/stats.json`.
3. Commits and pushes the two data files if they changed. GitHub Pages
   rebuilds automatically on push.

**Why the VRI reference is frozen, not refetched every run:** VRI
(`VEG_COMP_LYR_R1_POLY`) is a huge, province-wide dataset (millions of
polygons) that changes on roughly an annual cadence — re-pulling ~1.2M rows
over the same WFS endpoint on every scheduled run would be slow, expensive,
and unnecessarily exposed to that endpoint's flakiness for no benefit, since
the underlying data barely moves week to week. FOM proposed cutblocks, by
contrast, genuinely change week to week (new postings, expirations), which
is why *that* layer is what the schedule refreshes.

### Rebuilding the frozen old-growth reference

Only needed if the VRI baseline needs refreshing (e.g. once a year) — not
part of the automated weekly job.

```
/home/jericho/anaconda3/envs/yew_pytorch/bin/python pipeline/00_build_reference.py
```

This reads the full province-wide VRI geodatabase locally (not via WFS —
`/home/jericho/yew_project/data/VEG_COMP_LYR_R1_POLY_2024.gdb`, 6.87M
features) and writes `pipeline/reference/standing_old_growth.parquet`
(GeoParquet, zstd-compressed, geometry simplified to 75m tolerance — the
unsimplified layer was 349MB, over GitHub's 100MB file limit) plus
`pipeline/reference/reference_stats.json` (per-zone site-index percentile
thresholds and total standing old-growth hectares). Commit both after
regenerating.

## Performance techniques

- Leaflet canvas rendering (`preferCanvas: true`).
- Cutblock polygons simplified to 10m tolerance before export.
- Color encodes productivity tier via a light/mid/dark shade ramp on the
  proposed-cutblock color, not opacity — opacity blends inconsistently
  against a varying satellite basemap.
