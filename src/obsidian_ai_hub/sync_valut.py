"""Sync the Obsidian vault into md-hybrid-search."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from md_hybrid_search import ConfigMismatchError, DirectorySource, SearchIndex

from obsidian_ai_hub.utils import config

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
        raise RuntimeError(f"Failed to prepare model cache directory: {cache_dir}") from exc

    for env_name in MODEL_CACHE_ENV_VARS:
        os.environ[env_name] = str(cache_dir)

    return cache_dir


def _prepare_storage_paths() -> tuple[Path, Path]:
    """Ensure SQLite and Chroma storage directories exist."""
    sqlite_path = config.VAULT_INDEX_SQLITE_PATH.expanduser()
    chroma_path = config.VAULT_INDEX_CHROMA_PATH.expanduser()

    try:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        chroma_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to prepare vault index storage directories: {sqlite_path.parent} and {chroma_path}"
        ) from exc

    return sqlite_path, chroma_path


def _load_sentence_transformer(model_name: str, cache_dir: Path | None):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for vault indexing. "
            "Install it with: pip install sentence-transformers"
        ) from exc

    kwargs: dict[str, Any] = {}
    if cache_dir is not None:
        kwargs["cache_folder"] = str(cache_dir)

    return SentenceTransformer(model_name, **kwargs)


class SentenceTransformerEmbedder:
    """md-hybrid-search compatible embedder built on sentence-transformers."""

    def __init__(self, model_name: str, cache_dir: Path | None = None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = _load_sentence_transformer(model_name, cache_dir)
        self.embedding_dim = self._resolve_embedding_dim()
        # model_nameに基づいてprefixを設定
        if "ruri-large" in model_name.lower():
            self.query_prefix = "クエリ: "
            self.doc_prefix = "文章: "
        elif "sarashina" in model_name.lower():
            self.query_prefix = "task: 検索クエリ\nquery: "
            self.doc_prefix = "text: "
        else:
            # default fallback
            self.query_prefix = ""
            self.doc_prefix = ""

    def _resolve_embedding_dim(self) -> int:
        dim = None
        if hasattr(self._model, "get_sentence_embedding_dimension"):
            dim = self._model.get_sentence_embedding_dimension()
        elif hasattr(self._model, "dim"):
            dim = getattr(self._model, "dim")

        if not isinstance(dim, int) or dim <= 0:
            raise RuntimeError(
                f"Unable to determine embedding dimension for model: {self.model_name}"
            )

        return dim

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        encoded = self._model.encode(texts, show_progress_bar=False)
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()

        return [list(vector) for vector in encoded]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        documents_st_prefixed = [f"{self.doc_prefix}{doc}" for doc in texts]
        return self._encode(documents_st_prefixed)

    def embed_query(self, text: str) -> list[float]:
        encoded = self._encode([f"{self.query_prefix}{text}"])
        return encoded[0] if encoded else []


def build_vault_search_index() -> SearchIndex:
    """Create a SearchIndex configured for the current vault."""
    cache_dir = _prepare_model_cache_dir()
    sqlite_path, chroma_path = _prepare_storage_paths()

    embedder = SentenceTransformerEmbedder(
        model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
        cache_dir=cache_dir,
    )

    return SearchIndex(
        collection_name=config.VAULT_INDEX_COLLECTION_NAME,
        sources=[DirectorySource(str(config.VAULT_PATH))],
        sqlite_path=str(sqlite_path),
        chroma_path=str(chroma_path),
        embedder=embedder,
    )


def main():
    """Synchronize the vault into the md-hybrid-search index."""
    try:
        index = build_vault_search_index()
        report = index.sync()
    except ConfigMismatchError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("Vault index sync failed: %s", exc)
        raise SystemExit(1) from exc

    logger.info(
        "Vault index sync completed: scanned=%s new=%s updated=%s unchanged=%s deleted=%s inserted_chunks=%s deleted_chunks=%s",
        report.scanned_files,
        report.new_files,
        report.updated_files,
        report.unchanged_files,
        report.deleted_files,
        report.inserted_chunks,
        report.deleted_chunks,
    )
    return report
