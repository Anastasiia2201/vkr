from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    SourceDocumentViewSet,
    cadastral_location_view,
    extract_text_view,
    test_rent_contract_llm_view,
)

router = DefaultRouter()
router.register("documents", SourceDocumentViewSet, basename="source-document")

urlpatterns = [
    path(
        "cadastral/<str:cadastral_number>/location/",
        cadastral_location_view,
        name="cadastral-location",
    ),
    path("documents/extract-text/", extract_text_view, name="extract-text"),
    path("llm/rent-contract/resolve/", test_rent_contract_llm_view, name="llm-rent-contract-resolve"),
]

urlpatterns += router.urls
