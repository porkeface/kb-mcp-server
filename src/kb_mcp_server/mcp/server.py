"""FastMCP 实例定义"""

from mcp.server.fastmcp import FastMCP

# 创建 FastMCP 实例
mcp = FastMCP(
    "knowledge-base",
    instructions="知识库 MCP Server - 为 Claude Code Agent 提供多领域知识库检索能力",
)
