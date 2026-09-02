import pytest

import conversation
import policy
import session
from model import Basket, BasketItem
from payments import CAPTURED, FAILED, INITIATED, PaymentResult


@pytest.fixture(autouse=True)
def stub_side_effects(monkeypatch, product):
    lookup = lambda pid: product if str(pid) == "101" else None
    monkeypatch.setattr(policy.catalog, "get_product", lookup)
    monkeypatch.setattr(conversation.catalog, "get_product", lookup)
    monkeypatch.setattr(policy.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(policy.audit, "count_recent_purchases",
                        lambda customer_id, minutes: 0)
    monkeypatch.setattr(conversation.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(conversation.audit, "get_session", lambda sid: [])
    monkeypatch.setattr(conversation.audit, "init", lambda: None)
    monkeypatch.setattr(conversation.orders, "init", lambda: None)


@pytest.fixture
def reserved(monkeypatch):
    calls = {"reserve": 0, "release": 0}

    def reserve(items):
        calls["reserve"] += 1
        return True, ""

    def release(items):
        calls["release"] += 1

    monkeypatch.setattr(conversation.inventory, "reserve", reserve)
    monkeypatch.setattr(conversation.inventory, "release", release)
    return calls


@pytest.fixture
def recorded(monkeypatch):
    rows = []

    def record(customer_id, session_id, mandate_id, basket, result):
        rows.append({"customer_id": customer_id, "status": result.status,
                     "provider": result.provider, "amount": basket.total})
        return len(rows)

    monkeypatch.setattr(conversation.orders, "record", record)
    return rows


@pytest.fixture
def ready_session(mandate, product):
    session_id = conversation.start(mandate)
    state = session.get(session_id)
    state.basket = Basket(items=[
        BasketItem("101", product["item_name"], 1, 550.0)])
    state.state = session.REVIEWING
    return session_id


def charge_returns(monkeypatch, result):
    monkeypatch.setattr(conversation.payments, "charge",
                        lambda amount, sid, cid: result)


def test_capture_marks_the_session_paid(monkeypatch, ready_session, reserved,
                                        recorded):
    charge_returns(monkeypatch, PaymentResult(CAPTURED, "mock", "ref_1"))
    out = conversation.pay(ready_session, 550.0)
    assert out["state"] == session.PAID
    assert reserved["release"] == 0
    assert recorded[0]["status"] == CAPTURED


def test_failure_releases_the_stock(monkeypatch, ready_session, reserved,
                                    recorded):
    charge_returns(monkeypatch, PaymentResult(FAILED, "mock", message="No."))
    out = conversation.pay(ready_session, 550.0)
    assert out["state"] == session.REVIEWING
    assert reserved["release"] == 1
    assert recorded[0]["status"] == FAILED


def test_initiated_is_not_treated_as_paid(monkeypatch, ready_session,
                                          reserved, recorded):
    charge_returns(monkeypatch,
                   PaymentResult(INITIATED, "razorpay", "order_xyz"))
    out = conversation.pay(ready_session, 550.0)
    assert out["state"] == session.REVIEWING
    assert reserved["release"] == 1
    assert recorded[0]["status"] == INITIATED


def test_stale_total_is_refused(monkeypatch, ready_session, reserved,
                                recorded):
    charge_returns(monkeypatch, PaymentResult(CAPTURED, "mock", "ref_2"))
    out = conversation.pay(ready_session, 400.0)
    assert out["state"] == session.REVIEWING
    assert reserved["reserve"] == 0
    assert recorded == []


def test_blocked_basket_never_reaches_the_gateway(monkeypatch, mandate,
                                                  reserved, recorded, product):
    charge_returns(monkeypatch, PaymentResult(CAPTURED, "mock", "ref_3"))
    mandate.total_budget = 100.0
    session_id = conversation.start(mandate)
    state = session.get(session_id)
    state.basket = Basket(items=[
        BasketItem("101", product["item_name"], 1, 550.0)])
    state.state = session.REVIEWING

    out = conversation.pay(session_id, 550.0)
    assert reserved["reserve"] == 0
    assert recorded == []
    assert "over your" in out["reply"]


def test_paying_twice_is_refused(monkeypatch, ready_session, reserved,
                                 recorded):
    charge_returns(monkeypatch, PaymentResult(CAPTURED, "mock", "ref_4"))
    conversation.pay(ready_session, 550.0)
    out = conversation.pay(ready_session, 550.0)
    assert "already paid" in out["reply"]
    assert len(recorded) == 1


def test_clearing_the_cart_is_allowed(monkeypatch, mandate, product):
    monkeypatch.setattr(
        conversation.agent, "modify_basket",
        lambda *a, **k: (Basket(reasoning="Cart cleared."), [], ""))

    session_id = conversation.start(mandate)
    state = session.get(session_id)
    state.basket = Basket(items=[
        BasketItem("101", product["item_name"], 1, 550.0)])
    state.state = session.REVIEWING

    out = conversation.handle_turn(session_id, "empty the cart")
    assert out["items"] == []
    assert out["total"] == 0
    assert not out["can_pay"]