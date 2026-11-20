"""Reshape long and wide: one row per key, or one row per measure.

Long to wide (pivot)
    ``ID columns`` is an ordered list of key columns, ``Name column`` holds the level of each measure and
    ``Value column`` the measure. The result has one row per ID tuple, in order of first appearance, then the ID
    columns followed by one column per level, in order of first appearance. A level is the literal label: text
    stays as typed (no case folding, accents or signs are touched) and a number is written in its shortest form
    (1.0 gives "1", 2.5 gives "2.5"). Text and numbers are kept apart before they become names: the text "1" and
    the number 1 would both give the column "1", which is an error on Name column that shows both values. A level
    named like an ID column is an error too. Two rows with the same ID tuple and level are an error that shows both
    rows, even when one measure is blank; nothing is aggregated. A combination that never occurs stays blank and has
    no row in the source map. A blank measure with a valid key and level is a mapped blank cell.

Wide to long (unpivot)
    ``ID columns`` and ``Measure columns`` are ordered lists of distinct columns. Each source row gives one row per
    measure column, in source order and then in the order of Measure columns. ``Output names`` and ``Output values``
    name the two new columns (default "Variable" and "Value"). ``Drop missing values`` (default false) leaves out the
    blank measures; zeros, false and non-empty text are always kept. The ID columns must identify every row. The
    values keep their type: numbers stay numbers and text stays text, also "001" and "5". Measure columns of
    different types give a mixed column (see docs/reshape-long-wide.md for its CSV and .alab round trip).

Both directions
    The input is the masked worksheet: excluded cells arrive blank and stay blank. A row whose cells are blank in
    every chosen column is skipped (the empty rows at the bottom of a sheet); any other row with a blank key is an
    error that names the row. Rows are worksheet positions counted from 1. The result tables are ``Reshaped data``,
    ``Source map`` (Source row, Source column, Result row, Result column: one row per measure in the result) and
    ``Settings``. Every output table must fit ``MAX_COLUMNS`` columns and ``MAX_CELLS`` cells; the sizes are counted
    from the keys and levels before anything is allocated. ``preview`` runs the same checks and builds only the
    first 25 rows and 12 columns.
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .analysis_chain import ChainCancelled
from .data import MAX_CELLS, MAX_COLUMNS, _project_column_kind
from .field_error import FieldError
from .reporting import Result

METHOD = "Reshape long and wide"
DIRECTION, ID_COLUMNS, NAME_COLUMN, VALUE_COLUMN = "Direction", "ID columns", "Name column", "Value column"
MEASURE_COLUMNS, OUTPUT_NAMES, OUTPUT_VALUES, DROP_MISSING = (
    "Measure columns", "Output names", "Output values", "Drop missing values")
LONG_TO_WIDE, WIDE_TO_LONG = DIRECTIONS = ("Long to wide", "Wide to long")
DEFAULT_NAMES, DEFAULT_VALUES = "Variable", "Value"
WIDE_FIELDS = (DIRECTION, ID_COLUMNS, NAME_COLUMN, VALUE_COLUMN)
LONG_FIELDS = (DIRECTION, ID_COLUMNS, MEASURE_COLUMNS, OUTPUT_NAMES, OUTPUT_VALUES, DROP_MISSING)
# Field kinds for the generic dialogs and the catalog; the Qt window has its own editor (trama_qt.reshape_long_wide).
OPTIONS = {DIRECTION: DIRECTIONS, ID_COLUMNS: "Multiple", NAME_COLUMN: "Optional", VALUE_COLUMN: "Optional",
           MEASURE_COLUMNS: "Multiple (optional)", OUTPUT_NAMES: "Text", OUTPUT_VALUES: "Text", DROP_MISSING: False}
TABLE, SOURCE_MAP, SETTINGS = "Reshaped data", "Source map", "Settings"
MAP_COLUMNS = ("Source row", "Source column", "Result row", "Result column")
PREVIEW_ROWS, PREVIEW_COLUMNS = 25, 12
KINDS = {"numeric": "Numeric", "text": "Text", "mixed": "Mixed"}
_EXACT_FLOAT = 2 ** 53


class ReshapeCancelled(ChainCancelled):
    """Cancelled on the worker; the window keeps the previous result."""


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise ReshapeCancelled("Reshape cancelled.")


def _count(value):
    return f"{value:,}"


# -- options --------------------------------------------------------------------------------------------
def direction(options):
    value = options.get(DIRECTION, LONG_TO_WIDE)
    if value not in DIRECTIONS:
        raise FieldError(DIRECTION, 'Choose "Long to wide" or "Wide to long".')
    return value


def canonical(options):
    """The recipe keys of the chosen direction, with the defaults filled in (what a saved recipe holds)."""
    chosen = direction(options)
    if chosen == LONG_TO_WIDE:
        return {DIRECTION: chosen, ID_COLUMNS: list(options.get(ID_COLUMNS) or []),
                NAME_COLUMN: options.get(NAME_COLUMN), VALUE_COLUMN: options.get(VALUE_COLUMN)}
    return {DIRECTION: chosen, ID_COLUMNS: list(options.get(ID_COLUMNS) or []),
            MEASURE_COLUMNS: list(options.get(MEASURE_COLUMNS) or []),
            OUTPUT_NAMES: options.get(OUTPUT_NAMES, DEFAULT_NAMES), OUTPUT_VALUES: options.get(OUTPUT_VALUES, DEFAULT_VALUES),
            DROP_MISSING: bool(options.get(DROP_MISSING, False))}


def _column_list(options, field, frame, empty):
    raw = options.get(field)
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)) or any(not isinstance(name, str) for name in raw):
        raise FieldError(field, "The column list is not valid.")
    if not raw:
        raise FieldError(field, empty)
    seen = set()
    for name in raw:
        if name not in frame.columns:
            raise FieldError(field, f'Column "{name}" is not in the table.')
        if name in seen:
            raise FieldError(field, f'Column "{name}" is listed twice.')
        seen.add(name)
    return list(raw)


def _column(options, field, frame, empty):
    name = options.get(field)
    if not isinstance(name, str) or not name:
        raise FieldError(field, empty)
    if name not in frame.columns:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    return name


def _output_name(options, field, default, empty):
    name = options.get(field, default)
    if not isinstance(name, str) or not name.strip():
        raise FieldError(field, empty)
    return name


# -- cells ----------------------------------------------------------------------------------------------
def _missing(series):
    """Blank cells: NaN, None, NA and the empty string. Zero, false and other text are values."""
    blank = np.array(series.isna(), dtype=bool)
    if not pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
        blank = blank | np.asarray(series.isin([""]), dtype=bool)
    return blank


def _codes(series, blank):
    """Codes in order of first appearance; blank cells get -1. Values compare exactly (large integers too)."""
    codes, uniques = pd.factorize(series, use_na_sentinel=True, sort=False)
    codes = np.asarray(codes, dtype=np.int64)
    if blank.any():
        codes = codes.copy()
        codes[blank] = -1
    return codes, uniques


def _combine(codes):
    """One code per tuple of codes, in order of first appearance; any -1 gives -1."""
    combined = codes[0]
    for other in codes[1:]:
        cardinality = max(int(other.max(initial=-1)) + 1, 1)
        valid = (combined >= 0) & (other >= 0)
        merged = np.full(combined.shape, -1, dtype=np.int64)
        if valid.any():
            merged[valid] = pd.factorize(combined[valid] * cardinality + other[valid], sort=False)[0]
        combined = merged
    return combined


def _first_rows(codes, count):
    """For each code 0..count-1, the first position where it appears."""
    first = np.full(count, -1, dtype=np.int64)
    valid = np.flatnonzero(codes >= 0)
    if valid.size:
        values = codes[valid]
        order = np.argsort(values, kind="stable")
        sorted_codes = values[order]
        starts = np.flatnonzero(np.r_[True, sorted_codes[1:] != sorted_codes[:-1]])
        first[sorted_codes[starts]] = valid[order[starts]]
    return first


def level_name(value):
    """The column name a level gives: text as typed, numbers in their shortest form."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isfinite(number) and number.is_integer() and abs(number) < 1e16:
            return str(int(number))
        return repr(number)
    return str(value)


def _shown(value):
    """A level value in a message: text in quotes, numbers as they are."""
    return f'"{value}"' if isinstance(value, str) else level_name(value)


def _kind(series):
    return KINDS[_project_column_kind(series)]


def _take(series, indexer):
    """``series`` at ``indexer``; -1 gives a blank cell. The dtype is kept wherever a blank can be stored, and
    integers that a float could not hold exactly become nullable integers instead of floats."""
    fill = bool((indexer < 0).any())
    if isinstance(series.dtype, pd.api.extensions.ExtensionDtype):
        return pd.api.extensions.take(series.array, indexer, allow_fill=fill)
    values = series.to_numpy()
    if fill and values.dtype.kind in "iu":
        if values.size and np.abs(values.astype(object)).max() > _EXACT_FLOAT:
            return pd.api.extensions.take(pd.array(values, dtype="Int64"), indexer, allow_fill=True)
    if fill and values.dtype.kind == "b":
        return pd.api.extensions.take(pd.array(values, dtype="boolean"), indexer, allow_fill=True)
    return pd.api.extensions.take(values, indexer, allow_fill=fill)


def _limits(rows, columns, mapped, field):
    if columns > MAX_COLUMNS:
        raise FieldError(field, f"The result would have {_count(columns)} columns; the limit is {_count(MAX_COLUMNS)}.")
    cells = rows * columns
    if cells > MAX_CELLS:
        raise FieldError(field, f"The result would have {_count(cells)} cells ({_count(rows)} rows × "
                                f"{_count(columns)} columns); the limit is {_count(MAX_CELLS)}.")
    if mapped * len(MAP_COLUMNS) > MAX_CELLS:
        raise FieldError(field, f"The source map would have {_count(mapped)} rows; the limit is "
                                f"{_count(MAX_CELLS // len(MAP_COLUMNS))}.")


def _key_codes(frame, ids, used, blanks):
    """Codes of the ID tuple of each used row; a blank key is an error that names the row."""
    codes = []
    for name in ids:
        blank = blanks[name][used]
        if blank.any():
            row = int(used[np.argmax(blank)]) + 1
            raise FieldError(ID_COLUMNS, f'Row {row} has no value in ID column "{name}".')
        codes.append(_codes(frame[name].iloc[used], blank)[0])
    return _combine(codes)


# -- plans ----------------------------------------------------------------------------------------------
@dataclass
class _WidePlan:
    ids: list
    name: str
    value: str
    used: np.ndarray        # source positions of the measures, in source order
    row_codes: np.ndarray   # result row of each measure
    level_codes: np.ndarray  # result level of each measure
    rows: int
    levels: list            # column names
    first_rows: np.ndarray  # source position of the first appearance of each result row
    blank_values: int
    skipped: int

    @property
    def columns(self):
        return [*self.ids, *self.levels]

    @property
    def mapped(self):
        return int(self.used.size)

    @property
    def missing(self):
        return self.rows * len(self.levels) - self.mapped + self.blank_values


@dataclass
class _LongPlan:
    ids: list
    measures: list
    names: str
    values: str
    drop: bool
    used: np.ndarray   # source positions of the rows, in source order
    keep: np.ndarray   # used rows × measures: the measures that become rows
    blank: np.ndarray  # used rows × measures: blank measures
    skipped: int

    @property
    def columns(self):
        return [*self.ids, self.names, self.values]

    @property
    def rows(self):
        return int(self.keep.sum())

    @property
    def mapped(self):
        return self.rows

    @property
    def missing(self):
        return int((self.keep & self.blank).sum())


def plan(frame, options, cancel=None):
    """Validate the options against the table and count the result, without allocating it."""
    chosen = direction(options)
    _check(cancel)
    if chosen == LONG_TO_WIDE:
        return _wide_plan(frame, options, cancel)
    return _long_plan(frame, options, cancel)


def _wide_plan(frame, options, cancel):
    ids = _column_list(options, ID_COLUMNS, frame, "Choose at least one ID column.")
    name = _column(options, NAME_COLUMN, frame, "Choose the column that holds the level names.")
    value = _column(options, VALUE_COLUMN, frame, "Choose the column that holds the values.")
    if name in ids:
        raise FieldError(NAME_COLUMN, f'Column "{name}" is already an ID column.')
    if value in ids:
        raise FieldError(VALUE_COLUMN, f'Column "{value}" is already an ID column.')
    if value == name:
        raise FieldError(VALUE_COLUMN, "The name column and the value column must be different.")
    blanks = {column: _missing(frame[column]) for column in (*ids, name, value)}
    _check(cancel)
    empty = np.logical_and.reduce([blanks[column] for column in (*ids, name, value)])
    used = np.flatnonzero(~empty)
    if not used.size:
        raise FieldError(ID_COLUMNS, "The table has no rows with data in the chosen columns.")
    row_codes = _key_codes(frame, ids, used, blanks)
    _check(cancel)
    level_blank = blanks[name][used]
    if level_blank.any():
        row = int(used[np.argmax(level_blank)]) + 1
        raise FieldError(NAME_COLUMN, f'Row {row} has no value in the name column "{name}".')
    level_codes, uniques = _codes(frame[name].iloc[used], level_blank)
    level_values = list(uniques)
    levels = [level_name(item) for item in level_values]
    level_first = _first_rows(level_codes, len(levels))
    seen = {}
    for code, label in enumerate(levels):
        if label in seen:
            other = seen[label]
            first, second = sorted((other, code), key=lambda c: level_first[c])
            raise FieldError(NAME_COLUMN, f'Rows {int(used[level_first[first]]) + 1} and '
                                          f'{int(used[level_first[second]]) + 1} give the same column name '
                                          f'"{label}" from different values: {_shown(level_values[first])} and '
                                          f'{_shown(level_values[second])}.')
        seen[label] = code
        if label in ids:
            raise FieldError(NAME_COLUMN, f'The level "{label}" (row {int(used[level_first[code]]) + 1}) has the '
                                          f'same name as an ID column.')
    _check(cancel)
    rows = int(row_codes.max()) + 1
    combined = row_codes * len(levels) + level_codes
    repeated = pd.Series(combined).duplicated(keep=False).to_numpy()
    if repeated.any():
        first = int(np.argmax(repeated))
        second = int(np.flatnonzero(repeated & (combined == combined[first]))[1])
        raise FieldError(ID_COLUMNS, f'Rows {int(used[first]) + 1} and {int(used[second]) + 1} have the same ID and '
                                     f'level "{levels[level_codes[first]]}". Add an ID column that tells them apart, '
                                     f'or remove one of the rows.')
    _limits(rows, len(ids) + len(levels), int(used.size), NAME_COLUMN)
    first_rows = used[_first_rows(row_codes, rows)]
    return _WidePlan(ids, name, value, used, row_codes, level_codes, rows, levels, first_rows,
                     int(blanks[value][used].sum()), int(len(frame) - used.size))


def _long_plan(frame, options, cancel):
    ids = _column_list(options, ID_COLUMNS, frame, "Choose at least one ID column.")
    measures = _column_list(options, MEASURE_COLUMNS, frame, "Choose at least one measure column.")
    for column in measures:
        if column in ids:
            raise FieldError(MEASURE_COLUMNS, f'Column "{column}" is already an ID column.')
    names = _output_name(options, OUTPUT_NAMES, DEFAULT_NAMES, "Enter a name for the column of names.")
    values = _output_name(options, OUTPUT_VALUES, DEFAULT_VALUES, "Enter a name for the column of values.")
    if names in ids:
        raise FieldError(OUTPUT_NAMES, f'The name "{names}" is already used by an ID column.')
    if values in ids:
        raise FieldError(OUTPUT_VALUES, f'The name "{values}" is already used by an ID column.')
    if names == values:
        raise FieldError(OUTPUT_VALUES, "The column of names and the column of values need different names.")
    drop = options.get(DROP_MISSING, False)
    if not isinstance(drop, (bool, np.bool_)):
        raise FieldError(DROP_MISSING, "Choose whether blank measures are left out.")
    blanks = {}
    for column in (*ids, *measures):
        blanks[column] = _missing(frame[column])
        _check(cancel)
    empty = np.logical_and.reduce([blanks[column] for column in (*ids, *measures)])
    used = np.flatnonzero(~empty)
    if not used.size:
        raise FieldError(ID_COLUMNS, "The table has no rows with data in the chosen columns.")
    codes = _key_codes(frame, ids, used, blanks)
    repeated = pd.Series(codes).duplicated(keep=False).to_numpy()
    if repeated.any():
        first = int(np.argmax(repeated))
        second = int(np.flatnonzero(repeated & (codes == codes[first]))[1])
        raise FieldError(ID_COLUMNS, f'Rows {int(used[first]) + 1} and {int(used[second]) + 1} have the same ID. '
                                     f'Add an ID column that tells them apart.')
    blank = np.column_stack([blanks[column][used] for column in measures])
    keep = ~blank if drop else np.ones_like(blank)
    count = int(keep.sum())
    _limits(count, len(ids) + 2, count, MEASURE_COLUMNS)
    return _LongPlan(ids, measures, names, values, bool(drop), used, keep, blank, int(len(frame) - used.size))


# -- tables ---------------------------------------------------------------------------------------------
def _wide_table(frame, p, cancel, rows=None, columns=None):
    """The pivoted table; ``rows``/``columns`` limit it to the first rows and columns (the preview)."""
    shown_rows = p.rows if rows is None else min(rows, p.rows)
    shown_ids = p.ids if columns is None else p.ids[:columns]
    shown_levels = p.levels if columns is None else p.levels[:max(0, columns - len(shown_ids))]
    data = {}
    for name in shown_ids:
        data[name] = _take(frame[name], p.first_rows[:shown_rows])
    selected = (p.row_codes < shown_rows) & (p.level_codes < len(shown_levels))
    indexer = np.full((len(shown_levels), shown_rows), -1, dtype=np.int64)
    indexer[p.level_codes[selected], p.row_codes[selected]] = p.used[selected]
    source = frame[p.value]
    for position, label in enumerate(shown_levels):
        _check(cancel)
        data[label] = _take(source, indexer[position])
    return pd.DataFrame(data, columns=[*shown_ids, *shown_levels])


def _long_table(frame, p, cancel, rows=None, columns=None):
    flat = np.flatnonzero(p.keep.ravel())
    if rows is not None:
        flat = flat[:rows]
    source_rows, measure = np.divmod(flat, len(p.measures))
    positions = p.used[source_rows]
    names = p.columns if columns is None else p.columns[:columns]
    data = {}
    for name in p.ids:
        if name in names:
            data[name] = _take(frame[name], positions)
    if p.names in names:
        labels = np.asarray(p.measures, dtype=object)
        # Worksheet text, like an imported text column (pandas "string", blank = NA).
        data[p.names] = pd.array(labels[measure] if measure.size else np.empty(0, dtype=object), dtype="string")
    if p.values in names:
        parts = []
        for column in p.measures:
            _check(cancel)
            parts.append(frame[column].iloc[p.used].reset_index(drop=True))
        stacked = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
        _check(cancel)
        indexer = measure * len(p.used) + source_rows
        if isinstance(stacked.dtype, pd.api.extensions.ExtensionDtype):
            data[p.values] = stacked.array.take(indexer)
        else:
            data[p.values] = stacked.to_numpy()[indexer]
    return pd.DataFrame(data, columns=names)


def _source_map(p):
    if isinstance(p, _WidePlan):
        levels = np.asarray(p.levels, dtype=object)
        return pd.DataFrame({
            "Source row": p.used + 1,
            "Source column": np.full(p.used.size, p.value, dtype=object),
            "Result row": p.row_codes + 1,
            "Result column": levels[p.level_codes] if p.used.size else np.empty(0, dtype=object),
        })
    flat = np.flatnonzero(p.keep.ravel())
    source_rows, measure = np.divmod(flat, len(p.measures))
    labels = np.asarray(p.measures, dtype=object)
    return pd.DataFrame({
        "Source row": p.used[source_rows] + 1,
        "Source column": labels[measure] if flat.size else np.empty(0, dtype=object),
        "Result row": np.arange(1, flat.size + 1, dtype=np.int64),
        "Result column": np.full(flat.size, p.values, dtype=object),
    })


def _settings(frame, p, table):
    rows = [("Direction", LONG_TO_WIDE if isinstance(p, _WidePlan) else WIDE_TO_LONG)]
    rows += [(f"ID column {position}", name) for position, name in enumerate(p.ids, 1)]
    if isinstance(p, _WidePlan):
        rows += [("Name column", p.name), ("Value column", p.value), ("Value type", _kind(frame[p.value]))]
    else:
        rows += [(f"Measure column {position}", name) for position, name in enumerate(p.measures, 1)]
        rows += [(f"Measure type {position}", _kind(frame[name])) for position, name in enumerate(p.measures, 1)]
        rows += [("Output names", p.names), ("Output values", p.values),
                 ("Drop missing values", "Yes" if p.drop else "No")]
        if p.values in table:
            rows.append(("Values type", _kind(table[p.values])))
    rows += [("Source rows used", int(p.used.size)), ("Empty rows skipped", p.skipped),
             ("Result rows", int(len(table))), ("Result columns", int(len(table.columns))),
             ("Mapped cells", p.mapped), ("Blank cells", p.missing)]
    if isinstance(p, _WidePlan):
        rows.append(("Combinations never observed", p.rows * len(p.levels) - p.mapped))
    return pd.DataFrame({"Setting": [name for name, _ in rows],
                         "Value": pd.Series([value for _, value in rows], dtype=object)})


def reshape_long_wide(frame, options, cancel=None):
    """``analyse("Reshape long and wide", frame, options)``: Reshaped data, Source map and Settings."""
    p = plan(frame, options, cancel)
    _check(cancel)
    table = _wide_table(frame, p, cancel) if isinstance(p, _WidePlan) else _long_table(frame, p, cancel)
    _check(cancel)
    mapping = _source_map(p)
    _check(cancel)
    return Result({TABLE: table, SOURCE_MAP: mapping, SETTINGS: _settings(frame, p, table)})


@dataclass
class Preview:
    table: pd.DataFrame
    rows: int
    columns: int
    mapped: int
    missing: int

    @property
    def hidden_rows(self):
        return self.rows - len(self.table)

    @property
    def hidden_columns(self):
        return self.columns - len(self.table.columns)


def preview(frame, options, rows=PREVIEW_ROWS, columns=PREVIEW_COLUMNS, cancel=None):
    """The checks of the calculation and the first ``rows`` × ``columns`` of the result, with its full size."""
    p = plan(frame, options, cancel)
    build = _wide_table if isinstance(p, _WidePlan) else _long_table
    table = build(frame, p, cancel, rows=rows, columns=columns)
    return Preview(table, p.rows, len(p.columns), p.mapped, p.missing)


__all__ = ["METHOD", "OPTIONS", "DIRECTIONS", "LONG_TO_WIDE", "WIDE_TO_LONG", "Preview", "ReshapeCancelled",
           "canonical", "plan", "preview", "reshape_long_wide", "level_name"]
