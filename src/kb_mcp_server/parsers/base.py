"""文档解析器协议"""

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class ParsedChunk:
    """解析后的文档片段"""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 包含: source, page, section_title, format 等


class DocumentParser(Protocol):
    """文档解析器协议"""

    def parse(self, file_path: str) -> Sequence[ParsedChunk]:
        """解析文档，返回文本片段列表

        Args:
            file_path: 文件绝对路径

        Returns:
            解析后的文本片段列表

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件格式
        """
        ...

    @property
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名列表"""
        ...
