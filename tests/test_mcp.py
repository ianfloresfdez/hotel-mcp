"""Talks to the MCP server through a real client session (in memory), like Claude Desktop would."""

import json
from datetime import date, timedelta

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from hotel import core
from hotel.mcp_server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "mcp.db")


def d(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def text(result) -> str:
    return result.content[0].text


@pytest.mark.anyio
async def test_lists_tools_resources_and_prompts():
    async with create_connected_server_and_client_session(mcp) as s:
        tools = {t.name for t in (await s.list_tools()).tools}
        assert tools == {"check_availability", "get_booking", "occupancy_report", "create_booking", "cancel_booking"}
        assert [str(r.uri) for r in (await s.list_resources()).resources] == ["hotel://policies"]
        assert [p.name for p in (await s.list_prompts()).prompts] == ["front_desk_briefing"]


@pytest.mark.anyio
async def test_availability_tells_the_model_today():
    async with create_connected_server_and_client_session(mcp) as s:
        out = json.loads(text(await s.call_tool("check_availability", {"check_in": d(1), "check_out": d(2)})))
        assert out["today"] == date.today().isoformat() and out["rooms"]


@pytest.mark.anyio
async def test_errors_come_back_as_tool_errors():
    async with create_connected_server_and_client_session(mcp) as s:
        missing = await s.call_tool("get_booking", {"locator": "ZZZ999"})
        assert missing.isError and "No booking" in text(missing)


@pytest.mark.anyio
async def test_cancel_needs_confirm():
    async with create_connected_server_and_client_session(mcp) as s:
        ask = await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request"})
        assert "Ask the user" in text(ask)
        with core.connect() as db:
            assert core.get_booking(db, "RTY321")["status"] == "confirmed"      # nothing changed yet
        done = await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request", "confirm": True})
        assert json.loads(text(done))["status"] == "cancelled"


@pytest.mark.anyio
async def test_create_booking_needs_confirm():
    args = {"room_id": "203", "guest_name": "Eva Ruiz", "guest_email": "eva@example.com", "guests": 2,
            "check_in": d(10), "check_out": d(12)}
    async with create_connected_server_and_client_session(mcp) as s:
        assert "240 EUR" in text(await s.call_tool("create_booking", args))
        booked = json.loads(text(await s.call_tool("create_booking", {**args, "confirm": True})))
        assert booked["status"] == "confirmed" and booked["source"] == "mcp"
