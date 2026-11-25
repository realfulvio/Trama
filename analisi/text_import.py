"""Preview and filter UTF-8 delimited data before worksheet type inference."""
import csv
from dataclasses import dataclass
from io import StringIO

from .data import MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, _table, delimited_reader


TEXT_SUFFIXES = frozenset({".csv", ".tsv", ".txt"})
DELIMITERS = {"Automatic": None, "Comma": ",", "Semicolon": ";", "Tab": "\t"}
DECIMAL_MARKS = {"Automatic": None, "Dot": ".", "Comma": ","}


class ImportCancelled(Exception):
    """Reading or filtering stopped because the person pressed Cancel."""


def read_text_bytes(path):
    """The bytes of a text file (read only, never written) and their UTF-8 text."""
    with path.open("rb") as handle:
        content = handle.read(MAX_ENTRY + 1)
    if len(content) > MAX_ENTRY:
        raise ValueError("Input file exceeds 32 MiB.")
    return content, decode_text(content)


def decode_text(content):
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Save the text file with UTF-8 encoding before importing it.") from error


def read_text_file(path):
    return read_text_bytes(path)[1]


@dataclass(frozen=True)
class ImportOptions:
    header: bool = True
    first_row: int = 1
    last_row: int | None = None
    skip_rows: int = 0
    first_column: int = 1
    last_column: int | None = None
    skip_columns: int = 0
    decimal: str = "Automatic"
    missing_code: str = ""
    mark_excluded: bool = False


@dataclass(frozen=True)
class Selection:
    rows: range
    columns: range


def _positions(total, first, last, skip, axis):
    if skip < 0:
        raise ValueError(f"The number of {axis}s to skip must be zero or more.")
    if not total and first == 1 and last is None:
        return range(0)
    stop = total if last is None else last
    if not 1 <= first <= stop <= total:
        raise ValueError(f"Choose a {axis} range between 1 and {total}.")
    return range(first - 1, stop, skip + 1)


@dataclass
class TextImport:
    records: list[list[str]]
    width: int
    delimiter: str

    @classmethod
    def parse(cls, content, suffix, delimiter="Automatic", *, cancel=None):
        """``cancel``: an optional callable, asked every few thousand records, that stops the reading."""
        if delimiter not in DELIMITERS:
            raise ValueError("Choose a delimiter from the list.")
        reader = delimited_reader(StringIO(content, newline=""), suffix, DELIMITERS[delimiter], strict=True)
        records, width = [], 0
        try:
            for row in reader:
                width = max(width, len(row))
                if max(1, width) * (len(records) + 1) > MAX_CELLS:
                    raise ValueError("The text file exceeds the worksheet size limit.")
                if cancel is not None and not len(records) % 4096 and cancel():
                    raise ImportCancelled
                records.append(row)
        except csv.Error as error:
            raise ValueError("Could not read the delimited file. Check the quoted fields.") from error
        if not width:
            raise ValueError("The file contains no delimited data.")
        return cls(records, width, reader.dialect.delimiter)

    def plan(self, options):
        header = int(options.header)
        rows = _positions(len(self.records) - header, options.first_row, options.last_row, options.skip_rows, "row")
        columns = _positions(self.width, options.first_column, options.last_column, options.skip_columns, "column")
        if len(columns) > MAX_COLUMNS:
            raise ValueError(f"Choose no more than {MAX_COLUMNS} columns.")
        return Selection(range(rows.start + header, rows.stop + header, rows.step), columns)

    def table(self, options, *, limit=None, columns=None, cancel=None):
        """The filtered frame. ``columns`` (0-based file positions) replaces the column range of ``options``:
        a linked worksheet finds its columns by header. ``cancel`` as in ``parse``."""
        selection = self.plan(options)
        rows, columns = selection.rows, selection.columns if columns is None else columns
        if limit is not None:
            rows, columns = rows[:limit[0]], columns[:limit[1]]
        header = self.records[0] if options.header else ()
        names = [header[col] if col < len(header) and header[col].strip() else f"Column {col + 1}"
                 for col in columns]
        if options.decimal not in DECIMAL_MARKS:
            raise ValueError("Choose a decimal separator from the list.")
        decimal_mark = DECIMAL_MARKS[options.decimal] or ("," if self.delimiter == ";" else ".")
        missing = options.missing_code.strip()
        values, excluded = [], []
        for row_index, row in enumerate(rows):
            if cancel is not None and not row_index % 4096 and cancel():
                raise ImportCancelled
            raw = self.records[row]
            record = []
            for column_index, column in enumerate(columns):
                value = raw[column] if column < len(raw) else ""
                marked = options.mark_excluded and value.rstrip().endswith("*")
                if marked:
                    value = value.rstrip()[:-1].rstrip()
                if missing and value.strip() == missing:
                    value = ""
                if marked and value.strip():
                    excluded.append((row_index, column_index))
                record.append(value)
            values.append(record)
        frame = _table(names, values, decimal_mark=decimal_mark)
        if excluded:
            frame.attrs["excluded"] = excluded
        return frame
