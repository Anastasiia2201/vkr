from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.urls import reverse

from document_processor.services.rosreestr import (
    RosreestrError,
    RosreestrNotFoundError,
    fetch_location_by_cadastral_number,
)


class RosreestrServiceTests(SimpleTestCase):
    @patch("document_processor.services.rosreestr.requests.get")
    def test_fetch_location_success(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "feature": {
                        "attrs": {"address": "г. Москва"},
                        "center": {"x": 37.61, "y": 55.75},
                        "geometry": {
                            "type": "Point",
                            "coordinates": [37.61, 55.75],
                        },
                    }
                }
            ),
        )

        location = fetch_location_by_cadastral_number("77:01:0004010:123")

        self.assertEqual(location.address, "г. Москва")
        self.assertEqual(location.center_lon, 37.61)
        self.assertEqual(location.center_lat, 55.75)
        self.assertEqual(location.geometry.geom_type, "Point")

    @patch("document_processor.services.rosreestr.requests.get")
    def test_fetch_location_not_found(self, mock_get):
        mock_get.return_value = Mock(status_code=404)

        with self.assertRaises(RosreestrNotFoundError):
            fetch_location_by_cadastral_number("00:00:000000:000")

    @patch("document_processor.services.rosreestr.requests.get")
    def test_fetch_location_api_error(self, mock_get):
        mock_get.return_value = Mock(status_code=500)

        with self.assertRaises(RosreestrError):
            fetch_location_by_cadastral_number("77:01:0004010:123")


class CadastralLocationViewTests(SimpleTestCase):
    @patch("document_processor.views.fetch_location_by_cadastral_number")
    def test_view_returns_json(self, mock_fetch):
        mock_fetch.return_value = Mock(
            cadastral_number="77:01:0004010:123",
            address="г. Москва",
            center_lat=55.75,
            center_lon=37.61,
            geometry=Mock(geojson='{"type":"Point","coordinates":[37.61,55.75]}'),
        )

        response = self.client.get(
            reverse(
                "cadastral-location",
                kwargs={"cadastral_number": "77:01:0004010:123"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["address"], "г. Москва")

    @patch("document_processor.views.fetch_location_by_cadastral_number")
    def test_view_handles_not_found(self, mock_fetch):
        mock_fetch.side_effect = RosreestrNotFoundError("not found")

        response = self.client.get(
            reverse(
                "cadastral-location",
                kwargs={"cadastral_number": "00:00:000000:000"},
            )
        )

        self.assertEqual(response.status_code, 404)
