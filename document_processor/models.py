from django.contrib.gis.db import models
from django.contrib.gis.db.models.functions import Area


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
    source_url = models.TextField(blank=True)
    procedure_number = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
