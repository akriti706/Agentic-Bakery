"""Append-only record of every payment attempt."""

import csv
import json
import os
import sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "orders.db")
CSV_PATH = os.path.join(BASE, "data", "orders.csv")

COLUMNS = ["id", "created_at", "customer_id", "session_id", "mandate_id",
           "status", "provider", "reference", "amount", "saved",
           "item_count", "items", "message"]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            mandate_id  TEXT,
            status      TEXT NOT NULL,
            provider    TEXT NOT NULL,
            reference   TEXT,
            amount      REAL NOT NULL,
            saved       REAL DEFAULT 0,
            item_count  INTEGER NOT NULL,
            items       TEXT NOT NULL,
            message     TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_customer "
                 "ON orders(customer_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_session "
                 "ON orders(session_id)")
    conn.commit()
    conn.close()


def record(customer_id, session_id, mandate_id, basket, result) -> int:
    conn = _connect()
    cursor = conn.execute(
        """INSERT INTO orders
           (created_at, customer_id, session_id, mandate_id, status,
            provider, reference, amount, saved, item_count, items, message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(timespec="seconds"), str(customer_id),
         session_id, mandate_id, result.status, result.provider,
         result.reference, basket.total, basket.saved, len(basket.items),
         json.dumps([i.as_dict() for i in basket.items]), result.message))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()
    return order_id


def _rows_to_dicts(rows):
    out = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        out.append(order)
    return out


def for_customer(customer_id, limit=50) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? "
        "ORDER BY id DESC LIMIT ?", (str(customer_id), limit)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def all_orders(limit=500) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def export_csv(path=CSV_PATH) -> str:
    conn = _connect()
    rows = conn.execute("SELECT * FROM orders ORDER BY id ASC").fetchall()
    conn.close()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in COLUMNS})
    return path


if __name__ == "__main__":
    init()
    print(f"Orders table ready in {DB_PATH}")