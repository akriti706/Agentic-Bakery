# Agentic Bakery Storefront

An online bakery where an AI agent can handle the shopping process, while
a separate policy layer checks what the agent is trying to do before any
money is moved.

Built for the **Razorpay AI Buildathon — Track 01**.

---

## Why this exists

Think about the last thing you bought online. Right before paying, you
probably checked the total once more to make sure the price looked right
and that you were actually okay with spending that amount.

That small check is easy to overlook, but it is an important safety step.

Now remove that step and let an AI agent handle the purchase.

An agent might say that a cake costs ₹500 even when the actual price is
₹550. It might select a product that doesn't exist, request more items
than are available, or build a basket that is more expensive than what
the customer intended to spend.

An LLM can be very confident while being completely wrong.

For a normal chatbot, that is usually just an incorrect answer. For an
agent that can make payments, the same mistake can have a real
consequence.

So the agent should not be the final authority.

The agent can decide what it wants to buy. A separate part of the system
checks whether that decision is actually valid, whether it matches the
catalog, whether enough stock exists, and whether it stays within what
the customer authorised.

That is the main problem this project is trying to solve.

---

## The core idea

The main assumption behind the system is simple:

**An LLM's output is a claim, not the source of truth.**

If the agent says a product costs ₹500, that is a claim.

If it says the product is available, that is a claim.

If it says the customer can afford the basket, that is also a claim.

Before any of these claims can result in a payment, they are checked
against the actual data and rules of the shop.

The catalog is the source of truth for products, prices and stock. The
mandate defines what the customer has authorised. The payment records
tell us what actually happened.

The agent is responsible for understanding the customer's request and
building a basket. It is **not** responsible for deciding whether that
basket is allowed.

Before anything that is difficult to undo happens, the system checks the
proposal again.

### The basic flow

```text
   customer message
          │
          ▼
   ┌──────────────┐
   │   agent.py   │   reads the catalog, proposes a basket
   │  (untrusted) │
   └──────┬───────┘
          │  a claim, not a fact
          ▼
   ┌──────────────┐
   │  policy.py   │   re-reads the catalog, runs 9 rules
   │   the gate   │
   └──────┬───────┘
          │
     ┌────┴─────┐
     │          │
  blocked    approved
     │          │
     ▼          ▼
  reason    inventory.py   reserve stock
  shown     payments.py    charge
  to the    orders.py      record the attempt
  customer
```

`agent.py` is the bakery agent. It reads the catalog, interprets the
user's request, decides what should go into the basket and passes that
basket forward.

Everything produced by the agent is treated as something that needs to
be checked.

`policy.py` is the gate. It reads the catalog independently and runs nine
rules against the proposed basket. It does not simply trust the price,
product or quantity supplied by the agent.

Only after the checks pass does the system enter the payment flow: stock
is temporarily reserved, payment is attempted, and the order is recorded.

One deliberate design choice is that `agent.py` does **not** import
`policy.py`, `inventory.py` or `payments.py`.

Python would not stop someone from changing that later, but keeping this
dependency boundary visible makes the architecture much easier to review.
The agent should not have a direct path to stock or money, even if the
model behind it produces a bad decision.

---

## What it does

### Shopping by sentence

You can say something like:

> "A chocolate cake for my birthday"

The agent turns that into a structured catalog search using fields such
as category, flavour, occasion, taste, price and discount.

This isn't just a text search over product names. The filters correspond
to actual database columns, and the values available to the agent are
generated from the database. This means the agent cannot simply invent a
flavour that the bakery has never sold.

### A gate that refuses

The policy layer can reject things such as:

* hallucinated products
* incorrect prices
* duplicate product lines
* invalid quantities
* insufficient stock
* baskets that exceed the customer's budget

When something is rejected, the reason is returned as well. The customer
doesn't just get a generic "payment failed" type of response.

### A mandate

Every session opens with a mandate: a budget and an expiry time. The
customer can set the budget, and if they don't, a default from the
environment is used.

The mandate answers:

**"What has this customer actually authorised?"**

It is kept separate from the basket validation rules, which answer:

**"Is this particular basket valid?"**

The mandate cannot be overridden by the agent. Changing a budget means
starting a new session with a new mandate.

### Discounts computed once

The final price is calculated in one place.

The agent, cart, policy gate and payment flow all use that same pricing
function rather than calculating their own versions of the total.

This avoids a situation where the cart shows one price while the payment
flow uses another.

### Stock held, then released

Stock is reserved before attempting the charge.

If the payment succeeds, the reservation stays.

If the payment fails, the stock is released again.

This gives us a recoverable failure instead of leaving inventory in an
inconsistent state.

### An audit trail

The system keeps an append-only record of:

* searches
* agent proposals
* policy decisions
* stock movements
* payment results

The audit information is also shown live in the interface.

The idea is that if something goes wrong, there should be enough
information to reconstruct what the system actually did and why.

### An orders record

Every payment attempt gets an order record, whether the payment
eventually succeeds or not.

These records can be exported as CSV.

This is intentional. If there is a dispute, we want to know what the
system attempted, not just keep a record of successful payments.

### An MCP server

The bakery can also expose its catalog and policy checks through an MCP
server.

This allows an agent that is **not part of this application** to search
the bakery and request a basket quote using the same catalog and the same
policy rules.

---

## Running it

Create and activate a virtual environment:

```bash
python -m venv venv

venv\Scripts\activate
# source venv/bin/activate on macOS/Linux
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Create the environment file:

```bash
copy .env.example .env
```

Then add your Groq API key.

Load the catalog:

```bash
python src/load_items.py
```

Run the tests:

```bash
pytest
```

Start the application:

```bash
uvicorn main:app --reload --app-dir src
```

Open:

```text
http://127.0.0.1:8000
```

The login page opens first. Use the **Register** link to create an
account, then come back and log in.

The session and its mandate are created at login, so you need to be
logged in before the storefront will accept any requests.

Once you are in, start typing requests into the chat.

**All commands above are meant to be run from the project root, not from
inside `src/`.**

`python src/load_items.py` reloads the catalog from `items.csv` and
resets stock to its starting values.

The current stock can be inspected in `bakery_shop.db`, which is created
by that script.

---

## Environment

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Tool-calling model, for example `openai/gpt-oss-120b` |
| `PAYMENT_PROVIDER` | `mock` or `razorpay` |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay test keys |
| `FORCE_PAYMENT_FAILURE` | Set to `1` to demonstrate payment failure and stock rollback |
| `DEFAULT_TOTAL_BUDGET` | Budget used for the mandate when no budget is provided |

---

## Things worth trying

Here are a few requests that demonstrate the main parts of the system.

| Say this | What should happen |
| --- | --- |
| `i want a chocolate cake for my birthday` | Searches using category, flavour and occasion, then adds an item |
| `what's on discount` | Shows available offers without changing the cart |
| `add a red velvet cake as well` | Adds the item, or refuses it if doing so would exceed the budget |
| `make it two` | Changes the quantity and checks stock |
| `remove the cake` | Removes the item from the basket |
| `i want a mango brownie` | If there is no exact match, the agent explains which filter it had to relax |
| `i want 50 black forest cakes` | The request is blocked and the actual available stock is shown |

Then press **Pay**.

### Testing payment rollback

To see the rollback behaviour, set:

```text
FORCE_PAYMENT_FAILURE=1
```

in `.env` and press **Pay**.

The audit trail should show:

```text
stock reserved
      ↓
payment fails
      ↓
stock released
```

The cart stays intact, so the customer can try again.

Set the flag back to:

```text
FORCE_PAYMENT_FAILURE=0
```

and press Pay again to allow the payment to go through.

---

## How the code is laid out

```text
src/

    main.py          FastAPI routes

    conversation.py  orchestration:
                     message in, reply out

    agent.py         language -> proposed basket
                     (reads catalog only)

    catalog.py       read-only inventory search

    policy.py        the gate

    inventory.py     the only writer of stock

    payments.py      mock and Razorpay providers

    orders.py        append-only record of every
                     payment attempt

    audit.py         append-only decision log

    session.py       in-memory session state

    model.py         Basket, BasketItem, Mandate

    database.py      user accounts

    load_items.py    CSV -> SQLite

    mcp_server.py    the shop as an MCP server

data/
    items.csv
    databases built from it

static/
    login, register, storefront

tests/
    41 tests, no network, no live database
```

There are four databases, and they are kept separate because they have
different responsibilities and different update behaviour.

`bakery_shop.db` contains inventory and is the only database that changes
during normal shopping.

`load_items.py` rebuilds it from `items.csv` using a full table
replacement. Because of that, anything else stored there could disappear
whenever the catalog is reloaded.

That is why the orders and audit data are kept separately.

`orders.db` and `shop.db` are append-only by construction. Neither module
exposes update or delete operations.

An audit trail that can simply be edited afterwards would not be much use
for auditing.

`user.db` is separate again and stores user accounts.

---

## The gate

`policy.RULES` contains nine independent rule functions.

Each rule receives:

* the basket
* the mandate
* the relevant catalog rows

and returns a list of reasons why the basket fails that rule.

An empty list means the rule passed.

`evaluate()` runs all nine rules and collects their failures instead of
stopping at the first one.

This is deliberate.

If a basket has three problems, the customer should see all three at once
instead of fixing one problem, sending another request, discovering the
second problem, fixing that, and then discovering the third.

### The nine rules

| Rule | Blocks when |
| --- | --- |
| `_mandate_valid` | The authorisation has expired |
| `_basket_not_empty` | There is nothing to pay for |
| `_no_duplicates` | The same product appears more than once |
| `_products_exist` | A product ID is not present in the catalog |
| `_prices_match` | The claimed price differs from the real price by more than ₹0.01 |
| `_quantities_sane` | Quantity is below 1 |
| `_stock_sufficient` | Requested quantity exceeds available stock |
| `_within_total_budget` | Basket total exceeds the mandate budget |
| `_velocity_ok` | Too many orders have been paid in a short period |

Adding another rule is intentionally straightforward: write another
function and append it to `RULES`. The existing rules don't need to know
about it.

### Why some of these rules matter

`_no_duplicates` might look unnecessary at first.

Why should it matter if the same cake appears twice in a basket?

Because the basket is being assembled by an agent, and stock is checked
against individual lines.

For example, suppose there are three cakes left and the agent produces:

```text
Black Forest Cake x2
Black Forest Cake x2
```

If each line is checked separately, both might appear valid even though
the basket actually requires four cakes.

The duplicate check catches this before the reservation and payment
stage.

Otherwise the problem might only become visible inside
`inventory.reserve()`, which is a much worse place to discover it.

`_velocity_ok` works differently from the other rules.

Most rules ask:

> "Is this basket valid?"

This one asks:

> "Is this customer placing orders at a reasonable rate?"

A runaway agent can generate multiple individually valid orders. Checking
each basket separately won't necessarily catch that pattern.

For this rule, the audit history matters.

---

## Payment

`payments.py` returns one of three statuses, and only one of them means
money has actually been captured.

| Status | Meaning | Stock | Session becomes |
| --- | --- | --- | --- |
| `captured` | Money moved | Stays reserved | `PAID` |
| `initiated` | Razorpay order created, checkout not completed | Released | stays `REVIEWING` |
| `failed` | Declined, or a provider error | Released | stays `REVIEWING` |

The important distinction is between **creating a Razorpay order** and
**actually receiving a payment**.

`order.create` creates the order, but it does not mean the customer has
paid.

The live Razorpay flow in this project stops at order creation, so
treating that step as a successful payment would put information in the
audit log that isn't actually true.

That would be exactly the kind of mistake this project is designed to
avoid.

### Two checks happen immediately before charging

First, the policy gate runs again.

The basket might have been approved a minute earlier, but stock or prices
could have changed since then.

So an earlier approval isn't treated as permanently valid. The system
checks again immediately before payment.

Second, the total sent back by the browser is compared with the total
calculated by the shop.

If the browser is displaying ₹500 but the shop now calculates ₹550,
payment is stopped.

The customer should never end up confirming one amount while the system
charges another.

### Why reserve stock first?

Stock is reserved **before** the charge.

If the system charged first and reserved afterwards, another session
could potentially buy the last cake in between those two operations.

That creates a much worse failure:

> customer paid, but the product is no longer available.

With the current flow, the worst normal failure is:

> payment didn't go through, so the reservation can be released.

That is much easier to recover from.

---

## MCP: opening the shop to other agents

So far, the main flow describes an agent that lives inside this
application.

But agentic commerce becomes more interesting when the merchant can
expose its shop to **other agents** as well.

The MCP server can be started with:

```bash
python src/mcp_server.py
```

It exposes three read-only tools over the Model Context Protocol:

```text
search_products
get_product
quote_basket
```

`quote_basket` is the important one.

An external agent sends product IDs and quantities.

The server does **not** trust any price supplied by that caller. It reads
the actual price from the catalog and then runs the same
`policy.evaluate()` used by the internal shopping flow.

The response contains:

* whether the basket was approved
* the total calculated by the bakery
* the reason for every failed rule

So an external agent faces exactly the same checks the internal one does.

For example:

```text
hallucinated product
        ↓
"unknown" is not a product sold by this shop
```

or:

```text
99 of a 6-stock item
        ↓
Only 6 Black Forest Cakes are available
```

or:

```text
over the budget
        ↓
₹1000.00 is ₹500.00 over the ₹500.00 budget
```

This works because the policy gate is outside the agent.

The agent can change completely and the enforcement rules don't have to
change with it.

### What the MCP server deliberately does not expose

The MCP tools do **not** reserve stock or charge a card.

`quote_basket` only calculates and validates a basket.

Actually committing to a purchase still requires an authenticated session
and a mandate belonging to a known customer.

Exposing a write tool to an anonymous external caller would give that
caller the ability to affect real inventory.

A policy gate doesn't make that design safe, so the write operations stay
outside the MCP interface.

---

## Testing

Run:

```bash
pytest
```

There are currently **41 tests**.

They do not access the network or the live database.

The catalog and audit modules are stubbed during testing, so a test
doesn't fail just because someone bought a cake five minutes earlier, and
the tests don't write into the real audit log.

| File | Covers |
| --- | --- |
| `test_policy.py` | Every policy rule, both when it passes and when it should block |
| `test_pricing.py` | Discounted price accepted, original price rejected |
| `test_agent_parsing.py` | Valid, fenced and malformed model output |
| `test_flow.py` | Payment capture, rollback, stale totals and double-payment protection |

The most important tests are the ones that verify that the system
**refuses to do something**.

For example:

* a blocked basket must never reach the payment gateway
* a stale total must never be charged
* a failed payment must return the reserved stock

Those behaviours are central to the design, and they are also the easiest
things to accidentally break when changing the code later.

---

## Known limitations

This is a buildathon project, not a production payment system. These are
the main gaps.

### Sessions live in memory

Restarting the application clears carts.

The current implementation also assumes a single worker process.

For a production deployment, session state would need to move to a
persistent or shared store.

The current design keeps this responsibility inside one module, so
replacing the session storage would not require changing the policy
layer.

### The Razorpay flow stops at order creation

The live Razorpay integration currently stops after creating the Razorpay
order.

The actual checkout handoff is not implemented, so a live payment is
reported as `initiated` rather than `captured`.

The mock provider is used to demonstrate the complete flow, including
successful payment and rollback after failure.

### Enums and tool specifications are built at import time

If the catalog is edited while the server is already running, the server
needs to be restarted before the agent sees the new enum values and tool
specifications.

### A crash can leave stock reserved

If the process crashes after reserving stock but before releasing it,
that reservation can remain in place.

At this scale it can be fixed manually.

A production system would need something like a reservation timeout or a
background cleanup mechanism.

### Intent classification still depends on the model

The model decides whether a message is a browsing request or a request
that should modify the basket.

Occasionally, a browsing request could be interpreted as a basket
request.

The policy layer limits the damage this can cause, but it cannot
completely prevent the model from misunderstanding the user's intent.

### Passwords are stored as plain text

This is intentionally out of scope for the buildathon implementation and
should **not** be done in a production application.

---

## Further reading

`ARCHITECTURE.md` goes deeper into the project.

It contains:

* the state machine
* sequence diagrams
* design decisions and their trade-offs
* problems faced during development and their resolutions

If you want to understand not just *what* the project does but *why* it
was designed this way, that's the next file to read.