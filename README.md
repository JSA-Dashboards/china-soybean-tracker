# China Soybean Purchase Tracker

Streamlit app tracking progress toward China's 25 MMT/yr U.S. soybean commitment (2026/27 MY).
Three buckets: **China confirmed** (ESR weekly baseline + post-cutoff flash sales), **unknown destinations**
(logged flash sales), **unconfirmed trade intel** (cargoes x 60,000 MT). Data lives in `tracker_data.json`.

## Files
- `streamlit_app.py` — Snapshot (PNG/copy buttons), What's included, Change log, Admin tabs
- `tracker_logic.py` — all math + edit operations; `update_tracker.py` — command-line edits
- `admin.py` — Admin tab (Inbox, Weekly report, Unknown destinations, Trade intel, Manual entry)
- `store.py` — reads/commits `tracker_data.json` via the GitHub contents API (repo = database)
- `ingest.py` — droplet job: FAS mailbox -> Inbox; ESR weekly -> Weekly report. `esr.py` — ESR API
- Tests: `python -m pytest -q`

## Admin flow (nothing counts until a human confirms)
1. **Inbox** — flash sales parsed from the mailbox. Clean ones are pre-filled; ambiguous ones are marked *review*.
   Approve as China-confirmed or Unknown, or dismiss.
2. **Weekly report** — new ESR week (auto-fetched or typed). Preview shows the flash rows it absorbs; tick the
   unknown-destination rows and intel cargoes it also absorbed, then Apply. Unknown net sales < 0 in the ESR week
   means sales were rebooked out of unknown.
3. **Unknown destinations** — remove rows (reason required). Rows dated on/before the weekly cutoff are flagged *covered*.
4. **Trade intel** — set count, move cargoes to a confirmed flash (net total unchanged), or discard.

## Streamlit Cloud secrets
```toml
ADMIN_PASSWORD = "..."              # gates the Admin tab (locked if missing)
GITHUB_TOKEN   = "github_pat_..."   # fine-grained, this repo only, Contents: read+write
FAS_API_KEY    = "..."              # optional: "Check ESR" button
```
Public view needs none of these. Admin saves are commits; Cloud redeploys in ~1 minute.

## Droplet (not deployed yet)
`/opt/china-soybean-tracker` = git clone + `.venv` (`pip install requests`) + `.env` (chmod 600) with
`IMAP_HOST IMAP_USER IMAP_PASSWORD [IMAP_FOLDER] [FAS_SENDER_MATCH=usda] [FAS_SUBJECT_MATCH="export sales"] FAS_API_KEY GITHUB_TOKEN`.
Wrappers in `deploy/` (executable bit is committed). Droplet time is America/Chicago; FAS emails land ~8:02 CT.
```
10 8,9,10 * * 1-5  /opt/alerting/cron-alert "China soy flash ingest" "/opt/china-soybean-tracker/logs/*.log" /opt/china-soybean-tracker/deploy/run_flash.sh
45 7,11 * * 1-5    /opt/alerting/cron-alert "China soy weekly ESR" "/opt/china-soybean-tracker/logs/*.log" /opt/china-soybean-tracker/deploy/run_weekly.sh
```
Subscribe the mailbox at https://public.govdelivery.com/accounts/USDAFAS/subscriber/new (www.fas.usda.gov blocks scripts).
Check the parser on any new release type: `python ingest.py parse-file sample.msg` (prints, writes nothing).
Releases already in the tracker are skipped as duplicates; ambiguous ones land in the Inbox as *review*.
