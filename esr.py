"""USDA FAS ESR API: weekly soybean snapshot for China + unknown destinations.

Verified 2026-10-19: Wk 5 (week ending Oct 1) China = outstanding 8,804,000 +
accumulated exports 2,338,328 = 11,142,328, which matches the tracker baseline.
Country codes: China 5700, Unknown 9990. Soybeans = 801. `marketYear` is the year
the MY ends (2026/27 -> 2027).
"""
from datetime import date, timedelta

import requests

GATEWAY = "https://api.fas.usda.gov"
SOYBEANS, CHINA, UNKNOWN = 801, 5700, 9990


def fetch_weeks(api_key, country, marketing_year_end=2027, commodity=SOYBEANS):
    url = f"{GATEWAY}/api/esr/exports/commodityCode/{commodity}/countryCode/{country}/marketYear/{marketing_year_end}"
    r = requests.get(url, params={"api_key": api_key}, timeout=30)
    r.raise_for_status()
    return sorted(r.json(), key=lambda x: x["weekEndingDate"])


def week_label(week_end_iso, marketing_year_end=2027):
    """'Wk 5 (Oct 1)': Wk 1 is the first Thursday on/after Sep 1 of the MY start year."""
    we = date.fromisoformat(week_end_iso[:10])
    first = date(marketing_year_end - 1, 9, 1)
    first += timedelta(days=(3 - first.weekday()) % 7)  # Thursday
    n = 1 + (we - first).days // 7
    return f"Wk {n} ({we:%b} {we.day})"


def latest_snapshot(api_key, marketing_year_end=2027):
    """Latest weekly China + unknown-destination figures, or None if no data yet."""
    china = fetch_weeks(api_key, CHINA, marketing_year_end)
    if not china:
        return None
    c = china[-1]
    we = c["weekEndingDate"][:10]
    unk = next((u for u in fetch_weeks(api_key, UNKNOWN, marketing_year_end) if u["weekEndingDate"][:10] == we), None)
    return {
        "label": week_label(we, marketing_year_end),
        "cutoff": we,
        "outstanding": int(c["outstandingSales"]),
        "exports": int(c["accumulatedExports"]),
        "total_commitment": int(c["currentMYTotalCommitment"]),
        "unknown_net_sales": int(unk["currentMYNetSales"]) if unk else None,
        "unknown_outstanding": int(unk["outstandingSales"]) if unk else None,
    }


def unknown_weeks(api_key, marketing_year_end=2027):
    """Weekly soybean sales to UNKNOWN destinations: [{week, label, net_sales, outstanding}].
    A negative net_sales week means sales were rebooked out of unknown to a named destination."""
    out = []
    for r in fetch_weeks(api_key, UNKNOWN, marketing_year_end):
        we = r["weekEndingDate"][:10]
        out.append({"week": we, "label": week_label(we, marketing_year_end),
                    "net_sales": int(r["currentMYNetSales"]), "outstanding": int(r["outstandingSales"])})
    return out
