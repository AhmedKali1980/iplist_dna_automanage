# Technical Documentation - iplist_dna_automanage

## 1. Objective
This repository automates lifecycle management of Illumio IPLists that **must start with `DNA_`**. It exports labels/label-groups and traffic, computes FQDN deltas, imports new/updated IPLists, and sends an English report by email.

## 2. Repository structure
- `bin/cron_job.sh`: cron entrypoint.
- `bin/workloader_common.sh`: shared retry/backoff + command assembly.
- `bin/workloader_ipl_export.sh`: exports IPLists.
- `bin/workloader_label_export.sh`: exports labels.
- `bin/workloader_labelgroup.sh`: exports label groups.
- `bin/workloader_traffic_out.sh`: exports outbound traffic with source/destination include/exclude files.
- `bin/workloader_ipl_import.sh`: imports/updates IPLists.
- `bin/workloader_ipl_delete.sh`: deletes temporary IPLists by href list.
- `modules/dna_automanage.py`: orchestration and reporting logic.
- `modules/email_utils.py`: SMTP sender helper.
- `conf/global.conf`: global parameters.
- `RUNS/`: runtime output folders (`YYYYmmdd-HHMMSS`).

## 3. Implemented workflow
1. Export `export_iplists.csv`, `export_label.csv`, and `export_labelgroup.csv`.
2. Build `href_labels.all.csv` from all exported labels.
3. Resolve label-group names from `global.conf` into href files for source filters:
   - `href_labelgroups.include.src.wave1.csv`
   - `href_labelgroups.exclude.src.wave1.csv`
   - `href_labelgroups.include.src.wave2.csv`
   - `href_labelgroups.exclude.src.wave2.csv`
4. Create `service.exlude.csv` excluding ICMP/ICMPv6.
5. Export outbound flows in two passes:
   - `flow-out-fqdn-wave1-<timestamp>.csv`
   - `flow-out-fqdn-wave2-<timestamp>.csv`
6. In each wave file, remove rows with empty `Destination FQDN`, then merge the two waves into `flow-out-fqdn-<timestamp>.csv`.
7. Purge merged flow rows containing `.compute.` or matching IP-style hostnames.
8. Parse existing DNA_* IPLists only (`name starts with DNA_`).
9. Build a grouping-key/IP map from the filtered flow. Grouping key uses explicit patterns for some domains (for example `sgmonitoring.dev`, `sgmonitoring.prd`, `kafka.dev`, `kafka.prd`, `api.<second-label>`) and falls back to short-FQDN.
10. For each FQDN containing a configured availability-zone token (default: `eu-fr-paris`, `eu-fr-north`, `hk-hongkong`, `sg-singapore`), generate sibling FQDNs for the other zones, resolve them through DNS, and merge all discovered FQDNs/IPs into the same target IPList.
11. Create:
   - `new.iplist.new.fqdns.csv` with `name,description,include,fqdns`.
   - `update.iplist.existing.fqdns.csv` with `href,description,include,fqdns`.
12. Import create/update CSVs using `workloader_ipl_import.sh`.
13. Build report sections:
   - Execution status with response code and timestamps.
   - Created and updated DNA IPLists (added/removed IPs).
   - Deletion candidates with `Last seen at` older than 3 weeks.
   - IP addresses present in multiple DNA IPLists.
14. Send report by email using SMTP settings from `global.conf`.

## 4. Safety controls
- Strict scope: only `DNA_` prefixed IPLists are read/updated.
- Similar FQDNs sharing the same short-FQDN are grouped into one IPList (example: `ocs-compile.eur-fr-paris...` and `ocs-compile.eur-as-hk...` -> `DNA_ocs-compile-IPL`).
- Label exclusions by prefix are configurable (`EXCLUDED_LABEL_PREFIXES`).
- Flow query window is configurable (`NUMBER_OF_DAYS_AGO`).

## 5. Parameters to customize
Edit `conf/global.conf`:
- Workloader binary/config paths.
- SMTP and recipients (`MAIL_TO`).
- Retry policy.
- Prefix filters.
- Wave label-group filters (`LABELGROUP_TO_INCLUDE_SRC_WAVE1`, `LABELGROUP_TO_EXCLUDE_SRC_WAVE1`, `LABELGROUP_TO_INCLUDE_SRC_WAVE2`, `LABELGROUP_TO_EXCLUDE_SRC_WAVE2`).
- Regional expansion parameters (`AVAILABILITY_ZONES`, `DNS_LOOKUP_TIMEOUT_SEC`).
- Stale threshold days.

## 6. Outputs per run
Under `RUNS/<timestamp>/`:
- Raw exports (`export_*.csv`).
- Derived filters (`href_labels.all.csv`, `href_labelgroups.*.csv`, `service.exlude.csv`).
- Wave and merged flows (`flow-out-fqdn-wave*.csv`, `flow-out-fqdn-*.csv`).
- Import payloads (`new...csv`, `update...csv`).
- `execution.log` and `report.txt`.

## 7. DOCX generation
To avoid PR errors on platforms that reject binary files, the `.docx` is generated locally from the Markdown source:

```bash
python3 docs/build_docx.py
```

This command creates `docs/TECHNICAL_DOCUMENTATION.docx`.
