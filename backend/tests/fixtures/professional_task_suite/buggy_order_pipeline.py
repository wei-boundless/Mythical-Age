from __future__ import annotations


def normalize_status(value):
    if value is None:
        return "unknown"
    return str(value).strip()


def parse_orders(rows):
    orders = []
    for index, row in enumerate(rows):
        quantity = int(row.get("quantity") or 0)
        unit_price = float(row.get("unit_price") or 0)
        status = normalize_status(row.get("status"))
        order = {
            "id": row.get("id") or f"row-{index}",
            "sku": str(row.get("sku") or "").strip(),
            "region": str(row.get("region") or "").strip(),
            "quantity": quantity,
            "unit_price": unit_price,
            "status": status,
            "gross": quantity + unit_price,
        }
        if quantity >= 0:
            orders.append(order)
    return orders


def summarize_revenue(orders):
    summary = {}
    for order in orders:
        if order["status"] != "ready":
            continue
        region = order["region"]
        bucket = summary.setdefault(region, {"orders": 0, "quantity": 0, "gross": 0.0})
        bucket["orders"] += 1
        bucket["quantity"] += 1
        bucket["gross"] += order["gross"]
    return summary


def pick_restock_candidates(orders, *, threshold=5):
    candidates = []
    for order in orders:
        if order["quantity"] > threshold:
            candidates.append(order["sku"])
    return sorted(set(candidates), reverse=True)


def build_pipeline_report(rows):
    orders = parse_orders(rows)
    return {
        "orders": orders,
        "summary": summarize_revenue(orders),
        "restock_skus": pick_restock_candidates(orders, threshold=5),
    }


def test_pipeline_report_handles_realistic_orders():
    rows = [
        {"id": "a1", "sku": "AX-1", "region": "east", "quantity": "2", "unit_price": "10.50", "status": " READY "},
        {"id": "a2", "sku": "BX-2", "region": "east", "quantity": "6", "unit_price": "4.00", "status": "ready"},
        {"id": "a3", "sku": "CX-3", "region": "west", "quantity": "3", "unit_price": "7.00", "status": "blocked"},
        {"id": "a4", "sku": "DX-4", "region": "west", "quantity": "-1", "unit_price": "9.00", "status": "ready"},
        {"id": "a5", "sku": "EX-5", "region": "west", "quantity": "5", "unit_price": "2.00", "status": None},
    ]

    report = build_pipeline_report(rows)

    assert [order["id"] for order in report["orders"]] == ["a1", "a2", "a3", "a5"]
    assert report["orders"][0]["status"] == "ready"
    assert report["orders"][0]["gross"] == 21.0
    assert report["summary"] == {
        "east": {"orders": 2, "quantity": 8, "gross": 45.0},
    }
    assert report["restock_skus"] == ["EX-5", "BX-2"]


