"""Seller authentication and server-side analytics foundation.

Set SMITHX_AUTH_SECRET to a long random secret before enabling seller accounts.
This module deliberately does not expose seller analytics without a valid seller token.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

seller_bp = Blueprint("seller_auth", __name__, url_prefix="/api/marketplace/seller")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOKEN_MAX_AGE = 60 * 60 * 24 * 7


def _db_path():
    return os.environ.get("SMITHX_DB_PATH", str(Path("instance") / "smithx_marketplace.sqlite3"))


def _connect():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _serializer():
    secret = os.environ.get("SMITHX_AUTH_SECRET", "").strip()
    if len(secret) < 32:
        return None
    return URLSafeTimedSerializer(secret, salt="smithx-seller-auth-v1")


def require_seller(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        serializer = _serializer()
        if serializer is None:
            return jsonify({"error": "Seller authentication is not configured on the server"}), 503
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Bearer seller token required"}), 401
        try:
            payload = serializer.loads(header[7:].strip(), max_age=TOKEN_MAX_AGE)
        except SignatureExpired:
            return jsonify({"error": "Seller token expired; sign in again"}), 401
        except BadSignature:
            return jsonify({"error": "Invalid seller token"}), 401
        if payload.get("role") != "seller" or not payload.get("seller_id"):
            return jsonify({"error": "Seller token required"}), 403
        g.seller_id = str(payload["seller_id"])
        return fn(*args, **kwargs)
    return wrapped


def init_auth_schema():
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS seller_accounts (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_view_events (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            visitor_key TEXT NOT NULL,
            viewed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_product_views_product_time
            ON product_view_events(product_id, viewed_at);
        CREATE INDEX IF NOT EXISTS idx_product_views_visitor_time
            ON product_view_events(visitor_key, viewed_at);
        """)


@seller_bp.before_request
def ensure_auth_schema():
    init_auth_schema()


@seller_bp.post("/register")
def register_seller():
    serializer = _serializer()
    if serializer is None:
        return jsonify({"error": "Set SMITHX_AUTH_SECRET to at least 32 characters before enabling seller accounts"}), 503
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify({"error": "A valid email address is required"}), 400
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        return jsonify({"error": "Password must be between 12 and 256 characters"}), 400
    # A random ID avoids using an email address as a public seller identifier.
    import uuid
    seller_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as db:
            db.execute(
                "INSERT INTO seller_accounts (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (seller_id, email, generate_password_hash(password), now),
            )
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists"}), 409
    token = serializer.dumps({"role": "seller", "seller_id": seller_id})
    return jsonify({"seller": {"id": seller_id, "email": email}, "token": token, "token_type": "Bearer", "expires_in": TOKEN_MAX_AGE}), 201


@seller_bp.post("/login")
def login_seller():
    serializer = _serializer()
    if serializer is None:
        return jsonify({"error": "Seller authentication is not configured on the server"}), 503
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if not email or not isinstance(password, str):
        return jsonify({"error": "Email and password are required"}), 400
    with _connect() as db:
        seller = db.execute("SELECT * FROM seller_accounts WHERE email = ?", (email,)).fetchone()
    if seller is None or not check_password_hash(seller["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    token = serializer.dumps({"role": "seller", "seller_id": seller["id"]})
    return jsonify({"seller": {"id": seller["id"], "email": seller["email"]}, "token": token, "token_type": "Bearer", "expires_in": TOKEN_MAX_AGE})


@seller_bp.get("/analytics")
@require_seller
def seller_analytics():
    # Import lazily to avoid a module import cycle.
    from marketplace_store import _connect as marketplace_connect, init_db
    init_db()
    since = request.args.get("since", "30d")
    if since not in {"today", "7d", "30d", "all"}:
        return jsonify({"error": "since must be today, 7d, 30d, or all"}), 400
    now = datetime.now(timezone.utc)
    if since == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif since == "7d":
        from datetime import timedelta
        start = (now - timedelta(days=7)).isoformat()
    elif since == "30d":
        from datetime import timedelta
        start = (now - timedelta(days=30)).isoformat()
    else:
        start = ""
    with marketplace_connect() as db:
        product_rows = db.execute("SELECT id, inventory FROM products WHERE seller_id = ?", (g.seller_id,)).fetchall()
        product_ids = {row["id"] for row in product_rows}
        order_rows = db.execute("SELECT id, status, items_json, created_at FROM orders ORDER BY created_at DESC").fetchall()
        view_query = """
            SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_key) AS visitors
            FROM product_view_events v
            JOIN products p ON p.id = v.product_id
            WHERE p.seller_id = ? AND (? = '' OR v.viewed_at >= ?)
        """
        view_row = db.execute(view_query, (g.seller_id, start, start)).fetchone()
        views = int(view_row["views"] or 0)
        unique_visitors = int(view_row["visitors"] or 0)
        products_count = len(product_rows)
        inventory_count = sum(int(row["inventory"]) for row in product_rows)
    orders_count = 0
    units = 0
    revenue_minor = 0
    currency_totals = {}
    top = {}
    for order in order_rows:
        if start and order["created_at"] < start:
            continue
        if str(order["status"]).lower() in {"cancelled", "canceled", "refunded"}:
            continue
        import json
        try:
            items = json.loads(order["items_json"])
        except (TypeError, ValueError):
            continue
        seller_items = [item for item in items if str(item.get("seller_id", "")) == g.seller_id]
        if not seller_items:
            continue
        orders_count += 1
        for item in seller_items:
            quantity = int(item.get("quantity", 0) or 0)
            unit_price_minor = item.get("unit_price_minor")
            if unit_price_minor is None:
                unit_price_minor = round(float(item.get("unit_price", 0) or 0) * 100)
            amount = max(0, int(unit_price_minor)) * max(0, quantity)
            units += max(0, quantity)
            currency = str(item.get("currency") or "KES")
            currency_totals[currency] = currency_totals.get(currency, 0) + amount
            product_id = str(item.get("product_id", ""))
            name = str(item.get("title") or "Product")
            entry = top.setdefault(product_id or name, {"product_id": product_id, "title": name, "units": 0, "sales_minor": 0, "currency": currency})
            entry["units"] += max(0, quantity)
            entry["sales_minor"] += amount
    currency = max(currency_totals, key=currency_totals.get) if currency_totals else "KES"
    return jsonify({
        "period": since,
        "currency": currency,
        "products_listed": products_count,
        "inventory_units": inventory_count,
        "orders": orders_count,
        "units_sold_in_orders": units,
        "gross_order_value": round(currency_totals.get(currency, 0) / 100, 2),
        "product_views": views,
        "unique_visitors": unique_visitors,
        "top_products": sorted(top.values(), key=lambda item: item["sales_minor"], reverse=True)[:5],
        "profit_estimate": None,
        "profit_note": "Not available until product costs and paid-order/payment-fee data are recorded. These figures count orders except cancelled/refunded statuses; they are not verified paid sales."
    })


@seller_bp.post("/events/product-view")
def record_product_view():
    """Record a coarse product view; visitor_key should be a random, short-lived ID, not personal data."""
    import uuid
    data = request.get_json(silent=True) or {}
    product_id = str(data.get("product_id", "")).strip()
    visitor_key = str(data.get("visitor_key", "")).strip()
    if not product_id or len(product_id) > 100:
        return jsonify({"error": "product_id is required"}), 400
    if not visitor_key or len(visitor_key) < 16 or len(visitor_key) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", visitor_key):
        return jsonify({"error": "visitor_key must be a random opaque identifier between 16 and 128 characters"}), 400
    from marketplace_store import _connect as marketplace_connect, init_db
    init_db()
    with marketplace_connect() as db:
        exists = db.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
        if exists is None:
            return jsonify({"error": "product not found"}), 404
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        db.execute(
            "INSERT INTO product_view_events (id, product_id, visitor_key, viewed_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), product_id, visitor_key, now),
        )
    return jsonify({"recorded": True}), 202
