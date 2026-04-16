from django.db import models

from document_processor.models import LandPlot


class SatelliteImage(models.Model):
    class SourceChoices(models.TextChoices):
        PLANETARY_COMPUTER = "planetary_computer", "Planetary Computer"

    land_plot = models.ForeignKey(
        LandPlot,
        on_delete=models.CASCADE,
        related_name="satellite_images",
    )
    source = models.CharField(
        max_length=50,
        choices=SourceChoices.choices,
        default=SourceChoices.PLANETARY_COMPUTER,
    )
    scene_id = models.CharField(max_length=255, db_index=True)
    acquisition_date = models.DateTimeField()
    cloud_cover = models.FloatField(null=True, blank=True)
    preview_image = models.ImageField(
        upload_to="satellite/previews/%Y/%m/",
        null=True,
        blank=True,
    )
    bbox = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    predicted_class = models.CharField(max_length=32, null=True, blank=True)
    predicted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-acquisition_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["land_plot", "source", "scene_id"],
                name="unique_satellite_image_per_scene",
            )
        ]
    ndvi = models.FloatField(null=True, blank=True)
    features = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.land_plot.cadastral_number} | {self.scene_id}"
