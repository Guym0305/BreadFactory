from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.i18n import get_lang, resolve_lang, set_lang, t
from app.models.bakery import OrderStatus, Product
from app.security import assert_same_origin
from app.services.admin import (
    delete_user,
    delivery_dates,
    delivery_orders,
    get_admin_order,
    get_admin_product,
    list_orders,
    list_products,
    list_users,
    product_label,
    reset_user_password,
    set_user_admin,
    update_order,
    update_product,
)
from app.services.auth import (
    authenticate_user,
    clear_session,
    create_guest_user,
    current_user,
    customer_form_defaults,
    login_display_name,
    register_user,
    set_login_welcome,
    set_session_user,
)
from app.services.checkout import checkout_from_form, create_checkout
from app.services.errors import CheckoutError
from app.services.orders import get_order
from app.services.payments import apply_webhook
from app.services.slots import cycle_for, list_slots, week_choice_for
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
    for key in (
        "full_name",
        "phone",
        "email",
        "address",
        "notes",
        "payment_method",
        "payment_other",
        "delivery_date",
        "lang",
    ):
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


def _next_path(raw: str | None) -> str:
    if not raw:
        return "/"
    path = raw.strip()
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


def _resolve_next_path(user, raw: str | None) -> str:
    next_path = _next_path(raw)
    if user is not None and user.is_admin and next_path in ("/", ""):
        return "/admin"
    return next_path


def _login_redirect(request: Request, next_path: str = "/") -> RedirectResponse:
    lang = get_lang()
    target = quote(_next_path(next_path), safe="/?&=%")
    return RedirectResponse(redirect_path(f"/login?next={target}", lang), status_code=303)


def _require_admin(request: Request, db: Session):
    user = current_user(request, db)
    if user is None:
        return None, _login_redirect(request, request.url.path)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail=t("admin_only"))
    return user, None


def _render_home(
    request: Request,
    db: Session,
    *,
    selected: date | None = None,
    error: str | None = None,
    saved: dict | None = None,
    status_code: int = 200,
    week: str = "coming",
    user=None,
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
    form_saved = dict(saved or {})
    if user is not None and user.customer is not None:
        for key, value in customer_form_defaults(user.customer).items():
            form_saved.setdefault(key, value)
    context = {
        "slots": slots,
        "products": products,
        "slot": slot if show_bake else None,
        "error": error,
        "saved": form_saved,
        "lang": lang,
        "week": week,
        "current_user": user,
    }
    return render(request, "index.html", context, status_code=status_code)


@router.get("/about")
def about_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    return render(
        request,
        "about.html",
        {
            "current_user": current_user(request, db),
        },
    )


@router.get("/login")
def login_page(
    request: Request,
    next: str = "/",
    db: Session = Depends(get_db),
):
    resolve_lang(request)
    user = current_user(request, db)
    if user is not None:
        return RedirectResponse(redirect_path(_resolve_next_path(user, next)), status_code=302)
    return render(
        request,
        "login.html",
        {
            "next": _next_path(next),
            "error": None,
            "mode": "login",
            "saved_username": "",
            "saved_register": {},
            "current_user": None,
        },
    )


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    requested_next = _next_path(str(form.get("next") or "/"))
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    try:
        assert_same_origin(request)
        user = authenticate_user(db, username, password)
    except CheckoutError as exc:
        return render(
            request,
            "login.html",
            {
                "next": requested_next,
                "error": exc.message or t("login_failed"),
                "mode": "login",
                "saved_username": username.strip(),
                "saved_register": {},
                "current_user": None,
            },
            status_code=exc.status_code if exc.status_code >= 400 else 400,
        )
    response = RedirectResponse(redirect_path(_resolve_next_path(user, requested_next)), status_code=303)
    set_session_user(response, user.id)
    set_login_welcome(response, login_display_name(user))
    return response


@router.post("/register")
async def register_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    next_path = _next_path(str(form.get("next") or "/"))
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    saved_register = {
        "username": username.strip(),
        "full_name": str(form.get("full_name") or ""),
        "phone": str(form.get("phone") or ""),
        "email": str(form.get("email") or ""),
        "address": str(form.get("address") or ""),
    }
    try:
        assert_same_origin(request)
        user = register_user(
            db,
            username,
            password,
            full_name=saved_register["full_name"],
            phone=saved_register["phone"],
            email=saved_register["email"],
            address=saved_register["address"],
        )
    except CheckoutError as exc:
        return render(
            request,
            "login.html",
            {
                "next": next_path,
                "error": exc.message,
                "mode": "register",
                "saved_username": saved_register["username"],
                "saved_register": saved_register,
                "current_user": None,
            },
            status_code=exc.status_code,
        )
    response = RedirectResponse(redirect_path(next_path), status_code=303)
    set_session_user(response, user.id)
    return response


@router.post("/guest")
async def guest_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    next_path = _next_path(str(form.get("next") or "/"))
    try:
        assert_same_origin(request)
        user = create_guest_user(db)
    except CheckoutError as exc:
        return render(
            request,
            "login.html",
            {
                "next": next_path,
                "error": exc.message,
                "mode": "login",
                "saved_username": "",
                "saved_register": {},
                "current_user": None,
            },
            status_code=exc.status_code,
        )
    response = RedirectResponse(redirect_path(next_path), status_code=303)
    set_session_user(response, user.id)
    return response


@router.post("/logout")
async def logout_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    try:
        assert_same_origin(request)
    except CheckoutError:
        pass
    response = RedirectResponse(redirect_path("/login"), status_code=303)
    clear_session(response)
    return response


@router.get("/admin")
def admin_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    return render(
        request,
        "admin.html",
        {
            "current_user": user,
        },
    )


@router.get("/admin/orders")
def admin_orders_page(
    request: Request,
    db: Session = Depends(get_db),
    delivery_date: str | None = Query(default=None, alias="date"),
):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    selected = _parse_date(delivery_date)
    orders = list_orders(db, delivery=selected)
    return render(
        request,
        "admin_orders.html",
        {
            "current_user": user,
            "orders": orders,
            "selected_date": selected.isoformat() if selected else "",
            "dates": delivery_dates(db),
            "notice": request.query_params.get("saved") == "1",
            "error": None,
            "product_label": product_label,
            "status_value": _status_value,
        },
    )


def _parse_order_lines(form) -> list[dict]:
    item_ids = [str(value) for value in form.getlist("item_id")]
    product_ids = [str(value) for value in form.getlist("item_product_id")]
    quantities = [str(value) for value in form.getlist("item_quantity")]
    prices = [str(value) for value in form.getlist("item_unit_price")]
    remove_ids = {str(value) for value in form.getlist("item_remove")}
    if not (len(item_ids) == len(product_ids) == len(quantities) == len(prices)):
        raise CheckoutError(t("admin_bad_line"))
    lines: list[dict] = []
    for item_id, product_id, quantity, price in zip(item_ids, product_ids, quantities, prices):
        lines.append(
            {
                "id": int(item_id) if item_id.isdigit() else None,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": price,
                "remove": item_id in remove_ids,
            }
        )
    new_product = str(form.get("new_product_id") or "").strip()
    new_quantity = str(form.get("new_quantity") or "").strip()
    new_price = str(form.get("new_unit_price") or "").strip()
    if new_product:
        try:
            product_id = int(new_product)
        except ValueError as exc:
            raise CheckoutError(t("choose_from_bake")) from exc
        lines.append(
            {
                "id": None,
                "product_id": product_id,
                "quantity": new_quantity or "1",
                "unit_price": new_price,
                "remove": False,
            }
        )
    return lines


@router.get("/admin/orders/{order_id}")
def admin_order_edit_page(request: Request, order_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    try:
        order = get_admin_order(db, order_id)
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return render(
        request,
        "admin_order_edit.html",
        {
            "current_user": user,
            "order": order,
            "products": list_products(db),
            "statuses": list(OrderStatus),
            "error": None,
            "notice": request.query_params.get("saved") == "1",
            "product_label": product_label,
            "status_value": _status_value,
            "saved": {},
        },
    )


@router.post("/admin/orders/{order_id}")
async def admin_order_save(request: Request, order_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    form = await request.form()
    _use_lang(request, str(form.get("lang") or ""))
    try:
        assert_same_origin(request)
        lines = _parse_order_lines(form)
        # Fill missing new line price from product catalog.
        for row in lines:
            if row.get("id") is None and not str(row.get("unit_price") or "").strip():
                product = get_admin_product(db, int(row["product_id"]))
                row["unit_price"] = str(product.price)
        update_order(
            db,
            order_id,
            status=str(form.get("status") or ""),
            notes=str(form.get("notes") or ""),
            payment_method=str(form.get("payment_method") or ""),
            payment_other=str(form.get("payment_other") or ""),
            lines=lines,
        )
    except CheckoutError as exc:
        order = get_admin_order(db, order_id)
        return render(
            request,
            "admin_order_edit.html",
            {
                "current_user": user,
                "order": order,
                "products": list_products(db),
                "statuses": list(OrderStatus),
                "error": str(exc),
                "notice": False,
                "product_label": product_label,
                "status_value": _status_value,
                "saved": {
                    "status": str(form.get("status") or ""),
                    "notes": str(form.get("notes") or ""),
                    "payment_method": str(form.get("payment_method") or ""),
                    "payment_other": str(form.get("payment_other") or ""),
                },
            },
            status_code=exc.status_code if exc.status_code < 500 else 400,
        )
    return RedirectResponse(
        redirect_path(f"/admin/orders/{order_id}?saved=1"),
        status_code=303,
    )


@router.get("/admin/update-content")
def admin_products_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    return render(
        request,
        "admin_products.html",
        {
            "current_user": user,
            "products": list_products(db),
            "product_label": product_label,
            "notice": request.query_params.get("saved") == "1",
        },
    )


@router.get("/admin/products/{product_id}")
def admin_product_edit_page(request: Request, product_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    try:
        product = get_admin_product(db, product_id)
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return render(
        request,
        "admin_product_edit.html",
        {
            "current_user": user,
            "product": product,
            "error": None,
            "notice": request.query_params.get("saved") == "1",
            "saved": {},
        },
    )


@router.post("/admin/products/{product_id}")
async def admin_product_save(request: Request, product_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    form = await request.form()
    _use_lang(request, str(form.get("lang") or ""))
    saved = {
        "name_en": str(form.get("name_en") or ""),
        "name_he": str(form.get("name_he") or ""),
        "description_en": str(form.get("description_en") or ""),
        "description_he": str(form.get("description_he") or ""),
        "ingredients_en": str(form.get("ingredients_en") or ""),
        "ingredients_he": str(form.get("ingredients_he") or ""),
        "price": str(form.get("price") or ""),
        "fermentation_hours": str(form.get("fermentation_hours") or ""),
        "image_url": str(form.get("image_url") or ""),
        "is_active": str(form.get("is_active") or "") == "1",
    }
    try:
        assert_same_origin(request)
        update_product(db, product_id, **saved)
    except CheckoutError as exc:
        product = get_admin_product(db, product_id)
        return render(
            request,
            "admin_product_edit.html",
            {
                "current_user": user,
                "product": product,
                "error": str(exc),
                "notice": False,
                "saved": saved,
            },
            status_code=400,
        )
    return RedirectResponse(
        redirect_path(f"/admin/products/{product_id}?saved=1"),
        status_code=303,
    )


def _users_page(request: Request, user, db: Session, *, error=None, notice=None, notice_user=""):
    return render(
        request,
        "admin_users.html",
        {
            "current_user": user,
            "users": list_users(db),
            "error": error,
            "notice": notice,
            "notice_user": notice_user,
        },
        status_code=400 if error else 200,
    )


@router.get("/admin/change-password")
def admin_users_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    notice = None
    if request.query_params.get("saved") == "1":
        notice = "password"
    elif request.query_params.get("role") == "1":
        notice = "role"
    elif request.query_params.get("deleted") == "1":
        notice = "deleted"
    return _users_page(
        request,
        user,
        db,
        notice=notice,
        notice_user=request.query_params.get("user") or "",
    )


@router.post("/admin/users/{user_id}/password")
async def admin_user_password_save(request: Request, user_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    form = await request.form()
    _use_lang(request, str(form.get("lang") or ""))
    try:
        assert_same_origin(request)
        target = reset_user_password(db, user_id, str(form.get("password") or ""))
    except CheckoutError as exc:
        return _users_page(request, user, db, error=str(exc))
    return RedirectResponse(
        redirect_path(f"/admin/change-password?saved=1&user={quote(target.username)}"),
        status_code=303,
    )


@router.post("/admin/users/{user_id}/role")
async def admin_user_role_save(request: Request, user_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    form = await request.form()
    _use_lang(request, str(form.get("lang") or ""))
    try:
        assert_same_origin(request)
        target = set_user_admin(
            db,
            user_id,
            make_admin=str(form.get("is_admin") or "") == "1",
            actor=user,
        )
    except CheckoutError as exc:
        return _users_page(request, user, db, error=str(exc))
    return RedirectResponse(
        redirect_path(f"/admin/change-password?role=1&user={quote(target.username)}"),
        status_code=303,
    )


@router.post("/admin/users/{user_id}/delete")
async def admin_user_delete(request: Request, user_id: int, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    form = await request.form()
    _use_lang(request, str(form.get("lang") or ""))
    try:
        assert_same_origin(request)
        username = delete_user(db, user_id, actor=user)
    except CheckoutError as exc:
        return _users_page(request, user, db, error=str(exc))
    return RedirectResponse(
        redirect_path(f"/admin/change-password?deleted=1&user={quote(username)}"),
        status_code=303,
    )


@router.get("/admin/delivery-list")
def admin_delivery_list(
    request: Request,
    db: Session = Depends(get_db),
    delivery_date: str | None = Query(default=None, alias="date"),
):
    resolve_lang(request)
    user, redirect = _require_admin(request, db)
    if redirect is not None:
        return redirect
    selected = _parse_date(delivery_date) or cycle_for("coming")[1]
    orders = delivery_orders(db, selected)
    return render(
        request,
        "admin_delivery.html",
        {
            "current_user": user,
            "orders": orders,
            "selected_date": selected,
            "dates": delivery_dates(db),
            "product_label": product_label,
            "status_value": _status_value,
        },
    )


@router.get("/")
def home(
    request: Request,
    delivery_date: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    resolve_lang(request)
    user = current_user(request, db)
    if user is None:
        next_path = request.url.path
        if request.url.query:
            next_path = f"{next_path}?{request.url.query}"
        return _login_redirect(request, next_path)
    if user.is_admin:
        return RedirectResponse(redirect_path("/admin"), status_code=302)
    selected = _parse_date(delivery_date)
    week = "next" if request.query_params.get("week") == "next" else "coming"
    error = None
    if delivery_date and selected is None:
        error = t("choose_morning")
    return _render_home(request, db, selected=selected, error=error, week=week, user=user)


@router.post("/checkout")
async def start_checkout(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    saved = _saved_form(form)
    _use_lang(request, saved.get("lang"))
    user = current_user(request, db)
    if user is None:
        return _login_redirect(request, "/")
    try:
        assert_same_origin(request)
        order = create_checkout(db, checkout_from_form(form), user=user)
    except CheckoutError as exc:
        return _render_home(
            request,
            db,
            selected=_parse_date(saved.get("delivery_date")),
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            week=week_choice_for(_parse_date(saved.get("delivery_date"))),
            user=user,
        )
    return RedirectResponse(redirect_path(f"/order-success?order_id={order.order_number}"), status_code=303)


@router.get("/checkout/{order_number}")
def checkout_page(request: Request, order_number: str, db: Session = Depends(get_db)):
    resolve_lang(request)
    user = current_user(request, db)
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
    return render(request, "checkout.html", {"order": order, "status": status, "current_user": user})


@router.get("/order-success")
def order_success(request: Request, order_id: str = "", db: Session = Depends(get_db)):
    resolve_lang(request)
    user = current_user(request, db)
    order = get_order(db, order_id) if order_id else None
    if order is not None and _status_value(order) == OrderStatus.CANCELLED.value:
        return RedirectResponse(redirect_path(f"/order-failed?order_id={order.order_number}"), status_code=302)
    status = _status_value(order) if order is not None else ""
    return render(request, "order_success.html", {"order": order, "status": status, "current_user": user})


@router.get("/order-failed")
def order_failed(request: Request, order_id: str = "", db: Session = Depends(get_db)):
    resolve_lang(request)
    user = current_user(request, db)
    order = get_order(db, order_id) if order_id else None
    status = _status_value(order) if order is not None else ""
    return render(request, "order_failed.html", {"order": order, "status": status, "current_user": user})


@router.get("/pay/mock/{order_number}")
def mock_payment(request: Request, order_number: str, db: Session = Depends(get_db)):
    resolve_lang(request)
    if get_settings().grow_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    user = current_user(request, db)
    order = get_order(db, order_number)
    if order is None:
        raise HTTPException(status_code=404, detail=t("order_not_found"))
    status = _status_value(order)
    if status == OrderStatus.PAID.value:
        return RedirectResponse(redirect_path(f"/order-success?order_id={order.order_number}"), status_code=302)
    if status == OrderStatus.CANCELLED.value:
        return RedirectResponse(redirect_path(f"/order-failed?order_id={order.order_number}"), status_code=302)
    return render(request, "mock_payment.html", {"order": order, "current_user": user})


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
