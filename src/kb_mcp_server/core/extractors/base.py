"""实体提取器基类和协议"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...models.entity import Entity, Relation


@dataclass(frozen=True)
class ExtractionResult:
    """实体提取结果"""

    entities: list[Entity]
    relations: list[Relation]


class EntityExtractorBase(ABC):
    """实体提取器基类

    所有提取器（LLM、规则）都应实现此接口。
    """

    @abstractmethod
    async def extract(self, text: str) -> ExtractionResult:
        """从文本中提取实体和关系

        Args:
            text: 待提取的文本

        Returns:
            ExtractionResult 包含实体列表和关系列表
        """
        ...

    @abstractmethod
    async def extract_from_chunks(self, chunks: list[str]) -> ExtractionResult:
        """从多个文本块中提取实体和关系

        Args:
            chunks: 文本块列表

        Returns:
            合并后的 ExtractionResult
        """
        ...
