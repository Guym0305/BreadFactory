from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.services.errors import CheckoutError
from app.services.payments import apply_webhook, parse_grow_body, verify_webhook_signature

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("/webhook")
async def grow_payment_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    settings = get_settings()
    try:
        verify_webhook_signature(
            body,
            request.headers.get("x-grow-signature"),
            settings.grow_webhook_secret,
            require=settings.grow_enabled,
        )
        return apply_webhook(db, parse_grow_body(request.headers.get("content-type", ""), body))
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
