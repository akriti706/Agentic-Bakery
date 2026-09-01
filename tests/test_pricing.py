"""Discounted prices must be the ones verified, charged and displayed."""

import pytest

import policy


@pytest.fixture(autouse=True)
def stub_catalog(monkeypatch, product, discounted):
    rows = {"101": product, "105": discounted}
    monkeypatch.setattr(policy.catalog, "get_product",
                        lambda pid: rows.get(str(pid)))
    monkeypatch.setattr(policy.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(policy.audit, "count_recent_purchases",
                        lambda customer_id, minutes: 0)


def evaluate(basket, mandate):
    return policy.evaluate(basket, mandate, "session_test")


def test_discounted_price_is_accepted(basket_of, discounted, mandate):
    assert evaluate(basket_of(discounted), mandate).approved


def test_pre_discount_price_is_rejected(basket_of, discounted, mandate):
    decision = evaluate(basket_of(discounted, unit_price=450.0), mandate)
    assert not decision.approved
    assert "Rs337.50" in decision.reasons[0]


def test_verified_total_uses_the_discount(basket_of, discounted, mandate):
    assert evaluate(basket_of(discounted, quantity=2),
                    mandate).verified_total == 675.0


def test_list_price_comes_from_the_catalog(basket_of, discounted, mandate):
    basket = basket_of(discounted, quantity=2)
    evaluate(basket, mandate)
    assert basket.items[0].list_price == 450
    assert basket.saved == 225.0


def test_full_price_item_has_no_list_price(basket_of, product, mandate):
    basket = basket_of(product)
    evaluate(basket, mandate)
    assert basket.items[0].list_price is None
    assert basket.saved == 0.0


def test_budget_is_measured_after_discount(basket_of, discounted, mandate):
    mandate.total_budget = 400.0
    assert evaluate(basket_of(discounted), mandate).approved