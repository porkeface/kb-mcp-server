"""FastEmbed 本地 Embedding 提供商"""

from typing import Sequence

import structlog

logger = structlog.get_logger()


class FastEmbedEmbedding:
    """FastEmbed 本地 Embedding 提供商

    使用 BAAI/bge-small-en-v1.5 模型，384 维，零成本。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        """初始化 FastEmbed Embedding 提供商

        Args:
            model_name: 模型名称
        """
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise ImportError("需要安装 fastembed: uv add fastembed")

        self._model_name = model_name
        self._model = TextEmbedding(model_name=model_name)

        logger.info("FastEmbed 初始化", model=model_name)

    @property
    def dimension(self) -> int:
        """向量维度"""
        # BAAI/bge-small-en-v1.5 是 384 维
        if "small" in self._model_name:
            return 384
        elif "base" in self._model_name:
            return 768
        return 384

    @property
    def model_name(self) -> str:
        """模型名称"""
        return self._model_name

    def embed(self, text: str) -> list[float]:
        """生成单个文本的向量

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        embeddings = list(self._model.embed([text]))
        return embeddings[0].tolist()

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成文本向量

        Args:
            texts: 输入文本列表

        Returns:
            向量列表的列表
        """
        if not texts:
            return []

        embeddings = list(self._model.embed(list(texts)))
        return [emb.tolist() for emb in embeddings]
