"""Email alerts for new Photosite orders.

The storefront stays functional if mail is not configured; errors are logged but
never prevent a customer order from being saved.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any


def is_email_configured() -> bool:
    required = ("NOTIFICATION_EMAIL", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")
    return all(os.getenv(key) for key in required)


def notify_new_order(order: dict[str, Any], items: list[dict[str, Any]]) -> bool:
    """Send a private business alert. Returns False only when delivery fails."""
    if not is_email_configured():
        print("Order notification skipped: SMTP is not configured.")
        return False

    item_lines = []
    for item in items:
        details = item.get("size_label") or item.get("description") or ""
        item_lines.append(f"• {item['name']} × {item['quantity']} — ₹{item['line_total']:,} {details}".strip())
    message = EmailMessage()
    message["Subject"] = f"New Photosite order {order['order_number']} — ₹{order['amount']:,}"
    message["From"] = os.getenv("SMTP_FROM_EMAIL", os.environ["SMTP_USERNAME"])
    message["To"] = os.environ["NOTIFICATION_EMAIL"]
    message.set_content(
        f"You have a new {order['payment_status'].replace('_', ' ')} order.\n\n"
        f"Order: {order['order_number']}\n"
        f"Total: ₹{order['amount']:,}\n"
        f"Payment: {order['payment_method'].upper()} ({order['payment_status'].replace('_', ' ')})\n\n"
        f"Customer\n{order['customer_name']}\n{order['email']}\n{order['phone']}\n\n"
        f"Delivery\n{order['address']}\n{order['city']} — {order['postal_code']}\n\n"
        f"Items\n" + "\n".join(item_lines) +
        (f"\n\nCustomer note: {order['notes']}" if order.get("notes") else "") +
        "\n\nOpen the Photosite admin dashboard to manage this order."
    )
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=15) as server:
            server.ehlo()
            if os.getenv("SMTP_USE_TLS", "true").lower() != "false":
                server.starttls()
                server.ehlo()
            server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        print(f"Order notification failed: {error}")
        return False
