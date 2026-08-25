from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..config import Settings
from .mcp_history import MCPHistoryClient


class ContinuityAgent:
    """Google ADK explanation layer; deterministic code remains authoritative."""

    def __init__(self, settings: Settings):
        self.last_mcp_trace: dict = {}

        async def retrieve_continuity_history_through_mcp(production_id: str, scene_id: str) -> dict:
            """Retrieve prior continuity observations for one production scene through mcp-clickhouse."""
            self.last_mcp_trace = await MCPHistoryClient(settings.clickhouse_mcp_url).observations_for_scene(
                production_id, scene_id
            )
            return self.last_mcp_trace

        self.agent = Agent(
            name="wrapcheck_continuity_agent",
            model=settings.gemini_model,
            instruction=(
                "Explain supplied deterministic continuity conflicts to a script supervisor. "
                "Always call retrieve_continuity_history_through_mcp before answering. "
                "Use retrieved evidence to summarize continuity history. Never set severity, "
                "decide the wrap recommendation, or invent evidence."
            ),
            tools=[retrieve_continuity_history_through_mcp],
        )
        self.runner = InMemoryRunner(agent=self.agent, app_name="wrapcheck")

    async def retrieve_and_summarize(self, payload: str, user_id: str, session_id: str) -> str:
        await self.runner.session_service.create_session(
            app_name="wrapcheck", user_id=user_id, session_id=session_id
        )
        message = types.Content(role="user", parts=[types.Part(text=payload)])
        final = ""
        async for event in self.runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            if event.is_final_response() and event.content:
                final = "".join(part.text or "" for part in event.content.parts)
        return final


class WrapGateAgent:
    """ADK orchestrator whose only data access is the read-only ClickHouse MCP."""

    def __init__(self, settings: Settings):
        self.last_gate_context: dict = {}
        self.last_summary = ""

        async def retrieve_wrap_context_through_mcp(
            production_id: str, scene_id: str, setup_id: str,
            reference_take_id: str, candidate_take_id: str, run_id: str,
        ) -> dict:
            """Retrieve declared requirements and both take observations through mcp-clickhouse."""
            self.last_gate_context = await MCPHistoryClient(settings.clickhouse_mcp_url).gate_context(
                production_id, scene_id, setup_id, reference_take_id, candidate_take_id, run_id,
            )
            return self.last_gate_context

        self.agent = Agent(
            name="wrapcheck_release_gate_agent",
            model=settings.gemini_model,
            instruction=(
                "You prepare evidence for a deterministic on-set release gate. Always call "
                "retrieve_wrap_context_through_mcp exactly once with the identifiers supplied. "
                "Summarize only the returned rows. Never decide gate status, invent evidence, "
                "or recommend autonomous wrap clearance."
            ),
            tools=[retrieve_wrap_context_through_mcp],
        )
        self.runner = InMemoryRunner(agent=self.agent, app_name="wrapcheck-release-gate")

    async def retrieve_context(
        self, production_id: str, scene_id: str, setup_id: str,
        reference_take_id: str, candidate_take_id: str, run_id: str,
    ) -> dict:
        user_id = "script-supervisor"
        await self.runner.session_service.create_session(
            app_name="wrapcheck-release-gate", user_id=user_id, session_id=run_id,
        )
        message = types.Content(role="user", parts=[types.Part(text=(
            f"production_id={production_id}; scene_id={scene_id}; setup_id={setup_id}; "
            f"reference_take_id={reference_take_id}; candidate_take_id={candidate_take_id}; run_id={run_id}"
        ))])
        final = ""
        async for event in self.runner.run_async(user_id=user_id, session_id=run_id, new_message=message):
            if event.is_final_response() and event.content:
                final = "".join(part.text or "" for part in event.content.parts)
        if not self.last_gate_context:
            raise RuntimeError("The ADK agent did not retrieve wrap context through ClickHouse MCP.")
        self.last_summary = final
        return self.last_gate_context


class MediaHandoffAgent:
    """ADK agent that retrieves one delivery's normalized evidence through ClickHouse MCP."""

    def __init__(self, settings: Settings):
        self.last_context: dict = {}
        self.last_summary = ""

        async def retrieve_media_delivery_through_mcp(run_id: str) -> dict:
            """Retrieve expected takes and delivered media for a handoff run."""
            self.last_context = await MCPHistoryClient(settings.clickhouse_mcp_url).handoff_context(run_id)
            return self.last_context

        self.agent = Agent(
            name="wrapcheck_media_handoff_agent", model=settings.gemini_model,
            instruction=(
                "You investigate a film-set media delivery. Always call "
                "retrieve_media_delivery_through_mcp exactly once with the supplied run_id. "
                "Summarize which reports and media rows were retrieved. Never invent a file, "
                "mark a checksum verified, erase a card, or set release status."
            ),
            tools=[retrieve_media_delivery_through_mcp],
        )
        self.runner = InMemoryRunner(agent=self.agent, app_name="wrapcheck-media-handoff")

    async def retrieve_context(self, run_id: str) -> dict:
        user_id = "dit-operator"
        await self.runner.session_service.create_session(
            app_name="wrapcheck-media-handoff", user_id=user_id, session_id=run_id,
        )
        message = types.Content(role="user", parts=[types.Part(text=f"run_id={run_id}")])
        final = ""
        async for event in self.runner.run_async(user_id=user_id, session_id=run_id, new_message=message):
            if event.is_final_response() and event.content:
                final = "".join(part.text or "" for part in event.content.parts)
        if not self.last_context:
            raise RuntimeError("The ADK agent did not retrieve media context through ClickHouse MCP.")
        self.last_summary = final
        return self.last_context
