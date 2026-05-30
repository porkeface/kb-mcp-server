"""解析器测试"""

import pytest
from pathlib import Path

from kb_mcp_server.parsers.markdown_parser import MarkdownParser
from kb_mcp_server.parsers.text_parser import TextParser


class TestMarkdownParser:
    """Markdown 解析器测试类"""

    def test_supported_extensions(self):
        """测试支持的扩展名"""
        parser = MarkdownParser()
        assert ".md" in parser.supported_extensions
        assert ".markdown" in parser.supported_extensions

    def test_parse_basic(self, temp_dir, sample_markdown_content):
        """测试基本解析功能"""
        # 创建测试文件
        test_file = temp_dir / "test.md"
        test_file.write_text(sample_markdown_content, encoding="utf-8")

        parser = MarkdownParser()
        chunks = parser.parse(str(test_file))

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.text
            assert chunk.metadata["source"] == "test.md"
            assert chunk.metadata["format"] == "markdown"

    def test_section_metadata(self, temp_dir):
        """测试章节元数据"""
        content = "# 主标题\n\n## 第一节\n\n内容一\n\n## 第二节\n\n内容二"
        test_file = temp_dir / "test.md"
        test_file.write_text(content, encoding="utf-8")

        parser = MarkdownParser()
        chunks = parser.parse(str(test_file))

        # 应该有至少两个块（按 ## 切分）
        # section 来自 # 标题，subsection 来自 ## 标题
        subsections = [c.metadata.get("subsection") for c in chunks]
        assert any("第一节" in s for s in subsections if s)
        assert any("第二节" in s for s in subsections if s)

    def test_file_not_found(self):
        """测试文件不存在"""
        parser = MarkdownParser()

        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.md")


class TestTextParser:
    """纯文本解析器测试类"""

    def test_supported_extensions(self):
        """测试支持的扩展名"""
        parser = TextParser()
        assert ".txt" in parser.supported_extensions
        assert ".text" in parser.supported_extensions

    def test_parse_basic(self, temp_dir, sample_text_content):
        """测试基本解析功能"""
        test_file = temp_dir / "test.txt"
        test_file.write_text(sample_text_content, encoding="utf-8")

        parser = TextParser()
        chunks = parser.parse(str(test_file))

        assert len(chunks) == 3  # 三个段落
        for chunk in chunks:
            assert chunk.text
            assert chunk.metadata["source"] == "test.txt"
            assert chunk.metadata["format"] == "text"

    def test_paragraph_splitting(self, temp_dir):
        """测试段落切分"""
        content = "段落一\n\n段落二\n\n段落三"
        test_file = temp_dir / "test.txt"
        test_file.write_text(content, encoding="utf-8")

        parser = TextParser()
        chunks = parser.parse(str(test_file))

        assert len(chunks) == 3
        assert chunks[0].text == "段落一"
        assert chunks[1].text == "段落二"
        assert chunks[2].text == "段落三"

    def test_file_not_found(self):
        """测试文件不存在"""
        parser = TextParser()

        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.txt")
