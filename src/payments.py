"""Payment providers behind one interface."""

import os
import uuid
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

CAPTURED = "captured"
INITIATED = "initiated"
FAILED = "failed"

PROVIDER = os.getenv("PAYMENT_PROVIDER", "mock").lower()
CURRENCY = "INR"


@dataclass
class PaymentResult:
    status: str
    provider: str
    reference: str = ""
    message: str = ""

    @property
    def captured(self) -> bool:
        return self.status == CAPTURED

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "provider": self.provider,
            "reference": self.reference,
            "message": self.message,
        }

def _forced_failure() -> bool:
    
    load_dotenv(override=True)
    return os.getenv("FORCE_PAYMENT_FAILURE") == "1"
 
 
def _mock(amount, session_id, customer_id) -> PaymentResult:
    if _forced_failure():
        return PaymentResult(FAILED, "mock",
                             message="Card declined by issuer.")
    return PaymentResult(CAPTURED, "mock",
                         reference=f"mock_{uuid.uuid4().hex[:12]}",
                         message="Payment captured in test mode.")



def _razorpay(amount, session_id, customer_id) -> PaymentResult:
    key = os.getenv("RAZORPAY_KEY_ID")
    secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key or not secret:
        return PaymentResult(FAILED, "razorpay",
                             message="Razorpay credentials missing from .env.")
    try:
        import razorpay
    except ImportError:
        return PaymentResult(FAILED, "razorpay",
                             message="razorpay package is not installed.")

    try:
        client = razorpay.Client(auth=(key, secret))
        order = client.order.create({
            "amount": int(round(amount * 100)),
            "currency": CURRENCY,
            "receipt": session_id,
            "notes": {"customer_id": str(customer_id)},
        })
    except Exception as error:
        return PaymentResult(FAILED, "razorpay", message=str(error))

    return PaymentResult(
        INITIATED, "razorpay", reference=order["id"],
        message="Order created in Razorpay test mode. It stays unpaid "
                "until the customer completes checkout.")


PROVIDERS = {"mock": _mock, "razorpay": _razorpay}


def charge(amount: float, session_id: str, customer_id) -> PaymentResult:
    handler = PROVIDERS.get(PROVIDER)
    if handler is None:
        return PaymentResult(FAILED, PROVIDER,
                             message=f"Unknown payment provider {PROVIDER}.")
    return handler(amount, session_id, customer_id)