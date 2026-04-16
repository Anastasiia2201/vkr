import os
import shutil
import uuid
import hashlib
from pathlib import Path

from django.conf import settings
from django.utils import timezone


def source_document_upload_path(instance, filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".bin"
    document_type = getattr(instance, "document_type", None) or "unknown"

    allowed_types = {
        "egrn",
        "auction_protocol",
        "sale_contract",
        "unknown",
        "rent_contract",
    }

    if document_type not in allowed_types:
        document_type = "unknown"

    now = timezone.now()
    unique_name = f"{uuid.uuid4().hex}{extension}"

    return (
        f"source_documents/"
        f"{document_type}/"
        f"{now.year}/"
        f"{now.month:02d}/"
        f"{unique_name}"
    )


def build_processed_document_path(document_type: str, original_filename: str) -> str:
    extension = Path(original_filename).suffix.lower() or ".bin"
    now = timezone.now()
    unique_name = f"{uuid.uuid4().hex}{extension}"

    return (
        f"source_documents/"
        f"{document_type}/"
        f"{now.year}/"
        f"{now.month:02d}/"
        f"{unique_name}"
    )


def move_document_file(document) -> None:
    if not document.file:
        return

    current_path = document.file.path
    new_relative_path = build_processed_document_path(
        document.document_type,
        document.original_filename or os.path.basename(current_path),
    )
    new_absolute_path = os.path.join(settings.MEDIA_ROOT, new_relative_path)

    if os.path.abspath(current_path) == os.path.abspath(new_absolute_path):
        return

    os.makedirs(os.path.dirname(new_absolute_path), exist_ok=True)
    shutil.move(current_path, new_absolute_path)

    document.file.name = new_relative_path
    document.save(update_fields=["file"])


def calculate_file_hash(uploaded_file) -> str:
    sha256 = hashlib.sha256()

    for chunk in uploaded_file.chunks():
        sha256.update(chunk)

    uploaded_file.seek(0)
    return sha256.hexdigest()
