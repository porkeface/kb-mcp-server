"""混合检索编排器测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from kb_mcp_server.models.search import SearchResult, HybridSearchResult


class TestRetrievalOrchestrator:
    """混合检索编排器测试类"""

    @pytest.fixture
    def mock_qdrant(self):
        """创建模拟的 QdrantAdapter"""
        qdrant = MagicMock()
        qdrant.search.return_value = [
            SearchResult(text="乾卦：元亨利贞", score=0.95, source="vector", metadata={"doc_id": "doc1"}),
            SearchResult(text="坤卦：利牝马之贞", score=0.85, source="vector", metadata={"doc_id": "doc1"}),
        ]
        return qdrant

    @pytest.fixture
    def mock_graph(self):
        """创建模拟的 GraphAdapter"""
        graph = AsyncMock()
        graph.search_entities.return_value = [
            MagicMock(id="entity_1", name="乾卦", entity_type="hexagram", properties={}),
            MagicMock(id="entity_2", name="天", entity_type="concept", properties={}),
        ]
        graph.get_neighbors.return_value = [
            MagicMock(id="entity_3", name="刚健", entity_type="attribute", properties={}),
        ]
        return graph

    @pytest.fixture
    def mock_embedding(self):
        """创建模拟的 EmbeddingProvider"""
        embedding = MagicMock()
        embedding.embed.return_value = [0.1, 0.2, 0.3]
        return embedding

    @pytest.mark.asyncio
    async def test_vector_search(self, mock_qdrant, mock_embedding):
        """测试向量搜索"""
        from kb_mcp_server.core.orchestrator import RetrievalOrchestrator
        orchestrator = RetrievalOrchestrator(mock_qdrant, None, mock_embedding)

        results = await orchestrator.vector_search("yijing", "乾卦", top_k=5)

        assert len(results) == 2
        assert results[0].text == "乾卦：元亨利贞"
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_hybrid_search(self, mock_qdrant, mock_graph, mock_embedding):
        """测试混合搜索"""
        from kb_mcp_server.core.orchestrator import RetrievalOrchestrator
        orchestrator = RetrievalOrchestrator(mock_qdrant, mock_graph, mock_embedding)

        results = await orchestrator.hybrid_search("yijing", "乾卦", max_results=10)

        assert len(results) > 0
        # 验证结果按 RRF 分数排序
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    @pytest.mark.asyncio
    async def test_hybrid_search_with_weights(self, mock_qdrant, mock_graph, mock_embedding):
        """测试带权重的混合搜索"""
        from kb_mcp_server.core.orchestrator import RetrievalOrchestrator
        orchestrator = RetrievalOrchestrator(mock_qdrant, mock_graph, mock_embedding)

        # 向量权重更高
        results = await orchestrator.hybrid_search(
            "yijing", "乾卦", max_results=10,
            vector_weight=2.0, graph_weight=1.0, keyword_weight=1.0
        )

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_empty_query(self, mock_qdrant, mock_graph, mock_embedding):
        """测试空查询"""
        from kb_mcp_server.core.orchestrator import RetrievalOrchestrator
        orchestrator = RetrievalOrchestrator(mock_qdrant, mock_graph, mock_embedding)

        results = await orchestrator.hybrid_search("yijing", "", max_results=10)

        # 空查询应该返回空结果
        assert len(results) == 0

    def test_rrf_fusion(self):
        """测试 RRF 融合函数"""
        from kb_mcp_server.core.orchestrator import _rrf_fuse

        # 模拟三路检索结果
        vector_results = [
            SearchResult(text="结果1", score=0.95, source="vector"),
            SearchResult(text="结果2", score=0.85, source="vector"),
        ]

        graph_results = [
            SearchResult(text="结果1", score=0.9, source="graph"),
            SearchResult(text="结果3", score=0.8, source="graph"),
        ]

        keyword_results = [
            SearchResult(text="结果2", score=0.9, source="keyword"),
            SearchResult(text="结果3", score=0.85, source="keyword"),
        ]

        # 计算 RRF 融合
        fused = _rrf_fuse(
            ranked_lists=[vector_results, graph_results, keyword_results],
            weights=[1.0, 1.0, 1.0],
            max_results=10
        )

        # 验证融合结果
        assert len(fused) > 0

        # 验证结果按分数排序
        for i in range(len(fused) - 1):
            assert fused[i].score >= fused[i + 1].score

        # 验证多路命中的结果分数更高
        result1 = next(r for r in fused if "结果1" in r.text)
        result3 = next(r for r in fused if "结果3" in r.text)

        # 结果1 在向量路和图谱路都命中，结果3 在图谱路和关键词路命中
        assert result1.score > 0
        assert result3.score > 0
