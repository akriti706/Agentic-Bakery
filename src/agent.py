

import json
import os

import requests
from dotenv import load_dotenv

from model import Basket, BasketItem, Mandate
import catalog
import audit

load_dotenv()

PROVIDER =  "groq"


GROQ_MODEL = os.getenv("GROQ_MODEL")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_TOOL_ROUNDS = 3
MAX_OUTPUT_TOKENS = 1024
RETRIES = 2
SEARCH_LIMIT = 5
TOOL_FIELDS = ("product_id", "item_name", "category", "flavor", "price",
               "discount", "final_price", "on_sale", "available_quantity")
TIMEOUT_SECONDS = 120


class AgentError(RuntimeError):
    pass


def _tool_specs():
    return [
        {
            "name": "search_products",
            "description": (
                "Search the shop's own inventory. Returns products with "
                "price, final_price after any discount, and "
                "available_quantity. Always use this rather than guessing "
                "what the shop sells. Every filter is optional. Call this "
                "once for each different thing the customer asks for."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": catalog.enum_values("category"),
                    },
                    "flavor": {
                        "type": "string",
                        "enum": catalog.enum_values("flavor"),
                    },
                    "occasion": {
                        "type": "string",
                        "enum": catalog.enum_values("occasion"),
                    },
                    "taste": {
                        "type": "string",
                        "enum": catalog.enum_values("taste_profile"),
                        "description": "Words like fruity or nutty.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": (
                            "Maximum price per unit in INR, not an order "
                            "total."
                        ),
                    },
                    "on_sale": {
                        "type": "boolean",
                        "description": "True for discounted products only.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text keywords, only for what the filters "
                            "above cannot express."
                        ),
                    },
                },
                "required": [],
            },
        },
        {
            "name": "get_product",
            "description": (
                "Fetch full details for one product by its numeric id, to "
                "confirm price and stock before proposing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string",
                                   "description": "e.g. 101"},
                },
                "required": ["product_id"],
            },
        },
    ]


TOOL_SPECS = _tool_specs()


def _brief(row):
    return {field: row[field] for field in TOOL_FIELDS if field in row}


def _capped_price(requested, mandate, spent):
    remaining = max(mandate.total_budget - spent, 0.0)
    if requested is None:
        return remaining
    return min(float(requested), remaining)


def _search(args, mandate, session_id, seen, spent):
    data = catalog.search_products(
        query=args.get("query"),
        category=args.get("category"),
        flavor=args.get("flavor"),
        occasion=args.get("occasion"),
        taste=args.get("taste"),
        max_price=_capped_price(args.get("max_price"), mandate, spent),
        on_sale=args.get("on_sale"),
        limit=SEARCH_LIMIT,
    )
    results = data["results"]
    seen.extend(results)

    audit.log(session_id, audit.SEARCH, customer_id=mandate.customer_id,
              detail=f"{args} -> {len(results)} result(s)"
                     + (f", relaxed {data['relaxed']}"
                        if data["relaxed"] else ""))

    out = {"products": [_brief(row) for row in results]}
    if data["out_of_stock"]:
        out["out_of_stock"] = data["out_of_stock"]
        out["note"] = ("These matched but are sold out. Name them and say "
                       "they are out of stock, then offer the alternatives.")
    elif data["relaxed"]:
        out["relaxed_filters"] = data["relaxed"]
        out["note"] = ("No exact match, so these filters were dropped. Tell "
                       "the customer before offering these.")
    elif not results:
        out["note"] = "Nothing in stock matches this request."
    return out


def _run_tool(name, args, mandate, session_id, seen, spent):
    if name == "search_products":
        return _search(args, mandate, session_id, seen, spent)

    if name == "get_product":
        product = catalog.get_product(args.get("product_id"))
        if product is None:
            return {"error": "no such product"}
        seen.append(product)
        return {"product": _brief(product)}

    return {"error": f"unknown tool {name}"}


def _api_error(response):
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text[:200]
    return f"{response.status_code} from {PROVIDER}: {message}"

 

def _groq(system, user_text, mandate, session_id, seen, spent):
    key = os.getenv("GROQ_API_KEY")
    if not key or not GROQ_MODEL:
        raise AgentError("GROQ_API_KEY or GROQ_MODEL missing from .env")

    tools = [{"type": "function",
              "function": {"name": tool["name"],
                           "description": tool["description"],
                           "parameters": tool["parameters"]}}
             for tool in TOOL_SPECS]

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user_text}]

    for round_number in range(MAX_TOOL_ROUNDS):
        body = {"model": GROQ_MODEL, "messages": messages,
                "max_tokens": MAX_OUTPUT_TOKENS, "temperature": 0.2}
        if round_number < MAX_TOOL_ROUNDS - 1:
            body["tools"] = tools

        response = requests.post(
            GROQ_URL, timeout=TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {key}"}, json=body)

        if not response.ok:
            raise AgentError(_api_error(response))

        message = response.json()["choices"][0]["message"]
        calls = message.get("tool_calls")
        if not calls:
            return message.get("content") or ""

        messages.append(message)
        for call in calls:
            function = call["function"]
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(_run_tool(
                    function["name"],
                    json.loads(function.get("arguments") or "{}"),
                    mandate, session_id, seen, spent), default=str)})

    raise AgentError("the model kept searching without answering")



PROVIDERS={"groq":_groq}


def _call(system, user_text, mandate, session_id, seen, spent):
    handler = PROVIDERS.get(PROVIDER)
    if handler is None:
        raise AgentError(f"unknown LLM_PROVIDER {PROVIDER}")
    return handler(system, user_text, mandate, session_id, seen, spent)


_JSON_SHAPE = ('{"intent": "basket", '
               '"items": [{"product_id": "101", "name": "Truffle Cake", '
               '"quantity": 1, "unit_price": 550.0}], '
               '"reasoning": "one or two short sentences"}')

_RULES = """1. Set intent to exactly one of the words basket or browse. Use browse
   when the customer is only asking what exists. Use basket when they
   want something added, removed or changed. When browsing, leave items
   empty and describe what you found in reasoning.
2. Only propose products the tools returned. Never invent one.
3. Copy product_id and name exactly as returned. Use final_price as
   unit_price, never price. unit_price is the price of ONE unit — never
   divide or multiply it by quantity, and never change it when the
   quantity changes.
4. Use quantity 1 unless the customer asked for a specific number.
   Never propose more than available_quantity.
5. Search once per distinct thing the customer asked for.
6. Occasion words like birthday go in the occasion filter, descriptive
   words like fruity in the taste filter, never in query.
7. If a search reports out_of_stock, the product the customer named is
   sold out. Use intent browse, name it as sold out, and list the
   alternatives you found. Do not put a different product in the basket
   in its place.
8. If a search reports relaxed_filters, say which filter was dropped
   before offering what came back. Never substitute silently.
9. Keep the whole basket at or under the total budget.
10. When a product is discounted, mention the original price and the
    percent off, not only the final price.
11. You cannot take payment. If the customer says they are ready to pay
    or asks you to pay, return the basket unchanged and tell them to use
    the Pay button. Never say a payment was confirmed or completed."""

_FORMAT = f"""Reply with valid JSON only. No markdown fences, no text
before or after. Use double quotes everywhere and no quotation marks
inside any value.

{_JSON_SHAPE}"""


def _limits(mandate, spent=0.0):
    remaining = max(mandate.total_budget - spent, 0.0)
    if spent:
        return (f"The customer authorised Rs{mandate.total_budget:.2f} in "
                f"total. Rs{spent:.2f} is already in the basket, so "
                f"Rs{remaining:.2f} is left.")
    return (f"The customer has authorised Rs{mandate.total_budget:.2f} "
            f"in total.")


def _propose_prompt(mandate):
    return f"""You are a shopping assistant for an online bakery.

Search the catalog, then propose a basket for the customer's request.

{_limits(mandate)}

{_RULES}
12. If nothing suitable exists, return intent basket with an empty items
    list and explain why. Refusing is a valid answer.

{_FORMAT}"""


def _modify_prompt(basket, mandate):
    lines = "\n".join(
        f"{n}. {i.product_id}  {i.name}  x{i.quantity}  Rs{i.unit_price:.2f} each"
        for n, i in enumerate(basket.items, 1)) or "(empty)"

    return f"""You are a shopping assistant for an online bakery.

The customer's basket:

{lines}

Total: Rs{basket.total:.2f}

They have asked for a change. Return the COMPLETE updated basket,
including every item they did not mention, unchanged.

{_limits(mandate, basket.total)}

{_RULES}
13. Adding a new item means returning the existing items plus the new
    one. Do not drop anything the customer did not ask you to remove.
14. To remove something, leave it out of the list. If they ask to clear
    the cart, return an empty items list.
15. If the change is impossible, return the basket exactly as it is and
    explain why in reasoning.

{_FORMAT}"""


def _parse(text):
    cleaned = (text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise AgentError("the model did not return JSON")

    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as error:
        raise AgentError(f"the model returned malformed JSON: {error}")

    raw_items = data.get("items") or []
    items = []
    for raw in raw_items:
        try:
            items.append(BasketItem(
                product_id=str(raw["product_id"]).strip(),
                name=str(raw.get("name", "")),
                quantity=int(raw.get("quantity", 1)),
                unit_price=float(raw["unit_price"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue

    if raw_items and not items:
        raise AgentError("every item the model sent was malformed")

    intent = str(data.get("intent", "basket")).strip().lower()
    return Basket(items=items,
                  reasoning=str(data.get("reasoning", "")),
                  intent="browse" if intent == "browse" else "basket")


def _generate(system, text, mandate, session_id, label, spent):
    seen = []
    failure = ""

    for attempt in range(RETRIES):
        try:
            basket = _parse(_call(system, text, mandate, session_id,
                                  seen, spent))
        except AgentError as error:
            failure = str(error)
            continue
        except requests.RequestException as error:
            failure = str(error).split("?")[0]
            break

        audit.log(session_id, audit.BASKET_PROPOSED,
                  customer_id=mandate.customer_id,
                  detail=f"{label}: intent {basket.intent}, "
                         f"{len(basket.items)} item(s), claimed total "
                         f"Rs{basket.total:.2f} (unverified)",
                  reason=basket.reasoning)
        return basket, seen, ""

    audit.log(session_id, "AGENT_ERROR", customer_id=mandate.customer_id,
              detail=f"{label}: {failure}")
    return None, seen, failure


def propose_basket(request: str, mandate: Mandate, session_id: str):
    #First request
    basket, seen, failure = _generate(_propose_prompt(mandate), request,
                                      mandate, session_id, "proposed", 0.0)
    if basket is None:
        return Basket(reasoning=failure), seen, failure
    return basket, seen, ""


def modify_basket(instruction: str, basket: Basket, mandate: Mandate,
                  session_id: str):
  
    committed = basket.total - max(
        (item.line_total for item in basket.items), default=0.0)
    updated, seen, failure = _generate(_modify_prompt(basket, mandate),
                                       instruction, mandate, session_id,
                                       "modified", committed)
    if updated is None:
        return basket, seen, failure

    if updated.is_browse:
        return updated, seen, ""

    return updated, seen, ""