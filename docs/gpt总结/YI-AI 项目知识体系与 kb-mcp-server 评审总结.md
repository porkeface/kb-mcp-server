# YI-AI 项目知识体系与 kb-mcp-server 评审总结

更新时间：2026-05

---

# 一、核心结论

经过对 YI-AI 项目设计文档以及 kb-mcp-server 设计目标的分析，得到如下结论：

## kb-mcp-server 是必要的

kb-mcp-server 并不是一个普通 RAG 项目。

它的真正作用是：

```text
为 Agent 提供统一的易学知识体系
```

而不是：

```text
为最终用户提供问答能力
```

---

# 二、当前发现的问题

在开发 YI-AI 过程中发现：

Agent 在实现易学功能时经常出现：

* 六亲错误
* 纳甲错误
* 世应错误
* 旺衰判断错误
* 规则理解不一致

原因不是：

```text
Agent 不会写代码
```

而是：

```text
Agent 没有统一的易学知识来源
```

Agent 会混合：

* 网络资料
* 开源项目
* 训练语料
* 自身推测

导致实现结果不稳定。

---

# 三、kb-mcp-server 的真正价值

kb-mcp-server 的定位应该是：

```text
Yi Knowledge Hub
（易学知识中台）
```

而不是：

```text
向量检索系统
```

其作用：

```text
知识
↓
MCP
↓
Agent
↓
正确实现代码
```

---

# 四、YI-AI 实际架构理解

通过阅读项目文档发现：

YI-AI 已经不是简单的 AI 算卦系统。

其架构已经定义为：

```text
Foundation Layer
↓
Rule Engine Layer
↓
Knowledge Graph Layer
↓
AI Semantic Layer
↓
Memory Layer
↓
Simulation Layer
↓
Agent Layer
↓
Visualization Layer
```

这说明：

YI-AI 本质上是：

```text
易学领域操作系统
```

而不是：

```text
聊天机器人
```

---

# 五、重要认知

## 知识 ≠ 规则

这是项目最重要的结论。

知识：

```text
求财取妻财
```

属于：

```text
Knowledge
```

---

规则：

```text
妻财发动
月建生扶
日辰冲克

最终旺还是衰？
```

属于：

```text
Reasoning
```

---

知识库无法代替规则引擎。

---

# 六、未来架构定位

推荐架构：

```text
YI-AI

├── kb-mcp-server
│      Knowledge Layer
│
├── Yi Rule Engine
│      Rule Layer
│
├── Agent
│      Semantic Layer
│
└── UI
       Product Layer
```

---

# 七、kb-mcp-server 未来职责

## 1. Concept（概念）

例如：

```text
八卦
六亲
六神
纳甲
世应
五行
```

---

## 2. Rule（规则）

例如：

```text
世应规则
用神规则
旺衰规则
冲合规则
生克规则
```

---

## 3. Source（来源）

记录：

```text
周易
十翼
焦氏易林
火珠林
卜筮正宗
增删卜易
梅花易数
```

保证规则可追溯。

---

## 4. Case（案例）

例如：

```text
增删卜易案例
卜筮正宗案例
现代案例
```

用于案例检索。

---

## 5. Code Spec（规范）

例如：

```text
ShiYingEngine
LiuQinEngine
NaJiaEngine
```

接口标准。

---

# 八、Agent 开发规范

未来 Agent 不应自行推断规则。

必须：

```text
先查询 kb-mcp-server
再生成代码
```

禁止：

```text
根据模型记忆推断六爻规则
```

推荐流程：

```text
Agent
↓
MCP
↓
获取规则
↓
实现代码
↓
测试案例验证
```

---

# 九、知识体系建设建议

建立统一知识标准：

```text
docs/

├── bagua.md
├── wuxing.md
├── liuqin.md
├── liushen.md
├── najia.md
├── shiying.md
├── yongshen.md
└── rules.md
```

作为唯一可信来源。

---

# 十、易学知识体系分层

## L1 原典层

```text
周易
十翼
焦氏易林
京氏易传
```

---

## L2 结构化知识层

```text
八卦
六十四卦
纳甲
六亲
六神
世应
```

---

## L3 规则层

```text
生克
冲合
旺衰
用神
变卦
错综互
```

---

## L4 案例层

```text
增删卜易
卜筮正宗
高岛易断
现代案例
```

---

# 十一、项目当前最大的风险

不是：

```text
知识不够
```

而是：

```text
架构超前
实现滞后
```

目前已经规划：

* Neo4j
* Qdrant
* GraphRAG
* Memory
* Agent
* Simulation

但真正决定项目上限的是：

```text
Rule Engine
```

而不是：

```text
Embedding
GraphRAG
```

---

# 十二、最终结论

## 对 kb-mcp-server 的最终评价

它不是：

```text
普通知识库
```

而是：

```text
YI-AI 的知识操作系统层
```

作用：

```text
Single Source of Truth
（唯一可信知识源）
```

---

## 对 YI-AI 的最终评价

YI-AI 本质上是：

```text
易学知识系统
+
规则系统
+
Agent系统
```

其中：

```text
知识层 → kb-mcp-server

规则层 → Yi Rule Engine

推理层 → Agent

产品层 → Web/App
```

---

## 长期路线

优先级排序：

```text
规则引擎      ★★★★★★★★★★

知识中台      ★★★★★

案例库        ★★★★★

知识图谱      ★★★★

Agent         ★★★★

GraphRAG      ★★★

前端          ★★
```

核心原则：

```text
知识库负责告诉 Agent：

“规则是什么”

规则引擎负责：

“规则如何执行”

Agent负责：

“解释结果”
```

这是 YI-AI 长期发展的正确方向。
