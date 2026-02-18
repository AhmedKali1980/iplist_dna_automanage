#!/usr/bin/env python3
"""DNA IPList auto-management orchestrator.

This script exports data from PCE with workloader, discovers required DNS IPLists,
creates/updates only DNA_* IPLists, and sends an execution report by email.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import logging
import re
import socket
import subprocess
import xml.sax.saxutils as saxutils
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from email_utils import parse_recipients, send_carto_notification


IP_STYLE_FQDN_PATTERN = re.compile(
    r"^(?:ip-)?(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:-(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(?:\..+)?$",
    re.IGNORECASE,
)


@dataclass
class StepResult:
    name: str
    started_at: dt.datetime
    ended_at: dt.datetime
    rc: int
    details: str = ""


def read_conf(path: Path) -> Dict[str, str]:
    conf: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        conf[k.strip()] = v.strip()
    return conf


def parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def stub_step(name: str, details: str = "") -> StepResult:
    now = dt.datetime.now()
    return StepResult(name=name, started_at=now, ended_at=now, rc=0, details=details)


def copy_stub_csv(stub_root: Path, output_path: Path, filename: str) -> None:
    src = stub_root / filename
    if not src.exists():
        raise FileNotFoundError(f"Missing stub file: {src}")
    output_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def run_step(name: str, cmd: List[str], cwd: Path, logger: logging.Logger) -> StepResult:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        ended = dt.datetime.now()
        details = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        logger.info("%s rc=%s", name, proc.returncode)
        if proc.returncode != 0:
            logger.error("%s failed: %s", name, details)
        return StepResult(name=name, started_at=started, ended_at=ended, rc=proc.returncode, details=details.strip())
    except FileNotFoundError as exc:
        ended = dt.datetime.now()
        details = f"Command not found for step {name}: {exc}"
        logger.error(details)
        return StepResult(name=name, started_at=started, ended_at=ended, rc=127, details=details)


def csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fieldnames)
        wr.writeheader()
        wr.writerows(rows)


def choose(row: Dict[str, str], *keys: str, default: str = "") -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k].strip()
    return default


def value_at(values: List[object], index: int) -> str:
    if index >= len(values):
        return ""
    value = values[index]
    if value is None:
        return ""
    return str(value).strip()


def sanitize_name(fqdn: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9-]", ".", fqdn)
    return f"DNA_{safe}-IPL"


def short_fqdn(fqdn: str) -> str:
    host = (fqdn or "").strip().split(".", 1)[0].strip().lower()
    return host


def group_key_for_fqdn(fqdn: str) -> str:
    fqdn_l = (fqdn or "").strip().lower().strip(".")
    if not fqdn_l:
        return ""

    m = re.match(r"^[^.]+\.ece\.sgmonitoring\.(dev|prd)\..+$", fqdn_l)
    if m:
        return f"sgmonitoring.{m.group(1)}"

    m = re.match(r"^kfk(?:dev|prd)-\d+-fed\.fed\.kafka\.(dev|prd)\..+$", fqdn_l)
    if m:
        return f"kafka.{m.group(1)}"

    labels = fqdn_l.split(".")
    if len(labels) >= 2 and labels[0] == "api":
        return f"{labels[0]}.{labels[1]}"

    return short_fqdn(fqdn_l)


def parse_last_seen(desc: str) -> dt.date | None:
    m = re.search(r"Last seen at\s*:\s*(\d{4}-\d{2}-\d{2})", desc or "")
    if not m:
        return None
    return dt.date.fromisoformat(m.group(1))


def parse_list(conf: Dict[str, str], key: str, default: str = "") -> List[str]:
    raw = conf.get(key, default)
    return [v.strip() for v in raw.split(";") if v.strip()]


def parse_tokens(raw: str) -> List[str]:
    return [v.strip() for v in re.split(r"[;,]", raw or "") if v.strip()]


def parse_types(conf: Dict[str, str], key: str) -> Set[str]:
    return {v.lower() for v in parse_tokens(conf.get(key, ""))}


def build_label_href_filter(
    labels_rows: List[Dict[str, str]],
    types: Set[str],
    selectors_raw: str,
    selector_mode: str,
) -> List[str]:
    selectors = parse_tokens(selectors_raw)
    include_all = any(t.lower() == "all" for t in selectors)

    positive = [t for t in selectors if not t.startswith("!") and t.lower() != "all"]
    negative = [t[1:] for t in selectors if t.startswith("!") and len(t) > 1]

    def matches(value: str, token: str) -> bool:
        if selector_mode == "prefix":
            return value.startswith(token)
        return value == token

    hrefs: Set[str] = set()
    for row in labels_rows:
        label_type = choose(row, "key", "Key").lower()
        if types and label_type not in types:
            continue

        value = choose(row, "value", "Value")
        href = choose(row, "href", "Href")
        if not value or not href:
            continue

        if include_all or positive:
            selected = include_all or any(matches(value, token) for token in positive)
        else:
            selected = bool(negative)
        if not selected:
            continue

        if any(matches(value, token) for token in negative):
            continue

        hrefs.add(href)

    return sorted(hrefs)


def write_href_file(path: Path, hrefs: List[str]) -> None:
    path.write_text("\n".join(hrefs) + ("\n" if hrefs else ""), encoding="utf-8")


def drop_rows_without_destination_fqdn(flow_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    kept: List[Dict[str, str]] = []
    for row in flow_rows:
        vals = list(row.values())
        fqdn = choose(row, "Destination FQDN", "destination_fqdn", default=value_at(vals, 25))
        if fqdn:
            kept.append(row)
    return kept


def expand_fqdn_by_az(fqdn: str, az_tokens: List[str]) -> Set[str]:
    fqdn_l = (fqdn or "").strip().lower()
    if not fqdn_l:
        return set()

    for token in az_tokens:
        token_l = token.lower()
        if token_l in fqdn_l:
            return {fqdn_l.replace(token_l, az.lower()) for az in az_tokens}

    return {fqdn_l}


def resolve_fqdn_ips(fqdn: str, logger: logging.Logger) -> Set[str]:
    try:
        infos = socket.getaddrinfo(fqdn, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror:
        logger.debug("DNS resolution failed for %s", fqdn)
        return set()
    except OSError as exc:
        logger.warning("DNS resolution error for %s: %s", fqdn, exc)
        return set()

    resolved = set()
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            resolved.add(sockaddr[0])
    return resolved


def is_ip_style_fqdn(value: str) -> bool:
    return bool(IP_STYLE_FQDN_PATTERN.match((value or "").strip()))


def filter_flow_rows(flow_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered_flow: List[Dict[str, str]] = []
    for row in flow_rows:
        vals = list(row.values())
        fqdn = choose(row, "Destination FQDN", "destination_fqdn", default=value_at(vals, 25))
        if not fqdn or ".compute." in fqdn or is_ip_style_fqdn(fqdn):
            continue
        filtered_flow.append(row)
    return filtered_flow


def parse_semicolon_set(raw: str) -> Set[str]:
    return {v.strip() for v in (raw or "").split(";") if v.strip()}


def regroup_by_exact_ips_with_bridge_fqdn(
    desired_by_group_key: Dict[str, Dict[str, Set[str]]],
) -> tuple[Dict[str, Dict[str, Set[str]]], List[Dict[str, str]]]:
    """Regroup candidates by exact IP set and choose a bridge FQDN for naming.

    - Every group with the same exact sorted IP signature is merged together.
    - The bridge FQDN is the alphabetically first FQDN among merged members.
    - Final IPList name is built from the bridge short FQDN (`DNA_<short>-IPL`).
    - Empty-IP signatures are ignored to prevent empty IPList creation.
    """

    signature_to_payload: Dict[tuple[str, ...], Dict[str, Set[str]]] = {}
    signature_to_sources: Dict[tuple[str, ...], Set[str]] = defaultdict(set)

    for source_key, payload in desired_by_group_key.items():
        ips = set(payload.get("ips", set()))
        if not ips:
            continue

        signature = tuple(sorted(ips))
        if signature not in signature_to_payload:
            signature_to_payload[signature] = {"ips": set(), "fqdns": set()}

        signature_to_payload[signature]["ips"].update(ips)
        signature_to_payload[signature]["fqdns"].update(payload.get("fqdns", set()))
        signature_to_sources[signature].add(source_key)

    desired_by_iplist: Dict[str, Dict[str, Set[str]]] = {}
    regroup_events: List[Dict[str, str]] = []
    used_names: Set[str] = set()

    for signature in sorted(signature_to_payload.keys()):
        payload = signature_to_payload[signature]
        merged_fqdns = sorted(payload["fqdns"])
        if not merged_fqdns:
            continue

        bridge_fqdn = merged_fqdns[0]
        base_name = sanitize_name(short_fqdn(bridge_fqdn))

        candidate_name = base_name
        suffix = 2
        while candidate_name in used_names:
            candidate_name = sanitize_name(f"{short_fqdn(bridge_fqdn)}-{suffix}")
            suffix += 1

        used_names.add(candidate_name)
        desired_by_iplist[candidate_name] = {
            "ips": set(payload["ips"]),
            "fqdns": set(payload["fqdns"]),
        }

        sources = sorted(signature_to_sources[signature])
        regroup_events.append(
            {
                "target": candidate_name,
                "bridge_fqdn": bridge_fqdn,
                "sources": ";".join(sources),
                "ips": ";".join(signature),
            }
        )

    return desired_by_iplist, regroup_events


def collect_flow_ips(rows: List[Dict[str, str]]) -> Set[str]:
    ips: Set[str] = set()
    for row in rows:
        vals = list(row.values())
        dst_ip = choose(row, "Destination IP", "destination_ip", default=value_at(vals, 14))
        if dst_ip:
            ips.add(dst_ip)
    return ips


def html_escape_join(values: List[str], sep: str = "<br/>") -> str:
    return sep.join(html.escape(v) for v in values) if values else "-"


def fmt_delta(old_items: List[str], new_items: List[str]) -> str:
    old_set, new_set = set(old_items), set(new_items)
    unchanged = sorted(old_set & new_set)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    chunks = [html.escape(v) for v in unchanged]
    chunks.extend(f"<span style='color:#008000;font-weight:bold'>(+) {html.escape(v)}</span>" for v in added)
    chunks.extend(f"<span style='color:#c00000;font-weight:bold'>(-) {html.escape(v)}</span>" for v in removed)
    return "<br/>".join(chunks) if chunks else "-"


def build_table_html(title: str, headers: List[str], rows: List[List[str]]) -> str:
    table_style = "border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px;"
    th_style = "border:1px solid #bfbfbf;background:#d9d9d9;font-weight:bold;padding:6px;text-align:left;"
    td_style = "border:1px solid #d0d0d0;padding:6px;vertical-align:top;"

    thead = "".join(f"<th style='{th_style}'>{html.escape(h)}</th>" for h in headers)
    body_rows = []
    if rows:
        for row in rows:
            body_rows.append("<tr>" + "".join(f"<td style='{td_style}'>{cell}</td>" for cell in row) + "</tr>")
    else:
        body_rows.append(f"<tr><td style='{td_style}' colspan='{len(headers)}'>No data</td></tr>")

    return (
        f"<h3 style='font-family:Arial,sans-serif'>{html.escape(title)}</h3>"
        f"<table style='{table_style}'><thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def excel_column_name(index: int) -> str:
    name = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def excel_inline_cell(text: str, style: int = 0) -> str:
    escaped = saxutils.escape(text or "")
    return f"<c t='inlineStr' s='{style}'><is><t xml:space='preserve'>{escaped}</t></is></c>"


def build_excel(rows: List[Dict[str, str]], output_path: Path) -> None:
    headers = ["IPList name", "fqdns", "IP Adresses", "Last seen at", "href"]

    max_chars = [len(h) for h in headers]
    row_xml = []

    header_cells = "".join(excel_inline_cell(h, style=1) for h in headers)
    row_xml.append(f"<row r='1'>{header_cells}</row>")

    for row_idx, item in enumerate(rows, start=2):
        values = [
            item.get("name", ""),
            item.get("fqdns", "").replace(";", "; "),
            item.get("include", "").replace(";", "; "),
            item.get("last_seen", ""),
            item.get("href", ""),
        ]
        for i, v in enumerate(values):
            max_chars[i] = max(max_chars[i], len(v or ""))
        cells = "".join(excel_inline_cell(v, style=0) for i, v in enumerate(values))
        row_xml.append(f"<row r='{row_idx}'>{cells}</row>")

    max_width = 100.0
    cols_xml = []
    for i, width_chars in enumerate(max_chars, start=1):
        width = min(max(float(width_chars) + 2.0, 12.0), max_width)
        cols_xml.append(f"<col min='{i}' max='{i}' width='{width:.2f}' customWidth='1' bestFit='1'/>")

    sheet_xml = f"""<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <cols>{''.join(cols_xml)}</cols>
  <sheetData>{''.join(row_xml)}</sheetData>
</worksheet>
"""

    styles_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<styleSheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <fonts count='2'>
    <font><name val='Arial'/><sz val='11'/></font>
    <font><b/><name val='Arial'/><sz val='11'/></font>
  </fonts>
  <fills count='3'>
    <fill><patternFill patternType='none'/></fill>
    <fill><patternFill patternType='gray125'/></fill>
    <fill><patternFill patternType='solid'><fgColor rgb='FFD9E1F2'/><bgColor indexed='64'/></patternFill></fill>
  </fills>
  <borders count='1'><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0'/></cellStyleXfs>
  <cellXfs count='2'>
    <xf numFmtId='0' fontId='0' fillId='0' borderId='0' xfId='0' applyAlignment='1'><alignment vertical='top'/></xf>
    <xf numFmtId='0' fontId='1' fillId='2' borderId='0' xfId='0' applyFont='1' applyFill='1' applyAlignment='1'><alignment vertical='center'/></xf>
  </cellXfs>
  <cellStyles count='1'><cellStyle name='Normal' xfId='0' builtinId='0'/></cellStyles>
</styleSheet>
"""

    workbook_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <sheets><sheet name='DNA_IPLists' sheetId='1' r:id='rId1'/></sheets>
</workbook>
"""

    rels_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>
"""

    workbook_rels_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
  <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles' Target='styles.xml'/>
</Relationships>
"""

    content_types_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
  <Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
  <Override PartName='/xl/styles.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'/>
</Types>
"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/styles.xml", styles_xml)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    conf_path = Path(args.config).resolve()
    conf = read_conf(conf_path)

    use_stub_data = parse_bool(conf.get("USE_STUB_DATA", "false"))
    stub_data_dir = conf.get("STUB_DATA_DIR", "")
    stub_root = Path(stub_data_dir).resolve() if stub_data_dir else (root / "stub_data")

    now = dt.datetime.now()
    run_dir = (root / conf.get("EXPORT_ROOT", "./RUNS") / now.strftime(conf.get("DATE_FMT", "%Y%m%d-%H%M%S"))).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    execution_log = run_dir / "execution.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(execution_log, encoding="utf-8"), logging.StreamHandler()],
    )
    logger = logging.getLogger("dna_automanage")

    if use_stub_data:
        logger.info("Stub mode enabled (USE_STUB_DATA=true). Reading fixtures from %s", stub_root)
        if not stub_root.exists() or not stub_root.is_dir():
            logger.error("Stub data directory not found: %s", stub_root)
            return 1

    steps: List[StepResult] = []
    bin_dir = root / "bin"

    export_ipl = run_dir / "export_iplists.csv"
    export_label = run_dir / "export_label.csv"
    export_labelgroup = run_dir / "export_labelgroup.csv"

    expected_exports = {
        "export_iplists": export_ipl,
        "export_labels": export_label,
        "export_labelgroups": export_labelgroup,
    }

    for name, cmd in [
        ("export_iplists", [str(bin_dir / "workloader_ipl_export.sh"), str(export_ipl)]),
        ("export_labels", [str(bin_dir / "workloader_label_export.sh"), str(export_label)]),
        ("export_labelgroups", [str(bin_dir / "workloader_labelgroup.sh"), str(export_labelgroup)]),
    ]:
        if use_stub_data:
            stub_name = {
                "export_iplists": "export_iplists.csv",
                "export_labels": "export_label.csv",
                "export_labelgroups": "export_labelgroup.csv",
            }[name]
            try:
                copy_stub_csv(stub_root, expected_exports[name], stub_name)
                step = stub_step(name, f"stub copied from {stub_root / stub_name}")
            except FileNotFoundError as exc:
                logger.error("%s", exc)
                return 1
        else:
            step = run_step(name, cmd, root, logger)
        steps.append(step)
        if step.rc != 0:
            return 1

        expected_file = expected_exports[name]
        if not expected_file.exists() or expected_file.stat().st_size == 0:
            logger.error("%s reported success but did not generate %s", name, expected_file)
            return 1

    labels_rows = csv_rows(export_label)
    (run_dir / "service.exlude.csv").write_text("PortNumber,NumericIANA\n0,1\n0,58\n", encoding="utf-8")

    wave_specs = [
        {
            "name": "wave1",
            "incl_src_types_key": "LABELS_TYPE_TO_INCLUDE_SRC_WAVE1",
            "incl_src_values_key": "LABELS_PREFIX_TO_INCLUDE_SRC_WAVE1",
            "incl_src_mode": "prefix",
            "excl_src_types_key": "LABELS_TYPE_TO_EXCLUDE_SRC_WAVE1",
            "excl_src_values_key": "LABELS_TO_EXCLUDE_SRC_WAVE1",
            "excl_src_mode": "value",
            "excl_dst_types_key": "LABELS_TYPE_TO_EXCLUDE_DST_WAVE1",
            "excl_dst_values_key": "LABELS_TO_EXCLUDE_WAVE1",
            "excl_dst_mode": "value",
        },
        {
            "name": "wave2",
            "incl_src_types_key": "LABELS_TYPE_TO_INCLUDE_SRC_WAVE2",
            "incl_src_values_key": "LABELS_PREFIX_TO_INCLUDE_SRC_WAVE2",
            "incl_src_mode": "prefix",
            "excl_src_types_key": "LABELS_TYPE_TO_EXCLUDE_SRC_WAVE2",
            "excl_src_values_key": "LABELS_TO_EXCLUDE_SRC_WAVE2",
            "excl_src_mode": "value",
            "excl_dst_types_key": "LABELS_TYPE_TO_EXCLUDE_DST_WAVE2",
            "excl_dst_values_key": "LABELS_TO_EXCLUDE_WAVE2",
            "excl_dst_mode": "value",
        },
    ]

    days = int(conf.get("NUMBER_OF_DAYS_AGO", "7"))
    start_date = (now.date() - dt.timedelta(days=days)).isoformat()
    end_date = now.date().isoformat()
    timestamp = now.strftime('%Y%m%d-%H%M%S')
    wave_files: List[Path] = []

    for spec in wave_specs:
        wave = spec["name"]
        incl_src_hrefs = build_label_href_filter(
            labels_rows,
            parse_types(conf, spec["incl_src_types_key"]),
            conf.get(spec["incl_src_values_key"], ""),
            spec["incl_src_mode"],
        )
        excl_src_hrefs = build_label_href_filter(
            labels_rows,
            parse_types(conf, spec["excl_src_types_key"]),
            conf.get(spec["excl_src_values_key"], ""),
            spec["excl_src_mode"],
        )
        excl_dst_hrefs = build_label_href_filter(
            labels_rows,
            parse_types(conf, spec["excl_dst_types_key"]),
            conf.get(spec["excl_dst_values_key"], ""),
            spec["excl_dst_mode"],
        )

        incl_src_file = run_dir / f"href_labels.include.src.{wave}.csv"
        excl_src_file = run_dir / f"href_labels.exclude.src.{wave}.csv"
        excl_dst_file = run_dir / f"href_labels.exclude.dst.{wave}.csv"
        wave_flow_file = run_dir / f"flow-out-fqdn-{wave}-{timestamp}.csv"

        write_href_file(incl_src_file, incl_src_hrefs)
        write_href_file(excl_src_file, excl_src_hrefs)
        write_href_file(excl_dst_file, excl_dst_hrefs)

        if use_stub_data:
            stub_name = f"flow-out-fqdn-{wave}.csv"
            try:
                copy_stub_csv(stub_root, wave_flow_file, stub_name)
                step = stub_step(f"export_traffic_{wave}", f"stub copied from {stub_root / stub_name}")
            except FileNotFoundError as exc:
                logger.error("%s", exc)
                return 1
        else:
            step = run_step(
                f"export_traffic_{wave}",
                [
                    str(bin_dir / "workloader_traffic_out.sh"),
                    str(incl_src_file),
                    str(excl_src_file),
                    str(excl_dst_file),
                    str(run_dir / "service.exlude.csv"),
                    start_date,
                    end_date,
                    str(wave_flow_file),
                ],
                root,
                logger,
            )
        steps.append(step)
        if step.rc != 0:
            return 1
        wave_files.append(wave_flow_file)

    flow_file = run_dir / f"flow-out-fqdn-{timestamp}.csv"
    merged_flow_rows: List[Dict[str, str]] = []
    merged_headers: List[str] = []

    for wave_flow_file in wave_files:
        wave_flow_rows = csv_rows(wave_flow_file)
        if wave_flow_rows and not merged_headers:
            merged_headers = list(wave_flow_rows[0].keys())
        merged_flow_rows.extend(wave_flow_rows)

    if merged_flow_rows:
        merged_no_empty = drop_rows_without_destination_fqdn(merged_flow_rows)
        if merged_no_empty:
            write_csv(flow_file, list(merged_no_empty[0].keys()), merged_no_empty)
        else:
            write_csv(flow_file, merged_headers, [])
        filtered_flow = filter_flow_rows(merged_no_empty)
    else:
        flow_file.write_text("", encoding="utf-8")
        filtered_flow = []
        flow_file.write_text("", encoding="utf-8")

    ipl_rows = csv_rows(export_ipl)
    dna_prefix = conf.get("DNA_IPLIST_PREFIX", "DNA_")
    existing: Dict[str, Dict[str, str]] = {}
    for r in ipl_rows:
        name = choose(r, "name", "Name")
        if not name.startswith(dna_prefix):
            continue
        existing[name] = {
            "name": name,
            "description": choose(r, "description", "Description"),
            "include": choose(r, "include", "Include"),
            "fqdns": choose(r, "fqdns", "FQDNS", "fqdn"),
            "href": choose(r, "href", "Href"),
        }

    az_tokens = parse_list(conf, "AVAILABILITY_ZONES", "eu-fr-paris;eu-fr-north;hk-hongkong;sg-singapore")
    dns_timeout = float(conf.get("DNS_LOOKUP_TIMEOUT_SEC", "2"))
    socket.setdefaulttimeout(dns_timeout)

    ips_by_group_key: Dict[str, Set[str]] = defaultdict(set)
    fqdns_by_group_key: Dict[str, Set[str]] = defaultdict(set)
    for r in filtered_flow:
        vals = list(r.values())
        fqdn = choose(r, "Destination FQDN", default=value_at(vals, 25))
        ip = choose(r, "Destination IP", default=value_at(vals, 14))
        group_key = group_key_for_fqdn(fqdn)
        if fqdn and ip and group_key:
            ips_by_group_key[group_key].add(ip)
            fqdns_by_group_key[group_key].add(fqdn.lower())

            for candidate_fqdn in sorted(expand_fqdn_by_az(fqdn, az_tokens)):
                if candidate_fqdn == fqdn.lower():
                    continue
                candidate_ips = resolve_fqdn_ips(candidate_fqdn, logger)
                if candidate_ips:
                    fqdns_by_group_key[group_key].add(candidate_fqdn)
                    ips_by_group_key[group_key].update(candidate_ips)

    today = now.date().isoformat()
    create_rows, update_rows = [], []
    created_for_report, updated_for_report = [], []
    kept_by_dns_for_report, kept_by_flow_for_report = [], []
    merged_for_report: List[Dict[str, str]] = []
    current_state = {k: dict(v) for k, v in existing.items()}

    desired_by_group_key: Dict[str, Dict[str, Set[str]]] = {}
    for group_key, ips in sorted(ips_by_group_key.items()):
        desired_by_group_key[group_key] = {
            "ips": set(ips),
            "fqdns": set(fqdns_by_group_key[group_key]),
        }

    desired_by_iplist, regroup_events = regroup_by_exact_ips_with_bridge_fqdn(desired_by_group_key)

    candidate_ips_to_delete: Set[str] = set()
    for iplist_name, old in existing.items():
        old_ips = parse_semicolon_set(old["include"])
        desired_ips = desired_by_iplist.get(iplist_name, {}).get("ips", set())
        candidate_ips_to_delete.update(old_ips - desired_ips)

    flow_seen_ips_in_candidates: Set[str] = set()
    if candidate_ips_to_delete:
        flow_out_delete_candidates = run_dir / f"flow-out-dst-delete-candidates-{timestamp}.csv"

        if use_stub_data:
            stub_name = "flow-out-dst-delete-candidates.csv"
            try:
                copy_stub_csv(stub_root, flow_out_delete_candidates, stub_name)
                steps.append(stub_step("export_traffic_delete_candidates", f"stub copied from {stub_root / stub_name}"))
            except FileNotFoundError:
                flow_out_delete_candidates.write_text("", encoding="utf-8")
                steps.append(stub_step("export_traffic_delete_candidates", "stub file not provided, assuming no delete-candidate flows"))

            if flow_out_delete_candidates.exists() and flow_out_delete_candidates.stat().st_size > 0:
                flow_seen_ips_in_candidates = collect_flow_ips(csv_rows(flow_out_delete_candidates))
        else:
            tmp_name = f"_tmp_ip.to.delete_{timestamp}-IPL"
            tmp_create_csv = run_dir / "new.iplist.tmp.egress.to.delete.csv"
            tmp_href_file = run_dir / "href_tmp.egress.to.delete.csv"
            href_ips_to_delete_csv = run_dir / "href_ips.to.delete.csv"

            tmp_payload = {
                "description": f"Temporary candidate IP list generated at {now.isoformat(timespec='seconds')}",
                "include": ";".join(sorted(candidate_ips_to_delete)),
                "fqdns": "",
            }

            with tmp_create_csv.open("w", encoding="utf-8", newline="") as f:
                wr = csv.DictWriter(f, fieldnames=["name", "description", "include", "fqdns"])
                wr.writeheader()
                wr.writerow({"name": tmp_name, **tmp_payload})
            step = run_step("create_tmp_delete_iplist", [str(bin_dir / "workloader_ipl_import.sh"), str(tmp_create_csv)], root, logger)
            steps.append(step)
            if step.rc != 0:
                return 1

            tmp_export_csv = run_dir / "export_iplists.with.tmp.csv"
            step = run_step("export_iplists_for_tmp_href", [str(bin_dir / "workloader_ipl_export.sh"), str(tmp_export_csv)], root, logger)
            steps.append(step)
            if step.rc != 0:
                return 1

            tmp_rows = csv_rows(tmp_export_csv)
            tmp_href = ""
            for row in tmp_rows:
                if choose(row, "name", "Name") == tmp_name:
                    tmp_href = choose(row, "href", "Href")
                    break

            if not tmp_href:
                logger.error("Temporary IPList %s href not found after export", tmp_name)
                return 1

            tmp_href_file.write_text(tmp_href + "\n", encoding="utf-8")
            href_ips_to_delete_csv.write_text(tmp_href + "\n", encoding="utf-8")

            flow_days = int(conf.get("FLOW_DELETE_VERIFICATION_DAYS", "60"))
            flow_start = (now.date() - dt.timedelta(days=flow_days)).isoformat()
            flow_end = now.date().isoformat()

            flow_step_rc = 0
            try:
                step = run_step(
                    "export_traffic_delete_candidates",
                    [
                        str(bin_dir / "workloader_traffic_out_dst.sh"),
                        str(href_ips_to_delete_csv),
                        flow_start,
                        flow_end,
                        str(flow_out_delete_candidates),
                    ],
                    root,
                    logger,
                )
                steps.append(step)
                flow_step_rc = step.rc

                if flow_step_rc == 0 and flow_out_delete_candidates.exists() and flow_out_delete_candidates.stat().st_size > 0:
                    flow_seen_ips_in_candidates = collect_flow_ips(csv_rows(flow_out_delete_candidates))
            finally:
                cleanup_step = run_step("delete_tmp_delete_iplist", [str(bin_dir / "workloader_ipl_delete.sh"), str(tmp_href_file)], root, logger)
                steps.append(cleanup_step)
                if cleanup_step.rc != 0:
                    logger.warning("Temporary delete-candidate IPList could not be deleted, please clean manually: %s", tmp_name)

            if flow_step_rc != 0:
                return 1

    reassigned_for_report.extend(reassigned_ips)

    merged_for_report.extend(regroup_events)

    merged_for_report.extend(regroup_events)

    for iplist_name, desired in sorted(desired_by_iplist.items()):
        desired_ips = set(desired["ips"])
        if not desired_ips:
            continue
        fqdn_list = sorted(desired["fqdns"])
        description = f"Last seen at : {today}"

        if iplist_name in existing:
            old_ips = parse_semicolon_set(existing[iplist_name]["include"])
            old_fqdns_set = parse_semicolon_set(existing[iplist_name]["fqdns"])
            merged_fqdns_set = old_fqdns_set | set(fqdn_list)
            merged_fqdns = sorted(merged_fqdns_set)
            old_fqdns = sorted(old_fqdns_set)
            kept_dns = set()
            kept_flow = set()

            for ip in sorted(old_ips - desired_ips):
                fqdn_matches = [fqdn for fqdn in merged_fqdns if ip in resolve_fqdn_ips(fqdn, logger)]
                if fqdn_matches:
                    desired_ips.add(ip)
                    kept_dns.add(ip)
                    continue
                if ip in flow_seen_ips_in_candidates:
                    desired_ips.add(ip)
                    kept_flow.add(ip)

            include = ";".join(sorted(desired_ips))
            update_rows.append(
                {
                    "href": existing[iplist_name]["href"],
                    "description": description,
                    "include": include,
                    "fqdns": ";".join(merged_fqdns),
                }
            )

            if kept_dns:
                kept_by_dns_for_report.append({"name": iplist_name, "ips": sorted(kept_dns)})
            if kept_flow:
                kept_by_flow_for_report.append({"name": iplist_name, "ips": sorted(kept_flow)})

            if old_fqdns_set != merged_fqdns_set or old_ips != desired_ips:
                updated_for_report.append(
                    {
                        "name": iplist_name,
                        "old_fqdns": old_fqdns,
                        "new_fqdns": merged_fqdns,
                        "old_ips": sorted(old_ips),
                        "new_ips": sorted(desired_ips),
                    }
                )
        else:
            include = ";".join(sorted(desired_ips))
            create_rows.append({"name": iplist_name, "description": description, "include": include, "fqdns": ";".join(fqdn_list)})
            created_for_report.append({"name": iplist_name, "fqdns": fqdn_list, "ips": sorted(desired_ips)})

        current_state[iplist_name] = {
            "name": iplist_name,
            "description": description,
            "include": ";".join(sorted(desired_ips)),
            "fqdns": ";".join(merged_fqdns) if iplist_name in existing else ";".join(fqdn_list),
            "href": existing.get(iplist_name, {}).get("href", ""),
        }

    create_csv = run_dir / "new.iplist.new.fqdns.csv"
    update_csv = run_dir / "update.iplist.existing.fqdns.csv"
    with create_csv.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["name", "description", "include", "fqdns"])
        wr.writeheader()
        wr.writerows(create_rows)
    with update_csv.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["href", "description", "include", "fqdns"])
        wr.writeheader()
        wr.writerows(update_rows)

    for name, path in [("import_new_iplists", create_csv), ("update_existing_iplists", update_csv)]:
        if sum(1 for _ in path.open("r", encoding="utf-8")) > 1:
            if use_stub_data:
                steps.append(stub_step(name, f"stub mode: skipped workloader import for {path.name}"))
            else:
                steps.append(run_step(name, [str(bin_dir / "workloader_ipl_import.sh"), str(path)], root, logger))

    stale_threshold = int(conf.get("STALE_LAST_SEEN_DAYS", "21"))
    stale = []
    for v in current_state.values():
        d = parse_last_seen(v["description"])
        if d and (now.date() - d).days > stale_threshold:
            stale.append({"name": v["name"], "fqdns": v["fqdns"], "include": v["include"], "last_seen": d.isoformat(), "href": v["href"]})

    report_log = run_dir / "execution_report.log"
    with report_log.open("w", encoding="utf-8") as f:
        f.write("Section 1 - Execution summary\n")
        for s in steps:
            f.write(f"- {s.name}: rc={s.rc}; started={s.started_at}; ended={s.ended_at}\n")
        f.write("\nSection 2 - Detailed execution log\n")
        if execution_log.exists():
            f.write(execution_log.read_text(encoding="utf-8"))

    all_dna_rows = []
    for v in sorted(current_state.values(), key=lambda x: x["name"]):
        d = parse_last_seen(v["description"])
        all_dna_rows.append(
            {
                "name": v["name"],
                "fqdns": v["fqdns"],
                "include": v["include"],
                "last_seen": d.isoformat() if d else "",
                "href": v.get("href", ""),
            }
        )

    excel_path = run_dir / "DNA_IPLists_After_Run.xlsx"
    build_excel(all_dna_rows, excel_path)

    created_rows_html = [[html.escape(i["name"]), html_escape_join(i["fqdns"]), html_escape_join(i["ips"])] for i in created_for_report]
    updated_rows_html = [
        [
            html.escape(i["name"]),
            fmt_delta(i["old_fqdns"], i["new_fqdns"]),
            fmt_delta(i["old_ips"], i["new_ips"]),
        ]
        for i in updated_for_report
    ]
    stale_rows_html = [
        [
            html.escape(i["name"]),
            html_escape_join(sorted(filter(None, i["fqdns"].split(";")))),
            html_escape_join(sorted(filter(None, i["include"].split(";")))),
            html.escape(i["last_seen"]),
        ]
        for i in stale
    ]
    kept_dns_rows_html = [[html.escape(i["name"]), html_escape_join(i["ips"])] for i in kept_by_dns_for_report]
    kept_flow_rows_html = [[html.escape(i["name"]), html_escape_join(i["ips"])] for i in kept_by_flow_for_report]
    merged_rows_html = [
        [
            html.escape(i["target"]),
            html.escape(i["bridge_fqdn"]),
            html_escape_join(sorted(filter(None, i["sources"].split(";")))),
            html_escape_join(sorted(filter(None, i["ips"].split(";")))),
        ]
        for i in merged_for_report
    ]

    script_name = Path(__file__).name
    vm_hostname = socket.gethostname()

    body_html = (
        "<div style='font-family:Arial,sans-serif'>"
        + build_table_html(
            "Table 1 : New FQDN IPList(s) created",
            ["IPList name", "fqdns", "IP Adresses"],
            created_rows_html,
        )
        + "<br/>"
        + build_table_html(
            "Table 2 : Existing FQDN IPList(s) updated",
            ["IPList name", "fqdns", "IP Adresses"],
            updated_rows_html,
        )
        + "<br/>"
        + build_table_html(
            "Table 3 : FQDN IPList(s) candidate(s) for deletion (not seen since 3 weeks)",
            ["IPList name", "fqdns", "IP Adresses", "Last seen at"],
            stale_rows_html,
        )
        + "<br/>"
        + build_table_html(
            "Table 4 : IP(s) kept because still resolved by DNS",
            ["IPList name", "IP Adresses"],
            kept_dns_rows_html,
        )
        + "<br/>"
        + build_table_html(
            "Table 5 : IP(s) kept because still present in destination flows",
            ["IPList name", "IP Adresses"],
            kept_flow_rows_html,
        )
        + "<br/>"
        + build_table_html(
            "Table 6 : IPList regrouping by identical IP set",
            ["Target IPList", "Bridge FQDN", "Merged source groups", "Shared IPs"],
            merged_rows_html,
        )
        + f"<br/><p style='font-family:Arial,sans-serif'><strong>Sent by FQDN IPList Batch<br/>{html.escape(script_name)} / running from {html.escape(vm_hostname)}</strong></p>"
        + "</div>"
    )

    body_text_lines = [
        "New FQDN IPList(s) created:",
        *(f"- {i['name']} | fqdns={';'.join(i['fqdns'])} | ips={';'.join(i['ips'])}" for i in created_for_report),
        "",
        "Existing FQDN IPList(s) updated:",
        *(
            f"- {i['name']} | fqdns +( {','.join(sorted(set(i['new_fqdns'])-set(i['old_fqdns'])))} ) -( {','.join(sorted(set(i['old_fqdns'])-set(i['new_fqdns'])))} )"
            f" | ips +( {','.join(sorted(set(i['new_ips'])-set(i['old_ips'])))} ) -( {','.join(sorted(set(i['old_ips'])-set(i['new_ips'])))} )"
            for i in updated_for_report
        ),
        "",
        "FQDN IPList(s) candidate(s) for deletion (not seen since 3 weeks):",
        *(f"- {i['name']} | {i['fqdns']} | {i['include']} | {i['last_seen']}" for i in stale),
        "",
        "IP(s) kept because still resolved by DNS:",
        *(f"- {i['name']} | ips={';'.join(i['ips'])}" for i in kept_by_dns_for_report),
        "",
        "IP(s) kept because still present in destination flows:",
        *(f"- {i['name']} | ips={';'.join(i['ips'])}" for i in kept_by_flow_for_report),
        "",
        "IPList regrouping by identical IP set:",
        *(f"- target={i['target']} | bridge_fqdn={i['bridge_fqdn']} | sources={i['sources']} | ips={i['ips']}" for i in merged_for_report),
        "",
        "Sent by FQDN IPList Batch",
        f"{script_name} / running from {vm_hostname}",
    ]
    body_text = "\n".join(body_text_lines)

    recipients = parse_recipients(conf.get("MAIL_TO", ""))
    if recipients and conf.get("SMTP_SERVER", "").strip():
        send_carto_notification(
            conf=conf,
            recipients=recipients,
            subject=f"DNA IPList Auto-Manage report - {now.strftime('%Y-%m-%d %H:%M:%S')}",
            body_text=body_text,
            body_html=body_html,
            attachment_paths=[report_log, excel_path],
            logger=logger,
        )
    else:
        logger.warning("Email not sent (MAIL_TO/SMTP_SERVER not configured).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
