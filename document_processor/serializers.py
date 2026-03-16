from rest_framework import serializers
from .models import (
    SourceDocument,
    LandCategory,
    LandPlot,
    ContractType,
    Party,
    Contract,
)


class SourceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceDocument
        fields = [
            "id",
            "file",
            "original_filename",
            "document_type",
            "text_content",
            "ocr_used",
            "status",
            "confidence",
            "metadata",
            "created_at",
        ]
        read_only_fields = [
            "original_filename",
            "text_content",
            "ocr_used",
            "status",
            "confidence",
            "metadata",
            "created_at",
        ]

    def create(self, validated_data):
        uploaded_file = validated_data["file"]
        validated_data["original_filename"] = uploaded_file.name
        return super().create(validated_data)

    def update(self, instance, validated_data):
        uploaded_file = validated_data.get("file")
        if uploaded_file:
            validated_data["original_filename"] = uploaded_file.name
        return super().update(instance, validated_data)


class LandCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LandCategory
        fields = ["id", "name"]


class LandPlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandPlot
        fields = [
            "id",
            "cadastral_number",
            "area_hectares",
            "location",
            "land_category",
            "egrn_document",
            "geometry",
            "use_type",
            "created_at",
            "egrn_source_document",
        ]
        read_only_fields = ["created_at"]

    def validate_cadastral_number(self, value):
        import re
        pattern = r"^\d{2}:\d{2}:\d{6,7}:\d+$"
        if not re.match(pattern, value):
            raise serializers.ValidationError(
                "Некорректный формат кадастрового номера."
            )
        return value


class ContractTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractType
        fields = ["id", "name"]


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "name", "party_type"]


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = [
            "id",
            "name",
            "contract_type",
            "seller",
            "buyer",
            "land_plot",
            "source_document",
            "source_url",
            "procedure_number",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        seller = attrs.get("seller")
        buyer = attrs.get("buyer")

        if seller and buyer and seller == buyer:
            raise serializers.ValidationError(
                "Продавец и покупатель не могут совпадать."
            )
        return attrs
