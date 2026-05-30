# Knowledge Base MCP Server -- 详细架构设计文档

> 版本：v1.0.0 | 设计日期：2026-05-30

---

## 目录

- [1. 核心模块设计](#1-核心模块设计)
- [2. MCP Tools 详细设计](#2-mcp-tools-详细设计)
- [3. 多知识库管理方案](#3-多知识库管理方案)
- [4. 图谱与向量的协作方式](#4-图谱与向量的协作方式)
- [5. Docker 部署架构](#5-docker-部署架构)
- [6. 配置方案](#6-配置方案)
- [7. 项目目录结构](#7-项目目录结构)
- [8. 开发路线图](#8-开发路线图)
- [附录](#附录)

---

## 1. 核心模块设计

### 1.1 文档解析层 (Document Parser)

**职责**：将不同格式的文档统一解析为纯文本段落。

```
输入格式          解析器                   输出
─────────────────────────────────────────────────
.md (Markdown) -> MarkdownParser       -> [Section]
.pdf (PDF)     -> PyMuPDFParser        -> [Page]
.txt (Plain)   -> PlainTextParser      -> [Paragraph]
```

**设计要点**：

- 使用 `Protocol` 定义统一接口 `DocumentParser`
- Markdown 解析保留标题层级结构（H1/H2/H3 作为元数据）
- PDF 解析使用 PyMuPDF (`fitz`)，保留页码信息
- 每个解析结果包含：`text`, `metadata` (source, page, section_title, format)

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class ParsedChunk:
    """解析后的文档片段"""
    text: str
    metadata: dict[str, str]  # source, page, section, format, etc.

class DocumentParser(Protocol):
    """文档解析器协议"""
    def parse(self, file_path: str) -> list[ParsedChunk]: ...
    def supported_extensions(self) -> list[str]: ...
```

### 1.2 分块策略 (Chunking Strategy)

**目标**：将长文档切分为适合 Embedding 的语义块。

**策略**：滑动窗口 + 语义边界感知

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `chunk_size` | 512 tokens | 每个块的目标大小 |
| `chunk_overlap` | 64 tokens | 相邻块的重叠区域 |
| `min_chunk_size` | 100 tokens | 低于此阈值的块合并到前一块 |
| `separators` | `["\n## ", "\n### ", "\n\n", "\n", ". "]` | 优先在这些位置切分 |

**分块流程**：

```
原文 ──> 按段落/标题初分 ──> 合并过短段落 ──> 切分过长段落 ──> 添加重叠 ──> 输出块列表
```

**元数据继承**：每个块自动继承父文档的元数据，并添加 `chunk_index` 和 `chunk_total`。

```python
@dataclass(frozen=True)
class Chunk:
    """分块结果"""
    id: str            # 唯一ID: {kb_name}_{doc_id}_{chunk_index}
    text: str          # 块文本
    embedding: list[float] | None  # 向量（延迟生成）
    metadata: dict[str, str]       # 继承自文档 + chunk_index
```

### 1.3 Embedding 层

**设计模式**：策略模式 (Strategy Pattern)，支持运行时切换 Embedding 提供商。

```
                    EmbeddingProvider (Protocol)
                    ├── OpenAIEmbedding       # text-embedding-3-small (1536维)
                    ├── FastEmbedEmbedding    # BAAI/bge-small-en-v1.5 (384维, 本地)
                    └── JinaEmbedding         # jina-embeddings-v3 (可选)
```

```python
class EmbeddingProvider(Protocol):
    """Embedding 提供商协议"""
    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

**配置**：

```bash
EMBEDDING_PROVIDER=openai  # openai | fastembed | jina
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

**关键决策**：
- 默认使用 OpenAI `text-embedding-3-small`，1536 维，质量/成本平衡最佳
- 本地备选使用 FastEmbed `BAAI/bge-small-en-v1.5`，384 维，零成本
- 维度在创建 Qdrant collection 时确定，**不可中途变更**（需要重建索引）

### 1.4 向量检索层 (Qdrant Adapter)

**存储隔离**：每个知识库对应一个独立的 Qdrant Collection。

```
Qdrant
├── collection: kb_yijing      (vector_size=1536, distance=COSINE)
├── collection: kb_finance     (vector_size=1536, distance=COSINE)
└── collection: kb_medical     (vector_size=1536, distance=COSINE)
```

**Payload 结构**：

```json
{
    "doc_id": "doc_abc123",
    "chunk_index": 0,
    "text": "乾：元亨利贞...",
    "source": "yijing_original.md",
    "section": "乾卦",
    "format": "markdown",
    "kb_name": "yijing",
    "indexed_at": "2026-05-30T10:00:00Z"
}
```

**核心操作**：

```python
class QdrantAdapter:
    def ensure_collection(self, kb_name: str, dimension: int) -> None: ...
    def upsert_chunks(self, kb_name: str, chunks: list[Chunk]) -> None: ...
    def search(self, kb_name: str, query_vector: list[float], top_k: int = 10,
               score_threshold: float = 0.3) -> list[SearchResult]: ...
    def delete_collection(self, kb_name: str) -> None: ...
    def delete_document(self, kb_name: str, doc_id: str) -> None: ...
    def collection_info(self, kb_name: str) -> CollectionInfo: ...
```

### 1.5 知识图谱层 (Neo4j Adapter)

**存储隔离**：每个知识库使用 Label 前缀隔离（兼容 Community Edition）。

```
Neo4j
├── (:kb_yijing__Entity {name: "乾卦"})
│   ─[:kb_yijing__RELATED_TO]─>
│   (:kb_yijing__Entity {name: "天"})
│
├── (:kb_finance__Entity {name: "市盈率"})
│   ─[:kb_finance__RELATED_TO]─>
│   (:kb_finance__Entity {name: "估值"})
```

> **注**：如果使用 Neo4j Enterprise Edition，推荐使用 Database 级别隔离（`CREATE DATABASE kb_yijing`），性能和安全性更优。

**通用图谱 Schema**：

```
节点类型 (Labels):
├── Entity          # 通用实体（概念、术语、人物、机构...）
├── Document        # 文档节点
├── Chunk           # 文档块节点
└── Topic           # 主题/分类节点

关系类型:
├── MENTIONS        # Chunk -> Entity (块中提到了实体)
├── BELONGS_TO      # Entity -> Topic (实体属于某个主题)
├── RELATED_TO      # Entity -> Entity (实体间关系)
├── CONTAINS        # Document -> Chunk (文档包含块)
├── REFERENCES      # Entity -> Document (实体引用自文档)
└── SIMILAR_TO      # Entity -> Entity (语义相似，基于共现)
```

**领域扩展**：不同知识库可以在通用 Schema 基础上添加领域特定的节点和关系。

- `yijing` 知识库：添加 `Hexagram`, `Element`, `Trigram` 节点和 `OPPOSITE`, `GENERATES` 等关系
- `finance` 知识库：添加 `Company`, `Index`, `Sector` 节点和 `COMPETES_WITH`, `SUPPLIES_TO` 等关系

**核心操作**：

```python
class Neo4jAdapter:
    def ensure_database(self, kb_name: str) -> None: ...
    def add_entity(self, kb_name: str, entity: Entity) -> str: ...
    def add_relation(self, kb_name: str, source_id: str, target_id: str,
                     rel_type: str, properties: dict | None = None) -> None: ...
    def get_neighbors(self, kb_name: str, entity_id: str,
                      rel_type: str | None = None, depth: int = 1) -> list[Entity]: ...
    def find_path(self, kb_name: str, start_id: str, end_id: str,
                  max_depth: int = 3) -> list[Path]: ...
    def search_entities(self, kb_name: str, query: str,
                        limit: int = 10) -> list[Entity]: ...
    def cypher_query(self, kb_name: str, query: str,
                     params: dict | None = None) -> list[dict]: ...
    def delete_database(self, kb_name: str) -> None: ...
```

### 1.6 混合检索编排 (Retrieval Orchestrator)

**三路检索 + RRF 融合**：

```
查询 ──┬──> 向量检索 (Qdrant)    ──> [结果A: score排序]
       │
       ├──> 图谱检索 (Neo4j)     ──> [结果B: 关系深度排序]
       │
       └──> 关键词检索 (Qdrant payload filter) ──> [结果C: BM25排序]
                                                          │
                                                          ▼
                                               RRF 融合排序
                                                          │
                                                          ▼
                                               Top-K 结果返回
```

**RRF 算法**：

```
RRF_score(doc) = Σ  1 / (k + rank_i)

其中:
- k = 60 (常数)
- rank_i = 文档在第 i 路检索中的排名
- 对所有检索路的分数求和
```

**检索编排接口**：

```python
@dataclass(frozen=True)
class HybridSearchResult:
    text: str
    score: float           # RRF 融合分数
    source: str            # "vector" | "graph" | "keyword"
    metadata: dict[str, str]

class RetrievalOrchestrator:
    async def hybrid_search(
        self,
        kb_name: str,
        query: str,
        max_results: int = 10,
        vector_weight: float = 1.0,
        graph_weight: float = 1.0,
        keyword_weight: float = 1.0,
    ) -> list[HybridSearchResult]: ...

    async def vector_search(
        self, kb_name: str, query: str, top_k: int = 10
    ) -> list[HybridSearchResult]: ...

    async def graph_search(
        self, kb_name: str, query: str, depth: int = 2
    ) -> list[HybridSearchResult]: ...
```

---

## 2. MCP Tools 详细设计

### 2.1 工具总览

| 工具名 | 类别 | 说明 |
|--------|------|------|
| `kb_search` | 检索 | 向量语义搜索 |
| `kb_hybrid_search` | 检索 | 三路混合检索（向量 + 图谱 + 关键词） |
| `kb_graph_query` | 检索 | 知识图谱关系查询 |
| `kb_list` | 管理 | 列出所有知识库 |
| `kb_create` | 管理 | 创建新知识库 |
| `kb_delete` | 管理 | 删除知识库 |
| `kb_info` | 管理 | 获取知识库详情 |
| `kb_ingest` | 数据 | 导入文档到知识库 |
| `kb_add_entity` | 数据 | 向图谱添加实体 |
| `kb_add_relation` | 数据 | 向图谱添加关系 |

### 2.2 工具详细定义

#### `kb_search` -- 向量语义搜索

```python
@mcp.tool()
async def kb_search(
    kb_name: str,          # 知识库名称 (如 "yijing", "finance")
    query: str,            # 搜索查询文本
    top_k: int = 5,        # 返回结果数量 (1-20)
) -> list[dict]:
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
```

#### `kb_hybrid_search` -- 混合检索

```python
@mcp.tool()
async def kb_hybrid_search(
    kb_name: str,              # 知识库名称
    query: str,                # 搜索查询
    top_k: int = 10,           # 返回结果数量 (1-30)
    include_graph: bool = True, # 是否包含图谱检索
) -> list[dict]:
    """在指定知识库中进行三路混合检索。

    融合向量语义搜索、知识图谱关系查询、关键词匹配三种方式，
    使用 RRF (Reciprocal Rank Fusion) 算法排序。
    适用于：需要全面、准确的知识上下文时使用。
    """
```

#### `kb_graph_query` -- 图谱查询

```python
@mcp.tool()
async def kb_graph_query(
    kb_name: str,              # 知识库名称
    entity: str,               # 实体名称或ID
    relation: str | None = None, # 关系类型过滤 (可选)
    depth: int = 2,            # 查询深度 (1-3)
) -> dict:
    """查询知识图谱中实体的关系网络。

    从指定实体出发，沿关系边遍历图谱，返回相关的实体和关系。
    适用于：查找实体间关系、概念关联、知识脉络。
    """
```

#### `kb_list` -- 列出知识库

```python
@mcp.tool()
async def kb_list() -> list[dict]:
    """列出所有已创建的知识库。

    Returns:
        知识库列表，每项包含 name, description, document_count,
        chunk_count, entity_count, created_at
    """
```

#### `kb_create` -- 创建知识库

```python
@mcp.tool()
async def kb_create(
    name: str,                  # 知识库名称 (小写字母+下划线, 如 "yijing")
    description: str = "",      # 知识库描述
    embedding_provider: str = "openai",  # Embedding 提供商
) -> dict:
    """创建一个新的知识库。

    会同时在 Qdrant 和 Neo4j 中创建对应的存储空间。
    每个知识库完全隔离，互不影响。
    """
```

#### `kb_delete` -- 删除知识库

```python
@mcp.tool()
async def kb_delete(
    kb_name: str,       # 知识库名称
    confirm: bool = False, # 确认删除
) -> dict:
    """删除知识库及其所有数据（不可恢复）。
    confirm 必须为 True 才能执行删除。
    """
```

#### `kb_info` -- 知识库详情

```python
@mcp.tool()
async def kb_info(kb_name: str) -> dict:
    """获取知识库的详细信息。

    Returns:
        包含 name, description, document_count, chunk_count,
        entity_count, relation_count, embedding_model,
        qdrant_collection, created_at, last_updated 的详情
    """
```

#### `kb_ingest` -- 文档导入

```python
@mcp.tool()
async def kb_ingest(
    kb_name: str,           # 知识库名称
    file_path: str,         # 文件路径 (绝对路径)
    chunk_size: int = 512,  # 分块大小 (tokens)
    chunk_overlap: int = 64, # 块重叠 (tokens)
    extract_entities: bool = True,  # 是否自动提取实体到图谱
) -> dict:
    """将文档导入知识库。

    支持的格式：.md, .txt, .pdf
    流程：解析 -> 分块 -> Embedding -> 存入 Qdrant
    如果 extract_entities=True，还会自动提取实体和关系存入 Neo4j。

    Returns:
        导入结果，包含 doc_id, chunk_count, entity_count
    """
```

#### `kb_add_entity` -- 添加实体

```python
@mcp.tool()
async def kb_add_entity(
    kb_name: str,           # 知识库名称
    name: str,              # 实体名称
    entity_type: str = "concept",  # 实体类型
    properties: dict | None = None, # 附加属性
) -> dict:
    """向知识图谱添加实体节点。"""
```

#### `kb_add_relation` -- 添加关系

```python
@mcp.tool()
async def kb_add_relation(
    kb_name: str,           # 知识库名称
    source: str,            # 源实体名称或ID
    target: str,            # 目标实体名称或ID
    relation_type: str,     # 关系类型
    properties: dict | None = None, # 附加属性
) -> dict:
    """向知识图谱添加实体间关系。"""
```

### 2.3 MCP Resources

```python
@mcp.resource("kb://{kb_name}/info")
async def get_kb_info_resource(kb_name: str) -> str:
    """知识库信息资源"""

@mcp.resource("kb://{kb_name}/stats")
async def get_kb_stats_resource(kb_name: str) -> str:
    """知识库统计资源"""
```

---

## 3. 多知识库管理方案

### 3.1 知识库生命周期

```
创建 (kb_create)                    删除 (kb_delete)
    │                                    │
    ▼                                    ▼
┌─────────┐    导入文档     ┌─────────┐    搜索
│  EMPTY  │ ─────────────> │  READY  │ <──────── 查询请求
└─────────┘  (kb_ingest)   └─────────┘
```

### 3.2 存储隔离策略

**Qdrant 隔离**：Collection 级别隔离

```
Qdrant
├── collection: kb_yijing      # 独立的向量空间
│   ├── point: chunk_001
│   ├── point: chunk_002
│   └── ...
├── collection: kb_finance     # 完全独立
│   ├── point: chunk_001
│   └── ...
└── collection: kb_medical
    └── ...
```

**Neo4j 隔离**：Label 前缀隔离（兼容 Community Edition）

```
Neo4j
├── (:kb_yijing__Entity {name: "乾卦"})
│   ─[:kb_yijing__RELATED_TO]─>
│   (:kb_yijing__Entity {name: "天"})
│
├── (:kb_finance__Entity {name: "市盈率"})
│   ─[:kb_finance__RELATED_TO]─>
│   (:kb_finance__Entity {name: "估值"})
```

### 3.3 元数据注册表

知识库的元数据存储在 SQLite 文件中（`~/.kb-mcp/registry.db`）：

```sql
CREATE TABLE knowledge_bases (
    name        TEXT PRIMARY KEY,
    description TEXT,
    embedding_provider TEXT DEFAULT 'openai',
    embedding_model    TEXT DEFAULT 'text-embedding-3-small',
    embedding_dimension INTEGER DEFAULT 1536,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documents (
    id          TEXT PRIMARY KEY,
    kb_name     TEXT REFERENCES knowledge_bases(name),
    file_path   TEXT,
    file_name   TEXT,
    file_format TEXT,
    chunk_count INTEGER,
    status      TEXT DEFAULT 'indexed',
    indexed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.4 知识库切换

MCP Server 同时管理所有知识库，**不需要显式切换**。每个 MCP Tool 调用都通过 `kb_name` 参数指定目标知识库：

```python
# Agent 可以在一次会话中查询多个知识库
await kb_search(kb_name="yijing", query="乾卦")      # 查易经
await kb_search(kb_name="finance", query="市盈率")    # 查金融
await kb_search(kb_name="medical", query="气虚")      # 查医学
```

Claude Code Agent 根据当前任务上下文自动选择合适的知识库。

---

## 4. 图谱与向量的协作方式

### 4.1 场景划分

| 场景 | 推荐方式 | 原因 |
|------|----------|------|
| 概念模糊查找 | 向量搜索 | "和投资相关的概念" -- 语义匹配 |
| 精确实体查询 | 图谱查询 | "乾卦的错卦是什么" -- 关系遍历 |
| 多跳推理 | 图谱查询 | "A 影响 B，B 影响 C，那 A 对 C 的影响路径" |
| 文档段落检索 | 向量搜索 | 找到最相关的原始文档段落 |
| 综合分析 | 混合检索 | 需要同时获取语义相关性和结构关系 |
| 领域术语解释 | 向量 + 图谱 | 语义找到术语 + 图谱展开关联 |

### 4.2 混合查询流程

```
用户查询: "乾卦在事业方面的含义，以及相关的卦象关系"
                    │
                    ▼
        ┌───────────────────────┐
        │    Query Analysis     │
        │    分析查询意图        │
        └───────────┬───────────┘
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    ┌─────────┐ ┌────────┐ ┌──────────┐
    │ 向量路   │ │ 图谱路  │ │ 关键词路  │
    │         │ │        │ │          │
    │ Qdrant  │ │ Neo4j  │ │ Payload  │
    │ search  │ │ MATCH  │ │ filter   │
    │ top_k=10│ │ depth=2│ │ keywords │
    └────┬────┘ └───┬────┘ └────┬─────┘
         │          │           │
         ▼          ▼           ▼
    ┌─────────────────────────────────┐
    │        RRF Score Calculation    │
    │                                 │
    │  score(doc) = Σ 1/(60+rank_i)  │
    └───────────────┬─────────────────┘
                    │
                    ▼
    ┌─────────────────────────────────┐
    │     Merge & Deduplicate         │
    │     合并去重，取 Top-K           │
    └───────────────┬─────────────────┘
                    │
                    ▼
    返回: [
      {text: "乾：元亨利贞...", source: "vector", score: 0.052},
      {text: "乾卦错卦为坤...", source: "graph", score: 0.034},
      ...
    ]
```

### 4.3 图谱增强向量检索

图谱不仅作为独立检索路，还可以**增强向量检索的效果**：

1. **Query Expansion（查询扩展）**：
   - 从图谱中获取查询实体的邻居节点
   - 将邻居名称追加到查询文本中
   - 例："乾卦" -> "乾卦 天 刚健 乾 坤(错卦)"

2. **Result Reranking（结果重排）**：
   - 向量检索返回结果后，查询图谱中每个结果实体的关系
   - 与查询上下文相关的实体结果获得加分

3. **Context Enrichment（上下文丰富）**：
   - 向量检索命中文档块后，从图谱中补充该块中实体的关系信息
   - 返回给 Agent 的上下文更加完整

### 4.4 实体自动提取

文档导入时自动提取实体和关系的流程：

```
文档分块 ──> LLM 提取实体 ──> 去重/合并 ──> 写入 Neo4j
                │
                │ Prompt: "从以下文本中提取实体和关系，
                │         输出 JSON 格式: {entities: [...], relations: [...]}"
                │
                ▼
            结构化输出
            {
              "entities": [
                {"name": "乾卦", "type": "hexagram"},
                {"name": "天", "type": "concept"},
                {"name": "刚健", "type": "attribute"}
              ],
              "relations": [
                {"source": "乾卦", "target": "天", "type": "REPRESENTS"},
                {"source": "乾卦", "target": "刚健", "type": "HAS_ATTRIBUTE"}
              ]
            }
```

---

## 5. Docker 部署架构

### 5.1 docker-compose 设计

```yaml
# docker-compose.yml
# Knowledge Base MCP Server -- 完整部署
# 使用: docker compose up -d

services:
  # ──────────────────────────────────────
  # MCP Server (FastAPI + MCP)
  # ──────────────────────────────────────
  kb-mcp-server:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: kb-mcp-server
    ports:
      - "8100:8100"     # FastAPI 管理 API
      - "8101:8101"     # MCP Streamable HTTP 端点
    environment:
      # Qdrant
      QDRANT_URL: http://qdrant:6333
      # Neo4j
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: ${NEO4J_PASSWORD:-changeme}
      # Embedding
      EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER:-openai}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL:-text-embedding-3-small}
      # Server
      KB_MCP_HOST: 0.0.0.0
      KB_MCP_PORT: 8100
      KB_MCP_HTTP_PORT: 8101
      # 数据目录
      KB_MCP_DATA_DIR: /data
    volumes:
      - kb_mcp_data:/data
    depends_on:
      qdrant:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8100/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # ──────────────────────────────────────
  # Qdrant 向量数据库
  # ──────────────────────────────────────
  qdrant:
    image: qdrant/qdrant:v1.12.1
    container_name: kb-qdrant
    ports:
      - "6333:6333"     # REST API
      - "6334:6334"     # gRPC
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
      QDRANT__SERVICE__HTTP_PORT: 6333
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # ──────────────────────────────────────
  # Neo4j 图数据库
  # ──────────────────────────────────────
  neo4j:
    image: neo4j:5-community
    container_name: kb-neo4j
    ports:
      - "7474:7474"     # Web UI
      - "7687:7687"     # Bolt 协议
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-changeme}
      NEO4J_PLUGINS: '[]'
      NEO4J_server_memory_heap_max__size: "512m"
      NEO4J_server_memory_pagecache_size: "256m"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p ${NEO4J_PASSWORD:-changeme} 'RETURN 1'"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  kb_mcp_data:
  qdrant_data:
  neo4j_data:
  neo4j_logs:
```

### 5.2 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# 安装依赖
RUN uv sync --frozen --no-dev

# 复制源码
COPY src/ ./src/

# 创建数据目录
RUN mkdir -p /data

# 暴露端口
EXPOSE 8100 8101

# 启动
CMD ["uv", "run", "python", "-m", "kb_mcp_server"]
```

### 5.3 网络拓扑

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Network: kb-mcp-network (bridge)                    │
│                                                             │
│  ┌─────────────────┐                                       │
│  │  kb-mcp-server  │                                       │
│  │  :8100 (API)    │                                       │
│  │  :8101 (MCP)    │                                       │
│  └──────┬──┬───────┘                                       │
│         │  │                                                │
│    ┌────┘  └────┐                                          │
│    ▼            ▼                                          │
│  ┌──────────┐  ┌──────────┐                               │
│  │  qdrant  │  │  neo4j   │                               │
│  │  :6333   │  │  :7687   │                               │
│  └──────────┘  └──────────┘                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
    Host:8100      Host:6333      Host:7687
    (MCP Server)   (Qdrant UI)   (Neo4j UI)
```

### 5.4 启动命令

```bash
# 开发模式（前台运行，查看日志）
docker compose up

# 生产模式（后台运行）
docker compose up -d

# 查看日志
docker compose logs -f kb-mcp-server

# 停止
docker compose down

# 停止并清除数据
docker compose down -v
```

---

## 6. 配置方案

### 6.1 环境变量

```bash
# ===========================================
# Knowledge Base MCP Server 配置
# ===========================================

# ── Qdrant ──
QDRANT_URL=http://localhost:6333

# ── Neo4j ──
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# ── Embedding ──
EMBEDDING_PROVIDER=openai       # openai | fastembed
OPENAI_API_KEY=sk-xxx           # 使用 OpenAI 时必填
EMBEDDING_MODEL=text-embedding-3-small
# EMBEDDING_DIMENSION=1536      # 自动检测，通常不需要设置

# ── MCP Server ──
KB_MCP_HOST=127.0.0.1
KB_MCP_PORT=8100                # FastAPI 管理 API 端口
KB_MCP_HTTP_PORT=8101           # MCP Streamable HTTP 端口
KB_MCP_TRANSPORT=stdio          # stdio | streamable-http

# ── 数据目录 ──
KB_MCP_DATA_DIR=~/.kb-mcp      # 注册表数据库、上传文档存储

# ── 日志 ──
KB_MCP_LOG_LEVEL=INFO           # DEBUG | INFO | WARNING | ERROR

# ── 实体提取 (可选) ──
KB_MCP_EXTRACT_ENTITIES=true    # 导入文档时是否自动提取实体
KB_MCP_EXTRACT_LLM=deepseek     # 用于实体提取的 LLM
DEEPSEEK_API_KEY=sk-xxx         # LLM API Key
```

### 6.2 Claude Code 全局配置

在 `~/.claude/settings.json` 中配置 MCP Server：

**本地模式（stdio）**：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/kb-mcp-server",
        "python",
        "-m",
        "kb_mcp_server"
      ],
      "env": {
        "QDRANT_URL": "http://localhost:6333",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "EMBEDDING_PROVIDER": "openai",
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

### 6.3 项目级配置（可选）

在特定项目的 `.claude/settings.json` 中覆盖默认配置：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://localhost:8101/mcp",
      "env": {
        "DEFAULT_KB": "yijing"
      }
    }
  }
}
```

---

## 7. 项目目录结构

```
kb-mcp-server/
├── pyproject.toml                    # uv 项目配置
├── uv.lock                          # 依赖锁文件
├── Dockerfile                        # MCP Server 镜像
├── docker-compose.yml                # 完整部署配置
├── .env.example                      # 环境变量模板
├── README.md                         # 项目文档
├── docs/
│   └── architecture.md               # 本文档
│
├── src/
│   └── kb_mcp_server/
│       ├── __init__.py
│       ├── __main__.py               # 入口: python -m kb_mcp_server
│       ├── config.py                 # 配置加载 (Pydantic Settings)
│       │
│       ├── mcp/                      # MCP 协议层
│       │   ├── __init__.py
│       │   ├── server.py             # FastMCP 实例定义
│       │   ├── tools.py              # MCP Tools 实现
│       │   └── resources.py          # MCP Resources 实现
│       │
│       ├── core/                     # 核心业务逻辑
│       │   ├── __init__.py
│       │   ├── orchestrator.py       # 混合检索编排 (RRF)
│       │   ├── kb_manager.py         # 知识库 CRUD 管理
│       │   ├── chunker.py            # 文档分块策略
│       │   └── entity_extractor.py   # 实体自动提取
│       │
│       ├── parsers/                  # 文档解析层
│       │   ├── __init__.py
│       │   ├── base.py               # DocumentParser Protocol
│       │   ├── markdown_parser.py    # Markdown 解析
│       │   ├── pdf_parser.py         # PDF 解析
│       │   └── text_parser.py        # 纯文本解析
│       │
│       ├── embedding/                # Embedding 层
│       │   ├── __init__.py
│       │   ├── base.py               # EmbeddingProvider Protocol
│       │   ├── openai_provider.py    # OpenAI Embedding
│       │   └── fastembed_provider.py # FastEmbed 本地 Embedding
│       │
│       ├── storage/                  # 存储适配层
│       │   ├── __init__.py
│       │   ├── qdrant_adapter.py     # Qdrant 向量存储
│       │   ├── neo4j_adapter.py      # Neo4j 图存储
│       │   └── registry.py           # SQLite 元数据注册表
│       │
│       ├── models/                   # 数据模型
│       │   ├── __init__.py
│       │   ├── chunk.py              # Chunk, ParsedChunk
│       │   ├── entity.py             # Entity, Relation
│       │   ├── search.py             # SearchResult, HybridSearchResult
│       │   └── knowledge_base.py     # KnowledgeBaseInfo
│       │
│       └── api/                      # FastAPI 管理 API (可选)
│           ├── __init__.py
│           └── app.py                # 管理端 API 路由
│
├── tests/
│   ├── conftest.py
│   ├── test_mcp_tools.py
│   ├── test_chunker.py
│   ├── test_parsers.py
│   ├── test_embedding.py
│   ├── test_qdrant_adapter.py
│   ├── test_neo4j_adapter.py
│   └── test_orchestrator.py
│
└── scripts/
    ├── seed_yijing.py                # 导入易经知识库示例
    └── health_check.py               # 健康检查脚本
```

### 7.1 pyproject.toml

```toml
[project]
name = "kb-mcp-server"
version = "1.0.0"
description = "Knowledge Base MCP Server for Claude Code Agent"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.0.0",
    "qdrant-client>=1.18.0",
    "neo4j>=5.0.0",
    "openai>=1.50.0",
    "fastembed>=0.8.0",
    "pymupdf>=1.24.0",
    "structlog>=24.0.0",
    "aiosqlite>=0.20.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 8. 开发路线图

### Phase 1 -- MVP

| 任务 | 说明 |
|------|------|
| 项目脚手架 | uv init, 项目结构, pyproject.toml |
| MCP Server 框架 | FastMCP 实例, stdio 传输 |
| Embedding 层 | OpenAI Provider + FastEmbed Provider |
| Qdrant Adapter | Collection 管理, 向量 CRUD, 搜索 |
| 文档解析 | Markdown + TXT 解析器 |
| 分块器 | 滑动窗口分块 |
| `kb_search` Tool | 向量语义搜索 |
| `kb_create/list/info` Tools | 知识库基础管理 |
| `kb_ingest` Tool | 文档导入 |
| Docker Compose | Qdrant 单容器部署 |

### Phase 2 -- 图谱集成

| 任务 | 说明 |
|------|------|
| Neo4j Adapter | 节点/边 CRUD, Cypher 查询 |
| 实体提取 | LLM 辅助的实体/关系提取 |
| `kb_graph_query` Tool | 图谱关系查询 |
| `kb_add_entity/relation` Tools | 手动图谱写入 |
| `kb_hybrid_search` Tool | 三路混合检索 + RRF |
| Docker Compose | 添加 Neo4j 容器 |

### Phase 3 -- 生产化

| 任务 | 说明 |
|------|------|
| PDF 解析 | PyMuPDF 解析器 |
| Streamable HTTP | MCP 远程传输 |
| FastAPI 管理 API | REST API 管理端点 |
| 健康检查 | /health, /ready 端点 |
| 日志与监控 | structlog, 请求指标 |
| 测试覆盖 | 单元测试 + 集成测试 |
| 文档完善 | README, 部署指南 |

### Phase 4 -- 高级特性

| 任务 | 说明 |
|------|------|
| 查询扩展 | 图谱增强向量检索 |
| 结果重排 | Cross-encoder 重排序 |
| 增量更新 | 文档变更检测，增量索引 |
| 多模态 | 图片 OCR 支持 |
| 权限控制 | 知识库级别的访问控制 |
| 监控面板 | Grafana 仪表盘 |

---

## 附录

### A. 与现有 YI-AI 系统的关系

本 MCP Server 是**独立项目**，但可以复用 YI-AI 系统中已有的设计模式：

| 组件 | YI-AI 实现 | MCP Server 设计 |
|------|-----------|----------------|
| 向量后端 | `ai/adapters/qdrant_adapter.py` | `storage/qdrant_adapter.py` (增强版, 支持多 Collection) |
| 图谱后端 | `ai/adapters/neo4j_adapter.py` | `storage/neo4j_adapter.py` (增强版, 支持多 Database) |
| Embedding | `ai/embedding.py` (FastEmbed) | `embedding/` (策略模式, 支持 OpenAI) |
| 知识图谱 | `ai/knowledge_graph.py` (内存图) | `storage/neo4j_adapter.py` (持久化图) |
| RAG 融合 | `ai/rag_fusion.py` (三路 RRF) | `core/orchestrator.py` (三路 RRF, 增强版) |
| 分块 | 无（静态数据） | `core/chunker.py` (通用分块) |
| MCP 协议 | 无 | `mcp/` (全新) |

### B. 性能预期

| 操作 | 预期延迟 | 瓶颈 |
|------|----------|------|
| 向量搜索 (Qdrant) | < 50ms | 网络延迟 |
| 图谱查询 (Neo4j, depth=2) | < 100ms | 查询复杂度 |
| 混合检索 (三路 RRF) | < 200ms | 三路并行，取最慢 |
| Embedding (OpenAI API) | 200-500ms | API 延迟 |
| 文档导入 (单文档) | 2-10s | 取决于文档大小和 API 速度 |
| 实体提取 (LLM) | 1-5s | LLM API 延迟 |

### C. 安全考量

1. **API Key 保护**：所有密钥通过环境变量传入，不硬编码
2. **Neo4j 认证**：必须设置密码，禁止空密码
3. **Qdrant 访问**：生产环境建议启用 API Key 认证
4. **输入校验**：所有 MCP Tool 参数使用 Pydantic 严格校验
5. **Cypher 注入防护**：Neo4j 查询使用参数化，禁止字符串拼接
6. **文件路径校验**：`kb_ingest` 校验文件路径合法性，防止路径穿越
7. **删除确认**：`kb_delete` 需要 `confirm=True`，防止误删
