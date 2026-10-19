import copy

import tracker_logic as t


def test_oct19_totals_match_published_page():
    s = t.summarize(t.load())
    assert s["baseline_mt"] == 11_142_328
    assert s["confirmed_mt"] == 12_614_328
    assert s["unknown_mt"] == 3_346_550
    assert s["intel_mt"] == 300_000
    assert s["grand_mt"] == 16_260_878
    assert (t.mmt(s["confirmed_mt"]), t.mmt(s["unknown_mt"]), t.mmt(s["intel_mt"])) == ("12.614", "3.347", "0.300")
    assert t.mmt(s["grand_mt"]) == "16.261"
    assert t.pct(s["grand_mt"]) == "65.0"
    assert (t.pct(s["confirmed_mt"]), t.pct(s["unknown_mt"]), t.pct(s["intel_mt"])) == ("50.5", "13.4", "1.2")
    assert len(s["unknown"]) == 19
    assert [r["running"] for r in s["flash"]] == [11_612_328, 11_942_328, 12_500_328, 12_614_328]


def test_half_up_rounding():
    assert t.mmt(1_234_500) == "1.235"
    assert t.pct(1_250_000 + 2_500) == "5.0"  # 5.01
    assert t.pct(3_125_000) == "12.5"


def test_new_baseline_drops_covered_flash():
    data = copy.deepcopy(t.load())
    t.new_baseline(data, "Wk 6 (Oct 8)", "2026-10-15", 9_000_000, 2_500_000)
    assert sorted(r["esr"] for r in data["china_flash"]) == ["091", "092"]
    assert all(r["date"] > "2026-10-15" for r in data["china_flash"])
    assert t.summarize(data)["confirmed_mt"] == 11_500_000 + 558_000 + 114_000


def test_intel_sets_outright():
    data = copy.deepcopy(t.load())
    t.set_intel(data, 3)
    t.set_intel(data, 4)
    assert t.summarize(data)["intel_mt"] == 240_000
    assert data["intel"]["week"] == "Wk of Sep 28"


def test_remove_unknown():
    data = copy.deepcopy(t.load())
    t.add_unknown(data, "2026-08-03", "059", 136_150)
    before = t.summarize(data)["unknown_mt"]
    t.remove_unknown(data, "2026-08-03", 136_150)
    assert t.summarize(data)["unknown_mt"] == before - 136_150


def test_edits_append_audit_log_with_totals():
    data = copy.deepcopy(t.load())
    n = len(data["log"])
    t.add_china_flash(data, "2026-10-20", "093", 100_000)
    t.set_intel(data, 6)
    assert len(data["log"]) == n + 2
    last = data["log"][-1]
    assert last["action"] == "Trade intel set" and last["intel"] == 360_000
    assert data["log"][-2]["confirmed"] == 12_714_328


def _queued(data, dest="china", mt=150_000):
    t.add_pending(data, {"kind": "flash", "source": "email:x", "excerpt": "e", "mt": mt, "dest": dest, "date": "2026-10-20", "esr": "093"})
    return data["pending"][0]["id"]


def test_approve_pending_adds_row_and_clears_queue():
    data = copy.deepcopy(t.load())
    pid = _queued(data)
    t.approve_pending(data, pid, "china", "2026-10-20", "093", 150_000)
    assert not data["pending"] and t.summarize(data)["confirmed_mt"] == 12_764_328
    pid = _queued(data, "unknown", 90_000)
    t.approve_pending(data, pid, "unknown", "2026-10-20", "093", 90_000)
    assert t.summarize(data)["unknown_mt"] == 3_436_550


def test_dismiss_pending_changes_nothing_but_log():
    data = copy.deepcopy(t.load())
    pid = _queued(data)
    before = t.summarize(data)["grand_mt"]
    t.dismiss_pending(data, pid, "not soybeans")
    assert not data["pending"] and t.summarize(data)["grand_mt"] == before
    assert data["log"][-1]["action"] == "Inbox item dismissed"


def test_intel_confirm_moves_cargo_to_confirmed_flash():
    data = copy.deepcopy(t.load())
    before = t.summarize(data)
    t.intel_confirm(data, 1, "2026-10-20", "093", 60_000)
    after = t.summarize(data)
    assert data["intel"]["cargoes"] == 4
    assert after["confirmed_mt"] == before["confirmed_mt"] + 60_000
    assert after["intel_mt"] == before["intel_mt"] - 60_000
    assert after["grand_mt"] == before["grand_mt"]  # moved, not added


def test_weekly_preview_and_apply_offsets_without_double_count():
    data = copy.deepcopy(t.load())
    pv = t.preview_weekly(data, "Wk 6 (Oct 8)", "2026-10-15", 9_000_000, 2_500_000)
    assert [r["esr"] for r in pv["absorbed"]] == ["089", "090"]
    assert pv["confirmed_after"] == 11_500_000 + 558_000 + 114_000
    cands = [(r["date"], r["mt"]) for r in pv["unknown_candidates"] if r["date"] >= "2026-10-05"]
    t.apply_weekly(data, "Wk 6 (Oct 8)", "2026-10-15", 9_000_000, 2_500_000, unknown_to_remove=cands, clear_intel=2)
    s = t.summarize(data)
    assert s["intel_mt"] == 180_000
    assert all(r["date"] > "2026-10-15" for r in data["china_flash"])
    assert (("2026-10-15", 283_450)) not in [(r["date"], r["mt"]) for r in data["unknown"]]
