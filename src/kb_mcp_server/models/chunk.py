"""文档分块数据模型"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedChunk:
    """解析后的文档片段（分块前）"""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 包含: source, page, section_title, format 等


@dataclass(frozen=True)
class Chunk:
    """分块结果"""

    id: str  # 唯一ID: {kb_name}_{doc_id}_{chunk_index}
    text: str  # 块文本
    embedding: list[float] | None = None  # 向量（延迟生成）
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 包含: doc_id, chunk_index, chunk_total, source, section, format, kb_name, indexed_at
