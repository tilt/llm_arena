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
