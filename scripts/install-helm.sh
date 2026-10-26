#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
version=v3.19.0
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64) platform=linux-amd64 ;;
  Linux/aarch64) platform=linux-arm64 ;;
  *) echo 'Install Helm v3.19.0 manually on this platform.' >&2; exit 1 ;;
esac
mkdir -p .tools
download=$(mktemp -d)
trap 'rm -rf "$download"' EXIT
archive="helm-$version-$platform.tar.gz"
curl -fsSL --retry 2 "https://get.helm.sh/$archive" -o "$download/$archive"
curl -fsSL --retry 2 "https://get.helm.sh/$archive.sha256sum" -o "$download/$archive.sha256sum"
(cd "$download" && sha256sum -c "$archive.sha256sum")
tar -xzf "$download/$archive" -C "$download" "$platform/helm"
install -m 755 "$download/$platform/helm" ".tools/helm-$version"
".tools/helm-$version" version --short
echo "Set HELM to the absolute path of .tools/helm-$version before running release.py."
