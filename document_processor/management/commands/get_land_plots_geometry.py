from __future__ import annotations

from django.core.management.base import BaseCommand

from document_processor.models import LandPlot
from document_processor.services.rosreestr import (
    RosreestrError,
    fetch_location_by_cadastral_number,
)


class Command(BaseCommand):
    help = (
        "Заполняет geometry и связанные данные LandPlot по кадастровому номеру "
        "через Росреестр."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-without-geometry",
            action="store_true",
            help="Обрабатывать только участки без geometry",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Ограничить число участков",
        )
        parser.add_argument(
            "--cadastre",
            type=str,
            default=None,
            help="Обработать только один кадастровый номер",
        )

    def handle(self, *args, **options):
        qs = LandPlot.objects.all().order_by("id")

        if options["cadastre"]:
            qs = qs.filter(cadastral_number=options["cadastre"])

        if options["only_without_geometry"]:
            qs = qs.filter(geometry__isnull=True)

        limit = options["limit"]
        if limit:
            qs = qs[:limit]

        success_count = 0
        skipped_count = 0
        failed_count = 0

        for land_plot in qs:
            cad = land_plot.cadastral_number
            self.stdout.write("-" * 80)
            self.stdout.write(f"Участок: {cad}")

            if land_plot.geometry and options["only_without_geometry"]:
                skipped_count += 1
                self.stdout.write(self.style.WARNING("Геометрия уже есть, пропуск."))
                continue

            try:
                result = fetch_location_by_cadastral_number(cad)

                updated_plot = LandPlot.objects.get(cadastral_number=cad)
                has_geometry = updated_plot.geometry is not None

                if has_geometry:
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Геометрия сохранена. "
                            f"Адрес: {result.address}, "
                            f"центр: ({result.center_lat}, {result.center_lon})"
                        )
                    )
                else:
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR("Ответ получен, но geometry не сохранена.")
                    )

            except RosreestrError as exc:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"RosreestrError: {exc}"))
            except Exception as exc:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"Ошибка: {exc}"))

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS(f"Успешно: {success_count}"))
        self.stdout.write(self.style.WARNING(f"Пропущено: {skipped_count}"))
        self.stdout.write(self.style.ERROR(f"Ошибок: {failed_count}"))
