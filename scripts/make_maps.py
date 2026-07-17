"""
Step 4 of the pipeline: produce the static map (matplotlib) and the
interactive web map (Folium) from the analyzed data.
"""

import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
from folium.plugins import MarkerCluster

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def load_layers():
    for path in (config.PHOENIX_BOUNDARY_CLEAN, config.FEMA_FLOOD_ZONES_CLEAN, config.FACILITIES_ANALYZED):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run the earlier pipeline steps first.")

    boundary = gpd.read_file(config.PHOENIX_BOUNDARY_CLEAN)
    flood_zones = gpd.read_file(config.FEMA_FLOOD_ZONES_CLEAN)
    facilities = gpd.read_file(config.FACILITIES_ANALYZED)
    return boundary, flood_zones, facilities


def make_static_map(boundary, flood_zones, facilities):
    print("Building static map (matplotlib) ...")

    fig, ax = plt.subplots(figsize=(12, 12), dpi=200)

    # Layer 1: Phoenix boundary (context outline)
    boundary.boundary.plot(ax=ax, color="black", linewidth=1.5, zorder=1, label="Phoenix city boundary")

    # Layer 2: FEMA flood hazard zones, colored by SFHA status
    sfha = flood_zones[flood_zones["is_sfha"] == "T"]
    non_sfha = flood_zones[flood_zones["is_sfha"] != "T"]
    if not non_sfha.empty:
        non_sfha.plot(ax=ax, color="#b0c4de", edgecolor="none", alpha=0.5, zorder=2)
    if not sfha.empty:
        sfha.plot(ax=ax, color="#4a90d9", edgecolor="#1f5f99", linewidth=0.3, alpha=0.65, zorder=3)

    # Layer 3: facilities, color-coded by flood-risk flag
    not_at_risk = facilities[~facilities["intersects_flood_zone"]]
    at_risk = facilities[facilities["intersects_flood_zone"]]
    not_at_risk.plot(ax=ax, color="#2e7d32", markersize=6, alpha=0.6, zorder=4)
    at_risk.plot(ax=ax, color="#c62828", markersize=8, alpha=0.8, zorder=5)

    minx, miny, maxx, maxy = boundary.total_bounds
    pad_x, pad_y = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_axis_off()

    # Title
    ax.set_title(
        "Phoenix Environmental Facilities & FEMA Flood Hazard Zones\n"
        f"Facilities within {config.BUFFER_DISTANCE_MILES} mile of a Special Flood Hazard Area",
        fontsize=15,
        fontweight="bold",
        pad=16,
    )

    # Legend (built manually so it covers boundary/flood/facility layers together)
    legend_handles = [
        plt.Line2D([0], [0], color="black", lw=1.5, label="Phoenix city boundary"),
        plt.Rectangle((0, 0), 1, 1, fc="#4a90d9", alpha=0.65, label="FEMA Special Flood Hazard Area (SFHA)"),
        plt.Rectangle((0, 0), 1, 1, fc="#b0c4de", alpha=0.5, label="FEMA flood zone (non-SFHA, e.g. Zone X/D)"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#c62828", markersize=9,
                   label=f"Facility within {config.BUFFER_DISTANCE_MILES} mi of SFHA"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#2e7d32", markersize=8,
                   label=f"Facility NOT within {config.BUFFER_DISTANCE_MILES} mi of SFHA"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=8.5, framealpha=0.9)

    # North arrow (simple annotation -- data is in EPSG:4326 so "up" is north)
    ax.annotate(
        "N",
        xy=(0.96, 0.90), xytext=(0.96, 0.80),
        xycoords="axes fraction",
        ha="center", fontsize=13, fontweight="bold",
        arrowprops=dict(facecolor="black", width=3, headwidth=10, headlength=8),
    )

    # Scale note (approximate; EPSG:4326 degrees don't have a true linear scale bar,
    # so a text note is used instead of a graphical scale bar) + data source note,
    # placed in a dedicated strip below the map axes so they never overlap the legend.
    fig.text(
        0.02, 0.012,
        "Approx. extent: Phoenix city limits (~30 mi E-W). Map units: decimal degrees (EPSG:4326).  |  "
        "Sources: US Census TIGER/Line 2023 (boundary); EPA Facility Registry Service (facilities); "
        "FEMA National Flood Hazard Layer (flood zones). See data_sources.md.",
        fontsize=7.5, color="dimgray", va="bottom", ha="left",
    )

    fig.tight_layout(rect=[0, 0.02, 1, 1])
    fig.savefig(config.STATIC_MAP_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved -> {config.STATIC_MAP_PATH}")


def make_interactive_map(boundary, flood_zones, facilities):
    print("Building interactive map (Folium) ...")

    # Folium/Leaflet expects lat/lon (EPSG:4326) -- all inputs already are.
    centroid = boundary.geometry.iloc[0].centroid
    fmap = folium.Map(location=[centroid.y, centroid.x], zoom_start=11, tiles="cartodbpositron")

    boundary_layer = folium.FeatureGroup(name="Phoenix city boundary", show=True)
    folium.GeoJson(
        boundary,
        style_function=lambda x: {"color": "black", "weight": 2, "fillOpacity": 0},
    ).add_to(boundary_layer)
    boundary_layer.add_to(fmap)

    def flood_style(feature):
        is_sfha = feature["properties"].get("is_sfha") == "T"
        return {
            "color": "#1f5f99" if is_sfha else "#7a8a99",
            "weight": 0.5,
            "fillColor": "#4a90d9" if is_sfha else "#b0c4de",
            "fillOpacity": 0.45 if is_sfha else 0.25,
        }

    flood_layer = folium.FeatureGroup(name="FEMA flood hazard zones", show=True)
    folium.GeoJson(
        flood_zones,
        style_function=flood_style,
        tooltip=folium.GeoJsonTooltip(fields=["flood_zone", "zone_subtype", "is_sfha"]),
    ).add_to(flood_layer)
    flood_layer.add_to(fmap)

    at_risk_layer = folium.FeatureGroup(name=f"Facilities within {config.BUFFER_DISTANCE_MILES} mi of FEMA SFHA", show=True)
    # showCoverageOnHover=False disables Leaflet.markercluster's default
    # behavior of drawing a big rectangle showing every marker a cluster
    # bubble represents whenever you hover it -- that rectangle is a UI
    # affordance of the clustering plugin, not GIS data, and it makes
    # screenshots of the map look like there's a stray box floating on it.
    at_risk_cluster = MarkerCluster(options={"showCoverageOnHover": False}).add_to(at_risk_layer)
    not_risk_layer = folium.FeatureGroup(name="Other facilities", show=False)
    not_risk_cluster = MarkerCluster(options={"showCoverageOnHover": False}).add_to(not_risk_layer)

    for _, row in facilities.iterrows():
        at_risk = bool(row["intersects_flood_zone"])
        popup_html = (
            f"<b>{row['facility_name']}</b><br>"
            f"Category: {row['facility_category']}<br>"
            f"Flood risk (within {config.BUFFER_DISTANCE_MILES} mi of SFHA): {'Yes' if at_risk else 'No'}<br>"
            f"Flood zone type: {row['flood_zone_type']}"
        )
        marker = folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            color="#c62828" if at_risk else "#2e7d32",
            fill=True,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=300),
        )
        marker.add_to(at_risk_cluster if at_risk else not_risk_cluster)

    at_risk_layer.add_to(fmap)
    not_risk_layer.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)

    fmap.save(str(config.INTERACTIVE_MAP_PATH))
    print(f"  Saved -> {config.INTERACTIVE_MAP_PATH}")


def main():
    print("=" * 70)
    print("PRODUCING MAPS")
    print("=" * 70)

    boundary, flood_zones, facilities = load_layers()
    make_static_map(boundary, flood_zones, facilities)
    make_interactive_map(boundary, flood_zones, facilities)

    print("\n" + "=" * 70)
    print("MAP PRODUCTION COMPLETE")


if __name__ == "__main__":
    main()
