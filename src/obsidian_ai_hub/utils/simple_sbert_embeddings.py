import logging
import torch
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer
from . import config

logger = logging.getLogger(__name__)


class SimpleSbertEmbeddings:
    def __init__(self, model_name, cache_dir=None, allow_network_fallback=False):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.allow_network_fallback = allow_network_fallback
        self.device = (
            "mps"
            if torch.backends.mps.is_available()
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )

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

        self._load_model()
        self.embedding_dim = self._resolve_embedding_dim()

    def _load_model(self):
        path_to_model = self.model_name
        is_local = False
        if config.LOCAL_MODEL_DIR:
            local_path = config.LOCAL_MODEL_DIR / self.model_name
            if local_path.exists():
                path_to_model = str(local_path)
                is_local = True

        # 1. Try transformers from local path if it exists
        if is_local:
            try:
                if self._try_load_transformers(path_to_model, local_files_only=True):
                    return
            except Exception as e:
                if not self.allow_network_fallback:
                    raise RuntimeError(
                        f"Failed to load local model from {path_to_model}: {e}"
                    ) from e
                logger.warning(
                    "Failed to load local model %s, falling back to network",
                    path_to_model,
                    exc_info=True,
                )

        # 2. Try transformers with network fallback if allowed
        if self.allow_network_fallback:
            try:
                # If it was local and failed, we try model_name (which might be in cache or hub)
                # If it was not local, we try model_name
                if self._try_load_transformers(self.model_name, local_files_only=False):
                    return
            except Exception as e:
                logger.debug("Transformers network loading failed for %s", self.model_name, exc_info=True)

            # 3. Try SentenceTransformer with network fallback if allowed
            logger.info("Trying SentenceTransformer fallback for %s", self.model_name)
            try:
                st_kwargs = {}
                if self.cache_dir:
                    st_kwargs["cache_folder"] = str(self.cache_dir)
                self._model = SentenceTransformer(self.model_name, **st_kwargs)
                self._using_transformers = False
                return
            except Exception as e:
                logger.error("SentenceTransformer loading failed for %s", self.model_name, exc_info=True)
                raise RuntimeError(
                    f"Failed to load model {self.model_name} even with network fallback: {e}"
                ) from e

        # If we reach here, it means we couldn't load the model
        if is_local:
            raise RuntimeError(
                f"Failed to load local model {path_to_model} and network fallback is disabled."
            )
        else:
            raise RuntimeError(
                f"Model {self.model_name} not found locally and network fallback is disabled. "
                "Set VAULT_INDEX_ALLOW_NETWORK_FALLBACK=True to allow downloading."
            )

    def _try_load_transformers(self, path_to_model, local_files_only):
        tokenizer_kwargs = {"local_files_only": local_files_only}
        model_kwargs = {
            "torch_dtype": torch.float16,
            "low_cpu_mem_usage": True,
            "device_map": "auto",
            "local_files_only": local_files_only,
        }
        if self.cache_dir:
            tokenizer_kwargs["cache_dir"] = str(self.cache_dir)
            model_kwargs["cache_dir"] = str(self.cache_dir)

        self.tokenizer = AutoTokenizer.from_pretrained(
            path_to_model, **tokenizer_kwargs
        )
        try:
            self.model = AutoModel.from_pretrained(path_to_model, **model_kwargs)
        except Exception:
            # device_map が使えない環境向けのフォールバック
            model_kwargs.pop("device_map", None)
            model_kwargs.pop("torch_dtype", None)
            self.model = AutoModel.from_pretrained(path_to_model, **model_kwargs)
            # 試しに half にして device に移動
            try:
                self.model = self.model.half().to(self.device)
            except Exception:
                self.model = self.model.to(self.device)
        self._using_transformers = True
        return True

    def _resolve_embedding_dim(self) -> int:
        dim = None
        if not self._using_transformers:
            if hasattr(self._model, "get_embedding_dimension"):
                dim = self._model.get_embedding_dimension()
            elif hasattr(self._model, "get_sentence_embedding_dimension"):
                dim = self._model.get_sentence_embedding_dimension()
            elif hasattr(self._model, "dim"):
                dim = getattr(self._model, "dim")
        else:
            if hasattr(self.model.config, "hidden_size"):
                dim = self.model.config.hidden_size
            elif hasattr(self.model, "config") and hasattr(self.model.config, "d_model"):
                dim = self.model.config.d_model

        if not isinstance(dim, int) or dim <= 0:
            raise RuntimeError(
                f"Unable to determine embedding dimension for model: {self.model_name}"
            )

        return dim

    def _mean_pool(self, last_hidden_state, attention_mask):
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        )
        sum_embeddings = (last_hidden_state * input_mask_expanded).sum(1)
        sum_mask = input_mask_expanded.sum(1).clamp(min=1e-9)
        return sum_embeddings / sum_mask

    def _embed(self, texts, max_length=512, batch_size=16):
        if not self._using_transformers:
             # SentenceTransformer path
             encoded = self._model.encode(texts, show_progress_bar=False)
             if hasattr(encoded, "tolist"):
                 encoded = encoded.tolist()
             return [list(vector) for vector in encoded]

        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            enc = {k: v.to(self.model.device) for k, v in enc.items()}
            with torch.no_grad():
                out = self.model(**enc, return_dict=True)
                last = out.last_hidden_state
                pooled = self._mean_pool(last, enc["attention_mask"])
                all_vecs.extend(pooled.cpu().numpy())
        return [v.tolist() for v in all_vecs]

    def embed_documents(self, texts):
        documents_st_prefixed = [f"{self.doc_prefix}{doc}" for doc in texts]
        return self._embed(documents_st_prefixed)

    def embed_query(self, text):
        vecs = self._embed([f"{self.query_prefix}{text}"])
        return vecs[0]
