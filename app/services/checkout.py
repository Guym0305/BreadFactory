import secrets

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.bakery import Customer, Order, OrderItem, OrderStatus
from app.schemas.order import CheckoutIn, OrderCreated
from app.i18n import t
from app.services.errors import CheckoutError
from app.services.grow import create_hosted_payment
from app.services.orders import serialize_order
from app.services.slots import delivery_datetime, require_slot


def parse_checkout(data: dict) -> CheckoutIn:
    try:
        return CheckoutIn.model_validate(data)
    except ValidationError as exc:
        raise CheckoutError(_validation_message(exc)) from exc


def checkout_from_form(form) -> CheckoutIn:
    lines = []
    for key, value in form.multi_items():
        if not str(key).startswith("qty_"):
            continue
        raw = str(value).strip()
        if raw in ("", "0"):
            continue
        try:
            quantity = int(raw)
        except ValueError as exc:
            raise CheckoutError(t("whole_number")) from exc
        if quantity < 0:
            raise CheckoutError(t("whole_number"))
        try:
            product_id = int(str(key).removeprefix("qty_"))
        except ValueError as exc:
            raise CheckoutError(t("choose_from_bake")) from exc
        lines.append({"product_id": product_id, "quantity": quantity})

    return parse_checkout(
        {
            "full_name": form.get("full_name", ""),
            "phone": form.get("phone", ""),
            "email": form.get("email", ""),
            "address": form.get("address", ""),
            "notes": form.get("notes", ""),
            "delivery_date": form.get("delivery_date", ""),
            "lines": lines,
        }
    )


def create_checkout(db: Session, data: CheckoutIn) -> Order:
    slot = require_slot(db, data.delivery_date)
    chosen = _priced_lines(db, data)
    requested = sum(quantity for _, quantity in chosen)
    if requested > slot.remaining:
        if slot.remaining == 1:
            raise CheckoutError(t("one_left"))
        raise CheckoutError(t("n_left", n=slot.remaining))

    customer = db.query(Customer).filter(Customer.phone == data.phone).one_or_none()
    if customer is None:
        customer = Customer(
            full_name=data.full_name,
            phone=data.phone,
            email=data.email,
            address=data.address,
        )
        db.add(customer)
        db.flush()
    else:
        customer.full_name = data.full_name
        customer.email = data.email
        customer.address = data.address

    total = round(sum(product.price * quantity for product, quantity in chosen), 2)
    order = Order(
        customer_id=customer.id,
        order_number=_order_number(db, data.delivery_date),
        status=OrderStatus.PENDING_PAYMENT,
        delivery_date=delivery_datetime(data.delivery_date),
        total_amount=total,
        notes=data.notes,
    )
    db.add(order)
    db.flush()
    for product, quantity in chosen:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=round(product.price, 2),
            )
        )
    db.commit()
    db.refresh(order)
    db.refresh(customer)

    try:
        payment_url = create_hosted_payment(order, customer)
    except CheckoutError:
        order.status = OrderStatus.CANCELLED
        db.commit()
        raise

    order.payment_url = payment_url
    db.commit()
    db.refresh(order)
    return order


def created_payload(order: Order) -> OrderCreated:
    body = serialize_order(order).model_dump()
    body["payment_url"] = order.payment_url or ""
    return OrderCreated.model_validate(body)


def _priced_lines(db: Session, data: CheckoutIn):
    from app.models.bakery import Product

    product_ids = [line.product_id for line in data.lines]
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids), Product.is_active.is_(True))
    }
    chosen = []
    for line in data.lines:
        product = products.get(line.product_id)
        if product is None:
            raise CheckoutError(t("unavailable"))
        chosen.append((product, line.quantity))
    return chosen


def _order_number(db: Session, day) -> str:
    prefix = f"BAKE-{day.strftime('%Y%m%d')}-"
    for _ in range(8):
        candidate = f"{prefix}{secrets.randbelow(900) + 100}"
        exists = db.query(Order.id).filter(Order.order_number == candidate).first()
        if exists is None:
            return candidate
    raise CheckoutError(t("order_number"), 503)


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    message = str(error.get("msg", "Check the order and try again."))
    prefix = "Value error, "
    if message.startswith(prefix):
        message = message[len(prefix) :]
    return message
