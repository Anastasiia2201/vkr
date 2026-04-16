from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from functools import lru_cache

import spacy


CADASTRAL_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")

DATE_NUMERIC_RE = re.compile(
    r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b"
)

DATE_TEXTUAL_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s+(\d{4})\s*г?\.?\b",
    re.IGNORECASE,
)

AREA_RE = re.compile(
    r"(?:(?:площад[ья]|общая\s+площадь|площадь\s+участка)"
    r"[:\s]*)?([\d\s]+(?:[.,]\d+)?)\s*(га|гектар(?:а|ов)?|кв\.?\s*м|м2|квм)\b",
    re.IGNORECASE,
)

CONTRACT_NUMBER_PATTERNS = [
    re.compile(
        r"(?:номер\s+договора|№\s*договора|договор\s*№|договора\s*№)"
        r"[:\s]*([A-Za-zА-Яа-я0-9\-\/]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:номер\s+процедуры|номер\s+извещения|извещение\s*№|процедура\s*№)"
        r"[:\s]*([A-Za-zА-Яа-я0-9\-\/]+)",
        re.IGNORECASE,
    ),
]

SELLER_LABELS = [
    "продавец",
    "арендодатель",
    "организатор торгов",
    "уполномоченный орган",
]

BUYER_LABELS = [
    "покупатель",
    "арендатор",
    "победитель",
]

MONTHS = {
    "января": "01",
    "февраля": "02",
    "марта": "03",
    "апреля": "04",
    "мая": "05",
    "июня": "06",
    "июля": "07",
    "августа": "08",
    "сентября": "09",
    "октября": "10",
    "ноября": "11",
    "декабря": "12",
}


@dataclass
class ExtractedEntity:
    value: str
    entity_type: str
    start: int | None = None
    end: int | None = None
    source: str = "regex"
    confidence: float = 0.8
    normalized_value: str | float | None = None
    role: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=1)
def get_nlp():
    return spacy.load("ru_core_news_sm")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("\xa0", " ").strip()


def deduplicate_entities(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    seen: set[tuple] = set()
    result: list[ExtractedEntity] = []

    for entity in entities:
        key = (
            entity.entity_type,
            entity.role,
            str(entity.normalized_value or entity.value).strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)

    return result


def normalize_year(year: str) -> str:
    year = year.strip()
    if len(year) == 2:
        year_int = int(year)
        return f"20{year}" if year_int < 50 else f"19{year}"
    return year


def normalize_date(day: str, month: str, year: str) -> str | None:
    try:
        day_i = int(day)
        month_i = int(month)
        year_i = int(normalize_year(year))
    except ValueError:
        return None

    if not (1 <= day_i <= 31 and 1 <= month_i <= 12):
        return None

    return f"{year_i:04d}-{month_i:02d}-{day_i:02d}"


def extract_all_cadastral_numbers(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    for match in CADASTRAL_RE.finditer(text):
        value = match.group(0)
        entities.append(
            ExtractedEntity(
                value=value,
                normalized_value=value,
                entity_type="cadastral_number",
                start=match.start(),
                end=match.end(),
                source="regex",
                confidence=0.99,
            )
        )

    return deduplicate_entities(entities)


def extract_all_dates(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    for match in DATE_NUMERIC_RE.finditer(text):
        day, month, year = match.groups()
        normalized = normalize_date(day, month, year)
        if not normalized:
            continue

        entities.append(
            ExtractedEntity(
                value=match.group(0),
                normalized_value=normalized,
                entity_type="date",
                start=match.start(),
                end=match.end(),
                source="regex_numeric_date",
                confidence=0.95,
            )
        )

    for match in DATE_TEXTUAL_RE.finditer(text):
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name.lower())
        if not month:
            continue

        normalized = normalize_date(day, month, year)
        if not normalized:
            continue

        entities.append(
            ExtractedEntity(
                value=match.group(0),
                normalized_value=normalized,
                entity_type="date",
                start=match.start(),
                end=match.end(),
                source="regex_textual_date",
                confidence=0.93,
            )
        )

    return deduplicate_entities(entities)


def normalize_area(value: str, unit: str) -> float | None:
    raw = value.replace(" ", "").replace(",", ".")
    try:
        area = float(raw)
    except ValueError:
        return None

    unit_lower = unit.lower().replace(" ", "")

    if "га" in unit_lower or "гектар" in unit_lower:
        return round(area, 4)

    return round(area / 10000, 4)


def extract_all_areas(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    for match in AREA_RE.finditer(text):
        raw_value = match.group(1)
        unit = match.group(2)
        normalized = normalize_area(raw_value, unit)
        if normalized is None:
            continue

        entities.append(
            ExtractedEntity(
                value=match.group(0),
                normalized_value=normalized,
                entity_type="area_hectares",
                start=match.start(),
                end=match.end(),
                source="regex_area",
                confidence=0.90,
            )
        )

    return deduplicate_entities(entities)


def extract_all_contract_numbers(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    for pattern in CONTRACT_NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).strip(" .,:;")
            if len(value) < 3:
                continue

            entities.append(
                ExtractedEntity(
                    value=value,
                    normalized_value=value,
                    entity_type="contract_number",
                    start=match.start(1),
                    end=match.end(1),
                    source="regex_contract_number",
                    confidence=0.86,
                )
            )

    return deduplicate_entities(entities)


def cleanup_party_value(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value).strip(" :;-")
    if len(value) < 3:
        return None
    return value


def extract_party_by_labels(text: str, labels: list[str], role: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]

    for line in lines:
        lower = line.lower()

        for label in labels:
            if label in lower:
                value = re.sub(
                    rf"^.*?{re.escape(label)}[:\s\-–—]*",
                    "",
                    line,
                    flags=re.IGNORECASE,
                )
                value = cleanup_party_value(value)
                if not value:
                    continue

                entities.append(
                    ExtractedEntity(
                        value=value,
                        normalized_value=value,
                        entity_type="party",
                        source="label_rule",
                        confidence=0.84,
                        role=role,
                    )
                )

    return entities


def extract_parties_with_spacy(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    doc = get_nlp()(normalize_text(text))

    for ent in doc.ents:
        if ent.label_ not in {"ORG", "PER"}:
            continue

        value = cleanup_party_value(ent.text)
        if not value:
            continue

        entities.append(
            ExtractedEntity(
                value=value,
                normalized_value=value,
                entity_type="party",
                start=ent.start_char,
                end=ent.end_char,
                source=f"spacy_{ent.label_.lower()}",
                confidence=0.65,
            )
        )

    return entities


def extract_all_parties(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    entities.extend(extract_party_by_labels(text, SELLER_LABELS, role="seller"))
    entities.extend(extract_party_by_labels(text, BUYER_LABELS, role="buyer"))
    entities.extend(extract_parties_with_spacy(text))

    return deduplicate_entities(entities)


def extract_document_entities(text: str) -> dict:
    text = normalize_text(text)

    cadastral_numbers = extract_all_cadastral_numbers(text)
    dates = extract_all_dates(text)
    areas = extract_all_areas(text)
    contract_numbers = extract_all_contract_numbers(text)
    parties = extract_all_parties(text)

    all_entities = [
        *cadastral_numbers,
        *dates,
        *areas,
        *contract_numbers,
        *parties,
    ]

    return {
        "entities": {
            "cadastral_numbers": [item.to_dict() for item in cadastral_numbers],
            "dates": [item.to_dict() for item in dates],
            "areas": [item.to_dict() for item in areas],
            "contract_numbers": [item.to_dict() for item in contract_numbers],
            "parties": [item.to_dict() for item in parties],
        },
        "stats": {
            "cadastral_numbers_count": len(cadastral_numbers),
            "dates_count": len(dates),
            "areas_count": len(areas),
            "contract_numbers_count": len(contract_numbers),
            "parties_count": len(parties),
            "total_entities_count": len(all_entities),
        },
    }
