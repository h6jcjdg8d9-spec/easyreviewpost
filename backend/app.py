import os
import re
import sqlite3
import secrets
import requests
import anthropic
import stripe
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("GOOGLE_API_KEY")

PLACES_BASE = "https://maps.googleapis.com/maps/api/place"

_base = os.path.dirname(os.path.abspath(__file__))
_sibling = os.path.normpath(os.path.join(_base, "..", "frontend"))
FRONTEND_DIR = _sibling if os.path.exists(_sibling) else os.path.join(_base, "frontend")

# ── Stripe ─────────────────────────────────────────────────────────────────────
stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ONETIME_PRICE_CENTS     = 999   # $9.99
# Foundation placeholder for future subscription tier
SUBSCRIPTION_PRICE_ID   = os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID", "price_placeholder")
# Canonical public URL — set SITE_URL=https://easyreviewpost.com in Render env vars.
# Falls back to request.host_url inside the route if not set.
SITE_URL                = os.getenv("SITE_URL", "").rstrip("/")

# ── SQLite ─────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", os.path.join("/tmp", "tokens.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_range_tokens (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            token             TEXT UNIQUE NOT NULL,
            email             TEXT,
            stripe_session_id TEXT UNIQUE,
            tier              TEXT DEFAULT 'onetime',
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

@app.before_request
def ensure_db():
    """Initialize DB on first request instead of at import time."""
    app.before_request_funcs[None].remove(ensure_db)
    init_db()


@app.route("/debug")
def debug():
    return {"frontend_dir": FRONTEND_DIR, "exists": os.path.exists(FRONTEND_DIR)}


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/api/search", methods=["GET"])
def search_places():
    """
    Accept a query string and return up to 5 matching businesses.
    Return: { results: [{ place_id, name, address }] }
    """
    query = request.args.get("query", "").strip()
    if not query or len(query) < 3:
        return jsonify({"results": []})

    params = {
        "query": query,
        "key": API_KEY,
    }
    resp = requests.get(f"{PLACES_BASE}/textsearch/json", params=params, timeout=10)
    data = resp.json()
    print(f"[search] query={query!r} status={data.get('status')!r} count={len(data.get('results', []))}", flush=True)

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return jsonify({"error": "Search failed"}), 502

    results = [
        {
            "place_id": r["place_id"],
            "name": r.get("name", ""),
            "address": r.get("formatted_address", ""),
        }
        for r in data.get("results", [])[:5]
    ]
    return jsonify({"results": results})


@app.route("/api/reviews", methods=["POST"])
def get_reviews():
    """
    Accept a place_id.
    Return: { name, overall_rating, total_reviews, reviews: [...] }
    Each review: { author, rating, text, timestamp, relative_time }
    """
    body = request.get_json(silent=True) or {}
    place_id = body.get("place_id", "").strip()

    if not place_id:
        return jsonify({"error": "place_id is required"}), 400

    details = _fetch_place_details(
        place_id,
        fields="name,rating,user_ratings_total,reviews",
        reviews_sort="newest",
    )

    if details is None:
        return jsonify({"error": "Could not fetch reviews from Google."}), 502

    raw = details.get("reviews", [])
    print(f"[reviews] total_from_google={len(raw)}, ratings={[r.get('rating') for r in raw]}", flush=True)

    reviews = [
        {
            "author": r.get("author_name", "Anonymous"),
            "rating": r.get("rating", 5),
            "text": r.get("text", "").strip(),
            "timestamp": r.get("time", 0),          # Unix epoch — used for date filtering
            "relative_time": r.get("relative_time_description", ""),
        }
        for r in raw
        if r.get("text", "").strip() and r.get("rating") == 5
    ]
    print(f"[reviews] after_5star_filter={len(reviews)}", flush=True)

    return jsonify({
        "name": details.get("name", ""),
        "overall_rating": details.get("rating", 0),
        "total_reviews": details.get("user_ratings_total", 0),
        "reviews": reviews,
    })


@app.route("/api/excerpt", methods=["POST"])
def get_excerpt():
    """
    Feed a review's full text to Claude and get back the most compelling
    1-2 sentence shareable quote. Falls back to sentence-split if Claude
    is unavailable.
    """
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()

    if not text or len(text) < 80:
        return jsonify({"excerpt": text})

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    "Extract the single most compelling, shareable 1-2 sentence quote "
                    "from this Google review. Return only the quote text — no quotation "
                    "marks, no preamble. Prefer specific praise, vivid details, or "
                    "emotional moments over generic statements.\n\n"
                    f"Review: {text}"
                ),
            }],
        )
        excerpt = message.content[0].text.strip().strip('"').strip("'")
        return jsonify({"excerpt": excerpt})
    except Exception:
        sentences = re.findall(r"[^.!?]+[.!?]+", text)
        fallback = " ".join(sentences[:2]).strip() if sentences else text
        return jsonify({"excerpt": fallback or text})


@app.route("/api/create-checkout-onetime", methods=["POST"])
def create_checkout_onetime():
    """Create a Stripe Checkout session for the $9.99 custom-date-range one-time unlock."""
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": ONETIME_PRICE_CENTS,
                    "product_data": {
                        "name": "Custom Date Range — easyreviewpost",
                        "description": "Pull reviews from any date range. One-time purchase, yours forever.",
                    },
                },
                "quantity": 1,
            }],
            success_url=f"{SITE_URL or request.host_url.rstrip('/')}/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{SITE_URL or request.host_url.rstrip('/')}/",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/unlock-session", methods=["POST"])
def unlock_session():
    """
    Called by the frontend after Stripe redirects back with ?session_id=...
    Verifies payment, generates a token, stores it, and returns it so the
    frontend can set it as a cookie.
    """
    body       = request.get_json(silent=True) or {}
    session_id = body.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if session.payment_status != "paid":
        return jsonify({"error": "Payment not completed"}), 402

    email = (session.customer_details or {}).get("email", "") or ""

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT token FROM custom_range_tokens WHERE stripe_session_id = ?",
            (session_id,)
        ).fetchone()
        if row:
            return jsonify({"token": row["token"]})

        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO custom_range_tokens (token, email, stripe_session_id, tier) VALUES (?, ?, ?, ?)",
            (token, email, session_id, "onetime")
        )
        conn.commit()
        return jsonify({"token": token})
    finally:
        conn.close()


@app.route("/api/stripe-webhook", methods=["POST"], strict_slashes=False)
def stripe_webhook():
    """
    Stripe webhook listener — backup path for checkout.session.completed.
    Stores email for future automation feature even if unlock-session was
    already called.
    """
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        sess       = event["data"]["object"]
        session_id = sess["id"]
        email      = (sess.get("customer_details") or {}).get("email", "") or ""

        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id FROM custom_range_tokens WHERE stripe_session_id = ?",
                (session_id,)
            ).fetchone()
            if not existing:
                token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT OR IGNORE INTO custom_range_tokens (token, email, stripe_session_id, tier) VALUES (?, ?, ?, ?)",
                    (token, email, session_id, "onetime")
                )
                conn.commit()
        finally:
            conn.close()

    return jsonify({"status": "ok"})


@app.route("/api/stripe-webhook/", methods=["POST"])
def stripe_webhook_slash():
    """Catch trailing-slash variant that Render's routing layer may redirect to."""
    return stripe_webhook()


def _fetch_place_details(place_id, fields, **extra_params):
    """Shared helper for Place Details API calls. Returns the 'result' dict or None."""
    params = {"place_id": place_id, "fields": fields, "key": API_KEY, **extra_params}
    resp = requests.get(f"{PLACES_BASE}/details/json", params=params, timeout=10)
    data = resp.json()
    if data.get("status") != "OK":
        return None
    return data.get("result", {})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
