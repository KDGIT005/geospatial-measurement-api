"""Tests for measurement accuracy.

Verifies that projected UTM area/length and geodesic cross-checks
are accurate to within known tolerances.
"""

import math

from shapely.geometry import LineString, Polygon, mapping

from app.services.measurements import compute_measurement


class TestPolygonArea:
    """Area accuracy tests for polygons at various latitudes."""

    def test_1km_square_at_equator(self):
        """A ~1 km × 1 km square at the equator → area ≈ 1,000,000 m².

        Tolerance: 0.5% (5000 m²).
        """
        side_deg = 1000 / 111320  # ~0.008983°
        half = side_deg / 2
        poly = Polygon(
            [
                (-half, -half),
                (half, -half),
                (half, half),
                (-half, half),
                (-half, -half),
            ]
        )
        result = compute_measurement(mapping(poly), "EPSG:4326")

        assert result["measurement_type"] == "area"
        assert result["measurement_unit"] == "square_meters"
        assert result["method"] == "projected_utm"
        assert result["is_supported"] is True

        # Projected area within 0.5% of 1,000,000 m²
        assert abs(result["measurement_value"] - 1_000_000) < 5000

        # Geodesic area within 1% of 1,000,000 m²
        assert abs(result["geodesic_value"] - 1_000_000) < 10_000

    def test_1km_square_at_60n(self):
        """A ~1 km × 1 km square at 60°N → area ≈ 1,000,000 m²."""
        lat = 60.0
        lat_side = 1000 / 111320
        lon_side = 1000 / (111320 * math.cos(math.radians(lat)))
        half_lat = lat_side / 2
        half_lon = lon_side / 2

        poly = Polygon(
            [
                (-half_lon, lat - half_lat),
                (half_lon, lat - half_lat),
                (half_lon, lat + half_lat),
                (-half_lon, lat + half_lat),
                (-half_lon, lat - half_lat),
            ]
        )
        result = compute_measurement(mapping(poly), "EPSG:4326")

        assert result["measurement_type"] == "area"
        assert abs(result["measurement_value"] - 1_000_000) < 5000
        assert abs(result["geodesic_value"] - 1_000_000) < 5000

    def test_1km_square_southern_hemisphere(self):
        """A ~1 km × 1 km square near Sydney (−33.8°S) → area ≈ 1,000,000 m²."""
        lat = -33.8
        lat_side = 1000 / 111320
        lon_side = 1000 / (111320 * math.cos(math.radians(lat)))
        half_lat = lat_side / 2
        half_lon = lon_side / 2

        poly = Polygon(
            [
                (151.2 - half_lon, lat - half_lat),
                (151.2 + half_lon, lat - half_lat),
                (151.2 + half_lon, lat + half_lat),
                (151.2 - half_lon, lat + half_lat),
                (151.2 - half_lon, lat - half_lat),
            ]
        )
        result = compute_measurement(mapping(poly), "EPSG:4326")

        assert result["measurement_type"] == "area"
        assert result["projected_crs"].startswith("EPSG:327")  # southern hemisphere
        assert abs(result["measurement_value"] - 1_000_000) < 5000
        assert abs(result["geodesic_value"] - 1_000_000) < 5000

    def test_projected_vs_geodesic_agreement(self):
        """Projected and geodesic areas should agree within 1%."""
        side_deg = 1000 / 111320
        half = side_deg / 2
        poly = Polygon(
            [
                (-half, -half),
                (half, -half),
                (half, half),
                (-half, half),
                (-half, -half),
            ]
        )
        result = compute_measurement(mapping(poly), "EPSG:4326")

        projected = result["measurement_value"]
        geodesic = result["geodesic_value"]
        pct_diff = abs(projected - geodesic) / geodesic * 100
        assert pct_diff < 1.0, f"Projected vs geodesic differ by {pct_diff:.2f}%"

    def test_polygon_with_hole(self):
        """A polygon with a hole: both projected and geodesic should subtract the hole.

        Outer: ~2 km × 2 km (≈ 4,000,000 m²)
        Hole: ~1 km × 1 km (≈ 1,000,000 m²)
        Expected area: ≈ 3,000,000 m²
        """
        outer_side = 2000 / 111320
        hole_side = 1000 / 111320
        outer_half = outer_side / 2
        hole_half = hole_side / 2

        outer_ring = [
            (-outer_half, -outer_half),
            (outer_half, -outer_half),
            (outer_half, outer_half),
            (-outer_half, outer_half),
            (-outer_half, -outer_half),
        ]
        hole_ring = [
            (-hole_half, -hole_half),
            (hole_half, -hole_half),
            (hole_half, hole_half),
            (-hole_half, hole_half),
            (-hole_half, -hole_half),
        ]

        poly = Polygon(outer_ring, [hole_ring])
        result = compute_measurement(mapping(poly), "EPSG:4326")

        assert result["measurement_type"] == "area"
        # Expected: ~3,000,000 m² (4M outer - 1M hole)
        assert abs(result["measurement_value"] - 3_000_000) < 30_000
        assert abs(result["geodesic_value"] - 3_000_000) < 30_000


class TestLineStringLength:
    """Length accuracy tests for line geometries."""

    def test_1km_line_at_equator(self):
        """A ~1 km horizontal line at the equator.

        1° longitude at equator ≈ 111,320 m.
        So 1000 m ≈ 0.008983°.
        """
        line_deg = 1000 / 111320
        line = LineString([(0, 0), (line_deg, 0)])
        result = compute_measurement(mapping(line), "EPSG:4326")

        assert result["measurement_type"] == "length"
        assert result["measurement_unit"] == "meters"
        assert result["method"] == "projected_utm"
        assert abs(result["measurement_value"] - 1000) < 10  # within 10m

        # Geodesic should agree closely
        assert abs(result["geodesic_value"] - 1000) < 10

    def test_10km_diagonal_line(self):
        """A ~10 km diagonal line — projected and geodesic should agree within 1%."""
        line_deg = 10000 / 111320
        line = LineString([(0, 0), (line_deg, line_deg)])
        result = compute_measurement(mapping(line), "EPSG:4326")

        projected = result["measurement_value"]
        geodesic = result["geodesic_value"]
        pct_diff = abs(projected - geodesic) / geodesic * 100
        assert pct_diff < 1.0


class TestNoMeasurement:
    """Point geometries and unsupported types."""

    def test_point_no_measurement(self):
        """Points should have no measurement but be supported."""
        from shapely.geometry import Point, mapping

        result = compute_measurement(mapping(Point(0, 0)), "EPSG:4326")
        assert result["is_supported"] is True
        assert result["measurement_type"] is None
        assert result["measurement_value"] is None
        assert "Point" in result["note"]

    def test_multipoint_no_measurement(self):
        """MultiPoints also have no measurement."""
        from shapely.geometry import MultiPoint, mapping

        result = compute_measurement(mapping(MultiPoint([(0, 0), (1, 1)])), "EPSG:4326")
        assert result["is_supported"] is True
        assert result["measurement_type"] is None


class TestUnsupported:
    """Unsupported geometry types should be gracefully handled."""

    def test_geometry_collection_unsupported(self):
        """GeometryCollection is unsupported."""
        from shapely.geometry import GeometryCollection, Point, mapping

        gc = GeometryCollection([Point(0, 0)])
        result = compute_measurement(mapping(gc), "EPSG:4326")
        assert result["is_supported"] is False
        assert result["measurement_value"] is None

    def test_null_geometry(self):
        """Null GeoJSON should not crash."""
        result = compute_measurement({"type": "Point", "coordinates": []}, "EPSG:4326")
        assert result["is_supported"] is False
