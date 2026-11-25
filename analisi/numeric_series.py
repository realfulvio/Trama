"""Pure engine for validating and generating arithmetic and geometric numeric series."""
from copy import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
import sys

import numpy as np
import pandas as pd

from .data import (EDITABLE_LEGACY_FIXED_VALUES, EDITABLE_LEGACY_XY, MAX_CELLS, MAX_COLUMNS, decimal_comma)
from .grid_headings import column_label
from .grid_data import grow_rows
from .i18n import active_language
from .variable_types import VARIABLE_TYPES
from .worksheet_number_format import display_decimal_mark

ARITHMETIC = "arithmetic"
GEOMETRIC = "geometric"
DEFAULT_SINGLE_CELL_COUNT = 10

_MAX_FLOAT_LOG = math.log(sys.float_info.max)
_MAX_EXACT_INT = 2**53
_MIN_SUBNORMAL_LOG = math.log(math.ldexp(1.0, -1074))

_TEXT = {
    "title": ("Create numeric series", "Crea serie numerica"),
    "action": ("Create numeric series…", "Crea serie numerica…"),
    "mode": ("Series type", "Tipo di serie"),
    "arithmetic": ("Arithmetic", "Aritmetica"),
    "geometric": ("Geometric", "Geometrica"),
    "first": ("First value", "Primo valore"),
    "count": ("Number of terms", "Numero di termini"),
    "step": ("Step", "Passo"),
    "ratio": ("Ratio", "Fattore"),
    "range": ("Target range", "Intervallo"),
    "preview": ("Preview", "Anteprima"),
    "insert": ("Insert", "Inserisci"),
    "cancel": ("Cancel", "Annulla"),
    "replace_warning": (
        "{occupied} of {total} target cells already contain values and will be replaced.",
        "{occupied} celle occupate su {total} saranno sostituite.",
    ),
    "confirm_replace": (
        "Confirm replacing the {occupied} occupied cell(s)",
        "Conferma la sostituzione delle {occupied} celle occupate",
    ),
    "err.locked": (
        "Sheet frozen or read-only. Unfreeze it before creating a numeric series.",
        "Foglio congelato o di sola lettura. Sbloccalo prima di creare una serie numerica.",
    ),
    "err.selection": (
        "Select a single cell or a single-column range.",
        "Seleziona una singola cella o un intervallo in una sola colonna.",
    ),
    "err.multicolumn": (
        "Numeric series can only be inserted into a single column.",
        "La serie numerica può essere inserita solo in una singola colonna.",
    ),
    "err.formula": (
        "Calculated columns cannot be overwritten with a numeric series.",
        "Le colonne calcolate non possono essere sovrascritte con una serie numerica.",
    ),
    "err.locked_column": (
        "This column is locked in the current view.",
        "Questa colonna è bloccata nella vista corrente.",
    ),
    "err.non_numeric": (
        "Select a numeric column (text, categorical, and row-title columns are not supported).",
        "Seleziona una colonna numerica (le colonne di testo, categoriali o titoli di riga non sono supportate).",
    ),
    "err.virtual_column_gap": (
        "Select an existing numeric column or the adjacent empty column.",
        "Seleziona una colonna numerica esistente o la colonna vuota adiacente.",
    ),
    "err.virtual_disabled": (
        "This worksheet structure does not allow adding rows or columns.",
        "La struttura di questo foglio non consente di aggiungere righe o colonne.",
    ),
    "err.invalid_number": (
        "Enter a finite number or a fraction such as 1/2.",
        "Inserisci un numero finito o una frazione come 1/2.",
    ),
    "err.zero_denominator": (
        "The denominator of a fraction cannot be zero.",
        "Il denominatore di una frazione non può essere zero.",
    ),
    "err.count": (
        "Enter at least 1 term.",
        "Inserisci almeno 1 termine.",
    ),
    "err.limit": (
        "The series exceeds the worksheet size limit ({max_cells:,} cells).",
        "La serie supera il limite di dimensione del foglio ({max_cells:,} celle).",
    ),
    "err.overflow": (
        "The generated series contains values that are not finite or not representable.",
        "La serie generata contiene valori non finiti o non rappresentabili.",
    ),
    "err.integer_precision": (
        "Writing decimals here would reduce the precision of integers above 2^53.",
        "Scrivere valori decimali qui ridurrebbe la precisione di interi superiori a 2^53.",
    ),
    "err.integer_term": (
        "Integer series terms must be between −2^53 and 2^53.",
        "I termini interi della serie devono essere compresi tra −2^53 e 2^53.",
    ),
    "err.confirm_required": (
        "Confirm replacement of the existing occupied cells before applying.",
        "Conferma la sostituzione delle celle già occupate prima di procedere.",
    ),
}


def series_text(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


@dataclass(frozen=True)
class SeriesTarget:
    column: int
    start_row: int
    proposed_count: int
    is_virtual_column: bool


@dataclass(frozen=True)
class NumericSeriesPlan:
    start_row: int
    column: int
    mode: str
    count: int
    values: np.ndarray
    whole_integers: bool
    occupied_count: int
    is_virtual_column: bool
    range_label: str
    preview_first: tuple[float | int, ...]
    preview_last: tuple[float | int, ...]


def _parse_decimal_part(raw_part):
    cleaned = decimal_comma(raw_part.strip())
    if not cleaned:
        raise ValueError(series_text("err.invalid_number"))
    try:
        dec = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(series_text("err.invalid_number")) from error
    if not dec.is_finite():
        raise ValueError(series_text("err.invalid_number"))
    if dec != 0 and abs(dec.adjusted()) > 350:
        raise ValueError(series_text("err.overflow"))
    return dec


def parse_series_number(text):
    """Parse a finite number ('.' or ',' decimal separator, scientific notation, or 'a/b' fraction)."""
    if isinstance(text, bool) or text is None:
        raise ValueError(series_text("err.invalid_number"))
    if isinstance(text, (int, float)):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(series_text("err.invalid_number"))
        dec = Decimal(str(text))
        return Fraction(dec), dec
    if not isinstance(text, str):
        raise ValueError(series_text("err.invalid_number"))
    stripped = text.strip()
    if not stripped:
        raise ValueError(series_text("err.invalid_number"))
    parts = stripped.split("/")
    if len(parts) > 2:
        raise ValueError(series_text("err.invalid_number"))
    if len(parts) == 2:
        num = _parse_decimal_part(parts[0])
        den = _parse_decimal_part(parts[1])
        if den == 0:
            raise ValueError(series_text("err.zero_denominator"))
        frac = Fraction(num) / Fraction(den)
        try:
            as_float = float(frac)
        except OverflowError as error:
            raise ValueError(series_text("err.overflow")) from error
        if not math.isfinite(as_float) or (as_float == 0.0 and frac != 0):
            raise ValueError(series_text("err.overflow"))
        return frac, None
    dec = _parse_decimal_part(parts[0])
    try:
        as_float = float(dec)
    except OverflowError as error:
        raise ValueError(series_text("err.overflow")) from error
    if not math.isfinite(as_float) or (as_float == 0.0 and dec != 0):
        raise ValueError(series_text("err.overflow"))
    return Fraction(dec), dec


def format_series_value(value, *, decimal_mark=None):
    if decimal_mark is None:
        decimal_mark = display_decimal_mark()
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    number = float(value)
    if number == 0.0:
        number = 0.0
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    text = f"{number:.10g}"
    return text.replace(".", decimal_mark, 1) if decimal_mark != "." else text


def format_preview(first_values, last_values, count, *, decimal_mark=None):
    if decimal_mark is None:
        decimal_mark = display_decimal_mark()
    sep = "; " if decimal_mark == "," else ", "
    if count <= len(first_values) + len(last_values) and count <= 5:
        all_vals = (*first_values, *last_values) if len(first_values) < count else first_values[:count]
        return sep.join(format_series_value(v, decimal_mark=decimal_mark) for v in all_vals)
    head = sep.join(format_series_value(v, decimal_mark=decimal_mark) for v in first_values)
    tail = sep.join(format_series_value(v, decimal_mark=decimal_mark) for v in last_values)
    return f"{head}{sep}…{sep}{tail}"


def _grows_rows(dataset):
    return dataset.table_format != EDITABLE_LEGACY_XY and dataset.table_format not in EDITABLE_LEGACY_FIXED_VALUES


def _grows_columns(dataset):
    return _grows_rows(dataset) and not dataset.formulas


def validate_series_target(dataset, box, *, locked=False, read_only=False, full_column=False):
    """Validate that ``box`` selects one numeric (or adjacent virtual) column and return SeriesTarget."""
    if locked or read_only:
        raise ValueError(series_text("err.locked"))
    if box is None:
        raise ValueError(series_text("err.selection"))
    top, left, bottom, right = box
    if top < 0 or left < 0 or bottom < top or right < left:
        raise ValueError(series_text("err.selection"))
    if left != right:
        raise ValueError(series_text("err.multicolumn"))

    columns = dataset.columns
    if left > len(columns):
        raise ValueError(series_text("err.virtual_column_gap"))
    if left == len(columns):
        if not _grows_columns(dataset):
            raise ValueError(series_text("err.virtual_disabled"))
        proposed = (len(dataset.raw) if len(dataset.raw) > 0 else DEFAULT_SINGLE_CELL_COUNT) if full_column else (
            bottom - top + 1 if bottom > top else DEFAULT_SINGLE_CELL_COUNT
        )
        return SeriesTarget(column=left, start_row=top, proposed_count=proposed, is_virtual_column=True)

    indices = dataset.source_indices
    source = indices[left]
    if source is None:
        raise ValueError(series_text("err.formula"))
    if source in dataset.locked_columns:
        raise ValueError(series_text("err.locked_column"))

    name = dataset.raw.columns[source]
    series = dataset.raw.iloc[:, source]
    explicit_type = dataset.raw.attrs.get(VARIABLE_TYPES, {}).get(name)
    is_numeric = pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)
    if explicit_type in {"text", "categorical"} or not is_numeric:
        raise ValueError(series_text("err.non_numeric"))
    if dataset.table_format == EDITABLE_LEGACY_XY and left >= 2:
        raise ValueError(series_text("err.locked_column"))

    if full_column:
        proposed = len(dataset.raw) if len(dataset.raw) > 0 else DEFAULT_SINGLE_CELL_COUNT
    elif bottom > top:
        proposed = bottom - top + 1
    else:
        proposed = DEFAULT_SINGLE_CELL_COUNT
    return SeriesTarget(column=left, start_row=top, proposed_count=proposed, is_virtual_column=False)


def _generate_values(start_frac, start_dec, step_frac, step_dec, count, mode):
    if mode not in (ARITHMETIC, GEOMETRIC):
        raise ValueError("Invalid series mode.")
    if type(count) is not int or count < 1:
        raise ValueError(series_text("err.count"))

    integer_start = start_frac.denominator == 1
    integer_step = step_frac.denominator == 1
    if integer_start and abs(start_frac) > _MAX_EXACT_INT:
        raise ValueError(series_text("err.integer_term"))

    if mode == ARITHMETIC:
        last_frac = start_frac + (count - 1) * step_frac
        if integer_start and (integer_step or count == 1):
            if abs(last_frac) > _MAX_EXACT_INT:
                raise ValueError(series_text("err.integer_term"))
            step = int(step_frac) if count > 1 else 0
            values = int(start_frac) + np.arange(count, dtype=np.int64) * step
            return values.astype(np.float64), True
        try:
            last_f = float(last_frac)
        except OverflowError as error:
            raise ValueError(series_text("err.overflow")) from error
        if not math.isfinite(last_f) or (last_f == 0.0 and last_frac != 0):
            raise ValueError(series_text("err.overflow"))
        if count <= 5_000 and start_dec is not None and step_dec is not None:
            values = np.array([float(start_dec + k * step_dec) for k in range(count)], dtype=np.float64)
        else:
            values = float(start_frac) + np.arange(count, dtype=np.float64) * float(step_frac)
        if not np.isfinite(values).all():
            raise ValueError(series_text("err.overflow"))
        return values, False

    # Geometric progression: a * r^k
    if count == 1 or step_frac == 1:
        val_f = float(start_frac)
        values = np.full(count, val_f, dtype=np.float64)
        return values, integer_start
    if start_frac == 0:
        return np.zeros(count, dtype=np.float64), True
    if step_frac == 0:
        values = np.zeros(count, dtype=np.float64)
        values[0] = float(start_frac)
        return values, integer_start
    if step_frac == -1:
        val_f = float(start_frac)
        signs = np.where((np.arange(count) % 2) == 0, 1.0, -1.0)
        return val_f * signs, integer_start

    if integer_start and integer_step:
        start, ratio = int(start_frac), int(step_frac)
        exponent = count - 1
        # A nonzero integer start and |ratio| ≥ 2 reach the limit after at most 53 steps.
        if exponent > 53 or abs(start * ratio**exponent) > _MAX_EXACT_INT:
            raise ValueError(series_text("err.integer_term"))
        values = np.fromiter((start * ratio**index for index in range(count)),
                             dtype=np.float64, count=count)
        return values, True

    start_f = float(start_frac)
    step_f = float(step_frac)
    abs_start = abs(start_f)
    abs_step = abs(step_f)
    log_last = math.log(abs_start) + (count - 1) * math.log(abs_step)
    if log_last > _MAX_FLOAT_LOG - 1e-9:
        # Check exact last term if very close to float64 max, otherwise fail fast in O(1).
        if log_last > _MAX_FLOAT_LOG + 1.0:
            raise ValueError(series_text("err.overflow"))
        try:
            last_f = float(start_frac * (step_frac ** (count - 1)))
        except OverflowError as error:
            raise ValueError(series_text("err.overflow")) from error
        if not math.isfinite(last_f):
            raise ValueError(series_text("err.overflow"))
    if log_last < _MIN_SUBNORMAL_LOG + 1e-9:
        if log_last < _MIN_SUBNORMAL_LOG - 1.0:
            raise ValueError(series_text("err.overflow"))
        last_f = float(start_frac * (step_frac ** (count - 1)))
        if last_f == 0.0:
            raise ValueError(series_text("err.overflow"))

    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        exponents = np.arange(count, dtype=np.float64)
        values = start_f * np.power(step_f, exponents)
    if not np.isfinite(values).all() or (values == 0.0).any():
        raise ValueError(series_text("err.overflow"))

    # Check if every generated value is an exact integer (e.g. 16 * 0.5^k for k=0..3 -> 16, 8, 4, 2)
    whole_ints = bool(np.all(np.floor(values) == values) and np.all(np.abs(values) <= _MAX_EXACT_INT))
    return values, whole_ints


def plan_numeric_series(dataset, start_row, column, *, mode, start_text, count, step_text,
                        locked=False, read_only=False):
    """Validate target, parameters, size bounds and all generated numbers before touching the dataset."""
    target = validate_series_target(dataset, (start_row, column, start_row, column),
                                    locked=locked, read_only=read_only)
    if type(count) is not int or count < 1:
        raise ValueError(series_text("err.count"))
    stop_row = start_row + count
    raw = dataset.raw
    if not _grows_rows(dataset) and stop_row > len(raw):
        raise ValueError(series_text("err.virtual_disabled"))

    height = max(len(raw), stop_row)
    width = len(raw.columns) + (1 if target.is_virtual_column else 0)
    if width > max(MAX_COLUMNS, len(raw.columns)) or height * width > MAX_CELLS:
        raise ValueError(series_text("err.limit", max_cells=MAX_CELLS))

    start_frac, start_dec = parse_series_number(start_text)
    step_frac, step_dec = parse_series_number(step_text)
    values, whole_ints = _generate_values(start_frac, start_dec, step_frac, step_dec, count, mode)

    occupied_count = 0
    if not target.is_virtual_column:
        source = dataset.source_indices[column]
        existing = raw.iloc[:, source]
        overlap_stop = min(stop_row, len(raw))
        if start_row < overlap_stop:
            occupied_count = int(existing.iloc[start_row:overlap_stop].notna().sum())
        if pd.api.types.is_integer_dtype(existing.dtype) and not whole_ints:
            if (np.abs(values) > 2**53).any() or existing.dropna().map(lambda v: abs(int(v)) > 2**53).any():
                raise ValueError(series_text("err.integer_precision"))

    col_ref = column_label(column)
    range_label = f"{col_ref}{start_row + 1}:{col_ref}{stop_row}"
    if count <= 5:
        first_vals = tuple(int(v) if whole_ints and abs(v) <= 2**53 else float(v) for v in values)
        last_vals = ()
    else:
        first_vals = tuple(int(v) if whole_ints and abs(v) <= 2**53 else float(v) for v in values[:3])
        last_vals = tuple(int(v) if whole_ints and abs(v) <= 2**53 else float(v) for v in values[-2:])

    return NumericSeriesPlan(
        start_row=start_row,
        column=column,
        mode=mode,
        count=count,
        values=values,
        whole_integers=whole_ints,
        occupied_count=occupied_count,
        is_virtual_column=target.is_virtual_column,
        range_label=range_label,
        preview_first=first_vals,
        preview_last=last_vals,
    )


def apply_numeric_series(dataset, plan):
    """Apply a validated ``NumericSeriesPlan`` to a copy of ``dataset`` atomically."""
    raw = dataset.raw
    stop_row = plan.start_row + plan.count
    height = max(len(raw), stop_row)
    candidate = grow_rows(raw, height)
    if plan.is_virtual_column:
        name = f"Column {plan.column + 1}"
        while name in candidate.columns or name in dataset.formulas:
            name += " (new)"
        dtype = "Int64" if plan.whole_integers else "Float64"
        candidate[name] = pd.Series(pd.NA, index=candidate.index, dtype=dtype)
        source = len(candidate.columns) - 1
    else:
        source = dataset.source_indices[plan.column]
        name = candidate.columns[source]

    series = candidate[name].copy()
    if pd.api.types.is_integer_dtype(series.dtype):
        if plan.whole_integers and np.all((plan.values >= -(2**63)) & (plan.values < 2**63)):
            if not hasattr(series.dtype, "numpy_dtype"):
                series = series.convert_dtypes()
            series.iloc[plan.start_row:stop_row] = plan.values.astype(np.int64)
        else:
            series = series.astype("Float64")
            series.iloc[plan.start_row:stop_row] = plan.values
    else:
        if not hasattr(series.dtype, "numpy_dtype"):
            series = series.astype("Float64")
        series.iloc[plan.start_row:stop_row] = plan.values
    candidate[name] = series

    preview = copy(dataset)
    preview.raw = candidate
    preview.frame()
    dataset.raw = candidate
