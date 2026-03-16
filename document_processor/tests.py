import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from document_processor.models import LandCategory, LandPlot, SourceDocument
from document_processor.services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)


class FetchLocationByCadastralNumberTests(TestCase):
    def test_returns_data_from_db_if_geometry_exists(self):
        category = LandCategory.objects.create(name="Земли сельскохозяйственного назначения")
        geometry = MultiPolygon(
            Polygon((
                (63.0, 56.0),
                (63.1, 56.0),
                (63.1, 56.1),
                (63.0, 56.1),
                (63.0, 56.0),
            )),
            srid=4326,
        )

        LandPlot.objects.create(
            cadastral_number="45:04:000000:2345",
            location="Курганская область",
            land_category=category,
            area_hectares=10,
            geometry=geometry,
            use_type="Для сельскохозяйственного использования",
        )

        with patch("document_processor.services.rosreestr.subprocess.run") as mock_run:
            result = fetch_location_by_cadastral_number("45:04:000000:2345")

        self.assertEqual(result.cadastral_number, "45:04:000000:2345")
        self.assertEqual(result.address, "Курганская область")
        self.assertIsNotNone(result.geometry)
        mock_run.assert_not_called()

    @patch("document_processor.services.rosreestr.subprocess.run")
    def test_fetches_geojson_and_saves_land_plot(self, mock_run):
        geojson_data = {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[
                        [63.0, 56.0],
                        [63.1, 56.0],
                        [63.1, 56.1],
                        [63.0, 56.1],
                        [63.0, 56.0],
                    ]]
                ],
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:4326"},
                },
            },
            "properties": {
                "options": {
                    "readable_address": "Курганская область, тестовый адрес",
                    "land_record_category_type": "Земли сельскохозяйственного назначения",
                    "permitted_use_established_by_document": "Для сельскохозяйственного использования",
                    "specified_area": 100000,
                }
            },
        }

        cadastral_number = "45:04:000000:2345"
        file_name = f"{cadastral_number.replace(':', '_')}.geojson"

        with TemporaryDirectory() as tmp_dir:
            geojson_dir = Path(tmp_dir)
            (geojson_dir / file_name).write_text(
                json.dumps(geojson_data),
                encoding="utf-8",
            )

            with patch("document_processor.services.rosreestr.GEOJSON_DIR", geojson_dir):
                result = fetch_location_by_cadastral_number(cadastral_number)

        self.assertEqual(result.cadastral_number, cadastral_number)
        self.assertEqual(result.address, "Курганская область, тестовый адрес")
        self.assertIsNotNone(result.geometry)

        land_plot = LandPlot.objects.get(cadastral_number=cadastral_number)
        self.assertEqual(land_plot.location, "Курганская область, тестовый адрес")
        self.assertEqual(land_plot.use_type, "Для сельскохозяйственного использования")
        self.assertEqual(land_plot.area_hectares, 10)
        self.assertIsNotNone(land_plot.land_category)
        self.assertEqual(
            land_plot.land_category.name,
            "Земли сельскохозяйственного назначения",
        )

        mock_run.assert_called_once()

    @patch("document_processor.services.rosreestr.subprocess.run")
    def test_raises_error_if_rosreestr2coord_is_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        with self.assertRaises(RosreestrError):
            fetch_location_by_cadastral_number("45:04:000000:2345")


class SourceDocumentUploadTests(APITestCase):

    def test_upload_document(self):
        url = reverse("source-document-list")

        test_file = SimpleUploadedFile(
            "test.pdf",
            b"dummy file content",
            content_type="application/pdf"
        )

        data = {
            "file": test_file,
            "document_type": "egrn",
        }

        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, 201)

        self.assertEqual(SourceDocument.objects.count(), 1)

        document = SourceDocument.objects.first()

        self.assertEqual(document.document_type, "egrn")
        self.assertEqual(document.original_filename, "test.pdf")

        self.assertTrue(document.file.name.startswith("source_documents/"))
