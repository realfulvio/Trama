"""Reshape multiple-variable observations into native worksheet formats."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import repeat
import json
from numbers import Integral, Real

import numpy as np
import pandas as pd

from .data import MAX_CELLS, MAX_COLUMNS, decimal_comma
from .processing import FieldError, _column
from .reporting import Result, _report


EXTRACT_REARRANGE = "Extract and rearrange"
EXTRACT_TABLE = "Rearranged data"
OUTPUT = "Output table"
PREFIX = "Include variable name prefixes"
COMPLETE = "Only include complete rows"
X = "Independent (X) variable"
RESPONSE = "Response variable"
GROUP = "Grouping variable"
SUBJECT = "Subject/replicate variable"
TITLES = "Row titles"
ROW_FACTOR = "Row factor variable"
COLUMN_FACTOR = "Column factor variable"
TREATMENT = "Row (treatment) variable"
OUTCOME = "Column (outcome) variable"
COUNT = "Count variable"

EXTRACT_FIELDS = {
    "XY": (X, RESPONSE, GROUP, SUBJECT, TITLES),
    "Column": (RESPONSE, GROUP, SUBJECT, TITLES),
    "Grouped": (RESPONSE, ROW_FACTOR, COLUMN_FACTOR, SUBJECT),
    "Contingency": (TREATMENT, OUTCOME, COUNT),
}
EXTRACT_FORMATS = tuple(EXTRACT_FIELDS)
EXTRACT_OPTIONAL_FIELDS = frozenset((GROUP, SUBJECT, TITLES, COUNT))
_ROW_TITLE = "Row title"
_MAX_COUNT = int(np.iinfo(np.uint64).max)


def _missing(value):
    return (not value.strip() if isinstance(value, str) else
            pd.api.types.is_scalar(value) and pd.isna(value))


def _value(value, field, *, integer=False):
    if _missing(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (Integral, np.bool_)):
        return int(value)
    if isinstance(value, (Real, Decimal)):
        if isinstance(value, Decimal):
            finite = value.is_finite()
            whole = finite and value == value.to_integral_value()
        else:
            finite = np.isfinite(value)
            whole = finite and value == int(value)
        if finite and (whole or not integer):
            return int(value) if whole else value
    requirement = "whole numbers or category labels" if integer else "finite numbers or category labels"
    raise FieldError(field, f"{field} must contain {requirement}.")


def _ordered(levels):
    # The bundled Grouped example orders text levels alphabetically. Order numeric
    # levels numerically, and keep numeric and literal text levels distinct.
    return sorted(levels, key=lambda value: (isinstance(value, str), value))


def _label(value, variable=None):
    if variable is None:
        return str(value)
    label = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else str(value)
    return f"{variable} = {label}"


def _numeric_cell(value):
    if isinstance(value, str):
        return decimal_comma(value) if value.strip() else None
    return value


def _numbers(frame, name, field):
    raw = frame[name]
    if not pd.api.types.is_numeric_dtype(raw):
        # pandas' dtype inference on map() can round object integers with nulls.
        raw = pd.Series((_numeric_cell(value) for value in raw), index=raw.index, name=name, dtype=object)
    try:
        numbers = _column(raw.to_frame(), name, field, preserve_integers=True)
    except FieldError:
        raise
    except (TypeError, ValueError, OverflowError) as error:
        raise FieldError(field, f'Column "{name}" must contain finite numbers.') from error
    if not numbers.notna().any():
        raise FieldError(field, f'Column "{name}" has no numeric values to extract.')
    return numbers


def _check_shape(rows, columns):
    if columns > MAX_COLUMNS or rows * columns > MAX_CELLS:
        raise FieldError(OUTPUT, f"The result would have {rows:,} rows and {columns:,} columns, "
                                 "exceeding the worksheet size limit.")


def _groups(titles, repeats, reserved):
    """Choose unique physical headers while keeping replicate bands together."""
    used = set(reserved)
    groups = []
    for title in titles:
        # Workspace loading trims headers before looking up worksheet roles.
        title = title.strip()
        base = title
        suffix = 1
        while True:
            headers = [f"{base} [{index}]" for index in range(1, repeats + 1)] if repeats > 1 else [base]
            if used.isdisjoint(headers):
                break
            suffix += 1
            base = f"{title} ({suffix})"
        groups.append(headers)
        used.update(headers)
    return groups


def _place(cells, key, value, position):
    if _missing(value):
        return False
    if key in cells:
        raise FieldError(SUBJECT, f"Source row {position + 1} assigns a second value to the same subject and cell.")
    cells[key] = value
    return True


def _table(kind, rows, groups, repeats, cells, dtype, *, titles=None, x=None, subjects=None):
    """Materialize a sparse layout once its dense worksheet size is known."""
    leading = {}
    if titles is not None:
        leading[_ROW_TITLE] = pd.array([titles.get(row) for row in rows], dtype="string")
    if x is not None:
        name, coordinates, x_dtype = x
        name = name.strip() or "X"
        name = f"{name} (X)" if name in leading else name
        leading[name] = pd.array([coordinates.get(row) for row in rows], dtype=x_dtype)
    y_groups = _groups(groups.values(), len(repeats), leading)
    y_names = [name for group in y_groups for name in group]
    row_lookup = None if isinstance(rows, range) else {row: index for index, row in enumerate(rows)}
    group_offsets = {group: index * len(repeats) for index, group in enumerate(groups)}
    slots = {replicate: index for index, replicate in enumerate(repeats)}

    if pd.api.types.is_integer_dtype(dtype):
        values = np.zeros((len(y_names), len(rows)), dtype=getattr(dtype, "numpy_dtype", dtype))
        missing = np.ones(values.shape, dtype=bool)
        for (row, group, slot), value in cells.items():
            column = group_offsets[group] + slots[slot]
            position = row_lookup[row] if row_lookup is not None else row
            values[column, position] = value
            missing[column, position] = False
        data = {name: pd.arrays.IntegerArray(value, mask) for name, value, mask in
                zip(y_names, values, missing, strict=True)}
    else:
        values = np.full((len(y_names), len(rows)), np.nan)
        for (row, group, slot), value in cells.items():
            position = row_lookup[row] if row_lookup is not None else row
            values[group_offsets[group] + slots[slot], position] = value
        data = dict(zip(y_names, values, strict=True))

    result = pd.DataFrame({**leading, **data})
    result.attrs["table_format"] = "XY with replicates" if kind == "XY" and len(repeats) > 1 else kind.lower()
    result.attrs["worksheet_roles"] = {"x": [name] if x is not None else [], "y": y_groups}
    if titles is not None:
        result.attrs["row_title_column"] = _ROW_TITLE
    if subjects is not None:
        result.attrs["replicate_labels"] = [str(subject) for subject in subjects]
    return result


def _grouped(frame, names, y, *, complete, prefix):
    row_name, column_name, subject_name = (names[field] for field in (ROW_FACTOR, COLUMN_FACTOR, SUBJECT))
    subjects = frame[subject_name] if subject_name is not None else repeat(None)
    cells, occupied = {}, defaultdict(int)
    row_levels, column_levels, subject_levels = set(), set(), set()
    for position, (row, column, subject, value) in enumerate(zip(frame[row_name], frame[column_name], subjects, y)):
        row = _value(row, ROW_FACTOR, integer=True)
        column = _value(column, COLUMN_FACTOR, integer=True)
        subject = _value(subject, SUBJECT)
        if row is None or column is None or (subject_name is not None and subject is None):
            continue
        if complete and _missing(value):
            continue
        row_levels.add(row)
        column_levels.add(column)
        if subject_name is None:
            slot = occupied[row, column]
            occupied[row, column] += 1
        else:
            slot = subject
            subject_levels.add(subject)
        _place(cells, (row, column, slot), value, position)
    if not cells:
        raise FieldError(ROW_FACTOR, "No observations have a response and all selected factors or subjects.")

    repeat_count = len(subject_levels) if subject_name is not None else max(occupied.values())
    _check_shape(len(row_levels), 1 + len(column_levels) * repeat_count)
    rows = _ordered(row_levels)
    repeats = _ordered(subject_levels) if subject_name is not None else range(repeat_count)
    titles = {row: _label(row, row_name if prefix else None) for row in rows}
    groups = {column: _label(column, column_name if prefix else None) for column in _ordered(column_levels)}
    table = _table("Grouped", rows, groups, repeats, cells, y.dtype, titles=titles,
                   subjects=repeats if subject_name is not None else None)
    return table, len(cells)


def _flat(frame, kind, names, y, *, complete, prefix):
    """Place Column and XY values without losing repeated observations."""
    xy = kind == "XY"
    x_name = names.get(X)
    group_name, subject_name, title_name = (names[field] for field in (GROUP, SUBJECT, TITLES))
    grouped, matched = group_name is not None, subject_name is not None
    titled = title_name is not None or (matched and not xy)
    x = _numbers(frame, x_name, X) if xy else None
    xs = x if xy else repeat(None)
    groups = frame[group_name] if grouped else repeat(names[RESPONSE])
    subjects = frame[subject_name] if matched else repeat(None)
    raw_titles = frame[title_name] if title_name is not None else repeat(None)
    prefix_columns = int(titled) + int(xy)
    if not complete:
        _check_shape(len(frame), 1 + prefix_columns)

    cells, occurrences = {}, defaultdict(int)
    row_lookup, titles, coordinates = {}, {}, {}
    group_levels, subject_levels = set(), set()
    for position, (coordinate, group, subject, raw_title, value) in enumerate(zip(xs, groups, subjects, raw_titles, y)):
        coordinate = None if _missing(coordinate) else coordinate
        group = _value(group, GROUP, integer=True)
        subject = _value(subject, SUBJECT)
        title = (None if _missing(raw_title) else _label(raw_title, title_name if prefix else None))
        if matched and not xy and title_name is None and subject is not None:
            title = _label(subject, subject_name if prefix else None)
        has_key = group is not None and (not xy or coordinate is not None) and (not matched or subject is not None)
        present = has_key and not _missing(value)
        if complete and not present:
            continue
        if group is not None:
            group_levels.add(group)

        if matched:
            row_key = coordinate if xy else subject
            if row_key is None:
                continue
            position_out = row_lookup.setdefault(row_key, len(row_lookup) if complete else position)
            if xy and subject is not None:
                subject_levels.add(subject)
        elif complete and grouped:
            # Align equal X/row labels across groups by occurrence, while allowing
            # repeated X values or labels within the same group.
            match_key = (coordinate, title)
            occurrence = occurrences[group, match_key]
            occurrences[group, match_key] += 1
            position_out = row_lookup.setdefault((match_key, occurrence), len(row_lookup))
        elif complete:
            position_out = len(cells)
        else:
            position_out = position
        if coordinate is not None:
            coordinates[position_out] = coordinate
        if title is not None:
            if position_out in titles and titles[position_out] != title:
                raise FieldError(TITLES, f"Source row {position + 1} has a conflicting title for the same result row.")
            titles[position_out] = title
        if present:
            _place(cells, (position_out, group, subject if matched and xy else 0), value, position)
    if not cells:
        focus = SUBJECT if matched else GROUP if grouped else RESPONSE
        raise FieldError(focus, "No observations have a response and all selected destination values.")

    row_count = (len(row_lookup) if matched or grouped else len(cells)) if complete else len(frame)
    repeat_count = len(subject_levels) if matched and xy else 1
    _check_shape(row_count, prefix_columns + len(group_levels) * repeat_count)
    rows = range(row_count)
    repeats = _ordered(subject_levels) if matched and xy else (0,)
    display_groups = {group: _label(group, group_name if prefix else None) for group in _ordered(group_levels)}
    x_column = None
    if xy:
        x_dtype = x.dtype if pd.api.types.is_integer_dtype(x.dtype) else "Float64"
        x_column = (x_name, coordinates, x_dtype)
    table = _table(kind, rows, display_groups, repeats, cells, y.dtype, titles=titles if titled else None,
                   x=x_column, subjects=repeats if matched and xy else None)
    return table, len(cells)


def _weight(value):
    """Parse the increment without rounding textual integers through floats."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, Integral):
        weight = int(value)
    elif isinstance(value, Real):
        if not np.isfinite(value) or value != int(value):
            return None
        weight = int(value)
    elif isinstance(value, (str, Decimal)):
        try:
            weight = Decimal(decimal_comma(value))
        except InvalidOperation:
            return None
        if not weight.is_finite() or weight != weight.to_integral_value():
            return None
    else:
        return None
    if weight < 0:
        return None
    if weight > _MAX_COUNT:
        raise FieldError(COUNT, "A count exceeds the supported integer range.")
    return int(weight)


def _contingency(frame, names, *, prefix):
    row_name, column_name, count_name = (names[field] for field in (TREATMENT, OUTCOME, COUNT))
    weights = frame[count_name] if count_name is not None else repeat(1)
    rows, columns = set(), set()
    totals = defaultdict(int)
    used = invalid = 0
    for row, column, weight in zip(frame[row_name], frame[column_name], weights):
        row, column = _value(row, TREATMENT), _value(column, OUTCOME)
        if row is None or column is None or _missing(weight):
            continue
        weight = _weight(weight)
        if weight is None:
            invalid += 1
            continue
        total = totals[row, column] + weight
        if total > _MAX_COUNT:
            raise FieldError(COUNT, "The total for a contingency cell exceeds the supported integer range.")
        totals[row, column] = total
        rows.add(row)
        columns.add(column)
        used += 1
    if not totals:
        raise FieldError(COUNT if count_name is not None else TREATMENT,
                         "No observations have both categories and a usable count.")

    _check_shape(len(rows), 1 + len(columns))
    row_levels, column_levels = _ordered(rows), _ordered(columns)
    row_labels = [_label(row, row_name if prefix else None) for row in row_levels]
    column_labels = [_label(column, column_name if prefix else None) for column in column_levels]
    y_groups = _groups(column_labels, 1, (_ROW_TITLE,))
    table = pd.DataFrame({_ROW_TITLE: pd.array(row_labels, dtype="string"), **{
        names[0]: np.fromiter((totals.get((row, column), 0) for row in row_levels), dtype=np.uint64,
                              count=len(rows))
        for names, column in zip(y_groups, column_levels, strict=True)
    }})
    table.attrs.update(table_format="contingency", row_title_column=_ROW_TITLE,
                       worksheet_roles={"x": [], "y": y_groups})
    return table, used, invalid


def extract_rearrange(frame, options):
    """Return the worksheet and row counts from an exclusion-masked input frame.

    Worksheet type and column roles live in attrs so Dataset can adopt the
    result. Sparse Column/XY outputs retain source positions. Compact outputs
    combine compatible rows and keep the order of first occurrence. Grouped
    replicates without subjects fill slots in source order within each cell.
    """
    kind = options.get(OUTPUT, "XY")
    if not isinstance(kind, str) or kind not in EXTRACT_FORMATS:
        raise FieldError(OUTPUT, "Choose XY, Column, Grouped or Contingency.")
    if not frame.columns.is_unique:
        raise FieldError(OUTPUT, "Each source variable must have a unique name.")
    names = {}
    for field in EXTRACT_FIELDS[kind]:
        name = options.get(field)
        if (name is None or (isinstance(name, str) and not name)) and field in EXTRACT_OPTIONAL_FIELDS:
            names[field] = None
        elif not isinstance(name, str) or name not in frame:
            raise FieldError(field, f"Choose a column for {field}.")
        else:
            names[field] = name
    prefix = options.get(PREFIX, False)
    complete = options.get(COMPLETE, True)
    invalid = 0
    if kind == "Contingency":
        table, used, invalid = _contingency(frame, names, prefix=prefix)
    else:
        y = _numbers(frame, names[RESPONSE], RESPONSE)
        if kind == "Grouped":
            table, used = _grouped(frame, names, y, complete=complete, prefix=prefix)
        else:
            table, used = _flat(frame, kind, names, y, complete=complete, prefix=prefix)
    notes = {"Input rows": len(frame), "Rows used": used,
             "Rows with missing data": len(frame) - used - invalid}
    if kind == "Contingency" and names[COUNT] is not None:
        notes["Invalid counts skipped"] = invalid
    return Result({EXTRACT_TABLE: table, "Notes": _report(notes)})
