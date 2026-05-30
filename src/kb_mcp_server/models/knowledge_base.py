"""知识库信息数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class KnowledgeBaseInfo:
    """知识库元信息"""

    name: str  # 知识库名称
    description: str = ""  # 知识库描述
    embedding_provider: str = "openai"  # Embedding 提供商
    embedding_model: str = "text-embedding-3-small"  # Embedding 模型
    embedding_dimension: int = 1536  # 向量维度
    document_count: int = 0  # 文档数量
    chunk_count: int = 0  # 分块数量
    entity_count: int = 0  # 实体数量
    relation_count: int = 0  # 关系数量
    created_at: datetime | None = None  # 创建时间
    updated_at: datetime | None = None  # 更新时间
    extra: dict[str, Any] = field(default_factory=dict)  # 扩展字段
