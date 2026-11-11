#!/usr/bin/env bash
# Install SQLcl from Oracle's public download site and export SQLCL_BIN.
# Usage: install-sqlcl.sh <version>   (a pinned version below, or "latest")
# Pinned versions are checked against their recorded SHA-256; "latest" is not.
# Installs under $RUNNER_TEMP (falls back to $HOME) and appends
# SQLCL_BIN=<path to sql> to $GITHUB_ENV when set.
set -euo pipefail

BASE_URL="https://download.oracle.com/otn_software/java/sqldeveloper"

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <version>   (25.2 or latest)" >&2
  exit 2
fi
version="$1"

case "$version" in
  latest)
    zip_name="sqlcl-latest.zip"
    sha256=""
    ;;
  25.2)
    zip_name="sqlcl-25.2.2.199.0918.zip"
    sha256="62c20426441779520006c0973417d3e9665bad7babd61a046458fdec9bc61d5f"
    ;;
  *)
    echo "error: no SHA-256 recorded for SQLcl $version; add it to $0" >&2
    exit 2
    ;;
esac

dest="${RUNNER_TEMP:-$HOME}/sqlcl-$version"
rm -rf "$dest"
mkdir -p "$dest"
zip_path="$dest/$zip_name"

echo "Downloading $BASE_URL/$zip_name"
curl -fsSL --retry 3 -o "$zip_path" "$BASE_URL/$zip_name"

if [ -n "$sha256" ]; then
  actual=$(shasum -a 256 "$zip_path" | cut -d' ' -f1)
  if [ "$actual" != "$sha256" ]; then
    echo "error: SHA-256 mismatch for $zip_name: expected $sha256, got $actual" >&2
    exit 1
  fi
fi

unzip -q "$zip_path" -d "$dest"
rm -f "$zip_path"

sql_bin="$dest/sqlcl/bin/sql"
if [ ! -x "$sql_bin" ]; then
  echo "error: $sql_bin not found or not executable after unpacking" >&2
  exit 1
fi

echo "SQLCL_BIN=$sql_bin"
if [ -n "${GITHUB_ENV:-}" ]; then
  echo "SQLCL_BIN=$sql_bin" >> "$GITHUB_ENV"
fi
