# Technical Documentation - iplist_dna_automanage

## 1. Objective
This repository automates lifecycle management of Illumio IPLists that **must start with `DNA_`**. It exports labels and traffic, computes FQDN deltas, imports new/updated IPLists, and sends an English report by email.

## 2. Repository structure
- `bin/cron_job.sh`: cron entrypoint.
- `bin/workloader_common.sh`: shared retry/backoff + command assembly.
- `bin/workloader_ipl_export.sh`: exports IPLists.
- `bin/workloader_label_export.sh`: exports labels.
- `bin/workloader_traffic_out.sh`: exports outbound traffic with source/destination include/exclude files.
- `bin/workloader_traffic_out_dst.sh`: exports outbound traffic filtered by destination IPList href file.
- `bin/workloader_ipl_import.sh`: imports/updates IPLists.
- `bin/workloader_ipl_delete.sh`: deletes temporary IPLists by href list.
- `modules/dna_automanage.py`: orchestration and reporting logic.
- `modules/email_utils.py`: SMTP sender helper.
- `conf/global.conf`: global parameters.
- `RUNS/`: runtime output folders (`YYYYmmdd-HHMMSS`).

## 3. Implemented workflow
1. Export `export_iplists.csv` and `export_label.csv`.
2. Build label-filter href files for each wave from `global.conf` using label `key` (type) + value rules (`all`, exact values, prefixes, and negation with `!`). A selector list containing only negative terms (for example `!PRD`) means "all matching labels except these negatives".
3. Create `service.exlude.csv` excluding ICMP/ICMPv6.
4. Export outbound flows in two passes:
   - `flow-out-fqdn-wave1-<timestamp>.csv`
   - `flow-out-fqdn-wave2-<timestamp>.csv`
5. Merge wave files into `flow-out-fqdn-<timestamp>.csv`, then remove rows with empty `Destination FQDN`.
6. Purge remaining flow rows containing `.compute.` or matching IP-style hostnames.
7. Parse existing DNA_* IPLists only (`name starts with DNA_`).
8. Build a grouping-key/IP map from the filtered flow. Grouping key uses explicit patterns for some domains (for example `sgmonitoring.dev`, `sgmonitoring.prd`, `kafka.dev`, `kafka.prd`, `api.<second-label>`) and falls back to short-FQDN.
9. For each FQDN containing a configured availability-zone token (default: `eu-fr-paris`, `eu-fr-north`, `hk-hongkong`, `sg-singapore`), generate sibling FQDNs for the other zones, resolve them through DNS, and merge all discovered FQDNs/IPs into the same target IPList.
10. Enforce global IP uniqueness across DNA IPLists: each IP is assigned to one owner IPList only. Owner selection is deterministic with this priority: existing historical owner (if any), then environment priority (`prd/prod`, `preprod/ppd`, `uat`, `dev`), then higher FQDN count, then alphabetical order.
11. Create:
   - `new.iplist.new.fqdns.csv` with `name,description,include,fqdns`.
   - `update.iplist.existing.fqdns.csv` with `href,description,include,fqdns`.
12. For delete candidates (`existing IPs - desired IPs`), create a temporary IPList named `_tmp_ip.to.delete_<timestamp>-IPL` and export outbound flows on a configurable lookback (default 60 days) using `--incl-dst-file` built from that temporary IPList href.
13. When updating an existing DNA_* IPList, FQDNs are append-only: existing FQDNs are preserved and only newly discovered FQDNs are added (no automatic FQDN removal).
14. When updating each DNA_* IPList, keep a candidate IP if either:
   - it still resolves from one of the target FQDNs, or
   - it is still present in the 60-day destination flow export.
   Remove only IPs that satisfy neither condition.
15. Import create/update CSVs using `workloader_ipl_import.sh`.
16. Build report sections:
   - Execution status with response code and timestamps.
   - Created and updated DNA IPLists (added/removed IPs).
   - Deletion candidates with `Last seen at` older than 3 weeks.
   - IP(s) reassigned to enforce global uniqueness.
17. Send report by email using SMTP settings from `global.conf`.

## 4. Safety controls
- Strict scope: only `DNA_` prefixed IPLists are read/updated.
- Similar FQDNs sharing the same short-FQDN are grouped into one IPList (example: `ocs-compile.eur-fr-paris...` and `ocs-compile.eur-as-hk...` -> `DNA_ocs-compile-IPL`).
- Global uniqueness enforcement ensures one IP appears in only one `DNA_*` IPList at the end of each run.
- Wave label selectors are configurable from `global.conf` (types, prefix/value lists, negation `!`, and `all`).
- Flow query window is configurable (`NUMBER_OF_DAYS_AGO`).

## 5. Parameters to customize
Edit `conf/global.conf`:
- Workloader binary/config paths.
- SMTP and recipients (`MAIL_TO`).
- Retry policy.
- Prefix filters.
- Wave label filters (`LABELS_TYPE_TO_*`, `LABELS_PREFIX_TO_INCLUDE_SRC_*`, `LABELS_TO_EXCLUDE_SRC_*`, `LABELS_TO_EXCLUDE_*`).
- Regional expansion parameters (`AVAILABILITY_ZONES`, `DNS_LOOKUP_TIMEOUT_SEC`).
- Stale threshold days.
- Temporary delete-candidate control (`FLOW_DELETE_VERIFICATION_DAYS`).

## 6. Outputs per run
Under `RUNS/<timestamp>/`:
- Raw exports (`export_*.csv`).
- Derived filters (`href_labels.include.src.wave*.csv`, `href_labels.exclude.src.wave*.csv`, `href_labels.exclude.dst.wave*.csv`, `service.exlude.csv`).
- Wave and merged flows (`flow-out-fqdn-wave*.csv`, `flow-out-fqdn-*.csv`).
- Import payloads (`new...csv`, `update...csv`).
- `execution.log` and `report.txt`.

## 7. DOCX generation
To avoid PR errors on platforms that reject binary files, the `.docx` is generated locally from the Markdown source:

```bash
python3 docs/build_docx.py
```

This command creates `docs/TECHNICAL_DOCUMENTATION.docx`.
