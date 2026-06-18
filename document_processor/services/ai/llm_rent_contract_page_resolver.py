from __future__ import annotations

import time

from .llm_page_utils import (
    MODEL_NAME,
    call_ollama,
    read_ocr_pages,
    first_not_empty,
    save_llm_results,
)

MAX_PAGE_TEXT_CHARS = 6000


def build_page_prompt(page_text: str, page_number: int) -> list[dict]:
    page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    return [
        {
            "role": "system",
            "content": (
                "Ты извлекаешь данные из одной страницы OCR/Markdown текста договора аренды земельного участка. "
                "Страница может содержать только часть договора. "
                "Верни только валидный JSON. "
                "Не добавляй пояснения, Markdown или текст вне JSON. "
                "Не используй китайский язык. "
                "Если данных на этой странице нет, верни null."
            ),
        },
        {
            "role": "user",
            "content": f"""
Это страница {page_number} договора аренды.

Найди только те данные, которые явно есть на этой странице.

Верни JSON строго по схеме:

{{
  "page": {page_number},
  "contract_number": null,
  "contract_date": null,
  "parties": {{
    "lessor_name": null,
    "lessee_name": null
  }},
  "subject": {{
    "cadastral_number": null,
    "area": null,
    "subject_text": null
  }},
  "term": {{
    "start_date": null,
    "end_date": null
  }},
  "rent_payment": {{
    "rent_amount": null,
    "payment_period": null
  }},
  "party_details": {{
    "lessor": {{
      "inn": null,
      "kpp": null,
      "ogrn": null,
      "legal_address": null,
      "phone": null
    }},
    "lessee": {{
      "inn": null,
      "kpp": null,
      "ogrn": null,
      "legal_address": null,
      "phone": null
    }}
  }}
}}

Правила:
1. Не выдумывай данные.
2. Даты верни в формате YYYY-MM-DD, если можешь определить.
3. Если значение не найдено на странице — null.
4. Ответ должен быть только JSON.

Текст страницы:
\"\"\"{page_text}\"\"\"
""",
        },
    ]


def merge_partial_results(page_results: list[dict]) -> dict:
    merged = {
        "contract_number": None,
        "contract_date": None,
        "parties": {
            "lessor_name": None,
            "lessee_name": None,
        },
        "subject": {
            "cadastral_number": None,
            "area": None,
            "subject_text": None,
        },
        "term": {
            "start_date": None,
            "end_date": None,
        },
        "rent_payment": {
            "rent_amount": None,
            "payment_period": None,
        },
        "party_details": {
            "lessor": {
                "inn": None,
                "kpp": None,
                "ogrn": None,
                "legal_address": None,
                "phone": None,
            },
            "lessee": {
                "inn": None,
                "kpp": None,
                "ogrn": None,
                "legal_address": None,
                "phone": None,
            },
        },
        "notes": [],
        "pages": page_results,
    }

    for item in page_results:
        if not isinstance(item, dict):
            continue

        merged["contract_number"] = first_not_empty(
            merged["contract_number"],
            item.get("contract_number"),
        )
        merged["contract_date"] = first_not_empty(
            merged["contract_date"],
            item.get("contract_date"),
        )

        parties = item.get("parties") or {}
        merged["parties"]["lessor_name"] = first_not_empty(
            merged["parties"]["lessor_name"],
            parties.get("lessor_name"),
        )
        merged["parties"]["lessee_name"] = first_not_empty(
            merged["parties"]["lessee_name"],
            parties.get("lessee_name"),
        )

        subject = item.get("subject") or {}
        merged["subject"]["cadastral_number"] = first_not_empty(
            merged["subject"]["cadastral_number"],
            subject.get("cadastral_number"),
        )
        merged["subject"]["area"] = first_not_empty(
            merged["subject"]["area"],
            subject.get("area"),
        )
        merged["subject"]["subject_text"] = first_not_empty(
            merged["subject"]["subject_text"],
            subject.get("subject_text"),
        )

        term = item.get("term") or {}
        merged["term"]["start_date"] = first_not_empty(
            merged["term"]["start_date"],
            term.get("start_date"),
        )
        merged["term"]["end_date"] = first_not_empty(
            merged["term"]["end_date"],
            term.get("end_date"),
        )

        rent_payment = item.get("rent_payment") or {}
        merged["rent_payment"]["rent_amount"] = first_not_empty(
            merged["rent_payment"]["rent_amount"],
            rent_payment.get("rent_amount"),
        )
        merged["rent_payment"]["payment_period"] = first_not_empty(
            merged["rent_payment"]["payment_period"],
            rent_payment.get("payment_period"),
        )

        party_details = item.get("party_details") or {}

        for role in ("lessor", "lessee"):
            details = party_details.get(role) or {}

            for field in ("inn", "kpp", "ogrn", "legal_address", "phone"):
                merged["party_details"][role][field] = first_not_empty(
                    merged["party_details"][role][field],
                    details.get(field),
                )

        notes = item.get("notes")
        if isinstance(notes, list):
            for note in notes:
                if note and note not in merged["notes"]:
                    merged["notes"].append(note)

    return merged


def resolve_rent_contract_by_ocr_pages(document) -> dict:
    """
    Читает сохранённые OCR-страницы и отправляет каждую страницу в LLM.
    Никакой проверки релевантности страницы нет.
    Пропускаются только полностью пустые страницы.
    """
    started = time.monotonic()

    pages = read_ocr_pages(document)

    if not pages:
        raise ValueError(
            "OCR-страницы не найдены. Сначала нужно выполнить OCR документа."
        )

    page_results: list[dict] = []
    skipped_pages: list[dict] = []

    for page in pages:
        page_number = page["page"]
        page_text = page["text"]

        if not page_text.strip():
            skipped_pages.append(
                {
                    "page": page_number,
                    "reason": "empty_text",
                    "text_length": page.get("text_length"),
                }
            )
            continue

        messages = build_page_prompt(page_text, page_number)
        result = call_ollama(messages)

        page_results.append(result)

    merged = merge_partial_results(page_results)

    raw = {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "model": MODEL_NAME,
        "pages_total": len(pages),
        "pages_sent_to_llm": len(page_results),
        "skipped_pages": skipped_pages,
        "page_results": page_results,
    }

    paths = save_llm_results(
        document,
        raw=raw,
        parsed=merged,
        prefix="rent_contract",
    )

    raw.update(paths)

    return {
        "raw": raw,
        "parsed": merged,
    }
