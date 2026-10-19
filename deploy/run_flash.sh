#!/bin/bash
# FAS flash-sale mailbox -> admin Inbox. Run through /opt/alerting/cron-alert.
cd /opt/china-soybean-tracker || exit 1
mkdir -p logs
exec 9>/tmp/china-soy-flash.lock; flock -n 9 || exit 0
git pull --ff-only -q
set -a; . ./.env; set +a
.venv/bin/python ingest.py flash >> logs/flash.log 2>&1
