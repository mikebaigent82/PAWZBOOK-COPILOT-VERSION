#!/bin/sh
# Dump the database once a day; delete dumps older than KEEP_DAYS.
# Restore with:  gunzip -c FILE.sql.gz | docker compose exec -T db psql -U planner -d planner
set -eu
while true; do
  stamp=$(date -u +%Y%m%d-%H%M%S)
  pg_dump -h db -U planner -d planner --no-owner | gzip > "/backups/planner-$stamp.sql.gz.part"
  mv "/backups/planner-$stamp.sql.gz.part" "/backups/planner-$stamp.sql.gz"
  find /backups -name 'planner-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
  echo "backup written: planner-$stamp.sql.gz"
  sleep 86400
done
