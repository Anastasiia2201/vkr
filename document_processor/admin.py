# document_processor/admin.py

import json

from django.contrib import admin
from django.utils.html import format_html

from .models import SourceDocument, LandPlot, Party, Contract


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "document_type",
        "status",
        "ocr_used",
        "created_at",
    )
    list_filter = (
        "document_type",
        "status",
        "ocr_used",
        "created_at",
    )
    search_fields = (
        "original_filename",
        "text_content",
        "file_hash",
    )
    readonly_fields = (
        "file_hash",
        "text_content",
        "ocr_result_dir",
        "pretty_metadata",
        "created_at",
    )

    fieldsets = (
        ("Основная информация", {
            "fields": (
                "file",
                "original_filename",
                "document_type",
                "status",
                "ocr_used",
                "created_at",
            )
        }),
        ("Результаты обработки", {
            "fields": (
                "text_content",
                "ocr_result_dir",
                "pretty_metadata",
            )
        }),
        ("Технические данные", {
            "fields": (
                "file_hash",
            )
        }),
    )

    def pretty_metadata(self, obj):
        data = json.dumps(
            obj.metadata or {},
            ensure_ascii=False,
            indent=2,
        )
        return format_html(
            "<pre style='white-space: pre-wrap; font-size: 12px;'>{}</pre>",
            data,
        )

    pretty_metadata.short_description = "Метаданные обработки"


@admin.register(LandPlot)
class LandPlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cadastral_number",
        "area_hectares",
        "short_location",
        "use_type",
        "egrn_source_document",
        "created_at",
    )
    search_fields = (
        "cadastral_number",
        "location",
        "use_type",
    )
    list_filter = (
        "use_type",
        "created_at",
    )
    readonly_fields = (
        "created_at",
    )

    def short_location(self, obj):
        if not obj.location:
            return "-"
        return obj.location[:80] + "..." if len(obj.location) > 80 else obj.location

    short_location.short_description = "Местоположение"


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "inn",
        "kpp",
        "created_at",
    )
    search_fields = (
        "name",
        "inn",
        "kpp",
    )
    readonly_fields = (
        "created_at",
    )


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "contract_kind",
        "contract_number",
        "contract_date",
        "source_document",
        "created_at",
    )
    list_filter = (
        "contract_kind",
        "contract_date",
        "created_at",
    )
    search_fields = (
        "name",
        "contract_number",
        "source_document__original_filename",
    )
    filter_horizontal = (
        "land_plots",
    )
    readonly_fields = (
        "created_at",
    )