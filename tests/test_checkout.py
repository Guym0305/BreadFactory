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
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["ADMIN_USERNAME"] = "Admin"
os.environ["ADMIN_PASSWORD"] = "Admin"

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.bakery import Order, Product, User
from app.services.errors import CheckoutError
from app.services.payments import mask_card, verify_webhook_signature


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def customer(phone: str, day: str, product_id: int, quantity: int, method: str = "bit") -> dict:
    payload = {
        "full_name": "Noa Levi",
        "phone": phone,
        "email": "noa@example.com",
        "address": "12 Herzl Street, Tel Aviv",
        "notes": "",
        "payment_method": method,
        "delivery_date": day,
        "lines": [{"product_id": product_id, "quantity": quantity}],
    }
    if method == "other":
        payload["payment_other"] = "Check on delivery"
    return payload


def become_guest(client: TestClient) -> None:
    response = client.post("/guest", data={"lang": "en", "next": "/"}, follow_redirects=False)
    expect(response.status_code == 303, f"guest login failed: {response.status_code}")


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
        locked = client.get("/?lang=en", follow_redirects=False)
        expect(locked.status_code == 303, "home should require login")
        expect("/login" in locked.headers["location"], locked.headers["location"])

        login_page = client.get("/login?lang=en")
        expect(login_page.status_code == 200, "login page missing")
        expect("Continue as Guest" in login_page.text, "guest option missing")
        expect("Create account" in login_page.text, "register form missing")

        become_guest(client)
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
        expect("Guest" in home.text, "guest account chip missing")
        expect("Payment by Grow" not in home.text, "Grow payment copy should be gone")

        from app.config import get_settings

        os.environ["SESSION_EPOCH"] = "test-revision-after-deploy"
        get_settings.cache_clear()
        after_deploy = client.get("/?lang=en", follow_redirects=False)
        expect(after_deploy.status_code == 303, "new deploy should clear the prior session")
        expect("/login" in after_deploy.headers["location"], after_deploy.headers["location"])
        os.environ.pop("SESSION_EPOCH", None)
        get_settings.cache_clear()
        become_guest(client)

        hebrew_home = client.get("/?lang=he")
        expect("מועד אחרון להזמנה" in hebrew_home.text, "hebrew home is missing the order deadline")
        expect("המשלוח הבא" in hebrew_home.text, "hebrew home is missing the delivery label")
        expect("הזמנה לשבוע הבא" in hebrew_home.text, "hebrew home is missing the next-week link")
        expect('lang="he"' in hebrew_home.text, "hebrew page is missing its language")
        expect('dir="rtl"' in hebrew_home.text, "hebrew page should read right to left")

        css = client.get("/static/css/style.css")
        expect("#fdfbf7" in css.text, "parchment background is missing")
        expect(".pay-method-grid" in css.text, "payment method styles are missing")
        expect(".login-panels" in css.text, "login styles are missing")

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
        expect("Place order" in chosen.text, "order form is missing")
        expect("How to charge" in chosen.text, "payment method picker is missing")
        expect("/static/images/payment/bit.svg" in chosen.text, "Bit icon is missing")
        expect("/static/images/payment/paybox.svg" in chosen.text, "PayBox icon is missing")
        hebrew_bake = client.get(f"/?date={day}&lang=he")
        expect("לחם מחמצת כפרי" in hebrew_bake.text, "hebrew product title is missing")
        expect("כיכר גרעינים" in hebrew_bake.text, "hebrew seeded loaf title is missing")
        expect("איך לחייב" in hebrew_bake.text, "hebrew payment picker is missing")

        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        rejected = client.post(
            "/api/v1/orders",
            json=customer("0501234567", day, product_id, 1),
            headers={"Origin": "https://evil.example"},
        )
        expect(rejected.status_code in (401, 403), "cross-site or anonymous order was accepted")

        become_guest(client)
        cloud_form = {
            "delivery_date": day,
            "qty_" + str(product_id): "1",
            "full_name": "",
            "payment_method": "cash",
            "lang": "en",
        }
        behind_https = client.post(
            "/checkout",
            data=cloud_form,
            headers={"Origin": "https://testserver", "X-Forwarded-Proto": "https"},
        )
        expect(behind_https.status_code == 400, "https checkout behind a proxy was rejected")
        expect("another site" not in behind_https.text, "the public https site was treated as another site")
        expect("Enter a name." in behind_https.text, "validation should still run after the origin check")
        plain_https = client.post(
            "/checkout",
            data=cloud_form,
            headers={"Origin": "https://testserver"},
        )
        expect("another site" in plain_https.text, "https origin on a direct http connection should be refused")

        invalid = client.post(
            "/checkout",
            data={
                "delivery_date": day,
                "qty_" + str(product_id): "1",
                "full_name": "",
                "payment_method": "cash",
                "lang": "en",
            },
        )
        expect(invalid.status_code == 400, "blank name was accepted")
        expect("Enter a name." in invalid.text, "validation message missing")

        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        missing_auth = client.post("/api/v1/orders", json=customer("0505555555", day, product_id, 1))
        expect(missing_auth.status_code == 401, "anonymous API order was accepted")

        become_guest(client)
        created = client.post("/api/v1/orders", json=customer("0501111111", day, product_id, 1, "paybox"))
        expect(created.status_code == 200, created.text)
        body = created.json()
        order_number = body["order_number"]
        expect(order_number.startswith("BAKE-"), order_number)
        expect(body["status"] == "PAID", body["status"])
        expect(body["payment_method"] == "paybox", body["payment_method"])
        expect(body.get("payment_url", "") == "", "hosted payment URL should not be created")

        db = SessionLocal()
        try:
            stored = db.query(Order).filter_by(order_number=order_number).one()
            guest = db.query(User).filter(User.is_guest.is_(True)).order_by(User.id.desc()).first()
            expect(guest is not None, "guest user missing")
            expect(stored.customer_id == guest.customer_id, "order should use the signed-in customer")
            expect(stored.payment_method == "paybox", stored.payment_method)
            expect(stored.payment_url is None, "payment_url should stay empty")
            admin = db.query(User).filter_by(username="Admin").one()
            expect(admin.is_admin is True, "admin flag missing")
        finally:
            db.close()

        success = client.get(f"/order-success?order_id={order_number}&lang=en")
        expect("Order confirmed" in success.text, "confirmation copy missing")
        expect(f"Already rushing to bake order: {order_number}" in success.text, "confirmation headline missing")
        expect("PayBox" in success.text, "selected payment method missing from confirmation")
        expect("Noa Levi" in success.text, "customer name missing from confirmation")

        other = client.post(
            "/checkout",
            data={
                "delivery_date": day,
                "qty_" + str(product_id): "1",
                "full_name": "Dana Cohen",
                "phone": "0502222222",
                "email": "dana@example.com",
                "address": "8 Allenby Street, Tel Aviv",
                "payment_method": "other",
                "payment_other": "Friends and family",
                "lang": "en",
            },
            follow_redirects=False,
        )
        expect(other.status_code == 303, "form checkout did not redirect")
        expect("/order-success" in other.headers["location"], other.headers["location"])
        other_page = client.get(other.headers["location"])
        expect("Order confirmed" in other_page.text, "guest form checkout did not confirm the order")
        expect("Already rushing to bake order:" in other_page.text, "guest confirmation headline missing")
        expect("Dana Cohen" in other_page.text, "guest customer name missing from confirmation")
        expect("Friends and family" in other_page.text, "other payment text missing")
        expect("8 Allenby Street, Tel Aviv" in other_page.text, "guest delivery address missing")

        blocked = client.post("/api/v1/orders", json=customer("0503333333", day, product_id, 1))
        expect(blocked.status_code == 400, "capacity was exceeded")

        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        registered = client.post(
            "/register",
            data={
                "username": "baker_noa",
                "password": "secret12",
                "full_name": "Noa Baker",
                "phone": "0506666666",
                "email": "noa.baker@example.com",
                "address": "5 Bread Lane, Jerusalem",
                "lang": "en",
                "next": "/",
            },
            follow_redirects=False,
        )
        expect(registered.status_code == 303, "registration did not redirect")
        signed_in = client.get("/?week=next&lang=en")
        expect("baker_noa" in signed_in.text, "registered username missing from header")
        expect('value="Noa Baker"' in signed_in.text, "registered customer name was not prefilled")
        expect('value="0506666666"' in signed_in.text, "registered customer phone was not prefilled")
        expect("5 Bread Lane, Jerusalem" in signed_in.text, "registered customer address was not prefilled")

        db = SessionLocal()
        try:
            linked = db.query(User).filter_by(username="baker_noa").one()
            expect(linked.customer_id is not None, "registered user missing customer link")
            expect(linked.customer.full_name == "Noa Baker", linked.customer.full_name)
            expect(linked.customer.phone == "0506666666", linked.customer.phone)
            expect(linked.customer.email == "noa.baker@example.com", linked.customer.email)
        finally:
            db.close()

        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        duplicate = client.post(
            "/register",
            data={
                "username": "other_noa",
                "password": "secret12",
                "full_name": "Other Noa",
                "phone": "0506666666",
                "email": "other.noa@example.com",
                "address": "9 Other Street, Tel Aviv",
                "lang": "en",
                "next": "/",
            },
        )
        expect(duplicate.status_code == 400, "duplicate customer phone was accepted")
        expect("phone number already belongs" in duplicate.text, "duplicate phone message missing")

        bad_login = client.post(
            "/login",
            data={"username": "baker_noa", "password": "wrong-pass", "lang": "en", "next": "/"},
        )
        expect(bad_login.status_code == 400, "bad password was accepted")
        expect("Wrong username or password." in bad_login.text, "login error message missing")
        expect("banner-error" in bad_login.text, "login error should use error styling")

        client.post("/logout", data={"lang": "he"}, follow_redirects=False)
        hebrew_user = client.post(
            "/register",
            data={
                "username": "גיא_01",
                "password": "secret12",
                "full_name": "גיא מ",
                "phone": "0507777777",
                "email": "guy.he@example.com",
                "address": "1 Jaffa Street, Jerusalem",
                "lang": "he",
                "next": "/",
            },
            follow_redirects=False,
        )
        expect(hebrew_user.status_code == 303, "Hebrew username registration failed")
        hebrew_home = client.get("/?lang=he")
        expect("גיא_01" in hebrew_home.text, "Hebrew username missing from header")
        client.post("/logout", data={"lang": "en"}, follow_redirects=False)

        good_login = client.post(
            "/login",
            data={"username": "baker_noa", "password": "secret12", "lang": "en", "next": "/"},
            follow_redirects=False,
        )
        expect(good_login.status_code == 303, "good login did not redirect")
        returned = client.get("/?week=next&lang=en")
        expect("Wonderful to see you again, baker_noa" in returned.text, "welcome message missing")
        expect('value="Noa Baker"' in returned.text, "returning user lost saved customer details")
        expect('value="noa.baker@example.com"' in returned.text, "returning user lost saved email")
        client.post("/logout", data={"lang": "en"}, follow_redirects=False)

        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        admin_login = client.post(
            "/login",
            data={"username": "Admin", "password": "Admin", "lang": "en", "next": "/"},
            follow_redirects=False,
        )
        expect(admin_login.status_code == 303, "admin login failed")
        expect("/admin" in admin_login.headers["location"], admin_login.headers["location"])
        home_as_admin = client.get("/?lang=en", follow_redirects=False)
        expect(home_as_admin.status_code == 302, "admin should not see the regular home")
        expect("/admin" in home_as_admin.headers["location"], home_as_admin.headers["location"])
        admin_page = client.get("/admin?lang=en")
        expect(admin_page.status_code == 200, "admin page missing")
        expect("Bakery desk" in admin_page.text, "admin desk copy missing")
        expect("Orders" in admin_page.text, "orders action missing")
        expect("Products" in admin_page.text, "products action missing")
        expect("Customers" in admin_page.text, "customers action missing")
        expect("Delivery list" in admin_page.text, "delivery action missing")

        orders_page = client.get("/admin/orders?lang=en")
        expect(orders_page.status_code == 200, "orders page missing")
        expect("BAKE-" in orders_page.text, "expected seeded orders on admin list")

        products_page = client.get("/admin/update-content?lang=en")
        expect(products_page.status_code == 200, "products page missing")
        expect("Edit" in products_page.text, "product edit link missing")
        first_product = SessionLocal()
        try:
            product_id = first_product.query(Product).order_by(Product.id).first().id
        finally:
            first_product.close()
        product_edit = client.get(f"/admin/products/{product_id}?lang=en")
        expect(product_edit.status_code == 200, "product edit missing")
        saved_product = client.post(
            f"/admin/products/{product_id}",
            data={
                "lang": "en",
                "name_en": "Admin Updated Loaf",
                "name_he": "כיכר מעודכנת",
                "description_en": "Updated by admin",
                "description_he": "עודכן על ידי מנהל",
                "ingredients_en": "flour water",
                "ingredients_he": "קמח מים",
                "price": "42.50",
                "fermentation_hours": "30",
                "image_url": "",
                "is_active": "1",
            },
            follow_redirects=False,
        )
        expect(saved_product.status_code == 303, "product save failed")

        users_page = client.get("/admin/change-password?lang=en")
        expect(users_page.status_code == 200, "users page missing")
        expect("baker_noa" in users_page.text, "registered user missing from admin list")
        db = SessionLocal()
        try:
            baker = db.query(User).filter_by(username="baker_noa").one()
            baker_id = baker.id
        finally:
            db.close()
        reset = client.post(
            f"/admin/users/{baker_id}/password",
            data={"lang": "en", "password": "newpass99"},
            follow_redirects=False,
        )
        expect(reset.status_code == 303, "password reset failed")
        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        relogin = client.post(
            "/login",
            data={"username": "baker_noa", "password": "newpass99", "lang": "en", "next": "/"},
            follow_redirects=False,
        )
        expect(relogin.status_code == 303, "login with reset password failed")
        client.post("/logout", data={"lang": "en"}, follow_redirects=False)
        admin_again = client.post(
            "/login",
            data={"username": "Admin", "password": "Admin", "lang": "en", "next": "/"},
            follow_redirects=False,
        )
        expect(admin_again.status_code == 303, "admin re-login failed")

        delivery_page = client.get("/admin/delivery-list?lang=en")
        expect(delivery_page.status_code == 200, "delivery list missing")
        expect("Delivery list" in delivery_page.text, "delivery heading missing")

        db = SessionLocal()
        try:
            order = db.query(Order).order_by(Order.id).first()
            expect(order is not None, "missing order for admin line edit")
            order_id = order.id
            item = order.items[0]
            item_id = item.id
            item_product_id = item.product_id
            item_price = item.unit_price
            baker = db.query(User).filter_by(username="baker_noa").one()
            baker_id = baker.id
            hebrew = db.query(User).filter_by(username="גיא_01").one()
            hebrew_id = hebrew.id
        finally:
            db.close()

        order_edit = client.get(f"/admin/orders/{order_id}?lang=en")
        expect(order_edit.status_code == 200, "order edit page missing")
        expect("Order lines" in order_edit.text, "order line editor missing")
        from urllib.parse import urlencode

        saved_order = client.post(
            f"/admin/orders/{order_id}",
            content=urlencode(
                [
                    ("lang", "en"),
                    ("status", "PAID"),
                    ("payment_method", "bit"),
                    ("payment_other", ""),
                    ("notes", "Admin adjusted"),
                    ("item_id", str(item_id)),
                    ("item_product_id", str(item_product_id)),
                    ("item_quantity", "3"),
                    ("item_unit_price", f"{item_price:.2f}"),
                    ("new_product_id", str(product_id)),
                    ("new_quantity", "1"),
                    ("new_unit_price", ""),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        expect(saved_order.status_code == 303, "order line save failed")
        db = SessionLocal()
        try:
            updated = db.query(Order).filter_by(id=order_id).one()
            expect(updated.status.value == "PAID", "order status not updated")
            expect(len(updated.items) == 2, "expected existing + new order line")
            expect(sum(item.quantity for item in updated.items) == 4, "order quantities wrong")
        finally:
            db.close()

        promote = client.post(
            f"/admin/users/{baker_id}/role",
            data={"lang": "en", "is_admin": "1"},
            follow_redirects=False,
        )
        expect(promote.status_code == 303, "promote to admin failed")
        db = SessionLocal()
        try:
            expect(db.query(User).filter_by(id=baker_id).one().is_admin is True, "baker was not promoted")
        finally:
            db.close()
        demote = client.post(
            f"/admin/users/{baker_id}/role",
            data={"lang": "en"},
            follow_redirects=False,
        )
        expect(demote.status_code == 303, "demote admin failed")

        removed = client.post(
            f"/admin/users/{hebrew_id}/delete",
            data={"lang": "en"},
            follow_redirects=False,
        )
        expect(removed.status_code == 303, "user delete failed")
        db = SessionLocal()
        try:
            expect(db.query(User).filter_by(username="גיא_01").one_or_none() is None, "hebrew user still present")
        finally:
            db.close()

    print("order flow ok")


if __name__ == "__main__":
    main()
