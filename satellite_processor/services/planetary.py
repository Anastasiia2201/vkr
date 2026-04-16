from __future__ import annotations

from datetime import date
from io import BytesIO

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from django.core.files.base import ContentFile
from django.utils.dateparse import parse_datetime
from PIL import Image
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from document_processor.models import LandPlot
from satellite_processor.models import SatelliteImage


class PlanetaryError(Exception):
    pass


DEFAULT_BBOX_EXPAND_FACTOR = 2.0


MIN_CROP_SIZE_METERS = 200.0


PREVIEW_SIZE = (512, 512)


def get_land_plot_bbox(land_plot: LandPlot) -> list[float]:
    if not land_plot.geometry:
        raise PlanetaryError("У участка отсутствует geometry.")

    minx, miny, maxx, maxy = land_plot.geometry.extent

    if minx == maxx or miny == maxy:
        raise PlanetaryError("Некорректная geometry участка.")

    return [minx, miny, maxx, maxy]


def get_catalog():
    return pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1"
    )


def build_datetime_range(
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    today = date.today()

    if start_date is None and end_date is None:
        year = today.year
        if today.month < 10:
            year -= 1

        start_date = date(year, 5, 1)
        end_date = date(year, 9, 30)
    elif end_date is None:
        end_date = today
    elif start_date is None:
        start_date = date(end_date.year, 5, 1)

    if start_date > end_date:
        raise PlanetaryError("Некорректный диапазон дат.")

    return f"{start_date.isoformat()}/{end_date.isoformat()}"


def score_item(item) -> tuple[float, float, str]:
    props = item.properties

    cloud_cover = props.get("eo:cloud_cover")
    if cloud_cover is None:
        cloud_cover = 1000.0

    snow_ice = props.get("s2:snow_ice_percentage")
    if snow_ice is None:
        snow_ice = 1000.0

    dt = props.get("datetime", "")

    return (snow_ice, cloud_cover, dt)


def find_best_sentinel_item(
    bbox: list[float],
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 50,
    max_cloud_cover: float | None = 20.0,
    max_snow_ice_percentage: float | None = 20.0,
):
    catalog = get_catalog()

    datetime_range = build_datetime_range(start_date, end_date)

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=datetime_range,
        limit=limit,
    )

    items = list(search.items())
    if not items:
        raise PlanetaryError("Подходящие сцены Sentinel-2 не найдены.")

    filtered_items = []

    for item in items:
        props = item.properties
        cloud_cover = props.get("eo:cloud_cover")
        snow_ice = props.get("s2:snow_ice_percentage")

        if max_cloud_cover is not None and cloud_cover is not None:
            if cloud_cover > max_cloud_cover:
                continue

        if max_snow_ice_percentage is not None and snow_ice is not None:
            if snow_ice > max_snow_ice_percentage:
                continue

        filtered_items.append(item)

    if not filtered_items:
        raise PlanetaryError(
            "Сцены найдены, но все были отфильтрованы по облачности/снегу."
        )

    filtered_items.sort(key=score_item)

    return planetary_computer.sign(filtered_items[0])


def expand_bbox(
    bbox_wgs84: list[float],
    factor: float = DEFAULT_BBOX_EXPAND_FACTOR,
    min_size_meters: float = MIN_CROP_SIZE_METERS,
) -> list[float]:
    minx, miny, maxx, maxy = bbox_wgs84

    center_x = (minx + maxx) / 2.0
    center_y = (miny + maxy) / 2.0

    width_deg = maxx - minx
    height_deg = maxy - miny

    if width_deg <= 0 or height_deg <= 0:
        raise PlanetaryError("Некорректный bbox участка.")

    lat_rad = np.deg2rad(center_y)

    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * max(np.cos(lat_rad), 0.1)

    width_m = width_deg * meters_per_degree_lon
    height_m = height_deg * meters_per_degree_lat

    expanded_width_m = max(width_m * factor, min_size_meters)
    expanded_height_m = max(height_m * factor, min_size_meters)

    expanded_width_deg = expanded_width_m / meters_per_degree_lon
    expanded_height_deg = expanded_height_m / meters_per_degree_lat

    return [
        center_x - expanded_width_deg / 2.0,
        center_y - expanded_height_deg / 2.0,
        center_x + expanded_width_deg / 2.0,
        center_y + expanded_height_deg / 2.0,
    ]


def _get_window_for_bbox(src, bbox_wgs84: list[float]):
    left, bottom, right, top = transform_bounds(
        "EPSG:4326",
        src.crs,
        bbox_wgs84[0],
        bbox_wgs84[1],
        bbox_wgs84[2],
        bbox_wgs84[3],
        densify_pts=21,
    )

    return from_bounds(left, bottom, right, top, src.transform)


def _read_band(item, asset_name: str, bbox_wgs84: list[float]) -> np.ndarray:
    if asset_name not in item.assets:
        raise PlanetaryError(
            f"У сцены отсутствует asset '{asset_name}'. "
            f"Доступные assets: {list(item.assets.keys())}"
        )

    href = item.assets[asset_name].href

    with rasterio.open(href) as src:
        window = _get_window_for_bbox(src, bbox_wgs84)
        band = src.read(1, window=window)

    if band.size == 0:
        raise PlanetaryError(
            f"Получено пустое изображение участка для канала {asset_name}."
        )

    return band


def read_bands_with_nir(
    item,
    bbox_wgs84: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    red = _read_band(item, "B04", bbox_wgs84)
    green = _read_band(item, "B03", bbox_wgs84)
    blue = _read_band(item, "B02", bbox_wgs84)
    nir = _read_band(item, "B08", bbox_wgs84)

    return red, green, blue, nir


def read_rgb_bands_crop(
    item,
    bbox_wgs84: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return read_bands_with_nir(item, bbox_wgs84)


def compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    red = red.astype("float32")
    nir = nir.astype("float32")

    denominator = nir + red
    denominator[denominator == 0] = 1e-6

    ndvi = (nir - red) / denominator
    return ndvi


def extract_features(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    nir: np.ndarray,
) -> dict:
    ndvi = compute_ndvi(red, nir)

    return {
        "mean_ndvi": float(np.mean(ndvi)),
        "std_ndvi": float(np.std(ndvi)),
        "min_ndvi": float(np.min(ndvi)),
        "max_ndvi": float(np.max(ndvi)),
        "median_ndvi": float(np.median(ndvi)),
        "p25_ndvi": float(np.percentile(ndvi, 25)),
        "p75_ndvi": float(np.percentile(ndvi, 75)),
        "mean_red": float(np.mean(red)),
        "mean_green": float(np.mean(green)),
        "mean_blue": float(np.mean(blue)),
        "mean_nir": float(np.mean(nir)),
        "std_red": float(np.std(red)),
        "std_green": float(np.std(green)),
        "std_blue": float(np.std(blue)),
        "std_nir": float(np.std(nir)),
    }


def normalize_rgb(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype("float32")

    low = np.percentile(rgb, 2)
    high = np.percentile(rgb, 98)

    if high <= low:
        return np.clip(rgb, 0, 255).astype("uint8")

    rgb = (rgb - low) / (high - low)
    rgb = np.clip(rgb, 0, 1)
    rgb = (rgb * 255).astype("uint8")
    return rgb


def build_rgb_preview(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
) -> np.ndarray:
    rgb = np.stack([red, green, blue], axis=-1)
    rgb = normalize_rgb(rgb)

    image = Image.fromarray(rgb)
    image = image.resize(PREVIEW_SIZE, Image.Resampling.NEAREST)
    return np.array(image)


def build_preview_content(rgb_array: np.ndarray) -> ContentFile:
    image = Image.fromarray(rgb_array)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return ContentFile(buffer.getvalue())


def save_planetary_preview(
    land_plot: LandPlot,
    start_date: date | None = None,
    end_date: date | None = None,
    max_cloud_cover: float | None = 20.0,
    max_snow_ice_percentage: float | None = 20.0,
) -> SatelliteImage:
    original_bbox = get_land_plot_bbox(land_plot)
    bbox = expand_bbox(original_bbox)

    item = find_best_sentinel_item(
        bbox=bbox,
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=max_cloud_cover,
        max_snow_ice_percentage=max_snow_ice_percentage,
    )

    red, green, blue, nir = read_bands_with_nir(item, bbox)
    features = extract_features(red, green, blue, nir)
    ndvi_value = features["mean_ndvi"]

    rgb = build_rgb_preview(red, green, blue)
    preview_content = build_preview_content(rgb)

    acquisition_raw = item.properties.get("datetime")
    acquisition_date = parse_datetime(acquisition_raw)

    if acquisition_date is None:
        raise PlanetaryError("Не удалось разобрать дату съемки.")

    cloud_cover = item.properties.get("eo:cloud_cover")

    satellite_image, _ = SatelliteImage.objects.update_or_create(
        land_plot=land_plot,
        source=SatelliteImage.SourceChoices.PLANETARY_COMPUTER,
        scene_id=item.id,
        defaults={
            "acquisition_date": acquisition_date,
            "cloud_cover": cloud_cover,
            "bbox": bbox,
            "ndvi": ndvi_value,
            "features": features,
            "metadata": {
                "collection": item.collection_id,
                "properties": item.properties,
                "assets": list(item.assets.keys()),
                "original_bbox": original_bbox,
                "expanded_bbox": bbox,
                "bbox_expand_factor": DEFAULT_BBOX_EXPAND_FACTOR,
                "min_crop_size_meters": MIN_CROP_SIZE_METERS,
                "preview_size": list(PREVIEW_SIZE),
            },
        },
    )

    filename = f"{land_plot.cadastral_number.replace(':', '_')}_{item.id}.png"
    satellite_image.preview_image.save(filename, preview_content, save=True)

    return satellite_image
