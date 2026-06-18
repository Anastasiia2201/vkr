import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.db import transaction

from document_processor.models import LandPlot


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

    if 1:
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

    raw_geometry = GEOSGeometry(json.dumps(data["geometry"]))

    minx, miny, maxx, maxy = raw_geometry.extent

    looks_like_wgs84 = (
        -180 <= minx <= 180 and
        -180 <= maxx <= 180 and
        -90 <= miny <= 90 and
        -90 <= maxy <= 90
    )

    if looks_like_wgs84:
        # Координаты уже похожи на EPSG:4326,
        # даже если в crs ошибочно указан 3857
        raw_geometry.srid = 4326
        geometry_wgs84 = raw_geometry
    else:
        # Иначе считаем, что это действительно 3857
        if raw_geometry.srid is None:
            raw_geometry.srid = 3857

        geometry_wgs84 = raw_geometry.clone()
        geometry_wgs84.transform(4326)

    if geometry_wgs84.geom_type == "Polygon":
        geometry_wgs84 = MultiPolygon(geometry_wgs84, srid=4326)

    centroid = geometry_wgs84.centroid
    options = (data.get("properties") or {}).get("options") or {}

    address = options.get("readable_address")
    use_type = options.get("permitted_use_established_by_document")
    specified_area = options.get("specified_area")

    area_hectares = specified_area / 10000 if specified_area else None

    with transaction.atomic():
        defaults = {
            "location": address or "",
            "geometry": geometry_wgs84,
        }

        if area_hectares is not None:
            defaults["area_hectares"] = area_hectares

        if use_type:
            defaults["use_type"] = use_type

        land_plot, _ = LandPlot.objects.update_or_create(
            cadastral_number=cadastral_number,
            defaults=defaults,
        )

    return CadastralLocation(
        cadastral_number=land_plot.cadastral_number,
        address=land_plot.location,
        center_lat=centroid.y,
        center_lon=centroid.x,
        geometry=land_plot.geometry,
    )
