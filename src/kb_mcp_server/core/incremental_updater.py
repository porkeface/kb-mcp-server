"""增量更新模块 - 检测文档变更并智能更新索引"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import structlog

from ..core.chunker import Chunker, ChunkerConfig
from ..embedding.base import EmbeddingProvider
from ..models.chunk import Chunk
from ..parsers import MarkdownParser, TextParser, PdfParser
from ..parsers.base import DocumentParser
from ..storage.qdrant_adapter import QdrantAdapter
from ..storage.registry import Registry

logger = structlog.get_logger()


@dataclass(frozen=True)
class DocumentFingerprint:
    """文档指纹"""

    doc_id: str
    file_path: str
    file_hash: str
    chunk_hashes: list[str]
    indexed_at: datetime


@dataclass(frozen=True)
class UpdateResult:
    """更新结果"""

    doc_id: str
    action: str  # "created" | "updated" | "unchanged" | "deleted"
    chunks_added: int = 0
    chunks_removed: int = 0
    chunks_updated: int = 0
    message: str = ""


# 增量更新专用的 SQL
INCREMENTAL_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS document_fingerprints (
    doc_id       TEXT PRIMARY KEY,
    kb_name      TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    file_hash    TEXT NOT NULL,
    chunk_hashes TEXT NOT NULL,  -- JSON array
    indexed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (kb_name) REFERENCES knowledge_bases(name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fingerprints_kb
    ON document_fingerprints(kb_name);

CREATE INDEX IF NOT EXISTS idx_fingerprints_path
    ON document_fingerprints(kb_name, file_path);
"""


class IncrementalUpdater:
    """增量更新器

    通过文件哈希检测文档变更，只重新索引变更的分块，
    支持文档删除。
    """

    def __init__(
        self,
        registry: Registry,
        qdrant: QdrantAdapter,
        embedding_provider: EmbeddingProvider,
        db_path: Path | None = None,
    ) -> None:
        """初始化增量更新器

        Args:
            registry: 元数据注册表
            qdrant: Qdrant 适配器
            embedding_provider: Embedding 提供商
            db_path: 指纹数据库路径（默认使用 registry 同目录）
        """
        self._registry = registry
        self._qdrant = qdrant
        self._embedding = embedding_provider

        # 指纹数据库路径
        if db_path is None:
            # 从 registry 的 db_path 推断
            registry_db_path = registry._db_path
            self._db_path = registry_db_path.parent / "fingerprints.db"
        else:
            self._db_path = db_path

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

        logger.info("增量更新器初始化", db_path=str(self._db_path))

    async def initialize(self) -> None:
        """初始化指纹数据库"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(INCREMENTAL_TABLES_SQL)
            await db.commit()
        logger.info("指纹数据库初始化完成")

    def _compute_file_hash(self, file_path: str) -> str:
        """计算文件哈希

        Args:
            file_path: 文件路径

        Returns:
            文件的 SHA256 哈希值

        Raises:
            FileNotFoundError: 文件不存在
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    def _compute_chunk_hash(self, text: str) -> str:
        """计算分块文本哈希

        Args:
            text: 分块文本

        Returns:
            文本的 SHA256 哈希值
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def _get_fingerprint(
        self, kb_name: str, file_path: str
    ) -> DocumentFingerprint | None:
        """获取文档指纹

        Args:
            kb_name: 知识库名称
            file_path: 文件路径

        Returns:
            文档指纹，不存在返回 None
        """
        import json

        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM document_fingerprints
                WHERE kb_name = ? AND file_path = ?
                """,
                (kb_name, file_path),
            )
            row = await cursor.fetchone()

            if not row:
                return None

            chunk_hashes = json.loads(row["chunk_hashes"])
            return DocumentFingerprint(
                doc_id=row["doc_id"],
                file_path=row["file_path"],
                file_hash=row["file_hash"],
                chunk_hashes=chunk_hashes,
                indexed_at=datetime.fromisoformat(row["indexed_at"]),
            )

    async def _save_fingerprint(
        self, kb_name: str, fingerprint: DocumentFingerprint
    ) -> None:
        """保存文档指纹

        Args:
            kb_name: 知识库名称
            fingerprint: 文档指纹
        """
        import json

        chunk_hashes_json = json.dumps(fingerprint.chunk_hashes)

        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO document_fingerprints
                    (doc_id, kb_name, file_path, file_hash, chunk_hashes, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint.doc_id,
                    kb_name,
                    fingerprint.file_path,
                    fingerprint.file_hash,
                    chunk_hashes_json,
                    fingerprint.indexed_at,
                ),
            )
            await db.commit()

    async def _delete_fingerprint(self, kb_name: str, doc_id: str) -> None:
        """删除文档指纹

        Args:
            kb_name: 知识库名称
            doc_id: 文档 ID
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                "DELETE FROM document_fingerprints WHERE doc_id = ? AND kb_name = ?",
                (doc_id, kb_name),
            )
            await db.commit()

    async def check_changes(self, kb_name: str, file_path: str) -> bool:
        """检查文档是否有变更

        通过比较文件哈希判断文档是否已修改。

        Args:
            kb_name: 知识库名称
            file_path: 文件路径

        Returns:
            True 如果文档有变更或为新文档，False 如果文档未变更
        """
        try:
            # 计算当前文件哈希
            current_hash = self._compute_file_hash(file_path)

            # 获取已存储的指纹
            fingerprint = await self._get_fingerprint(kb_name, file_path)

            if fingerprint is None:
                logger.info("新文档检测", file=file_path, kb=kb_name)
                return True

            # 比较哈希
            if fingerprint.file_hash != current_hash:
                logger.info(
                    "文档变更检测",
                    file=file_path,
                    kb=kb_name,
                    old_hash=fingerprint.file_hash[:8],
                    new_hash=current_hash[:8],
                )
                return True

            logger.debug("文档未变更", file=file_path, kb=kb_name)
            return False

        except FileNotFoundError:
            logger.warning("文件不存在", file=file_path)
            return False
        except Exception as e:
            logger.error("检查文档变更失败", file=file_path, error=str(e))
            return True  # 出错时假设有变更

    async def update_document(
        self,
        kb_name: str,
        file_path: str,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> UpdateResult:
        """更新文档索引

        检测文档变更，只重新索引变更的分块。

        Args:
            kb_name: 知识库名称
            file_path: 文件路径
            chunk_size: 分块大小
            chunk_overlap: 块重叠

        Returns:
            更新结果

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 知识库不存在或文件格式不支持
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 检查知识库是否存在
        kb_info = await self._registry.get_kb(kb_name)
        if not kb_info:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        # 获取解析器
        ext = path.suffix.lower()
        parser = self._parsers.get(ext)
        if not parser:
            raise ValueError(f"不支持的文件格式: {ext}")

        # 计算当前文件哈希
        current_hash = self._compute_file_hash(file_path)

        # 获取已存储的指纹
        old_fingerprint = await self._get_fingerprint(kb_name, file_path)

        # 如果文档未变更，直接返回
        if old_fingerprint and old_fingerprint.file_hash == current_hash:
            return UpdateResult(
                doc_id=old_fingerprint.doc_id,
                action="unchanged",
                message="文档未变更，无需更新",
            )

        # 解析并分块文档
        logger.info("开始解析文档", file=file_path, format=ext)
        parsed_chunks = parser.parse(file_path)

        # 生成文档 ID（复用旧 ID 或创建新 ID）
        import uuid

        doc_id = old_fingerprint.doc_id if old_fingerprint else uuid.uuid4().hex[:12]

        chunker = Chunker(ChunkerConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap))
        chunks = chunker.chunk(list(parsed_chunks), kb_name, doc_id)

        if not chunks:
            # 文档无内容，删除旧索引
            if old_fingerprint:
                self._qdrant.delete_document(kb_name, doc_id)
                await self._delete_fingerprint(kb_name, doc_id)
                await self._registry.delete_document(kb_name, doc_id)
                return UpdateResult(
                    doc_id=doc_id,
                    action="updated",
                    chunks_removed=len(old_fingerprint.chunk_hashes),
                    message="文档内容已清空",
                )
            return UpdateResult(
                doc_id=doc_id,
                action="created",
                message="文档无有效内容",
            )

        # 计算新分块哈希
        new_chunk_hashes = [self._compute_chunk_hash(c.text) for c in chunks]

        # 计算变更的分块
        if old_fingerprint:
            old_hashes_set = set(old_fingerprint.chunk_hashes)
            new_hashes_set = set(new_chunk_hashes)

            added_hashes = new_hashes_set - old_hashes_set
            removed_hashes = old_hashes_set - new_hashes_set
            unchanged_hashes = old_hashes_set & new_hashes_set

            logger.info(
                "分块变更统计",
                total=len(chunks),
                added=len(added_hashes),
                removed=len(removed_hashes),
                unchanged=len(unchanged_hashes),
            )

            # 只为变更的分块生成 Embedding
            chunks_to_embed = [
                c for c in chunks if self._compute_chunk_hash(c.text) in added_hashes
            ]
        else:
            # 新文档，所有分块都需要嵌入
            chunks_to_embed = chunks
            added_hashes = set(new_chunk_hashes)
            removed_hashes: set[str] = set()

        # 生成 Embedding
        if chunks_to_embed:
            logger.info("开始生成 Embedding", chunk_count=len(chunks_to_embed))
            texts = [c.text for c in chunks_to_embed]
            embeddings = self._embedding.embed_batch(texts)

            # 将 Embedding 附加到 Chunk
            chunks_with_embedding: list[Chunk] = []
            for chunk, embedding in zip(chunks_to_embed, embeddings):
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

        # 删除旧的被移除的分块
        if removed_hashes and old_fingerprint:
            # 删除旧文档的所有分块
            self._qdrant.delete_document(kb_name, doc_id)

            # 重新嵌入所有分块
            logger.info("重新嵌入所有分块", chunk_count=len(chunks))
            texts = [c.text for c in chunks]
            embeddings = self._embedding.embed_batch(texts)

            all_chunks_with_embedding = [
                Chunk(id=c.id, text=c.text, embedding=e, metadata=c.metadata)
                for c, e in zip(chunks, embeddings)
            ]
            self._qdrant.upsert_chunks(kb_name, all_chunks_with_embedding)

        # 更新指纹
        new_fingerprint = DocumentFingerprint(
            doc_id=doc_id,
            file_path=file_path,
            file_hash=current_hash,
            chunk_hashes=new_chunk_hashes,
            indexed_at=datetime.now(timezone.utc),
        )
        await self._save_fingerprint(kb_name, new_fingerprint)

        # 更新注册表
        await self._registry.add_document(
            kb_name=kb_name,
            doc_id=doc_id,
            file_path=file_path,
            file_name=path.name,
            file_format=ext,
            chunk_count=len(chunks),
        )

        action = "updated" if old_fingerprint else "created"
        result = UpdateResult(
            doc_id=doc_id,
            action=action,
            chunks_added=len(added_hashes),
            chunks_removed=len(removed_hashes),
            message=f"文档{action}，共 {len(chunks)} 个分块",
        )

        logger.info(
            "文档更新完成",
            kb=kb_name,
            doc_id=doc_id,
            action=action,
            chunks=len(chunks),
        )

        return result

    async def remove_document(self, kb_name: str, doc_id: str) -> UpdateResult:
        """删除文档索引

        Args:
            kb_name: 知识库名称
            doc_id: 文档 ID

        Returns:
            删除结果
        """
        # 从 Qdrant 删除分块
        self._qdrant.delete_document(kb_name, doc_id)

        # 从指纹数据库删除
        await self._delete_fingerprint(kb_name, doc_id)

        # 从注册表删除
        deleted = await self._registry.delete_document(kb_name, doc_id)

        if deleted:
            logger.info("文档已删除", kb=kb_name, doc_id=doc_id)
            return UpdateResult(
                doc_id=doc_id,
                action="deleted",
                message="文档已成功删除",
            )
        else:
            logger.warning("文档不存在", kb=kb_name, doc_id=doc_id)
            return UpdateResult(
                doc_id=doc_id,
                action="deleted",
                message="文档不存在或已被删除",
            )

    async def scan_directory(
        self,
        kb_name: str,
        directory: str,
        extensions: list[str] | None = None,
    ) -> list[UpdateResult]:
        """扫描目录并更新变更的文档

        Args:
            kb_name: 知识库名称
            directory: 目录路径
            extensions: 文件扩展名过滤（默认支持所有已注册格式）

        Returns:
            更新结果列表
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise ValueError(f"目录不存在: {directory}")

        # 默认扩展名
        if extensions is None:
            extensions = list(self._parsers.keys())

        results: list[UpdateResult] = []

        # 扫描目录中的文件
        for ext in extensions:
            for file_path in dir_path.rglob(f"*{ext}"):
                try:
                    # 检查是否有变更
                    has_changes = await self.check_changes(kb_name, str(file_path))
                    if has_changes:
                        result = await self.update_document(kb_name, str(file_path))
                        results.append(result)
                    else:
                        results.append(
                            UpdateResult(
                                doc_id="",
                                action="unchanged",
                                message=str(file_path),
                            )
                        )
                except Exception as e:
                    logger.error(
                        "处理文件失败",
                        file=str(file_path),
                        error=str(e),
                    )
                    results.append(
                        UpdateResult(
                            doc_id="",
                            action="error",
                            message=f"处理失败: {e!s}",
                        )
                    )

        # 统计
        created = sum(1 for r in results if r.action == "created")
        updated = sum(1 for r in results if r.action == "updated")
        unchanged = sum(1 for r in results if r.action == "unchanged")
        errors = sum(1 for r in results if r.action == "error")

        logger.info(
            "目录扫描完成",
            kb=kb_name,
            directory=directory,
            total=len(results),
            created=created,
            updated=updated,
            unchanged=unchanged,
            errors=errors,
        )

        return results
