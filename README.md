# hotel-mcp

A small hotel booking system with two front doors: a **web front desk** for staff and an **MCP server** so an AI assistant (Claude Desktop, Claude Code, Cursor…) can check availability and create or cancel bookings. Both use the same SQLite database, so a booking made by the assistant shows up on the front-desk screen within seconds, marked in purple.

I built it to practise MCP with the official Python SDK, kept deliberately small: the MCP server is one short file of thin tools over the booking engine.

```
You:     Is there a double free next weekend?
Claude:  ⏵ check_availability
         Yes: room 202 from Friday to Sunday, 220 EUR. Shall I book it?
You:     Yes, for Eva Ruiz, eva@example.com.
Claude:  ⏵ create_booking (confirm=false) → "book room 202 for Eva Ruiz… 220 EUR?"
         ⏵ create_booking (confirm=true)
         Booked: locator K7Q2MZ, room 202, 220 EUR.
```
<sub>Illustrative conversation; the exact wording depends on the assistant.</sub>

## How it fits together

```
 Claude / Cursor / Claude Code            Browser
          │ MCP (stdio or Streamable HTTP)    │ HTTP JSON
          ▼                                   ▼
   hotel/mcp_server.py                 hotel/web.py  +  static/index.html
   5 tools · 1 resource · 1 prompt     FastAPI · availability grid · activity log
          └──────────────┬────────────────────┘
                         ▼
                   hotel/core.py     booking rules, transactions, audit log
                         ▼
                      hotel.db       SQLite (created and seeded on first run)
```

## What the MCP server exposes

| | Name | What it does |
|---|---|---|
| tool | `check_availability` | Rooms free for a stay that fit the party, cheapest first, plus today's date |
| tool | `get_booking` | One booking by locator |
| tool | `occupancy_report` | Who is staying, arriving and leaving on a day |
| tool | `create_booking` | Books a room; needs `confirm=true` (see below) |
| tool | `cancel_booking` | Cancels a booking; needs `confirm=true` |
| resource | `hotel://policies` | Cancellation and stay rules |
| prompt | `front_desk_briefing` | Morning summary of arrivals and departures |

## A few decisions

- **The user confirms, not the model.** Writing tools first return a question with the price or refund ("Ask the user: …") and only act when called again with `confirm=true`. The tool description tells the model to do that only after the user says yes.
- **The rules live in one place.** `core.py` holds availability, pricing, the 48 h cancellation policy and the audit log; the MCP tools and the web API are thin layers over it.
- **No double bookings.** Availability is checked and the booking written inside one `BEGIN IMMEDIATE` SQLite transaction, so the web and the assistant cannot take the same room at once.
- **Errors the model can act on.** Broken rules raise with a message saying what to do ("Room 102 is not free … Use check_availability"); the SDK returns them as tool errors (`isError`).
- **The model is told the date.** It does not know what day it is, so `check_availability` returns `today` and relative requests like "next weekend" resolve correctly.

## Run it

Requires Python 3.10+.

```bash
git clone https://github.com/ianfloresfdez/hotel-mcp
cd hotel-mcp
python -m venv .venv
.venv/Scripts/activate        # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev]"
```

**Front desk:** `hotel-web`, then open http://127.0.0.1:8850

**Claude Desktop:** add this to `claude_desktop_config.json` and restart Claude:

```json
{
  "mcpServers": {
    "hotel": {
      "command": "C:/path/to/hotel-mcp/.venv/Scripts/hotel-mcp.exe"
    }
  }
}
```

On macOS/Linux the command is `/path/to/hotel-mcp/.venv/bin/hotel-mcp`.

**Claude Code:** `claude mcp add hotel -- /path/to/hotel-mcp/.venv/Scripts/hotel-mcp.exe`

**MCP Inspector:** `npx @modelcontextprotocol/inspector .venv/Scripts/hotel-mcp.exe`

**Streamable HTTP:** `hotel-mcp --http` serves http://127.0.0.1:8851/mcp. It has no authentication: keep it on localhost.

## Tests

```bash
pytest
```

19 tests: the booking rules in `core.py` (overlaps, capacity, idempotency, validation messages, cancellation terms, audit) and the MCP server driven through a real client session in memory.

## What I would add next

- **Elicitation** for confirmations, so the client shows a confirm dialog instead of relying on the model to ask.
- **OAuth 2.1** on the HTTP transport, and per-user authorisation so a guest only sees their own bookings.
- Treat guest-written text (special requests) as untrusted data when it is returned to the model.
- Postgres, rate limiting and tracing per tool call.

## License

MIT
