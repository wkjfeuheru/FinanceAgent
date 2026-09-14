"""本地 CPU embedding 的 seam 与 sentence-transformers 实现。

模型在首次调用时才加载，FastAPI 启动不会联网下载模型。
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from finance_agent import config


@runtime_checkable
class EmbeddingProvider(Protocol):
    """文本向量化边界；测试使用确定性 fake。"""

    @property
    def dimension(self) -> int: ...

    @property
    def descriptor(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbeddingProvider:
    """默认本地中文 embedding，固定 CPU、固定维度、L2 归一化。"""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        cache_dir: str | None = None,
        revision: str | None = None,
        dimension: int = 512,
    ) -> None:
        self._model_name = model_name or config.FAQ_EMBEDDING_MODEL
        self._device = device or config.FAQ_EMBEDDING_DEVICE
        self._cache_dir = cache_dir or config.FAQ_EMBEDDING_MODEL_CACHE_DIR
        self._revision = revision
        self._dimension = dimension
        self._model = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def descriptor(self) -> str:
        revision = self._revision or "main"
        return f"{self._model_name}@{revision}:dim{self._dimension}:normalized"

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
                cache_folder=self._cache_dir,
                revision=self._revision,
            )
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load_model()
        vectors = model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [list(map(float, vector)) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
