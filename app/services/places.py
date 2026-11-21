"""Towns we deliver to, and the self-pickup points, from the about page."""

from app.i18n import get_lang, t
from app.services.auth import normalize_address
from app.services.errors import CheckoutError


class Place:
    def __init__(self, place_id: str, he: str, en: str) -> None:
        self.id = place_id
        self.he = he
        self.en = en

    def label(self, lang: str | None = None) -> str:
        chosen = lang or get_lang()
        return self.he if chosen == "he" else self.en


# Settlements named on the about page as delivery towns.
DELIVERY_CITIES = (
    Place("maale-hahamisha", "מעלה החמישה", "Ma’ale HaHamisha"),
    Place("kiryat-anavim", "קריית ענבים", "Kiryat Anavim"),
    Place("beit-nekofa", "בית נקופה", "Beit Nekofa"),
    Place("neve-ilan", "נווה אילן", "Neve Ilan"),
    Place("yad-hashmona", "יד השמונה", "Yad HaShmona"),
    Place("shoeva", "שואבה", "Sho’eva"),
    Place("shoresh", "שורש", "Shoresh"),
    Place("har-adar", "הר אדר", "Har Adar"),
    Place("mevaseret-zion", "מבשרת ציון", "Mevaseret Zion"),
)

# Pickup points named on the about page.
PICKUP_POINTS = (
    Place("neve-ilan-etz-harimon", "נווה אילן (רחוב עץ הרימון 75)", "Neve Ilan (Etz HaRimon 75)"),
    Place("kiryat-anavim-pickup", "קריית ענבים", "Kiryat Anavim"),
    Place("yehuda-winery", "יקב יהודה במושב שורש", "Yehuda Winery in Moshav Shoresh"),
    Place("mevaseret-harotem", "מבשרת ציון (רחוב הרותם 15)", "Mevaseret Zion (HaRotem 15)"),
)

_DELIVERY = {place.id: place for place in DELIVERY_CITIES}
_PICKUP = {place.id: place for place in PICKUP_POINTS}


def address_form_fields(address: str) -> dict[str, str]:
    """Turn a stored delivery or pickup line back into cart form fields."""
    text = (address or "").strip()
    if not text or text == "-":
        return {}
    for marker in ("משלוח · ", "Delivery · "):
        if text.startswith(marker):
            place, street = _split_place(text[len(marker) :], DELIVERY_CITIES)
            fields = {"fulfillment": "delivery", "street_address": street}
            if place is not None:
                fields["delivery_city"] = place.id
            return fields
    for marker in ("איסוף עצמי · ", "Pickup · "):
        if text.startswith(marker):
            place, _street = _split_place(text[len(marker) :], PICKUP_POINTS)
            if place is None:
                return {"fulfillment": "pickup"}
            return {"fulfillment": "pickup", "pickup_point": place.id}
    return {"fulfillment": "delivery", "street_address": text}


def _split_place(rest: str, places: tuple[Place, ...]) -> tuple[Place | None, str]:
    ranked = sorted(places, key=lambda place: max(len(place.he), len(place.en)), reverse=True)
    for place in ranked:
        for label in (place.he, place.en):
            if rest == label:
                return place, ""
            prefix = f"{label}, "
            if rest.startswith(prefix):
                return place, rest[len(prefix) :]
    return None, rest


def registration_address(
    fulfillment: str,
    delivery_city: str,
    pickup_point: str,
    street_address: str = "",
) -> str:
    """Turn the registration choice into the customer address stored on the account."""
    kind = (fulfillment or "").strip()
    if kind == "delivery":
        place = _DELIVERY.get((delivery_city or "").strip())
        if place is None:
            raise CheckoutError(t("choose_city"))
        street = normalize_address(street_address)
        return f"{t('fulfillment_delivery')} · {place.label()}, {street}"
    if kind == "pickup":
        place = _PICKUP.get((pickup_point or "").strip())
        if place is None:
            raise CheckoutError(t("choose_pickup"))
        return f"{t('fulfillment_pickup')} · {place.label()}"
    raise CheckoutError(t("choose_fulfillment"))
