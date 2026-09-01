"""
The gate. Every basket passes through here before it can be paid for.

Nothing the model says is trusted. Product ids, names, prices and
quantities are re-checked against the catalog, and the total is
re-computed from catalog prices.

Each rule is an independent function taking (basket, mandate, rows) and
returning a list of reasons. Adding a rule means appending one function
to RULES.
"""

from dataclasses import dataclass, field

import catalog
import audit

PRICE_TOLERANCE = 0.01

VELOCITY_WINDOW_MINUTES = 10
VELOCITY_MAX_PURCHASES = 3

APPROVE = "APPROVE"
BLOCK = "BLOCK"


@dataclass
class Decision:
    decision: str
    reasons: list[str] = field(default_factory=list)
    verified_total: float = 0.0

    @property
    def approved(self) -> bool:
        return self.decision == APPROVE


def verified_total(basket) -> float:
    total = 0.0
    for item in basket.items:
        row = catalog.get_product(item.product_id)
        if row:
            total += row["final_price"] * item.quantity
    return round(total, 2)


def _mandate_valid(basket, mandate, rows):
    if mandate.is_expired:
        return ["This authorisation has expired."]
    return []


def _basket_not_empty(basket, mandate, rows):
    if basket.is_empty:
        return ["The basket is empty."]
    return []


def _no_duplicates(basket, mandate, rows):
    seen = set()
    for item in basket.items:
        if item.product_id in seen:
            return [f"{item.name} appears more than once in the basket."]
        seen.add(item.product_id)
    return []


def _products_exist(basket, mandate, rows):
    return [f"'{i.name or i.product_id}' is not a product this shop sells."
            for i in basket.items if rows.get(i.product_id) is None]


def _prices_match(basket, mandate, rows):
    reasons = []
    for item in basket.items:
        row = rows.get(item.product_id)
        if row is None:
            continue
        expected = row["final_price"]
        if abs(item.unit_price - expected) > PRICE_TOLERANCE:
            reasons.append(f"{row['item_name']} is Rs{expected:.2f}, not "
                           f"Rs{item.unit_price:.2f}.")
    return reasons


def _quantities_sane(basket, mandate, rows):
    reasons = []
    for item in basket.items:
        if item.quantity < 1:
            reasons.append(f"{item.name} has an invalid quantity.")
        
    return reasons


def _stock_sufficient(basket, mandate, rows):
    reasons = []
    for item in basket.items:
        row = rows.get(item.product_id)
        if row is None:
            continue
        if item.quantity > row["available_quantity"]:
            reasons.append(f"Only {row['available_quantity']} of "
                           f"{row['item_name']} left in stock.")
    return reasons





def _within_total_budget(basket, mandate, rows):
    total = verified_total(basket)
    if total > mandate.total_budget:
        over = round(total - mandate.total_budget, 2)
        return [f"Rs{total:.2f} is Rs{over:.2f} over your "
                f"Rs{mandate.total_budget:.2f} budget."]
    return []


def _velocity_ok(basket, mandate, rows):
    recent = audit.count_recent_purchases(mandate.customer_id,
                                          VELOCITY_WINDOW_MINUTES)
    if recent >= VELOCITY_MAX_PURCHASES:
        return [f"{recent} orders already placed in the last "
                f"{VELOCITY_WINDOW_MINUTES} minutes."]
    return []


RULES = [
    _mandate_valid,
    _basket_not_empty,
    _no_duplicates,
    _products_exist,
    _prices_match,
    _quantities_sane,
    _stock_sufficient,
    _within_total_budget,
    _velocity_ok,
]


def _stamp_list_prices(basket, rows):
    for item in basket.items:
        row = rows.get(item.product_id)
        item.list_price = row["price"] if row and row["on_sale"] else None


def evaluate(basket, mandate, session_id) -> Decision:
    rows = {i.product_id: catalog.get_product(i.product_id)
            for i in basket.items}
    _stamp_list_prices(basket, rows)

    reasons = []
    for rule in RULES:
        reasons.extend(rule(basket, mandate, rows))

    decision = Decision(
        decision=BLOCK if reasons else APPROVE,
        reasons=reasons,
        verified_total=verified_total(basket),
    )

    audit.log(session_id, audit.POLICY_DECISION,
              customer_id=mandate.customer_id,
              decision=decision.decision,
              detail=f"{len(basket.items)} item(s), verified total "
                     f"Rs{decision.verified_total:.2f}",
              reason="; ".join(reasons) or None)
    return decision