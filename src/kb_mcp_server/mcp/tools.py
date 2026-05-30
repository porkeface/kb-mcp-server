"""MCP Tools 实现"""

from typing import Any

import structlog

from .server import mcp

logger = structlog.get_logger()

# 全局 KBManager 实例（在启动时初始化）
_kb_manager = None


def set_kb_manager(manager: Any) -> None:
    """设置 KBManager 实例"""
    global _kb_manager
    _kb_manager = manager


def _get_manager() -> Any:
    """获取 KBManager 实例"""
    if _kb_manager is None:
        raise RuntimeError("KBManager 未初始化，请先调用 set_kb_manager")
    return _kb_manager


# ──────────────────────────────────────────────
# 检索类 Tools
# ──────────────────────────────────────────────


@mcp.tool()
async def kb_search(
    kb_name: str,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """在指定知识库中进行语义搜索。

    使用向量相似度匹配，返回与查询语义最相关的知识片段。
    适用于：查找概念解释、术语定义、相关文档段落。

    Args:
        kb_name: 知识库名称，可通过 kb_list 查看可用知识库
        query: 搜索查询，用自然语言描述要查找的内容
        top_k: 返回结果数量，默认5，最大20

    Returns:
        包含 text, score, source, metadata 的结果列表
    """
    manager = _get_manager()

    # 参数校验
    top_k = max(1, min(top_k, 20))

    results = await manager.search(
        kb_name=kb_name,
        query=query,
        top_k=top_k,
    )

    return [
        {
            "text": r.text,
            "score": round(r.score, 4),
            "source": r.source,
            "metadata": r.metadata,
        }
        for r in results
    ]


# ──────────────────────────────────────────────
# 管理类 Tools
# ──────────────────────────────────────────────


@mcp.tool()
async def kb_list() -> list[dict[str, Any]]:
    """列出所有已创建的知识库。

    Returns:
        知识库列表，每项包含 name, description, document_count, chunk_count, created_at
    """
    manager = _get_manager()
    kbs = await manager.list_kbs()

    return [
        {
            "name": kb.name,
            "description": kb.description,
            "document_count": kb.document_count,
            "chunk_count": kb.chunk_count,
            "embedding_model": kb.embedding_model,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
        }
        for kb in kbs
    ]


@mcp.tool()
async def kb_create(
    name: str,
    description: str = "",
) -> dict[str, Any]:
    """创建一个新的知识库。

    会同时在 Qdrant 中创建对应的向量存储空间。
    每个知识库完全隔离，互不影响。

    Args:
        name: 知识库名称 (小写字母+下划线, 如 "yijing")
        description: 知识库描述

    Returns:
        创建结果，包含知识库信息
    """
    manager = _get_manager()

    # 名称校验
    if not name.isascii() or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError("知识库名称只能包含英文字母、数字和下划线")

    kb_info = await manager.create_kb(name=name, description=description)

    return {
        "success": True,
        "message": f"知识库 '{name}' 创建成功",
        "kb": {
            "name": kb_info.name,
            "description": kb_info.description,
            "embedding_model": kb_info.embedding_model,
            "embedding_dimension": kb_info.embedding_dimension,
            "created_at": kb_info.created_at.isoformat() if kb_info.created_at else None,
        },
    }


@mcp.tool()
async def kb_info(kb_name: str) -> dict[str, Any]:
    """获取知识库的详细信息。

    Args:
        kb_name: 知识库名称

    Returns:
        包含 name, description, document_count, chunk_count,
        embedding_model, created_at, last_updated 的详情
    """
    manager = _get_manager()

    kb_info = await manager.get_kb_info(kb_name)
    if not kb_info:
        raise ValueError(f"知识库 '{kb_name}' 不存在")

    result: dict[str, Any] = {
        "name": kb_info.name,
        "description": kb_info.description,
        "document_count": kb_info.document_count,
        "chunk_count": kb_info.chunk_count,
        "embedding_provider": kb_info.embedding_provider,
        "embedding_model": kb_info.embedding_model,
        "embedding_dimension": kb_info.embedding_dimension,
        "created_at": kb_info.created_at.isoformat() if kb_info.created_at else None,
        "updated_at": kb_info.updated_at.isoformat() if kb_info.updated_at else None,
    }

    # 添加 Qdrant 信息
    if "qdrant_points" in kb_info.extra:
        result["qdrant_points"] = kb_info.extra["qdrant_points"]
        result["qdrant_status"] = kb_info.extra["qdrant_status"]

    return result


@mcp.tool()
async def kb_delete(
    kb_name: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """删除知识库及其所有数据（不可恢复）。

    Args:
        kb_name: 知识库名称
        confirm: 确认删除，必须为 True 才能执行

    Returns:
        删除结果
    """
    manager = _get_manager()

    if not confirm:
        return {
            "success": False,
            "message": "必须设置 confirm=True 才能删除知识库。此操作不可恢复！",
        }

    result = await manager.delete_kb(name=kb_name, confirm=True)
    return result


# ──────────────────────────────────────────────
# 数据类 Tools
# ──────────────────────────────────────────────


@mcp.tool()
async def kb_ingest(
    kb_name: str,
    file_path: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> dict[str, Any]:
    """将文档导入知识库。

    支持的格式：.md, .txt, .pdf
    流程：解析 -> 分块 -> Embedding -> 存入 Qdrant

    Args:
        kb_name: 知识库名称
        file_path: 文件路径 (绝对路径)
        chunk_size: 分块大小 (tokens)，默认512
        chunk_overlap: 块重叠 (tokens)，默认64

    Returns:
        导入结果，包含 doc_id, chunk_count
    """
    manager = _get_manager()

    result = await manager.ingest(
        kb_name=kb_name,
        file_path=file_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    return result


def register_tools() -> None:
    """注册所有 MCP Tools

    注意：Tools 通过 @mcp.tool() 装饰器自动注册，
    此函数主要用于触发模块加载。
    """
    logger.info("MCP Tools 已注册")
