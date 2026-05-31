"""实体提取器测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kb_mcp_server.config import Settings
from kb_mcp_server.models.entity import Entity, Relation


def _make_settings(**overrides) -> Settings:
    """创建测试用 Settings"""
    defaults = {
        "kb_mcp_extract_llm": "deepseek",
        "deepseek_api_key": "test-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestEntityExtractor:
    """实体提取器测试类"""

    @pytest.fixture
    def mock_llm_json(self):
        """模拟 LLM 返回的 JSON 字符串"""
        return '{"entities": [{"name": "乾卦", "type": "hexagram", "description": "乾卦代表天"}, {"name": "天", "type": "concept", "description": "天的概念"}], "relations": [{"source": "乾卦", "target": "天", "type": "REPRESENTS", "description": "乾卦代表天"}]}'

    @pytest.fixture
    def mock_http_response(self, mock_llm_json):
        """模拟 HTTP 响应"""
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": mock_llm_json
                    }
                }
            ]
        }
        return response

    @pytest.mark.asyncio
    async def test_extract_entities(self, mock_http_response):
        """测试提取实体"""
        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_http_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

            extractor = EntityExtractor(settings=_make_settings())

            text = "乾卦代表天，象征刚健。"
            result = await extractor.extract(text)

            assert len(result.entities) == 2
            assert result.entities[0].name == "乾卦"
            assert result.entities[0].entity_type == "hexagram"
            assert result.entities[1].name == "天"
            assert result.entities[1].entity_type == "concept"
            assert len(result.relations) == 1
            assert result.relations[0].relation_type == "REPRESENTS"

    @pytest.mark.asyncio
    async def test_extract_from_chunks(self, mock_http_response):
        """测试从分块列表提取实体"""
        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_http_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor
            from kb_mcp_server.models.chunk import Chunk

            extractor = EntityExtractor(settings=_make_settings())

            chunks = [
                Chunk(
                    id="chunk_1",
                    text="乾卦代表天",
                    metadata={"kb_name": "yijing"}
                )
            ]

            result = await extractor.extract_from_chunks(chunks)

            assert len(result.entities) == 2
            assert result.entities[0].name == "乾卦"

    @pytest.mark.asyncio
    async def test_extract_empty_text_returns_empty(self):
        """测试提取空文本返回空结果"""
        from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

        extractor = EntityExtractor(settings=_make_settings())

        result = await extractor.extract("")
        assert len(result.entities) == 0
        assert len(result.relations) == 0

        result = await extractor.extract("   ")
        assert len(result.entities) == 0
        assert len(result.relations) == 0

    @pytest.mark.asyncio
    async def test_entity_deduplication(self):
        """测试实体去重 - 同名实体只保留一个"""
        dedup_json = '{"entities": [{"name": "乾卦", "type": "hexagram"}, {"name": "乾卦", "type": "hexagram"}], "relations": []}'

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": dedup_json}}]
        }

        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

            extractor = EntityExtractor(settings=_make_settings())

            text = "乾卦代表天。乾卦象征刚健。"
            result = await extractor.extract(text)

            # 应该去重，只有一个乾卦
            assert len(result.entities) == 1
            assert result.entities[0].name == "乾卦"

    @pytest.mark.asyncio
    async def test_extract_from_chunks_merges_entities(self):
        """测试跨块实体合并去重"""
        chunk1_json = '{"entities": [{"name": "乾卦", "type": "hexagram"}, {"name": "天", "type": "concept"}], "relations": [{"source": "乾卦", "target": "天", "type": "REPRESENTS"}]}'
        chunk2_json = '{"entities": [{"name": "乾卦", "type": "hexagram"}, {"name": "坤卦", "type": "hexagram"}], "relations": [{"source": "坤卦", "target": "地", "type": "REPRESENTS"}]}'
        # 地 entity is in the relation but not in entities - that's expected from LLM

        responses = []
        for json_str in [chunk1_json, chunk2_json]:
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": json_str}}]}
            responses.append(resp)

        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=responses)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor
            from kb_mcp_server.models.chunk import Chunk

            extractor = EntityExtractor(settings=_make_settings())

            chunks = [
                Chunk(id="c1", text="乾卦代表天", metadata={}),
                Chunk(id="c2", text="坤卦代表地", metadata={}),
            ]

            result = await extractor.extract_from_chunks(chunks)

            # 乾卦 should be deduplicated across chunks
            entity_names = {e.name for e in result.entities}
            assert "乾卦" in entity_names
            assert "天" in entity_names
            assert "坤卦" in entity_names
            # 地 is not in entities (only in relation from chunk2), so relation is filtered out
            # Verify only one 乾卦
            qian_count = sum(1 for e in result.entities if e.name == "乾卦")
            assert qian_count == 1

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_empty(self):
        """测试空分块列表返回空结果"""
        from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

        extractor = EntityExtractor(settings=_make_settings())
        result = await extractor.extract_from_chunks([])

        assert len(result.entities) == 0
        assert len(result.relations) == 0

    @pytest.mark.asyncio
    async def test_unsupported_provider_raises(self):
        """测试不支持的提供商抛出异常"""
        from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

        with pytest.raises(ValueError, match="不支持的 LLM 提供商"):
            EntityExtractor(settings=_make_settings(kb_mcp_extract_llm="unsupported"))

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        """测试缺少 API Key 抛出异常"""
        from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

        with pytest.raises(ValueError, match="未配置"):
            EntityExtractor(settings=_make_settings(deepseek_api_key=None, llm_api_key=None))

    @pytest.mark.asyncio
    async def test_openai_provider(self):
        """测试 OpenAI 提供商配置"""
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": '{"entities": [], "relations": []}'}}]
        }

        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

            extractor = EntityExtractor(
                settings=_make_settings(
                    kb_mcp_extract_llm="openai",
                    openai_api_key="sk-test",
                )
            )

            result = await extractor.extract("测试文本")
            assert result.entities == []
            assert result.relations == []

    @pytest.mark.asyncio
    async def test_llm_returns_markdown_wrapped_json(self):
        """测试 LLM 返回被 markdown 代码块包裹的 JSON"""
        wrapped_json = '```json\n{"entities": [{"name": "测试", "type": "concept"}], "relations": []}\n```'

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": wrapped_json}}]
        }

        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

            extractor = EntityExtractor(settings=_make_settings())

            result = await extractor.extract("测试内容")
            assert len(result.entities) == 1
            assert result.entities[0].name == "测试"

    @pytest.mark.asyncio
    async def test_relation_filtered_when_entity_missing(self):
        """测试引用不存在实体的关系被过滤"""
        json_str = '{"entities": [{"name": "乾卦", "type": "hexagram"}], "relations": [{"source": "乾卦", "target": "天", "type": "REPRESENTS"}]}'

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": json_str}}]
        }

        with patch("kb_mcp_server.core.extractors.llm_extractor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client

            from kb_mcp_server.core.extractors import LLMEntityExtractor as EntityExtractor

            extractor = EntityExtractor(settings=_make_settings())

            result = await extractor.extract("乾卦相关文本")
            # "天" is not in entities, so the relation should be filtered
            assert len(result.entities) == 1
            assert len(result.relations) == 0
