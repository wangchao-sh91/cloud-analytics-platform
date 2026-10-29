#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

uv run --project apps/backend --frozen ruff check apps/backend scripts
npm --prefix apps/frontend run lint
npm --prefix apps/frontend run typecheck
