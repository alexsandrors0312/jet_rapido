"""Interface local; relatório detalhado somente com saída explícita."""
import argparse
import json
from pathlib import Path
from zipfile import BadZipFile

from .importer import ImportValidationError, import_workbook


def main() -> int:
    parser = argparse.ArgumentParser(description="Analisa a exportação SPX sem modificar o Excel.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--output", type=Path, help="JSON com endereços e pacotes; manter fora do Git")
    args = parser.parse_args()
    try:
        result = import_workbook(args.file, args.sheet)
        if args.output:
            if args.output.suffix.lower() != ".json":
                raise ImportValidationError("A saída deve ter extensão .json.")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Não substitui um resultado existente silenciosamente.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        print(f"Avisos para revisão: {len(result['warnings'])}")
        return 0
    except (ImportValidationError, OSError, BadZipFile) as error:
        parser.exit(2, f"Importação não concluída: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
