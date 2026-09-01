"""
Each rule in policy.RULES gets a test that trips it and one that does not.

The catalog is stubbed so these tests never touch the real database and
never depend on current stock levels.
"""

import pytest

import policy
from model import Basket, BasketItem


@pytest.fixture(autouse=True)
def stub_catalog(monkeypatch, product, discounted):
    rows = {"101": product, "105": discounted}
    monkeypatch.setattr(policy.catalog, "get_product",
                        lambda pid: rows.get(str(pid)))
    monkeypatch.setattr(policy.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(policy.audit, "count_recent_purchases",
                        lambda customer_id, minutes: 0)
    return rows


def evaluate(basket, mandate):
    return policy.evaluate(basket, mandate, "session_test")


def test_clean_basket_is_approved(basket_of, product, mandate):
    assert evaluate(basket_of(product), mandate).approved


def test_expired_mandate_blocks(basket_of, product, expired_mandate):
    decision = evaluate(basket_of(product), expired_mandate)
    assert not decision.approved
    assert "expired" in decision.reasons[0]


def test_empty_basket_blocks(mandate):
    assert not evaluate(Basket(), mandate).approved


def test_duplicate_product_blocks(product, mandate):
    basket = Basket(items=[
        BasketItem("101", product["item_name"], 1, 550.0),
        BasketItem("101", product["item_name"], 1, 550.0),
    ])
    assert not evaluate(basket, mandate).approved


def test_unknown_product_blocks(mandate):
    basket = Basket(items=[BasketItem("999", "Unicorn Cake", 1, 10.0)])
    decision = evaluate(basket, mandate)
    assert not decision.approved
    assert "not a product" in decision.reasons[0]


def test_wrong_price_blocks(basket_of, product, mandate):
    decision = evaluate(basket_of(product, unit_price=99.0), mandate)
    assert not decision.approved
    assert "Rs550.00" in decision.reasons[0]


def test_rounding_noise_is_tolerated(basket_of, product, mandate):
    assert evaluate(basket_of(product, unit_price=550.004), mandate).approved


def test_zero_quantity_blocks(basket_of, product, mandate):
    assert not evaluate(basket_of(product, quantity=0), mandate).approved





def test_quantity_over_stock_blocks(basket_of, product, mandate):
    decision = evaluate(basket_of(product, quantity=5), mandate)
    assert not decision.approved
    assert any("left in stock" in reason for reason in decision.reasons)


def test_total_budget_blocks(basket_of, product, mandate):
    mandate.total_budget = 800.0
    decision = evaluate(basket_of(product, quantity=2), mandate)
    assert not decision.approved
    assert any("over your" in reason for reason in decision.reasons)


def test_budget_message_states_the_overage(basket_of, product, mandate):
    mandate.total_budget = 900.0
    reasons = evaluate(basket_of(product, quantity=2), mandate).reasons
    assert any("Rs200.00" in reason for reason in reasons)


def test_velocity_blocks(monkeypatch, basket_of, product, mandate):
    monkeypatch.setattr(
        policy.audit, "count_recent_purchases",
        lambda customer_id, minutes: policy.VELOCITY_MAX_PURCHASES)
    assert not evaluate(basket_of(product), mandate).approved


def test_every_violation_is_reported(product, mandate):
    mandate.total_budget = 100.0
    basket = Basket(items=[
        BasketItem("101", product["item_name"], 99, 1.0),
        BasketItem("999", "Unicorn Cake", 1, 10.0),
    ])
    reasons = evaluate(basket, mandate).reasons
    assert len(reasons) >= 3


def test_stamped_list_price_does_not_look_like_a_change(basket_of, discounted,
                                                        mandate):
    proposed = basket_of(discounted)
    evaluate(proposed, mandate)
    assert basket_of(discounted).contents == proposed.contents


def test_a_real_change_is_still_detected(basket_of, discounted, mandate):
    proposed = basket_of(discounted)
    evaluate(proposed, mandate)
    assert basket_of(discounted, quantity=2).contents != proposed.contents