from app.config import Settings
from app.services.mcp_history import MCPHistoryClient
from app.services.adk_workflow import ContinuityAgent


def test_mcp_configuration_uses_official_endpoint():
    settings = Settings(clickhouse_mcp_url="http://clickhouse-mcp:8000/mcp")
    client = MCPHistoryClient(settings.clickhouse_mcp_url)
    assert client.url.endswith("/mcp")


def test_adk_agent_registers_mcp_retrieval_tool():
    agent = ContinuityAgent(Settings())
    assert agent.agent.tools[0].__name__ == "retrieve_continuity_history_through_mcp"
