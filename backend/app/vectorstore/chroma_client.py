import logging
import os
import threading
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.utils.text_utils import chunk_text

logger = logging.getLogger(__name__)


class ChromaStore:
    """ChromaDB 封装，支持懒加载、异步模型加载和降级。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._client = None
                    cls._instance._collections = {}
                    cls._instance._embedding_fn = None
                    cls._instance._model_ready = False
                    cls._instance._model_loading = False
                    cls._instance._model_ready_event = threading.Event()
        return cls._instance

    def _ensure_client(self):
        if self._client is not None:
            return
        persist_dir = Path(settings.CHROMA_PERSIST_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        except Exception:
            logger.exception("ChromaDB 客户端初始化失败")
            self._client = None

    def _get_embedding_fn(self):
        if self._embedding_fn is not None:
            return self._embedding_fn

        # 启动后台线程加载 embedding 模型。
        if not self._model_loading:
            self._model_loading = True
            threading.Thread(target=self._load_model, daemon=True).start()

        # 模型尚未就绪时返回占位值，实际检索会等待 ready 标记。
        return None

    def _load_model(self):
        try:
            # 模型已在本地缓存，强制离线加载，避免联网检查更新时
            # 因 huggingface.co 不可达而触发 5 次重试（约 40s）阻塞。
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
            model.encode(["warmup"])
            self._embedding_fn = model.encode
            self._model_ready = True
            self._model_ready_event.set()
        except Exception:
            logger.exception("Embedding 模型加载失败，降级为简单哈希向量")
            # 本地模型加载失败时降级为简单哈希向量。
            def _simple_embed(texts: list[str]) -> list[list[float]]:
                results = []
                for text in texts:
                    vec = [0.0] * 128
                    for i, ch in enumerate(text[:1000]):
                        vec[ord(ch) % 128] += 1.0
                    total = sum(v * v for v in vec) ** 0.5
                    if total > 0:
                        vec = [v / total for v in vec]
                    results.append(vec)
                return results
            self._embedding_fn = _simple_embed
            self._model_ready = True
            self._model_ready_event.set()

    def _get_collection(self, name: str):
        self._ensure_client()
        if self._client is None:
            return None
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(name)
        return self._collections[name]

    def upsert_texts(self, collection_name: str, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None):
        if not texts:
            return
        embed_fn = self._get_embedding_fn()
        if not self._model_ready:
            self._model_ready_event.wait(timeout=30)
            embed_fn = self._get_embedding_fn()
        if not self._model_ready or embed_fn is None:
            logger.warning("Embedding 模型尚未就绪，跳过本次向量写入")
            return
        self._ensure_client()
        if self._client is None:
            return

        collection = self._get_collection(collection_name)
        if collection is None:
            return

        all_chunks, all_ids, all_metas = [], [], []
        for i, text in enumerate(texts):
            chunks = chunk_text(text)
            base_id = ids[i] if ids else str(i)
            base_meta = metadatas[i] if metadatas else {}
            for ci, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                all_chunks.append(chunk)
                all_ids.append(f"{base_id}_c{ci}")
                all_metas.append({**base_meta, "chunk_index": ci, "source_id": base_id})

        if not all_chunks:
            return

        embeddings = embed_fn(all_chunks)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()

        collection.upsert(ids=all_ids, documents=all_chunks, embeddings=embeddings, metadatas=all_metas)

    def search(self, collection_name: str, query: str, top_k: int = 5, kb_ids: list[str] | None = None) -> list[dict]:
        """语义检索；模型或 ChromaDB 不可用时返回空列表。"""
        embed_fn = self._get_embedding_fn()
        if not self._model_ready:
            self._model_ready_event.wait(timeout=30)
            embed_fn = self._get_embedding_fn()
        if not self._model_ready or embed_fn is None:
            return []
        self._ensure_client()
        if self._client is None:
            return []

        collection = self._get_collection(collection_name)
        if collection is None:
            return []

        try:
            qe = embed_fn([query])
            if hasattr(qe, "tolist"):
                qe = qe.tolist()

            where = {"kb_id": {"$in": kb_ids}} if kb_ids else None
            kwargs = {"where": where} if where else {}
            results = collection.query(query_embeddings=qe, n_results=top_k, include=["documents", "metadatas", "distances"], **kwargs)
            items = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    items.append({
                        "id": results["ids"][0][i],
                        "text": results["documents"][0][i] if results["documents"][0] else "",
                        "metadata": results["metadatas"][0][i] if results["metadatas"] and results["metadatas"][0] else {},
                        "distance": results["distances"][0][i] if results["distances"] and results["distances"][0] else 0,
                    })
            return items
        except Exception:
            logger.exception("ChromaDB 查询失败")
            return []

    def delete_by_source(self, collection_name: str, source_id: str):
        self._ensure_client()
        if self._client is None:
            return
        collection = self._get_collection(collection_name)
        if collection is None:
            return
        try:
            results = collection.get(where={"source_id": source_id})
            if results["ids"]:
                collection.delete(ids=results["ids"])
        except Exception:
            logger.exception("ChromaDB 删除来源文档失败")
