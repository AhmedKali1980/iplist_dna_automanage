#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"
HREF_FILE="${1:?managed wkld href file required}"
OUT="${2:?output csv}"
retry_backoff "process-export" -- process-export --href-file "$HREF_FILE" --output-file "$OUT"
