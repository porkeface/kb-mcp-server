"""可配置的规则提取器 - 适用于有明确实体词表的领域"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from ...models.entity import Entity, Relation
from .base import EntityExtractorBase, ExtractionResult

logger = structlog.get_logger()


@dataclass(frozen=True)
class EntityRule:
    """实体提取规则"""

    entity_type: str  # 实体类型
    terms: list[str]  # 词表
    description_prefix: str = ""  # 描述前缀


@dataclass(frozen=True)
class RelationRule:
    """关系提取规则"""

    source_type: str  # 源实体类型
    target_type: str  # 目标实体类型
    relation_type: str  # 关系类型
    pattern: str = ""  # 匹配模式（正则），为空则自动关联
    description_template: str = "{source}与{target}相关"  # 描述模板


@dataclass(frozen=True)
class RuleConfig:
    """规则提取器配置

    示例：
        config = RuleConfig(
            name="finance",
            entity_rules=[
                EntityRule("indicator", ["市盈率", "市净率", "ROE", "ROA"], "财务指标："),
                EntityRule("concept", ["股票", "债券", "基金", "期货"], "金融概念："),
            ],
            relation_rules=[
                RelationRule("indicator", "concept", "USED_FOR", description_template="{source}用于衡量{target}"),
            ],
        )
    """

    name: str  # 配置名称
    entity_rules: list[EntityRule] = field(default_factory=list)
    relation_rules: list[RelationRule] = field(default_factory=list)


class RuleBasedExtractor(EntityExtractorBase):
    """可配置的规则提取器

    通过配置词表和关系规则来提取实体，适用于有明确术语表的领域。
    速度快、无需 LLM、免费，但需要预先配置词表。
    """

    def __init__(self, config: RuleConfig) -> None:
        """初始化规则提取器

        Args:
            config: 规则配置
        """
        self._config = config
        # 实体名称 -> Entity 映射（去重）
        self._entity_map: dict[str, Entity] = {}
        # 关系去重
        self._relation_keys: set[tuple[str, str, str]] = set()
        self._relations: list[Relation] = []
        # 实体类型 -> 名称集合（用于关系匹配）
        self._type_entities: dict[str, set[str]] = {}

        logger.info("RuleBasedExtractor 初始化", config_name=config.name)

    def _reset(self) -> None:
        """重置状态"""
        self._entity_map.clear()
        self._relation_keys.clear()
        self._relations.clear()
        self._type_entities.clear()

    def _get_or_create_entity(
        self,
        name: str,
        entity_type: str,
        description: str = "",
    ) -> Entity:
        """获取或创建实体（去重）"""
        if name in self._entity_map:
            return self._entity_map[name]

        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        props = {}
        if description:
            props["description"] = description

        entity = Entity(id=entity_id, name=name, entity_type=entity_type, properties=props)
        self._entity_map[name] = entity

        # 记录类型映射
        if entity_type not in self._type_entities:
            self._type_entities[entity_type] = set()
        self._type_entities[entity_type].add(name)

        return entity

    def _add_relation(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        description: str = "",
    ) -> None:
        """添加关系（去重）"""
        key = (source_name, target_name, rel_type)
        if key in self._relation_keys:
            return
        self._relation_keys.add(key)

        source = self._entity_map.get(source_name)
        target = self._entity_map.get(target_name)
        if not source or not target:
            return

        props = {}
        if description:
            props["description"] = description

        self._relations.append(
            Relation(
                source_id=source.id,
                target_id=target.id,
                relation_type=rel_type,
                properties=props,
            )
        )

    def _extract_entities(self, text: str) -> None:
        """根据规则提取实体"""
        for rule in self._config.entity_rules:
            for term in rule.terms:
                # 使用词边界匹配
                if re.search(rf"(?:^|[，。、；\s]){re.escape(term)}(?:$|[，。、；\s])", text):
                    desc = f"{rule.description_prefix}{term}" if rule.description_prefix else ""
                    self._get_or_create_entity(term, rule.entity_type, desc)

    def _extract_relations(self, text: str) -> None:
        """根据规则提取关系"""
        for rule in self._config.relation_rules:
            source_names = self._type_entities.get(rule.source_type, set())
            target_names = self._type_entities.get(rule.target_type, set())

            for source_name in source_names:
                for target_name in target_names:
                    if source_name == target_name:
                        continue

                    # 如果有匹配模式，检查是否匹配
                    if rule.pattern:
                        if not re.search(rule.pattern, text):
                            continue

                    # 检查文本中是否同时出现源和目标
                    if source_name in text and target_name in text:
                        desc = rule.description_template.format(
                            source=source_name, target=target_name
                        )
                        self._add_relation(source_name, target_name, rule.relation_type, desc)

    def extract(self, text: str) -> ExtractionResult:
        """从文本中提取实体和关系"""
        self._reset()

        self._extract_entities(text)
        self._extract_relations(text)

        entities = list(self._entity_map.values())
        relations = self._relations

        logger.info(
            "规则提取完成",
            config_name=self._config.name,
            entity_count=len(entities),
            relation_count=len(relations),
        )

        return ExtractionResult(entities=entities, relations=relations)

    async def extract_from_chunks(self, chunks: list[str]) -> ExtractionResult:
        """从多个文本块中提取实体和关系"""
        self._reset()

        for chunk in chunks:
            self._extract_entities(chunk)
            self._extract_relations(chunk)

        entities = list(self._entity_map.values())
        relations = self._relations

        logger.info(
            "分块提取完成",
            config_name=self._config.name,
            chunk_count=len(chunks),
            total_entities=len(entities),
            total_relations=len(relations),
        )

        return ExtractionResult(entities=entities, relations=relations)
