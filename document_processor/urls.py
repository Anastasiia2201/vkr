from django.urls import path
from rest_framework.routers import DefaultRouter

from document_processor.views import (
    cadastral_location_view,
    SourceDocumentViewSet,
)

router = DefaultRouter()
router.register("documents", SourceDocumentViewSet, basename="source-document")

urlpatterns = [
    path(
        "cadastral/<str:cadastral_number>/location/",
        cadastral_location_view,
        name="cadastral-location",
    ),
]

urlpatterns += router.urls
