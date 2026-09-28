"""Excel (.xlsx) and CSV read/write utilities for AURA.

Supports pandas DataFrames and OpenPyXL when available, and includes a
standards-compliant OpenXML (.xlsx) multi-sheet reader/writer using Python's
built-in `zipfile`, `csv`, and `xml.etree.ElementTree` modules so batch upload,
template download, and 8-sheet governance export work in all environments.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

try:
    import pandas as pd  # type: ignore[import-untyped]

    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

try:
    import openpyxl  # type: ignore[import-untyped]

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _col_letter(idx_zero_based: int) -> str:
    """Convert 0-based column index to Excel column letters (A, B, ..., Z, AA, ...)."""
    result = ""
    n = idx_zero_based + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _col_index(col_letters: str) -> int:
    """Convert Excel column letters to 0-based index."""
    idx = 0
    for ch in col_letters:
        if "A" <= ch <= "Z":
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


def _normalize_sheet_rows(sheet_data: Any) -> tuple[list[str], list[list[Any]]]:
    """Normalize a DataFrame or list[dict[str, Any]] into (columns, rows)."""
    if HAS_PANDAS and pd is not None and isinstance(sheet_data, pd.DataFrame):
        cols = [str(c) for c in sheet_data.columns]
        rows = [list(r) for r in sheet_data.itertuples(index=False)]
        return cols, rows

    if isinstance(sheet_data, list):
        if not sheet_data:
            return ["info"], []
        first = sheet_data[0]
        if isinstance(first, dict):
            cols_set: list[str] = []
            for item in sheet_data:
                for k in item.keys():
                    if str(k) not in cols_set:
                        cols_set.append(str(k))
            rows = [[item.get(c) for c in cols_set] for item in sheet_data]
            return cols_set, rows

    return ["value"], [[str(sheet_data)]]


def write_excel_sheets(
    sheets: dict[str, Any],
    target: str | Path | io.BytesIO | None = None,
) -> bytes:
    """Write multiple sheets (DataFrames or list of dicts) to an .xlsx workbook and return bytes."""
    if HAS_PANDAS and HAS_OPENPYXL and pd is not None:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for sheet_name, sheet_data in sheets.items():
                safe_name = sheet_name[:31]
                if isinstance(sheet_data, pd.DataFrame):
                    df = sheet_data
                else:
                    df = pd.DataFrame(sheet_data)
                df.to_excel(writer, sheet_name=safe_name, index=False)
        data = buf.getvalue()
        if isinstance(target, (str, Path)):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(data)
        elif isinstance(target, io.BytesIO):
            target.write(data)
            target.seek(0)
        return data

    # Standard-library OpenXML (.xlsx) multi-sheet writer
    buf = io.BytesIO()
    sheet_names = [name[:31] for name in sheets.keys()]
    normalized = [_normalize_sheet_rows(val) for val in sheets.values()]

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        overrides = "\n".join(
            f'  <Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheet_names) + 1)
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
            f"{overrides}\n"
            "</Types>"
        )
        zf.writestr("[Content_Types].xml", content_types)

        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>\n'
            "</Relationships>"
        )
        zf.writestr("_rels/.rels", root_rels)

        sheet_nodes = "\n".join(
            f'    <sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheet_names, start=1)
        )
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            "  <sheets>\n"
            f"{sheet_nodes}\n"
            "  </sheets>\n"
            "</workbook>"
        )
        zf.writestr("xl/workbook.xml", workbook_xml)

        wb_rels_nodes = "\n".join(
            f'  <Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i, name in enumerate(sheet_names, start=1)
        )
        wb_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f"{wb_rels_nodes}\n"
            "</Relationships>"
        )
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)

        for sheet_idx, (cols, rows) in enumerate(normalized, start=1):
            rows_xml: list[str] = []
            header_cells = [
                f'<c r="{_col_letter(c_idx)}1" t="inlineStr"><is><t>{escape(col)}</t></is></c>'
                for c_idx, col in enumerate(cols)
            ]
            rows_xml.append(f'    <row r="1">{"".join(header_cells)}</row>')

            for r_idx, row in enumerate(rows, start=2):
                cell_xmls: list[str] = []
                for c_idx, val in enumerate(row):
                    ref = f"{_col_letter(c_idx)}{r_idx}"
                    if val is None:
                        cell_xmls.append(f'<c r="{ref}" t="inlineStr"><is><t></t></is></c>')
                    elif isinstance(val, bool):
                        cell_xmls.append(f'<c r="{ref}" t="inlineStr"><is><t>{str(val)}</t></is></c>')
                    elif isinstance(val, (int, float)):
                        cell_xmls.append(f'<c r="{ref}"><v>{val}</v></c>')
                    else:
                        s_val = escape(str(val))
                        cell_xmls.append(f'<c r="{ref}" t="inlineStr"><is><t>{s_val}</t></is></c>')
                rows_xml.append(f'    <row r="{r_idx}">{"".join(cell_xmls)}</row>')

            sheet_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
                "  <sheetData>\n"
                + "\n".join(rows_xml)
                + "\n  </sheetData>\n"
                "</worksheet>"
            )
            zf.writestr(f"xl/worksheets/sheet{sheet_idx}.xml", sheet_xml)

    data = buf.getvalue()
    if isinstance(target, (str, Path)):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(data)
    elif isinstance(target, io.BytesIO):
        target.write(data)
        target.seek(0)
    return data


def read_excel_records(source: str | Path | bytes | io.BytesIO, sheet_index: int = 0) -> tuple[list[str], list[dict[str, Any]]]:
    """Read an .xlsx worksheet and return (columns, list_of_row_dicts)."""
    if isinstance(source, (str, Path)):
        raw_bytes = Path(source).read_bytes()
    elif isinstance(source, io.BytesIO):
        raw_bytes = source.getvalue()
    else:
        raw_bytes = source

    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("main:si", ns):
                texts = [t.text or "" for t in si.findall(".//main:t", ns)]
                shared_strings.append("".join(texts))

        sheet_path = f"xl/worksheets/sheet{sheet_index + 1}.xml"
        if sheet_path not in zf.namelist():
            sheet_files = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet"))
            if not sheet_files:
                return [], []
            sheet_path = sheet_files[0]

        ws_root = ET.fromstring(zf.read(sheet_path))
        parsed_rows: list[list[Any]] = []
        max_cols = 0

        for row_el in ws_root.findall(".//main:sheetData/main:row", ns):
            row_dict: dict[int, Any] = {}
            for c_el in row_el.findall("main:c", ns):
                ref = c_el.attrib.get("r", "A1")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                c_idx = _col_index(col_letters)
                c_type = c_el.attrib.get("t", "")
                val: Any = None
                if c_type == "inlineStr":
                    t_el = c_el.find(".//main:t", ns)
                    val = t_el.text if (t_el is not None and t_el.text is not None) else ""
                elif c_type == "s":
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text is not None:
                        s_idx = int(v_el.text)
                        val = shared_strings[s_idx] if 0 <= s_idx < len(shared_strings) else ""
                else:
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text is not None:
                        raw_v = v_el.text
                        try:
                            val = int(raw_v) if "." not in raw_v else float(raw_v)
                        except ValueError:
                            val = raw_v
                row_dict[c_idx] = val
                if c_idx + 1 > max_cols:
                    max_cols = c_idx + 1
            if row_dict:
                parsed_rows.append([row_dict.get(i) for i in range(max_cols)])

    if not parsed_rows:
        return [], []
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(parsed_rows[0])]
    records: list[dict[str, Any]] = []
    for row in parsed_rows[1:]:
        padded = row + [None] * (len(headers) - len(row))
        records.append({headers[i]: padded[i] for i in range(len(headers))})
    return headers, records


def write_csv_records(rows: list[dict[str, Any]], target: str | Path) -> None:
    """Write a list of dicts to a CSV file."""
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with target_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
