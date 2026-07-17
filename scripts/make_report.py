"""
Step 5 of the pipeline: generate a short PDF technical report summarizing
the project, methodology, and findings.

Every number that appears under "Key Findings" is read directly from
data/processed/summary_statistics.csv (produced by analysis.py) -- nothing
in this script hardcodes a finding.
"""

import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def load_summary() -> dict:
    if not config.SUMMARY_CSV.exists():
        raise FileNotFoundError(f"{config.SUMMARY_CSV} not found. Run scripts/analysis.py first.")
    df = pd.read_csv(config.SUMMARY_CSV)
    return dict(zip(df["metric"], df["value"]))


def build_findings_bullets(summary: dict) -> list:
    total = int(summary["total_facilities_analyzed"])
    n_at_risk = int(summary["facilities_within_0.5mi_of_sfha"])
    pct_at_risk = summary["pct_facilities_within_0.5mi_of_sfha"]

    category_counts = {
        k.split("::", 1)[1]: int(v)
        for k, v in summary.items()
        if k.startswith("category_count::")
    }
    top_category, top_category_count = max(category_counts.items(), key=lambda kv: kv[1])

    top_near_sfha = {
        k.split("::", 1)[1]: int(v)
        for k, v in summary.items()
        if k.startswith("top_category_near_sfha_rank")
    }
    top_near_sfha_name, top_near_sfha_count = next(iter(top_near_sfha.items()))

    bullets = [
        f"{total:,} EPA-registered environmental facilities in Phoenix were analyzed.",
        f"{n_at_risk:,} facilities ({pct_at_risk:.1f}%) are located within "
        f"{config.BUFFER_DISTANCE_MILES} mile of a FEMA Special Flood Hazard Area (SFHA).",
        f"The most common facility category overall is \"{top_category}\" "
        f"({top_category_count:,} facilities).",
        f"Among facilities within 0.5 mi of a FEMA SFHA, \"{top_near_sfha_name}\" is the most "
        f"frequent category ({top_near_sfha_count:,} facilities).",
    ]
    return bullets


def build_report(summary: dict):
    print(f"Building PDF report -> {config.REPORT_PDF_PATH}")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1Custom", fontSize=16, leading=19, spaceAfter=5, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="H2Custom", fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=2, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="BodyCustom", fontSize=8.3, leading=10.8, spaceAfter=1))
    styles.add(ParagraphStyle(name="SmallItalic", fontSize=7, leading=9, textColor=colors.grey, fontName="Helvetica-Oblique"))

    doc = SimpleDocTemplate(
        str(config.REPORT_PDF_PATH),
        pagesize=LETTER,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )

    story = []

    story.append(Paragraph("Phoenix Environmental &amp; Flood Risk GIS Analysis", styles["H1Custom"]))
    story.append(Paragraph(
        "A screening-level spatial analysis of EPA-registered environmental facilities in "
        "Phoenix, Arizona relative to FEMA-mapped flood hazard zones.",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("Project Goal", styles["H2Custom"]))
    story.append(Paragraph(
        "Identify environmental facilities in Phoenix / Maricopa County that fall within or "
        "near FEMA flood hazard zones, in order to flag facilities that may warrant closer "
        "review of flood-related environmental risk (e.g. contaminant release during a flood event).",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("Data Sources", styles["H2Custom"]))
    source_bullets = [
        "Phoenix city boundary: US Census Bureau TIGER/Line Places, 2023 vintage.",
        "Environmental facilities: EPA Facility Registry Service (FRS), Arizona state-combined "
        "CSV bulk download.",
        "Flood hazard zones: FEMA National Flood Hazard Layer (NFHL), ArcGIS REST MapServer, "
        "Layer 28 (\"Flood Hazard Zones\").",
    ]
    story.append(ListFlowable(
        [ListItem(Paragraph(b, styles["BodyCustom"])) for b in source_bullets],
        bulletType="bullet", leftIndent=12, spaceBefore=0, spaceAfter=0,
    ))
    story.append(Paragraph("Full source details, access dates, and known limitations are documented in data_sources.md.", styles["SmallItalic"]))

    story.append(Paragraph("Methodology", styles["H2Custom"]))
    method_bullets = [
        "Downloaded and cleaned all three source layers; validated/repaired geometries; "
        "dropped facility records with missing or invalid coordinates.",
        "Spatially filtered EPA facilities to those falling within the Phoenix boundary "
        "using point-in-polygon containment (not city-name text matching).",
        f"Reprojected all layers to a projected coordinate system (EPSG:2223, NAD83 / Arizona "
        f"Central State Plane, US feet) and buffered each facility by "
        f"{config.BUFFER_DISTANCE_MILES} mile.",
        "Spatially joined facility buffers against FEMA flood hazard polygons to flag "
        "facilities within the buffer distance of a Special Flood Hazard Area (SFHA).",
        "Aggregated per-facility results into summary counts by category and flood-risk status.",
    ]
    story.append(ListFlowable(
        [ListItem(Paragraph(b, styles["BodyCustom"])) for b in method_bullets],
        bulletType="bullet", leftIndent=12, spaceBefore=0, spaceAfter=0,
    ))

    story.append(Paragraph("Coordinate Reference System (CRS) Notes", styles["H2Custom"]))
    story.append(Paragraph(
        "Buffering and spatial joins were performed in EPSG:2223 (a projected CRS measured in "
        "US feet), not in EPSG:4326 (geographic WGS84, measured in decimal degrees). A degree of "
        "longitude represents a different real-world distance depending on latitude, so a "
        "\"0.5 degree\" buffer would not equal 0.5 miles anywhere, and would be inconsistent "
        "across the study area. All layers are stored in and web-mapped from EPSG:4326, since "
        "Folium/Leaflet require geographic coordinates, but every distance calculation happens "
        "in the projected CRS.",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("Key Findings", styles["H2Custom"]))
    for bullet in build_findings_bullets(summary):
        story.append(Paragraph(f"&bull; {bullet}", styles["BodyCustom"]))

    story.append(Paragraph("Facility Category Breakdown", styles["H2Custom"]))
    category_counts = {
        k.split("::", 1)[1]: int(v)
        for k, v in summary.items()
        if k.startswith("category_count::")
    }
    table_data = [["Facility Category", "Count"]] + [
        [cat, f"{count:,}"] for cat, count in sorted(category_counts.items(), key=lambda kv: -kv[1])
    ]
    table = Table(table_data, colWidths=[3.8 * inch, 1.2 * inch], rowHeights=13)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e4a62")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
    ]))
    story.append(table)

    if config.STATIC_MAP_PATH.exists():
        story.append(Paragraph("Map", styles["H2Custom"]))
        story.append(Image(str(config.STATIC_MAP_PATH), width=2.3 * inch, height=2.3 * 1.35 * inch))
        story.append(Paragraph("Full-resolution static map: maps/final_map.png. Interactive version: maps/interactive_map.html.", styles["SmallItalic"]))

    story.append(Paragraph("Data Quality Notes", styles["H2Custom"]))
    story.append(Paragraph(
        "EPA FRS facility records with missing, zero, or out-of-range latitude/longitude were "
        "dropped prior to analysis (see data_sources.md and clean_data.py for exact counts). "
        "A small number of FEMA flood zone polygons required geometry repair "
        "(self-intersecting rings) before use. Facility \"category\" is derived from the "
        "EPA program acronym(s) associated with each facility (e.g. RCRAINFO, NPDES); "
        "facilities with only minor/state program enrollments fall into an \"Other / "
        "State-Registered\" bucket.",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("Limitations", styles["H2Custom"]))
    story.append(Paragraph(
        "This is a screening-level proximity analysis, not a hydraulic or engineering flood "
        "risk assessment. Proximity to a mapped flood zone does not by itself indicate actual "
        "flood exposure (e.g. elevation, drainage infrastructure, and levees are not modeled). "
        "The EPA FRS facility category classification used here is a simplified relabeling of "
        "raw program-enrollment codes, not an official EPA facility-type taxonomy. FEMA flood "
        "maps are periodically revised and may not reflect the most current conditions.",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("Recommended Next Steps", styles["H2Custom"]))
    next_steps = [
        "Incorporate facility-level hazardous substance/quantity data (e.g. TRI release "
        "volumes) to weight risk beyond simple proximity.",
        "Add a digital elevation model (DEM) to assess relative facility elevation within "
        "flood zones.",
        "Extend the analysis to all of Maricopa County using county GIS parcel/zoning data.",
        "Validate a sample of results in QGIS desktop against the source FEMA FIRM panels.",
    ]
    story.append(ListFlowable(
        [ListItem(Paragraph(s, styles["BodyCustom"])) for s in next_steps],
        bulletType="bullet", leftIndent=12, spaceBefore=0, spaceAfter=0,
    ))

    doc.build(story)
    print(f"  Saved -> {config.REPORT_PDF_PATH}")


def main():
    print("=" * 70)
    print("GENERATING REPORT")
    print("=" * 70)
    summary = load_summary()
    build_report(summary)
    print("\n" + "=" * 70)
    print("REPORT GENERATION COMPLETE")


if __name__ == "__main__":
    main()
