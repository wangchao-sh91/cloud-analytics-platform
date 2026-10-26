#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Explicit context, namespace and release are required by the Helm release tool.
exec python3 scripts/release.py deploy "$@"
