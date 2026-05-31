"""易学实体提取器 - 基于规则的快速提取（无需 LLM）"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import structlog

from ..models.entity import Entity, Relation

logger = structlog.get_logger()


# ── 八卦 ──
BAGUA = ["乾", "坤", "震", "巽", "坎", "离", "艮", "兑"]

# ── 六十四卦（名称列表） ──
HEXAGRAM_NAMES = [
    "乾", "坤", "屯", "蒙", "需", "讼", "师", "比",
    "小畜", "履", "泰", "否", "同人", "大有", "谦", "豫",
    "随", "蛊", "临", "观", "噬嗑", "贲", "剥", "复",
    "无妄", "大畜", "颐", "大过", "坎", "离", "咸", "恒",
    "遯", "大壮", "晋", "明夷", "家人", "睽", "蹇", "解",
    "损", "益", "夬", "姤", "萃", "升", "困", "井",
    "革", "鼎", "震", "艮", "渐", "归妹", "丰", "旅",
    "巽", "兑", "涣", "节", "中孚", "小过", "既济", "未济",
]

# ── 五行 ──
WUXING = ["金", "木", "水", "火", "土"]

# ── 六亲 ──
LIUQIN = ["父母", "兄弟", "子孙", "妻财", "官鬼"]

# ── 六神 ──
LIUSHEN = ["青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武"]

# ── 天干 ──
TIANGAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

# ── 地支 ──
DIZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# ── 爻位 ──
YAO_POSITIONS = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]

# ── 关键概念 ──
CONCEPTS = [
    "世爻", "应爻", "用神", "原神", "忌神", "仇神",
    "飞神", "伏神", "动爻", "变爻", "静爻",
    "月建", "日辰", "旺", "相", "休", "囚", "死",
    "生", "克", "冲", "合", "刑", "害",
    "进神", "退神", "反吟", "伏吟", "旬空", "月破",
    "墓", "绝", "长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养",
]

# ── 文献名称 ──
DOCUMENTS = [
    "周易", "易经", "十翼", "彖传", "象传", "系辞", "文言", "说卦", "序卦", "杂卦",
    "卜筮正宗", "增删卜易", "火珠林", "梅花易数", "焦氏易林", "黄金策",
    "京氏易传", "易隐", "易冒", "易林补遗", "天玄赋", "千金赋",
    "高岛易断",
]


@dataclass(frozen=True)
class ExtractionResult:
    """实体提取结果"""
    entities: list[Entity]
    relations: list[Relation]


class YijingExtractor:
    """易学实体提取器

    使用规则匹配从文本中提取易学实体和关系，无需 LLM。
    适用于：卦名、五行、六亲、六神、天干地支、概念、文献等。
    """

    def __init__(self) -> None:
        # 实体名称 -> Entity 映射（去重）
        self._entity_map: dict[str, Entity] = {}
        # 关系去重
        self._relation_keys: set[tuple[str, str, str]] = set()
        self._relations: list[Relation] = []

    def _reset(self) -> None:
        """重置状态"""
        self._entity_map.clear()
        self._relation_keys.clear()
        self._relations.clear()

    def _get_or_create_entity(
        self,
        name: str,
        entity_type: str,
        description: str = "",
    ) -> Entity:
        """获取或创建实体（去重）"""
        if name in self._entity_map:
            return self._entity_map[name]

        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        props = {}
        if description:
            props["description"] = description

        entity = Entity(
            id=entity_id,
            name=name,
            entity_type=entity_type,
            properties=props,
        )
        self._entity_map[name] = entity
        return entity

    def _add_relation(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        description: str = "",
    ) -> None:
        """添加关系（去重）"""
        key = (source_name, target_name, rel_type)
        if key in self._relation_keys:
            return
        self._relation_keys.add(key)

        source = self._entity_map.get(source_name)
        target = self._entity_map.get(target_name)
        if not source or not target:
            return

        props = {}
        if description:
            props["description"] = description

        self._relations.append(
            Relation(
                source_id=source.id,
                target_id=target.id,
                relation_type=rel_type,
                properties=props,
            )
        )

    def _extract_pattern_matches(
        self,
        text: str,
        patterns: list[str],
        entity_type: str,
        description_prefix: str = "",
    ) -> list[str]:
        """从文本中提取匹配的模式"""
        found = []
        for pattern in patterns:
            # 使用词边界匹配
            if re.search(rf"(?:^|[，。、；\s]){re.escape(pattern)}(?:$|[，。、；\s])", text):
                desc = f"{description_prefix}{pattern}" if description_prefix else ""
                self._get_or_create_entity(pattern, entity_type, desc)
                found.append(pattern)
        return found

    def extract(self, text: str) -> ExtractionResult:
        """从文本中提取易学实体和关系

        Args:
            text: 待提取的文本

        Returns:
            ExtractionResult 包含实体列表和关系列表
        """
        self._reset()
        self._extract_internal(text)

        entities = list(self._entity_map.values())
        relations = self._relations

        logger.info(
            "易学实体提取完成",
            entity_count=len(entities),
            relation_count=len(relations),
        )

        return ExtractionResult(entities=entities, relations=relations)

    def extract_from_chunks(self, chunks: list[str]) -> ExtractionResult:
        """从多个文本块中提取实体和关系

        Args:
            chunks: 文本块列表

        Returns:
            合并后的 ExtractionResult
        """
        self._reset()

        for chunk in chunks:
            # 不调用 self.extract()（会重置状态），直接执行提取逻辑
            self._extract_internal(chunk)

        entities = list(self._entity_map.values())
        relations = self._relations

        logger.info(
            "分块提取完成",
            chunk_count=len(chunks),
            total_entities=len(entities),
            total_relations=len(relations),
        )

        return ExtractionResult(entities=entities, relations=relations)

    def _extract_internal(self, text: str) -> None:
        """内部提取方法（不重置状态）"""
        # 1. 提取八卦
        bagua_found = self._extract_pattern_matches(text, BAGUA, "hexagram", "八卦：")

        # 2. 提取六十四卦
        hex_found = self._extract_pattern_matches(text, HEXAGRAM_NAMES, "hexagram", "卦象：")

        # 3. 提取五行
        wuxing_found = self._extract_pattern_matches(text, WUXING, "element", "五行：")

        # 4. 提取六亲
        liuqin_found = self._extract_pattern_matches(text, LIUQIN, "liuqin", "六亲：")

        # 5. 提取六神
        liushen_found = self._extract_pattern_matches(text, LIUSHEN, "liushen", "六神：")

        # 6. 提取天干
        tiangan_found = self._extract_pattern_matches(text, TIANGAN, "tiangan", "天干：")

        # 7. 提取地支
        dizhi_found = self._extract_pattern_matches(text, DIZHI, "dizhi", "地支：")

        # 8. 提取概念
        concept_found = self._extract_pattern_matches(text, CONCEPTS, "concept")

        # 9. 提取文献
        doc_found = self._extract_pattern_matches(text, DOCUMENTS, "document", "文献：")

        # ── 建立关系 ──

        # 卦 -> 五行 关系（从文本中推断）
        all_hex = bagua_found + hex_found
        for hex_name in all_hex:
            for wx in wuxing_found:
                # 检查是否有"乾金"、"坤土"等模式
                if re.search(rf"{re.escape(hex_name)}.*{re.escape(wx)}", text):
                    self._add_relation(hex_name, wx, "HAS_ELEMENT", f"{hex_name}属{wx}")

        # 六亲 -> 五行 关系
        for lq in liuqin_found:
            for wx in wuxing_found:
                if re.search(rf"{re.escape(lq)}.*{re.escape(wx)}", text):
                    self._add_relation(lq, wx, "RELATES_TO", f"{lq}与{wx}相关")

        # 文献 -> 概念 关系
        for doc in doc_found:
            for concept in concept_found:
                if re.search(rf"{re.escape(doc)}.*{re.escape(concept)}", text):
                    self._add_relation(doc, concept, "MENTIONS", f"{doc}提及{concept}")

        # 卦 -> 六亲 关系
        for hex_name in all_hex:
            for lq in liuqin_found:
                if re.search(rf"{re.escape(hex_name)}.*{re.escape(lq)}", text):
                    self._add_relation(hex_name, lq, "HAS_LIUQIN", f"{hex_name}有{lq}")
