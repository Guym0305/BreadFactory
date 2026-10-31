from pathlib import Path
import random

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "images"
OUT.mkdir(parents=True, exist_ok=True)


def holes(rng, count, fill, min_r, max_r, y_max=780):
    parts = []
    for _ in range(count):
        cx = rng.randint(30, 1170)
        cy = rng.randint(30, y_max)
        rx = rng.randint(min_r, max_r)
        ry = max(8, int(rx * rng.uniform(0.58, 0.92)))
        opacity = rng.choice(["0.82", "0.9", "0.96"])
        parts.append(
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" fill-opacity="{opacity}"/>'
        )
    return "".join(parts)


def write(name, body):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900" role="img">'
        f"{body}</svg>"
    )
    (OUT / name).write_text(svg, encoding="utf-8")


rng = random.Random(7)
write(
    "country-crumb.svg",
    '<rect width="1200" height="900" fill="#E7C99A"/>'
    + holes(rng, 10, "#FBF6EC", 70, 120)
    + holes(rng, 46, "#F7F1E4", 16, 64)
    + '<rect y="790" width="1200" height="110" fill="#8C5A32"/>'
    + '<rect y="782" width="1200" height="14" fill="#C8924A"/>',
)

rng = random.Random(11)
seeds = []
for _ in range(80):
    cx = rng.randint(20, 1180)
    cy = rng.randint(20, 770)
    color = rng.choice(["#2C261C", "#E6D3A1", "#6B4E32"])
    rx = rng.randint(4, 11)
    seeds.append(
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{max(3, rx - 2)}" fill="{color}" transform="rotate({rng.randint(0, 180)} {cx} {cy})"/>'
    )
write(
    "seeded-crumb.svg",
    '<rect width="1200" height="900" fill="#C6A15C"/>'
    + holes(rng, 8, "#F3E6C8", 48, 90)
    + holes(rng, 40, "#EFE0C0", 12, 36)
    + "".join(seeds)
    + '<rect y="790" width="1200" height="110" fill="#4A3424"/>'
    + '<rect y="782" width="1200" height="12" fill="#8C6A3A"/>',
)

rng = random.Random(19)
olives = []
for _ in range(18):
    cx = rng.randint(80, 1120)
    cy = rng.randint(70, 740)
    olives.append(
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rng.randint(18, 34)}" ry="{rng.randint(12, 20)}" fill="#3E4A34" transform="rotate({rng.randint(0, 180)} {cx} {cy})"/>'
    )
write(
    "olive-crumb.svg",
    '<rect width="1200" height="900" fill="#E4D2AE"/>'
    + holes(rng, 8, "#FBF6EC", 60, 100)
    + holes(rng, 36, "#F6EFE0", 14, 48)
    + "".join(olives)
    + '<rect y="790" width="1200" height="110" fill="#7A6240"/>'
    + '<rect y="782" width="1200" height="12" fill="#C4B8A5"/>',
)
print(OUT)
