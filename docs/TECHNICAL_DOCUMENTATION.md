# Technical Documentation - iplist_dna_automanage

## 1. Objective
This repository automates lifecycle management of Illumio IPLists that **must start with `DNA_`**. It exports workloads, labels, and traffic, computes FQDN deltas, imports new/updated IPLists, and sends an English report by email.

## 2. Repository structure
- `bin/cron_job.sh`: cron entrypoint.
- `bin/workloader_common.sh`: shared retry/backoff + command assembly.
- `bin/workloader_ipl_export.sh`: exports IPLists.
- `bin/workloader_wkld_m_export.sh`: exports managed workloads.
- `bin/workloader_label_export.sh`: exports labels.
- `bin/workloader_traffic_out.sh`: exports outbound traffic with include/exclude files.
- `bin/workloader_ipl_import.sh`: imports/updates IPLists.
- `bin/workloader_ipl_delete.sh`: deletes temporary IPLists by href list.
- `modules/dna_automanage.py`: orchestration and reporting logic.
- `modules/email_utils.py`: SMTP sender helper.
- `conf/global.conf`: global parameters.
- `RUNS/`: runtime output folders (`YYYYmmdd-HHMMSS`).

## 3. Implemented workflow
1. Export `export_iplists.csv`, `export_wkld.m.csv`, `export_label.csv`.
2. Parse managed workload `app` labels and build `href_labels.wkld.m.csv`.
3. Filter labels where `key=app` and build `href_labels.app.csv`.
4. Create `service.exlude.csv` excluding ICMP/ICMPv6.
5. Export outbound flows into `flow-out-fqdn-<timestamp>.csv`.
6. Purge flow rows where destination FQDN is empty, contains `.compute.`, or matches IP-style hostnames.
7. Build `ipl.ip.with.fqdn.to.exclude.csv` from distinct `Destination IP` values found in the cleaned flow, then import temporary IPList `_tmp_ipl.ip.with.fqdn.to.exclude_<timestamp>-IPL`.
8. Re-export IPLists, extract temporary IPList `href`, append this `href` to `href_labels.app.csv`, run a second outbound traffic export, and clean the second flow file with the same FQDN filters.
9. Merge first-pass and second-pass cleaned flow files into `flow-out-fqdn-<new_timestamp>-fusion.csv`, write `href_ipl.tmp.csv`, then delete the temporary IPList using `workloader_ipl_delete.sh`.
10. Parse existing DNA_* IPLists only (`name starts with DNA_`).
11. Build a new short-FQDN/IP map from the merged filtered flow (short-FQDN = first label before the first `.`).
12. For each FQDN containing a configured availability-zone token (default: `eu-fr-paris`, `eu-fr-north`, `hk-hongkong`, `sg-singapore`), generate sibling FQDNs for the other zones, resolve them through DNS, and merge all discovered FQDNs/IPs into the same target IPList.
13. Create:
   - `new.iplist.new.fqdns.csv` with `name,description,include,fqdns`.
   - `update.iplist.existing.fqdns.csv` with `href,description,include,fqdns`.
14. Import create/update CSVs using `workloader_ipl_import.sh`.
15. Build report sections:
   - Execution status with response code and timestamps.
   - Created and updated DNA IPLists (added/removed IPs).
   - Deletion candidates with `Last seen at` older than 3 weeks.
   - IP addresses present in multiple DNA IPLists.
16. Send report by email using SMTP settings from `global.conf`.

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
- Regional expansion parameters (`AVAILABILITY_ZONES`, `DNS_LOOKUP_TIMEOUT_SEC`).
- Stale threshold days.

## 6. Outputs per run
Under `RUNS/<timestamp>/`:
- Raw exports (`export_*.csv`).
- Derived filters (`href_labels.*.csv`, `service.exlude.csv`).
- Filtered flows (`flow-out-fqdn-*.csv`).
- Import payloads (`new...csv`, `update...csv`).
- `execution.log` and `report.txt`.

## 7. DOCX generation
To avoid PR errors on platforms that reject binary files, the `.docx` is generated locally from the Markdown source:

```bash
python3 docs/build_docx.py
```

This command creates `docs/TECHNICAL_DOCUMENTATION.docx`.
