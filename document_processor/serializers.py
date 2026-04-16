import re

from rest_framework import serializers

from .services.storage import calculate_file_hash
from .models import (
    SourceDocument,
    LandPlot,
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
            "metadata",
            "created_at",
        ]
        read_only_fields = [
            "original_filename",
            "document_type",
            "text_content",
            "ocr_used",
            "status",
            "metadata",
            "created_at",
        ]

    def create(self, validated_data):
        uploaded_file = validated_data["file"]
        file_hash = calculate_file_hash(uploaded_file)

        existing_document = SourceDocument.objects.filter(file_hash=file_hash).first()
        if existing_document:
            return existing_document

        validated_data["original_filename"] = uploaded_file.name
        validated_data["file_hash"] = file_hash
        return super().create(validated_data)

    def update(self, instance, validated_data):
        uploaded_file = validated_data.get("file")
        if uploaded_file:
            validated_data["original_filename"] = uploaded_file.name
            validated_data["file_hash"] = calculate_file_hash(uploaded_file)
        return super().update(instance, validated_data)


class LandPlotSerializer(serializers.ModelSerializer):
    egrn_source_document_id = serializers.IntegerField(
        source="egrn_source_document.id",
        read_only=True,
    )

    class Meta:
        model = LandPlot
        fields = [
            "id",
            "cadastral_number",
            "area_hectares",
            "location",
            "geometry",
            "use_type",
            "egrn_source_document",
            "egrn_source_document_id",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_cadastral_number(self, value):
        pattern = r"^\d{2}:\d{2}:\d{6,7}:\d+$"
        if not re.match(pattern, value):
            raise serializers.ValidationError(
                "Некорректный формат кадастрового номера."
            )
        return value


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = [
            "id",
            "name",
            "inn",
            "kpp",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class ContractSerializer(serializers.ModelSerializer):
    party_1 = PartySerializer(read_only=True)
    party_2 = PartySerializer(read_only=True)
    land_plots = LandPlotSerializer(many=True, read_only=True)

    party_1_id = serializers.PrimaryKeyRelatedField(
        source="party_1",
        queryset=Party.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    party_2_id = serializers.PrimaryKeyRelatedField(
        source="party_2",
        queryset=Party.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    land_plot_ids = serializers.PrimaryKeyRelatedField(
        source="land_plots",
        queryset=LandPlot.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = Contract
        fields = [
            "id",
            "source_document",
            "contract_kind",
            "name",
            "contract_number",
            "contract_date",
            "party_1",
            "party_2",
            "party_1_id",
            "party_2_id",
            "land_plots",
            "land_plot_ids",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        party_1 = attrs.get("party_1")
        party_2 = attrs.get("party_2")

        if party_1 and party_2 and party_1 == party_2:
            raise serializers.ValidationError(
                "Сторона 1 и сторона 2 не могут совпадать."
            )
        return attrs


class ExtractTextRequestSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    force_ocr = serializers.BooleanField(required=False, default=False)


class RentContractLLMTestSerializer(serializers.Serializer):
    text = serializers.CharField(required=True, allow_blank=False)


class ExtractTextResponseSerializer(serializers.Serializer):
    text = serializers.CharField()
    ocr_used = serializers.BooleanField()
