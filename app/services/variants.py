VARIANTS = ("regular", "vegan")
CHALLAH_NAME_EN = "Sourdough Challah"

_LABELS = {
    "he": {"regular": "רגילה", "vegan": "טבעונית"},
    "en": {"regular": "Regular", "vegan": "Vegan"},
}


def offers_version(product) -> bool:
    name = getattr(product, "name_en", None) or getattr(product, "name", None) or ""
    return name == CHALLAH_NAME_EN


def clean_variant(product, raw) -> str | None:
    """A challah line is regular or vegan. Every other product has no version."""
    if product is None or not offers_version(product):
        return None
    value = str(raw or "").strip().lower()
    if value not in VARIANTS:
        return "regular"
    return value


def variant_label(variant: str | None, lang: str) -> str:
    labels = _LABELS["he" if lang == "he" else "en"]
    return labels.get(variant or "", "")


def line_title(product, variant: str | None, lang: str) -> str:
    if product is None:
        name = "לחם" if lang == "he" else "Loaf"
    elif lang == "he":
        name = product.name_he or product.name
    else:
        name = product.name_en or product.name
    label = variant_label(variant, lang)
    if label:
        return f"{name} · {label}"
    return name
