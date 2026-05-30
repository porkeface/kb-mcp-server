"""配置管理 API"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigResponse(BaseModel):
    """配置响应"""
    success: bool
    data: dict
    message: str = ""


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    settings: dict


# 需要隐藏的敏感字段
SENSITIVE_FIELDS = {"openai_api_key", "deepseek_api_key", "mimo_api_key", "qdrant_api_key", "neo4j_password"}


def mask_value(key: str, value: str | None) -> str | None:
    """隐藏敏感信息"""
    if value is None:
        return None
    if key in SENSITIVE_FIELDS and len(value) > 8:
        return value[:4] + "****" + value[-4:]
    return value


def get_env_path() -> Path:
    """获取 .env 文件路径"""
    return Path(__file__).parent.parent.parent.parent / ".env"


def read_env_file() -> dict:
    """读取 .env 文件"""
    env_path = get_env_path()
    config = {}

    if not env_path.exists():
        return config

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                config[key] = value

    return config


def write_env_file(config: dict) -> None:
    """写入 .env 文件"""
    env_path = get_env_path()

    # 读取现有内容作为模板
    existing_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # 构建新的内容
    new_lines = []
    updated_keys = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in config:
                value = config[key]
                new_lines.append(f"{key}={value}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

    # 添加新字段
    for key, value in config.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# 配置字段定义
CONFIG_FIELDS = [
    # Qdrant
    {"key": "QDRANT_URL", "label": "Qdrant 地址", "group": "Qdrant", "type": "text", "placeholder": "http://localhost:6333"},
    {"key": "QDRANT_API_KEY", "label": "Qdrant API Key", "group": "Qdrant", "type": "password", "placeholder": "可选", "sensitive": True},

    # Neo4j
    {"key": "NEO4J_URI", "label": "Neo4j URI", "group": "Neo4j", "type": "text", "placeholder": "bolt://localhost:7687"},
    {"key": "NEO4J_USER", "label": "Neo4j 用户名", "group": "Neo4j", "type": "text", "placeholder": "neo4j"},
    {"key": "NEO4J_PASSWORD", "label": "Neo4j 密码", "group": "Neo4j", "type": "password", "placeholder": "changeme", "sensitive": True},

    # Embedding
    {"key": "EMBEDDING_PROVIDER", "label": "Embedding 提供商", "group": "Embedding", "type": "select", "options": ["openai", "fastembed"]},
    {"key": "OPENAI_API_KEY", "label": "OpenAI API Key", "group": "Embedding", "type": "password", "placeholder": "OpenAI 或兼容 API", "sensitive": True},
    {"key": "EMBEDDING_MODEL", "label": "Embedding 模型", "group": "Embedding", "type": "text", "placeholder": "text-embedding-3-small"},
    {"key": "EMBEDDING_BASE_URL", "label": "Embedding API 地址", "group": "Embedding", "type": "text", "placeholder": "用于 DeepSeek 等兼容 API"},
    {"key": "EMBEDDING_DIMENSION", "label": "向量维度", "group": "Embedding", "type": "number", "placeholder": "自动检测"},

    # LLM 实体提取
    {"key": "KB_MCP_EXTRACT_ENTITIES", "label": "启用实体提取", "group": "LLM 实体提取", "type": "select", "options": ["true", "false"]},
    {"key": "KB_MCP_EXTRACT_LLM", "label": "LLM 提供商", "group": "LLM 实体提取", "type": "select", "options": ["openai", "deepseek", "mimo"]},
    {"key": "DEEPSEEK_API_KEY", "label": "DeepSeek API Key", "group": "LLM 实体提取", "type": "password", "placeholder": "用于实体提取", "sensitive": True},
    {"key": "MIMO_API_KEY", "label": "MIMO API Key", "group": "LLM 实体提取", "type": "password", "placeholder": "小米 MIMO", "sensitive": True},
    {"key": "MIMO_BASE_URL", "label": "MIMO API 地址", "group": "LLM 实体提取", "type": "text", "placeholder": "https://api.mimo.ai/v1"},

    # Server
    {"key": "KB_MCP_HOST", "label": "服务主机", "group": "服务配置", "type": "text", "placeholder": "127.0.0.1"},
    {"key": "KB_MCP_PORT", "label": "管理 API 端口", "group": "服务配置", "type": "number", "placeholder": "8100"},
    {"key": "KB_MCP_HTTP_PORT", "label": "MCP HTTP 端口", "group": "服务配置", "type": "number", "placeholder": "8101"},
    {"key": "KB_MCP_LOG_LEVEL", "label": "日志级别", "group": "服务配置", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
]


@router.get("/schema")
async def get_config_schema() -> dict:
    """获取配置字段定义"""
    return {
        "success": True,
        "data": {
            "fields": CONFIG_FIELDS,
            "groups": list(dict.fromkeys(f["group"] for f in CONFIG_FIELDS))
        }
    }


@router.get("")
async def get_config() -> dict:
    """获取当前配置"""
    try:
        config = read_env_file()

        # 添加默认值
        defaults = {
            "QDRANT_URL": "http://localhost:6333",
            "NEO4J_URI": "bolt://localhost:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "changeme",
            "EMBEDDING_PROVIDER": "openai",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "KB_MCP_HOST": "127.0.0.1",
            "KB_MCP_PORT": "8100",
            "KB_MCP_HTTP_PORT": "8101",
            "KB_MCP_EXTRACT_ENTITIES": "true",
            "KB_MCP_EXTRACT_LLM": "deepseek",
            "KB_MCP_LOG_LEVEL": "INFO",
        }

        merged = {**defaults, **config}

        # 隐藏敏感信息
        masked = {}
        for key, value in merged.items():
            field_def = next((f for f in CONFIG_FIELDS if f["key"] == key), None)
            if field_def and field_def.get("sensitive"):
                masked[key] = mask_value(key, value)
            else:
                masked[key] = value

        return {
            "success": True,
            "data": masked
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def update_config(request: ConfigUpdateRequest) -> dict:
    """更新配置"""
    try:
        # 验证字段
        valid_keys = {f["key"] for f in CONFIG_FIELDS}
        invalid_keys = set(request.settings.keys()) - valid_keys
        if invalid_keys:
            raise HTTPException(status_code=400, detail=f"无效的配置项: {', '.join(invalid_keys)}")

        # 读取现有配置
        current = read_env_file()

        # 处理敏感字段 - 如果值包含 ****，表示未修改
        for key, value in request.settings.items():
            if "****" in str(value):
                # 保持原值不变
                continue
            if value == "" or value is None:
                # 删除空值
                current.pop(key, None)
            else:
                current[key] = str(value)

        # 写入文件
        write_env_file(current)

        return {
            "success": True,
            "message": "配置已保存，重启服务后生效"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/{service}")
async def test_connection(service: str) -> dict:
    """测试服务连接"""
    try:
        config = read_env_file()

        if service == "qdrant":
            return await _test_qdrant(config)
        elif service == "neo4j":
            return await _test_neo4j(config)
        elif service == "embedding":
            return await _test_embedding(config)
        elif service == "deepseek":
            return await _test_deepseek(config)
        elif service == "mimo":
            return await _test_mimo(config)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的服务: {service}")
    except HTTPException:
        raise
    except Exception as e:
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }


async def _test_qdrant(config: dict) -> dict:
    """测试 Qdrant 连接"""
    try:
        from qdrant_client import QdrantClient

        url = config.get("QDRANT_URL", "http://localhost:6333")
        api_key = config.get("QDRANT_API_KEY")

        client = QdrantClient(url=url, api_key=api_key, timeout=5)
        collections = client.get_collections()

        return {
            "success": True,
            "message": f"连接成功，共 {len(collections.collections)} 个集合"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"连接失败: {str(e)}"
        }


async def _test_neo4j(config: dict) -> dict:
    """测试 Neo4j 连接"""
    try:
        from neo4j import GraphDatabase

        uri = config.get("NEO4J_URI", "bolt://localhost:7687")
        user = config.get("NEO4J_USER", "neo4j")
        password = config.get("NEO4J_PASSWORD", "changeme")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            result = session.run("RETURN 1 AS num")
            record = result.single()
            if record and record["num"] == 1:
                return {
                    "success": True,
                    "message": "连接成功"
                }
        driver.close()
        return {
            "success": False,
            "message": "连接失败"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"连接失败: {str(e)}"
        }


async def _test_embedding(config: dict) -> dict:
    """测试 Embedding API"""
    try:
        import httpx

        provider = config.get("EMBEDDING_PROVIDER", "openai")

        if provider == "fastembed":
            try:
                from fastembed import TextEmbedding
                model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
                embeddings = list(model.embed(["测试"]))
                return {
                    "success": True,
                    "message": f"FastEmbed 可用，维度: {len(embeddings[0])}"
                }
            except ImportError:
                return {
                    "success": False,
                    "message": "FastEmbed 未安装，请运行: uv add fastembed"
                }

        # OpenAI 兼容 API
        api_key = config.get("OPENAI_API_KEY")
        if not api_key:
            return {
                "success": False,
                "message": "请先配置 OPENAI_API_KEY"
            }

        base_url = config.get("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        model = config.get("EMBEDDING_MODEL", "text-embedding-3-small")

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"input": "测试", "model": model}
            )

            if response.status_code == 200:
                data = response.json()
                dimension = len(data["data"][0]["embedding"])
                return {
                    "success": True,
                    "message": f"连接成功，模型: {model}，维度: {dimension}"
                }
            else:
                return {
                    "success": False,
                    "message": f"API 错误: {response.status_code} - {response.text[:200]}"
                }
    except Exception as e:
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }


async def _test_deepseek(config: dict) -> dict:
    """测试 DeepSeek API"""
    try:
        import httpx

        api_key = config.get("DEEPSEEK_API_KEY")
        if not api_key:
            return {
                "success": False,
                "message": "请先配置 DEEPSEEK_API_KEY"
            }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "DeepSeek API 连接成功"
                }
            else:
                return {
                    "success": False,
                    "message": f"API 错误: {response.status_code} - {response.text[:200]}"
                }
    except Exception as e:
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }


async def _test_mimo(config: dict) -> dict:
    """测试 MIMO API"""
    try:
        import httpx

        api_key = config.get("MIMO_API_KEY")
        base_url = config.get("MIMO_BASE_URL", "https://api.mimo.ai/v1")

        if not api_key:
            return {
                "success": False,
                "message": "请先配置 MIMO_API_KEY"
            }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "mimo-chat",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "MIMO API 连接成功"
                }
            else:
                return {
                    "success": False,
                    "message": f"API 错误: {response.status_code} - {response.text[:200]}"
                }
    except Exception as e:
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }
