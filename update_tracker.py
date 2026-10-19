"""Update tracker_data.json. Usage (from this folder):

  python update_tracker.py flash   2026-10-20 093 150000 [--note "..."]   # soybeans confirmed to China
  python update_tracker.py unknown 2026-10-20 093 150000 [--note "..."]   # soybeans to unknown destinations
  python update_tracker.py intel   4 [--week "Wk of Oct 5"]               # sets cargoes outright
  python update_tracker.py baseline "Wk 6 (Oct 8)" 2026-10-08 9000000 2500000   # label cutoff outstanding exports
  python update_tracker.py remove-unknown 2026-08-03 136150 [--note "..."]

Only enter figures you have from USDA FAS / the desk. Then commit + push to redeploy.
"""
import argparse

import tracker_logic as t

p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
for name in ("flash", "unknown"):
    s = sub.add_parser(name)
    s.add_argument("date"); s.add_argument("esr"); s.add_argument("mt", type=int); s.add_argument("--note", default="")
s = sub.add_parser("intel"); s.add_argument("cargoes", type=int); s.add_argument("--week")
s = sub.add_parser("baseline")
s.add_argument("label"); s.add_argument("cutoff"); s.add_argument("outstanding", type=int); s.add_argument("exports", type=int)
s = sub.add_parser("remove-unknown"); s.add_argument("date"); s.add_argument("mt", type=int); s.add_argument("--note")
a = p.parse_args()

data = t.load()
if a.cmd == "flash":
    t.add_china_flash(data, a.date, a.esr, a.mt, a.note)
elif a.cmd == "unknown":
    t.add_unknown(data, a.date, a.esr, a.mt, a.note)
elif a.cmd == "intel":
    t.set_intel(data, a.cargoes, a.week)
elif a.cmd == "baseline":
    t.new_baseline(data, a.label, a.cutoff, a.outstanding, a.exports)
elif a.cmd == "remove-unknown":
    kw = {"note": a.note} if a.note else {}
    t.remove_unknown(data, a.date, a.mt, **kw)
t.save(data)
s = t.summarize(data)
print(f"Confirmed {t.mmt(s['confirmed_mt'])} + Unknown {t.mmt(s['unknown_mt'])} + Intel {t.mmt(s['intel_mt'])} "
      f"= {t.mmt(s['grand_mt'])} MMT ({t.pct(s['grand_mt'])}% of 25 MMT)")
