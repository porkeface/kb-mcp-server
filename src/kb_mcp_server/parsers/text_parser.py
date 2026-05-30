"""纯文本文档解析器"""

from pathlib import Path
from typing import Sequence

from .base import ParsedChunk


class TextParser:
    """纯文本文档解析器

    按段落（空行分隔）切分文档。
    """

    @property
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名"""
        return [".txt", ".text"]

    def parse(self, file_path: str) -> Sequence[ParsedChunk]:
        """解析纯文本文档

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
        """解析纯文本内容，按段落切分"""
        chunks: list[ParsedChunk] = []

        # 按空行切分段落
        paragraphs = content.split("\n\n")

        for i, paragraph in enumerate(paragraphs):
            text = paragraph.strip()
            if not text:
                continue

            metadata: dict[str, str] = {
                "source": source,
                "format": "text",
                "paragraph_index": str(i),
            }

            chunks.append(ParsedChunk(text=text, metadata=metadata))

        return chunks
