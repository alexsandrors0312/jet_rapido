"""Limites adicionais para evitar XLSX excessivamente expandido."""

from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .importer import ImportValidationError


def validate_xlsx_archive(path: Path, *, max_entries: int, max_uncompressed_bytes: int) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise ImportValidationError("O XLSX contém arquivos internos demais.")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ImportValidationError("O XLSX contém membros internos duplicados.")
            total = 0
            for entry in entries:
                member = PurePosixPath(entry.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ImportValidationError("O XLSX contém um caminho interno inválido.")
                total += entry.file_size
                if total > max_uncompressed_bytes:
                    raise ImportValidationError("O conteúdo descompactado do XLSX excede o limite.")
            required = {"[Content_Types].xml", "xl/workbook.xml"}
            if not required.issubset(set(names)):
                raise ImportValidationError("O arquivo não contém uma estrutura XLSX válida.")
    except BadZipFile as error:
        raise ImportValidationError("O arquivo não é um XLSX válido.") from error
