"""Front-desk web app: a JSON API over the booking engine plus one static page.

    python -m hotel.web        # http://127.0.0.1:8850
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hotel import core

app = FastAPI(title="Hotel front desk", version="0.1.0")
STATIC = Path(__file__).parent / "static"


def run(fn, *args, **kwargs):
    try:
        with core.connect() as conn:
            return fn(conn, *args, **kwargs)
    except core.HotelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


class NewBooking(BaseModel):
    room_id: str = Field(pattern=r"^\d{3}$")
    guest_name: str = Field(min_length=2, max_length=80)
    guest_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    guests: int = Field(ge=1, le=4)
    check_in: str
    check_out: str
    special_requests: str = Field(default="", max_length=500)


class Cancel(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/rooms")
def rooms() -> list[dict]:
    return run(core.list_rooms)


@app.get("/api/bookings")
def bookings(include_cancelled: bool = True) -> list[dict]:
    return run(core.find_bookings, include_cancelled=include_cancelled)


@app.get("/api/availability")
def availability(check_in: str, check_out: str, guests: int = 1) -> list[dict]:
    return run(core.availability, check_in, check_out, guests)


@app.get("/api/occupancy")
def occupancy(date: str | None = None) -> dict:
    return run(core.occupancy, date)


@app.get("/api/audit")
def audit(limit: int = 30) -> list[dict]:
    return run(core.audit_log, min(limit, 200))


@app.post("/api/bookings", status_code=201)
def create(b: NewBooking) -> dict:
    return run(core.create_booking, **b.model_dump(), source="web")


@app.post("/api/bookings/{locator}/cancel")
def cancel(locator: str, c: Cancel) -> dict:
    return run(core.cancel_booking, locator, c.reason, source="web")


@app.post("/api/reset")
def reset() -> dict:
    run(core.reset_demo)
    return {"ok": True}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8850)


if __name__ == "__main__":
    main()
