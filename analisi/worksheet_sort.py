"""Pure planning, validation, and stable permutation computation for sorting worksheet rows."""
from __future__ import annotations

from dataclasses import dataclass
import math
from operator import itemgetter
import unicodedata

import numpy as np
import pandas as pd

from .grid_headings import heading_bands
from .i18n import active_language
from .worksheet_row_identity import validate_permutation

ASCENDING = "ascending"
DESCENDING = "descending"
DIRECTIONS = (ASCENDING, DESCENDING)
ROW_TITLE_NAMES = frozenset({"row title", "row titles"})

_MISSING_SENTINEL = type(pd.NA)
_MAX_EXACT_FLOAT_INT = 2**53

_TEXT = {
    "title": ("Sort rows", "Ordina righe"),
    "action": ("Sort rows…", "Ordina righe…"),
    "action_by_x": ("Sort by X", "Ordina per X"),
    "action_by_row_title": ("Sort by row title", "Ordina per titolo di riga"),
    "sheet": ("Worksheet", "Foglio"),
    "scope": ("Scope", "Ambito"),
    "scope_value": ("Whole worksheet ({rows:,} rows)", "Foglio intero ({rows:,} righe)"),
    "key": ("Sort by", "Ordina per"),
    "direction": ("Direction", "Direzione"),
    "ascending": ("Ascending", "Crescente"),
    "descending": ("Descending", "Decrescente"),
    "missing_note": (
        "Missing values stay last in both directions.",
        "I valori mancanti restano in fondo in entrambe le direzioni.",
    ),
    "identity_note": (
        "Rows are already in this order.",
        "Le righe sono già in questo ordine.",
    ),
    "ok": ("Sort", "Ordina"),
    "cancel": ("Cancel", "Annulla"),
    "done": (
        "Sorted {rows:,} rows by {key} ({direction}).",
        "Ordinate {rows:,} righe per {key} ({direction}).",
    ),
    "already_sorted": (
        "Rows are already ordered by {key} ({direction}).",
        "Le righe sono già ordinate per {key} ({direction}).",
    ),
    "err.locked": (
        "Sheet frozen or read-only. Unfreeze it before sorting rows.",
        "Foglio congelato o di sola lettura. Sbloccalo prima di ordinare le righe.",
    ),
    "err.reorder_unavailable": (
        "Rows in this table format cannot be reordered.",
        "Le righe in questo formato di tabella non possono essere riordinate.",
    ),
    "err.formula_key": (
        "Calculated columns cannot be used as sort keys because their values may depend on row order.",
        "Le colonne calcolate non possono essere usate come chiave di ordinamento perché possono dipendere dall'ordine delle righe.",
    ),
    "err.unknown_key": (
        "Choose an existing source column to sort by.",
        "Scegli una colonna di origine esistente per ordinare.",
    ),
    "err.direction": (
        "Choose Ascending or Descending order.",
        "Scegli l'ordinamento crescente o decrescente.",
    ),
    "err.stale": (
        "The worksheet or project changed while the dialog was open. Reopen Sort rows.",
        "Il foglio o il progetto è cambiato mentre la finestra era aperta. Riapri Ordina righe.",
    ),
    "err.empty": (
        "This worksheet has no source columns to sort.",
        "Questo foglio non ha colonne di origine da ordinare.",
    ),
}


def sort_text(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


@dataclass(frozen=True)
class SortKeyOption:
    name: str
    display_column: int
    raw_column: int
    is_row_title: bool
    is_x: bool
    is_numeric: bool


@dataclass(frozen=True)
class RowSortPlan:
    key_name: str
    raw_column: int
    display_column: int
    direction: str
    row_count: int
    order: np.ndarray
    inverse: np.ndarray
    changed: bool


def sortable_columns(dataset) -> list[SortKeyOption]:
    """Return selectable source columns in visible grid order, excluding calculated columns."""
    raw = dataset.raw
    columns = tuple(dataset.columns)
    indices = tuple(dataset.source_indices)
    formulas = set(dataset.formulas)
    calculated = {pos for pos, name in enumerate(columns) if name in formulas}
    names = [str(name) for name in columns]
    bands, roles = heading_bands(raw, names, len(raw.columns), dataset.table_format, calculated=calculated)
    dtypes = raw.dtypes
    options: list[SortKeyOption] = []
    seen: set[str] = set()
    for display_col, (name, raw_col) in enumerate(zip(columns, indices)):
        if raw_col is None or name in formulas or name in seen:
            continue
        seen.add(name)
        band = bands[display_col][2] if display_col < len(bands) else ""
        role = roles[display_col] if display_col < len(roles) else ""
        folded = name.casefold()
        is_row_title = band == "Row titles" or folded in ROW_TITLE_NAMES
        is_x = not is_row_title and (band == "X" or role == "X" or folded == "x")
        dtype = dtypes.iloc[raw_col]
        is_numeric = bool(pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype))
        options.append(SortKeyOption(
            name=name,
            display_column=display_col,
            raw_column=raw_col,
            is_row_title=is_row_title,
            is_x=is_x,
            is_numeric=is_numeric,
        ))
    return options


def x_sort_column(dataset) -> str | None:
    """Return the X source column name when applicable, else ``None``."""
    options = sortable_columns(dataset)
    x_opts = [opt for opt in options if opt.is_x]
    if not x_opts:
        return None
    for opt in x_opts:
        if opt.name.casefold() == "x":
            return opt.name
    for opt in x_opts:
        if opt.is_numeric:
            return opt.name
    return x_opts[0].name


def row_title_sort_column(dataset) -> str | None:
    """Return the Row title source column name when applicable, else ``None``."""
    for opt in sortable_columns(dataset):
        if opt.is_row_title:
            return opt.name
    return None


def validate_sort_key(dataset, key) -> SortKeyOption:
    """Resolve and validate ``key`` (source column name or visible column index)."""
    options = sortable_columns(dataset)
    if isinstance(key, int) and not isinstance(key, bool):
        columns = dataset.columns
        indices = dataset.source_indices
        if not (0 <= key < len(columns)):
            raise ValueError(sort_text("err.unknown_key"))
        if columns[key] in dataset.formulas or indices[key] is None:
            raise ValueError(sort_text("err.formula_key"))
        for opt in options:
            if opt.display_column == key:
                return opt
        raise ValueError(sort_text("err.unknown_key"))
    if isinstance(key, str):
        if key in dataset.formulas:
            raise ValueError(sort_text("err.formula_key"))
        for opt in options:
            if opt.name == key:
                return opt
    raise ValueError(sort_text("err.unknown_key"))


def _is_missing_scalar(value) -> bool:
    if value is None or value is _MISSING_SENTINEL or isinstance(value, _MISSING_SENTINEL):
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text_fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _numeric_float_order(values: np.ndarray, direction: str) -> np.ndarray:
    missing = np.isnan(values)
    valid_idx = np.flatnonzero(~missing)
    missing_idx = np.flatnonzero(missing)
    if len(valid_idx) <= 1:
        return np.concatenate((valid_idx, missing_idx)).astype(np.intp, copy=False)
    valid_vals = values[valid_idx]
    key_vals = valid_vals if direction == ASCENDING else -valid_vals
    sorted_valid = valid_idx[np.argsort(key_vals, kind="mergesort")]
    return np.concatenate((sorted_valid, missing_idx)).astype(np.intp, copy=False)


def compute_sort_order(series: pd.Series, direction: str = ASCENDING) -> np.ndarray:
    """Compute a stable row-index permutation placing missing values last in both directions."""
    if direction not in DIRECTIONS:
        raise ValueError(sort_text("err.direction"))
    length = len(series)
    if length <= 1:
        return np.arange(length, dtype=np.intp)

    dtype = series.dtype
    reverse = direction == DESCENDING
    if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
        if pd.api.types.is_integer_dtype(dtype) and getattr(dtype, "itemsize", 0) >= 8:
            # Guard 64-bit integer precision outside exact float64 range (2**53).
            non_na = series.dropna()
            if not non_na.empty:
                lo = int(non_na.min())
                hi = int(non_na.max())
                if lo < -_MAX_EXACT_FLOAT_INT or hi > _MAX_EXACT_FLOAT_INT:
                    items = []
                    missing = []
                    for idx, val in enumerate(series.tolist()):
                        if _is_missing_scalar(val):
                            missing.append(idx)
                        else:
                            items.append((idx, int(val)))
                    items.sort(key=itemgetter(1), reverse=reverse)
                    return np.asarray([idx for idx, _ in items] + missing, dtype=np.intp)
        values = series.to_numpy(dtype=np.float64, na_value=np.nan)
        return _numeric_float_order(values, direction)

    raw_values = series.tolist()
    # Check whether an object column stores purely numeric scalars (+ missing).
    if dtype == object or isinstance(dtype, pd.CategoricalDtype):
        all_numeric = True
        for val in raw_values:
            if _is_missing_scalar(val):
                continue
            if isinstance(val, bool) or not isinstance(val, (int, float, np.number)):
                all_numeric = False
                break
        if all_numeric:
            float_vals = np.array(
                [np.nan if _is_missing_scalar(v) else float(v) for v in raw_values],
                dtype=np.float64,
            )
            return _numeric_float_order(float_vals, direction)

    items = []
    missing = []
    has_mixed_non_str = False
    for idx, val in enumerate(raw_values):
        if _is_missing_scalar(val):
            missing.append(idx)
        elif isinstance(val, str):
            items.append((idx, _text_fold(val)))
        else:
            has_mixed_non_str = True
            items.append((idx, val))
    if has_mixed_non_str:
        # Compare heterogeneous non-missing scalars safely by category then normalized value.
        safe_items = []
        for idx, val in items:
            if isinstance(val, (int, float, np.number)) and not isinstance(val, bool):
                safe_items.append((idx, (0, float(val))))
            else:
                safe_items.append((idx, (1, _text_fold(str(val)))))
        safe_items.sort(key=itemgetter(1), reverse=reverse)
        return np.asarray([idx for idx, _ in safe_items] + missing, dtype=np.intp)

    # Python's Timsort with reverse=True keeps original relative order for equal folded keys.
    items.sort(key=itemgetter(1), reverse=reverse)
    return np.asarray([idx for idx, _ in items] + missing, dtype=np.intp)


def plan_row_sort(dataset, key, direction: str = ASCENDING, *, locked: bool = False,
                  reorder_allowed: bool = True) -> RowSortPlan:
    """Validate worksheet state, sort key, and direction and compute the resulting permutation."""
    if locked:
        raise ValueError(sort_text("err.locked"))
    if not reorder_allowed:
        raise ValueError(sort_text("err.reorder_unavailable"))
    option = validate_sort_key(dataset, key)
    order = validate_permutation(
        compute_sort_order(dataset.raw.iloc[:, option.raw_column], direction),
        len(dataset.raw),
    )
    length = len(order)
    inverse = np.empty(length, dtype=np.intp)
    if length:
        inverse[order] = np.arange(length, dtype=np.intp)
    changed = not np.array_equal(order, np.arange(length, dtype=np.intp))
    return RowSortPlan(
        key_name=option.name,
        raw_column=option.raw_column,
        display_column=option.display_column,
        direction=direction,
        row_count=length,
        order=order,
        inverse=inverse,
        changed=changed,
    )


def remap_selection_after_sort(inverse: np.ndarray, length: int, box, current_row: int | None,
                               current_col: int | None):
    """Return ``(top, left, bottom, right, active_row, active_col)`` following the moved rows.

    If a multi-row contiguous selection scatters across non-adjacent rows, avoid stretching
    selection over unrelated rows by focusing only on the moved active cell's row/columns.
    """
    if length <= 0:
        return None
    active_row = int(inverse[current_row]) if current_row is not None and 0 <= current_row < length else None
    active_col = current_col if current_col is not None and current_col >= 0 else 0
    if box is None:
        if active_row is None:
            return None
        return (active_row, active_col, active_row, active_col, active_row, active_col)
    top, left, bottom, right = box
    if top >= length:
        if active_row is None:
            return None
        return (active_row, active_col, active_row, active_col, active_row, active_col)
    clamped_bottom = min(bottom, length - 1)
    mapped = sorted(int(inverse[row]) for row in range(max(0, top), clamped_bottom + 1))
    if not mapped:
        return None
    is_contiguous = (mapped[-1] - mapped[0] + 1) == len(mapped)
    if is_contiguous:
        target_row = active_row if active_row is not None and mapped[0] <= active_row <= mapped[-1] else mapped[0]
        return (mapped[0], left, mapped[-1], right, target_row, active_col)
    focus_row = active_row if active_row is not None else mapped[0]
    focus_col = max(left, min(right, active_col))
    return (focus_row, left, focus_row, right, focus_row, focus_col)
