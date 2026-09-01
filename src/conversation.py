import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from model import Basket, Mandate
import catalog
import policy
import inventory
import payments
import agent
import audit
import orders
import session

load_dotenv()

MANDATE_HOURS = 1
MAX_ALTERNATIVES = 5
BROWSE_LIMIT = 8
DEFAULT_TOTAL_BUDGET = float(os.getenv("DEFAULT_TOTAL_BUDGET"))

def create_mandate(customer_id, total_budget=None,
                   valid_hours=MANDATE_HOURS) -> Mandate:
    return Mandate(
        mandate_id=f"M_{uuid.uuid4().hex[:8]}",
        customer_id=customer_id,
        expires_at=datetime.now() + timedelta(hours=valid_hours),
        total_budget=float(total_budget or DEFAULT_TOTAL_BUDGET),
       
    )

def start(mandate: Mandate) -> str:
    session_id = uuid.uuid4().hex[:12]
    session.create(session_id, mandate)
    audit.log(session_id, "CONVERSATION_START",
              customer_id=mandate.customer_id)
    return session_id


def _alternatives(seen, basket):
    chosen = {str(i.product_id) for i in basket.items}
    wanted = set()
    for item in basket.items:
        row = catalog.get_product(item.product_id)
        if row:
            wanted.add(row["category"])

    out, added = [], set()
    for row in seen:
        pid = str(row["product_id"])
        if pid in chosen or pid in added or row["category"] not in wanted:
            continue
        if row["available_quantity"] < 1:
            continue
        out.append({"product_id": pid, "name": row["item_name"],
                    "price": row["final_price"], "category": row["category"]})
        added.add(pid)

    out.sort(key=lambda x: x["price"])
    return out[:MAX_ALTERNATIVES]


def _line(item):
    text = f"• {item.name} — Rs{item.unit_price:.2f}"
    if item.list_price:
        text += f" (was Rs{item.list_price:.2f})"
    if item.quantity > 1:
        text += f" x {item.quantity}"
    return text


def _lines(basket):
    return "\n".join(_line(i) for i in basket.items)


def _catalog_lines(rows, limit=BROWSE_LIMIT):
    out, seen_ids = [], set()
    for row in rows:
        pid = str(row["product_id"])
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        line = f"• {row['item_name']} — Rs{row['final_price']:.2f}"
        if row["on_sale"]:
            line += f" (was Rs{row['price']:.2f}, {row['discount']}% off)"
        out.append(line)
        if len(out) >= limit:
            break
    return "\n".join(out)


def _summary(basket, alternatives, tail):
    text = _lines(basket) + f"\n\nTotal: Rs{basket.total:.2f}"
    if basket.saved:
        text += f"  (saved Rs{basket.saved:.2f})"
    if alternatives:
        text += ("\n\nAlso available: "
                 + ", ".join(f"{a['name']} (Rs{a['price']:.2f})"
                             for a in alternatives) + ".")
    return text + f"\n\n{tail}"


def _reply(s, text, extra=None):
    s.say("shop", text)
    out = {
        "session_id": s.session_id,
        "state": s.state,
        "reply": text,
        "items": [i.__dict__ for i in s.basket.items],
        "total": s.basket.total,
        "saved": s.basket.saved,
        "alternatives": s.alternatives,
        "can_pay": s.state == session.REVIEWING and not s.basket.is_empty,
        "mandate": s.mandate.as_dict(),
        "remaining_budget": round(
            max(s.mandate.total_budget - s.basket.total, 0), 2),
        "audit_trail": audit.get_session(s.session_id),
    }
    if extra:
        out.update(extra)
    return out


def _accept(s, basket, seen, opening, tail):
    s.basket = basket
    if seen:
        s.last_search = seen
    s.alternatives = _alternatives(s.last_search, basket)
    s.state = session.REVIEWING
    return _reply(s, opening + _summary(basket, s.alternatives, tail))


def _browse(s, basket, seen):
    """The customer asked what exists. Show it; change nothing."""
    if seen:
        s.last_search = seen

    listing = _catalog_lines(s.last_search)
    if not listing:
        return _reply(s, basket.reasoning
                      or "I could not find anything matching that.")

    text = (basket.reasoning + "\n\n" if basket.reasoning else "") + listing
    if s.basket.is_empty:
        text += "\n\nTell me which one you want and I will add it."
    else:
        text += ("\n\nYour cart is unchanged. Tell me which one to add."
                 "\n\n" + _lines(s.basket)
                 + f"\n\nTotal: Rs{s.basket.total:.2f}")
    return _reply(s, text)


def _shopping(s, message):
    basket, seen, failure = agent.propose_basket(message, s.mandate,
                                                 s.session_id)
    if failure:
        return _reply(s, f"The assistant could not answer: {failure}. "
                         "Please try again.")

    if basket.is_browse:
        return _browse(s, basket, seen)

    if basket.is_empty:
        return _reply(s, basket.reasoning
                      or "I could not find anything for that. Try "
                         "describing it differently.")

    decision = policy.evaluate(basket, s.mandate, s.session_id)
    if not decision.approved:
        return _reply(s, "I put a basket together but it did not pass "
                         "checks, so I have not kept it:\n\n"
                      + "\n".join(f"• {r}" for r in decision.reasons))

    return _accept(s, basket, seen, "Added to your cart:\n\n",
                   "Tell me if you want to change or add anything. "
                   "When you are ready, use the Pay button.")


def _reviewing(s, message):
    previous = s.basket
    updated, seen, failure = agent.modify_basket(message, previous,
                                                 s.mandate, s.session_id)
    if failure:
        return _reply(s, f"{failure} Your cart is unchanged:\n\n"
                      + _summary(previous, s.alternatives,
                                 "Try naming the item, for example "
                                 "'make it two' or 'remove the brownie'."))

    if updated.is_browse:
        return _browse(s, updated, seen)

    if updated.is_empty and not previous.is_empty:
        s.basket = updated
        s.alternatives = []
        return _reply(s, (updated.reasoning or "Your cart is now empty.")
                      + "\n\nTell me what you would like instead.")

    if updated.contents == previous.contents:
        return _reply(s, (updated.reasoning
                          or "I could not work out what to change.")
                      + "\n\nNothing was added. Your cart is unchanged:"
                        "\n\n"
                      + _summary(previous, s.alternatives,
                                 "Raise your budget with Start new session, "
                                 "or ask for something cheaper."))

    decision = policy.evaluate(updated, s.mandate, s.session_id)
    if not decision.approved:
        return _reply(s, "That change was blocked:\n\n"
                      + "\n".join(f"• {r}" for r in decision.reasons)
                      + "\n\nYour cart is unchanged:\n\n"
                      + _summary(previous, s.alternatives,
                                 "Raise your budget with Start new session, "
                                 "or ask for something cheaper."))

    return _accept(s, updated, seen, "Updated. Your cart:\n\n",
                   "Anything else, or use the Pay button.")


def handle_turn(session_id: str, message: str) -> dict:
    s = session.get(session_id)
    if s is None:
        return {"error": "unknown session", "state": session.CANCELLED}

    s.say("user", message)
    audit.log(session_id, audit.REQUEST_RECEIVED,
              customer_id=s.mandate.customer_id, detail=message)

    if s.mandate.is_expired:
        s.state = session.CANCELLED
        return _reply(s, "This authorisation has expired. Start a new "
                         "session before ordering anything.")

    if s.state == session.PAID:
        return _reply(s, "This order is already paid for. Start a new "
                         "session to shop again.")

    if s.state == session.REVIEWING:
        return _reviewing(s, message)

    return _shopping(s, message)


def pay(session_id: str, authorised_total: float) -> dict:
    s = session.get(session_id)
    if s is None:
        return {"error": "unknown session", "state": session.CANCELLED}

    if s.state == session.PAID:
        return _reply(s, "This order is already paid for.")

    if s.state != session.REVIEWING or s.basket.is_empty:
        return _reply(s, "There is nothing to pay for yet.")

    decision = policy.evaluate(s.basket, s.mandate, s.session_id)
    if not decision.approved:
        return _reply(s, "Payment stopped:\n\n"
                      + "\n".join(f"• {r}" for r in decision.reasons))

    if abs(float(authorised_total) - decision.verified_total) > 0.01:
        return _reply(s, f"The total changed since you were shown it. "
                         f"It is now Rs{decision.verified_total:.2f}. "
                         "Check the cart and try again.")

    reserved, why = inventory.reserve(s.basket.items)
    if not reserved:
        return _reply(s, f"Payment stopped: {why}")
    audit.log(session_id, audit.STOCK_RESERVED,
              customer_id=s.mandate.customer_id,
              detail=f"{len(s.basket.items)} item(s) held")

    audit.log(session_id, audit.PAYMENT_ATTEMPT,
              customer_id=s.mandate.customer_id,
              detail=f"Rs{decision.verified_total:.2f} via {payments.PROVIDER}")

    result = payments.charge(decision.verified_total, session_id,
                             s.mandate.customer_id)

    audit.log(session_id, audit.PAYMENT_RESULT,
              customer_id=s.mandate.customer_id,
              decision=result.status.upper(),
              detail=result.reference or None,
              reason=result.message)

    order_id = orders.record(s.mandate.customer_id, session_id,
                             s.mandate.mandate_id, s.basket, result)
    extra = {"order_id": order_id, "payment": result.as_dict()}

    if not result.captured:
        inventory.release(s.basket.items)
        audit.log(session_id, audit.STOCK_RELEASED,
                  customer_id=s.mandate.customer_id,
                  detail=f"payment {result.status}, stock returned")
        
        return _reply(s, f"The order was not completed. {result.message} "
                         f"Reference {result.reference or 'none'}. "
                         "Your cart is still here if you want to retry.",
                      extra)
    

    s.state = session.PAID
    audit.log(session_id, audit.SESSION_COMPLETE,
              customer_id=s.mandate.customer_id,
              detail=f"paid Rs{decision.verified_total:.2f}")

    return _reply(s, f"Paid Rs{decision.verified_total:.2f}. "
                     f"Reference {result.reference}. Thank you!", extra)