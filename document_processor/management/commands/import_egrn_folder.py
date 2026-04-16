from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from document_processor.models import SourceDocument, LandPlot
from document_processor.services.text_extractor import extract_text_from_document
from document_processor.services.re_parser import parse_egrn_document
from document_processor.services.document_processor import save_egrn_data
from document_processor.services.rosreestr import (
    fetch_location_by_cadastral_number,
    RosreestrError,
)


def calculate_local_file_hash(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class Command(BaseCommand):
    help = (
        "Импортирует выписки ЕГРН из папки, сохраняет SourceDocument, "
        "создаёт/обновляет LandPlot и получает geometry/bbox через Росреестр."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--folder",
            type=str,
            default="egrn",
            help="Папка с PDF-файлами выписок ЕГРН",
        )
        parser.add_argument(
            "--force-ocr",
            action="store_true",
            help="Всегда использовать OCR при извлечении текста",
        )
        parser.add_argument(
            "--force-reprocess",
            action="store_true",
            help="Обрабатывать документ заново, даже если такой hash уже есть",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Ограничить количество файлов",
        )

    def handle(self, *args, **options):
        folder = Path(options["folder"]).expanduser().resolve()
        force_ocr = options["force_ocr"]
        force_reprocess = options["force_reprocess"]
        limit = options["limit"]

        if not folder.exists() or not folder.is_dir():
            self.stderr.write(self.style.ERROR(f"Папка не найдена: {folder}"))
            return

        files = sorted(
            [
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in {".pdf"}
            ]
        )

        if limit:
            files = files[:limit]

        if not files:
            self.stdout.write(self.style.WARNING("PDF-файлы не найдены."))
            return

        created_docs = 0
        updated_docs = 0
        created_plots = 0
        updated_plots = 0
        bbox_ok = 0
        failed = 0

        self.stdout.write(f"Папка: {folder}")
        self.stdout.write(f"Файлов к обработке: {len(files)}")

        for index, file_path in enumerate(files, start=1):
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(f"[{index}/{len(files)}] {file_path.name}")

            try:
                file_hash = calculate_local_file_hash(file_path)

                document = SourceDocument.objects.filter(file_hash=file_hash).first()

                if document and not force_reprocess:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Документ уже есть в базе: id={document.id}"
                        )
                    )
                else:
                    if document is None:
                        with file_path.open("rb") as f:
                            django_file = File(f, name=file_path.name)
                            document = SourceDocument.objects.create(
                                file=django_file,
                                original_filename=file_path.name,
                                document_type=SourceDocument.DocumentType.EGRN,
                                file_hash=file_hash,
                                status=SourceDocument.ProcessingStatus.UPLOADED,
                            )
                        created_docs += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Создан SourceDocument id={document.id}"
                            )
                        )
                    else:
                        updated_docs += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Повторная обработка SourceDocument id={document.id}"
                            )
                        )

                    text, ocr_used = extract_text_from_document(
                        str(file_path),
                        force_ocr=force_ocr,
                    )

                    resolved_data = parse_egrn_document(text)

                    document.document_type = SourceDocument.DocumentType.EGRN
                    document.text_content = text
                    document.ocr_used = ocr_used
                    document.status = SourceDocument.ProcessingStatus.PROCESSED
                    document.metadata = {
                        "parsing_version": "v4",
                        "detected_document_type": SourceDocument.DocumentType.EGRN,
                        "resolved_by": "parse_egrn_document",
                        "resolved_data": resolved_data,
                    }
                    document.save(
                        update_fields=[
                            "document_type",
                            "text_content",
                            "ocr_used",
                            "status",
                            "metadata",
                        ]
                    )

                    existing_plot = None
                    cadastral_number = resolved_data.get("cadastral_number")
                    if cadastral_number:
                        existing_plot = LandPlot.objects.filter(
                            cadastral_number=cadastral_number
                        ).first()

                    save_egrn_data(document, resolved_data)

                    if cadastral_number:
                        plot = LandPlot.objects.filter(
                            cadastral_number=cadastral_number
                        ).first()
                        if plot:
                            if existing_plot is None:
                                created_plots += 1
                            else:
                                updated_plots += 1

                resolved_data = (document.metadata or {}).get("resolved_data") or {}
                cadastral_number = resolved_data.get("cadastral_number")

                if not cadastral_number:
                    self.stdout.write(
                        self.style.ERROR("Кадастровый номер не найден в документе.")
                    )
                    failed += 1
                    continue

                try:
                    fetch_location_by_cadastral_number(cadastral_number)
                except RosreestrError as exc:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Не удалось получить геометрию из Росреестра: {exc}"
                        )
                    )
                    failed += 1
                    continue

                land_plot = LandPlot.objects.get(cadastral_number=cadastral_number)

                if not land_plot.geometry:
                    self.stdout.write(
                        self.style.ERROR("Geometry не сохранена.")
                    )
                    failed += 1
                    continue

                minx, miny, maxx, maxy = land_plot.geometry.extent
                bbox = [minx, miny, maxx, maxy]
                bbox_ok += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"LandPlot: {land_plot.cadastral_number}"
                    )
                )
                self.stdout.write(f"Площадь, га: {land_plot.area_hectares}")
                self.stdout.write(f"Адрес: {land_plot.location}")
                self.stdout.write(f"use_type: {land_plot.use_type}")
                self.stdout.write(f"bbox: {bbox}")

            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(f"Ошибка обработки {file_path.name}: {exc}")
                )

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(f"Создано SourceDocument: {created_docs}"))
        self.stdout.write(self.style.SUCCESS(f"Переобработано SourceDocument: {updated_docs}"))
        self.stdout.write(self.style.SUCCESS(f"Создано LandPlot: {created_plots}"))
        self.stdout.write(self.style.SUCCESS(f"Обновлено LandPlot: {updated_plots}"))
        self.stdout.write(self.style.SUCCESS(f"bbox получен: {bbox_ok}"))
        if failed:
            self.stdout.write(self.style.ERROR(f"Ошибок: {failed}"))
