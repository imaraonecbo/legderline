import os
from fastapi.testclient import TestClient

# Ensure deterministic isolated local DB for tests.
os.environ["LEDGERLINE_DB_PATH"] = "/tmp/ledgerline-test.db"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""
os.environ["LEDGERLINE_ADMIN_TOKEN"] = "test-admin-token"
from ledgerline.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_home_contains_price_and_intake():
    response = client.get("/")
    assert response.status_code == 200
    assert "$600" in response.text
    assert 'action="/intake"' in response.text

def test_intake_saved_without_checkout():
    response = client.post("/intake", data={
        "name": "Test User", "business": "Test Shop", "email": "owner@example.com",
        "website": "https://example.com", "need": "Automate appointment reminders for customers"
    })
    assert response.status_code == 202
    assert "Checkout is not enabled yet" in response.text

def test_checkout_fails_closed_without_credentials():
    response = client.get("/checkout?lead_id=1")
    assert response.status_code == 503

def test_admin_requires_token():
    assert client.get("/admin/summary").status_code == 401
    response = client.get("/admin/summary", headers={"Authorization": "Bearer test-admin-token"})
    assert response.status_code == 200
    assert "paid_orders" in response.json()
