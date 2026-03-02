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

VENV_ACTIVATE_REL="${VENV_ACTIVATE_REL:-../venv/bin/activate}"
if [[ "${VENV_ACTIVATE_REL}" = /* ]]; then
  VENV_ACTIVATE_PATH="${VENV_ACTIVATE_REL}"
else
  VENV_ACTIVATE_PATH="$(cd "${ROOT_DIR}" && realpath "${VENV_ACTIVATE_REL}")"
fi

if [[ ! -f "${VENV_ACTIVATE_PATH}" ]]; then
  echo "ERROR: python virtualenv activation script not found at ${VENV_ACTIVATE_PATH}" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "${VENV_ACTIVATE_PATH}"

export_root_conf="${EXPORT_ROOT:-./RUNS}"
if [[ "${export_root_conf}" = /* ]]; then
  export_root_path="${export_root_conf}"
else
  export_root_path="$(cd "${ROOT_DIR}" && realpath "${export_root_conf}")"
fi
mkdir -p "${export_root_path}"

WORKLOADER_LOG="${ROOT_DIR}/workloader.log"
exec >>"${WORKLOADER_LOG}" 2>&1
echo "$(date '+%F %T') INFO cron_job started"

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

run_dir="$(find "${export_root_path}" -mindepth 1 -maxdepth 1 -type d -printf '%P\n' | sort | tail -n 1)"
if [[ -n "${run_dir}" ]]; then
  destination_log="${export_root_path}/${run_dir}/workloader.log"
  mv -f "${WORKLOADER_LOG}" "${destination_log}"
  echo "$(date '+%F %T') INFO moved workloader.log to ${destination_log}"
else
  echo "$(date '+%F %T') WARNING no run directory found under ${export_root_path}; keeping ${WORKLOADER_LOG}"
fi
