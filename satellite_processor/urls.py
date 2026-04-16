from django.urls import path

from .views import (
    fetch_satellite_preview_view,
    satellite_images_by_cadastral_number_view,
    classify_land_plot_view,
    satellite_preview_light_view

)

urlpatterns = [
    path(
        "preview-light/<str:cadastral_number>/",
        satellite_preview_light_view,
        name="satellite-preview-light",
    ),
    path(
        "preview/<str:cadastral_number>/",
        fetch_satellite_preview_view,
        name="satellite-preview",
    ),
    path(
        "images/<str:cadastral_number>/",
        satellite_images_by_cadastral_number_view,
        name="satellite-images-by-cadastral-number",
    ),
    path(
        "classify/<str:cadastral_number>/",
        classify_land_plot_view,
        name="satellite-classify",
    ),
]
