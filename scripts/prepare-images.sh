#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cluster=${1:?Usage: bash scripts/prepare-images.sh KIND_CLUSTER KUBE_CONTEXT IMAGE_TAG}
context=${2:?Explicit context is required}
tag=${3:?Image tag is required}
[[ "$tag" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$ ]] || exit 1
config=$(mktemp)
trap 'rm -f "$config"' EXIT
kind get kubeconfig --name "$cluster" > "$config"
expected=$(kubectl --kubeconfig "$config" config view --minify -o jsonpath='{.clusters[0].cluster.server}')
actual=$(kubectl --context "$context" config view --minify -o jsonpath='{.clusters[0].cluster.server}')
[[ "$actual" == "$expected" ]] || { echo 'Context does not match kind cluster.' >&2; exit 1; }
docker build -t "cap-backend:$tag" apps/backend
docker build -t "cap-frontend:$tag" apps/frontend
kind load docker-image --name "$cluster" "cap-backend:$tag" "cap-frontend:$tag"
