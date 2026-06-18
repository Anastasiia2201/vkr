from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction

from document_processor.models import (
    SourceDocument,
    LandPlot,
    Contract,
    Party,
)
from .re_parser import parse_egrn_document
from .text_extractor import extract_text_from_document
from .storage import move_document_file
from .ai.llm_rent_contract_page_resolver import resolve_rent_contract_by_ocr_pages
from .ai.llm_auction_protocol_resolver import resolve_auction_protocol_with_llm


def detect_document_type(text: str) -> str:
    lower_text = (text or "").lower()

    if "выписка из единого государственного реестра недвижимости" in lower_text:
        return SourceDocument.DocumentType.EGRN

    if "договор" in lower_text and "аренд" in lower_text:
        return SourceDocument.DocumentType.RENT_CONTRACT

    if "протокол" in lower_text and ("аукцион" in lower_text or "торг" in lower_text):
        return SourceDocument.DocumentType.AUCTION_PROTOCOL

    return SourceDocument.DocumentType.UNKNOWN


def get_document_text(document: SourceDocument, force_reprocess: bool) -> tuple[str, bool]:
    if force_reprocess:
        return extract_text_from_document(document.file.path, force_ocr=True)

    if document.text_content:
        return document.text_content, document.ocr_used

    return extract_text_from_document(document.file.path)


def parse_date_safe(value: str | None) -> date | None:
    if not value:
        return None

    value = str(value).strip()
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None


def normalize_inn(value: str | None) -> str | None:
    if not value:
        return None

    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) not in (10, 12):
        return None
    return digits


def normalize_kpp(value: str | None) -> str | None:
    if not value:
        return None

    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 9:
        return None
    return digits


def get_or_create_party(
    name: str | None,
    inn: str | None = None,
    kpp: str | None = None,
    metadata: dict | None = None,
) -> Party | None:
    cleaned_name = normalize_name(name)
    if not cleaned_name:
        return None

    inn = normalize_inn(inn)
    kpp = normalize_kpp(kpp)
    metadata = metadata or {}

    party = None

    if inn:
        party = Party.objects.filter(inn=inn).first()

    if party is None:
        party = Party.objects.filter(name=cleaned_name).first()

    if party is None:
        return Party.objects.create(
            name=cleaned_name,
            inn=inn,
            kpp=kpp,
            metadata=metadata,
        )

    updated = False

    if inn and not party.inn:
        party.inn = inn
        updated = True

    if kpp and not party.kpp:
        party.kpp = kpp
        updated = True

    if metadata:
        merged_metadata = {**(party.metadata or {}), **metadata}
        if merged_metadata != (party.metadata or {}):
            party.metadata = merged_metadata
            updated = True

    if cleaned_name != party.name and len(cleaned_name) > len(party.name or ""):
        party.name = cleaned_name
        updated = True

    if updated:
        party.save()

    return party


def get_or_create_land_plot(
    cadastral_number: str | None,
    *,
    area_hectares: float | None = None,
    location: str | None = None,
    use_type: str | None = None,
    egrn_source_document: SourceDocument | None = None,
) -> LandPlot | None:
    cadastral_number = normalize_name(cadastral_number)
    if not cadastral_number:
        return None

    defaults: dict[str, Any] = {}

    if area_hectares is not None:
        defaults["area_hectares"] = area_hectares

    if location is not None:
        defaults["location"] = location

    if use_type is not None:
        defaults["use_type"] = use_type

    if egrn_source_document is not None:
        defaults["egrn_source_document"] = egrn_source_document

    land_plot, _ = LandPlot.objects.update_or_create(
        cadastral_number=cadastral_number,
        defaults=defaults,
    )
    return land_plot


def extract_subject_cadastral_numbers(subject: dict) -> list[str]:
    """
    Поддерживает и старый формат:
      {"cadastral_number": "..."}
    и возможный будущий:
      {"cadastral_numbers": ["...", "..."]}
    """
    values: list[str] = []

    single_value = subject.get("cadastral_number")
    if single_value:
        values.append(str(single_value).strip())

    multi_value = subject.get("cadastral_numbers")
    if isinstance(multi_value, list):
        values.extend(str(item).strip() for item in multi_value if item)

    # удаляем дубли, сохраняя порядок
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)

    return result


def save_egrn_data(document: SourceDocument, resolved_data: dict) -> None:
    cadastral_number = resolved_data.get("cadastral_number")
    if not cadastral_number:
        return

    get_or_create_land_plot(
        cadastral_number=cadastral_number,
        area_hectares=resolved_data.get("area_hectares"),
        location=resolved_data.get("location"),
        use_type=resolved_data.get("use_type"),
        egrn_source_document=document,
    )


def save_rent_contract_data(document: SourceDocument, rent_data: dict) -> None:
    subject = rent_data.get("subject") or {}
    parties = rent_data.get("parties") or {}
    term = rent_data.get("term") or {}
    rent_payment = rent_data.get("rent_payment") or {}

    cadastral_numbers = extract_subject_cadastral_numbers(subject)
    land_plots: list[LandPlot] = []

    for cadastral_number in cadastral_numbers:
        land_plot = get_or_create_land_plot(
            cadastral_number=cadastral_number,
            area_hectares=subject.get("area_hectares"),
        )
        if land_plot:
            land_plots.append(land_plot)

    lessor = get_or_create_party(
        name=parties.get("lessor_name"),
        inn=parties.get("lessor_inn"),
        kpp=parties.get("lessor_kpp"),
        metadata={
            "address": parties.get("lessor_address"),
            "phone": parties.get("lessor_phone"),
            "email": parties.get("lessor_email"),
        },
    )
    lessee = get_or_create_party(
        name=parties.get("lessee_name"),
        inn=parties.get("lessee_inn"),
        kpp=parties.get("lessee_kpp"),
        metadata={
            "address": parties.get("lessee_address"),
            "phone": parties.get("lessee_phone"),
            "email": parties.get("lessee_email"),
        },
    )

    contract_number = normalize_name(rent_data.get("contract_number")) or ""
    contract_date = parse_date_safe(rent_data.get("contract_date"))

    contract_name = "Договор аренды"
    if contract_number:
        contract_name = f"Договор аренды № {contract_number}"

    contract, _ = Contract.objects.update_or_create(
        source_document=document,
        defaults={
            "contract_kind": Contract.ContractKind.RENT,
            "name": contract_name,
            "contract_number": contract_number,
            "contract_date": contract_date,
            "party_1": lessor,
            "party_2": lessee,
            "metadata": {
                "parties_raw": parties,
                "subject": subject,
                "term": term,
                "rent_payment": rent_payment,
                "party_1_role": "lessor",
                "party_2_role": "lessee",
            },
        },
    )

    if land_plots:
        contract.land_plots.set(land_plots)
    else:
        contract.land_plots.clear()


def save_auction_protocol_data(document: SourceDocument, protocol_data: dict) -> None:
    subject = protocol_data.get("subject") or {}
    result = protocol_data.get("result") or {}

    cadastral_numbers = extract_subject_cadastral_numbers(subject)
    land_plots: list[LandPlot] = []

    for cadastral_number in cadastral_numbers:
        land_plot = get_or_create_land_plot(
            cadastral_number=cadastral_number,
            area_hectares=subject.get("area_hectares"),
            location=subject.get("location"),
        )
        if land_plot:
            land_plots.append(land_plot)

    organizer = get_or_create_party(
        name=protocol_data.get("organizer_name"),
    )
    winner = get_or_create_party(
        name=protocol_data.get("winner_name"),
        inn=protocol_data.get("winner_inn"),
        metadata={
            "participants": protocol_data.get("participants"),
        },
    )

    protocol_number = normalize_name(protocol_data.get("protocol_number")) or ""
    protocol_date = parse_date_safe(protocol_data.get("protocol_date"))

    contract_name = "Протокол торгов"
    if protocol_number:
        contract_name = f"Протокол торгов № {protocol_number}"

    contract, _ = Contract.objects.update_or_create(
        source_document=document,
        defaults={
            "contract_kind": Contract.ContractKind.OTHER,
            "name": contract_name,
            "contract_number": protocol_number,
            "contract_date": protocol_date,
            "party_1": organizer,
            "party_2": winner,
            "metadata": {
                "document_kind": protocol_data.get("document_kind"),
                "auction_form": protocol_data.get("auction_form"),
                "seller_name": protocol_data.get("seller_name"),
                "participants": protocol_data.get("participants") or [],
                "subject": subject,
                "result": result,
                "procedure_number": protocol_data.get("procedure_number"),
                "party_1_role": "organizer",
                "party_2_role": "winner",
            },
        },
    )

    if land_plots:
        contract.land_plots.set(land_plots)
    else:
        contract.land_plots.clear()


def process_egrn_document(document: SourceDocument, text: str) -> None:
    resolved_data = parse_egrn_document(text)

    document.metadata = {
        "detected_document_type": document.document_type,
        "resolved_by": "parse_egrn_document",
        "resolved_data": resolved_data,
    }
    document.save(update_fields=["metadata"])

    save_egrn_data(document, resolved_data)


def process_rent_contract_document(document: SourceDocument, text: str) -> None:
    llm_result = resolve_rent_contract_by_ocr_pages(document)

    rent_data = llm_result.get("parsed") or {}

    document.metadata = {
        **(document.metadata or {}),
        "detected_document_type": document.document_type,
        "resolved_by": "resolve_rent_contract_by_ocr_pages",
        "resolved_data": rent_data,
        "llm_raw": llm_result.get("raw"),
    }
    document.save(update_fields=["metadata"])

    save_rent_contract_data(document, rent_data)


def process_auction_protocol_document(document: SourceDocument, text: str) -> None:
    llm_result = resolve_auction_protocol_with_llm(text)
    protocol_data = llm_result.get("parsed") or {}

    document.metadata = {
        "detected_document_type": document.document_type,
        "resolved_by": "resolve_auction_protocol_with_llm",
        "resolved_data": protocol_data,
        "llm_raw": llm_result.get("raw"),
    }
    document.save(update_fields=["metadata"])

    save_auction_protocol_data(document, protocol_data)


@transaction.atomic
def process_source_document(
    document_id: int,
    force_reprocess: bool = False,
) -> SourceDocument:
    document = SourceDocument.objects.select_for_update().get(pk=document_id)

    if (
        not force_reprocess
        and document.status == SourceDocument.ProcessingStatus.PROCESSED
        and document.text_content
    ):
        return document

    old_document_type = document.document_type

    try:
        text, ocr_used = get_document_text(document, force_reprocess)

        document.text_content = text
        document.ocr_used = ocr_used
        document.document_type = detect_document_type(text)
        document.status = SourceDocument.ProcessingStatus.PROCESSED
        document.save(update_fields=["text_content", "ocr_used", "document_type", "status"])

        if document.document_type == SourceDocument.DocumentType.EGRN:
            process_egrn_document(document, text)

        elif document.document_type == SourceDocument.DocumentType.RENT_CONTRACT:
            process_rent_contract_document(document, text)

        elif document.document_type == SourceDocument.DocumentType.AUCTION_PROTOCOL:
            process_auction_protocol_document(document, text)

        else:
            document.metadata = {
                "detected_document_type": document.document_type,
                "warnings": ["Тип документа не поддерживается."],
            }
            document.save(update_fields=["metadata"])

        if document.document_type != old_document_type:
            move_document_file(document)

    except Exception as exc:
        document.status = SourceDocument.ProcessingStatus.FAILED
        document.metadata = {
            **(document.metadata or {}),
            "error": str(exc),
        }
        document.save(update_fields=["status", "metadata"])

    return document
