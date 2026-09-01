

import sqlite3

import load_items


def _connect():
    return sqlite3.connect(load_items.db_path)


def reserve(items) -> tuple[bool, str]:
    """Atomically decrement stock for every item, or change nothing."""
    con = _connect()
    try:
        con.execute("begin immediate")
        for item in items:
            cur = con.execute(
                "update items set available_quantity = available_quantity - ? "
                "where product_id = ? and available_quantity >= ?",
                (item.quantity, int(item.product_id), item.quantity))
            if cur.rowcount == 0:
                con.rollback()
                return False, f"{item.name} is no longer available in that quantity."
        con.commit()
        return True, ""
    except (sqlite3.Error, ValueError) as e:
        con.rollback()
        return False, str(e)
    finally:
        con.close()


def release(items) -> None:
    """Put reserved stock back after a failed payment."""
    con = _connect()
    try:
        con.execute("begin immediate")
        for item in items:
            con.execute(
                "update items set available_quantity = available_quantity + ? "
                "where product_id = ?",
                (item.quantity, int(item.product_id)))
        con.commit()
    except (sqlite3.Error, ValueError):
        con.rollback()
    finally:
        con.close()