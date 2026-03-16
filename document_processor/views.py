import json

from rest_framework import viewsets, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)
from .models import SourceDocument
from .serializers import SourceDocumentSerializer
from .services.document_processor import process_source_document


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


class SourceDocumentViewSet(viewsets.ModelViewSet):
    queryset = SourceDocument.objects.all()
    serializer_class = SourceDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()

        process_source_document(document.id)

        document.refresh_from_db()
        output_serializer = self.get_serializer(document)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
    