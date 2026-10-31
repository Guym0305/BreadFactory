from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.i18n import get_lang, resolve_lang
from app.models.bakery import Product
from app.schemas.product import ProductOut, SlotOut
from app.services.slots import list_slots

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/products", response_model=list[ProductOut])
def products(db: Session = Depends(get_db)):
    rows = db.query(Product).filter(Product.is_active.is_(True)).order_by(Product.id).all()
    return rows


@router.get("/slots", response_model=list[SlotOut])
def slots(request: Request, db: Session = Depends(get_db)):
    resolve_lang(request)
    week = request.query_params.get("week")
    if week != "next":
        week = "coming"
    return [
        SlotOut(
            date=slot.date,
            weekday=slot.weekday,
            window=slot.window,
            order_by=slot.order_by,
            remaining=slot.remaining,
            capacity=slot.capacity,
            available=slot.available,
        )
        for slot in list_slots(db, lang=get_lang(), week=week)
    ]
