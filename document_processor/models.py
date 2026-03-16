from django.contrib.gis.db import models
from .services.storage import source_document_upload_path


class SourceDocument(models.Model):
    class DocumentType(models.TextChoices):
        EGRN = "egrn", "Выписка ЕГРН"
        AUCTION_PROTOCOL = "auction_protocol", "Протокол торгов"
        SALE_CONTRACT = "sale_contract", "Договор купли-продажи"
        UNKNOWN = "unknown", "Неизвестно"

    class ProcessingStatus(models.TextChoices):
        UPLOADED = "uploaded", "Загружен"
        PROCESSED = "processed", "Обработан"
        FAILED = "failed", "Ошибка"

    file = models.FileField(upload_to=source_document_upload_path)
    original_filename = models.CharField(max_length=255, blank=True)
    document_type = models.CharField(
        max_length=32,
        choices=DocumentType.choices,
        default=DocumentType.UNKNOWN
    )
    text_content = models.TextField(blank=True)
    ocr_used = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.UPLOADED
    )
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename or f"Документ #{self.pk}"


class LandCategory(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class LandPlot(models.Model):
    cadastral_number = models.CharField(max_length=50, unique=True)
    area_hectares = models.FloatField(null=True, blank=True)
    location = models.TextField(blank=True)
    land_category = models.ForeignKey(
        LandCategory,
        on_delete=models.SET_NULL,
        null=True
    )
    egrn_document = models.FileField(
        upload_to="documents/egrn/",
        null=True,
        blank=True
    )
    geometry = models.MultiPolygonField(
        srid=4326,
        null=True,
        blank=True
    )
    use_type = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    egrn_source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="egrn_land_plots"
    )

    def calculate_area(self):
        if self.geometry:
            return self.geometry.area

    def __str__(self):
        return self.cadastral_number


class ContractType(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Party(models.Model):
    PARTY_TYPES = (
        ('legal', 'Юридическое лицо'),
        ('physical', 'Физическое лицо'),
        ('authority', 'Орган власти'),
    )
    name = models.TextField()
    party_type = models.CharField(
        max_length=20,
        choices=PARTY_TYPES
    )

    def __str__(self):
        return self.name


class Contract(models.Model):
    name = models.CharField(max_length=255)
    contract_type = models.ForeignKey(
        ContractType,
        on_delete=models.SET_NULL,
        null=True
    )
    seller = models.ForeignKey(
        Party,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sold_contracts"
    )
    buyer = models.ForeignKey(
        Party,
        on_delete=models.SET_NULL,
        null=True,
        related_name="bought_contracts"
    )
    land_plot = models.ForeignKey(
        LandPlot,
        on_delete=models.CASCADE,
        related_name="contracts"
    )
    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts"
    )
    source_url = models.TextField(blank=True)
    procedure_number = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
