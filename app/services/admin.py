from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session, joinedload

from app.i18n import t
from app.models.bakery import Order, OrderItem, OrderStatus, Product, User
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


def update_order(
    db: Session,
    order_id: int,
    *,
    status: str,
    notes: str,
    payment_method: str,
    payment_other: str,
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
    db.commit()
    db.refresh(order)
    return order


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


def reset_user_password(db: Session, user_id: int, password: str) -> User:
    user = db.query(User).options(joinedload(User.customer)).filter(User.id == user_id).one_or_none()
    if user is None:
        raise CheckoutError(t("admin_user_missing"), status_code=404)
    if user.is_guest:
        raise CheckoutError(t("admin_guest_password"))
    if len(password) < 6 or len(password) > 100:
        raise CheckoutError(t("password_invalid"))
    user.password_hash = hash_password(password)
    db.commit()
    db.refresh(user)
    return user


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
