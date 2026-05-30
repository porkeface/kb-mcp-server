"""MCP Tools 测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kb_mcp_server.models.knowledge_base import KnowledgeBaseInfo
from kb_mcp_server.models.search import SearchResult


class TestMCPTools:
    """MCP Tools 测试类"""

    @pytest.fixture
    def mock_manager(self):
        """创建模拟的 KBManager"""
        manager = AsyncMock()
        return manager

    @pytest.mark.asyncio
    async def test_kb_list_empty(self, mock_manager):
        """测试列出空知识库"""
        mock_manager.list_kbs.return_value = []

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_list
            result = await kb_list()

        assert result == []

    @pytest.mark.asyncio
    async def test_kb_list_with_kbs(self, mock_manager):
        """测试列出知识库"""
        from datetime import datetime

        mock_manager.list_kbs.return_value = [
            KnowledgeBaseInfo(
                name="yijing",
                description="易经知识库",
                document_count=5,
                chunk_count=100,
                embedding_model="text-embedding-3-small",
                created_at=datetime(2026, 1, 1),
            ),
            KnowledgeBaseInfo(
                name="finance",
                description="金融知识库",
                document_count=3,
                chunk_count=50,
                embedding_model="text-embedding-3-small",
                created_at=datetime(2026, 1, 2),
            ),
        ]

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_list
            result = await kb_list()

        assert len(result) == 2
        assert result[0]["name"] == "yijing"
        assert result[0]["document_count"] == 5
        assert result[1]["name"] == "finance"

    @pytest.mark.asyncio
    async def test_kb_create(self, mock_manager):
        """测试创建知识库"""
        from datetime import datetime

        mock_manager.create_kb.return_value = KnowledgeBaseInfo(
            name="test_kb",
            description="测试知识库",
            embedding_model="text-embedding-3-small",
            embedding_dimension=1536,
            created_at=datetime(2026, 1, 1),
        )

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_create
            result = await kb_create(name="test_kb", description="测试知识库")

        assert result["success"] is True
        assert result["kb"]["name"] == "test_kb"

    @pytest.mark.asyncio
    async def test_kb_create_invalid_name(self, mock_manager):
        """测试创建知识库 - 无效名称"""
        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_create

            with pytest.raises(ValueError, match="只能包含"):
                await kb_create(name="invalid-name!")

    @pytest.mark.asyncio
    async def test_kb_search(self, mock_manager):
        """测试语义搜索"""
        mock_manager.search.return_value = [
            SearchResult(
                text="乾卦：元亨利贞",
                score=0.95,
                source="vector",
                metadata={"doc_id": "doc1", "section": "乾卦"},
            ),
            SearchResult(
                text="坤卦：利牝马之贞",
                score=0.85,
                source="vector",
                metadata={"doc_id": "doc1", "section": "坤卦"},
            ),
        ]

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_search
            result = await kb_search(kb_name="yijing", query="乾卦", top_k=5)

        assert len(result) == 2
        assert result[0]["text"] == "乾卦：元亨利贞"
        assert result[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_kb_delete_without_confirm(self, mock_manager):
        """测试删除知识库 - 未确认"""
        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_delete
            result = await kb_delete(kb_name="test_kb", confirm=False)

        assert result["success"] is False
        assert "confirm=True" in result["message"]

    @pytest.mark.asyncio
    async def test_kb_delete_with_confirm(self, mock_manager):
        """测试删除知识库 - 已确认"""
        mock_manager.delete_kb.return_value = {"success": True, "message": "已删除"}

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_delete
            result = await kb_delete(kb_name="test_kb", confirm=True)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_kb_ingest(self, mock_manager):
        """测试文档导入"""
        mock_manager.ingest.return_value = {
            "doc_id": "abc123",
            "chunk_count": 10,
            "file_name": "test.md",
            "message": "导入成功",
        }

        with patch("kb_mcp_server.mcp.tools._kb_manager", mock_manager):
            from kb_mcp_server.mcp.tools import kb_ingest
            result = await kb_ingest(
                kb_name="test_kb",
                file_path="/path/to/test.md",
            )

        assert result["doc_id"] == "abc123"
        assert result["chunk_count"] == 10
