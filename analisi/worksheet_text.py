"""Text presentation of worksheet and result cells: font, size, color, bold, italic, underline, alignment.

A text style changes how a cell is drawn, never what it stores. Numbers stay numbers for the calculations, the
clipboard, CSV/XLSX export and "Use result as data"; only the grid, the printed pages and the rich exports read
the style. An attribute that is not set is *inherited* from the table font, the number format and the default
alignment of the cell, so ``Restore text`` simply removes the attributes and leaves backgrounds and number
formats alone.

Styles are stored as **row runs per column**, not per cell: a style applied to ``50 000 × 20`` cells is 20 runs.
The store is immutable (every operation returns a new store, or ``self`` when nothing changes), so undo
snapshots and recovery copies can share it, as they share the number formats.

Data tables key the runs by column name; result tables key them by column position (0 is the row-title column),
as the number formats do. Rows are counted from 0 and runs are half-open: ``(start, stop, style)``.
"""
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain
import math
import re

from .worksheet_row_identity import row_move_slices

FONT, SIZE, COLOR, BOLD, ITALIC, UNDERLINE, ALIGN = "font", "size", "color", "bold", "italic", "underline", "align"
ATTRIBUTES = (FONT, SIZE, COLOR, BOLD, ITALIC, UNDERLINE, ALIGN)
FLAGS = (BOLD, ITALIC, UNDERLINE)
ALIGNMENTS = ("left", "center", "right")
MIN_SIZE, MAX_SIZE = 6, 72
SIZE_CHOICES = (8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48)
MAX_RUNS = 200_000  # Saved runs per table: a bound on what a file can ask the reader to build.
MAX_FONT_NAME = 128

# What a group of selected cells shows for one attribute.
INHERITED, UNIFORM, MIXED = "inherited", "uniform", "mixed"

_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_value(attribute, value):
    """The canonical form of one attribute value; ``ValueError`` when it cannot be shown."""
    if attribute == FONT:
        if (not isinstance(value, str) or not value.strip() or len(value) > MAX_FONT_NAME
                or any(ord(char) < 32 or 0xd800 <= ord(char) <= 0xdfff for char in value)):
            raise ValueError("Invalid text style font.")
        return value
    if attribute == SIZE:
        if not _number(value) or not MIN_SIZE <= value <= MAX_SIZE:
            raise ValueError(f"Choose a text size between {MIN_SIZE} and {MAX_SIZE} points.")
        value = round(float(value) * 2) / 2
        return int(value) if value == int(value) else value
    if attribute == COLOR:
        if not isinstance(value, str) or not _COLOR.fullmatch(value):
            raise ValueError("Use a six-digit hex colour for the text.")
        return value.lower()
    if attribute in FLAGS:
        if type(value) is not bool:
            raise ValueError("Invalid text style flag.")
        return value
    if attribute == ALIGN:
        if not isinstance(value, str) or value not in ALIGNMENTS:
            raise ValueError("Choose left, center or right alignment.")
        return value
    raise ValueError("Unknown text style attribute.")


def validated_style(style):
    """The canonical ``dict`` of a non-empty style, attributes in a fixed order."""
    if not isinstance(style, Mapping) or not style or set(style) - set(ATTRIBUTES):
        raise ValueError("Invalid text style.")
    return {attribute: valid_value(attribute, style[attribute]) for attribute in ATTRIBUTES if attribute in style}


def _items(style):
    return tuple((attribute, style[attribute]) for attribute in ATTRIBUTES if attribute in style)


def _patched(items, changes):
    """``items`` with each attribute of ``changes`` set, or removed when its value is ``None``."""
    style = dict(items)
    for attribute, value in changes:
        if value is None:
            style.pop(attribute, None)
        else:
            style[attribute] = value
    return _items(style)


def _normalise_changes(changes):
    """``changes`` as ((attribute, canonical value or None), ...)."""
    if not isinstance(changes, Mapping) or set(changes) - set(ATTRIBUTES):
        raise ValueError("Invalid text style.")
    return tuple((attribute, None if changes[attribute] is None else valid_value(attribute, changes[attribute]))
                 for attribute in ATTRIBUTES if attribute in changes)


def _coalesce(runs):
    merged = []
    for start, stop, style in runs:
        if start >= stop or not style:
            continue
        if merged and merged[-1][1] == start and merged[-1][2] == style:
            merged[-1] = (merged[-1][0], stop, style)
        else:
            merged.append((start, stop, style))
    return tuple(merged)


def _patch_runs(runs, top, stop, changes):
    """The runs of one column after ``changes`` reached rows ``top`` to ``stop`` (exclusive)."""
    before = [run for run in runs if run[1] <= top]
    after = [run for run in runs if run[0] >= stop]
    middle = [run for run in runs if run[1] > top and run[0] < stop]
    out = list(before)
    for start, end, style in middle:
        if start < top:
            out.append((start, top, style))
    cursor = top
    for start, end, style in middle:
        start, end = max(start, top), min(end, stop)
        if cursor < start:
            out.append((cursor, start, _patched((), changes)))
        out.append((start, end, _patched(style, changes)))
        cursor = end
    if cursor < stop:
        out.append((cursor, stop, _patched((), changes)))
    for start, end, style in middle:
        if end > stop:
            out.append((stop, end, style))
    out.extend(after)
    return _coalesce(out)


@dataclass(frozen=True)
class TextState:
    """What the selection shows for one attribute: nothing set, one value everywhere, or a mixture."""
    kind: str
    value: object = None


class TextStyles:
    """Immutable row runs per column. ``key`` is a column name (data tables) or a position (results)."""

    __slots__ = ("runs", "_starts")

    def __init__(self, runs=None):
        self.runs = {key: tuple(value) for key, value in (runs or {}).items() if value}
        self._starts = {}

    # -- inspection ---------------------------------------------------------------------------------
    def __bool__(self):
        return bool(self.runs)

    def __eq__(self, other):
        return isinstance(other, TextStyles) and self.runs == other.runs

    def __hash__(self):
        return hash(tuple(sorted(self.runs.items(), key=lambda item: repr(item[0]))))

    def __repr__(self):
        return f"TextStyles({self.run_count()} runs in {len(self.runs)} columns)"

    def run_count(self):
        return sum(len(runs) for runs in self.runs.values())

    def style_at(self, key, row):
        """The style attributes of one cell as ``{attribute: value}``; empty when everything is inherited."""
        runs = self.runs.get(key)
        if not runs:
            return {}
        starts = self._starts.get(key)
        if starts is None:
            starts = self._starts[key] = [run[0] for run in runs]
        position = bisect_right(starts, row) - 1
        if position >= 0 and runs[position][1] > row:
            return dict(runs[position][2])
        return {}

    def largest_size(self, default):
        """The biggest font size any run asks for, to size the rows (``default`` when none sets a size)."""
        sizes = [value for runs in self.runs.values() for _, _, style in runs for attribute, value in style
                 if attribute == SIZE]
        return max([default, *sizes])

    def states(self, keys, top, stop):
        """Per attribute, what rows ``top`` to ``stop`` (exclusive) of the columns ``keys`` show."""
        seen = {attribute: set() for attribute in ATTRIBUTES}
        total = stop - top
        for key in keys:
            covered = []
            for start, end, style in self.runs.get(key, ()):
                if end <= top or start >= stop:
                    continue
                start, end = max(start, top), min(end, stop)
                covered.append((start, end))
                values = dict(style)
                for attribute in ATTRIBUTES:
                    seen[attribute].add(values.get(attribute))
            if sum(end - start for start, end in covered) < total:
                for attribute in ATTRIBUTES:
                    seen[attribute].add(None)
        result = {}
        for attribute, values in seen.items():
            if values <= {None}:
                result[attribute] = TextState(INHERITED)
            elif len(values) == 1:
                result[attribute] = TextState(UNIFORM, next(iter(values)))
            else:
                result[attribute] = TextState(MIXED)
        return result

    # -- editing ------------------------------------------------------------------------------------
    def apply(self, keys, top, stop, changes):
        """``changes`` (attribute → value, or ``None`` to inherit again) on rows ``top`` to ``stop`` of ``keys``."""
        changes = _normalise_changes(changes)
        if not changes or stop <= top:
            return self
        runs = dict(self.runs)
        for key in keys:
            revised = _patch_runs(runs.get(key, ()), max(0, top), stop, changes)
            if revised:
                runs[key] = revised
            else:
                runs.pop(key, None)
        return self if runs == self.runs else TextStyles(runs)

    def clear(self, keys, top, stop):
        """Remove every text attribute from rows ``top`` to ``stop`` of ``keys`` (``Restore text``)."""
        return self.apply(keys, top, stop, {attribute: None for attribute in ATTRIBUTES})

    # -- structure changes: the one place where row and column edits reach the text styles ----------
    def insert_rows(self, at, count):
        """New blank rows ``at``…: runs below shift down, a run that spans the insertion point is split."""
        if count <= 0 or not self.runs:
            return self
        runs = {}
        for key, column in self.runs.items():
            out = []
            for start, stop, style in column:
                if stop <= at:
                    out.append((start, stop, style))
                elif start >= at:
                    out.append((start + count, stop + count, style))
                else:
                    out.append((start, at, style))
                    out.append((at + count, stop + count, style))
            runs[key] = tuple(out)
        return TextStyles(runs)

    def delete_rows(self, rows):
        """Delete rows: a run shrinks by the deleted rows inside it and disappears when none is left."""
        rows = sorted(set(rows))
        if not rows or not self.runs:
            return self
        runs = {}
        for key, column in self.runs.items():
            out = []
            for start, stop, style in column:
                first = start - bisect_right(rows, start - 1)
                last = stop - bisect_right(rows, stop - 1)
                if last > first:
                    out.append((first, last, style))
            if out:
                runs[key] = _coalesce(out)
        return TextStyles(runs)

    def move_rows(self, length, start, stop, destination):
        """Move the styles with their source rows, retaining compact intervals."""
        if not self.runs or start <= destination <= stop:
            return self
        slices = row_move_slices(length, start, stop, destination)
        moved = {}
        for key, column in self.runs.items():
            out = []
            offset = 0
            for first, last in slices:
                for left, right, style in column:
                    if left >= last:
                        break
                    if right > first:
                        out.append((offset + max(left, first) - first, offset + min(right, last) - first, style))
                offset += last - first
            moved[key] = _coalesce(out)
        return self if moved == self.runs else TextStyles(moved)

    def rename(self, old, new):
        if old == new or old not in self.runs:
            return self
        runs = {(new if key == old else key): value for key, value in self.runs.items()}
        return TextStyles(runs)

    def rename_many(self, names):
        if not any(old in self.runs and old != new for old, new in names.items()):
            return self
        return TextStyles({names.get(key, key): value for key, value in self.runs.items()})

    def drop(self, keys):
        keys = set(keys)
        if not keys & self.runs.keys():
            return self
        return TextStyles({key: value for key, value in self.runs.items() if key not in keys})

    def clip(self, row_limit):
        """The styles restricted to ``row_limit`` rows (results can shrink after a recalculation)."""
        if all(run[1] <= row_limit for column in self.runs.values() for run in column):
            return self
        runs = {}
        for key, column in self.runs.items():
            kept = tuple((start, min(stop, row_limit), style) for start, stop, style in column if start < row_limit)
            if kept:
                runs[key] = kept
        return TextStyles(runs)

    # -- saved form ---------------------------------------------------------------------------------
    def records(self, order=None):
        """``[[key, top, stop, style], ...]``: columns in ``order`` (unknown keys dropped) or in key order."""
        if order is None:
            keys = sorted(self.runs, key=repr)
        else:
            keys = [key for key in order if key in self.runs]
        return [[key, start, stop, dict(style)] for key in keys for start, stop, style in self.runs[key]]


def read_text_styles(records, row_limit, keys, *, integer_keys=False):
    """The store of saved ``records``; ``ValueError`` for anything that is not a coherent set of runs.

    ``keys`` are the columns that exist (names, or positions for a result); ``row_limit`` is the number of rows.
    """
    if not isinstance(records, list) or len(records) > MAX_RUNS:
        raise ValueError("Invalid saved text styles.")
    runs = {}
    for entry in records:
        if not isinstance(entry, list) or len(entry) != 4:
            raise ValueError("Invalid saved text style.")
        key, start, stop, style = entry
        if integer_keys:
            if type(key) is not int or key not in keys:
                raise ValueError("A text style references an unknown column.")
        elif not isinstance(key, str) or key not in keys:
            raise ValueError("A text style references an unknown column.")
        if type(start) is not int or type(stop) is not int or not 0 <= start < stop <= row_limit:
            raise ValueError("A text style references rows that do not exist.")
        column = runs.setdefault(key, [])
        if column and start < column[-1][1]:
            raise ValueError("Saved text styles overlap or are out of order.")
        column.append((start, stop, _items(validated_style(style))))
    return TextStyles({key: _coalesce(column) for key, column in runs.items()})


def effective(style, base):
    """``base`` (defaults of the cell) overridden by the attributes of ``style``."""
    return {**base, **style}


def font_description(style, base_family="", base_size=None):
    """``(family, size, bold, italic, underline)`` of a cell: what the style sets over the table font."""
    return (style.get(FONT, base_family), style.get(SIZE, base_size), style.get(BOLD, False),
            style.get(ITALIC, False), style.get(UNDERLINE, False))


def selection_keys(columns, left, right):
    """The keys of the columns ``left`` to ``right`` (inclusive) of ``columns`` that exist."""
    return list(chain(columns[max(0, left):max(0, right + 1)]))
