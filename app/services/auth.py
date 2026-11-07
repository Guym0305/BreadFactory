import hashlib
import hmac
import re
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.i18n import t
from app.models.bakery import Customer, User, utcnow
from app.services.errors import CheckoutError

SESSION_COOKIE = "bf_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,40}$")
PLACEHOLDER_EMAIL_SUFFIX = "@users.local"
PLACEHOLDER_ADDRESS = "-"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, rounds, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(rounds),
    ).hex()
    return hmac.compare_digest(check, digest)


def _sign(value: str) -> str:
    secret = get_settings().session_secret.encode("utf-8")
    signature = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{value}.{signature}"
    return urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def _unsign(token: str) -> str | None:
    try:
        raw = urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        value, signature = raw.rsplit(".", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    secret = get_settings().session_secret.encode("utf-8")
    expected = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return value


def set_session_user(response: Response, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        _sign(str(user_id)),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    raw = _unsign(token)
    if raw is None or not raw.isdigit():
        return None
    return (
        db.query(User)
        .options(joinedload(User.customer))
        .filter(User.id == int(raw))
        .one_or_none()
    )


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if user is None:
        raise CheckoutError(t("login_required"), 401)
    return user


def _provisional_customer(display_name: str) -> Customer:
    suffix = secrets.token_hex(4)
    return Customer(
        full_name=display_name,
        phone=f"+199{secrets.randbelow(10**9):09d}",
        email=f"{suffix}{PLACEHOLDER_EMAIL_SUFFIX}",
        address=PLACEHOLDER_ADDRESS,
        created_at=utcnow(),
    )


def customer_form_defaults(customer: Customer | None) -> dict[str, str]:
    if customer is None:
        return {}
    saved: dict[str, str] = {}
    if customer.full_name and not customer.full_name.startswith("guest_"):
        saved["full_name"] = customer.full_name
    if customer.phone and not customer.phone.startswith("+199"):
        saved["phone"] = customer.phone
    if customer.email and not customer.email.endswith(PLACEHOLDER_EMAIL_SUFFIX):
        saved["email"] = customer.email
    if customer.address and customer.address != PLACEHOLDER_ADDRESS:
        saved["address"] = customer.address
    return saved


def normalize_username(value: str) -> str:
    cleaned = value.strip()
    if not USERNAME_RE.fullmatch(cleaned):
        raise CheckoutError(t("username_invalid"))
    return cleaned.lower()


def _find_user_by_username(db: Session, username: str) -> User | None:
    return (
        db.query(User)
        .options(joinedload(User.customer))
        .filter(func.lower(User.username) == username.strip().lower())
        .one_or_none()
    )


def register_user(db: Session, username: str, password: str) -> User:
    name = normalize_username(username)
    if len(password) < 6 or len(password) > 100:
        raise CheckoutError(t("password_invalid"))
    if _find_user_by_username(db, name) is not None:
        raise CheckoutError(t("username_taken"))
    customer = _provisional_customer(name)
    db.add(customer)
    db.flush()
    user = User(
        username=name,
        password_hash=hash_password(password),
        is_guest=False,
        is_admin=False,
        customer_id=customer.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User:
    normalize_username(username)
    user = _find_user_by_username(db, username)
    if user is None or user.is_guest or not verify_password(password, user.password_hash):
        raise CheckoutError(t("login_failed"))
    return user


def create_guest_user(db: Session) -> User:
    for _ in range(8):
        name = f"guest_{secrets.token_hex(4)}"
        if db.query(User.id).filter(User.username == name).first() is None:
            customer = _provisional_customer(name)
            db.add(customer)
            db.flush()
            user = User(
                username=name,
                password_hash=None,
                is_guest=True,
                is_admin=False,
                customer_id=customer.id,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
    raise CheckoutError(t("guest_failed"), 503)


def ensure_admin_user(db: Session) -> None:
    settings = get_settings()
    username = settings.admin_username.strip()
    password = settings.admin_password
    if not username or not password:
        return
    if not USERNAME_RE.fullmatch(username):
        return
    user = _find_user_by_username(db, username)
    if user is None:
        customer = _provisional_customer(username)
        db.add(customer)
        db.flush()
        user = User(
            username=username,
            password_hash=hash_password(password),
            is_guest=False,
            is_admin=True,
            customer_id=customer.id,
        )
        db.add(user)
    else:
        user.username = username
        user.is_admin = True
        user.is_guest = False
        if not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
    db.commit()
