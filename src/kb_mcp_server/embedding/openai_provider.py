"""OpenAI Embedding 提供商"""

from typing import Sequence

import structlog

logger = structlog.get_logger()


class OpenAIEmbedding:
    """OpenAI Embedding 提供商

    使用 OpenAI text-embedding-3-small 模型，1536 维。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int | None = None,
        base_url: str | None = None,
    ) -> None:
        """初始化 OpenAI Embedding 提供商

        Args:
            api_key: OpenAI API Key
            model: 模型名称
            dimension: 向量维度（可选，默认由模型决定）
            base_url: API 基础地址（可选，用于 DeepSeek 等兼容 API）
        """
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._dimension = dimension

        logger.info("OpenAI Embedding 初始化", model=model, dimension=dimension, base_url=base_url)

    @property
    def dimension(self) -> int:
        """向量维度"""
        if self._dimension:
            return self._dimension
        # text-embedding-3-small 默认 1536 维
        if "small" in self._model:
            return 1536
        elif "large" in self._model:
            return 3072
        return 1536

    @property
    def model_name(self) -> str:
        """模型名称"""
        return self._model

    def embed(self, text: str) -> list[float]:
        """生成单个文本的向量

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        response = self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimension,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成文本向量

        Args:
            texts: 输入文本列表

        Returns:
            向量列表的列表
        """
        if not texts:
            return []

        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=self._dimension,
        )

        # 按索引排序确保顺序正确
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
