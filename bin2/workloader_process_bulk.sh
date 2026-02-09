#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/workloader_common.sh"

HREF_FILE="${1:?managed wkld href file required (bulk)}"
OUT="${2:?output csv}"

attempt=1
rc=1

while (( attempt <= 3 )); do
  echo "$(date '+%F %T') START [process-export-bulk] attempt=${attempt} CMD=${EXECUTABLE} --config-file ${CFG} ${PCE_NAME:+--pce $PCE_NAME} process-export --href-file ${HREF_FILE} --output-file ${OUT}"
  set +e
  "${EXECUTABLE}" --config-file "${CFG}" ${PCE_NAME:+--pce "$PCE_NAME"} \
    process-export --href-file "${HREF_FILE}" --output-file "${OUT}"
  rc=$?
  set -e

  if [[ $rc -eq 0 && -s "$OUT" ]]; then
    echo "$(date '+%F %T') END [process-export-bulk] status=OK rc=$rc out=${OUT}"
    pause_yellow "process-export-bulk" 60
    exit 0
  fi

  echo "$(date '+%F %T') END [process-export-bulk] status=FAIL rc=$rc"
  if (( attempt < 3 )); then
    pause_orange "process-export-bulk attempt=${attempt}" 60
  fi
  (( attempt++ ))
done

echo "RETRY STOP [process-export-bulk] max attempts reached=3"
exit 1

