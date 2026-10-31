import hashlib
import hmac
import json
import re
from urllib.parse import parse_qs

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bakery import OrderStatus, PaymentTransaction
from app.services.errors import CheckoutError
from app.services.orders import get_order

ORDER_NUMBER = re.compile(r"^BAKE-\d{8}-\d{3}$")
SUCCESS_STATUSES = {"0", "SUCCESS", "APPROVED"}


def verify_webhook_signature(body: bytes, signature: str | None, secret: str, require: bool) -> None:
    """Confirm the notify request with HMAC-SHA256 over the raw body.

    Grow's live signing header must be aligned with this check before production
    traffic is accepted. When a Grow API key is configured and the secret is
    empty, the webhook is refused.
    """
    cleaned_secret = secret.strip()
    if not cleaned_secret:
        if require:
            raise CheckoutError("Payment webhook is not configured.", 401)
        return

    provided = (signature or "").strip()
    if provided.lower().startswith("sha256="):
        provided = provided.split("=", 1)[1]
    expected = hmac.new(cleaned_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided.lower()):
        raise CheckoutError("Invalid payment signature.", 401)


def parse_grow_body(content_type: str, body: bytes) -> dict:
    text = body.decode("utf-8", errors="replace")
    if "application/json" in content_type or text.lstrip().startswith("{"):
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise CheckoutError("Payment notification could not be read.", 400) from exc
        if not isinstance(data, dict):
            raise CheckoutError("Payment notification could not be read.", 400)
        custom = data.get("custom_fields") or {}
        if isinstance(custom, str):
            try:
                custom = json.loads(custom)
            except json.JSONDecodeError:
                custom = {}
        if not isinstance(custom, dict):
            custom = {}
        order_number = custom.get("order_id") or data.get("order_id")
        return _normalize(
            order_number=order_number,
            grow_transaction_id=data.get("transaction_id") or data.get("err_id"),
            status=data.get("status"),
            amount=data.get("sum"),
            card_mask=data.get("card_mask"),
            raw=data,
        )

    parsed = parse_qs(text, keep_blank_values=True)

    def first(*names: str) -> str | None:
        for name in names:
            values = parsed.get(name)
            if values and values[0] != "":
                return values[0]
        return None

    raw = {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
    return _normalize(
        order_number=first("custom_fields[order_id]", "order_id"),
        grow_transaction_id=first("transaction_id", "err_id"),
        status=first("status"),
        amount=first("sum"),
        card_mask=first("card_mask"),
        raw=raw,
    )


def apply_webhook(db: Session, payload: dict) -> dict:
    order_number = payload["order_number"]
    if not ORDER_NUMBER.fullmatch(order_number or ""):
        raise CheckoutError("Order not found.", 404)

    order = get_order(db, order_number)
    if order is None:
        raise CheckoutError("Order not found.", 404)
    if order.status == OrderStatus.PAID:
        return {"status": "already_processed"}

    status = payload["status"]
    if status is None:
        raise CheckoutError("Payment status is missing.", 400)
    if str(status).upper() not in SUCCESS_STATUSES:
        order.status = OrderStatus.CANCELLED
        db.commit()
        return {"status": "failed"}

    amount = payload["amount"]
    if amount is None:
        raise CheckoutError("Payment amount is missing.", 400)
    if abs(amount - round(order.total_amount, 2)) > 0.009:
        raise CheckoutError("Payment amount does not match the order.", 400)
    grow_tx_id = payload["grow_transaction_id"]
    if not grow_tx_id:
        raise CheckoutError("Payment reference is missing.", 400)
    if order.transaction is not None:
        return {"status": "already_processed"}

    order.status = OrderStatus.PAID
    db.add(
        PaymentTransaction(
            order_id=order.id,
            grow_transaction_id=str(grow_tx_id)[:100],
            amount_charged=amount,
            card_mask=mask_card(payload["card_mask"]),
            status="SUCCESS",
            raw_response=json.dumps(_sanitize(payload["raw"]), default=str)[:20000],
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "already_processed"}
    return {"status": "ok"}


def _sanitize(value):
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if value is None:
        return None
    text = str(value)
    digits = "".join(character for character in text if character.isdigit())
    if 13 <= len(digits) <= 19 and "*" not in text:
        return mask_card(text)
    return value


def mask_card(value: str | None) -> str:
    if not value:
        return "****"
    text = str(value).strip()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 13 and "*" not in text:
        return f"****{digits[-4:]}"[:20]
    return text[:20]


def _normalize(
    order_number,
    grow_transaction_id,
    status,
    amount,
    card_mask,
    raw: dict,
) -> dict:
    parsed_amount = None
    if amount not in (None, ""):
        try:
            parsed_amount = round(float(amount), 2)
        except (TypeError, ValueError) as exc:
            raise CheckoutError("Payment amount could not be read.", 400) from exc
    return {
        "order_number": str(order_number).strip() if order_number else "",
        "grow_transaction_id": str(grow_transaction_id).strip() if grow_transaction_id else "",
        "status": str(status).strip() if status not in (None, "") else None,
        "amount": parsed_amount,
        "card_mask": str(card_mask) if card_mask else None,
        "raw": raw,
    }
