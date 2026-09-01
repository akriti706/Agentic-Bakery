"""
Exposes the shop to agents this merchant does not control.

The buyer's agent gets the same read-only catalog tools the internal
agent uses, plus a quote tool that runs the real policy gate. An outside
agent therefore faces exactly the checks the inside one does: it cannot
invent a price, exceed a mandate, or oversell stock, because none of
those decisions live in the agent.

Nothing here writes. Reserving stock and charging a card stay behind the
authenticated session flow in conversation.py.

    python src/mcp_server.py
"""

import uuid
from datetime import datetime, timedelta

from mcp.server.mcpserver import MCPServer

import catalog
import policy
from model import Basket, BasketItem, Mandate

SERVER_NAME = "agentic-bakery"
QUOTE_SESSION_PREFIX = "mcp"
DEFAULT_QUOTE_BUDGET = 5000.0

server = MCPServer(
    name=SERVER_NAME,
    instructions=(
        "Search this bakery's live inventory and price a basket before "
        "committing to it. Prices and stock come from the shop's own "
        "database. Always quote a basket before telling a customer it "
        "can be bought."
    ),
)


@server.tool(
    description=(
        "Search the bakery's inventory. Every filter is optional. Returns "
        "products with price, final_price after any discount, and "
        "available_quantity, plus which filters had to be relaxed and "
        "anything that matched but is sold out."
    )
)
def search_products(category: str | None = None,
                    flavor: str | None = None,
                    occasion: str | None = None,
                    taste: str | None = None,
                    max_price: float | None = None,
                    on_sale: bool | None = None,
                    query: str | None = None,
                    limit: int = 5) -> dict:
    data = catalog.search_products(
        category=category, flavor=flavor, occasion=occasion, taste=taste,
        max_price=max_price, on_sale=on_sale, query=query,
        limit=max(1, min(limit, 10)))

    return {
        "products": [
            {
                "product_id": row["product_id"],
                "name": row["item_name"],
                "category": row["category"],
                "flavor": row["flavor"],
                "price": row["price"],
                "final_price": row["final_price"],
                "discount_percent": row["discount"],
                "available_quantity": row["available_quantity"],
            }
            for row in data["results"]
        ],
        "relaxed_filters": data["relaxed"],
        "out_of_stock": data["out_of_stock"],
    }


@server.tool(
    description=(
        "Fetch one product by its numeric id. Use this to confirm the "
        "current price and stock before quoting."
    )
)
def get_product(product_id: str) -> dict:
    row = catalog.get_product(product_id)
    if row is None:
        return {"error": "no such product", "product_id": product_id}
    return {
        "product_id": row["product_id"],
        "name": row["item_name"],
        "category": row["category"],
        "flavor": row["flavor"],
        "occasion": row["occasion"],
        "price": row["price"],
        "final_price": row["final_price"],
        "discount_percent": row["discount"],
        "available_quantity": row["available_quantity"],
    }


@server.tool(
    description=(
        "Price a proposed basket against the shop's rules. Each item needs "
        "product_id and quantity. Returns approved true or false, the "
        "total computed from the shop's own prices, and a reason for every "
        "rule that failed. This does not reserve stock or take payment."
    )
)
def quote_basket(items: list[dict],
                 total_budget: float = DEFAULT_QUOTE_BUDGET) -> dict:
    basket = Basket()
    for raw in items:
        row = catalog.get_product(raw.get("product_id"))
        if row is None:
            basket.items.append(BasketItem(
                product_id=str(raw.get("product_id")),
                name="unknown", quantity=1, unit_price=0.0))
            continue
        basket.items.append(BasketItem(
            product_id=str(row["product_id"]),
            name=row["item_name"],
            quantity=int(raw.get("quantity", 1)),
            unit_price=row["final_price"],
        ))

    mandate = Mandate(
        mandate_id=f"Q_{uuid.uuid4().hex[:8]}",
        customer_id=f"{QUOTE_SESSION_PREFIX}-client",
        expires_at=datetime.now() + timedelta(minutes=5),
        total_budget=float(total_budget),
    )

    decision = policy.evaluate(
        basket, mandate, f"{QUOTE_SESSION_PREFIX}_{mandate.mandate_id}")

    return {
        "approved": decision.approved,
        "total": decision.verified_total,
        "saved": basket.saved,
        "reasons": decision.reasons,
        "items": [item.as_dict() for item in basket.items],
        "note": ("Quotes are priced by the shop, not by the caller. To "
                 "complete a purchase, use the shop's checkout."),
    }


if __name__ == "__main__":
    server.run(transport="stdio")