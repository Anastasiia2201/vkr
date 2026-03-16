import fitz

from .ocr import extract_text_with_ocr


def extract_text_from_document(file_path: str) -> tuple[str, bool]:
    doc = fitz.open(file_path)
    full_text = []

    for page in doc:
        text = page.get_text("text")
        if text:
            full_text.append(text)

    extracted_text = "\n".join(full_text).strip()

    if extracted_text:
        return extracted_text, False

    ocr_text = extract_text_with_ocr(file_path)
    return ocr_text, True
