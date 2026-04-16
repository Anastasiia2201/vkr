import json
import os
import tempfile
import time

import requests
from rest_framework import viewsets, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response

from .services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)
from .models import SourceDocument
from .serializers import (
    SourceDocumentSerializer,
    ExtractTextRequestSerializer,
    RentContractLLMTestSerializer,
)
from .services.document_processor import process_source_document
from .services.storage import calculate_file_hash
from .services.text_extractor import extract_text_from_document
from .services.ai.llm_rent_contract_resolver import resolve_rent_contract_with_llm


def to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def extract_text_view(request):
    serializer = ExtractTextRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    uploaded_file = serializer.validated_data["file"]
    force_ocr = serializer.validated_data.get("force_ocr", False)

    original_name = uploaded_file.name or "document.bin"
    suffix = os.path.splitext(original_name)[1] or ".bin"

    temp_path = None
    started_at = time.monotonic()

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        text, ocr_used = extract_text_from_document(
            temp_path,
            force_ocr=force_ocr,
        )

        elapsed = round(time.monotonic() - started_at, 3)

        return Response(
            {
                "status": "ok",
                "text": text,
                "ocr_used": ocr_used,
                "elapsed_seconds": elapsed,
                "text_length": len(text or ""),
            },
            status=status.HTTP_200_OK,
        )
    except Exception as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Ошибка извлечения текста: {exc}",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@api_view(["POST"])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def test_rent_contract_llm_view(request):
    serializer = RentContractLLMTestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    text = serializer.validated_data["text"]
    started_at = time.monotonic()

    try:
        result = resolve_rent_contract_with_llm(text)
        elapsed = round(time.monotonic() - started_at, 3)

        return Response(
            {
                "status": "ok",
                "elapsed_seconds": elapsed,
                "result": result,
            },
            status=status.HTTP_200_OK,
        )
    except requests.Timeout:
        return Response(
            {
                "status": "failed",
                "detail": "LLM не ответила вовремя.",
            },
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except requests.RequestException as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Ошибка обращения к LLM: {exc}",
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Внутренняя ошибка сервера: {exc}",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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


class SourceDocumentViewSet(viewsets.ModelViewSet):
    queryset = SourceDocument.objects.all()
    serializer_class = SourceDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        uploaded_file = request.data.get("file")
        force_reprocess = to_bool(request.data.get("force_reprocess"))

        if uploaded_file is None:
            return Response(
                {"file": ["Это поле обязательно."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        file_hash = calculate_file_hash(uploaded_file)
        existing_document = SourceDocument.objects.filter(file_hash=file_hash).first()

        if existing_document:
            if force_reprocess:
                process_source_document(
                    existing_document.id,
                    force_reprocess=True,
                )
                existing_document.refresh_from_db()

            serializer = self.get_serializer(existing_document)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()

        process_source_document(document.id, force_reprocess=False)
        document.refresh_from_db()

        output_serializer = self.get_serializer(document)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
    