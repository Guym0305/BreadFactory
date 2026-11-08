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
| `DATABASE_URL` | Local default is SQLite (`sqlite:///./data/bakery.db`). On Cloud Run use Cloud SQL PostgreSQL (see below). |
| `PUBLIC_BASE_URL` | Public origin Grow uses for success, failure, and webhook URLs. |
| `SLOT_CAPACITY` | Loaves available on each bake morning. Default 20. |
| `SESSION_SECRET` | Signs the login session cookie. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Seeded admin account (`Admin` / `Admin` by default). |
| `GROW_API_KEY` | Bearer token for the hosted payment request. |
| `GROW_PAGE_CODE` | Grow page code. |
| `GROW_USER_ID` | Grow user id. |
| `GROW_API_URL` | Payment-session endpoint. Default follows `TECH_DESIGN.md`. |
| `GROW_WEBHOOK_SECRET` | HMAC-SHA256 secret. The raw webhook body must match `X-Grow-Signature`. Required once `GROW_API_KEY` is set. |

## Cloud SQL (PostgreSQL) on Cloud Run

Local development and tests keep SQLite. Production should use Cloud SQL so users and orders survive redeploys. No Cloud SQL Proxy binary is required in the image when using the Cloud Run connector.

Cloud SQL **PostgreSQL** instance (already created):

```text
bread-factory-514112:me-west1:breadfactory
```

1. On the instance: **Databases** → create database `bakery` (if missing).
2. On the instance: **Users** → create a Postgres user + password (or use the one you already set).
3. Cloud Run → your service → **Edit & deploy new revision**:
   - **Connections** → add Cloud SQL: `bread-factory-514112:me-west1:breadfactory`
   - Runtime service account needs **Cloud SQL Client**
   - **Variables** → set:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@/bakery?host=/cloudsql/bread-factory-514112:me-west1:breadfactory
```

Replace `USER` and `PASSWORD` with that Postgres user. Deploy. On startup Alembic creates the tables.

Existing local `data/bakery.db` (and any prior `/tmp` SQLite on Cloud Run) is not copied to Cloud SQL automatically.

### After deploy — persistence check

1. Register a user or place an order on the live service.
2. Redeploy the same or a new revision.
3. Confirm the user/order is still present. If data vanishes, the service is still on ephemeral SQLite or the Cloud SQL connection/env is wrong.

## Tests

```bash
pip install -r requirements.txt
python tests/test_checkout.py
```

The checkout script forces `DATABASE_URL` to a local SQLite file and does not need Postgres.

Bake mornings follow the weekly Friday delivery cycle. Ordering closes Wednesday. An unpaid hold still applies for payment-pending edge cases.

Morning invoicing is not connected.