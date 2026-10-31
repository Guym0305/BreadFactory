import hashlib
import hmac
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

db_path = ROOT / "data" / "test-checkout.db"
for suffix in ("", "-wal", "-shm"):
    candidate = Path(str(db_path) + suffix)
    if candidate.exists():
        candidate.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./data/test-checkout.db"
os.environ["SLOT_CAPACITY"] = "2"
os.environ["GROW_API_KEY"] = ""
os.environ["GROW_WEBHOOK_SECRET"] = ""
os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1:8000"

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.bakery import Order, PaymentTransaction, utcnow
from app.services.errors import CheckoutError
from app.services.payments import mask_card, verify_webhook_signature


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def customer(phone: str, day: str, product_id: int, quantity: int) -> dict:
    return {
        "full_name": "Noa Levi",
        "phone": phone,
        "email": "noa@example.com",
        "address": "12 Herzl Street, Tel Aviv",
        "notes": "",
        "delivery_date": day,
        "lines": [{"product_id": product_id, "quantity": quantity}],
    }


def main() -> None:
    body = b"status=SUCCESS"
    try:
        verify_webhook_signature(body, "nope", "secret", True)
        raise SystemExit("bad signature was accepted")
    except CheckoutError as exc:
        expect(exc.status_code == 401, "bad signature should be rejected")
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    verify_webhook_signature(body, digest, "secret", True)
    expect(mask_card("4580123412341234") == "****1234", "full card numbers must be masked")

    with TestClient(app) as client:
        home = client.get("/?lang=en")
        expect(home.status_code == 200, f"home status {home.status_code}")
        expect("Last ordering" in home.text, "home is missing the Wednesday deadline")
        expect("Next delivery" in home.text, "home is missing the Friday delivery")
        expect("Order for next week" in home.text, "home is missing the next-week link")
        expect("לחם בהר" in home.text, "the business name should lead the english page")
        expect("hero-loaf.jpg" in home.text, "the home page is missing its stand-in photo")
        expect("country-loaf.jpg" in home.text, "product photos were not switched on")
        expect("Playfair+Display" in home.text, "serif face is not loaded")
        expect('lang="en"' in home.text, "english page is missing its language")

        hebrew_home = client.get("/?lang=he")
        expect("מועד אחרון להזמנה" in hebrew_home.text, "hebrew home is missing the order deadline")
        expect("המשלוח הבא" in hebrew_home.text, "hebrew home is missing the delivery label")
        expect("הזמנה לשבוע הבא" in hebrew_home.text, "hebrew home is missing the next-week link")
        expect('lang="he"' in hebrew_home.text, "hebrew page is missing its language")
        expect('dir="rtl"' in hebrew_home.text, "hebrew page should read right to left")

        css = client.get("/static/css/style.css")
        expect("#fdfbf7" in css.text, "parchment background is missing")

        slots = client.get("/api/v1/slots?lang=en").json()
        products = client.get("/api/v1/products").json()
        expect(len(products) == 3, "expected three seeded loaves")
        expect(len(slots) == 1, "the screen should offer one delivery week")
        day = slots[0]["date"]
        delivery = date.fromisoformat(day)
        deadline = date.fromisoformat(slots[0]["order_by"])
        expect(delivery.weekday() == 4, "delivery should be a Friday")
        expect(deadline.weekday() == 2, "last ordering should be a Wednesday")
        expect(deadline < delivery, "ordering should close before delivery")
        product_id = products[0]["id"]
        expect(slots[0]["remaining"] == 2, "capacity was not applied")

        following = client.get("/api/v1/slots?week=next&lang=en").json()
        expect(
            date.fromisoformat(following[0]["date"]) - delivery == timedelta(days=7),
            "next week should be the Friday after the coming delivery",
        )
        next_page = client.get("/?week=next&lang=en")
        expect("Coming delivery" in next_page.text, "next week view should link back")
        expect("Next week" in next_page.text, "next week heading is missing")

        chosen = client.get(f"/?date={day}&lang=en")
        expect("Country Sourdough" in chosen.text, "gallery did not open for the coming Friday")
        expect("Proceed to payment" in chosen.text, "checkout form is missing")
        hebrew_bake = client.get(f"/?date={day}&lang=he")
        expect("לחם מחמצת כפרי" in hebrew_bake.text, "hebrew product title is missing")
        expect("כיכר גרעינים" in hebrew_bake.text, "hebrew seeded loaf title is missing")

        rejected = client.post(
            "/api/v1/orders",
            json=customer("0501234567", day, product_id, 1),
            headers={"Origin": "https://evil.example"},
        )
        expect(rejected.status_code == 403, "cross-site order was accepted")

        invalid = client.post(
            "/checkout",
            data={"delivery_date": day, "qty_" + str(product_id): "1", "full_name": "", "lang": "en"},
        )
        expect(invalid.status_code == 400, "blank name was accepted")
        expect("Enter a name." in invalid.text, "validation message missing")

        created = client.post("/api/v1/orders", json=customer("0501111111", day, product_id, 1))
        expect(created.status_code == 200, created.text)
        order_number = created.json()["order_number"]
        expect(order_number.startswith("BAKE-"), order_number)

        checkout = client.get(f"/checkout/{order_number}?lang=en")
        expect(checkout.status_code == 200, "checkout page missing")
        expect("<iframe" in checkout.text, "payment iframe missing")
        expect(f"/pay/mock/{order_number}" in checkout.text, "development payment URL missing")

        mismatch = client.post(
            "/api/v1/payments/webhook",
            data={
                "order_id": order_number,
                "transaction_id": "TX-WRONG",
                "status": "SUCCESS",
                "sum": "1.00",
                "card_mask": "4580123412349999",
            },
        )
        expect(mismatch.status_code == 400, "mismatched amount was accepted")
        still_pending = client.get(f"/api/v1/orders/{order_number}").json()
        expect(still_pending["status"] == "PENDING_PAYMENT", still_pending["status"])

        paid = client.post(
            "/api/v1/payments/webhook",
            data={
                "order_id": order_number,
                "transaction_id": "TX-1",
                "status": "SUCCESS",
                "sum": str(created.json()["total_amount"]),
                "card_mask": "4580123412349999",
            },
        )
        expect(paid.status_code == 200, paid.text)
        expect(paid.json()["status"] == "ok", paid.text)
        duplicate = client.post(
            "/api/v1/payments/webhook",
            data={
                "order_id": order_number,
                "transaction_id": "TX-1",
                "status": "SUCCESS",
                "sum": str(created.json()["total_amount"]),
            },
        )
        expect(duplicate.json()["status"] == "already_processed", duplicate.text)

        success = client.get(f"/order-success?order_id={order_number}&lang=en")
        expect("Payment received" in success.text, "confirmation copy missing")

        db = SessionLocal()
        try:
            stored = db.query(PaymentTransaction).filter_by(order_id=db.query(Order).filter_by(order_number=order_number).one().id).one()
            expect(stored.card_mask == "****9999", stored.card_mask)
            expect(db.query(PaymentTransaction).count() == 1, "webhook created a duplicate transaction")
        finally:
            db.close()

        pending = client.post("/api/v1/orders", json=customer("0502222222", day, product_id, 1))
        expect(pending.status_code == 200, pending.text)
        blocked = client.post("/api/v1/orders", json=customer("0503333333", day, product_id, 1))
        expect(blocked.status_code == 400, "capacity was exceeded")

        db = SessionLocal()
        try:
            held = db.query(Order).filter_by(order_number=pending.json()["order_number"]).one()
            held.created_at = utcnow() - timedelta(minutes=45)
            db.commit()
        finally:
            db.close()

        released = client.post("/api/v1/orders", json=customer("0504444444", day, product_id, 1))
        expect(released.status_code == 200, released.text)
        form_checkout = client.post(
            f"/pay/mock/{released.json()['order_number']}/complete",
            follow_redirects=False,
        )
        expect(form_checkout.status_code == 303, "mock payment did not redirect")
        confirmed = client.get(form_checkout.headers["location"] if "lang=" in form_checkout.headers["location"] else form_checkout.headers["location"] + "&lang=en")
        expect("Payment received" in confirmed.text, "mock payment did not confirm the order")

    print("order flow ok")


if __name__ == "__main__":
    main()
