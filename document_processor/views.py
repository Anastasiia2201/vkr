from django.http import JsonResponse
from django.views.decorators.http import require_GET

from document_processor.services.rosreestr import (
    RosreestrError,
    RosreestrNotFoundError,
    fetch_location_by_cadastral_number,
)


@require_GET
def cadastral_location_view(request, cadastral_number: str) -> JsonResponse:
    try:
        location = fetch_location_by_cadastral_number(cadastral_number)
    except RosreestrNotFoundError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    except RosreestrError as exc:
        return JsonResponse({"detail": str(exc)}, status=502)

    return JsonResponse(
        {
            "cadastral_number": location.cadastral_number,
            "address": location.address,
            "center": {
                "lat": location.center_lat,
                "lon": location.center_lon,
            },
            "geometry": location.geometry.geojson if location.geometry else None,
        }
    )
