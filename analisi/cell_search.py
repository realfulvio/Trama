"""Find and replace in the cells of a sheet: literal Unicode text, never a regular expression.

The scan walks the real cells column by column in blocks of rows, so a 50 000 × 20 worksheet
can be searched in short steps (the window keeps responding and the scan can be cancelled).
Matches come back in reading order: row first, then column, as the sheet shows them.

Replacing is planned first (``plan_replace``) and applied later (``apply_replace``): the plan keeps
the text each cell had, so the caller can refuse to apply it when the sheet changed meanwhile.
"""
from collections import Counter
from dataclasses import dataclass, field
import re

import numpy as np
import pandas as pd

from .data import MAX_ENTRY

# Why a match is found but not replaced (the preview lists them).
READ_ONLY = "read_only"      # A result sheet or a frozen sheet: search only.
FORMULA = "formula"          # A calculated column.
LOCKED = "locked"            # A column a recovered graph needs as it is.
NUMBER = "number"            # A number, a date, TRUE/FALSE: only text cells are replaced in this release.
UNCHANGED = "unchanged"      # The replacement gives back the same text.
REASONS = (READ_ONLY, FORMULA, LOCKED, NUMBER, UNCHANGED)

PREVIEW_ROWS = 200           # The preview lists these first changes and counts the others.
_NUMBER_CHARS = frozenset("0123456789.,-+eEinfaINFA ")


@dataclass(frozen=True)
class SearchOptions:
    query: str
    case_sensitive: bool = False
    whole_cell: bool = False

    def pattern(self):
        if not self.query:
            raise ValueError("Enter the text to find.")
        return re.compile(re.escape(self.query), 0 if self.case_sensitive else re.IGNORECASE)

    def matcher(self):
        pattern = self.pattern()
        return pattern.fullmatch if self.whole_cell else pattern.search


def may_match_number(query):
    """False when the text cannot appear in a number written without a format (letters, symbols)."""
    return set(query) <= _NUMBER_CHARS


def cell_name(row, column):
    """Spreadsheet address of a worksheet cell (column A, row 1 = the first cell)."""
    letters = ""
    column += 1
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(65 + rest) + letters
    return f"{letters}{row + 1}"


class CellScan:
    """Search in steps. ``cell_texts(column, start, stop)`` gives, for each row of the block, the texts
    a cell can be found by (stored value, text on screen) or ``None`` for an empty cell.

    ``ranges`` limits the search to (top, left, bottom, right) rectangles, which may be several and may
    overlap: a cell is visited once. ``step()`` examines one block of rows and returns True at the end."""

    def __init__(self, rows, columns, cell_texts, options, *, ranges=None, chunk=4096):
        self.match = options.matcher()  # Raises for an empty query, before any work.
        self.options = options
        self.rows, self.columns = rows, columns
        self.cell_texts = cell_texts
        self.chunk = max(1, int(chunk))
        if ranges is None:
            self.ranges = [(0, 0, rows - 1, columns - 1)] if rows and columns else []
        else:
            self.ranges = [(max(0, top), max(0, left), min(rows - 1, bottom), min(columns - 1, right))
                           for top, left, bottom, right in ranges]
            self.ranges = [box for box in self.ranges if box[0] <= box[2] and box[1] <= box[3]]
        self.first = min((box[0] for box in self.ranges), default=0)
        self.last = max((box[2] for box in self.ranges), default=-1)
        self.position = self.first
        self.matches = []
        self.done = not self.ranges

    @property
    def progress(self):
        """Fraction of the rows already examined."""
        span = self.last - self.first + 1
        return 1.0 if self.done or span <= 0 else (self.position - self.first) / span

    def _rows_of(self, column, start, stop):
        """Boolean mask of the rows [start, stop) of ``column`` inside the ranges, or None when none is."""
        mask = None
        for top, left, bottom, right in self.ranges:
            if left <= column <= right and top < stop and bottom >= start:
                if mask is None:
                    mask = np.zeros(stop - start, dtype=bool)
                mask[max(top, start) - start:min(bottom + 1, stop) - start] = True
        return mask

    def step(self):
        if self.done:
            return True
        start = self.position
        stop = min(self.last + 1, start + self.chunk)
        found = []
        for column in range(self.columns):
            mask = self._rows_of(column, start, stop)
            if mask is None:
                continue
            texts = self.cell_texts(column, start, stop)
            if texts is None:
                continue
            match = self.match
            for offset in np.flatnonzero(mask):
                candidates = texts[offset]
                if candidates and any(text and match(text) for text in candidates):
                    found.append((start + int(offset), column))
        found.sort()
        self.matches.extend(found)
        self.position = stop
        self.done = stop > self.last
        return self.done

    def run(self):
        while not self.step():
            pass
        return self.matches


def worksheet_texts(frame, options, renderer=None, display=None):
    """The ``cell_texts`` of a worksheet frame: text cells by their text, numbers by the stored value and
    by the text on screen (a number shown with two decimals is still found by all its digits)."""
    numeric_query = may_match_number(options.query)
    shown = display or (lambda value: str(value))

    def texts(column, start, stop):
        series = frame.iloc[start:stop, column]
        values = series.to_numpy(dtype=object, na_value=None)
        number_column = (pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype))
        formatted = renderer is not None and renderer.formats.get(column) is not None
        if number_column and not numeric_query and not formatted:
            return None
        result = []
        for value in values:
            if value is None or (isinstance(value, float) and value != value):
                result.append(None)
            elif isinstance(value, str):
                result.append((value,))
            else:
                screen = renderer.text(column, value) if formatted else None
                result.append((str(value), screen if screen is not None else shown(value)))
        return result

    return texts


@dataclass
class ReplacePlan:
    """What «Replace all» will do, checked again before it is applied."""
    title: str
    revision: int
    options: SearchOptions
    replacement: str
    changes: list = field(default_factory=list)   # (row, column, source column, before, after)
    skipped: Counter = field(default_factory=Counter)
    total: int = 0
    too_long: str | None = None   # The first cell whose new text would exceed the size limit.
    problem: str | None = None    # The table refuses the new values (message of the check).

    @property
    def preview(self):
        return self.changes[:PREVIEW_ROWS]


def replaced_text(text, options, replacement):
    """The cell text after the replacement; ``$`` and ``\\`` in the replacement are plain characters."""
    if options.whole_cell:
        return replacement if options.matcher()(text) else text
    return options.pattern().sub(lambda _match: replacement, text)


def plan_replace(dataset, frame, matches, options, replacement, *, title="", revision=0, read_only=False):
    """Sort the matches into cells to replace and cells left alone (with the reason)."""
    plan = ReplacePlan(title, revision, options, replacement, total=len(matches))
    if read_only:
        plan.skipped[READ_ONLY] = len(matches)
        return plan
    pattern = options.pattern()
    whole = options.whole_cell
    sources = dataset.source_indices
    locked = set(dataset.locked_columns)
    for row, column in matches:
        source = sources[column] if column < len(sources) else None
        if source is None:
            plan.skipped[FORMULA] += 1
            continue
        if source in locked:
            plan.skipped[LOCKED] += 1
            continue
        value = frame.iat[row, column]
        if not isinstance(value, str):
            plan.skipped[NUMBER] += 1
            continue
        after = replacement if whole else pattern.sub(lambda _match: replacement, value)
        if after == value:
            plan.skipped[UNCHANGED] += 1
            continue
        if len(after) > MAX_ENTRY and plan.too_long is None:
            plan.too_long = cell_name(row, column)
        plan.changes.append((row, column, source, value, after))
    if plan.changes and plan.too_long is None:
        from copy import copy
        trial = copy(dataset)
        try:
            apply_replace(trial, plan.changes)
            trial.frame()
        except (ValueError, TypeError, OverflowError) as error:
            plan.problem = str(error)
    return plan


def stale_cells(dataset, changes):
    """The changes whose cell no longer holds the text the preview showed."""
    raw = dataset.raw
    stale = []
    for change in changes:
        row, _column, source, before, _after = change
        if row >= len(raw) or source >= len(raw.columns) or raw.iat[row, source] != before:
            stale.append(change)
    return stale


def apply_replace(dataset, changes):
    """Write the new texts in a copy of the source table and swap it in (an empty text empties the cell).

    Exclusions, formats, row and column identities are kept: only the values of the cells change."""
    if not changes:
        return
    raw = dataset.raw
    by_column = {}
    for row, _column, source, _before, after in changes:
        by_column.setdefault(source, ([], []))
        by_column[source][0].append(row)
        by_column[source][1].append(after if after else pd.NA)
    candidate = raw.copy()
    for source, (rows, values) in by_column.items():
        series = candidate.iloc[:, source].copy()
        if not (pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype)):
            raise ValueError(f"{raw.columns[source]}: only text cells can be replaced.")
        series.iloc[rows] = values
        candidate.isetitem(source, series)
    dataset.raw = candidate


__all__ = ["CellScan", "SearchOptions", "ReplacePlan", "plan_replace", "apply_replace", "stale_cells",
           "worksheet_texts", "replaced_text", "cell_name", "REASONS", "PREVIEW_ROWS"]
