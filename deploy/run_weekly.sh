#!/bin/bash
# Latest weekly ESR snapshot -> admin "Weekly report" (queued only if newer than the baseline).
cd /opt/china-soybean-tracker || exit 1
mkdir -p logs
exec 9>/tmp/china-soy-weekly.lock; flock -n 9 || exit 0
git pull --ff-only -q
set -a; . ./.env; set +a
.venv/bin/python ingest.py weekly >> logs/weekly.log 2>&1
