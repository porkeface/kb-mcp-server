"""提取器工厂 - 根据配置创建合适的提取器"""

from __future__ import annotations

import structlog

from ...config import Settings
from .base import EntityExtractorBase
from .llm_extractor import LLMEntityExtractor
from .rule_extractor import RuleBasedExtractor, RuleConfig
from .yijing_rules import YI_JING_RULES

logger = structlog.get_logger()

# ── 预定义的规则配置 ──
BUILTIN_RULE_CONFIGS: dict[str, RuleConfig] = {
    "yijing": YI_JING_RULES,
}


def create_extractor(
    settings: Settings,
    extractor_type: str = "auto",
    rule_config: RuleConfig | None = None,
) -> EntityExtractorBase:
    """创建实体提取器

    Args:
        settings: 应用配置
        extractor_type: 提取器类型
            - "auto": 自动选择（优先规则，无配置时用 LLM）
            - "llm": 使用 LLM 提取
            - "rule": 使用规则提取
            - "none": 不提取
        rule_config: 规则配置（仅 rule 类型需要）

    Returns:
        EntityExtractorBase 实例

    Raises:
        ValueError: 不支持的提取器类型或配置
    """
    if extractor_type == "none":
        logger.info("实体提取已禁用")
        return _NoopExtractor()

    if extractor_type == "llm":
        return LLMEntityExtractor(settings)

    if extractor_type == "rule":
        if rule_config is None:
            # 尝试从预定义配置中查找
            kb_name = getattr(settings, "kb_mcp_default_kb", None)
            if kb_name and kb_name in BUILTIN_RULE_CONFIGS:
                rule_config = BUILTIN_RULE_CONFIGS[kb_name]
            else:
                raise ValueError("使用规则提取器必须提供 rule_config")
        return RuleBasedExtractor(rule_config)

    if extractor_type == "auto":
        # 自动选择：如果有 LLM API Key 则用 LLM，否则用规则
        if settings.llm_api_key or settings.openai_api_key:
            logger.info("自动选择 LLM 提取器")
            return LLMEntityExtractor(settings)
        else:
            logger.info("自动选择规则提取器（无 LLM API Key）")
            return RuleBasedExtractor(YI_JING_RULES)

    raise ValueError(f"不支持的提取器类型: {extractor_type}")


def get_rule_config(name: str) -> RuleConfig | None:
    """获取预定义的规则配置

    Args:
        name: 配置名称

    Returns:
        RuleConfig 或 None
    """
    return BUILTIN_RULE_CONFIGS.get(name)


def register_rule_config(name: str, config: RuleConfig) -> None:
    """注册自定义规则配置

    Args:
        name: 配置名称
        config: 规则配置
    """
    BUILTIN_RULE_CONFIGS[name] = config
    logger.info("规则配置已注册", name=name)


class _NoopExtractor(EntityExtractorBase):
    """空提取器 - 不提取任何实体"""

    async def extract(self, text: str):
        from .base import ExtractionResult
        return ExtractionResult(entities=[], relations=[])

    async def extract_from_chunks(self, chunks: list[str]):
        from .base import ExtractionResult
        return ExtractionResult(entities=[], relations=[])
