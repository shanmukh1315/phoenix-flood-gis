"""
Central configuration for the Phoenix Environmental & Flood Risk GIS Analysis project.

All paths, URLs, and analysis parameters live here so the rest of the
pipeline (fetch -> clean -> analyze -> map -> report) reads from one
single source of truth instead of scattering "magic values" across files.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MAPS_DIR = PROJECT_ROOT / "maps"
REPORTS_DIR = PROJECT_ROOT / "reports"
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"

for _dir in (DATA_RAW_DIR, DATA_PROCESSED_DIR, MAPS_DIR, REPORTS_DIR, SCREENSHOTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Raw data file paths
# ---------------------------------------------------------------------------
PHOENIX_BOUNDARY_RAW = DATA_RAW_DIR / "phoenix_boundary_raw.geojson"
MARICOPA_PLACES_RAW = DATA_RAW_DIR / "tl_2023_04_place.zip"

EPA_FRS_AZ_ZIP = DATA_RAW_DIR / "state_combined_az.zip"
EPA_FRS_FACILITY_CSV = DATA_RAW_DIR / "AZ_FACILITY_FILE.CSV"

FEMA_FLOOD_ZONES_RAW = DATA_RAW_DIR / "fema_flood_zones_raw.geojson"

# ---------------------------------------------------------------------------
# Processed data file paths
# ---------------------------------------------------------------------------
PHOENIX_BOUNDARY_CLEAN = DATA_PROCESSED_DIR / "phoenix_boundary.gpkg"
EPA_FACILITIES_CLEAN = DATA_PROCESSED_DIR / "epa_facilities_phoenix.gpkg"
FEMA_FLOOD_ZONES_CLEAN = DATA_PROCESSED_DIR / "fema_flood_zones_phoenix.gpkg"

FACILITIES_ANALYZED = DATA_PROCESSED_DIR / "facilities_analyzed.gpkg"
FACILITY_BUFFERS = DATA_PROCESSED_DIR / "facility_buffers.gpkg"
SUMMARY_CSV = DATA_PROCESSED_DIR / "summary_statistics.csv"

# ---------------------------------------------------------------------------
# Map / report output paths
# ---------------------------------------------------------------------------
STATIC_MAP_PATH = MAPS_DIR / "final_map.png"
INTERACTIVE_MAP_PATH = MAPS_DIR / "interactive_map.html"
REPORT_PDF_PATH = REPORTS_DIR / "gis_summary.pdf"

# ---------------------------------------------------------------------------
# Data source endpoints
# ---------------------------------------------------------------------------
# US Census TIGER/Line 2023 Places file for Arizona. Used to derive the
# Phoenix city boundary. This is a stable, no-auth, no-rate-limit federal
# source -- more reliable for automated pipelines than the City of Phoenix
# ArcGIS portal, which changes layer IDs periodically.
CENSUS_TIGER_AZ_PLACES_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_04_place.zip"
)
PHOENIX_PLACE_NAME = "Phoenix"
PHOENIX_STATE_FIPS = "04"  # Arizona

# EPA Facility Registry Service (FRS) -- state-combined CSV bulk download.
# This is the officially documented bulk-download product (see
# https://www.epa.gov/frs/epa-state-combined-csv-download-files) and avoids
# the FRS REST API's small "process limit" row cap, which rejects any
# spatial/city query broad enough to cover a metro area the size of Phoenix.
EPA_FRS_AZ_ZIP_URL = "https://ordsext.epa.gov/FLA/www3/state_files/state_combined_az.zip"

# FEMA National Flood Hazard Layer (NFHL), ArcGIS REST MapServer.
# Layer 28 = "Flood Hazard Zones" (polygon layer with FLD_ZONE / ZONE_SUBTY /
# SFHA_TF attributes). Queried by bounding box because a full-layer export
# is not offered and the service caps each response at 2,000 records.
FEMA_NFHL_MAPSERVER_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
FEMA_FLOOD_ZONE_LAYER_ID = 28
# The service advertises a 2,000-record max, but in practice returning that
# many complex flood-zone polygons with full geometry in one request causes
# the server to error out (HTTP 500). 500 records per page is small enough
# to be reliable while still needing only a handful of requests for Phoenix.
FEMA_PAGE_SIZE = 500

# Bounding box (WGS84 / EPSG:4326) used to query FEMA NFHL. Chosen to
# comfortably cover the City of Phoenix; the cleaning step then clips to the
# real Phoenix boundary polygon so this generous box does not leak data
# from neighboring cities into the final analysis.
PHOENIX_QUERY_BBOX = {
    "xmin": -112.35,
    "ymin": 33.28,
    "xmax": -111.85,
    "ymax": 33.72,
}

# ---------------------------------------------------------------------------
# Coordinate reference systems
# ---------------------------------------------------------------------------
# EPSG:4326 (WGS84 lat/lon) is used for storage and for the Folium web map,
# because Folium/Leaflet always expects geographic (lat/lon) coordinates.
CRS_STORAGE = "EPSG:4326"
CRS_WEB_MAP = "EPSG:4326"

# EPSG:2223 -- NAD83 / Arizona Central State Plane (US Survey Feet) is a
# projected CRS centered on the Phoenix metro area. It is used for ALL
# distance/area math (buffering, spatial joins measured in miles).
#
# Why not just buffer in EPSG:4326? EPSG:4326 stores coordinates in decimal
# degrees, not a linear unit like feet or meters. A ".5" buffer in that CRS
# would mean "0.5 degrees", not "0.5 miles" -- and a degree of longitude
# shrinks as you move away from the equator, so the same buffer "radius"
# would represent a different real-world distance depending on latitude.
# Buffering must be done in a projected CRS with a true linear unit so the
# 0.5-mile buffer is geometrically correct and consistent everywhere in the
# study area.
CRS_PROJECTED = "EPSG:2223"

# ---------------------------------------------------------------------------
# Analysis parameters
# ---------------------------------------------------------------------------
BUFFER_DISTANCE_MILES = 0.5
FEET_PER_MILE = 5280
BUFFER_DISTANCE_FEET = BUFFER_DISTANCE_MILES * FEET_PER_MILE  # EPSG:2223 units are US survey feet

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "Phoenix-GIS-Portfolio-Project/1.0 (educational/portfolio use)"
