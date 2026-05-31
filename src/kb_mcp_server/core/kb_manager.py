"""知识库管理器 - 核心业务逻辑"""

from pathlib import Path
from typing import Any
import uuid

import structlog
from neo4j import AsyncGraphDatabase

from ..config import Settings
from ..core.chunker import Chunker, ChunkerConfig
from ..core.extractors import LLMEntityExtractor, RuleBasedExtractor
from ..core.extractors.factory import create_extractor
from ..core.orchestrator import RetrievalOrchestrator
from ..embedding.base import EmbeddingProvider
from ..models.chunk import Chunk
from ..models.knowledge_base import KnowledgeBaseInfo
from ..models.search import HybridSearchResult, SearchResult
from ..parsers import MarkdownParser, TextParser, PdfParser
from ..parsers.base import DocumentParser
from ..storage.neo4j_adapter import Neo4jAdapter
from ..storage.registry import Registry
from ..storage.qdrant_adapter import QdrantAdapter

logger = structlog.get_logger()


class KBManager:
    """知识库管理器

    负责知识库的 CRUD 操作，协调解析器、分块器、Embedding 和存储层。
    支持向量检索 + 图谱检索 + 关键词检索的三路融合。
    """

    def __init__(
        self,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        """初始化知识库管理器

        Args:
            settings: 应用配置
            embedding_provider: Embedding 提供商
        """
        self._settings = settings
        self._embedding = embedding_provider

        # 初始化存储层
        self._registry = Registry(settings.registry_db_path)
        self._qdrant = QdrantAdapter(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

        # 初始化 Neo4j 适配器
        self._neo4j: Neo4jAdapter | None = None
        if settings.neo4j_uri:
            try:
                driver = AsyncGraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                self._neo4j = Neo4jAdapter(driver)
                logger.info("Neo4j 适配器已初始化", uri=settings.neo4j_uri)
            except Exception as e:
                logger.warning("Neo4j 初始化失败，图谱功能不可用", error=str(e))

        # 初始化实体提取器（根据配置选择）
        self._extractor = create_extractor(
            settings,
            extractor_type=settings.kb_mcp_extractor_type,
        )
        logger.info(
            "实体提取器初始化",
            type=settings.kb_mcp_extractor_type,
            extractor_type=type(self._extractor).__name__,
        )

        # 初始化检索编排器（三路融合）
        self._orchestrator = RetrievalOrchestrator(
            qdrant=self._qdrant,
            embedding=embedding_provider,
            graph=self._neo4j,
        )

        # 初始化解析器
        self._parsers: dict[str, DocumentParser] = {
            ".md": MarkdownParser(),
            ".markdown": MarkdownParser(),
            ".txt": TextParser(),
            ".text": TextParser(),
            ".pdf": PdfParser(),
        }

        # 初始化分块器
        self._chunker = Chunker()

    async def initialize(self) -> None:
        """初始化管理器（创建数据库表等）"""
        await self._registry.initialize()
        logger.info("KBManager 初始化完成", has_neo4j=self._neo4j is not None)

    async def create_kb(
        self,
        name: str,
        description: str = "",
    ) -> KnowledgeBaseInfo:
        """创建知识库

        Args:
            name: 知识库名称
            description: 描述

        Returns:
            创建的知识库信息

        Raises:
            ValueError: 知识库名称已存在
        """
        # 检查是否已存在
        existing = await self._registry.get_kb(name)
        if existing:
            raise ValueError(f"知识库 '{name}' 已存在")

        # 在 Qdrant 中创建 Collection
        self._qdrant.ensure_collection(name, self._embedding.dimension)

        # 在 Neo4j 中创建索引
        if self._neo4j:
            try:
                await self._neo4j.ensure_indexes(name)
                logger.info("Neo4j 索引已创建", kb=name)
            except Exception as e:
                logger.warning("创建 Neo4j 索引失败", kb=name, error=str(e))

        # 在注册表中创建记录
        kb_info = await self._registry.create_kb(
            name=name,
            description=description,
            embedding_provider=self._settings.embedding_provider,
            embedding_model=self._settings.embedding_model,
            embedding_dimension=self._embedding.dimension,
        )

        logger.info("知识库已创建", name=name)
        return kb_info

    async def list_kbs(self) -> list[KnowledgeBaseInfo]:
        """列出所有知识库

        Returns:
            知识库信息列表
        """
        return await self._registry.list_kbs()

    async def get_kb_info(self, name: str) -> KnowledgeBaseInfo | None:
        """获取知识库详情

        Args:
            name: 知识库名称

        Returns:
            知识库信息，不存在返回 None
        """
        kb_info = await self._registry.get_kb(name)
        if not kb_info:
            return None

        # 尝试从 Qdrant 获取更多信息
        try:
            collection_info = self._qdrant.collection_info(name)
            kb_info.extra["qdrant_points"] = collection_info.points_count
            kb_info.extra["qdrant_status"] = collection_info.status
        except Exception as e:
            logger.debug("获取 Qdrant 信息失败", kb=name, error=str(e))

        # 尝试从 Neo4j 获取图谱信息
        if self._neo4j:
            try:
                entity_count = await self._neo4j.get_entity_count(name)
                relation_count = await self._neo4j.get_relation_count(name)
                kb_info.extra["neo4j_entities"] = entity_count
                kb_info.extra["neo4j_relations"] = relation_count
            except Exception as e:
                logger.debug("获取 Neo4j 信息失败", kb=name, error=str(e))

        return kb_info

    async def delete_kb(self, name: str, confirm: bool = False) -> dict[str, Any]:
        """删除知识库

        Args:
            name: 知识库名称
            confirm: 确认删除

        Returns:
            删除结果

        Raises:
            ValueError: 未确认删除或知识库不存在
        """
        if not confirm:
            raise ValueError("必须设置 confirm=True 才能删除知识库")

        # 检查是否存在
        existing = await self._registry.get_kb(name)
        if not existing:
            raise ValueError(f"知识库 '{name}' 不存在")

        # 从 Qdrant 删除 Collection
        self._qdrant.delete_collection(name)

        # 从 Neo4j 删除图数据
        if self._neo4j:
            try:
                await self._neo4j.delete_database(name)
                logger.info("Neo4j 图数据已删除", kb=name)
            except Exception as e:
                logger.warning("删除 Neo4j 数据失败", kb=name, error=str(e))

        # 从注册表删除
        await self._registry.delete_kb(name)

        logger.info("知识库已删除", name=name)
        return {"success": True, "message": f"知识库 '{name}' 已删除"}

    async def ingest(
        self,
        kb_name: str,
        file_path: str,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> dict[str, Any]:
        """导入文档到知识库

        Args:
            kb_name: 知识库名称
            file_path: 文件路径
            chunk_size: 分块大小
            chunk_overlap: 块重叠

        Returns:
            导入结果

        Raises:
            ValueError: 知识库不存在或文件格式不支持
            FileNotFoundError: 文件不存在
        """
        # 检查知识库是否存在
        kb_info = await self._registry.get_kb(kb_name)
        if not kb_info:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        # 检查文件是否存在
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 获取解析器
        ext = path.suffix.lower()
        parser = self._parsers.get(ext)
        if not parser:
            raise ValueError(f"不支持的文件格式: {ext}")

        # 解析文档
        logger.info("开始解析文档", file=file_path, format=ext)
        parsed_chunks = parser.parse(file_path)

        # 分块
        doc_id = uuid.uuid4().hex[:12]
        chunker = Chunker(ChunkerConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap))
        chunks = chunker.chunk(list(parsed_chunks), kb_name, doc_id)

        if not chunks:
            return {"doc_id": doc_id, "chunk_count": 0, "message": "文档无有效内容"}

        # 生成 Embedding
        logger.info("开始生成 Embedding", chunk_count=len(chunks))
        texts = [c.text for c in chunks]
        embeddings = self._embedding.embed_batch(texts)

        # 将 Embedding 附加到 Chunk
        chunks_with_embedding: list[Chunk] = []
        for chunk, embedding in zip(chunks, embeddings):
            chunks_with_embedding.append(
                Chunk(
                    id=chunk.id,
                    text=chunk.text,
                    embedding=embedding,
                    metadata=chunk.metadata,
                )
            )

        # 写入 Qdrant
        self._qdrant.upsert_chunks(kb_name, chunks_with_embedding)

        # 提取实体并写入 Neo4j
        entity_count = 0
        relation_count = 0
        if self._neo4j and self._settings.kb_mcp_extract_entities:
            try:
                logger.info("开始提取实体", kb=kb_name, extractor=type(self._extractor).__name__)
                chunk_texts = [c.text for c in chunks]
                extraction = await self._extractor.extract_from_chunks(chunk_texts)

                if extraction.entities:
                    entity_count = await self._neo4j.add_entities_batch(
                        kb_name, extraction.entities
                    )
                if extraction.relations:
                    relation_count = await self._neo4j.add_relations_batch(
                        kb_name, extraction.relations
                    )

                logger.info(
                    "实体写入 Neo4j 完成",
                    kb=kb_name,
                    entities=entity_count,
                    relations=relation_count,
                )
            except Exception as e:
                logger.warning(
                    "实体提取/写入失败（不影响文档导入）",
                    kb=kb_name,
                    error=str(e),
                )

        # 记录文档信息
        await self._registry.add_document(
            kb_name=kb_name,
            doc_id=doc_id,
            file_path=file_path,
            file_name=path.name,
            file_format=ext,
            chunk_count=len(chunks),
        )

        logger.info(
            "文档导入完成",
            kb_name=kb_name,
            doc_id=doc_id,
            chunk_count=len(chunks),
        )

        return {
            "doc_id": doc_id,
            "chunk_count": len(chunks),
            "entity_count": entity_count,
            "relation_count": relation_count,
            "file_name": path.name,
            "message": f"文档已成功导入，共 {len(chunks)} 个分块，{entity_count} 个实体，{relation_count} 个关系",
        }

    async def search(
        self,
        kb_name: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.01,
    ) -> list[SearchResult]:
        """三路融合搜索（向量 + 图谱 + 关键词）

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            top_k: 返回结果数量
            score_threshold: 最低相似度阈值（RRF 融合后分数较低，默认 0.01）

        Returns:
            搜索结果列表

        Raises:
            ValueError: 知识库不存在
        """
        # 检查知识库是否存在
        kb_info = await self._registry.get_kb(kb_name)
        if not kb_info:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        # 使用三路融合搜索
        hybrid_results = await self._orchestrator.hybrid_search(
            kb_name=kb_name,
            query=query,
            max_results=top_k,
        )

        # 转换为 SearchResult 格式
        results: list[SearchResult] = []
        for hr in hybrid_results:
            if hr.score >= score_threshold:
                results.append(
                    SearchResult(
                        text=hr.text,
                        score=hr.score,
                        source=hr.source,
                        metadata=hr.metadata,
                    )
                )

        logger.info(
            "搜索完成",
            kb_name=kb_name,
            query=query[:50],
            result_count=len(results),
        )

        return results

    async def hybrid_search(
        self,
        kb_name: str,
        query: str,
        max_results: int = 10,
    ) -> list[HybridSearchResult]:
        """三路融合搜索（详细版本，返回 HybridSearchResult）

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            混合搜索结果列表
        """
        kb_info = await self._registry.get_kb(kb_name)
        if not kb_info:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        return await self._orchestrator.hybrid_search(
            kb_name=kb_name,
            query=query,
            max_results=max_results,
        )
