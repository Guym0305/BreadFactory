from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.i18n import t
from app.models.bakery import Order, OrderItem, OrderStatus, utcnow
from app.services.errors import CheckoutError

BAKERY_TZ = ZoneInfo("Asia/Jerusalem")
# Israeli week opens on Sunday and closes on Saturday.
# Orders for that week close at the end of Wednesday. Delivery is Friday.
THURSDAY = 3
DELIVERY_WINDOW = "8:00–12:00"
WEEKDAYS = {
    "en": (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ),
    "he": (
        "יום שני",
        "יום שלישי",
        "יום רביעי",
        "יום חמישי",
        "יום שישי",
        "שבת",
        "יום ראשון",
    ),
}
MONTHS = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "he": (
        "ינואר",
        "פברואר",
        "מרץ",
        "אפריל",
        "מאי",
        "יוני",
        "יולי",
        "אוגוסט",
        "ספטמבר",
        "אוקטובר",
        "נובמבר",
        "דצמבר",
    ),
}


class DeliverySlot:
    def __init__(self, day: date, remaining: int, capacity: int, lang: str = "en", order_by: date | None = None):
        names = WEEKDAYS.get(lang, WEEKDAYS["en"])
        months = MONTHS.get(lang, MONTHS["en"])
        self.date = day
        self.weekday = names[day.weekday()]
        self.day = day.day
        self.month = months[day.month - 1]
        self.window = DELIVERY_WINDOW
        self.remaining = remaining
        self.capacity = capacity
        deadline = order_by or day
        self.order_by = deadline
        self.order_weekday = names[deadline.weekday()]
        self.order_day = deadline.day
        self.order_month = months[deadline.month - 1]

    @property
    def available(self) -> bool:
        return self.remaining > 0

    @property
    def label(self) -> str:
        return f"{self.weekday}, {self.day} {self.month}"


def bakery_now() -> datetime:
    return datetime.now(BAKERY_TZ)


def delivery_datetime(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 8, 0, 0)


def week_sunday(day: date) -> date:
    """Sunday that opens the Israeli week containing this date."""
    return day - timedelta(days=(day.weekday() - 6) % 7)


def coming_cycle(now: datetime | None = None) -> tuple[date, date]:
    """Wednesday order deadline and Friday delivery for the open week.

    Thursday, Friday, and Saturday close the current week, so the coming
    delivery is Friday of the following week.
    """
    current = now or bakery_now()
    sunday = week_sunday(current.date())
    if current.date().weekday() in (THURSDAY, THURSDAY + 1, THURSDAY + 2):
        sunday += timedelta(days=7)
    return sunday + timedelta(days=3), sunday + timedelta(days=5)


def cycle_for(week: str, now: datetime | None = None) -> tuple[date, date]:
    order_by, delivery = coming_cycle(now)
    if week == "next":
        return order_by + timedelta(days=7), delivery + timedelta(days=7)
    return order_by, delivery


def week_choice_for(day: date | None, now: datetime | None = None) -> str:
    if day is None:
        return "coming"
    _, coming = coming_cycle(now)
    return "next" if day != coming else "coming"


def reserved_quantities(db: Session, days: list[date]) -> dict[date, int]:
    totals = {day: 0 for day in days}
    if not days:
        return totals
    settings = get_settings()
    start = datetime.combine(min(days), time.min)
    end = datetime.combine(max(days) + timedelta(days=1), time.min)
    cutoff = utcnow() - timedelta(minutes=settings.payment_hold_minutes)
    rows = (
        db.query(Order.delivery_date, Order.status, Order.created_at, OrderItem.quantity)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.delivery_date >= start, Order.delivery_date < end)
        .filter(
            Order.status.in_(
                [OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.DELIVERED]
            )
        )
        .all()
    )
    for delivery_date, status, created_at, quantity in rows:
        day = delivery_date.date()
        if day not in totals:
            continue
        if status == OrderStatus.PENDING_PAYMENT and created_at is not None and created_at < cutoff:
            continue
        totals[day] += quantity
    return totals


def list_slots(db: Session, now: datetime | None = None, lang: str = "en", week: str = "coming") -> list[DeliverySlot]:
    settings = get_settings()
    order_by, delivery = cycle_for(week, now)
    reserved = reserved_quantities(db, [delivery])
    capacity = settings.slot_capacity
    remaining = max(capacity - reserved.get(delivery, 0), 0)
    return [DeliverySlot(delivery, remaining, capacity, lang, order_by)]


def require_slot(db: Session, day: date) -> DeliverySlot:
    now = bakery_now()
    for week in ("coming", "next"):
        for slot in list_slots(db, now, week=week):
            if slot.date == day:
                if not slot.available:
                    raise CheckoutError(t("fully_booked"))
                return slot
    raise CheckoutError(t("choose_morning"))
