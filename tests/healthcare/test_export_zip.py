import stat
import zipfile
from pathlib import Path

import pytest

from obsidian_ai_hub.healthcare import export_zip
from tests.healthcare.helpers import write_mini_export_zip


def _zip_with(base: Path, entries: dict[str, bytes], *, compress: bool = zipfile.ZIP_DEFLATED) -> Path:
    zip_path = base / "archive.zip"
    with zipfile.ZipFile(zip_path, "w", compress) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return zip_path


def test_extract_mini_export_from_nested_prefix(tmp_path: Path):
    zip_path = write_mini_export_zip(tmp_path)
    dest = export_zip.extract_health_export(zip_path, tmp_path / "out")

    assert (dest / "export.xml").is_file()
    ecg_files = list((dest / "electrocardiograms").glob("*.csv"))
    assert len(ecg_files) == 1
    # Nested apple_health_export/ prefix is stripped so file_path stays relative.
    assert ecg_files[0].parent.name == "electrocardiograms"


def test_extract_accepts_root_level_export_xml(tmp_path: Path):
    zip_path = _zip_with(
        tmp_path,
        {"export.xml": b"<HealthData></HealthData>"},
    )
    dest = export_zip.extract_health_export(zip_path, tmp_path / "out")
    assert (dest / "export.xml").read_bytes() == b"<HealthData></HealthData>"


def test_extract_ignores_cda_and_macosx(tmp_path: Path):
    zip_path = _zip_with(
        tmp_path,
        {
            "apple_health_export/export.xml": b"<HealthData/>",
            "apple_health_export/export_cda.xml": b"<ClinicalDocument/>",
            "__MACOSX/apple_health_export/._export.xml": b"junk",
        },
    )
    dest = export_zip.extract_health_export(zip_path, tmp_path / "out")
    assert (dest / "export.xml").is_file()
    assert not (dest / "export_cda.xml").exists()
    assert not (tmp_path / "out" / "__MACOSX").exists()


def test_missing_export_xml_is_rejected(tmp_path: Path):
    zip_path = _zip_with(tmp_path, {"apple_health_export/other.txt": b"x"})
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out")


def test_not_a_zip_is_rejected(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(bad, tmp_path / "out")


def test_zip_slip_is_rejected(tmp_path: Path):
    zip_path = _zip_with(
        tmp_path,
        {
            "apple_health_export/export.xml": b"<HealthData/>",
            "apple_health_export/../../evil.xml": b"<evil/>",
        },
    )
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out")


def test_absolute_path_is_rejected(tmp_path: Path):
    zip_path = _zip_with(
        tmp_path,
        {
            "apple_health_export/export.xml": b"<HealthData/>",
            "/tmp/evil.xml": b"<evil/>",
        },
    )
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out")


def test_symlink_entry_is_rejected(tmp_path: Path):
    zip_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("apple_health_export/export.xml", b"<HealthData/>")
        info = zipfile.ZipInfo("apple_health_export/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "target")
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out")


def test_entry_count_cap(tmp_path: Path):
    zip_path = write_mini_export_zip(tmp_path)
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out", max_entries=1)


def test_uncompressed_size_cap(tmp_path: Path):
    zip_path = write_mini_export_zip(tmp_path)
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out", max_uncompressed_bytes=8)


def test_compression_ratio_cap(tmp_path: Path):
    zip_path = _zip_with(
        tmp_path,
        {"apple_health_export/export.xml": b"a" * 100000},
    )
    with pytest.raises(export_zip.ExportZipError):
        export_zip.extract_health_export(zip_path, tmp_path / "out", max_compression_ratio=2)
