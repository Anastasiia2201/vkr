from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.timezone import localtime

from document_processor.models import LandPlot
from satellite_processor.services.planetary import PlanetaryError, save_planetary_preview


class Command(BaseCommand):
    help = (
        "Для каждого LandPlot получает спутниковый снимок, открывает его, "
        "запрашивает label и сохраняет разметку в JSON."
    )

    DEFAULT_LABELS = {
        "agriculture",
        "overgrown",
        "built_up",
        "bare",
        "skip",
        "quit",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="dataset.json",
            help="Путь к JSON-файлу разметки",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            default="dataset_images",
            help="Папка для локальных копий снимков",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Дата начала поиска снимков, YYYY-MM-DD",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Дата конца поиска снимков, YYYY-MM-DD",
        )
        parser.add_argument(
            "--max-cloud-cover",
            type=float,
            default=20.0,
            help="Максимальная облачность",
        )
        parser.add_argument(
            "--max-snow-ice",
            type=float,
            default=20.0,
            help="Максимальный процент снега/льда",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Ограничить число участков",
        )
        parser.add_argument(
            "--only-without-label",
            action="store_true",
            help="Пропускать участки, которые уже есть в JSON",
        )
        parser.add_argument(
            "--min-area",
            type=float,
            default=None,
            help="Минимальная площадь участка в гектарах",
        )
        parser.add_argument(
            "--max-area",
            type=float,
            default=None,
            help="Максимальная площадь участка в гектарах",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"]).expanduser().resolve()
        images_dir = Path(options["images_dir"]).expanduser().resolve()
        images_dir.mkdir(parents=True, exist_ok=True)

        dataset = self._load_dataset(output_path)
        existing_cadastral_numbers = {
            item.get("cadastral_number")
            for item in dataset
            if item.get("cadastral_number")
        }

        qs = LandPlot.objects.filter(geometry__isnull=False).order_by("id")

        min_area = options["min_area"]
        max_area = options["max_area"]

        if min_area is not None or max_area is not None:
            qs = qs.filter(area_hectares__isnull=False)

        if min_area is not None:
            qs = qs.filter(area_hectares__gte=min_area)

        if max_area is not None:
            qs = qs.filter(area_hectares__lte=max_area)

        limit = options["limit"]
        if limit:
            qs = qs[:limit]

        processed = 0
        saved = 0
        skipped = 0
        failed = 0

        self.stdout.write(f"JSON: {output_path}")
        self.stdout.write(f"Папка снимков: {images_dir}")
        self.stdout.write(
            f"Фильтр площади: min_area={min_area}, max_area={max_area}"
        )
        self.stdout.write(
            f"Участков к обходу: {qs.count() if hasattr(qs, 'count') else 'unknown'}"
        )

        search_start_date = self._parse_date(options["start_date"])
        search_end_date = self._parse_date(options["end_date"])

        for land_plot in qs:
            cadastral_number = land_plot.cadastral_number
            processed += 1

            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(f"[{processed}] Участок: {cadastral_number}")
            self.stdout.write(f"Площадь, га: {land_plot.area_hectares}")

            if (
                options["only_without_label"]
                and cadastral_number in existing_cadastral_numbers
            ):
                skipped += 1
                self.stdout.write(
                    self.style.WARNING("Уже размечен в JSON, пропуск.")
                )
                continue

            try:
                satellite_image = save_planetary_preview(
                    land_plot=land_plot,
                    start_date=search_start_date,
                    end_date=search_end_date,
                    max_cloud_cover=options["max_cloud_cover"],
                    max_snow_ice_percentage=options["max_snow_ice"],
                )
            except PlanetaryError as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"PlanetaryError: {exc}"))
                continue
            except Exception as exc:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f"Ошибка получения снимка: {exc}")
                )
                continue

            if not satellite_image.preview_image:
                failed += 1
                self.stdout.write(
                    self.style.ERROR("У снимка отсутствует preview_image.")
                )
                continue

            source_image_path = Path(satellite_image.preview_image.path)
            local_image_path = images_dir / source_image_path.name

            try:
                shutil.copy2(source_image_path, local_image_path)
            except Exception as exc:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"Не удалось скопировать изображение: {exc}"
                    )
                )
                continue

            acquisition_date = satellite_image.acquisition_date
            acquisition_date_str = (
                localtime(acquisition_date).isoformat()
                if acquisition_date is not None
                else None
            )

            self.stdout.write(f"Локальный файл: {local_image_path}")
            self.stdout.write(f"Дата съемки: {acquisition_date_str}")
            self.stdout.write(f"Облачность: {satellite_image.cloud_cover}")
            self.stdout.write(f"Scene ID: {satellite_image.scene_id}")
            self.stdout.write(f"NDVI: {satellite_image.ndvi}")
            self.stdout.write(f"Features: {satellite_image.features}")

            opened = self._open_image(local_image_path)
            if not opened:
                self.stdout.write(
                    self.style.WARNING(
                        "Не удалось автоматически открыть изображение. "
                        "Открой его вручную."
                    )
                )

            label = self._ask_label()
            if label == "quit":
                self.stdout.write(
                    self.style.WARNING("Завершение по запросу пользователя.")
                )
                break

            if label == "skip":
                skipped += 1
                self.stdout.write(self.style.WARNING("Разметка пропущена."))
                continue

            comment = input("Комментарий (можно пусто): ").strip()
            confidence = self._ask_confidence()

            record = {
                "cadastral_number": cadastral_number,
                "label": label,
                "comment": comment,
                "confidence": confidence,
                "image_path": str(local_image_path),
                "preview_image": satellite_image.preview_image.name,
                "acquisition_date": acquisition_date_str,
                "cloud_cover": satellite_image.cloud_cover,
                "scene_id": satellite_image.scene_id,
                "source": satellite_image.source,
                "bbox": satellite_image.bbox,
                "ndvi": satellite_image.ndvi,
                "features": satellite_image.features or {},
                "land_plot": {
                    "location": land_plot.location,
                    "area_hectares": land_plot.area_hectares,
                    "use_type": land_plot.use_type,
                },
            }

            dataset.append(record)
            existing_cadastral_numbers.add(cadastral_number)
            self._save_dataset(output_path, dataset)

            saved += 1
            self.stdout.write(self.style.SUCCESS("Запись сохранена в JSON."))

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(f"Сохранено: {saved}"))
        self.stdout.write(self.style.WARNING(f"Пропущено: {skipped}"))
        self.stdout.write(self.style.ERROR(f"Ошибок: {failed}"))

    def _parse_date(self, value: str | None):
        if not value:
            return None

        from datetime import date

        return date.fromisoformat(value)

    def _load_dataset(self, output_path: Path) -> list[dict]:
        if not output_path.exists():
            return []

        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Некорректный JSON в {output_path}: {exc}"
            ) from exc

    def _save_dataset(self, output_path: Path, dataset: list[dict]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
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

    def _ask_label(self) -> str:
        while True:
            value = input(
                "Label "
                "(agriculture / overgrown / built_up / bare / skip / quit): "
            ).strip().lower()

            if value in self.DEFAULT_LABELS:
                return value

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
            print(
                "Число должно быть в диапазоне [0..1], confidence пропущен."
            )
            return None

        return value
