"""知识图谱实体和关系数据模型"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Entity:
    """知识图谱实体节点"""

    id: str  # 唯一ID
    name: str  # 实体名称
    entity_type: str = "concept"  # 实体类型: concept, hexagram, person, org, etc.
    properties: dict[str, Any] = field(default_factory=dict)
    # properties 包含: description, source, created_at 等


@dataclass(frozen=True)
class Relation:
    """知识图谱关系边"""

    source_id: str  # 源实体 ID
    target_id: str  # 目标实体 ID
    relation_type: str  # 关系类型: RELATED_TO, MENTIONS, BELONGS_TO, etc.
    properties: dict[str, Any] = field(default_factory=dict)
    # properties 包含: weight, source, created_at 等
