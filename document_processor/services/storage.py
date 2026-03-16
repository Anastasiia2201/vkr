import uuid
from pathlib import Path
from django.utils import timezone


def source_document_upload_path(instance, filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".bin"
    document_type = getattr(instance, "document_type", None) or "unknown"

    allowed_types = {
        "egrn",
        "auction_protocol",
        "sale_contract",
        "unknown",
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
