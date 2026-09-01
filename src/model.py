from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BasketItem:
    product_id: str
    name: str
    quantity: int
    unit_price: float
    list_price: float | None = None

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)

    @property
    def saved(self) -> float:
        if not self.list_price:
            return 0.0
        return round((self.list_price - self.unit_price) * self.quantity, 2)

    @property
    def key(self) -> tuple:
        return (self.product_id, self.quantity, self.unit_price)

    def as_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "list_price": self.list_price,
            "line_total": self.line_total,
        }


@dataclass
class Basket:
    items: list[BasketItem] = field(default_factory=list)
    reasoning: str = ""
    intent: str = "basket"

    @property
    def total(self) -> float:
        return round(sum(i.line_total for i in self.items), 2)

    @property
    def saved(self) -> float:
        return round(sum(i.saved for i in self.items), 2)

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0

    @property
    def is_browse(self) -> bool:
        return self.intent == "browse"

    @property
    def contents(self) -> list:
        """What the customer actually ordered, ignoring stamped metadata."""
        return sorted(i.key for i in self.items)


@dataclass
class Mandate:
    mandate_id: str
    customer_id: str
    expires_at: datetime
    total_budget: float
    

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at

    def as_dict(self) -> dict:
        return {
            "mandate_id": self.mandate_id,
            "total_budget": self.total_budget,
            "expires_at": self.expires_at.isoformat(timespec="seconds"),
        }