from __future__ import annotations

import time

from .llm_page_utils import (
    MODEL_NAME,
    call_ollama,
    read_ocr_pages,
    first_not_empty,
    merge_lists,
    save_llm_results,
)


MAX_PAGE_TEXT_CHARS = 6000


def build_page_prompt(page_text: str, page_number: int) -> list[dict]:
    page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    return [
        {
            "role": "system",
            "content": (
                "Ты извлекаешь данные из одной страницы OCR/Markdown текста "
                "протокола торгов или аукциона по земельному участку. "
                "Страница может содержать только часть документа. "
                "Верни только валидный JSON. "
                "Не добавляй пояснения, Markdown или текст вне JSON. "
                "Не используй китайский язык. "
                "Если данных на этой странице нет, верни null."
            ),
        },
        {
            "role": "user",
            "content": f"""
Это страница {page_number} протокола торгов или аукциона.

Найди только те данные, которые явно есть на этой странице.

Верни JSON строго по схеме:

{{
  "page": {page_number},
  "document_kind": null,
  "protocol_number": null,
  "protocol_date": null,
  "procedure_number": null,
  "auction_form": null,
  "organizer_name": null,
  "seller_name": null,
  "winner_name": null,
  "winner_inn": null,
  "participants": [],
  "subject": {{
    "cadastral_number": null,
    "area": null,
    "location": null,
    "lot_number": null,
    "subject_text": null
  }},
  "result": {{
    "status": null,
    "starting_price": null,
    "final_price": null,
    "annual_rent": null,
    "rent_amount": null,
    "sale_price": null,
    "payment_period": null,
    "result_text": null
  }}
}}

Правила:
1. Ответ должен быть только JSON.
2. Используй только текст этой страницы.
3. Не выдумывай данные.
4. Если значение не найдено на странице — null.
5. Даты верни в формате YYYY-MM-DD, если можешь определить.
6. area — площадь в квадратных метрах.
7. participants — список участников, если они явно перечислены на странице.
8. Не добавляй поле notes.
9. Не добавляй дополнительные поля вне схемы.
10. Не переводи названия организаций, ФИО и адреса.

Пояснения к полям:
- document_kind: тип протокола, например "протокол о результатах торгов", "протокол рассмотрения заявок", "протокол аукциона".
- protocol_number: номер самого протокола.
- protocol_date: дата составления протокола.
- procedure_number: номер процедуры, извещения или торгов.
- auction_form: форма торгов, например "аукцион", "открытый аукцион".
- organizer_name: организатор торгов.
- seller_name: продавец, арендодатель или уполномоченный орган.
- winner_name: победитель торгов.
- winner_inn: ИНН победителя, если есть.
- subject: сведения о земельном участке.
- result: итог торгов, цена, арендная плата, победитель.

Текст страницы:
\"\"\"{page_text}\"\"\"
""",
        },
    ]


def clean_page_result(data: dict, page_number: int) -> dict:
    """
    Удаляет notes и любые лишние поля, даже если модель их вернула.
    """
    if not isinstance(data, dict):
        data = {}

    allowed_top = {
        "page",
        "document_kind",
        "protocol_number",
        "protocol_date",
        "procedure_number",
        "auction_form",
        "organizer_name",
        "seller_name",
        "winner_name",
        "winner_inn",
        "participants",
        "subject",
        "result",
    }

    allowed_subject = {
        "cadastral_number",
        "area",
        "location",
        "lot_number",
        "subject_text",
    }

    allowed_result = {
        "status",
        "starting_price",
        "final_price",
        "annual_rent",
        "rent_amount",
        "sale_price",
        "payment_period",
        "result_text",
    }

    cleaned = {
        key: value
        for key, value in data.items()
        if key in allowed_top
    }

    cleaned["page"] = page_number

    subject = cleaned.get("subject") or {}
    if not isinstance(subject, dict):
        subject = {}

    cleaned["subject"] = {
        key: value
        for key, value in subject.items()
        if key in allowed_subject
    }

    result = cleaned.get("result") or {}
    if not isinstance(result, dict):
        result = {}

    cleaned["result"] = {
        key: value
        for key, value in result.items()
        if key in allowed_result
    }

    participants = cleaned.get("participants")
    if not isinstance(participants, list):
        cleaned["participants"] = []

    return cleaned


def merge_partial_results(page_results: list[dict]) -> dict:
    page_results = sorted(
        page_results,
        key=lambda item: item.get("page") or 9999,
    )

    merged = {
        "document_kind": None,
        "protocol_number": None,
        "protocol_date": None,
        "procedure_number": None,
        "auction_form": None,
        "organizer_name": None,
        "seller_name": None,
        "winner_name": None,
        "winner_inn": None,
        "participants": [],
        "subject": {
            "cadastral_number": None,
            "area": None,
            "location": None,
            "lot_number": None,
            "subject_text": None,
        },
        "result": {
            "status": None,
            "starting_price": None,
            "final_price": None,
            "annual_rent": None,
            "rent_amount": None,
            "sale_price": None,
            "payment_period": None,
            "result_text": None,
        },
        "pages": page_results,
    }

    for item in page_results:
        if not isinstance(item, dict):
            continue

        for key in (
            "document_kind",
            "protocol_number",
            "protocol_date",
            "procedure_number",
            "auction_form",
            "organizer_name",
            "seller_name",
            "winner_name",
            "winner_inn",
        ):
            merged[key] = first_not_empty(
                merged[key],
                item.get(key),
            )

        subject = item.get("subject") or {}
        for key in (
            "cadastral_number",
            "area",
            "location",
            "lot_number",
            "subject_text",
        ):
            merged["subject"][key] = first_not_empty(
                merged["subject"][key],
                subject.get(key),
            )

        result = item.get("result") or {}
        for key in (
            "status",
            "starting_price",
            "final_price",
            "annual_rent",
            "rent_amount",
            "sale_price",
            "payment_period",
            "result_text",
        ):
            merged["result"][key] = first_not_empty(
                merged["result"][key],
                result.get(key),
            )

        # если победитель найден внутри result — поднимаем наверх
        merged["winner_name"] = first_not_empty(
            merged["winner_name"],
            result.get("winner_name"),
        )
        merged["winner_inn"] = first_not_empty(
            merged["winner_inn"],
            result.get("winner_inn"),
        )

        participants = item.get("participants")
        if isinstance(participants, list):
            merged["participants"] = merge_lists(
                merged["participants"],
                participants,
            )

    return merged


def resolve_auction_protocol_by_ocr_pages(document) -> dict:
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
        raw_result = call_ollama(messages, num_predict=900)
        result = clean_page_result(raw_result, page_number)

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
        prefix="auction_protocol",
    )

    raw.update(paths)

    return {
        "raw": raw,
        "parsed": merged,
    }
