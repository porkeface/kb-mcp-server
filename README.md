# Knowledge Base MCP Server

> 通用知识库 MCP 服务 -- 为 Claude Code Agent 提供专业知识辅助
>
> 版本：v1.0.0 | 设计日期：2026-05-30

## 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [MCP Tools](#mcp-tools)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [开发路线图](#开发路线图)

---

## 项目概述

### 定位

一个独立部署的 MCP Server，为 Claude Code Agent 提供**多领域知识库**的语义检索和知识图谱推理能力。Agent 在编写代码时，可以通过 MCP 协议实时查询专业知识库，获取领域上下文。

### 核心能力

| 能力 | 说明 |
|------|------|
| 多知识库 | 支持同时管理多个领域知识库（yijing、finance、medical 等） |
| 语义搜索 | 基于 Qdrant 向量数据库的语义相似度检索 |
| 知识图谱 | 基于 Neo4j 的实体关系推理和路径查询 |
| 混合检索 | 向量 + 图谱 + 关键词三路融合，RRF 排序 |
| 文档摄入 | 支持 Markdown / PDF / TXT 文档的解析、分块、索引 |
| 跨项目 | 全局配置在 `~/.claude/settings.json`，所有项目可用 |
| 独立部署 | Docker 一键部署，自带 Neo4j + Qdrant |

### 使用场景

```
你写金融项目 → Agent 调用 kb_search(kb="finance", query="市盈率计算") → 获取专业知识
你写医疗项目 → Agent 调用 kb_search(kb="medical", query="气虚辨证") → 获取专业知识
你写易学项目 → Agent 调用 kb_search(kb="yijing", query="乾卦事业") → 获取专业知识
```

---

## 系统架构

### 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Claude Code Agent                             │
│                                                                      │
│  用户提问 ──> Agent 推理 ──> 调用 MCP Tools ──> 组装上下文 ──> 生成代码  │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ MCP Protocol (stdio / Streamable HTTP)
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Knowledge Base MCP Server                          │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                    MCP Tool Layer                            │     │
│  │  kb_search | kb_hybrid_search | kb_graph_query              │     │
│  │  kb_list | kb_create | kb_delete | kb_ingest | kb_info     │     │
│  └──────────────────────────┬──────────────────────────────────┘     │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐     │
│  │                  Retrieval Orchestrator                      │     │
│  │   ┌──────────┐   ┌──────────────┐   ┌─────────────────┐    │     │
│  │   │  Vector   │   │  Knowledge   │   │    Keyword      │    │     │
│  │   │  Search   │   │  Graph Search│   │    Search       │    │     │
│  │   └────┬─────┘   └──────┬───────┘   └────────┬────────┘    │     │
│  │        └────────────────┼─────────────────────┘             │     │
│  │                         ▼                                    │     │
│  │              ┌──────────────────┐                           │     │
│  │              │  RRF Fusion      │                           │     │
│  │              └──────────────────┘                           │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐     │
│  │                   Core Services Layer                        │     │
│  │   ┌────────────┐  ┌────────────┐  ┌──────────────────────┐ │     │
│  │   │ Embedding   │  │  Document   │  │  Knowledge Base     │ │     │
│  │   │ Service     │  │  Parser     │  │  Manager            │ │     │
│  │   └────────────┘  └────────────┘  └──────────────────────┘ │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐     │
│  │                   Storage Adapter Layer                      │     │
│  │   ┌──────────────────┐       ┌──────────────────────────┐  │     │
│  │   │  Qdrant Adapter   │       │  Neo4j Adapter           │  │     │
│  │   │  (Vector Store)   │       │  (Graph Store)           │  │     │
│  │   └──────────────────┘       └──────────────────────────┘  │     │
│  └──────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
                │                              │
    ┌───────────▼───────────┐      ┌──────────▼───────────┐
    │   Qdrant Container    │      │   Neo4j Container     │
    │  Collection per KB:   │      │  Label prefix per KB: │
    │  kb_yijing            │      │  kb_yijing__*         │
    │  kb_finance           │      │  kb_finance__*        │
    └───────────────────────┘      └───────────────────────┘
```

### 请求流程

```
Claude Code Agent                    MCP Server                     Storage
      │                                  │                             │
      │  1. kb_hybrid_search(            │                             │
      │     kb="yijing",                 │                             │
      │     query="乾卦事业")            │                             │
      │ ───────────────────────────────> │                             │
      │                                  │  2. Embed(query)            │
      │                                  │ ──────────────> OpenAI API  │
      │                                  │                             │
      │                                  │  3. Qdrant.search(          │
      │                                  │     collection="kb_yijing") │
      │                                  │ ──────────────────────────> │
      │                                  │                             │
      │                                  │  4. Neo4j.query(            │
      │                                  │     "MATCH related nodes")  │
      │                                  │ ──────────────────────────> │
      │                                  │                             │
      │                                  │  5. RRF Fusion              │
      │  6. 返回融合后的知识上下文        │                             │
      │ <─────────────────────────────── │                             │
```

---

## 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 语言 | Python 3.12+ | 主力开发语言 |
| 包管理 | uv | 快速 Python 包管理器 |
| MCP SDK | `mcp` (FastMCP) | Python MCP 协议 SDK |
| Web 框架 | FastAPI | 管理 API |
| 向量数据库 | Qdrant | 语义搜索 |
| 图数据库 | Neo4j 5 | 知识图谱 |
| Embedding | OpenAI `text-embedding-3-small` | 策略模式，可切换 |
| 文档解析 | PyMuPDF / 标准库 | MD / PDF / TXT |
| 部署 | Docker Compose | 一键部署 |

---

## MCP Tools

### 检索类

| 工具 | 说明 |
|------|------|
| `kb_search` | 向量语义搜索 |
| `kb_hybrid_search` | 三路混合检索（向量 + 图谱 + 关键词） |
| `kb_graph_query` | 知识图谱关系查询 |

### 管理类

| 工具 | 说明 |
|------|------|
| `kb_list` | 列出所有知识库 |
| `kb_create` | 创建新知识库 |
| `kb_delete` | 删除知识库 |
| `kb_info` | 获取知识库详情 |

### 数据类

| 工具 | 说明 |
|------|------|
| `kb_ingest` | 导入文档到知识库 |
| `kb_add_entity` | 向图谱添加实体 |
| `kb_add_relation` | 向图谱添加关系 |

详细参数见 [MCP Tools 设计文档](docs/architecture.md#4-mcp-tools-设计)。

---

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url> kb-mcp-server
cd kb-mcp-server
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 OpenAI API Key 等配置
```

### 3. Docker 部署

```bash
docker compose up -d
```

### 4. 配置 Claude Code

在 `~/.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://localhost:8101/mcp"
    }
  }
}
```

### 5. 使用

在 Claude Code 中：

```
# 创建知识库
kb_create(name="yijing", description="易经知识库")

# 导入文档
kb_ingest(kb_name="yijing", file_path="/path/to/yijing.md")

# 搜索
kb_search(kb_name="yijing", query="乾卦初九爻辞")
```

---

## 配置说明

### 环境变量

```bash
# Qdrant
QDRANT_URL=http://localhost:6333

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# Embedding
EMBEDDING_PROVIDER=openai       # openai | fastembed
OPENAI_API_KEY=sk-xxx
EMBEDDING_MODEL=text-embedding-3-small

# MCP Server
KB_MCP_HOST=127.0.0.1
KB_MCP_PORT=8100
KB_MCP_HTTP_PORT=8101
KB_MCP_TRANSPORT=stdio          # stdio | streamable-http

# 数据目录
KB_MCP_DATA_DIR=~/.kb-mcp

# 日志
KB_MCP_LOG_LEVEL=INFO
```

### Claude Code 配置

**本地模式（stdio）**：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/kb-mcp-server", "python", "-m", "kb_mcp_server"],
      "env": {
        "OPENAI_API_KEY": "sk-your-key"
      }
    }
  }
}
```

**远程模式（Docker 部署后）**：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://localhost:8101/mcp"
    }
  }
}
```

---

## 项目结构

```
kb-mcp-server/
├── pyproject.toml                    # uv 项目配置
├── uv.lock                          # 依赖锁文件
├── Dockerfile                        # MCP Server 镜像
├── docker-compose.yml                # 完整部署配置
├── .env.example                      # 环境变量模板
├── README.md                         # 本文档
├── docs/
│   └── architecture.md               # 详细架构设计文档
│
├── src/
│   └── kb_mcp_server/
│       ├── __init__.py
│       ├── __main__.py               # 入口
│       ├── config.py                 # 配置加载
│       │
│       ├── mcp/                      # MCP 协议层
│       │   ├── server.py             # FastMCP 实例
│       │   ├── tools.py              # MCP Tools
│       │   └── resources.py          # MCP Resources
│       │
│       ├── core/                     # 核心业务
│       │   ├── orchestrator.py       # 混合检索编排 (RRF)
│       │   ├── kb_manager.py         # 知识库 CRUD
│       │   ├── chunker.py            # 文档分块
│       │   └── entity_extractor.py   # 实体提取
│       │
│       ├── parsers/                  # 文档解析
│       │   ├── base.py               # Protocol
│       │   ├── markdown_parser.py
│       │   ├── pdf_parser.py
│       │   └── text_parser.py
│       │
│       ├── embedding/                # Embedding 层
│       │   ├── base.py               # Protocol
│       │   ├── openai_provider.py
│       │   └── fastembed_provider.py
│       │
│       ├── storage/                  # 存储适配
│       │   ├── qdrant_adapter.py
│       │   ├── neo4j_adapter.py
│       │   └── registry.py           # SQLite 元数据
│       │
│       ├── models/                   # 数据模型
│       │   ├── chunk.py
│       │   ├── entity.py
│       │   ├── search.py
│       │   └── knowledge_base.py
│       │
│       └── api/                      # FastAPI 管理 API
│           └── app.py
│
├── tests/                            # 测试
│   └── ...
│
└── scripts/                          # 工具脚本
    ├── seed_yijing.py
    └── health_check.py
```

---

## 开发路线图

### Phase 1 -- MVP

- [ ] 项目脚手架（uv init, 目录结构）
- [ ] MCP Server 框架（FastMCP, stdio 传输）
- [ ] Embedding 层（OpenAI + FastEmbed）
- [ ] Qdrant Adapter（Collection 管理, 向量 CRUD）
- [ ] 文档解析（Markdown + TXT）
- [ ] 分块器（滑动窗口）
- [ ] `kb_search`, `kb_create`, `kb_list`, `kb_info`, `kb_ingest` Tools
- [ ] Docker Compose（Qdrant）

### Phase 2 -- 图谱集成

- [ ] Neo4j Adapter（节点/边 CRUD）
- [ ] 实体提取（LLM 辅助）
- [ ] `kb_graph_query`, `kb_add_entity`, `kb_add_relation` Tools
- [ ] `kb_hybrid_search` Tool（三路 RRF）
- [ ] Docker Compose（添加 Neo4j）

### Phase 3 -- 生产化

- [ ] PDF 解析（PyMuPDF）
- [ ] Streamable HTTP 传输
- [ ] FastAPI 管理 API
- [ ] 健康检查 / 日志 / 监控
- [ ] 测试覆盖 80%+

### Phase 4 -- 高级特性

- [ ] 查询扩展（图谱增强向量检索）
- [ ] 结果重排（Cross-encoder）
- [ ] 增量更新
- [ ] 多模态（图片 OCR）

---

## 详细设计

完整架构设计文档见 [docs/architecture.md](docs/architecture.md)。

---

## License

MIT
