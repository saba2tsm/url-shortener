import os
import logging
import sys
from config import config_by_name
from urllib.parse import urlparse

from flask import Flask, jsonify, request, redirect, abort
from flask_cors import CORS
from flask_migrate import Migrate
from dotenv import load_dotenv

from extensions import db
from models import Url, Click
from utils import generate_short_code
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

app = Flask(__name__)

env_name = os.environ.get("FLASK_ENV", "development")
app.config.from_object(config_by_name[env_name])

if env_name == "production" and app.config["SECRET_KEY"] == "dev-key-change-me":
    raise RuntimeError("SECRET_KEY must be set via environment variable in production")

CORS(app, origins=app.config["CORS_ORIGIN"])


logging.basicConfig(
    level=logging.DEBUG if app.config["DEBUG"] else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

db.init_app(app)
migrate = Migrate(app, db)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=app.config["RATELIMIT_STORAGE_URI"],
)

def is_valid_url(url):
    if len(url) > 2048:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if parsed.netloc == request.host:
        return False  # block shortening a link that points back at ourselves
    return True



@app.route("/health")
def health_check():
    return jsonify({"status": "ok"})


@app.route("/health/db")
def db_health_check():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "database": str(e)}), 500


@app.route("/api/urls", methods=["POST"])
@limiter.limit("10 per minute")
def create_short_url():
    data = request.get_json(silent=True) or {}
    original_url = data.get("original_url", "").strip()

    if not original_url or not is_valid_url(original_url):
        return jsonify({"error": "A valid original_url (http/https) is required"}), 400

    for _ in range(5):
        code = generate_short_code()
        if not Url.query.filter_by(short_code=code).first():
            break
    else:
        return jsonify({"error": "Could not generate a unique code, please retry"}), 500

    url = Url(short_code=code, original_url=original_url)
    db.session.add(url)
    db.session.commit()
    logger.info(f"Created short URL: {code} -> {original_url}")

    return jsonify({
        "id": url.id,
        "short_code": url.short_code,
        "short_url": request.host_url + url.short_code,
        "original_url": url.original_url,
        "created_at": url.created_at.isoformat(),
    }), 201

@app.route("/api/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    url = Url.query.get(url_id)
    if not url:
        return jsonify({"error": "URL not found"}), 404

    short_code = url.short_code
    db.session.delete(url)
    db.session.commit()
    logger.info(f"Deleted URL id={url_id} short_code={short_code}")
    return jsonify({"message": "Deleted"}), 200

@app.route("/<short_code>")
def redirect_to_original(short_code):
    url = Url.query.filter_by(short_code=short_code, is_active=True).first()
    if not url:
        abort(404)

    click = Click(
        url_id=url.id,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        user_agent=request.headers.get("User-Agent"),
        referrer=request.headers.get("Referer"),
    )
    db.session.add(click)
    db.session.commit()
    logger.info(f"Click recorded: short_code={short_code} url_id={url.id}")

    return redirect(url.original_url)

@app.route("/api/urls")
def list_urls():
    results = (
        db.session.query(Url, func.count(Click.id).label("click_count"))
        .outerjoin(Click, Click.url_id == Url.id)
        .group_by(Url.id)
        .order_by(func.count(Click.id).desc())
        .all()
    )
    return jsonify([
        {
            "id": url.id,
            "short_code": url.short_code,
            "short_url": request.host_url + url.short_code,
            "original_url": url.original_url,
            "created_at": url.created_at.isoformat(),
            "is_active": url.is_active,
            "click_count": click_count,
        }
        for url, click_count in results
    ])


@app.route("/api/analytics/summary")
def analytics_summary():
    today = datetime.now(timezone.utc).date()
    return jsonify({
        "total_urls": Url.query.count(),
        "total_clicks": Click.query.count(),
        "clicks_today": Click.query.filter(func.date(Click.clicked_at) == today).count(),
    })


@app.route("/api/analytics/clicks-daily")
def clicks_daily():
    days = request.args.get("days", default=7, type=int)
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=days - 1)

    results = (
        db.session.query(
            func.date(Click.clicked_at).label("day"),
            func.count(Click.id).label("count"),
        )
        .filter(func.date(Click.clicked_at) >= start_day)
        .group_by("day")
        .all()
    )
    counts_by_day = {row.day.isoformat(): row.count for row in results}

    return jsonify([
        {
            "date": (start_day + timedelta(days=i)).isoformat(),
            "clicks": counts_by_day.get((start_day + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(days)
    ])

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Rate limit exceeded", "detail": str(e.description)}), 429


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)