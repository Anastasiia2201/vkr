import subprocess
import json
from django.contrib.gis.geos import GEOSGeometry

def get_geometry_cli(cad_num):
    result = subprocess.run(
        ["rosreestr2coord", "-c", cad_num],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return None

    # Будет создан файл *.geojson в рабочей директории
    # Здесь нужно найти этот файл и прочитать его
    # (обычно он создаётся под именем <cadastral>.geojson)
    fname = f"{cad_num}.geojson"
    with open(fname, "r", encoding="utf-8") as f:
        gj = json.load(f)

    return GEOSGeometry(json.dumps(gj["features"][0]["geometry"]))