"""File ingestion service: save, validate, extract, and read geospatial features.

Handles:
- Stream-checking upload size against the configured limit
- Zip security (zip-slip, zip-bomb, hidden files)
- Finding .shp inside subfolders of a zip
- Reading KML (via pyogrio, with lxml fallback) and Shapefile
- Sanitising feature properties (numpy types, NaN, dates → JSON-safe)
"""

import logging
import math
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import shapely
from shapely.geometry import mapping

from app.config import settings
from app.core.exceptions import (
    FileTooLargeError,
    InvalidGeospatialFileError,
    MissingCRSError,
    UnsupportedFileTypeError,
    ZipSecurityError,
)

logger = logging.getLogger(__name__)

# Supported upload extensions
ALLOWED_EXTENSIONS = {".kml", ".zip"}

# Files and directories to ignore inside zips
IGNORED_PREFIXES = {"__MACOSX", "."}


def detect_file_type(filename: str) -> str:
    """Return 'kml' or 'shapefile' based on the file extension.

    Raises UnsupportedFileTypeError if the extension is not .kml or .zip.
    """
    ext = Path(filename).suffix.lower()
    if ext == ".kml":
        return "kml"
    if ext == ".zip":
        return "shapefile"
    raise UnsupportedFileTypeError(f"Unsupported file extension: '{ext}'. Use .kml or .zip.")


async def save_upload_stream(upload_file, dest_path: Path) -> int:
    """Stream an uploaded file to disk, enforcing the size limit.

    Returns the total number of bytes written.
    Raises FileTooLargeError if the file exceeds MAX_UPLOAD_SIZE.
    """
    chunk_size = 64 * 1024  # 64 KB chunks
    total = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.MAX_UPLOAD_SIZE:
                raise FileTooLargeError(
                    f"File exceeds maximum upload size of "
                    f"{settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
                )
            f.write(chunk)
    return total


def _is_ignored(name: str) -> bool:
    """Return True for hidden files and __MACOSX entries."""
    parts = Path(name).parts
    return any(part.startswith(".") or part in IGNORED_PREFIXES for part in parts)


def validate_and_extract_zip(zip_path: Path, extract_dir: Path) -> Path:
    """Validate a zip for security issues and extract it.

    Returns the path to the single .shp file found inside.

    Security checks:
    - Zip-slip: reject entries with path traversal (.. or absolute paths)
    - Zip-bomb: cap total uncompressed size and entry count
    - Ignore __MACOSX and hidden files
    - Require exactly one .shp file

    The .shp can be in a subfolder.
    """
    if not zipfile.is_zipfile(zip_path):
        raise InvalidGeospatialFileError("File is not a valid zip archive.")

    with zipfile.ZipFile(zip_path, "r") as zf:
        entries = zf.infolist()

        # --- Zip-bomb: entry count check ---
        if len(entries) > settings.MAX_ZIP_ENTRIES:
            raise ZipSecurityError(
                f"Zip contains {len(entries)} entries, exceeding the limit of "
                f"{settings.MAX_ZIP_ENTRIES}."
            )

        # --- Zip-slip + zip-bomb (size) + find .shp ---
        total_uncompressed = 0
        shp_files: list[str] = []

        for info in entries:
            # Zip-slip: reject path traversal
            member_path = Path(info.filename)
            if info.filename.startswith("/") or ".." in member_path.parts:
                raise ZipSecurityError(f"Zip entry '{info.filename}' contains path traversal.")

            # Skip ignored entries
            if _is_ignored(info.filename) or info.is_dir():
                continue

            total_uncompressed += info.file_size
            if total_uncompressed > settings.MAX_ZIP_UNCOMPRESSED_SIZE:
                raise ZipSecurityError(
                    f"Zip uncompressed size exceeds "
                    f"{settings.MAX_ZIP_UNCOMPRESSED_SIZE // (1024 * 1024)} MB limit."
                )

            if info.filename.lower().endswith(".shp"):
                shp_files.append(info.filename)

        if len(shp_files) == 0:
            raise InvalidGeospatialFileError("Zip does not contain a .shp file.")
        if len(shp_files) > 1:
            raise InvalidGeospatialFileError(
                f"Zip contains multiple .shp files ({', '.join(shp_files)}). "
                f"Please upload a zip with exactly one Shapefile."
            )

        # Extract only non-ignored entries
        for info in entries:
            if not _is_ignored(info.filename) and not info.is_dir():
                zf.extract(info, extract_dir)

    shp_path = extract_dir / shp_files[0]

    # Verify required companion files exist alongside the .shp
    stem = shp_path.stem
    parent = shp_path.parent
    for required_ext in [".shx", ".dbf"]:
        companion = parent / f"{stem}{required_ext}"
        if not companion.exists():
            # Case-insensitive check
            found = any(f.name.lower() == f"{stem.lower()}{required_ext}" for f in parent.iterdir())
            if not found:
                raise InvalidGeospatialFileError(
                    f"Shapefile is missing required companion file: {stem}{required_ext}"
                )

    return shp_path


def _sanitise_value(val: Any) -> Any:
    """Convert a single value to something JSON-safe.

    Handles numpy scalars, NaN/Inf, dates, and bytes.
    """
    if val is None:
        return None

    # numpy scalar → Python native
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.ndarray):
        return val.tolist()

    # Python float NaN/Inf
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None

    # datetime-like → ISO string
    if hasattr(val, "isoformat"):
        return val.isoformat()

    # bytes → decode
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")

    return val


def sanitise_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Make all property values JSON-serialisable."""
    return {k: _sanitise_value(v) for k, v in props.items()}


def _has_kml_driver() -> bool:
    """Check if pyogrio has a working KML or LIBKML driver."""
    drivers = pyogrio.list_drivers()
    return "KML" in drivers or "LIBKML" in drivers


def _read_kml_pyogrio(kml_path: Path) -> list[dict]:
    """Read all layers from a KML file using pyogrio/geopandas.

    Returns a flat list of feature dicts with a global feature_index.
    KML is always EPSG:4326 by specification.
    """
    # List all layers in the KML
    layers = pyogrio.list_layers(kml_path)
    features: list[dict] = []
    global_index = 0

    for layer_name, _ in layers:
        try:
            gdf = gpd.read_file(kml_path, layer=layer_name, engine="pyogrio")
        except Exception as exc:
            logger.warning("Failed to read KML layer '%s': %s", layer_name, exc)
            continue

        if gdf.empty:
            continue

        for _, row in gdf.iterrows():
            geom = row.geometry
            props = {col: row[col] for col in gdf.columns if col != gdf.geometry.name}
            features.append(
                _build_feature_dict(geom, sanitise_properties(props), global_index, "EPSG:4326")
            )
            global_index += 1

    return features


def _read_kml_lxml(kml_path: Path) -> list[dict]:
    """Fallback KML reader using lxml to parse the raw XML.

    Extracts Placemark geometries as GeoJSON. Limited but works without
    the GDAL KML driver.
    """
    from lxml import etree

    tree = etree.parse(str(kml_path))

    root = tree.getroot()

    # Handle default namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    placemarks = root.findall(f".//{ns}Placemark")
    features: list[dict] = []

    geom_tags = ["Point", "LineString", "Polygon", "MultiGeometry"]

    for idx, pm in enumerate(placemarks):
        # Extract name as a property
        name_el = pm.find(f"{ns}Name") or pm.find(f"{ns}name")
        props: dict[str, Any] = {}
        if name_el is not None and name_el.text:
            props["name"] = name_el.text

        # Extract description
        desc_el = pm.find(f"{ns}description") or pm.find(f"{ns}Description")
        if desc_el is not None and desc_el.text:
            props["description"] = desc_el.text

        # Find geometry element
        geom = None
        for tag in geom_tags:
            geom_el = pm.find(f".//{ns}{tag}")
            if geom_el is not None:
                geom = _parse_kml_geometry(geom_el, ns)
                break

        features.append(_build_feature_dict(geom, props, idx, "EPSG:4326"))

    return features


def _parse_kml_geometry(el, ns: str):
    """Parse a KML geometry element into a Shapely geometry.

    Drops Z values (2D measurements only).
    """
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag

    if tag == "Point":
        coords_text = el.find(f"{ns}coordinates").text.strip()
        parts = coords_text.split(",")
        return shapely.Point(float(parts[0]), float(parts[1]))

    if tag == "LineString":
        coords_text = el.find(f"{ns}coordinates").text.strip()
        coords = _parse_coord_string(coords_text)
        return shapely.LineString(coords)

    if tag == "Polygon":
        outer_el = el.find(f"{ns}outerBoundaryIs/{ns}LinearRing/{ns}coordinates")
        if outer_el is None:
            return None
        outer = _parse_coord_string(outer_el.text.strip())
        holes = []
        for inner_el in el.findall(f"{ns}innerBoundaryIs/{ns}LinearRing/{ns}coordinates"):
            holes.append(_parse_coord_string(inner_el.text.strip()))
        return shapely.Polygon(outer, holes)

    if tag == "MultiGeometry":
        parts = []
        for child in el:
            g = _parse_kml_geometry(child, ns)
            if g is not None:
                parts.append(g)
        if parts:
            return shapely.GeometryCollection(parts)
        return None

    return None


def _parse_coord_string(text: str) -> list[tuple[float, float]]:
    """Parse a KML coordinates string into 2D (lon, lat) tuples."""
    coords = []
    for token in text.split():
        parts = token.split(",")
        coords.append((float(parts[0]), float(parts[1])))
    return coords


def _drop_z(geom):
    """Remove Z coordinates from a geometry (2D measurements only)."""
    if geom is None or geom.is_empty:
        return geom
    if shapely.has_z(geom):
        return shapely.force_2d(geom)
    return geom


def _build_feature_dict(geom, properties: dict, index: int, crs: str) -> dict:
    """Build a standardised feature dict from a geometry and properties."""
    geom = _drop_z(geom)

    if geom is None or geom.is_empty:
        return {
            "feature_index": index,
            "geometry_type": None,
            "geometry": None,
            "crs": crs,
            "properties": properties,
            "is_supported": False,
            "is_valid": None,
            "note": "Null or empty geometry",
        }

    geojson = mapping(geom)
    return {
        "feature_index": index,
        "geometry_type": geom.geom_type,
        "geometry": geojson,
        "crs": crs,
        "properties": properties,
        "is_supported": True,
        "is_valid": geom.is_valid,
        "note": None if geom.is_valid else "Invalid geometry (e.g. self-intersection)",
    }


def read_kml(kml_path: Path) -> tuple[list[dict], str]:
    """Read features from a KML file.

    Returns (features, crs). KML is always EPSG:4326.
    Uses pyogrio if the KML driver is available, otherwise falls back to lxml.
    """
    if kml_path.stat().st_size == 0:
        raise InvalidGeospatialFileError("KML file is empty.")

    crs = "EPSG:4326"

    try:
        if _has_kml_driver():
            logger.info("Reading KML with pyogrio (KML driver available)")
            try:
                features = _read_kml_pyogrio(kml_path)
            except Exception as exc:
                logger.warning("pyogrio failed to parse KML, trying lxml: %s", exc)
                features = _read_kml_lxml(kml_path)
        else:
            logger.info("KML driver not available, falling back to lxml parser")
            features = _read_kml_lxml(kml_path)
    except InvalidGeospatialFileError:
        raise
    except Exception as exc:
        raise InvalidGeospatialFileError(f"Failed to parse KML: {exc}") from exc

    if not features:
        raise InvalidGeospatialFileError("KML file contains no features.")

    return features, crs


def read_shapefile(shp_path: Path) -> tuple[list[dict], str]:
    """Read features from a Shapefile.

    Returns (features, crs_string).
    Raises MissingCRSError if the .prj is missing or unparseable.
    """
    # Check for .prj file
    prj_path = shp_path.with_suffix(".prj")
    prj_exists = prj_path.exists()
    if not prj_exists:
        # Case-insensitive check
        prj_exists = any(
            f.name.lower() == f"{shp_path.stem.lower()}.prj" for f in shp_path.parent.iterdir()
        )

    try:
        gdf = gpd.read_file(shp_path, engine="pyogrio")
    except Exception as exc:
        raise InvalidGeospatialFileError(f"Failed to read Shapefile: {exc}") from exc

    # Determine CRS
    if gdf.crs is None:
        if not prj_exists:
            raise MissingCRSError(
                "Shapefile has no .prj file. Cannot determine CRS. "
                "Please include a valid .prj file in the zip."
            )
        raise MissingCRSError(
            "Shapefile .prj file is present but could not be parsed. "
            "Ensure it contains a valid coordinate reference system definition."
        )

    # Try to get an EPSG code; fall back to the CRS name or WKT
    epsg = gdf.crs.to_epsg()
    if epsg is not None:
        crs_string = f"EPSG:{epsg}"
    else:
        crs_string = gdf.crs.to_wkt()
        logger.info("CRS has no EPSG code, storing WKT: %s...", crs_string[:80])

    # Extract features
    features: list[dict] = []
    for idx, row in gdf.iterrows():
        geom = row.geometry
        props = {col: row[col] for col in gdf.columns if col != gdf.geometry.name}
        features.append(_build_feature_dict(geom, sanitise_properties(props), idx, crs_string))

    if not features:
        raise InvalidGeospatialFileError("Shapefile contains no features.")

    return features, crs_string


class IngestContext:
    """Context manager that creates a temporary directory for processing
    and ensures cleanup even if processing fails."""

    def __init__(self):
        self.temp_dir: Path | None = None

    def __enter__(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="geospatial_"))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        return False  # Don't suppress exceptions
