#!/usr/bin/env bash
# Only the container created by this invocation is removed on exit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm -f -v "$container_id" >/dev/null
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Credentials exist only for this disposable container; no mounted data or env files.
POSTGRES_PASSWORD="$(uv run --project apps/backend --frozen python -c 'import secrets; print(secrets.token_hex(24))')"
export POSTGRES_PASSWORD
container_id="$(docker run -d --label cap.lab/purpose=isolated-code-tests \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD -e POSTGRES_USER=cap_test -e POSTGRES_DB=cap_test \
  -p 127.0.0.1::5432 postgres:17)"
port="$(docker port "$container_id" 5432/tcp)"
port="${port##*:}"
export TEST_DATABASE_URL="postgresql+psycopg://cap_test:${POSTGRES_PASSWORD}@127.0.0.1:${port}/cap_test"
unset POSTGRES_PASSWORD DATABASE_URL
uv run --project apps/backend --frozen python scripts/check_code.py all
