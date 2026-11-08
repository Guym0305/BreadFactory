# Technical Design Document: Artisanal Sourdough Bakery Ordering Platform

## 1. Executive Summary & Core Objective

Build a lightweight, highly reliable, direct-to-consumer (DTC) ordering platform for an artisanal sourdough bakery. The platform operates on a pre-order model (no physical store) with direct local deliveries.

Key constraints and design goals:

- **Zero Payment PCI Footprint:** Never handle or store full credit card details.
- **Cost Efficiency:** Zero fixed monthly infrastructure costs ($0 fixed cloud fee via Cloud Run, pay-per-transaction payment gateway via Grow).
- **Simplicity:** SQLite locally, Cloud SQL PostgreSQL in production; Python FastAPI backend, server-rendered or clean SPA/lightweight frontend.
- **Developer-Friendly:** Fully containerized, optimized for Cursor IDE workflows, and auto-deployable to Google Cloud Run via GitHub.

Repository: [https://github.com/Guym0305/BreadFactory.git](https://github.com/Guym0305/BreadFactory.git)

---

## 2. Visual Design System

The storefront should feel like a bakery counter, not a generic shop template. Model the visual style on Poilâne (artisanal, timeless, slow-food heritage) combined with modern DTC minimalism: quiet, material, and confident. Decoration comes from photography, type, and space.

### Color Palette

| Role | Token | Value | Use |
| :--- | :--- | :--- | :--- |
| Background | `--color-parchment` | `#FDFBF7` | Page background. Alternate wash: `#FBF9F5`. |
| Text & strong accents | `--color-espresso` | `#1A1A1A` | Headings, body, icons, borders. Never pure `#000000`. |
| Muted gold | `--color-gold` | `#A68B5B` | Small rules, price, focus rings, primary button hover. |
| Deep olive | `--color-olive` | `#3E4A34` | Primary buttons, slot-selected state, success confirmation. |
| Earth | `--color-clay` | `#C4B8A5` | Hairline dividers, inactive chips, image mats. |

Surfaces stay warm. Gold and olive appear as accents, not large fills. Buttons are olive with parchment text. Links and prices use espresso, with gold only for emphasis.

### Typography

- **Headings:** A classic serif — Playfair Display, with Merriweather as the fallback — to evoke tradition and craft. Use it for the wordmark, section titles, product names, and the delivery-date prompt.
- **Body and UI:** A clean sans-serif — Inter, with Roboto as the fallback — for descriptions, forms, slot pickers, quantities, and the checkout handoff. Mobile order flows must stay crisp at 16px body size.

Load both from a single font stylesheet. Do not mix a third display face.

### Product Imagery & Layout

- Give every product card generous negative space so the catalog reads as a gallery, not a grid of tiles.
- Prefer one loaf per row on small screens and a sparse two-column layout on wide screens. Avoid dense catalogs.
- Support macro photography layouts that can show crumb structure and crust texture at large scale: a full-bleed or near full-bleed image, a short serif name, and the price, with ingredients and fermentation time set in small sans-serif beneath.
- Image mats use parchment or clay. Do not put drop shadows or bright badges on the loaves.

### Order Flow Usability

1. **Date and slot first.** A prominent delivery date and slot selector is the first decision, before product browsing. Capacity and batch limits are visible on the slot itself so a customer never builds a basket for a full bake.
2. **Then the gallery.** Products shown are those available for the chosen slot. Changing the slot recalculates availability before checkout.
3. **Quiet checkout.** The transition into payment is a single focused step: order summary, then the Grow hosted payment page embedded in an iframe. No cross-sells, no extra navigation, no card fields of our own. On return, a parchment confirmation page states the order number, delivery slot, and that payment was received.

---

## 3. Tech Stack Specification

| Component | Technology | Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.11 + FastAPI + Uvicorn/Gunicorn | Fast execution, native async handling, auto OpenAPI docs, lightweight. |
| **Database** | SQLite locally; Cloud SQL PostgreSQL in production (SQLAlchemy ORM) | SQLite for local/tests; Postgres for durable Cloud Run data. |
| **Migrations** | Alembic | Structured schema version control. |
| **Payment Gateway** | Grow (by Meshulam/CardCom) Hosted Checkout / iFrame | $0/month fixed cost, PCI-DSS Level 1 compliant, Apple Pay/Bit support. |
| **Invoicing (Optional)** | Morning (Green Invoice) API | Auto-generates tax receipts upon webhook confirmation. |
| **Containerization** | Docker | Consistent environment between local Cursor dev and Cloud Run. |
| **Hosting & CI/CD** | Google Cloud Run + Cloud Build + GitHub | Zero-downtime deployments, scale-to-zero cost model, high availability. |

---

## 4. System Architecture & Data Flow

The canonical payment notify path is `POST /api/v1/payments/webhook`.

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                 CLIENT BROWSER                                   │
└──────────────┬───────────────────────────────────────────────────▲───────────────┘
               │ 1. Select Delivery Date & Bread Items             │
               │ 2. Initiates Checkout                             │ 6. Order Confirmed
               ▼                                                   │    Redirect
┌──────────────────────────────────────────────┐                   │
│         PYTHON FASTAPI (CLOUD RUN)           │                   │
│                                              │                   │
│ - Validates Item Stock & Delivery Slot       │                   │
│ - Creates Pending Order in DB (SQLite/PG)    │                   │
│ - Calls Grow API to Request Payment URL      │                   │
└──────────────┬───────────────────────────────┘                   │
               │ 3. Returns Hosted Payment URL                     │
               ▼                                                   │
┌──────────────────────────────────────────────────────────────────┴───────────────┐
│                          GROW PAYMENT HOSTED PAGE / IFRAME                       │
│                   (User enters Card Details / Apple Pay / Bit)                   │
└──────────────┬───────────────────────────────────────────────────────────────────┘
               │ 4. Payment Processed
               ▼
┌──────────────────────────────────────────────┐
│           GROW PAYMENT GATEWAY               │
└──────────────┬───────────────────────────────┘
               │ 5. Asynchronous Webhook (POST)
               │    Payload: order_id, transaction_id, status="SUCCESS", amount
               ▼
┌──────────────────────────────────────────────┐         ┌─────────────────────────┐
│  FASTAPI  POST /api/v1/payments/webhook      │────────►│   MORNING INVOICING API │
│                                              │         │  (Generates Receipt)    │
│ - Verifies Webhook Signature                 │         └─────────────────────────┘
│ - Updates Order Status to "PAID"             │
│ - Saves transaction_id to DB                 │
└──────────────────────────────────────────────┘
```

---

## 5. Database Schema & Models

Local and tests use SQLite with WAL mode. Production uses Cloud SQL PostgreSQL via `DATABASE_URL`. SQLite-only pragmas and `BEGIN IMMEDIATE` apply only when the URL starts with `sqlite`.

### Entity Relationship Diagram

- Customer 1 ─── N Order
- Order 1 ─── N OrderItem
- Order 1 ─── 1 PaymentTransaction
- Product 1 ─── N OrderItem

### SQLAlchemy Models (Python Code Target)

```python
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    DELIVERED = "DELIVERED"

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    image_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    ingredients = Column(Text, nullable=True)  # e.g., "Organic spelt flour, water, salt"
    fermentation_hours = Column(Integer, default=30)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_number = Column(String(32), unique=True, nullable=False, index=True)  # e.g., "BAKE-20261101-984"
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT, nullable=False)
    delivery_date = Column(DateTime, nullable=False)
    total_amount = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    payment_url = Column(String(512), nullable=True)  # Hosted Grow page, kept for the checkout iframe
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")
    transaction = relationship("PaymentTransaction", back_populates="order", uselist=False)

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    grow_transaction_id = Column(String(100), nullable=False, index=True)  # Gateway Reference
    amount_charged = Column(Float, nullable=False)
    card_mask = Column(String(20), nullable=True)  # e.g., "****-****-****-4321"
    status = Column(String(50), nullable=False)  # e.g., "SUCCESS", "DECLINED"
    raw_response = Column(Text, nullable=True)  # JSON string for debugging
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="transaction")
```

---

## 6. Grow Payment Gateway Integration Specification

Card data stays on Grow. This application stores only the gateway reference, amount, masked card, status, and the raw webhook payload for debugging.

### Step A: Initiating Payment Session (Backend → Grow API)

When the user clicks "Proceed to Payment", the FastAPI backend sends a payload to the Grow API.

- **Endpoint:** `POST https://api.grow.co.il/v1/page/create` (or the Grow/Meshulam endpoint in use)
- **Headers:** `Authorization: Bearer <GROW_API_KEY>`

```json
{
  "page_code": "YOUR_GROW_PAGE_CODE",
  "user_id": "YOUR_GROW_USER_ID",
  "sum": 150.00,
  "currency": "ILS",
  "cname": "Israel Israeli",
  "email": "israel@example.com",
  "phone": "0501234567",
  "description": "Sourdough Bakery Order BAKE-20261101-984",
  "custom_fields": {
    "order_id": "BAKE-20261101-984"
  },
  "success_url": "https://your-bakery-site.run.app/order-success?order_id=BAKE-20261101-984",
  "failure_url": "https://your-bakery-site.run.app/order-failed",
  "notify_url": "https://your-bakery-site.run.app/api/v1/payments/webhook"
}
```

Grow returns a hosted payment URL (for example `https://grow.co.il/pay/abc123xyz`). The frontend embeds that URL in an iframe on a distraction-free checkout screen. A full-page redirect is acceptable if the iframe is blocked.

### Step B: Asynchronous Webhook Endpoint (Grow → FastAPI)

FastAPI exposes a webhook handler to verify transaction completion. The handler must be idempotent: a repeated SUCCESS notification for an order already marked `PAID` returns success and does not create a second transaction or a second invoice.

```python
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import json

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

@router.post("/webhook")
async def grow_payment_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.form()  # Grow sends form-encoded or JSON POST

    # 1. Extract payment status parameters
    order_number = payload.get("custom_fields[order_id]") or payload.get("order_id")
    grow_tx_id = payload.get("transaction_id") or payload.get("err_id")
    status = payload.get("status")  # e.g., "0" or "SUCCESS"
    amount = float(payload.get("sum", 0.0))
    card_mask = payload.get("card_mask", "****")

    # 2. Fetch order from SQLite
    order = db.query(Order).filter(Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Idempotency check: Skip if already marked as PAID
    if order.status == OrderStatus.PAID:
        return {"status": "already_processed"}

    # 3. Verify and update
    if status in ["0", "SUCCESS", "APPROVED"]:
        order.status = OrderStatus.PAID

        # Save transaction metadata
        transaction = PaymentTransaction(
            order_id=order.id,
            grow_transaction_id=str(grow_tx_id),
            amount_charged=amount,
            card_mask=card_mask,
            status="SUCCESS",
            raw_response=json.dumps(dict(payload))
        )
        db.add(transaction)
        db.commit()

        # Trigger async task to send receipt via Morning API & Notification SMS/Email
        # trigger_morning_invoice(order)

        return {"status": "ok"}
    else:
        order.status = OrderStatus.CANCELLED
        db.commit()
        return {"status": "failed"}
```

Webhook signature verification is required before any status change. Reject unsigned or mismatched payloads.

---

## 7. Dockerfile & Cloud Run Configuration

### Dockerfile

```dockerfile
# Use minimal official Python runtime
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies needed for compilation / SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port 8080 (Google Cloud Run default)
EXPOSE 8080

# Execute Gunicorn with Uvicorn workers
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 -k uvicorn.workers.UvicornWorker app.main:app
```

### requirements.txt

```text
fastapi==0.110.0
uvicorn[standard]==0.28.0
gunicorn==21.2.0
sqlalchemy==2.0.41
alembic==1.13.1
psycopg[binary]==3.2.9
pydantic==2.11.7
pydantic-settings==2.9.1
httpx==0.27.0
python-multipart==0.0.9
jinja2==3.1.3
tzdata==2024.1
```

Local development uses SQLite. Production on Cloud Run should set `DATABASE_URL` to Cloud SQL PostgreSQL via the Cloud Run Cloud SQL connector (Unix socket). Instance: `bread-factory-514112:me-west1:breadfactory`. Example: `postgresql+psycopg://USER:PASSWORD@/bakery?host=/cloudsql/bread-factory-514112:me-west1:breadfactory`. SQLite under `/tmp` on Cloud Run remains ephemeral and is not recommended once orders must survive redeploys.

---

## 8. Project Structure (Optimized for Cursor IDE)

The repository root is this project. Internal layout:

```text
│
├── .github/
│   └── workflows/
│       └── deploy.yml            # Optional GitHub Actions workflow
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app entry point & migrations on startup
│   ├── config.py                 # Pydantic BaseSettings (Env variables)
│   ├── database.py               # Dialect-aware SQLAlchemy engine (SQLite / Postgres)
│   │
│   ├── models/                   # SQLAlchemy ORM Models
│   │   ├── __init__.py
│   │   └── bakery.py
│   │
│   ├── schemas/                  # Pydantic schemas for request/response
│   │   ├── order.py
│   │   └── product.py
│   │
│   ├── api/                      # Route Handlers
│   │   ├── __init__.py
│   │   ├── products.py
│   │   ├── orders.py
│   │   └── payments.py           # Grow webhook & payment initiation
│   │
│   ├── templates/                # Jinja2 HTML Templates (if using SSR)
│   │   ├── index.html
│   │   ├── checkout.html
│   │   └── order_success.html
│   │
│   └── static/                   # CSS, JS, Images
│       ├── css/style.css
│       └── js/checkout.js
│
├── data/
│   └── bakery.db                 # Local SQLite database file (git-ignored)
│
├── .gitignore
├── Dockerfile
├── README.md
├── TECH_DESIGN.md                # This file
└── requirements.txt
```

Templates and CSS implement Section 2. `index.html` opens with the date/slot selector, then the gallery. `checkout.html` is the iframe handoff. `order_success.html` is the confirmation.

---

## 9. Deployment Steps to Google Cloud Run

1. Push code to GitHub:

```bash
git add .
git commit -m "Initial commit: Bakery core architecture"
git branch -M main
git remote add origin https://github.com/Guym0305/BreadFactory.git
git push -u origin main
```

The local repository is already initialized and `origin` already points at that URL. Skip `git init` and `git remote add` if they already exist.

2. Cloud SQL (PostgreSQL) instance:
   - Connection name: `bread-factory-514112:me-west1:breadfactory`
   - Enable the **Cloud SQL Admin API** if needed.
   - Create database `bakery` and a user/password on that instance.

3. Set up Cloud Run in Google Cloud Console:
   - Go to Google Cloud Console → Cloud Run.
   - Click **Create Service**.
   - Select **Continuously deploy from a repository**.
   - Authorize GitHub and select repository `Guym0305/BreadFactory`.
   - Build type: Dockerfile (path `/Dockerfile`).
   - Service name: `bakery-service`.
   - Region: prefer `me-west1` (same as Cloud SQL).
   - Add a **Cloud SQL connection** to `bread-factory-514112:me-west1:breadfactory`.
   - Grant the Cloud Run runtime service account `roles/cloudsql.client`.
   - Environment variables:
     - `GROW_API_KEY` = `<your-key>`
     - `GROW_PAGE_CODE` = `<your-code>`
     - `SESSION_SECRET` = `<strong-secret>`
     - `DATABASE_URL` = `postgresql+psycopg://USER:PASSWORD@/bakery?host=/cloudsql/bread-factory-514112:me-west1:breadfactory`
   - Allow unauthenticated invocations (public access).
   - Click **Create**.

No Cloud SQL Proxy binary is needed in the image when using the Cloud Run connector and Unix socket `host=`. On first boot, Alembic migrations create tables. Local `data/bakery.db` is not copied to Cloud SQL.

**Persistence check after deploy:** register a user or place an order, redeploy, and confirm the data is still present.

Do not commit Grow keys, Morning credentials, or `data/bakery.db`.
