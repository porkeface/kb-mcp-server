"""配置加载 - 使用 Pydantic Settings"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # ── Qdrant ──
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant 服务地址")
    qdrant_api_key: str | None = Field(default=None, description="Qdrant API Key")

    # ── Neo4j ──
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j 连接 URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j 用户名")
    neo4j_password: str = Field(default="changeme", description="Neo4j 密码")

    # ── Embedding ──
    embedding_provider: str = Field(default="openai", description="Embedding 提供商: openai | deepseek | fastembed")
    openai_api_key: str | None = Field(default=None, description="OpenAI API Key")
    embedding_api_key: str | None = Field(default=None, description="Embedding API Key（DeepSeek 等）")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding 模型名称"
    )
    embedding_dimension: int | None = Field(default=None, description="向量维度（自动检测）")
    embedding_base_url: str | None = Field(default=None, description="Embedding API 基础地址（用于 DeepSeek 等兼容 API）")

    # ── MCP Server ──
    kb_mcp_host: str = Field(default="127.0.0.1", description="MCP Server 主机")
    kb_mcp_port: int = Field(default=8100, description="FastAPI 管理 API 端口")
    kb_mcp_http_port: int = Field(default=8101, description="MCP Streamable HTTP 端口")
    kb_mcp_transport: str = Field(default="stdio", description="传输方式: stdio | streamable-http")

    # ── 数据目录 ──
    kb_mcp_data_dir: Path = Field(
        default=Path.home() / ".kb-mcp", description="数据目录路径"
    )

    # ── 日志 ──
    kb_mcp_log_level: str = Field(default="INFO", description="日志级别")

    # ── 实体提取 (可选) ──
    kb_mcp_extract_entities: bool = Field(
        default=True, description="导入文档时是否自动提取实体"
    )
    kb_mcp_extract_llm: str = Field(default="deepseek", description="用于实体提取的 LLM: openai | deepseek | mimo")
    llm_model: str | None = Field(default=None, description="LLM 模型名称（用户自定义）")
    llm_api_key: str | None = Field(default=None, description="LLM API Key（通用）")
    llm_base_url: str | None = Field(default=None, description="LLM API 基础地址（通用）")
    deepseek_api_key: str | None = Field(default=None, description="DeepSeek API Key")
    mimo_api_key: str | None = Field(default=None, description="小米 MIMO API Key")
    mimo_base_url: str | None = Field(default=None, description="小米 MIMO API 基础地址")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def registry_db_path(self) -> Path:
        """SQLite 注册表数据库路径"""
        return self.kb_mcp_data_dir / "registry.db"

    @property
    def uploads_dir(self) -> Path:
        """上传文件目录"""
        return self.kb_mcp_data_dir / "uploads"

    def ensure_dirs(self) -> None:
        """确保数据目录存在"""
        self.kb_mcp_data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


# 全局配置单例
settings = Settings()
