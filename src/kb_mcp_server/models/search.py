"""搜索结果数据模型"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    """单路搜索结果"""

    text: str  # 文本内容
    score: float  # 相似度分数
    source: str  # 来源: "vector" | "graph" | "keyword"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridSearchResult:
    """混合检索结果（RRF 融合后）"""

    text: str  # 文本内容
    score: float  # RRF 融合分数
    source: str  # 主要来源: "vector" | "graph" | "keyword"
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)  # 所有命中的来源
