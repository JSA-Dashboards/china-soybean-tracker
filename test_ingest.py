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


# ---- real FAS GovDelivery releases (public USDA text; recipient address removed) ----
# Real emails repeat the body as a truncated preview first, then the full text.
_PREVIEW = "Caution : External ( fas.usda@service.govdelivery.com ) Graymail, Sensitive Content Details Not Graymail Spam Phish More... "
_LEGAL = " ### The U.S. Department of Agriculture is required by law to publicly release summary sales data obtained from U.S. exporters of many agricultural commodities."


def _real(date, esr, title, body):
    head = f"{date} FAS-ESR-{esr}-26 {title} "
    return f"{head}{body[:90]} {_PREVIEW}{head}{body}{_LEGAL}"


REAL = {
    "089": ("October 14, 2026", "Export Sales to China",
            "Private exporters reported sales of 470,000 metric tons of soybeans for delivery to China during the 2026/2027 marketing year."),
    "090": ("October 15, 2026", "Export Sales to China and Unknown Destinations",
            "Private exporters reported to the following sales activity: 330,000 metric tons of soybeans for delivery to China during the 2026/2027 marketing year "
            "283,450 metric tons of soybeans received in the reporting period for delivery to unknown destinations during the 2026/2027 marketing year"),
    "091": ("October 16, 2026", "Export Sales to China, Japan, and Unknown Destinations",
            "Private exporters reported the following sales activities: 127,000 metric tons of corn for delivery to Japan during the 2026/2027 marketing year "
            "558,000 metric tons of soybeans for delivery to China during the 2026/2027 marketing year "
            "236,000 metric tons of soybeans for delivery to unknown destinations during the 2026/2027 marketing year"),
}


def _parse_real(esr):
    date, title, body = REAL[esr]
    day = {"089": "2026-10-14", "090": "2026-10-15", "091": "2026-10-16"}[esr]
    return ig.parse_text(_real(date, esr, title, body), f"{day}T08:02", title)


def test_real_esr_089_china_only():
    r = _parse_real("089")
    assert [(c["esr"], c["mt"], c["dest"]) for c in r["clean"]] == [("089", 470000, "china")]
    assert not r["review"] and not r["out_of_scope"]


def test_real_esr_090_list_format_china_and_unknown():
    r = _parse_real("090")
    assert [(c["mt"], c["dest"]) for c in r["clean"]] == [(330000, "china"), (283450, "unknown")]
    assert not r["review"]


def test_real_esr_091_corn_set_aside():
    r = _parse_real("091")
    assert [(c["mt"], c["dest"]) for c in r["clean"]] == [(558000, "china"), (236000, "unknown")]
    assert [(o["commodity"], o["dest"], o["mt"]) for o in r["out_of_scope"]] == [("Corn", "Japan", 127000)]


def test_real_parses_match_the_published_tracker_rows():
    data = t.load()
    flash = {(f["esr"], f["mt"]) for f in data["china_flash"]}
    unk = {(u["esr"], u["mt"]) for u in data["unknown"] if u["esr"]}
    for esr in REAL:
        for c in _parse_real(esr)["clean"]:
            assert (c["esr"], c["mt"]) in (flash if c["dest"] == "china" else unk)
