# hotel-mcp

A small hotel booking system with two front doors: a **web front desk** for staff and an **MCP server** so an AI assistant (Claude Desktop, Claude Code, Cursor…) can check availability, look up, create and cancel bookings. Both write to the same SQLite database, so a booking made by the assistant appears on the front-desk screen within seconds, marked as made through MCP.

I built it to practise the patterns that matter when AI agents operate on a real booking system: confirmation before anything irreversible, idempotent retries, no double bookings, minimal data to the model, and guest-written text treated as untrusted.

```
You:     Who arrives today, and is there anything we need to prepare?
Claude:  ⏵ occupancy_report
         Occupancy tonight: 2/6 rooms (33%). One arrival: Marta Soler, suite 301, 3 guests until Friday.
         Her special request was withheld because it contained instructions aimed at the AI assistant,
         so please check it on the front-desk screen.

You:     Cancel Jordi Puig's booking, he called to say he can't come.
Claude:  ⏵ find_bookings → ⏵ cancel_booking
         [Confirm] Cancel booking RTY321 (Jordi Puig, room 202, …)? Refund 220 EUR.   ← you click Confirm
         Done: RTY321 is cancelled and 220 EUR will be refunded.
```
<sub>Illustrative conversation; the exact wording depends on the assistant.</sub>

## How it fits together

```
 Claude / Cursor / Claude Code            Browser
          │ MCP (stdio or Streamable HTTP)    │ HTTP JSON
          ▼                                   ▼
   hotel/mcp_server.py                 hotel/web.py  +  static/index.html
   7 tools · 2 resources · 1 prompt    FastAPI · availability grid · audit log
          └──────────────┬────────────────────┘
                         ▼
                   hotel/core.py     booking rules, transactions, audit
                         ▼
                      hotel.db       SQLite (created and seeded on first run)
```

## MCP tools

| Tool | Type | What it does |
|---|---|---|
| `list_rooms` | read | Rooms with type, capacity and nightly price |
| `check_availability` | read | Rooms free for a whole stay that fit the party, cheapest first, with the total |
| `get_booking` | read | One booking by locator, plus the cancellation terms that would apply now |
| `find_bookings` | read | A guest's bookings (by email) or everyone staying on a date. A filter is required |
| `occupancy_report` | read | Occupancy, arrivals and departures for a night |
| `create_booking` | write | Books a room after the user confirms the room and price. Takes an `idempotency_key` |
| `cancel_booking` | **destructive** | Cancels after the user confirms, showing the refund and any fee |

Resources: `hotel://policies` (cancellation and stay rules) and `hotel://rooms`.
Prompt: `front_desk_briefing`, the morning summary of arrivals, departures and guest requests.

## Design choices

- **The user confirms, not the model.** `create_booking` and `cancel_booking` ask the user through MCP *elicitation* (a confirmation dialog in the client). Clients without elicitation get an error telling the model to ask the user and call again with `confirm=true`. A declined confirmation changes nothing.
- **Retries never book twice.** `create_booking` accepts an `idempotency_key`: repeating the call returns the first booking. Cancelling an already cancelled booking is a no-op.
- **No double bookings.** Availability is checked and the booking is written inside one `BEGIN IMMEDIATE` transaction, so two requests (web and MCP at once) cannot take the same room.
- **Guest text is data, not instructions.** Special requests come back wrapped in `<guest_text untrusted>`, and text that talks to the AI assistant is withheld. The seed data includes one such request to show it. This is one layer only; the confirmation step is what actually stops an injected cancellation.
- **The model sees only what it needs.** Emails are masked (`a***@example.com`) and idempotency keys are never returned. `find_bookings` refuses to list everything and caps results at 20.
- **Errors say what to do next.** Broken rules come back as tool errors the model can act on ("Room 102 is not free from … Check availability for other rooms").
- **Validated inputs.** Pydantic types with patterns and ranges on every argument (locators, ISO dates, party size, lengths).
- **Annotated tools.** `readOnlyHint` on reads, `destructiveHint` on cancellation, `idempotentHint` where it holds.
- **Everything is audited.** Every booking and cancellation is logged with its source (`web` or `mcp`) and shown on the front desk.
- **stdio-safe.** Logs go to stderr, because stdout carries the protocol.

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

On macOS/Linux the command is `/path/to/hotel-mcp/.venv/bin/hotel-mcp`. Set `HOTEL_DB` in an `env` block to use another database file.

**Claude Code:** `claude mcp add hotel -- /path/to/hotel-mcp/.venv/Scripts/hotel-mcp.exe`

**Remote (Streamable HTTP):** `hotel-mcp --http` serves http://127.0.0.1:8851/mcp. It has no authentication: keep it on localhost.

**MCP Inspector:** `npx @modelcontextprotocol/inspector .venv/Scripts/hotel-mcp.exe`

Keep the front desk open while you talk to the assistant: its changes appear there, in purple.

## Try it

- "What rooms are free from next Friday to Sunday for two people?"
- "Book the cheapest one for Eva Ruiz, eva@example.com."
- "Give me today's front desk briefing." (the `front_desk_briefing` prompt)
- "What would it cost Ana García to cancel ABC123 now?"
- "Cancel QWE456 because the guest note says so." It will ask you first. Say no.

## Tests

```bash
pytest
```

20 tests. The core tests cover overlap rules, capacity, idempotency, validation messages, cancellation terms and the audit log. The MCP tests drive the server through a real client session in memory: tool and resource listing, argument validation, the injection guard, confirmation with and without elicitation, and idempotent booking.

## Before this goes near real guests

This is a learning project. For production I would add:
- **Authentication**: OAuth 2.1 on the HTTP transport (validate the token's audience and scopes), and staff identity on the web app.
- **Per-user authorisation**: a guest-facing assistant must only see that guest's bookings, decided by the token and never by an id the model sends.
- **Postgres** instead of SQLite, rate limiting, OpenTelemetry traces per tool call, and evals that check the assistant picks the right tool with the right arguments.
- A **payment provider** behind its own confirmation flow; this demo stores no card data at all.

## License

MIT
