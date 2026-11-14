from dataclasses import dataclass
from datetime import date

from fastapi import Request, Response

from app.i18n import t
from app.services.auth import _session_epoch, _sign, _unsign
from app.services.errors import CheckoutError

CART_COOKIE = "bf_cart"
CART_MAX_AGE = 60 * 60 * 24 * 14
MAX_LINE = 99


@dataclass
class Cart:
    delivery_date: date | None
    quantities: dict[int, int]

    @property
    def loaf_count(self) -> int:
        return sum(self.quantities.values())


def empty_cart() -> Cart:
    return Cart(None, {})


def _parse_items(items_part: str) -> dict[int, int]:
    quantities: dict[int, int] = {}
    if not items_part:
        return quantities
    for piece in items_part.split(","):
        product_part, eq, qty_part = piece.partition("=")
        if eq != "=" or not product_part.isdigit() or not qty_part.isdigit():
            continue
        amount = int(qty_part)
        if amount > 0:
            quantities[int(product_part)] = min(amount, MAX_LINE)
    return quantities


def read_cart(request: Request) -> Cart:
    token = request.cookies.get(CART_COOKIE)
    if not token:
        return empty_cart()
    raw = _unsign(token)
    if raw is None:
        return empty_cart()
    epoch, sep, rest = raw.partition(":")
    if sep != ":" or epoch != _session_epoch() or not rest:
        return empty_cart()
    found: list[tuple[date, dict[int, int]]] = []
    # One Friday is stored as "date:id=qty". Older multi-Friday cookies used
    # "date|id=qty;date|id=qty" and are folded into a single basket.
    chunks = [rest] if "|" not in rest and rest.count(":") == 1 else rest.split(";")
    for chunk in chunks:
        if "|" in chunk:
            date_part, mark, items_part = chunk.partition("|")
            if mark != "|":
                continue
        else:
            date_part, mark, items_part = chunk.partition(":")
            if mark != ":":
                continue
        try:
            delivery = date.fromisoformat(date_part)
        except ValueError:
            continue
        quantities = _parse_items(items_part)
        if quantities:
            found.append((delivery, quantities))
    if not found:
        return empty_cart()
    merged: dict[int, int] = {}
    for _delivery, quantities in found:
        for product_id, quantity in quantities.items():
            merged[product_id] = min(merged.get(product_id, 0) + quantity, MAX_LINE)
    return Cart(found[-1][0], merged)


def write_cart(response: Response, cart: Cart) -> None:
    quantities = {pid: qty for pid, qty in cart.quantities.items() if qty > 0}
    if cart.delivery_date is None or not quantities:
        clear_cart(response)
        return
    body = ",".join(f"{pid}={quantities[pid]}" for pid in sorted(quantities))
    payload = f"{_session_epoch()}:{cart.delivery_date.isoformat()}:{body}"
    response.set_cookie(
        CART_COOKIE,
        _sign(payload),
        max_age=CART_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_cart(response: Response) -> None:
    response.delete_cookie(CART_COOKIE, path="/")


def quantities_from_form(form) -> dict[int, int]:
    quantities: dict[int, int] = {}
    for key, value in form.multi_items():
        name = str(key)
        if not name.startswith("qty_"):
            continue
        raw = str(value).strip()
        if raw in ("", "0"):
            continue
        try:
            quantity = int(raw)
            product_id = int(name.removeprefix("qty_"))
        except ValueError as exc:
            raise CheckoutError(t("whole_number")) from exc
        if quantity < 0 or product_id < 1 or quantity > MAX_LINE:
            raise CheckoutError(t("whole_number"))
        if quantity > 0:
            quantities[product_id] = quantity
    return quantities
