"""Unit tests for CRS module: UTM zone selection for known cities."""

from shapely.geometry import Point

from app.services.crs import get_utm_epsg, select_utm_crs


class TestUTMZoneSelection:
    """Verify UTM zone selection against known city coordinates."""

    def test_bengaluru_utm_zone(self):
        """Bengaluru (77.59°E, 12.97°N) → UTM zone 43N → EPSG:32643."""
        epsg = get_utm_epsg(77.59, 12.97)
        assert epsg == 32643

    def test_london_utm_zone(self):
        """London (−0.12°, 51.51°N) → UTM zone 30N → EPSG:32630."""
        epsg = get_utm_epsg(-0.12, 51.51)
        assert epsg == 32630

    def test_sydney_utm_zone(self):
        """Sydney (151.21°E, −33.87°S) → UTM zone 56S → EPSG:32756."""
        epsg = get_utm_epsg(151.21, -33.87)
        assert epsg == 32756

    def test_new_york_utm_zone(self):
        """New York (−74.0°, 40.71°N) → UTM zone 18N → EPSG:32618."""
        epsg = get_utm_epsg(-74.0, 40.71)
        assert epsg == 32618

    def test_tokyo_utm_zone(self):
        """Tokyo (139.69°E, 35.69°N) → UTM zone 54N → EPSG:32654."""
        epsg = get_utm_epsg(139.69, 35.69)
        assert epsg == 32654

    def test_zone_clamped_min(self):
        """Longitude −180 should give zone 1, not zone 0."""
        epsg = get_utm_epsg(-180.0, 10.0)
        assert epsg == 32601

    def test_zone_clamped_max(self):
        """Longitude 179.99 should give zone 60."""
        epsg = get_utm_epsg(179.99, 10.0)
        assert epsg == 32660

    def test_equator_southern(self):
        """Just south of the equator → southern hemisphere code."""
        epsg = get_utm_epsg(0.0, -0.01)
        assert epsg == 32731  # zone 31, southern


class TestSelectUTMCRS:
    """Test the full select_utm_crs pipeline with shapely geometries."""

    def test_point_in_bengaluru(self):
        """A point in Bengaluru should select EPSG:32643."""
        point = Point(77.59, 12.97)
        crs = select_utm_crs(point, "EPSG:4326")
        assert crs == "EPSG:32643"

    def test_polygon_in_london(self):
        """A small polygon around London should select EPSG:32630."""
        from shapely.geometry import Polygon

        poly = Polygon(
            [
                (-0.13, 51.50),
                (-0.11, 51.50),
                (-0.11, 51.52),
                (-0.13, 51.52),
                (-0.13, 51.50),
            ]
        )
        crs = select_utm_crs(poly, "EPSG:4326")
        assert crs == "EPSG:32630"

    def test_projected_source_crs(self):
        """Even with a projected source CRS, we still pick UTM from centroid."""
        # Web Mercator point roughly at Bengaluru
        point = Point(8637488, 1449791)  # approximate EPSG:3857 coords
        crs = select_utm_crs(point, "EPSG:3857")
        assert crs == "EPSG:32643"
