"""
Run the entire Phoenix Environmental & Flood Risk GIS Analysis pipeline
end-to-end:

  1. fetch_data.py   -- download raw data
  2. clean_data.py   -- clean/standardize/filter to Phoenix
  3. analysis.py     -- buffer + spatial join + summary statistics
  4. make_maps.py    -- static PNG map + interactive Folium map
  5. make_report.py  -- PDF technical report

Usage:
    python run_pipeline.py
"""

import subprocess
import sys
import time
from pathlib import Path

import config

PIPELINE_STEPS = [
    ("Fetching raw data", "scripts/fetch_data.py"),
    ("Cleaning data", "scripts/clean_data.py"),
    ("Running spatial analysis", "scripts/analysis.py"),
    ("Producing maps", "scripts/make_maps.py"),
    ("Generating report", "scripts/make_report.py"),
]


def run_step(label: str, script_path: str) -> None:
    print("\n" + "#" * 70)
    print(f"# {label}  ({script_path})")
    print("#" * 70)
    result = subprocess.run([sys.executable, script_path], cwd=str(config.PROJECT_ROOT))
    if result.returncode != 0:
        raise SystemExit(
            f"\nPipeline stopped: '{script_path}' exited with code {result.returncode}.\n"
            f"Fix the error above and re-run python run_pipeline.py."
        )


def main():
    start = time.time()
    print("=" * 70)
    print("PHOENIX ENVIRONMENTAL & FLOOD RISK GIS ANALYSIS -- FULL PIPELINE")
    print("=" * 70)

    for label, script_path in PIPELINE_STEPS:
        run_step(label, script_path)

    elapsed = time.time() - start
    print("\n" + "=" * 70)
    print(f"PIPELINE COMPLETE in {elapsed:.1f} seconds")
    print("=" * 70)
    print("\nGenerated outputs:")
    outputs = [
        config.PHOENIX_BOUNDARY_CLEAN,
        config.EPA_FACILITIES_CLEAN,
        config.FEMA_FLOOD_ZONES_CLEAN,
        config.FACILITIES_ANALYZED,
        config.FACILITY_BUFFERS,
        config.SUMMARY_CSV,
        config.STATIC_MAP_PATH,
        config.INTERACTIVE_MAP_PATH,
        config.REPORT_PDF_PATH,
    ]
    for path in outputs:
        status = "OK" if Path(path).exists() else "MISSING"
        print(f"  [{status:>7}] {path}")

    print(
        "\nOpen maps/interactive_map.html in a browser, maps/final_map.png for the "
        "static map, and reports/gis_summary.pdf for the written summary."
    )


if __name__ == "__main__":
    main()
