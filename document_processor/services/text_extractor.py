import fitz

from .ocr import extract_text_with_ocr, is_text_bad


TEXT_LAYER_MIN_LEN = 80


def extract_text_layer(
    file_path: str,
    max_pages: int | None = None,
) -> str:
    doc = fitz.open(file_path)
    text_parts = []

    try:
        page_count = len(doc)
        limit = min(page_count, max_pages) if max_pages is not None else page_count

        for page_index in range(limit):
            page = doc[page_index]
            text = page.get_text("text")
            if text and text.strip():
                text_parts.append(text)
    finally:
        doc.close()

    return "\n".join(text_parts).strip()


def is_probably_text_pdf(text: str) -> bool:
    return len(text.strip()) >= TEXT_LAYER_MIN_LEN


def extract_text_from_document(
    file_path: str,
    force_ocr: bool = False,
) -> tuple[str, bool]:
    """
    Возвращает:
    - извлечённый текст
    - использовался ли OCR
    """
    if not force_ocr:
        doc = fitz.open(file_path)
        text_parts = []

        for page in doc:
            text = page.get_text("text")
            if text and text.strip():
                text_parts.append(text)

        doc.close()

        extracted_text = "\n".join(text_parts).strip()

        # Если текста достаточно, считаем PDF текстовым
        if extracted_text and not is_text_bad(extracted_text):
            if len(extracted_text) > 500:
                return extracted_text, False

    # Иначе считаем, что это скан, и запускаем OCR
    ocr_text = extract_text_with_ocr(file_path)
    return ocr_text, True
