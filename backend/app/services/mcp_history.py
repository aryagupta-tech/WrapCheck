import json
from contextlib import asynccontextmanager

import anyio
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


class MCPHistoryClient:
    """Read continuity history through the official mcp-clickhouse service."""

    def __init__(self, url: str, audience: str | None = None):
        self.url = url
        self.audience = audience

    @asynccontextmanager
    async def _session(self):
        headers: dict[str, str] = {}
        if self.audience:
            token = await anyio.to_thread.run_sync(
                lambda: id_token.fetch_id_token(Request(), self.audience)
            )
            headers["Authorization"] = f"Bearer {token}"
        async with create_mcp_http_client(headers=headers) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    async def observations_for_scene(self, production_id: str, scene_id: str) -> dict:
        # JSON escaping is reused inside SQL single-quoted literals after escaping apostrophes.
        prod = production_id.replace("'", "''")
        scene = scene_id.replace("'", "''")
        query = (
            "SELECT observation_id, take_id, entity_type, entity_name, attribute, observed_value, "
            "confidence, evidence_description, evidence_frame_timestamp_ms "
            f"FROM wrapcheck.observations WHERE production_id = '{prod}' AND scene_id = '{scene}' "
            "ORDER BY created_at DESC LIMIT 500"
        )
        async with self._session() as session:
            result = await session.call_tool("run_query", {"query": query})
            return {"tool": "run_query", "query": query, "result": result.model_dump(mode="json")}

    async def gate_context(
        self, production_id: str, scene_id: str, setup_id: str,
        reference_take_id: str, candidate_take_id: str, run_id: str,
    ) -> dict:
        values = [
            production_id.replace("'", "''"), scene_id.replace("'", "''"),
            setup_id.replace("'", "''"), reference_take_id.replace("'", "''"),
            candidate_take_id.replace("'", "''"), run_id.replace("'", "''"),
        ]
        prod, scene, setup, reference, candidate, run = values
        requirements_query = (
            "SELECT requirement_id, requirement_type, label, entity_name, attribute, expected_value "
            "FROM wrapcheck.scene_requirements FINAL "
            f"WHERE production_id = '{prod}' AND scene_id = '{scene}' AND setup_id = '{setup}' "
            "ORDER BY requirement_id"
        )
        observations_query = (
            "SELECT observation_id, run_id, production_id, scene_id, setup_id, take_id, requirement_id, "
            "result, normalized_value, confidence, evidence_description, timestamp_start_ms, "
            "timestamp_end_ms, source, created_at FROM wrapcheck.requirement_observations "
            f"WHERE production_id = '{prod}' AND scene_id = '{scene}' AND setup_id = '{setup}' "
            f"AND run_id = '{run}' "
            f"AND take_id IN ('{reference}', '{candidate}') "
            "ORDER BY take_id, requirement_id, created_at DESC LIMIT 100"
        )
        async with self._session() as session:
            requirements = await session.call_tool("run_query", {"query": requirements_query})
            observations = await session.call_tool("run_query", {"query": observations_query})
        return {
            "tool": "run_query",
            "queries": [requirements_query, observations_query],
            "requirements": _rows(requirements),
            "observations": _rows(observations),
        }

    async def handoff_context(self, run_id: str) -> dict:
        run = run_id.replace("'", "''")
        expectations_query = (
            "SELECT expectation_id, run_id, production, shoot_day, scene, take, circled, "
            "camera_roll, card_id, video_filename, sound_roll, audio_filename, frame_rate, script_note "
            f"FROM wrapcheck.media_expectations WHERE run_id = '{run}' "
            "ORDER BY scene, take"
        )
        inventory_query = (
            "SELECT media_id, run_id, filename, kind, roll, card_id, scene, take, size_bytes, "
            "checksum_state, checksum FROM wrapcheck.media_inventory "
            f"WHERE run_id = '{run}' ORDER BY kind, filename"
        )
        copies_query = (
            "SELECT media_id, run_id, filename, destination, checksum_algorithm, checksum, "
            "verified, verified_at FROM wrapcheck.media_copies "
            f"WHERE run_id = '{run}' ORDER BY filename, destination"
        )
        async with self._session() as session:
            expectations = await session.call_tool("run_query", {"query": expectations_query})
            inventory = await session.call_tool("run_query", {"query": inventory_query})
            copies = await session.call_tool("run_query", {"query": copies_query})
        return {
            "tool": "run_query", "queries": [expectations_query, inventory_query, copies_query],
            "expectations": _rows(expectations), "inventory": _merge_copies(_rows(inventory), _rows(copies)),
        }


def _merge_copies(inventory: list[dict], copies: list[dict]) -> list[dict]:
    by_media: dict[str, list[dict]] = {}
    for copy in copies:
        by_media.setdefault(str(copy.get("media_id", "")), []).append({
            "destination": copy.get("destination", ""),
            "checksum_algorithm": copy.get("checksum_algorithm", "sha256"),
            "checksum": copy.get("checksum", ""),
            "verified": bool(copy.get("verified", False)),
            "verified_at": copy.get("verified_at"),
        })
    for item in inventory:
        item["copies"] = by_media.get(str(item.get("media_id", "")), [])
        item.pop("checksum_state", None)
        item.pop("checksum", None)
    return inventory


def _rows(result) -> list[dict]:
    """Parse the official mcp-clickhouse JSON tool result without trusting prose."""
    rows: list[dict] = []
    for block in result.content:
        text = getattr(block, "text", "")
        if not text:
            continue
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                rows.extend(item for item in decoded if isinstance(item, dict))
            elif isinstance(decoded, dict):
                nested = decoded.get("data") or decoded.get("rows")
                columns = decoded.get("columns")
                if (
                    isinstance(columns, list)
                    and isinstance(nested, list)
                    and all(isinstance(item, list) for item in nested)
                ):
                    rows.extend(dict(zip(columns, item, strict=False)) for item in nested)
                elif isinstance(nested, list):
                    rows.extend(item for item in nested if isinstance(item, dict))
                else:
                    rows.append(decoded)
            continue
        except json.JSONDecodeError:
            pass
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows
