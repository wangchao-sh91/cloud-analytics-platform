#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export HELM="${HELM:-$ROOT/.tools/helm-v3.19.0}"
export KUBE_VERSION=1.35.8
export KUBECONFIG=/dev/null
if [[ ! -x "$HELM" ]]; then
  echo 'Run bash scripts/install-helm.sh or set HELM to an absolute Helm v3.19.0 executable.' >&2
  exit 1
fi
if [[ "$("$HELM" version --template '{{.Version}}')" != v3.19.0 ]]; then
  echo 'Helm validation requires v3.19.0.' >&2
  exit 1
fi

for values in default values-kind.yaml values-legacy.yaml; do
  flags=()
  if [[ "$values" != default ]]; then
    flags=(-f "charts/cap/$values")
  fi
  echo "Validating $values (Kubernetes $KUBE_VERSION)"
  "$HELM" lint charts/cap --kube-version "$KUBE_VERSION" "${flags[@]}"
  # Rendering can generate credentials. Validate without publishing the YAML.
  "$HELM" template review charts/cap --kube-version "$KUBE_VERSION" "${flags[@]}" >/dev/null
done
uv run --project apps/backend --frozen python -m pytest -q scripts/tests/test_chart.py
