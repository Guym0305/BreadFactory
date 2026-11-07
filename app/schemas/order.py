import re
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.i18n import t

PHONE_RE = re.compile(r"\+?\d{9,15}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PAYMENT_METHODS = ("bit", "paybox", "bank_transfer", "cash", "other")


class OrderLineIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=30)


class CheckoutIn(BaseModel):
    full_name: str
    phone: str
    email: str
    address: str
    notes: str | None = None
    payment_method: str
    payment_other: str | None = None
    delivery_date: date
    lines: list[OrderLineIn]

    @field_validator("full_name", "address")
    @classmethod
    def required_text(cls, value: str, info) -> str:
        cleaned = value.strip()
        limit = 100 if info.field_name == "full_name" else 500
        if not cleaned:
            raise ValueError(t("enter_name") if info.field_name == "full_name" else t("enter_address"))
        if len(cleaned) > limit:
            raise ValueError(t("name_long") if info.field_name == "full_name" else t("address_long"))
        return cleaned

    @field_validator("phone")
    @classmethod
    def phone_number(cls, value: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", value.strip())
        if not PHONE_RE.fullmatch(cleaned):
            raise ValueError(t("phone"))
        return cleaned

    @field_validator("email")
    @classmethod
    def email_address(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if len(cleaned) > 100 or not EMAIL_RE.fullmatch(cleaned):
            raise ValueError(t("email"))
        return cleaned

    @field_validator("notes")
    @classmethod
    def optional_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 1000:
            raise ValueError(t("notes_long"))
        return cleaned

    @field_validator("payment_method")
    @classmethod
    def known_payment_method(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in PAYMENT_METHODS:
            raise ValueError(t("choose_payment"))
        return cleaned

    @field_validator("payment_other")
    @classmethod
    def optional_payment_other(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 120:
            raise ValueError(t("payment_other_long"))
        return cleaned

    @model_validator(mode="after")
    def at_least_one_loaf(self):
        if not self.lines:
            raise ValueError(t("choose_loaf"))
        if self.payment_method == "other" and not self.payment_other:
            raise ValueError(t("enter_payment_other"))
        if self.payment_method != "other":
            self.payment_other = None
        return self


class OrderLineOut(BaseModel):
    product_name: str
    quantity: int
    unit_price: float


class OrderStatusOut(BaseModel):
    order_number: str
    status: str
    delivery_date: datetime
    total_amount: float
    payment_method: str | None = None
    payment_other: str | None = None
    lines: list[OrderLineOut]


class OrderCreated(OrderStatusOut):
    payment_url: str = ""
