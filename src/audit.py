"""
audit.py — append-only decision log.

Deliberately has no update() or delete(). An audit trail that can be
edited is not an audit trail.
"""

import sqlite3
import os
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "shop.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    """Create the audit table. Safe to call repeatedly."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            customer_id INT NOT NULL,
            detail      TEXT,
            event_type  TEXT NOT NULL,
            decision    TEXT,
            reason      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON audit_log(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer ON audit_log(customer_id, timestamp)")
    conn.commit()
    conn.close()


def log(session_id: str,
        event_type: str,
        customer_id: int,
        detail:str=None,
        decision: str = None,
        reason: str = None) -> None:
    
    conn = _connect()
    conn.execute(
        """INSERT INTO audit_log
              (timestamp, session_id, customer_id, event_type, detail, decision, reason)
              VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), session_id, customer_id,
         event_type, detail, decision, reason)
    )
    conn.commit()
    conn.close()


def get_session(session_id: str) -> list[dict]:
    """Full ordered story of one purchase attempt."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_recent_purchases(customer_id: str, minutes: int) -> int:
    """
    How many payments this customer completed in the last N minutes.
    Powers the velocity check in policy.py.
    """
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    conn = _connect()
    row = conn.execute(
        """SELECT COUNT(*) FROM audit_log
           WHERE customer_id = ?
             AND event_type = 'PAYMENT_RESULT'
             AND decision = 'SUCCESS'
             AND timestamp > ?""",
        (customer_id, cutoff)
    ).fetchone()
    conn.close()
    return row[0]


# Event types — use these constants, don't type strings by hand
REQUEST_RECEIVED = "REQUEST_RECEIVED"
SEARCH = "SEARCH"
BASKET_PROPOSED = "BASKET_PROPOSED"
POLICY_DECISION = "POLICY_DECISION"
STOCK_RESERVED = "STOCK_RESERVED"
STOCK_RELEASED = "STOCK_RELEASED"
PAYMENT_ATTEMPT = "PAYMENT_ATTEMPT"
PAYMENT_RESULT = "PAYMENT_RESULT"
RECOVERY_ATTEMPT = "RECOVERY_ATTEMPT"
SESSION_COMPLETE = "SESSION_COMPLETE"


if __name__ == "__main__":
    init()
    print(f"Audit table ready in {DB_PATH}")