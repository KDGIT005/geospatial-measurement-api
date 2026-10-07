"""Shared test fixtures.

All sample files are generated programmatically — no binary fixtures.
Each test gets a fresh in-memory SQLite database.
"""

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """Provide a DB session connected to the in-memory database."""
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine):
    """FastAPI TestClient wired to the test database."""
    app = create_app()
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# KML generators
# ---------------------------------------------------------------------------


def _kml_polygon_coords(coords: list[tuple[float, float]]) -> str:
    """Format coordinates as a KML coordinate string (lon,lat,0)."""
    return " ".join(f"{lon},{lat},0" for lon, lat in coords)


def make_kml_string(
    placemarks: list[dict],
    name: str = "TestKML",
) -> str:
    """Build a KML string from a list of placemarks.

    Each placemark dict has:
    - 'name': str
    - 'geometry_type': 'Point' | 'LineString' | 'Polygon'
    - 'coordinates': list of (lon, lat) tuples
    - For Polygon, 'coordinates' is the outer ring.
    - Optional 'inner_rings': list of list of (lon, lat) tuples for holes.
    """
    placemark_xml = []
    for pm in placemarks:
        geom_xml = _build_kml_geometry(pm)
        pm_name = pm.get("name", "Feature")
        placemark_xml.append(f"<Placemark><name>{pm_name}</name>{geom_xml}</Placemark>")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2">'
        f"<Document><name>{name}</name>" + "".join(placemark_xml) + "</Document></kml>"
    )


def _build_kml_geometry(pm: dict) -> str:
    """Build a KML geometry element from a placemark dict."""
    geom_type = pm["geometry_type"]
    coords = pm.get("coordinates", [])

    if geom_type == "Point":
        lon, lat = coords[0]
        return f"<Point><coordinates>{lon},{lat},0</coordinates></Point>"

    if geom_type == "LineString":
        coord_str = _kml_polygon_coords(coords)
        return f"<LineString><coordinates>{coord_str}</coordinates></LineString>"

    if geom_type == "Polygon":
        outer = _kml_polygon_coords(coords)
        inner_xml = ""
        for hole in pm.get("inner_rings", []):
            hole_str = _kml_polygon_coords(hole)
            inner_xml += (
                f"<innerBoundaryIs><LinearRing>"
                f"<coordinates>{hole_str}</coordinates>"
                f"</LinearRing></innerBoundaryIs>"
            )
        return (
            f"<Polygon>"
            f"<outerBoundaryIs><LinearRing>"
            f"<coordinates>{outer}</coordinates>"
            f"</LinearRing></outerBoundaryIs>"
            f"{inner_xml}"
            f"</Polygon>"
        )

    return ""


def make_square_kml(center_lon: float, center_lat: float, side_deg: float) -> str:
    """Create a KML with a single square polygon.

    side_deg is the approximate side length in degrees.
    """
    half = side_deg / 2
    coords = [
        (center_lon - half, center_lat - half),
        (center_lon + half, center_lat - half),
        (center_lon + half, center_lat + half),
        (center_lon - half, center_lat + half),
        (center_lon - half, center_lat - half),  # close ring
    ]
    return make_kml_string(
        [
            {
                "name": "Square",
                "geometry_type": "Polygon",
                "coordinates": coords,
            }
        ]
    )


def make_polygon_with_hole_kml(
    center_lon: float,
    center_lat: float,
    outer_half_deg: float,
    hole_half_deg: float,
) -> str:
    """Create a KML with a polygon that has a rectangular hole."""
    outer = [
        (center_lon - outer_half_deg, center_lat - outer_half_deg),
        (center_lon + outer_half_deg, center_lat - outer_half_deg),
        (center_lon + outer_half_deg, center_lat + outer_half_deg),
        (center_lon - outer_half_deg, center_lat + outer_half_deg),
        (center_lon - outer_half_deg, center_lat - outer_half_deg),
    ]
    hole = [
        (center_lon - hole_half_deg, center_lat - hole_half_deg),
        (center_lon + hole_half_deg, center_lat - hole_half_deg),
        (center_lon + hole_half_deg, center_lat + hole_half_deg),
        (center_lon - hole_half_deg, center_lat + hole_half_deg),
        (center_lon - hole_half_deg, center_lat - hole_half_deg),
    ]
    return make_kml_string(
        [
            {
                "name": "PolygonWithHole",
                "geometry_type": "Polygon",
                "coordinates": outer,
                "inner_rings": [hole],
            }
        ]
    )


# ---------------------------------------------------------------------------
# Shapefile generators (zipped)
# ---------------------------------------------------------------------------


def make_zipped_shapefile(
    geometries: list,
    properties_list: list[dict] | None = None,
    crs: str = "EPSG:4326",
    include_prj: bool = True,
) -> bytes:
    """Build a zipped shapefile in memory from a list of Shapely geometries.

    Returns the zip file as bytes.
    """
    import tempfile

    if properties_list is None:
        properties_list = [{"id": i} for i in range(len(geometries))]

    gdf = gpd.GeoDataFrame(properties_list, geometry=geometries, crs=crs)

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = Path(tmpdir) / "data.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio")

        # If we want to test missing .prj, remove it
        if not include_prj:
            prj_file = shp_path.with_suffix(".prj")
            if prj_file.exists():
                prj_file.unlink()

        # Zip all shapefile components
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in Path(tmpdir).iterdir():
                if f.is_file():
                    zf.write(f, f.name)

        return buf.getvalue()


def make_zipped_shapefile_in_subfolder(
    geometries: list,
    properties_list: list[dict] | None = None,
    crs: str = "EPSG:4326",
) -> bytes:
    """Build a zipped shapefile where the .shp is inside a subfolder."""
    import tempfile

    if properties_list is None:
        properties_list = [{"id": i} for i in range(len(geometries))]

    gdf = gpd.GeoDataFrame(properties_list, geometry=geometries, crs=crs)

    with tempfile.TemporaryDirectory() as tmpdir:
        sub = Path(tmpdir) / "subfolder"
        sub.mkdir()
        shp_path = sub / "data.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sub.iterdir():
                if f.is_file():
                    zf.write(f, f"subfolder/{f.name}")

        return buf.getvalue()


# ---------------------------------------------------------------------------
# Convenience geometry builders
# ---------------------------------------------------------------------------


def equator_1km_square() -> Polygon:
    """A ~1 km × 1 km square near the equator (lon=0, lat=0).

    1 degree of latitude ≈ 111,320 m at the equator.
    1 degree of longitude ≈ 111,320 m at the equator.
    So ~1 km ≈ 0.008983° (1000 / 111320).
    """
    side = 1000 / 111320  # ~0.008983 degrees
    half = side / 2
    return Polygon(
        [
            (-half, -half),
            (half, -half),
            (half, half),
            (-half, half),
            (-half, -half),
        ]
    )


def high_lat_1km_square(lat: float = 60.0) -> Polygon:
    """A ~1 km × 1 km square at a high latitude.

    At 60°N, 1° longitude ≈ 55,660 m (111320 * cos(60°)).
    """
    import math

    lat_side = 1000 / 111320
    lon_side = 1000 / (111320 * math.cos(math.radians(lat)))
    half_lat = lat_side / 2
    half_lon = lon_side / 2
    return Polygon(
        [
            (-half_lon, lat - half_lat),
            (half_lon, lat - half_lat),
            (half_lon, lat + half_lat),
            (-half_lon, lat + half_lat),
            (-half_lon, lat - half_lat),
        ]
    )


def southern_1km_square(lat: float = -33.8) -> Polygon:
    """A ~1 km × 1 km square in the southern hemisphere."""
    import math

    lat_side = 1000 / 111320
    lon_side = 1000 / (111320 * math.cos(math.radians(lat)))
    half_lat = lat_side / 2
    half_lon = lon_side / 2
    return Polygon(
        [
            (151.2 - half_lon, lat - half_lat),
            (151.2 + half_lon, lat - half_lat),
            (151.2 + half_lon, lat + half_lat),
            (151.2 - half_lon, lat + half_lat),
            (151.2 - half_lon, lat - half_lat),
        ]
    )
