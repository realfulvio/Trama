"""Curve pipeline (0.93): differences, a cumulative trapezoid and Savitzky–Golay smoothing on one XY curve.

It is the fourth choice of ``Method`` in Smooth / differentiate / integrate. The three older choices keep their code
(``exploration.curve_operation``); the dispatcher sends only ``Method = Curve pipeline`` here.

Points
    Every worksheet row is a point with X, Y and its zero-based position in the worksheet order (a pandas index of any
    kind is ignored). A row without a usable X has no place on the axis and is skipped. A row with a valid X and no
    usable Y (empty or excluded) is a gap: it stays out of the curve and splits it there. A curve may therefore
    hold several blocks, and blocks are never joined. Blocks are numbered from 1 along increasing X, empty
    result blocks included, so a number always names the same stretch of the data. X values must be distinct, also
    when one of the two rows has no Y. Text and infinite values are rejected on their own field.

Operations (per block, in the units of the worksheet)
    Identity             the samples.
    First difference     dY/dX between consecutive samples of a block, placed at x_left + dX/2.
    Second difference    the same operation on the points of the first difference.
    Cumulative trapezoid starts from ``Initial integral`` at the first sample of every block and adds
                         dX · ((y_left + y_right) / 2 − Baseline) per step: a signed area. A lone sample keeps the
                         initial value.

Smoothing (after the operation, on the points it produced, separately per block)
    Savitzky–Golay: for every centre with ``Half-window`` m points on each side, the polynomial of the chosen degree
    that fits the 2m + 1 values by least squares is evaluated at the centre, which is a fixed weighted sum of the
    window. Centres without a complete window are not emitted. The X grid of an eligible block (at least 2m + 1
    points) must be evenly spaced: the largest deviation of a step from the median step may not exceed
    ``GRID_TOLERANCE`` times the median step. Blocks shorter than 2m + 1 points give nothing.

Source rows
    ``First source row`` and ``Last source row`` are the positions of the first and last worksheet row that the
    value was calculated from, in increasing X order (so they can decrease for an unsorted sheet). A difference joins
    the ends of the two points behind it, a cumulative value keeps the first row of its block, and smoothing
    extends the ends to the rows inside the window.

Budget
    The weights of one window are at most 101 numbers and each block is convolved on its own, so the memory is a few
    working arrays of the block length. ``MAX_ROWS`` bounds the worksheet rows before anything is converted.
"""
from dataclasses import dataclass
from functools import lru_cache
from numbers import Integral, Real

import numpy as np
import pandas as pd

from .field_error import FieldError
from .reporting import Result, _plot

CURVE_METHOD = "Smooth / differentiate / integrate"
PIPELINE = "Curve pipeline"
OPERATION, SMOOTHING, BASELINE, INITIAL = "Operation", "Smoothing", "Baseline", "Initial integral"
HALF_WINDOW, DEGREE = "Half-window", "Polynomial degree"
IDENTITY, FIRST, SECOND, CUMULATIVE = OPERATIONS = (
    "Identity", "First difference", "Second difference", "Cumulative trapezoid")
NO_SMOOTHING, SAVITZKY_GOLAY = SMOOTHERS = ("None", "Savitzky–Golay")
DEFAULT_HALF_WINDOW, DEFAULT_DEGREE = 2, 2
MIN_HALF_WINDOW, MAX_HALF_WINDOW, MAX_DEGREE = 1, 50, 6
# The fields the pipeline adds to Smooth / differentiate / integrate, in dialog order. Method itself is the existing
# field; its fourth choice is PIPELINE. The defaults are the ones of the specification: Identity, None, 0, 0, 2, 2.
OPTIONS = {OPERATION: OPERATIONS, SMOOTHING: SMOOTHERS, BASELINE: 0.0, INITIAL: 0.0,
           HALF_WINDOW: DEFAULT_HALF_WINDOW, DEGREE: DEFAULT_DEGREE}
PIPELINE_FIELDS = tuple(OPTIONS)

CURVE, SETTINGS = "Curve", "Settings"
COLUMNS = ["X", "Value", "Block", "First source row", "Last source row"]
# 200,000 worksheet rows: the working arrays and the Curve sheet stay a few tens of megabytes, a 50,000 row curve
# (the size the pipeline is exercised at) takes well under a second, and the drawn line stays interactive.
MAX_ROWS = 200_000
GRID_TOLERANCE = 1e-10
SMOOTHING_NOTE = ("Smoothed values are a descriptive transformation of the data. They are not a fitted model "
                  "and not new measurements.")
ERROR_PREFIX = "curve.pipeline.error."


def visibility(method, operation, smoothing):
    """The pipeline fields shown for a Method; the LOWESS fraction stays with the three older choices."""
    pipeline = method == PIPELINE
    return {"LOWESS fraction": not pipeline, OPERATION: pipeline, SMOOTHING: pipeline,
            BASELINE: pipeline and operation == CUMULATIVE, INITIAL: pipeline and operation == CUMULATIVE,
            HALF_WINDOW: pipeline and smoothing == SAVITZKY_GOLAY, DEGREE: pipeline and smoothing == SAVITZKY_GOLAY}


def max_degree(half_window):
    return min(MAX_DEGREE, 2 * half_window)


# --- options -------------------------------------------------------------------------------------------------

def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"{name} must be one of the listed choices.")
    return value


def _number(options, name, default=0.0):
    value = options.get(name, default)
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            raise FieldError(name, f"{name} must be a finite number.") from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(name, f"{name} must be a finite number.")
    value = float(value)
    if not np.isfinite(value):
        raise FieldError(name, f"{name} must be a finite number.")
    return value


def _integer(options, name, low, high, default, message=None):
    value = options.get(name, default)
    message = message or f"{name} must be a whole number from {low} to {high}."
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            raise FieldError(name, message) from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (Integral, Real)):
        raise FieldError(name, message)
    if isinstance(value, Real) and not isinstance(value, Integral):
        if not np.isfinite(value) or value != int(value):
            raise FieldError(name, message)
    value = int(value)
    if not low <= value <= high:
        raise FieldError(name, message)
    return value


@dataclass(frozen=True)
class Settings:
    x: str
    y: str
    operation: str
    smoothing: str
    baseline: float
    initial: float
    half_window: int
    degree: int

    @property
    def smoothed(self):
        return self.smoothing == SAVITZKY_GOLAY

    @property
    def window(self):
        return 2 * self.half_window + 1


def read_options(frame, options):
    """Check the fields that act: Baseline and Initial integral only for the integral, the window only with smoothing."""
    x, y = options.get("X"), options.get("Y")
    for field, name in (("X", x), ("Y", y)):
        if not isinstance(name, str) or name not in frame:
            raise FieldError(field, f'Choose an existing column for {field}: "{name}" is not in the worksheet.')
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    operation = _choice(options, OPERATION, OPERATIONS)
    smoothing = _choice(options, SMOOTHING, SMOOTHERS)
    baseline = initial = 0.0
    if operation == CUMULATIVE:
        baseline, initial = _number(options, BASELINE), _number(options, INITIAL)
    half_window, degree = DEFAULT_HALF_WINDOW, DEFAULT_DEGREE
    if smoothing == SAVITZKY_GOLAY:
        half_window = _integer(options, HALF_WINDOW, MIN_HALF_WINDOW, MAX_HALF_WINDOW, DEFAULT_HALF_WINDOW)
        top = max_degree(half_window)
        degree = _integer(options, DEGREE, 0, top, DEFAULT_DEGREE,
                          f"{DEGREE} must be a whole number from 0 to {top} for this half-window.")
    return Settings(x, y, operation, smoothing, baseline, initial, half_window, degree)


# --- points --------------------------------------------------------------------------------------------------

@dataclass
class Points:
    """The usable samples in increasing X order, with the worksheet rows they came from and their blocks."""
    x: np.ndarray
    y: np.ndarray
    position: np.ndarray
    block: np.ndarray
    rows_without_x: int
    rows_without_y: int
    blocks: int


def _column(frame, name, field):
    """Numbers of a worksheet column with NaN for empty cells; text and infinity are errors of the field."""
    series = frame[name]
    if isinstance(series, pd.DataFrame):
        raise FieldError(field, "Worksheet column names must be unique.")
    if (pd.api.types.is_complex_dtype(series) or pd.api.types.is_datetime64_any_dtype(series)
            or pd.api.types.is_timedelta64_dtype(series)):
        raise FieldError(field, f"Column {name} is not numeric.")
    numbers = pd.to_numeric(series, errors="coerce")
    blank = series.isna()
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        blank = blank | series.map(lambda cell: isinstance(cell, str) and not cell.strip())
    text = ~blank & numbers.isna()
    if text.any():
        row = int(np.flatnonzero(text.to_numpy())[0]) + 1
        raise FieldError(field, f"Column {name} has text instead of a number at row {row}.")
    try:
        values = numbers.astype("float64").to_numpy()
    except (TypeError, ValueError):
        raise FieldError(field, f"Column {name} is not numeric.") from None
    infinite = np.isinf(values)
    if infinite.any():
        row = int(np.flatnonzero(infinite)[0]) + 1
        raise FieldError(field, f"Column {name} has an infinite value at row {row}.")
    return values


def curve_points(frame, settings):
    rows = len(frame)
    if rows > MAX_ROWS:
        raise FieldError("X", f"The curve pipeline supports up to {MAX_ROWS:,} worksheet rows; this sheet has {rows:,}.")
    x = _column(frame, settings.x, "X")
    y = _column(frame, settings.y, "Y")
    position = np.arange(rows)
    usable_x = ~np.isnan(x)
    order = np.argsort(x[usable_x], kind="stable")
    xs, ys, rows_at = x[usable_x][order], y[usable_x][order], position[usable_x][order]
    repeated = np.flatnonzero(np.diff(xs) == 0)
    if repeated.size:
        raise FieldError("X", f"X must be distinct; the value {xs[repeated[0]]:g} appears more than once.")
    usable_y = ~np.isnan(ys)
    # A block starts at a usable Y whose predecessor in X order is not usable.
    starts = usable_y & ~np.concatenate(([False], usable_y[:-1]))
    block = np.cumsum(starts)
    if not usable_y.any():
        raise FieldError("Y", "Y has no number on a row with a valid X.")
    return Points(xs[usable_y], ys[usable_y], rows_at[usable_y], block[usable_y],
                  int(rows - usable_x.sum()), int(usable_x.sum() - usable_y.sum()), int(starts.sum()))


# --- calculation ---------------------------------------------------------------------------------------------

@dataclass
class Series:
    x: np.ndarray
    value: np.ndarray
    block: np.ndarray
    first: np.ndarray
    last: np.ndarray

    def __len__(self):
        return len(self.x)


def _runs(block):
    """Start and end index of every run of equal block numbers."""
    cuts = np.flatnonzero(np.diff(block) != 0) + 1
    return np.concatenate(([0], cuts)), np.concatenate((cuts, [len(block)]))


def _identity(points):
    return Series(points.x, points.y, points.block, points.position, points.position)


def _difference(series):
    """dY/dX between consecutive points of one block, at the midpoint x_left + dX/2."""
    left = np.flatnonzero(series.block[:-1] == series.block[1:])
    right = left + 1
    step = series.x[right] - series.x[left]
    with np.errstate(all="ignore"):
        value = (series.value[right] - series.value[left]) / step
    return Series(series.x[left] + step / 2, value, series.block[left], series.first[left], series.last[right])


def _cumulative(series, baseline, initial):
    """Signed trapezoid areas from ``initial`` at the start of every block, each block on its own."""
    value = np.empty(len(series))
    first = np.empty(len(series), dtype=series.first.dtype)
    with np.errstate(all="ignore"):
        for start, end in zip(*_runs(series.block)):
            value[start] = initial
            first[start:end] = series.first[start]
            if end - start > 1:
                step = np.diff(series.x[start:end])
                height = (series.value[start:end - 1] + series.value[start + 1:end]) / 2 - baseline
                np.cumsum(step * height, out=value[start + 1:end])
                value[start + 1:end] += initial
    return Series(series.x, value, series.block, first, series.last)


def operate(points, settings):
    series = _identity(points)
    if settings.operation == CUMULATIVE:
        series = _cumulative(series, settings.baseline, settings.initial)
    elif settings.operation != IDENTITY:
        series = _difference(series)
        if settings.operation == SECOND:
            series = _difference(series)
        if not len(series):
            raise FieldError(OPERATION, f"No block has enough points for {settings.operation}: "
                                        f"the first difference needs two, the second difference three.")
    if not np.isfinite(series.value).all():
        raise FieldError(OPERATION, "The calculation produced a value that is not finite. "
                                    "Rescale X or Y, or choose another operation.")
    return series


@lru_cache(maxsize=64)
def savitzky_golay_weights(half_window, degree):
    """Weights w with smoothed(centre) = sum(w_j · y_j): the constant term of the least-squares polynomial.

    The window offsets are scaled to [-1, 1] first, which keeps the 7 × 101 design matrix well conditioned.
    """
    offsets = np.arange(-half_window, half_window + 1) / half_window
    weights = np.linalg.pinv(np.vander(offsets, degree + 1, increasing=True))[0]
    weights.setflags(write=False)
    return weights


def smooth(series, settings):
    """Savitzky–Golay per block; only complete windows give a point."""
    m, width = settings.half_window, settings.window
    weights = savitzky_golay_weights(m, settings.degree)
    pieces = []
    for start, end in zip(*_runs(series.block)):
        if end - start < width:
            continue
        x = series.x[start:end]
        steps = np.diff(x)
        median = np.median(steps)
        if np.max(np.abs(steps - median)) > GRID_TOLERANCE * median:
            raise FieldError(SMOOTHING, f"Savitzky–Golay needs evenly spaced X values; the steps of block "
                                        f"{int(series.block[start])} differ from the median step by more than "
                                        f"{GRID_TOLERANCE:g} of it.")
        with np.errstate(all="ignore"):
            value = np.convolve(series.value[start:end], weights, mode="valid")
        pieces.append(Series(x[m:end - start - m], value, series.block[start + m:end - m],
                             series.first[start:end - 2 * m], series.last[start + 2 * m:end]))
    if not pieces:
        raise FieldError(HALF_WINDOW, f"No block has the {width} points that this half-window needs. "
                                      f"Reduce the half-window or choose a longer curve.")
    result = Series(*(np.concatenate([getattr(piece, field) for piece in pieces])
                      for field in ("x", "value", "block", "first", "last")))
    if not np.isfinite(result.value).all():
        raise FieldError(SMOOTHING, "The calculation produced a value that is not finite. "
                                    "Rescale X or Y, or choose another operation.")
    return result


def calculate(frame, options):
    """The settings, the usable points and the result series of one pipeline run."""
    settings = read_options(frame, options)
    points = curve_points(frame, settings)
    series = operate(points, settings)
    if settings.smoothed:
        series = smooth(series, settings)
    return settings, points, series


# --- sheets and graph ----------------------------------------------------------------------------------------

def curve_table(series):
    return pd.DataFrame({"X": series.x, "Value": series.value, "Block": series.block.astype(np.int64),
                         "First source row": series.first.astype(np.int64),
                         "Last source row": series.last.astype(np.int64)}, columns=COLUMNS)


def unit_text(settings):
    x, y = settings.x, settings.y
    return {IDENTITY: y, FIRST: f"{y} per {x}", SECOND: f"{y} per {x} squared",
            CUMULATIVE: f"{y} × {x}"}[settings.operation]


def settings_table(settings, points, series):
    rows = [("Operation", settings.operation), ("Smoothing", settings.smoothing)]
    if settings.operation == CUMULATIVE:
        rows += [("Baseline", settings.baseline), ("Initial integral", settings.initial)]
    if settings.smoothed:
        rows += [("Half-window", settings.half_window), ("Polynomial degree", settings.degree),
                 ("Window points", settings.window)]
    rows += [("Output unit", unit_text(settings)),
             ("Valid points", int(len(points.x))),
             ("Rows skipped (X missing or excluded)", points.rows_without_x),
             ("Gap rows (Y missing or excluded)", points.rows_without_y),
             ("Blocks", points.blocks),
             ("Blocks without output", points.blocks - len(np.unique(series.block))),
             ("Output points", int(len(series))),
             ("Source row numbering", "Zero-based position in worksheet order")]
    if settings.smoothed:
        rows.append(("Note", SMOOTHING_NOTE))
    return pd.DataFrame({"Setting": [name for name, _ in rows], "Value": pd.Series([value for _, value in rows],
                                                                                   dtype=object)})


def _y_label(settings):
    y, x = settings.y, settings.x
    return {IDENTITY: y, FIRST: f"Δ{y} / Δ{x}", SECOND: f"Δ²{y} / Δ{x}²",
            CUMULATIVE: f"Cumulative area of {y}"}[settings.operation]


def _broken(series):
    """X and values with a NaN between two blocks, so that one line never crosses a gap."""
    cuts = np.flatnonzero(np.diff(series.block) != 0) + 1
    return np.insert(series.x, cuts, np.nan), np.insert(series.value, cuts, np.nan)


def figure(settings, points, series):
    name = settings.operation + (f" + {settings.smoothing}" if settings.smoothed else "")
    fig, ax = _plot(name, settings.x, _y_label(settings))
    x, value = _broken(series)
    small = len(series) <= 60
    line, = ax.plot(x, value, label=name, zorder=2, marker="o" if small else None, markersize=3)
    # A block of one point has no segment; it is still part of the result.
    lone = np.bincount(series.block)[series.block] == 1
    if not small and lone.any():
        ax.plot(series.x[lone], series.value[lone], linestyle="none", marker="o", markersize=3,
                color=line.get_color(), zorder=2, label="_nolegend_")
    if settings.smoothed and settings.operation == IDENTITY:
        # Same unit as the output, so the measured points stay visible behind the smoothed curve.
        ax.scatter(points.x, points.y, s=12, color="0.6", label="Original data", zorder=1)
    ax.legend()
    return fig


def analysis(frame, options):
    settings, points, series = calculate(frame, options)
    return Result({CURVE: curve_table(series), SETTINGS: settings_table(settings, points, series)},
                  figure(settings, points, series))
