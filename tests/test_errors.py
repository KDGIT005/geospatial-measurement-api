"""Tests for error handling: wrong extension, corrupt zip, missing .prj, etc.

Also covers GET endpoints (404, pagination, include_geometry).
"""

import io
import zipfile

from shapely.geometry import Polygon

from tests.conftest import make_zipped_shapefile


class TestUnsupportedFileType:
    """Wrong file extensions should return 415."""

    def test_txt_file_rejected(self, client):
        response = client.post(
            "/api/files/",
            files={"file": ("data.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert response.status_code == 415
        assert response.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    def test_geojson_file_rejected(self, client):
        response = client.post(
            "/api/files/",
            files={"file": ("data.geojson", io.BytesIO(b"{}"), "application/json")},
        )
        assert response.status_code == 415

    def test_csv_file_rejected(self, client):
        response = client.post(
            "/api/files/",
            files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
        )
        assert response.status_code == 415


class TestCorruptFiles:
    """Corrupt or empty files should return 400."""

    def test_corrupt_zip(self, client):
        """A file with .zip extension but not actually a zip."""
        response = client.post(
            "/api/files/",
            files={"file": ("corrupt.zip", io.BytesIO(b"not a zip"), "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_GEOSPATIAL_FILE"

    def test_empty_zip(self, client):
        """A valid zip with no .shp inside."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "just a readme")
        response = client.post(
            "/api/files/",
            files={"file": ("empty.zip", io.BytesIO(buf.getvalue()), "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_GEOSPATIAL_FILE"

    def test_empty_kml(self, client):
        """An empty file with .kml extension."""
        response = client.post(
            "/api/files/",
            files={"file": ("empty.kml", io.BytesIO(b""), "application/xml")},
        )
        # Should fail during parsing
        assert response.status_code in (400, 422)


class TestMissingPRJ:
    """Shapefile without .prj should return 422."""

    def test_no_prj_file(self, client):
        """Shapefile zip with no .prj → 422 MISSING_CRS."""
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        zip_bytes = make_zipped_shapefile([poly], include_prj=False)

        response = client.post(
            "/api/files/",
            files={"file": ("no_prj.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "MISSING_CRS"


class TestZipSecurity:
    """Zip-slip and other security checks."""

    def test_zip_slip_rejected(self, client):
        """A zip with path traversal entries should be rejected."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", "evil content")
            zf.writestr("data.shp", "dummy")
        response = client.post(
            "/api/files/",
            files={"file": ("slip.zip", io.BytesIO(buf.getvalue()), "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "ZIP_SECURITY_ERROR"


class TestFileTooLarge:
    """Oversized files should return 413."""

    def test_oversized_file(self, client, monkeypatch):
        """File exceeding MAX_UPLOAD_SIZE should be rejected."""
        from app.config import settings

        # Temporarily set a very small limit
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE", 100)

        data = b"x" * 200
        response = client.post(
            "/api/files/",
            files={"file": ("big.kml", io.BytesIO(data), "application/xml")},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "FILE_TOO_LARGE"


class TestGetFile:
    """Tests for GET /api/files/{id}/."""

    def test_get_file_not_found(self, client):
        """Unknown ID returns 404."""
        response = client.get("/api/files/nonexistent-id/")
        assert response.status_code == 404
        assert response.json()["code"] == "FILE_NOT_FOUND"

    def test_get_file_after_upload(self, client):
        """Uploading then getting a file returns correct detail."""
        from tests.conftest import make_square_kml

        kml = make_square_kml(0, 0, 0.01)
        upload = client.post(
            "/api/files/",
            files={"file": ("test.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        file_id = upload.json()["id"]

        response = client.get(f"/api/files/{file_id}/")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == file_id
        assert data["file_type"] == "kml"
        assert data["status"] == "COMPLETED"
        assert "created_at" in data
        assert data["measured_feature_count"] == 1
        assert data["unsupported_feature_count"] == 0


class TestGetMeasurements:
    """Tests for GET /api/files/{id}/measurements/."""

    def test_measurements_not_found(self, client):
        """Unknown ID returns 404."""
        response = client.get("/api/files/nonexistent-id/measurements/")
        assert response.status_code == 404

    def test_pagination(self, client):
        """Pagination with limit and offset works correctly."""
        from tests.conftest import make_kml_string

        # Create KML with 5 points
        placemarks = [
            {"name": f"P{i}", "geometry_type": "Point", "coordinates": [(i, i)]} for i in range(5)
        ]
        kml = make_kml_string(placemarks)
        upload = client.post(
            "/api/files/",
            files={"file": ("points.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        file_id = upload.json()["id"]

        # Get first 2
        r1 = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=0")
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["total"] == 5
        assert d1["limit"] == 2
        assert d1["offset"] == 0
        assert len(d1["features"]) == 2

        # Get next 2
        r2 = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=2")
        d2 = r2.json()
        assert len(d2["features"]) == 2
        assert d2["features"][0]["feature_index"] == 2

        # Last page
        r3 = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=4")
        d3 = r3.json()
        assert len(d3["features"]) == 1

    def test_include_geometry_false(self, client):
        """include_geometry=false removes geometry from response."""
        from tests.conftest import make_square_kml

        kml = make_square_kml(0, 0, 0.01)
        upload = client.post(
            "/api/files/",
            files={"file": ("sq.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        file_id = upload.json()["id"]

        response = client.get(f"/api/files/{file_id}/measurements/?include_geometry=false")
        assert response.status_code == 200
        features = response.json()["features"]
        assert features[0]["geometry"] is None
        # Measurement should still be present
        assert features[0]["measurement"] is not None

    def test_include_geometry_true_default(self, client):
        """By default, geometry is included."""
        from tests.conftest import make_square_kml

        kml = make_square_kml(0, 0, 0.01)
        upload = client.post(
            "/api/files/",
            files={"file": ("sq.kml", io.BytesIO(kml.encode()), "application/xml")},
        )
        file_id = upload.json()["id"]

        response = client.get(f"/api/files/{file_id}/measurements/")
        features = response.json()["features"]
        assert features[0]["geometry"] is not None


class TestHealthEndpoint:
    """Basic health check."""

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
