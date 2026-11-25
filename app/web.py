from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.i18n import get_lang, resolve_lang, set_lang, t
from app.models.bakery import OrderStatus, Product
from app.security import assert_same_origin
from app.seed import sort_catalog
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
    update_customer_profile,
)
from app.services.cart import (
    MAX_LINE,
    Cart,
    clear_cart,
    lines_from_form,
    lines_from_mapping,
    normalize_lines,
    read_cart,
    totals_from_lines,
    write_cart,
)
from app.services.variants import VARIANTS, line_title, offers_version
from app.services.checkout import checkout_from_form, create_checkout
from app.services.errors import CheckoutError
from app.services.orders import get_order, list_customer_orders
from app.services.places import address_form_fields, registration_address
from app.services.payments import apply_webhook
from app.services.slots import (
    BAKERY_TZ,
    assert_cart_fits,
    bakery_now,
    cycle_for,
    list_slots,
    ordering_closed,
    reserved_product_quantities,
    week_choice_for,
)
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
        "fulfillment",
        "delivery_city",
        "street_address",
        "pickup_point",
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


def _return_path(raw: str | None, flag: str, extra: dict | None = None) -> str:
    safe = _next_path(None if raw is None else str(raw))
    parts = urlsplit(safe)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("added", None)
    query.pop("added_product", None)
    query.pop("replaced", None)
    query[flag] = "1"
    if extra:
        for key, value in extra.items():
            query[key] = value
    encoded = urlencode(query)
    path = parts.path or "/"
    target = f"{path}?{encoded}" if encoded else path
    if parts.fragment:
        target = f"{target}#{parts.fragment}"
    return target


def _shopper(request: Request, db: Session):
    """A customer, a guest, or nobody. Administrators stay in the admin area."""
    user = current_user(request, db)
    if user is not None and user.is_admin:
        return None, RedirectResponse(redirect_path("/admin"), status_code=303)
    return user, None


def _customer_or_redirect(request: Request, db: Session, next_path: str):
    user = current_user(request, db)
    if user is None:
        return None, _login_redirect(request, next_path)
    if user.is_admin:
        return None, RedirectResponse(redirect_path("/admin"), status_code=303)
    return user, None


def _active_products(db: Session, product_ids: list[int]) -> dict[int, Product]:
    if not product_ids:
        return {}
    return {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids), Product.is_active.is_(True))
    }


def _line_caps(db: Session, slot, quantities: dict[int, int], products: dict[int, Product]) -> dict[int, int]:
    if slot is None:
        return {product_id: quantity for product_id, quantity in quantities.items()}
    taken = reserved_product_quantities(db, slot.date)
    counted = sum(
        quantity
        for product_id, quantity in quantities.items()
        if (product := products.get(product_id)) is not None and product.counts_toward_capacity
    )
    spare = max(slot.remaining - counted, 0)
    caps: dict[int, int] = {}
    for product_id, quantity in quantities.items():
        product = products.get(product_id)
        if product is None:
            continue
        cap = quantity + spare if product.counts_toward_capacity else 99
        if product.delivery_limit is not None:
            cap = min(cap, max(product.delivery_limit - taken.get(product_id, 0), 0))
        caps[product_id] = max(cap, 0)
    return caps


def _product_rooms(db: Session, products: list[Product], cart_quantities: dict[int, int], slot, day: date | None):
    rooms: dict[int, int] = {}
    if slot is None or day is None:
        return rooms, False
    taken = reserved_product_quantities(db, day)
    by_id = {product.id: product for product in products}
    cart_counted = sum(
        quantity
        for product_id, quantity in cart_quantities.items()
        if (product := by_id.get(product_id)) is not None and product.counts_toward_capacity
    )
    spare = max(slot.remaining - cart_counted, 0)
    for product in products:
        cap = spare if product.counts_toward_capacity else 99
        if product.delivery_limit is not None:
            already = taken.get(product.id, 0) + cart_quantities.get(product.id, 0)
            cap = min(cap, max(product.delivery_limit - already, 0))
        rooms[product.id] = max(cap, 0)
    return rooms, spare == 0 and cart_counted > 0


def _ordered_out(db: Session, products: list[Product], slot, day: date | None) -> dict[int, bool]:
    """True when placed orders, not the open cart, have used up a product."""
    if slot is None or day is None:
        return {}
    taken = reserved_product_quantities(db, day)
    sold_out: dict[int, bool] = {}
    for product in products:
        limit_gone = product.delivery_limit is not None and taken.get(product.id, 0) >= product.delivery_limit
        bake_gone = bool(product.counts_toward_capacity) and slot.remaining <= 0
        sold_out[product.id] = limit_gone or bake_gone
    return sold_out


def _posted_lang(form) -> str | None:
    posted = form.get("lang")
    return str(posted) if posted else None


def _whole_quantity(raw, *, minimum: int) -> int:
    try:
        quantity = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise CheckoutError(t("whole_number")) from exc
    if quantity < minimum or quantity > 99:
        raise CheckoutError(t("choose_loaf") if quantity < 1 else t("whole_number"))
    return quantity


def _product_id(raw) -> int:
    try:
        product_id = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise CheckoutError(t("choose_from_bake")) from exc
    if product_id < 1:
        raise CheckoutError(t("choose_from_bake"))
    return product_id


def _cart_lines(raw_lines: dict, db: Session) -> tuple[dict, dict[int, int], dict[int, Product]]:
    product_ids = [product_id for product_id, _variant in raw_lines]
    products = _active_products(db, product_ids)
    lines = normalize_lines(raw_lines, products)
    return lines, totals_from_lines(lines), products


def _slot_for_day(db: Session, day: date, lang: str):
    week = week_choice_for(day)
    slots = list_slots(db, lang=lang, week=week)
    slot = slots[0] if slots and slots[0].date == day else None
    return slot, week


def _delivery_choices(db: Session, lang: str) -> tuple[list[dict], bool]:
    closed = ordering_closed()
    weeks = ("coming",) if closed else ("coming", "next")
    keys = ("next_friday",) if closed else ("coming", "next")
    choices = []
    for week, key in zip(weeks, keys, strict=True):
        slots = list_slots(db, lang=lang, week=week)
        if slots:
            choices.append({"key": key, "slot": slots[0]})
    return choices, closed


def _selected_day(cart: Cart, choices: list[dict]) -> date | None:
    allowed = {item["slot"].date for item in choices}
    if cart.delivery_date in allowed:
        return cart.delivery_date
    if choices:
        return choices[0]["slot"].date
    return cart.delivery_date


def _render_cart(
    request: Request,
    db: Session,
    *,
    error: str | None = None,
    saved: dict | None = None,
    status_code: int = 200,
    user=None,
):
    lang = get_lang()
    cart = read_cart(request)
    choices, deadline_closed = _delivery_choices(db, lang)
    form_saved = dict(saved or {})
    selected = _selected_day(cart, choices)
    posted_day = _parse_date(form_saved.get("delivery_date"))
    allowed = {item["slot"].date for item in choices}
    if posted_day in allowed:
        selected = posted_day
    if any(str(key).startswith("qty_") for key in form_saved):
        raw_lines = lines_from_mapping(form_saved)
    else:
        raw_lines = dict(cart.lines)
    raw_lines, quantities, products = _cart_lines(raw_lines, db)
    slot = None
    week = "coming"
    for choice in choices:
        if choice["slot"].date == selected:
            slot = choice["slot"]
            week = "next" if choice["key"] == "next" else "coming"
            break
    line_caps = _line_caps(db, slot, quantities, products)
    version_order = {"": 0, "regular": 1, "vegan": 2}
    lines = []
    for (product_id, variant), quantity in sorted(
        raw_lines.items(),
        key=lambda item: (item[0][0], version_order.get(item[0][1], 9)),
    ):
        product = products.get(product_id)
        if product is None or quantity <= 0:
            continue
        product_cap = line_caps.get(product_id, quantity)
        shared_spare = max(product_cap - quantities.get(product_id, quantity), 0)
        lines.append(
            {
                "product": product,
                "quantity": quantity,
                "variant": variant,
                "max_quantity": quantity + shared_spare,
            }
        )
    if user is not None and user.customer is not None:
        defaults = customer_form_defaults(user.customer)
        defaults.update(address_form_fields(defaults.get("address", "")))
        for key, value in defaults.items():
            form_saved.setdefault(key, value)
    context = {
        "lines": lines,
        "slot": slot,
        "error": error,
        "saved": form_saved,
        "week": week,
        "current_user": user,
        "delivery_date": selected.isoformat() if selected else "",
        "cart_count": sum(line["quantity"] for line in lines),
        "choices": choices,
        "deadline_closed": deadline_closed,
        "selected_delivery": selected,
        "reordered": request.query_params.get("reordered") == "1" and error is None,
        "reordered_skipped": request.query_params.get("skipped") == "1" and error is None,
    }
    return render(request, "cart.html", context, status_code=status_code)


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
    show_bake = slot is not None
    products = []
    if show_bake:
        products = sort_catalog(
            db.query(Product).filter(Product.is_active.is_(True)).all()
        )
    form_saved = dict(saved or {})
    if user is not None and user.customer is not None:
        for key, value in customer_form_defaults(user.customer).items():
            form_saved.setdefault(key, value)
    visible_slot = slot if show_bake else None
    cart = read_cart(request)
    choices, deadline_closed = _delivery_choices(db, lang)
    allowed = {item["slot"].date: item["slot"] for item in choices}
    target = cart.delivery_date if cart.delivery_date in allowed else (visible_slot.date if visible_slot else None)
    cart_quantities = {pid: qty for pid, qty in cart.quantities.items() if qty > 0}
    cart_held = sum(cart_quantities.values())
    limit = allowed.get(target) if target in allowed else visible_slot
    product_room, cart_holds_bake = _product_rooms(db, products, cart_quantities, limit, target)
    product_sold_out = _ordered_out(db, products, limit, target)
    context = {
        "slots": slots,
        "products": products,
        "slot": visible_slot,
        "error": error,
        "saved": form_saved,
        "lang": lang,
        "week": week,
        "current_user": user,
        "cart_quantities": cart_quantities,
        "cart_held": cart_held,
        "product_room": product_room,
        "product_sold_out": product_sold_out,
        "bake_full": visible_slot is not None and visible_slot.remaining <= 0,
        "cart_holds_bake": cart_holds_bake,
        "added": request.query_params.get("added") == "1" and error is None,
        "added_product": _product_id(request.query_params.get("added_product")) if str(request.query_params.get("added_product") or "").isdigit() else None,
        "deadline_closed": deadline_closed,
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
        "fulfillment": str(form.get("fulfillment") or ""),
        "delivery_city": str(form.get("delivery_city") or ""),
        "street_address": str(form.get("street_address") or ""),
        "pickup_point": str(form.get("pickup_point") or ""),
    }
    try:
        assert_same_origin(request)
        address = registration_address(
            saved_register["fulfillment"],
            saved_register["delivery_city"],
            saved_register["pickup_point"],
            saved_register["street_address"],
        )
        user = register_user(
            db,
            username,
            password,
            full_name=saved_register["full_name"],
            phone=saved_register["phone"],
            email=saved_register["email"],
            address=address,
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


def _account_form(user) -> dict[str, str]:
    customer = user.customer
    saved = customer_form_defaults(customer)
    saved.update(address_form_fields((customer.address if customer is not None else "") or ""))
    return saved


def _posted_account(form) -> dict[str, str]:
    return {
        "full_name": str(form.get("full_name") or ""),
        "phone": str(form.get("phone") or ""),
        "email": str(form.get("email") or ""),
        "fulfillment": str(form.get("fulfillment") or ""),
        "delivery_city": str(form.get("delivery_city") or ""),
        "street_address": str(form.get("street_address") or ""),
        "pickup_point": str(form.get("pickup_point") or ""),
    }


@router.get("/account")
def account_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user = current_user(request, db)
    if user is None:
        return _login_redirect(request, "/account")
    return render(
        request,
        "account.html",
        {
            "current_user": user,
            "saved": {} if user.is_guest else _account_form(user),
            "error": None,
            "notice": request.query_params.get("saved") == "1",
        },
    )


@router.post("/account")
async def account_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, str(form.get("lang")) if form.get("lang") else None)
    user = current_user(request, db)
    if user is None:
        return _login_redirect(request, "/account")
    posted = _posted_account(form)
    try:
        assert_same_origin(request)
        address = registration_address(
            posted["fulfillment"],
            posted["delivery_city"],
            posted["pickup_point"],
            posted["street_address"],
        )
        update_customer_profile(
            db,
            user,
            full_name=posted["full_name"],
            phone=posted["phone"],
            email=posted["email"],
            address=address,
        )
    except CheckoutError as exc:
        return render(
            request,
            "account.html",
            {
                "current_user": user,
                "saved": posted,
                "error": exc.message,
                "notice": False,
            },
            status_code=exc.status_code,
        )
    return RedirectResponse(redirect_path("/account?saved=1"), status_code=303)


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
    variants = [str(value) for value in form.getlist("item_variant")]
    if not (len(item_ids) == len(product_ids) == len(quantities) == len(prices)):
        raise CheckoutError(t("admin_bad_line"))
    use_variants = len(variants) == len(item_ids)
    lines: list[dict] = []
    for index, (item_id, product_id, quantity, price) in enumerate(
        zip(item_ids, product_ids, quantities, prices)
    ):
        lines.append(
            {
                "id": int(item_id) if item_id.isdigit() else None,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": price,
                "variant": variants[index] if use_variants else "",
                "set_variant": use_variants,
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
                "variant": str(form.get("new_variant") or ""),
                "set_variant": True,
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
        "delivery_limit": str(form.get("delivery_limit") or ""),
        "counts_toward_capacity": str(form.get("counts_toward_capacity") or "") == "1",
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


@router.get("/cart")
def cart_page(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _shopper(request, db)
    if redirect is not None:
        return redirect
    return _render_cart(request, db, user=user)


@router.post("/cart/add")
async def add_to_cart(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, _posted_lang(form))
    user, redirect = _shopper(request, db)
    if redirect is not None:
        return redirect
    day = _parse_date(str(form.get("delivery_date") or ""))
    try:
        assert_same_origin(request)
        product_id = _product_id(form.get("product_id"))
        quantity = _whole_quantity(form.get("quantity") or "1", minimum=1)
        products = _active_products(db, [product_id])
        if product_id not in products:
            raise CheckoutError(t("unavailable"))
        cart = read_cart(request)
        choices, _closed = _delivery_choices(db, get_lang())
        allowed = {item["slot"].date: item["slot"] for item in choices}
        if cart.delivery_date in allowed:
            day = cart.delivery_date
        elif day not in allowed:
            if not choices:
                raise CheckoutError(t("choose_morning"))
            day = choices[0]["slot"].date
        held = _active_products(db, [pid for pid, _variant in cart.lines] + [product_id])
        lines = normalize_lines(dict(cart.lines), held)
        raw_variant = str(form.get("variant") or "").strip().lower()
        variant = raw_variant if offers_version(products[product_id]) and raw_variant in VARIANTS else ""
        if offers_version(products[product_id]) and not variant:
            variant = "regular"
        lines[(product_id, variant)] = min(lines.get((product_id, variant), 0) + quantity, MAX_LINE)
        quantities = totals_from_lines(lines)
        assert_cart_fits(db, day, quantities)
        cart = Cart(day, quantities, lines)
    except CheckoutError as exc:
        return _render_home(
            request,
            db,
            selected=day,
            error=exc.message,
            status_code=exc.status_code,
            week="coming",
            user=user,
        )
    response = RedirectResponse(
        _return_path(form.get("next"), "added", {"added_product": str(product_id)}),
        status_code=303,
    )
    write_cart(response, cart)
    return response


@router.post("/cart/delivery")
async def choose_delivery(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, _posted_lang(form))
    user, redirect = _shopper(request, db)
    if redirect is not None:
        return redirect
    day = _parse_date(str(form.get("delivery_date") or ""))
    cart = read_cart(request)
    try:
        assert_same_origin(request)
        choices, _closed = _delivery_choices(db, get_lang())
        allowed = {item["slot"].date: item["slot"] for item in choices}
        if day not in allowed:
            raise CheckoutError(t("choose_morning"))
        assert_cart_fits(db, day, cart.quantities)
    except CheckoutError as exc:
        saved = _saved_form(form)
        saved["delivery_date"] = cart.delivery_date.isoformat() if cart.delivery_date else ""
        for (product_id, variant), quantity in cart.lines.items():
            suffix = f"_{variant}" if variant else ""
            saved[f"qty_{product_id}{suffix}"] = str(quantity)
        return _render_cart(
            request,
            db,
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            user=user,
        )
    response = RedirectResponse(redirect_path("/cart"), status_code=303)
    write_cart(response, Cart(day, dict(cart.quantities), dict(cart.lines)))
    return response


@router.post("/cart/update")
async def update_cart(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    saved = _saved_form(form)
    _use_lang(request, _posted_lang(form))
    user, redirect = _shopper(request, db)
    if redirect is not None:
        return redirect
    day = _parse_date(saved.get("delivery_date"))
    try:
        assert_same_origin(request)
        lines, quantities, _products = _cart_lines(lines_from_form(form), db)
        assert_cart_fits(db, day, quantities)
    except CheckoutError as exc:
        return _render_cart(
            request,
            db,
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            user=user,
        )
    response = RedirectResponse(redirect_path("/cart"), status_code=303)
    write_cart(response, Cart(day if quantities else None, quantities, lines))
    return response


@router.post("/cart/remove")
async def remove_from_cart(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    saved = _saved_form(form)
    _use_lang(request, _posted_lang(form))
    user, redirect = _shopper(request, db)
    if redirect is not None:
        return redirect
    day = _parse_date(saved.get("delivery_date"))
    try:
        assert_same_origin(request)
        lines = lines_from_form(form)
        remove_line = str(form.get("remove_line") or "")
        if remove_line:
            pid_part, _, variant = remove_line.partition("@")
            product_id = _product_id(pid_part)
            variant = variant if variant in VARIANTS else ""
            lines.pop((product_id, variant), None)
        else:
            product_id = _product_id(form.get("product_id"))
            lines = {key: qty for key, qty in lines.items() if key[0] != product_id}
        lines, quantities, _products = _cart_lines(lines, db)
        assert_cart_fits(db, day, quantities)
    except CheckoutError as exc:
        return _render_cart(
            request,
            db,
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            user=user,
        )
    response = RedirectResponse(redirect_path("/cart"), status_code=303)
    write_cart(response, Cart(day if quantities else None, quantities, lines))
    return response


_PROGRESS_LABELS = {
    "en": {
        "received": "Received and in progress",
        "completed": "Completed",
        "cancelled": "Cancelled",
    },
    "he": {
        "received": "התקבל ובטיפול",
        "completed": "הושלם",
        "cancelled": "בוטל",
    },
}


def _progress_key(order) -> str:
    if _status_value(order) == OrderStatus.CANCELLED.value:
        return "cancelled"
    delivery = order.delivery_date
    if delivery.tzinfo is None:
        done_at = delivery.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=BAKERY_TZ)
    else:
        done_at = delivery.astimezone(BAKERY_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    if bakery_now() >= done_at:
        return "completed"
    return "received"


def _placed_local(order) -> datetime:
    created = order.created_at
    if created is None:
        return order.delivery_date
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(BAKERY_TZ)


def _history_rows(db: Session, user, lang: str) -> list[dict]:
    labels = _PROGRESS_LABELS["he" if lang == "he" else "en"]
    rows = []
    for order in list_customer_orders(db, user.customer_id):
        lines = []
        for item in order.items:
            product = item.product
            lines.append(
                {
                    "name": line_title(product, item.variant, lang),
                    "quantity": item.quantity,
                    "total": round(item.quantity * item.unit_price, 2),
                }
            )
        rows.append(
            {
                "number": order.order_number,
                "placed": _placed_local(order),
                "delivery": order.delivery_date,
                "progress": labels[_progress_key(order)],
                "total": order.total_amount,
                "lines": lines,
            }
        )
    return rows


def _render_orders(request: Request, db: Session, user, *, error: str | None = None, status_code: int = 200):
    lang = get_lang()
    return render(
        request,
        "orders.html",
        {
            "current_user": user,
            "orders": _history_rows(db, user, lang),
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/orders")
def my_orders(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    user, redirect = _customer_or_redirect(request, db, "/orders")
    if redirect is not None:
        return redirect
    return _render_orders(request, db, user)


@router.post("/orders/{order_number}/reorder")
async def reorder(request: Request, order_number: str, db: Session = Depends(get_db)):
    form = await request.form()
    _use_lang(request, _posted_lang(form))
    user, redirect = _customer_or_redirect(request, db, "/orders")
    if redirect is not None:
        return redirect
    order = get_order(db, order_number)
    if order is None or order.customer_id != user.customer_id:
        raise HTTPException(status_code=404, detail=t("order_not_found"))
    try:
        assert_same_origin(request)
        active = _active_products(db, [item.product_id for item in order.items])
        additions: dict[tuple[int, str], int] = {}
        skipped = False
        for item in order.items:
            if item.product_id not in active or item.quantity < 1:
                skipped = True
                continue
            variant = item.variant if item.variant in VARIANTS else ""
            if offers_version(active[item.product_id]):
                variant = variant or "regular"
            else:
                variant = ""
            key = (item.product_id, variant)
            additions[key] = min(additions.get(key, 0) + item.quantity, MAX_LINE)
        if not additions:
            raise CheckoutError(t("reorder_unavailable"))
        cart = read_cart(request)
        choices, _closed = _delivery_choices(db, get_lang())
        allowed = {item["slot"].date for item in choices}
        if cart.delivery_date in allowed:
            day = cart.delivery_date
        elif choices:
            day = choices[0]["slot"].date
        else:
            raise CheckoutError(t("choose_morning"))
        held_ids = [pid for pid, _variant in cart.lines] + [pid for pid, _variant in additions]
        lines = normalize_lines(dict(cart.lines), _active_products(db, held_ids))
        for key, quantity in additions.items():
            lines[key] = min(lines.get(key, 0) + quantity, MAX_LINE)
        quantities = totals_from_lines(lines)
        assert_cart_fits(db, day, quantities)
    except CheckoutError as exc:
        return _render_orders(request, db, user, error=exc.message, status_code=exc.status_code)
    query = "reordered=1&skipped=1" if skipped else "reordered=1"
    response = RedirectResponse(redirect_path(f"/cart?{query}"), status_code=303)
    write_cart(response, Cart(day, quantities, lines))
    return response


@router.get("/")
def home(
    request: Request,
    delivery_date: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    resolve_lang(request)
    user = current_user(request, db)
    if user is not None and user.is_admin:
        return RedirectResponse(redirect_path("/admin"), status_code=302)
    selected = _parse_date(delivery_date)
    week = "coming"
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
    if user is not None and user.is_admin:
        return RedirectResponse(redirect_path("/admin"), status_code=303)
    created_guest = False
    try:
        assert_same_origin(request)
        data = checkout_from_form(form)
        if user is None:
            user = create_guest_user(db)
            created_guest = True
        order = create_checkout(db, data, user=user)
    except CheckoutError as exc:
        response = _render_cart(
            request,
            db,
            error=exc.message,
            saved=saved,
            status_code=exc.status_code,
            user=user,
        )
        if created_guest and user is not None:
            set_session_user(response, user.id)
        return response
    response = RedirectResponse(redirect_path(f"/order-success?order_id={order.order_number}"), status_code=303)
    clear_cart(response)
    if created_guest and user is not None:
        set_session_user(response, user.id)
    return response


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
