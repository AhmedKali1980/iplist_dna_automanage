#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"
OUT="${1:?output csv}"
retry_backoff "ruleset-export" -- ruleset-export --output-file "$OUT"
