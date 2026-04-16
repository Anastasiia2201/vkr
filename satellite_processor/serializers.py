from datetime import date, timedelta

from rest_framework import serializers

from .models import SatelliteImage


def get_default_target_date(today: date | None = None) -> date:
    today = today or date.today()

    if 5 <= today.month <= 9:
        return today

    if today.month >= 10:
        return date(today.year, 9, 30)

    return date(today.year - 1, 9, 30)


class SatelliteImageSerializer(serializers.ModelSerializer):
    preview_image_url = serializers.SerializerMethodField()
    cadastral_number = serializers.CharField(
        source="land_plot.cadastral_number",
        read_only=True,
    )

    class Meta:
        model = SatelliteImage
        fields = [
            "id",
            "cadastral_number",
            "source",
            "scene_id",
            "acquisition_date",
            "cloud_cover",
            "preview_image",
            "preview_image_url",
            "bbox",
            "metadata",
            "created_at",
            "predicted_class",
        ]
        read_only_fields = fields

    def get_preview_image_url(self, obj):
        request = self.context.get("request")
        if not obj.preview_image:
            return None
        url = obj.preview_image.url
        return request.build_absolute_uri(url) if request else url


class SatellitePreviewRequestSerializer(serializers.Serializer):
    target_date = serializers.DateField(required=False)
    days_delta = serializers.IntegerField(required=False, min_value=0, default=10)

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    max_cloud_cover = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        default=20.0,
    )
    max_snow_ice_percentage = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        default=20.0,
    )

    def validate(self, attrs):
        target_date = attrs.get("target_date")
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        has_target = target_date is not None
        has_range = start_date is not None or end_date is not None

        if has_target and has_range:
            raise serializers.ValidationError(
                "Нужно передать либо target_date, либо start_date/end_date."
            )

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                "start_date не может быть больше end_date."
            )

        return attrs

    def get_search_dates(self):
        data = self.validated_data

        target_date = data.get("target_date")
        if target_date:
            delta = data.get("days_delta", 7)
            return (
                target_date - timedelta(days=delta),
                target_date + timedelta(days=delta),
            )

        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if start_date or end_date:
            return start_date, end_date

        # ничего не передали -> отдаем None, None
        return None, None
