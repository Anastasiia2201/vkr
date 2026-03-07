import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.db import transaction

from document_processor.models import LandCategory, LandPlot


GEOJSON_DIR = Path("output/geojson")


class RosreestrError(Exception):
    pass


@dataclass
class CadastralLocation:
    cadastral_number: str
    address: str | None
    center_lat: float | None
    center_lon: float | None
    geometry: GEOSGeometry | None


def fetch_location_by_cadastral_number(cadastral_number: str) -> CadastralLocation:
    try:
        land_plot = LandPlot.objects.select_related("land_category").get(
            cadastral_number=cadastral_number
        )

        if land_plot.geometry:
            centroid = land_plot.geometry.centroid
            return CadastralLocation(
                cadastral_number=land_plot.cadastral_number,
                address=land_plot.location,
                center_lat=centroid.y,
                center_lon=centroid.x,
                geometry=land_plot.geometry,
            )
    except LandPlot.DoesNotExist:
        land_plot = None

    if not land_plot:
        try:
            subprocess.run(
                ["rosreestr2coord", "-c", cadastral_number],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
        except FileNotFoundError as exc:
            raise RosreestrError("Утилита rosreestr2coord не установлена") from exc
        except subprocess.CalledProcessError as exc:
            raise RosreestrError("Ошибка выполнения rosreestr2coord") from exc

    try:
        geojson_path = GEOJSON_DIR / f"{cadastral_number.replace(':', '_')}.geojson"
        data = json.loads(geojson_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RosreestrError(f"GeoJSON файл не найден: {geojson_path}") from exc
    except json.JSONDecodeError as exc:
        raise RosreestrError("Ошибка чтения GeoJSON") from exc

    geometry = GEOSGeometry(json.dumps(data["geometry"]))
    geometry_wgs84 = geometry.clone()
    geometry_wgs84.transform(4326)

    if geometry_wgs84.geom_type == "Polygon":
        geometry_wgs84 = MultiPolygon(geometry_wgs84, srid=4326)

    centroid = geometry_wgs84.centroid

    options = data["properties"]["options"]

    address = options.get("readable_address")
    category_name = options.get("land_record_category_type")
    use_type = options.get("permitted_use_established_by_document")
    specified_area = options.get("specified_area")

    area_hectares = specified_area / 10000 if specified_area else None

    with transaction.atomic():
        land_category = None
        if category_name:
            land_category, _ = LandCategory.objects.get_or_create(name=category_name)

        land_plot, _ = LandPlot.objects.update_or_create(
            cadastral_number=cadastral_number,
            defaults={
                "location": address or "",
                "land_category": land_category,
                "area_hectares": area_hectares,
                "geometry": geometry_wgs84,
                "use_type": use_type,
            },
        )

    return CadastralLocation(
        cadastral_number=land_plot.cadastral_number,
        address=land_plot.location,
        center_lat=centroid.y,
        center_lon=centroid.x,
        geometry=land_plot.geometry,
    )
