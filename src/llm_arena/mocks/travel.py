"""Mock travel services (flights, hotels, calendar) with an injected failure.

Some flights appear in search results but are sold out at booking time — the agent must notice
and recover (replan), which is what the planning scenario measures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import Field

from llm_arena.tools.registry import Tool, tool

CITY_CODES = {"Ostreva": "OST", "Pellmoor": "PEL", "Varrel": "VAR"}

# id, origin, destination, departs, arrives, price_eur, sold_out_on_booking
FLIGHTS: list[tuple[str, str, str, str, str, float, bool]] = [
    ("CA101", "OST", "PEL", "2026-06-09T07:10", "2026-06-09T08:25", 89.0, False),  # clashes with the calendar
    ("CA117", "OST", "PEL", "2026-06-09T16:05", "2026-06-09T17:20", 119.0, True),  # sold out at booking
    ("WM240", "OST", "PEL", "2026-06-09T18:40", "2026-06-09T19:55", 164.0, False),
    ("WM252", "OST", "PEL", "2026-06-09T21:30", "2026-06-09T22:45", 99.0, False),  # arrives too late
    ("CA130", "PEL", "OST", "2026-06-12T15:20", "2026-06-12T16:35", 92.0, False),  # leaves too early
    ("CA134", "PEL", "OST", "2026-06-12T18:15", "2026-06-12T19:30", 128.0, False),
    ("WM266", "PEL", "OST", "2026-06-12T20:50", "2026-06-12T22:05", 149.0, False),
    ("NR410", "PEL", "VAR", "2026-06-20T06:30", "2026-06-20T08:40", 139.0, True),  # sold out at booking
    ("NR414", "PEL", "VAR", "2026-06-20T08:15", "2026-06-20T10:25", 155.0, False),
    ("WM418", "PEL", "VAR", "2026-06-20T09:50", "2026-06-20T12:05", 118.0, False),  # arrives after noon
    ("NR422", "PEL", "VAR", "2026-06-20T10:10", "2026-06-20T11:55", 171.0, False),
]

# id, city, name, stars, price_per_night, km_to (landmark -> distance)
HOTELS: list[tuple[str, str, str, int, float, dict[str, float]]] = [
    ("H-PEL-1", "Pellmoor", "Hotel Kessel", 4, 185.0, {"Kessel Hall": 0.3}),
    ("H-PEL-2", "Pellmoor", "The Selm Quay", 4, 142.0, {"Kessel Hall": 1.6}),
    ("H-PEL-3", "Pellmoor", "Budget Inn Pellmoor", 2, 69.0, {"Kessel Hall": 0.8}),
    ("H-PEL-4", "Pellmoor", "Grand Westmarch", 5, 240.0, {"Kessel Hall": 2.9}),
    ("H-VAR-1", "Varrel", "Oskel Riverside", 3, 118.0, {"Varrel Old Town": 1.1}),
    ("H-VAR-2", "Varrel", "Old Town Loft", 4, 149.0, {"Varrel Old Town": 0.2}),
    ("H-VAR-3", "Varrel", "Varrel Plaza", 4, 172.0, {"Varrel Old Town": 0.1}),
    ("H-VAR-4", "Varrel", "Station Hostel", 2, 55.0, {"Varrel Old Town": 2.4}),
]

CALENDAR = [
    {"title": "Team retro (Ostreva office)", "start": "2026-06-09T13:00", "end": "2026-06-09T15:30"},
    {"title": "Design Summit", "start": "2026-06-10T09:00", "end": "2026-06-12T16:00"},
    {"title": "Dentist", "start": "2026-06-19T08:00", "end": "2026-06-19T09:00"},
]


@dataclass
class TravelAgency:
    bookings: list[dict[str, Any]] = field(default_factory=list)
    failed_bookings: list[str] = field(default_factory=list)

    def active(self) -> list[dict[str, Any]]:
        return [booking for booking in self.bookings if booking["status"] == "confirmed"]

    def tools(self) -> list[Tool]:
        return _travel_tools(self)


def _flight(flight: tuple[str, str, str, str, str, float, bool]) -> dict[str, Any]:
    flight_id, origin, destination, departs, arrives, price, _ = flight
    return {
        "flight_id": flight_id,
        "origin": origin,
        "destination": destination,
        "departs": departs,
        "arrives": arrives,
        "price_eur": price,
    }


def _travel_tools(agency: TravelAgency) -> list[Tool]:
    @tool
    def search_flights(
        origin: Annotated[str, Field(description="City name or code, e.g. Ostreva / OST")],
        destination: Annotated[str, Field(description="City name or code")],
        date: Annotated[str, Field(description="YYYY-MM-DD")],
    ) -> list[dict[str, Any]]:
        """Find flights on a date. Prices are per person in EUR; times are local."""
        o, d = CITY_CODES.get(origin, origin.upper()), CITY_CODES.get(destination, destination.upper())
        return [_flight(f) for f in FLIGHTS if f[1] == o and f[2] == d and f[3].startswith(date)]

    @tool(permission="write")
    def book_flight(flight_id: str) -> dict[str, Any]:
        """Book a flight by id. Returns a booking id, or an error if the flight is unavailable."""
        flight = next((f for f in FLIGHTS if f[0] == flight_id), None)
        if flight is None:
            raise ValueError(f"unknown flight {flight_id}")
        if flight[6]:
            agency.failed_bookings.append(flight_id)
            raise RuntimeError(f"flight {flight_id} is sold out")
        booking = {
            "booking_id": f"B{len(agency.bookings) + 1:03d}",
            "type": "flight",
            "status": "confirmed",
            **_flight(flight),
        }
        agency.bookings.append(booking)
        return booking

    @tool
    def search_hotels(
        city: str,
        check_in: Annotated[str, Field(description="YYYY-MM-DD")],
        nights: int,
    ) -> list[dict[str, Any]]:
        """Find hotels in a city with total price for the stay and distances to landmarks (km)."""
        return [
            {
                "hotel_id": h[0],
                "name": h[2],
                "stars": h[3],
                "price_per_night_eur": h[4],
                "total_eur": h[4] * nights,
                "distance_km": h[5],
                "check_in": check_in,
                "nights": nights,
            }
            for h in HOTELS
            if h[1].lower() == city.lower()
        ]

    @tool(permission="write")
    def book_hotel(hotel_id: str, check_in: str, nights: int) -> dict[str, Any]:
        """Book a hotel stay. Returns a booking id."""
        hotel = next((h for h in HOTELS if h[0] == hotel_id), None)
        if hotel is None:
            raise ValueError(f"unknown hotel {hotel_id}")
        booking = {
            "booking_id": f"B{len(agency.bookings) + 1:03d}",
            "type": "hotel",
            "status": "confirmed",
            "hotel_id": hotel_id,
            "name": hotel[2],
            "city": hotel[1],
            "check_in": check_in,
            "nights": nights,
            "total_eur": hotel[4] * nights,
        }
        agency.bookings.append(booking)
        return booking

    @tool
    def get_calendar(start_date: str, end_date: str) -> list[dict[str, str]]:
        """List the traveller's calendar entries between two dates (inclusive)."""
        return [event for event in CALENDAR if start_date <= event["start"][:10] <= end_date]

    @tool(permission="destructive")
    def cancel_booking(booking_id: str) -> str:
        """Cancel a confirmed booking."""
        booking = next((b for b in agency.bookings if b["booking_id"] == booking_id), None)
        if booking is None:
            raise ValueError(f"unknown booking {booking_id}")
        booking["status"] = "cancelled"
        return f"{booking_id} cancelled"

    return [search_flights, book_flight, search_hotels, book_hotel, get_calendar, cancel_booking]
