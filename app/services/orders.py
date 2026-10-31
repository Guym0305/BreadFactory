from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.i18n import get_lang
from app.models.bakery import Order, OrderItem, OrderStatus
from app.schemas.order import OrderLineOut, OrderStatusOut


def get_order(db: Session, order_number: str) -> Order | None:
    statement = (
        select(Order)
        .options(joinedload(Order.customer), joinedload(Order.items).joinedload(OrderItem.product))
        .where(Order.order_number == order_number)
    )
    return db.execute(statement).unique().scalar_one_or_none()


def _product_name(product) -> str:
    if product is None:
        return "לחם" if get_lang() == "he" else "Loaf"
    if get_lang() == "he":
        return product.name_he or product.name
    return product.name_en or product.name


def serialize_order(order: Order) -> OrderStatusOut:
    status = order.status.value if isinstance(order.status, OrderStatus) else str(order.status)
    return OrderStatusOut(
        order_number=order.order_number,
        status=status,
        delivery_date=order.delivery_date,
        total_amount=order.total_amount,
        lines=[
            OrderLineOut(
                product_name=_product_name(item.product),
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in order.items
        ],
    )
