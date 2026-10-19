"""Parser tests use SYNTHETIC text in the FAS flash-sale style, not real emails.
Replace/extend with real GovDelivery samples (python ingest.py parse-file <file>)."""
import copy

import ingest as ig
import tracker_logic as t

D = "2026-10-20T09:05"


def P(text, subject="Export Sales ESR-093-26"):
    return ig.parse_text(text, D, subject)


def test_clean_china():
    r = P("Private exporters reported to the U.S. Department of Agriculture export sales of 150,000 metric tons of soybeans for delivery to China during the 2026/2027 marketing year.")
    assert len(r["clean"]) == 1 and not r["review"]
    c = r["clean"][0]
    assert (c["mt"], c["dest"], c["esr"], c["date"]) == (150000, "china", "093", "2026-10-20")


def test_clean_unknown():
    r = P("Private exporters reported export sales of 261,000 metric tons of soybeans for delivery to unknown destinations during the 2026/27 marketing year.")
    assert r["clean"][0]["dest"] == "unknown"


def test_wrong_marketing_year_goes_to_review():
    r = P("Private exporters reported export sales of 100,000 metric tons of soybeans for delivery to China during the 2025/2026 marketing year.")
    assert not r["clean"] and "marketing year" in r["review"][0]["reason"]


def test_two_marketing_years_in_one_sentence_review():
    r = P("Sales of 120,000 metric tons of soybeans for delivery to China during the 2025/26 marketing year and 100,000 metric tons for delivery during the 2026/27 marketing year.")
    assert not r["clean"] and r["review"]


def test_switch_wording_goes_to_review():
    r = P("Export sales of 126,000 metric tons of soybeans previously reported for delivery to unknown destinations were switched to China during the 2026/27 marketing year.")
    assert not r["clean"] and "switch" in r["review"][0]["reason"]


def test_other_destination_review():
    r = P("Private exporters reported export sales of 130,000 metric tons of soybeans for delivery to Egypt during the 2026/27 marketing year.")
    assert not r["clean"] and r["review"]


def test_corn_and_meal_out_of_scope_not_queued():
    r = P("Export sales of 127,000 metric tons of corn for delivery to Japan during the 2026/27 marketing year. "
          "Export sales of 90,000 metric tons of soybean meal for delivery to China during the 2026/27 marketing year.")
    assert not r["clean"] and not r["review"] and len(r["out_of_scope"]) == 2


def test_mixed_release_keeps_soy_drops_corn():
    r = P("Private exporters reported export sales of 236,000 metric tons of soybeans for delivery to unknown destinations during the 2026/2027 marketing year. "
          "Export sales of 127,000 metric tons of corn for delivery to Japan during the 2026/2027 marketing year.")
    assert [c["mt"] for c in r["clean"]] == [236000] and r["out_of_scope"][0]["commodity"] == "Corn"


def test_missing_esr_flagged_but_clean():
    r = P("Export sales of 100,000 metric tons of soybeans for delivery to China during the 2026/27 marketing year.", subject="Flash sale")
    assert r["clean"][0]["esr"] == "" and "ESR" in r["clean"][0]["reason"]


def test_queue_is_idempotent_and_never_touches_totals():
    data = copy.deepcopy(t.load())
    before = t.summarize(data)["grand_mt"]
    m = {"id": "<m1>", "subject": "ESR-093-26", "received": D,
         "body": "Export sales of 150,000 metric tons of soybeans for delivery to China during the 2026/27 marketing year."}
    assert ig.queue_result(data, m)["queued"] == 1
    assert ig.queue_result(data, m)["queued"] == 0
    assert len(data["pending"]) == 1 and t.summarize(data)["grand_mt"] == before
