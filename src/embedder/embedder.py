"""Embedder — sentence-transformers로 CPU 임베딩 생성."""
from __future__ import annotations
from pathlib import Path

from sentence_transformers import SentenceTransformer


class Embedder:
    """multilingual-e5-large 임베딩."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large", cache_dir: str | None = None):
        self.model = SentenceTransformer(
            model_name,
            cache_folder=cache_dir,
            device="cpu",
        )
        # e5 모델은 query/passage prefix 필요
        self._is_e5 = "e5" in model_name.lower()

    def embed_documents(self, texts: list[str], batch_size: int = 8) -> list[list[float]]:
        """문서(패시지) 임베딩. e5 모델은 'passage: ' prefix 추가."""
        if self._is_e5:
            texts = [f"passage: {t}" for t in texts]
        embeddings = self.model.encode(texts, batch_size=batch_size, show_progress_bar=True)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """질문 임베딩. e5 모델은 'query: ' prefix 추가."""
        text = f"query: {query}" if self._is_e5 else query
        embedding = self.model.encode([text])
        return embedding[0].tolist()
