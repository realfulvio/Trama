"""Worksheet variable types and explicit column conversions."""
from decimal import Decimal
import math

import pandas as pd

from .i18n import tr

VARIABLE_TYPES = "variable_types"
TYPES = ("numeric", "text", "categorical")


def validated_types(types, columns):
    if (not isinstance(types, dict)
            or any(name not in columns or kind not in TYPES for name, kind in types.items())):
        raise ValueError("Invalid saved worksheet variable types.")
    return types


def inferred_type(series):
    return "numeric" if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series) else "text"


def convert_type(series, kind):
    from .data import _table, decimal_comma

    if kind in {"text", "categorical"}:
        return series.astype("string")
    if inferred_type(series) == "numeric":
        return series
    if kind == "auto":
        inferred = _table([series.name], [[value] for value in series], decimal_mark=",").iloc[:, 0]
        inferred.index = series.index
        return inferred

    original = series.astype("string").replace("", pd.NA)
    numbers = original.map(decimal_comma, na_action="ignore")
    parsed = pd.to_numeric(numbers, errors="coerce", dtype_backend="numpy_nullable")
    present = original.notna()
    if parsed.notna().sum() != present.sum() or not all(math.isfinite(value) for value in parsed[present]):
        raise ValueError(tr("variables.error.numeric", name=series.name))
    for value, converted in zip(numbers[present], parsed[present], strict=True):
        exact = Decimal(value)
        if exact == exact.to_integral_value() and exact != int(converted):
            raise ValueError(tr("variables.error.numeric", name=series.name))
    return parsed
