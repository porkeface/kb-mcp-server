"""Knowledge Base MCP Server 入口"""

import asyncio
import sys

import structlog

from .config import settings
from .core.kb_manager import KBManager
from .embedding.openai_provider import OpenAIEmbedding
from .embedding.fastembed_provider import FastEmbedEmbedding
from .mcp.server import mcp
from .mcp.tools import register_tools, set_kb_manager

logger = structlog.get_logger()


def create_embedding_provider():
    """根据配置创建 Embedding 提供商"""
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("使用 OpenAI Embedding 时必须设置 OPENAI_API_KEY")
        return OpenAIEmbedding(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    elif settings.embedding_provider == "fastembed":
        return FastEmbedEmbedding(model_name=settings.embedding_model)
    else:
        raise ValueError(f"不支持的 Embedding 提供商: {settings.embedding_provider}")


async def async_main() -> None:
    """异步主函数"""
    # 确保数据目录存在
    settings.ensure_dirs()

    # 配置日志
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger.info(
        "启动 Knowledge Base MCP Server",
        transport=settings.kb_mcp_transport,
        data_dir=str(settings.kb_mcp_data_dir),
    )

    # 创建 Embedding 提供商
    embedding_provider = create_embedding_provider()
    logger.info(
        "Embedding 提供商初始化完成",
        provider=settings.embedding_provider,
        model=embedding_provider.model_name,
        dimension=embedding_provider.dimension,
    )

    # 创建 KBManager
    kb_manager = KBManager(
        settings=settings,
        embedding_provider=embedding_provider,
    )
    await kb_manager.initialize()

    # 设置全局 KBManager
    set_kb_manager(kb_manager)

    # 注册 Tools
    register_tools()

    logger.info("MCP Server 准备就绪，等待连接...")

    # 运行 MCP Server
    if settings.kb_mcp_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # Streamable HTTP 模式
        mcp.run(transport="streamable-http")


def main() -> None:
    """主函数"""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error("启动失败", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
