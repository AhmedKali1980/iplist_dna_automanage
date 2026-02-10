#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONF_FILE="${1:-${ROOT_DIR}/conf/global.conf}"

if [[ ! -f "${CONF_FILE}" ]]; then
  echo "ERROR: global config not found at ${CONF_FILE}" >&2
  exit 2
fi

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

load_conf() {
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *=* ]] && continue

    key="$(trim "${line%%=*}")"
    value="$(trim "${line#*=}")"

    if [[ "$value" =~ ^".*"$ || "$value" =~ ^'.*'$ ]]; then
      value="${value:1:${#value}-2}"
    fi

    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "WARNING: ignored invalid key '${key}' in ${CONF_FILE}" >&2
      continue
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
  done <"${CONF_FILE}"
}

load_conf

export GLOBAL_CONF_PATH="${CONF_FILE}"
export EXECUTABLE="${EXECUTABLE:?Missing EXECUTABLE in global.conf}"
export CFG="${EXECUTABLE_CONFIG_FILE:?Missing EXECUTABLE_CONFIG_FILE in global.conf}"

export PCE_NAME="${PCE_NAME:-}"
export BASE_SLEEP="${RETRY_BASE_SLEEP:-3}"
export BACKOFF="${RETRY_BACKOFF_FACTOR:-2}"
export MAX_SLEEP="${RETRY_MAX_SLEEP:-60}"
export JITTER="${RETRY_JITTER_PCT:-20}"
export TIMEOUT_SEC="${TIMEOUT_SEC:-2700}"
export MAX_ATTEMPTS="${RETRY_MAX_ATTEMPTS:-5}"

python3 "${ROOT_DIR}/modules/dna_automanage.py" --config "${CONF_FILE}"
