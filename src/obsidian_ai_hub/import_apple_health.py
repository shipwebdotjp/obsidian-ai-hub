"""Thin CLI wrapper for Apple Health import — logic lives in healthcare/importer.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from obsidian_ai_hub.healthcare.importer import import_export
from obsidian_ai_hub.utils import config


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if n <= 0:
        raise argparse.ArgumentTypeError(f"--batch-size must be a positive integer, got {value}")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import Apple Health export into healthcare.sqlite3")
    p.add_argument(
        "--export-dir",
        type=str,
        default=str(config.HEALTHCARE_EXPORT_DIR),
        help="Directory containing export.xml (default: %(default)s)",
    )
    p.add_argument(
        "--batch-size",
        type=_positive_int,
        default=5000,
        help="Commit batch size (default: %(default)s)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count without writing to DB",
    )
    return p


def main(argv: list[str] | None = None) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    export_dir = Path(args.export_dir).expanduser()
    result = import_export(
        export_dir,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    # Human-readable summary
    print(f"Import {'(dry-run) ' if args.dry_run else ''}from {export_dir}:")
    for k, v in result.items():
        if k == "import_id":
            continue
        if k.startswith("_"):
            continue
        print(f"  {k}: {v}")
    if "import_id" in result:
        print(f"  import_id: {result['import_id']}")
    return result


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
