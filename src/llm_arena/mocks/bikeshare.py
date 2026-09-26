"""Seeded SQLite database of a fictional bike-rental company ("Veloria Bikes").

The schema contains deliberate traps that a text-only reading of the SQL tends to miss but the
query *results* reveal: money is stored in cents, refunds are negative ledger amounts, deposit
returns are not revenue, and a few bikes were never rented. That makes it a good testbed for
reflection with external (execution) feedback.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE stations (
    station_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE bikes (
    bike_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    category TEXT NOT NULL,          -- 'city', 'e-bike', 'cargo'
    home_station_id INTEGER REFERENCES stations(station_id)
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    joined_on TEXT NOT NULL          -- ISO date
);
CREATE TABLE rentals (
    rental_id INTEGER PRIMARY KEY,
    bike_id INTEGER REFERENCES bikes(bike_id),
    customer_id INTEGER REFERENCES customers(customer_id),
    start_station_id INTEGER REFERENCES stations(station_id),
    end_station_id INTEGER REFERENCES stations(station_id),
    started_at TEXT NOT NULL,        -- ISO timestamp
    ended_at TEXT NOT NULL
);
CREATE TABLE ledger (
    entry_id INTEGER PRIMARY KEY,
    rental_id INTEGER REFERENCES rentals(rental_id),
    entry_type TEXT NOT NULL,        -- 'rental_fee', 'refund', 'damage_fee', 'deposit', 'deposit_return'
    amount_cents INTEGER NOT NULL,   -- refunds and deposit returns are negative
    booked_at TEXT NOT NULL
);
"""

_STATIONS = [
    (1, "Old Harbour", "Harborview"),
    (2, "Market Square", "Harborview"),
    (3, "University Gate", "Harborview"),
    (4, "Riverside Mill", "Linden Falls"),
    (5, "Central Depot", "Linden Falls"),
    (6, "Hilltop Park", "Kessel"),
]
_MODELS = [
    ("Stroller 3", "city"),
    ("Stroller 5", "city"),
    ("Volt Cruiser", "e-bike"),
    ("Volt Summit", "e-bike"),
    ("Haul XL", "cargo"),
]
_FIRST = [
    "Ada",
    "Bram",
    "Cleo",
    "Dario",
    "Elin",
    "Farid",
    "Greta",
    "Hugo",
    "Ines",
    "Jonas",
    "Kaia",
    "Lev",
    "Mira",
    "Nils",
]
_LAST = ["Arden", "Brook", "Castell", "Dunmore", "Eske", "Fairholm", "Grell", "Hask"]
_HOURLY_CENTS = {"city": 300, "e-bike": 650, "cargo": 900}


def build_database(path: Path, seed: int = 7) -> Path:
    """Create (or overwrite) the database at `path` deterministically from `seed`."""
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO stations VALUES (?, ?, ?)", _STATIONS)
        bikes = []
        for bike_id in range(1, 41):
            model, category = _MODELS[rng.randrange(len(_MODELS))]
            bikes.append((bike_id, model, category, rng.choice(_STATIONS)[0]))
        db.executemany("INSERT INTO bikes VALUES (?, ?, ?, ?)", bikes)
        customers = [
            (
                cid,
                f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
                f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            )
            for cid in range(1, 61)
        ]
        db.executemany("INSERT INTO customers VALUES (?, ?, ?)", customers)
        _insert_rentals(db, rng, bikes)
    return path


def _insert_rentals(db: sqlite3.Connection, rng: random.Random, bikes: list[tuple[int, str, str, int]]) -> None:
    # Bikes 37-40 are never rented, for "which bikes were never rented" questions.
    rentable = [bike for bike in bikes if bike[0] <= 36]
    base = datetime(2026, 1, 1, 6, 0)
    entry_id = 1
    for rental_id in range(1, 451):
        bike_id, _, category, _ = rng.choice(rentable)
        started = base + timedelta(days=rng.randint(0, 150), minutes=rng.randint(0, 14 * 60))
        minutes = max(5, int(rng.lognormvariate(3.8, 0.7)))
        ended = started + timedelta(minutes=minutes)
        start_station = rng.choice(_STATIONS)[0]
        end_station = start_station if rng.random() < 0.6 else rng.choice(_STATIONS)[0]
        db.execute(
            "INSERT INTO rentals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rental_id,
                bike_id,
                rng.randint(1, 60),
                start_station,
                end_station,
                started.isoformat(),
                ended.isoformat(),
            ),
        )
        fee = max(100, round(_HOURLY_CENTS[category] * minutes / 60))
        entries = [("deposit", 5000), ("deposit_return", -5000), ("rental_fee", fee)]
        if rng.random() < 0.08:
            entries.append(("refund", -round(fee * rng.choice([0.5, 1.0]))))
        if rng.random() < 0.05:
            entries.append(("damage_fee", rng.choice([1500, 2500, 4000])))
        for entry_type, amount in entries:
            booked = ended if entry_type != "deposit" else started
            db.execute(
                "INSERT INTO ledger VALUES (?, ?, ?, ?, ?)",
                (entry_id, rental_id, entry_type, amount, booked.isoformat()),
            )
            entry_id += 1


def schema_text() -> str:
    return SCHEMA.strip()
