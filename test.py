from document_processor.models import SourceDocument
from django.core.files import File

f = open("media/source_documents/egrn/выписка из ЕГРН на 335 уч..pdf", "rb")

doc = SourceDocument.objects.create(
    file=File(f),
    document_type="44"
)

print(doc.file.path)
