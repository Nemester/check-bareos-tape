#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# check_bareos_tape.py - Icinga2 / Nagios plugin for Bareos tape lifecycle monitoring
#
# Repository: https://github.com/Nemester/check-bareos-tape
#
# Copyright (C) 2026 Manuel Sonder
#
# This plugin checks the lifecycle state of Bareos tape volumes via the
# PostgreSQL catalog and returns monitoring status plus performance data
# for recycle count, mount count, write errors, tape age, and volume status.
#
# SPDX-License-Identifier: MIT
#
# Changelog
# 2026-05-21   V1.0    Initial implementation
# 2026-05-22   V1.1    Add --no-perfdata flag
 
import argparse
import sys
from datetime import datetime, timezone
 
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print(
        "[UNKNOWN] Required Python module 'psycopg2' is not installed.\n"
        "Install it with one of:\n"
        "  pip install psycopg2-binary\n"
        "  apt install python3-psycopg2\n"
        "  yum install python3-psycopg2"
    )
    sys.exit(3)
 
 
VERSION = "1.1"
 
OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3
 
# LTO generation native capacities in bytes (used when volcapacitybytes = 0)
LTO_CAPACITIES = {
    "LTO-5":  1_500_000_000_000,
    "LTO-6":  2_500_000_000_000,
    "LTO-7":  6_000_000_000_000,
    "LTO-8": 12_000_000_000_000,
    "LTO-9": 18_000_000_000_000,
}
 
# Vendor-rated load cycle limits per LTO generation
LTO_LOAD_CYCLES = {
    "LTO-5": 500,
    "LTO-6": 500,
    "LTO-7": 500,
    "LTO-8": 500,
    "LTO-9": 500,
}
 
# Default thresholds
DEFAULT_WARNING_RECYCLE_COUNT  = 150
DEFAULT_CRITICAL_RECYCLE_COUNT = 400
 
DEFAULT_WARNING_MOUNT_COUNT    = 500
DEFAULT_CRITICAL_MOUNT_COUNT   = 800
 
DEFAULT_WARNING_ERRORS         = 1
DEFAULT_CRITICAL_ERRORS        = 5
 
DEFAULT_WARNING_AGE_DAYS       = 2555   # ~7 years
DEFAULT_CRITICAL_AGE_DAYS      = 3650   # ~10 years
 
 
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
 
def read_password_from_file(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if "Password" in line:
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2].strip('"')
    raise ValueError(f"No password found in {path}")
 
 
def human_bytes(value: int) -> str:
    if value is None:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"
 
 
def plugin_exit(code: int, message: str, perfdata: str = "") -> None:
    if perfdata:
        print(f"{message} | {perfdata}")
    else:
        print(message)
    sys.exit(code)
 
 
def status_label(code: int) -> str:
    return {
        OK:       "OK",
        WARNING:  "WARNING",
        CRITICAL: "CRITICAL",
        UNKNOWN:  "UNKNOWN",
    }.get(code, "UNKNOWN")
 
 
def connect_db(args):
    try:
        conn = psycopg2.connect(
            host=args.host,
            port=args.port,
            dbname=args.database,
            user=args.user,
            password=args.password,
        )
        return conn
    except Exception as exc:
        plugin_exit(UNKNOWN, f"[UNKNOWN] Database connection failed: {exc}")
 
 
def age_days_from_labeldate(labeldate) -> int | None:
    if labeldate is None:
        return None
    now = datetime.now(timezone.utc)
    if labeldate.tzinfo is None:
        labeldate = labeldate.replace(tzinfo=timezone.utc)
    return int((now - labeldate).total_seconds() / 86400)
 
 
def apply_max_thresholds(value: int, warning_max, critical_max) -> int:
    if critical_max is not None and value >= critical_max:
        return CRITICAL
    if warning_max is not None and value >= warning_max:
        return WARNING
    return OK
 
 
def combine_codes(*codes: int) -> int:
    return max(codes) if codes else OK
 
 
# ---------------------------------------------------------------------------
# Argument parsing & validation
# ---------------------------------------------------------------------------
 
def parse_args():
    parser = argparse.ArgumentParser(
        description="Icinga/Nagios plugin for checking Bareos tape volume lifecycle"
    )
 
    # Connection
    parser.add_argument("-H", "--host",     default="127.0.0.1", help="PostgreSQL host (default: 127.0.0.1)")
    parser.add_argument("-P", "--port",     type=int, default=5432, help="PostgreSQL port (default: 5432)")
    parser.add_argument("-d", "--database", default="bareos",    help="Database name (default: bareos)")
    parser.add_argument("-U", "--user",     required=True,       help="Database user")
 
    pw_group = parser.add_mutually_exclusive_group()
    pw_group.add_argument("-p", "--password", help="Database password")
    pw_group.add_argument(
        "--password-file",
        default="/etc/bareos/bareos-dir.conf",
        help="File containing 'Password = ...' (default: /etc/bareos/bareos-dir.conf)",
    )
 
    # Volume selection
    vol_group = parser.add_mutually_exclusive_group(required=True)
    vol_group.add_argument("-v", "--volume",    help="Tape volume name to check (exact match)")
    vol_group.add_argument("-m", "--mediatype", help="Check all volumes of this media type (e.g. LTO-9)")
    vol_group.add_argument("--pool",            help="Check all volumes in this pool name")
 
    parser.add_argument(
        "--exclude-status",
        default="Recycle,Scratch,Purged",
        help="Comma-separated VolStatus values to exclude (default: Recycle,Scratch,Purged)",
    )
 
    # Recycle count thresholds
    parser.add_argument(
        "--warning-recycle-count",
        type=int,
        default=DEFAULT_WARNING_RECYCLE_COUNT,
        help=f"WARNING if RecycleCount >= this value (default: {DEFAULT_WARNING_RECYCLE_COUNT})",
    )
    parser.add_argument(
        "--critical-recycle-count",
        type=int,
        default=DEFAULT_CRITICAL_RECYCLE_COUNT,
        help=f"CRITICAL if RecycleCount >= this value (default: {DEFAULT_CRITICAL_RECYCLE_COUNT})",
    )
 
    # Mount count thresholds
    parser.add_argument(
        "--warning-mount-count",
        type=int,
        default=DEFAULT_WARNING_MOUNT_COUNT,
        help=f"WARNING if VolMounts >= this value (default: {DEFAULT_WARNING_MOUNT_COUNT})",
    )
    parser.add_argument(
        "--critical-mount-count",
        type=int,
        default=DEFAULT_CRITICAL_MOUNT_COUNT,
        help=f"CRITICAL if VolMounts >= this value (default: {DEFAULT_CRITICAL_MOUNT_COUNT})",
    )
 
    # Error thresholds
    parser.add_argument(
        "--warning-errors",
        type=int,
        default=DEFAULT_WARNING_ERRORS,
        help=f"WARNING if VolErrors >= this value (default: {DEFAULT_WARNING_ERRORS})",
    )
    parser.add_argument(
        "--critical-errors",
        type=int,
        default=DEFAULT_CRITICAL_ERRORS,
        help=f"CRITICAL if VolErrors >= this value (default: {DEFAULT_CRITICAL_ERRORS})",
    )
 
    # Age thresholds (days since LabelDate)
    parser.add_argument(
        "--warning-age-days",
        type=int,
        default=DEFAULT_WARNING_AGE_DAYS,
        help=f"WARNING if tape age (from LabelDate) >= this many days (default: {DEFAULT_WARNING_AGE_DAYS})",
    )
    parser.add_argument(
        "--critical-age-days",
        type=int,
        default=DEFAULT_CRITICAL_AGE_DAYS,
        help=f"CRITICAL if tape age (from LabelDate) >= this many days (default: {DEFAULT_CRITICAL_AGE_DAYS})",
    )
 
    parser.add_argument(
        "--no-perfdata",
        action="store_true",
        default=False,
        help="Disable performance data output (default: perfdata enabled)",
    )
 
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
 
    args = parser.parse_args()
 
    # Validate threshold ordering
    try:
        _validate_thresholds(args)
    except ValueError as exc:
        parser.error(str(exc))
 
    # Parse excluded statuses
    args.exclude_status_set = {
        s.strip() for s in args.exclude_status.split(",") if s.strip()
    }
 
    return args
 
 
def _validate_thresholds(args) -> None:
    pairs = [
        ("--warning-recycle-count",  args.warning_recycle_count,
         "--critical-recycle-count", args.critical_recycle_count),
        ("--warning-mount-count",    args.warning_mount_count,
         "--critical-mount-count",   args.critical_mount_count),
        ("--warning-errors",         args.warning_errors,
         "--critical-errors",        args.critical_errors),
        ("--warning-age-days",       args.warning_age_days,
         "--critical-age-days",      args.critical_age_days),
    ]
    for warn_name, warn_val, crit_name, crit_val in pairs:
        if warn_val is not None and crit_val is not None and warn_val > crit_val:
            raise ValueError(
                f"{warn_name} ({warn_val}) must be <= {crit_name} ({crit_val})"
            )
 
 
# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
 
def build_query(args):
    where = []
    params = []
 
    if args.volume:
        where.append("VolumeName = %s")
        params.append(args.volume)
    elif args.mediatype:
        where.append("MediaType = %s")
        params.append(args.mediatype)
    elif args.pool:
        where.append(
            "PoolId = (SELECT PoolId FROM Pool WHERE Name = %s LIMIT 1)"
        )
        params.append(args.pool)
 
    if args.exclude_status_set:
        placeholders = ",".join(["%s"] * len(args.exclude_status_set))
        where.append(f"VolStatus NOT IN ({placeholders})")
        params.extend(sorted(args.exclude_status_set))
 
    where_sql = " AND ".join(where) if where else "1=1"
 
    sql = f"""
        SELECT
            MediaId,
            VolumeName,
            MediaType,
            VolStatus,
            RecycleCount,
            VolMounts,
            VolErrors,
            VolBytes,
            VolCapacityBytes,
            LabelDate,
            LastWritten,
            Pool.Name AS PoolName
        FROM Media
        LEFT JOIN Pool USING (PoolId)
        WHERE {where_sql}
        ORDER BY VolumeName ASC
    """
    return sql, params
 
 
# ---------------------------------------------------------------------------
# Per-volume evaluation
# ---------------------------------------------------------------------------
 
def evaluate_volume(row, args) -> tuple[int, list[str]]:
    """Return (exit_code, list_of_hit_descriptions) for a single volume."""
    hits = []
 
    recycle_count = int(row["recyclecount"] or 0)
    vol_mounts    = int(row["volmounts"]    or 0)
    vol_errors    = int(row["volerrors"]    or 0)
    age_days      = age_days_from_labeldate(row["labeldate"])
    vol_status    = row["volstatus"] or ""
 
    codes = []
 
    # 1. Recycle count
    rc = apply_max_thresholds(
        recycle_count,
        args.warning_recycle_count,
        args.critical_recycle_count,
    )
    if rc > OK:
        hits.append(
            f"recycle_count={recycle_count}>="
            f"{args.critical_recycle_count if rc == CRITICAL else args.warning_recycle_count}"
            f" ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    # 2. Mount count
    rc = apply_max_thresholds(
        vol_mounts,
        args.warning_mount_count,
        args.critical_mount_count,
    )
    if rc > OK:
        hits.append(
            f"vol_mounts={vol_mounts}>="
            f"{args.critical_mount_count if rc == CRITICAL else args.warning_mount_count}"
            f" ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    # 3. Errors
    rc = apply_max_thresholds(
        vol_errors,
        args.warning_errors,
        args.critical_errors,
    )
    if rc > OK:
        hits.append(
            f"vol_errors={vol_errors}>="
            f"{args.critical_errors if rc == CRITICAL else args.warning_errors}"
            f" ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    # 4. Age
    if age_days is not None:
        rc = apply_max_thresholds(
            age_days,
            args.warning_age_days,
            args.critical_age_days,
        )
        if rc > OK:
            hits.append(
                f"age={age_days}d>="
                f"{args.critical_age_days if rc == CRITICAL else args.warning_age_days}"
                f"d ({status_label(rc).lower()})"
            )
        codes.append(rc)
 
    # 5. VolStatus = Error always → CRITICAL
    if vol_status == "Error":
        codes.append(CRITICAL)
        hits.append(f"vol_status=Error (critical)")
 
    return combine_codes(*codes), hits
 
 
def build_perfdata_for_volume(row, args) -> str:
    recycle_count = int(row["recyclecount"] or 0)
    vol_mounts    = int(row["volmounts"]    or 0)
    vol_errors    = int(row["volerrors"]    or 0)
    vol_bytes     = int(row["volbytes"]     or 0)
    age_days      = age_days_from_labeldate(row["labeldate"])
    vol_name      = row["volumename"].replace(" ", "_")
 
    cap = int(row["volcapacitybytes"] or 0)
    if cap == 0:
        cap = LTO_CAPACITIES.get(row["mediatype"] or "", 0)
 
    parts = [
        f"'{vol_name}_recycle_count'={recycle_count}c;"
        f"{args.warning_recycle_count};{args.critical_recycle_count};;",
 
        f"'{vol_name}_vol_mounts'={vol_mounts}c;"
        f"{args.warning_mount_count};{args.critical_mount_count};;",
 
        f"'{vol_name}_vol_errors'={vol_errors}c;"
        f"{args.warning_errors};{args.critical_errors};;",
 
        f"'{vol_name}_vol_bytes'={vol_bytes}B;;;;{cap if cap else ''}",
 
        f"'{vol_name}_age_days'={age_days if age_days is not None else 0}d;"
        f"{args.warning_age_days};{args.critical_age_days};;",
    ]
    return " ".join(parts)
 
 
# ---------------------------------------------------------------------------
# Main check logic
# ---------------------------------------------------------------------------
 
def check_tapes(args):
    conn = connect_db(args)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            sql, params = build_query(args)
            cur.execute(sql, params)
            rows = cur.fetchall()
 
            if not rows:
                scope = (
                    f"volume '{args.volume}'"      if args.volume    else
                    f"mediatype '{args.mediatype}'" if args.mediatype else
                    f"pool '{args.pool}'"
                )
                plugin_exit(
                    UNKNOWN,
                    f"[UNKNOWN] No tape volumes found for {scope}"
                )
 
            if args.volume:
                # Single-volume mode: detailed output
                _report_single(rows[0], args)
            else:
                # Multi-volume mode: summary + worst offenders
                _report_multi(rows, args)
 
    except Exception as exc:
        plugin_exit(UNKNOWN, f"[UNKNOWN] Query failed: {exc}")
    finally:
        conn.close()
 
 
def _report_single(row, args):
    code, hits = evaluate_volume(row, args)
 
    recycle_count = int(row["recyclecount"] or 0)
    vol_mounts    = int(row["volmounts"]    or 0)
    vol_errors    = int(row["volerrors"]    or 0)
    vol_bytes     = int(row["volbytes"]     or 0)
    age_days      = age_days_from_labeldate(row["labeldate"])
    vol_status    = row["volstatus"] or "n/a"
    mediatype     = row["mediatype"] or "n/a"
    pool          = row["poolname"]  or "n/a"
 
    threshold_text = f", threshold_hits={'; '.join(hits)}" if hits else ""
 
    message = (
        f"[{status_label(code)}] "
        f"Tape '{row['volumename']}' ({mediatype}, pool={pool}): "
        f"status={vol_status}, "
        f"recycle_count={recycle_count}, "
        f"vol_mounts={vol_mounts}, "
        f"vol_errors={vol_errors}, "
        f"age={age_days}d, "
        f"vol_bytes={human_bytes(vol_bytes)}"
        f"{threshold_text}"
    )
 
    perfdata = "" if args.no_perfdata else build_perfdata_for_volume(row, args)
    plugin_exit(code, message, perfdata)
 
 
def _report_multi(rows, args):
    total         = len(rows)
    ok_count      = 0
    warning_count = 0
    critical_count = 0
    worst_code    = OK
    worst_rows: list = []   # volumes that triggered the worst state
    all_perfdata  = []
 
    for row in rows:
        code, hits = evaluate_volume(row, args)
        if not args.no_perfdata:
            all_perfdata.append(build_perfdata_for_volume(row, args))
 
        if code == OK:
            ok_count += 1
        elif code == WARNING:
            warning_count += 1
        else:
            critical_count += 1
 
        if code > worst_code:
            worst_code = code
            worst_rows = [(row, hits)]
        elif code == worst_code and code > OK:
            worst_rows.append((row, hits))
 
    # Build summary of offending tapes
    offender_parts = []
    for row, hits in worst_rows[:5]:   # cap at 5 to keep output readable
        offender_parts.append(
            f"{row['volumename']} ({'; '.join(hits)})"
        )
    offenders_text = "; ".join(offender_parts)
    if len(worst_rows) > 5:
        offenders_text += f" ... and {len(worst_rows) - 5} more"
 
    if worst_code == OK:
        detail = "all volumes within lifecycle thresholds"
    else:
        detail = f"offenders: {offenders_text}"
 
    message = (
        f"[{status_label(worst_code)}] "
        f"Tape lifecycle: checked {total} volume(s), "
        f"OK={ok_count}, WARNING={warning_count}, CRITICAL={critical_count}; "
        f"{detail}"
    )
 
    perfdata = "" if args.no_perfdata else " ".join(all_perfdata)
    plugin_exit(worst_code, message, perfdata)
 
 
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
 
def main():
    args = parse_args()
 
    if not args.password:
        try:
            args.password = read_password_from_file(args.password_file)
        except Exception as exc:
            plugin_exit(UNKNOWN, f"[UNKNOWN] Could not read password: {exc}")
 
    check_tapes(args)
 
 
if __name__ == "__main__":
    main()

