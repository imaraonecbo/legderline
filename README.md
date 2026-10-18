# Ledgerline

Ledgerline is a small-business workflow automation service offer with a $600 fixed setup package. This repository is a **starter MVP**, not a claim that the business is already earning revenue.

## Current features

- Public service landing page describing a bounded setup package.
- Customer workflow-intake form with validation and SQLite persistence.
- Optional, separate marketing-contact consent checkbox.
- Stripe Checkout integration for a fixed $600 USD payment, disabled unless credentials are configured.
- Signed Stripe webhook verification and idempotent event handling; payment is marked paid only after provider-confirmed status, amount and currency match.
- Admin summary endpoint protected by a bearer token.
- Health endpoint, privacy notice, Render Blueprint, and basic tests.

## Not included / not yet production-verified

- Automatic delivery of completed automation work; each job still requires a defined scope and human acceptance/delivery process.
- Email sending, CRM integration, automated lead scraping, or bulk outreach.
- Legal review of service terms/privacy text, verified business contact details, or a retention/deletion process.
- A real customer, successful live payment, or verified revenue.

## Local run (PowerShell or terminal)

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn ledgerline.main:app --reload
```

Open `http://127.0.0.1:8000`. Run tests with `pytest -q`.

## Deploy on Render

1. Create a new GitHub repository named `ledgerline` under the intended account and push this project.
2. In Render, create a Blueprint from that repository and review `render.yaml` before applying it. This Blueprint creates a separate `ledgerline` service and persistent disk; it does not modify `autoops-hub-staging`.
3. Set `PUBLIC_BASE_URL` to the actual Render URL.
4. Set Stripe **test** credentials in Render first. Configure the Stripe webhook endpoint as `https://YOUR-HOST/webhooks/stripe` and subscribe to `checkout.session.completed`, `checkout.session.async_payment_succeeded`, and `checkout.session.async_payment_failed`. Set the signing secret as `STRIPE_WEBHOOK_SECRET`.
5. Confirm the health endpoint, test intake, use Stripe test cards, and verify webhook-driven status before enabling live credentials.
6. Switch to live Stripe keys only after reviewing the offer, terms, refund policy, tax obligations, privacy notice, and fulfilment capacity.

## Important configuration

- `LEDGERLINE_DB_PATH` should point to `/var/data/ledgerline.db` when using the included Render disk. Do not use an ephemeral filesystem for customer/order data.
- `LEDGERLINE_ADMIN_TOKEN` must be a strong random secret. Use `Authorization: Bearer <token>` for `/admin/summary`.
- Never commit `.env` or provider secrets.
- The checkout return URL does not prove payment. The signed webhook is authoritative.
- The $600 scope must be confirmed with each buyer before accepting payment; do not promise business outcomes or income guarantees.

## Current status

Code prototype assembled; deployment and provider integration are not yet verified. No real customer or revenue is claimed.
