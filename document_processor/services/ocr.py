from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import fitz
from django.conf import settings
from django.utils import timezone
from PIL import Image
from paddleocr import PPStructureV3


OCR_ENGINE = "ppstructurev3"

RENDER_SCALE = 1.2
MAX_PAGES_FOR_OCR = 10
MAX_DOCUMENT_OCR_SECONDS = 300
MIN_TEXT_LEN = 20


_pipeline = None


@dataclass
class OCRPageResult:
    page: int
    text: str
    text_length: int
    markdown_path: str | None = None


def get_pipeline():
    """
    Ленивая загрузка PPStructureV3.
    Модель тяжёлая, поэтому не создаём её при импорте файла.
    """
    global _pipeline

    if _pipeline is None:
        _pipeline = PPStructureV3(lang="ru")

    return _pipeline


def get_ocr_result_dir_for_document(document_id: int) -> Path:
    return Path(settings.MEDIA_ROOT) / "ocr_results" / f"document_{document_id}"


def build_ocr_result_dir_for_document(document_id: int) -> Path:
    result_dir = get_ocr_result_dir_for_document(document_id)
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir


def reset_ocr_result_dir_for_document(document_id: int) -> Path:
    result_dir = get_ocr_result_dir_for_document(document_id)

    if result_dir.exists():
        shutil.rmtree(result_dir)

    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir


def get_combined_text_path(result_dir: Path) -> Path:
    return result_dir / "combined_text.txt"


def get_pages_metadata_path(result_dir: Path) -> Path:
    return result_dir / "pages.json"


def load_saved_ocr_result(result_dir: Path) -> tuple[str, dict] | None:
    """
    Если OCR уже был выполнен, возвращает сохранённый текст и metadata.
    """
    combined_path = get_combined_text_path(result_dir)
    metadata_path = get_pages_metadata_path(result_dir)

    if not combined_path.exists():
        return None

    text = combined_path.read_text(encoding="utf-8")

    metadata = {}

    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}

    return text, metadata


def render_pdf_page(page: fitz.Page, scale: float = RENDER_SCALE) -> Image.Image:
    pix = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        alpha=False,
    )
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def read_markdown_files(directory: Path) -> str:
    """
    Для LLM нам нужен человекочитаемый Markdown,
    а не огромный JSON с координатами.
    """
    parts: list[str] = []

    for path in sorted(directory.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue

        if content:
            parts.append(content)

    return "\n\n".join(parts).strip()


def save_page_text(result_dir: Path, page_number: int, text: str) -> Path:
    page_path = result_dir / f"page_{page_number:03d}.md"
    page_path.write_text(text or "", encoding="utf-8")
    return page_path


def ppstructure_image_to_text(image_path: Path) -> str:
    pipeline = get_pipeline()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output = pipeline.predict(str(image_path))

        page_parts: list[str] = []

        for i, res in enumerate(output):
            item_dir = tmpdir_path / f"item_{i + 1}"
            item_dir.mkdir(parents=True, exist_ok=True)

            try:
                res.save_to_markdown(str(item_dir))
            except Exception:
                pass

            text = read_markdown_files(item_dir)

            if text:
                page_parts.append(text)
            else:
                # fallback, если markdown не сохранился
                page_parts.append(str(res))

        return "\n\n".join(page_parts).strip()


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
    text = normalize_cadastral_numbers(text)

    return text.strip()


def is_text_bad(text: str) -> bool:
    """
    Функция нужна для совместимости с text_extractor.py.
    """
    text = normalize_ocr_text(text)

    if not text or len(text) < 80:
        return True

    total = len(text)
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))

    if cyr / max(total, 1) < 0.25:
        return True

    weird = len(re.findall(r"[©`_]", text))
    if weird > 10:
        return True

    return False


def extract_text_with_paddle_ocr(
    file_path: str,
    result_dir: Path,
) -> tuple[str, dict]:
    """
    Выполняет OCR/PP-StructureV3 и сохраняет результат в result_dir.

    Важно:
    - result_dir должен быть подготовлен заранее;
    - эта функция не решает, удалять старую папку или нет.
    """
    started = time.monotonic()

    pages: list[OCRPageResult] = []
    combined_parts: list[str] = []

    path = Path(file_path)

    if path.suffix.lower() == ".pdf":
        doc = fitz.open(file_path)

        try:
            page_count = min(len(doc), MAX_PAGES_FOR_OCR)

            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)

                for page_index in range(page_count):
                    if time.monotonic() - started > MAX_DOCUMENT_OCR_SECONDS:
                        break

                    page_number = page_index + 1

                    image = render_pdf_page(doc[page_index])
                    image_path = tmpdir_path / f"page_{page_number:03d}.png"
                    image.save(image_path)

                    page_text = ppstructure_image_to_text(image_path)
                    page_text = normalize_ocr_text(page_text)

                    markdown_path = None

                    if page_text and len(page_text) >= MIN_TEXT_LEN:
                        page_file = save_page_text(
                            result_dir=result_dir,
                            page_number=page_number,
                            text=page_text,
                        )
                        markdown_path = str(page_file.relative_to(settings.MEDIA_ROOT))

                        combined_parts.append(
                            f"--- Страница {page_number} ---\n{page_text}"
                        )

                    pages.append(
                        OCRPageResult(
                            page=page_number,
                            text=page_text,
                            text_length=len(page_text or ""),
                            markdown_path=markdown_path,
                        )
                    )

        finally:
            doc.close()

    else:
        page_text = ppstructure_image_to_text(path)
        page_text = normalize_ocr_text(page_text)

        markdown_path = None

        if page_text and len(page_text) >= MIN_TEXT_LEN:
            page_file = save_page_text(
                result_dir=result_dir,
                page_number=1,
                text=page_text,
            )
            markdown_path = str(page_file.relative_to(settings.MEDIA_ROOT))
            combined_parts.append(page_text)

        pages.append(
            OCRPageResult(
                page=1,
                text=page_text,
                text_length=len(page_text or ""),
                markdown_path=markdown_path,
            )
        )

    combined_text = "\n\n".join(combined_parts).strip()

    combined_path = result_dir / "combined_text.txt"
    combined_path.write_text(combined_text, encoding="utf-8")

    pages_metadata = [
        {
            "page": page.page,
            "text_length": page.text_length,
            "markdown_path": page.markdown_path,
        }
        for page in pages
    ]

    metadata = {
        "ocr_engine": OCR_ENGINE,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "result_dir": str(result_dir.relative_to(settings.MEDIA_ROOT)),
        "combined_text_path": str(combined_path.relative_to(settings.MEDIA_ROOT)),
        "page_count_processed": len(pages),
        "pages": pages_metadata,
        "processed_at": timezone.now().isoformat(),
    }

    metadata_path = result_dir / "pages.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return combined_text, metadata


def extract_text_with_paddle_ocr_for_document(
    document,
    force_ocr: bool = False,
) -> tuple[str, dict, bool]:
    """
    OCR для SourceDocument.

    Возвращает:
    - text;
    - metadata;
    - from_cache: True, если вернули сохранённый результат.
    """
    if document.pk is None:
        raise ValueError("Document must be saved before OCR processing.")

    if force_ocr:
        result_dir = reset_ocr_result_dir_for_document(document.id)
    else:
        result_dir = build_ocr_result_dir_for_document(document.id)

        saved = load_saved_ocr_result(result_dir)
        if saved is not None:
            text, metadata = saved
            return text, metadata, True

    text, metadata = extract_text_with_paddle_ocr(
        file_path=document.file.path,
        result_dir=result_dir,
    )

    document.ocr_result_dir = metadata.get("result_dir", "")
    document.ocr_engine = metadata.get("ocr_engine", OCR_ENGINE)
    document.ocr_processed_at = timezone.now()
    document.save(update_fields=["ocr_result_dir"])

    return text, metadata, False


def extract_text_with_ocr(file_path: str) -> str:
    """
    Совместимость со старым text_extractor.py.

    Если OCR вызывается без SourceDocument, результат сохраняется
    во временную папку и не привязывается к БД.
    Для сохранения в БД используй extract_text_with_paddle_ocr_for_document().
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        text, _metadata = extract_text_with_paddle_ocr(
            file_path=file_path,
            result_dir=Path(tmpdir),
        )
        return text
