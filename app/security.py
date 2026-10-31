from urllib.parse import urlsplit

from fastapi import Request

from app.i18n import t
from app.services.errors import CheckoutError


def external_scheme(request: Request) -> str:
    """Scheme the browser used. Cloud Run terminates TLS and forwards HTTP."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        return forwarded.split(",")[-1].strip().lower()
    return request.url.scheme


def assert_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    host = request.headers.get("host") or request.url.netloc
    if parsed.scheme != external_scheme(request) or parsed.netloc != host:
        raise CheckoutError(t("cross_site"), 403)
