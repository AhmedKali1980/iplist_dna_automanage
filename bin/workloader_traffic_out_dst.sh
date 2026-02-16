#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"

INCLUDE_DST_FILE="${1:?include dst file required}"
START_DATE="${2:?start date YYYY-mm-dd required}"
END_DATE="${3:?end date YYYY-mm-dd required}"
OUT_CSV="${4:?output csv required}"

retry_backoff "traffic-out-dst" -- traffic \
  --incl-dst-file "${INCLUDE_DST_FILE}" \
  --start "${START_DATE}" \
  --end "${END_DATE}" \
  --max-results 200000 \
  --output-file "${OUT_CSV}"
