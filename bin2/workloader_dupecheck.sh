#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"
OUT="${1:?output csv}"
ONE_IF="${2:-}"
if [[ "${ONE_IF,,}" == "true" ]]; then
  retry_backoff "dupecheck" -- dupecheck --one-interface-match --output-file "$OUT"
else
  retry_backoff "dupecheck" -- dupecheck --output-file "$OUT"
fi
