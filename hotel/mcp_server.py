"""MCP server for the hotel: thin tools over hotel/core.py, the same engine the web app uses.

    hotel-mcp            # stdio, for Claude Desktop / Claude Code
    hotel-mcp --http     # Streamable HTTP on http://127.0.0.1:8851/mcp
"""

import sys
from datetime import date

from mcp.server.fastmcp import FastMCP

from hotel import core

mcp = FastMCP("hotel", instructions="Front desk of a small hotel. Dates are YYYY-MM-DD.", port=8851)


@mcp.tool()
def check_availability(check_in: str, check_out: str, guests: int = 1) -> dict:
    """Rooms free for the whole stay that fit the party, cheapest first. Also returns today's date."""
    with core.connect() as db:
        return {"today": date.today().isoformat(), "rooms": core.availability(db, check_in, check_out, guests)}


@mcp.tool()
def get_booking(locator: str) -> dict:
    """One booking by its 6-character locator, e.g. ABC123."""
    with core.connect() as db:
        return core.get_booking(db, locator)


@mcp.tool()
def occupancy_report(day: str = "") -> dict:
    """Who is staying, arriving and leaving on a day (default: today)."""
    with core.connect() as db:
        return core.occupancy(db, day or None)


@mcp.tool()
def create_booking(room_id: str, guest_name: str, guest_email: str, guests: int,
                   check_in: str, check_out: str, confirm: bool = False) -> dict | str:
    """Books a room. First call it with confirm=false, show the user the price,
    and call again with confirm=true only if the user says yes."""
    with core.connect() as db:
        if not confirm:
            room = next((r for r in core.availability(db, check_in, check_out, guests) if r["id"] == room_id), None)
            if not room:
                raise ValueError(f"Room {room_id} is not free for those dates. Use check_availability.")
            return f"Ask the user: book room {room_id} for {guest_name}, {check_in} to {check_out}, {room['total']:.0f} EUR?"
        return core.create_booking(db, room_id=room_id, guest_name=guest_name, guest_email=guest_email,
                                   guests=guests, check_in=check_in, check_out=check_out, source="mcp")


@mcp.tool()
def cancel_booking(locator: str, reason: str, confirm: bool = False) -> dict | str:
    """Cancels a booking. First call it with confirm=false, show the user the refund,
    and call again with confirm=true only if the user says yes."""
    with core.connect() as db:
        if not confirm:
            terms = core.cancellation_terms(core.get_booking(db, locator))
            return f"Ask the user: cancel {locator.upper()}? Refund {terms['refund']:.0f} EUR, fee {terms['fee']:.0f} EUR."
        return core.cancel_booking(db, locator, reason, source="mcp")


@mcp.resource("hotel://policies")
def policies() -> str:
    """Cancellation and stay rules."""
    return "Free cancellation until 48 h before check-in (14:00); after that the first night is charged. Max 30 nights."


@mcp.prompt()
def front_desk_briefing() -> str:
    """Morning summary for the front desk."""
    return "Using the hotel tools, tell me today's arrivals and departures and anything to prepare."


def main() -> None:
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")


if __name__ == "__main__":
    main()
