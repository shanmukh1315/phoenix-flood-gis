# Data Sources

This project uses only real, publicly available data. This file documents
every source used, exactly how it was accessed, and any limitations or
workarounds discovered while building the pipeline.

---

## 1. Phoenix City Boundary

- **Source name:** US Census Bureau TIGER/Line Places, 2023 vintage, Arizona
- **URL:** `https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_04_place.zip`
- **Access date:** 2026-07-07
- **Format:** Zipped ESRI Shapefile (read directly by GeoPandas via the
  `zip://` prefix, no manual unzip needed)
- **CRS:** EPSG:4269 (NAD83 geographic) as delivered; reprojected in
  `clean_data.py`
- **License / usage terms:** Public domain (US federal government data)
- **Fields used:** `NAME` (place name, filtered to `"Phoenix"`), `GEOID`,
  geometry
- **Access limitations / workarounds:**
  - The original plan was to use the City of Phoenix open data portal /
    ArcGIS REST services directly. That was dropped in favor of Census
    TIGER/Line because TIGER is a stable, versioned, no-auth, no-rate-limit
    federal source, whereas city open-data portals periodically renumber
    or retire feature layers, which breaks reproducibility for anyone
    re-running this pipeline later.
  - The statewide Arizona Places file (all AZ cities/towns) is downloaded
    and then filtered down to the single `Phoenix` feature locally --
    there is no per-city download endpoint.

---

## 2. EPA Facility Registry Service (FRS) — Environmental Facilities

- **Source name:** EPA Facility Registry Service (FRS), Arizona
  state-combined CSV bulk download
- **URL:** `https://ordsext.epa.gov/FLA/www3/state_files/state_combined_az.zip`
  (linked from the official EPA page
  `https://www.epa.gov/frs/epa-state-combined-csv-download-files`)
- **Access date:** 2026-07-07
- **Format:** Zipped CSV files (facility, environmental interest, NAICS,
  SIC, program, and other reference tables; this project uses only
  `AZ_FACILITY_FILE.CSV`, since it already includes a semicolon/comma
  -delimited `PGM_SYS_ACRNMS` column listing every EPA/state program each
  facility is enrolled in -- enough to derive a facility category without
  needing a separate join against `AZ_ENVIRONMENTAL_INTEREST_FILE.CSV`)
- **CRS:** None (plain lat/lon columns `LATITUDE83` / `LONGITUDE83`, NAD83
  geographic -- effectively equivalent to EPSG:4269 / treated as EPSG:4326
  for this analysis, consistent with EPA's own documentation)
- **License / usage terms:** Public domain (US federal government data)
- **Fields used:** `REGISTRY_ID`, `PRIMARY_NAME`, `LOCATION_ADDRESS`,
  `CITY_NAME`, `COUNTY_NAME`, `STATE_CODE`, `SITE_TYPE_NAME`,
  `LATITUDE83`, `LONGITUDE83`, `PGM_SYS_ACRNMS` (the last is parsed to
  derive a human-readable `facility_category`)
- **Access limitations / workarounds:**
  - **The FRS REST API (`frs_rest_services.get_facilities`) was tried
    first** and does support spatial queries via `latitude83` /
    `longitude83` / `search_radius` (miles). However, it enforces a hidden
    "process limit" on result size and returns
    `"Process Limit would be exceeded - please make search parameters more
    selective!"` for any radius wide enough to cover the Phoenix metro
    area (a 3-mile radius around downtown Phoenix already fails; only a
    ~1-mile radius consistently succeeds). Tiling the whole city into
    dozens of 1-mile-radius circles was judged too fragile/slow for a
    reproducible pipeline.
  - **Resolution:** EPA publishes the exact same underlying data as a
    documented bulk CSV download per state (see URL above). This project
    uses that bulk download instead, then filters to Maricopa
    County / Phoenix locally in `clean_data.py` using a real spatial
    join against the Phoenix boundary polygon, not string matching alone.
  - The facility file contains statewide Arizona facilities (~59,700
    rows); only a small subset intersects Phoenix/Maricopa County and
    survives the coordinate-validity and spatial-containment filters in
    `clean_data.py`.
  - `PGM_SYS_ACRNMS` is a semicolon/comma-delimited list of every EPA and
    state program a facility is enrolled in (e.g. `RCRAINFO`, `AIRS/AFS`,
    `NPDES`, `TRIS`). `clean_data.py` derives a single simplified
    `facility_category` from this field for readability; the full raw
    value is retained in the cleaned attribute table.

---

## 3. FEMA National Flood Hazard Layer (NFHL) — Flood Hazard Zones

- **Source name:** FEMA National Flood Hazard Layer (NFHL), ArcGIS REST
  MapServer, Layer 28 ("Flood Hazard Zones")
- **URL:** `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- **Access date:** 2026-07-07
- **Format:** GeoJSON (via `f=geojson` on the ArcGIS REST query endpoint)
- **CRS:** Requested and returned in EPSG:4326 (`outSR=4326`)
- **License / usage terms:** Public domain (US federal government data,
  FEMA)
- **Fields used:** `FLD_ZONE` (flood zone code, e.g. `A`, `AE`, `X`),
  `ZONE_SUBTY` (zone subtype, e.g. "FLOODWAY", "0.2 PCT ANNUAL CHANCE
  FLOOD HAZARD"), `SFHA_TF` (T/F flag for whether the zone is a Special
  Flood Hazard Area), geometry
- **Access limitations / workarounds:**
  - There is no single "download the whole layer" button for NFHL
    polygons at the national/regional level, so the layer is queried by
    bounding box (see `config.PHOENIX_QUERY_BBOX`) via the ArcGIS REST
    `query` operation.
  - The service advertises a `maxRecordCount` of 2,000 features per
    request, but in practice requesting 2,000 flood-zone polygons with
    full geometry in one call reliably returned `HTTP 500` errors. A
    request page size of 500 (see `config.FEMA_PAGE_SIZE`) works
    reliably. `fetch_data.py` pages through the bounding box with
    `resultOffset` until a page returns fewer than 500 features, and
    retries each page up to 3 times on transient failures.
  - The bounding box is intentionally generous (covers more than just
    Phoenix) so that Phoenix's irregular, non-rectangular city boundary is
    never clipped; `clean_data.py` then spatially clips the result down to
    the real Phoenix polygon.

---

## 4. Maricopa County GIS Open Data (Optional Context Layer)

Not used in the current version of this project. The Phoenix boundary from
Census TIGER/Line already provides the geographic extent needed for the
core analysis (facility-to-flood-zone proximity), and adding a county
boundary or parcels layer did not materially change the analysis. This is
listed here as a natural "next step" enhancement — see the README's
"What I would improve with more time" section.
