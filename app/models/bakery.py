import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    DELIVERED = "DELIVERED"


def _status_values(choices):
    return [item.value for item in choices]


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=True)
    name_he = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    description_he = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    image_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    ingredients = Column(Text, nullable=True)
    ingredients_en = Column(Text, nullable=True)
    ingredients_he = Column(Text, nullable=True)
    fermentation_hours = Column(Integer, default=30)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    orders = relationship("Order", back_populates="customer")
    user = relationship("User", back_populates="customer", uselist=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(40), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    is_guest = Column(Boolean, default=False, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=utcnow)

    customer = relationship("Customer", back_populates="user")



class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    order_number = Column(String(32), unique=True, nullable=False, index=True)
    status = Column(
        Enum(OrderStatus, native_enum=False, length=32, values_callable=_status_values),
        default=OrderStatus.PENDING_PAYMENT,
        nullable=False,
    )
    delivery_date = Column(DateTime, nullable=False, index=True)
    total_amount = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    payment_method = Column(String(32), nullable=True)
    payment_other = Column(String(120), nullable=True)
    payment_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")
    transaction = relationship("PaymentTransaction", back_populates="order", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    grow_transaction_id = Column(String(100), nullable=False, index=True)
    amount_charged = Column(Float, nullable=False)
    card_mask = Column(String(20), nullable=True)
    status = Column(String(50), nullable=False)
    raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    order = relationship("Order", back_populates="transaction")
