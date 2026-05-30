"""Embedding 提供商协议"""

from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Embedding 提供商协议

    支持运行时切换不同的 Embedding 提供商。
    """

    @property
    def dimension(self) -> int:
        """向量维度"""
        ...

    @property
    def model_name(self) -> str:
        """模型名称"""
        ...

    def embed(self, text: str) -> list[float]:
        """生成单个文本的向量

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成文本向量

        Args:
            texts: 输入文本列表

        Returns:
            向量列表的列表
        """
        ...
