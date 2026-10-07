"""Generate sample geospatial files for testing and demonstration.

Generates:
1. samples/cubbon_park.kml - KML containing Polygon, LineString, Point in Bengaluru.
2. samples/bengaluru_zones.zip - Zipped ESRI Shapefile with Polygon features in EPSG:4326.
"""

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon


def main():
    samples_dir = Path("samples")
    samples_dir.mkdir(exist_ok=True)

    # 1. Create sample KML
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Cubbon Park Bengaluru</name>
    <description>Sample geospatial features in Bengaluru, India (UTM Zone 43N)</description>
    <Placemark>
      <name>Cubbon Park Boundary</name>
      <description>Major park in Bengaluru central business district</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5900,12.9730,0
              77.5950,12.9730,0
              77.5950,12.9780,0
              77.5900,12.9780,0
              77.5900,12.9730,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Kasturba Road Promenade</name>
      <description>Road running along the edge of Cubbon Park</description>
      <LineString>
        <coordinates>
          77.5900,12.9730,0
          77.5925,12.9755,0
          77.5950,12.9780,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>State Central Library</name>
      <description>Heritage building inside Cubbon Park</description>
      <Point>
        <coordinates>77.5925,12.9750,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""

    kml_path = samples_dir / "cubbon_park.kml"
    kml_path.write_text(kml_content, encoding="utf-8")
    print(f"Generated: {kml_path}")

    # 2. Create sample zipped Shapefile
    poly1 = Polygon(
        [
            (77.585, 12.965),
            (77.595, 12.965),
            (77.595, 12.975),
            (77.585, 12.975),
            (77.585, 12.965),
        ]
    )
    poly2 = Polygon(
        [
            (77.596, 12.965),
            (77.606, 12.965),
            (77.606, 12.975),
            (77.596, 12.975),
            (77.596, 12.965),
        ]
    )
    gdf = gpd.GeoDataFrame(
        [
            {"name": "Zone Alpha", "zone_type": "Commercial", "priority": 1, "geometry": poly1},
            {"name": "Zone Beta", "zone_type": "Residential", "priority": 2, "geometry": poly2},
        ],
        crs="EPSG:4326",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = Path(tmp_dir) / "bengaluru_zones.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        zip_target = samples_dir / "bengaluru_zones.zip"
        with zipfile.ZipFile(zip_target, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in Path(tmp_dir).iterdir():
                zf.write(f, arcname=f.name)
        print(f"Generated: {zip_target}")


if __name__ == "__main__":
    main()
