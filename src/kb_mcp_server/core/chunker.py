"""文档分块器 - 滑动窗口 + 语义边界感知"""

from dataclasses import dataclass, field
from typing import Any

from ..models.chunk import Chunk, ParsedChunk


@dataclass(frozen=True)
class ChunkerConfig:
    """分块配置"""

    chunk_size: int = 512  # 每个块的目标大小 (tokens)
    chunk_overlap: int = 64  # 相邻块的重叠区域 (tokens)
    min_chunk_size: int = 100  # 低于此阈值的块合并到前一块
    separators: list[str] = field(
        default_factory=lambda: ["\n## ", "\n### ", "\n\n", "\n", ". "]
    )


class Chunker:
    """文档分块器

    使用滑动窗口策略，结合语义边界（标题、段落）进行分块。
    """

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()

    def chunk(
        self,
        parsed_chunks: list[ParsedChunk],
        kb_name: str,
        doc_id: str,
    ) -> list[Chunk]:
        """将解析后的文档片段分块

        Args:
            parsed_chunks: 解析后的文档片段列表
            kb_name: 知识库名称
            doc_id: 文档 ID

        Returns:
            分块结果列表
        """
        all_chunks: list[Chunk] = []

        for parsed in parsed_chunks:
            sub_chunks = self._split_text(parsed.text)
            for sub_text in sub_chunks:
                if len(sub_text.strip()) < self.config.min_chunk_size:
                    # 跳过过短的片段
                    continue

                chunk_id = f"{kb_name}_{doc_id}_{len(all_chunks)}"
                metadata = {
                    **parsed.metadata,
                    "kb_name": kb_name,
                    "doc_id": doc_id,
                    "chunk_index": str(len(all_chunks)),
                }

                all_chunks.append(
                    Chunk(id=chunk_id, text=sub_text.strip(), metadata=metadata)
                )

        # 更新 chunk_total
        result: list[Chunk] = []
        for chunk in all_chunks:
            metadata = {**chunk.metadata, "chunk_total": str(len(all_chunks))}
            result.append(
                Chunk(id=chunk.id, text=chunk.text, embedding=chunk.embedding, metadata=metadata)
            )

        return result

    def _split_text(self, text: str) -> list[str]:
        """使用分隔符切分文本"""
        # 尝试使用分隔符切分
        for separator in self.config.separators:
            if separator in text:
                parts = text.split(separator)
                result: list[str] = []
                current = ""

                for part in parts:
                    if not part.strip():
                        continue

                    # 如果当前累积文本 + 新部分超过 chunk_size，保存当前文本
                    if current and len(current) + len(part) > self.config.chunk_size:
                        result.append(current)
                        # 添加重叠
                        overlap_text = current[-self.config.chunk_overlap :] if len(current) > self.config.chunk_overlap else ""
                        current = overlap_text + separator + part
                    else:
                        if current:
                            current += separator + part
                        else:
                            current = part

                if current.strip():
                    result.append(current)

                return result

        # 如果没有找到分隔符，使用滑动窗口
        return self._sliding_window(text)

    def _sliding_window(self, text: str) -> list[str]:
        """滑动窗口切分"""
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + self.config.chunk_size

            if end >= len(text):
                chunks.append(text[start:])
                break

            # 尝试在词边界切分
            last_space = text.rfind(" ", start, end)
            if last_space > start:
                end = last_space

            chunks.append(text[start:end])
            start = end - self.config.chunk_overlap

        return chunks
