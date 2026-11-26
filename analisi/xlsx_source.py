"""One sheet of an .xlsx workbook as the source of a linked worksheet (``analisi.source_link``).

The workbook is read from the bytes that ``source_link.read_file`` has just digested, so the version compared is
exactly the version whose SHA-256 the link confirms. It is opened read-only with the values Excel stored for its
formulas (``data_only``): nothing is evaluated and links to other workbooks are never followed or refreshed.

The sheet is found by its exact name, never by its place in the workbook, so moving it among the other sheets
changes nothing. A sheet renamed or removed is reported with the names the workbook has now; the person then
chooses another sheet explicitly.

Cells arrive as in File → Import Excel workbook… (``analisi.xlsx_exchange``): numbers stay numbers (integers and
decimals compare equal), text stays literal (``007`` stays text), an empty cell is a missing value, booleans are
logical values (TRUE/FALSE), dates and times become ISO text (``2026-11-26``, ``2026-11-26T08:30:00``, ``08:30:00``).
A linked cell that holds a formula without a stored result, or an Excel error value (``#DIV/0!``…), blocks the
update with the sheet and the cell: its value is unknown, and an empty cell would silently change the data.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from zipfile import BadZipFile, ZipFile

import pandas as pd

from .data import MAX_ENTRY
from .xlsx_exchange import (MAX_EXCEL_ROWS, MAX_SHEET_NAME, MAX_UNPACKED, ExchangeCancelled, _build, _column_index,
                            _excel_length, _header_text, _open, _scan_member, _sheet_members, _sheet_rows)

WORKBOOK = "xlsx"
SUFFIXES = frozenset({".xlsx"})
_REFERENCE = re.compile(r"([A-Z]{1,3})(\d+)")


class MissingSheet(ValueError):
    """The workbook has no worksheet with the linked name (renamed, removed, or now a chart sheet)."""

    def __init__(self, sheet, sheets):
        super().__init__(f'The workbook has no sheet named "{sheet}".')
        self.sheet, self.sheets = sheet, tuple(sheets)


@dataclass(frozen=True)
class WorkbookOptions:
    """How a linked worksheet reads its workbook: the exact sheet name, and the header row (1-based) or ``None``
    to read the columns by position (A, B, … become Column 1, Column 2, …)."""
    sheet: str
    header: int | None = 1

    @property
    def mark_excluded(self):  # A workbook has no exclusion mark: cells keep the exclusions of the worksheet.
        return False


def is_workbook(path):
    return str(path).lower().endswith(".xlsx")


def valid_sheet_name(name):
    return isinstance(name, str) and 0 < _excel_length(name) <= MAX_SHEET_NAME and "\x00" not in name


def valid_header(header):
    return header is None or (type(header) is int and 1 <= header <= MAX_EXCEL_ROWS)


class _Stop:
    """``source_link`` passes a callable; ``xlsx_exchange`` asks ``is_set()``."""

    def __init__(self, cancel):
        self.cancel = cancel

    def is_set(self):
        return self.cancel is not None and bool(self.cancel())


def _archive(content):
    """The zip of the workbook, refused before openpyxl sees it when it is not a plain .xlsx within the limits."""
    if len(content) > MAX_ENTRY:
        raise ValueError("The workbook exceeds 32 MiB.")
    try:
        archive = ZipFile(BytesIO(content))
        if sum(member.file_size for member in archive.infolist()) > MAX_UNPACKED:
            raise ValueError("The workbook exceeds the decompressed size limit.")
        if "xl/vbaProject.bin" in archive.namelist():
            raise ValueError("Macro-enabled workbooks are not supported. Save it as .xlsx without macros.")
    except BadZipFile as error:
        raise ValueError("The file is not a valid .xlsx workbook.") from error
    return archive


@dataclass
class WorkbookTable:
    """The linked sheet as Trama imports it, with what ``source_link`` needs to find its columns again."""
    sheet: str
    sheets: tuple  # Names of the worksheets, in workbook order.
    header: list  # Header texts (stripped) of every column, empty without a header row.
    width: int
    frame: pd.DataFrame  # Every column of the sheet, named as the import names them.
    blocked: list  # (row, column, reference, "formula" | "error"), 1-based, cells whose value is unknown.
    external: list  # References of formulas linked to other workbooks: their stored result is used.

    def table(self, positions):
        """The columns at ``positions`` (0-based), in that order."""
        frame = self.frame.iloc[:, list(positions)].copy()
        frame.attrs = {}
        return frame

    def cell_problems(self, positions):
        """Why the linked cells cannot be read: formulas without a stored result and error values in the linked
        columns, from the header row down (rows above the header are not read)."""
        from .source_link import _shown, message

        wanted = {position + 1 for position in positions}
        first = self.header_row or 1
        formulas = [reference for row, column, reference, kind in self.blocked
                    if kind == "formula" and column in wanted and row >= first]
        errors = [reference for row, column, reference, kind in self.blocked
                  if kind == "error" and column in wanted and row >= first]
        problems = []
        if formulas:
            problems.append(message("Sheet {sheet}, cell(s) {cells}: formulas without a stored result. Open the "
                                    "workbook in Excel, let it calculate, save it and update again.",
                                    sheet=self.sheet, cells=_shown(formulas)))
        if errors:
            problems.append(message("Sheet {sheet}, cell(s) {cells}: Excel error values. Correct them in the "
                                    "workbook and update again.", sheet=self.sheet, cells=_shown(errors)))
        return problems

    header_row: int | None = None


def _cells(references, kind):
    found = []
    for reference in references:
        if match := _REFERENCE.fullmatch(reference):
            found.append((int(match[2]), _column_index(match[1]), reference, kind))
    return found


def sheet_names(content):
    """Worksheet names of the workbook in ``content``, in workbook order (chart sheets left out)."""
    _archive(content)
    workbook = _open(BytesIO(content))
    try:
        return tuple(sheet.title for sheet in workbook.worksheets)
    finally:
        workbook.close()


@dataclass
class LoadedSheet:
    """The rows of one sheet, read once: the import dialog builds the table again for every header row."""
    sheet: str
    sheets: tuple
    rows: list
    blocked: list
    external: list

    def table(self, header):
        """The ``WorkbookTable`` with header row ``header`` (1-based) or ``None`` (columns by position)."""
        if not valid_header(header):
            raise ValueError("Choose a header row from 1 up, or no header.")
        hidden = [(row, column) for row, column, _, _ in self.blocked]
        frame = _build(self.sheet, self.rows, header, uncached=hidden)
        width = len(frame.columns)
        if header is not None:
            head = [_header_text(value) for value in self.rows[header - 1]]
            head += [None] * (width - len(head))
            names = ["" if value is None else str(value).strip() for value in head[:width]]
        else:
            names = []
        return WorkbookTable(self.sheet, self.sheets, names, width, frame, self.blocked, self.external, header)


def load_sheet(content, sheet_name, *, cancel=None):
    """Read the rows of the sheet ``sheet_name`` of the workbook in ``content`` (bytes).

    Raises ``MissingSheet`` when the workbook has no worksheet of that name, ``ExchangeCancelled`` when
    ``cancel()`` turns true, and ``ValueError`` when the workbook cannot be read or exceeds the limits."""
    if not valid_sheet_name(sheet_name):
        raise ValueError("Invalid link to a source file.")
    stop = _Stop(cancel)
    archive = _archive(content)
    try:
        workbook = _open(BytesIO(content))
        try:
            sheets = tuple(sheet.title for sheet in workbook.worksheets)
            if sheet_name not in sheets:
                raise MissingSheet(sheet_name, sheets)
            try:
                rows, _ = _sheet_rows(workbook[sheet_name], cancel=stop)
            except (ValueError, ExchangeCancelled):
                raise
            except Exception as error:  # noqa: BLE001 - openpyxl raises many kinds on a damaged sheet.
                raise ValueError(f'Worksheet "{sheet_name}" could not be read.') from error
        finally:
            workbook.close()
        if stop.is_set():
            raise ExchangeCancelled("Cancelled.")
        try:
            uncached, errors, external = _scan_member(archive, _sheet_members(archive).get(sheet_name), cancel=stop)
        except ExchangeCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - damaged XML
            raise ValueError(f'Worksheet "{sheet_name}" could not be read.') from error
    finally:
        archive.close()
    return LoadedSheet(sheet_name, sheets, rows, _cells(uncached, "formula") + _cells(errors, "error"),
                       list(external))


def read_sheet(content, options, *, cancel=None):
    """``load_sheet`` then the table with ``options.header``: what an update compares."""
    if not valid_header(options.header):
        raise ValueError("Invalid link to a source file.")
    return load_sheet(content, options.sheet, cancel=cancel).table(options.header)
