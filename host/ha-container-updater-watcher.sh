#!/bin/bash
# =============================================================================
# ha-container-updater-watcher.sh
# Host-side daemon loop — watches for the trigger file written by the HA
# Container Updater custom component, then calls ha-container-updater.sh.
#
# Designed to be run as a systemd service (see ha-container-updater-watcher.service).
# Should NOT be called manually in normal operation.
#
# Security model
# ──────────────
#  1. The trigger file must be valid JSON and contain the magic string
#     "ha_container_updater_REQUESTED" to prevent accidental or unauthorised
#     triggers from stray files.
#  2. Only one update can run at a time; a lock file prevents concurrent runs.
#  3. The trigger file is removed immediately after it is validated so a
#     crashed watcher restart doesn't re-trigger.
# =============================================================================

set -euo pipefail

# ── Configuration (override via environment or edit here) ─────────────────────
TRIGGER_FILE="${HA_UPDATER_TRIGGER_FILE:-/tmp/ha-container-updater-trigger}"
UPDATER_SCRIPT="${HA_UPDATER_SCRIPT:-/usr/local/bin/ha-container-updater.sh}"
LOG_FILE="${HA_UPDATER_LOG_FILE:-/home/pi/homeassistant/ha-container-updater.log}"
LOCK_FILE="${HA_UPDATER_LOCK_FILE:-/tmp/ha-container-updater.lock}"
POLL_INTERVAL="${HA_UPDATER_POLL_INTERVAL:-5}"   # seconds between trigger checks

# ── Logging ───────────────────────────────────────────────────────────────────
_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local entry="${timestamp} - ${level^^} - (ha-update-watcher) - ${message}"
    echo "${entry}"
    mkdir -p "$(dirname "${LOG_FILE}")"
    echo "${entry}" >> "${LOG_FILE}"
}

log_info()  { _log "INFO"  "$1"; }
log_warn()  { _log "WARN"  "$1"; }
log_error() { _log "ERROR" "$1"; echo "ERROR: $1" >&2; }

# ── Startup ───────────────────────────────────────────────────────────────────
log_info "━━━ HA Container Updater Watcher starting ━━━"
log_info "Trigger file  : ${TRIGGER_FILE}"
log_info "Updater script: ${UPDATER_SCRIPT}"
log_info "Poll interval : ${POLL_INTERVAL}s"

if [[ ! -x "${UPDATER_SCRIPT}" ]]; then
    log_error "Updater script not found or not executable: ${UPDATER_SCRIPT}"
    exit 1
fi

# ── Cleanup handler ───────────────────────────────────────────────────────────
cleanup() {
    log_info "Watcher shutting down — cleaning up."
    rm -f "${LOCK_FILE}"
}
trap cleanup EXIT INT TERM

# ── Main loop ─────────────────────────────────────────────────────────────────
while true; do
    if [[ -f "${TRIGGER_FILE}" ]]; then
        log_info "Trigger file detected: ${TRIGGER_FILE}"

        # Read the trigger file content once
        file_content="$(cat "${TRIGGER_FILE}" 2>/dev/null || true)"

        # Parse the JSON payload and extract updater arguments.
        # Use ||true pattern so parse_status captures the real exit code
        # without triggering set -e on failure.
        parse_output=""
        parse_status=0
        parse_output=$(python3 -c '
import json, sys
try:
    data = json.loads(sys.stdin.read())
except Exception as exc:
    print(f"PARSE JSON ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
if not isinstance(data, dict) or data.get("magic") != "ha_container_updater_REQUESTED":
    print("PARSE MAGIC ERROR: missing or wrong magic field", file=sys.stderr)
    sys.exit(1)
args = []
if "compose_dir" in data:
    args.extend(["--compose-dir", data["compose_dir"]])
if "compose_file" in data:
    args.extend(["--compose-file", data["compose_file"]])
if "service_name" in data:
    args.extend(["--service", data["service_name"]])
if "prune_images" in data:
    args.append("--prune" if data["prune_images"] else "--no-prune")
print("\n".join(args))
' <<< "${file_content}") || parse_status=$?

        if [[ ${parse_status} -ne 0 ]]; then
            log_warn "Trigger file content invalid (JSON parse failed or magic mismatch). Ignoring."
            rm -f "${TRIGGER_FILE}"
            sleep "${POLL_INTERVAL}"
            continue
        fi

        # Build the args array from the parsed output
        updater_args_array=()
        while IFS= read -r arg; do
            [[ -n "${arg}" ]] && updater_args_array+=("${arg}")
        done <<< "${parse_output}"

        if [[ ${#updater_args_array[@]} -eq 0 ]]; then
            log_warn "Trigger JSON payload contained no recognized args; ignoring."
            rm -f "${TRIGGER_FILE}"
            sleep "${POLL_INTERVAL}"
            continue
        fi
        log_info "Parsed trigger args: ${updater_args_array[*]}"

        # Remove trigger immediately to prevent re-triggering after a restart
        rm -f "${TRIGGER_FILE}"
        log_info "Trigger file removed. Proceeding with update."

        # Enforce single-run lock — validate the PID is still alive so a
        # crashed watcher or SIGKILL'd updater doesn't leave a permanent block.
        if [[ -f "${LOCK_FILE}" ]]; then
            lock_pid="$(cat "${LOCK_FILE}" 2>/dev/null || echo "")"
            if [[ -n "${lock_pid}" ]] && kill -0 "${lock_pid}" 2>/dev/null; then
                log_warn "Update already in progress (PID ${lock_pid} is running). Skipping."
                sleep "${POLL_INTERVAL}"
                continue
            else
                log_warn "Stale lock file found (PID '${lock_pid}' is not running). Removing and proceeding."
                rm -f "${LOCK_FILE}"
            fi
        fi

        # Acquire lock
        echo $$ > "${LOCK_FILE}"

        log_info "Invoking updater: ${UPDATER_SCRIPT} ${updater_args_array[*]}"
        if "${UPDATER_SCRIPT}" "${updater_args_array[@]}"; then
            log_info "Update completed successfully."
        else
            exit_code=$?
            log_error "Updater script exited with code ${exit_code}. See log for details."
        fi

        # Release lock
        rm -f "${LOCK_FILE}"
    fi

    sleep "${POLL_INTERVAL}"
done