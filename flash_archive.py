"""Archive of EVERY USDA daily flash export sale (all commodities, all destinations, all marketing years).

  python flash_archive.py run [--days N]     read the FAS mailbox, MERGE new items into Snowflake JSA.FLASH_SALES
  python flash_archive.py backfill --days N  same, wider window (mailbox is scanned by date, ~200 msgs/day)
  python flash_archive.py setup              create the schema/table/views only
  python flash_archive.py parse-file X       parse a saved .msg/.eml/.txt and print the items (no writes)
  python flash_archive.py --dry-run ...      with run/backfill: fetch + parse, print, no Snowflake

Separate from the China tracker's review-first Inbox: that decides what COUNTS toward the 25 MMT; this is a
plain record of what USDA reported, one row per item, so it keeps switches / cancellations / revisions as rows
(flags column) instead of dropping them. Nothing here touches tracker_data.json.

One row per item in a release ('N metric tons of X for delivery to Y during the MY marketing year'),
keyed (MESSAGE_ID, ITEM_IDX), so reruns and overlapping windows are idempotent.

Mail source and env: same Graph delegated token as ingest.py (see its docstring), plus the fleet-standard
SNOWFLAKE_* vars (SNOWFLAKE_PRIVATE_KEY_PATH / _PRIVATE_KEY, optional _PWD).
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import ingest as ig

SCHEMA = "FLASH_SALES"
TABLE = "SALES"

# Longest names first so "soybean meal" is not read as "soybeans".
COMMODITIES = [
    ("soybean meal", "Soybean Meal"), ("soybeans meal", "Soybean Meal"), ("soymeal", "Soybean Meal"),
    ("soybean oil", "Soybean Oil"), ("soyoil", "Soybean Oil"), ("soybean cake", "Soybean Cake"),
    ("soybeans", "Soybeans"), ("soybean", "Soybeans"),
    ("hard red winter wheat", "Wheat"), ("hard red spring wheat", "Wheat"), ("soft red winter wheat", "Wheat"),
    ("white wheat", "Wheat"), ("durum wheat", "Wheat"), ("wheat", "Wheat"),
    ("corn", "Corn"), ("sorghum", "Sorghum"), ("barley", "Barley"), ("oats", "Oats"), ("oat", "Oats"),
    ("rice", "Rice"), ("cotton", "Cotton"), ("beef", "Beef"), ("pork", "Pork"), ("ddgs", "DDGS"),
]
FLAG_RES = [
    ("switch", re.compile(r"switch", re.I)),
    ("cancel", re.compile(r"cancel", re.I)),
    ("reduction", re.compile(r"reduc", re.I)),
    ("destination_change", re.compile(r"chang(?:e|es|ed)\s+in\s+destination", re.I)),
    ("rebooked", re.compile(r"rebook", re.I)),
    ("revision", re.compile(r"revis|correct|previously", re.I)),
]
DEST_ANY_RE = re.compile(
    r"(?:delivery\s+to|destined\s+for|(?:switched|changed|shifted)\s+to|\bto)\s+"
    r"(unknown\s+destinations?|[A-Z][\w'’.&-]*(?:\s+(?:and\s+)?[A-Z][\w'’.&-]*)*)")


def _commodity(seg):
    low = seg.lower()
    m = re.search(r"(?:metric\s+tons?|MT)\s+of\s+(.+?)(?=\s+(?:for|to|during|in|previously)\b|[,.;]|$)", low)
    probe = m.group(1) if m else low
    for needle, name in COMMODITIES:
        if re.search(r"\b" + re.escape(needle) + r"\b", probe):
            return name
    for needle, name in COMMODITIES:  # fall back to anywhere in the item
        if re.search(r"\b" + re.escape(needle) + r"\b", low):
            return name
    return m.group(1).strip().title() if m else ""


def _marketing_years(seg):
    return sorted({f"{a}/{b}" for a, b in ig.MY_RE.findall(seg)})


def _destinations(seg):
    dests = []
    for d in DEST_ANY_RE.findall(seg):
        if d.startswith(ig.IGNORE_DEST):
            continue
        d = "Unknown Destinations" if d.lower().startswith("unknown") else d.strip()
        if d not in dests:
            dests.append(d)
    return dests


def parse_items(text, received_iso, subject=""):
    """Every sale item in one release -> list of row dicts (no filtering by commodity/destination/year)."""
    esr_m = ig.ESR_RE.search(subject + " " + text)
    esr = esr_m.group(1).zfill(3) if esr_m else ""
    core = ig._core(text)
    starts = [m.start() for m in ig.AMOUNT_RE.finditer(core)]
    rows, seen = [], set()
    for i, s0 in enumerate(starts):
        seg = core[s0: starts[i + 1] if i + 1 < len(starts) else len(core)]
        end = re.search(r"marketing\s+year\.?", seg, re.I)
        seg = (seg[:end.end()] if end else seg[:300]).strip()
        if seg in seen:  # the HTML preview repeats the body
            continue
        seen.add(seg)
        mt = int(ig.AMOUNT_RE.match(seg).group(1).replace(",", ""))
        my = _marketing_years(seg)
        dests = _destinations(seg)
        rows.append({
            "sale_date": received_iso[:10], "esr": esr, "commodity": _commodity(seg), "mt": mt,
            "destination": " / ".join(dests), "marketing_year": " & ".join(my),
            "flags": ",".join(n for n, rx in FLAG_RES if rx.search(seg)),
            "excerpt": seg[:600], "subject": subject, "received": received_iso,
        })
    for idx, r in enumerate(rows):
        r["item_idx"] = idx
    return rows


def rows_for_messages(msgs):
    out = []
    for m in msgs:
        for r in parse_items(m["body"], m["received"], m["subject"]):
            out.append({**r, "message_id": m["id"]})
    return out


# ---------------------------------------------------------------- Snowflake
def sf_connect():
    import snowflake.connector
    kw = dict(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
              role=os.environ.get("SNOWFLAKE_ROLE") or None, warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
              database="JSA", login_timeout=30)  # database pinned: a shared .env must not redirect this job
    path = (os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH") or "").strip()
    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY") or ""
    if path or pem.strip():
        from cryptography.hazmat.primitives import serialization
        data = open(path, "rb").read() if path else pem.replace("\\n", "\n").encode()
        pwd = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD") or None
        key = serialization.load_pem_private_key(data, password=pwd.encode() if pwd else None)
        kw["private_key"] = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption())
    else:
        kw["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    return snowflake.connector.connect(**kw)


def setup(conn):
    cur = conn.cursor()
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS JSA.{SCHEMA}")
    cur.execute(f"USE SCHEMA JSA.{SCHEMA}")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            MESSAGE_ID     VARCHAR NOT NULL,
            ITEM_IDX       NUMBER(4,0) NOT NULL,
            SALE_DATE      DATE NOT NULL,          -- release date, America/Chicago
            RECEIVED       VARCHAR,                -- ISO timestamp the email arrived (CT)
            ESR            VARCHAR,                -- FAS-ESR release number
            COMMODITY      VARCHAR,
            MT             NUMBER(12,0),
            DESTINATION    VARCHAR,                -- 'Unknown Destinations' kept as such
            MARKETING_YEAR VARCHAR,                -- e.g. 2026/27 ('2025/26 & 2026/27' if both named)
            FLAGS          VARCHAR,                -- switch,cancel,reduction,rebooked,revision,...
            EXCERPT        VARCHAR,
            SUBJECT        VARCHAR,
            LOADED_AT      TIMESTAMP_NTZ,
            PRIMARY KEY (MESSAGE_ID, ITEM_IDX)
        )""")
    cur.execute(f"""
        CREATE OR REPLACE VIEW DAILY AS
        SELECT SALE_DATE, COMMODITY, DESTINATION, MARKETING_YEAR, SUM(MT) AS MT, COUNT(*) AS ITEMS,
               MAX(IFF(FLAGS <> '', 1, 0)) = 1 AS HAS_FLAGS
        FROM {TABLE} GROUP BY 1, 2, 3, 4""")
    for stmt in (f"GRANT USAGE ON SCHEMA JSA.{SCHEMA} TO ROLE JSA_ANALYST",
                 f"GRANT SELECT ON ALL TABLES IN SCHEMA JSA.{SCHEMA} TO ROLE JSA_ANALYST",
                 f"GRANT SELECT ON ALL VIEWS IN SCHEMA JSA.{SCHEMA} TO ROLE JSA_ANALYST"):
        try:
            cur.execute(stmt)
        except Exception as e:  # role absent on this account: not fatal
            print(f"  (grant skipped: {str(e).splitlines()[0]})")
            break


def load(conn, rows):
    if not rows:
        print("  nothing to load")
        return
    loaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute(f"USE SCHEMA JSA.{SCHEMA}")
    tmpdir = tempfile.mkdtemp(prefix="flash_")  # no spaces in the path: PUT does not quote reliably
    path = os.path.join(tmpdir, "flash.json")
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    try:
        cur.execute("CREATE OR REPLACE TEMPORARY STAGE _FLASH_STAGE FILE_FORMAT = (TYPE = JSON)")
        cur.execute("CREATE OR REPLACE TEMPORARY TABLE _FLASH_RAW (V VARIANT)")
        cur.execute(f"PUT 'file://{Path(path).as_posix()}' @_FLASH_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
        cur.execute("COPY INTO _FLASH_RAW FROM @_FLASH_STAGE PURGE = TRUE")
        cur.execute(f"""
            MERGE INTO {TABLE} t USING (
                SELECT V:message_id::VARCHAR AS MESSAGE_ID, V:item_idx::NUMBER AS ITEM_IDX,
                       TO_DATE(V:sale_date::VARCHAR) AS SALE_DATE, V:received::VARCHAR AS RECEIVED,
                       V:esr::VARCHAR AS ESR, V:commodity::VARCHAR AS COMMODITY, V:mt::NUMBER AS MT,
                       V:destination::VARCHAR AS DESTINATION, V:marketing_year::VARCHAR AS MARKETING_YEAR,
                       V:flags::VARCHAR AS FLAGS, V:excerpt::VARCHAR AS EXCERPT, V:subject::VARCHAR AS SUBJECT
                FROM _FLASH_RAW
                QUALIFY ROW_NUMBER() OVER (PARTITION BY MESSAGE_ID, ITEM_IDX ORDER BY RECEIVED DESC) = 1
            ) s ON t.MESSAGE_ID = s.MESSAGE_ID AND t.ITEM_IDX = s.ITEM_IDX
            WHEN MATCHED THEN UPDATE SET t.SALE_DATE = s.SALE_DATE, t.RECEIVED = s.RECEIVED, t.ESR = s.ESR,
                t.COMMODITY = s.COMMODITY, t.MT = s.MT, t.DESTINATION = s.DESTINATION,
                t.MARKETING_YEAR = s.MARKETING_YEAR, t.FLAGS = s.FLAGS, t.EXCERPT = s.EXCERPT,
                t.SUBJECT = s.SUBJECT, t.LOADED_AT = '{loaded_at}'
            WHEN NOT MATCHED THEN INSERT (MESSAGE_ID, ITEM_IDX, SALE_DATE, RECEIVED, ESR, COMMODITY, MT, DESTINATION,
                MARKETING_YEAR, FLAGS, EXCERPT, SUBJECT, LOADED_AT)
            VALUES (s.MESSAGE_ID, s.ITEM_IDX, s.SALE_DATE, s.RECEIVED, s.ESR, s.COMMODITY, s.MT, s.DESTINATION,
                s.MARKETING_YEAR, s.FLAGS, s.EXCERPT, s.SUBJECT, '{loaded_at}')""")
        ins, upd = cur.fetchone()[:2]
        conn.commit()
        print(f"  {len(rows)} items parsed, {ins} inserted, {upd} updated")
    finally:
        try:
            os.remove(path)
            os.rmdir(tmpdir)
        except OSError:
            pass


def _get(requests, url, token, params=None, tries=5):
    """GET with Graph throttling (429/503) honoured."""
    import time
    for i in range(tries):
        r = requests.get(url, headers={"Authorization": "Bearer " + token}, params=params, timeout=60)
        if r.status_code in (429, 503, 504):
            time.sleep(min(int(r.headers.get("Retry-After", 5 * (i + 1))), 60))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def fetch_light(days, progress=True):
    """FAS emails for the last `days` days, one day at a time. Lists headers only (no bodies) and fetches the
    body just for sender/subject matches, so a long window is light on memory, Graph and the droplet."""
    import requests
    from datetime import timedelta
    env = ig._env()
    sender = env.get("FAS_SENDER_MATCH", "usda").lower()
    subject_match = env.get("FAS_SUBJECT_MATCH", "export sales").lower()
    base = f"https://graph.microsoft.com/v1.0/users/{env['GRAPH_INBOX_USER']}/messages"
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    found = []
    for back in range(days, -1, -1):
        start, end = today - timedelta(days=back), today - timedelta(days=back - 1)
        token = ig._graph_token(env)  # silent refresh each day: a long run outlives one token
        params = {"$filter": f"receivedDateTime ge {start:%Y-%m-%dT%H:%M:%SZ} and receivedDateTime lt {end:%Y-%m-%dT%H:%M:%SZ}",
                  "$top": "100", "$select": "id,internetMessageId,subject,receivedDateTime,from"}
        url, n_all, n_hit = base, 0, 0
        while url:
            data = _get(requests, url, token, params)
            params = None
            for g in data.get("value", []):
                n_all += 1
                addr = ((g.get("from") or {}).get("emailAddress") or {})
                who = f"{addr.get('name', '')} {addr.get('address', '')}".lower()
                if sender in who and subject_match in (g.get("subject") or "").lower():
                    full = _get(requests, f"{base}/{g['id']}", token,
                                {"$select": "id,internetMessageId,subject,receivedDateTime,body"})
                    found.append(ig.normalize_graph_message(full))
                    n_hit += 1
            url = data.get("@odata.nextLink")
        if progress:
            print(f"  {start:%Y-%m-%d}: {n_all} messages, {n_hit} FAS", flush=True)
    return sorted(found, key=lambda m: m["received"])


def run(days, dry=False, max_pages=None):
    msgs = fetch_light(days)
    rows = rows_for_messages(msgs)
    print(f"{len(msgs)} FAS emails, {len(rows)} items")
    if dry:
        for r in rows:
            print(f"  {r['sale_date']} ESR-{r['esr']} {r['mt']:>9,} MT {r['commodity']:<13} -> {r['destination']} "
                  f"[{r['marketing_year']}] {r['flags']}")
        return
    conn = sf_connect()
    try:
        setup(conn)
        load(conn, rows)
    finally:
        conn.close()


def _arg(name, default):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    dry = "--dry-run" in sys.argv
    if cmd == "run":
        run(_arg("--days", 5), dry)
    elif cmd == "backfill":
        run(_arg("--days", 365), dry)
    elif cmd == "setup":
        c = sf_connect()
        setup(c)
        c.close()
    elif cmd == "parse-file":
        p = sys.argv[2]
        if p.lower().endswith(".msg"):
            import extract_msg  # pip install extract-msg (local use only)
            m = extract_msg.Message(p)
            body = m.body or ig.html_to_text((m.htmlBody or b"").decode("utf-8", "replace"))
            items = parse_items(body, str(m.date)[:16].replace(" ", "T"), str(m.subject))
        else:
            import email
            raw = open(p, "rb").read()
            msg = email.message_from_bytes(raw)
            body = ig._body(msg) if msg.get("Subject") else raw.decode("utf-8", errors="replace")
            items = parse_items(body, ig._received_ct(msg) if msg.get("Date") else datetime.now().isoformat(),
                                str(msg.get("Subject", "")))
        print(json.dumps(items, indent=2))
    else:
        print(__doc__)
