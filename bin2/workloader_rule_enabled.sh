#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"
HREFS_FILE="${1:?file with enabled ruleset hrefs required}"
OUT="${2:?output csv}"
retry_backoff "rule-export-enabled-rs" -- rule-export --ruleset-hrefs "$HREFS_FILE" --expand-svcs --output-file "$OUT"
