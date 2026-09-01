"""Read-only access to the shop's inventory."""

import sqlite3

import load_items

SEPARATORS = (";", "&")

RELAX_ORDER = ["taste", "occasion", "flavor", "query"]

_MULTI_COLUMNS = ("flavor", "occasion", "taste_profile", "recommendation")


def _connect():
    con = sqlite3.connect(load_items.db_path)
    con.row_factory = sqlite3.Row
    return con


def final_price(row):
    """Price the customer actually pays, after any discount."""
    discount = row.get("discount") or 0
    return round(row["price"] * (1 - discount / 100), 2)


def _decorate(row):
    row["final_price"] = final_price(row)
    row["on_sale"] = (row.get("discount") or 0) > 0
    return row


def _split(raw):
    parts = [str(raw)]
    for sep in SEPARATORS:
        parts = [p for chunk in parts for p in chunk.split(sep)]
    return [p.strip() for p in parts if p.strip()]


def enum_values(column):
    """Distinct values for a column, with compound cells split into tags."""
    con = _connect()
    try:
        rows = con.execute(
            f"select distinct {column} from items "
            f"where {column} is not null and trim({column}) != ''"
        ).fetchall()
    finally:
        con.close()

    values = set()
    for row in rows:
        if column in _MULTI_COLUMNS:
            values.update(_split(row[0]))
        else:
            values.add(str(row[0]).strip())
    return sorted(values)


def _build(filters, in_stock_only=True):
    sql = ("select * from items where available_quantity > 0"
           if in_stock_only else "select * from items where 1 = 1")
    params = []

    if filters.get("query"):
        sql += (" and (lower(item_name) like ? or lower(description) like ?"
                " or lower(flavor) like ? or lower(taste_profile) like ?"
                " or lower(recommendation) like ?)")
        term = f"%{filters['query'].lower()}%"
        params += [term] * 5

    if filters.get("max_price") is not None:
        sql += " and price * (1 - coalesce(discount, 0) / 100.0) <= ?"
        params.append(filters["max_price"])

    if filters.get("category"):
        sql += " and lower(category) = ?"
        params.append(filters["category"].lower())

    if filters.get("flavor"):
        sql += " and lower(flavor) like ?"
        params.append(f"%{filters['flavor'].lower()}%")

    if filters.get("occasion"):
        sql += " and lower(occasion) like ?"
        params.append(f"%{filters['occasion'].lower()}%")

    if filters.get("on_sale"):
        sql += " and coalesce(discount, 0) > 0"

    if filters.get("taste"):
        sql += " and lower(taste_profile) like ?"
        params.append(f"%{filters['taste'].lower()}%")

    return (sql + " order by price * (1 - coalesce(discount, 0) / 100.0) "
            "asc limit ?"), params


def _out_of_stock(con, filters, limit):
    """Products the original filters matched but that have no stock left."""
    sql, params = _build(filters, in_stock_only=False)
    rows = con.execute(sql, params + [limit]).fetchall()
    return [dict(r)["item_name"] for r in rows
            if dict(r)["available_quantity"] < 1]


def search_products(query=None, category=None, flavor=None, occasion=None,
                    taste=None, max_price=None, on_sale=None, limit=10,
                    relax=True):
    """
    Search the catalog.

    Returns results plus the filters that produced them and any that had
    to be dropped. Category and max_price are never relaxed: substituting
    a different kind of item, or overshooting a stated budget, is worse
    than returning nothing.
    """
    filters = {
        "query": query or None,
        "category": category or None,
        "flavor": flavor or None,
        "occasion": occasion or None,
        "taste": taste or None,
        "max_price": max_price,
        "on_sale": on_sale or None,
    }
    wanted = dict(filters)
    relaxed = []

    con = _connect()
    try:
        while True:
            sql, params = _build(filters)
            rows = con.execute(sql, params + [limit]).fetchall()
            if rows or not relax:
                break
            droppable = [k for k in RELAX_ORDER if filters.get(k)]
            if not droppable:
                break
            filters[droppable[0]] = None
            relaxed.append(droppable[0])

        sold_out = _out_of_stock(con, wanted, limit) if relaxed else []
    finally:
        con.close()

    return {
        "results": [_decorate(dict(r)) for r in rows],
        "applied": {k: v for k, v in filters.items() if v is not None},
        "relaxed": relaxed,
        "out_of_stock": sold_out,
    }


def get_product(product_id):
    """Authoritative row for one product, or None."""
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None
    con = _connect()
    try:
        row = con.execute("select * from items where product_id = ?",
                          (pid,)).fetchone()
    finally:
        con.close()
    return _decorate(dict(row)) if row else None


def deals(limit=8):
    """In-stock products with an active discount, deepest first."""
    con = _connect()
    try:
        rows = con.execute(
            "select * from items where coalesce(discount, 0) > 0 "
            "and available_quantity > 0 order by discount desc limit ?",
            (limit,)).fetchall()
    finally:
        con.close()
    return [_decorate(dict(r)) for r in rows]


def categories():
    return enum_values("category")