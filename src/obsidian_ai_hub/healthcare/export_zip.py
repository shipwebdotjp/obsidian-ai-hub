"""Safe extraction of an Apple Health export ``.zip`` archive.

Only the entries the importer actually consumes are extracted:

- ``export.xml`` (the streaming XML source)
- ``electrocardiograms/*.csv`` (file-referenced ECG waveforms)

Everything else — notably ``export_cda.xml``, which the importer deliberately
skips — is ignored. This bounds disk usage and zip-bomb exposure.

Security posture:

- No ``extractall``; each wanted entry is streamed to a resolved target whose
  path is verified to stay inside the destination directory (zip slip).
- Absolute paths, drive letters, ``..`` components, backslashes, NUL bytes,
  encrypted entries, and symlinks are rejected before any write.
- Entry count, total declared uncompressed size, and per-entry compression
  ratio are validated from the central directory *before* decompression.
- Unexpected failures propagate; nothing is masked.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

DEFAULT_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024  # 20 GiB
DEFAULT_MAX_ZIP_ENTRIES = 200_000
DEFAULT_MAX_COMPRESSION_RATIO = 1000
_ECG_DIR = "electrocardiograms"
_EXPORT_XML = "export.xml"
_MACOSX_PREFIX = "__MACOSX/"


class ExportZipError(ValueError):
    """Raised when an archive is not a usable Apple Health export."""


def _is_unsafe_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    if "\\" in name:
        return True
    # Reject absolute posix paths and Windows drive-letter paths.
    if name.startswith("/"):
        return True
    if len(name) >= 2 and name[1] == ":":
        return True
    parts = name.split("/")
    return any(part == ".." for part in parts)


def _export_root_prefix(zf: zipfile.ZipFile) -> str:
    """Return the directory prefix (with trailing slash) holding ``export.xml``."""
    prefixes: set[str] = set()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith(_MACOSX_PREFIX):
            continue
        if name.split("/")[-1] != _EXPORT_XML:
            continue
        prefixes.add(name[: -len(_EXPORT_XML)])
    if not prefixes:
        raise ExportZipError("export.xml が zip 内に見つかりません")
    if len(prefixes) > 1:
        raise ExportZipError(
            "export.xml が複数箇所に存在し、どれを取り込むか一意に決められません"
        )
    return prefixes.pop()


def _is_wanted(name: str, root_prefix: str) -> bool:
    if not name.startswith(root_prefix):
        return False
    rel = name[len(root_prefix) :]
    if rel == _EXPORT_XML:
        return True
    return rel.startswith(f"{_ECG_DIR}/") and rel.endswith(".csv")


def _validate_archive(
    zf: zipfile.ZipFile,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: int,
) -> None:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ExportZipError(
            f"zip のエントリ数が上限を超えています ({len(infos)} > {max_entries})"
        )
    total = 0
    for info in infos:
        total += info.file_size
        if total > max_uncompressed_bytes:
            raise ExportZipError("zip の展開後サイズが上限を超えています")
        if info.flag_bits & 0x1:
            raise ExportZipError("暗号化された zip は取り込めません")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ExportZipError("zip にシンボリックリンクが含まれています")
        if info.compress_size > 0 and max_compression_ratio > 0:
            ratio = info.file_size / info.compress_size
            if ratio > max_compression_ratio:
                raise ExportZipError("zip の圧縮率が異常に高く、安全に展開できません")
        if _is_unsafe_name(info.filename):
            raise ExportZipError(f"zip に安全でないパスが含まれています: {info.filename!r}")


def _safe_target(dest_dir: Path, relative: str) -> Path:
    target = (dest_dir / relative).resolve()
    if not target.is_relative_to(dest_dir.resolve()):
        raise ExportZipError(f"zip のパスが展開先を越えています: {relative!r}")
    return target


def extract_health_export(
    zip_path: Path | str,
    dest_dir: Path | str,
    *,
    max_entries: int = DEFAULT_MAX_ZIP_ENTRIES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> Path:
    """Extract the entries needed for import into ``dest_dir``.

    Returns ``dest_dir`` (containing ``export.xml`` and optionally
    ``electrocardiograms/``). Raises :class:`ExportZipError` for archives that
    cannot be safely or unambiguously imported. No partial DB writes happen
    here; this function only writes files under ``dest_dir``.
    """
    zip_path = Path(zip_path).expanduser()
    dest_dir = Path(dest_dir).expanduser()
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip が見つかりません: {zip_path}")

    if not zipfile.is_zipfile(zip_path):
        raise ExportZipError("有効な zip ファイルではありません")

    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        _validate_archive(
            zf,
            max_entries=max_entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
        )
        root_prefix = _export_root_prefix(zf)
        wanted = [i for i in zf.infolist() if not i.is_dir() and _is_wanted(i.filename, root_prefix)]
        if not wanted:
            raise ExportZipError("zip に取り込み対象のファイルがありません")
        extracted_total = 0
        for info in wanted:
            relative = info.filename[len(root_prefix) :]
            if _is_unsafe_name(relative):
                raise ExportZipError(f"zip に安全でないパスが含まれています: {info.filename!r}")
            target = _safe_target(dest_dir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Cap the *actual* decompressed bytes: central-directory file_size
            # can be spoofed (understated), so the pre-check is not sufficient.
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    extracted_total += len(chunk)
                    if extracted_total > max_uncompressed_bytes:
                        raise ExportZipError("zip の展開後サイズが上限を超えています")
                    dst.write(chunk)
    return dest_dir
