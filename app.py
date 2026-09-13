"""Photosite storefront application.

Run locally with:
    flask --app app run --debug
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from base64 import b64decode
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

import razorpay
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from notifications import is_email_configured, notify_new_order

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE = DATA_DIR / "photosite.db"
ALLOWED_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp"}

FRAME_SIZES = {
    "6x8": {"label": "6 × 8 in", "price": 899},
    "8x10": {"label": "8 × 10 in", "price": 1199},
    "12x16": {"label": "12 × 16 in", "price": 1499},
    "16x20": {"label": "16 × 20 in", "price": 1999},
}
FRAME_COLORS = {
    "walnut": "Warm walnut",
    "oak": "Soft oak",
    "charcoal": "Charcoal",
    "brass": "Golden brass",
}
PURPOSES = {
    "family", "friends", "religious", "gifts", "wedding", "birthday",
    "anniversary", "wall-art", "certificate", "custom",
}
PRODUCTS = {
    "everyday": {"name": "The Everyday", "description": "Classic wood · 6 colours", "price": 899},
    "gallery": {"name": "The Gallery", "description": "Modern wood · 4 colours", "price": 1199},
    "heritage": {"name": "The Heritage", "description": "Statement grain · 3 colours", "price": 1499},
    "brass-edit": {"name": "The Brass Edit", "description": "Warm metal · 2 colours", "price": 1699},
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", secrets.token_urlsafe(32)),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
app.jinja_env.filters["from_json"] = json.loads


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create database folders and tables on first deployment."""
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    with db_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                city TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                notes TEXT,
                items_json TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                order_status TEXT NOT NULL DEFAULT 'placed',
                razorpay_order_id TEXT,
                razorpay_payment_id TEXT,
                user_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Small migration for stores created before customer accounts were added.
        order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)")}
        if "user_id" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")


def is_allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_TYPES


def save_photo() -> str | None:
    photo = request.files.get("photo")
    if photo is None or not photo.filename:
        return None
    if not is_allowed_image(photo.filename):
        raise ValueError("Upload a PNG, JPG, JPEG, or WEBP photo.")
    extension = secure_filename(photo.filename).rsplit(".", 1)[1].lower()
    saved_name = f"{uuid.uuid4().hex}.{extension}"
    photo.save(UPLOAD_DIR / saved_name)
    return f"uploads/{saved_name}"


def calculate_items(items: list[dict[str, Any]], photo_path: str | None) -> tuple[list[dict[str, Any]], int]:
    """Recalculate every price on the server; never trust a browser-supplied total."""
    if not 1 <= len(items) <= 10:
        raise ValueError("Your cart must contain between 1 and 10 items.")

    safe_items: list[dict[str, Any]] = []
    total = 0
    for position, item in enumerate(items):
        item_type = item.get("type")
        quantity = item.get("quantity", 1)
        if not isinstance(quantity, int) or not 1 <= quantity <= 5:
            raise ValueError("Each item quantity must be between 1 and 5.")

        if item_type == "custom":
            size = item.get("size")
            color = item.get("color")
            purpose = item.get("purpose")
            if size not in FRAME_SIZES or color not in FRAME_COLORS or purpose not in PURPOSES:
                raise ValueError("One of your custom frame options is invalid.")
            safe_item = {
                "type": "custom",
                "name": "Custom photo frame",
                "size": size,
                "size_label": FRAME_SIZES[size]["label"],
                "color": color,
                "color_label": FRAME_COLORS[color],
                "purpose": purpose,
                "quantity": quantity,
                "unit_price": FRAME_SIZES[size]["price"],
                "photo": photo_path if position == 0 else None,
            }
        elif item_type == "product":
            product_id = item.get("product_id")
            product = PRODUCTS.get(product_id)
            if not product:
                raise ValueError("One of the selected products is unavailable.")
            safe_item = {
                "type": "product",
                "product_id": product_id,
                "name": product["name"],
                "description": product["description"],
                "quantity": quantity,
                "unit_price": product["price"],
            }
        else:
            raise ValueError("Invalid item in cart.")

        safe_item["line_total"] = safe_item["quantity"] * safe_item["unit_price"]
        total += safe_item["line_total"]
        safe_items.append(safe_item)
    return safe_items, total


def order_number() -> str:
    return f"PS-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


def razorpay_is_configured() -> bool:
    return bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET"))


def razorpay_client() -> razorpay.Client:
    return razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))


def current_user() -> sqlite3.Row | None:
    """Return the signed-in customer, dropping a stale session if the account was removed."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db_connection() as connection:
        user = connection.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        session.clear()
    return user


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("homepage", signin="1"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Basic "):
            return ("Login required", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})
        try:
            decoded = b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return ("Invalid login", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})
        expected_user = os.getenv("ADMIN_USERNAME", "admin")
        expected_password = os.getenv("ADMIN_PASSWORD", "change-this-before-launch")
        if not (hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password)):
            return ("Invalid login", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})
        return view(*args, **kwargs)
    return wrapped


@app.get("/")
def homepage():
    return render_template("index.html", user=current_user())


@app.get("/api/auth/me")
def auth_me():
    user = current_user()
    if not user:
        return jsonify({"user": None})
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"]}})


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or "@" not in email or len(email) > 254:
        return jsonify({"error": "Enter your name and a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Choose a password with at least 8 characters."}), 400
    with db_connection() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, email, generate_password_hash(password), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error": "An account with this email already exists. Please sign in."}), 409
    session.clear()
    session["user_id"] = cursor.lastrowid
    return jsonify({"user": {"id": cursor.lastrowid, "name": name, "email": email}}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with db_connection() as connection:
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 401
    session.clear()
    session["user_id"] = user["id"]
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"]}})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"message": "Signed out."})


@app.get("/account")
@customer_required
def account():
    user = current_user()
    with db_connection() as connection:
        orders = connection.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return render_template("account.html", user=user, orders=orders)


@app.get("/api/config")
def public_config():
    return jsonify({
        "currency": "INR",
        "online_payments": razorpay_is_configured(),
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "") if razorpay_is_configured() else "",
    })


@app.get("/api/products")
def product_list():
    return jsonify([{"id": product_id, **product} for product_id, product in PRODUCTS.items()])


@app.get("/uploads/<path:filename>")
@admin_required
def uploaded_photo(filename: str):
    """Customer images remain private to an authenticated store administrator."""
    return send_from_directory(UPLOAD_DIR, filename)


@app.post("/api/orders")
def create_order():
    try:
        items = json.loads(request.form.get("items", "[]"))
    except json.JSONDecodeError:
        return jsonify({"error": "The cart data is invalid."}), 400
    if not isinstance(items, list):
        return jsonify({"error": "The cart data is invalid."}), 400

    fields = {field: request.form.get(field, "").strip() for field in ("name", "email", "phone", "address", "city", "postal_code", "notes", "payment_method")}
    required = ("name", "email", "phone", "address", "city", "postal_code", "payment_method")
    if any(not fields[field] for field in required):
        return jsonify({"error": "Please complete all delivery details."}), 400
    if "@" not in fields["email"] or len(fields["phone"]) < 8:
        return jsonify({"error": "Please enter a valid email and phone number."}), 400
    if fields["payment_method"] not in {"cod", "razorpay"}:
        return jsonify({"error": "Select a valid payment method."}), 400
    if fields["payment_method"] == "razorpay" and not razorpay_is_configured():
        return jsonify({"error": "Online payments are not configured yet. Please choose Cash on Delivery."}), 400

    try:
        photo_path = save_photo()
        safe_items, total = calculate_items(items, photo_path)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    number = order_number()
    payment_status = "pending" if fields["payment_method"] == "razorpay" else "cash_on_delivery"
    created_at = datetime.now(timezone.utc).isoformat()
    signed_in_user = current_user()
    with db_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO orders (order_number, customer_name, email, phone, address, city, postal_code, notes, items_json, amount, payment_method, payment_status, user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (number, fields["name"], fields["email"], fields["phone"], fields["address"], fields["city"], fields["postal_code"], fields["notes"], json.dumps(safe_items), total, fields["payment_method"], payment_status, signed_in_user["id"] if signed_in_user else None, created_at),
        )
        internal_id = cursor.lastrowid

    response: dict[str, Any] = {"order_number": number, "amount": total, "payment_method": fields["payment_method"]}
    if fields["payment_method"] == "razorpay":
        payment_order = razorpay_client().order.create({"amount": total * 100, "currency": "INR", "receipt": number, "notes": {"photosite_order": number}})
        with db_connection() as connection:
            connection.execute("UPDATE orders SET razorpay_order_id = ? WHERE id = ?", (payment_order["id"], internal_id))
        response["razorpay"] = {"key": os.environ["RAZORPAY_KEY_ID"], "order_id": payment_order["id"], "name": "Photosite", "description": f"Order {number}"}
    else:
        notify_new_order({"order_number": number, "amount": total, "payment_method": "cod", "payment_status": payment_status, **fields}, safe_items)
    return jsonify(response), 201


@app.post("/api/payments/razorpay/verify")
def verify_razorpay_payment():
    data = request.get_json(silent=True) or {}
    received_order_id = data.get("razorpay_order_id", "")
    payment_id = data.get("razorpay_payment_id", "")
    signature = data.get("razorpay_signature", "")
    if not razorpay_is_configured() or not all((received_order_id, payment_id, signature)):
        return jsonify({"error": "Payment verification data is incomplete."}), 400
    payload = f"{received_order_id}|{payment_id}".encode()
    expected = hmac.new(os.environ["RAZORPAY_KEY_SECRET"].encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify({"error": "Payment verification failed."}), 400
    with db_connection() as connection:
        order = connection.execute("SELECT * FROM orders WHERE razorpay_order_id = ?", (received_order_id,)).fetchone()
        if not order:
            return jsonify({"error": "Order not found."}), 404
        connection.execute("UPDATE orders SET payment_status = 'paid', payment_method = 'razorpay', razorpay_payment_id = ? WHERE razorpay_order_id = ?", (payment_id, received_order_id))
    order_data = dict(order)
    order_data["payment_status"] = "paid"
    notify_new_order(order_data, json.loads(order_data["items_json"]))
    return jsonify({"message": "Payment verified.", "order_number": order["order_number"]})


@app.get("/admin")
@admin_required
def admin_dashboard():
    with db_connection() as connection:
        orders = connection.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        metrics = connection.execute(
            """SELECT COUNT(*) AS total_orders,
                      COALESCE(SUM(CASE WHEN order_status != 'cancelled' THEN amount ELSE 0 END), 0) AS order_value,
                      COALESCE(SUM(CASE WHEN payment_status = 'paid' THEN amount ELSE 0 END), 0) AS paid_value,
                      COALESCE(SUM(CASE WHEN order_status IN ('placed', 'processing') THEN 1 ELSE 0 END), 0) AS action_needed,
                      COALESCE(SUM(CASE WHEN order_status = 'shipped' THEN 1 ELSE 0 END), 0) AS shipped_orders
               FROM orders"""
        ).fetchone()
        customers = connection.execute(
            """SELECT customer_name, email, phone, COUNT(*) AS orders_count,
                      COALESCE(SUM(amount), 0) AS lifetime_value, MAX(created_at) AS last_order
               FROM orders GROUP BY lower(email) ORDER BY last_order DESC"""
        ).fetchall()
    return render_template("admin.html", orders=orders, metrics=metrics, customers=customers,
                           notifications_enabled=is_email_configured(),
                           notification_email=os.getenv("NOTIFICATION_EMAIL", "Not configured"))


@app.patch("/api/admin/orders/<int:order_id>/status")
@admin_required
def update_order_status(order_id: int):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"placed", "processing", "shipped", "delivered", "cancelled"}:
        return jsonify({"error": "Invalid order status."}), 400
    with db_connection() as connection:
        result = connection.execute("UPDATE orders SET order_status = ? WHERE id = ?", (status, order_id))
        if result.rowcount == 0:
            return jsonify({"error": "Order not found."}), 404
    return jsonify({"message": "Order updated."})


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    return jsonify({"error": "Photo is too large. Please upload an image under 8 MB."}), 413


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
