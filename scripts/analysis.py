"""
Step 3 of the pipeline: the core spatial analysis.

For every EPA-registered facility in Phoenix, this script asks: "is this
facility within 0.5 miles of a FEMA-designated flood hazard zone?" It does
this with three classic GIS operations:

1. Buffer  -- draw a 0.5-mile circle around every facility point.
2. Overlay/spatial join -- see which of those circles touch a flood zone
   polygon.
3. Summarize -- turn the per-facility results into aggregate statistics.

All numbers in the summary are computed from the data at run time --
nothing here is a hardcoded finding.
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def load_cleaned_layers():
    print("Loading cleaned layers ...")
    for path in (config.EPA_FACILITIES_CLEAN, config.FEMA_FLOOD_ZONES_CLEAN, config.PHOENIX_BOUNDARY_CLEAN):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run scripts/clean_data.py first.")

    facilities = gpd.read_file(config.EPA_FACILITIES_CLEAN)
    flood_zones = gpd.read_file(config.FEMA_FLOOD_ZONES_CLEAN)
    boundary = gpd.read_file(config.PHOENIX_BOUNDARY_CLEAN)
    print(f"  {len(facilities):,} facilities, {len(flood_zones):,} flood zone polygons")
    return facilities, flood_zones, boundary


def buffer_facilities(facilities_4326: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Reproject facility points to a projected CRS and draw a 0.5-mile buffer
    (circle) around each one.

    Buffering must happen in a projected CRS with a real linear unit (US
    feet, here) -- see the long comment in config.py for why EPSG:4326
    (degrees) would silently give the wrong buffer size.
    """
    print(f"\nBuffering {len(facilities_4326):,} facilities by {config.BUFFER_DISTANCE_MILES} miles ...")
    facilities_proj = facilities_4326.to_crs(config.CRS_PROJECTED)

    buffers = facilities_proj.copy()
    buffers["geometry"] = facilities_proj.geometry.buffer(config.BUFFER_DISTANCE_FEET)
    print(f"  Buffer radius: {config.BUFFER_DISTANCE_FEET:.0f} feet ({config.CRS_PROJECTED})")
    return buffers


def join_buffers_to_flood_zones(
    buffers_proj: gpd.GeoDataFrame, flood_zones_4326: gpd.GeoDataFrame
) -> pd.DataFrame:
    """
    Spatially join each facility's buffer against FEMA flood hazard polygons
    and roll the results up to one row per facility:
      - intersects_flood_zone: True if the buffer touches any Special Flood
        Hazard Area (SFHA) polygon (zones like A, AE, AH, AO, VE -- areas
        with a 1%-annual-chance flood risk). Zone X ("minimal risk", outside
        the mapped floodplain) and Zone D ("undetermined") are NOT counted
        as flood risk here, since flagging every facility near a Zone X
        polygon would make the flag meaningless (Zone X covers most of the
        city).
      - flood_zone_type: the distinct SFHA zone code(s) found within the
        buffer, e.g. "AE" or "A, AE".
    """
    print("Spatially joining facility buffers to FEMA flood hazard zones ...")
    flood_proj = flood_zones_4326.to_crs(config.CRS_PROJECTED)

    joined = gpd.sjoin(
        buffers_proj[["registry_id", "geometry"]],
        flood_proj[["flood_zone", "is_sfha", "geometry"]],
        how="left",
        predicate="intersects",
    )

    sfha_hits = joined[joined["is_sfha"] == "T"]
    zone_types_by_facility = (
        sfha_hits.groupby("registry_id")["flood_zone"]
        .apply(lambda zones: ", ".join(sorted(set(zones))))
        .rename("flood_zone_type")
    )

    result = pd.DataFrame({"registry_id": buffers_proj["registry_id"]})
    result = result.merge(zone_types_by_facility, on="registry_id", how="left")
    result["intersects_flood_zone"] = result["flood_zone_type"].notna()
    result["flood_zone_type"] = result["flood_zone_type"].fillna("None")

    n_flagged = result["intersects_flood_zone"].sum()
    print(f"  {n_flagged:,} of {len(result):,} facilities are within {config.BUFFER_DISTANCE_MILES} "
          f"miles of a FEMA Special Flood Hazard Area")
    return result


def build_summary(facilities_analyzed: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute every summary statistic straight from the analyzed data."""
    print("Building summary statistics ...")
    total = len(facilities_analyzed)
    n_at_risk = int(facilities_analyzed["intersects_flood_zone"].sum())
    pct_at_risk = round(100 * n_at_risk / total, 2) if total else 0.0

    rows = [
        {"metric": "total_facilities_analyzed", "value": total},
        {"metric": "facilities_within_0.5mi_of_sfha", "value": n_at_risk},
        {"metric": "pct_facilities_within_0.5mi_of_sfha", "value": pct_at_risk},
    ]

    category_counts = facilities_analyzed["facility_category"].value_counts()
    for category, count in category_counts.items():
        rows.append({"metric": f"category_count::{category}", "value": int(count)})

    flag_counts = facilities_analyzed["intersects_flood_zone"].value_counts()
    for flag, count in flag_counts.items():
        rows.append({"metric": f"flood_risk_flag_count::{flag}", "value": int(count)})

    at_risk = facilities_analyzed[facilities_analyzed["intersects_flood_zone"]]
    top_categories_near_sfha = at_risk["facility_category"].value_counts().head(5)
    for rank, (category, count) in enumerate(top_categories_near_sfha.items(), start=1):
        rows.append({"metric": f"top_category_near_sfha_rank{rank}::{category}", "value": int(count)})

    summary = pd.DataFrame(rows)
    return summary


def main():
    print("=" * 70)
    print("RUNNING SPATIAL ANALYSIS")
    print("=" * 70)

    facilities, flood_zones, boundary = load_cleaned_layers()

    buffers_proj = buffer_facilities(facilities)
    join_results = join_buffers_to_flood_zones(buffers_proj, flood_zones)

    facilities_analyzed = facilities.merge(join_results, on="registry_id", how="left")

    # Save the analyzed facilities (in WGS84, for easy web mapping/QGIS use)
    facilities_analyzed.to_file(config.FACILITIES_ANALYZED, driver="GPKG")
    print(f"\nSaved analyzed facilities -> {config.FACILITIES_ANALYZED}")

    # Save the buffers themselves (reprojected back to WGS84 for storage)
    buffers_4326 = buffers_proj.to_crs(config.CRS_STORAGE)
    buffers_4326 = buffers_4326.merge(
        facilities_analyzed[["registry_id", "facility_name", "intersects_flood_zone"]],
        on="registry_id",
        how="left",
    )
    buffers_4326.to_file(config.FACILITY_BUFFERS, driver="GPKG")
    print(f"Saved facility buffers -> {config.FACILITY_BUFFERS}")

    summary = build_summary(facilities_analyzed)
    summary.to_csv(config.SUMMARY_CSV, index=False)
    print(f"Saved summary statistics -> {config.SUMMARY_CSV}")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    total = len(facilities_analyzed)
    n_at_risk = int(facilities_analyzed["intersects_flood_zone"].sum())
    print(f"  Total facilities analyzed    : {total:,}")
    print(f"  Within 0.5 mi of a FEMA SFHA : {n_at_risk:,} "
          f"({100 * n_at_risk / total:.1f}%)")


if __name__ == "__main__":
    main()
