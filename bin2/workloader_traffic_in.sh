
#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"

INCL_FILE="${1:?include labels (semicolon CSV) required}"
START="${2:?start date YYYY-mm-dd}"
END="${3:?end date YYYY-mm-dd}"
OUT="${4:?output csv}"
EXCL_LABELS_FILE="${5:-}"
EXCL_IPLISTS_FILE="${6:-}"

args=( traffic -a "$INCL_FILE" -s "$START" -e "$END" )

# Exclusion files (Qualys)
if [[ -n "$EXCL_LABELS_FILE" && -s "$EXCL_LABELS_FILE" ]]; then
  args+=( --excl-src-file "$EXCL_LABELS_FILE" )
fi
if [[ -n "$EXCL_IPLISTS_FILE" && -s "$EXCL_IPLISTS_FILE" ]]; then
  args+=( --excl-src-file "$EXCL_IPLISTS_FILE" )
fi

args+=( --output-file "$OUT" )

retry_backoff "traffic-in" -- "${args[@]}"

