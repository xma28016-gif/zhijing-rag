#!/usr/bin/env sh
set -eu

base_url=${1:-http://localhost:8080}
base_url=${base_url%/}

curl --fail --silent --show-error "$base_url/api/v1/health/live" >/dev/null
curl --fail --silent --show-error "$base_url/api/v1/health/ready" >/dev/null
echo "API live and ready: $base_url"
