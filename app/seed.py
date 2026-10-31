from sqlalchemy.orm import Session

from app.models.bakery import Product

SEED_PRODUCTS = [
    {
        "name": "Country Sourdough",
        "name_en": "Country Sourdough",
        "name_he": "לחם מחמצת כפרי",
        "description": "A long ferment and an open crumb, with a crust that snaps. The loaf we bake most mornings.",
        "description_en": "A long ferment and an open crumb, with a crust that snaps. The loaf we bake most mornings.",
        "description_he": "התפחה ארוכה ופנים פתוחים, עם קרום שנשבר. הכיכר שאנחנו אופים ברוב הבקרים.",
        "price": 36.0,
        "image_url": "/static/images/country-loaf.jpg",
        "ingredients": "Wheat flour, water, salt",
        "ingredients_en": "Wheat flour, water, salt",
        "ingredients_he": "קמח חיטה, מים, מלח",
        "fermentation_hours": 30,
    },
    {
        "name": "Seeded Miche",
        "name_en": "Seeded Miche",
        "name_he": "כיכר גרעינים",
        "description": "The same dough, rolled in sesame, flax, and sunflower. A darker crust and a moist center.",
        "description_en": "The same dough, rolled in sesame, flax, and sunflower. A darker crust and a moist center.",
        "description_he": "אותו בצק, עטוף בשומשום, פשתן וחמניות. קרום כהה ומרכז לח.",
        "price": 42.0,
        "image_url": "/static/images/seeded-loaf.jpg",
        "ingredients": "Wheat flour, water, salt, sesame, flax, sunflower",
        "ingredients_en": "Wheat flour, water, salt, sesame, flax, sunflower",
        "ingredients_he": "קמח חיטה, מים, מלח, שומשום, פשתן, חמניות",
        "fermentation_hours": 36,
    },
    {
        "name": "Olive & Herb",
        "name_en": "Olive & Herb",
        "name_he": "זיתים ועשבי תיבול",
        "description": "Green olives and thyme folded through a gentler dough. Best the morning it arrives.",
        "description_en": "Green olives and thyme folded through a gentler dough. Best the morning it arrives.",
        "description_he": "זיתים ירוקים וטימין בבצק עדין יותר. הכיכר הכי טובה בבוקר שהיא מגיעה.",
        "price": 44.0,
        "image_url": "/static/images/olive-loaf.jpg",
        "ingredients": "Wheat flour, water, salt, olives, thyme, olive oil",
        "ingredients_en": "Wheat flour, water, salt, olives, thyme, olive oil",
        "ingredients_he": "קמח חיטה, מים, מלח, זיתים, טימין, שמן זית",
        "fermentation_hours": 24,
    },
]


PLACEHOLDER_IMAGES = {
    "/static/images/country-crumb.svg",
    "/static/images/seeded-crumb.svg",
    "/static/images/olive-crumb.svg",
}


def seed_products(db: Session) -> None:
    existing = db.query(Product).all()
    by_name = {(product.name_en or product.name): product for product in existing}
    translated = (
        "name_en",
        "name_he",
        "description_en",
        "description_he",
        "ingredients_en",
        "ingredients_he",
    )
    for record in SEED_PRODUCTS:
        current = by_name.get(record["name_en"])
        if current is None:
            db.add(Product(**record, is_active=True))
            continue
        for key in translated:
            if not getattr(current, key):
                setattr(current, key, record[key])
        # Stand-in photos replace the drawn crumbs. A later real photo is left in place.
        if not current.image_url or current.image_url in PLACEHOLDER_IMAGES:
            current.image_url = record["image_url"]
    db.commit()
