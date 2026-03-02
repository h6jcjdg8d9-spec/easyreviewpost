import os
import re
import requests
import anthropic
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("GOOGLE_API_KEY")

PLACES_BASE = "https://maps.googleapis.com/maps/api/place"

_base = os.path.dirname(__file__)
_candidate = os.path.join(_base, "..", "frontend")
FRONTEND_DIR = _candidate if os.path.exists(_candidate) else os.path.join(_base, "frontend")


@app.route("/debug")
def debug():
    return {"frontend_dir": FRONTEND_DIR, "exists": os.path.exists(FRONTEND_DIR)}


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


def extract_place_id_from_url(url):
    """
    Google Maps URLs sometimes embed the Place ID directly.
    It appears after '!1s' and starts with 'ChIJ'.
    e.g. ...!1sChIJN1t_tDeuEmsRUsoyG83frY4!2m2!...
    """
    match = re.search(r"!1s(ChIJ[^!&]+)", url)
    return match.group(1) if match else None


def extract_query_from_url(url):
    """
    Pull the human-readable business name out of a Google Maps URL
    so we can fall back to a text search.
    e.g. /maps/place/Joe%27s+Pizza/@...
    """
    match = re.search(r"/maps/place/([^/@?]+)", url)
    if match:
        raw = match.group(1)
        # URL-decode + replace + with space
        return requests.utils.unquote(raw).replace("+", " ")
    return None


@app.route("/api/lookup", methods=["POST"])
def lookup_place():
    """
    Accept a Google Business Profile / Maps URL.
    Return: { place_id, name, address, total_reviews, overall_rating }
    """
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()

    if not url:
        return jsonify({"error": "url is required"}), 400

    # --- Attempt 1: extract Place ID directly from the URL ---
    place_id = extract_place_id_from_url(url)

    if place_id:
        # Validate and enrich with a lightweight Details call
        details = _fetch_place_details(place_id, fields="name,formatted_address,rating,user_ratings_total")
        if details:
            return jsonify({
                "place_id": place_id,
                "name": details.get("name", ""),
                "address": details.get("formatted_address", ""),
                "overall_rating": details.get("rating", 0),
                "total_reviews": details.get("user_ratings_total", 0),
            })

    # --- Attempt 2: text search using the business name in the URL ---
    query = extract_query_from_url(url)
    if not query:
        return jsonify({"error": "Could not parse business name from URL. Try pasting the full Google Maps URL."}), 400

    resp = requests.get(
        f"{PLACES_BASE}/findplacefromtext/json",
        params={
            "input": query,
            "inputtype": "textquery",
            "fields": "place_id,name,formatted_address,rating,user_ratings_total",
            "key": API_KEY,
        },
        timeout=10,
    )
    data = resp.json()

    if data.get("status") != "OK" or not data.get("candidates"):
        return jsonify({"error": f"Business not found (status: {data.get('status')}). Try a different URL."}), 404

    candidate = data["candidates"][0]
    return jsonify({
        "place_id": candidate["place_id"],
        "name": candidate.get("name", ""),
        "address": candidate.get("formatted_address", ""),
        "overall_rating": candidate.get("rating", 0),
        "total_reviews": candidate.get("user_ratings_total", 0),
    })


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

    reviews = [
        {
            "author": r.get("author_name", "Anonymous"),
            "rating": r.get("rating", 5),
            "text": r.get("text", "").strip(),
            "timestamp": r.get("time", 0),          # Unix epoch — used for date filtering
            "relative_time": r.get("relative_time_description", ""),
        }
        for r in details.get("reviews", [])
        if r.get("text", "").strip()                # skip reviews with no text
    ]

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
