"""FastAPI 管理 API - 知识库管理接口"""

import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import settings
from ..core.kb_manager import KBManager
from ..mcp.tools import _get_manager
from .config_api import router as config_router

logger = structlog.get_logger()


# ──────────────────────────────────────────────
# 依赖注入
# ──────────────────────────────────────────────


def get_kb_manager() -> KBManager:
    """获取 KBManager 实例（FastAPI 依赖注入）"""
    try:
        return _get_manager()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="KBManager 未初始化，请等待服务启动完成",
        )


# ──────────────────────────────────────────────
# 响应格式
# ──────────────────────────────────────────────


def success_response(data: Any = None, message: str = "success") -> JSONResponse:
    """成功响应格式"""
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            "data": data,
        },
    )


def error_response(status_code: int, detail: str) -> JSONResponse:
    """错误响应格式"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": detail,
            "data": None,
        },
    )


# ──────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("FastAPI 管理 API 启动")
    yield
    logger.info("FastAPI 管理 API 关闭")


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────

app = FastAPI(
    title="KB MCP Server 管理 API",
    description="知识库管理系统 API - 提供知识库的 CRUD、文档导入和语义搜索功能",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册配置管理路由
app.include_router(config_router)

# 配置热重载回调
def _reload_config():
    """重新加载配置（热重载）

    由于 Pydantic Settings 在模块加载时就读取 .env，
    热重载只能更新环境变量，下次创建新实例时才会生效。
    已创建的 KBManager 等组件不会自动更新。
    """
    import os

    # 重新读取 .env 文件到环境变量
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key:
                        os.environ[key] = value

    logger.info("配置环境变量已更新（重启后完全生效）")

from .config_api import set_reload_callback
set_reload_callback(_reload_config)


# ──────────────────────────────────────────────
# 健康检查
# ──────────────────────────────────────────────


@app.get("/health")
async def health_check() -> JSONResponse:
    """健康检查端点"""
    return success_response(
        data={
            "status": "healthy",
            "transport": settings.kb_mcp_transport,
            "data_dir": str(settings.kb_mcp_data_dir),
        },
        message="服务运行正常",
    )


@app.get("/ready")
async def readiness_check(manager: KBManager = Depends(get_kb_manager)) -> JSONResponse:
    """就绪检查端点 - 验证依赖服务是否可用"""
    try:
        await manager.list_kbs()
        return success_response(
            data={
                "status": "ready",
                "qdrant": "connected",
            },
            message="服务已就绪",
        )
    except Exception as e:
        return error_response(
            status_code=503,
            detail=f"服务未就绪: {str(e)}",
        )


# ──────────────────────────────────────────────
# 知识库管理
# ──────────────────────────────────────────────


@app.get("/api/knowledge-bases")
async def list_knowledge_bases(
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """列出所有知识库"""
    try:
        kbs = await manager.list_kbs()
        data = [
            {
                "name": kb.name,
                "description": kb.description,
                "document_count": kb.document_count,
                "chunk_count": kb.chunk_count,
                "embedding_model": kb.embedding_model,
                "created_at": kb.created_at.isoformat() if kb.created_at else None,
                "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
            }
            for kb in kbs
        ]
        return success_response(data=data, message=f"共 {len(data)} 个知识库")
    except Exception as e:
        logger.error("列出知识库失败", error=str(e))
        return error_response(status_code=500, detail=f"列出知识库失败: {str(e)}")


@app.post("/api/knowledge-bases")
async def create_knowledge_base(
    name: str = Query(..., description="知识库名称（小写字母+下划线）"),
    description: str = Query("", description="知识库描述"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """创建知识库"""
    # 名称校验
    if not name.isascii() or not all(c.isalnum() or c == "_" for c in name):
        return error_response(
            status_code=400,
            detail="知识库名称只能包含英文字母、数字和下划线",
        )

    try:
        kb_info = await manager.create_kb(name=name, description=description)
        return success_response(
            data={
                "name": kb_info.name,
                "description": kb_info.description,
                "embedding_model": kb_info.embedding_model,
                "embedding_dimension": kb_info.embedding_dimension,
                "created_at": kb_info.created_at.isoformat() if kb_info.created_at else None,
            },
            message=f"知识库 '{name}' 创建成功",
        )
    except ValueError as e:
        return error_response(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("创建知识库失败", name=name, error=str(e))
        return error_response(status_code=500, detail=f"创建知识库失败: {str(e)}")


@app.get("/api/knowledge-bases/{name}")
async def get_knowledge_base(
    name: str,
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """获取知识库详情"""
    try:
        kb_info = await manager.get_kb_info(name)
        if not kb_info:
            return error_response(status_code=404, detail=f"知识库 '{name}' 不存在")

        data: dict[str, Any] = {
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
            data["qdrant_points"] = kb_info.extra["qdrant_points"]
            data["qdrant_status"] = kb_info.extra["qdrant_status"]

        return success_response(data=data, message="获取知识库详情成功")
    except Exception as e:
        logger.error("获取知识库详情失败", name=name, error=str(e))
        return error_response(status_code=500, detail=f"获取知识库详情失败: {str(e)}")


@app.delete("/api/knowledge-bases/{name}")
async def delete_knowledge_base(
    name: str,
    confirm: bool = Query(False, description="确认删除"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """删除知识库"""
    if not confirm:
        return error_response(
            status_code=400,
            detail="必须设置 confirm=true 才能删除知识库。此操作不可恢复！",
        )

    try:
        result = await manager.delete_kb(name=name, confirm=True)
        return success_response(data=result, message=f"知识库 '{name}' 已删除")
    except ValueError as e:
        return error_response(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("删除知识库失败", name=name, error=str(e))
        return error_response(status_code=500, detail=f"删除知识库失败: {str(e)}")


# ──────────────────────────────────────────────
# 文档导入
# ──────────────────────────────────────────────


@app.post("/api/knowledge-bases/{name}/ingest")
async def ingest_document(
    name: str,
    file_path: str = Query(..., description="文件绝对路径"),
    chunk_size: int = Query(512, description="分块大小（tokens）"),
    chunk_overlap: int = Query(64, description="块重叠（tokens）"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """导入文档到知识库"""
    try:
        result = await manager.ingest(
            kb_name=name,
            file_path=file_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return success_response(
            data=result,
            message=result.get("message", "文档导入成功"),
        )
    except ValueError as e:
        return error_response(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        return error_response(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("文档导入失败", name=name, file_path=file_path, error=str(e))
        return error_response(status_code=500, detail=f"文档导入失败: {str(e)}")


# ──────────────────────────────────────────────
# 搜索
# ──────────────────────────────────────────────


@app.get("/api/knowledge-bases/{name}/search")
async def search_knowledge_base(
    name: str,
    query: str = Query(..., description="搜索查询"),
    top_k: int = Query(5, ge=1, le=20, description="返回结果数量"),
    score_threshold: float = Query(0.3, ge=0, le=1, description="最低相似度阈值"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """在知识库中进行语义搜索"""
    try:
        results = await manager.search(
            kb_name=name,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        data = [
            {
                "text": r.text,
                "score": round(r.score, 4),
                "source": r.source,
                "metadata": r.metadata,
            }
            for r in results
        ]

        return success_response(
            data=data,
            message=f"共找到 {len(data)} 条结果",
        )
    except ValueError as e:
        return error_response(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("搜索失败", name=name, query=query[:50], error=str(e))
        return error_response(status_code=500, detail=f"搜索失败: {str(e)}")


# ──────────────────────────────────────────────
# 混合搜索
# ──────────────────────────────────────────────


@app.get("/api/knowledge-bases/{name}/hybrid_search")
async def hybrid_search_knowledge_base(
    name: str,
    query: str = Query(..., description="搜索查询"),
    top_k: int = Query(10, ge=1, le=30, description="返回结果数量"),
    include_graph: bool = Query(True, description="是否包含图谱检索"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """在知识库中进行混合检索"""
    try:
        # 如果有编排器，使用混合搜索
        if hasattr(manager, '_orchestrator') and manager._orchestrator:
            results = await manager._orchestrator.hybrid_search(
                kb_name=name,
                query=query,
                max_results=top_k,
            )

            data = [
                {
                    "text": r.text,
                    "score": round(r.score, 4),
                    "source": r.source,
                    "metadata": r.metadata,
                    "sources": r.sources,
                }
                for r in results
            ]
        else:
            # 降级到普通搜索
            results = await manager.search(
                kb_name=name,
                query=query,
                top_k=top_k,
            )

            data = [
                {
                    "text": r.text,
                    "score": round(r.score, 4),
                    "source": r.source,
                    "metadata": r.metadata,
                }
                for r in results
            ]

        return success_response(
            data=data,
            message=f"共找到 {len(data)} 条结果",
        )
    except ValueError as e:
        return error_response(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("混合搜索失败", name=name, query=query[:50], error=str(e))
        return error_response(status_code=500, detail=f"混合搜索失败: {str(e)}")


# ──────────────────────────────────────────────
# 文件上传
# ──────────────────────────────────────────────


@app.post("/api/knowledge-bases/{name}/upload")
async def upload_file(
    name: str,
    file: UploadFile = File(..., description="上传的文件"),
    extract_entities: bool = Query(True, description="是否自动提取实体"),
    manager: KBManager = Depends(get_kb_manager),
) -> JSONResponse:
    """上传文件到知识库"""
    # 检查文件类型
    allowed_extensions = {".md", ".markdown", ".txt", ".text", ".pdf"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        return error_response(
            status_code=400,
            detail=f"不支持的文件格式: {file_ext}，支持: {', '.join(allowed_extensions)}",
        )

    try:
        # 保存上传的文件
        upload_dir = settings.uploads_dir / name
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名
        unique_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        file_path = upload_dir / unique_filename

        # 写入文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info("文件已上传", filename=file.filename, path=str(file_path))

        # 导入到知识库
        result = await manager.ingest(
            kb_name=name,
            file_path=str(file_path),
        )

        return success_response(
            data={
                "filename": file.filename,
                "stored_path": str(file_path),
                **result,
            },
            message=result.get("message", "文件上传并导入成功"),
        )
    except ValueError as e:
        return error_response(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        return error_response(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("文件上传失败", name=name, filename=file.filename, error=str(e))
        return error_response(status_code=500, detail=f"文件上传失败: {str(e)}")


# ──────────────────────────────────────────────
# 静态文件和 Web UI
# ──────────────────────────────────────────────

# 获取静态文件目录
static_dir = Path(__file__).parent.parent / "static"

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_ui():
    """提供 Web UI 入口"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return error_response(status_code=404, detail="Web UI 未找到")
