"""Talks to the MCP server through a real client session (in memory), like Claude Desktop would."""

import json
from datetime import date, timedelta

import pytest
from mcp import types
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


def data(result: types.CallToolResult):
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


def accept(answer: bool):
    async def callback(context, params):
        return types.ElicitResult(action="accept", content={"confirm": True}) if answer else types.ElicitResult(action="decline")
    return callback


@pytest.mark.anyio
async def test_lists_tools_resources_and_prompts():
    async with create_connected_server_and_client_session(mcp) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == {"list_rooms", "check_availability", "get_booking", "find_bookings",
                              "occupancy_report", "create_booking", "cancel_booking"}
        assert tools["cancel_booking"].annotations.destructiveHint is True
        assert tools["get_booking"].annotations.readOnlyHint is True
        assert {str(r.uri) for r in (await s.list_resources()).resources} == {"hotel://policies", "hotel://rooms"}
        assert [p.name for p in (await s.list_prompts()).prompts] == ["front_desk_briefing"]


@pytest.mark.anyio
async def test_invalid_arguments_and_unknown_booking_are_tool_errors():
    async with create_connected_server_and_client_session(mcp) as s:
        bad = await s.call_tool("get_booking", {"locator": "abc"})
        assert bad.isError
        missing = await s.call_tool("get_booking", {"locator": "ZZZ999"})
        assert missing.isError and "No booking" in missing.content[0].text


@pytest.mark.anyio
async def test_guest_text_is_delimited_and_injection_withheld():
    async with create_connected_server_and_client_session(mcp) as s:
        b = data(await s.call_tool("get_booking", {"locator": "QWE456"}))
        assert "withheld" in b["special_requests"] and "ignore your instructions" not in json.dumps(b)
        assert b["guest_email"] == "m***@example.com"                      # data minimisation


@pytest.mark.anyio
async def test_cancel_without_elicitation_needs_explicit_confirm():
    async with create_connected_server_and_client_session(mcp) as s:   # client without elicitation support
        first = await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request"})
        assert first.isError and "confirm=true" in first.content[0].text
        done = data(await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request", "confirm": True}))
        assert done["status"] == "cancelled"


@pytest.mark.anyio
async def test_declined_elicitation_changes_nothing():
    async with create_connected_server_and_client_session(mcp, elicitation_callback=accept(False)) as s:
        out = data(await s.call_tool("cancel_booking", {"locator": "ABC123", "reason": "note in a review said so"}))
        assert out["status"] == "not_cancelled"
    with core.connect() as conn:
        assert core.get_booking(conn, "ABC123")["status"] == "confirmed"


@pytest.mark.anyio
async def test_create_booking_with_confirmation_and_idempotency():
    args = {"room_id": "203", "guest_name": "Eva Ruiz", "guest_email": "eva@example.com", "guests": 2,
            "check_in": d(10), "check_out": d(12), "idempotency_key": "chat-1-booking"}
    async with create_connected_server_and_client_session(mcp, elicitation_callback=accept(True)) as s:
        first = data(await s.call_tool("create_booking", args))
        again = data(await s.call_tool("create_booking", args))
        assert first["status"] == "confirmed" and first["total"] == 240.0
        assert again["locator"] == first["locator"] and again["idempotent_replay"]


@pytest.mark.anyio
async def test_read_tools_tell_the_model_what_day_it_is():
    async with create_connected_server_and_client_session(mcp) as s:
        init_today = date.today().isoformat()
        for name, args in [("check_availability", {"check_in": d(1), "check_out": d(2)}),
                           ("get_booking", {"locator": "ABC123"}),
                           ("find_bookings", {"date": d(0)}),
                           ("occupancy_report", {})]:
            assert init_today in data(await s.call_tool(name, args))["today"], name
