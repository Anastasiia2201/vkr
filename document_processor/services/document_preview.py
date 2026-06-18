from __future__ import annotations

import shutil
from pathlib import Path

import fitz
from django.conf import settings

from document_processor.models import SourceDocument


PREVIEW_SCALE = 1.5
MAX_PREVIEW_PAGES = 10


def get_document_preview_dir(document_id: int) -> Path:
    return Path(settings.MEDIA_ROOT) / "document_previews" / f"document_{document_id}"


def reset_document_preview_dir(document_id: int) -> Path:
    preview_dir = get_document_preview_dir(document_id)

    if preview_dir.exists():
        shutil.rmtree(preview_dir)

    preview_dir.mkdir(parents=True, exist_ok=True)
    return preview_dir


def build_document_page_previews(
    document: SourceDocument,
    *,
    force: bool = False,
    max_pages: int = MAX_PREVIEW_PAGES,
) -> list[dict]:
    """
    Рендерит страницы PDF в PNG и возвращает список относительных путей.
    """

    if not document.file:
        raise ValueError("У документа отсутствует файл.")

    file_path = Path(document.file.path)

    if file_path.suffix.lower() != ".pdf":
        raise ValueError("Preview страниц поддерживается только для PDF.")

    preview_dir = get_document_preview_dir(document.id)

    if force:
        preview_dir = reset_document_preview_dir(document.id)
    else:
        preview_dir.mkdir(parents=True, exist_ok=True)

    existing_pages = sorted(preview_dir.glob("page_*.png"))

    if existing_pages and not force:
        return [
            {
                "page": index + 1,
                "image_path": str(path.relative_to(settings.MEDIA_ROOT)),
            }
            for index, path in enumerate(existing_pages)
        ]

    doc = fitz.open(str(file_path))
    pages: list[dict] = []

    try:
        page_count = min(len(doc), max_pages)

        for page_index in range(page_count):
            page_number = page_index + 1
            page = doc[page_index]

            pix = page.get_pixmap(
                matrix=fitz.Matrix(PREVIEW_SCALE, PREVIEW_SCALE),
                alpha=False,
            )

            image_path = preview_dir / f"page_{page_number:03d}.png"
            pix.save(str(image_path))

            pages.append(
                {
                    "page": page_number,
                    "image_path": str(image_path.relative_to(settings.MEDIA_ROOT)),
                }
            )

    finally:
        doc.close()

    return pages
