import json
from pathlib import Path
from django.conf import settings
import time
import requests

from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from celery.result import AsyncResult
from geocontrol.celery import app as celery_app

from .tasks import (run_ocr_task,
                    run_ai_analysis_task)
from .services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)
from .services.document_preview import build_document_page_previews
from .models import SourceDocument
from .serializers import (
    SourceDocumentSerializer,
    SourceDocumentBase64UploadSerializer
)
from .services.storage import calculate_file_hash
from .services.ai.llm_rent_contract_page_resolver import (
    resolve_rent_contract_by_ocr_pages,
)
from .services.ai.llm_auction_protocol_page_resolver import (
    resolve_auction_protocol_by_ocr_pages,
)
from .services.re_parser import parse_egrn_document
from .services.document_processor import (
    save_rent_contract_data,
    save_auction_protocol_data,
    save_egrn_data,
    process_source_document
)
from .services.ocr import extract_text_with_paddle_ocr_for_document


def to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@api_view(["POST"])
def document_ocr_view(request, document_id: int):
    force_ocr = to_bool(request.data.get("force_ocr"))

    started_at = time.monotonic()

    try:
        document = SourceDocument.objects.get(id=document_id)

        text, ocr_metadata, from_cache = extract_text_with_paddle_ocr_for_document(
            document=document,
            force_ocr=force_ocr,
        )

        document.text_content = text
        document.ocr_used = True
        document.status = SourceDocument.ProcessingStatus.PROCESSED

        if not document.document_type or document.document_type == SourceDocument.DocumentType.UNKNOWN:
            from .services.document_processor import detect_document_type
            document.document_type = detect_document_type(text)

        document.metadata = {
            **(document.metadata or {}),
            "ocr": ocr_metadata,
        }

        document.save(
            update_fields=[
                "text_content",
                "ocr_used",
                "document_type",
                "status",
                "metadata",
            ]
        )

        elapsed = round(time.monotonic() - started_at, 3)

        return Response(
            {
                "status": "ok",
                "document_id": document.id,
                "document_type": document.document_type,
                "ocr_from_cache": from_cache,
                "ocr_result_dir": document.ocr_result_dir,
                "elapsed_seconds": elapsed,
                "text_length": len(text or ""),
                "ocr_metadata": ocr_metadata,
            },
            status=status.HTTP_200_OK,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Ошибка OCR: {exc}",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
def document_ocr_result_view(request, document_id: int):
    try:
        document = SourceDocument.objects.get(id=document_id)

        metadata = document.metadata or {}

        if document.text_content:
            return Response(
                {
                    "status": "ok",
                    "document_id": document.id,
                    "document_type": document.document_type,
                    "ocr_result_dir": getattr(document, "ocr_result_dir", ""),
                    "text": document.text_content,
                    "text_length": len(document.text_content or ""),
                    "ocr_used": document.ocr_used,
                    "text_source": metadata.get("text_source"),
                    "pages_metadata": metadata.get("ocr", {}).get("pages", []),
                },
                status=status.HTTP_200_OK,
            )

        if getattr(document, "ocr_result_dir", ""):
            result_dir = Path(settings.MEDIA_ROOT) / document.ocr_result_dir
            combined_path = result_dir / "combined_text.txt"
            pages_path = result_dir / "pages.json"

            if combined_path.exists():
                text = combined_path.read_text(encoding="utf-8")

                pages_metadata = {}
                if pages_path.exists():
                    try:
                        pages_metadata = json.loads(
                            pages_path.read_text(encoding="utf-8")
                        )
                    except json.JSONDecodeError:
                        pages_metadata = {}

                return Response(
                    {
                        "status": "ok",
                        "document_id": document.id,
                        "document_type": document.document_type,
                        "ocr_result_dir": document.ocr_result_dir,
                        "text": text,
                        "text_length": len(text),
                        "ocr_used": document.ocr_used,
                        "text_source": metadata.get("text_source", "ocr"),
                        "pages_metadata": pages_metadata,
                    },
                    status=status.HTTP_200_OK,
                )

        return Response(
            {
                "status": "failed",
                "document_id": document.id,
                "detail": "Для документа ещё нет извлечённого текста.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Ошибка получения текста документа: {exc}",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
def document_analyze_view(request, document_id: int):
    started_at = time.monotonic()

    try:
        document = SourceDocument.objects.get(id=document_id)

        if not document.text_content and not document.ocr_result_dir:
            return Response(
                {
                    "status": "failed",
                    "detail": "Сначала нужно выполнить OCR документа.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if document.document_type == SourceDocument.DocumentType.UNKNOWN:
            from .services.document_processor import detect_document_type

            document.document_type = detect_document_type(document.text_content or "")
            document.save(update_fields=["document_type"])

        if document.document_type == SourceDocument.DocumentType.RENT_CONTRACT:
            llm_result = resolve_rent_contract_by_ocr_pages(document)
            resolved_data = llm_result.get("parsed") or {}
            resolved_by = "resolve_rent_contract_by_ocr_pages"
            raw = llm_result.get("raw")

            save_rent_contract_data(document, resolved_data)

        elif document.document_type == SourceDocument.DocumentType.AUCTION_PROTOCOL:
            llm_result = resolve_auction_protocol_by_ocr_pages(document)
            resolved_data = llm_result.get("parsed") or {}
            resolved_by = "resolve_auction_protocol_by_ocr_pages"
            raw = llm_result.get("raw")

            save_auction_protocol_data(document, resolved_data)

        elif document.document_type == SourceDocument.DocumentType.EGRN:
            resolved_data = parse_egrn_document(document.text_content or "")
            resolved_by = "parse_egrn_document"
            raw = None

            save_egrn_data(document, resolved_data)

        else:
            return Response(
                {
                    "status": "failed",
                    "document_id": document.id,
                    "document_type": document.document_type,
                    "detail": "Для данного типа документа анализ не поддерживается.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        document.metadata = {
            **(document.metadata or {}),
            "resolved_by": resolved_by,
            "resolved_data": resolved_data,
            "llm_raw": raw,
        }
        document.status = SourceDocument.ProcessingStatus.PROCESSED
        document.save(update_fields=["metadata", "status"])

        elapsed = round(time.monotonic() - started_at, 3)

        return Response(
            {
                "status": "ok",
                "document_id": document.id,
                "document_type": document.document_type,
                "elapsed_seconds": elapsed,
                "resolved_by": resolved_by,
                "resolved_data": resolved_data,
                "raw": raw,
            },
            status=status.HTTP_200_OK,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
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

        document.refresh_from_db()

        output_serializer = self.get_serializer(document)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def document_upload_base64_view(request):
    serializer = SourceDocumentBase64UploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    document = serializer.save()

    output_serializer = SourceDocumentSerializer(
        document,
        context={"request": request},
    )

    return Response(output_serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def document_preview_pages_view(request, document_id: int):
    try:
        document = SourceDocument.objects.get(id=document_id)

        force = to_bool(request.query_params.get("force"))
        max_pages_raw = request.query_params.get("max_pages")

        try:
            max_pages = int(max_pages_raw) if max_pages_raw else 10
        except ValueError:
            max_pages = 10

        pages = build_document_page_previews(
            document=document,
            force=force,
            max_pages=max_pages,
        )

        result_pages = []

        for page in pages:
            image_path = page["image_path"]

            image_url = request.build_absolute_uri(
                settings.MEDIA_URL + image_path.replace("\\", "/")
            )

            result_pages.append(
                {
                    "page": page["page"],
                    "image_path": image_path,
                    "image_url": image_url,
                }
            )

        return Response(
            {
                "status": "ok",
                "document_id": document.id,
                "pages_count": len(result_pages),
                "pages": result_pages,
            },
            status=status.HTTP_200_OK,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as exc:
        return Response(
            {
                "status": "failed",
                "detail": f"Ошибка формирования preview: {exc}",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
def document_ocr_start_view(request, document_id: int):
    try:
        SourceDocument.objects.get(id=document_id)

        force_ocr = to_bool(request.data.get("force_ocr", False))

        task = run_ocr_task.delay(document_id, force_ocr)

        return Response(
            {
                "status": "started",
                "document_id": document_id,
                "task_id": task.id,
                "message": "Извлечение текста запущено.",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["GET"])
def task_status_view(request, task_id: str):
    task = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "state": task.state,
    }

    if task.state == "PENDING":
        response["status"] = "pending"
        response["message"] = "Задача ожидает выполнения."

    elif task.state == "STARTED":
        response["status"] = "processing"
        response["message"] = "Задача выполняется."

    elif task.state == "SUCCESS":
        response["status"] = "done"
        response["message"] = "Задача выполнена."
        response["result"] = task.result

    elif task.state == "FAILURE":
        response["status"] = "failed"
        response["message"] = "Ошибка выполнения задачи."
        response["error"] = str(task.result)

    else:
        response["status"] = task.state.lower()
        response["message"] = "Состояние задачи: " + task.state

    return Response(response)


@api_view(["POST"])
def document_analyze_start_view(request, document_id: int):
    try:
        SourceDocument.objects.get(id=document_id)

        task = run_ai_analysis_task.delay(document_id)

        return Response(
            {
                "status": "started",
                "document_id": document_id,
                "task_id": task.id,
                "message": "AI-анализ запущен.",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["GET"])
def document_analysis_result_view(request, document_id: int):
    try:
        document = SourceDocument.objects.get(id=document_id)

        metadata = document.metadata or {}
        resolved_data = metadata.get("resolved_data")

        if not resolved_data:
            return Response(
                {
                    "status": "failed",
                    "detail": "Результат AI-анализа для документа ещё не найден.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "status": "ok",
                "document_id": document.id,
                "document_type": document.document_type,
                "resolved_by": metadata.get("resolved_by"),
                "resolved_data": resolved_data,
            },
            status=status.HTTP_200_OK,
        )

    except SourceDocument.DoesNotExist:
        return Response(
            {
                "status": "failed",
                "detail": f"Документ с id={document_id} не найден.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )
