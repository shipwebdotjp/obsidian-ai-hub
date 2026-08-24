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
