from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.i18n import t
from app.models.bakery import Order, OrderItem, OrderStatus, Product, utcnow
from app.services.errors import CheckoutError

BAKERY_TZ = ZoneInfo("Asia/Jerusalem")
# Israeli week opens on Sunday and closes on Saturday.
# Orders for this Friday close on Wednesday at 20:00. Delivery is Friday.
WEDNESDAY = 2
THURSDAY = 3
ORDER_CUTOFF = time(20, 0)
ORDER_CUTOFF_LABEL = "20:00"
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
        self.order_cutoff = ORDER_CUTOFF_LABEL

    @property
    def available(self) -> bool:
        return self.remaining > 0

    @property
    def label(self) -> str:
        return f"{self.weekday}, {self.day} {self.month}"


def bakery_now() -> datetime:
    return datetime.now(BAKERY_TZ)


def _as_bakery_time(now: datetime | None) -> datetime:
    current = now or bakery_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=BAKERY_TZ)
    return current.astimezone(BAKERY_TZ)


def delivery_datetime(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 8, 0, 0)


def week_sunday(day: date) -> date:
    """Sunday that opens the Israeli week containing this date."""
    return day - timedelta(days=(day.weekday() - 6) % 7)


def coming_cycle(now: datetime | None = None) -> tuple[date, date]:
    """Wednesday 20:00 order deadline and Friday delivery for the open week.

    From Wednesday at 20:00 through Saturday, this Friday is closed, so the
    coming delivery is Friday of the following week.
    """
    current = _as_bakery_time(now)
    sunday = week_sunday(current.date())
    weekday = current.weekday()
    past_cutoff = weekday == WEDNESDAY and current.time() >= ORDER_CUTOFF
    if past_cutoff or weekday in (THURSDAY, THURSDAY + 1, THURSDAY + 2):
        sunday += timedelta(days=7)
    return sunday + timedelta(days=3), sunday + timedelta(days=5)


def this_weeks_friday(now: datetime | None = None) -> date:
    current = _as_bakery_time(now)
    return week_sunday(current.date()) + timedelta(days=5)


def ordering_closed(now: datetime | None = None) -> bool:
    """True from Wednesday at 20:00, once this Friday can no longer be ordered."""
    _, coming = coming_cycle(now)
    return coming != this_weeks_friday(now)


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


def _reservation_rows(db: Session, days: list[date]):
    if not days:
        return []
    settings = get_settings()
    start = datetime.combine(min(days), time.min)
    end = datetime.combine(max(days) + timedelta(days=1), time.min)
    cutoff = utcnow() - timedelta(minutes=settings.payment_hold_minutes)
    rows = (
        db.query(
            Order.delivery_date,
            Order.status,
            Order.created_at,
            OrderItem.product_id,
            OrderItem.quantity,
            Product.counts_toward_capacity,
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(Order.delivery_date >= start, Order.delivery_date < end)
        .filter(
            Order.status.in_(
                [OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.DELIVERED]
            )
        )
        .all()
    )
    kept = []
    for delivery_date, status, created_at, product_id, quantity, counts in rows:
        day = delivery_date.date()
        if day not in days:
            continue
        if status == OrderStatus.PENDING_PAYMENT and created_at is not None and created_at < cutoff:
            continue
        kept.append((day, product_id, quantity, bool(counts)))
    return kept


def reserved_quantities(db: Session, days: list[date]) -> dict[date, int]:
    totals = {day: 0 for day in days}
    for day, _product_id, quantity, counts in _reservation_rows(db, days):
        if counts:
            totals[day] += quantity
    return totals


def reserved_product_quantities(db: Session, day: date) -> dict[int, int]:
    totals: dict[int, int] = {}
    for _day, product_id, quantity, _counts in _reservation_rows(db, [day]):
        totals[product_id] = totals.get(product_id, 0) + quantity
    return totals


def assert_cart_fits(db: Session, day: date | None, quantities: dict[int, int]) -> DeliverySlot:
    """Check a basket against the general bake limit and each product limit."""
    slot = find_slot(db, day)
    if not quantities:
        return slot
    products = {
        product.id: product
        for product in db.query(Product).filter(
            Product.id.in_(list(quantities)),
            Product.is_active.is_(True),
        )
    }
    if set(quantities) - set(products):
        raise CheckoutError(t("unavailable"))
    taken = reserved_product_quantities(db, slot.date)
    counted = 0
    for product_id, quantity in quantities.items():
        product = products[product_id]
        if product.counts_toward_capacity:
            counted += quantity
        limit = product.delivery_limit
        if limit is None:
            continue
        left = limit - taken.get(product_id, 0)
        if quantity > left:
            if left <= 0:
                raise CheckoutError(t("product_sold_out"))
            if left == 1:
                raise CheckoutError(t("product_one_left"))
            raise CheckoutError(t("product_n_left", n=left))
    if counted > slot.remaining:
        if slot.remaining <= 0:
            raise CheckoutError(t("fully_booked"))
        if slot.remaining == 1:
            raise CheckoutError(t("one_left"))
        raise CheckoutError(t("n_left", n=slot.remaining))
    return slot


def list_slots(db: Session, now: datetime | None = None, lang: str = "en", week: str = "coming") -> list[DeliverySlot]:
    settings = get_settings()
    order_by, delivery = cycle_for(week, now)
    reserved = reserved_quantities(db, [delivery])
    capacity = settings.slot_capacity
    remaining = max(capacity - reserved.get(delivery, 0), 0)
    return [DeliverySlot(delivery, remaining, capacity, lang, order_by)]


def find_slot(db: Session, day: date | None) -> DeliverySlot:
    if day is None:
        raise CheckoutError(t("choose_morning"))
    now = bakery_now()
    for week in ("coming", "next"):
        for slot in list_slots(db, now, week=week):
            if slot.date == day:
                return slot
    raise CheckoutError(t("choose_morning"))


def require_slot(db: Session, day: date) -> DeliverySlot:
    slot = find_slot(db, day)
    if not slot.available:
        raise CheckoutError(t("fully_booked"))
    return slot
