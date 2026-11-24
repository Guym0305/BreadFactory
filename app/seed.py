from sqlalchemy.orm import Session

from app.models.bakery import Product
from app.services.auth import ensure_admin_user

# Menu order: breads, pizza and khachapuri, crackers, then cake and cookie.
CATALOG_ORDER = [
    "100% Whole Spelt Sourdough",
    "100% Whole Spelt Sourdough with Seeds",
    "Classic Country Sourdough",
    "Country Sourdough with Olives & Lemon Zest",
    "Country Loaf with Onion & Sesame",
    "Sourdough Challah",
    "Ruta Wheat Loaf with Walnuts",
    "Japanese Milk Bread",
    "Sourdough Pizza Base",
    "Khachapuri-Style Pastry, 100% Sourdough",
    "Whole Spelt Crackers",
    "Gluten-Free Crackers",
    "Carrot Cake Loaf with Cream Cheese and Pecans",
    "Giant Brown-Butter Chocolate Chip Cookie",
]


def sort_catalog(products):
    rank = {name: index for index, name in enumerate(CATALOG_ORDER)}
    return sorted(
        products,
        key=lambda product: (rank.get(product.name_en or product.name, len(rank)), product.id or 0),
    )


# Stable catalog keys used to upsert Cloud SQL / local products on each boot.
SEED_PRODUCTS = [
    {
        "slug": "spelt-100",
        "name": "100% Whole Spelt Sourdough",
        "name_en": "100% Whole Spelt Sourdough",
        "name_he": "לחם מחמצת כוסמין מלא 100%",
        "description": "",
        "description_en": "",
        "description_he": "",
        "price": 30.0,
        "image_url": "/static/images/catalog/spelt-100.jpg",
        "ingredients": "Whole spelt flour, water, salt",
        "ingredients_en": "Whole spelt flour, water, salt",
        "ingredients_he": "קמח כוסמין מלא, מים, מלח",
        "fermentation_hours": 30,
    },
    {
        "slug": "spelt-seeded",
        "name": "100% Whole Spelt Sourdough with Seeds",
        "name_en": "100% Whole Spelt Sourdough with Seeds",
        "name_he": "לחם מחמצת כוסמין מלא 100% בתוספת גרעינים",
        "description": "",
        "description_en": "",
        "description_he": "",
        "price": 32.0,
        "image_url": "/static/images/catalog/spelt-seeded.jpg",
        "ingredients": "Whole spelt flour, water, salt, seeds",
        "ingredients_en": "Whole spelt flour, water, salt, seeds",
        "ingredients_he": "קמח כוסמין מלא, מים, מלח, גרעינים",
        "fermentation_hours": 30,
    },
    {
        "slug": "country-classic",
        "name": "Classic Country Sourdough",
        "name_en": "Classic Country Sourdough",
        "name_he": "לחם מחמצת כפרי קלאסי - ללא תוספות",
        "description": "",
        "description_en": "",
        "description_he": "",
        "price": 30.0,
        "image_url": "/static/images/catalog/country-classic.jpg",
        "ingredients": "Wheat flour, water, salt",
        "ingredients_en": "Wheat flour, water, salt",
        "ingredients_he": "קמח חיטה, מים, מלח",
        "fermentation_hours": 30,
    },
    {
        "slug": "country-olive-lemon",
        "name": "Country Sourdough with Olives & Lemon Zest",
        "name_en": "Country Sourdough with Olives & Lemon Zest",
        "name_he": "לחם מחמצת כפרי בתוספת זיתים וגרידת לימון",
        "description": "",
        "description_en": "",
        "description_he": "",
        "price": 30.0,
        "image_url": "/static/images/catalog/country-olive-lemon.jpg",
        "ingredients": "Wheat flour, water, salt, olives, lemon zest",
        "ingredients_en": "Wheat flour, water, salt, olives, lemon zest",
        "ingredients_he": "קמח חיטה, מים, מלח, זיתים, גרידת לימון",
        "fermentation_hours": 30,
    },
    {
        "slug": "country-onion-sesame",
        "name": "Country Loaf with Onion & Sesame",
        "name_en": "Country Loaf with Onion & Sesame",
        "name_he": "לחם כפרי בתוספת בצל וציפוי שומשום",
        "description": "Addictive — you have been warned.",
        "description_en": "Addictive — you have been warned.",
        "description_he": "ממכר — ראו הוזהרתם!",
        "price": 30.0,
        "image_url": "/static/images/catalog/country-onion-sesame.jpg",
        "ingredients": "Wheat flour, water, salt, onion, sesame",
        "ingredients_en": "Wheat flour, water, salt, onion, sesame",
        "ingredients_he": "קמח חיטה, מים, מלח, בצל, שומשום",
        "fermentation_hours": 30,
    },
    {
        "slug": "ruta-walnut",
        "name": "Ruta Wheat Loaf with Walnuts",
        "name_en": "Ruta Wheat Loaf with Walnuts",
        "name_he": "לחם רֻתָּה עם אגוזי מלך",
        "description": "94% whole-grain flour from Ruta wheat, an Israeli landrace, with walnuts.",
        "description_en": "94% whole-grain flour from Ruta wheat, an Israeli landrace, with walnuts.",
        "description_he": "94% קמח מלא מחיטת רותה, זן ארץ־ישראלי, בתוספת אגוזי מלך.",
        "price": 30.0,
        "image_url": "/static/images/catalog/ruta-walnut.jpg",
        "ingredients": "Ruta whole wheat flour, water, salt, walnuts",
        "ingredients_en": "Ruta whole wheat flour, water, salt, walnuts",
        "ingredients_he": "קמח חיטת רותה מלאה, מים, מלח, אגוזי מלך",
        "fermentation_hours": 30,
    },
    {
        "slug": "challah-sourdough",
        "name": "Sourdough Challah",
        "name_en": "Sourdough Challah",
        "name_he": "חלה מחמצת",
        "description": "20% whole flour, no commercial yeast.",
        "description_en": "20% whole flour, no commercial yeast.",
        "description_he": "20% קמח מלא, ללא שמרים תעשתיים.",
        "price": 30.0,
        "image_url": "/static/images/catalog/challah-sourdough.jpg",
        "ingredients": "Wheat flour, whole wheat flour, water, salt (egg wash)",
        "ingredients_en": "Wheat flour, whole wheat flour, water, salt (egg wash)",
        "ingredients_he": "קמח חיטה, קמח מלא, מים, מלח (הברשה בביצה)",
        "fermentation_hours": 24,
    },
    {
        "slug": "japanese-milk",
        "name": "Japanese Milk Bread",
        "name_en": "Japanese Milk Bread",
        "name_he": "לחם חלב יפני",
        "description": "100% sourdough, no commercial yeast. A large sandwich loaf (about 1 kg), cloud-soft and perfect for a generous sandwich. Contains milk and eggs.",
        "description_en": "100% sourdough, no commercial yeast. A large sandwich loaf (about 1 kg), cloud-soft and perfect for a generous sandwich. Contains milk and eggs.",
        "description_he": "100% מחמצת, ללא שמרים תעשייתיים. כיכר קסטן גדולה (כקילו), רכה כענן ומושלמת לכריך מפנק. מכילה חלב וביצים.",
        "price": 42.0,
        "image_url": "/static/images/catalog/japanese-milk.jpg",
        "ingredients": "Wheat flour, milk, eggs, water, salt",
        "ingredients_en": "Wheat flour, milk, eggs, water, salt",
        "ingredients_he": "קמח חיטה, חלב, ביצים, מים, מלח",
        "fermentation_hours": 24,
    },
    {
        "slug": "pizza-base",
        "name": "Sourdough Pizza Base",
        "name_en": "Sourdough Pizza Base",
        "name_he": "תחתיות פיצה 100% מחמצת",
        "description": "Pizza with real tomato sauce and shredded mozzarella (no yeast). It arrives frozen with home-oven instructions.",
        "description_en": "Pizza with real tomato sauce and shredded mozzarella (no yeast). It arrives frozen with home-oven instructions.",
        "description_he": "פיצה עם רוטב מעגבניות אמיתיות ומוצרלה מגורדת (ללא שמרים). הפיצה מגיעה קפואה עם הוראות הכנה לתנור הביתי.",
        "price": 33.0,
        "image_url": "/static/images/catalog/pizza-base.jpg",
        "ingredients": "Wheat flour, water, salt, tomato sauce, mozzarella",
        "ingredients_en": "Wheat flour, water, salt, tomato sauce, mozzarella",
        "ingredients_he": "קמח חיטה, מים, מלח, רוטב עגבניות, מוצרלה",
        "fermentation_hours": 24,
    },
    {
        "slug": "cracker-spelt",
        "name": "Whole Spelt Crackers",
        "name_en": "Whole Spelt Crackers",
        "name_he": "קרקר מ100% כוסמין מלא בתוספת תבלינים",
        "description": "With spices. 200 g pack.",
        "description_en": "With spices. 200 g pack.",
        "description_he": "אריזה של 200 גרם",
        "price": 33.0,
        "image_url": "/static/images/catalog/cracker-spelt.jpg",
        "ingredients": "Whole spelt flour, spices, salt",
        "ingredients_en": "Whole spelt flour, spices, salt",
        "ingredients_he": "קמח כוסמין מלא, תבלינים, מלח",
        "fermentation_hours": 0,
    },
    {
        "slug": "cracker-gf",
        "name": "Gluten-Free Crackers",
        "name_en": "Gluten-Free Crackers",
        "name_he": "קרקר מ100% כוסמת וטף בתוספת תבלינים",
        "description": "100% buckwheat and teff with spices. 200 g pack.",
        "description_en": "100% buckwheat and teff with spices. 200 g pack.",
        "description_he": "אריזה של 200 גרם",
        "price": 36.0,
        "image_url": "/static/images/catalog/cracker-spelt.jpg",
        "ingredients": "Teff flour, green buckwheat, spices, salt",
        "ingredients_en": "Teff flour, green buckwheat, spices, salt",
        "ingredients_he": "קמח טף, כוסמת ירוקה, תבלינים, מלח",
        "fermentation_hours": 0,
    },
    {
        "slug": "cookie-choc-chip",
        "name": "Giant Brown-Butter Chocolate Chip Cookie",
        "name_en": "Giant Brown-Butter Chocolate Chip Cookie",
        "name_he": "עוגיית שוקולד צ׳יפס ענקית",
        "description": "Giant cookie with brown butter, dark chocolate, and Maldon salt.",
        "description_en": "Giant cookie with brown butter, dark chocolate, and Maldon salt.",
        "description_he": "עוגיית שוקולד צ׳יפס ענקית עם חמאה חומה, שוקולד מריר ומלח מלדון.",
        "price": 16.0,
        "image_url": "/static/images/catalog/cookie-choc-chip.jpg",
        "ingredients": "Flour, brown butter, dark chocolate, Maldon salt, sugar, eggs",
        "ingredients_en": "Flour, brown butter, dark chocolate, Maldon salt, sugar, eggs",
        "ingredients_he": "קמח, חמאה חומה, שוקולד מריר, מלח מלדון, סוכר, ביצים",
        "fermentation_hours": 0,
        "counts_toward_capacity": False,
    },
    {
        "slug": "carrot-cake",
        "name": "Carrot Cake Loaf with Cream Cheese and Pecans",
        "name_en": "Carrot Cake Loaf with Cream Cheese and Pecans",
        "name_he": "פס עוגת גזר עם קרם גבינה ופקאן",
        "description": "",
        "description_en": "",
        "description_he": "",
        "price": 50.0,
        "image_url": "/static/images/catalog/carrot-cake.png",
        "ingredients": "Flour, carrot, cream cheese, pecans, eggs, sugar",
        "ingredients_en": "Flour, carrot, cream cheese, pecans, eggs, sugar",
        "ingredients_he": "קמח, גזר, קרם גבינה, פקאן, ביצים, סוכר",
        "fermentation_hours": 0,
        "counts_toward_capacity": False,
    },
    {
        "slug": "khachapuri",
        "name": "Khachapuri-Style Pastry, 100% Sourdough",
        "name_en": "Khachapuri-Style Pastry, 100% Sourdough",
        "name_he": "מאפה בסגנון חאצפורי - 100% מחמצת",
        "description": "Boat-shaped pastry filled with cheeses. Arrives frozen, without an egg, with home-oven instructions.",
        "description_en": "Boat-shaped pastry filled with cheeses. Arrives frozen, without an egg, with home-oven instructions.",
        "description_he": "מאפה סירה במילוי גבינות. מגיע קפוא ללא ביצה עם הוראות הכנה לתנור הביתי.",
        "price": 40.0,
        "image_url": "/static/images/catalog/khachapuri.jpg",
        "ingredients": "Wheat flour, cheeses, water, salt",
        "ingredients_en": "Wheat flour, cheeses, water, salt",
        "ingredients_he": "קמח חיטה, גבינות, מים, מלח",
        "fermentation_hours": 0,
    },
]

# Legacy stand-in names from earlier seeds (matched on name_en or name).
LEGACY_PRODUCT_NAMES = {
    "Country Sourdough",
    "Seeded Miche",
    "Olive & Herb",
    "לחם מחמצת כפרי",
    "כיכר גרעינים",
    "זיתים ועשבי תיבול",
}


def seed_products(db: Session) -> None:
    existing = db.query(Product).all()
    by_en = {(product.name_en or product.name): product for product in existing}
    by_he = {product.name_he: product for product in existing if product.name_he}
    active_keys: set[str] = set()
    fields = (
        "name",
        "name_en",
        "name_he",
        "description",
        "description_en",
        "description_he",
        "ingredients",
        "ingredients_en",
        "ingredients_he",
        "price",
        "image_url",
        "fermentation_hours",
    )

    for record in SEED_PRODUCTS:
        payload = {key: record[key] for key in fields}
        current = by_en.get(record["name_en"]) or by_he.get(record["name_he"])
        if current is None:
            current = Product(
                **payload,
                is_active=True,
                counts_toward_capacity=record.get("counts_toward_capacity", True),
            )
            db.add(current)
        else:
            for key, value in payload.items():
                setattr(current, key, value)
            current.is_active = True
        active_keys.add(record["name_en"])
        active_keys.add(record["name_he"])

    for product in existing:
        labels = {product.name, product.name_en, product.name_he}
        if labels & LEGACY_PRODUCT_NAMES:
            product.is_active = False
            continue
        if (product.name_en or product.name) not in active_keys and (product.name_he or "") not in active_keys:
            # Keep unknown admin-created products active; only retire known legacy stand-ins above.
            pass

    db.commit()
    ensure_admin_user(db)
