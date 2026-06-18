from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    SourceDocumentViewSet,
    cadastral_location_view,
    document_ocr_view,
    document_ocr_result_view,
    document_analyze_view,
    document_analysis_result_view,
    document_upload_base64_view,
    document_preview_pages_view,
    document_ocr_start_view,
    document_analyze_start_view,
    task_status_view
)

router = DefaultRouter()
router.register("documents", SourceDocumentViewSet, basename="source-document")

urlpatterns = [
    path(
        "cadastral/<str:cadastral_number>/location/",
        cadastral_location_view,
        name="cadastral-location",
    ),
    path(
        "documents/<int:document_id>/ocr/",
        document_ocr_view,
        name="document-ocr",
    ),
    path(
        "documents/<int:document_id>/ocr-result/",
        document_ocr_result_view,
        name="document-ocr-result",
    ),
    path(
        "documents/<int:document_id>/analyze/",
        document_analyze_view,
        name="document-analyze",
    ),
    path(
        "documents/<int:document_id>/analysis-result/",
        document_analysis_result_view,
        name="document-analysis-result",
    ),
    path(
        "documents/upload-base64/",
        document_upload_base64_view,
        name="document-upload-base64",
    ),
    path(
        "documents/<int:document_id>/preview-pages/",
        document_preview_pages_view,
        name="document-preview-pages",
    ),
    path(
        "documents/<int:document_id>/ocr/start/",
        document_ocr_start_view,
        name="document-ocr-start",
    ),
    path(
        "tasks/<str:task_id>/status/",
        task_status_view,
        name="task-status",
    ),
    path(
        "documents/<int:document_id>/analyze/start/",
        document_analyze_start_view,
        name="document-analyze-start",
    ),
    ]

urlpatterns += router.urls
