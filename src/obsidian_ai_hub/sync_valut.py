"""Sync the Obsidian vaults into md-hybrid-search (per-Vault indexes)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from md_hybrid_search import ConfigMismatchError, DirectorySource, SearchIndex

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings

logger = logging.getLogger(__name__)

MODEL_CACHE_ENV_VARS = (
    "HF_HOME",
    "HF_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
)
MODEL_CACHE_SUBDIR = "sentence-transformers"


def _prepare_model_cache_dir() -> Path | None:
    """Resolve and prepare the cache directory used for model downloads."""
    base_dir = config.LOCAL_MODEL_DIR
    if not base_dir:
        return None

    cache_dir = (base_dir / MODEL_CACHE_SUBDIR).expanduser()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to prepare model cache directory: {cache_dir}"
        ) from exc

    for env_name in MODEL_CACHE_ENV_VARS:
        os.environ[env_name] = str(cache_dir)

    return cache_dir


def _prepare_storage_paths(vault_id: str) -> tuple[Path, Path]:
    """Ensure per-Vault SQLite and Chroma storage directories exist."""
    sqlite_path, chroma_path = config.vault_index_paths(vault_id)
    sqlite_path = sqlite_path.expanduser()
    chroma_path = chroma_path.expanduser()

    try:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        chroma_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to prepare vault index storage directories: {sqlite_path.parent} and {chroma_path}"
        ) from exc

    return sqlite_path, chroma_path


def _read_identity(vault_id: str) -> dict | None:
    identity_path = config.vault_index_identity_path(vault_id)
    try:
        if not identity_path.exists():
            return None
        return json.loads(identity_path.read_text(encoding="utf-8"))
    except OSError as exc:
        # An unreadable sidecar also disables verification: fail closed and
        # require an explicit rebuild rather than serving a possibly stale
        # index. (A missing file on first run returns None above.)
        logger.warning("cannot read vault identity for '%s': %s", vault_id, exc)
        raise config.VaultIndexStaleError(
            f"Vault '{vault_id}' index identity is unreadable; "
            f"run --rebuild-vault --vault {vault_id} before searching"
        ) from exc
    except ValueError as exc:
        # Corrupt sidecar must not silently disable the stale-path guard:
        # fail closed and require an explicit rebuild.
        logger.warning(
            "corrupt vault identity for '%s': %s; requiring rebuild", vault_id, exc
        )
        raise config.VaultIndexStaleError(
            f"Vault '{vault_id}' index identity is corrupt; "
            f"run --rebuild-vault --vault {vault_id} before searching"
        ) from exc


def _write_identity(vault_id: str, vault_path: Path) -> None:
    identity_path = config.vault_index_identity_path(vault_id)
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vault_id": vault_id,
        "path": str(vault_path),
        "collection_name": config.VAULT_INDEX_COLLECTION_NAME,
        "embedder_model": config.VAULT_INDEX_EMBEDDER_MODEL,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(identity_path.parent),
            prefix=".identity-tmp-",
            suffix=".part",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, identity_path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def check_vault_index_identity(vault_id: str) -> None:
    """Raise VaultIndexStaleError when the stored index was built for another path.

    A path change invalidates the existing index: search must not use it
    until ``--rebuild-vault --vault <id>`` succeeds.
    """
    descriptor = config.resolve_vault_descriptor(vault_id)
    stored = _read_identity(descriptor.vault_id)
    if stored is None:
        return
    stored_path = stored.get("path")
    if stored_path is not None and Path(str(stored_path)) != descriptor.path:
        raise config.VaultIndexStaleError(
            f"Vault '{descriptor.vault_id}' path changed "
            f"({stored_path} -> {descriptor.path}); "
            f"run --rebuild-vault --vault {descriptor.vault_id} before searching"
        )


def build_vault_search_index(
    vault_id: str | None = None, *, check_identity: bool = True
) -> SearchIndex:
    """Create a SearchIndex configured for one Vault.

    ``None`` resolves to the primary Vault (legacy single-vault callers).
    Rebuild passes ``check_identity=False``: it re-creates the index, so a
    stale path identity must not block construction (the fresh identity is
    recorded after a successful rebuild).
    """
    descriptor = config.resolve_vault_descriptor(vault_id)
    if check_identity:
        check_vault_index_identity(descriptor.vault_id)
    cache_dir = _prepare_model_cache_dir()
    sqlite_path, chroma_path = _prepare_storage_paths(descriptor.vault_id)

    embedder = SimpleSbertEmbeddings(
        model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
        cache_dir=cache_dir,
        allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK,
    )

    return SearchIndex(
        collection_name=config.VAULT_INDEX_COLLECTION_NAME,
        sources=[DirectorySource(str(descriptor.path))],
        sqlite_path=str(sqlite_path),
        chroma_path=str(chroma_path),
        embedder=embedder,
    )


def sync_one_vault(vault_id: str):
    """Sync a single Vault index and record its identity on success."""
    descriptor = config.resolve_vault_descriptor(vault_id)
    index = build_vault_search_index(descriptor.vault_id)
    report = index.sync()
    _write_identity(descriptor.vault_id, descriptor.path)
    return report


def sync_vaults(vault_ids: list[str] | None = None) -> dict[str, object]:
    """Sync all (ID order) or selected Vaults, attempting the rest after failure.

    Returns ``{"succeeded": [...], "failed": {id: error}}``. Raises
    ``SystemExit(1)`` when any Vault fails, after attempting the rest.
    Unknown Vault IDs also fail closed with ``SystemExit(1)``.
    """
    try:
        targets = config.resolve_vault_ids(vault_ids)
    except (KeyError, ValueError, RuntimeError) as exc:
        logger.error("Vault index sync failed: %s", exc)
        raise SystemExit(1) from exc
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for vid in targets:
        try:
            report = sync_one_vault(vid)
            succeeded.append(vid)
            logger.info(
                "Vault index sync completed for '%s': scanned=%s new=%s updated=%s unchanged=%s deleted=%s inserted_chunks=%s deleted_chunks=%s",
                vid,
                report.scanned_files,
                report.new_files,
                report.updated_files,
                report.unchanged_files,
                report.deleted_files,
                report.inserted_chunks,
                report.deleted_chunks,
            )
        except (ConfigMismatchError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            logger.error("Vault index sync failed for '%s': %s", vid, exc)
            failed[vid] = str(exc)
    if failed:
        raise SystemExit(1)
    return {"succeeded": succeeded, "failed": failed}


def main(vault_ids: list[str] | None = None):
    """Synchronize Vault(s) into the md-hybrid-search index."""
    try:
        result = sync_vaults(vault_ids)
    except SystemExit:
        raise
    except (ConfigMismatchError, FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("Vault index sync failed: %s", exc)
        raise SystemExit(1) from exc
    return result
