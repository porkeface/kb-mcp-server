"""配置管理 API"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])


def mask_value(key: str, value: str | None) -> str | None:
    """隐藏敏感信息"""
    if value is None:
        return None
    if "key" in key.lower() and len(value) > 8:
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


# 提供商配置映射
LLM_PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "default_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "mimo": {
        "name": "小米 MIMO",
        "default_url": "https://api.mimo.ai/v1",
        "default_model": "mimo-chat",
    },
}

EMBEDDING_PROVIDERS = {
    "openai": {
        "name": "OpenAI 兼容",
        "default_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-embedding",
    },
    "fastembed": {
        "name": "FastEmbed (本地)",
        "default_url": None,
        "default_model": "BAAI/bge-small-en-v1.5",
    },
}


@router.get("")
async def get_config() -> dict:
    """获取当前配置"""
    try:
        config = read_env_file()

        # 构建简化的配置响应
        data = {
            # Qdrant
            "QDRANT_URL": config.get("QDRANT_URL", "http://localhost:6333"),

            # Neo4j
            "NEO4J_URI": config.get("NEO4J_URI", "bolt://localhost:7687"),
            "NEO4J_USER": config.get("NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": mask_value("NEO4J_PASSWORD", config.get("NEO4J_PASSWORD", "changeme")),

            # Embedding
            "EMBEDDING_PROVIDER": config.get("EMBEDDING_PROVIDER", "openai"),
            "EMBEDDING_API_KEY": mask_value("EMBEDDING_API_KEY", _get_embedding_api_key(config)),
            "EMBEDDING_MODEL": config.get("EMBEDDING_MODEL", ""),
            "EMBEDDING_BASE_URL": config.get("EMBEDDING_BASE_URL", ""),
            "EMBEDDING_DIMENSION": config.get("EMBEDDING_DIMENSION", ""),

            # LLM 实体提取
            "KB_MCP_EXTRACT_ENTITIES": config.get("KB_MCP_EXTRACT_ENTITIES", "true"),
            "KB_MCP_EXTRACT_LLM": config.get("KB_MCP_EXTRACT_LLM", "deepseek"),
            "LLM_API_KEY": mask_value("LLM_API_KEY", _get_llm_api_key(config)),
            "LLM_BASE_URL": config.get("LLM_BASE_URL", ""),

            # 服务配置
            "KB_MCP_HOST": config.get("KB_MCP_HOST", "127.0.0.1"),
            "KB_MCP_PORT": config.get("KB_MCP_PORT", "8100"),
            "KB_MCP_LOG_LEVEL": config.get("KB_MCP_LOG_LEVEL", "INFO"),
        }

        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_embedding_api_key(config: dict) -> str | None:
    """获取 Embedding API Key（兼容旧配置）"""
    provider = config.get("EMBEDDING_PROVIDER", "openai")
    if provider == "fastembed":
        return None
    # 优先使用新字段，兼容旧字段
    return config.get("EMBEDDING_API_KEY") or config.get("OPENAI_API_KEY")


def _get_llm_api_key(config: dict) -> str | None:
    """获取 LLM API Key（兼容旧配置）"""
    provider = config.get("KB_MCP_EXTRACT_LLM", "deepseek")
    # 优先使用新字段，兼容旧字段
    if provider == "deepseek":
        return config.get("LLM_API_KEY") or config.get("DEEPSEEK_API_KEY")
    elif provider == "mimo":
        return config.get("LLM_API_KEY") or config.get("MIMO_API_KEY")
    elif provider == "openai":
        return config.get("LLM_API_KEY") or config.get("OPENAI_API_KEY")
    return config.get("LLM_API_KEY")


@router.post("")
async def update_config(request: dict) -> dict:
    """更新配置"""
    try:
        settings = request.get("settings", {})

        # 读取现有配置
        current = read_env_file()

        # 字段映射（UI 字段 -> .env 字段）
        for key, value in settings.items():
            if "****" in str(value):
                continue  # 跳过未修改的敏感字段

            if key == "EMBEDDING_API_KEY":
                # 写入到提供商对应的字段
                provider = settings.get("EMBEDDING_PROVIDER", current.get("EMBEDDING_PROVIDER", "openai"))
                if provider == "fastembed":
                    continue
                if value:
                    current["EMBEDDING_API_KEY"] = value
                    # 兼容旧代码
                    if provider == "openai":
                        current["OPENAI_API_KEY"] = value
                else:
                    current.pop("EMBEDDING_API_KEY", None)
                    current.pop("OPENAI_API_KEY", None)

            elif key == "LLM_API_KEY":
                # 写入到提供商对应的字段
                provider = settings.get("KB_MCP_EXTRACT_LLM", current.get("KB_MCP_EXTRACT_LLM", "deepseek"))
                if value:
                    current["LLM_API_KEY"] = value
                    # 兼容旧代码
                    if provider == "deepseek":
                        current["DEEPSEEK_API_KEY"] = value
                    elif provider == "mimo":
                        current["MIMO_API_KEY"] = value
                    elif provider == "openai":
                        current["OPENAI_API_KEY"] = value
                else:
                    current.pop("LLM_API_KEY", None)
                    current.pop("DEEPSEEK_API_KEY", None)
                    current.pop("MIMO_API_KEY", None)

            elif key == "LLM_BASE_URL":
                if value:
                    current["LLM_BASE_URL"] = value
                    # 兼容旧代码
                    provider = settings.get("KB_MCP_EXTRACT_LLM", current.get("KB_MCP_EXTRACT_LLM", "deepseek"))
                    if provider == "mimo":
                        current["MIMO_BASE_URL"] = value
                else:
                    current.pop("LLM_BASE_URL", None)
                    current.pop("MIMO_BASE_URL", None)

            elif key == "EMBEDDING_BASE_URL":
                if value:
                    current["EMBEDDING_BASE_URL"] = value
                else:
                    current.pop("EMBEDDING_BASE_URL", None)

            elif value == "" or value is None:
                current.pop(key, None)
            else:
                current[key] = str(value)

        # 写入文件
        write_env_file(current)

        return {"success": True, "message": "配置已保存，重启服务后生效"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers")
async def get_providers() -> dict:
    """获取提供商配置"""
    return {
        "success": True,
        "data": {
            "llm": LLM_PROVIDERS,
            "embedding": EMBEDDING_PROVIDERS,
        }
    }


@router.post("/test/{service}")
async def test_connection(service: str, request: dict = None) -> dict:
    """测试服务连接

    可选传入当前 UI 中的配置值进行测试，无需先保存
    """
    try:
        # 合并 .env 文件配置和 UI 传入的配置
        config = read_env_file()
        if request and "settings" in request:
            ui_settings = request["settings"]
            # UI 传入的值优先（跳过空值和未修改的敏感字段）
            for key, value in ui_settings.items():
                if value and "****" not in str(value):
                    config[key] = value

        if service == "qdrant":
            return await _test_qdrant(config)
        elif service == "neo4j":
            return await _test_neo4j(config)
        elif service == "embedding":
            return await _test_embedding(config)
        elif service == "llm":
            return await _test_llm(config)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的服务: {service}")
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


async def _test_qdrant(config: dict) -> dict:
    """测试 Qdrant 连接"""
    try:
        from qdrant_client import QdrantClient

        url = config.get("QDRANT_URL", "http://localhost:6333")
        client = QdrantClient(url=url, timeout=5)
        collections = client.get_collections()

        return {
            "success": True,
            "message": f"连接成功，共 {len(collections.collections)} 个集合"
        }
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


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
                return {"success": True, "message": "连接成功"}
        driver.close()
        return {"success": False, "message": "连接失败"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


async def _test_embedding(config: dict) -> dict:
    """测试 Embedding API"""
    try:
        import httpx

        provider = config.get("EMBEDDING_PROVIDER", "openai")

        if provider == "fastembed":
            try:
                from fastembed import TextEmbedding
                model_name = config.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
                if model_name.startswith("text-embedding"):
                    model_name = "BAAI/bge-small-en-v1.5"
                model = TextEmbedding(model_name=model_name)
                embeddings = list(model.embed(["测试"]))
                return {
                    "success": True,
                    "message": f"FastEmbed 可用，维度: {len(embeddings[0])}"
                }
            except ImportError:
                return {"success": False, "message": "FastEmbed 未安装，请运行: uv add fastembed"}

        # API 方式
        api_key = _get_embedding_api_key(config)
        if not api_key:
            return {"success": False, "message": "请先配置 Embedding API Key"}

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
                return {"success": True, "message": f"连接成功，模型: {model}，维度: {dimension}"}
            else:
                return {"success": False, "message": f"API 错误: {response.status_code}"}
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


async def _test_llm(config: dict) -> dict:
    """测试 LLM API"""
    try:
        import httpx

        provider = config.get("KB_MCP_EXTRACT_LLM", "deepseek")
        api_key = _get_llm_api_key(config)

        if not api_key:
            return {"success": False, "message": "请先配置 LLM API Key"}

        provider_info = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["deepseek"])
        base_url = config.get("LLM_BASE_URL") or provider_info["default_url"]
        model = provider_info["default_model"]

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )

            if response.status_code == 200:
                return {"success": True, "message": f"{provider_info['name']} API 连接成功"}
            else:
                return {"success": False, "message": f"API 错误: {response.status_code}"}
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}
