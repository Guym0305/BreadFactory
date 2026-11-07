from contextvars import ContextVar
from urllib.parse import urlencode

from fastapi import Request

SUPPORTED = ("he", "en")
DEFAULT_LANG = "he"
_current: ContextVar[str] = ContextVar("lang", default=DEFAULT_LANG)

MESSAGES = {
    "en": {
        "enter_name": "Enter a name.",
        "enter_address": "Enter an address.",
        "name_long": "Name is too long.",
        "address_long": "Address is too long.",
        "phone": "Enter a phone number we can reach you on.",
        "email": "Enter a valid email address.",
        "notes_long": "Notes are too long.",
        "choose_loaf": "Choose at least one loaf.",
        "choose_payment": "Choose how you will pay.",
        "enter_payment_other": "Enter how you will pay.",
        "payment_other_long": "That payment note is too long.",
        "whole_number": "Enter a whole number of loaves.",
        "choose_from_bake": "Choose a loaf from the bake.",
        "one_left": "Only 1 loaf is left for this delivery.",
        "n_left": "Only {n} loaves are left for this delivery.",
        "unavailable": "A chosen loaf is no longer available.",
        "order_number": "Could not reserve an order number. Please try again.",
        "fully_booked": "This delivery is full.",
        "choose_morning": "That delivery week is not open.",
        "cross_site": "This order cannot be submitted from another site.",
        "payment_start": "Payment could not be started. Please try again.",
        "order_not_found": "Order not found.",
        "pay_bit": "Bit",
        "pay_paybox": "PayBox",
        "pay_bank_transfer": "Bank transfer",
        "pay_cash": "Cash",
        "pay_other": "Other",
        "login_required": "Sign in or continue as guest to order.",
        "username_invalid": "Usernames use 3–40 letters, numbers, or underscores.",
        "password_invalid": "Passwords need at least 6 characters.",
        "username_taken": "That username is already taken.",
        "phone_taken": "That phone number already belongs to another customer.",
        "email_taken": "That email already belongs to another customer.",
        "login_failed": "Wrong username or password.",
        "guest_failed": "Could not start a guest session. Please try again.",
        "admin_only": "Admin access required.",
    },
    "he": {
        "enter_name": "הזינו שם.",
        "enter_address": "הזינו כתובת.",
        "name_long": "השם ארוך מדי.",
        "address_long": "הכתובת ארוכה מדי.",
        "phone": "הזינו מספר טלפון שאפשר להשיג אתכם בו.",
        "email": "הזינו כתובת דוא״ל תקינה.",
        "notes_long": "ההערות ארוכות מדי.",
        "choose_loaf": "בחרו לפחות כיכר אחת.",
        "choose_payment": "בחרו איך תשלמו.",
        "enter_payment_other": "הזינו איך תשלמו.",
        "payment_other_long": "הערת התשלום ארוכה מדי.",
        "whole_number": "הזינו מספר שלם של כיכרות.",
        "choose_from_bake": "בחרו כיכר מהאפייה.",
        "one_left": "נותרה כיכר אחת למשלוח הזה.",
        "n_left": "נותרו {n} כיכרות למשלוח הזה.",
        "unavailable": "אחת הכיכרות שנבחרו כבר לא זמינה.",
        "order_number": "לא הצלחנו לשמור מספר הזמנה. נסו שוב.",
        "fully_booked": "המשלוח הזה מלא.",
        "choose_morning": "שבוע המשלוח הזה אינו פתוח.",
        "cross_site": "אי אפשר לשלוח את ההזמנה מאתר אחר.",
        "payment_start": "לא הצלחנו לפתוח את התשלום. נסו שוב.",
        "order_not_found": "ההזמנה לא נמצאה.",
        "pay_bit": "Bit",
        "pay_paybox": "PayBox",
        "pay_bank_transfer": "העברה בנקאית",
        "pay_cash": "מזומן",
        "pay_other": "אחר",
        "login_required": "התחברו או המשיכו כאורח כדי להזמין.",
        "username_invalid": "שם משתמש: 3–40 אותיות, ספרות או קו תחתון.",
        "password_invalid": "סיסמה צריכה לפחות 6 תווים.",
        "username_taken": "שם המשתמש כבר תפוס.",
        "phone_taken": "מספר הטלפון כבר שייך ללקוח אחר.",
        "email_taken": "כתובת הדוא״ל כבר שייכת ללקוח אחר.",
        "login_failed": "שם משתמש או סיסמה שגויים.",
        "guest_failed": "לא הצלחנו לפתוח אורח. נסו שוב.",
        "admin_only": "נדרשת הרשאת מנהל.",
    },
}


def set_lang(lang: str) -> str:
    chosen = lang if lang in SUPPORTED else DEFAULT_LANG
    _current.set(chosen)
    return chosen


def get_lang() -> str:
    return _current.get()


def t(key: str, **values) -> str:
    catalog = MESSAGES[get_lang()]
    return catalog[key].format(**values)


def resolve_lang(request: Request) -> str:
    query = request.query_params.get("lang")
    if query in SUPPORTED:
        return set_lang(query)
    cookie = request.cookies.get("bf_lang")
    if cookie in SUPPORTED:
        return set_lang(cookie)
    return set_lang(DEFAULT_LANG)


def language_switch(request: Request, target: str) -> str:
    path = request.url.path if request.method == "GET" else "/"
    params = dict(request.query_params) if request.method == "GET" else {}
    params["lang"] = target
    if path != "/" and "date" in params and not path.endswith("/"):
        pass
    query = urlencode(params)
    return f"{path}?{query}" if query else path
