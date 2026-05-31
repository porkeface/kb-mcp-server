"""Qdrant 向量存储适配器"""

from dataclasses import dataclass
from datetime import datetime

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ..models.chunk import Chunk
from ..models.search import SearchResult

logger = structlog.get_logger()


@dataclass
class CollectionInfo:
    """Qdrant Collection 信息"""

    name: str
    vectors_count: int
    points_count: int
    status: str


class QdrantAdapter:
    """Qdrant 向量存储适配器

    每个知识库对应一个独立的 Qdrant Collection。
    """

    def __init__(self, url: str, api_key: str | None = None) -> None:
        """初始化 Qdrant 适配器

        Args:
            url: Qdrant 服务地址
            api_key: API Key（可选）
        """
        self._client = QdrantClient(url=url, api_key=api_key)
        logger.info("Qdrant 适配器初始化", url=url)

    def _collection_name(self, kb_name: str) -> str:
        """获取 Collection 名称"""
        return f"kb_{kb_name}"

    def ensure_collection(self, kb_name: str, dimension: int) -> None:
        """确保 Collection 存在

        Args:
            kb_name: 知识库名称
            dimension: 向量维度
        """
        collection_name = self._collection_name(kb_name)

        # 检查是否已存在
        collections = self._client.get_collections().collections
        exists = any(c.name == collection_name for c in collections)

        if not exists:
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            logger.info("Collection 已创建", collection=collection_name, dimension=dimension)
        else:
            logger.debug("Collection 已存在", collection=collection_name)

    def upsert_chunks(self, kb_name: str, chunks: list[Chunk]) -> None:
        """批量插入或更新分块

        Args:
            kb_name: 知识库名称
            chunks: 分块列表（必须包含 embedding）
        """
        if not chunks:
            return

        collection_name = self._collection_name(kb_name)

        points: list[PointStruct] = []
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning("跳过无向量的分块", chunk_id=chunk.id)
                continue

            payload = {
                "text": chunk.text,
                "doc_id": chunk.metadata.get("doc_id", ""),
                "chunk_index": chunk.metadata.get("chunk_index", "0"),
                "source": chunk.metadata.get("source", ""),
                "section": chunk.metadata.get("section", ""),
                "format": chunk.metadata.get("format", ""),
                "kb_name": kb_name,
                "indexed_at": datetime.now().isoformat(),  # TODO: 考虑使用 UTC 时间
            }

            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload=payload,
                )
            )

        if points:
            self._client.upsert(collection_name=collection_name, points=points)
            logger.info("分块已写入 Qdrant", collection=collection_name, count=len(points))

    def search(
        self,
        kb_name: str,
        query_vector: list[float],
        top_k: int = 10,
        score_threshold: float = 0.3,
    ) -> list[SearchResult]:
        """向量搜索

        Args:
            kb_name: 知识库名称
            query_vector: 查询向量
            top_k: 返回结果数量
            score_threshold: 最低相似度阈值

        Returns:
            搜索结果列表
        """
        collection_name = self._collection_name(kb_name)

        results = self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )

        search_results: list[SearchResult] = []
        for result in results.points:
            payload = result.payload or {}
            search_results.append(
                SearchResult(
                    text=payload.get("text", ""),
                    score=result.score,
                    source="vector",
                    metadata={
                        "doc_id": payload.get("doc_id", ""),
                        "chunk_index": payload.get("chunk_index", "0"),
                        "section": payload.get("section", ""),
                        "source": payload.get("source", ""),
                        "format": payload.get("format", ""),
                    },
                )
            )

        return search_results

    def keyword_search(
        self,
        kb_name: str,
        query: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """关键词全文搜索

        使用 Qdrant 的全文搜索功能（MatchText）进行关键词匹配。

        Args:
            kb_name: 知识库名称
            query: 搜索关键词
            top_k: 返回结果数量

        Returns:
            搜索结果列表
        """
        from qdrant_client.models import Filter, FieldCondition, MatchText

        collection_name = self._collection_name(kb_name)

        results = self._client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="text",
                        match=MatchText(query=query),
                    )
                ]
            ),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        search_results: list[SearchResult] = []
        for point in results[0]:
            payload = point.payload or {}
            search_results.append(
                SearchResult(
                    text=payload.get("text", ""),
                    score=0.8,
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

        return search_results

    def delete_collection(self, kb_name: str) -> None:
        """删除 Collection

        Args:
            kb_name: 知识库名称
        """
        collection_name = self._collection_name(kb_name)

        try:
            self._client.delete_collection(collection_name=collection_name)
            logger.info("Collection 已删除", collection=collection_name)
        except Exception as e:
            logger.warning("删除 Collection 失败", collection=collection_name, error=str(e))

    def delete_document(self, kb_name: str, doc_id: str) -> None:
        """删除文档的所有分块

        Args:
            kb_name: 知识库名称
            doc_id: 文档 ID
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        collection_name = self._collection_name(kb_name)

        self._client.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                ]
            ),
        )

        logger.info("文档分块已删除", collection=collection_name, doc_id=doc_id)

    def collection_info(self, kb_name: str) -> CollectionInfo:
        """获取 Collection 信息

        Args:
            kb_name: 知识库名称

        Returns:
            Collection 信息
        """
        collection_name = self._collection_name(kb_name)

        info = self._client.get_collection(collection_name=collection_name)

        return CollectionInfo(
            name=collection_name,
            vectors_count=info.vectors_count or 0,
            points_count=info.points_count or 0,
            status=str(info.status),
        )
