import importlib.util
from pathlib import Path


def _load_helpers():
    helpers_path = Path(__file__).parent / "helpers.py"
    spec = importlib.util.spec_from_file_location("healthcare_helpers", helpers_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_mini_fixtures_exist():
    fixtures = Path(__file__).parent / "fixtures"
    assert (fixtures / "export_mini.xml").exists()
    assert (fixtures / "ecg_mini.csv").exists()
    xml = (fixtures / "export_mini.xml").read_text(encoding="utf-8")
    assert "<HealthData" in xml
    assert "HKQuantityTypeIdentifierHeartRate" in xml
    assert "HKCategoryTypeIdentifierSleepAnalysis" in xml
    assert "HKWorkoutActivityTypeCycling" in xml
    assert "ActivitySummary" in xml
    assert "HeartRateVariabilityMetadataList" in xml
    ecg_csv = (fixtures / "ecg_mini.csv").read_text(encoding="utf-8")
    assert "リードI" in ecg_csv
    assert "µV" in ecg_csv


def test_helpers_generate_isolated_export(tmp_path: Path):
    helpers = _load_helpers()

    export_dir = helpers.write_mini_export(tmp_path)
    assert (export_dir / "export.xml").exists()
    assert (export_dir / "electrocardiograms" / "ecg_2026-08-20.csv").exists()

    extra_record = (
        '<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Extra"'
        ' unit="count" creationDate="2026-08-20 12:00:00 +0900"'
        ' startDate="2026-08-20 12:00:00 +0900" endDate="2026-08-20 12:01:00 +0900" value="10"/>'
    )
    export_dir2 = helpers.write_mini_export(
        tmp_path / "second", extra_records_xml=extra_record
    )
    assert "Extra" in (export_dir2 / "export.xml").read_text(encoding="utf-8")
    # First copy must remain untouched (isolation guarantee)
    assert "Extra" not in (export_dir / "export.xml").read_text(encoding="utf-8")


def test_helpers_write_ecg_csv(tmp_path: Path):
    helpers = _load_helpers()

    dest = tmp_path / "ecg.csv"
    helpers.write_ecg_csv(dest, samples=[1.0, 2.0, 3.0])
    txt = dest.read_text(encoding="utf-8")
    assert "リードI" in txt
    non_empty = [line for line in txt.splitlines() if line.strip()]
    assert non_empty[-3:] == ["1.0", "2.0", "3.0"]


def test_write_mini_export_rejects_malformed_base_fixture(tmp_path: Path, monkeypatch):
    import pytest

    helpers = _load_helpers()
    # Patch the cached fixture content to a malformed version without </HealthData>
    monkeypatch.setattr(helpers, "_mini_export_xml", lambda: "<HealthData><Record/></HealthData")
    # The helper's internal check looks for exactly one </HealthData>; with 0 or 2 it would raise,
    # but our monkeypatched content has 1 — so we test the branch that would raise by
    # temporarily making the base fixture miss the anchor
    # To trigger the ValueError, patch the cached content to have no closing tag
    monkeypatch.setattr(helpers, "_mini_export_xml", lambda: "<HealthData></HealthData><HealthData></HealthData>")
    import pytest as _pytest

    # Actually test the helper's guard by calling with extra_records that would trigger the count check
    # The current implementation checks xml.count("</HealthData>") != 1
    # So a base with 2 occurrences should raise
    try:
        helpers.write_mini_export(tmp_path, extra_records_xml="<Record/>")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "exactly one" in str(exc)
