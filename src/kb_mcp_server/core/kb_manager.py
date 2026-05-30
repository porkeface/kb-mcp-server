"""知识库管理器 - 核心业务逻辑"""

from pathlib import Path
from typing import Any
import uuid

import structlog

from ..config import Settings
from ..core.chunker import Chunker, ChunkerConfig
from ..embedding.base import EmbeddingProvider
from ..models.chunk import Chunk
from ..models.knowledge_base import KnowledgeBaseInfo
from ..models.search import SearchResult
from ..parsers import MarkdownParser, TextParser, PdfParser
from ..parsers.base import DocumentParser
from ..storage.registry import Registry
from ..storage.qdrant_adapter import QdrantAdapter

logger = structlog.get_logger()


class KBManager:
    """知识库管理器

    负责知识库的 CRUD 操作，协调解析器、分块器、Embedding 和存储层。
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
        logger.info("KBManager 初始化完成")

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
        except Exception:
            pass

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
            "file_name": path.name,
            "message": f"文档已成功导入，共 {len(chunks)} 个分块",
        }

    async def search(
        self,
        kb_name: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.2,
    ) -> list[SearchResult]:
        """向量语义搜索

        Args:
            kb_name: 知识库名称
            query: 搜索查询
            top_k: 返回结果数量
            score_threshold: 最低相似度阈值

        Returns:
            搜索结果列表

        Raises:
            ValueError: 知识库不存在
        """
        # 检查知识库是否存在
        kb_info = await self._registry.get_kb(kb_name)
        if not kb_info:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        # 生成查询向量
        query_vector = self._embedding.embed(query)

        # 向量搜索
        results = self._qdrant.search(
            kb_name=kb_name,
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        logger.info(
            "搜索完成",
            kb_name=kb_name,
            query=query[:50],
            result_count=len(results),
        )

        return results
