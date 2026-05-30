"""测试配置"""

import pytest
from pathlib import Path
import tempfile
import shutil

from kb_mcp_server.parsers.base import ParsedChunk
from kb_mcp_server.models.chunk import Chunk


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_markdown_content():
    """示例 Markdown 内容"""
    return """# 测试文档

## 第一章 概述

这是第一章的内容。包含一些测试文本。

### 1.1 背景

这是背景介绍部分。

## 第二章 详细说明

这是第二章的内容。

### 2.1 技术方案

技术方案的详细描述。
"""


@pytest.fixture
def sample_text_content():
    """示例纯文本内容"""
    return """这是第一段内容。

这是第二段内容。

这是第三段内容。
"""


@pytest.fixture
def sample_parsed_chunks():
    """示例解析后的文档片段"""
    return [
        ParsedChunk(
            text="# 测试文档\n\n## 第一章 概述\n\n这是第一章的内容。",
            metadata={"source": "test.md", "format": "markdown", "section": "第一章 概述"},
        ),
        ParsedChunk(
            text="## 第二章 详细说明\n\n这是第二章的内容。",
            metadata={"source": "test.md", "format": "markdown", "section": "第二章 详细说明"},
        ),
    ]


@pytest.fixture
def sample_chunks():
    """示例分块结果"""
    return [
        Chunk(
            id="test_kb_doc1_0",
            text="这是第一个分块的内容。",
            embedding=[0.1, 0.2, 0.3],
            metadata={"kb_name": "test_kb", "doc_id": "doc1", "chunk_index": "0"},
        ),
        Chunk(
            id="test_kb_doc1_1",
            text="这是第二个分块的内容。",
            embedding=[0.4, 0.5, 0.6],
            metadata={"kb_name": "test_kb", "doc_id": "doc1", "chunk_index": "1"},
        ),
    ]
