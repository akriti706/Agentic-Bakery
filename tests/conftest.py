from datetime import datetime, timedelta
import pytest
from model import Basket, BasketItem, Mandate


@pytest.fixture
def mandate():
    return Mandate(
        mandate_id="M_test",
        customer_id="test_customer",
        expires_at=datetime.now() + timedelta(hours=1),
        total_budget=1000.0,
    )


@pytest.fixture
def expired_mandate(mandate):
    mandate.expires_at = datetime.now() - timedelta(minutes=1)
    return mandate


@pytest.fixture
def product():
    return {
        "product_id": 101,
        "item_name": "Chocolate Truffle Cake",
        "category": "Cake",
        "flavor": "Chocolate",
        "price": 550,
        "discount": 0,
        "final_price": 550.0,
        "on_sale": False,
        "available_quantity": 4,
    }


@pytest.fixture
def discounted(product):
    row = dict(product)
    row.update(product_id=105, item_name="Pineapple Cake", price=450,
               discount=25, final_price=337.5, on_sale=True,
               available_quantity=3)
    return row


@pytest.fixture
def basket_of():
    def build(row, quantity=1, unit_price=None):
        return Basket(items=[BasketItem(
            product_id=str(row["product_id"]),
            name=row["item_name"],
            quantity=quantity,
            unit_price=row["final_price"] if unit_price is None else unit_price,
        )])
    return build