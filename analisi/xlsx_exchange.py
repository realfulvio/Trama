"""Excel workbooks in and out of Trama: choose sheets and header rows on import, write several tables on export.

The pure API never opens a dialog and needs no Qt application:

* ``inspect_workbook(path)`` lists every sheet in workbook order with its literal name, state (``visible``,
  ``hidden``, ``veryHidden``), indicative size and whether it can be imported;
* ``read_workbook(path, {name: header_row or None})`` returns ``{name: DataFrame}`` in the order asked;
* ``write_workbook(path, [(name, frame), ...], overwrite=False)`` writes, verifies and publishes atomically and
  returns the Excel sheet names written.

Reading uses the values Excel stored for formulas (``data_only``) and never follows external links; nothing is
evaluated. Text stays literal, numbers stay numbers, booleans stay booleans, dates and times become ISO text.
Writing stores text as string cells whatever its first character, so no formula ever reaches the file.

The legacy reader (``analisi.data.load_tables``) is untouched: it still opens every sheet with the first row
as header. Both share the header normalisation of ``analisi.data._headers``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .data import MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, _headers

STATES = ("visible", "hidden", "veryHidden")
MAX_SHEET_NAME = 31  # UTF-16 code units, as Excel counts them.
RESERVED_SHEET_NAMES = ("History",)  # Excel keeps it for the change history of shared workbooks.
MAX_EXCEL_ROWS = 1_048_576
MAX_EXCEL_COLUMNS = 16_384
MAX_TEXT = 32_767
MAX_INTEGER_DIGITS = 15  # Excel keeps 15 significant digits: longer integers would change silently.
MAX_UNPACKED = 4 * MAX_ENTRY
_NAME_FORBIDDEN = re.compile(r"[\[\]:*?/\\\x00-\x1f\x7f]")
_ILLEGAL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FORMULA_SCAN = re.compile(rb"<(?:\w+:)?f[\s>/]|\st=\"e\"")
_EXTERNAL_REFERENCE = re.compile(r"\[\d+\]")
_CELL_REFERENCE = re.compile(r"([A-Z]{1,3})(\d+)")
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_ERROR_CODES = frozenset({"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA",
                          "#SPILL!", "#CALC!", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!",
                          "#EXTERNAL!", "#PYTHON!"})


class ExchangeCancelled(Exception):
    """The person cancelled an import or an export before anything changed."""


@dataclass(frozen=True)
class SheetInfo:
    """One sheet of a workbook. ``rows`` and ``columns`` are indicative: Excel's stored dimension."""
    name: str
    state: str
    kind: str = "worksheet"  # "worksheet" or "chartsheet"
    rows: int = 0
    columns: int = 0
    empty: bool = False

    @property
    def importable(self):
        return self.kind == "worksheet" and not self.empty


@dataclass
class SheetPreview:
    """The top-left corner of a sheet with Excel coordinates, and what Trama would make of it.

    ``grid`` holds rows ``first_row``… of converted values (``None`` = empty) for the first ``len(letters)``
    columns. ``names`` are the effective Trama column names (all of them when the width is known). ``error``
    explains why the choice cannot be imported; ``warnings`` lists cells in the preview that need attention.
    """
    sheet: str
    header: int | None
    first_row: int
    letters: list[str]
    grid: list[list]
    names: list[str]
    width: int
    rows_known: int
    complete: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


# == helpers =========================================================================================
def column_letter(index):
    """1 → A, 27 → AA."""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _column_index(letters):
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - 64
    return number


def _excel_length(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _excel_cut(text, units):
    """The longest prefix of ``text`` that fits in ``units`` UTF-16 code units (never half a pair)."""
    while _excel_length(text) > units:
        text = text[:-1]
    return text


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ExchangeCancelled("Cancelled.")


def _summary(sheet, coordinates, limit=6):
    shown = ", ".join(coordinates[:limit])
    more = f" (+{len(coordinates) - limit})" if len(coordinates) > limit else ""
    return f"{sheet}: {shown}{more}"


def _check_source(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsm", ".xltm", ".xlsb", ".xls", ".xlt"}:
        raise ValueError("Only .xlsx workbooks can be read: macro-enabled and binary Excel formats are not supported.")
    if suffix != ".xlsx":
        raise ValueError("Choose an .xlsx workbook.")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ValueError(f"The workbook could not be read: {error}") from error
    if size > MAX_ENTRY:
        raise ValueError("The workbook exceeds 32 MiB.")
    try:
        with ZipFile(path) as archive:
            if sum(member.file_size for member in archive.infolist()) > MAX_UNPACKED:
                raise ValueError("The workbook exceeds the decompressed size limit.")
            if "xl/vbaProject.bin" in archive.namelist():
                raise ValueError("Macro-enabled workbooks are not supported. Save it as .xlsx without macros.")
    except BadZipFile as error:
        raise ValueError("The file is not a valid .xlsx workbook.") from error
    except OSError as error:
        raise ValueError(f"The workbook could not be read: {error}") from error
    return path


_OPEN_LOCK = threading.Lock()


def _sized_sheet_class():
    """openpyxl's read-only sheet, except that a sheet without a ``<dimension>`` element (files written in
    streaming mode, our own exports among them) is not parsed in full just to learn that it has none: the
    search stops where the cells begin. The result is the same (no stored size); only the time changes."""
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    from openpyxl.worksheet.dimensions import SheetDimension

    class SizedSheet(ReadOnlyWorksheet):
        def _get_size(self):
            with self._get_source() as source:
                for event, element in ET.iterparse(source, events=("start", "end")):
                    tag = element.tag.rsplit("}", 1)[-1]
                    if event == "start" and tag == "sheetData":
                        return
                    if event == "end" and tag == "dimension":
                        boundaries = SheetDimension.from_tree(element).boundaries
                        if boundaries is not None:
                            self._min_column, self._min_row, self._max_column, self._max_row = boundaries
                        return

    return SizedSheet


def _open(path):
    import openpyxl.reader.excel as reader
    from openpyxl import load_workbook

    try:
        with _OPEN_LOCK:  # The swap is scoped to this call; other loads see the original class again.
            original = reader.ReadOnlyWorksheet
            reader.ReadOnlyWorksheet = _sized_sheet_class()
            try:
                return load_workbook(path, read_only=True, data_only=True, keep_links=False)
            finally:
                reader.ReadOnlyWorksheet = original
    except ValueError:
        raise
    except Exception as error:  # openpyxl raises KeyError, InvalidFileException, XML errors…
        raise ValueError("The file is not a valid .xlsx workbook.") from error


def _iso(value, *, date_only=False):
    if isinstance(value, _dt.datetime):
        if date_only:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        seconds = value.total_seconds()
        sign = "-" if seconds < 0 else ""
        seconds = abs(seconds)
        hours, rest = divmod(seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        whole = int(seconds)
        fraction = f"{seconds - whole:.6f}"[1:].rstrip("0").rstrip(".")
        return f"{sign}{int(hours):02d}:{int(minutes):02d}:{whole:02d}{fraction}"
    return value


def _is_midnight(value):
    return isinstance(value, _dt.datetime) and value.time() == _dt.time(0)


def _header_text(value):
    """A header cell as text: dates in ISO form, everything else as written."""
    if value is None:
        return None
    if isinstance(value, (_dt.date, _dt.time, _dt.timedelta)):
        return _iso(value, date_only=_is_midnight(value))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _column(values):
    """One imported column: numbers, booleans, text or a literal mix, with missing values kept."""
    present = [value for value in values if value is not None]
    if any(isinstance(value, (_dt.date, _dt.time, _dt.timedelta)) for value in present):
        date_only = all(_is_midnight(value) for value in present if isinstance(value, _dt.datetime))
        values = [_iso(value, date_only=date_only) for value in values]
        present = [value for value in values if value is not None]
    if not present:
        return pd.array([pd.NA] * len(values), dtype="Float64")
    kinds = {bool if isinstance(value, bool) else (str if isinstance(value, str) else float) for value in present}
    if kinds == {bool}:
        return pd.array(values, dtype="boolean")
    if kinds == {str}:
        return pd.array(values, dtype="string")
    if kinds == {float}:
        return pd.to_numeric(pd.Series(values, dtype=object), dtype_backend="numpy_nullable").array
    return pd.array([pd.NA if value is None else value for value in values], dtype=object)


# == workbook structure ==============================================================================
def _sheet_members(archive):
    """Sheet name → worksheet XML member, from workbook.xml and its relationships."""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {}
    for node in relations:
        target = node.get("Target", "")
        if target.startswith("/"):
            target = target[1:]
        elif not target.startswith("xl/"):
            target = "xl/" + target
        targets[node.get("Id")] = os.path.normpath(target).replace("\\", "/")
    members = {}
    relation = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for node in workbook.iter(f"{_SHEET_NS}sheet"):
        members[node.get("name")] = targets.get(node.get(relation))
    return members


def _scan_member(archive, member, *, cancel=None):
    """Coordinates of formulas without a stored result, error cells and external-link formulas.

    Only parsed when the raw XML contains formulas or error cells at all, so plain sheets cost one quick pass
    over their bytes."""
    uncached, errors, external = [], [], []
    if member is None or member not in archive.namelist():
        return uncached, errors, external
    found, tail = False, b""
    with archive.open(member) as handle:
        while chunk := handle.read(1 << 20):
            _check_cancel(cancel)
            if _FORMULA_SCAN.search(tail + chunk):
                found = True
                break
            tail = chunk[-16:]
    if not found:
        return uncached, errors, external
    with archive.open(member) as handle:
        row_number = column_number = 0
        for event, node in ET.iterparse(handle, events=("start", "end")):
            tag = node.tag.rsplit("}", 1)[-1]
            if event == "start":
                if tag == "row":
                    row_number = int(node.get("r") or row_number + 1)
                    if row_number % 256 == 0:
                        _check_cancel(cancel)
                    column_number = 0
                continue
            if tag != "c":
                if tag == "row":
                    node.clear()
                continue
            reference = node.get("r")
            if reference and (match := _CELL_REFERENCE.fullmatch(reference)):
                column_number = _column_index(match[1])
            else:
                column_number += 1
                reference = f"{column_letter(column_number)}{row_number}"
            formula = node.find(f"{_SHEET_NS}f")
            stored = node.find(f"{_SHEET_NS}v")
            if node.get("t") == "e":
                errors.append(reference)
            elif formula is not None and (stored is None or not (stored.text or "")):
                uncached.append(reference)
            if formula is not None and formula.text and _EXTERNAL_REFERENCE.search(formula.text):
                external.append(reference)
            node.clear()
    return uncached, errors, external


def _first_value(sheet):
    for row in sheet.iter_rows(values_only=True):
        if any(value is not None and value != "" for value in row):
            return True
    return False


def inspect_workbook(path):
    """Every sheet in workbook order. A corrupt or unsupported file raises ValueError."""
    path = _check_source(path)
    workbook = _open(path)
    try:
        records = []
        worksheets = {sheet.title for sheet in workbook.worksheets}
        for name in workbook.sheetnames:
            sheet = workbook[name]
            state = getattr(sheet, "sheet_state", "visible") or "visible"
            if name not in worksheets:
                records.append(SheetInfo(name, state, "chartsheet", 0, 0, True))
                continue
            try:
                rows, columns = sheet.max_row or 0, sheet.max_column or 0
                empty = not _first_value(sheet)
            except Exception as error:
                raise ValueError(f'Worksheet "{name}" could not be read.') from error
            records.append(SheetInfo(name, state, "worksheet", rows, columns, empty))
        return records
    finally:
        workbook.close()


# == reading =========================================================================================
def _validate_header(header):
    if header is None:
        return None
    if isinstance(header, bool) or not isinstance(header, (int, np.integer)) or header < 1:
        raise ValueError("Choose a header row from 1 up, or no header.")
    return int(header)


def _clean(value):
    return None if value == "" else value


def _sheet_rows(sheet, *, limit=None, cancel=None):
    """Rows of converted values (empty strings → None), trailing empty rows dropped, sizes checked as read.

    With ``limit`` it stops after that many rows and reports whether the sheet ended."""
    rows, last = [], 0
    width = 0
    for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if number % 4096 == 0:
            _check_cancel(cancel)
        values = [_clean(value) for value in row]
        while values and values[-1] is None:
            values.pop()
        rows.append(values)
        if values:
            last = number
            width = max(width, len(values))
            if width > MAX_COLUMNS:
                raise ValueError(f'Worksheet "{sheet.title}" has more than {MAX_COLUMNS} columns.')
            if width * last > MAX_CELLS:
                raise ValueError(f'Worksheet "{sheet.title}" exceeds the table size limit.')
        elif number - last > MAX_CELLS:
            break  # A long run of empty rows: the rest of the sheet cannot hold data within the limits.
        if limit is not None and number >= limit:
            return rows[:last] if last else [], False
    return rows[:last], True


def _build(name, rows, header, *, uncached=(), errors=()):
    """The DataFrame for one sheet from its rows (1-based ``header`` or ``None``)."""
    if not rows:
        raise ValueError(f'Worksheet "{name}" has no values to import.')
    if header is not None and header > len(rows):
        raise ValueError(f'Worksheet "{name}": the header row {header} is past the last row with values '
                         f'({len(rows)}).')
    start = 0 if header is None else header
    body = rows[start:]
    width = max([len(row) for row in body] + [len(rows[header - 1]) if header else 0, 1])
    if header is None:
        names = _headers([None] * width)
    else:
        head = [_header_text(value) for value in rows[header - 1]]
        names = _headers(head + [None] * (width - len(head)))
    missing = {(row, column) for row, column in (*uncached, *errors)}
    columns = []
    for index in range(width):
        values = []
        for offset, row in enumerate(body):
            value = row[index] if index < len(row) else None
            if missing and (start + offset + 1, index + 1) in missing:
                value = None
            values.append(value)
        columns.append(_column(values))
    frame = pd.DataFrame(dict(zip(range(width), columns)))
    frame.columns = names
    return frame


def _positions(coordinates):
    found = []
    for reference in coordinates:
        match = _CELL_REFERENCE.fullmatch(reference)
        if match:
            found.append((int(match[2]), _column_index(match[1])))
    return found


class WorkbookReader:
    """An open workbook for the import dialog: inspection, previews and the final read share one handle.

    Use as a context manager; ``close`` releases the file."""

    def __init__(self, path):
        self.path = _check_source(path)
        self.workbook = _open(self.path)
        try:
            self.archive = ZipFile(self.path)
            self.members = _sheet_members(self.archive)
        except Exception as error:
            self.workbook.close()
            raise ValueError("The file is not a valid .xlsx workbook.") from error
        self._scans = {}
        self._sheets = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.workbook.close()
        self.archive.close()

    def sheets(self):
        if self._sheets is None:
            records = []
            worksheets = {sheet.title for sheet in self.workbook.worksheets}
            for name in self.workbook.sheetnames:
                sheet = self.workbook[name]
                state = getattr(sheet, "sheet_state", "visible") or "visible"
                if name not in worksheets:
                    records.append(SheetInfo(name, state, "chartsheet", 0, 0, True))
                    continue
                try:
                    empty = not _first_value(sheet)
                    rows, columns = sheet.max_row or 0, sheet.max_column or 0
                except Exception as error:
                    raise ValueError(f'Worksheet "{name}" could not be read.') from error
                records.append(SheetInfo(name, state, "worksheet", rows, columns, empty))
            self._sheets = records
        return self._sheets

    def _sheet(self, name):
        info = next((item for item in self.sheets() if item.name == name), None)
        if info is None:
            raise ValueError(f'The workbook has no sheet named "{name}".')
        if info.kind != "worksheet":
            raise ValueError(f'"{name}" is a chart sheet and holds no cells to import.')
        if info.empty:
            raise ValueError(f'Worksheet "{name}" has no values to import.')
        return self.workbook[name]

    def scan(self, name):
        if name not in self._scans:
            try:
                self._scans[name] = _scan_member(self.archive, self.members.get(name))
            except (ET.ParseError, OSError, ValueError) as error:
                raise ValueError(f'Worksheet "{name}" could not be read.') from error
        return self._scans[name]

    def _notes(self, name, uncached, errors, external):
        notes = []
        if uncached:
            notes.append("Formulas without a stored result stay empty — " + _summary(name, uncached))
        if errors:
            notes.append("Excel error values stay empty — " + _summary(name, errors))
        if external:
            notes.append("Formulas linked to other workbooks keep their stored result — " + _summary(name, external))
        return notes

    def preview(self, name, header=1, *, rows=12, columns=12):
        """The first rows of ``name`` with header row ``header`` (``None`` = no header)."""
        header = _validate_header(header)
        sheet = self._sheet(name)
        wanted = max(rows + (header or 0), 1)
        try:
            grid, complete = _sheet_rows(sheet, limit=wanted)
        except (ValueError, ExchangeCancelled):
            raise
        except Exception as error:
            raise ValueError(f'Worksheet "{name}" could not be read.') from error
        uncached, errors, external = self.scan(name)
        hidden = set(_positions(uncached)) | set(_positions(errors))
        visible_rows = [[None if (number, column) in hidden else value
                         for column, value in enumerate(row, 1)] for number, row in enumerate(grid, 1)]
        width = max([len(row) for row in visible_rows] + [1])
        error = names = None
        try:
            if complete:
                frame = _build(name, grid, header, uncached=_positions(uncached), errors=_positions(errors))
                names = list(frame.columns)
            else:
                if header is not None and header > len(grid):
                    raise ValueError(f'Worksheet "{name}": the header row {header} is past the rows read.')
                head = [_header_text(value) for value in grid[header - 1]] if header else []
                names = _headers(head + [None] * (width - len(head))) if header else _headers([None] * width)
        except ValueError as problem:
            error, names = str(problem), []
        shown = visible_rows[:wanted]
        letters = [column_letter(index) for index in range(1, min(width, columns) + 1)]
        grid_out = [[_iso(row[index], date_only=_is_midnight(row[index])) if index < len(row) else None
                     for index in range(len(letters))] for row in shown]
        return SheetPreview(name, header, 1, letters, grid_out, names, width, len(grid), complete, error,
                            self._notes(name, uncached, errors, external))

    def read(self, selections, *, warnings=None, progress=None, cancel=None):
        """``{name: DataFrame}`` in the order of ``selections``; any problem raises before anything is returned."""
        if not isinstance(selections, dict) or not selections:
            raise ValueError("Choose at least one worksheet to import.")
        plan = [(name, _validate_header(header)) for name, header in selections.items()]
        for name, _ in plan:
            self._sheet(name)
        total = len(plan)
        tables, notes = {}, []
        for done, (name, header) in enumerate(plan):
            _check_cancel(cancel)
            if progress is not None:
                progress(done, total)
            sheet = self.workbook[name]
            try:
                rows, _ = _sheet_rows(sheet, cancel=cancel)
            except (ValueError, ExchangeCancelled):
                raise
            except Exception as error:
                raise ValueError(f'Worksheet "{name}" could not be read.') from error
            uncached, errors, external = self.scan(name)
            _check_cancel(cancel)
            tables[name] = _build(name, rows, header, uncached=_positions(uncached), errors=_positions(errors))
            notes.extend(self._notes(name, uncached, errors, external))
        if progress is not None:
            progress(total, total)
        if warnings is not None:
            warnings.extend(notes)
        return tables


def read_workbook(path, selections, *, warnings=None, progress=None, cancel=None):
    """Read the chosen sheets: ``selections`` maps sheet name → 1-based header row, or ``None`` for no header.

    Returns ``{name: DataFrame}`` in the order of ``selections``. Unknown or empty sheets, header rows past the
    data, invalid options and unreadable files raise ValueError and return nothing. ``warnings`` (a list)
    receives the notes about formulas without stored results, error cells and external links."""
    with WorkbookReader(path) as reader:
        return reader.read(selections, warnings=warnings, progress=progress, cancel=cancel)


# == writing =========================================================================================
def excel_sheet_names(desired):
    """Deterministic Excel names for ``desired``: forbidden characters → ``_``, no edge apostrophes, at most 31
    UTF-16 units, ``Sheet`` when empty, unique ignoring case, ``History`` reserved, collisions ``(2)``, ``(3)``…"""
    used = {name.casefold() for name in RESERVED_SHEET_NAMES}
    result = []
    for name in desired:
        base = _NAME_FORBIDDEN.sub("_", str(name))
        base = base.strip("'")
        base = _excel_cut(base, MAX_SHEET_NAME).strip("'") or "Sheet"
        candidate, number = base, 2
        while candidate.casefold() in used:
            suffix = f" ({number})"
            candidate = _excel_cut(base, MAX_SHEET_NAME - len(suffix)).rstrip("'") + suffix
            number += 1
        used.add(candidate.casefold())
        result.append(candidate)
    return result


def _flat(label):
    if isinstance(label, tuple):
        parts = [_flat(part) for part in label if part is not None and str(part) != ""]
        return " · ".join(parts)
    if label is None:
        return ""
    if isinstance(label, float) and math.isnan(label):
        return ""
    if isinstance(label, (_dt.date, _dt.time, pd.Timestamp)):
        return _value_text(label)
    return str(label)


def materialize_index(frame):
    """A result table with its index as leading columns: level names kept, unnamed levels named
    deterministically (``Row`` for a single level, ``Level 1``, ``Level 2``… otherwise), column labels flattened
    and made unique (``analisi.data._headers``)."""
    index = frame.index
    levels = index.nlevels
    names = []
    for position, level in enumerate(index.names, 1):
        text = _flat(level).strip() if level is not None else ""
        names.append(text or ("Row" if levels == 1 else f"Level {position}"))
    columns = _headers([_flat(label) for label in frame.columns]) if frame.shape[1] else []
    used = {name.casefold() for name in columns}
    for position, name in enumerate(names):
        candidate, number = name, 2
        while candidate.casefold() in used:  # The table's own columns keep their names; index levels give way.
            candidate, number = f"{name} ({number})", number + 1
        used.add(candidate.casefold())
        names[position] = candidate
    parts = [pd.Series(index.get_level_values(position)).reset_index(drop=True) for position in range(levels)]
    parts += [frame.iloc[:, position].reset_index(drop=True) for position in range(frame.shape[1])]
    out = pd.concat(parts, axis=1, ignore_index=True)
    out.columns = names + columns
    return out


def _value_text(value):
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None and value.time() == _dt.time(0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, _dt.timedelta)):
        return _iso(pd.Timedelta(value).to_pytimedelta())
    return str(value)


def _excel_value(value):
    """A Python value ready for a cell, or a ValueError reason (str) when it cannot be written faithfully."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None, None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int):
        if abs(value) >= 10 ** MAX_INTEGER_DIGITS:
            return None, f"the integer {value} has more than {MAX_INTEGER_DIGITS} digits and Excel would round it"
        return value, None
    if isinstance(value, float):
        if math.isnan(value):
            return None, None
        if math.isinf(value):
            return None, "infinite values cannot be stored in Excel"
        return value, None
    if isinstance(value, (pd.Timestamp, _dt.date, _dt.time, pd.Timedelta, _dt.timedelta)):
        value = _value_text(value)
    elif not isinstance(value, str):
        if isinstance(value, (complex, bytes)) or pd.api.types.is_scalar(value):
            value = str(value)
        else:
            return None, f"a {type(value).__name__} value cannot be stored in a cell"
    return _text(value)


def _text(value):
    if len(value) > MAX_TEXT:
        return None, f"a text of {len(value):,} characters exceeds Excel's {MAX_TEXT:,}"
    if _ILLEGAL_TEXT.search(value):
        return None, "the text contains control characters Excel cannot store"
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None, "the text contains characters that cannot be written"
    return value, None


@dataclass
class _Sheet:
    title: str
    excel: str
    header: list
    columns: list  # Lists of converted Python values, one per column.
    rows: int


def _prepare_columns(title, excel, frame, cancel=None):
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f'"{title}" is not a table.')
    if frame.shape[0] + 1 > MAX_EXCEL_ROWS:
        raise ValueError(f'"{title}" has {frame.shape[0]:,} rows: an Excel sheet holds at most '
                         f'{MAX_EXCEL_ROWS - 1:,} below the header. Split or filter the data.')
    if frame.shape[1] > MAX_EXCEL_COLUMNS:
        raise ValueError(f'"{title}" has more columns than an Excel sheet holds ({MAX_EXCEL_COLUMNS:,}).')
    header = []
    for position, label in enumerate(frame.columns, 1):
        text, problem = _text(_flat(label))
        if problem:
            raise ValueError(f'Sheet "{title}" (Excel "{excel}"), header of column {position}: {problem}. '
                             "Correct the data and export again.")
        header.append(text)
    columns = []
    for position in range(frame.shape[1]):
        _check_cancel(cancel)
        series = frame.iloc[:, position]
        dtype = series.dtype
        if pd.api.types.is_float_dtype(dtype):
            array = series.to_numpy(dtype="float64", na_value=np.nan)
            bad = np.flatnonzero(np.isinf(array))
            if bad.size:
                raise ValueError(f'Sheet "{title}" (Excel "{excel}"), row {int(bad[0]) + 2}, column '
                                 f'"{header[position]}": infinite values cannot be stored in Excel. '
                                 "Correct the data and export again.")
            values = [None if value != value else value for value in array.tolist()]
        elif pd.api.types.is_bool_dtype(dtype):
            values = [None if value is pd.NA else bool(value) for value in series.tolist()]
        elif pd.api.types.is_integer_dtype(dtype):
            values = [None if value is pd.NA else int(value) for value in series.tolist()]
            limit = 10 ** MAX_INTEGER_DIGITS
            for row, value in enumerate(values):
                if value is not None and abs(value) >= limit:
                    raise ValueError(f'Sheet "{title}" (Excel "{excel}"), row {row + 2}, column '
                                     f'"{header[position]}": the integer {value} has more than '
                                     f'{MAX_INTEGER_DIGITS} digits and Excel would round it. '
                                     "Store it as text or round it, then export again.")
        else:
            values = []
            for row, value in enumerate(series.tolist()):
                converted, problem = _excel_value(value)
                if problem:
                    raise ValueError(f'Sheet "{title}" (Excel "{excel}"), row {row + 2}, column '
                                     f'"{header[position]}": {problem}. Correct the data and export again.')
                values.append(converted)
        columns.append(values)
    return _Sheet(title, excel, header, columns, frame.shape[0])


def _string_cell(sheet, value):
    from openpyxl.cell import WriteOnlyCell

    cell = WriteOnlyCell(sheet, value=value)
    cell.data_type = "s"  # Literal text even when it starts with "=" or reads like an error code.
    return cell


def _needs_cell(value):
    return isinstance(value, str) and (value[:1] == "=" or value in _ERROR_CODES)


def _write(handle_path, sheets, *, progress=None, cancel=None):
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    try:
        _fill(workbook, sheets, progress, cancel)
        _check_cancel(cancel)
        workbook.save(handle_path)
    except BaseException:
        _abandon(workbook)
        raise


def _abandon(workbook):
    """Close the streaming sheets of a workbook that will not be saved and remove openpyxl's own temporary
    files at once (otherwise they would wait for the end of the program)."""
    for sheet in getattr(workbook, "_sheets", []):
        rows, writer = getattr(sheet, "_rows", None), getattr(sheet, "_writer", None)
        try:
            if rows is not None:
                rows.close()
            if writer is not None:
                writer.close()
                writer.cleanup()
        except Exception:
            pass


def _fill(workbook, sheets, progress, cancel):
    total = sum(sheet.rows for sheet in sheets) or 1
    done = 0
    for item in sheets:
        target = workbook.create_sheet(item.excel)
        width = max(len(item.header), 1)
        reference = f"A1:{column_letter(width)}{item.rows + 1}"
        target.calculate_dimension = lambda reference=reference: reference  # Stored size: readers skip a scan.
        target.append([_string_cell(target, text) for text in item.header])
        columns = item.columns
        for number, row in enumerate(zip(*columns) if columns else (), 1):
            if any(_needs_cell(value) for value in row):
                row = [_string_cell(target, value) if _needs_cell(value) else value for value in row]
            target.append(row)
            if number % 2048 == 0:
                _check_cancel(cancel)
                if progress is not None:
                    progress(done + number, total)
        done += item.rows


def _verify(path, names):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except Exception as error:
        raise ValueError("The exported workbook could not be opened again; nothing was replaced.") from error
    try:
        if workbook.sheetnames != list(names):
            raise ValueError("The exported workbook does not contain the expected sheets; nothing was replaced.")
    finally:
        workbook.close()


class PreparedWorkbook:
    """A written and verified workbook waiting next to its destination. ``publish`` puts it in place;
    ``discard`` removes it. Either way the temporary file is gone afterwards."""

    def __init__(self, path, temporary, names):
        self.path, self.temporary, self.names = Path(path), Path(temporary), list(names)

    def publish(self, *, overwrite=False):
        try:
            if overwrite:
                os.replace(self.temporary, self.path)
            else:
                try:
                    os.link(self.temporary, self.path)  # Atomic and refuses an existing file.
                except FileExistsError:
                    raise
                except OSError:
                    if self.path.exists():
                        raise FileExistsError(str(self.path)) from None
                    os.replace(self.temporary, self.path)
        finally:
            self.discard()
        return self.names

    def discard(self):
        try:
            self.temporary.unlink()
        except FileNotFoundError:
            pass


def prepare_workbook(path, sheets, *, progress=None, cancel=None):
    """Validate ``sheets`` (pairs of desired name and DataFrame), write them to a temporary file next to
    ``path`` and verify it opens. Returns a ``PreparedWorkbook``; nothing at ``path`` changes yet."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Choose a file name ending in .xlsx.")
    entries = list(sheets)
    if not entries:
        raise ValueError("Choose at least one sheet or result table to export.")
    names = excel_sheet_names([name for name, _ in entries])
    prepared = []
    for (title, frame), excel in zip(entries, names):
        _check_cancel(cancel)
        prepared.append(_prepare_columns(str(title), excel, frame, cancel))
    directory = path.parent if str(path.parent) else Path(".")
    handle, temporary = tempfile.mkstemp(prefix=".~trama-", suffix=".xlsx", dir=directory)
    os.close(handle)
    temporary = Path(temporary)
    try:
        _write(temporary, prepared, progress=progress, cancel=cancel)
        _check_cancel(cancel)
        _verify(temporary, names)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return PreparedWorkbook(path, temporary, names)


def write_workbook(path, sheets, *, overwrite=False, progress=None, cancel=None):
    """Write ``sheets`` (pairs of desired name and DataFrame with indexes already materialized) to ``path``.

    Returns the Excel sheet names in order. ``FileExistsError`` when ``path`` exists and ``overwrite`` is false;
    ValueError for data Excel cannot store (with sheet and row). The previous file stays intact on any failure."""
    path = Path(path)
    if not overwrite and path.exists():
        raise FileExistsError(str(path))
    prepared = prepare_workbook(path, sheets, progress=progress, cancel=cancel)
    return prepared.publish(overwrite=overwrite)
