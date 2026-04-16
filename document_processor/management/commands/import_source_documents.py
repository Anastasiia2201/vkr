from __future__ import annotations

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from document_processor.models import SourceDocument
from document_processor.services.document_processor import process_source_document
from document_processor.services.storage import calculate_file_hash


class Command(BaseCommand):
    help = (
        "Импортирует документы из папки в SourceDocument, "
        "избегает дублей по file_hash и запускает обработку."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "folder",
            type=str,
            help="Путь к папке с документами",
        )
        parser.add_argument(
            "--recursive",
            action="store_true",
            help="Искать файлы рекурсивно по подпапкам",
        )
        parser.add_argument(
            "--extensions",
            nargs="+",
            default=[".pdf"],
            help="Список расширений файлов, например: --extensions .pdf .docx",
        )

    def handle(self, *args, **options):
        folder = Path(options["folder"]).expanduser().resolve()
        recursive = options["recursive"]
        extensions = {ext.lower() for ext in options["extensions"]}

        if not folder.exists() or not folder.is_dir():
            raise CommandError(f"Папка не найдена: {folder}")

        files = self._collect_files(folder, recursive, extensions)

        if not files:
            self.stdout.write(self.style.WARNING("Файлы не найдены."))
            return

        created_count = 0
        skipped_count = 0
        failed_count = 0

        self.stdout.write(f"Найдено файлов: {len(files)}")

        for file_path in files:
            self.stdout.write("-" * 80)
            self.stdout.write(f"Обработка: {file_path.name}")

            try:
                with file_path.open("rb") as fh:
                    django_file = File(fh, name=file_path.name)
                    file_hash = calculate_file_hash(django_file)

                    existing = SourceDocument.objects.filter(file_hash=file_hash).first()
                    if existing:
                        skipped_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Пропуск: дубликат, document_id={existing.id}, "
                                f"filename={existing.original_filename}"
                            )
                        )
                        continue

                with file_path.open("rb") as fh:
                    django_file = File(fh, name=file_path.name)

                    document = SourceDocument.objects.create(
                        file=django_file,
                        original_filename=file_path.name,
                        file_hash=file_hash,
                        document_type=SourceDocument.DocumentType.UNKNOWN,
                        status=SourceDocument.ProcessingStatus.UPLOADED,
                    )

                process_source_document(document.id)
                document.refresh_from_db()

                if document.status == SourceDocument.ProcessingStatus.FAILED:
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"Ошибка обработки: document_id={document.id}, "
                            f"type={document.document_type}, "
                            f"metadata={document.metadata}"
                        )
                    )
                else:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Импортировано: document_id={document.id}, "
                            f"type={document.document_type}, "
                            f"status={document.status}"
                        )
                    )

            except Exception as exc:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(f"Не удалось обработать {file_path.name}: {exc}")
                )

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS(f"Создано: {created_count}"))
        self.stdout.write(self.style.WARNING(f"Пропущено дублей: {skipped_count}"))
        self.stdout.write(self.style.ERROR(f"Ошибок: {failed_count}"))

    def _collect_files(
        self,
        folder: Path,
        recursive: bool,
        extensions: set[str],
    ) -> list[Path]:
        pattern = "**/*" if recursive else "*"
        files = []

        for path in folder.glob(pattern):
            if path.is_file() and path.suffix.lower() in extensions:
                files.append(path)

        return sorted(files)
