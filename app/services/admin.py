from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.i18n import t
from app.models.bakery import Customer, Order, OrderItem, OrderStatus, Product, User
from app.services.auth import hash_password
from app.services.errors import CheckoutError
from app.services.slots import cycle_for


EDITABLE_ORDER_STATUSES = {
    OrderStatus.PENDING_PAYMENT.value,
    OrderStatus.PAID.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.DELIVERED.value,
}


def list_orders(db: Session, *, delivery: date | None = None, limit: int = 100) -> list[Order]:
    query = (
        db.query(Order)
        .options(joinedload(Order.customer), joinedload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.delivery_date.desc(), Order.id.desc())
    )
    if delivery is not None:
        start = datetime.combine(delivery, time.min)
        end = datetime.combine(delivery + timedelta(days=1), time.min)
        query = query.filter(Order.delivery_date >= start, Order.delivery_date < end)
    return query.limit(limit).all()


def get_admin_order(db: Session, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(joinedload(Order.customer), joinedload(Order.items).joinedload(OrderItem.product))
        .filter(Order.id == order_id)
        .one_or_none()
    )
    if order is None:
        raise CheckoutError(t("order_not_found"), status_code=404)
    return order


def _parse_money(raw: str) -> float:
    try:
        amount = float(raw)
    except ValueError as exc:
        raise CheckoutError(t("admin_bad_price")) from exc
    if amount < 0 or amount > 10_000:
        raise CheckoutError(t("admin_bad_price"))
    return amount


def _parse_quantity(raw: str) -> int:
    try:
        quantity = int(str(raw).strip())
    except ValueError as exc:
        raise CheckoutError(t("whole_number")) from exc
    if quantity < 1 or quantity > 99:
        raise CheckoutError(t("whole_number"))
    return quantity


def _apply_order_lines(db: Session, order: Order, lines: list[dict[str, Any]]) -> None:
    """Replace order items from admin form rows and refresh total_amount."""
    existing = {item.id: item for item in order.items}
    keep_ids: set[int] = set()
    total = 0.0
    for row in lines:
        if row.get("remove"):
            continue
        product_id = int(row["product_id"])
        product = db.query(Product).filter(Product.id == product_id).one_or_none()
        if product is None:
            raise CheckoutError(t("choose_from_bake"))
        quantity = _parse_quantity(str(row["quantity"]))
        unit_price = _parse_money(str(row["unit_price"]))
        item_id = row.get("id")
        if item_id:
            item = existing.get(int(item_id))
            if item is None or item.order_id != order.id:
                raise CheckoutError(t("admin_bad_line"))
            item.product_id = product_id
            item.quantity = quantity
            item.unit_price = unit_price
            keep_ids.add(item.id)
        else:
            item = OrderItem(
                order_id=order.id,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
            )
            db.add(item)
            db.flush()
            keep_ids.add(item.id)
        total += quantity * unit_price
    if not keep_ids or total <= 0:
        raise CheckoutError(t("choose_loaf"))
    for item_id, item in existing.items():
        if item_id not in keep_ids:
            db.delete(item)
    order.total_amount = round(total, 2)


def update_order(
    db: Session,
    order_id: int,
    *,
    status: str,
    notes: str,
    payment_method: str,
    payment_other: str,
    lines: list[dict[str, Any]] | None = None,
) -> Order:
    order = get_admin_order(db, order_id)
    cleaned_status = status.strip().upper()
    if cleaned_status not in EDITABLE_ORDER_STATUSES:
        raise CheckoutError(t("admin_bad_status"))
    order.status = OrderStatus(cleaned_status)
    order.notes = notes.strip() or None
    method = payment_method.strip().lower()
    order.payment_method = method or None
    other = payment_other.strip()
    if method == "other":
        if not other:
            raise CheckoutError(t("enter_payment_other"))
        if len(other) > 120:
            raise CheckoutError(t("payment_other_long"))
        order.payment_other = other
    else:
        order.payment_other = None
    if lines is not None:
        _apply_order_lines(db, order, lines)
    db.commit()
    return get_admin_order(db, order.id)


def list_products(db: Session) -> list[Product]:
    return db.query(Product).order_by(Product.id).all()


def get_admin_product(db: Session, product_id: int) -> Product:
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if product is None:
        raise CheckoutError(t("admin_product_missing"), status_code=404)
    return product


def update_product(
    db: Session,
    product_id: int,
    *,
    name_en: str,
    name_he: str,
    description_en: str,
    description_he: str,
    ingredients_en: str,
    ingredients_he: str,
    price: str,
    fermentation_hours: str,
    image_url: str,
    is_active: bool,
) -> Product:
    product = get_admin_product(db, product_id)
    cleaned_en = name_en.strip()
    cleaned_he = name_he.strip()
    if not cleaned_en and not cleaned_he:
        raise CheckoutError(t("admin_product_name"))
    try:
        amount = float(price)
    except ValueError as exc:
        raise CheckoutError(t("admin_bad_price")) from exc
    if amount < 0 or amount > 10_000:
        raise CheckoutError(t("admin_bad_price"))
    try:
        hours = int(fermentation_hours.strip() or "0")
    except ValueError as exc:
        raise CheckoutError(t("admin_bad_hours")) from exc
    if hours < 0 or hours > 240:
        raise CheckoutError(t("admin_bad_hours"))

    product.name_en = cleaned_en or None
    product.name_he = cleaned_he or None
    product.name = cleaned_en or cleaned_he
    product.description_en = description_en.strip() or None
    product.description_he = description_he.strip() or None
    product.description = product.description_en or product.description_he
    product.ingredients_en = ingredients_en.strip() or None
    product.ingredients_he = ingredients_he.strip() or None
    product.ingredients = product.ingredients_en or product.ingredients_he
    product.price = amount
    product.fermentation_hours = hours
    product.image_url = image_url.strip() or None
    product.is_active = is_active
    db.commit()
    db.refresh(product)
    return product


def list_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .options(joinedload(User.customer))
        .order_by(User.is_admin.desc(), User.username)
        .all()
    )


def _get_user(db: Session, user_id: int) -> User:
    user = db.query(User).options(joinedload(User.customer)).filter(User.id == user_id).one_or_none()
    if user is None:
        raise CheckoutError(t("admin_user_missing"), status_code=404)
    return user


def _admin_count(db: Session) -> int:
    return db.query(User).filter(User.is_admin.is_(True)).count()


def reset_user_password(db: Session, user_id: int, password: str) -> User:
    user = _get_user(db, user_id)
    if user.is_guest:
        raise CheckoutError(t("admin_guest_password"))
    if len(password) < 6 or len(password) > 100:
        raise CheckoutError(t("password_invalid"))
    user.password_hash = hash_password(password)
    db.commit()
    db.refresh(user)
    return user


def set_user_admin(db: Session, user_id: int, *, make_admin: bool, actor: User) -> User:
    user = _get_user(db, user_id)
    if user.is_guest and make_admin:
        raise CheckoutError(t("admin_guest_admin"))
    if user.is_admin and not make_admin:
        if user.id == actor.id:
            raise CheckoutError(t("admin_cannot_demote_self"))
        if _admin_count(db) <= 1:
            raise CheckoutError(t("admin_last_admin"))
    user.is_admin = make_admin
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int, *, actor: User) -> str:
    user = _get_user(db, user_id)
    if user.id == actor.id:
        raise CheckoutError(t("admin_cannot_delete_self"))
    if user.is_admin and _admin_count(db) <= 1:
        raise CheckoutError(t("admin_last_admin"))
    username = user.username
    customer = user.customer
    customer_id = user.customer_id
    db.delete(user)
    db.flush()
    if customer_id is not None:
        order_count = db.query(Order.id).filter(Order.customer_id == customer_id).count()
        if order_count == 0 and customer is not None:
            db.delete(customer)
    db.commit()
    return username


def delivery_orders(db: Session, delivery: date) -> list[Order]:
    return list_orders(db, delivery=delivery, limit=500)


def delivery_dates(db: Session) -> list[date]:
    coming = cycle_for("coming")[1]
    nxt = cycle_for("next")[1]
    dates = [coming, nxt]
    rows = db.query(Order.delivery_date).distinct().all()
    for (value,) in rows:
        day = value.date() if isinstance(value, datetime) else value
        if day not in dates:
            dates.append(day)
    return sorted(dates)


def product_label(product: Product | None, lang: str) -> str:
    if product is None:
        return "—"
    if lang == "he":
        return product.name_he or product.name_en or product.name
    return product.name_en or product.name_he or product.name
