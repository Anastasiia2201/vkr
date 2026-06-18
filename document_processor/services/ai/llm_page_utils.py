from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from django.conf import settings


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://172.31.240.1:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")


def safe_parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")

        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

    return {
        "error": "invalid_json",
        "raw": text,
    }


def call_ollama(messages: list[dict], *, num_predict: int = 700) -> dict:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {
                "temperature": 0,
                "top_p": 0.1,
                "num_predict": num_predict,
                "num_ctx": 8192,
            },
        },
        timeout=180,
    )
    response.raise_for_status()

    raw = response.json()["message"]["content"]
    return safe_parse_json(raw)


def get_document_ocr_result_dir(document) -> Path:
    if not document.ocr_result_dir:
        raise ValueError(
            "У документа отсутствует ocr_result_dir. "
            "Сначала нужно выполнить OCR."
        )

    result_dir = Path(settings.MEDIA_ROOT) / document.ocr_result_dir

    if not result_dir.exists():
        raise FileNotFoundError(f"OCR-папка не найдена: {result_dir}")

    return result_dir


def read_ocr_pages(document) -> list[dict[str, Any]]:
    result_dir = get_document_ocr_result_dir(document)
    page_paths = sorted(result_dir.glob("page_*.md"))

    pages: list[dict[str, Any]] = []

    for path in page_paths:
        match = re.search(r"page_(\d+)\.md$", path.name)
        page_number = int(match.group(1)) if match else len(pages) + 1

        text = path.read_text(encoding="utf-8").strip()

        pages.append(
            {
                "page": page_number,
                "path": str(path.relative_to(settings.MEDIA_ROOT)),
                "text": text,
                "text_length": len(text),
            }
        )

    return pages


def clean_dict_by_keys(data: dict, allowed_keys: set[str]) -> dict:
    if not isinstance(data, dict):
        return {}

    return {
        key: value
        for key, value in data.items()
        if key in allowed_keys
    }


def is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def first_not_empty(current: Any, new: Any) -> Any:
    if not is_empty_value(current):
        return current

    if is_empty_value(new):
        return current

    return new


def merge_lists(current: list, new: list) -> list:
    result = list(current or [])
    seen = {
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in result
    }

    for item in new or []:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result


def save_llm_results(
    document,
    *,
    raw: dict,
    parsed: dict,
    prefix: str,
) -> dict:
    """
    Сохраняет LLM-результаты рядом с OCR-страницами.

    prefix:
    - "rent_contract"
    - "auction_protocol"
    """
    result_dir = get_document_ocr_result_dir(document)

    pages_result_path = result_dir / f"llm_{prefix}_pages_result.json"
    merged_result_path = result_dir / f"llm_{prefix}_merged_result.json"

    pages_payload = {
        "raw": raw,
        "parsed": parsed,
    }

    pages_result_path.write_text(
        json.dumps(pages_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    merged_result_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "llm_pages_result_path": str(
            pages_result_path.relative_to(settings.MEDIA_ROOT)
        ),
        "llm_merged_result_path": str(
            merged_result_path.relative_to(settings.MEDIA_ROOT)
        ),
    }
