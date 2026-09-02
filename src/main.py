import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import audit
import catalog
import conversation
import orders
from database import check_user, create_table, save_user
from contextlib import asynccontextmanager

BASE = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = BASE / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_table()
    audit.init()
    orders.init()
    yield

app = FastAPI(title="Agentic Bakery", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


class User(BaseModel):
    email: str
    password: str
    total_budget: float | None = None
   


class TurnRequest(BaseModel):
    session_id: str
    message: str


class PayRequest(BaseModel):
    session_id: str
    total: float


class SessionRequest(BaseModel):
    customer_id: str
    total_budget: float | None = None
    



@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/register")
def register(user: User):
    customer_id = save_user(user.email, user.password)
    return {"success": True, "customer_id": customer_id, "email": user.email}


@app.post("/login")
def login(user: User):
    result = check_user(user.email, user.password)
    if result is None:
        return JSONResponse(status_code=401,
                            content={"success": False,
                                     "message": "Invalid email or password"})

    customer_id = result[0]
    mandate = conversation.create_mandate(customer_id, user.total_budget)
    return {
        "success": True,
        "customer_id": customer_id,
        "session_id": conversation.start(mandate),
        "mandate": mandate.as_dict(),
    }


@app.post("/app/session")
def new_session(req: SessionRequest):
    mandate = conversation.create_mandate(req.customer_id, req.total_budget)
    return {"session_id": conversation.start(mandate),
            "mandate": mandate.as_dict()}


@app.post("/app/start")
def turn(req: TurnRequest):
    return JSONResponse(conversation.handle_turn(req.session_id, req.message))


@app.post("/app/pay")
def pay(req: PayRequest):
    return JSONResponse(conversation.pay(req.session_id, req.total))


@app.get("/app/deals")
def deals():
    return {"deals": catalog.deals()}


@app.get("/app/categories")
def categories():
    return {"categories": catalog.categories()}


@app.get("/app/orders")
def all_orders():
    return {"orders": orders.all_orders()}


@app.get("/app/orders/{customer_id}")
def customer_orders(customer_id: str):
    return {"orders": orders.for_customer(customer_id)}


@app.get("/app/orders.csv")
def orders_csv():
    path = orders.export_csv()
    return FileResponse(path, media_type="text/csv", filename="orders.csv")


@app.get("/app/audit/{session_id}")
def trail(session_id: str):
    return {"audit_trail": audit.get_session(session_id)}