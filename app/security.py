from urllib.parse import urlsplit

from fastapi import Request

from app.i18n import t
from app.services.errors import CheckoutError


def assert_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.scheme != request.url.scheme or parsed.netloc != request.url.netloc:
        raise CheckoutError(t("cross_site"), 403)
