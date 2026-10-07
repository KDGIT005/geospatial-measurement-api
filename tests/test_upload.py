"""Tests for file upload endpoint (POST /api/files/).

Covers successful uploads (KML and Shapefile), feature counting, and
correct response structure.
"""

import io

from shapely.geometry import Polygon

from tests.conftest import (
    make_kml_string,
    make_square_kml,
    make_zipped_shapefile,
    make_zipped_shapefile_in_subfolder,
)


class TestKMLUpload:
    """KML upload success cases."""

    def test_upload_kml_polygon(self, client):
        """Upload a KML with a polygon, expect 201 and correct feature_count."""
        kml = make_square_kml(center_lon=0, center_lat=0, side_deg=0.01)
        response = client.post(
            "/api/files/",
            files={
                "file": (
                    "test.kml",
                    io.BytesIO(kml.encode()),
                    "application/vnd.google-earth.kml+xml",
                )
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["feature_count"] == 1
        assert data["crs"] == "EPSG:4326"
        assert data["status"] == "COMPLETED"
        assert "id" in data

    def test_upload_kml_multiple_features(self, client):
        """KML with mixed geometry types returns correct feature count."""
        kml = make_kml_string(
            [
                {"name": "Point1", "geometry_type": "Point", "coordinates": [(0, 0)]},
                {"name": "Line1", "geometry_type": "LineString", "coordinates": [(0, 0), (1, 1)]},
                {
                    "name": "Poly1",
                    "geometry_type": "Polygon",
                    "coordinates": [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
                },
            ]
        )
        response = client.post(
            "/api/files/",
            files={"file": ("multi.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        assert response.status_code == 201
        assert response.json()["feature_count"] == 3


class TestShapefileUpload:
    """Zipped Shapefile upload success cases."""

    def test_upload_shapefile_polygon(self, client):
        """Upload a zipped Shapefile with a polygon."""
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        zip_bytes = make_zipped_shapefile([poly])

        response = client.post(
            "/api/files/",
            files={"file": ("data.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["feature_count"] == 1
        assert data["status"] == "COMPLETED"
        assert data["crs"] is not None

    def test_upload_shapefile_in_subfolder(self, client):
        """Shapefile inside a subfolder in the zip should still be found."""
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        zip_bytes = make_zipped_shapefile_in_subfolder([poly])

        response = client.post(
            "/api/files/",
            files={"file": ("nested.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 201
        assert response.json()["feature_count"] == 1

    def test_upload_shapefile_multiple_features(self, client):
        """Shapefile with multiple features returns correct count."""
        geoms = [Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1), (i, 0)]) for i in range(5)]
        zip_bytes = make_zipped_shapefile(geoms)

        response = client.post(
            "/api/files/",
            files={"file": ("multi.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 201
        assert response.json()["feature_count"] == 5


class TestMixedGeometryUpload:
    """Upload files with mixed geometry types."""

    def test_mixed_kml(self, client):
        """KML with Point, LineString, Polygon returns correct per-feature results."""
        kml = make_kml_string(
            [
                {"name": "P", "geometry_type": "Point", "coordinates": [(10, 20)]},
                {"name": "L", "geometry_type": "LineString", "coordinates": [(0, 0), (1, 1)]},
                {
                    "name": "Pg",
                    "geometry_type": "Polygon",
                    "coordinates": [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
                },
            ]
        )
        response = client.post(
            "/api/files/",
            files={"file": ("mixed.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        assert response.status_code == 201
        file_id = response.json()["id"]

        # Check measurements
        meas_response = client.get(f"/api/files/{file_id}/measurements/")
        assert meas_response.status_code == 200
        features = meas_response.json()["features"]

        # Point: no measurement
        assert features[0]["geometry_type"] == "Point"
        assert features[0]["measurement"] is None
        assert features[0]["supported"] is True

        # LineString: length
        assert features[1]["geometry_type"] == "LineString"
        assert features[1]["measurement"]["type"] == "length"

        # Polygon: area
        assert features[2]["geometry_type"] == "Polygon"
        assert features[2]["measurement"]["type"] == "area"
