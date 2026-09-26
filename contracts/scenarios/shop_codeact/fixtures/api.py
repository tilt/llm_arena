import json, sqlite3
TODAY = "2026-05-14"
_DB = "state/shop.sqlite"

def _conn():
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    return conn

def _log(conn, action, payload):
    conn.execute("INSERT INTO actions (action, payload) VALUES (?, ?)", (action, json.dumps(payload)))

def get_order(order_id):
    with _conn() as c:
        order = c.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            raise KeyError(f"order {order_id} not found")
        items = [dict(r) for r in c.execute("SELECT sku, qty, unit_price FROM order_items WHERE order_id = ?", (order_id,))]
        return {**dict(order), "items": items}

def list_orders(customer_email):
    with _conn() as c:
        ids = [r[0] for r in c.execute("SELECT order_id FROM orders WHERE customer_email = ?", (customer_email,))]
    return [get_order(i) for i in ids]

def get_product(sku):
    with _conn() as c:
        row = c.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        if row is None:
            raise KeyError(f"product {sku} not found")
        return dict(row)

def list_products():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM products ORDER BY sku")]

def cancel_order(order_id):
    order = get_order(order_id)
    with _conn() as c:
        c.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        for item in order["items"]:
            c.execute("UPDATE products SET stock = stock + ? WHERE sku = ?", (item["qty"], item["sku"]))
        _log(c, "cancel_order", {"order_id": order_id, "previous_status": order["status"]})
    return get_order(order_id)

def issue_refund(order_id, amount, reason):
    get_order(order_id)
    with _conn() as c:
        c.execute("INSERT INTO refunds (order_id, amount, reason) VALUES (?, ?, ?)", (order_id, round(float(amount), 2), reason))
        _log(c, "issue_refund", {"order_id": order_id, "amount": amount})
    return {"order_id": order_id, "refunded": round(float(amount), 2)}

def restock(sku, quantity):
    get_product(sku)
    with _conn() as c:
        c.execute("UPDATE products SET stock = stock + ? WHERE sku = ?", (int(quantity), sku))
        _log(c, "restock", {"sku": sku, "quantity": quantity})
    return get_product(sku)

def send_message(customer_email, text):
    with _conn() as c:
        c.execute("INSERT INTO messages (customer_email, text) VALUES (?, ?)", (customer_email, text))
        _log(c, "send_message", {"customer_email": customer_email})
    return {"sent": True}
