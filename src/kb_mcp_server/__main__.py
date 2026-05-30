"""Knowledge Base MCP Server 入口"""

import asyncio
import sys

import structlog
import uvicorn

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
            base_url=settings.embedding_base_url,
        )
    elif settings.embedding_provider == "fastembed":
        # FastEmbed 使用本地模型，不支持 OpenAI 模型名
        model = settings.embedding_model
        if model.startswith("text-embedding"):
            model = "BAAI/bge-small-en-v1.5"
        return FastEmbedEmbedding(model_name=model)
    else:
        raise ValueError(f"不支持的 Embedding 提供商: {settings.embedding_provider}")


def _configure_logging() -> None:
    """配置 structlog 日志"""
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


async def _init_kb_manager() -> KBManager:
    """初始化 KBManager 实例"""
    settings.ensure_dirs()

    embedding_provider = create_embedding_provider()
    logger.info(
        "Embedding 提供商初始化完成",
        provider=settings.embedding_provider,
        model=embedding_provider.model_name,
        dimension=embedding_provider.dimension,
    )

    kb_manager = KBManager(
        settings=settings,
        embedding_provider=embedding_provider,
    )
    await kb_manager.initialize()
    return kb_manager


def _run_stdio(mcp_instance) -> None:
    """以 stdio 模式运行 MCP Server"""
    logger.info("MCP Server 以 stdio 模式启动")
    mcp_instance.run(transport="stdio")


def _run_streamable_http(mcp_instance) -> None:
    """以 streamable-http 模式运行 MCP Server"""
    logger.info(
        "MCP Server 以 streamable-http 模式启动",
        host=settings.kb_mcp_host,
        port=settings.kb_mcp_http_port,
    )
    mcp_instance.run(transport="streamable-http")


def _run_fastapi_server() -> None:
    """运行 FastAPI 管理 API 服务"""
    logger.info(
        "FastAPI 管理 API 启动",
        host=settings.kb_mcp_host,
        port=settings.kb_mcp_port,
    )
    uvicorn.run(
        "kb_mcp_server.api.app:app",
        host=settings.kb_mcp_host,
        port=settings.kb_mcp_port,
        log_level=settings.kb_mcp_log_level.lower(),
        reload=False,
    )


async def async_init() -> None:
    """异步初始化"""
    _configure_logging()

    logger.info(
        "启动 Knowledge Base MCP Server",
        transport=settings.kb_mcp_transport,
        data_dir=str(settings.kb_mcp_data_dir),
    )

    # 初始化 KBManager
    kb_manager = await _init_kb_manager()

    # 设置全局 KBManager（MCP Tools 和 FastAPI 都使用）
    set_kb_manager(kb_manager)

    # 注册 MCP Tools
    register_tools()
    logger.info("MCP Tools 已注册")


def main() -> None:
    """主函数"""
    try:
        # 先异步初始化
        asyncio.run(async_init())

        # 根据传输模式运行
        if settings.kb_mcp_transport == "stdio":
            _run_stdio(mcp)
        elif settings.kb_mcp_transport == "streamable-http":
            import threading

            # 在后台线程运行 FastAPI
            fastapi_thread = threading.Thread(target=_run_fastapi_server, daemon=True)
            fastapi_thread.start()

            # 主线程运行 MCP Server
            _run_streamable_http(mcp)
        else:
            raise ValueError(f"不支持的传输方式: {settings.kb_mcp_transport}")
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error("启动失败", error=str(e))
        sys.exit(1)




if __name__ == "__main__":
    main()
