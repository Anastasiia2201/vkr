from __future__ import annotations

import time

from celery import shared_task

from document_processor.models import SourceDocument
from document_processor.services.ocr import extract_text_with_paddle_ocr_for_document
from document_processor.services.document_processor import (
    detect_document_type,
    save_rent_contract_data,
    save_auction_protocol_data,
    save_egrn_data,
)
from document_processor.services.re_parser import parse_egrn_document
from document_processor.services.ai.llm_rent_contract_page_resolver import (
    resolve_rent_contract_by_ocr_pages,
)
from document_processor.services.ai.llm_auction_protocol_page_resolver import (
    resolve_auction_protocol_by_ocr_pages,
)


@shared_task(bind=True)
def run_ocr_task(self, document_id: int, force_ocr: bool = False) -> dict:
    document = SourceDocument.objects.get(id=document_id)

    from_cache = False
    ocr_metadata = {}

    if document.text_content and not force_ocr:
        text = document.text_content
        ocr_used = document.ocr_used
        text_source = (document.metadata or {}).get("text_source", "cache")
        from_cache = True

    else:
        text = ""

        # 1. Сначала пробуем текстовый слой PDF,
        # если пользователь не нажал "принудительно OCR"
        if not force_ocr:
            from document_processor.services.text_extractor import extract_text_layer
            from document_processor.services.ocr import is_text_bad

            text_layer = extract_text_layer(document.file.path)

            if text_layer and not is_text_bad(text_layer) and len(text_layer) > 500:
                text = text_layer
                ocr_used = False
                text_source = "pdf_text_layer"

        # 2. Если текстового слоя нет или он плохой — запускаем OCR,
        # но обязательно через функцию для SourceDocument
        if not text:
            text, ocr_metadata, from_cache = extract_text_with_paddle_ocr_for_document(
                document=document,
                force_ocr=force_ocr,
            )

            ocr_used = True
            text_source = "ocr"

    document.text_content = text
    document.ocr_used = ocr_used
    document.status = SourceDocument.ProcessingStatus.PROCESSED

    if (
        not document.document_type
        or document.document_type == SourceDocument.DocumentType.UNKNOWN
    ):
        document.document_type = detect_document_type(text)

    document.metadata = {
        **(document.metadata or {}),
        "text_source": text_source,
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

    return {
        "status": "ok",
        "document_id": document.id,
        "document_type": document.document_type,
        "ocr_used": ocr_used,
        "ocr_from_cache": from_cache,
        "text_source": text_source,
        "text_length": len(text or ""),
    }


@shared_task(bind=True)
def run_ai_analysis_task(self, document_id: int) -> dict:
    started_at = time.monotonic()

    document = SourceDocument.objects.get(id=document_id)

    if not document.text_content:
        raise ValueError("Сначала нужно извлечь текст документа.")

    if (
        not document.document_type
        or document.document_type == SourceDocument.DocumentType.UNKNOWN
    ):
        document.document_type = detect_document_type(document.text_content or "")
        document.save(update_fields=["document_type"])

    if document.document_type == SourceDocument.DocumentType.RENT_CONTRACT:
        llm_result = resolve_rent_contract_by_ocr_pages(document)
        resolved_data = llm_result.get("parsed") or {}
        resolved_by = "LLM: договор аренды"

        save_rent_contract_data(document, resolved_data)

    elif document.document_type == SourceDocument.DocumentType.AUCTION_PROTOCOL:
        llm_result = resolve_auction_protocol_by_ocr_pages(document)
        resolved_data = llm_result.get("parsed") or {}
        resolved_by = "LLM: протокол торгов"

        save_auction_protocol_data(document, resolved_data)

    elif document.document_type == SourceDocument.DocumentType.EGRN:
        # ВАЖНО: для ЕГРН LLM не вызываем
        resolved_data = parse_egrn_document(document.text_content or "")
        resolved_by = "Парсер ЕГРН"

        save_egrn_data(document, resolved_data)

    else:
        raise ValueError(
            f"Для типа документа {document.document_type} анализ не поддерживается."
        )

    document.metadata = {
        **(document.metadata or {}),
        "resolved_by": resolved_by,
        "resolved_data": resolved_data,
    }

    document.status = SourceDocument.ProcessingStatus.PROCESSED
    document.save(update_fields=["metadata", "status"])

    return {
        "status": "ok",
        "document_id": document.id,
        "document_type": document.document_type,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "resolved_by": resolved_by,
        "resolved_data": resolved_data,
    }
