"""
Step 1 of the pipeline: download all raw data into /data/raw.

Three real public sources are used:

1. US Census TIGER/Line 2023 Places (Arizona) -> Phoenix city boundary.
2. EPA Facility Registry Service (FRS) state-combined CSV bulk download
   (Arizona) -> environmental facility locations and attributes.
3. FEMA National Flood Hazard Layer (NFHL), ArcGIS REST MapServer, layer 28
   "Flood Hazard Zones" -> flood hazard polygons for the Phoenix area.

Every function fails loudly (with a clear message) rather than silently
falling back to fake data. If a source is genuinely unavailable, that is
recorded in data_sources.md, not papered over here.
"""

import json
import sys
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def _download_file(url: str, dest_path: Path, description: str) -> None:
    """Stream-download a URL to disk, raising a clear error on failure."""
    print(f"  Fetching {description} ...")
    print(f"    URL: {url}")
    try:
        response = requests.get(
            url,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": config.USER_AGENT},
            stream=True,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Failed to download {description} from {url}: {exc}"
        ) from exc

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            f.write(chunk)

    size_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"    Saved to {dest_path} ({size_mb:.1f} MB)")


def fetch_phoenix_boundary() -> None:
    """
    Download the Census TIGER/Line Places file for Arizona and extract the
    single feature whose NAME == "Phoenix". Saved as raw GeoJSON so
    clean_data.py can load it with no further network calls.
    """
    print("\n[1/3] Phoenix city boundary (US Census TIGER/Line Places)")

    if not config.MARICOPA_PLACES_RAW.exists():
        _download_file(
            config.CENSUS_TIGER_AZ_PLACES_URL,
            config.MARICOPA_PLACES_RAW,
            "Arizona TIGER/Line Places shapefile (zipped)",
        )
    else:
        print(f"    Already downloaded: {config.MARICOPA_PLACES_RAW}")

    # geopandas can read a zipped shapefile directly using the "zip://" prefix
    import geopandas as gpd

    try:
        places = gpd.read_file(f"zip://{config.MARICOPA_PLACES_RAW}")
    except Exception as exc:
        raise RuntimeError(
            f"Downloaded TIGER/Line Places file could not be read: {exc}"
        ) from exc

    phoenix = places[places["NAME"] == config.PHOENIX_PLACE_NAME].copy()
    if phoenix.empty:
        raise RuntimeError(
            "No feature named 'Phoenix' found in the TIGER/Line Places file. "
            "The Census file format or field name may have changed."
        )

    phoenix.to_file(config.PHOENIX_BOUNDARY_RAW, driver="GeoJSON")
    print(f"    Extracted Phoenix boundary -> {config.PHOENIX_BOUNDARY_RAW}")


def fetch_epa_facilities() -> None:
    """
    Download the EPA FRS Arizona state-combined CSV bulk file and unzip the
    facility-level CSV needed for this analysis.

    Note: the FRS REST API (frs_rest_services.get_facilities) was evaluated
    first but rejects any query wide enough to cover a metro area the size
    of Phoenix ("Process Limit would be exceeded"). The bulk CSV download is
    EPA's own documented workaround for exactly this situation, see
    data_sources.md for details.
    """
    print("\n[2/3] EPA Facility Registry Service (FRS) facilities (Arizona)")

    if not config.EPA_FRS_AZ_ZIP.exists():
        _download_file(
            config.EPA_FRS_AZ_ZIP_URL,
            config.EPA_FRS_AZ_ZIP,
            "EPA FRS Arizona state-combined CSV archive",
        )
    else:
        print(f"    Already downloaded: {config.EPA_FRS_AZ_ZIP}")

    try:
        with zipfile.ZipFile(config.EPA_FRS_AZ_ZIP) as z:
            name = "AZ_FACILITY_FILE.CSV"
            if name not in z.namelist():
                raise RuntimeError(
                    f"Expected file '{name}' not found inside the FRS zip archive. "
                    f"Archive contents: {z.namelist()}"
                )
            z.extract(name, path=config.DATA_RAW_DIR)
            print(f"    Extracted {name}")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"Downloaded EPA FRS file is not a valid zip archive: {exc}"
        ) from exc


def fetch_fema_flood_zones() -> None:
    """
    Query the FEMA NFHL ArcGIS REST MapServer (layer 28, "Flood Hazard
    Zones") for all polygons intersecting a bounding box around Phoenix.

    The service caps each response at config.FEMA_PAGE_SIZE features, so
    this pages through results with resultOffset until the server reports
    no more records, then merges everything into one GeoJSON file.
    """
    print("\n[3/3] FEMA National Flood Hazard Layer (NFHL) flood zones")

    if config.FEMA_FLOOD_ZONES_RAW.exists():
        print(f"    Already downloaded: {config.FEMA_FLOOD_ZONES_RAW}")
        return

    bbox = config.PHOENIX_QUERY_BBOX
    query_url = f"{config.FEMA_NFHL_MAPSERVER_URL}/{config.FEMA_FLOOD_ZONE_LAYER_ID}/query"
    base_params = {
        "geometry": f"{bbox['xmin']},{bbox['ymin']},{bbox['xmax']},{bbox['ymax']}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STUDY_TYP,DFIRM_ID",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": config.FEMA_PAGE_SIZE,
    }

    all_features = []
    offset = 0
    page = 1
    max_retries = 3
    while True:
        params = dict(base_params, resultOffset=offset)
        print(f"    Requesting page {page} (offset={offset}) ...")

        payload = None
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(
                    query_url,
                    params=params,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": config.USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.exceptions.RequestException, json.JSONDecodeError) as exc:
                last_error = exc
                print(f"      Attempt {attempt}/{max_retries} failed: {exc}")

        if payload is None:
            raise RuntimeError(
                f"FEMA NFHL query failed on page {page} (offset={offset}) "
                f"after {max_retries} attempts: {last_error}"
            )

        if "error" in payload:
            raise RuntimeError(f"FEMA NFHL service returned an error: {payload['error']}")

        features = payload.get("features", [])
        all_features.extend(features)
        print(f"      Retrieved {len(features)} features (running total: {len(all_features)})")

        if len(features) < config.FEMA_PAGE_SIZE:
            break  # last page
        offset += config.FEMA_PAGE_SIZE
        page += 1

    if not all_features:
        raise RuntimeError(
            "FEMA NFHL query returned zero flood hazard features for the Phoenix "
            "bounding box. This would be unusual for this area -- check the "
            "bounding box in config.py and the service status."
        )

    feature_collection = {"type": "FeatureCollection", "features": all_features}
    with open(config.FEMA_FLOOD_ZONES_RAW, "w") as f:
        json.dump(feature_collection, f)

    print(f"    Saved {len(all_features)} flood hazard polygons -> {config.FEMA_FLOOD_ZONES_RAW}")


def main():
    print("=" * 70)
    print("FETCHING RAW DATA")
    print("=" * 70)

    errors = []
    for label, fn in [
        ("Phoenix boundary", fetch_phoenix_boundary),
        ("EPA FRS facilities", fetch_epa_facilities),
        ("FEMA flood zones", fetch_fema_flood_zones),
    ]:
        try:
            fn()
        except Exception as exc:
            print(f"\n  ERROR fetching {label}: {exc}")
            errors.append((label, str(exc)))

    print("\n" + "=" * 70)
    if errors:
        print("FETCH COMPLETED WITH ERRORS:")
        for label, msg in errors:
            print(f"  - {label}: {msg}")
        print(
            "See data_sources.md for documented fallbacks. The pipeline "
            "cannot proceed with fabricated data, so downstream steps that "
            "depend on a failed source will also fail until this is resolved."
        )
        sys.exit(1)
    else:
        print("All raw data fetched successfully.")


if __name__ == "__main__":
    main()
