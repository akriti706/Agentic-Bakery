import pytest

import agent
from agent import AgentError
from model import Basket, BasketItem


def test_plain_json_parses():
    basket = agent._parse('{"intent": "basket", "items": [{"product_id": '
                          '"101", "name": "Cake", "quantity": 2, '
                          '"unit_price": 550.0}], "reasoning": "ok"}')
    assert basket.intent == "basket"
    assert basket.items[0].quantity == 2
    assert basket.total == 1100.0


def test_fenced_json_parses():
    basket = agent._parse('```json\n{"intent": "browse", "items": [], '
                          '"reasoning": "here"}\n```')
    assert basket.is_browse
    assert basket.is_empty


def test_unknown_intent_falls_back_to_basket():
    assert agent._parse('{"intent": "shopping", "items": []}').intent == "basket"


def test_empty_response_raises():
    with pytest.raises(AgentError):
        agent._parse("")


def test_prose_without_json_raises():
    with pytest.raises(AgentError):
        agent._parse("Sorry, I could not help with that.")


def test_malformed_json_raises():
    with pytest.raises(AgentError):
        agent._parse('{"intent": "browse" or "basket", "items": []}')


def test_item_missing_price_is_dropped():
    basket = agent._parse('{"intent": "basket", "items": ['
                          '{"product_id": "101", "name": "A", "quantity": 1},'
                          '{"product_id": "102", "name": "B", "quantity": 1,'
                          ' "unit_price": 500.0}], "reasoning": ""}')
    assert [i.product_id for i in basket.items] == ["102"]


def test_deliberate_empty_basket_is_kept():
    basket = agent._parse('{"intent": "basket", "items": [], '
                          '"reasoning": "Removed as requested."}')
    assert basket.is_empty
    assert not basket.is_browse


def test_all_items_malformed_raises():
    with pytest.raises(AgentError):
        agent._parse('{"intent": "basket", "items": ['
                     '{"product_id": "101", "name": "A"}], "reasoning": ""}')


def test_search_price_is_capped_by_remaining_budget(mandate):
    assert agent._capped_price(None, mandate, 0) == mandate.total_budget
    assert agent._capped_price(None, mandate, 700) == 300
    assert agent._capped_price(900, mandate, 700) == 300
    assert agent._capped_price(200, mandate, 700) == 200
    assert agent._capped_price(None, mandate, 1200) == 0


def _modify_ceiling(basket, mandate):
    committed = basket.total - max(
        (item.line_total for item in basket.items), default=0.0)
    return agent._capped_price(None, mandate, committed)


def test_a_swap_can_still_reach_the_full_budget(mandate):
    basket = Basket(items=[BasketItem("102", "Black Forest", 1, 900.0)])
    assert _modify_ceiling(basket, mandate) == mandate.total_budget


def test_adding_to_a_two_item_basket_leaves_headroom(mandate):
    basket = Basket(items=[BasketItem("a", "A", 1, 500.0),
                           BasketItem("b", "B", 1, 400.0)])
    assert _modify_ceiling(basket, mandate) == 600.0


def test_both_entry_points_reach_the_search_tool(monkeypatch, mandate):
    ceilings = []

    def fake_search(**kwargs):
        ceilings.append(kwargs["max_price"])
        return {"results": [], "relaxed": [], "out_of_stock": []}

    monkeypatch.setattr(agent.catalog, "search_products", fake_search)
    monkeypatch.setattr(agent.audit, "log", lambda *a, **k: None)

    agent._run_tool("search_products", {}, mandate, "sid", [], 0.0)
    basket = Basket(items=[BasketItem("a", "A", 1, 400.0)])
    committed = basket.total - max(i.line_total for i in basket.items)
    agent._run_tool("search_products", {}, mandate, "sid", [], committed)

    assert ceilings == [mandate.total_budget, mandate.total_budget]