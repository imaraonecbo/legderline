import os, json, hmac, hashlib, sqlite3, secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("LEDGERLINE_DB_PATH", str(BASE_DIR / "ledgerline.db"))
PRICE_CENTS = 60000
CURRENCY = "usd"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.getenv("LEDGERLINE_ADMIN_TOKEN", "")

app = FastAPI(title="Ledgerline", version="1.0.0", description="Business operations automation service intake and checkout")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            business TEXT NOT NULL,
            email TEXT NOT NULL,
            website TEXT DEFAULT '',
            need TEXT NOT NULL,
            consent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            stripe_session_id TEXT UNIQUE,
            customer_email TEXT,
            amount_total INTEGER,
            currency TEXT,
            payment_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            fulfilled_at TEXT,
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            received_at TEXT NOT NULL
        )""")

init_db()

class Intake(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    business: str = Field(min_length=2, max_length=160)
    email: EmailStr
    website: str = Field(default="", max_length=300)
    need: str = Field(min_length=10, max_length=3000)
    consent: bool = False

@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "reachable", "checkout_configured": bool(STRIPE_SECRET_KEY)}
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "checkout_ready": bool(STRIPE_SECRET_KEY), "price": "$600", "error": None})

@app.post("/intake")
def intake(request: Request, name: str = Form(...), business: str = Form(...), email: str = Form(...), website: str = Form(""), need: str = Form(...), consent: Optional[str] = Form(None)):
    payload = Intake(name=name.strip(), business=business.strip(), email=email.strip(), website=website.strip(), need=need.strip(), consent=consent == "yes")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute("INSERT INTO leads(name,business,email,website,need,consent,created_at) VALUES(?,?,?,?,?,?,?)",
            (payload.name, payload.business, str(payload.email), payload.website, payload.need, int(payload.consent), now))
        lead_id = cur.lastrowid
    if not STRIPE_SECRET_KEY:
        return templates.TemplateResponse(request=request, name="thanks.html", context={"request": request, "lead_id": lead_id, "checkout_ready": False}, status_code=202)
    return RedirectResponse(url=f"/checkout?lead_id={lead_id}", status_code=303)

@app.get("/checkout")
def checkout(lead_id: int):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Checkout is not enabled yet. Configure STRIPE_SECRET_KEY and PUBLIC_BASE_URL.")
    with db() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Intake not found")
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=lead["email"],
            line_items=[{"price_data": {"currency": CURRENCY, "product_data": {"name": "Ledgerline Business Automation Setup", "description": "Defined onboarding and automation setup package; deliverables agreed before work begins."}, "unit_amount": PRICE_CENTS}, "quantity": 1}],
            metadata={"lead_id": str(lead_id), "product": "ledgerline_setup"},
            success_url=f"{PUBLIC_BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{PUBLIC_BASE_URL}/payment/cancelled?lead_id={lead_id}")
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO orders(lead_id,stripe_session_id,customer_email,amount_total,currency,payment_status,created_at) VALUES(?,?,?,?,?,?,?)",
                (lead_id, session.id, lead["email"], PRICE_CENTS, CURRENCY, "pending", datetime.now(timezone.utc).isoformat()))
        return RedirectResponse(session.url, status_code=303)
    except HTTPException:
        raise
    except Exception as exc:
        # Never expose provider credentials or raw exception details to customers.
        raise HTTPException(status_code=502, detail="Could not create checkout session. Please contact support.") from exc

@app.get("/payment/success", response_class=HTMLResponse)
def payment_success(request: Request, session_id: str):
    # Browser return is not proof of payment; webhook updates the authoritative status.
    with db() as conn:
        order = conn.execute("SELECT payment_status FROM orders WHERE stripe_session_id=?", (session_id,)).fetchone()
    status = order["payment_status"] if order else "pending_verification"
    return templates.TemplateResponse(request=request, name="payment.html", context={"request": request, "heading": "Thank you", "message": "We are verifying your payment securely. Fulfilment starts only after the payment provider confirms it.", "status": status})

@app.get("/payment/cancelled", response_class=HTMLResponse)
def payment_cancelled(request: Request, lead_id: int):
    return templates.TemplateResponse(request=request, name="payment.html", context={"request": request, "heading": "Checkout cancelled", "message": "No payment was recorded by this return page. You can contact us if you want to resume.", "status": "cancelled"})

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None)):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    payload = await request.body()
    try:
        import stripe
        event = stripe.Webhook.construct_event(payload, stripe_signature or "", STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature or payload")
    event_id, event_type = event["id"], event["type"]
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        existing = conn.execute("SELECT event_id FROM webhook_events WHERE event_id=?", (event_id,)).fetchone()
        if existing:
            return {"received": True, "duplicate": True}
        conn.execute("INSERT INTO webhook_events(event_id,event_type,received_at) VALUES(?,?,?)", (event_id,event_type,now))
        if event_type == "checkout.session.completed":
            obj = event["data"]["object"]
            # Mark paid only if Stripe reports paid and the amount/currency match this fixed product.
            if obj.get("payment_status") == "paid" and obj.get("amount_total") == PRICE_CENTS and obj.get("currency") == CURRENCY:
                conn.execute("UPDATE orders SET payment_status='paid' WHERE stripe_session_id=?", (obj.get("id"),))
        elif event_type == "checkout.session.async_payment_succeeded":
            obj = event["data"]["object"]
            if obj.get("amount_total") == PRICE_CENTS and obj.get("currency") == CURRENCY:
                conn.execute("UPDATE orders SET payment_status='paid' WHERE stripe_session_id=?", (obj.get("id"),))
        elif event_type == "checkout.session.async_payment_failed":
            obj = event["data"]["object"]
            conn.execute("UPDATE orders SET payment_status='failed' WHERE stripe_session_id=?", (obj.get("id"),))
    return {"received": True}

@app.get("/admin/summary")
def admin_summary(authorization: Optional[str] = Header(None)):
    if not ADMIN_TOKEN or not authorization or not hmac.compare_digest(authorization.removeprefix("Bearer "), ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    with db() as conn:
        leads = conn.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]
        paid = conn.execute("SELECT COUNT(*) n FROM orders WHERE payment_status='paid'").fetchone()["n"]
        pending = conn.execute("SELECT COUNT(*) n FROM orders WHERE payment_status='pending'").fetchone()["n"]
    return {"leads": leads, "paid_orders": paid, "pending_orders": pending, "gross_paid_usd": round(paid * PRICE_CENTS / 100, 2)}

@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(request=request, name="privacy.html", context={"request": request})
