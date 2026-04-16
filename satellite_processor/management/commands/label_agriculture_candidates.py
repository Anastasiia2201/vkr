from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from satellite_processor.services.planetary import (
    PlanetaryError,
    build_preview_content,
    build_rgb_preview,
    extract_features,
    find_best_sentinel_item,
    read_bands_with_nir,
)


AGRICULTURE_CANDIDATES = [
    {"id": "agri_01", "region": "Rostov Oblast", "bbox": [39.1800, 47.1200, 39.2050, 47.1450]},
    {"id": "agri_02", "region": "Rostov Oblast", "bbox": [39.2450, 47.0850, 39.2700, 47.1100]},
    {"id": "agri_03", "region": "Rostov Oblast", "bbox": [39.3150, 47.1600, 39.3400, 47.1850]},
    {"id": "agri_04", "region": "Rostov Oblast", "bbox": [39.4100, 47.0400, 39.4350, 47.0650]},
    {"id": "agri_05", "region": "Rostov Oblast", "bbox": [39.5200, 46.9800, 39.5450, 47.0050]},
    {"id": "agri_06", "region": "Rostov Oblast", "bbox": [40.1200, 47.3600, 40.1450, 47.3850]},
    {"id": "agri_07", "region": "Rostov Oblast", "bbox": [40.2600, 47.2500, 40.2850, 47.2750]},
    {"id": "agri_08", "region": "Rostov Oblast", "bbox": [40.4800, 47.1800, 40.5050, 47.2050]},
    {"id": "agri_09", "region": "Krasnodar Krai", "bbox": [40.9200, 45.0800, 40.9450, 45.1050]},
    {"id": "agri_10", "region": "Krasnodar Krai", "bbox": [40.7800, 45.0200, 40.8050, 45.0450]},
    {"id": "agri_11", "region": "Krasnodar Krai", "bbox": [40.6400, 45.1400, 40.6650, 45.1650]},
    {"id": "agri_12", "region": "Krasnodar Krai", "bbox": [40.5200, 45.0600, 40.5450, 45.0850]},
    {"id": "agri_13", "region": "Krasnodar Krai", "bbox": [40.3500, 45.1800, 40.3750, 45.2050]},
    {"id": "agri_14", "region": "Krasnodar Krai", "bbox": [40.1800, 45.1200, 40.2050, 45.1450]},
    {"id": "agri_15", "region": "Voronezh Oblast", "bbox": [39.8200, 50.9200, 39.8450, 50.9450]},
    {"id": "agri_16", "region": "Voronezh Oblast", "bbox": [40.1200, 50.9800, 40.1450, 51.0050]},
    {"id": "agri_17", "region": "Voronezh Oblast", "bbox": [39.9800, 51.1400, 40.0050, 51.1650]},
    {"id": "agri_18", "region": "Voronezh Oblast", "bbox": [39.6200, 50.8600, 39.6450, 50.8850]},
    {"id": "agri_19", "region": "Belgorod Oblast", "bbox": [37.8800, 50.7200, 37.9050, 50.7450]},
    {"id": "agri_20", "region": "Belgorod Oblast", "bbox": [38.0200, 50.8400, 38.0450, 50.8650]},
]

AGRICULTURE_CANDIDATES_2 = [
    # Краснодарский край (очень высокая вероятность agriculture)
    {"id": "agri_21", "region": "Krasnodar", "bbox": [39.020, 45.150, 39.045, 45.175]},
    {"id": "agri_22", "region": "Krasnodar", "bbox": [39.100, 45.120, 39.125, 45.145]},
    {"id": "agri_23", "region": "Krasnodar", "bbox": [39.180, 45.090, 39.205, 45.115]},
    {"id": "agri_24", "region": "Krasnodar", "bbox": [39.250, 45.050, 39.275, 45.075]},
    {"id": "agri_25", "region": "Krasnodar", "bbox": [39.320, 45.130, 39.345, 45.155]},
    {"id": "agri_26", "region": "Krasnodar", "bbox": [39.400, 45.170, 39.425, 45.195]},

    # Ставропольский край
    {"id": "agri_27", "region": "Stavropol", "bbox": [42.050, 45.200, 42.075, 45.225]},
    {"id": "agri_28", "region": "Stavropol", "bbox": [42.120, 45.260, 42.145, 45.285]},
    {"id": "agri_29", "region": "Stavropol", "bbox": [42.200, 45.180, 42.225, 45.205]},
    {"id": "agri_30", "region": "Stavropol", "bbox": [42.300, 45.240, 42.325, 45.265]},

    # Ростовская область
    {"id": "agri_31", "region": "Rostov", "bbox": [40.000, 47.200, 40.025, 47.225]},
    {"id": "agri_32", "region": "Rostov", "bbox": [40.080, 47.150, 40.105, 47.175]},
    {"id": "agri_33", "region": "Rostov", "bbox": [40.160, 47.100, 40.185, 47.125]},
    {"id": "agri_34", "region": "Rostov", "bbox": [40.240, 47.050, 40.265, 47.075]},

    # Воронежская область
    {"id": "agri_35", "region": "Voronezh", "bbox": [40.400, 51.000, 40.425, 51.025]},
    {"id": "agri_36", "region": "Voronezh", "bbox": [40.500, 50.950, 40.525, 50.975]},
    {"id": "agri_37", "region": "Voronezh", "bbox": [40.600, 50.900, 40.625, 50.925]},

    # Белгородская область
    {"id": "agri_38", "region": "Belgorod", "bbox": [38.600, 50.600, 38.625, 50.625]},
    {"id": "agri_39", "region": "Belgorod", "bbox": [38.700, 50.550, 38.725, 50.575]},

    # Татарстан
    {"id": "agri_40", "region": "Tatarstan", "bbox": [49.200, 55.700, 49.225, 55.725]},
]


BUILT_UP_CANDIDATES = [
    {"id": "built_01", "region": "Rostov", "bbox": [39.700, 47.240, 39.715, 47.255]},
    {"id": "built_02", "region": "Rostov", "bbox": [39.760, 47.210, 39.775, 47.225]},
    {"id": "built_03", "region": "Rostov", "bbox": [40.050, 47.180, 40.065, 47.195]},
    {"id": "built_04", "region": "Rostov", "bbox": [40.120, 47.140, 40.135, 47.155]},
    {"id": "built_05", "region": "Rostov", "bbox": [40.200, 47.100, 40.215, 47.115]},

    {"id": "built_06", "region": "Krasnodar", "bbox": [39.080, 45.060, 39.095, 45.075]},
    {"id": "built_07", "region": "Krasnodar", "bbox": [39.140, 45.020, 39.155, 45.035]},
    {"id": "built_08", "region": "Krasnodar", "bbox": [39.200, 45.000, 39.215, 45.015]},
    {"id": "built_09", "region": "Krasnodar", "bbox": [39.260, 45.040, 39.275, 45.055]},
    {"id": "built_10", "region": "Krasnodar", "bbox": [39.320, 45.080, 39.335, 45.095]},
]

BARE_CANDIDATES = VBARE_CANDIDATES_2 = [
    # Ростовская область (очень хорошие сухие поля)
    {"id": "bare_21", "region": "Rostov", "bbox": [39.700, 46.900, 39.725, 46.925]},
    {"id": "bare_22", "region": "Rostov", "bbox": [39.780, 46.850, 39.805, 46.875]},
    {"id": "bare_23", "region": "Rostov", "bbox": [39.860, 46.800, 39.885, 46.825]},
    {"id": "bare_24", "region": "Rostov", "bbox": [39.940, 46.750, 39.965, 46.775]},
    {"id": "bare_25", "region": "Rostov", "bbox": [40.020, 46.700, 40.045, 46.725]},

    # Калмыкия (очень много настоящего bare)
    {"id": "bare_26", "region": "Kalmykia", "bbox": [44.000, 46.200, 44.025, 46.225]},
    {"id": "bare_27", "region": "Kalmykia", "bbox": [44.100, 46.150, 44.125, 46.175]},
    {"id": "bare_28", "region": "Kalmykia", "bbox": [44.200, 46.100, 44.225, 46.125]},
    {"id": "bare_29", "region": "Kalmykia", "bbox": [44.300, 46.050, 44.325, 46.075]},
    {"id": "bare_30", "region": "Kalmykia", "bbox": [44.400, 46.000, 44.425, 46.025]},

    # Астраханская область (полупустыня)
    {"id": "bare_31", "region": "Astrakhan", "bbox": [47.000, 46.300, 47.025, 46.325]},
    {"id": "bare_32", "region": "Astrakhan", "bbox": [47.100, 46.250, 47.125, 46.275]},
    {"id": "bare_33", "region": "Astrakhan", "bbox": [47.200, 46.200, 47.225, 46.225]},
    {"id": "bare_34", "region": "Astrakhan", "bbox": [47.300, 46.150, 47.325, 46.175]},

    # Ставрополь (сухие участки)
    {"id": "bare_35", "region": "Stavropol", "bbox": [42.400, 44.900, 42.425, 44.925]},
    {"id": "bare_36", "region": "Stavropol", "bbox": [42.500, 44.850, 42.525, 44.875]},
    {"id": "bare_37", "region": "Stavropol", "bbox": [42.600, 44.800, 42.625, 44.825]},

    # Волгоградская область
    {"id": "bare_38", "region": "Volgograd", "bbox": [43.500, 48.500, 43.525, 48.525]},
    {"id": "bare_39", "region": "Volgograd", "bbox": [43.600, 48.450, 43.625, 48.475]},
    {"id": "bare_40", "region": "Volgograd", "bbox": [43.700, 48.400, 43.725, 48.425]},
]

BUILT_UP_DENSE = [
# Ростов — плотные поселки
{"id":"built_51","region":"Rostov","bbox":[39.720,47.230,39.730,47.240]},
{"id":"built_52","region":"Rostov","bbox":[39.750,47.210,39.760,47.220]},
{"id":"built_53","region":"Rostov","bbox":[39.780,47.190,39.790,47.200]},
{"id":"built_54","region":"Rostov","bbox":[39.810,47.170,39.820,47.180]},
{"id":"built_55","region":"Rostov","bbox":[39.840,47.150,39.850,47.160]},

# Краснодар — частный сектор плотный
{"id":"built_56","region":"Krasnodar","bbox":[39.050,45.040,39.060,45.050]},
{"id":"built_57","region":"Krasnodar","bbox":[39.080,45.020,39.090,45.030]},
{"id":"built_58","region":"Krasnodar","bbox":[39.110,45.010,39.120,45.020]},
{"id":"built_59","region":"Krasnodar","bbox":[39.140,45.030,39.150,45.040]},
{"id":"built_60","region":"Krasnodar","bbox":[39.170,45.050,39.180,45.060]},

# Воронеж — плотные деревни
{"id":"built_61","region":"Voronezh","bbox":[39.250,51.600,39.260,51.610]},
{"id":"built_62","region":"Voronezh","bbox":[39.280,51.580,39.290,51.590]},
{"id":"built_63","region":"Voronezh","bbox":[39.310,51.560,39.320,51.570]},
{"id":"built_64","region":"Voronezh","bbox":[39.340,51.540,39.350,51.550]},
{"id":"built_65","region":"Voronezh","bbox":[39.370,51.520,39.380,51.530]},

# Белгород — компактные поселки
{"id":"built_66","region":"Belgorod","bbox":[36.650,50.580,36.660,50.590]},
{"id":"built_67","region":"Belgorod","bbox":[36.680,50.560,36.690,50.570]},
{"id":"built_68","region":"Belgorod","bbox":[36.710,50.540,36.720,50.550]},
{"id":"built_69","region":"Belgorod","bbox":[36.740,50.520,36.750,50.530]},
{"id":"built_70","region":"Belgorod","bbox":[36.770,50.500,36.780,50.510]},

# Татарстан — плотная застройка
{"id":"built_71","region":"Tatarstan","bbox":[49.150,55.700,49.160,55.710]},
{"id":"built_72","region":"Tatarstan","bbox":[49.180,55.680,49.190,55.690]},
{"id":"built_73","region":"Tatarstan","bbox":[49.210,55.660,49.220,55.670]},
{"id":"built_74","region":"Tatarstan","bbox":[49.240,55.640,49.250,55.650]},
{"id":"built_75","region":"Tatarstan","bbox":[49.270,55.620,49.280,55.630]},

# Волгоград — поселки
{"id":"built_76","region":"Volgograd","bbox":[43.550,48.600,43.560,48.610]},
{"id":"built_77","region":"Volgograd","bbox":[43.580,48.580,43.590,48.590]},
{"id":"built_78","region":"Volgograd","bbox":[43.610,48.560,43.620,48.570]},
{"id":"built_79","region":"Volgograd","bbox":[43.640,48.540,43.650,48.550]},
{"id":"built_80","region":"Volgograd","bbox":[43.670,48.520,43.680,48.530]},

# Дополнительные — более плотные зоны
{"id":"built_81","region":"South","bbox":[40.000,45.000,40.010,45.010]},
{"id":"built_82","region":"South","bbox":[40.050,45.020,40.060,45.030]},
{"id":"built_83","region":"South","bbox":[40.100,45.040,40.110,45.050]},
{"id":"built_84","region":"South","bbox":[40.150,45.060,40.160,45.070]},
{"id":"built_85","region":"South","bbox":[40.200,45.080,40.210,45.090]},

{"id":"built_86","region":"South","bbox":[38.500,45.200,38.510,45.210]},
{"id":"built_87","region":"South","bbox":[38.550,45.220,38.560,45.230]},
{"id":"built_88","region":"South","bbox":[38.600,45.240,38.610,45.250]},
{"id":"built_89","region":"South","bbox":[38.650,45.260,38.660,45.270]},
{"id":"built_90","region":"South","bbox":[38.700,45.280,38.710,45.290]},

{"id":"built_91","region":"South","bbox":[41.000,44.800,41.010,44.810]},
{"id":"built_92","region":"South","bbox":[41.050,44.820,41.060,44.830]},
{"id":"built_93","region":"South","bbox":[41.100,44.840,41.110,44.850]},
{"id":"built_94","region":"South","bbox":[41.150,44.860,41.160,44.870]},
{"id":"built_95","region":"South","bbox":[41.200,44.880,41.210,44.890]},

{"id":"built_96","region":"South","bbox":[42.000,44.600,42.010,44.610]},
{"id":"built_97","region":"South","bbox":[42.050,44.620,42.060,44.630]},
{"id":"built_98","region":"South","bbox":[42.100,44.640,42.110,44.650]},
{"id":"built_99","region":"South","bbox":[42.150,44.660,42.160,44.670]},
{"id":"built_100","region":"South","bbox":[42.200,44.680,42.210,44.690]},
]

BARE_CANDIDATES_3 = [
# Калмыкия (идеальный bare)
{"id":"bare_41","region":"Kalmykia","bbox":[44.500,46.000,44.525,46.025]},
{"id":"bare_42","region":"Kalmykia","bbox":[44.600,45.950,44.625,45.975]},
{"id":"bare_43","region":"Kalmykia","bbox":[44.700,45.900,44.725,45.925]},
{"id":"bare_44","region":"Kalmykia","bbox":[44.800,45.850,44.825,45.875]},
{"id":"bare_45","region":"Kalmykia","bbox":[44.900,45.800,44.925,45.825]},

# Астрахань
{"id":"bare_46","region":"Astrakhan","bbox":[47.400,46.200,47.425,46.225]},
{"id":"bare_47","region":"Astrakhan","bbox":[47.500,46.150,47.525,46.175]},
{"id":"bare_48","region":"Astrakhan","bbox":[47.600,46.100,47.625,46.125]},
{"id":"bare_49","region":"Astrakhan","bbox":[47.700,46.050,47.725,46.075]},
{"id":"bare_50","region":"Astrakhan","bbox":[47.800,46.000,47.825,46.025]},

# Волгоград
{"id":"bare_51","region":"Volgograd","bbox":[44.100,48.200,44.125,48.225]},
{"id":"bare_52","region":"Volgograd","bbox":[44.200,48.150,44.225,48.175]},
{"id":"bare_53","region":"Volgograd","bbox":[44.300,48.100,44.325,48.125]},
{"id":"bare_54","region":"Volgograd","bbox":[44.400,48.050,44.425,48.075]},
{"id":"bare_55","region":"Volgograd","bbox":[44.500,48.000,44.525,48.025]},

# Ставрополь (сухие зоны)
{"id":"bare_56","region":"Stavropol","bbox":[42.700,44.700,42.725,44.725]},
{"id":"bare_57","region":"Stavropol","bbox":[42.800,44.650,42.825,44.675]},
{"id":"bare_58","region":"Stavropol","bbox":[42.900,44.600,42.925,44.625]},
{"id":"bare_59","region":"Stavropol","bbox":[43.000,44.550,43.025,44.575]},
{"id":"bare_60","region":"Stavropol","bbox":[43.100,44.500,43.125,44.525]},

# Ростов (сухие поля)
{"id":"bare_61","region":"Rostov","bbox":[40.200,46.600,40.225,46.625]},
{"id":"bare_62","region":"Rostov","bbox":[40.300,46.550,40.325,46.575]},
{"id":"bare_63","region":"Rostov","bbox":[40.400,46.500,40.425,46.525]},
{"id":"bare_64","region":"Rostov","bbox":[40.500,46.450,40.525,46.475]},
{"id":"bare_65","region":"Rostov","bbox":[40.600,46.400,40.625,46.425]},

# Казахстан граница (очень сухо)
{"id":"bare_66","region":"SouthRussia","bbox":[48.500,46.500,48.525,46.525]},
{"id":"bare_67","region":"SouthRussia","bbox":[48.600,46.450,48.625,46.475]},
{"id":"bare_68","region":"SouthRussia","bbox":[48.700,46.400,48.725,46.425]},
{"id":"bare_69","region":"SouthRussia","bbox":[48.800,46.350,48.825,46.375]},
{"id":"bare_70","region":"SouthRussia","bbox":[48.900,46.300,48.925,46.325]},
]

ALL_CANDIDATES = BUILT_UP_DENSE


class Command(BaseCommand):
    help = (
        "Загружает bbox-кандидаты сельхозполей, получает снимки, "
        "спрашивает label и сохраняет в dataset.json."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", type=str, default="dataset2.json")
        parser.add_argument("--images-dir", type=str, default="dataset_images_manual")
        parser.add_argument("--start-date", type=str, default="2025-05-01")
        parser.add_argument("--end-date", type=str, default="2025-09-30")
        parser.add_argument("--max-cloud-cover", type=float, default=15.0)
        parser.add_argument("--max-snow-ice", type=float, default=5.0)
        parser.add_argument("--only-without-label", action="store_true")

    def handle(self, *args, **options):
        output_path = Path(options["output"]).expanduser().resolve()
        images_dir = Path(options["images_dir"]).expanduser().resolve()
        images_dir.mkdir(parents=True, exist_ok=True)

        dataset = self._load_dataset(output_path)
        existing_ids = {
            item.get("candidate_id")
            for item in dataset
            if item.get("candidate_id")
        }

        start_date = date.fromisoformat(options["start_date"])
        end_date = date.fromisoformat(options["end_date"])

        saved = 0
        skipped = 0
        failed = 0

        for candidate in ALL_CANDIDATES:
            candidate_id = candidate["id"]
            bbox = candidate["bbox"]

            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(f"{candidate_id} | {candidate['region']} | bbox={bbox}")

            if options["only_without_label"] and candidate_id in existing_ids:
                skipped += 1
                self.stdout.write(self.style.WARNING("Уже есть в dataset.json, пропуск."))
                continue

            try:
                item = find_best_sentinel_item(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=options["max_cloud_cover"],
                    max_snow_ice_percentage=options["max_snow_ice"],
                )

                red, green, blue, nir = read_bands_with_nir(item, bbox)
                features = extract_features(red, green, blue, nir)
                rgb = build_rgb_preview(red, green, blue)
                preview_content = build_preview_content(rgb)

            except PlanetaryError as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"PlanetaryError: {exc}"))
                continue
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"Ошибка получения снимка: {exc}"))
                continue

            image_path = images_dir / f"{candidate_id}_{item.id}.png"
            image_path.write_bytes(preview_content.read())

            self.stdout.write(f"Снимок: {image_path}")
            self.stdout.write(f"Scene ID: {item.id}")
            self.stdout.write(f"Features: {features}")

            self._open_image(image_path)

            label = self._ask_label(default="built_up")
            if label == "quit":
                break
            if label == "skip":
                skipped += 1
                continue

            comment = input("Комментарий (можно пусто): ").strip()
            confidence = self._ask_confidence()

            record = {
                "candidate_id": candidate_id,
                "source_type": "manual_bbox",
                "region": candidate["region"],
                "bbox": bbox,
                "label": label,
                "comment": comment,
                "confidence": confidence,
                "image_path": str(image_path),
                "scene_id": item.id,
                "acquisition_date": item.properties.get("datetime"),
                "cloud_cover": item.properties.get("eo:cloud_cover"),
                "ndvi": features.get("mean_ndvi"),
                "features": features,
            }

            dataset.append(record)
            existing_ids.add(candidate_id)
            self._save_dataset(output_path, dataset)
            saved += 1
            self.stdout.write(self.style.SUCCESS("Запись сохранена."))

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(f"Сохранено: {saved}"))
        self.stdout.write(self.style.WARNING(f"Пропущено: {skipped}"))
        self.stdout.write(self.style.ERROR(f"Ошибок: {failed}"))

    def _load_dataset(self, output_path: Path) -> list[dict]:
        if not output_path.exists():
            return []
        return json.loads(output_path.read_text(encoding="utf-8"))

    def _save_dataset(self, output_path: Path, dataset: list[dict]) -> None:
        output_path.write_text(
            json.dumps(dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _open_image(self, image_path: Path) -> bool:
        open_commands = [
            ["wslview", str(image_path)],
            ["xdg-open", str(image_path)],
        ]

        for cmd in open_commands:
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except Exception:
                    continue
        return False

    def _ask_label(self, default: str = "agriculture") -> str:
        allowed = {"agriculture", "overgrown", "bare", "built_up", "skip", "quit"}
        while True:
            raw = input(
                f"Label [Enter={default}] "
                "(agriculture / overgrown / bare / built_up / skip / quit): "
            ).strip().lower()

            if not raw:
                return default
            if raw in allowed:
                return raw
            print("Некорректный label.")

    def _ask_confidence(self) -> float | None:
        raw = input("Уверенность [0..1], можно пусто: ").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            print("Некорректное число, confidence пропущен.")
            return None
        if not (0.0 <= value <= 1.0):
            print("Число должно быть в диапазоне [0..1], confidence пропущен.")
            return None
        return value
