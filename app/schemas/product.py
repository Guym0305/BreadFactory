from datetime import date

from pydantic import BaseModel, ConfigDict


class ProductOut(BaseModel):
    id: int
    name: str
    name_en: str | None
    name_he: str | None
    description: str | None
    description_en: str | None
    description_he: str | None
    price: float
    image_url: str | None
    is_active: bool
    ingredients: str | None
    ingredients_en: str | None
    ingredients_he: str | None
    fermentation_hours: int

    model_config = ConfigDict(from_attributes=True)


class SlotOut(BaseModel):
    date: date
    weekday: str
    window: str
    order_by: date
    remaining: int
    capacity: int
    available: bool
