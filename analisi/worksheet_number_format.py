"""Display-only number formats for worksheet and result columns, shared by the Tk and Qt grids.

A format changes what a cell shows, never what it stores: formulas, statistics, editing, the clipboard,
CSV/XLSX export and "Use result as data" keep reading the numbers. ``format_number`` returns ``None`` whenever
the renderer that already draws the cell must be kept: Automatic, text, booleans, missing values, infinities.

Formats are saved per column name on data tables and per analysis, result sheet and column position on result
tables (position 0 is the row-title column, which keeps its style).
"""
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain
import math

import numpy as np
import pandas as pd

from .grid_headings import heading_bands
from .i18n import active_language, tr

AUTOMATIC, FIXED, SIGNIFICANT, SCIENTIFIC = "automatic", "fixed", "significant", "scientific"
MODES = (AUTOMATIC, FIXED, SIGNIFICANT, SCIENTIFIC)
DIGIT_RANGES = {FIXED: (0, 12), SIGNIFICANT: (1, 15), SCIENTIFIC: (0, 12)}
DEFAULT_DIGITS = {FIXED: 2, SIGNIFICANT: 4, SCIENTIFIC: 3}
DECIMAL_MARKS = (".", ",")
SAMPLE_VALUE = 1234.5678
_SUFFIX = {FIXED: "f", SIGNIFICANT: "g", SCIENTIFIC: "e"}

# Why a selected column keeps its current style.
TEXT, ROW_TITLES, CODES, COUNTS, METHOD = "text", "row_titles", "codes", "counts", "method"
_PREVIEW_SCAN = 5000
_LISTED_NAMES = 6


def validated_spec(spec):
    """The canonical copy of a format: ``{"mode": m}`` for Automatic, ``{"mode": m, "digits": d}`` otherwise."""
    if not isinstance(spec, Mapping):
        raise ValueError("A number format needs a mode.")
    mode = spec.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Unknown number format mode.")
    if mode == AUTOMATIC:
        if set(spec) != {"mode"}:
            raise ValueError("The automatic number format takes no digits.")
        return {"mode": AUTOMATIC}
    if set(spec) != {"mode", "digits"}:
        raise ValueError("This number format needs a number of digits.")
    digits = spec["digits"]
    low, high = DIGIT_RANGES[mode]
    if type(digits) is not int or not low <= digits <= high:
        raise ValueError(f"Choose between {low} and {high} digits for this number format.")
    return {"mode": mode, "digits": digits}


def number_value(value):
    """The finite real number a cell holds, or ``None`` for text, booleans, missing values and infinities."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return value if math.isfinite(value) else None
    return None


def _render(number, mode, digits, decimal_mark):
    if number == 0:
        number = 0  # A negative zero is shown as zero.
    if mode == FIXED and isinstance(number, int):
        # Whole numbers stay exact beyond 2**53: no detour through a float.
        text = str(number) + ("." + "0" * digits if digits else "")
    else:
        try:
            # Python formats the exact binary value, so ties round to even (2.125 → 2.12, 2.375 → 2.38).
            text = format(number, f".{digits}{_SUFFIX[mode]}")
        except OverflowError:  # An integer beyond the float range: the usual renderer shows it.
            return None
        if mode == FIXED and text.startswith("-") and float(text) == 0:
            text = text[1:]  # -0.004 with two decimals is 0.00, not -0.00.
    return text.replace(".", decimal_mark) if decimal_mark != "." else text


def format_number(value, spec, *, decimal_mark="."):
    """The text a formatted cell shows, or ``None`` when the existing renderer must draw ``value``.

    ``spec`` holds ``mode`` (automatic, fixed, significant or scientific) and, except for Automatic, ``digits``:
    0–12 after the separator for fixed and scientific, 1–15 significant digits. Inconsistent formats raise
    ``ValueError``. Ties round to even, a negative zero is shown as zero and the exponent has a sign and at
    least two digits (``1.250e-04``).
    """
    spec = validated_spec(spec)
    if decimal_mark not in DECIMAL_MARKS:
        raise ValueError("The decimal mark must be a point or a comma.")
    if spec["mode"] == AUTOMATIC:
        return None
    number = number_value(value)
    if number is None:
        return None
    return _render(number, spec["mode"], spec["digits"], decimal_mark)


def formatter(spec, decimal_mark="."):
    """A one-argument ``format_number`` for a format checked once, for grids that format many cells."""
    spec = validated_spec(spec)
    if decimal_mark not in DECIMAL_MARKS:
        raise ValueError("The decimal mark must be a point or a comma.")
    if spec["mode"] == AUTOMATIC:
        return lambda value: None
    mode, digits = spec["mode"], spec["digits"]

    def text(value):
        number = number_value(value)
        return None if number is None else _render(number, mode, digits, decimal_mark)
    return text


def display_decimal_mark():
    """Formatted cells follow the display language: a comma in Italian, a point in English."""
    return "," if active_language() == "it" else "."


def automatic_text(value):
    """The cell text of the classic grids before any format: blank when missing, ten significant digits."""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)):
        return f"{value:.10g}"
    return str(value)


def edit_text(value):
    """The editor text of a formatted cell: the stored, unrounded number (as the Tk grid always edits it)."""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


class Renderer:
    """Formats for the visible cells of one grid: position → format, compiled once per language."""

    def __init__(self, formats=None):
        self.formats = dict(formats or {})
        self._compiled = {}

    def __bool__(self):
        return bool(self.formats)

    def text(self, position, value):
        """The formatted text, or ``None`` for the existing renderer."""
        spec = self.formats.get(position)
        if spec is None:
            return None
        mark = display_decimal_mark()
        key = position, mark
        function = self._compiled.get(key)
        if function is None:
            function = self._compiled[key] = formatter(spec, mark)
        return function(value)


# -- persistence and editing ---------------------------------------------------------------------
def assign_formats(current, keys, spec):
    """``current`` with ``spec`` on ``keys`` (Automatic or ``None`` removes them); the same object if unchanged."""
    spec = None if spec is None else validated_spec(spec)
    new = dict(current)
    for key in keys:
        if spec is None or spec["mode"] == AUTOMATIC:
            new.pop(key, None)
        else:
            new[key] = spec
    return current if new == current else new


def column_records(formats, columns):
    """The saved form of data-table formats: worksheet order, existing columns only."""
    return {name: dict(formats[name]) for name in columns if name in formats}


def read_column_formats(record, columns):
    if not isinstance(record, dict) or len(record) > len(columns):
        raise ValueError("Invalid saved number formats.")
    formats = {}
    for name, spec in record.items():
        if name not in columns:
            raise ValueError("A number format references an unknown column.")
        spec = validated_spec(spec)
        if spec["mode"] != AUTOMATIC:
            formats[name] = spec
    return formats


def position_records(formats):
    return [[position, dict(spec)] for position, spec in sorted(formats.items())]


def read_position_formats(records, limit):
    if not isinstance(records, list) or len(records) > limit:
        raise ValueError("Invalid saved result number formats.")
    formats = {}
    for entry in records:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError("Invalid saved result number format.")
        position, spec = entry
        if type(position) is not int or not 1 <= position < limit:
            raise ValueError("A result number format references an unknown column.")
        if position in formats:
            raise ValueError("Duplicate saved result number format.")
        spec = validated_spec(spec)
        if spec["mode"] != AUTOMATIC:
            formats[position] = spec
    return formats


# -- which columns can change ---------------------------------------------------------------------
@dataclass(frozen=True)
class FormatColumn:
    position: int
    name: str
    reason: str | None = None  # None: the column takes a number format.

    @property
    def eligible(self):
        return self.reason is None


def _real(value):
    return (isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))
            and not (isinstance(value, (float, np.floating)) and math.isnan(value)))


def numeric_column(series):
    """Numbers, not booleans; a mixed column counts when it holds at least one number."""
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return False
    if pd.api.types.is_numeric_dtype(dtype):
        return True
    return dtype == object and any(_real(value) for value in series.array)


def _whole_numbers(series):
    values = pd.to_numeric(pd.Series(series.array, dtype=object), errors="coerce").astype(float)
    values = values[np.isfinite(values)]
    return bool((values == np.floor(values)).all())


def worksheet_columns(dataset, frame):
    """Every column of a data table as the grid shows it (``frame``), with the reason it keeps its style."""
    kind = (dataset.table_format or "").casefold()
    names = [str(name) for name in frame.columns]
    calculated = {position for position, name in enumerate(frame.columns) if name in dataset.formulas}
    bands, _ = heading_bands(frame, names, len(dataset.raw.columns), dataset.table_format, calculated=calculated)
    columns = []
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if position < len(bands) and bands[position][2] == "Row titles":
            reason = ROW_TITLES
        elif kind.startswith("contingency"):
            reason = COUNTS  # Contingency tables keep their whole counts.
        elif not numeric_column(series):
            reason = TEXT
        elif kind.startswith("survival") and _whole_numbers(series):
            reason = CODES  # Event and censor codes (and whole times) stay as typed.
        else:
            reason = None
        columns.append(FormatColumn(position, str(name), reason))
    return columns


def result_columns(frame, index_title, method_columns=()):
    """Every column of a result table as shown: position 0 holds the row titles; ``method_columns`` already
    have a format chosen by the analysis (ROC thresholds with infinity, for example)."""
    columns = [FormatColumn(0, str(index_title), ROW_TITLES)]
    for position, name in enumerate(frame.columns, 1):
        if name in method_columns:
            reason = METHOD
        elif not numeric_column(frame.iloc[:, position - 1]):
            reason = TEXT
        else:
            reason = None
        columns.append(FormatColumn(position, str(name), reason))
    return columns


def _names(columns):
    names = [column.name for column in columns]
    if len(names) > _LISTED_NAMES:
        return tr("number_format.more", names=", ".join(names[:_LISTED_NAMES]), count=len(names) - _LISTED_NAMES)
    return ", ".join(names)


@dataclass
class FormatTarget:
    """The columns a Number format command reaches: the selected ones that change and those that keep their
    style, the format to start from and a real value for the preview."""
    changing: list
    unchanged: list
    spec: dict
    value: object
    sample: bool
    has_format: bool

    @property
    def keys(self):
        return [column.position for column in self.changing]

    def changing_text(self):
        return tr("number_format.changing", columns=_names(self.changing))

    def unchanged_text(self):
        if not self.unchanged:
            return ""
        parts = []
        for reason in (TEXT, ROW_TITLES, CODES, COUNTS, METHOD):
            group = [column for column in self.unchanged if column.reason == reason]
            if group:
                parts.append(tr(f"number_format.reason_{reason}", columns=_names(group)))
        return tr("number_format.unchanged", reasons="; ".join(parts))


def format_target(columns, box, formats, *, active=None, value_at=None, rows=0):
    """Build the target of a selection ``box`` (top, left, bottom, right) over ``columns``.

    ``formats`` maps positions to their current format; ``value_at(row, position)`` reads a stored value of the
    ``rows`` filled rows; ``active`` is the active cell. Raises ``ValueError`` with a message for the user when
    nothing in the sheet or in the selection can take a number format.
    """
    if not any(column.eligible for column in columns):
        if columns and all(column.reason in (COUNTS, ROW_TITLES) for column in columns) and any(
                column.reason == COUNTS for column in columns):
            raise ValueError(tr("number_format.contingency"))
        raise ValueError(tr("number_format.no_sheet_columns"))
    top, left, bottom, right = box
    selected = [column for column in columns if left <= column.position <= right]
    changing = [column for column in selected if column.eligible]
    if not changing:
        raise ValueError(tr("number_format.no_selected_columns"))
    unchanged = [column for column in selected if not column.eligible]
    active_column = active[1] if active is not None else None
    current = [formats.get(column.position) for column in changing]
    spec = formats.get(active_column) if active_column in {column.position for column in changing} else None
    spec = spec or next((item for item in current if item is not None), None) or {"mode": AUTOMATIC}
    value, sample = SAMPLE_VALUE, True
    if value_at is not None:
        first, last = max(0, top), min(rows - 1, bottom, max(0, top) + _PREVIEW_SCAN - 1)
        candidates = ((row, column.position) for column in changing for row in range(first, last + 1))
        if active is not None and active[1] in {column.position for column in changing} and 0 <= active[0] < rows:
            candidates = chain([active], candidates)
        for row, position in candidates:  # Lazy: the first number ends the scan.
            number = number_value(value_at(row, position))
            if number is not None:
                value, sample = value_at(row, position), False
                break
    return FormatTarget(changing, unchanged, validated_spec(spec), value, sample,
                        any(item is not None for item in current))


class FormatDraft:
    """The dialog's state: a mode and its digits, kept within the range of the mode."""

    def __init__(self, spec):
        spec = validated_spec(spec)
        self.mode = spec["mode"]
        self.digits = spec.get("digits", DEFAULT_DIGITS[FIXED])

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError("Unknown number format mode.")
        if mode != AUTOMATIC:
            low, high = DIGIT_RANGES[mode]
            if self.mode == AUTOMATIC or not low <= self.digits <= high:
                self.digits = DEFAULT_DIGITS[mode] if self.mode == AUTOMATIC else min(high, max(low, self.digits))
        self.mode = mode

    def set_digits(self, digits):
        low, high = self.range()
        if type(digits) is not int or not low <= digits <= high:
            raise ValueError(f"Choose between {low} and {high} digits for this number format.")
        self.digits = digits

    def range(self):
        return DIGIT_RANGES.get(self.mode, (0, 12))

    def spec(self):
        return {"mode": AUTOMATIC} if self.mode == AUTOMATIC else {"mode": self.mode, "digits": self.digits}

    def digits_label(self):
        return tr(f"number_format.digits_{self.mode}")

    def preview(self, value):
        text = format_number(value, self.spec(), decimal_mark=display_decimal_mark())
        return automatic_text(value) if text is None else text


def mode_label(mode):
    return tr(f"number_format.mode_{mode}")
