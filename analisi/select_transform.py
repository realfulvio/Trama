"""Filter a multiple-variable worksheet and calculate additional columns."""
from decimal import Decimal, InvalidOperation
from operator import eq, ge, gt, le, lt, ne

import numpy as np
import pandas as pd

from .data import MAX_CELLS, MAX_COLUMNS, decimal_comma, formula
from .processing import FieldError
from .reporting import Result


SELECT_TRANSFORM = "Select and Transform"
FILTERS, CALCULATED = "Row filters", "Calculated variables"
MISSING = ("Is missing", "Is not missing")
COMPARISONS = {"=": eq, "!=": ne, ">": gt, ">=": ge, "<": lt, "<=": le}
TARGETS = ("Number", "Text", "Column")
MAX_RULES = 32
SELECT_OPTIONS = {"Variables": "Multiple (optional)", "First row": "Text", "Last row": "Text"}


def _numeric(series):
    dtype = series.dtype
    return pd.api.types.is_integer_dtype(dtype) or pd.api.types.is_float_dtype(dtype)


def _missing(series):
    if _numeric(series):
        return ~np.isfinite(series.to_numpy(dtype=float, na_value=np.nan))
    return series.astype("string").str.strip().fillna("").eq("").to_numpy(dtype=bool)


def _row_number(options, name, default):
    raw = options.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw) if type(raw) in {int, str} else 0
    except ValueError:
        value = 0
    if not 1 <= value <= MAX_CELLS:
        raise FieldError(name, f"{name} must be a row number from 1 to {MAX_CELLS:,}, or blank.")
    return value


def _column(frame, name, field):
    if not isinstance(name, str) or name not in frame:
        raise FieldError(FILTERS, f"{field}: choose an existing variable.")
    return frame[name]


def _number(series, value, field):
    if not _numeric(series):
        raise FieldError(FILTERS, f"{field}: choose a numeric variable for a number comparison.")
    try:
        number = Decimal(decimal_comma(value))
    except InvalidOperation:
        raise FieldError(FILTERS, f"{field}: enter a finite number.") from None
    if not number.is_finite():
        raise FieldError(FILTERS, f"{field}: enter a finite number.")
    if pd.api.types.is_float_dtype(series):
        number = float(number)
        if not np.isfinite(number):
            raise FieldError(FILTERS, f"{field}: enter a finite number within the floating-point range.")
    return number


def _comparison(frame, rule, position):
    field = f"Condition {position}"
    if not isinstance(rule, dict):
        raise FieldError(FILTERS, f"{field}: invalid condition.")
    left = _column(frame, rule.get("column"), field)
    missing = _missing(left)
    operation = rule.get("operator")
    if operation in MISSING:
        return missing if operation == MISSING[0] else ~missing
    target, value = rule.get("target"), rule.get("value")
    if (not isinstance(operation, str) or operation not in COMPARISONS
            or target not in TARGETS or not isinstance(value, str) or len(value) > 2048):
        raise FieldError(FILTERS, f"{field}: choose an operator and enter a comparison value.")
    if target == "Column":
        right = _column(frame, value, field)
        missing |= _missing(right)
        if _numeric(left) != _numeric(right):
            raise FieldError(FILTERS, f"{field}: compare two variables of the same type.")
        text = not _numeric(left)
        if text:
            right = right.astype("string")
        elif left.dtype != right.dtype and (
            pd.api.types.is_integer_dtype(left) or pd.api.types.is_integer_dtype(right)
        ):
            # Python scalar comparisons preserve large integers when types differ.
            left, right = left.astype(object), right.astype(object)
    elif target == "Text":
        right, text = value, True
    else:
        right, text = _number(left, value, field), False
    if text:
        if operation not in {"=", "!="}:
            raise FieldError(FILTERS, f"{field}: text comparisons support only = and !=.")
        left = left.astype("string")
    matches = COMPARISONS[operation](left, right)
    return ~missing & matches.fillna(False).to_numpy(dtype=bool)


def _rules(options, field):
    value = options.get(field, [])
    if not isinstance(value, list) or len(value) > MAX_RULES:
        raise FieldError(field, f"Enter at most {MAX_RULES} items.")
    return value


def _derived(source, record, position):
    field = f"Calculated variable {position}"
    if not isinstance(record, dict):
        raise FieldError(CALCULATED, f"{field}: invalid definition.")
    name, expression = record.get("name"), record.get("expression")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 160 or "\n" in name or "\r" in name:
        raise FieldError(CALCULATED, f"{field}: enter a name of up to 160 characters.")
    name = name.strip()
    if name in source:
        raise FieldError(CALCULATED, f'{field}: "{name}" already exists.')
    if not isinstance(expression, str):
        raise FieldError(CALCULATED, f'{field}: enter a formula for "{name}".')
    try:
        source[name] = formula(source, expression)
    except ValueError as error:
        raise FieldError(CALCULATED, f'"{name}": {error}') from error
    return name


def select_transform(frame, options):
    """Keep rows satisfying every condition and evaluate formulas on those rows."""
    columns = options.get("Variables", list(frame.columns))
    if (not frame.columns.is_unique or not isinstance(columns, list) or any(not isinstance(name, str) or name not in frame for name in columns)
            or len(set(columns)) != len(columns)):
        raise FieldError("Variables", "Choose distinct existing variables.")
    filters, calculated = _rules(options, FILTERS), _rules(options, CALCULATED)
    width = len(columns) + len(calculated)
    if not width:
        raise FieldError("Variables", "Choose at least one output column or calculated variable.")
    if width > MAX_COLUMNS:
        raise FieldError("Variables", f"The output supports at most {MAX_COLUMNS} columns.")
    first = _row_number(options, "First row", 1)
    last = _row_number(options, "Last row", max(len(frame), first))
    if last < first:
        raise FieldError("Last row", "Last row must be at or after the first row.")
    selected = frame.iloc[first - 1:last]
    if len(selected) * len(filters) > 4 * MAX_CELLS:
        raise FieldError(FILTERS, "The selection exceeds the work limit. Reduce the row range or conditions.")
    mask = np.ones(len(selected), dtype=bool)
    for position, rule in enumerate(filters, 1):
        mask &= _comparison(selected, rule, position)
    if mask.sum() * (len(frame.columns) + len(calculated)) > MAX_CELLS:
        raise FieldError(CALCULATED, "The selected rows and variables exceed the cell limit.")
    source = selected.iloc[mask].reset_index(drop=True)
    names = [*columns]
    for position, record in enumerate(calculated, 1):
        names.append(_derived(source, record, position))
    output = source.loc[:, names].copy()
    output.attrs = {"table_format": "multivariable"}
    return Result({"Selected data": output})
