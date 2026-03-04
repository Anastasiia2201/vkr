from django.urls import path

from document_processor.views import cadastral_location_view

urlpatterns = [
    path(
        "cadastral/<str:cadastral_number>/location/",
        cadastral_location_view,
        name="cadastral-location",
    ),
]
