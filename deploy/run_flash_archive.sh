#!/bin/bash
# Every USDA flash sale (all commodities) -> Snowflake JSA.FLASH_SALES.SALES. Run through /opt/alerting/cron-alert.
cd /opt/china-soybean-tracker || exit 1
mkdir -p logs
exec 9>/tmp/flash-archive.lock; flock -n 9 || exit 0
git pull --ff-only -q
set -a; . ./.env; set +a
.venv/bin/python flash_archive.py run --days 5 >> logs/flash_archive.log 2>&1
