"""PDF 文档解析器"""

from pathlib import Path
from typing import Sequence

from .base import ParsedChunk


class PdfParser:
    """PDF 文档解析器

    使用 PyMuPDF (fitz) 解析 PDF，保留页码信息。
    """

    @property
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名"""
        return [".pdf"]

    def parse(self, file_path: str) -> Sequence[ParsedChunk]:
        """解析 PDF 文档

        Args:
            file_path: 文件绝对路径

        Returns:
            解析后的文本片段列表

        Raises:
            FileNotFoundError: 文件不存在
            ImportError: PyMuPDF 未安装
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            import importlib.util
            if importlib.util.find_spec("fitz") is None:
                raise ImportError("PyMuPDF 未安装")
        except ImportError:
            raise ImportError("需要安装 PyMuPDF: uv add pymupdf")

        return self._parse_pdf(path)

    def _parse_pdf(self, path: Path) -> list[ParsedChunk]:
        """解析 PDF 文件"""
        import fitz

        chunks: list[ParsedChunk] = []
        source = path.name

        with fitz.open(str(path)) as doc:
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text")

                if not text.strip():
                    continue

                # 按段落切分页面内容
                paragraphs = text.split("\n\n")

                for para_idx, paragraph in enumerate(paragraphs):
                    text = paragraph.strip()
                    if not text:
                        continue

                    metadata: dict[str, str] = {
                        "source": source,
                        "format": "pdf",
                        "page": str(page_num + 1),
                        "paragraph_index": str(para_idx),
                    }

                    chunks.append(ParsedChunk(text=text, metadata=metadata))

        return chunks
