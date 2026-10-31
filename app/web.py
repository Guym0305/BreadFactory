from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.i18n import get_lang, resolve_lang, set_lang, t
from app.models.bakery import OrderStatus, Product
from app.security import assert_same_origin
from app.services.checkout import checkout_from_form, create_checkout
from app.services.errors import CheckoutError
from app.services.orders import get_order
from app.services.payments import apply_webhook
from app.services.slots import list_slots, week_choice_for
from app.templating import redirect_path, render

router = APIRouter(tags=["pages"])


def _status_value(order) -> str:
    status = order.status
    return status.value if isinstance(status, OrderStatus) else str(status)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _saved_form(form) -> dict[str, str]:
    saved: dict[str, str] = {}
    for key in ("full_name", "phone", "email", "address", "notes", "delivery_date", "lang"):
        value = form.get(key)
        if value is not None:
            saved[key] = str(value)
    for key, value in form.multi_items():
        if str(key).startswith("qty_"):
            saved[str(key)] = str(value)
    return saved


def _use_lang(request: Request, posted: str | None = None) -> str:
    if posted in ("he", "en"):
        return set_lang(posted)
    return resolve_lang(request)


def _render_home(
    request: Request,
    db: Session,
    *,
    selected: date | None = None,
    error: str | None = None,
    saved: dict | None = None,
    status_code: int = 200,
    week: str = "coming",
):
    lang = get_lang()
    if week != "next":
        week = "coming"
    slots = list_slots(db, lang=lang, week=week)
    slot = slots[0] if slots else None
    if selected is not None and slot is not None and selected != slot.date and error is None:
        error = t("choose_morning")
    if slot is not None and not slot.available and error is None:
        error = t("fully_booked")
    show_bake = slot is not None and slot.available
    products = []
    if show_bake:
        products = db.query(Product).filter(Product.is_active.is_(True)).order_by(Product.id).all()
    context = {
        "slots": slots,
        "products": products,
        "slot": slot if show_bake else None,
        "error": error,
        "saved": saved or {},
        "lang": lang,
        "week": week,
    }
    return render(request, "index.html", context, status_code=status_code)


@router.get("/")
def home(
    request: Request,
    delivery_date: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    resolve_lang(request)
    selected = _parse_date(delivery_date)
    week = "next" if request.query_params.get("week") == "next" else "coming"
    error = None
    if delivery_date and selected is None:
        error = t("choose_morning")
    return _render_home(request, db, selected=selected, error=error, week=week)


@router.post("/checkout")
async def start_checkout(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    saved = _saved_form(form)
    _use_lang(request, saved.get("lang"))
    try:
        assert_same_origin(request)
        order = create_checkout(db, checkout_from_form(form))
    except CheckoutError as exc:
        return _render_home(
            request,
            db,
            selected=_parse_date(saved.get("delivery_date")),
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            week=week_choice_for(_parse_date(saved.get("delivery_date"))),
        )
    return RedirectResponse(redirect_path(f"/checkout/{order.order_number}"), status_code=303)


@router.get("/checkout/{order_number}")
def checkout_page(request: Request, order_number: str, db: Session = Depends(get_db)):
    resolve_lang(request)
    order = get_order(db, order_number)
    if order is None:
        raise HTTPException(status_code=404, detail=t("order_not_found"))
    status = _status_value(order)
    if status == OrderStatus.PAID.value:
        return RedirectResponse(redirect_path(f"/order-success?order_id={order.order_number}"), status_code=302)
    if status == OrderStatus.CANCELLED.value:
        return RedirectResponse(redirect_path(f"/order-failed?order_id={order.order_number}"), status_code=302)
    if not order.payment_url:
        raise HTTPException(status_code=502, detail=t("payment_start"))
    return render(request, "checkout.html", {"order": order, "status": status})


@router.get("/order-success")
def order_success(request: Request, order_id: str = "", db: Session = Depends(get_db)):
    resolve_lang(request)
    order = get_order(db, order_id) if order_id else None
    if order is not None and _status_value(order) == OrderStatus.CANCELLED.value:
        return RedirectResponse(redirect_path(f"/order-failed?order_id={order.order_number}"), status_code=302)
    status = _status_value(order) if order is not None else ""
    return render(request, "order_success.html", {"order": order, "status": status})


@router.get("/order-failed")
def order_failed(request: Request, order_id: str = "", db: Session = Depends(get_db)):
    resolve_lang(request)
    order = get_order(db, order_id) if order_id else None
    status = _status_value(order) if order is not None else ""
    return render(request, "order_failed.html", {"order": order, "status": status})


@router.get("/pay/mock/{order_number}")
def mock_payment(request: Request, order_number: str, db: Session = Depends(get_db)):
    resolve_lang(request)
    if get_settings().grow_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    order = get_order(db, order_number)
    if order is None:
        raise HTTPException(status_code=404, detail=t("order_not_found"))
    status = _status_value(order)
    if status == OrderStatus.PAID.value:
        return RedirectResponse(redirect_path(f"/order-success?order_id={order.order_number}"), status_code=302)
    if status == OrderStatus.CANCELLED.value:
        return RedirectResponse(redirect_path(f"/order-failed?order_id={order.order_number}"), status_code=302)
    return render(request, "mock_payment.html", {"order": order})


@router.post("/pay/mock/{order_number}/complete")
async def complete_mock(request: Request, order_number: str, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    if get_settings().grow_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        assert_same_origin(request)
        order = get_order(db, order_number)
        if order is None:
            raise CheckoutError(t("order_not_found"), 404)
        if _status_value(order) != OrderStatus.PAID.value:
            apply_webhook(
                db,
                {
                    "order_number": order.order_number,
                    "grow_transaction_id": f"MOCK-{order.order_number}",
                    "status": "SUCCESS",
                    "amount": round(order.total_amount, 2),
                    "card_mask": "****",
                    "raw": {"source": "development-stand-in"},
                },
            )
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return RedirectResponse(redirect_path(f"/order-success?order_id={order_number}"), status_code=303)
