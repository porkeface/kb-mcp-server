"""SQLite 元数据注册表"""

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import structlog

from ..models.knowledge_base import KnowledgeBaseInfo

logger = structlog.get_logger()

# SQL 建表语句
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    name        TEXT PRIMARY KEY,
    description TEXT DEFAULT '',
    embedding_provider TEXT DEFAULT 'openai',
    embedding_model    TEXT DEFAULT 'text-embedding-3-small',
    embedding_dimension INTEGER DEFAULT 1536,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    kb_name     TEXT NOT NULL,
    file_path   TEXT,
    file_name   TEXT,
    file_format TEXT,
    chunk_count INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'indexed',
    indexed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (kb_name) REFERENCES knowledge_bases(name) ON DELETE CASCADE
);
"""


class Registry:
    """知识库元数据注册表

    使用 SQLite 存储知识库和文档的元数据。
    """

    def __init__(self, db_path: Path) -> None:
        """初始化注册表

        Args:
            db_path: SQLite 数据库文件路径
        """
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """初始化数据库表"""
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(CREATE_TABLES_SQL)
            await db.commit()
        logger.info("注册表初始化完成", path=str(self._db_path))

    async def create_kb(
        self,
        name: str,
        description: str = "",
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        embedding_dimension: int = 1536,
    ) -> KnowledgeBaseInfo:
        """创建知识库记录

        Args:
            name: 知识库名称
            description: 描述
            embedding_provider: Embedding 提供商
            embedding_model: Embedding 模型
            embedding_dimension: 向量维度

        Returns:
            创建的知识库信息
        """
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT INTO knowledge_bases
                    (name, description, embedding_provider, embedding_model, embedding_dimension, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, description, embedding_provider, embedding_model, embedding_dimension, now, now),
            )
            await db.commit()

        logger.info("知识库记录已创建", name=name)

        return KnowledgeBaseInfo(
            name=name,
            description=description,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            created_at=now,
            updated_at=now,
        )

    async def get_kb(self, name: str) -> KnowledgeBaseInfo | None:
        """获取知识库信息

        Args:
            name: 知识库名称

        Returns:
            知识库信息，不存在返回 None
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM knowledge_bases WHERE name = ?", (name,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            # 获取文档数量
            doc_cursor = await db.execute(
                "SELECT COUNT(*) as count FROM documents WHERE kb_name = ?", (name,)
            )
            doc_row = await doc_cursor.fetchone()
            doc_count = doc_row[0] if doc_row else 0

            # 获取分块总数
            chunk_cursor = await db.execute(
                "SELECT COALESCE(SUM(chunk_count), 0) as total FROM documents WHERE kb_name = ?",
                (name,),
            )
            chunk_row = await chunk_cursor.fetchone()
            chunk_count = chunk_row[0] if chunk_row else 0

            return KnowledgeBaseInfo(
                name=row["name"],
                description=row["description"],
                embedding_provider=row["embedding_provider"],
                embedding_model=row["embedding_model"],
                embedding_dimension=row["embedding_dimension"],
                document_count=doc_count,
                chunk_count=chunk_count,
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )

    async def list_kbs(self) -> list[KnowledgeBaseInfo]:
        """列出所有知识库

        Returns:
            知识库信息列表
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC")
            rows = await cursor.fetchall()

            result: list[KnowledgeBaseInfo] = []
            for row in rows:
                # 获取文档数量
                doc_cursor = await db.execute(
                    "SELECT COUNT(*) as count FROM documents WHERE kb_name = ?",
                    (row["name"],),
                )
                doc_row = await doc_cursor.fetchone()
                doc_count = doc_row[0] if doc_row else 0

                # 获取分块总数
                chunk_cursor = await db.execute(
                    "SELECT COALESCE(SUM(chunk_count), 0) as total FROM documents WHERE kb_name = ?",
                    (row["name"],),
                )
                chunk_row = await chunk_cursor.fetchone()
                chunk_count = chunk_row[0] if chunk_row else 0

                result.append(
                    KnowledgeBaseInfo(
                        name=row["name"],
                        description=row["description"],
                        embedding_provider=row["embedding_provider"],
                        embedding_model=row["embedding_model"],
                        embedding_dimension=row["embedding_dimension"],
                        document_count=doc_count,
                        chunk_count=chunk_count,
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                    )
                )

            return result

    async def delete_kb(self, name: str) -> bool:
        """删除知识库记录

        Args:
            name: 知识库名称

        Returns:
            是否删除成功
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            # 先删除关联的文档
            await db.execute("DELETE FROM documents WHERE kb_name = ?", (name,))
            # 删除知识库
            cursor = await db.execute("DELETE FROM knowledge_bases WHERE name = ?", (name,))
            await db.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("知识库记录已删除", name=name)

            return deleted

    async def add_document(
        self,
        kb_name: str,
        doc_id: str,
        file_path: str,
        file_name: str,
        file_format: str,
        chunk_count: int,
    ) -> None:
        """添加文档记录

        Args:
            kb_name: 知识库名称
            doc_id: 文档 ID
            file_path: 文件路径
            file_name: 文件名
            file_format: 文件格式
            chunk_count: 分块数量
        """
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT INTO documents (id, kb_name, file_path, file_name, file_format, chunk_count, status, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, 'indexed', ?)
                """,
                (doc_id, kb_name, file_path, file_name, file_format, chunk_count, now),
            )
            # 更新知识库的 updated_at
            await db.execute(
                "UPDATE knowledge_bases SET updated_at = ? WHERE name = ?",
                (now, kb_name),
            )
            await db.commit()

        logger.info("文档记录已添加", kb_name=kb_name, doc_id=doc_id, chunk_count=chunk_count)

    async def delete_document(self, kb_name: str, doc_id: str) -> bool:
        """删除文档记录

        Args:
            kb_name: 知识库名称
            doc_id: 文档 ID

        Returns:
            是否删除成功
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            cursor = await db.execute(
                "DELETE FROM documents WHERE id = ? AND kb_name = ?",
                (doc_id, kb_name),
            )
            await db.commit()

            return cursor.rowcount > 0
