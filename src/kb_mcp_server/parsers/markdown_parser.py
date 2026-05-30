"""Markdown 文档解析器"""

from pathlib import Path
from typing import Sequence

from .base import ParsedChunk


class MarkdownParser:
    """Markdown 文档解析器

    保留标题层级结构，按段落和标题切分文档。
    """

    @property
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名"""
        return [".md", ".markdown"]

    def parse(self, file_path: str) -> Sequence[ParsedChunk]:
        """解析 Markdown 文档

        Args:
            file_path: 文件绝对路径

        Returns:
            解析后的文本片段列表

        Raises:
            FileNotFoundError: 文件不存在
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        content = path.read_text(encoding="utf-8")
        source = path.name

        return self._parse_content(content, source)

    def _parse_content(self, content: str, source: str) -> list[ParsedChunk]:
        """解析 Markdown 内容"""
        chunks: list[ParsedChunk] = []
        current_section = ""
        current_subsection = ""
        current_text: list[str] = []

        for line in content.split("\n"):
            # 检测标题
            if line.startswith("# "):
                # 保存之前的文本
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        chunks.append(self._make_chunk(text, source, current_section, current_subsection))
                    current_text = []

                current_section = line[2:].strip()
                current_subsection = ""
                current_text.append(line)

            elif line.startswith("## "):
                # 保存之前的文本
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        chunks.append(self._make_chunk(text, source, current_section, current_subsection))
                    current_text = []

                current_subsection = line[3:].strip()
                current_text.append(line)

            elif line.startswith("### "):
                # ### 标题作为当前段落的一部分
                current_text.append(line)

            else:
                # 普通文本行
                current_text.append(line)

        # 保存最后一段
        if current_text:
            text = "\n".join(current_text).strip()
            if text:
                chunks.append(self._make_chunk(text, source, current_section, current_subsection))

        return chunks

    def _make_chunk(
        self, text: str, source: str, section: str, subsection: str
    ) -> ParsedChunk:
        """创建解析片段"""
        metadata: dict[str, str] = {
            "source": source,
            "format": "markdown",
            "section": section,
        }
        if subsection:
            metadata["subsection"] = subsection

        return ParsedChunk(text=text, metadata=metadata)
