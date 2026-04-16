from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from document_processor.services.text_extractor import extract_text_from_document


class Command(BaseCommand):
    help = "Быстрая проверка извлечения текста и OCR для PDF-файлов"

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            type=str,
            help="Путь к PDF-файлу или папке с PDF-файлами"
        )
        parser.add_argument(
            "--save-txt",
            action="store_true",
            help="Сохранять извлечённый текст рядом с PDF в .txt"
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Показывать весь извлечённый текст"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=3000,
            help="Сколько символов текста показывать в консоли"
        )

    def handle(self, *args, **options):
        input_path = Path(options["path"])

        if not input_path.exists():
            raise CommandError(f"Путь не найден: {input_path}")

        if input_path.is_file():
            if input_path.suffix.lower() != ".pdf":
                raise CommandError("Нужно передать PDF-файл или папку с PDF-файлами")
            files = [input_path]
        else:
            files = sorted(input_path.glob("*.pdf"))

        if not files:
            self.stdout.write(self.style.WARNING("PDF-файлы не найдены"))
            return

        self.stdout.write(self.style.SUCCESS(f"Найдено файлов: {len(files)}"))

        for file_path in files:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.MIGRATE_HEADING(f"Файл: {file_path.name}"))
            self.stdout.write(f"Путь: {file_path}")

            try:
                text, ocr_used = extract_text_from_document(str(file_path))

                self.stdout.write(f"OCR использован: {ocr_used}")
                self.stdout.write(f"Длина текста: {len(text)} символов")

                if options["save_txt"]:
                    txt_path = file_path.with_suffix(".txt")
                    txt_path.write_text(text, encoding="utf-8")
                    self.stdout.write(
                        self.style.SUCCESS(f"TXT сохранён: {txt_path.name}")
                    )

                self.stdout.write("-" * 80)
                self.stdout.write("ИЗВЛЕЧЁННЫЙ ТЕКСТ:")
                self.stdout.write("-" * 80)

                if options["full"]:
                    preview = text
                else:
                    preview = text[:options["limit"]]

                if preview.strip():
                    self.stdout.write(preview)
                    if not options["full"] and len(text) > options["limit"]:
                        self.stdout.write("\n... [текст обрезан]")
                else:
                    self.stdout.write(self.style.WARNING("Текст не извлечён"))

            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Ошибка: {exc}"))
