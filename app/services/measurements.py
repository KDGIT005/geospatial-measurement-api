"""Measurement calculations for geospatial features.

Every measurement follows the same flow:
1. Determine if the geometry type is measurable (Polygon → area, Line → length).
2. Reproject the geometry to the correct UTM zone (always, regardless of source CRS).
3. Compute the projected value using Shapely on the UTM geometry.
4. Compute a geodesic cross-check using pyproj.Geod on the WGS84 geometry.
5. Return both values so reviewers can verify accuracy.

The geodesic value uses the WGS84 ellipsoid and is the "gold standard"
for accuracy, but the projected UTM value is simpler to explain and is
the primary result.
"""

import logging

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import orient

from app.services.crs import reproject_geometry, reproject_to_4326, select_utm_crs

logger = logging.getLogger(__name__)

# WGS84 ellipsoid for geodesic calculations
_geod = Geod(ellps="WGS84")

# Geometry types that produce area measurements
AREA_TYPES = {"Polygon", "MultiPolygon"}

# Geometry types that produce length measurements
LENGTH_TYPES = {"LineString", "MultiLineString"}

# Geometry types that are valid but don't need measurement
NO_MEASUREMENT_TYPES = {"Point", "MultiPoint"}

# Everything else is unsupported
UNSUPPORTED_NOTE = "Geometry type not supported for measurement"


def compute_measurement(
    geojson: dict,
    source_crs: str,
) -> dict:
    """Compute area or length for a single GeoJSON geometry.

    Returns a dict with keys matching the Feature model columns:
    - measurement_type, measurement_value, measurement_unit
    - projected_crs, geodesic_value, method
    - is_supported, note

    Handles each geometry independently — one bad geometry never crashes
    the whole file.
    """
    try:
        geom = shape(geojson)
    except Exception as exc:
        logger.warning("Failed to parse geometry: %s", exc)
        return _unsupported_result("Failed to parse geometry")

    if geom is None or geom.is_empty:
        return _unsupported_result("Null or empty geometry")

    geom_type = geom.geom_type

    # Points: supported but no measurement needed
    if geom_type in NO_MEASUREMENT_TYPES:
        return {
            "measurement_type": None,
            "measurement_value": None,
            "measurement_unit": None,
            "projected_crs": None,
            "geodesic_value": None,
            "method": None,
            "is_supported": True,
            "note": f"No measurement required for {geom_type} geometries",
        }

    # Unsupported types (GeometryCollection, LinearRing, etc.)
    if geom_type not in AREA_TYPES and geom_type not in LENGTH_TYPES:
        return _unsupported_result(UNSUPPORTED_NOTE)

    # --- Measurable geometry: Polygon/MultiPolygon or LineString/MultiLineString ---
    try:
        return _measure(geom, geom_type, source_crs)
    except Exception as exc:
        logger.warning("Measurement failed for %s: %s", geom_type, exc)
        return _unsupported_result(f"Measurement failed: {exc}")


def _measure(geom, geom_type: str, source_crs: str) -> dict:
    """Project to UTM, compute, and cross-check with geodesic."""

    # 1. Select UTM zone from centroid
    utm_crs = select_utm_crs(geom, source_crs)

    # 2. Reproject to UTM
    geom_utm = reproject_geometry(geom, source_crs, utm_crs)

    # 3. Get WGS84 geometry for geodesic cross-check
    geom_4326 = reproject_to_4326(geom, source_crs)

    if geom_type in AREA_TYPES:
        return _measure_area(geom_utm, geom_4326, utm_crs)
    return _measure_length(geom_utm, geom_4326, utm_crs)


def _measure_area(geom_utm, geom_4326, utm_crs: str) -> dict:
    """Compute area in m² using projected UTM + geodesic cross-check."""

    # Projected area from shapely (in metres²)
    projected_area = geom_utm.area

    # Geodesic area from pyproj (returns negative for counter-clockwise,
    # so take absolute value).
    # pyproj Geod requires exterior to be CCW and holes to be CW
    # so holes are correctly subtracted.
    oriented_4326 = orient(geom_4326, sign=1.0)
    geodesic_area, _ = _geod.geometry_area_perimeter(oriented_4326)
    geodesic_area = abs(geodesic_area)

    return {
        "measurement_type": "area",
        "measurement_value": round(projected_area, 2),
        "measurement_unit": "square_meters",
        "projected_crs": utm_crs,
        "geodesic_value": round(geodesic_area, 2),
        "method": "projected_utm",
        "is_supported": True,
        "note": None,
    }


def _measure_length(geom_utm, geom_4326, utm_crs: str) -> dict:
    """Compute length in metres using projected UTM + geodesic cross-check."""

    # Projected length from shapely (in metres)
    projected_length = geom_utm.length

    # Geodesic length from pyproj
    geodesic_length = _geod.geometry_length(geom_4326)

    return {
        "measurement_type": "length",
        "measurement_value": round(projected_length, 2),
        "measurement_unit": "meters",
        "projected_crs": utm_crs,
        "geodesic_value": round(geodesic_length, 2),
        "method": "projected_utm",
        "is_supported": True,
        "note": None,
    }


def _unsupported_result(note: str) -> dict:
    """Return a measurement result dict for unsupported geometries."""
    return {
        "measurement_type": None,
        "measurement_value": None,
        "measurement_unit": None,
        "projected_crs": None,
        "geodesic_value": None,
        "method": None,
        "is_supported": False,
        "note": note,
    }
