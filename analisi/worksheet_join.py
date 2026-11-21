"""Join two worksheets of a project by one to four key columns (Analyze → Data Processing).

The left worksheet is the input of the analysis; the right worksheet is another native data sheet of the
same project, named by its exact title in ``Join right sheet``. The application resolves that title and
passes the evaluated right frame (formulas calculated, excluded cells blank) as ``join_data``; this module
never looks it up, so it runs on any worker without the interface.

Keys
    Text keys match exactly, spaces included. Integers and finite decimals match when they have the same
    value, without converting integers to float (2**53 + 1 never equals 2.0**53). Booleans are a type of
    their own, distinct from numbers and text. NumPy and pandas scalars count as their Python equivalents.
    A key with a missing value, an empty string, a non-finite number or an excluded cell matches nothing;
    any other cell type is refused on the key field before the output is allocated.

Cardinality
    ``One-to-many`` means one left row for many right rows: the left keys must be unique. Uniqueness is
    checked on every complete key of the side that needs it, also on keys without a match.

Output
    ``Joined data``: the left columns in order, then the right columns that are not keys, with
    ``Name [right]``, ``Name [right 2]``… for a name already taken. A right-only row carries its key values in
    the left key columns. ``Join provenance`` gives the 1-based worksheet positions and the state of every
    output row; ``Join diagnostics`` counts inputs, missing keys, matches and unmatched rows (also those the
    join type leaves out). Rows follow the left order, the right order inside a multiple match, then the
    right-only rows in their order. The number of rows is counted before anything is expanded.
"""
import math

import numpy as np
import pandas as pd

from .data import MAX_CELLS, MAX_COLUMNS
from .field_error import FieldError
from .reporting import Result

METHOD = "Join worksheets by key"
RIGHT_SHEET, LEFT_KEYS, RIGHT_KEYS = "Join right sheet", "Join left keys", "Join right keys"
JOIN_TYPE, CARDINALITY = "Join type", "Join cardinality"
INNER, LEFT, FULL = TYPES = ("Inner", "Left", "Full")
ONE_TO_ONE, ONE_TO_MANY, MANY_TO_ONE, MANY_TO_MANY = CARDINALITIES = (
    "One-to-one", "One-to-many", "Many-to-one", "Many-to-many")
DEFAULT_TYPE, DEFAULT_CARDINALITY = LEFT, ONE_TO_ONE
JOINED, PROVENANCE, DIAGNOSTICS = "Joined data", "Join provenance", "Join diagnostics"
MATCHED, LEFT_ONLY, RIGHT_ONLY = "Matched", "Left only", "Right only"
DIAGNOSTIC_NAMES = ("Left input rows", "Right input rows", "Left rows with missing key",
                    "Right rows with missing key", "Matched pairs", "Unmatched left rows", "Unmatched right rows",
                    "Output rows")
MAX_KEYS = 4
MAX_ROWS = 100_000

# Dialog kinds: the Qt dialog has its own editor for this analysis (trama_qt.worksheet_join).
SHEET_CHOICE = "Worksheet title"
KEY_PAIRS = "Key column pairs"
OPTIONS = {RIGHT_SHEET: SHEET_CHOICE, LEFT_KEYS: KEY_PAIRS, RIGHT_KEYS: KEY_PAIRS, JOIN_TYPE: TYPES,
           CARDINALITY: CARDINALITIES}

_UNIQUE_LEFT = {ONE_TO_ONE, ONE_TO_MANY}
_UNIQUE_RIGHT = {ONE_TO_ONE, MANY_TO_ONE}
_CHECK_EVERY = 8192


class JoinKeyError(FieldError):
    """A problem of one key pair. ``pair`` is its 0-based position in the dialog."""

    def __init__(self, field, message, pair):
        super().__init__(field, message)
        self.pair = pair


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        from .analysis_chain import ChainCancelled
        raise ChainCancelled


def right_title(options):
    title = (options or {}).get(RIGHT_SHEET)
    return title if isinstance(title, str) and title else None


def missing_source(title):
    """The error of a right worksheet that cannot be read. The dialog lets the user link another one."""
    if title is None:
        return FieldError(RIGHT_SHEET, "Choose the right worksheet in Join right sheet.")
    return FieldError(RIGHT_SHEET, f'The worksheet "{title}" is not in this project. Choose a data sheet in '
                                   "Join right sheet to link it again.")


def view_source(title):
    return FieldError(RIGHT_SHEET, f'The worksheet "{title}" is a recovered result view, not a data sheet. Choose a '
                                   "data sheet in Join right sheet.")


def same_source(title):
    return FieldError(RIGHT_SHEET, f'The worksheet "{title}" is already on the left. Choose another data sheet in '
                                   "Join right sheet.")


def key_lists(options):
    """The two key lists of a recipe, validated without data. Raises FieldError."""
    left, right = options.get(LEFT_KEYS), options.get(RIGHT_KEYS)
    for field, keys in ((LEFT_KEYS, left), (RIGHT_KEYS, right)):
        if not isinstance(keys, (list, tuple)) or not all(isinstance(name, str) and name for name in keys):
            raise FieldError(field, "Choose from 1 to 4 pairs of key columns.")
    if not 1 <= len(left) <= MAX_KEYS or not 1 <= len(right) <= MAX_KEYS:
        raise FieldError(LEFT_KEYS if not 1 <= len(left) <= MAX_KEYS else RIGHT_KEYS,
                         "Choose from 1 to 4 pairs of key columns.")
    if len(left) != len(right):
        field = LEFT_KEYS if len(left) < len(right) else RIGHT_KEYS
        raise JoinKeyError(field, "Each key pair needs a left column and a right column.", min(len(left), len(right)))
    for field, keys, side in ((LEFT_KEYS, left, "left"), (RIGHT_KEYS, right, "right")):
        seen = set()
        for pair, name in enumerate(keys):
            if name in seen:
                raise JoinKeyError(field, f'Pair {pair + 1}: "{name}" is already a {side} key.', pair)
            seen.add(name)
    return list(left), list(right)


def choices(options):
    kind = options.get(JOIN_TYPE, DEFAULT_TYPE)
    if kind not in TYPES:
        raise FieldError(JOIN_TYPE, "Join type: choose Inner, Left or Full.")
    rule = options.get(CARDINALITY, DEFAULT_CARDINALITY)
    if rule not in CARDINALITIES:
        raise FieldError(CARDINALITY, "Join cardinality: choose one of the listed options.")
    return kind, rule


def check_columns(left_columns, right_columns, left_keys, right_keys):
    """Every key names a column of its side. Raises JoinKeyError on the first missing one."""
    left_columns, right_columns = set(left_columns), set(right_columns)
    for pair, (left, right) in enumerate(zip(left_keys, right_keys)):
        if left not in left_columns:
            raise JoinKeyError(LEFT_KEYS, f'Pair {pair + 1}: the left worksheet has no column "{left}".', pair)
        if right not in right_columns:
            raise JoinKeyError(RIGHT_KEYS, f'Pair {pair + 1}: the right worksheet has no column "{right}".', pair)


def validate(options, left_columns=None, right_columns=None):
    """Cheap checks of a recipe, with the column names when they are known. Returns the parsed recipe."""
    if not isinstance(options, dict):
        raise FieldError(RIGHT_SHEET, "Choose the right worksheet in Join right sheet.")
    if right_title(options) is None:
        raise missing_source(None)
    left_keys, right_keys = key_lists(options)
    kind, rule = choices(options)
    if left_columns is not None and right_columns is not None:
        check_columns(left_columns, right_columns, left_keys, right_keys)
    return left_keys, right_keys, kind, rule


# ---------------------------------------------------------------------------
# Keys


_MISSING = object()


def _atom(value):
    """The comparable form of one key cell, ``_MISSING`` for a cell that matches nothing, None if refused."""
    if value is None or value is pd.NA or value is pd.NaT:
        return _MISSING
    if isinstance(value, (bool, np.bool_)):
        return ("b", bool(value))
    if isinstance(value, (int, np.integer)):
        return ("n", int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return _MISSING
        # An integral float compares as the exact integer it represents, never the other way round.
        return ("n", int(number) if number.is_integer() else number)
    if isinstance(value, str):
        return _MISSING if value == "" else ("s", str(value))
    try:
        if pd.isna(value):
            return _MISSING
    except (TypeError, ValueError):
        pass
    return None


def _keys(frame, names, field, side, cancel):
    """One tuple per row, or None for a row with an incomplete key."""
    columns = [frame[name].to_numpy(dtype=object) for name in names]
    keys = []
    for row in range(len(frame)):
        if row % _CHECK_EVERY == 0:
            _cancelled(cancel)
        key = []
        for pair, values in enumerate(columns):
            atom = _atom(values[row])
            if atom is None:
                raise JoinKeyError(
                    field, f'Pair {pair + 1}: column "{names[pair]}" of the {side} worksheet holds an unsupported '
                           f"value in row {row + 1}. Keys accept text, numbers and true/false values.", pair)
            if atom is _MISSING:
                key = None
                break
            key.append(atom)
        keys.append(None if key is None else tuple(key))
    return keys


def _check_unique(keys, side, rule, cancel):
    first = {}
    for row, key in enumerate(keys):
        if row % _CHECK_EVERY == 0:
            _cancelled(cancel)
        if key is None:
            continue
        previous = first.setdefault(key, row)
        if previous != row:
            raise FieldError(CARDINALITY,
                             f"The {side} worksheet repeats a key in rows {previous + 1} and {row + 1}. {rule} needs "
                             f"unique keys on the {side}: choose another cardinality or correct the data.")


# ---------------------------------------------------------------------------
# Output


def output_names(left_columns, right_columns, right_keys):
    """Names of the joined columns and the right columns they come from."""
    right_keys = set(right_keys)
    carried = [name for name in right_columns if name not in right_keys]
    left = list(left_columns)
    taken = set(left)
    # Right names that do not collide keep their name: reserve them before any suffix is chosen.
    taken.update(name for name in carried if name not in set(left))
    names = []
    for name in carried:
        if name not in left:
            names.append(name)
            continue
        candidate, number = f"{name} [right]", 2
        while candidate in taken:
            candidate = f"{name} [right {number}]"
            number += 1
        taken.add(candidate)
        names.append(candidate)
    return left + names, carried


def _take(series, positions, missing):
    """``series`` at 0-based ``positions``; rows marked by ``missing`` are blank. Keeps integers exact."""
    values = series.reset_index(drop=True)
    if missing.any():
        if values.dtype.kind in "iub":
            values = values.convert_dtypes()
        positions = np.where(missing, -1, positions)
        return values.reindex(positions).reset_index(drop=True)
    return values.take(positions).reset_index(drop=True)


def _fill(target, source, rows):
    """``target`` with the values of ``source`` at ``rows`` (a boolean mask)."""
    if not rows.any():
        return target
    if target.dtype != source.dtype:
        target, source = target.astype(object), source.astype(object)
    filled = target.mask(rows, source)
    return filled.infer_objects() if filled.dtype == object else filled


def _row_numbers(positions, missing):
    numbers = pd.array(positions + 1, dtype="Int64")
    numbers[missing] = pd.NA
    return pd.Series(numbers, dtype="Int64")


def join_worksheets(left, right, options, *, cancel=None):
    """Join the evaluated ``left`` and ``right`` worksheets with ``options``. Returns a Result of three tables."""
    if right is None:
        raise missing_source(right_title(options))
    left_keys, right_keys, kind, rule = validate(options, left.columns, right.columns)
    _cancelled(cancel)
    names, carried = output_names(left.columns, right.columns, right_keys)
    if len(names) > MAX_COLUMNS:
        raise FieldError(RIGHT_SHEET, f"The joined sheet would have {len(names):,} columns; a sheet holds at most "
                                      f"{MAX_COLUMNS:,}.")

    left_rows, right_rows = _keys(left, left_keys, LEFT_KEYS, "left", cancel), \
        _keys(right, right_keys, RIGHT_KEYS, "right", cancel)
    if rule in _UNIQUE_LEFT:
        _check_unique(left_rows, "left", rule, cancel)
    if rule in _UNIQUE_RIGHT:
        _check_unique(right_rows, "right", rule, cancel)

    index = {}
    for row, key in enumerate(right_rows):
        if key is not None:
            index.setdefault(key, []).append(row)
    _cancelled(cancel)
    matched_pairs = unmatched_left = 0
    left_matched = set()
    for key in left_rows:
        found = index.get(key) if key is not None else None
        if found:
            matched_pairs += len(found)
            left_matched.add(key)
        else:
            unmatched_left += 1
    right_unmatched = [row for row, key in enumerate(right_rows) if key is None or key not in left_matched]
    rows = matched_pairs + (unmatched_left if kind in (LEFT, FULL) else 0) + (len(right_unmatched) if kind == FULL else 0)
    cells = rows * len(names)
    if rows > MAX_ROWS or cells > MAX_CELLS:
        raise FieldError(JOIN_TYPE, f"The join would create {rows:,} rows ({cells:,} cells); the limit is "
                                    f"{MAX_ROWS:,} rows and {MAX_CELLS:,} cells. Choose Inner, add key columns or "
                                    "reduce the repeated keys.")
    _cancelled(cancel)

    left_positions = np.empty(rows, dtype=np.int64)
    right_positions = np.empty(rows, dtype=np.int64)
    at = 0
    for row, key in enumerate(left_rows):
        if row % _CHECK_EVERY == 0:
            _cancelled(cancel)
        found = index.get(key) if key is not None else None
        if found:
            count = len(found)
            left_positions[at:at + count] = row
            right_positions[at:at + count] = found
            at += count
        elif kind != INNER:
            left_positions[at], right_positions[at] = row, -1
            at += 1
    if kind == FULL:
        count = len(right_unmatched)
        left_positions[at:at + count] = -1
        right_positions[at:at + count] = right_unmatched
        at += count
    assert at == rows
    left_missing, right_missing = left_positions < 0, right_positions < 0

    columns = {}
    for name in left.columns:
        columns[name] = _take(left[name], left_positions, left_missing)
    for left_name, right_name in zip(left_keys, right_keys):
        # A right-only row identifies itself with its own key values in the left key columns.
        columns[left_name] = _fill(columns[left_name], _take(right[right_name], right_positions, right_missing),
                                   left_missing)
    for name, source in zip(names[len(left.columns):], carried):
        columns[name] = _take(right[source], right_positions, right_missing)
    joined = pd.DataFrame(columns, columns=names) if names else pd.DataFrame(index=range(rows))
    joined.index = pd.RangeIndex(rows)

    states = np.where(left_missing, RIGHT_ONLY, np.where(right_missing, LEFT_ONLY, MATCHED))
    provenance = pd.DataFrame({"Left row": _row_numbers(left_positions, left_missing),
                               "Right row": _row_numbers(right_positions, right_missing),
                               "State": pd.Series(states, dtype=object)})
    counts = (len(left), len(right), sum(key is None for key in left_rows), sum(key is None for key in right_rows),
              matched_pairs, unmatched_left, len(right_unmatched), rows)
    diagnostics = pd.DataFrame({"Metric": list(DIAGNOSTIC_NAMES), "Value": pd.Series(counts, dtype="int64")})
    return Result({JOINED: joined, PROVENANCE: provenance, DIAGNOSTICS: diagnostics})
