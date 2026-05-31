"""易学领域规则配置"""

from .rule_extractor import EntityRule, RelationRule, RuleConfig

# ── 八卦 ──
BAGUA = ["乾", "坤", "震", "巽", "坎", "离", "艮", "兑"]

# ── 六十四卦 ──
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

# ── 关键概念 ──
CONCEPTS = [
    "世爻", "应爻", "用神", "原神", "忌神", "仇神",
    "飞神", "伏神", "动爻", "变爻", "静爻",
    "月建", "日辰", "旺", "相", "休", "囚", "死",
    "生", "克", "冲", "合", "刑", "害",
    "进神", "退神", "反吟", "伏吟", "旬空", "月破",
    "墓", "绝", "长生", "沐浴", "冠带", "临官", "帝旺",
    "衰", "病", "胎", "养",
    "纳甲", "卦身", "卦宫",
]

# ── 文献名称 ──
DOCUMENTS = [
    "周易", "易经", "十翼", "彖传", "象传", "系辞", "文言", "说卦", "序卦", "杂卦",
    "卜筮正宗", "增删卜易", "火珠林", "梅花易数", "焦氏易林", "黄金策",
    "京氏易传", "易隐", "易冒", "易林补遗", "天玄赋", "千金赋", "高岛易断",
]

# ── 易学领域规则配置 ──
YI_JING_RULES = RuleConfig(
    name="yijing",
    entity_rules=[
        EntityRule("hexagram", list(dict.fromkeys(BAGUA + HEXAGRAM_NAMES)), "卦象："),
        EntityRule("element", WUXING, "五行："),
        EntityRule("liuqin", LIUQIN, "六亲："),
        EntityRule("liushen", LIUSHEN, "六神："),
        EntityRule("tiangan", TIANGAN, "天干："),
        EntityRule("dizhi", DIZHI, "地支："),
        EntityRule("concept", CONCEPTS),
        EntityRule("document", DOCUMENTS, "文献："),
    ],
    relation_rules=[
        # 卦 -> 五行
        RelationRule(
            source_type="hexagram",
            target_type="element",
            relation_type="HAS_ELEMENT",
            pattern=r"[一-鿿]{1,2}.{0,5}[金木水火土]",
            description_template="{source}属{target}",
        ),
        # 六亲 -> 五行
        RelationRule(
            source_type="liuqin",
            target_type="element",
            relation_type="RELATES_TO",
            description_template="{source}与{target}相关",
        ),
        # 文献 -> 概念
        RelationRule(
            source_type="document",
            target_type="concept",
            relation_type="MENTIONS",
            description_template="{source}提及{target}",
        ),
        # 卦 -> 六亲
        RelationRule(
            source_type="hexagram",
            target_type="liuqin",
            relation_type="HAS_LIUQIN",
            description_template="{source}有{target}",
        ),
        # 概念 -> 概念
        RelationRule(
            source_type="concept",
            target_type="concept",
            relation_type="RELATED_TO",
            description_template="{source}与{target}相关",
        ),
    ],
)
