from dataclasses import dataclass, field
from datetime import date

from fastapi import Request, Response

from app.i18n import t
from app.services.auth import _session_epoch, _sign, _unsign
from app.services.errors import CheckoutError
from app.services.variants import VARIANTS, offers_version

CART_COOKIE = "bf_cart"
CART_MAX_AGE = 60 * 60 * 24 * 14
MAX_LINE = 99

LineKey = tuple[int, str]


def totals_from_lines(lines: dict[LineKey, int]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for (product_id, _variant), quantity in lines.items():
        if quantity > 0:
            totals[product_id] = min(totals.get(product_id, 0) + quantity, MAX_LINE)
    return totals


def normalize_lines(lines: dict[LineKey, int], products: dict) -> dict[LineKey, int]:
    """Challah lines are regular or vegan. Other products stay a single line."""
    merged: dict[LineKey, int] = {}
    for (product_id, variant), quantity in lines.items():
        if quantity <= 0:
            continue
        product = products.get(product_id)
        if product is not None and offers_version(product):
            chosen = variant if variant in VARIANTS else "regular"
        else:
            chosen = ""
        key = (product_id, chosen)
        merged[key] = min(merged.get(key, 0) + quantity, MAX_LINE)
    return merged


@dataclass
class Cart:
    delivery_date: date | None
    quantities: dict[int, int]
    lines: dict[LineKey, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lines:
            self.quantities = totals_from_lines(self.lines)
        else:
            self.lines = {
                (product_id, ""): quantity
                for product_id, quantity in self.quantities.items()
                if quantity > 0
            }

    @property
    def loaf_count(self) -> int:
        return sum(self.quantities.values())


def empty_cart() -> Cart:
    return Cart(None, {})


def parse_qty_name(name: str) -> LineKey | None:
    if not name.startswith("qty_"):
        return None
    rest = name.removeprefix("qty_")
    variant = ""
    for candidate in VARIANTS:
        suffix = f"_{candidate}"
        if rest.endswith(suffix):
            variant = candidate
            rest = rest[: -len(suffix)]
            break
    if not rest.isdigit():
        return None
    return int(rest), variant


def _parse_items(items_part: str) -> dict[LineKey, int]:
    lines: dict[LineKey, int] = {}
    if not items_part:
        return lines
    for piece in items_part.split(","):
        product_part, eq, qty_part = piece.partition("=")
        if eq != "=" or not qty_part.isdigit():
            continue
        if "@" in product_part:
            id_part, _, variant = product_part.partition("@")
            if variant not in VARIANTS:
                continue
        else:
            id_part, variant = product_part, ""
        if not id_part.isdigit():
            continue
        amount = int(qty_part)
        if amount > 0:
            lines[(int(id_part), variant)] = min(amount, MAX_LINE)
    return lines


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
    found: list[tuple[date, dict[LineKey, int]]] = []
    # One Friday is stored as "date:id=qty". A challah version is "id@vegan=qty".
    # Older multi-Friday cookies used "date|id=qty;date|id=qty" and are folded in.
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
        lines = _parse_items(items_part)
        if lines:
            found.append((delivery, lines))
    if not found:
        return empty_cart()
    merged: dict[LineKey, int] = {}
    for _delivery, lines in found:
        for key, quantity in lines.items():
            merged[key] = min(merged.get(key, 0) + quantity, MAX_LINE)
    return Cart(found[-1][0], totals_from_lines(merged), merged)


def write_cart(response: Response, cart: Cart) -> None:
    lines = {key: qty for key, qty in cart.lines.items() if qty > 0}
    if cart.delivery_date is None or not lines:
        clear_cart(response)
        return
    parts = []
    for product_id, variant in sorted(lines):
        token = f"{product_id}@{variant}" if variant else str(product_id)
        parts.append(f"{token}={lines[(product_id, variant)]}")
    payload = f"{_session_epoch()}:{cart.delivery_date.isoformat()}:{','.join(parts)}"
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


def lines_from_pairs(pairs) -> dict[LineKey, int]:
    lines: dict[LineKey, int] = {}
    for key, value in pairs:
        parsed = parse_qty_name(str(key))
        if parsed is None:
            continue
        raw = str(value).strip()
        if raw in ("", "0"):
            continue
        try:
            quantity = int(raw)
        except ValueError as exc:
            raise CheckoutError(t("whole_number")) from exc
        product_id, variant = parsed
        if quantity < 0 or product_id < 1 or quantity > MAX_LINE:
            raise CheckoutError(t("whole_number"))
        if quantity > 0:
            lines[(product_id, variant)] = quantity
    return lines


def lines_from_form(form) -> dict[LineKey, int]:
    return lines_from_pairs(form.multi_items())


def lines_from_mapping(mapping) -> dict[LineKey, int]:
    lines: dict[LineKey, int] = {}
    for key, value in mapping.items():
        parsed = parse_qty_name(str(key))
        if parsed is None:
            continue
        raw = str(value).strip()
        if raw in ("", "0"):
            continue
        try:
            quantity = int(raw)
        except ValueError:
            continue
        product_id, variant = parsed
        if product_id >= 1 and quantity > 0:
            lines[(product_id, variant)] = min(quantity, MAX_LINE)
    return lines


def quantities_from_form(form) -> dict[int, int]:
    return totals_from_lines(lines_from_form(form))
