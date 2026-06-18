from __future__ import annotations
from datetime import date, timedelta

from pathlib import Path
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier
from django.conf import settings
from django.db import transaction

from document_processor.models import LandPlot
from satellite_processor.models import SatelliteImage
from satellite_processor.services.planetary import (
    PlanetaryError,
    save_planetary_preview,
)


MODEL_VERSION = "catboost_v1"


MODEL_PATH = Path(settings.BASE_DIR) / "ml_models" / "land_plot_catboost.cbm"

EXCLUDED_FEATURES = {
    "cloud_cover",
    "area_hectares",
    "land_category",
    "use_type",
}


class ClassificationError(Exception):
    pass


_model_cache: CatBoostClassifier | None = None


def get_model() -> CatBoostClassifier:
    global _model_cache

    if _model_cache is not None:
        return _model_cache

    if not MODEL_PATH.exists():
        raise ClassificationError(
            f"Файл модели не найден: {MODEL_PATH}"
        )

    model = CatBoostClassifier()
    model.load_model(str(MODEL_PATH))
    _model_cache = model
    return model


def build_feature_row(satellite_image: SatelliteImage) -> pd.DataFrame:
    """
    Собирает один объект признаков в том же формате,
    в каком модель обучалась на dataset.json.
    """
    row: dict[str, Any] = {
        "ndvi": satellite_image.ndvi,
    }

    features = satellite_image.features or {}
    row.update(features)

    for feature_name in EXCLUDED_FEATURES:
        row.pop(feature_name, None)

    return pd.DataFrame([row])


def predict_satellite_image_class(satellite_image: SatelliteImage) -> str:
    if satellite_image.ndvi is None:
        raise ClassificationError("У SatelliteImage отсутствует ndvi.")

    if not satellite_image.features:
        raise ClassificationError("У SatelliteImage отсутствуют features.")

    model = get_model()
    X = build_feature_row(satellite_image)

    prediction = model.predict(X)

    if hasattr(prediction, "tolist"):
        prediction = prediction.tolist()

    try:
        predicted_class = prediction[0][0]
    except (IndexError, TypeError):
        raise ClassificationError(
            f"Не удалось разобрать предсказание модели: {prediction}"
        )

    return str(predicted_class)


@transaction.atomic
def classify_satellite_image(satellite_image: SatelliteImage) -> SatelliteImage:
    predicted_class = predict_satellite_image_class(satellite_image)

    satellite_image.predicted_class = predicted_class
    satellite_image.save(update_fields=["predicted_class"])

    return satellite_image


def get_closest_warm_date(today: date | None = None) -> date:
    """
    Возвращает ближайшую дату в теплый сезон (май–сентябрь).
    """
    today = today or date.today()
    if 5 <= today.month <= 9:
        return today

    if today.month >= 10:
        return date(today.year, 9, 30)

    return date(today.year - 1, 9, 30)


@transaction.atomic
def classify_land_plot_by_cadastral_number(
    cadastral_number: str,
    start_date=None,
    end_date=None,
    max_cloud_cover: float | None = 20.0,
    max_snow_ice_percentage: float | None = 20.0,
) -> SatelliteImage:
    """
    1. Находит участок по кадастровому номеру
    2. Получает/обновляет спутниковый снимок
    3. Классифицирует снимок
    4. Сохраняет predicted_class в SatelliteImage
    """
    try:
        land_plot = LandPlot.objects.get(cadastral_number=cadastral_number)
    except LandPlot.DoesNotExist as exc:
        raise ClassificationError(
            f"Участок с кадастровым номером {cadastral_number} не найден."
        ) from exc

    satellite_image = SatelliteImage.objects.filter(
        land_plot=land_plot,
        ndvi__isnull=False,
    ).exclude(
        features={}
    ).order_by(
        "-acquisition_date",
        "-created_at",
    ).first()

    if satellite_image is None:
        try:
            target_date = get_closest_warm_date()
            start_date = target_date - timedelta(days=10)
            end_date = target_date + timedelta(days=10)

            satellite_image = save_planetary_preview(
                land_plot=land_plot,
                start_date=start_date,
                end_date=end_date,
                max_cloud_cover=max_cloud_cover,
                max_snow_ice_percentage=max_snow_ice_percentage,
            )
        except PlanetaryError as exc:
            raise ClassificationError(str(exc)) from exc

    return classify_satellite_image(satellite_image)
