import json
import logging
import os
import tempfile
from pathlib import Path

from obsidian_ai_hub.handler import obsidian_vault_retriever
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


# --- Vault Search services ---

# NOTE: serialization is provided by the dedicated single-worker executor in
# obsidian_vault_retriever (required by md-hybrid-search's single-thread
# SQLite connection), so no lock is needed here.


def search_vault(q: str, k: int = 10, mode: str = "hybrid") -> dict:
    result_json = obsidian_vault_retriever.search_obsidian_vault.func(
        query=q, k=k, search_mode=mode
    )
    try:
        results = json.loads(result_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse vault search JSON output: %s", e)
        raise ValueError("vault search returned invalid JSON") from e
    if isinstance(results, dict) and "error" in results:
        raise ValueError(results["error"])

    vault_name = Path(config.VAULT_PATH).name
    for hit in results:
        if not isinstance(hit.get("metadata"), dict):
            hit["metadata"] = {}
        hit["metadata"]["vault_name"] = vault_name
    return {"items": results, "total": len(results)}


def _resolve_vault_file_path(relative_path: str) -> Path:
    """Validate *relative_path* and return the resolved file path in the Vault.

    Shares the single path-safety rule used by both the reader and the
    context-reference validation: no absolute paths, no ``..`` components,
    ``.md`` only, resolved target must stay inside ``VAULT_PATH`` and be a
    regular file. Raises ``ValueError`` / ``FileNotFoundError``
    with the same messages as :func:`get_vault_file`.
    """
    vault_dir = Path(config.VAULT_PATH).resolve()

    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")

    if p.suffix.lower() != ".md":
        raise ValueError("Only Markdown (.md) files are allowed")

    # Resolve resolved path (to handle symlinks properly)
    try:
        resolved_path = (vault_dir / p).resolve(strict=True)
    except FileNotFoundError:
        # Check traversal on non-existing path
        resolved_path = (vault_dir / p).resolve(strict=False)
        try:
            resolved_path.relative_to(vault_dir)
        except ValueError:
            raise ValueError("Path is outside the Vault")
        raise FileNotFoundError("File not found")

    # Verify containment for existing file
    try:
        resolved_path.relative_to(vault_dir)
    except ValueError:
        raise ValueError("Path is outside the Vault")

    if not resolved_path.is_file():
        raise FileNotFoundError("File is not a file")
    return resolved_path


def get_vault_file(relative_path: str) -> dict:
    resolved_path = _resolve_vault_file_path(relative_path)

    with open(resolved_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "content": content,
        "relative_path": relative_path,
    }


def validate_vault_file_ref(relative_path: str) -> str:
    """Validate an agent context-reference path without reading its body.

    Returns the normalized vault-relative POSIX path. Raises ``ValueError``
    for unsafe/non-Markdown paths and ``FileNotFoundError`` for missing
    targets, mirroring :func:`get_vault_file` semantics.
    """
    vault_dir = Path(config.VAULT_PATH).resolve()
    resolved = _resolve_vault_file_path(relative_path)
    return resolved.relative_to(vault_dir).as_posix()


# --- Vault file listing service (agent @-reference picker) ---
# Hidden/system directories never shown in the Vault file picker.
_HIDDEN_DIR_PREFIXES = (".",)


def _is_listable_markdown(candidate: Path, vault_dir: Path) -> bool:
    """Return True when *candidate* is a listable ``.md`` file in the Vault."""
    try:
        rel = candidate.relative_to(vault_dir)
    except ValueError:
        return False
    # ``rglob`` follows symlinked directories on Python < 3.13, so the
    # resolved parent (not just the leaf) must stay inside the Vault.
    try:
        if not candidate.parent.resolve().is_relative_to(vault_dir):
            return False
    except (OSError, RuntimeError):
        return False
    if any(part.startswith(_HIDDEN_DIR_PREFIXES) for part in rel.parts[:-1]):
        return False
    if candidate.name.startswith("."):
        return False
    if candidate.suffix.lower() != ".md":
        return False
    if candidate.is_symlink():
        # Resolve the link and require the real target to stay in the Vault.
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        try:
            resolved.relative_to(vault_dir)
        except ValueError:
            return False
        return resolved.is_file()
    return candidate.is_file()


def list_vault_files() -> dict:
    """List all ``.md`` files in the Vault for the agent context picker.

    Returns ``{"items": [{"relative_path", "size", "mtime"}], "total"}``
    with vault-relative POSIX paths sorted ascending. Hidden directories
    (``.obsidian``, ``.trash``, ``.git``, …) and symlink escapes are
    excluded. Only paths are returned; note bodies are read on demand.
    """
    vault_dir = _resolve_vault_dir()
    if not vault_dir.is_dir():
        raise FileNotFoundError("Vault directory not found")
    items: list[dict] = []
    for candidate in sorted(vault_dir.rglob("*.md")):
        if not _is_listable_markdown(candidate, vault_dir):
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        items.append(
            {
                "relative_path": candidate.relative_to(vault_dir).as_posix(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return {"items": items, "total": len(items)}


# --- Vault file write service ---
#
# Operation-scenario contract (see docs/development-quality-playbook.md):
#
# | 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
# | --- | --- | --- | --- | --- | --- | --- |
# | 入力検証 | `VaultWriteFileInput` (args_schema単一正本: relative_path/content/overwrite) | `relative_path` (Vault相対・正規化POSIX) | なし (検証失敗は書込まない) | 本サービス | 不正・Vault外・型不一致は例外で停止 | なし |
# | 上書き判定 | 既存有無 (`lexists` + 解決先存在) と `overwrite` | `overwritten: bool` | overwrite偽時は空ファイルの原子クレーム (`O_CREAT\|O_EXCL\|O_NOFOLLOW`) | 本サービス | 既存あり・overwrite偽は `FileExistsError` で停止 | なし (クレーム自体は空ファイル作成) |
# | 実行 | 検証済み正規化パス + UTF-8バイト列 | `relative_path` / `bytes_written` | Vault内ファイル (一時ファイル+`os.replace`で原子置換) | Vault購読者・次回vault index | I/O失敗は `OSError` で停止 (部分書込みを残さない) | Vaultファイルの新規作成・上書き |
# | 再実行 | 同一入力の再実行 | `relative_path` | 同一ファイル | 呼出し者 | overwrite偽なら2回目は競合停止、真なら冪等な置換 (at-least-once) | 同左 (自動ロールバックなし) |
#
# 正本と識別子の分離: 表示用ラベルを使わず、Vault相対パスの正規化文字列だけを
# 識別子にする。`overwrite` の既定は `False` であり、上書きには明示的な
# `overwrite=true` を要する (既存の書込み規約は存在しないため)。
#
# 保証範囲: `os.replace` は置換先シンボリックリンクを辿らないため、既存リンク
# 自体が置換されリンク先は変更されない。`overwrite=false` の競合判定は原子
# クレームでTOCTOUを閉じる (クラッシュ時は空ファイルが残り、再実行は競合停止
# する安全側)。検証〜`mkdir` 間の祖先シンボリックリンク差替えは、単一ユーザの
# ローカル利用を前提に best-effort (検証前後で containment を再確認) とし、
# 能動的なローカル攻撃者への完全防止は保証しない。


def _resolve_vault_dir() -> Path:
    # NOTE: module-level ``config`` import (not a function-local one) keeps
    # this service on the same config object the test sandbox patches, even
    # when another test module replaces sys.modules["...utils.config"].
    raw = getattr(config, "VAULT_PATH", None)
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        raise ValueError("Vault path is not configured (VAULT_PATH is empty)")
    return Path(raw).expanduser().resolve(strict=False)


def _resolve_contained_target(vault_dir: Path, relative_path: str) -> tuple[Path, Path]:
    """Validate *relative_path* and return ``(candidate, resolved)``.

    ``candidate`` is the lexical Vault-joined path, ``resolved`` is the
    symlink-resolved absolute target. Both are guaranteed to stay inside
    ``vault_dir``; otherwise ``ValueError`` is raised and nothing is written.
    """
    if not isinstance(relative_path, str) or relative_path.strip() == "":
        raise ValueError("relative_path must be a non-empty string")
    if "\x00" in relative_path:
        raise ValueError("relative_path must not contain NUL bytes")
    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")
    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")
    candidate = vault_dir / p
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Unable to resolve path inside the Vault: {exc}") from exc
    try:
        resolved.relative_to(vault_dir)
    except ValueError:
        raise ValueError("Path is outside the Vault") from None
    if resolved == vault_dir:
        raise ValueError(
            "Path must point to a file inside the Vault, not the Vault root"
        )
    return candidate, resolved


def write_vault_file(relative_path: str, content: str, overwrite: bool = False) -> dict:
    """Write UTF-8 text to a Vault-relative file atomically.

    Creates missing parent directories inside the Vault. Existing files are
    only replaced when ``overwrite`` is explicitly ``True``; otherwise a
    ``FileExistsError`` is raised and the existing file is left untouched.
    """
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    if not isinstance(overwrite, bool):
        raise TypeError("overwrite must be a boolean")
    vault_dir = _resolve_vault_dir()
    try:
        vault_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Unable to prepare Vault directory: {exc}") from exc
    # Re-resolve after ensuring the root (best-effort against symlink swaps).
    candidate, resolved = _resolve_contained_target(vault_dir, relative_path)

    already_exists = os.path.lexists(candidate) or resolved.exists()
    if already_exists and resolved.is_dir():
        raise IsADirectoryError(f"Path is a directory, not a file: {relative_path}")
    if already_exists and not overwrite:
        raise FileExistsError(
            f"File already exists (set overwrite=true to overwrite): {relative_path}"
        )

    parent = candidate.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Unable to create parent directories: {exc}") from exc
    # Final containment check after creating parents (never write outside).
    candidate, resolved = _resolve_contained_target(vault_dir, relative_path)

    if not overwrite:
        # Atomically claim the path (O_CREAT|O_EXCL) so a concurrent creator
        # between the existence check above and the os.replace below cannot
        # be silently overwritten (TOCTOU close). O_NOFOLLOW refuses a
        # symlink swapped in for the final component. The claim is our own
        # empty regular file, which the atomic replace then fills.
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            )
        except FileExistsError:
            raise FileExistsError(
                f"File already exists (set overwrite=true to overwrite): {relative_path}"
            ) from None
        except OSError as exc:
            raise OSError(f"Failed to write Vault file: {exc}") from exc
        os.close(fd)

    data = content.encode("utf-8")
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(parent),
            prefix=".oaihub-tmp-",
            suffix=".part",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, candidate)
        tmp_path = None
    except OSError as exc:
        raise OSError(f"Failed to write Vault file: {exc}") from exc
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    normalized = Path(relative_path).as_posix()
    return {
        "relative_path": normalized,
        "bytes_written": len(data),
        "overwritten": bool(already_exists),
    }
