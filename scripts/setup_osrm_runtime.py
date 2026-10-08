"""Extract the private OSRM/osmium wheels into a writable runtime directory.

The wheels stay under ``data/osrm-tools`` (ignored by Git). The already installed
``data/osrm-tools/runtime`` may be locked by filesystem ACLs, so this script
builds an equivalent runtime from the same wheels without touching it. The
runtime holds ``bin/osrm-extract.exe``, ``bin/osrm-contract.exe``,
``share/osrm/profiles/*.lua`` (including ``car.lua``) and the DLL folders used by
``scripts/prepare_osrm_windows.py``.
"""

import argparse
from pathlib import Path
import zipfile


DEFAULT_WHEELS = (
    "data/osrm-tools/osrm_bindings-0.3.0-cp312-abi3-win_amd64.whl",
    "data/osrm-tools/osmium-4.3.1-cp312-cp312-win_amd64.whl",
)
REQUIRED = (
    "bin/osrm-extract.exe",
    "bin/osrm-contract.exe",
    "bin/osrm-routed.exe",
    "share/osrm/profiles/car.lua",
    "share/osrm/profiles/foot.lua",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/osrm-tools/wheel-runtime"))
    parser.add_argument("--wheel", type=Path, action="append", default=None,
                        help="Repita para informar os wheels; o padrão usa os de data/osrm-tools.")
    parser.add_argument("--force", action="store_true",
                        help="Reextrai sobre uma pasta existente.")
    args = parser.parse_args()
    wheels = args.wheel or [Path(path) for path in DEFAULT_WHEELS]
    for wheel in wheels:
        if not wheel.is_file():
            parser.error(f"Wheel não encontrado: {wheel}")
    if args.output.exists() and not args.force:
        missing = [name for name in REQUIRED if not (args.output / name).is_file()]
        if not missing:
            print(f"Runtime já preparado em {args.output}. Use --force para reextrair.")
            return
        parser.error("A pasta de saída existe e está incompleta; use --force.")
    args.output.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(args.output)
        print(f"Extraído: {wheel.name}", flush=True)
    missing = [name for name in REQUIRED if not (args.output / name).is_file()]
    if missing:
        raise RuntimeError(f"Runtime incompleto, faltam: {', '.join(missing)}")
    print(f"Runtime OSRM preparado em {args.output}.", flush=True)
    print("Use com --runtime em scripts/prepare_osrm_windows.py.", flush=True)


if __name__ == "__main__":
    main()
