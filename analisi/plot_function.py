"""Plot a function: evaluate catalog equations with entered parameters on an X grid.

Nothing is fitted. Each curve is one parameter set of the same catalog model; the
tables hold the values, optional numerical derivatives and a cumulative integral.
"""
import math

import numpy as np
import pandas as pd

from .curve_models import CELL_DEATH_MODELS, MODEL_GROUPS, MODELS
from .processing import FieldError
from .reporting import Result, _plot, _report

PLOT_FUNCTION = "Plot a function"
MODEL, X_SOURCE, X_MIN, X_MAX, SEGMENTS, X_COLUMN, CURVES = (
    "Model", "X source", "X minimum", "X maximum", "Segments", "X column", "Curves")
FIRST, SECOND, INTEGRAL = "First derivative", "Second derivative", "Integral"
OBSERVATION_COLUMNS = "Observed XY columns"
LINEAR, GEOMETRIC, WORKSHEET = "Linear", "Geometric", "Worksheet"
SOURCES = (LINEAR, GEOMETRIC, WORKSHEET)
VALUES, PARAMETERS, SETTINGS = "Function values", "Parameters", "Settings"
CURVE_LIST = "Curve list"  # Dialog kind of the Curves field: a list of {"name", "parameters"}.
DEFAULT_MODEL = "Straight line"
DEFAULT_MIN, DEFAULT_MAX, DEFAULT_SEGMENTS = 0., 10., 150
MIN_SEGMENTS, MAX_SEGMENTS = 2, 10_000
MAX_CURVES = 12
MAX_EVALUATIONS = 120_000

# Models with a shared parameter need a joint fit of several data sets, so they cannot be plotted alone.
# The dispatcher and the dialog use this same list, in catalog family order with the default first.
_ORDERED = tuple(dict.fromkeys(name for names in MODEL_GROUPS.values() for name in names))
PLOTTABLE = tuple(dict.fromkeys(
    name for name in (DEFAULT_MODEL, *_ORDERED, *MODELS) if not MODELS[name].required_shared))
# The catalog marks Power series positive for its log-spaced fitting grid, yet a*x^b + c*x^d is defined
# on negative X for integer exponents. Its values are checked point by point: a pole or a fractional
# power of a negative X leaves an empty cell instead of rejecting the range.
POINTWISE_DOMAIN = frozenset({"Power series"})

OPTIONS = {MODEL: PLOTTABLE, X_SOURCE: SOURCES, X_MIN: DEFAULT_MIN, X_MAX: DEFAULT_MAX,
           SEGMENTS: DEFAULT_SEGMENTS, X_COLUMN: None, CURVES: CURVE_LIST,
           FIRST: False, SECOND: False, INTEGRAL: False}
TABS = {"Function": (MODEL, X_SOURCE, X_MIN, X_MAX, SEGMENTS, X_COLUMN), "Curves": (CURVES,),
        "Output": (FIRST, SECOND, INTEGRAL)}
EXAMPLE_CURVES = ({"name": "A", "parameters": {"Intercept": 0., "Slope": 1.}},
                  {"name": "B", "parameters": {"Intercept": 2., "Slope": .5}})
GRAPH_NOTE = "The graph draws Function values. Derivative and integral sheets can be exported."


def visibility(source):
    """Worksheet X uses a column; generated grids use the limits and the segment count."""
    generated = source != WORKSHEET
    return {X_MIN: generated, X_MAX: generated, SEGMENTS: generated, X_COLUMN: not generated}


def _is_number(value):
    return (not isinstance(value, (bool, np.bool_))
            and isinstance(value, (int, float, np.integer, np.floating)))


def _finite(value, field, label=None):
    label = label or field
    if not _is_number(value):
        raise FieldError(field, f"{label} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise FieldError(field, f"{label} must be finite.")
    return value


def _bounds(spec):
    k = len(spec.parameters)
    lower, upper = (np.broadcast_to(np.asarray(bound, dtype=float), (k,)) for bound in spec.bounds)
    return dict(zip(spec.parameters, zip(lower.tolist(), upper.tolist())))


def _limit_text(lower, upper):
    tiny = np.finfo(float).tiny
    parts = []
    if lower == tiny:
        parts.append("greater than 0")
    elif math.isfinite(lower):
        parts.append(f"at least {lower:g}")
    if upper == -tiny:
        parts.append("less than 0")
    elif math.isfinite(upper):
        parts.append(f"at most {upper:g}")
    return " and ".join(parts)


def check_model(o):
    model = o.get(MODEL, DEFAULT_MODEL)
    if model not in PLOTTABLE:
        if isinstance(model, str) and model in MODELS:
            shared = ", ".join(MODELS[model].required_shared)
            raise FieldError(MODEL, f"{model} needs a joint fit with shared {shared} and cannot be plotted alone.")
        raise FieldError(MODEL, "Choose an equation from the catalog.")
    return model


def check_curves(model, curves):
    """Return [(name, {parameter: float})] in the order entered, or raise FieldError on Curves."""
    spec = MODELS[model]
    if not isinstance(curves, (list, tuple)) or not curves:
        raise FieldError(CURVES, "Add at least one curve.")
    if len(curves) > MAX_CURVES:
        raise FieldError(CURVES, f"Plot up to {MAX_CURVES} curves; this list has {len(curves)}.")
    bounds = _bounds(spec)
    checked, seen = [], set()
    for position, entry in enumerate(curves, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise FieldError(CURVES, f"Curve {position} needs a name.")
        name = entry["name"].strip()
        if not name:
            raise FieldError(CURVES, f"Curve {position} needs a name.")
        if name.casefold() == "x":
            raise FieldError(CURVES, f"Curve {position}: X is the name of the X column. Choose another name.")
        if name.casefold() in seen:
            raise FieldError(CURVES, f"Curve {position}: the name {name} is already used (names ignore case).")
        seen.add(name.casefold())
        values = entry.get("parameters")
        if not isinstance(values, dict):
            raise FieldError(CURVES, f"Curve {name}: enter the parameters of {model}.")
        extra = [key for key in values if key not in spec.parameters]
        if extra:
            raise FieldError(CURVES, f"Curve {name}: {extra[0]} is not a parameter of {model}.")
        missing = [key for key in spec.parameters if key not in values]
        if missing:
            raise FieldError(CURVES, f"Curve {name}: enter a value for {', '.join(missing)}.")
        parameters = {}
        for key in spec.parameters:
            value = _finite(values[key], CURVES, f"Curve {name}: {key}")
            lower, upper = bounds[key]
            if not lower <= value <= upper:
                raise FieldError(CURVES, f"Curve {name}: {key} must be {_limit_text(lower, upper)}.")
            parameters[key] = value
        checked.append((name, parameters))
    return checked


def _segments(o):
    value = o.get(SEGMENTS, DEFAULT_SEGMENTS)
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) != int(value):
        raise FieldError(SEGMENTS, "Segments must be a whole number.")
    value = int(value)
    if not MIN_SEGMENTS <= value <= MAX_SEGMENTS:
        raise FieldError(SEGMENTS, f"Segments must be between {MIN_SEGMENTS} and {MAX_SEGMENTS:,}.")
    return value


def _budget(points, curves, field):
    if points * curves > MAX_EVALUATIONS:
        raise FieldError(field, f"{points:,} X values × {curves} curves exceed the limit of "
                                f"{MAX_EVALUATIONS:,} evaluations. Use fewer points or curves.")


def generated_grid(o, curves):
    source = o.get(X_SOURCE, LINEAR)
    lo = _finite(o.get(X_MIN, DEFAULT_MIN), X_MIN)
    hi = _finite(o.get(X_MAX, DEFAULT_MAX), X_MAX)
    if source == GEOMETRIC and lo <= 0:
        raise FieldError(X_MIN, "A geometric grid needs X minimum greater than 0.")
    if source == GEOMETRIC and hi <= 0:
        raise FieldError(X_MAX, "A geometric grid needs X maximum greater than 0.")
    if not lo < hi:
        raise FieldError(X_MAX, "X maximum must be greater than X minimum.")
    n = _segments(o)
    _budget(n + 1, curves, SEGMENTS)
    t = np.arange(1, n) / n
    with np.errstate(all="ignore"):
        if source == GEOMETRIC:
            middle = np.exp(math.log(lo) + t * math.log(hi / lo))
        elif math.isfinite(hi - lo):
            middle = lo + (hi - lo) * t
        else:
            middle = lo * (1 - t) + hi * t
    x = np.concatenate(([lo], middle, [hi]))
    if not np.isfinite(x).all():
        raise FieldError(X_MAX, "The X range is too wide to represent. Narrow X minimum or X maximum.")
    if not (np.diff(x) > 0).all():
        raise FieldError(SEGMENTS, "The X values are too close to stay distinct. Use fewer segments or a wider range.")
    return x


def worksheet_grid(frame, o, curves):
    column = o.get(X_COLUMN)
    if not isinstance(column, str) or not column or column not in frame:
        raise FieldError(X_COLUMN, "Choose the worksheet column that holds X.")
    values = []
    for row, cell in enumerate(frame[column].tolist(), 1):
        if cell is None or cell is pd.NA or cell is pd.NaT:
            continue
        if isinstance(cell, str):
            if cell.strip():
                raise FieldError(X_COLUMN, f"Row {row} of {column} is not a number.")
            continue
        if _is_number(cell) and math.isnan(float(cell)):
            continue
        if not _is_number(cell):
            raise FieldError(X_COLUMN, f"Row {row} of {column} is not a number.")
        if not math.isfinite(float(cell)):
            raise FieldError(X_COLUMN, f"Row {row} of {column} is infinite.")
        values.append((row, float(cell)))
    _budget(len(values), curves, X_COLUMN)
    if len(values) < 3:
        raise FieldError(X_COLUMN, f"{column} needs at least three X values.")
    for (_, before), (row, value) in zip(values, values[1:]):
        if not value > before:
            raise FieldError(X_COLUMN, f"Row {row} of {column}: X values must be distinct and increasing.")
    return np.array([value for _, value in values])


def check_domain(model, x, field):
    # The plot can show the lognormal limit at zero. Fitting still requires positive observations.
    domain = "nonnegative" if model == "Lognormal" else MODELS[model].domain
    if model in POINTWISE_DOMAIN or domain is None:
        return domain
    if domain == "positive" and (x <= 0).any():
        raise FieldError(field, f"{model} needs X greater than 0.")
    if domain == "nonnegative" and (x < 0).any():
        raise FieldError(field, f"{model} needs X of 0 or more.")
    return domain


def evaluate(model, x, parameters):
    """Values of one curve; a non-finite value becomes NaN so the cell stays empty."""
    spec = MODELS[model]
    with np.errstate(all="ignore"):
        try:
            y = spec.equation(x.astype(float), *(parameters[name] for name in spec.parameters))
            y = np.array(np.broadcast_to(np.asarray(y, dtype=float), x.shape))
        except (ArithmeticError, ValueError, TypeError):
            y = np.full(x.shape, np.nan)
    y[~np.isfinite(y)] = np.nan
    return y


def _runs(y):
    finite = np.isfinite(y)
    start = None
    for index, ok in enumerate([*finite.tolist(), False]):
        if ok and start is None:
            start = index
        elif not ok and start is not None:
            yield start, index
            start = None


def derivative(x, y):
    """Three-point Lagrange gradient on each finite run of at least three points; second order at the edges."""
    result = np.full(len(x), np.nan)
    for first, end in _runs(y):
        if end - first < 3:
            continue
        index = np.arange(first, end)
        base = np.clip(index - 1, first, end - 3)
        nodes = [base, base + 1, base + 2]
        xi = x[index]
        total = np.zeros(len(index))
        with np.errstate(all="ignore"):
            for k in range(3):
                own, (a, b) = nodes[k], [nodes[j] for j in range(3) if j != k]
                weight = ((xi - x[a]) + (xi - x[b])) / ((x[own] - x[a]) * (x[own] - x[b]))
                total = total + weight * y[own]
        result[first:end] = total
    result[~np.isfinite(result)] = np.nan
    return result


def integral(x, y):
    """Cumulative trapezoids from 0 at the first finite value; the first gap or overflow ends it."""
    result = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(y))
    if not len(finite):
        return result
    start = int(finite[0])
    result[start] = total = 0.
    for j in range(start + 1, len(x)):
        if not math.isfinite(y[j]):
            break
        with np.errstate(all="ignore"):
            total = total + (y[j] + y[j - 1]) * (x[j] - x[j - 1]) / 2.
        if not math.isfinite(total):
            break
        result[j] = total
    return result


def _sheet(x, names, columns):
    return pd.DataFrame({"X": x, **dict(zip(names, columns, strict=True))})


def _draw_observations(axes, frame, columns):
    if (not isinstance(columns, (tuple, list)) or len(columns) != 2
            or not all(isinstance(name, str) and name in frame.columns for name in columns)
            or columns[0] == columns[1]):
        raise FieldError(OBSERVATION_COLUMNS, "The original observation columns are unavailable.")
    x, y = (pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            for name in columns)
    keep = np.isfinite(x) & np.isfinite(y)
    axes.plot(x[keep], y[keep], linestyle="None", marker="o", label=columns[1])


def plot_function(frame, o):
    model = check_model(o)
    curves = check_curves(model, o.get(CURVES))
    source = o.get(X_SOURCE, LINEAR)
    if source not in SOURCES:
        raise FieldError(X_SOURCE, f"X source must be one of {', '.join(SOURCES)}.")
    if source == WORKSHEET:
        x, field = worksheet_grid(frame, o, len(curves)), X_COLUMN
    else:
        x, field = generated_grid(o, len(curves)), X_MIN
    domain = check_domain(model, x, field)
    names = [name for name, _ in curves]
    values = [evaluate(model, x, parameters) for _, parameters in curves]
    for name, y in zip(names, values):
        if not np.isfinite(y).any():
            raise FieldError(CURVES, f"Curve {name} has no finite value on this X range.")
    spec = MODELS[model]
    tables = {
        VALUES: _sheet(x, names, values),
        PARAMETERS: pd.DataFrame([[name, *(parameters[key] for key in spec.parameters)]
                                  for name, parameters in curves], columns=["Curve", *spec.parameters]),
    }
    settings = {"Model": model, "X source": source, "X minimum": float(x[0]), "X maximum": float(x[-1]),
                "Points": len(x)}
    if source == WORKSHEET:
        settings["X column"] = o[X_COLUMN]
    else:
        settings["Segments"] = len(x) - 1
    settings.update({f"Non-finite values · {name}": int((~np.isfinite(y)).sum()) for name, y in zip(names, values)})
    tables[SETTINGS] = _report(settings)
    if o.get(FIRST) or o.get(SECOND):
        first = [derivative(x, y) for y in values]
        if o.get(FIRST):
            tables[FIRST] = _sheet(x, names, first)
        if o.get(SECOND):
            tables[SECOND] = _sheet(x, names, [derivative(x, d) for d in first])
    if o.get(INTEGRAL):
        tables[INTEGRAL] = _sheet(x, names, [integral(x, y) for y in values])
    figure, axes = _plot(model, "X", "Y")
    axes._tramastat_log_x_omit_zero = domain == "nonnegative"
    axes._tramastat_log_y_omit_zero = model in CELL_DEATH_MODELS
    if OBSERVATION_COLUMNS in o:
        _draw_observations(axes, frame, o[OBSERVATION_COLUMNS])
    for name, y in zip(names, values):
        axes.plot(x, y, label=name)
    axes.legend()
    return Result(tables, figure)
