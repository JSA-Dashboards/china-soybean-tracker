"""SYNTHETIC text in the FAS flash-sale style (same caveat as test_ingest.py)."""
import flash_archive as fa

D = "2026-10-20T09:05"


def P(text, subject="Export Sales ESR-093-26"):
    return fa.parse_items(text, D, subject)


def test_every_commodity_and_destination_is_kept():
    rows = P("Export sales of 127,000 metric tons of corn for delivery to Japan during the 2026/2027 marketing year. "
             "Export sales of 90,000 metric tons of soybean meal for delivery to the Philippines during the 2026/27 marketing year. "
             "Export sales of 236,000 metric tons of soybeans for delivery to unknown destinations during the 2026/2027 marketing year.")
    got = [(r["commodity"], r["mt"], r["destination"], r["marketing_year"]) for r in rows]
    assert got[0] == ("Corn", 127000, "Japan", "2026/27")
    assert got[1][0] == "Soybean Meal" and got[1][1] == 90000
    assert got[2] == ("Soybeans", 236000, "Unknown Destinations", "2026/27")
    assert [r["item_idx"] for r in rows] == [0, 1, 2] and all(r["esr"] == "093" for r in rows)


def test_switch_is_kept_with_a_flag():
    rows = P("Export sales of 126,000 metric tons of soybeans previously reported for delivery to unknown destinations "
             "were switched to China during the 2026/27 marketing year.")
    assert len(rows) == 1 and rows[0]["commodity"] == "Soybeans"
    assert "switch" in rows[0]["flags"] and "revision" in rows[0]["flags"]


def test_old_marketing_year_is_kept_not_dropped():
    rows = P("Export sales of 100,000 metric tons of wheat for delivery to Egypt during the 2025/2026 marketing year.")
    assert rows[0]["marketing_year"] == "2025/26" and rows[0]["commodity"] == "Wheat"


def test_repeated_preview_body_is_not_double_counted():
    body = "Export sales of 150,000 metric tons of soybeans for delivery to China during the 2026/27 marketing year."
    rows = P("FAS-ESR-093 " + body[:60] + " ... FAS-ESR-093 " + body)
    assert len(rows) == 1 and rows[0]["mt"] == 150000 and rows[0]["destination"] == "China"


def test_plain_sale_has_no_flags():
    rows = P("Export sales of 150,000 metric tons of sorghum for delivery to China during the 2026/27 marketing year.")
    assert rows[0]["flags"] == "" and rows[0]["commodity"] == "Sorghum"


def test_fetch_light_lists_headers_then_fetches_only_fas_bodies(monkeypatch):
    import requests
    calls = []

    class R:
        status_code = 200
        headers = {}

        def __init__(self, j):
            self.j = j

        def raise_for_status(self):
            pass

        def json(self):
            return self.j

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        if url.endswith("/messages/FAS1"):
            return R({"id": "FAS1", "internetMessageId": "<a>", "subject": "Export Sales to China",
                      "receivedDateTime": "2026-10-20T13:02:00Z",
                      "body": {"contentType": "text", "content": "150,000 metric tons of soybeans for delivery to China during the 2026/27 marketing year."}})
        return R({"value": [
            {"id": "FAS1", "subject": "Export Sales to China", "from": {"emailAddress": {"name": "USDA FAS", "address": "x@usda.gov"}}},
            {"id": "OTH", "subject": "Lunch?", "from": {"emailAddress": {"name": "Bob", "address": "b@x.com"}}}]})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(fa.ig, "_env", lambda: {"GRAPH_INBOX_USER": "me@x.com"})
    monkeypatch.setattr(fa.ig, "_graph_token", lambda env: "tok")
    msgs = fa.fetch_light(1, progress=False)
    assert len(msgs) == 2 and all(m["id"] == "<a>" for m in msgs)  # one FAS hit per day-chunk, 2 chunks (days 1 and 0)
    assert not any(url.endswith("/messages/OTH") for url, _ in calls)
