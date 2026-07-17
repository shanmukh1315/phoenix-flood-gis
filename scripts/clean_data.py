"""
Step 2 of the pipeline: clean and standardize the raw data downloaded by
fetch_data.py, and save analysis-ready layers into /data/processed.

Beginner-friendly note: "cleaning" in a GIS workflow usually means three
things -- (1) turning plain coordinate columns into real geometry objects,
(2) making sure every layer agrees on a coordinate reference system (CRS),
and (3) checking/fixing invalid geometries before doing any spatial math on
them. This script does all three, plus filters the statewide EPA facility
list down to just the Phoenix / Maricopa County area.
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# EPA program acronyms (from PGM_SYS_ACRNMS), ranked from most to least
# specific/relevant to environmental & flood-risk screening. The first
# matching acronym found for a facility becomes its simplified category.
# This mapping is just a readability layer over EPA's real program codes --
# nothing here is invented data, it is a relabeling of real values.
PROGRAM_CATEGORY_PRIORITY = [
    ("RCRAINFO", "Hazardous Waste (RCRA)"),
    ("CERCLIS", "Superfund / Contaminated Site"),
    ("SEMS", "Superfund / Contaminated Site"),
    ("NPDES", "Water Discharge (NPDES)"),
    ("ICIS", "Water/Air Compliance (ICIS)"),
    ("UIC", "Underground Injection Control"),
    ("SDWIS", "Drinking Water (SDWIS)"),
    ("AIRS/AFS", "Air Emissions (AIRS/AFS)"),
    ("EIS", "Air Emissions (EIS)"),
    ("E-GGRT", "Greenhouse Gas Reporting"),
    ("TRIS", "Toxics Release Inventory (TRI)"),
    ("BR", "Chemical Reporting (Biennial Report)"),
]
DEFAULT_CATEGORY = "Other / State-Registered Facility"


def derive_facility_category(pgm_sys_acrnms: str) -> str:
    """Map a facility's raw program-acronym string to one readable category."""
    if not isinstance(pgm_sys_acrnms, str) or not pgm_sys_acrnms.strip():
        return DEFAULT_CATEGORY
    programs_present = {token.split(":")[0].strip() for token in pgm_sys_acrnms.split(",")}
    for acronym, label in PROGRAM_CATEGORY_PRIORITY:
        if acronym in programs_present:
            return label
    return DEFAULT_CATEGORY


def load_and_clean_phoenix_boundary() -> gpd.GeoDataFrame:
    print("\n[1/3] Cleaning Phoenix boundary")

    if not config.PHOENIX_BOUNDARY_RAW.exists():
        raise FileNotFoundError(
            f"{config.PHOENIX_BOUNDARY_RAW} not found. Run scripts/fetch_data.py first."
        )

    boundary = gpd.read_file(config.PHOENIX_BOUNDARY_RAW)

    # Every GIS layer must have a defined CRS before you can trust distance
    # or overlay operations on it. TIGER/Line ships as EPSG:4269 (NAD83).
    if boundary.crs is None:
        raise ValueError("Phoenix boundary has no CRS defined -- cannot proceed safely.")
    print(f"    Raw CRS: {boundary.crs}")

    # Geometry validity check: a polygon can be technically "invalid" if its
    # edges self-intersect (common after any kind of geometric edit).
    # buffer(0) is a standard GeoPandas/Shapely trick to repair most of
    # these without changing the shape in any meaningful way.
    n_invalid = (~boundary.geometry.is_valid).sum()
    if n_invalid:
        print(f"    Repairing {n_invalid} invalid geometr{'y' if n_invalid == 1 else 'ies'}...")
        boundary["geometry"] = boundary.geometry.buffer(0)

    # Reproject to WGS84 (EPSG:4326) for storage/web-mapping consistency.
    boundary = boundary.to_crs(config.CRS_STORAGE)

    boundary = boundary[["NAME", "GEOID", "geometry"]].rename(columns={"NAME": "city_name"})
    boundary.to_file(config.PHOENIX_BOUNDARY_CLEAN, driver="GPKG")
    print(f"    Saved -> {config.PHOENIX_BOUNDARY_CLEAN}")
    return boundary


def load_and_clean_epa_facilities(phoenix_boundary_4326: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print("\n[2/3] Cleaning EPA FRS facilities")

    if not config.EPA_FRS_FACILITY_CSV.exists():
        raise FileNotFoundError(
            f"{config.EPA_FRS_FACILITY_CSV} not found. Run scripts/fetch_data.py first."
        )

    df = pd.read_csv(
        config.EPA_FRS_FACILITY_CSV,
        dtype={"POSTAL_CODE": str, "FIPS_CODE": str},
        low_memory=False,
    )
    print(f"    Loaded {len(df):,} statewide Arizona FRS facility records")

    # Drop records with missing or invalid latitude/longitude -- you cannot
    # place a facility on a map, or do any spatial analysis on it, without
    # valid coordinates.
    before = len(df)
    df = df.dropna(subset=["LATITUDE83", "LONGITUDE83"])
    df = df[
        df["LATITUDE83"].between(-90, 90) & df["LONGITUDE83"].between(-180, 180)
    ]
    # A small number of legacy FRS records use the sentinel (0, 0) for
    # "unknown location" -- that is not a real place, so drop it too.
    df = df[~((df["LATITUDE83"] == 0) & (df["LONGITUDE83"] == 0))]
    print(f"    Dropped {before - len(df):,} records with missing/invalid coordinates")

    # Standardize name/category text fields (trim whitespace, consistent case)
    df["facility_name"] = df["PRIMARY_NAME"].astype(str).str.strip().str.title()
    df["facility_category"] = df["PGM_SYS_ACRNMS"].apply(derive_facility_category)
    df["city_name_raw"] = df["CITY_NAME"].astype(str).str.strip().str.title()
    df["county_name_raw"] = df["COUNTY_NAME"].astype(str).str.strip().str.title()

    # Turn plain lat/lon columns into real point geometry. This is the
    # single step that promotes a normal pandas DataFrame into a GIS layer
    # (a GeoDataFrame) that GeoPandas can plot, reproject, and spatially join.
    facilities = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["LONGITUDE83"], df["LATITUDE83"]),
        crs=config.CRS_STORAGE,  # FRS coordinates are NAD83 geographic, treated as EPSG:4326 here
    )

    # Filter to facilities that actually fall within the Phoenix city
    # boundary using real spatial containment (a point-in-polygon test),
    # not just matching the CITY_NAME text column. This catches facilities
    # whose address says a neighboring city/ZIP but whose point coordinate
    # is genuinely inside Phoenix, and excludes the reverse case.
    boundary_union = phoenix_boundary_4326.unary_union
    within_phoenix = facilities[facilities.geometry.within(boundary_union)].copy()
    print(
        f"    {len(within_phoenix):,} of {len(facilities):,} statewide facilities fall "
        f"spatially within the Phoenix city boundary"
    )

    if within_phoenix.empty:
        raise ValueError(
            "Zero EPA facilities fell within the Phoenix boundary after the spatial "
            "filter -- something is likely wrong with the CRS or boundary geometry."
        )

    keep_cols = [
        "REGISTRY_ID",
        "facility_name",
        "facility_category",
        "PGM_SYS_ACRNMS",
        "SITE_TYPE_NAME",
        "LOCATION_ADDRESS",
        "city_name_raw",
        "county_name_raw",
        "geometry",
    ]
    within_phoenix = within_phoenix[keep_cols].rename(
        columns={
            "REGISTRY_ID": "registry_id",
            "PGM_SYS_ACRNMS": "epa_programs_raw",
            "SITE_TYPE_NAME": "site_type",
            "LOCATION_ADDRESS": "address",
        }
    )

    within_phoenix.to_file(config.EPA_FACILITIES_CLEAN, driver="GPKG")
    print(f"    Saved -> {config.EPA_FACILITIES_CLEAN}")
    return within_phoenix


def load_and_clean_flood_zones(phoenix_boundary_4326: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print("\n[3/3] Cleaning FEMA flood hazard zones")

    if not config.FEMA_FLOOD_ZONES_RAW.exists():
        raise FileNotFoundError(
            f"{config.FEMA_FLOOD_ZONES_RAW} not found. Run scripts/fetch_data.py first."
        )

    flood = gpd.read_file(config.FEMA_FLOOD_ZONES_RAW)
    print(f"    Loaded {len(flood):,} raw flood hazard polygons")

    if flood.crs is None:
        # The FEMA query explicitly requested outSR=4326, so assume WGS84
        # if the service did not embed a CRS in the GeoJSON (some ArcGIS
        # GeoJSON exports omit it because GeoJSON's spec assumes 4326).
        flood = flood.set_crs(config.CRS_STORAGE)
    else:
        flood = flood.to_crs(config.CRS_STORAGE)

    n_invalid = (~flood.geometry.is_valid).sum()
    if n_invalid:
        print(f"    Repairing {n_invalid} invalid flood zone geometr{'y' if n_invalid == 1 else 'ies'}...")
        flood["geometry"] = flood.geometry.buffer(0)

    # Drop any empty/missing geometries that can result from a buffer(0)
    # repair on a degenerate polygon.
    flood = flood[~flood.geometry.is_empty & flood.geometry.notna()]

    # Clip the (intentionally oversized) bounding-box query result down to
    # the true Phoenix city boundary, so flood zones from neighboring
    # cities like Glendale or Tempe don't leak into the Phoenix-only analysis.
    # This is a real geometric clip (gpd.overlay "intersection"), not just a
    # "does it touch Phoenix at all" filter -- an intersects() filter would
    # keep the *entire* polygon of any flood zone that merely crosses the
    # city line, which is what made earlier maps show flood zones bleeding
    # outside the Phoenix boundary. Clipping is done in the projected CRS
    # because polygon-on-polygon overlay is more numerically stable in a
    # linear-unit CRS than in geographic degrees.
    flood_proj = flood.to_crs(config.CRS_PROJECTED)
    boundary_proj = phoenix_boundary_4326.to_crs(config.CRS_PROJECTED)

    flood_phoenix = gpd.overlay(
        flood_proj,
        boundary_proj[["geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    flood_phoenix = flood_phoenix.to_crs(config.CRS_STORAGE)
    print(f"    {len(flood_phoenix):,} flood zone polygon pieces clipped to the Phoenix boundary")

    keep_cols = [c for c in ["FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "geometry"] if c in flood_phoenix.columns]
    flood_phoenix = flood_phoenix[keep_cols].rename(
        columns={"FLD_ZONE": "flood_zone", "ZONE_SUBTY": "zone_subtype", "SFHA_TF": "is_sfha"}
    )

    flood_phoenix.to_file(config.FEMA_FLOOD_ZONES_CLEAN, driver="GPKG")
    print(f"    Saved -> {config.FEMA_FLOOD_ZONES_CLEAN}")
    return flood_phoenix


def main():
    print("=" * 70)
    print("CLEANING DATA")
    print("=" * 70)

    boundary = load_and_clean_phoenix_boundary()
    facilities = load_and_clean_epa_facilities(boundary)
    flood_zones = load_and_clean_flood_zones(boundary)

    print("\n" + "=" * 70)
    print("CLEANING COMPLETE")
    print(f"  Phoenix boundary features : {len(boundary)}")
    print(f"  EPA facilities in Phoenix : {len(facilities)}")
    print(f"  Flood zone polygons       : {len(flood_zones)}")


if __name__ == "__main__":
    main()
