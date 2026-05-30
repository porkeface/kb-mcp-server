"""Neo4j Adapter 测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kb_mcp_server.models.entity import Entity, Relation


class TestNeo4jAdapter:
    """Neo4j Adapter 测试类"""

    @pytest.fixture
    def mock_driver(self):
        """创建模拟的 Neo4j Driver"""
        driver = AsyncMock()
        session = AsyncMock()
        driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
        driver.session.return_value.__aexit__ = AsyncMock(return_value=None)
        return driver, session

    @pytest.mark.asyncio
    async def test_add_entity(self, mock_driver):
        """测试添加实体"""
        driver, session = mock_driver

        # 模拟返回结果
        result = MagicMock()
        result.data.return_value = [{"id": "entity_123"}]
        session.run = AsyncMock(return_value=result)

        with patch("neo4j.AsyncGraphDatabase") as mock_db:
            mock_db.driver.return_value = driver

            from kb_mcp_server.storage.neo4j_adapter import Neo4jAdapter
            adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password")

            entity = Entity(
                id="entity_123",
                name="乾卦",
                entity_type="hexagram",
                properties={"description": "乾卦代表天"}
            )

            entity_id = await adapter.add_entity("yijing", entity)

            assert entity_id == "entity_123"

    @pytest.mark.asyncio
    async def test_add_relation(self, mock_driver):
        """测试添加关系"""
        driver, session = mock_driver

        # 模拟返回结果
        result = MagicMock()
        result.data.return_value = []
        session.run = AsyncMock(return_value=result)

        with patch("neo4j.AsyncGraphDatabase") as mock_db:
            mock_db.driver.return_value = driver

            from kb_mcp_server.storage.neo4j_adapter import Neo4jAdapter
            adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password")

            relation = Relation(
                source_id="entity_1",
                target_id="entity_2",
                relation_type="RELATED_TO",
                properties={"weight": 0.8}
            )

            await adapter.add_relation("yijing", relation)

            # 验证 session.run 被调用
            session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_neighbors(self, mock_driver):
        """测试获取邻居节点"""
        driver, session = mock_driver

        # 模拟返回结果
        result = MagicMock()
        result.data.return_value = [
            {"id": "entity_2", "name": "天", "type": "concept"},
            {"id": "entity_3", "name": "刚健", "type": "attribute"}
        ]
        session.run = AsyncMock(return_value=result)

        with patch("neo4j.AsyncGraphDatabase") as mock_db:
            mock_db.driver.return_value = driver

            from kb_mcp_server.storage.neo4j_adapter import Neo4jAdapter
            adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password")

            neighbors = await adapter.get_neighbors("yijing", "entity_1", depth=1)

            assert len(neighbors) == 2
            assert neighbors[0].name == "天"
            assert neighbors[1].name == "刚健"

    @pytest.mark.asyncio
    async def test_search_entities(self, mock_driver):
        """测试搜索实体"""
        driver, session = mock_driver

        # 模拟返回结果
        result = MagicMock()
        result.data.return_value = [
            {"id": "entity_1", "name": "乾卦", "type": "hexagram"},
            {"id": "entity_2", "name": "乾元", "type": "concept"}
        ]
        session.run = AsyncMock(return_value=result)

        with patch("neo4j.AsyncGraphDatabase") as mock_db:
            mock_db.driver.return_value = driver

            from kb_mcp_server.storage.neo4j_adapter import Neo4jAdapter
            adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password")

            entities = await adapter.search_entities("yijing", "乾")

            assert len(entities) == 2
            assert entities[0].name == "乾卦"

    @pytest.mark.asyncio
    async def test_delete_database(self, mock_driver):
        """测试删除知识库数据"""
        driver, session = mock_driver

        # 模拟返回结果
        result = MagicMock()
        result.data.return_value = [{"deleted": 10}]
        session.run = AsyncMock(return_value=result)

        with patch("neo4j.AsyncGraphDatabase") as mock_db:
            mock_db.driver.return_value = driver

            from kb_mcp_server.storage.neo4j_adapter import Neo4jAdapter
            adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password")

            await adapter.delete_database("yijing")

            # 验证 session.run 被调用
            session.run.assert_called()
