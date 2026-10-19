"""Pure calculation + data helpers for the China Soybean Purchase Tracker.

All figures are metric tons (MT). MMT = MT / 1,000,000 rounded half-up to 3
decimals; percentages of the 25 MMT goal are rounded half-up to 1 decimal.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GOAL_MT = 25_000_000
DATA_PATH = Path(__file__).with_name("tracker_data.json")


def load(path=DATA_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(data, path=DATA_PATH):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now():
    """Timestamp in Central Time (Streamlit Cloud runs UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="minutes")
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec="minutes")


def log_entry(data, action, detail):
    """Append an audit row with the resulting totals (MT) after the change."""
    s = summarize(data)
    data.setdefault("log", []).append({
        "ts": _now(), "action": action, "detail": detail,
        "confirmed": s["confirmed_mt"], "unknown": s["unknown_mt"],
        "intel": s["intel_mt"], "grand": s["grand_mt"],
    })
    return data


def d(iso):
    return date.fromisoformat(iso)


def fmt_date(iso):
    x = d(iso)
    return f"{x:%b} {x.day}"


def mmt(mt):
    """MT -> MMT string, 3 decimals, half-up."""
    return str((Decimal(mt) / 1_000_000).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def pct(mt):
    """Share of the 25 MMT goal, 1 decimal, half-up."""
    return str((Decimal(mt) * 100 / GOAL_MT).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def with_running(rows, start=0):
    total = start
    out = []
    for r in rows:
        total += r["mt"]
        out.append({**r, "running": total})
    return out


def baseline_total(data):
    b = data["baseline"]
    return b["outstanding_sales"] + b["accumulated_exports"]


def summarize(data):
    base = baseline_total(data)
    flash = with_running(sorted(data["china_flash"], key=lambda r: r["date"]), start=base)
    unknown = with_running(sorted(data["unknown"], key=lambda r: r["date"]))
    i = data["intel"]
    intel_mt = i["cargoes"] * i["mt_per_cargo"]
    confirmed = flash[-1]["running"] if flash else base
    unknown_mt = unknown[-1]["running"] if unknown else 0
    grand = confirmed + unknown_mt + intel_mt
    return {
        "baseline_mt": base,
        "flash": flash,
        "unknown": unknown,
        "confirmed_mt": confirmed,
        "unknown_mt": unknown_mt,
        "intel_mt": intel_mt,
        "grand_mt": grand,
    }


# ---- edits (each returns the mutated data dict) ---------------------------

def add_china_flash(data, iso, esr, mt, note=""):
    data["china_flash"].append({"date": iso, "esr": esr, "mt": mt, "note": note})
    data["as_of"] = max(data["as_of"], iso)
    return log_entry(data, "Flash sale → China confirmed", f"{fmt_date(iso)} · ESR-{esr} · {mt:,} MT {note}".strip())


def add_unknown(data, iso, esr, mt, note=""):
    data["unknown"].append({"date": iso, "esr": esr, "mt": mt, "note": note})
    data["as_of"] = max(data["as_of"], iso)
    return log_entry(data, "Flash sale → unknown destinations", f"{fmt_date(iso)} · ESR-{esr} · {mt:,} MT {note}".strip())


def remove_unknown(data, iso, mt, note="removed from the unknown-destination log per JSA desk update.", esr=""):
    """Drop one unknown-destination row (matched on date + MT) and footnote it."""
    for r in data["unknown"]:
        if r["date"] == iso and r["mt"] == mt:
            data["unknown"].remove(r)
            data["unknown_removed"].append({"date": iso, "esr": esr or r["esr"], "mt": mt, "note": note})
            return log_entry(data, "Removed from unknown destinations", f"{fmt_date(iso)} · {mt:,} MT · {note}")
    raise ValueError(f"No unknown-destination row on {iso} for {mt:,} MT")


def set_intel(data, cargoes, week=None, mt_per_cargo=None):
    """Set trade intel outright (replaces, never adds). Week label kept unless given."""
    data["intel"]["cargoes"] = cargoes
    if week:
        data["intel"]["week"] = week
    if mt_per_cargo:
        data["intel"]["mt_per_cargo"] = mt_per_cargo
    i = data["intel"]
    return log_entry(data, "Trade intel set", f"{i['cargoes']} cargoes × {i['mt_per_cargo']:,} MT · {i['week']}")


def new_baseline(data, label, cutoff_iso, outstanding, exports, source=None):
    """New weekly ESR snapshot: replaces the baseline and every flash row it covers
    (flash dated on/before the cutoff), so nothing is counted twice."""
    data["baseline"].update(
        label=label, cutoff=cutoff_iso, outstanding_sales=outstanding,
        accumulated_exports=exports, source=source or f"USDA ESR Query System, {label}",
    )
    before = len(data["china_flash"])
    data["china_flash"] = [r for r in data["china_flash"] if r["date"] > cutoff_iso]
    dropped = before - len(data["china_flash"])
    return log_entry(data, "New weekly ESR baseline",
                     f"{label} · outstanding {outstanding:,} + exports {exports:,} · {dropped} flash row(s) absorbed")


# ---- admin workflow: inbox, intel -> confirmed, weekly report -------------

import copy
import hashlib


def _pid(*parts):
    return "p-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def add_pending(data, item):
    """Queue an inbox item for admin review. Returns False if already queued."""
    item.setdefault("id", _pid(item.get("source"), item.get("excerpt"), item.get("mt"), item.get("dest")))
    queue = data.setdefault("pending", [])
    if any(p["id"] == item["id"] for p in queue):
        return False
    queue.append(item)
    return True


def _pending(data, pid):
    for p in data.get("pending", []):
        if p["id"] == pid:
            return p
    raise ValueError(f"No pending item {pid}")


def approve_pending(data, pid, dest, iso, esr, mt, note=""):
    """Accept an inbox item. dest = 'china' (confirmed flash) or 'unknown'."""
    p = _pending(data, pid)
    data["pending"].remove(p)
    note = f"{note} (from inbox)".strip()
    if dest == "china":
        return add_china_flash(data, iso, esr, mt, note)
    if dest == "unknown":
        return add_unknown(data, iso, esr, mt, note)
    raise ValueError("dest must be 'china' or 'unknown'")


def dismiss_pending(data, pid, reason):
    p = _pending(data, pid)
    data["pending"].remove(p)
    return log_entry(data, "Inbox item dismissed", f"{p.get('date', '')} \xb7 {p.get('mt') or ''} MT \xb7 {reason}")


def intel_confirm(data, n, iso, esr, mt, note=""):
    """Move n unconfirmed intel cargoes to a confirmed China flash sale."""
    if not 1 <= n <= data["intel"]["cargoes"]:
        raise ValueError(f"Can clear 1\u2013{data['intel']['cargoes']} cargoes")
    data["intel"]["cargoes"] -= n
    return add_china_flash(data, iso, esr, mt, f"{note} (cleared {n} intel cargo(es))".strip())


def intel_discard(data, n, reason):
    if not 1 <= n <= data["intel"]["cargoes"]:
        raise ValueError(f"Can clear 1\u2013{data['intel']['cargoes']} cargoes")
    data["intel"]["cargoes"] -= n
    return log_entry(data, "Trade intel cleared", f"{n} cargo(es) \xb7 {reason}")


def unknown_review(data):
    """Unknown-destination rows, tagged against the current weekly cutoff.
    'covered' = dated on/before the cutoff, so the weekly China report may have
    absorbed it; 'new' = after the cutoff."""
    cutoff = data["baseline"]["cutoff"]
    return [{**r, "status": "covered" if r["date"] <= cutoff else "new"}
            for r in sorted(data["unknown"], key=lambda r: r["date"])]


def preview_weekly(data, label, cutoff_iso, outstanding, exports):
    """What applying a weekly ESR snapshot would change (no mutation)."""
    new = copy.deepcopy(data)
    new_baseline(new, label, cutoff_iso, outstanding, exports)
    b, a = summarize(data), summarize(new)
    return {
        "confirmed_before": b["confirmed_mt"], "confirmed_after": a["confirmed_mt"],
        "grand_before": b["grand_mt"], "grand_after": a["grand_mt"],
        "absorbed": [r for r in data["china_flash"] if r["date"] <= cutoff_iso],
        "unknown_candidates": [r for r in data["unknown"] if r["date"] <= cutoff_iso],
    }


def apply_weekly(data, label, cutoff_iso, outstanding, exports,
                 unknown_to_remove=(), clear_intel=0, note=""):
    """Apply a weekly snapshot (drops the flash rows it covers), then remove the
    unknown rows and intel cargoes the admin ticked, so nothing is double counted."""
    new_baseline(data, label, cutoff_iso, outstanding, exports)
    for iso, mt in unknown_to_remove:
        remove_unknown(data, iso, mt, note=note or f"absorbed/rebooked per {label} weekly report")
    if clear_intel:
        intel_discard(data, clear_intel, note or f"confirmed in {label} weekly report")
    data.pop("pending_weekly", None)
    return data
