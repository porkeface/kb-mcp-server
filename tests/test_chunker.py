"""分块器测试"""

import pytest

from kb_mcp_server.core.chunker import Chunker, ChunkerConfig
from kb_mcp_server.parsers.base import ParsedChunk


class TestChunker:
    """分块器测试类"""

    def test_basic_chunking(self):
        """测试基本分块功能"""
        chunker = Chunker(ChunkerConfig(chunk_size=100, chunk_overlap=20))

        parsed = [
            ParsedChunk(
                text="这是一段测试文本，用于验证分块器的基本功能。" * 10,
                metadata={"source": "test.md", "format": "markdown"},
            )
        ]

        chunks = chunker.chunk(parsed, kb_name="test_kb", doc_id="doc1")

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.id.startswith("test_kb_doc1_")
            assert "kb_name" in chunk.metadata
            assert chunk.metadata["kb_name"] == "test_kb"

    def test_chunk_id_generation(self):
        """测试分块 ID 生成"""
        chunker = Chunker(ChunkerConfig(min_chunk_size=1))

        parsed = [
            ParsedChunk(text="测试内容", metadata={})
        ]

        chunks = chunker.chunk(parsed, kb_name="my_kb", doc_id="abc123")

        assert len(chunks) == 1
        assert chunks[0].id == "my_kb_abc123_0"

    def test_metadata_inheritance(self):
        """测试元数据继承"""
        chunker = Chunker(ChunkerConfig(min_chunk_size=1))

        parsed = [
            ParsedChunk(
                text="测试内容",
                metadata={"source": "test.md", "section": "概述"},
            )
        ]

        chunks = chunker.chunk(parsed, kb_name="test_kb", doc_id="doc1")

        assert len(chunks) == 1
        assert chunks[0].metadata["source"] == "test.md"
        assert chunks[0].metadata["section"] == "概述"
        assert "chunk_index" in chunks[0].metadata
        assert "chunk_total" in chunks[0].metadata

    def test_separator_splitting(self):
        """测试按分隔符切分"""
        chunker = Chunker(ChunkerConfig(chunk_size=50, chunk_overlap=10, min_chunk_size=10))

        text = "## 标题一\n\n内容一\n\n## 标题二\n\n内容二"
        parsed = [ParsedChunk(text=text, metadata={})]

        chunks = chunker.chunk(parsed, kb_name="test_kb", doc_id="doc1")

        assert len(chunks) >= 1

    def test_min_chunk_size(self):
        """测试最小分块大小"""
        chunker = Chunker(ChunkerConfig(chunk_size=100, min_chunk_size=50))

        parsed = [
            ParsedChunk(text="短", metadata={}),  # 低于最小大小
            ParsedChunk(text="这是一段足够长的测试文本，应该被保留。", metadata={}),
        ]

        chunks = chunker.chunk(parsed, kb_name="test_kb", doc_id="doc1")

        # 短文本应该被跳过
        for chunk in chunks:
            assert len(chunk.text) >= 50 or "足够长" in chunk.text

    def test_empty_input(self):
        """测试空输入"""
        chunker = Chunker()

        chunks = chunker.chunk([], kb_name="test_kb", doc_id="doc1")

        assert chunks == []

    def test_chunk_total_metadata(self):
        """测试 chunk_total 元数据"""
        chunker = Chunker(ChunkerConfig(chunk_size=20, chunk_overlap=5))

        text = "A" * 100  # 应该被分成多个块
        parsed = [ParsedChunk(text=text, metadata={})]

        chunks = chunker.chunk(parsed, kb_name="test_kb", doc_id="doc1")

        for chunk in chunks:
            assert chunk.metadata["chunk_total"] == str(len(chunks))
