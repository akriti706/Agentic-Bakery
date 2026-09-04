from dataclasses import dataclass, field
from datetime import datetime

from model import Mandate, Basket

SHOPPING = "SHOPPING"
REVIEWING = "REVIEWING"
PAID = "PAID"
CANCELLED = "CANCELLED"

HISTORY_CONTEXT_TURNS = 8

@dataclass
class Turn:
    who: str
    text: str
    
@dataclass
class Session:
    session_id: str
    mandate: Mandate
    basket: Basket = field(default_factory=Basket)
    state: str = SHOPPING
    history: list[Turn] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    last_search: list[dict] = field(default_factory=list)

    def say(self, who: str, text: str) -> None:
        self.history.append(Turn(who=who, text=text))

    @property
    def transcript(self) -> str:
        return "\n".join(f"{t.who}: {t.text}"
                         for t in self.history[-HISTORY_CONTEXT_TURNS:])


_SESSIONS: dict[str, Session] = {}


def create(session_id: str, mandate: Mandate) -> Session:
    _SESSIONS[session_id] = Session(session_id=session_id, mandate=mandate)
    return _SESSIONS[session_id]


def get(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)

def count() -> int:
    return len(_SESSIONS)