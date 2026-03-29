import os
import re
import sqlite3
import secrets
import requests
import anthropic
import stripe
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from mailer import generate_review_png, send_review_email

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY     = os.getenv("GOOGLE_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

PLACES_BASE     = "https://maps.googleapis.com/maps/api/place"
PLACES_NEW_BASE = "https://places.googleapis.com/v1/places"

_base = os.path.dirname(os.path.abspath(__file__))
_sibling = os.path.normpath(os.path.join(_base, "..", "frontend"))
FRONTEND_DIR = _sibling if os.path.exists(_sibling) else os.path.join(_base, "frontend")

# ── Stripe ─────────────────────────────────────────────────────────────────────
stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ONETIME_PRICE_CENTS     = 499   # $4.99
SUBSCRIPTION_PRICE_ID   = os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID", "price_1TChiUK1B0iiSk9yMzGfQb0q")
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            email                   TEXT NOT NULL,
            place_id                TEXT NOT NULL,
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            status                  TEXT DEFAULT 'pending',
            last_swept_at           TEXT,
            created_at              TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_reviews (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            subscriber_id  INTEGER NOT NULL,
            review_key     TEXT NOT NULL,
            sent_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(subscriber_id, review_key)
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


def _extract_place_id_from_url(url):
    """
    Try to extract a place identifier from a Google Maps URL.
    Returns (id, id_type) where id_type is 'place_id' or 'data_id', or (None, None).
    """
    # ?place_id=... or &query_place_id=...
    m = re.search(r'(?:place_id|query_place_id)=([A-Za-z0-9_\-]+)', url)
    if m:
        return m.group(1), 'place_id'
    # data=!...!1sChIJ... encoded in the URL path
    m = re.search(r'!1s(ChIJ[A-Za-z0-9_\-]+)', url)
    if m:
        return m.group(1), 'place_id'
    # data=!...!1s0xHEX:0xHEX (data_id format)
    m = re.search(r'!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)', url)
    if m:
        return m.group(1), 'data_id'
    return None, None


def _extract_name_from_maps_url(url):
    """Extract business name from a /maps/place/Name/@ style URL."""
    m = re.search(r'/maps/place/([^/@]+)', url)
    if m:
        return re.sub(r'\+', ' ', m.group(1)).replace('%20', ' ')
    return None


@app.route("/api/search", methods=["GET"])
def search_places():
    """
    Accept a business name or Google Maps URL and return up to 5 matching businesses.
    Return: { results: [{ place_id, name, address }] }
    """
    query = request.args.get("query", "").strip()
    if not query or len(query) < 3:
        return jsonify({"results": []})

    # ── Google Maps URL: try direct place lookup first ─────────────────────
    if "google.com/maps" in query or "maps.google.com" in query:
        extracted_id, id_type = _extract_place_id_from_url(query)
        if extracted_id and id_type == 'place_id':
            details = _fetch_place_details(extracted_id, fields="name,formatted_address,place_id")
            if details:
                print(f"[search] maps_url → place_id={extracted_id!r} name={details.get('name')!r}", flush=True)
                return jsonify({"results": [{
                    "place_id": extracted_id,
                    "name": details.get("name", ""),
                    "address": details.get("formatted_address", ""),
                }]})
        elif extracted_id and id_type == 'data_id' and SERPAPI_KEY:
            info = _serpapi_place_info(extracted_id)
            if info:
                print(f"[search] maps_url → data_id={extracted_id!r} name={info.get('name')!r}", flush=True)
                return jsonify({"results": [{
                    "place_id": extracted_id,
                    "name": info.get("name", ""),
                    "address": info.get("address", ""),
                }]})
        # Fall back to extracting name and running text search
        name = _extract_name_from_maps_url(query)
        if name:
            query = name
            print(f"[search] maps_url → extracted name={query!r}", flush=True)

    # ── Normal text search ─────────────────────────────────────────────────
    params = {"query": query, "key": API_KEY}
    resp = requests.get(f"{PLACES_BASE}/textsearch/json", params=params, timeout=10)
    data = resp.json()
    print(f"[search] query={query!r} status={data.get('status')!r} count={len(data.get('results', []))}", flush=True)
    for r in data.get("results", [])[:5]:
        print(f"  → {r.get('place_id')} | {r.get('name')} | {r.get('formatted_address')}", flush=True)

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

    # Place metadata (name, aggregate rating, total count)
    if place_id.startswith("0x") and SERPAPI_KEY:
        info = _serpapi_place_info(place_id)
        if info is None:
            return jsonify({"error": "Could not fetch business details."}), 502
        details = {"name": info["name"], "rating": info["rating"], "user_ratings_total": info["total"]}
    else:
        details = _fetch_place_details(place_id, fields="name,rating,user_ratings_total")
        if details is None:
            return jsonify({"error": "Could not fetch business details."}), 502

    # Reviews — prefer SerpAPI, fall back to legacy Places API
    reviews = _fetch_reviews_serpapi(place_id) if SERPAPI_KEY else None

    if reviews is None:
        legacy = _fetch_place_details(
            place_id,
            fields="reviews",
            reviews_sort="newest",
        )
        if legacy is None:
            return jsonify({"error": "Could not fetch reviews."}), 502
        raw = legacy.get("reviews", [])
        reviews = [{
            "author":        r.get("author_name", "Anonymous"),
            "rating":        r.get("rating", 5),
            "text":          r.get("text", "").strip(),
            "timestamp":     r.get("time", 0),
            "relative_time": r.get("relative_time_description", ""),
        } for r in raw]

    print(f"[reviews] total_fetched={len(reviews)}", flush=True)

    five_star = [r for r in reviews if r.get("text") and r.get("rating") == 5]
    print(f"[reviews] after_5star_filter={len(five_star)}", flush=True)

    if len(five_star) <= 1:
        four_star = [r for r in reviews if r.get("text") and r.get("rating") == 4]
        out = five_star + four_star
        print(f"[reviews] sparse_fallback: added {len(four_star)} four-star reviews", flush=True)
    else:
        out = five_star

    return jsonify({
        "name":           details.get("name", ""),
        "overall_rating": details.get("rating", 0),
        "total_reviews":  details.get("user_ratings_total", 0),
        "reviews":        out,
    })


@app.route("/api/email-graphics", methods=["POST"])
def email_graphics():
    """
    Send user-rendered review graphics to a given email address.
    Body: { email, business_name, graphics: [{ author, png_b64 }] }
    """
    import base64
    body         = request.get_json(silent=True) or {}
    to_email     = body.get("email", "").strip()
    business_name = body.get("business_name", "your business").strip()
    graphics     = body.get("graphics", [])

    if not to_email or not graphics:
        return jsonify({"error": "email and graphics are required"}), 400

    reviews_with_images = []
    for g in graphics[:10]:  # cap at 10
        raw_b64 = g.get("png_b64", "")
        if raw_b64.startswith("data:"):
            raw_b64 = raw_b64.split(",", 1)[-1]
        try:
            png_bytes = base64.b64decode(raw_b64)
        except Exception:
            continue
        reviews_with_images.append({
            "author":    g.get("author", "reviewer"),
            "text":      "",
            "png_bytes": png_bytes,
        })

    if not reviews_with_images:
        return jsonify({"error": "No valid graphics"}), 400

    try:
        from mailer import send_review_email
        send_review_email(to_email, business_name, reviews_with_images)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/create-checkout-subscription", methods=["POST"])
def create_checkout_subscription():
    """Create a Stripe Checkout session for the $9/month Auto subscription."""
    body     = request.get_json(silent=True) or {}
    email    = body.get("email", "").strip()
    place_id = body.get("place_id", "").strip()

    if not email or not place_id:
        return jsonify({"error": "email and place_id are required"}), 400

    base_url = SITE_URL or request.host_url.rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            customer_email=email,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": SUBSCRIPTION_PRICE_ID, "quantity": 1}],
            metadata={"place_id": place_id, "email": email},
            success_url=f"{base_url}/?auto_success=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/",
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
        mode       = sess.get("mode")

        conn = get_db()
        try:
            if mode == "subscription":
                place_id       = (sess.get("metadata") or {}).get("place_id", "")
                subscription_id = sess.get("subscription", "")
                customer_id     = sess.get("customer", "")
                conn.execute(
                    """INSERT OR IGNORE INTO subscribers
                       (email, place_id, stripe_customer_id, stripe_subscription_id, status)
                       VALUES (?, ?, ?, ?, 'active')""",
                    (email, place_id, customer_id, subscription_id)
                )
                conn.commit()
            else:
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


SWEEP_SECRET = os.getenv("SWEEP_SECRET", "")

@app.route("/api/sweep", methods=["POST"])
def sweep():
    """
    Daily cron endpoint. Checks every active subscriber for new 5-star reviews
    and emails graphics for any that haven't been sent yet.
    Protected by SWEEP_SECRET header.
    """
    if SWEEP_SECRET and request.headers.get("X-Sweep-Secret") != SWEEP_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    try:
        subscribers = conn.execute(
            "SELECT * FROM subscribers WHERE status = 'active'"
        ).fetchall()
    finally:
        conn.close()

    results = []
    for sub in subscribers:
        sub_id   = sub["id"]
        email    = sub["email"]
        place_id = sub["place_id"]

        details = _fetch_place_details(
            place_id,
            fields="name,reviews",
            reviews_sort="newest",
        )
        if not details:
            results.append({"email": email, "status": "fetch_failed"})
            continue

        biz_name = details.get("name", "your business")
        raw      = details.get("reviews", [])
        five_star = [r for r in raw if r.get("rating") == 5 and r.get("text", "").strip()]

        conn = get_db()
        try:
            new_reviews = []
            for r in five_star:
                key = f"{r.get('author_name','')}:{r.get('time', 0)}"
                exists = conn.execute(
                    "SELECT 1 FROM sent_reviews WHERE subscriber_id=? AND review_key=?",
                    (sub_id, key)
                ).fetchone()
                if not exists:
                    new_reviews.append(r)

            if not new_reviews:
                results.append({"email": email, "status": "no_new_reviews"})
                conn.execute(
                    "UPDATE subscribers SET last_swept_at=datetime('now') WHERE id=?",
                    (sub_id,)
                )
                conn.commit()
                continue

            # Generate graphics and send email
            reviews_with_images = []
            for r in new_reviews[:5]:  # cap at 5 per email
                text = r.get("text", "").strip()
                png  = generate_review_png(text[:300], r.get("author_name", "A guest"), biz_name)
                reviews_with_images.append({
                    "author":    r.get("author_name", "A guest"),
                    "text":      text,
                    "png_bytes": png,
                })

            send_review_email(email, biz_name, reviews_with_images)

            # Mark as sent
            for r in new_reviews[:5]:
                key = f"{r.get('author_name','')}:{r.get('time', 0)}"
                conn.execute(
                    "INSERT OR IGNORE INTO sent_reviews (subscriber_id, review_key) VALUES (?, ?)",
                    (sub_id, key)
                )
            conn.execute(
                "UPDATE subscribers SET last_swept_at=datetime('now') WHERE id=?",
                (sub_id,)
            )
            conn.commit()
            results.append({"email": email, "status": "sent", "count": len(reviews_with_images)})
        except Exception as e:
            results.append({"email": email, "status": "error", "detail": str(e)})
        finally:
            conn.close()

    return jsonify({"swept": len(subscribers), "results": results})


def _approx_timestamp_from_relative(relative):
    """Approximate a Unix timestamp from a string like '2 months ago'."""
    now = datetime.now(timezone.utc)
    if not relative:
        return int(now.timestamp())
    s = relative.lower()
    m = re.search(r'(\d+)', s)
    n = int(m.group(1)) if m else 1
    try:
        if 'minute' in s:
            return int((now - timedelta(minutes=n)).timestamp())
        if 'hour'   in s:
            return int((now - timedelta(hours=n)).timestamp())
        if 'day'    in s:
            return int((now - timedelta(days=n)).timestamp())
        if 'week'   in s:
            return int((now - timedelta(weeks=n)).timestamp())
        if 'month'  in s:
            return int((now - timedelta(days=n * 30)).timestamp())
        if 'year'   in s:
            return int((now - timedelta(days=n * 365)).timestamp())
    except Exception:
        pass
    return int(now.timestamp())


def _serpapi_id_param(place_id):
    """Return the correct SerpAPI parameter key for a given place identifier."""
    if place_id.startswith("0x"):
        return "data_id"
    return "place_id"


def _serpapi_place_info(place_id):
    """
    Fetch place metadata (name, address, rating, review count) from SerpAPI.
    Returns a dict or None on failure.
    """
    id_key = _serpapi_id_param(place_id)
    params = {
        "engine":  "google_maps_reviews",
        id_key:    place_id,
        "hl":      "en",
        "api_key": SERPAPI_KEY,
    }
    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = resp.json()
    except Exception:
        return None
    if "error" in data:
        return None
    info = data.get("place_info", {})
    return {
        "name":    info.get("title", ""),
        "address": info.get("address", ""),
        "rating":  info.get("rating", 0),
        "total":   info.get("reviews", 0),
    }


def _fetch_reviews_serpapi(place_id, max_reviews=40):
    """
    Fetch reviews via SerpAPI google_maps_reviews engine, following pagination.
    Returns list of normalized review dicts or None on failure.
    """
    id_key = _serpapi_id_param(place_id)
    all_reviews = []
    base_params = {
        "engine":   "google_maps_reviews",
        id_key:     place_id,
        "sort_by":  "newestFirst",
        "hl":       "en",
        "api_key":  SERPAPI_KEY,
    }
    params = dict(base_params)
    page = 0

    while len(all_reviews) < max_reviews:
        try:
            resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
            data = resp.json()
        except Exception as e:
            print(f"[serpapi] request failed (page {page}): {e}", flush=True)
            break

        if "error" in data:
            print(f"[serpapi] error (page {page}): {data['error']}", flush=True)
            if page == 0:
                return None
            break

        raw = data.get("reviews", [])
        print(f"[serpapi] page={page} fetched={len(raw)}", flush=True)
        all_reviews.extend(raw)

        next_token = data.get("serpapi_pagination", {}).get("next_page_token")
        if not next_token or not raw:
            break

        params = {**base_params, "next_page_token": next_token}
        page += 1

    print(f"[serpapi] place_id={place_id!r} total={len(all_reviews)}", flush=True)
    def _ts(r):
        iso = r.get("iso_date", "")
        if iso:
            try:
                return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
            except Exception:
                pass
        return _approx_timestamp_from_relative(r.get("date", ""))

    return [{
        "author":        r.get("user", {}).get("name", "Anonymous"),
        "rating":        r.get("rating", 5),
        "text":          r.get("snippet", "").strip(),
        "timestamp":     _ts(r),
        "relative_time": r.get("date", ""),
    } for r in all_reviews]


def _fetch_place_details(place_id, fields, **extra_params):
    """Legacy Places API helper. Returns the 'result' dict or None."""
    params = {"place_id": place_id, "fields": fields, "key": API_KEY, **extra_params}
    resp = requests.get(f"{PLACES_BASE}/details/json", params=params, timeout=10)
    data = resp.json()
    if data.get("status") != "OK":
        return None
    return data.get("result", {})


def _fetch_place_details_new(place_id, field_mask):
    """
    Places API (New) helper — returns up to 53 reviews.
    field_mask: comma-separated list e.g. 'displayName,rating,userRatingCount,reviews'
    Returns a normalized dict with keys: name, rating, user_ratings_total, reviews (legacy shape).
    """
    headers = {
        "X-Goog-Api-Key":   API_KEY,
        "X-Goog-FieldMask": field_mask,
    }
    resp = requests.get(f"{PLACES_NEW_BASE}/{place_id}", headers=headers, timeout=10)
    if resp.status_code != 200:
        print(f"[places_new] status={resp.status_code} body={resp.text[:200]}", flush=True)
        return None

    data = resp.json()

    # Normalize to the same shape the rest of the code expects
    reviews_raw = data.get("reviews", [])
    reviews = []
    for r in reviews_raw:
        # publishTime is ISO 8601 — convert to Unix epoch for date filtering
        pub = r.get("publishTime", "")
        try:
            # Strip fractional seconds before parsing (fromisoformat pre-3.11 chokes on them)
            pub_clean = re.sub(r'\.\d+Z$', 'Z', pub).replace("Z", "+00:00")
            ts = int(datetime.fromisoformat(pub_clean).timestamp())
        except Exception:
            ts = 0
        reviews.append({
            "author_name":               r.get("authorAttribution", {}).get("displayName", "Anonymous"),
            "rating":                    r.get("rating", 5),
            "text":                      r.get("text", {}).get("text", "").strip(),
            "time":                      ts,
            "relative_time_description": r.get("relativePublishTimeDescription", ""),
        })

    return {
        "name":               data.get("displayName", {}).get("text", ""),
        "rating":             data.get("rating", 0),
        "user_ratings_total": data.get("userRatingCount", 0),
        "reviews":            reviews,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
