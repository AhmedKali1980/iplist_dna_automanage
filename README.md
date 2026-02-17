# iplist_dna_automanage

Automation project to maintain DNA_* IPLists from outbound FQDN traffic.

## Quick start

1. Configure `conf/global.conf`.
2. Run once manually:
   ```bash
   ./bin/cron_job.sh ./conf/global.conf
   ```
3. Add cron entry:
   ```cron
   15 2 * * * /path/to/iplist_dna_automanage/bin/cron_job.sh /path/to/iplist_dna_automanage/conf/global.conf
   ```

All run artifacts are generated under `RUNS/<YYYYmmdd-HHMMSS>/`.


## Stub mode (sans export PCE)

Pour tester tout le traitement sans lancer d'exports PCE/workloader :

1. Active le mode stub dans `conf/global.conf` :
   ```ini
   USE_STUB_DATA=true
   STUB_DATA_DIR=./stub_data
   ```
2. Ajuste les CSV dans `stub_data/` si besoin (`export_iplists.csv`, `export_label.csv`, `export_labelgroup.csv`, `flow-out-fqdn-wave1.csv`, `flow-out-fqdn-wave2.csv`, optionnellement `flow-out-dst-delete-candidates.csv`).
3. Lance le job normalement :
   ```bash
   ./bin/cron_job.sh ./conf/global.conf
   ```

Le script génère les mêmes artefacts et applique les mêmes règles métier, mais sans appels workloader/PCE.

## Documentation

- Markdown: `docs/TECHNICAL_DOCUMENTATION.md`
- To generate the Word file locally (without storing binaries in git):
  ```bash
  python3 docs/build_docx.py
  ```

