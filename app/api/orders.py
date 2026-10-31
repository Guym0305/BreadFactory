import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.i18n import resolve_lang
from app.schemas.order import OrderCreated, OrderStatusOut
from app.security import assert_same_origin
from app.services.checkout import create_checkout, created_payload, parse_checkout
from app.services.errors import CheckoutError
from app.services.orders import get_order, serialize_order

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post("", response_model=OrderCreated)
async def create_order(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    try:
        assert_same_origin(request)
        payload = await request.json()
        order = create_checkout(db, parse_checkout(payload))
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Order could not be read.") from exc
    return created_payload(order)


@router.get("/{order_number}", response_model=OrderStatusOut)
def read_order(order_number: str, request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    order = get_order(db, order_number)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return serialize_order(order)
