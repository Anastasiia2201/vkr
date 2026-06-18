import json

from django.contrib import admin
from django.utils.html import format_html

from .models import SatelliteImage


@admin.register(SatelliteImage)
class SatelliteImageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "land_plot",
        "source",
        "scene_id",
        "acquisition_date",
        "cloud_cover",
        "ndvi",
        "predicted_class",
        "created_at",
    )

    list_filter = (
        "source",
        "predicted_class",
        "acquisition_date",
        "created_at",
    )

    search_fields = (
        "land_plot__cadastral_number",
        "scene_id",
    )

    readonly_fields = (
        "pretty_features",
        "pretty_metadata",
        "created_at",
    )

    def pretty_features(self, obj):
        data = json.dumps(obj.features or {}, ensure_ascii=False, indent=2)
        return format_html(
            "<pre style='white-space: pre-wrap; font-size: 12px;'>{}</pre>",
            data,
        )

    pretty_features.short_description = "Признаки"

    def pretty_metadata(self, obj):
        data = json.dumps(obj.metadata or {}, ensure_ascii=False, indent=2)
        return format_html(
            "<pre style='white-space: pre-wrap; font-size: 12px;'>{}</pre>",
            data,
        )

    pretty_metadata.short_description = "Метаданные"