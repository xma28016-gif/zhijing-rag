#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /absolute/backup-root" >&2
  exit 2
fi

case "$1" in
  /*) backup_root=$1 ;;
  *) echo "Backup root must be an absolute path." >&2; exit 2 ;;
esac

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="${backup_root%/}/zhijing-${timestamp}"
mkdir -p "$backup_dir"

docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' \
  > "$backup_dir/postgres.dump"
docker compose exec -T minio tar -C /data -czf - . > "$backup_dir/minio-data.tgz"

cat > "$backup_dir/manifest.txt" <<EOF
created_at=${timestamp}
postgres_dump=postgres.dump
minio_archive=minio-data.tgz
compose_project=zhijing-rag
EOF

chmod 600 "$backup_dir/postgres.dump" "$backup_dir/minio-data.tgz" "$backup_dir/manifest.txt"
echo "$backup_dir"
