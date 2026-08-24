"""Helpers to build synthetic Apple Health export fixtures for tests.

Fixtures are tiny and fully synthetic (no real PII). They live in
tests/healthcare/fixtures/ for golden-file reference, but most tests
should generate isolated copies under tmp_path via these helpers to
avoid cross-test pollution — following tests/test_migrate_*.py pattern.

Usage:
    helpers = _load_helpers()  # see test_fixtures_smoke.py
    export_dir = helpers.write_mini_export(tmp_path)
    # -> tmp_path/export/export.xml + tmp_path/export/electrocardiograms/ecg_2026-08-20.csv
    from obsidian_ai_hub.healthcare.importer import import_export
    result = import_export(export_dir)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

MINI_EXPORT_XML = (_FIXTURE_DIR / "export_mini.xml").read_text(encoding="utf-8")
MINI_ECG_CSV = (_FIXTURE_DIR / "ecg_mini.csv").read_text(encoding="utf-8")

ECG_SUBDIR = "electrocardiograms"
ECG_FILENAME = "ecg_2026-08-20.csv"
ECG_RECORDED_AT = "2026-08-20 08:22:18 +0900"


def write_mini_export(
    base: Path,
    *,
    subdir: str = "export",
    include_ecg: bool = True,
    extra_records_xml: str = "",
) -> Path:
    """Create a synthetic export directory under base and return its Path.

    Structure:
        <base>/<subdir>/
            export.xml
            electrocardiograms/ecg_2026-08-20.csv  (if include_ecg)

    extra_records_xml is inserted before </HealthData> for per-test variations
    (e.g. duplicate fingerprint, malformed record).
    """
    export_dir = base / subdir
    export_dir.mkdir(parents=True, exist_ok=True)

    xml = MINI_EXPORT_XML
    if extra_records_xml:
        if xml.count("</HealthData>") != 1:
            raise ValueError("fixture export_mini.xml must contain exactly one </HealthData>")
        xml = xml.replace("</HealthData>", f"{extra_records_xml}\n</HealthData>")

    (export_dir / "export.xml").write_text(xml, encoding="utf-8")

    if include_ecg:
        ecg_dir = export_dir / ECG_SUBDIR
        ecg_dir.mkdir(parents=True, exist_ok=True)
        (ecg_dir / ECG_FILENAME).write_text(MINI_ECG_CSV, encoding="utf-8")

    return export_dir


def write_ecg_csv(
    dest: Path,
    *,
    recorded_at: str = "2026-08-20 08:22:18 +0900",
    classification: str = "洞調律",
    sample_rate_hz: int = 512,
    samples: list[float] | None = None,
) -> Path:
    """Write a synthetic ECG CSV to dest and return dest."""
    if samples is None:
        samples = [1.3, -0.9, -3.2, -5.5]
    header = textwrap.dedent(f"""\
        名前,テスト太郎
        生年月日,"1990/01/01"
        記録日,{recorded_at}
        分類,{classification}
        症状,
        ソフトウェアバージョン,1.90
        デバイス,"Watch6,1"
        サンプルレート,{sample_rate_hz}ヘルツ


        リード,リードI
        単位,µV

        """)
    body = "\n".join(str(v) for v in samples) + "\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + body, encoding="utf-8")
    return dest



