import re


def parse_auction_protocol(text: str) -> dict:
    result = {
        "cadastral_number": None,
        "procedure_number": None,
        "seller_name": None,
        "buyer_name": None,
        "confidence": 0.70,
    }

    cadastral_match = re.search(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b", text)
    if cadastral_match:
        result["cadastral_number"] = cadastral_match.group(0)

    procedure_match = re.search(
        r"№\s*([0-9]{10,})",
        text
    )
    if procedure_match:
        result["procedure_number"] = procedure_match.group(1)

    return result


def parse_egrn_document(text: str) -> dict:
    result = {
        "cadastral_number": None,
        "area_hectares": None,
        "location": None,
        "land_category": None,
        "use_type": None,
        "confidence": 0.80,
    }

    cadastral_match = re.search(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b", text)
    if cadastral_match:
        result["cadastral_number"] = cadastral_match.group(0)

    area_match = re.search(r"Площадь[:\s]+([\d\s,.]+)", text, re.IGNORECASE)
    if area_match:
        raw_area = area_match.group(1).replace(" ", "").replace(",", ".")
        try:
            area_sq_m = float(raw_area)
            result["area_hectares"] = area_sq_m / 10000
        except ValueError:
            pass

    location_match = re.search(
        r"Местоположение[:\s]+(.+)",
        text,
        re.IGNORECASE
    )
    if location_match:
        result["location"] = location_match.group(1).strip()

    category_match = re.search(
        r"Категория земель[:\s]+(.+)",
        text,
        re.IGNORECASE
    )
    if category_match:
        result["land_category"] = category_match.group(1).strip()

    use_type_match = re.search(
        r"Виды разрешенного использования[:\s]+(.+)",
        text,
        re.IGNORECASE
    )
    if use_type_match:
        result["use_type"] = use_type_match.group(1).strip()

    return result
