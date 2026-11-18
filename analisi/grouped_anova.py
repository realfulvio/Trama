"""Prepare replicated Grouped worksheets for ordinary two-factor ANOVA."""
import numpy as np
import pandas as pd

from .data import MAX_CELLS, _worksheet_roles
from .field_error import FieldError
from .processing import _column
from .worksheet_series import series_columns, series_labels

METHOD = "Grouped two-way ANOVA"
ROWS = "Row labels"
VALUES = "Y columns"
ROW_NAME = "Row factor name"
COLUMN_NAME = "Column factor name"
INTERACTION = "Include interaction"


def grouped_inputs(frame, options):
    """Return complete observations and their factor names, without estimating the model."""
    if not frame.columns.is_unique:
        raise FieldError(VALUES, "Worksheet column names must be unique.")
    row_labels = options.get(ROWS)
    if not isinstance(row_labels, str) or row_labels not in frame:
        raise FieldError(ROWS, "Choose the column with the row factor levels.")

    selected = options.get(VALUES)
    if selected is None or isinstance(selected, (list, tuple)) and not selected:
        roles = _worksheet_roles(frame)
        selected = ([name for group in roles["y"] for name in group if name != row_labels]
                    if roles else [name for name in frame if name != row_labels])
    if (not isinstance(selected, (list, tuple)) or not selected
            or any(not isinstance(name, str) or name not in frame for name in selected)
            or row_labels in selected or len(set(selected)) != len(selected)):
        raise FieldError(VALUES, "Choose distinct numeric columns separate from the row labels.")
    if len(frame) * len(selected) > MAX_CELLS:
        raise FieldError(VALUES, "The selected two-way ANOVA data exceed the worksheet size limit.")

    row_factor = _factor_name(options, ROW_NAME, "Row factor")
    column_factor = _factor_name(options, COLUMN_NAME, "Column factor")
    if row_factor == column_factor:
        raise FieldError(COLUMN_NAME, "Choose different names for the two factors.")
    response = "Response"
    while response in {row_factor, column_factor}:
        response += " (Y)"

    groups = series_columns(frame, selected, recognize_replicates=True)
    labels = frame[row_labels].astype("string")
    mask = np.zeros(len(frame), dtype=bool)
    parts = []
    for group, level in zip(groups, series_labels(groups), strict=True):
        values = np.column_stack([_column(frame, name, VALUES).to_numpy(dtype=float) for name in group])
        rows, repeats = np.where(np.isfinite(values))
        if not rows.size:
            continue
        mask[rows] = True
        parts.append(pd.DataFrame({
            response: values[rows, repeats],
            row_factor: labels.iloc[rows].to_numpy(),
            column_factor: level,
        }))
    present = labels.iloc[mask]
    if present.isna().any() or present.str.strip().eq("").any() or present.duplicated().any():
        raise FieldError(ROWS, "Each included row needs a distinct, nonempty label.")
    if len(present) < 2:
        raise FieldError(ROWS, "At least two row levels must have observations.")
    if len(parts) < 2:
        raise FieldError(VALUES, "At least two column groups must have observations.")
    return pd.concat(parts, ignore_index=True), response, [row_factor, column_factor]


def _factor_name(options, field, default):
    name = options.get(field, "")
    if not isinstance(name, str) or len(name) > 160:
        raise FieldError(field, "Enter a factor name of up to 160 characters.")
    if name.strip() == "Residual":
        raise FieldError(field, 'Choose a factor name other than "Residual".')
    return name.strip() or default
