#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
RUNTIME="$ROOT/.runtime"
mkdir -p "$RUNTIME/downloads"
PG_VERSION=17.11
REDIS_VERSION=7.4.5
VECTOR_VERSION=0.8.1

fetch() {
  if [ -f "$2" ] && tar -tf "$2" >/dev/null 2>&1; then return; fi
  curl --fail --location --http1.1 --continue-at - --retry 3 --retry-all-errors \
    --connect-timeout 20 --max-time 1800 --output "$2" "$1"
}

if [ ! -x "$RUNTIME/postgres/bin/pg_ctl" ]; then
  fetch "https://ftp.postgresql.org/pub/source/v$PG_VERSION/postgresql-$PG_VERSION.tar.bz2" "$RUNTIME/downloads/postgresql.tar.bz2"
  tar -xjf "$RUNTIME/downloads/postgresql.tar.bz2" -C "$RUNTIME"
  (cd "$RUNTIME/postgresql-$PG_VERSION"; ./configure --prefix="$RUNTIME/postgres" --without-icu --without-readline --without-zlib; make -j4; make install)
fi
if [ ! -f "$RUNTIME/postgres/share/extension/vector.control" ]; then
  fetch "https://github.com/pgvector/pgvector/archive/refs/tags/v$VECTOR_VERSION.tar.gz" "$RUNTIME/downloads/pgvector.tar.gz"
  tar -xzf "$RUNTIME/downloads/pgvector.tar.gz" -C "$RUNTIME"
  make -C "$RUNTIME/pgvector-$VECTOR_VERSION" PG_CONFIG="$RUNTIME/postgres/bin/pg_config" -j4
  make -C "$RUNTIME/pgvector-$VECTOR_VERSION" PG_CONFIG="$RUNTIME/postgres/bin/pg_config" install
fi
if [ ! -x "$RUNTIME/redis-$REDIS_VERSION/src/redis-server" ]; then
  fetch "https://github.com/redis/redis/archive/refs/tags/$REDIS_VERSION.tar.gz" "$RUNTIME/downloads/redis.tar.gz"
  tar -xzf "$RUNTIME/downloads/redis.tar.gz" -C "$RUNTIME"
  make -C "$RUNTIME/redis-$REDIS_VERSION" -j4 BUILD_TLS=no
fi
if [ ! -x backend/.venv/bin/python ]; then
  python3.12 -m venv backend/.venv
  backend/.venv/bin/python -m pip install -r backend/requirements.lock
fi
if [ ! -d node_modules ]; then pnpm install --frozen-lockfile; fi
echo '本机依赖已准备好。执行 backend/.venv/bin/python scripts/local.py start 启动。'
