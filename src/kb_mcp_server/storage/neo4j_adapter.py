"""Neo4j 图数据库适配器

使用 Label 前缀隔离策略，兼容 Neo4j Community Edition。
每个知识库使用 `kb_{name}__` 前缀隔离节点标签和关系类型。
"""

from __future__ import annotations

from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncResult
from neo4j.exceptions import Neo4jError

from ..models.entity import Entity, Relation

logger = structlog.get_logger()

# ── 节点类型（基础标签） ──
NODE_LABELS = ("Entity", "Document", "Chunk", "Topic")

# ── 关系类型 ──
RELATION_TYPES = (
    "MENTIONS",
    "BELONGS_TO",
    "RELATED_TO",
    "CONTAINS",
    "REFERENCES",
    "SIMILAR_TO",
)


class Neo4jAdapter:
    """Neo4j 图数据库适配器

    使用 Label 前缀实现知识库级别的数据隔离，
    兼容 Neo4j Community Edition（不支持多数据库）。

    每个知识库的节点标签格式: ``kb_{kb_name}__{NodeLabel}``
    每个知识库的关系类型格式: ``kb_{kb_name}__{REL_TYPE}``
    """

    def __init__(self, driver: AsyncDriver) -> None:
        """初始化 Neo4j 适配器

        Args:
            driver: Neo4j 异步驱动实例
        """
        self._driver = driver
        logger.info("Neo4j 适配器初始化完成")

    async def close(self) -> None:
        """关闭驱动连接"""
        await self._driver.close()
        logger.info("Neo4j 连接已关闭")

    # ── 内部工具方法 ──

    @staticmethod
    def _node_label(kb_name: str, label: str) -> str:
        """生成带前缀的节点标签

        Args:
            kb_name: 知识库名称
            label: 基础标签名称

        Returns:
            带前缀的标签，如 ``kb_mykb__Entity``
        """
        return f"kb_{kb_name}__{label}"

    @staticmethod
    def _rel_type(kb_name: str, rel_type: str) -> str:
        """生成带前缀的关系类型

        Args:
            kb_name: 知识库名称
            rel_type: 基础关系类型

        Returns:
            带前缀的关系类型，如 ``kb_mykb__MENTIONS``
        """
        return f"kb_{kb_name}__{rel_type}"

    @staticmethod
    def _validate_kb_name(kb_name: str) -> None:
        """校验知识库名称合法性（防止 Cypher 注入）

        Args:
            kb_name: 知识库名称

        Raises:
            ValueError: 名称包含非法字符
        """
        if not kb_name:
            raise ValueError("知识库名称不能为空")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        invalid = set(kb_name) - allowed
        if invalid:
            raise ValueError(
                f"知识库名称包含非法字符: {invalid}，仅允许字母、数字、下划线和连字符"
            )

    @staticmethod
    def _entity_to_node_properties(entity: Entity) -> dict[str, Any]:
        """将 Entity 转换为 Neo4j 节点属性字典

        Args:
            entity: 实体对象

        Returns:
            属性字典
        """
        props: dict[str, Any] = {
            "id": entity.id,
            "name": entity.name,
            "entity_type": entity.entity_type,
        }
        # 合并自定义属性，避免覆盖核心字段
        for key, value in entity.properties.items():
            if key not in props:
                props[key] = value
        return props

    @staticmethod
    def _record_to_entity(record: Any) -> Entity:
        """将 Neo4j 记录转换为 Entity

        Args:
            record: Neo4j 节点记录（包含 n 别名）

        Returns:
            Entity 对象
        """
        node = record["n"]
        props = dict(node.items())
        # 提取核心字段
        entity_id = props.pop("id", "")
        name = props.pop("name", "")
        entity_type = props.pop("entity_type", "concept")
        # 剩余字段作为 properties
        return Entity(
            id=entity_id,
            name=name,
            entity_type=entity_type,
            properties=props,
        )

    @staticmethod
    def _record_to_relation(record: Any, kb_name: str) -> dict[str, Any]:
        """将 Neo4j 路径/关系记录转换为关系字典

        Args:
            record: 包含关系信息的记录
            kb_name: 知识库名称（用于去除前缀）

        Returns:
            关系信息字典
        """
        rel = record["r"]
        prefix = f"kb_{kb_name}__"
        rel_type = rel.type
        if rel_type.startswith(prefix):
            rel_type = rel_type[len(prefix):]
        return {
            "source_id": rel.start_node.get("id", ""),
            "target_id": rel.end_node.get("id", ""),
            "relation_type": rel_type,
            "properties": dict(rel.items()),
        }

    # ── 核心公共方法 ──

    async def ensure_indexes(self, kb_name: str) -> None:
        """确保知识库的索引存在

        为实体节点创建唯一约束和全文索引。

        Args:
            kb_name: 知识库名称
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")

        async with self._driver.session() as session:
            # 唯一约束（自动创建索引）
            constraint_name = f"kb_{kb_name}_entity_id_unique"
            try:
                await session.run(
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:`{label}`) REQUIRE n.id IS UNIQUE"
                )
                logger.info("唯一约束已创建", kb=kb_name, constraint=constraint_name)
            except Neo4jError as e:
                # Community Edition 可能不支持某些约束语法
                logger.warning(
                    "创建唯一约束失败（可能不支持），将回退到普通索引",
                    kb=kb_name,
                    error=str(e),
                )
                await session.run(
                    f"CREATE INDEX kb_{kb_name}_entity_id IF NOT EXISTS "
                    f"FOR (n:`{label}`) ON (n.id)"
                )

            # 名称索引，用于搜索
            await session.run(
                f"CREATE INDEX kb_{kb_name}_entity_name IF NOT EXISTS "
                f"FOR (n:`{label}`) ON (n.name)"
            )

            # 实体类型索引
            await session.run(
                f"CREATE INDEX kb_{kb_name}_entity_type IF NOT EXISTS "
                f"FOR (n:`{label}`) ON (n.entity_type)"
            )

        logger.info("索引确保完成", kb=kb_name)

    async def add_entity(self, kb_name: str, entity: Entity) -> None:
        """添加或更新实体节点

        使用 MERGE 语义，通过实体 ID 去重。

        Args:
            kb_name: 知识库名称
            entity: 实体对象
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")
        props = self._entity_to_node_properties(entity)

        async with self._driver.session() as session:
            await session.run(
                f"MERGE (n:`{label}` {{id: $id}}) "
                f"SET n += $props",
                id=entity.id,
                props=props,
            )

        logger.debug("实体已添加/更新", kb=kb_name, entity_id=entity.id, name=entity.name)

    async def add_entities_batch(self, kb_name: str, entities: list[Entity]) -> int:
        """批量添加实体节点

        Args:
            kb_name: 知识库名称
            entities: 实体列表

        Returns:
            成功添加的实体数量
        """
        self._validate_kb_name(kb_name)
        if not entities:
            return 0

        label = self._node_label(kb_name, "Entity")

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"UNWIND $entities AS e "
                f"MERGE (n:`{label}` {{id: e.id}}) "
                f"SET n += e "
                f"RETURN count(n) AS cnt",
                entities=[
                    self._entity_to_node_properties(e) for e in entities
                ],
            )
            record = await result.single()
            count = record["cnt"] if record else 0

        logger.info("批量添加实体完成", kb=kb_name, count=count)
        return count

    async def add_relation(
        self,
        kb_name: str,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """添加关系

        使用 MERGE 语义，避免重复关系。

        Args:
            kb_name: 知识库名称
            source_id: 源实体 ID
            target_id: 目标实体 ID
            rel_type: 关系类型
            properties: 关系属性

        Returns:
            是否添加成功
        """
        self._validate_kb_name(kb_name)
        node_label = self._node_label(kb_name, "Entity")
        prefixed_rel = self._rel_type(kb_name, rel_type)
        props = properties or {}

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (a:`{node_label}` {{id: $source_id}}) "
                f"MATCH (b:`{node_label}` {{id: $target_id}}) "
                f"MERGE (a)-[r:`{prefixed_rel}`]->(b) "
                f"SET r += $props "
                f"RETURN type(r) AS rel_type",
                source_id=source_id,
                target_id=target_id,
                props=props,
            )
            record = await result.single()

        success = record is not None
        if success:
            logger.debug(
                "关系已添加",
                kb=kb_name,
                source=source_id,
                target=target_id,
                rel_type=rel_type,
            )
        else:
            logger.warning(
                "关系添加失败：未找到源或目标实体",
                kb=kb_name,
                source=source_id,
                target=target_id,
                rel_type=rel_type,
            )
        return success

    async def add_relations_batch(
        self, kb_name: str, relations: list[Relation]
    ) -> int:
        """批量添加关系

        Args:
            kb_name: 知识库名称
            relations: 关系列表

        Returns:
            成功添加的关系数量
        """
        self._validate_kb_name(kb_name)
        if not relations:
            return 0

        node_label = self._node_label(kb_name, "Entity")
        # 按关系类型分组批量写入
        grouped: dict[str, list[dict[str, Any]]] = {}
        for rel in relations:
            prefixed_rel = self._rel_type(kb_name, rel.relation_type)
            grouped.setdefault(prefixed_rel, []).append({
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "properties": rel.properties,
            })

        total = 0
        async with self._driver.session() as session:
            for prefixed_rel, items in grouped.items():
                result: AsyncResult = await session.run(
                    f"UNWIND $relations AS rel "
                    f"MATCH (a:`{node_label}` {{id: rel.source_id}}) "
                    f"MATCH (b:`{node_label}` {{id: rel.target_id}}) "
                    f"MERGE (a)-[r:`{prefixed_rel}`]->(b) "
                    f"SET r += rel.properties "
                    f"RETURN count(r) AS cnt",
                    relations=items,
                )
                record = await result.single()
                total += record["cnt"] if record else 0

        logger.info("批量添加关系完成", kb=kb_name, count=total)
        return total

    async def get_neighbors(
        self,
        kb_name: str,
        entity_id: str,
        rel_type: str | None = None,
        depth: int = 1,
    ) -> list[Entity]:
        """获取邻居节点

        通过 BFS 方式获取指定深度内的所有邻居节点。

        Args:
            kb_name: 知识库名称
            entity_id: 起始实体 ID
            rel_type: 关系类型过滤（可选，不过滤则遍历所有关系类型）
            depth: 遍历深度，默认 1

        Returns:
            邻居实体列表（不包含起始节点）
        """
        self._validate_kb_name(kb_name)
        node_label = self._node_label(kb_name, "Entity")
        depth = max(1, min(depth, 10))  # 限制最大深度为 10

        if rel_type:
            prefixed_rel = self._rel_type(kb_name, rel_type)
            rel_pattern = f":`{prefixed_rel}`"
        else:
            # 遍历所有带该知识库前缀的关系类型
            prefix = f"kb_{kb_name}__"
            rel_types = [f":`{prefix}{rt}`" for rt in RELATION_TYPES]
            rel_pattern = "|".join(rel_types)

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (start:`{node_label}` {{id: $entity_id}}) "
                f"MATCH (start)-[{rel_pattern}*1..{depth}]-(neighbor:`{node_label}`) "
                f"WHERE neighbor.id <> $entity_id "
                f"WITH DISTINCT neighbor AS n "
                f"RETURN n",
                entity_id=entity_id,
            )
            records = await result.fetch()
            entities = [self._record_to_entity(r) for r in records]

        logger.debug(
            "获取邻居完成",
            kb=kb_name,
            entity_id=entity_id,
            rel_type=rel_type,
            depth=depth,
            count=len(entities),
        )
        return entities

    async def find_path(
        self,
        kb_name: str,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """查找两个实体之间的路径

        使用最短路径算法查找两个实体之间的关系路径。

        Args:
            kb_name: 知识库名称
            start_id: 起始实体 ID
            end_id: 目标实体 ID
            max_depth: 最大搜索深度，默认 5

        Returns:
            路径上的关系列表，格式为:
            [{"source_id", "target_id", "relation_type", "properties"}, ...]
        """
        self._validate_kb_name(kb_name)
        node_label = self._node_label(kb_name, "Entity")
        max_depth = max(1, min(max_depth, 15))

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (start:`{node_label}` {{id: $start_id}}) "
                f"MATCH (end:`{node_label}` {{id: $end_id}}) "
                f"MATCH path = shortestPath((start)-[*..{max_depth}]-(end)) "
                f"UNWIND relationships(path) AS r "
                f"RETURN r",
                start_id=start_id,
                end_id=end_id,
            )
            records = await result.fetch()
            path_relations = [self._record_to_relation(r, kb_name) for r in records]

        logger.debug(
            "路径查找完成",
            kb=kb_name,
            start=start_id,
            end=end_id,
            hops=len(path_relations),
        )
        return path_relations

    async def search_entities(
        self,
        kb_name: str,
        query: str,
        limit: int = 20,
    ) -> list[Entity]:
        """搜索实体

        按实体名称进行模糊搜索（CONTAINS 匹配）。

        Args:
            kb_name: 知识库名称
            query: 搜索关键词
            limit: 返回结果数量上限，默认 20

        Returns:
            匹配的实体列表
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")
        limit = max(1, min(limit, 100))

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (n:`{label}`) "
                f"WHERE n.name CONTAINS $query "
                f"RETURN n "
                f"ORDER BY n.name "
                f"LIMIT $limit",
                query=query,
                limit=limit,
            )
            records = await result.fetch()
            entities = [self._record_to_entity(r) for r in records]

        logger.debug("实体搜索完成", kb=kb_name, query=query, count=len(entities))
        return entities

    async def get_entity(self, kb_name: str, entity_id: str) -> Entity | None:
        """获取单个实体

        Args:
            kb_name: 知识库名称
            entity_id: 实体 ID

        Returns:
            实体对象，不存在返回 None
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (n:`{label}` {{id: $entity_id}}) RETURN n",
                entity_id=entity_id,
            )
            record = await result.single()

        if record is None:
            return None
        return self._record_to_entity(record)

    async def delete_entity(self, kb_name: str, entity_id: str) -> bool:
        """删除实体及其关联的关系

        Args:
            kb_name: 知识库名称
            entity_id: 实体 ID

        Returns:
            是否删除成功
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (n:`{label}` {{id: $entity_id}}) "
                f"DETACH DELETE n "
                f"RETURN count(n) AS cnt",
                entity_id=entity_id,
            )
            record = await result.single()
            count = record["cnt"] if record else 0

        deleted = count > 0
        if deleted:
            logger.debug("实体已删除", kb=kb_name, entity_id=entity_id)
        return deleted

    async def delete_database(self, kb_name: str) -> None:
        """删除知识库的所有数据

        删除该知识库前缀下的所有节点和关系。

        Args:
            kb_name: 知识库名称
        """
        self._validate_kb_name(kb_name)

        async with self._driver.session() as session:
            # 删除所有带该知识库前缀标签的节点（及其关系）
            for label in NODE_LABELS:
                prefixed_label = self._node_label(kb_name, label)
                await session.run(
                    f"MATCH (n:`{prefixed_label}`) DETACH DELETE n"
                )

        logger.info("知识库图数据已完全删除", kb=kb_name)

    async def get_entity_count(self, kb_name: str) -> int:
        """获取知识库的实体数量

        Args:
            kb_name: 知识库名称

        Returns:
            实体节点数量
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (n:`{label}`) RETURN count(n) AS cnt"
            )
            record = await result.single()
            return record["cnt"] if record else 0

    async def get_relation_count(self, kb_name: str) -> int:
        """获取知识库的关系数量

        通过遍历所有带前缀的关系类型统计。

        Args:
            kb_name: 知识库名称

        Returns:
            关系边数量
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")
        prefix = f"kb_{kb_name}__"

        # 只统计带该知识库前缀的关系
        total = 0
        async with self._driver.session() as session:
            for rt in RELATION_TYPES:
                prefixed_rel = f"{prefix}{rt}"
                result: AsyncResult = await session.run(
                    f"MATCH (n:`{label}`)-[r:`{prefixed_rel}`]-() "
                    f"RETURN count(r) AS cnt"
                )
                record = await result.single()
                total += record["cnt"] if record else 0

        return total

    async def get_all_entities(
        self,
        kb_name: str,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Entity]:
        """获取知识库所有实体（分页）

        Args:
            kb_name: 知识库名称
            entity_type: 实体类型过滤（可选）
            limit: 返回数量上限
            offset: 偏移量

        Returns:
            实体列表
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")
        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        where_clause = ""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if entity_type:
            where_clause = "WHERE n.entity_type = $entity_type"
            params["entity_type"] = entity_type

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH (n:`{label}`) "
                f"{where_clause} "
                f"RETURN n "
                f"ORDER BY n.name "
                f"SKIP $offset "
                f"LIMIT $limit",
                **params,
            )
            records = await result.fetch()
            return [self._record_to_entity(r) for r in records]

    async def get_entity_relations(
        self,
        kb_name: str,
        entity_id: str,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """获取实体的所有关系

        Args:
            kb_name: 知识库名称
            entity_id: 实体 ID
            direction: 方向过滤 - "outgoing", "incoming", "both"

        Returns:
            关系列表
        """
        self._validate_kb_name(kb_name)
        label = self._node_label(kb_name, "Entity")

        if direction == "outgoing":
            pattern = "(n:`{label}` {{id: $entity_id}})-[r]->(m)"
        elif direction == "incoming":
            pattern = "(m)-[r]->(n:`{label}` {{id: $entity_id}})"
        else:
            pattern = "(n:`{label}` {{id: $entity_id}})-[r]-(m)"
        pattern = pattern.format(label=label)

        async with self._driver.session() as session:
            result: AsyncResult = await session.run(
                f"MATCH {pattern} RETURN r",
                entity_id=entity_id,
            )
            records = await result.fetch()
            return [self._record_to_relation(r, kb_name) for r in records]
