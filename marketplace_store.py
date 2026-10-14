"""SQLite-backed marketplace API foundation for SMITHX.

This module intentionally uses Python's standard library so the existing
Flask service can run it without adding an ORM dependency. Set
SMITHX_DB_PATH to choose a persistent database file in production.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request
from seller_auth import require_seller

marketplace_bp = Blueprint("marketplace", __name__, url_prefix="/api/marketplace")


def _db_path():
    return os.environ.get("SMITHX_DB_PATH", str(Path("instance") / "smithx_marketplace.sqlite3"))


def _connect():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            seller_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Other',
            price_minor INTEGER NOT NULL CHECK(price_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'KES',
            inventory INTEGER NOT NULL DEFAULT 0 CHECK(inventory >= 0),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id);
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            currency TEXT NOT NULL,
            subtotal_minor INTEGER NOT NULL CHECK(subtotal_minor >= 0),
            status TEXT NOT NULL,
            items_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
        """)


@marketplace_bp.before_request
def ensure_schema():
    init_db()


def _money_to_minor(value):
    # Prices are expressed in major currency units in API requests and stored
    # as integer minor units to avoid floating-point arithmetic.
    if isinstance(value, bool):
        raise ValueError("price must be a non-negative number")
    amount = round(float(value) * 100)
    if amount < 0:
        raise ValueError("price must be a non-negative number")
    return amount


def _product_json(row):
    item = dict(row)
    item["price"] = item.pop("price_minor") / 100
    return item


@marketplace_bp.get("/health")
def marketplace_health():
    return jsonify({"status": "ok", "service": "SMITHX marketplace API", "storage": "sqlite"})


@marketplace_bp.get("/products")
def list_products():
    seller_id = request.args.get("seller_id", "").strip()
    with _connect() as db:
        if seller_id:
            rows = db.execute(
                "SELECT * FROM products WHERE seller_id = ? ORDER BY created_at DESC",
                (seller_id,),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    return jsonify({"products": [_product_json(row) for row in rows]})


@marketplace_bp.post("/products")
@require_seller
def create_product():
    data = request.get_json(silent=True) or {}
    seller_id = g.seller_id
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    try:
        price_minor = _money_to_minor(data.get("price", 0))
        inventory_raw = data.get("inventory", 0)
        if isinstance(inventory_raw, bool) or str(inventory_raw).strip() == "":
            raise ValueError("inventory must be a non-negative integer")
        inventory = int(inventory_raw)
        if inventory < 0 or float(inventory_raw) != inventory:
            raise ValueError("inventory must be a non-negative integer")
    except (TypeError, ValueError, OverflowError):
        return jsonify({"error": "price and inventory must be valid non-negative values"}), 400
    title = title[:200]
    description = str(data.get("description", "")).strip()[:10000]
    category = str(data.get("category", "Other")).strip()[:100] or "Other"
    currency = str(data.get("currency", "KES")).strip().upper()
    if not __import__("re").fullmatch(r"[A-Z]{3}", currency):
        return jsonify({"error": "currency must be a three-letter ISO-style code"}), 400

    product_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    values = (
        product_id, seller_id, title,
        description,
        category,
        price_minor, currency,
        inventory, created_at,
    )
    with _connect() as db:
        db.execute(
            """INSERT INTO products
            (id, seller_id, title, description, category, price_minor, currency, inventory, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return jsonify({"product": _product_json(row)}), 201


@marketplace_bp.post("/orders")
def create_order():
    """Create a testable pending order; this endpoint does not charge money."""
    data = request.get_json(silent=True) or {}
    customer_id = str(data.get("customer_id", "")).strip()
    requested_items = data.get("items")
    if not customer_id or not isinstance(requested_items, list) or not requested_items:
        return jsonify({"error": "customer_id and a non-empty items list are required"}), 400

    quantities = {}
    for item in requested_items:
        if not isinstance(item, dict):
            return jsonify({"error": "each item must contain product_id and quantity"}), 400
        product_id = str(item.get("product_id", "")).strip()
        try:
            quantity = int(item.get("quantity", 0))
        except (TypeError, ValueError):
            quantity = 0
        if not product_id or quantity < 1:
            return jsonify({"error": "each item requires a product_id and positive integer quantity"}), 400
        quantities[product_id] = quantities.get(product_id, 0) + quantity

    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    normalized_items = []
    subtotal_minor = 0
    currencies = set()

    with _connect() as db:
        for product_id, quantity in quantities.items():
            row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if row is None:
                return jsonify({"error": "product not found", "product_id": product_id}), 404
            if row["inventory"] < quantity:
                return jsonify({"error": "insufficient inventory", "product_id": product_id}), 409
            currencies.add(row["currency"])
            line_total = row["price_minor"] * quantity
            subtotal_minor += line_total
            normalized_items.append({
                "product_id": row["id"], "title": row["title"],
                "seller_id": row["seller_id"], "quantity": quantity,
                "unit_price": row["price_minor"] / 100,
                "line_total": line_total / 100, "currency": row["currency"],
            })

        if len(currencies) != 1:
            return jsonify({"error": "all items in an order must use the same currency"}), 400
        currency = next(iter(currencies))
        for item in normalized_items:
            db.execute(
                "UPDATE products SET inventory = inventory - ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )
        db.execute(
            """INSERT INTO orders (id, customer_id, currency, subtotal_minor, status, items_json, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (order_id, customer_id, currency, subtotal_minor, json.dumps(normalized_items), now),
        )
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    return jsonify({
        "order": {
            "id": order["id"], "customer_id": order["customer_id"],
            "currency": order["currency"], "subtotal": order["subtotal_minor"] / 100,
            "status": order["status"], "items": json.loads(order["items_json"]),
            "created_at": order["created_at"],
            "payment_status": "not_processed",
        }
    }), 201


@marketplace_bp.get("/orders/<order_id>")
def get_order(order_id):
    with _connect() as db:
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return jsonify({"error": "order not found"}), 404
    return jsonify({"order": {
        "id": row["id"], "customer_id": row["customer_id"],
        "currency": row["currency"], "subtotal": row["subtotal_minor"] / 100,
        "status": row["status"], "items": json.loads(row["items_json"]),
        "created_at": row["created_at"], "payment_status": "not_processed",
    }})
