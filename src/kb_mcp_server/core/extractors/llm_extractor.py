"""LLM 通用实体提取器 - 适用于任何领域"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
import structlog

from ...config import Settings
from ...models.entity import Entity, Relation
from .base import EntityExtractorBase, ExtractionResult

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
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "default_model": "mimo-v2.5",
    },
}

# ── 通用提取 Prompt ──
_EXTRACTION_PROMPT = """\
你是一个实体和关系提取专家。请从以下文本中提取实体（概念、事物、人物、术语等）以及它们之间的关系。

要求：
1. 实体名称必须是文本中出现的原文或其规范化形式
2. 实体类型包括：concept（概念）、person（人物）、org（组织）、place（地点）、event（事件）、document（文献）、term（术语）、method（方法）、tool（工具）等
3. 关系类型使用英文大写蛇形命名，如：CONTAINS、BELONGS_TO、RELATED_TO、MENTIONS、DERIVES_FROM、USES、CAUSES 等
4. 为每个实体和关系提供简洁的中文描述
5. 仅提取文本中明确提及或可直接推断的实体和关系
6. 尽量提取有价值的领域知识实体，避免提取太泛的词（如"问题"、"方法"）

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

class LLMEntityExtractor(EntityExtractorBase):
    """LLM 通用实体提取器

    使用 LLM 从文本中提取实体和关系，适用于任何领域。
    支持 OpenAI、DeepSeek、MIMO 等兼容 OpenAI API 的提供商。
    """

    def __init__(
        self,
        settings: Settings,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """初始化 LLM 实体提取器

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

        # 获取 base_url（优先使用用户配置的）
        self._base_url = settings.llm_base_url or settings.mimo_base_url or provider_config["base_url"]

        # 获取模型名称（优先使用用户配置的）
        self._model = settings.llm_model or provider_config["default_model"]

        # 获取 API Key
        api_key = self._resolve_api_key(settings, provider_name)
        if not api_key:
            raise ValueError(f"未配置 {provider_name} 的 API Key")

        self._api_key = api_key

        logger.info(
            "LLMEntityExtractor 初始化",
            provider=provider_name,
            model=self._model,
            base_url=self._base_url,
        )

    @staticmethod
    def _resolve_api_key(settings: Settings, provider: str) -> str | None:
        """根据提供商解析 API Key"""
        if settings.llm_api_key:
            return settings.llm_api_key
        if provider == "openai":
            return settings.openai_api_key
        if provider == "deepseek":
            return settings.deepseek_api_key
        if provider == "mimo":
            return settings.mimo_api_key
        return None

    @staticmethod
    def _get_or_create_entity_id(name: str, name_to_id: dict[str, str]) -> str:
        """获取实体 ID（去重）"""
        normalized = name.strip()
        if normalized in name_to_id:
            return name_to_id[normalized]
        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        name_to_id[normalized] = entity_id
        return entity_id

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM API"""
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
                logger.warning("LLM API HTTP 错误", attempt=attempt, status=status, error=str(exc))
                if status == 429 or status >= 500:
                    continue
                raise RuntimeError(f"LLM API 客户端错误 (HTTP {status}): {exc}") from exc

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("LLM API 请求错误", attempt=attempt, error=str(exc))
                continue

            except Exception as exc:
                last_error = exc
                logger.warning("LLM API 未知错误", attempt=attempt, error=str(exc))
                continue

        raise RuntimeError(f"LLM API 调用失败（已重试 {self._max_retries} 次）: {last_error}")

    def _parse_llm_response(self, raw: str) -> dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        text = raw.strip()

        # 简化 markdown 代码块剥离：用 regex 替代复杂的行迭代
        text = re.sub(r"^```(?:\w*)\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 返回的 JSON 格式无效: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"LLM 返回的数据不是字典类型: {type(data)}")

        return {
            "entities": data.get("entities", []),
            "relations": data.get("relations", []),
        }

    def _convert_to_entities(self, raw_entities: list[dict[str, Any]], name_to_id: dict[str, str]) -> list[Entity]:
        """将原始实体数据转换为 Entity 对象（含去重）"""
        entities: list[Entity] = []
        seen: set[str] = set()

        for raw in raw_entities:
            name = raw.get("name", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)

            entity_id = self._get_or_create_entity_id(name, name_to_id)
            entity_type = raw.get("type", "concept")
            description = raw.get("description", "")

            properties: dict[str, Any] = {}
            if description:
                properties["description"] = description

            entities.append(
                Entity(id=entity_id, name=name, entity_type=entity_type, properties=properties)
            )

        return entities

    def _convert_to_relations(
        self,
        raw_relations: list[dict[str, Any]],
        valid_entity_names: set[str],
        name_to_id: dict[str, str],
    ) -> list[Relation]:
        """将原始关系数据转换为 Relation 对象"""
        relations: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()

        for raw in raw_relations:
            source_name = raw.get("source", "").strip()
            target_name = raw.get("target", "").strip()
            relation_type = raw.get("type", "RELATED_TO")

            if not source_name or not target_name:
                continue
            if source_name not in valid_entity_names or target_name not in valid_entity_names:
                continue

            dedup_key = (source_name, target_name, relation_type)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            source_id = self._get_or_create_entity_id(source_name, name_to_id)
            target_id = self._get_or_create_entity_id(target_name, name_to_id)
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

    async def _extract_single(self, text: str, name_to_id: dict[str, str]) -> ExtractionResult:
        """从单个文本提取实体和关系（内部方法，共享 name_to_id）"""
        prompt = _EXTRACTION_PROMPT.format(text=text)
        raw_response = await self._call_llm(prompt)
        parsed = self._parse_llm_response(raw_response)

        entities = self._convert_to_entities(parsed["entities"], name_to_id)
        valid_names = {e.name for e in entities}
        relations = self._convert_to_relations(parsed["relations"], valid_names, name_to_id)

        return ExtractionResult(entities=entities, relations=relations)

    async def extract(self, text: str) -> ExtractionResult:
        """从文本中提取实体和关系"""
        if not text or not text.strip():
            return ExtractionResult(entities=[], relations=[])

        name_to_id: dict[str, str] = {}

        logger.info("开始 LLM 实体提取", text_length=len(text), provider=self._provider)
        result = await self._extract_single(text, name_to_id)

        logger.info(
            "LLM 实体提取完成",
            entity_count=len(result.entities),
            relation_count=len(result.relations),
        )

        return result

    async def extract_from_chunks(self, chunks: list[str]) -> ExtractionResult:
        """从多个文本块中提取实体和关系（逐块提取后合并去重）

        所有块共享同一个 name_to_id 映射，确保跨块的同名实体获得一致的 ID。
        不调用 self.extract()，直接调用内部方法保持一致性。
        """
        if not chunks:
            return ExtractionResult(entities=[], relations=[])

        # 跨块共享的实体名称 -> ID 映射
        name_to_id: dict[str, str] = {}

        all_entities: list[Entity] = []
        all_relations: list[Relation] = []
        seen_entity_names: set[str] = set()
        seen_relation_keys: set[tuple[str, str, str]] = set()

        for i, chunk in enumerate(chunks):
            logger.info("处理分块", chunk_index=i + 1, chunk_total=len(chunks))

            try:
                result = await self._extract_single(chunk, name_to_id)
            except Exception as exc:
                logger.error("分块提取失败，跳过", chunk_index=i, error=str(exc))
                continue

            # 合并实体（去重）
            for entity in result.entities:
                if entity.name not in seen_entity_names:
                    seen_entity_names.add(entity.name)
                    all_entities.append(entity)

            # 合并关系（去重）
            for relation in result.relations:
                dedup_key = (relation.source_id, relation.target_id, relation.relation_type)
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
