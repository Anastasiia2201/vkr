from __future__ import annotations

import io
import re
import time

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image


OCR_LANG = "rus+eng"

RENDER_SCALE = 2.5
MIN_TEXT_LEN = 20
MAX_IMAGE_SIDE = 6000

TESSERACT_TIMEOUT = 12
FAST_TESSERACT_TIMEOUT = 5

MAX_PAGE_OCR_SECONDS = 20
MAX_DOCUMENT_OCR_SECONDS = 120
MAX_PAGES_FOR_OCR = 7


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    rgb = image.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def resize_if_needed(
    image: np.ndarray,
    max_side: int = MAX_IMAGE_SIDE,
) -> np.ndarray:
    h, w = image.shape[:2]
    current_max = max(h, w)

    if current_max <= max_side:
        return image

    scale = max_side / current_max
    return cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )


def crop_margins(gray: np.ndarray) -> np.ndarray:
    inv = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)[1]
    coords = cv2.findNonZero(inv)

    if coords is None:
        return gray

    x, y, w, h = cv2.boundingRect(coords)
    pad = 15

    x1 = max(x - pad, 0)
    y1 = max(y - pad, 0)
    x2 = min(x + w + pad, gray.shape[1])
    y2 = min(y + h + pad, gray.shape[0])

    return gray[y1:y2, x1:x2]


def deskew_image(gray: np.ndarray) -> np.ndarray:
    thresh = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )[1]

    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 100:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle

    if abs(angle) < 0.3:
        return gray

    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    return cv2.warpAffine(
        gray,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def upscale_small_image(
    gray: np.ndarray,
    min_width: int = 1800,
) -> np.ndarray:
    h, w = gray.shape[:2]
    if w >= min_width:
        return gray

    scale = min_width / max(w, 1)
    return cv2.resize(
        gray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )


def preprocess_for_ocr(
    image: Image.Image,
    strong: bool = False,
) -> Image.Image:
    bgr = resize_if_needed(pil_to_bgr(image))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = crop_margins(gray)
    gray = deskew_image(gray)
    gray = upscale_small_image(gray)

    if strong:
        gray = cv2.fastNlMeansDenoising(
            gray,
            None,
            h=10,
            templateWindowSize=7,
            searchWindowSize=21,
        )

        gray = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8),
        ).apply(gray)

    return Image.fromarray(gray)


def normalize_cadastral_numbers(text: str) -> str:
    if not text:
        return ""

    text = re.sub(
        r"\b(\d{2})\s*[-–—:]\s*(\d{2})\s*:\s*(\d{6,7})\s*:\s*(\d+)\b",
        r"\1:\2:\3:\4",
        text,
    )

    text = re.sub(
        r"\b(\d{2})\s*:\s*(\d{2})\s*:\s*(\d{6,7})\s*:\s*(\d+)\b",
        r"\1:\2:\3:\4",
        text,
    )

    return text


def normalize_ocr_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    replacements = {
        "|": "1",
        "I": "1",
        "l": "1",
        "O": "0",
        "o": "0",
    }

    def fix_number_like(match: re.Match) -> str:
        value = match.group(0)
        for src, dst in replacements.items():
            value = value.replace(src, dst)
        return value

    text = re.sub(r"\b[0-9OIlo:]{6,}\b", fix_number_like, text)
    text = normalize_cadastral_numbers(text)
    return text.strip()


def is_text_bad(text: str) -> bool:
    text = normalize_ocr_text(text)

    if not text or len(text) < 80:
        return True

    total = len(text)
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    if cyr / max(total, 1) < 0.35:
        return True

    weird = len(re.findall(r"[©`_]", text))
    if weird > 5:
        return True

    one_char_words = len(re.findall(r"\b[А-Яа-яЁёA-Za-z]\b", text))
    if one_char_words > 25:
        return True

    return False


def run_tesseract(
    image: Image.Image,
    config: str,
    timeout: int,
) -> str:
    return pytesseract.image_to_string(
        image,
        lang=OCR_LANG,
        config=config,
        timeout=timeout,
    )


def extract_text_from_image(
    image: Image.Image,
    page_deadline: float,
) -> str:
    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
    ]

    variants = [
        preprocess_for_ocr(image, strong=False),
        preprocess_for_ocr(image, strong=True),
    ]

    best_text = ""

    for variant in variants:
        if time.monotonic() >= page_deadline:
            break

        for config in configs:
            if time.monotonic() >= page_deadline:
                break

            try:
                text = run_tesseract(
                    variant,
                    config=config,
                    timeout=TESSERACT_TIMEOUT,
                )
            except RuntimeError:
                continue

            text = normalize_ocr_text(text)

            if text and not is_text_bad(text):
                return text

            if len(text) > len(best_text):
                best_text = text

    return best_text


def render_pdf_page(
    page: fitz.Page,
    scale: float = RENDER_SCALE,
) -> Image.Image:
    pix = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        alpha=False,
    )
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def extract_text_with_ocr(file_path: str) -> str:
    doc = fitz.open(file_path)
    pages_text = []
    started = time.monotonic()

    try:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES_FOR_OCR:
                break

            if time.monotonic() - started > MAX_DOCUMENT_OCR_SECONDS:
                break

            deadline = time.monotonic() + MAX_PAGE_OCR_SECONDS

            try:
                image = render_pdf_page(page)
                text = extract_text_from_image(image, deadline)
            except Exception:
                text = ""

            if text and len(text) >= MIN_TEXT_LEN:
                pages_text.append(text)

    finally:
        doc.close()

    return "\n\n".join(pages_text).strip()
