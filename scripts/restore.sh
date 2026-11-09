#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ] || [ "$1" != "--confirm-restore" ]; then
  echo "Usage: $0 --confirm-restore /absolute/path/to/zhijing-backup" >&2
  exit 2
fi

case "$2" in
  /*) backup_dir=${2%/} ;;
  *) echo "Backup directory must be an absolute path." >&2; exit 2 ;;
esac

for required in postgres.dump minio-data.tgz manifest.txt; do
  if [ ! -f "$backup_dir/$required" ]; then
    echo "Missing backup file: $backup_dir/$required" >&2
    exit 2
  fi
done

# Keep the restored stores isolated from writers while pg_restore cleans tables
# and the MinIO archive replaces objects.
docker compose stop api worker beat web nginx
docker compose up -d postgres redis minio

cat "$backup_dir/postgres.dump" | docker compose exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner'
cat "$backup_dir/minio-data.tgz" | docker compose exec -T minio sh -c \
  'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -C /data -xzf -'

docker compose up -d
echo "Restore submitted. Run ./scripts/healthcheck.sh after services become healthy."
