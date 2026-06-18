from django.contrib.gis.db import models
from .services.storage import source_document_upload_path


class SourceDocument(models.Model):
    class DocumentType(models.TextChoices):
        EGRN = "egrn", "Выписка ЕГРН"
        AUCTION_PROTOCOL = "auction_protocol", "Протокол торгов"
        SALE_CONTRACT = "sale_contract", "Договор купли-продажи"
        RENT_CONTRACT = "rent_contract", "Договор аренды"
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
        default=DocumentType.UNKNOWN,
    )

    text_content = models.TextField(blank=True)
    ocr_result_dir = models.CharField(max_length=500, blank=True)
    ocr_used = models.BooleanField(default=False)

    status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.UPLOADED,
    )

    metadata = models.JSONField(default=dict, blank=True)

    file_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename or f"Документ #{self.pk}"


class LandPlot(models.Model):
    cadastral_number = models.CharField(max_length=50, unique=True)
    area_hectares = models.FloatField(null=True, blank=True)
    location = models.TextField(blank=True)
    geometry = models.MultiPolygonField(
        srid=4326,
        null=True,
        blank=True,
    )
    use_type = models.CharField(null=True, blank=True)

    egrn_source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="egrn_land_plots",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.cadastral_number


class Party(models.Model):
    name = models.TextField()

    inn = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    kpp = models.CharField(max_length=9, null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Contract(models.Model):
    class ContractKind(models.TextChoices):
        RENT = "rent", "Договор аренды"
        SALE = "sale", "Договор купли-продажи"
        OTHER = "other", "Иной договор"

    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.CASCADE,
        related_name="contracts",
    )

    contract_kind = models.CharField(
        max_length=20,
        choices=ContractKind.choices,
        default=ContractKind.OTHER,
    )

    name = models.CharField(max_length=255, blank=True)
    contract_number = models.CharField(max_length=100, blank=True)
    contract_date = models.DateField(null=True, blank=True)

    party_1 = models.ForeignKey(
        Party,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_as_party_1",
    )
    party_2 = models.ForeignKey(
        Party,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts_as_party_2",
    )

    land_plots = models.ManyToManyField(
        LandPlot,
        related_name="contracts",
        blank=True,
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.name:
            return self.name
        if self.contract_number:
            return f"Договор № {self.contract_number}"
        return f"Договор #{self.pk}"
