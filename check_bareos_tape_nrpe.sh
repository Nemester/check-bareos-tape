#!/usr/bin/env bash
#
# check_bareos_tape_nrpe.sh
#
# Wrapper for check_bareos_tape.py via NRPE
#
# Copyright (C) 2026 Manuel Sonder
#
# SPDX-License-Identifier: MIT
#
# This script executes a remote check for Bareos tape volume lifecycle
# using the check_bareos_tape.py plugin on a remote host via NRPE.
#
# It evaluates physical wear and age of tape media and alerts before
# tapes approach end-of-life, preventing unexpected tape failures
# during backup operations.
#
# Features:
#   - Check a single volume by name, all volumes by media type, or all
#     volumes in a pool
#   - Threshold-based alerting for:
#       * Recycle count  (physical reuse cycles)
#       * Mount count    (total load operations)
#       * Write errors
#       * Tape age       (days since LabelDate)
#   - Optional exclusion of volumes by status
#   - Pass-through of performance data from remote plugin
#
# The wrapper builds the argument string and forwards it via NRPE.
#
# Requirements:
#   - NRPE installed on remote host
#   - NRPE command configured to execute check_bareos_tape.py
#   - check_bareos_tape.py available on remote system
#
# Usage:
#   check_bareos_tape_nrpe.sh -H <nrpe_host> (-v <volume> | -m <mediatype> | --pool <pool>) [options]
#
# Examples:
#   # Check all LTO-9 tapes with default thresholds
#   check_bareos_tape_nrpe.sh -H backuphost -m LTO-9
#
#   # Check all tapes in a pool with custom wear thresholds
#   check_bareos_tape_nrpe.sh -H backuphost --pool Tape-D \
#     --warning-recycle-count 100 \
#     --critical-recycle-count 250
#
#   # Check a single tape volume
#   check_bareos_tape_nrpe.sh -H backuphost -v UV5963L9
#
# Exit Codes:
#   0 - OK
#   1 - WARNING
#   2 - CRITICAL
#   3 - UNKNOWN
#
# Notes:
#   - The actual evaluation logic is implemented in check_bareos_tape.py
#   - This wrapper only handles argument parsing and NRPE communication
#   - Exactly one of -v, -m, or --pool must be provided
#
# Changelog:
#   1.0 - 2026-05-20 - Initial implementation
 
 
set -euo pipefail
 
NRPE_BIN="${NRPE_BIN:-/usr/lib/nagios/plugins/check_nrpe}"
NRPE_HOST="${NRPE_HOST:-}"
NRPE_PORT="${NRPE_PORT:-5666}"
NRPE_TIMEOUT="${NRPE_TIMEOUT:-10}"
NRPE_CMD="${NRPE_CMD:-check_bareos_tapes}"
 
VOLUME="${VOLUME:-}"
MEDIATYPE="${MEDIATYPE:-}"
POOL="${POOL:-}"
 
EXCLUDE_STATUS="${EXCLUDE_STATUS:-}"
 
WARNING_RECYCLE_COUNT="${WARNING_RECYCLE_COUNT:-}"
CRITICAL_RECYCLE_COUNT="${CRITICAL_RECYCLE_COUNT:-}"
 
WARNING_MOUNT_COUNT="${WARNING_MOUNT_COUNT:-}"
CRITICAL_MOUNT_COUNT="${CRITICAL_MOUNT_COUNT:-}"
 
WARNING_ERRORS="${WARNING_ERRORS:-}"
CRITICAL_ERRORS="${CRITICAL_ERRORS:-}"
 
WARNING_AGE_DAYS="${WARNING_AGE_DAYS:-}"
CRITICAL_AGE_DAYS="${CRITICAL_AGE_DAYS:-}"
 
NO_PERFDATA="${NO_PERFDATA:-}"
 
usage() {
  cat <<EOF
Usage:
  $0 -H <nrpe_host> (-v <volume> | -m <mediatype> | --pool <pool>) [options]
 
Required:
  -H, --host                  NRPE host
 
Volume selection (exactly one required):
  -v, --volume                Check a single tape volume by name
  -m, --mediatype             Check all volumes of this media type (e.g. LTO-9)
      --pool                  Check all volumes in this pool name
 
Optional:
  -p, --port                  NRPE port (default: 5666)
  -t, --timeout               NRPE timeout in seconds (default: 10)
      --nrpe-cmd              NRPE command name (default: check_bareos_tape)
 
      --exclude-status        Comma-separated VolStatus values to exclude
                              (default: Recycle,Scratch,Purged)
 
      --warning-recycle-count     WARNING if RecycleCount >= this value
      --critical-recycle-count    CRITICAL if RecycleCount >= this value
 
      --warning-mount-count       WARNING if VolMounts >= this value
      --critical-mount-count      CRITICAL if VolMounts >= this value
 
      --warning-errors            WARNING if VolErrors >= this value
      --critical-errors           CRITICAL if VolErrors >= this value
 
      --warning-age-days          WARNING if tape age (days since LabelDate) >= this value
      --critical-age-days         CRITICAL if tape age (days since LabelDate) >= this value
 
      --no-perfdata           Disable performance data output
 
Examples:
  $0 -H backuphost -m LTO-9
  $0 -H backuphost --pool Tape-D --warning-recycle-count 100 --critical-recycle-count 250
  $0 -H backuphost -v UV5963L9
EOF
}
 
append_arg() {
  local key="$1"
  local value="$2"
 
  if [[ -n "$value" ]]; then
    REMOTE_ARGS+=" $key $value"
  fi
}
 
append_flag() {
  local key="$1"
  local value="$2"
 
  if [[ -n "$value" ]]; then
    REMOTE_ARGS+=" $key"
  fi
}
 
while [[ $# -gt 0 ]]; do
  case "$1" in
    -H|--host)                    NRPE_HOST="$2";              shift 2;;
    -p|--port)                    NRPE_PORT="$2";              shift 2;;
    -t|--timeout)                 NRPE_TIMEOUT="$2";           shift 2;;
    --nrpe-cmd)                   NRPE_CMD="$2";               shift 2;;
 
    -v|--volume)                  VOLUME="$2";                 shift 2;;
    -m|--mediatype)               MEDIATYPE="$2";              shift 2;;
    --pool)                       POOL="$2";                   shift 2;;
 
    --exclude-status)             EXCLUDE_STATUS="$2";         shift 2;;
 
    --warning-recycle-count)      WARNING_RECYCLE_COUNT="$2";  shift 2;;
    --critical-recycle-count)     CRITICAL_RECYCLE_COUNT="$2"; shift 2;;
 
    --warning-mount-count)        WARNING_MOUNT_COUNT="$2";    shift 2;;
    --critical-mount-count)       CRITICAL_MOUNT_COUNT="$2";   shift 2;;
 
    --warning-errors)             WARNING_ERRORS="$2";         shift 2;;
    --critical-errors)            CRITICAL_ERRORS="$2";        shift 2;;
 
    --warning-age-days)           WARNING_AGE_DAYS="$2";       shift 2;;
    --critical-age-days)          CRITICAL_AGE_DAYS="$2";      shift 2;;
 
    --no-perfdata)                NO_PERFDATA="1";              shift;;
 
    -h|--help) usage; exit 0;;
    *) echo "UNKNOWN - unsupported argument: $1"; usage; exit 3;;
  esac
done
 
# Validate required arguments
if [[ -z "${NRPE_HOST}" ]]; then
  echo "UNKNOWN - missing NRPE host"
  exit 3
fi
 
# Validate that exactly one volume selection argument is provided
SELECTION_COUNT=0
[[ -n "${VOLUME}"    ]] && (( SELECTION_COUNT++ )) || true
[[ -n "${MEDIATYPE}" ]] && (( SELECTION_COUNT++ )) || true
[[ -n "${POOL}"      ]] && (( SELECTION_COUNT++ )) || true
 
if [[ "${SELECTION_COUNT}" -eq 0 ]]; then
  echo "UNKNOWN - missing volume selection: provide one of -v, -m, or --pool"
  exit 3
fi
 
if [[ "${SELECTION_COUNT}" -gt 1 ]]; then
  echo "UNKNOWN - conflicting volume selection: provide only one of -v, -m, or --pool"
  exit 3
fi
 
if [[ ! -x "${NRPE_BIN}" ]]; then
  echo "UNKNOWN - check_nrpe not found: ${NRPE_BIN}"
  exit 3
fi
 
# Build remote argument string
if [[ -n "${VOLUME}" ]]; then
  REMOTE_ARGS="-v $VOLUME"
elif [[ -n "${MEDIATYPE}" ]]; then
  REMOTE_ARGS="-m $MEDIATYPE"
else
  REMOTE_ARGS="--pool $POOL"
fi
 
append_arg "--exclude-status"          "$EXCLUDE_STATUS"
 
append_arg "--warning-recycle-count"   "$WARNING_RECYCLE_COUNT"
append_arg "--critical-recycle-count"  "$CRITICAL_RECYCLE_COUNT"
 
append_arg "--warning-mount-count"     "$WARNING_MOUNT_COUNT"
append_arg "--critical-mount-count"    "$CRITICAL_MOUNT_COUNT"
 
append_arg "--warning-errors"          "$WARNING_ERRORS"
append_arg "--critical-errors"         "$CRITICAL_ERRORS"
 
append_arg "--warning-age-days"        "$WARNING_AGE_DAYS"
append_arg "--critical-age-days"       "$CRITICAL_AGE_DAYS"
 
append_flag "--no-perfdata"            "$NO_PERFDATA"
 
set +e
OUTPUT="$("${NRPE_BIN}" \
  -H "${NRPE_HOST}" \
  -p "${NRPE_PORT}" \
  -t "${NRPE_TIMEOUT}" \
  -c "${NRPE_CMD}" \
  -a "${REMOTE_ARGS}" 2>&1)"
RC=$?
set -e
 
echo "${OUTPUT}"
exit "${RC}"
 
