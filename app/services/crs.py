"""CRS detection and projected CRS selection.

The core rule: **never measure area or length in geographic (degree) coordinates.**

Strategy for every feature:
1. Get the feature's centroid in EPSG:4326.
2. Pick the UTM zone: zone = floor((lon + 180) / 6) + 1, clamped to [1, 60].
3. Northern hemisphere → EPSG:326{zone:02d}, southern → EPSG:327{zone:02d}.
4. Always reproject to the selected UTM CRS, even if the source is already
   projected (e.g. Web Mercator is metre-based but distorts area).

Transformer instances are cached per CRS pair for performance.
"""

import logging
import warnings
from functools import lru_cache
from math import floor

from pyproj import CRS, Transformer
from shapely.ops import transform

logger = logging.getLogger(__name__)


def _apply_transform(transformer: Transformer, geom):
    """Apply coordinate transformation while suppressing Shapely deprecation warning."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", category=DeprecationWarning, message=".*shapely.ops.transform.*"
        )
        return transform(transformer.transform, geom)


def get_utm_epsg(lon: float, lat: float) -> int:
    """Return the EPSG code for the UTM zone covering the given lon/lat.

    zone = floor((lon + 180) / 6) + 1, clamped to [1, 60].
    Northern hemisphere: 32600 + zone, southern: 32700 + zone.
    """
    zone = floor((lon + 180) / 6) + 1
    zone = max(1, min(60, zone))

    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


@lru_cache(maxsize=64)
def _get_transformer(src_epsg: str, dst_epsg: str) -> Transformer:
    """Create and cache a pyproj Transformer between two CRS strings.

    always_xy=True ensures coordinate order is (lon, lat) / (x, y),
    matching shapely's convention.
    """
    src_crs = CRS(src_epsg)
    dst_crs = CRS(dst_epsg)
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def reproject_to_4326(geom, source_crs: str):
    """Reproject a geometry to EPSG:4326 so we can get its centroid lon/lat.

    If the source is already EPSG:4326, returns the geometry unchanged.
    """
    if _is_4326(source_crs):
        return geom

    transformer = _get_transformer(source_crs, "EPSG:4326")
    return _apply_transform(transformer, geom)


def _is_4326(crs_string: str) -> bool:
    """Check if a CRS string represents EPSG:4326."""
    try:
        crs = CRS(crs_string)
        return crs.to_epsg() == 4326
    except Exception:
        return False


def select_utm_crs(geom, source_crs: str) -> str:
    """Pick the UTM CRS for a geometry based on its centroid.

    Steps:
    1. Reproject to WGS84 if not already.
    2. Get centroid lon/lat.
    3. Compute UTM zone and return the EPSG string.
    """
    geom_4326 = reproject_to_4326(geom, source_crs)
    centroid = geom_4326.centroid

    lon = centroid.x
    lat = centroid.y

    epsg_code = get_utm_epsg(lon, lat)
    return f"EPSG:{epsg_code}"


def reproject_geometry(geom, source_crs: str, target_crs: str):
    """Reproject a shapely geometry from source_crs to target_crs.

    Returns the reprojected geometry.
    """
    transformer = _get_transformer(source_crs, target_crs)
    return _apply_transform(transformer, geom)
