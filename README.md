# check_bareos_tapes.py

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blueviolet?style=for-the-badge" alt="License: MIT">
  <img src="https://img.shields.io/badge/Built%20by-NEMESTER-DARKGREEN?style=for-the-badge" alt="Built by Nemester">
</p>

A lightweight Icinga2 / Nagios plugin for monitoring the **lifecycle state of Bareos tape volumes** via the Bareos PostgreSQL catalog.

This plugin is focused on a simple and practical use case:

- track physical wear and age of tape media
- alert before tapes approach end-of-life
- expose per-volume performance data for trending and graphing
- support both single-volume and fleet-wide checks



---

## Table of Contents

- [Features](#features)
- [Lifecycle Metrics](#lifecycle-metrics)
- [Default Thresholds](#default-thresholds)
- [Requirements](#requirements)
- [Bareos Catalog Permissions](#bareos-catalog-permissions)
- [Installation](#installation)
- [Usage](#usage)
  - [Required arguments](#required-arguments)
  - [Authentication](#authentication)
  - [Connection options](#connection-options)
  - [Volume selection](#volume-selection)
  - [Threshold options](#threshold-options)
  - [Other options](#other-options)
- [Examples](#examples)
- [Example Output](#example-output)
- [Performance Data](#performance-data)
- [Icinga2 Example](#icinga2-example)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Backlog / Ideas](#backlog--ideas)
- [License](#license)

---

## Features

- Check a single tape volume by name, all volumes by media type, or all volumes in a pool
- Four independent lifecycle checks per volume:
  - recycle count (physical reuse cycles)
  - mount count (total load operations)
  - write errors
  - tape age (days since `LabelDate`)
- Unconditional `CRITICAL` for volumes in `VolStatus = Error`
- Configurable exclusion of volumes by status (e.g. `Recycle`, `Scratch`, `Purged`)
- Per-volume performance data for graphing in Grafana or Icinga
- `--no-perfdata` flag for monitoring systems that do not process perfdata

---

## Lifecycle Metrics

| Metric | Catalog Column | Rationale |
|---|---|---|
| Recycle count | `RecycleCount` | Primary wear indicator: how many times the tape has been fully recycled |
| Mount count | `VolMounts` | Total load operations including reads and partial writes |
| Write errors | `VolErrors` | Non-zero values indicate media degradation |
| Tape age | `LabelDate` | Manufacturers recommend retirement after ~10 years regardless of usage |
| Volume status | `VolStatus` | `Error` state means the tape is already unusable |

---

## Default Thresholds

| Metric | Warning | Critical |
|---|---|---|
| `RecycleCount` | >= 150 | >= 400 |
| `VolMounts` | >= 500 | >= 800 |
| `VolErrors` | >= 1 | >= 5 |
| Age (days from `LabelDate`) | >= 2555 (~7 years) | >= 3650 (~10 years) |
| `VolStatus = Error` | — | always CRITICAL |

All thresholds can be overridden via command-line parameters.

---

## Requirements

- Python 3.10 or newer
- PostgreSQL client libraries
- Python package: `psycopg2`

### Install dependency

Using pip:

```bash
pip install psycopg2-binary
```

Using system package (Debian/Ubuntu):

```bash
apt install python3-psycopg2
```

Using system package (RHEL/CentOS):

```bash
yum install python3-psycopg2
```

---

## Bareos Catalog Permissions

The plugin connects directly to the Bareos PostgreSQL catalog and reads the `Media` and `Pool` tables.

```sql
GRANT SELECT ON Media TO monitoring;
GRANT SELECT ON Pool  TO monitoring;
```

---

## Installation

Copy the script to your monitoring plugins directory on the Bareos director host, or on any host that can reach the Bareos PostgreSQL catalog:

```bash
cp check_bareos_tapes.py /usr/local/lib/nagios/plugins/
chmod +x /usr/local/lib/nagios/plugins/check_bareos_tapes.py
```

---

## Usage

```bash
check_bareos_tapes.py -U USER [-p PASSWORD | --password-file FILE] (-v VOLUME | -m MEDIATYPE | --pool POOL) [OPTIONS]
```

### Required arguments

- `-U`, `--user`  
  Database user

Exactly one of the following volume selection options is also required:

- `-v`, `--volume` — check a single volume by name
- `-m`, `--mediatype` — check all volumes of a given media type
- `--pool` — check all volumes in a named pool

### Authentication

- `-p`, `--password`  
  Database password (mutually exclusive with `--password-file`)

- `--password-file`  
  File containing a line like `Password = secret`

Default password file:

```text
/etc/bareos/bareos-dir.conf
```

### Connection options

- `-H`, `--host`  
  PostgreSQL host  
  Default: `127.0.0.1`

- `-P`, `--port`  
  PostgreSQL port  
  Default: `5432`

- `-d`, `--database`  
  Database name  
  Default: `bareos`

### Volume selection

Exactly one of the following must be provided:

- `-v`, `--volume NAME`  
  Check a single tape volume by exact name. Returns detailed single-volume output.

- `-m`, `--mediatype TYPE`  
  Check all volumes of this media type (e.g. `LTO-9`). Returns a fleet summary with offender detail.

- `--pool NAME`  
  Check all volumes in this pool. Returns a fleet summary with offender detail.

- `--exclude-status LIST`  
  Comma-separated `VolStatus` values to skip entirely.  
  Default: `Recycle,Scratch,Purged`

### Threshold options

All thresholds trigger when the measured value rises **at or above** the configured value.

#### Recycle count

- `--warning-recycle-count N`  
  Return `WARNING` if `RecycleCount >= N`  
  Default: `150`

- `--critical-recycle-count N`  
  Return `CRITICAL` if `RecycleCount >= N`  
  Default: `400`

Validation rule:

```text
warning-recycle-count <= critical-recycle-count
```

#### Mount count

- `--warning-mount-count N`  
  Return `WARNING` if `VolMounts >= N`  
  Default: `500`

- `--critical-mount-count N`  
  Return `CRITICAL` if `VolMounts >= N`  
  Default: `800`

Validation rule:

```text
warning-mount-count <= critical-mount-count
```

#### Write errors

- `--warning-errors N`  
  Return `WARNING` if `VolErrors >= N`  
  Default: `1`

- `--critical-errors N`  
  Return `CRITICAL` if `VolErrors >= N`  
  Default: `5`

Validation rule:

```text
warning-errors <= critical-errors
```

#### Tape age

- `--warning-age-days N`  
  Return `WARNING` if tape age (days since `LabelDate`) >= N  
  Default: `2555` (~7 years)

- `--critical-age-days N`  
  Return `CRITICAL` if tape age >= N  
  Default: `3650` (~10 years)

Validation rule:

```text
warning-age-days <= critical-age-days
```

### Other options

- `--no-perfdata`  
  Disable performance data output. Useful when the monitoring system does not support perfdata or when output size is a concern for large tape libraries.  
  Default: perfdata enabled

- `--version`  
  Show plugin version

---

## Examples

### Check all LTO-9 tapes with default thresholds

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password -m LTO-9
```

### Check all tapes in a pool

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc
```

### Check a single volume

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password -v UV5963L9
```

### Tighten recycle thresholds

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password -m LTO-9 \
  --warning-recycle-count 100 \
  --critical-recycle-count 250
```

### Treat any write error as WARNING only

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password -m LTO-9 \
  --warning-errors 1 \
  --critical-errors 10
```

### Include Purged volumes in the check

```bash
check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc \
  --exclude-status Recycle,Scratch
```

---

## Example Output

### Single volume: OK

```text
[OK] Tape 'UV5963L9' (LTO-9, pool=Tape-Inc): status=Full, recycle_count=2, vol_mounts=3, vol_errors=0, age=124d, vol_bytes=17.96 TB
```

### Single volume: WARNING

```text
[WARNING] Tape 'UV0012L9' (LTO-9, pool=Tape-Inc): status=Used, recycle_count=162, vol_mounts=165, vol_errors=0, age=980d, vol_bytes=8.23 TB, threshold_hits=recycle_count=162>=150 (warning)
```

### Single volume: CRITICAL

```text
[CRITICAL] Tape 'UV0007L9' (LTO-9, pool=Tape-Inc): status=Error, recycle_count=430, vol_mounts=441, vol_errors=7, age=1204d, vol_bytes=0.00 B, threshold_hits=recycle_count=430>=400 (critical); vol_errors=7>=5 (critical); vol_status=Error (critical)
```

### Fleet check: OK

```text
[OK] Tape lifecycle: checked 24 volume(s), OK=24, WARNING=0, CRITICAL=0; all volumes within lifecycle thresholds
```

### Fleet check: WARNING

```text
[WARNING] Tape lifecycle: checked 24 volume(s), OK=22, WARNING=1, CRITICAL=1; offenders: UV0012L9 (recycle_count=162>=150 (warning)); UV0007L9 (recycle_count=430>=400 (critical); vol_errors=7>=5 (critical))
```

### UNKNOWN: no volumes found

```text
[UNKNOWN] No tape volumes found for mediatype 'LTO-9'
```

---

## Performance Data

Each volume emits five perfdata metrics, prefixed with the volume name:

| Label | Unit | Thresholds |
|---|---|---|
| `<vol>_recycle_count` | `c` (counter) | warn ; crit |
| `<vol>_vol_mounts` | `c` (counter) | warn ; crit |
| `<vol>_vol_errors` | `c` (counter) | warn ; crit |
| `<vol>_vol_bytes` | `B` (bytes) | none; max = LTO native capacity |
| `<vol>_age_days` | `d` (days) | warn ; crit |

Example perfdata for a single volume:

```text
'UV5963L9_recycle_count'=2c;150;400;; 'UV5963L9_vol_mounts'=3c;500;800;; 'UV5963L9_vol_errors'=0c;1;5;; 'UV5963L9_vol_bytes'=19743134252032B;;;;18000000000000 'UV5963L9_age_days'=124d;2555;3650;;
```

The `vol_bytes` max value is taken from `VolCapacityBytes` if non-zero, otherwise from the built-in LTO capacity table:

| Media type | Native capacity |
|---|---|
| LTO-5 | 1.5 TB |
| LTO-6 | 2.5 TB |
| LTO-7 | 6.0 TB |
| LTO-8 | 12.0 TB |
| LTO-9 | 18.0 TB |

Use `--no-perfdata` to suppress all perfdata output — useful when checking a large library where the output line would become very long.

---

## Icinga2 Example

You can set up the check on any host that can access the PostgreSQL DB on the bareos director. If you don't want to expose the database use the provided wrapper script (`check_bareos_tape_nrpe.sh`) and trigger the check through nrpe (see example below)

### NRPE setup on the Bareos host

Add to `/etc/nagios/nrpe_local.cfg` on the Bareos director:

```ini
command[check_bareos_tapes]=/usr/local/lib/nagios/plugins/check_bareos_tapes.py -U bareos --password-file /etc/bareos/db-password $ARG1$
```


### Wrapper script on the Icinga host

Use the included `check_bareos_tape_nrpe.sh` wrapper on the Icinga master/satellite. Place it in your plugins contrib directory:

```bash
cp check_bareos_tape_nrpe.sh /usr/local/lib/nagios/plugins/
chmod +x /usr/local/lib/nagios/plugins/check_bareos_tape_nrpe.sh
```

### CheckCommand definition

```icinga2
object CheckCommand "check_bareos_tape" {
  import "plugin-check-command"
  command = [ PluginContribDir + "/check_bareos_tape_nrpe.sh" ]
  arguments = {
    "-H" = {
      value       = "$bareos_dir$"
      required    = true
      description = "NRPE host running the Bareos check"
    }
    "-p" = {
      value       = "$bareos_nrpe_port$"
      required    = false
      description = "NRPE port (default: 5666)"
    }
    "-t" = {
      value       = "$bareos_nrpe_timeout$"
      required    = false
      description = "NRPE timeout in seconds (default: 10)"
    }
    "--nrpe-cmd" = {
      value       = "$bareos_tape_nrpe_cmd$"
      required    = false
      description = "NRPE command name (default: check_bareos_tape)"
    }
    "-v" = {
      value       = "$bareos_tape_volume$"
      required    = false
      description = "Check a single tape volume by name"
    }
    "-m" = {
      value       = "$bareos_tape_mediatype$"
      required    = false
      description = "Check all volumes of this media type (e.g. LTO-9)"
    }
    "--pool" = {
      value       = "$bareos_tape_pool$"
      required    = false
      description = "Check all volumes in this pool name"
    }
    "--exclude-status" = {
      value       = "$bareos_tape_exclude_status$"
      required    = false
      description = "Comma-separated VolStatus values to exclude (default: Recycle,Scratch,Purged)"
    }
    "--warning-recycle-count" = {
      value       = "$bareos_tape_warning_recycle_count$"
      required    = false
      description = "WARNING if RecycleCount >= this value (default: 150)"
    }
    "--critical-recycle-count" = {
      value       = "$bareos_tape_critical_recycle_count$"
      required    = false
      description = "CRITICAL if RecycleCount >= this value (default: 400)"
    }
    "--warning-mount-count" = {
      value       = "$bareos_tape_warning_mount_count$"
      required    = false
      description = "WARNING if VolMounts >= this value (default: 500)"
    }
    "--critical-mount-count" = {
      value       = "$bareos_tape_critical_mount_count$"
      required    = false
      description = "CRITICAL if VolMounts >= this value (default: 800)"
    }
    "--warning-errors" = {
      value       = "$bareos_tape_warning_errors$"
      required    = false
      description = "WARNING if VolErrors >= this value (default: 1)"
    }
    "--critical-errors" = {
      value       = "$bareos_tape_critical_errors$"
      required    = false
      description = "CRITICAL if VolErrors >= this value (default: 5)"
    }
    "--warning-age-days" = {
      value       = "$bareos_tape_warning_age_days$"
      required    = false
      description = "WARNING if tape age in days >= this value (default: 2555)"
    }
    "--critical-age-days" = {
      value       = "$bareos_tape_critical_age_days$"
      required    = false
      description = "CRITICAL if tape age in days >= this value (default: 3650)"
    }
    "--no-perfdata" = {
      set_if      = "$bareos_tape_no_perfdata$"
      description = "Disable performance data output"
    }
  }
}
```

### Service apply rule

```icinga2
apply Service "Bareos tape health " for (label => config in host.vars.bareos_tape_checks) {
  import "generic-service"
  check_interval     = 24h
  max_check_attempts = 3
  retry_interval     = 24h
  vars.notification_interval = 24h
  check_command = "check_bareos_tape"

  vars.bareos_dir          = host.vars.bareos_dir ? host.vars.bareos_dir : "bareos-dir.example.com"
  vars.bareos_nrpe_port    = host.vars.bareos_nrpe_port ? host.vars.bareos_nrpe_port : 5666
  vars.bareos_nrpe_timeout = host.vars.bareos_nrpe_timeout ? host.vars.bareos_nrpe_timeout : 10

  // Volume selection — set exactly one per entry in bareos_tape_checks
  vars.bareos_tape_volume    = config.tape_volume    ? config.tape_volume    : null
  vars.bareos_tape_mediatype = config.tape_mediatype ? config.tape_mediatype : null
  vars.bareos_tape_pool      = config.tape_pool      ? config.tape_pool      : null

  vars.bareos_tape_exclude_status = config.tape_exclude_status ? config.tape_exclude_status : null

  // Recycle count — warn at 150, critical at 400
  vars.bareos_tape_warning_recycle_count  = config.tape_warning_recycle_count  ? config.tape_warning_recycle_count  : 150
  vars.bareos_tape_critical_recycle_count = config.tape_critical_recycle_count ? config.tape_critical_recycle_count : 400

  // Mount count — warn at 500, critical at 800
  vars.bareos_tape_warning_mount_count    = config.tape_warning_mount_count    ? config.tape_warning_mount_count    : 500
  vars.bareos_tape_critical_mount_count   = config.tape_critical_mount_count   ? config.tape_critical_mount_count   : 800

  // Write errors — warn at 1, critical at 5
  vars.bareos_tape_warning_errors         = config.tape_warning_errors         ? config.tape_warning_errors         : 1
  vars.bareos_tape_critical_errors        = config.tape_critical_errors        ? config.tape_critical_errors        : 5

  // Tape age — warn at ~7 years (2555d), critical at ~10 years (3650d)
  vars.bareos_tape_warning_age_days       = config.tape_warning_age_days       ? config.tape_warning_age_days       : 2555
  vars.bareos_tape_critical_age_days      = config.tape_critical_age_days      ? config.tape_critical_age_days      : 3650

  vars.bareos_tape_no_perfdata            = config.tape_no_perfdata            ? config.tape_no_perfdata            : false

  vars.notification.mail.users  = [ "Backup" ]

  assign where host.vars.bareos_tape_checks
}
```

### Example host vars

```icinga2
vars.bareos_dir = "bareos-director.example.com"

// Check all LTO-9 tapes with default thresholds
vars.bareos_tape_checks["LTO-9 fleet"] = {
  tape_mediatype = "LTO-9"
}

// Check all tapes in a pool with custom recycle threshold
vars.bareos_tape_checks["Tape-Inc pool"] = {
  tape_pool                    = "Tape-Inc"
  tape_warning_recycle_count   = 100
  tape_critical_recycle_count  = 250
}

// Check a single volume
vars.bareos_tape_checks["UV5963L9"] = {
  tape_volume = "UV5963L9"
}
```

The dict key (e.g. `"LTO-9 fleet"`) becomes part of the Icinga service name: `"Bareos tape health LTO-9 fleet"`. Use descriptive labels to distinguish checks in the Icinga web interface.

---

## Security Notes

- The plugin uses parameterized SQL queries to avoid SQL injection.
- Avoid passing passwords on the command line if possible, because they may appear in process listings.
- Prefer `--password-file` or a protected wrapper script.
- Restrict file permissions on configuration files containing credentials.

Recommended permissions:

```bash
chmod 600 /etc/bareos/db-password
```

---

## Troubleshooting

### `UNKNOWN - Required Python module 'psycopg2' is not installed`

Install the module:

```bash
pip install psycopg2-binary
# or
apt install python3-psycopg2
```

### `UNKNOWN - Database connection failed`

Check:

- PostgreSQL is reachable from the monitoring host
- host, port, database, user, and password are correct
- firewall rules allow the connection
- the database user has `SELECT` on `Media` and `Pool`

### `UNKNOWN - No tape volumes found`

Check:

- the volume name, media type, or pool name is spelled correctly
- the volume is not excluded by `--exclude-status`
- the volume exists in the Bareos catalog:

```sql
SELECT VolumeName, VolStatus, MediaType FROM Media WHERE VolumeName = 'UV5963L9';
```

### Plugin returns `CRITICAL` for a tape that seems fine

A `VolStatus = Error` always returns `CRITICAL` regardless of other thresholds. Check the current status and metrics directly:

```sql
SELECT VolumeName, VolStatus, RecycleCount, VolMounts, VolErrors, LabelDate
FROM Media
WHERE VolumeName = 'UV5963L9';
```

Adjust thresholds if the defaults are too tight for your environment.

### `NRPE: Unable to read output`

Typical causes:

- the NRPE command definition for `check_bareos_tapes` is missing in `nrpe_local.cfg`
- `dont_blame_nrpe=1` is not set in `nrpe.cfg` (needed for passing arguments)
- the NRPE user cannot read the password file
- the NRPE timeout is too low for a large fleet check

---

## Backlog / Ideas

Possible future improvements:

- human-readable age arguments like `7y` or `2555d`
- alert on tapes not written to in unexpectedly long time despite `Append` status
- JSON output mode for external integrations
- summary-only mode that omits per-volume perfdata for very large libraries

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## ⭐ Support the Project

If you find this project useful, please consider giving it a star on GitHub.
It helps others discover the project and motivates me to keep improving it. Thank you for your support!
