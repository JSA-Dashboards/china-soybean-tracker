"""Pure calculation + data helpers for the China Soybean Purchase Tracker.

All figures are metric tons (MT). MMT = MT / 1,000,000 rounded half-up to 3
decimals; percentages of the 25 MMT goal are rounded half-up to 1 decimal.
"""
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GOAL_MT = 25_000_000
DATA_PATH = Path(__file__).with_name("tracker_data.json")


def load(path=DATA_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(data, path=DATA_PATH):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    return data


def add_unknown(data, iso, esr, mt, note=""):
    data["unknown"].append({"date": iso, "esr": esr, "mt": mt, "note": note})
    data["as_of"] = max(data["as_of"], iso)
    return data


def remove_unknown(data, iso, mt, note="removed from the unknown-destination log per JSA desk update.", esr=""):
    """Drop one unknown-destination row (matched on date + MT) and footnote it."""
    for r in data["unknown"]:
        if r["date"] == iso and r["mt"] == mt:
            data["unknown"].remove(r)
            data["unknown_removed"].append({"date": iso, "esr": esr or r["esr"], "mt": mt, "note": note})
            return data
    raise ValueError(f"No unknown-destination row on {iso} for {mt:,} MT")


def set_intel(data, cargoes, week=None, mt_per_cargo=None):
    """Set trade intel outright (replaces, never adds). Week label kept unless given."""
    data["intel"]["cargoes"] = cargoes
    if week:
        data["intel"]["week"] = week
    if mt_per_cargo:
        data["intel"]["mt_per_cargo"] = mt_per_cargo
    return data


def new_baseline(data, label, cutoff_iso, outstanding, exports, source=None):
    """New weekly ESR snapshot: replaces the baseline and every flash row it covers
    (flash dated on/before the cutoff), so nothing is counted twice."""
    data["baseline"].update(
        label=label, cutoff=cutoff_iso, outstanding_sales=outstanding,
        accumulated_exports=exports, source=source or f"USDA ESR Query System, {label}",
    )
    data["china_flash"] = [r for r in data["china_flash"] if r["date"] > cutoff_iso]
    return data
