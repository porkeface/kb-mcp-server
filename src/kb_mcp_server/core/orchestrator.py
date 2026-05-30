"""混合检索编排器 - 三路检索 + RRF 融合"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import structlog

from ..embedding.base import EmbeddingProvider
from ..models.search import HybridSearchResult, SearchResult
from ..storage.qdrant_adapter import QdrantAdapter

logger = structlog.get_logger()

# RRF 常量
RRF_K = 60


# ---------------------------------------------------------------------------
# 图谱适配器协议（Neo4jAdapter 实现此协议）
# ---------------------------------------------------------------------------

class GraphAdapter(Protocol):
    """图谱检索适配器协议

    Neo4jAdapter 需实现此接口。方法为 async，因为底层使用 Neo4j 异步驱动。
    """

    async def search_entities(
        self,
        kb_name: str,
        query: str,
        limit: int = 20,
    ) -> list[Any]:
        """搜索实体（名称模糊匹配）

        Args:
            kb_name: 知识库名称
            query: 搜索关键词
            limit: 返回结果上限

        Returns:
            实体列表
        """
        ...

    async def get_neighbors(
        self,
        kb_name: str,
        entity_id: str,
        rel_type: str | None = None,
        depth: int = 1,
    ) -> list[Any]:
        """获取邻居节点

        Args:
            kb_name: 知识库名称
            entity_id: 起始实体 ID
            rel_type: 关系类型过滤（可选）
            depth: 遍历深度

        Returns:
            邻居实体列表
        """
        ...


# ---------------------------------------------------------------------------
# RRF 融合
# ---------------------------------------------------------------------------

def _rrf_fuse(
    ranked_lists: list[list[SearchResult]],
    weights: list[float],
    max_results: int,
) -> list[HybridSearchResult]:
    """Reciprocal Rank Fusion 融合算法

    对多路检索结果按 RRF 公式计算融合分数：
        RRF_score(doc) = Σ weight_i / (k + rank_i)

    Args:
        ranked_lists: 每路检索的有序结果列表
        weights: 每路检索的权重
        max_results: 最终返回的最大结果数

    Returns:
        按 RRF 分数降序排列的混合检索结果
    """
    # key -> {rrf_score, sources_set, best_result}
    score_map: dict[str, dict[str, Any]] = {}

    for results, weight in zip(ranked_lists, weights):
        for rank, result in enumerate(results):
            key = _dedup_key(result)
            rrf_contribution = weight / (RRF_K + rank)

            if key not in score_map:
                score_map[key] = {
                    "rrf_score": 0.0,
                    "sources": set(),
                    "result": result,
                }

            score_map[key]["rrf_score"] += rrf_contribution
            score_map[key]["sources"].add(result.source)

    # 按 RRF 分数降序排序
    sorted_items = sorted(
        score_map.values(),
        key=lambda x: x["rrf_score"],
        reverse=True,
    )

    # 构建最终结果
    fused: list[HybridSearchResult] = []
    for item in sorted_items[:max_results]:
        result: SearchResult = item["result"]
        sources = sorted(item["sources"])
        primary_source = sources[0] if sources else result.source

        fused.append(
            HybridSearchResult(
                text=result.text,
                score=item["rrf_score"],
                source=primary_source,
                metadata=dict(result.metadata),
                sources=sources,
            )
        )

    return fused


def _dedup_key(result: SearchResult) -> str:
    """生成去重键：基于文本内容的前 200 字符

    相同文本视为同一文档，融合时合并分数。
    """
    return result.text[:200].strip()


# ---------------------------------------------------------------------------
# 单路检索函数（同步，用于 run_in_executor）
# ---------------------------------------------------------------------------

def _vector_search_sync(
    qdrant: QdrantAdapter,
    embedding: EmbeddingProvider,
    kb_name: str,
    query: str,
    top_k: int,
) -> list[SearchResult]:
    """同步向量检索"""
    query_vector = embedding.embed(query)
    return qdrant.search(
        kb_name=kb_name,
        query_vector=query_vector,
        top_k=top_k,
        score_threshold=0.2,
    )


def _keyword_search_sync(
    qdrant: QdrantAdapter,
    embedding: EmbeddingProvider,
    kb_name: str,
    query: str,
    top_k: int,
) -> list[SearchResult]:
    """关键词检索 - 使用 Qdrant 全文搜索

    使用 Qdrant 的全文搜索功能（models.Text）进行关键词匹配。
    如果全文搜索不可用，降级为向量检索。
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchText

        # 使用 Qdrant 全文搜索
        collection_name = f"kb_{kb_name}"
        results = qdrant._client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="text",
                        match=MatchText(query=query)
                    )
                ]
            ),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        search_results = []
        for point in results[0]:  # results is (points, next_page_offset)
            payload = point.payload or {}
            search_results.append(
                SearchResult(
                    text=payload.get("text", ""),
                    score=0.8,  # 全文匹配给固定分数
                    source="keyword",
                    metadata={
                        "doc_id": payload.get("doc_id", ""),
                        "chunk_index": payload.get("chunk_index", "0"),
                        "section": payload.get("section", ""),
                        "source": payload.get("source", ""),
                        "format": payload.get("format", ""),
                    },
                )
            )

        if search_results:
            return search_results

        # 如果全文搜索没有结果，降级为向量检索
        logger.debug("全文搜索无结果，降级为向量检索", kb_name=kb_name, query=query[:50])
    except Exception as e:
        logger.debug("全文搜索不可用，使用向量检索", kb_name=kb_name, error=str(e))

    # 降级：使用向量检索
    query_vector = embedding.embed(query)
    return qdrant.search(
        kb_name=kb_name,
        query_vector=query_vector,
        top_k=top_k,
        score_threshold=0.1,
    )


# ---------------------------------------------------------------------------
# 图谱检索（async，直接 await Neo4jAdapter）
# ---------------------------------------------------------------------------

async def _graph_search_async(
    graph: GraphAdapter,
    kb_name: str,
    query: str,
    depth: int,
) -> list[SearchResult]:
    """异步图谱检索

    流程：
    1. 搜索匹配实体（名称 CONTAINS）
    2. 对每个实体获取 N 跳邻居
    3. 将实体 + 邻居的描述信息转为 SearchResult
    """

    # 第一步：模糊搜索匹配的实体
    entities = await graph.search_entities(kb_name, query, limit=10)
    if not entities:
        return []

    results: list[SearchResult] = []
    seen_ids: set[str] = set()

    for entity in entities:
        entity_id = entity.id
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)

        # 实体自身的描述
        desc = entity.properties.get("description", entity.name)
        if desc:
            results.append(
                SearchResult(
                    text=desc,
                    score=1.0,
                    source="graph",
                    metadata={
                        "entity_id": entity_id,
                        "entity_name": entity.name,
                        "entity_type": entity.entity_type,
                        "relation": "self",
                    },
                )
            )

        # 第二步：获取邻居节点（关系遍历）
        try:
            neighbors = await graph.get_neighbors(
                kb_name, entity_id, depth=depth
            )
            for neighbor in neighbors:
                if neighbor.id in seen_ids:
                    continue
                seen_ids.add(neighbor.id)

                neighbor_desc = neighbor.properties.get(
                    "description", neighbor.name
                )
                if neighbor_desc:
                    # 距离越近分数越高
                    neighbor_score = 0.8 / depth
                    results.append(
                        SearchResult(
                            text=neighbor_desc,
                            score=neighbor_score,
                            source="graph",
                            metadata={
                                "entity_id": neighbor.id,
                                "entity_name": neighbor.name,
                                "entity_type": neighbor.entity_type,
                                "relation": "neighbor",
                                "from_entity": entity.name,
                            },
                        )
                    )
        except Exception as exc:
            logger.warning(
                "获取邻居失败",
                kb_name=kb_name,
                entity_id=entity_id,
                error=str(exc),
            )

    return results


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------

class RetrievalOrchestrator:
    """混合检索编排器

    协调三路检索（向量、图谱、关键词），通过 RRF 算法融合结果。
    三路检索并行执行，单路失败不影响其他路。
    """

    def __init__(
        self,
        qdrant: QdrantAdapter,
        embedding: EmbeddingProvider,
        graph: GraphAdapter | None = None,
    ) -> None:
        """初始化编排器

        Args:
            qdrant: Qdrant 向量存储适配器
            embedding: Embedding 提供商
            graph: 图谱适配器（可选，未配置时跳过图谱检索）
        """
        self._qdrant = qdrant
        self._embedding = embedding
        self._graph = graph

        logger.info(
            "RetrievalOrchestrator 初始化",
            has_graph=graph is not None,
        )

    async def hybrid_search(
        self,
        kb_name: str,
        query: str,
        max_results: int = 10,
        vector_weight: float = 1.0,
        graph_weight: float = 0.8,
        keyword_weight: float = 0.5,
    ) -> list[HybridSearchResult]:
        """三路混合检索

        并行执行向量检索、图谱检索、关键词检索，然后通过 RRF 融合。

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            max_results: 最终返回的最大结果数
            vector_weight: 向量检索权重
            graph_weight: 图谱检索权重
            keyword_weight: 关键词检索权重

        Returns:
            RRF 融合后的混合检索结果列表
        """
        top_k = max_results * 3  # 每路取更多候选，融合后再截断

        logger.info(
            "开始混合检索",
            kb_name=kb_name,
            query=query[:80],
            max_results=max_results,
            weights={
                "vector": vector_weight,
                "graph": graph_weight,
                "keyword": keyword_weight,
            },
        )

        # 构建并行任务
        loop = asyncio.get_running_loop()
        coros: list[asyncio.Task[Any]] = []

        # 向量检索（同步 -> run_in_executor）
        vector_task = loop.run_in_executor(
            None,
            _vector_search_sync,
            self._qdrant,
            self._embedding,
            kb_name,
            query,
            top_k,
        )
        coros.append(asyncio.ensure_future(vector_task))

        # 图谱检索（async -> 直接创建 task）
        has_graph = self._graph is not None
        if has_graph:
            graph_task = asyncio.ensure_future(
                _graph_search_async(self._graph, kb_name, query, depth=2)
            )
            coros.append(graph_task)

        # 关键词检索（同步 -> run_in_executor）
        keyword_task = loop.run_in_executor(
            None,
            _keyword_search_sync,
            self._qdrant,
            self._embedding,
            kb_name,
            query,
            top_k,
        )
        coros.append(asyncio.ensure_future(keyword_task))

        # 并行等待，单路异常不传播
        results = await asyncio.gather(*coros, return_exceptions=True)

        # ── 收集各路结果 ──
        vector_results: list[SearchResult] = []
        graph_results: list[SearchResult] = []
        keyword_results: list[SearchResult] = []
        active_weights: list[float] = []
        active_results: list[list[SearchResult]] = []

        # 向量检索结果（始终为 index 0）
        if isinstance(results[0], Exception):
            logger.warning(
                "向量检索失败",
                kb_name=kb_name,
                error=str(results[0]),
            )
        else:
            vector_results = results[0]
            active_results.append(vector_results)
            active_weights.append(vector_weight)
            logger.debug("向量检索完成", count=len(vector_results))

        # 图谱检索结果（index 1，仅当配置了图谱适配器）
        if has_graph:
            if isinstance(results[1], Exception):
                logger.warning(
                    "图谱检索失败",
                    kb_name=kb_name,
                    error=str(results[1]),
                )
            else:
                graph_results = results[1]
                active_results.append(graph_results)
                active_weights.append(graph_weight)
                logger.debug("图谱检索完成", count=len(graph_results))

        # 关键词检索结果（最后一个）
        keyword_idx = len(results) - 1
        if isinstance(results[keyword_idx], Exception):
            logger.warning(
                "关键词检索失败",
                kb_name=kb_name,
                error=str(results[keyword_idx]),
            )
        else:
            keyword_results = results[keyword_idx]
            active_results.append(keyword_results)
            active_weights.append(keyword_weight)
            logger.debug("关键词检索完成", count=len(keyword_results))

        # 所有路都失败则返回空
        if not active_results:
            logger.error("所有检索路均失败", kb_name=kb_name)
            return []

        # RRF 融合
        fused = _rrf_fuse(active_results, active_weights, max_results)

        logger.info(
            "混合检索完成",
            kb_name=kb_name,
            vector_count=len(vector_results),
            graph_count=len(graph_results),
            keyword_count=len(keyword_results),
            fused_count=len(fused),
        )

        return fused

    async def vector_search(
        self,
        kb_name: str,
        query: str,
        top_k: int = 10,
    ) -> list[HybridSearchResult]:
        """纯向量检索

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            _vector_search_sync,
            self._qdrant,
            self._embedding,
            kb_name,
            query,
            top_k,
        )

        return [
            HybridSearchResult(
                text=r.text,
                score=r.score,
                source=r.source,
                metadata=dict(r.metadata),
                sources=[r.source],
            )
            for r in results
        ]

    async def graph_search(
        self,
        kb_name: str,
        query: str,
        depth: int = 2,
    ) -> list[HybridSearchResult]:
        """纯图谱检索

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            depth: 图遍历深度

        Returns:
            检索结果列表

        Raises:
            RuntimeError: 图谱适配器未配置
        """
        if self._graph is None:
            raise RuntimeError("图谱适配器未配置，无法执行图谱检索")

        results = await _graph_search_async(
            self._graph, kb_name, query, depth
        )

        return [
            HybridSearchResult(
                text=r.text,
                score=r.score,
                source=r.source,
                metadata=dict(r.metadata),
                sources=[r.source],
            )
            for r in results
        ]
