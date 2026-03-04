import json
from dataclasses import dataclass
from typing import Any

import requests
from django.contrib.gis.geos import GEOSGeometry

ROSREESTR_FEATURE_URL = "https://pkk.rosreestr.ru/api/features/1/{cadastral_number}"


class RosreestrError(Exception):
    """Базовая ошибка работы с API Росреестра."""


class RosreestrNotFoundError(RosreestrError):
    """Кадастровый номер не найден в API Росреестра."""


@dataclass
class CadastralLocation:
    cadastral_number: str
    address: str | None
    center_lat: float | None
    center_lon: float | None
    geometry: GEOSGeometry | None


def fetch_location_by_cadastral_number(
    cadastral_number: str,
    timeout: int = 15,
) -> CadastralLocation:
    """Получить геометрию и центр участка по кадастровому номеру."""
    response = requests.get(
        ROSREESTR_FEATURE_URL.format(cadastral_number=cadastral_number),
        timeout=timeout,
    )

    if response.status_code == 404:
        raise RosreestrNotFoundError(
            f"Кадастровый номер {cadastral_number} не найден"
        )

    if response.status_code != 200:
        raise RosreestrError(
            f"Ошибка API Росреестра. Код ответа: {response.status_code}"
        )

    data = response.json()
    feature: dict[str, Any] = data.get("feature") or {}
    attrs: dict[str, Any] = feature.get("attrs") or {}

    geometry_data = feature.get("geometry")
    geometry = _to_geos_geometry(geometry_data)

    center = feature.get("center")

    return CadastralLocation(
        cadastral_number=cadastral_number,
        address=attrs.get("address") or attrs.get("readable_address"),
        center_lat=_extract_center_lat(center),
        center_lon=_extract_center_lon(center),
        geometry=geometry,
    )


def _to_geos_geometry(geometry_data: dict[str, Any] | None) -> GEOSGeometry | None:
    if not geometry_data:
        return None

    return GEOSGeometry(json.dumps(geometry_data), srid=4326)


def _extract_center_lat(center: Any) -> float | None:
    if isinstance(center, dict):
        return center.get("y")
    if isinstance(center, list) and len(center) > 1:
        return center[1]
    return None


def _extract_center_lon(center: Any) -> float | None:
    if isinstance(center, dict):
        return center.get("x")
    if isinstance(center, list) and center:
        return center[0]
    return None
