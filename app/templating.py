from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.i18n import get_lang, language_switch, resolve_lang, set_lang
from app.services.slots import DELIVERY_WINDOW, MONTHS, WEEKDAYS

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def render(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    lang = context.get("lang") or resolve_lang(request)
    set_lang(lang)
    context["request"] = request
    context["lang"] = lang
    context.setdefault("week", "coming")
    context["switch_he"] = language_switch(request, "he")
    context["switch_en"] = language_switch(request, "en")
    response = HTMLResponse(templates.get_template(f"{lang}/{name}").render(context), status_code=status_code)
    response.set_cookie("bf_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    return response


def money(value: float) -> str:
    amount = float(value)
    if abs(amount - round(amount)) < 0.001:
        return f"₪{amount:.0f}"
    return f"₪{amount:.2f}"


def delivery_label(value, lang: str = "en") -> str:
    chosen = lang if lang in WEEKDAYS else "en"
    weekday = WEEKDAYS[chosen][value.weekday()]
    month = MONTHS[chosen][value.month - 1]
    if chosen == "he":
        return f"{weekday}, {value.day} ב{month}"
    return f"{weekday}, {value.day} {month}"


templates.env.filters["money"] = money
templates.env.filters["delivery_label"] = delivery_label
templates.env.globals["delivery_window"] = DELIVERY_WINDOW


def redirect_path(path: str, lang: str | None = None) -> str:
    chosen = lang or get_lang()
    query = urlencode({"lang": chosen})
    join = "&" if "?" in path else "?"
    if "lang=" in path:
        return path
    return f"{path}{join}{query}"
