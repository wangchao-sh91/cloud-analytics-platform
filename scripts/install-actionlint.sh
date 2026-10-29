#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
version=1.7.12
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64) platform=linux_amd64 ;;
  Linux/aarch64) platform=linux_arm64 ;;
  *) echo 'Install actionlint 1.7.12 manually on this platform.' >&2; exit 1 ;;
esac
mkdir -p .tools
download=$(mktemp -d)
trap 'rm -rf "$download"' EXIT
archive="actionlint_${version}_${platform}.tar.gz"
base="https://github.com/rhysd/actionlint/releases/download/v${version}"
curl -fsSL --retry 2 "$base/$archive" -o "$download/$archive"
curl -fsSL --retry 2 "$base/actionlint_${version}_checksums.txt" -o "$download/checksums.txt"
awk -v archive="$archive" '$2 == archive {print}' "$download/checksums.txt" > "$download/selected.sha256"
test -s "$download/selected.sha256"
(cd "$download" && sha256sum -c selected.sha256)
tar -xzf "$download/$archive" -C "$download" actionlint
install -m 755 "$download/actionlint" ".tools/actionlint-v$version"
".tools/actionlint-v$version" -version
