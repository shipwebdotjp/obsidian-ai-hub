import torch
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer
import config


class SimpleSbertEmbeddings:
    def __init__(self, model_name):
        path_to_model = str(config.LOCAL_MODEL_DIR / model_name)
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

        # まずは transformers 側で低メモリ読み込みを試みる
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                path_to_model, local_files_only=True
            )
            # low_cpu_mem_usage と torch_dtype を指定して読み込む（可能なら半精度で）
            try:
                self.model = AutoModel.from_pretrained(
                    path_to_model,
                    torch_dtype=torch.float16,
                    low_cpu_mem_usage=True,
                    device_map="auto",
                    local_files_only=True,
                )
            except Exception:
                # device_map が使えない環境向けのフォールバック
                self.model = AutoModel.from_pretrained(
                    path_to_model, low_cpu_mem_usage=True, local_files_only=True
                )
                # 試しに half にして device に移動
                try:
                    self.model = self.model.half().to(self.device)
                except Exception:
                    self.model = self.model.to(self.device)
        except Exception:
            # transformers で失敗したら元の SentenceTransformer にフォールバック
            path_to_model = str(config.LOCAL_MODEL_DIR / model_name)
            self._model = SentenceTransformer(path_to_model)
            return

    def _resolve_embedding_dim(self) -> int:
        dim = None
        if hasattr(self._model, "get_sentence_embedding_dimension"):
            dim = self._model.get_embedding_dimension()
        elif hasattr(self._model, "dim"):
            dim = getattr(self._model, "dim")

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
