import json

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)


@api_view(["GET"])
def cadastral_location_view(request, cadastral_number: str):
    try:
        location = fetch_location_by_cadastral_number(cadastral_number)

        return Response(
            {
                "cadastral_number": location.cadastral_number,
                "address": location.address,
                "center_lat": location.center_lat,
                "center_lon": location.center_lon,
                "geometry": (
                    json.loads(location.geometry.geojson)
                    if location.geometry
                    else None
                ),
            },
            status=status.HTTP_200_OK,
        )

    except RosreestrError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as exc:
        return Response(
            {"detail": f"Внутренняя ошибка сервера: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
