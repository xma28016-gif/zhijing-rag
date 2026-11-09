#!/usr/bin/env sh
set -eu

target="${1:-.env}"
if [ -e "$target" ]; then
  echo "$target already exists; refusing to overwrite it." >&2
  exit 1
fi

master_key="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"
postgres_password="$(openssl rand -hex 24)"
minio_password="$(openssl rand -hex 24)"

sed \
  -e "s#replace-with-urlsafe-base64-32-byte-key#$master_key#" \
  -e "s#replace-with-strong-database-password#$postgres_password#" \
  -e "s#replace-with-strong-minio-password#$minio_password#" \
  .env.example > "$target"

chmod 600 "$target"
echo "Created $target with generated local secrets."
