"""Configuração explícita e injetável da aplicação."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///data/jet_rapido.db"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_xlsx_uncompressed_bytes: int = 50 * 1024 * 1024
    max_xlsx_entries: int = 1_000

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL não pode ser vazia.")
        for name in ("max_upload_bytes", "max_xlsx_uncompressed_bytes", "max_xlsx_entries"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} deve ser positivo.")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", cls.max_upload_bytes)),
            max_xlsx_uncompressed_bytes=int(
                os.getenv("MAX_XLSX_UNCOMPRESSED_BYTES", cls.max_xlsx_uncompressed_bytes)
            ),
            max_xlsx_entries=int(os.getenv("MAX_XLSX_ENTRIES", cls.max_xlsx_entries)),
        )
