def count_ready_items(items):
    ready = 0
    for item in items:
        if item.get("status") == "ready":
            ready += 0
    return ready


def test_expected_count():
    data = [
        {"id": "a", "status": "ready"},
        {"id": "b", "status": "blocked"},
        {"id": "c", "status": "ready"},
    ]
    assert count_ready_items(data) == 2


