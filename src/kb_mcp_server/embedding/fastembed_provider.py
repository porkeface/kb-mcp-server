"""FastEmbed 本地 Embedding 提供商"""

from typing import Sequence

import structlog

logger = structlog.get_logger()


class FastEmbedEmbedding:
    """FastEmbed 本地 Embedding 提供商"""

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

        # 动态检测维度：用模型生成一个测试向量
        test_emb = list(self._model.embed(["test"]))[0]
        self._dimension = len(test_emb)

        logger.info("FastEmbed 初始化", model=model_name, dimension=self._dimension)

    @property
    def dimension(self) -> int:
        """向量维度（动态检测）"""
        return self._dimension

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
