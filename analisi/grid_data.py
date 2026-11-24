"""Values-only clipboard operations on positional data table ranges."""
import copy
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO
from itertools import chain, repeat
import math
import sys

import numpy as np
import pandas as pd

from .data import (EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_FIXED_VALUES, EDITABLE_LEGACY_XY,
                   MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, _table, decimal_comma)
from .variable_types import VARIABLE_TYPES


def clipboard_rows(text, *, max_columns=MAX_COLUMNS, transpose=False):
    if len(text) > MAX_ENTRY:
        raise ValueError("The clipboard block exceeds the size limit.")
    rows, width = [], 1
    try:
        for row in csv.reader(StringIO(text, newline=""), dialect="excel-tab", strict=True):
            width = max(width, len(row))
            height = len(rows) + 1
            if (height if transpose else width) > max_columns or width * height > MAX_CELLS:
                raise ValueError("The clipboard block exceeds the table size limit.")
            rows.append(row)
    except csv.Error as error:
        raise ValueError("Could not read the tab-delimited clipboard values.") from error
    if not rows:
        raise ValueError("The clipboard has no tabular values.")
    rectangle = [row + [""] * (width - len(row)) for row in rows]
    return [list(column) for column in zip(*rectangle, strict=True)] if transpose else rectangle


def filter_clipboard_rows(rows, *, first=1, last=None, skip=0):
    """Keep the first selected row and then skip a fixed number between rows."""
    stop = len(rows) if last is None else last
    if not 1 <= first <= stop <= len(rows):
        raise ValueError(f"Choose a row range between 1 and {len(rows)}.")
    if skip < 0:
        raise ValueError("Rows to skip must be zero or more.")
    return rows[first - 1:stop:skip + 1]


def clipboard_decimal_mark():
    if sys.platform == "win32":
        from ctypes import create_unicode_buffer, windll

        separator = create_unicode_buffer(4)
        locale_sdecimal = 0x0000000E
        if windll.kernel32.GetLocaleInfoEx(None, locale_sdecimal, separator, len(separator)):
            if separator.value == ",":
                return ","
    return "."


def copy_block(frame, selection, excluded, *, decimal_mark="."):
    top, left, bottom, right = selection
    stream = StringIO(newline="")
    writer = csv.writer(stream, dialect="excel-tab")
    block = frame.iloc[top:bottom + 1, left:right + 1]
    blank = (None,) * (right - left + 1)
    rows = chain(block.itertuples(index=False, name=None), repeat(blank, bottom - top + 1 - len(block)))
    def cell_text(value, position):
        if position in excluded or pd.isna(value):
            return ""
        text = str(value)
        return text.replace(".", decimal_mark, 1) if isinstance(value, (float, np.floating)) else text

    for row_index, row in enumerate(rows, top):
        writer.writerow(cell_text(value, (row_index, col)) for col, value in enumerate(row, left))
        if stream.tell() > MAX_ENTRY:
            raise ValueError("Select a smaller range to copy.")
    return stream.getvalue()


def _numeric_values(column, values, *, protect_integers=False):
    integer = pd.api.types.is_integer_dtype(column.dtype)
    limits = np.iinfo(column.dtype.numpy_dtype) if integer else None
    numbers = []
    for value in values:
        value = decimal_comma(value.strip())
        if not value:
            numbers.append(pd.NA)
            continue
        try:
            number = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("This column requires a number.") from error
        if not number.is_finite():
            raise ValueError("Enter a finite number.")
        if integer and number == number.to_integral_value():
            if not limits.min <= number <= limits.max:
                raise ValueError("The integer exceeds this column's range.")
            numbers.append(int(number))
        else:
            converted = float(number)
            if not math.isfinite(converted) or (converted == 0 and number != 0):
                raise ValueError("The number exceeds the supported range.")
            if protect_integers and number == number.to_integral_value() and Decimal.from_float(converted) != number:
                raise ValueError("The numeric paste would reduce the precision of an integer.")
            numbers.append(converted)
    if integer and any(isinstance(value, float) for value in numbers):
        if (any(abs(value) > 2**53 for value in numbers if value is not pd.NA)
                or column.dropna().map(lambda value: abs(int(value)) > 2**53).any()):
            raise ValueError("A decimal paste would reduce the precision of this integer column.")
        column = column.astype("Float64")
    return column, numbers


def grow_rows(raw, height):
    """Create a source frame with additional blank rows and exact integers."""
    candidate = raw.copy()
    if height != len(raw):
        for name in raw.select_dtypes(include=["integer", "bool"]):
            candidate[name] = candidate[name].convert_dtypes()
        candidate = candidate.reset_index(drop=True).reindex(range(height))
    return candidate


def paste_block(dataset, top, left, rows):
    """Apply a whole rectangular block, including any growth, after validation."""
    raw = dataset.raw
    if (top < 0 or not 0 <= left < len(raw.columns) + len(dataset.formulas)
            or not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows)):
        raise ValueError("Select a valid cell and a rectangular block.")
    stop_row, stop_column = top + len(rows), left + len(rows[0])
    if dataset.formulas:
        span = dataset.source_span(left, stop_column)
        if span is None:
            raise ValueError("Calculated columns are edited using Formula. Select source cells for paste.")
        left, stop_column = span
    if dataset.table_format == EDITABLE_LEGACY_XY and (stop_row > len(raw) or (left < 4 and stop_column > 2)):
        raise ValueError("Edit existing X/Y coordinates here. Use Format to rename or style a series.")
    if dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES and (
        stop_row > len(raw) or stop_column > len(raw.columns)
        or any(left <= column < stop_column for column in dataset.locked_columns)
    ):
        raise ValueError("Edit only the numerical values of the existing graph data.")
    height, width = max(len(raw), stop_row), max(len(raw.columns), stop_column)
    if (width > max(MAX_COLUMNS, len(raw.columns)) or height * width > MAX_CELLS):
        raise ValueError("The paste would exceed the table size limit.")
    candidate = grow_rows(raw, height)
    for col, values in enumerate(zip(*rows, strict=True), left):
        if col >= len(candidate.columns):
            # Columns can only grow on the right, from an existing cell.
            if col != len(candidate.columns):
                raise ValueError("Select an existing cell to paste into.")
            name = f"Column {col + 1}"
            while name in candidate.columns:
                name += " (new)"
            candidate[name] = pd.Series(pd.NA, index=candidate.index, dtype="Int64")
        name = candidate.columns[col]
        series = candidate[name].copy()
        try:
            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
                if series.notna().any() or raw.attrs.get(VARIABLE_TYPES, {}).get(name) == "numeric":
                    if not hasattr(series.dtype, "numpy_dtype"):
                        series = series.astype("Float64") if pd.api.types.is_float_dtype(series) else series.convert_dtypes()
                    series, parsed = _numeric_values(series, values)
                else:
                    inferred = _table([name], [[value] for value in values], decimal_mark=",").iloc[:, 0]
                    series = series.astype(inferred.dtype)
                    if pd.api.types.is_float_dtype(inferred):
                        series, parsed = _numeric_values(series, values, protect_integers=True)
                    else:
                        parsed = inferred.array
            elif pd.api.types.is_bool_dtype(series):
                series = series.astype("boolean")
                choices = {"true": True, "false": False, "": pd.NA}
                try:
                    parsed = [choices[value.strip().casefold()] for value in values]
                except KeyError as error:
                    raise ValueError("This column requires TRUE or FALSE.") from error
            else:
                if series.dtype != "object":
                    series = series.astype("string")
                parsed = [value or pd.NA for value in values]
            series.iloc[top:stop_row] = parsed
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"{name}: {error}") from error
        candidate[name] = series
    preview = copy.copy(dataset)
    preview.raw = candidate
    preview.frame()
    if dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES:
        from .legacy_binary_bars import validate_bar_values
        from .legacy_emf_edit import edit_emf_preview
        from .legacy_pdf_stacks import validate_stack_values
        from .legacy_restore import LEGACY_GRAPH_STYLE, LEGACY_PREVIEW, SAVED_EDITABLE_GRAPH

        recipes = [options for method, options in dataset.analyses if method == SAVED_EDITABLE_GRAPH]
        if len(recipes) != 1:
            raise ValueError("The recovered graph is missing or ambiguous.")
        options, = recipes
        style = options.get(LEGACY_GRAPH_STYLE)
        if dataset.table_format == EDITABLE_LEGACY_EMF:
            edit_emf_preview(candidate, style, options.get(LEGACY_PREVIEW))
        else:
            validator = validate_bar_values if dataset.table_format == EDITABLE_LEGACY_COLUMNS else validate_stack_values
            validator(candidate, style)
    dataset.raw = candidate


def edit_cell_value(dataset, row, column, text):
    """Handle a typed expression in an empty variable without changing clipboard semantics."""
    expression = text.strip()
    if (row >= 0 and expression.startswith("=") and dataset.can_enter_formula(column)
            and dataset.source_indices[column] is not None and not dataset.column_has_values(column)):
        dataset.set_worksheet_formula(column, expression)
    else:
        paste_block(dataset, row, column, [[text]])


def clear_block(dataset, selection):
    """Clear the existing cells in a range and their exclusion flags atomically."""
    top, left, bottom, right = selection
    raw = dataset.raw
    if not (0 <= top <= bottom and 0 <= left <= right):
        raise ValueError("Select a valid cell range.")
    span = dataset.source_span(left, right + 1)
    if span is None:
        raise ValueError("Calculated columns cannot be cleared. Select source cells.")
    left, stop_column = span
    right = stop_column - 1
    if dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES or any(
            left <= column <= right for column in dataset.locked_columns):
        raise ValueError("Edit the supported values of the recovered graph individually.")
    stop = min(bottom + 1, len(raw))
    if top >= stop:
        return
    excluded = {(row, col) for row, col in dataset.excluded if not (top <= row < stop and left <= col <= right)}
    if excluded == dataset.excluded and raw.iloc[top:stop, left:right + 1].isna().all().all():
        return
    candidate = raw.copy()
    for column in range(left, right + 1):
        series = candidate.iloc[:, column].copy()
        if pd.api.types.is_integer_dtype(series) or pd.api.types.is_bool_dtype(series):
            series = series.convert_dtypes()
        series.iloc[top:stop] = pd.NA
        candidate.isetitem(column, series)
    preview = copy.copy(dataset)
    preview.raw, preview.excluded = candidate, excluded
    preview.frame()
    dataset.raw, dataset.excluded = candidate, excluded
