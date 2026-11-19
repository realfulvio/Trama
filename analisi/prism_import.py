"""Read source tables from verified GraphPad Prism ZIP and XML containers."""
from collections import Counter
import csv
from io import StringIO
import json
import re
import tokenize
from itertools import zip_longest
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

import numpy as np

from .data import (COLUMN_FORMULA_FUNCTIONS, ELEMENTWISE_FORMULA_FUNCTIONS, MAX_CELLS, MAX_COLUMNS, MAX_ENTRY,
                   _member, _table, formula)
from .formula_windows import CONDITIONAL_CALLS, WINDOW_CALLS, WINDOW_CLAUSES, WINDOW_KEYWORDS
from .info import InfoSheet, MAX_INFO_FIELDS, MAX_INFO_SHEETS

_PRISM_NS = "{http://graphpad.com/prism/Prism.htm}"
_XSLT_NS = "{http://www.w3.org/1999/XSL/Transform}"
_TABLE_FORMATS = {"multivariable", "column", "xy", "survival", "contingency", "grouped", "nested", "parts_of_whole"}
_Y_SUMMARY = {
    "SD": ("Mean", "SD"), "SE": ("Mean", "SEM"), "CV": ("Mean", "CV%"),
    "SDN": ("Mean", "SD", "N"), "SEN": ("Mean", "SEM", "N"), "CVN": ("Mean", "CV%", "N"),
    "low-high": ("Center", "Plus", "Minus"), "upper-lower-limits": ("Center", "Upper", "Lower"),
}
_ZIP_SUMMARY = {key: _Y_SUMMARY[value] for key, value in {
    "y_sd": "SD", "y_se": "SE", "y_cv": "CV", "y_sd_n": "SDN", "y_se_n": "SEN", "y_cv_n": "CVN",
    "y_plus_minus": "low-high", "y_high_low": "upper-lower-limits",
}.items()}
# These calls have matching semantics in the Prism and TramaStat evaluators.
_FORMULA_CALLS = ELEMENTWISE_FORMULA_FUNCTIONS.keys() | COLUMN_FORMULA_FUNCTIONS.keys() | {"MIN", "MAX", "SUM"}


def _store_table(tables, title, frame):
    name, number = title, 2
    while name in tables:
        name = f"{title} ({number})"
        number += 1
    tables[name] = frame
    return name


def _finish(tables, skipped, info_sheets=None):
    if not tables and not info_sheets:
        message = "The Prism file has no supported source data tables."
        if skipped:
            message += " Unsupported sheets: " + ", ".join(skipped)
        raise ValueError(message)
    if skipped:
        for frame in tables.values():
            frame.attrs["skipped"] = skipped
    return tables


def _json_object(archive, name):
    result = json.loads(_member(archive, name))
    if not isinstance(result, dict):
        raise ValueError(f"Invalid Prism metadata in {name}.")
    return result


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid identifier in Prism metadata.")
    return value


def _formula_recipe(expression, columns, allowed_calls=_FORMULA_CALLS):
    if not isinstance(expression, str) or len(expression) > 2048:
        raise ValueError("Unsupported Prism formula.")
    expression = expression.strip().removeprefix("=").strip()
    tokens = list(tokenize.generate_tokens(StringIO(expression).readline))
    window_form = any(token.type == tokenize.NAME and token.string.upper() in (WINDOW_CLAUSES | CONDITIONAL_CALLS.keys())
                      for token in tokens)
    if window_form:
        allowed_calls = allowed_calls | WINDOW_CALLS | CONDITIONAL_CALLS.keys() | {"AND", "OR", "NOT"}
    result, dependencies = [], set()
    for i, token in enumerate(tokens):
        kind, value = token.type, token.string
        if kind == tokenize.NAME:
            called = i + 1 < len(tokens) and tokens[i + 1].string == "("
            if called and value.upper() in allowed_calls:
                value = value.upper()
            elif not called and window_form and (
                    value.upper() in WINDOW_KEYWORDS or (value.upper() == "BY" and i > 0
                                                         and tokens[i - 1].string.upper() == "ORDER")):
                value = value.upper()
            elif not called and value.upper() == "MOD" and value not in columns:
                value = "MOD"
            elif not called and value in columns:
                name = columns[value]
                result.extend([(tokenize.NAME, "COL"), (tokenize.OP, "("),
                               (tokenize.STRING, repr(name)), (tokenize.OP, ")")])
                dependencies.add(name)
                continue
            else:
                raise ValueError("Unsupported Prism formula reference or function.")
        result.append((kind, value))
    return "=" + tokenize.untokenize(result).strip(), dependencies


def _letters(index):
    """Convert a zero-based column position to A, B, ..., AA."""
    result = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(ord("A") + remainder) + result
        index -= 1
    return result


def _restore_formulas(frame, variables, transforms):
    columns = {_letters(i): frame.columns[column] for i, column in enumerate(variables)}
    pending, failed, restored = {}, set(), {}
    for column, expression in transforms.items():
        name = frame.columns[column]
        try:
            pending[name] = _formula_recipe(expression, columns)
        except (ValueError, SyntaxError, tokenize.TokenError):
            failed.add(name)
    while pending:
        # Keep at least one stored column for the editable project table.
        if len(restored) >= len(frame.columns) - 1:
            break
        ready = [name for name, (_, deps) in pending.items() if deps.isdisjoint(pending)]
        if not ready:
            break
        for name in ready:
            if len(restored) >= len(frame.columns) - 1:
                break
            expression, deps = pending.pop(name)
            if not deps.isdisjoint(failed):
                failed.add(name)
                continue
            try:
                frame[name] = formula(frame, expression)
            except ValueError:
                failed.add(name)
            else:
                restored[name] = expression
    if restored:
        frame.attrs["prism_formulas"] = restored
    if failed or pending:
        frame.attrs["import_warnings"] = ["Unsupported formulas left as stored values where available: "
                                          + ", ".join(name for name in frame if name in failed or name in pending)]
    return frame


def _category_order(metadata):
    categories = metadata.get("categories")
    if not isinstance(categories, list) or not 2 <= len(categories) <= 32:
        return ()
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in categories):
        return ()
    labels = tuple(item["name"] for item in categories)
    return labels if len(set(labels)) == len(labels) and all(labels) else ()


def _zip_table(archive, names, table, remaining_cells, *, result=False):
    fmt = table.get("format")
    mode = table.get("dataFormat")
    ids = table.get("dataSets", [])
    if not isinstance(ids, list):
        raise ValueError("Invalid Prism data set list.")
    labels = _ZIP_SUMMARY.get(mode)
    allowed_format = fmt in _TABLE_FORMATS or (result and fmt == "view")
    allowed_mode = labels is not None or mode in ("y_single", "y_replicates") or (result and mode == "text")
    if not ids or not allowed_format or not allowed_mode:
        return None
    repeats = len(labels) if labels else table.get("replicatesCount") if mode == "y_replicates" else 1
    if type(repeats) is not int or repeats < 1:
        raise ValueError("Invalid Prism replicate count.")
    prefixes = [(table.get("rowTitlesDataSet"), "Row title", "text"),
                (table.get("xDataSet"), "X", None)]
    prefixes = [entry for entry in prefixes if entry[0] is not None]
    roles = [_identifier(uid) for uid in [*(entry[0] for entry in prefixes), *ids]]
    if len(set(roles)) != len(roles):
        raise ValueError("A Prism table uses the same data set in multiple column roles.")
    xmode = table.get("xDataSetFormat", "y_single")
    generated = xmode == "series" and table.get("xDataSet") is not None
    if xmode not in {"y_single", "y_error"} and not generated:
        return None
    width = len(prefixes) + len(ids) * repeats + int(xmode == "y_error" and table.get("xDataSet") is not None)
    if width > MAX_COLUMNS:
        raise ValueError("Prism data table exceeds the column limit.")
    headers, kinds, variables, transforms, slices = [], [], [], {}, {}
    sequence = None
    category_orders = {}
    for uid, default, kind in prefixes:
        metadata = _json_object(archive, f"data/sets/{_identifier(uid)}.json")
        name = metadata.get("title") or default
        start = len(headers)
        headers.append(name)
        kinds.append(kind or metadata.get("currentType", metadata.get("dataType")))
        if default == "X" and xmode == "y_error":
            headers.append(f"{name} [Error]")
            kinds.append(None)
        if default == "X" and generated:
            replicates = metadata.get("replicates")
            if not isinstance(replicates, list) or len(replicates) != 1:
                return None
            replicate = replicates[0]
            if not isinstance(replicate, dict) or replicate.get("@class") != "SeriesReplicate":
                return None
            start_value, interval = replicate.get("startValue"), replicate.get("interval")
            if type(start_value) not in (int, float) or type(interval) not in (int, float):
                return None
            if not np.isfinite([start_value, interval]).all():
                return None
            sequence = start, start_value, interval
        slices[uid] = slice(start, len(headers))
    for number, uid in enumerate(ids, 1):
        metadata = _json_object(archive, f"data/sets/{_identifier(uid)}.json")
        name = metadata.get("title") or f"Y{number}"
        kind = "text" if mode == "text" else metadata.get("currentType", metadata.get("dataType"))
        start = len(headers)
        if repeats == 1 and fmt == "multivariable":
            if kind == "categorical" and (order := _category_order(metadata)):
                category_orders[uid] = order
            variables.append(len(headers))
            source = metadata.get("valuesStorageData")
            if isinstance(source, dict) and source.get("@class") == "TransformDataSource":
                transforms[len(headers)] = source.get("transform")
        if labels:
            headers.extend(f"{name} [{label}]" for label in labels)
        else:
            headers.extend(name if repeats == 1 else f"{name} [{i + 1}]" for i in range(repeats))
        kinds.extend([kind] * repeats)
        slices[uid] = slice(start, len(headers))
    path = f"data/tables/{_identifier(table.get('uid'))}/"
    csv_name = path + "data.csv"
    content_name = path + "content.json"
    expected_rows = None
    stored_width = width - int(generated)
    if content_name in names:
        content = _json_object(archive, content_name)
        declared_width = content.get("numberOfColumns")
        expected_rows = content.get("numberOfRows")
        if (type(declared_width) is not int or declared_width != stored_width
                or type(expected_rows) is not int or expected_rows < 0):
            raise ValueError("Prism table storage dimensions do not match its columns.")
        if expected_rows * width > remaining_cells:
            raise ValueError("Prism data tables exceed the cell limit.")
    csv_text = _member(archive, csv_name) if csv_name in names or expected_rows != 0 else ""
    rows = []
    for row in csv.reader(StringIO(csv_text, newline=""), strict=True):
        if (len(rows) + 1) * width > remaining_cells:
            raise ValueError("Prism data tables exceed the cell limit.")
        if len(row) > stored_width:
            raise ValueError("Prism CSV row is wider than its table metadata.")
        if sequence:
            position, start_value, interval = sequence
            if len(row) < position:
                row.extend([""] * (position - len(row)))
            value = start_value + len(rows) * interval
            if not np.isfinite(value):
                raise ValueError("Generated Prism X values exceed the numeric range.")
            row.insert(position, value)
        rows.append(row)
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError("Prism CSV row count differs from its table metadata.")
    frame = _table(headers, rows, kinds)
    frame.attrs["table_format"] = fmt
    frame.attrs["prism_columns"] = {uid: list(frame.columns[region]) for uid, region in slices.items()}
    frame.attrs["prism_x"] = table.get("xDataSet")
    frame.attrs["prism_y"] = ids
    frame.attrs["prism_y_format"] = mode
    if category_orders:
        frame.attrs["prism_category_orders"] = category_orders
    return _restore_formulas(frame, variables, transforms) if transforms else frame


def _zip_info_text(value):
    if isinstance(value, dict):
        value = value.get("string")
    if not isinstance(value, str):
        raise ValueError("Invalid Prism Info text.")
    return value


def _zip_info(archive, ids, target, skipped):
    if not isinstance(ids, list) or len(ids) > MAX_INFO_SHEETS:
        raise ValueError("Invalid Prism Info sheet list or too many sheets.")
    seen = set()
    for entry in ids:
        title = "Info sheet"
        try:
            uid = _identifier(entry)
            if uid in seen:
                raise ValueError("Duplicate Prism Info sheet identifier.")
            seen.add(uid)
            sheet = _json_object(archive, f"info/{uid}/sheet.json")
            if sheet.get("@class") != "InfoSheet" or sheet.get("uid") != uid:
                raise ValueError("Invalid Prism Info sheet identity.")
            title = _zip_info_text(sheet.get("title") or "Info sheet")
            fields = sheet.get("constants", [])
            if not isinstance(fields, list) or len(fields) > MAX_INFO_FIELDS:
                raise ValueError("Invalid Prism Info constant list.")
            pairs = [(_zip_info_text(row["name"]), _zip_info_text(row["value"])) for row in fields]
            target.append(InfoSheet(title, tuple(pairs), _zip_info_text(sheet.get("notesText", ""))))
        except (KeyError, TypeError, ValueError):
            skipped.append(title)


def _prism_zip(path, restore=False, info_sheets=None):
    tables, skipped, cells = {}, [], 0
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 25_000 or sum(member.file_size for member in members) > 4 * MAX_ENTRY:
                raise ValueError("Prism project exceeds the decompressed size or entry limit.")
            names = {member.filename for member in members}
            if len(names) != len(members):
                raise ValueError("Prism project contains duplicate archive entries.")
            document = _json_object(archive, "document.json")
            sheets = document.get("sheets")
            ids = sheets.get("data", []) if isinstance(sheets, dict) else None
            if not isinstance(ids, list) or len(ids) > 256:
                raise ValueError("Invalid Prism data sheet list or too many sheets.")
            seen = set()
            sources = {}
            for uid in ids:
                uid = _identifier(uid)
                if uid in seen:
                    raise ValueError("Prism document contains a duplicate data sheet identifier.")
                seen.add(uid)
                sheet = _json_object(archive, f"data/sheets/{uid}/sheet.json")
                title = sheet.get("title") or uid
                table = sheet.get("table")
                if not isinstance(title, str) or not isinstance(table, dict):
                    raise ValueError("Invalid Prism data sheet metadata.")
                try:
                    frame = _zip_table(archive, names, table, MAX_CELLS - cells)
                except (KeyError, TypeError, ValueError, csv.Error) as error:
                    raise ValueError(f"{title}: {error}") from error
                if frame is None:
                    skipped.append(title)
                    continue
                cells += frame.size
                _store_table(tables, title, frame)
                sources[uid] = frame
            if restore and tables:
                from .prism_restore import restore_sheets

                try:
                    restore_sheets(archive, names, sheets, sources, tables, cells)
                except (TypeError, ValueError):
                    next(iter(tables.values())).attrs.setdefault("import_warnings", []).append(
                        "Some saved Prism sheet metadata could not be read.")
            if info_sheets is not None:
                _zip_info(archive, sheets.get("info", []), info_sheets, skipped)
    except (BadZipFile, RuntimeError, KeyError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Invalid or unreadable Prism archive: {error}") from error
    return _finish(tables, skipped, info_sheets)


def _xml_text(element):
    return "".join(element.itertext()) if element is not None else ""


def _xml_tables(root, ns):
    elements = root.findall(ns + "Table")
    if len(elements) > 256:
        raise ValueError("Project contains too many data sheets.")
    order = {}
    for ref in root.findall(f"{ns}TableSequence/{ns}Ref"):
        order.setdefault(ref.get("ID"), len(order))
    return sorted(elements, key=lambda table: order.get(table.get("ID"), len(order)))


def _xml_column(table, column, ns, role, fallback):
    subs = column.findall(ns + "Subcolumn")
    if not subs or (role == "RowTitlesColumn" and not any(sub.findall(ns + "d") for sub in subs)):
        return []
    title = _xml_text(column.find(ns + "Title")) or fallback
    yformat, xformat = table.get("YFormat"), table.get("XFormat")
    labels = _Y_SUMMARY.get(yformat) if role == "YColumn" else None
    if role == "XColumn" and xformat == "error":
        labels = ("Value", "Error")
    if labels is not None and len(subs) != len(labels):
        raise ValueError(f"{title}: summary subcolumns do not match the declared format.")
    mv_type = column.get("MVType", "").split("|")[-1].lower()
    text = (role in {"RowTitlesColumn", "XAdvancedColumn"} or mv_type in {"label", "categorical", "text"}
            or (role == "YColumn" and yformat == "text") or (role == "XColumn" and xformat == "text"))
    result = []
    for i, sub in enumerate(subs):
        if role == "XAdvancedColumn":
            name = f"{title} [{xformat.title()}]" if len(subs) == 1 else f"{title} [{xformat.title()} {i + 1}]"
        elif labels:
            name = f"{title} [{labels[i]}]"
        else:
            name = title if len(subs) == 1 else f"{title} [{i + 1}]"
        values, excluded = [], []
        for index, cell in enumerate(sub.findall(ns + "d")):
            values.append(_xml_text(cell))
            if cell.get("Excluded", "").lower() in {"1", "true", "yes"}:
                excluded.append(index)
        result.append((name, "text" if text else None, values, excluded))
    return result


def _xml_info(root, ns, target, skipped):
    elements = root.findall(ns + "Info")
    if len(elements) > MAX_INFO_SHEETS:
        raise ValueError("Project contains too many Info sheets.")
    order = {}
    for ref in root.findall(f"{ns}InfoSequence/{ns}Ref"):
        order.setdefault(ref.get("ID"), len(order))
    for element in sorted(elements, key=lambda sheet: order.get(sheet.get("ID"), len(order))):
        title = _xml_text(element.find(ns + "Title")) or element.get("ID") or "Info sheet"
        fields = element.findall(ns + "Constant")
        try:
            if len(fields) > MAX_INFO_FIELDS:
                raise ValueError("Prism Info sheet contains too many constants.")
            pairs = tuple((_xml_text(row.find(ns + "Name")), _xml_text(row.find(ns + "Value"))) for row in fields)
            notes = _xml_text(element.find(ns + "Notes"))
            target.append(InfoSheet(title, pairs, notes))
        except ValueError:
            skipped.append(title)


def _prism_xml(path, info_sheets=None, *, restore=False):
    data = path.read_bytes()
    if b"<!DOCTYPE" in data.replace(b"\0", b"").upper():
        raise ValueError("Prism XML files containing a DOCTYPE are unsupported.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("Invalid Prism XML.") from error
    if root.tag == _XSLT_NS + "stylesheet":
        # Installer tutorial XML may be wrapped for browser display. Read
        # the literal data document and leave the stylesheet inert.
        root = root.find(_PRISM_NS + "GraphPadPrismFile")
    if root is None or root.tag not in {"GraphPadPrismFile", _PRISM_NS + "GraphPadPrismFile"}:
        raise ValueError("Unrecognized Prism XML document.")
    ns = root.tag[:-len("GraphPadPrismFile")]
    tables, skipped, total_cells = {}, [], 0
    xml_sources = {}
    xml_tables = _xml_tables(root, ns)
    table_ids = Counter(table.get("ID") for table in xml_tables) if restore else {}
    for table in xml_tables:
        title = _xml_text(table.find(ns + "Title")) or table.get("ID") or "Data"
        if table.get("TableType") == "Result":
            continue
        columns, x_spans, y_spans = [], [], []
        table_format = table.get("ExtTableType") or table.get("TableType", "column")
        xformat = table.get("XFormat")
        for column in table:
            role = column.tag.removeprefix(ns)
            if role == "RowTitlesColumn":
                fallback = "Row title"
            elif role == "XColumn" or (role == "XAdvancedColumn" and xformat in {"date", "startenddate", "time"}):
                fallback = "X"
            elif role == "YColumn":
                fallback = f"Y{len(columns) + 1}"
            else:
                continue
            start = len(columns)
            columns.extend(_xml_column(table, column, ns, role, fallback))
            if role == "XColumn" and len(columns) > start:
                x_spans.append((start, len(columns)))
            if role == "YColumn" and len(columns) > start:
                y_spans.append((start, len(columns), _xml_text(column.find(ns + "Title")) or fallback))
        if not columns:
            skipped.append(title)
            continue
        names, kinds, values, excluded = zip(*columns, strict=True)
        total_cells += max(map(len, values)) * len(columns)
        if len(columns) > MAX_COLUMNS or total_cells > MAX_CELLS:
            raise ValueError("Prism XML tables exceed the size limit.")
        frame = _table(names, [list(row) for row in zip_longest(*values)], kinds, decimal_mark=",")
        frame.attrs["excluded"] = sorted((row, col) for col, rows in enumerate(excluded) for row in rows)
        frame.attrs["table_format"] = table_format
        if table_format.casefold() == "nested":
            frame.attrs["worksheet_roles"] = {"x": [], "y": [frame.columns[a:b].tolist() for a, b, _ in y_spans]}
        _store_table(tables, title, frame)
        if (restore and table_format.casefold() == "xy" and xformat == "numbers" and table.get("YFormat") == "replicates"
                and len(x_spans) == 1 and table_ids[table.get("ID")] == 1
                and (match := re.fullmatch(r"Table(0|[1-9][0-9]{0,4})", table.get("ID", "")))):
            start, stop = x_spans[0]
            if stop - start == 1:
                groups = [(label, frame.columns[a:b].tolist()) for a, b, label in y_spans]
                xml_sources[int(match[1])] = frame, frame.columns[start], groups
    if xml_sources:
        from .prism_xml_xy import attach_xml_error_graphs

        attach_xml_error_graphs(root, ns, xml_sources)
    elif restore and not xml_tables:
        from .prism_xml_generated import recover_generated_graphs
        from .prism_xml_xy import template_data

        payload = template_data(root, ns)
        if payload is not None:
            for title, frame in recover_generated_graphs(payload):
                _store_table(tables, title, frame)
    if info_sheets is not None:
        _xml_info(root, ns, info_sheets, skipped)
    return _finish(tables, skipped, info_sheets)


def load_prism(path, *, restore=False, info_sheets=None):
    with path.open("rb") as stream:
        header = stream.read(256)
    if header.startswith(b"PK") or is_zipfile(path):
        return _prism_zip(path, restore=restore, info_sheets=info_sheets)
    if path.stat().st_size > MAX_ENTRY:
        raise ValueError("Prism input file exceeds 32 MiB.")
    if header.startswith(b"PCFFGRA4"):
        from .prism_binary import load_prism_binary

        return load_prism_binary(path, restore=restore, info_sheets=info_sheets)
    xml_header = header.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"<", b"\xff\xfe", b"\xfe\xff"))
    if header.startswith(b"PCFF") or (path.suffix.lower() in {".pzf", ".pzt"} and not xml_header):
        raise ValueError("This Prism binary project is unsupported. Save a copy as .prism or .pzfx in Prism.")
    return _prism_xml(path, info_sheets=info_sheets, restore=restore)
