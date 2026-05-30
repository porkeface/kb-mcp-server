"""实体提取器 - 使用 LLM 从文本中提取知识图谱实体和关系"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from ..config import Settings
from ..models.chunk import Chunk
from ..models.entity import Entity, Relation

logger = structlog.get_logger()

# ── 默认配置 ──

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_TEMPERATURE = 0.1

# ── LLM 提供商配置 ──

_PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "mimo": {
        "base_url": "https://api.mimo.ai/v1",  # 小米 MIMO API 地址（需要确认）
        "default_model": "mimo-chat",
    },
}


# ── 提取 Prompt ──

_EXTRACTION_PROMPT = """\
你是一个实体和关系提取专家。请从以下文本中提取实体（概念、事物、人物等）以及它们之间的关系。

要求：
1. 实体名称必须是文本中出现的原文或其规范化形式
2. 实体类型包括：concept（概念）、hexagram（卦象）、person（人物）、org（组织）、place（地点）、event（事件）、document（文献）、symbol（符号）等
3. 关系类型使用英文大写蛇形命名，如：REPRESENTS、CONTAINS、BELONGS_TO、RELATED_TO、MENTIONS、DERIVES_FROM 等
4. 为每个实体和关系提供简洁的中文描述
5. 仅提取文本中明确提及或可直接推断的实体和关系

请严格按以下 JSON 格式返回，不要包含任何其他文本：

```json
{{
  "entities": [
    {{"name": "实体名", "type": "实体类型", "description": "简洁描述"}}
  ],
  "relations": [
    {{"source": "源实体名", "target": "目标实体名", "type": "关系类型", "description": "关系描述"}}
  ]
}}
```

文本内容：
{text}
"""


@dataclass(frozen=True)
class ExtractionResult:
    """实体提取结果"""

    entities: list[Entity]
    relations: list[Relation]


class EntityExtractor:
    """实体提取器

    使用 LLM 从文本中提取知识图谱的实体和关系。
    支持 OpenAI 和 DeepSeek 等兼容 OpenAI API 的提供商。
    """

    def __init__(
        self,
        settings: Settings,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """初始化实体提取器

        Args:
            settings: 应用配置
            max_retries: 最大重试次数
            timeout: HTTP 请求超时（秒）
        """
        self._max_retries = max_retries
        self._timeout = timeout

        # 根据配置选择 LLM 提供商
        provider_name = settings.kb_mcp_extract_llm.lower()
        provider_config = _PROVIDER_CONFIGS.get(provider_name)
        if not provider_config:
            raise ValueError(
                f"不支持的 LLM 提供商: {provider_name}，"
                f"支持的提供商: {list(_PROVIDER_CONFIGS.keys())}"
            )

        self._provider = provider_name
        self._base_url = provider_config["base_url"]
        self._model = provider_config["default_model"]

        # 获取 API Key
        api_key = self._resolve_api_key(settings, provider_name)
        if not api_key:
            raise ValueError(f"未配置 {provider_name} 的 API Key")

        self._api_key = api_key

        # 实体名称 -> ID 映射（用于去重）
        self._entity_name_to_id: dict[str, str] = {}

        logger.info(
            "EntityExtractor 初始化",
            provider=provider_name,
            model=self._model,
        )

    @staticmethod
    def _resolve_api_key(settings: Settings, provider: str) -> str | None:
        """根据提供商解析 API Key

        Args:
            settings: 应用配置
            provider: 提供商名称

        Returns:
            API Key，未配置返回 None
        """
        if provider == "openai":
            return settings.openai_api_key
        if provider == "deepseek":
            return settings.deepseek_api_key
        return None

    def _reset_entity_map(self) -> None:
        """重置实体名称映射（每次新的提取任务前调用）"""
        self._entity_name_to_id.clear()

    def _get_or_create_entity_id(self, name: str) -> str:
        """获取实体 ID（去重逻辑）

        如果同名实体已存在，返回已有 ID；否则生成新 ID。

        Args:
            name: 实体名称

        Returns:
            实体 ID
        """
        normalized = name.strip()
        if normalized in self._entity_name_to_id:
            return self._entity_name_to_id[normalized]

        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        self._entity_name_to_id[normalized] = entity_id
        return entity_id

    def _build_prompt(self, text: str) -> str:
        """构建提取提示词

        Args:
            text: 待提取的文本

        Returns:
            完整的提示词
        """
        return _EXTRACTION_PROMPT.format(text=text)

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM API

        Args:
            prompt: 用户提示词

        Returns:
            LLM 响应文本

        Raises:
            RuntimeError: API 调用失败且重试耗尽
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个精准的实体和关系提取工具，只返回 JSON 格式的结果。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": _DEFAULT_TEMPERATURE,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()

                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    logger.debug("LLM 调用成功", attempt=attempt, provider=self._provider)
                    return content

            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                logger.warning(
                    "LLM API HTTP 错误",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    status=status,
                    provider=self._provider,
                    error=str(exc),
                )
                # 429 (限流) 或 5xx 服务端错误可重试
                if status == 429 or status >= 500:
                    continue
                # 4xx 客户端错误不重试
                raise RuntimeError(
                    f"LLM API 客户端错误 (HTTP {status}): {exc}"
                ) from exc

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "LLM API 请求错误",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    provider=self._provider,
                    error=str(exc),
                )
                continue

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM API 未知错误",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    provider=self._provider,
                    error=str(exc),
                )
                continue

        raise RuntimeError(
            f"LLM API 调用失败（已重试 {self._max_retries} 次）: {last_error}"
        )

    def _parse_llm_response(self, raw: str) -> dict[str, Any]:
        """解析 LLM 返回的 JSON

        Args:
            raw: LLM 原始响应文本

        Returns:
            解析后的字典，包含 entities 和 relations

        Raises:
            ValueError: JSON 解析失败或格式不符合预期
        """
        text = raw.strip()

        # 处理可能被 markdown 代码块包裹的情况
        if text.startswith("```"):
            # 去掉首尾的 ``` 行
            lines = text.split("\n")
            # 找到第一个 ``` 和最后一个 ```
            start_idx = 0
            end_idx = len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith("```") and start_idx == 0:
                    start_idx = i + 1
                elif line.strip() == "```" and i > start_idx:
                    end_idx = i
            text = "\n".join(lines[start_idx:end_idx])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 返回的 JSON 格式无效: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"LLM 返回的数据不是字典类型: {type(data)}")

        entities_raw = data.get("entities", [])
        relations_raw = data.get("relations", [])

        if not isinstance(entities_raw, list):
            raise ValueError(f"entities 字段不是列表: {type(entities_raw)}")
        if not isinstance(relations_raw, list):
            raise ValueError(f"relations 字段不是列表: {type(relations_raw)}")

        return {"entities": entities_raw, "relations": relations_raw}

    def _convert_to_entities(self, raw_entities: list[dict[str, Any]]) -> list[Entity]:
        """将原始实体数据转换为 Entity 对象（含去重）

        Args:
            raw_entities: LLM 返回的原始实体列表

        Returns:
            去重后的 Entity 对象列表
        """
        entities: list[Entity] = []
        seen: set[str] = set()

        for raw in raw_entities:
            name = raw.get("name", "").strip()
            if not name:
                logger.warning("跳过无名称实体", raw=raw)
                continue

            # 去重：同名实体只保留第一个
            normalized_name = name
            if normalized_name in seen:
                logger.debug("跳过重复实体", name=name)
                continue
            seen.add(normalized_name)

            entity_id = self._get_or_create_entity_id(name)
            entity_type = raw.get("type", "concept")
            description = raw.get("description", "")

            properties: dict[str, Any] = {}
            if description:
                properties["description"] = description

            entities.append(
                Entity(
                    id=entity_id,
                    name=name,
                    entity_type=entity_type,
                    properties=properties,
                )
            )

        return entities

    def _convert_to_relations(
        self,
        raw_relations: list[dict[str, Any]],
        valid_entity_names: set[str],
    ) -> list[Relation]:
        """将原始关系数据转换为 Relation 对象

        Args:
            raw_relations: LLM 返回的原始关系列表
            valid_entity_names: 有效的实体名称集合（用于过滤无效关系）

        Returns:
            Relation 对象列表
        """
        relations: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()

        for raw in raw_relations:
            source_name = raw.get("source", "").strip()
            target_name = raw.get("target", "").strip()
            relation_type = raw.get("type", "RELATED_TO")

            if not source_name or not target_name:
                logger.warning("跳过无源/目标关系", raw=raw)
                continue

            # 验证实体存在
            if source_name not in valid_entity_names:
                logger.debug(
                    "跳过关系：源实体不存在",
                    source=source_name,
                    relation_type=relation_type,
                )
                continue
            if target_name not in valid_entity_names:
                logger.debug(
                    "跳过关系：目标实体不存在",
                    target=target_name,
                    relation_type=relation_type,
                )
                continue

            # 去重
            dedup_key = (source_name, target_name, relation_type)
            if dedup_key in seen:
                logger.debug(
                    "跳过重复关系",
                    source=source_name,
                    target=target_name,
                    type=relation_type,
                )
                continue
            seen.add(dedup_key)

            source_id = self._get_or_create_entity_id(source_name)
            target_id = self._get_or_create_entity_id(target_name)
            description = raw.get("description", "")

            properties: dict[str, Any] = {}
            if description:
                properties["description"] = description

            relations.append(
                Relation(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                    properties=properties,
                )
            )

        return relations

    async def extract(self, text: str) -> ExtractionResult:
        """从文本中提取实体和关系

        Args:
            text: 待提取的文本内容

        Returns:
            ExtractionResult 包含实体列表和关系列表

        Raises:
            ValueError: 文本为空或 LLM 返回格式无效
            RuntimeError: LLM API 调用失败
        """
        if not text or not text.strip():
            raise ValueError("待提取文本不能为空")

        self._reset_entity_map()

        prompt = self._build_prompt(text)
        logger.info("开始实体提取", text_length=len(text), provider=self._provider)

        raw_response = await self._call_llm(prompt)
        parsed = self._parse_llm_response(raw_response)

        entities = self._convert_to_entities(parsed["entities"])
        valid_names = {e.name for e in entities}
        relations = self._convert_to_relations(parsed["relations"], valid_names)

        logger.info(
            "实体提取完成",
            entity_count=len(entities),
            relation_count=len(relations),
        )

        return ExtractionResult(entities=entities, relations=relations)

    async def extract_from_chunks(
        self,
        chunks: list[Chunk],
    ) -> ExtractionResult:
        """从分块列表中提取实体和关系

        逐块提取后合并去重。所有块共享同一个实体映射，
        确保跨块的同名实体被正确关联。

        Args:
            chunks: 文档分块列表

        Returns:
            ExtractionResult 包含合并去重后的实体列表和关系列表
        """
        if not chunks:
            return ExtractionResult(entities=[], relations=[])

        self._reset_entity_map()

        all_entities: list[Entity] = []
        all_relations: list[Relation] = []
        seen_entity_names: set[str] = set()
        seen_relation_keys: set[tuple[str, str, str]] = set()

        for i, chunk in enumerate(chunks):
            logger.info(
                "处理分块",
                chunk_index=i + 1,
                chunk_total=len(chunks),
                text_length=len(chunk.text),
            )

            try:
                result = await self.extract(chunk.text)
            except Exception as exc:
                logger.error(
                    "分块提取失败，跳过",
                    chunk_index=i,
                    error=str(exc),
                )
                continue

            # 合并实体（去重）
            for entity in result.entities:
                if entity.name not in seen_entity_names:
                    seen_entity_names.add(entity.name)
                    all_entities.append(entity)

            # 合并关系（去重）
            for relation in result.relations:
                dedup_key = (
                    relation.source_id,
                    relation.target_id,
                    relation.relation_type,
                )
                if dedup_key not in seen_relation_keys:
                    seen_relation_keys.add(dedup_key)
                    all_relations.append(relation)

        logger.info(
            "分块提取完成",
            chunk_count=len(chunks),
            total_entities=len(all_entities),
            total_relations=len(all_relations),
        )

        return ExtractionResult(entities=all_entities, relations=all_relations)
