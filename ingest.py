"""Inbox ingest for the China Soybean Tracker (runs on the droplet via cron).

  python ingest.py flash            read the FAS mailbox, queue flash sales for admin review
  python ingest.py weekly           fetch the latest ESR week; queue it if newer than the baseline
  python ingest.py parse-file X     parse a saved email/text file and print the result (no writes)

Nothing here changes the published totals. Everything lands in the admin Inbox /
Weekly report for a human to confirm. Parser is deliberately strict: a sentence is
a clean candidate only if it is exactly one amount of *soybeans* to *China* or
*unknown destinations* for the *2026/27* marketing year, with no switch / cancel /
reduction wording. Everything else is queued as "review".

Env (droplet): IMAP_HOST, IMAP_USER, IMAP_PASSWORD, [IMAP_FOLDER=INBOX],
[FAS_SENDER_MATCH=usda], FAS_API_KEY, GITHUB_TOKEN (contents:write on the repo).
"""
import email
import imaplib
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from html import unescape

import tracker_logic as t

MY_TARGET = "2026/27"
ESR_RE = re.compile(r"ESR[\s\-]*(\d{2,3})(?:-\d{2})?", re.I)
AMOUNT_RE = re.compile(r"([\d,]{4,})\s*(?:metric\s+tons?|MT)\b", re.I)
MY_RE = re.compile(r"\b(20\d\d)\s*/\s*(?:20)?(\d\d)\b")
DEST_RE = re.compile(r"(?:delivery\s+to|destined\s+for|\bto)\s+(unknown\s+destinations?|[A-Z][\w'’.&-]*(?:\s+[A-Z][\w'’.&-]*)*)")
COMMODITY_RE = re.compile(r"(?:metric\s+tons?|MT)\s+of\s+([A-Za-z ]+?)(?=\s+(?:for|to|during|in)\b|[,.;]|$)", re.I)
SOY_RE = re.compile(r"soybeans?(?![a-z])(?!\s+(?:meal|oil|cake))", re.I)
NONSOY_SOY_RE = re.compile(r"soy\w*\s+(?:meal|oil|cake)|soymeal|soyoil", re.I)
NONSOY_RE = re.compile(r"corn|wheat|sorghum|barley|oats?|rice|cotton|meal|oil|cake|pork|beef|chicken|ethanol|ddgs", re.I)
RISKY = re.compile(r"switch|cancel|reduc|chang(?:e|es|ed)\s+in\s+destination|rebook|revis|correct|previously", re.I)
IGNORE_DEST = ("U.S", "USDA", "Department", "Export", "Private")


def _norm_dest(raw):
    r = raw.strip().lower()
    return "unknown" if r.startswith("unknown") else r


def _core(text):
    """The release body only: after the last 'FAS-ESR-NNN' header (the .msg/HTML preview
    repeats the text, and the first copy is truncated), before the legal boilerplate."""
    flat = re.sub(r"\s+", " ", text)
    marks = list(re.finditer(r"FAS[\s-]*ESR[\s-]*\d{2,3}", flat, re.I))
    if marks:
        flat = flat[marks[-1].start():]
    cut = re.search(r"###|The U\.S\. Department of Agriculture is required", flat)
    return flat[:cut.start()] if cut else flat


def parse_text(text, received_iso, subject=""):
    """Return {'clean': [...], 'review': [...], 'out_of_scope': [...]} for one email body.
    FAS flash releases are a short list of items, each 'N metric tons of <commodity> for
    delivery to <destination> during the <MY> marketing year', so the text is split at each
    amount and every item is judged on its own."""
    esr_m = ESR_RE.search(subject + " " + text)
    esr = esr_m.group(1).zfill(3) if esr_m else ""
    out = {"clean": [], "review": [], "out_of_scope": []}
    core = _core(text)
    risky = RISKY.search(core)  # switch/cancel wording anywhere taints every soybean item
    starts = [m.start() for m in AMOUNT_RE.finditer(core)]
    seen = set()
    for i, s0 in enumerate(starts):
        seg = core[s0: starts[i + 1] if i + 1 < len(starts) else len(core)]
        end = re.search(r"marketing\s+year\.?", seg, re.I)
        seg = (seg[:end.end()] if end else seg[:300]).strip()
        if seg in seen:
            continue
        seen.add(seg)
        amt = AMOUNT_RE.match(seg)
        mt = int(amt.group(1).replace(",", ""))
        com_m = COMMODITY_RE.search(seg)
        commodity = com_m.group(1).strip().lower() if com_m else ""
        if SOY_RE.search(seg) and not NONSOY_SOY_RE.search(commodity):
            commodity = "soybeans"  # "soybeans previously reported ..." must not slip out of scope
        elif commodity and not NONSOY_RE.search(commodity):
            commodity = ""  # unfamiliar commodity text -> review, never silently dropped
        dests = {_norm_dest(d) for d in DEST_RE.findall(seg) if not d.startswith(IGNORE_DEST)}
        mys = {f"{a}/{b}" for a, b in MY_RE.findall(seg)}
        base = {"date": received_iso[:10], "esr": esr, "excerpt": seg[:400]}
        if commodity and commodity != "soybeans":
            out["out_of_scope"].append({**base, "commodity": commodity.title(),
                                        "dest": ", ".join(d.title() for d in sorted(dests)) or "\u2014", "mt": mt})
            continue
        reasons = []
        if not commodity:
            reasons.append("commodity not recognised")
        if risky:
            reasons.append("switch / cancel / reduction wording in the release")
        if dests not in ({"china"}, {"unknown"}):
            reasons.append(f"destination not exactly China or unknown ({', '.join(sorted(dests)) or 'none found'})")
        if mys != {MY_TARGET}:
            reasons.append(f"marketing year {', '.join(sorted(mys)) or 'not stated'} (need {MY_TARGET} only)")
        if reasons:
            out["review"].append({**base, "mt": mt, "dest": None, "reason": "; ".join(reasons)})
        else:
            out["clean"].append({**base, "mt": mt, "dest": next(iter(dests)),
                                 "reason": "" if esr else "no ESR number found \u2014 enter it on approval"})
    return out


# ---- mailbox --------------------------------------------------------------

def html_to_text(h):
    return unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</>", " ", h)))


def _body(msg):
    parts = [p for p in msg.walk() if p.get_content_maintype() == "text"] if msg.is_multipart() else [msg]
    plain = [p for p in parts if p.get_content_subtype() == "plain"]
    chosen = plain[0] if plain else (parts[0] if parts else None)
    if chosen is None:
        return ""
    raw = chosen.get_payload(decode=True) or b""
    txt = raw.decode(chosen.get_content_charset() or "utf-8", errors="replace")
    if chosen.get_content_subtype() == "html":
        txt = unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", txt)))
    return txt


def _received_ct(msg):
    dt = email.utils.parsedate_to_datetime(msg["Date"]) if msg["Date"] else datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo("America/Chicago"))
    except Exception:
        pass
    return dt.isoformat(timespec="minutes")


def fetch_messages(days=5):
    host, user, pw = os.environ["IMAP_HOST"], os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"]
    match = os.environ.get("FAS_SENDER_MATCH", "usda").lower()
    subject_match = os.environ.get("FAS_SUBJECT_MATCH", "export sales").lower()
    box = imaplib.IMAP4_SSL(host)
    box.login(user, pw)
    box.select(os.environ.get("IMAP_FOLDER", "INBOX"), readonly=True)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, ids = box.search(None, f'(SINCE "{since}")')
    for num in ids[0].split():
        _, parts = box.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(parts[0][1])
        subj = str(make_header(decode_header(msg.get("Subject", ""))))
        if match not in str(msg.get("From", "")).lower() or subject_match not in subj.lower():
            continue
        yield {
            "id": str(msg.get("Message-ID", num)).strip(),
            "subject": str(make_header(decode_header(msg.get("Subject", "")))),
            "received": _received_ct(msg),
            "body": _body(msg),
        }
    box.logout()


def ingest_flash():
    import store
    summary = {"messages": 0, "queued": 0, "review": 0, "out_of_scope": 0}
    msgs = list(fetch_messages())

    def apply(data):
        seen = set(data.setdefault("ingest_seen", []))
        for m in msgs:
            if m["id"] in seen:
                continue
            summary["messages"] += 1
            res = queue_result(data, m)
            for k in ("queued", "review", "out_of_scope"):
                summary[k] += res[k]
            data["ingest_seen"].append(m["id"])
        data["ingest_seen"] = data["ingest_seen"][-500:]

    if msgs:
        store.update(apply, "Inbox: queue new FAS flash-sale emails for review")
    return summary


def queue_result(data, m):
    res = parse_text(m["body"], m["received"], m["subject"])
    n = {"queued": 0, "review": 0, "out_of_scope": 0}
    for kind, items in (("flash", res["clean"]), ("review", res["review"])):
        for it in items:
            added = t.add_pending(data, {**it, "kind": kind, "source": f"email:{m['id']}",
                                         "subject": m["subject"], "received": m["received"]})
            n["queued" if kind == "flash" else "review"] += int(added)
    for it in res["out_of_scope"]:  # informational only: never touches totals
        row = {"date": it["date"], "esr": it["esr"], "commodity": it["commodity"], "destination": it["dest"],
               "mt": it["mt"], "reason": "Out of scope (not soybeans)"}
        if row not in data.setdefault("excluded", []):
            data["excluded"].append(row)
            n["out_of_scope"] += 1
    return n


def ingest_weekly():
    import esr
    import store
    key = store.cfg("FAS_API_KEY")
    if not key:
        raise SystemExit("FAS_API_KEY not set")
    snap = esr.latest_snapshot(key)
    result = {"queued": False, "label": snap and snap["label"]}

    def apply(data):
        if snap and snap["cutoff"] > data["baseline"]["cutoff"] and data.get("pending_weekly", {}).get("cutoff") != snap["cutoff"]:
            data["pending_weekly"] = {**snap, "fetched": t._now()}
            result["queued"] = True

    store.update(apply, "Inbox: new weekly ESR snapshot available")
    return result


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "flash":
        print(ingest_flash())
    elif cmd == "weekly":
        print(ingest_weekly())
    elif cmd == "parse-file":
        if sys.argv[2].lower().endswith(".msg"):
            import extract_msg  # pip install extract-msg (local use only)
            m = extract_msg.Message(sys.argv[2])
            body = m.body or html_to_text((m.htmlBody or b"").decode("utf-8", "replace"))
            import json
            print(json.dumps(parse_text(body, str(m.date)[:16].replace(" ", "T"), str(m.subject)), indent=2))
            sys.exit(0)
        raw = open(sys.argv[2], "rb").read()
        msg = email.message_from_bytes(raw)
        body = _body(msg) if msg.get("Subject") else raw.decode("utf-8", errors="replace")
        import json
        print(json.dumps(parse_text(body, _received_ct(msg) if msg.get("Date") else datetime.now().isoformat(),
                                    str(msg.get("Subject", ""))), indent=2))
    else:
        print(__doc__)
