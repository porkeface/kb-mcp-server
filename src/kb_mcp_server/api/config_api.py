"""配置管理 API"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
import structlog

router = APIRouter(prefix="/api/config", tags=["config"])
logger = structlog.get_logger()

# 全局配置热重载回调
_reload_callback = None


def set_reload_callback(callback):
    """设置配置热重载回调函数"""
    global _reload_callback
    _reload_callback = callback


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
                if key:
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
        "default_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "default_model": "mimo-v2.5",
    },
}


# 允许通过 API 更新的配置键白名单
ALLOWED_KEYS: set[str] = {
    "QDRANT_URL",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_DIMENSION",
    "OPENAI_API_KEY",
    "KB_MCP_EXTRACT_ENTITIES",
    "KB_MCP_EXTRACT_LLM",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "DEEPSEEK_API_KEY",
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "KB_MCP_HOST",
    "KB_MCP_PORT",
    "KB_MCP_LOG_LEVEL",
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
            "EMBEDDING_API_KEY": mask_value("EMBEDDING_API_KEY", config.get("EMBEDDING_API_KEY") or config.get("OPENAI_API_KEY")),
            "EMBEDDING_MODEL": config.get("EMBEDDING_MODEL", ""),
            "EMBEDDING_BASE_URL": config.get("EMBEDDING_BASE_URL", ""),
            "EMBEDDING_DIMENSION": config.get("EMBEDDING_DIMENSION", ""),

            # LLM 实体提取
            "KB_MCP_EXTRACT_ENTITIES": config.get("KB_MCP_EXTRACT_ENTITIES", "true"),
            "KB_MCP_EXTRACT_LLM": config.get("KB_MCP_EXTRACT_LLM", "deepseek"),
            "LLM_MODEL": config.get("LLM_MODEL", ""),
            "LLM_API_KEY": mask_value("LLM_API_KEY", config.get("LLM_API_KEY") or config.get("DEEPSEEK_API_KEY") or config.get("MIMO_API_KEY")),
            "LLM_BASE_URL": config.get("LLM_BASE_URL") or config.get("MIMO_BASE_URL", ""),

            # 服务配置
            "KB_MCP_HOST": config.get("KB_MCP_HOST", "127.0.0.1"),
            "KB_MCP_PORT": config.get("KB_MCP_PORT", "8100"),
            "KB_MCP_LOG_LEVEL": config.get("KB_MCP_LOG_LEVEL", "INFO"),
        }

        return {"success": True, "data": data}
    except Exception as e:
        logger.error("获取配置失败", error=str(e))
        return {"success": False, "message": str(e), "data": {}}


@router.post("")
async def update_config(request: Request) -> dict:
    """更新配置"""
    try:
        body = await request.json()
        settings = body.get("settings", {})

        if not settings:
            return {"success": False, "message": "没有配置数据"}

        # 读取现有配置
        current = read_env_file()

        # 字段映射（UI 字段 -> .env 字段）
        for key, value in settings.items():
            # 白名单校验
            if key not in ALLOWED_KEYS:
                logger.warning("拒绝未授权的配置键", key=key)
                continue

            # 跳过未修改的敏感字段
            if isinstance(value, str) and "****" in value:
                continue

            # 值中去除换行符（防止注入）
            if isinstance(value, str):
                value = value.replace("\n", "").replace("\r", "")

            if key == "EMBEDDING_API_KEY":
                provider = settings.get("EMBEDDING_PROVIDER", current.get("EMBEDDING_PROVIDER", "openai"))
                if provider == "fastembed":
                    continue
                if value:
                    current["EMBEDDING_API_KEY"] = str(value)
                    if provider == "openai":
                        current["OPENAI_API_KEY"] = str(value)
                else:
                    current.pop("EMBEDDING_API_KEY", None)
                    current.pop("OPENAI_API_KEY", None)

            elif key == "LLM_API_KEY":
                provider = settings.get("KB_MCP_EXTRACT_LLM", current.get("KB_MCP_EXTRACT_LLM", "deepseek"))
                if value:
                    current["LLM_API_KEY"] = str(value)
                    if provider == "deepseek":
                        current["DEEPSEEK_API_KEY"] = str(value)
                    elif provider == "mimo":
                        current["MIMO_API_KEY"] = str(value)
                    elif provider == "openai":
                        current["OPENAI_API_KEY"] = str(value)
                else:
                    current.pop("LLM_API_KEY", None)
                    current.pop("DEEPSEEK_API_KEY", None)
                    current.pop("MIMO_API_KEY", None)

            elif key == "LLM_BASE_URL":
                if value:
                    current["LLM_BASE_URL"] = str(value)
                    provider = settings.get("KB_MCP_EXTRACT_LLM", current.get("KB_MCP_EXTRACT_LLM", "deepseek"))
                    if provider == "mimo":
                        current["MIMO_BASE_URL"] = str(value)
                else:
                    current.pop("LLM_BASE_URL", None)
                    current.pop("MIMO_BASE_URL", None)

            elif key == "EMBEDDING_BASE_URL":
                if value:
                    current["EMBEDDING_BASE_URL"] = str(value)
                else:
                    current.pop("EMBEDDING_BASE_URL", None)

            elif key in ("NEO4J_PASSWORD",):
                if value:
                    current[key] = str(value)
                # 空值不更新密码

            elif value == "" or value is None:
                current.pop(key, None)
            else:
                current[key] = str(value)

        # 写入文件
        write_env_file(current)

        # 触发热重载
        if _reload_callback:
            try:
                _reload_callback()
                logger.info("配置热重载成功")
            except Exception as e:
                logger.warning("配置热重载失败", error=str(e))

        return {"success": True, "message": "配置已保存并生效"}
    except Exception as e:
        logger.error("保存配置失败", error=str(e))
        return {"success": False, "message": f"保存失败: {str(e)}"}


@router.post("/test/{service}")
async def test_connection(service: str, request: Request) -> dict:
    """测试服务连接（使用 UI 中的值，无需先保存）"""
    try:
        body = await request.json()
        ui_settings = body.get("settings", {})

        # 使用 UI 传入的配置（不读取 .env 文件，避免混淆）
        config = {}

        # 处理 UI 传入的值
        for key, value in ui_settings.items():
            # 跳过包含 **** 的值（未修改的敏感字段）
            if isinstance(value, str) and "****" in value:
                continue
            # 空值也记录（表示用户清空了该字段）
            config[key] = str(value) if value is not None else ""

        logger.info("测试连接", service=service, provider=config.get("EMBEDDING_PROVIDER") or config.get("KB_MCP_EXTRACT_LLM"))

        if service == "qdrant":
            return await _test_qdrant(config)
        elif service == "neo4j":
            return await _test_neo4j(config)
        elif service == "embedding":
            return await _test_embedding(config)
        elif service == "llm":
            return await _test_llm(config)
        else:
            return {"success": False, "message": f"不支持的服务: {service}"}
    except Exception as e:
        logger.error("测试连接失败", service=service, error=str(e))
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
        try:
            with driver.session() as session:
                result = session.run("RETURN 1 AS num")
                record = result.single()
                if record and record["num"] == 1:
                    return {"success": True, "message": "连接成功"}
            return {"success": False, "message": "连接失败"}
        finally:
            driver.close()
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


async def _test_embedding(config: dict) -> dict:
    """测试 Embedding API"""
    provider = config.get("EMBEDDING_PROVIDER", "openai")
    logger.info("测试 Embedding", provider=provider, config_keys=list(config.keys()), has_key=bool(config.get("EMBEDDING_API_KEY")))

    # FastEmbed 本地模型
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
                "message": f"FastEmbed 可用，模型: {model_name}，维度: {len(embeddings[0])}"
            }
        except ImportError:
            return {"success": False, "message": "FastEmbed 未安装，请运行: uv add fastembed"}
        except Exception as e:
            return {"success": False, "message": f"FastEmbed 错误: {str(e)}"}

    # OpenAI 兼容 API
    api_key = config.get("EMBEDDING_API_KEY") or config.get("OPENAI_API_KEY")
    if not api_key:
        return {"success": False, "message": f"请先配置 API Key（当前提供商: {provider}）"}

    base_url = config.get("EMBEDDING_BASE_URL", "")
    if not base_url:
        if provider == "deepseek":
            base_url = "https://api.deepseek.com/v1"
        else:
            base_url = "https://api.openai.com/v1"

    model = config.get("EMBEDDING_MODEL", "text-embedding-3-small")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
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
                error_msg = response.text[:200] if response.text else f"HTTP {response.status_code}"
                return {"success": False, "message": f"API 错误: {error_msg}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


async def _test_llm(config: dict) -> dict:
    """测试 LLM API"""
    provider = config.get("KB_MCP_EXTRACT_LLM", "deepseek")
    logger.info("测试 LLM", provider=provider)

    # 获取 API Key
    api_key = config.get("LLM_API_KEY")
    if not api_key:
        if provider == "deepseek":
            api_key = config.get("DEEPSEEK_API_KEY")
        elif provider == "mimo":
            api_key = config.get("MIMO_API_KEY")
        elif provider == "openai":
            api_key = config.get("OPENAI_API_KEY")

    if not api_key:
        return {"success": False, "message": f"请先配置 API Key（当前提供商: {provider}）"}

    # 获取 base_url
    provider_info = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["deepseek"])
    base_url = config.get("LLM_BASE_URL", "")
    if not base_url:
        if provider == "mimo":
            base_url = config.get("MIMO_BASE_URL", provider_info["default_url"])
        else:
            base_url = provider_info["default_url"]

    # 获取模型名称（优先使用用户指定的，否则使用默认值）
    model = config.get("LLM_MODEL", "") or provider_info["default_model"]

    logger.info("LLM 测试参数", provider=provider, base_url=base_url, model=model, has_key=bool(api_key))

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )

            if response.status_code == 200:
                return {"success": True, "message": f"{provider_info['name']} API 连接成功"}
            else:
                error_msg = response.text[:200] if response.text else f"HTTP {response.status_code}"
                return {"success": False, "message": f"API 错误 ({response.status_code}): {error_msg}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}
