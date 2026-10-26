#!/bin/sh
set -eu
destination="${1:-./artifacts/backups}"
mkdir -p "$destination"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose exec -T postgres pg_dump -U supportpilot -d supportpilot -Fc > "$destination/database-$stamp.dump"
docker compose exec -T api tar -C /app/data -czf - uploads > "$destination/uploads-$stamp.tar.gz"
printf 'Backup written to %s. Also back up ENCRYPTION_KEY and server configuration in a separate secret store.\n' "$destination"
