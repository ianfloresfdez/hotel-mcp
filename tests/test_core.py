from datetime import date, datetime, timedelta

import pytest

from hotel import core


@pytest.fixture
def conn(tmp_path):
    with core.connect(tmp_path / "test.db") as c:
        yield c


def d(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def test_seed_creates_rooms_and_demo_bookings(conn):
    assert len(core.list_rooms(conn)) == 6
    assert core.get_booking(conn, "abc123")["guest_name"] == "Ana García"   # locator is case-insensitive


def test_availability_excludes_overlapping_stays(conn):
    # ABC123 holds room 201 from day 2 to day 5
    free = {r["id"] for r in core.availability(conn, d(3), d(4), guests=2)}
    assert "201" not in free and "202" in free
    # back-to-back stays do not overlap: checking in the day ABC123 checks out is fine
    assert "201" in {r["id"] for r in core.availability(conn, d(5), d(6), guests=2)}


def test_availability_respects_capacity_and_prices_the_stay(conn):
    rooms = core.availability(conn, d(20), d(23), guests=3)
    assert [r["id"] for r in rooms] == ["301"]
    assert rooms[0]["nights"] == 3 and rooms[0]["total"] == 660.0


def test_create_booking_and_double_booking_is_rejected(conn):
    b = core.create_booking(conn, room_id="102", guest_name="Eva", guest_email="eva@example.com", guests=1,
                            check_in=d(10), check_out=d(12))
    assert b["status"] == "confirmed" and b["total"] == 140.0 and len(b["locator"]) == 6
    with pytest.raises(core.HotelError, match="not free"):
        core.create_booking(conn, room_id="102", guest_name="Max", guest_email="max@example.com", guests=1,
                            check_in=d(11), check_out=d(13))


def test_idempotency_key_never_books_twice(conn):
    args = dict(room_id="203", guest_name="Eva", guest_email="eva@example.com", guests=2,
                check_in=d(10), check_out=d(11), idempotency_key="req-42")
    first = core.create_booking(conn, **args)
    again = core.create_booking(conn, **args)
    assert again["locator"] == first["locator"] and again["idempotent_replay"]
    assert len(core.find_bookings(conn, guest_email="eva@example.com")) == 1


@pytest.mark.parametrize("kwargs, message", [
    (dict(check_in=d(5), check_out=d(5)), "after check_in"),
    (dict(check_in=d(-3), check_out=d(-1)), "past"),
    (dict(check_in=d(1), check_out=d(40)), "30 nights"),
    (dict(check_in="tomorrow", check_out=d(3)), "YYYY-MM-DD"),
    (dict(check_in=d(1), check_out=d(2), guests=3), "takes 1 guest"),
    (dict(check_in=d(1), check_out=d(2), room_id="999"), "does not exist"),
])
def test_validation_errors_say_what_to_do(conn, kwargs, message):
    base = dict(room_id="102", guest_name="Eva", guest_email="eva@example.com", guests=1)
    with pytest.raises(core.HotelError, match=message):
        core.create_booking(conn, **{**base, **kwargs})


def test_cancellation_terms():
    booking = {"check_in": "2026-12-10", "check_out": "2026-12-13", "total": 300.0}
    early = core.cancellation_terms(booking, now=datetime(2026, 12, 1, 12, 0))
    late = core.cancellation_terms(booking, now=datetime(2026, 12, 9, 12, 0))
    assert early == {"free": True, "fee": 0.0, "refund": 300.0}
    assert late == {"free": False, "fee": 100.0, "refund": 200.0}


def test_cancel_is_idempotent_and_audited(conn):
    first = core.cancel_booking(conn, "RTY321", "Guest request")
    assert first["status"] == "cancelled" and first["refund"] == 220.0   # a week ahead: free
    again = core.cancel_booking(conn, "RTY321", "Guest request")
    assert again["already_cancelled"]
    assert [a["action"] for a in core.audit_log(conn)] == ["cancel_booking"]
    assert "202" in {r["id"] for r in core.availability(conn, d(7), d(9), guests=2)}


def test_occupancy(conn):
    o = core.occupancy(conn)
    assert o["rooms_total"] == 6 and o["rooms_occupied"] == 2          # XYZ789 and QWE456 stay tonight
    assert [b["locator"] for b in o["arrivals"]] == ["QWE456"]
