import requests
from django.contrib.gis.geos import GEOSGeometry


def fetch_geometry(cadastral_number):
    url = f"https://pkk.rosreestr.ru/api/features/1/{cadastral_number}"
    response = requests.get(url)

    if response.status_code != 200:
        return None

    data = response.json()

    geom_json = data['feature']['geometry']
    return GEOSGeometry(str(geom_json))
