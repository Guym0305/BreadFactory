# Bread Factory

Direct pre-order site for an artisanal sourdough bakery. Customers choose a delivery morning, then a loaf. Card details stay on Grow.

The visual and technical specification is in `TECH_DESIGN.md`.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

Copy `.env.example` to `.env` when you have Grow credentials. With `GROW_API_KEY` empty, checkout uses a local stand-in that confirms the order without collecting a card.

## Configuration

| Variable | Purpose |
| :--- | :--- |
| `DATABASE_URL` | SQLite path. Cloud Run can use `sqlite:////tmp/bakery.db` until a persistent volume is attached. |
| `PUBLIC_BASE_URL` | Public origin Grow uses for success, failure, and webhook URLs. |
| `SLOT_CAPACITY` | Loaves available on each bake morning. Default 20. |
| `GROW_API_KEY` | Bearer token for the hosted payment request. |
| `GROW_PAGE_CODE` | Grow page code. |
| `GROW_USER_ID` | Grow user id. |
| `GROW_API_URL` | Payment-session endpoint. Default follows `TECH_DESIGN.md`. |
| `GROW_WEBHOOK_SECRET` | HMAC-SHA256 secret. The raw webhook body must match `X-Grow-Signature`. Required once `GROW_API_KEY` is set. |

Bake mornings are Tuesday through Saturday, shown for the next six open days. Ordering closes for the same day at 18:00 Asia/Jerusalem. An unpaid order holds its loaves for 30 minutes.

Morning invoicing is not connected.
