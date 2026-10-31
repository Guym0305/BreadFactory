import json
import logging

import httpx

from app.config import get_settings
from app.i18n import get_lang, t
from app.models.bakery import Customer, Order
from app.services.errors import CheckoutError

log = logging.getLogger(__name__)


def create_hosted_payment(order: Order, customer: Customer) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    lang = get_lang()
    if not settings.grow_enabled:
        return f"{base}/pay/mock/{order.order_number}?lang={lang}"

    payload = {
        "page_code": settings.grow_page_code,
        "user_id": settings.grow_user_id,
        "sum": round(order.total_amount, 2),
        "currency": "ILS",
        "cname": customer.full_name,
        "email": customer.email,
        "phone": customer.phone,
        "description": f"Sourdough Bakery Order {order.order_number}",
        "custom_fields": {"order_id": order.order_number},
        "success_url": f"{base}/order-success?order_id={order.order_number}&lang={lang}",
        "failure_url": f"{base}/order-failed?order_id={order.order_number}&lang={lang}",
        "notify_url": f"{base}/api/v1/payments/webhook",
    }
    headers = {"Authorization": f"Bearer {settings.grow_api_key}"}
    try:
        response = httpx.post(settings.grow_api_url, json=payload, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        log.warning("Grow payment request could not be sent: %s", exc.__class__.__name__)
        raise CheckoutError(t("payment_start"), 502) from exc

    if response.status_code >= 400:
        log.warning("Grow payment request failed with status %s", response.status_code)
        raise CheckoutError(t("payment_start"), 502)

    return _payment_url(response)


def _payment_url(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise CheckoutError(t("payment_start"), 502) from exc

    if isinstance(body, str) and body.startswith("http"):
        return body
    if not isinstance(body, dict):
        raise CheckoutError(t("payment_start"), 502)

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    url = body.get("url") or body.get("payment_url") or data.get("url") or data.get("payment_url")
    if not isinstance(url, str) or not url.startswith("http"):
        log.warning("Grow payment response did not include a hosted URL")
        raise CheckoutError(t("payment_start"), 502)
    return url
