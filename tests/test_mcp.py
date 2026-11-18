"""Talks to the MCP server through a real client session (in memory), like Claude Desktop would."""

import json
import re
from datetime import date, timedelta

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from hotel import core
from hotel import mcp_server
from hotel.mcp_server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "mcp.db")
    mcp_server.recent_changes.clear()


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


def code_in(result) -> str:
    return re.search(r"confirmation_code=(\w+)", text(result)).group(1)


BOOKING = {"room_id": "203", "guest_name": "Eva Ruiz", "guest_email": "eva@example.com", "guests": 2}


@pytest.mark.anyio
async def test_cancel_needs_the_code():
    async with create_connected_server_and_client_session(mcp) as s:
        ask = await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request"})
        assert "Ask the user" in text(ask)
        with core.connect() as db:
            assert core.get_booking(db, "RTY321")["status"] == "confirmed"      # nothing changed yet
        done = await s.call_tool("cancel_booking", {"locator": "RTY321", "reason": "Guest request",
                                                    "confirmation_code": code_in(ask)})
        assert json.loads(text(done))["status"] == "cancelled"


@pytest.mark.anyio
async def test_create_booking_needs_the_code():
    args = {**BOOKING, "check_in": d(10), "check_out": d(12)}
    async with create_connected_server_and_client_session(mcp) as s:
        ask = await s.call_tool("create_booking", args)
        assert "240 EUR" in text(ask)
        booked = json.loads(text(await s.call_tool("create_booking", {**args, "confirmation_code": code_in(ask)})))
        assert booked["status"] == "confirmed" and booked["source"] == "mcp"


@pytest.mark.anyio
async def test_made_up_code_is_rejected():
    args = {**BOOKING, "check_in": d(10), "check_out": d(12), "confirmation_code": "12345678"}
    async with create_connected_server_and_client_session(mcp) as s:
        out = await s.call_tool("create_booking", args)
        assert out.isError and "Wrong confirmation_code" in text(out)


@pytest.mark.anyio
async def test_code_stops_working_if_the_data_changes():
    args = {**BOOKING, "check_in": d(10), "check_out": d(12)}
    async with create_connected_server_and_client_session(mcp) as s:
        code = code_in(await s.call_tool("create_booking", args))
        out = await s.call_tool("create_booking", {**args, "check_out": d(14), "confirmation_code": code})
        assert out.isError                      # the user approved 2 nights, not 4


@pytest.mark.anyio
async def test_retry_does_not_book_twice():
    args = {**BOOKING, "check_in": d(10), "check_out": d(12)}
    async with create_connected_server_and_client_session(mcp) as s:
        args["confirmation_code"] = code_in(await s.call_tool("create_booking", args))
        first = json.loads(text(await s.call_tool("create_booking", args)))
        again = json.loads(text(await s.call_tool("create_booking", args)))
        assert again["locator"] == first["locator"] and again["idempotent_replay"]


@pytest.mark.anyio
async def test_bad_input_is_rejected_before_the_database():
    async with create_connected_server_and_client_session(mcp) as s:
        assert (await s.call_tool("get_booking", {"locator": "' OR 1=1 --"})).isError
        assert (await s.call_tool("check_availability", {"check_in": d(1), "check_out": d(2), "guests": 50})).isError


@pytest.mark.anyio
async def test_model_does_not_see_full_emails():
    async with create_connected_server_and_client_session(mcp) as s:
        b = json.loads(text(await s.call_tool("get_booking", {"locator": "ABC123"})))
        assert b["guest_email"] == "a***@example.com" and "idempotency_key" not in b


@pytest.mark.anyio
async def test_too_many_changes_are_blocked():
    async with create_connected_server_and_client_session(mcp) as s:
        results = []
        for n in range(6):
            args = {**BOOKING, "check_in": d(20 + 2 * n), "check_out": d(21 + 2 * n)}
            args["confirmation_code"] = code_in(await s.call_tool("create_booking", args))
            results.append(await s.call_tool("create_booking", args))
        assert not any(r.isError for r in results[:5])
        assert results[5].isError and "Too many changes" in text(results[5])
