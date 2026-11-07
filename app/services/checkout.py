import secrets

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.bakery import Customer, Order, OrderItem, OrderStatus, User
from app.schemas.order import CheckoutIn, OrderCreated
from app.i18n import t
from app.services.errors import CheckoutError
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
            "payment_method": form.get("payment_method", ""),
            "payment_other": form.get("payment_other", ""),
            "delivery_date": form.get("delivery_date", ""),
            "lines": lines,
        }
    )


def create_checkout(db: Session, data: CheckoutIn, user: User | None = None) -> Order:
    slot = require_slot(db, data.delivery_date)
    chosen = _priced_lines(db, data)
    requested = sum(quantity for _, quantity in chosen)
    if requested > slot.remaining:
        if slot.remaining == 1:
            raise CheckoutError(t("one_left"))
        raise CheckoutError(t("n_left", n=slot.remaining))

    if user is not None:
        customer = db.query(Customer).filter(Customer.id == user.customer_id).one_or_none()
        if customer is None:
            raise CheckoutError(t("login_required"), 401)
        customer.full_name = data.full_name
        customer.phone = data.phone
        customer.email = data.email
        customer.address = data.address
    else:
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
        status=OrderStatus.PAID,
        delivery_date=delivery_datetime(data.delivery_date),
        total_amount=total,
        notes=data.notes,
        payment_method=data.payment_method,
        payment_other=data.payment_other,
        payment_url=None,
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
    return order


def created_payload(order: Order) -> OrderCreated:
    body = serialize_order(order).model_dump()
    body["payment_url"] = ""
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
