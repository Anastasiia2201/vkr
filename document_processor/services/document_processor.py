from django.utils import timezone

from document_processor.models import SourceDocument, LandPlot, LandCategory
from .re_parser import parse_auction_protocol, parse_egrn_document
from .text_extractor import extract_text_from_document


def detect_document_type(text: str) -> str:
    lower_text = text.lower()

    if "выписка из единого государственного реестра недвижимости" in lower_text:
        return SourceDocument.DocumentType.EGRN

    if "протокол" in lower_text and "аукцион" in lower_text:
        return SourceDocument.DocumentType.AUCTION_PROTOCOL

    if "протокол" in lower_text and "торг" in lower_text:
        return SourceDocument.DocumentType.AUCTION_PROTOCOL

    if "договор купли-продажи" in lower_text:
        return SourceDocument.DocumentType.SALE_CONTRACT

    return SourceDocument.DocumentType.UNKNOWN


def process_source_document(document_id: int) -> SourceDocument:
    document = SourceDocument.objects.get(pk=document_id)

    try:
        extracted_text, ocr_used = extract_text_from_document(document.file.path)

        document.text_content = extracted_text
        document.ocr_used = ocr_used

        if not document.document_type or document.document_type == SourceDocument.DocumentType.UNKNOWN:
            document.document_type = detect_document_type(extracted_text)

        parsed_data = {}

        if document.document_type == SourceDocument.DocumentType.EGRN:
            parsed_data = parse_egrn_document(extracted_text)
            save_egrn_data(document, parsed_data)

        elif document.document_type == SourceDocument.DocumentType.AUCTION_PROTOCOL:
            parsed_data = parse_auction_protocol(extracted_text)

        document.metadata = parsed_data
        document.status = SourceDocument.ProcessingStatus.PROCESSED
        document.confidence = parsed_data.get("confidence")
        document.save()

    except Exception as exc:
        document.status = SourceDocument.ProcessingStatus.FAILED
        document.metadata = {
            **document.metadata,
            "error": str(exc),
        }
        document.save()

    return document


def save_egrn_data(document: SourceDocument, parsed_data: dict) -> None:
    cadastral_number = parsed_data.get("cadastral_number")
    if not cadastral_number:
        return

    land_category_name = parsed_data.get("land_category")
    land_category = None

    if land_category_name:
        land_category, _ = LandCategory.objects.get_or_create(
            name=land_category_name
        )

    land_plot, _ = LandPlot.objects.update_or_create(
        cadastral_number=cadastral_number,
        defaults={
            "area_hectares": parsed_data.get("area_hectares"),
            "location": parsed_data.get("location", ""),
            "land_category": land_category,
            "use_type": parsed_data.get("use_type"),
            "egrn_source_document": document,
        }
    )
