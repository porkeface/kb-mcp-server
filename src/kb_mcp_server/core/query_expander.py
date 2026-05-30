"""查询扩展模块 - 从知识图谱扩展查询语义"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from .orchestrator import GraphAdapter

logger = structlog.get_logger()


@dataclass(frozen=True)
class ExpansionConfig:
    """查询扩展配置"""

    max_neighbors: int = 10  # 最大邻居数量
    separator: str = " "  # 扩展词分隔符


class QueryExpander:
    """查询扩展器

    从知识图谱中获取查询实体的邻居节点，
    将邻居名称追加到查询文本中以提高召回率。

    示例:
        "乾卦" -> "乾卦 天 刚健 乾坤"
    """

    def __init__(
        self,
        graph: GraphAdapter,
        config: ExpansionConfig | None = None,
    ) -> None:
        """初始化查询扩展器

        Args:
            graph: 图谱适配器（需实现 GraphAdapter Protocol）
            config: 扩展配置
        """
        self._graph = graph
        self._config = config or ExpansionConfig()

    def _extract_entity_names(self, query: str) -> list[str]:
        """从查询文本中提取可能的实体名称

        使用简单的规则提取：
        - 中文词组（2-8 字）
        - 英文单词

        Args:
            query: 查询文本

        Returns:
            提取的实体名称列表
        """
        # 匹配中文词组（2-8 字）
        chinese_pattern = r"[一-鿿]{2,8}"
        # 匹配英文单词
        english_pattern = r"[a-zA-Z]+"

        entities: list[str] = []

        # 提取中文实体
        chinese_matches = re.findall(chinese_pattern, query)
        entities.extend(chinese_matches)

        # 提取英文实体
        english_matches = re.findall(english_pattern, query)
        entities.extend(english_matches)

        # 去重并保持顺序
        seen: set[str] = set()
        unique_entities: list[str] = []
        for entity in entities:
            if entity not in seen:
                seen.add(entity)
                unique_entities.append(entity)

        return unique_entities

    async def expand_query(self, kb_name: str, query: str, depth: int = 1) -> str:
        """扩展查询文本

        从图谱中获取查询实体的邻居节点，将邻居名称追加到查询中。

        Args:
            kb_name: 知识库名称
            query: 原始查询文本
            depth: 查询深度（默认 1 跳）

        Returns:
            扩展后的查询文本

        示例:
            >>> expander.expand_query("yijing", "乾卦")
            "乾卦 天 刚健 乾坤"
        """
        if not query.strip():
            return query

        # 提取实体名称
        entity_names = self._extract_entity_names(query)
        if not entity_names:
            logger.debug("查询中未提取到实体", query=query)
            return query

        logger.info(
            "开始扩展查询",
            kb=kb_name,
            query=query,
            entities=entity_names,
            depth=depth,
        )

        # 收集所有邻居名称
        seen_names: set[str] = set(entity_names)  # 排除原始查询中的实体
        expansion_parts: list[str] = []

        for entity_name in entity_names:
            try:
                # 搜索匹配的实体
                entities = await self._graph.search_entities(
                    kb_name=kb_name, query=entity_name, limit=5
                )

                for entity in entities:
                    # 获取该实体的邻居
                    neighbors = await self._graph.get_neighbors(
                        kb_name=kb_name,
                        entity_id=entity.id,
                        depth=depth,
                    )

                    for neighbor in neighbors:
                        neighbor_name = neighbor.name
                        if neighbor_name not in seen_names:
                            seen_names.add(neighbor_name)
                            expansion_parts.append(neighbor_name)

                            # 达到最大数量则停止
                            if len(expansion_parts) >= self._config.max_neighbors:
                                break

                    if len(expansion_parts) >= self._config.max_neighbors:
                        break

            except Exception as e:
                logger.warning(
                    "获取实体邻居失败",
                    entity=entity_name,
                    error=str(e),
                )
                continue

            if len(expansion_parts) >= self._config.max_neighbors:
                break

        if not expansion_parts:
            logger.debug("未找到邻居节点", query=query)
            return query

        # 拼接原始查询和扩展
        expansion_text = self._config.separator.join(expansion_parts)
        expanded_query = f"{query}{self._config.separator}{expansion_text}"

        logger.info(
            "查询扩展完成",
            kb=kb_name,
            original=query,
            expanded=expanded_query,
            neighbor_count=len(expansion_parts),
        )

        return expanded_query

    async def get_entity_context(
        self, kb_name: str, entity_name: str, depth: int = 1
    ) -> dict[str, Any]:
        """获取实体的上下文信息（用于 RAG 增强）

        Args:
            kb_name: 知识库名称
            entity_name: 实体名称
            depth: 查询深度

        Returns:
            实体上下文，格式:
            {
                "entity": "乾卦",
                "neighbors": ["天", "刚健", "乾坤"],
                "neighbor_count": 3
            }
        """
        try:
            # 搜索匹配的实体
            entities = await self._graph.search_entities(
                kb_name=kb_name, query=entity_name, limit=1
            )

            if not entities:
                return {
                    "entity": entity_name,
                    "neighbors": [],
                    "neighbor_count": 0,
                }

            entity = entities[0]

            # 获取邻居
            neighbors = await self._graph.get_neighbors(
                kb_name=kb_name,
                entity_id=entity.id,
                depth=depth,
            )

            neighbor_names = [n.name for n in neighbors]

            return {
                "entity": entity.name,
                "neighbors": neighbor_names,
                "neighbor_count": len(neighbor_names),
            }

        except Exception as e:
            logger.error(
                "获取实体上下文失败",
                entity=entity_name,
                kb=kb_name,
                error=str(e),
            )
            return {
                "entity": entity_name,
                "neighbors": [],
                "neighbor_count": 0,
                "error": str(e),
            }
