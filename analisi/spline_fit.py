"""Fit spline/LOWESS: five interpolators on one X/Y series, residuals, direct and inverse queries.

Support
    Complete X/Y pairs of the analysed frame (excluded cells already masked) are sorted stably by X. With
    ``Duplicate X = Reject`` an exact repeat of X is an error on X; with ``Average`` the pairs that share an exact X
    become one support point with the arithmetic mean of Y and the count N.

Models (all in sheet units; X is centred and scaled to [-1, 1] inside the cubic fits)
    Point-to-point      affine between support points, at least 2 X.
    Cubic spline        natural cubic (zero second derivative at both ends), at least 4 X.
    Akima spline        classic Akima (scipy ``method="akima"``), at least 5 X.
    Smoothing spline    unweighted least-squares cubic B-spline with *fixed* knots: equally spaced interior knots
                        between X min and X max and the end knots repeated four times. It needs 4 + knots points and
                        a full-rank design (Schoenberg–Whitney); zero knots is the least-squares cubic polynomial.
                        This is not a penalised smoothing spline: the knots, not a smoothing parameter, set the fit.
    LOWESS              statsmodels LOWESS with the chosen fraction and robust iterations on the support points,
                        affine between the smoothed support values, at least 12 X and ``floor(fraction·n) >= 3``.

Queries
    Y from X evaluates the model on the closed observed domain. X from Y finds every root on every piece of the model
    (affine pieces directly, cubic pieces from the local polynomial split at its turning points), keeps tangent
    roots, joins flat pieces into plateaus and merges the shared ends of adjacent pieces. One isolated root is
    "In range", none is "Outside calibration", several roots or any plateau is "Ambiguous" and goes to the
    "Inverse solutions" and "Inverse plateaus" sheets. The number of drawn segments never changes these answers.
"""
from dataclasses import dataclass
from math import floor
from numbers import Integral, Real

import numpy as np
import pandas as pd
from scipy.interpolate import Akima1DInterpolator, BSpline, CubicSpline, PPoly
from scipy.optimize import brentq
from statsmodels.nonparametric.smoothers_lowess import lowess

from .processing import FieldError, _column

SPLINE_FIT = "Fit spline/LOWESS"
POINT, CUBIC, AKIMA, SMOOTH, LOWESS = METHODS = (
    "Point-to-point", "Cubic spline", "Akima spline", "Smoothing spline", "LOWESS")
METHOD, SEGMENTS, DUPLICATES, KNOTS = "Method", "Segments", "Duplicate X", "Interior knots"
FRACTION, ITERATIONS, RESIDUALS, DIRECTION, QUERY = (
    "LOWESS fraction", "Robust iterations", "Residuals", "Direction", "Query")
REJECT, AVERAGE = DUPLICATE_POLICIES = ("Reject", "Average")
NO_QUERY, Y_FROM_X, X_FROM_Y = DIRECTIONS = ("None", "Y from X", "X from Y")
DEFAULT_SEGMENTS, DEFAULT_KNOTS, DEFAULT_FRACTION, DEFAULT_ITERATIONS = 150, 3, .5, 3
# Role strings are the ones the workbench uses: None is a required column, "Optional" an optional one.
OPTIONS = {"X": None, "Y": None, METHOD: METHODS, DUPLICATES: DUPLICATE_POLICIES, KNOTS: DEFAULT_KNOTS,
           FRACTION: DEFAULT_FRACTION, ITERATIONS: DEFAULT_ITERATIONS, DIRECTION: DIRECTIONS, QUERY: "Optional",
           SEGMENTS: DEFAULT_SEGMENTS, RESIDUALS: False}
TABS = {"Interpolation": (DIRECTION, QUERY), "Output": (SEGMENTS, RESIDUALS)}
METHOD_NOTE = ("Smoothing spline: least-squares cubic B-spline with fixed, equally spaced interior knots, "
               "not a penalised smoothing spline. Cubic spline is the natural cubic. LOWESS joins the smoothed "
               "support points with straight segments.")

SUPPORT, COORDINATES, RESIDUAL_SHEET = "Support points", "Curve coordinates", "Residuals"
VALUES, SOLUTIONS, PLATEAUS = "Interpolated values", "Inverse solutions", "Inverse plateaus"
IN_RANGE, OUTSIDE, AMBIGUOUS = "In range", "Outside calibration", "Ambiguous"

MINIMUM = {POINT: 2, CUBIC: 4, AKIMA: 5, SMOOTH: 4, LOWESS: 12}
MAX_SEGMENTS, MAX_SUPPORT, MAX_KNOTS, MAX_ITERATIONS = 10_000, 10_000, 64, 3
INVERSE_BUDGET = 2_000_000
# Relative tolerances: the value test is on the local scale of a piece, the root merge on its width.
VALUE_TOLERANCE, ROOT_TOLERANCE, CONDITION_LIMIT = 1e-12, 1e-9, 1e12


def visibility(method, direction):
    """Knots belong to the smoothing spline, fraction and iterations to LOWESS, Query to a query direction."""
    return {KNOTS: method == SMOOTH, FRACTION: method == LOWESS, ITERATIONS: method == LOWESS,
            QUERY: direction != NO_QUERY}


def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose one of: {', '.join(choices)}.")
    return value


def _integer(options, name, low, high, default):
    value = options.get(name, default)
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            raise FieldError(name, f"{name} must be a whole number from {low} to {high}.") from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (Integral, Real)):
        raise FieldError(name, f"{name} must be a whole number from {low} to {high}.")
    if isinstance(value, Real) and not isinstance(value, Integral):
        if not np.isfinite(value) or value != int(value):
            raise FieldError(name, f"{name} must be a whole number from {low} to {high}.")
    value = int(value)
    if not low <= value <= high:
        raise FieldError(name, f"{name} must be a whole number from {low} to {high}.")
    return value


def _fraction(options):
    value = options.get(FRACTION, DEFAULT_FRACTION)
    message = f"{FRACTION} must be a number greater than 0 and at most 1."
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            raise FieldError(FRACTION, message) from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(FRACTION, message)
    value = float(value)
    if not np.isfinite(value) or not 0 < value <= 1:
        raise FieldError(FRACTION, message)
    return value


@dataclass(frozen=True)
class Settings:
    x: str
    y: str
    method: str
    segments: int
    duplicates: str
    knots: int
    fraction: float
    iterations: int
    residuals: bool
    direction: str
    query: str | None


def read_options(frame, options):
    """Check the visible options only: hidden method fields never reach the result."""
    x, y = options.get("X"), options.get("Y")
    for field, name in (("X", x), ("Y", y)):
        if not isinstance(name, str) or name not in frame:
            raise FieldError(field, f"Choose a column for {field}.")
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    method = _choice(options, METHOD, METHODS)
    segments = _integer(options, SEGMENTS, 2, MAX_SEGMENTS, DEFAULT_SEGMENTS)
    duplicates = _choice(options, DUPLICATES, DUPLICATE_POLICIES)
    knots = _integer(options, KNOTS, 0, MAX_KNOTS, DEFAULT_KNOTS) if method == SMOOTH else 0
    fraction = _fraction(options) if method == LOWESS else DEFAULT_FRACTION
    iterations = (_integer(options, ITERATIONS, 0, MAX_ITERATIONS, DEFAULT_ITERATIONS) if method == LOWESS
                  else DEFAULT_ITERATIONS)
    residuals = options.get(RESIDUALS, False)
    if not isinstance(residuals, (bool, np.bool_)):
        raise FieldError(RESIDUALS, "Residuals must be on or off.")
    direction = _choice(options, DIRECTION, DIRECTIONS)
    query = None
    if direction != NO_QUERY:
        query = options.get(QUERY)
        if not isinstance(query, str) or query not in frame:
            raise FieldError(QUERY, "Choose a query column for this direction.")
        if query in (x, y):
            raise FieldError(QUERY, "Choose a query column different from X and Y.")
    return Settings(x, y, method, segments, duplicates, knots, fraction, iterations, bool(residuals), direction,
                    query)


def _row_title_column(frame, blocked):
    for name in frame.columns:
        if name not in blocked and str(name).casefold() in {"row title", "row titles"}:
            return name
    return None


@dataclass
class Model:
    """A fitted curve: ``evaluate`` takes sheet X; ``pieces`` gives the solvable parts for inversion."""
    method: str
    x: np.ndarray          # support X
    y: np.ndarray          # support Y (means)
    counts: np.ndarray
    nodes: np.ndarray      # values at the support X that the affine models join (fitted Y for LOWESS)
    breaks: np.ndarray     # piece boundaries in sheet X
    poly: PPoly | None     # cubic models, in normalised X
    center: float
    scale: float

    def normalise(self, values):
        return (np.asarray(values, dtype=float) - self.center) / self.scale

    def evaluate(self, values):
        values = np.asarray(values, dtype=float)
        if self.poly is None:
            with np.errstate(all="ignore"):
                found = np.interp(values, self.x, self.nodes)
        else:
            with np.errstate(all="ignore"):
                found = self.poly(self.normalise(values))
        if not np.isfinite(found).all():
            raise ValueError("The fitted curve gives values outside the representable range. "
                             "Rescale Y before fitting.")
        return found

    @property
    def piece_count(self):
        return len(self.breaks) - 1


def _support(frame, settings):
    x = _column(frame, settings.x, "X").to_numpy(dtype=float)
    y = _column(frame, settings.y, "Y").to_numpy(dtype=float)
    complete = np.isfinite(x) & np.isfinite(y)
    rows = np.flatnonzero(complete)
    order = np.argsort(x[rows], kind="stable")
    sx, sy = x[rows][order], y[rows][order]
    if len(sx) and settings.duplicates == REJECT:
        repeated = np.flatnonzero(sx[1:] == sx[:-1])
        if repeated.size:
            raise FieldError("X", f"X = {sx[repeated[0]]:g} appears more than once. "
                                  "Choose Duplicate X = Average to fit the mean of Y at each X.")
    unique, inverse, counts = np.unique(sx, return_inverse=True, return_counts=True)
    means = np.bincount(inverse, weights=sy, minlength=len(unique)) / counts if len(unique) else unique
    if not np.isfinite(means).all():
        raise FieldError("Y", "The mean of Y at a repeated X exceeds the representable range.")
    need = MINIMUM[settings.method] + (settings.knots if settings.method == SMOOTH else 0)
    if len(unique) < MINIMUM[settings.method]:
        raise FieldError("X", f"{settings.method} needs at least {MINIMUM[settings.method]} distinct X values "
                              f"with Y; found {len(unique)}.")
    if len(unique) > MAX_SUPPORT:
        raise FieldError("X", f"Fit spline/LOWESS accepts up to {MAX_SUPPORT:,} support points; "
                              f"found {len(unique):,}.")
    if len(unique) < need:
        raise FieldError(KNOTS, f"{settings.knots} interior knots need at least {need} support points; "
                                f"found {len(unique)}. Use fewer knots.")
    return x, y, complete, unique, means, counts.astype(int)


def effective_segments(settings, points):
    return max(settings.segments, 4 * points) if settings.method == LOWESS else settings.segments


def _check_budgets(frame, settings, points):
    if effective_segments(settings, points) > MAX_SEGMENTS:
        raise FieldError("X", f"LOWESS draws at least 4 segments per support point; {points:,} points need "
                              f"{4 * points:,} segments, above the limit of {MAX_SEGMENTS:,}.")
    if settings.method == LOWESS and floor(settings.fraction * points) < 3:
        raise FieldError(FRACTION, f"With {points} support points the LOWESS window floor({settings.fraction:g} × "
                                   f"{points}) holds fewer than 3 points. Increase the fraction.")
    queries = None
    if settings.query is not None:
        queries = _column(frame, settings.query, QUERY).to_numpy(dtype=float)
        if settings.direction == X_FROM_Y:
            pieces = settings.knots + 1 if settings.method == SMOOTH else points - 1
            effective = int(np.isfinite(queries).sum())
            if effective * pieces > INVERSE_BUDGET:
                raise FieldError(QUERY, f"{effective:,} queries × {pieces:,} pieces exceed the inversion budget of "
                                        f"{INVERSE_BUDGET:,}. Query fewer rows or use fewer support points.")
    return queries


def _schoenberg_whitney(knots, x):
    """True when each B-spline can be matched to its own support X (strictly increasing)."""
    count = len(knots) - 4
    design = BSpline.design_matrix(x, knots, 3).toarray()
    used = -1
    for basis in range(count):
        candidates = np.flatnonzero(design[used + 1:, basis] > 0)
        if not candidates.size:
            return False, design
        used += 1 + candidates[0]
    return True, design


def _fit(settings, x, y, counts):
    center, scale = (x[0] + x[-1]) / 2, (x[-1] - x[0]) / 2
    t = (x - center) / scale
    breaks, poly, nodes = x, None, y
    try:
        with np.errstate(all="ignore"):
            if settings.method == CUBIC:
                poly = CubicSpline(t, y, bc_type="natural")
            elif settings.method == AKIMA:
                poly = Akima1DInterpolator(t, y, method="akima")
    except ValueError:
        raise ValueError(f"The {settings.method.lower()} gives values outside the representable range. "
                         "Rescale Y before fitting.") from None
    if settings.method == SMOOTH:
        breaks = np.linspace(x[0], x[-1], settings.knots + 2)
        breaks[0], breaks[-1] = x[0], x[-1]
        inner = (breaks[1:-1] - center) / scale
        knots = np.r_[[t[0]] * 4, inner, [t[-1]] * 4]
        supported, design = _schoenberg_whitney(knots, t)
        if not supported:
            raise FieldError(KNOTS, "A knot interval holds no X values, so the spline is not determined. "
                                    "Use fewer interior knots.")
        if np.linalg.cond(design) > CONDITION_LIMIT:
            raise FieldError(KNOTS, "The X values do not determine every spline coefficient reliably. "
                                    "Use fewer interior knots.")
        coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
        spline = PPoly.from_spline(BSpline(knots, coefficients, 3, extrapolate=True))
        # Drop the empty intervals of the repeated end knots: one cubic per knot interval remains.
        pieces = np.flatnonzero(np.diff(spline.x) > 0)
        poly = PPoly(spline.c[:, pieces], np.r_[spline.x[pieces], spline.x[pieces[-1] + 1]], extrapolate=True)
        if poly.c.shape[1] != settings.knots + 1:
            raise ValueError("Could not convert the smoothing spline to its knot intervals.")
    elif settings.method == LOWESS:
        with np.errstate(all="ignore"):
            nodes = lowess(y, x, frac=settings.fraction, it=settings.iterations, is_sorted=True,
                           return_sorted=False)
        nodes = np.asarray(nodes, dtype=float)
        if not np.isfinite(nodes).all():
            raise ValueError("LOWESS could not smooth these values. Check the X spacing and the fraction.")
    if poly is not None and not np.isfinite(poly.c).all():
        raise ValueError(f"The {settings.method.lower()} gives values outside the representable range. "
                         "Rescale Y before fitting.")
    return Model(settings.method, x, y, counts, nodes, breaks, poly, center, scale)


# ---- inversion --------------------------------------------------------------------------------------------------

def _affine_roots(model, target):
    roots, plateaus = [], []
    x, v = model.x, model.nodes
    for lo, hi, first, last in zip(x[:-1], x[1:], v[:-1], v[1:], strict=True):
        if first == last:
            if first == target:
                plateaus.append([lo, hi])
            continue
        if not min(first, last) <= target <= max(first, last):
            continue
        if target == first:
            roots.append(lo)
        elif target == last:
            roots.append(hi)
        else:
            roots.append(min(max(lo + (hi - lo) * (target - first) / (last - first), lo), hi))
    return roots, plateaus


def _stationary(c3, c2, c1):
    """Real roots of 3c3 u² + 2c2 u + c1 in (0, 1), computed without cancellation."""
    a, b, c = 3 * c3, 2 * c2, c1
    if a == 0:
        return [-c / b] if b != 0 else []
    disc = b * b - 4 * a * c
    if disc < 0:
        return [-b / (2 * a)]  # closest approach: a tangent candidate, checked by value
    root = np.sqrt(disc)
    q = -(b + np.copysign(root, b)) / 2
    found = [q / a]
    if q != 0:
        found.append(c / q)
    return found


def _cubic_roots(coefficients, target):
    """Roots in [0, 1] of the scaled cubic sum(c_k u^k) − target, and whether it is flat at target."""
    c3, c2, c1, c0 = coefficients
    scale = max(abs(c3), abs(c2), abs(c1), abs(c0), abs(target))
    tolerance = VALUE_TOLERANCE * scale if scale else 0.0
    if max(abs(c3), abs(c2), abs(c1)) <= tolerance:
        return [], abs(c0 - target) <= tolerance

    def value(u):
        return ((c3 * u + c2) * u + c1) * u + c0 - target

    marks = sorted({0.0, 1.0, *(u for u in _stationary(c3, c2, c1) if 0 < u < 1)})
    found = []
    for u in marks:
        if abs(value(u)) <= tolerance:
            found.append(u)
    for lo, hi in zip(marks[:-1], marks[1:], strict=True):
        a, b = value(lo), value(hi)
        if abs(a) <= tolerance or abs(b) <= tolerance or np.sign(a) == np.sign(b):
            continue
        found.append(brentq(value, lo, hi, xtol=1e-15, rtol=4 * np.finfo(float).eps, maxiter=200))
    return found, False


def _polynomial_roots(model, target):
    roots, plateaus = [], []
    poly = model.poly
    for piece in range(model.piece_count):
        lo, hi = model.breaks[piece], model.breaks[piece + 1]
        width = poly.x[piece + 1] - poly.x[piece]
        # Local variable u in [0, 1] across the piece: c_k scaled by width^k.
        c = poly.c[:, piece] * width ** np.arange(3, -1, -1)
        if not np.isfinite(c).all():
            raise ValueError(f"Could not solve piece {piece + 1} ({lo:g} to {hi:g}) of the {model.method.lower()} "
                             "reliably. The source data are unchanged.")
        found, flat = _cubic_roots(c, target)
        if flat:
            plateaus.append([lo, hi])
            continue
        for u in found:
            roots.append(lo if u <= 0 else hi if u >= 1 else min(max(lo + (hi - lo) * u, lo), hi))
    return roots, plateaus


def _merge(roots, plateaus, model):
    joined = []
    for lo, hi in plateaus:
        if joined and joined[-1][1] == lo:
            joined[-1][1] = hi
        else:
            joined.append([lo, hi])
    roots = sorted(roots)
    distinct = []
    for root in roots:
        if distinct:
            piece = min(max(np.searchsorted(model.breaks, root, side="right") - 1, 0), model.piece_count - 1)
            width = model.breaks[piece + 1] - model.breaks[piece]
            if root - distinct[-1] <= ROOT_TOLERANCE * width:
                # Prefer an exact support/knot X when the duplicate comes from a shared end.
                if root in model.breaks:
                    distinct[-1] = root
                continue
        distinct.append(root)
    isolated = [root for root in distinct if not any(lo <= root <= hi for lo, hi in joined)]
    return isolated, joined


def invert(model, target):
    if model.poly is None:
        roots, plateaus = _affine_roots(model, target)
    else:
        roots, plateaus = _polynomial_roots(model, target)
    return _merge(roots, plateaus, model)


# ---- analysis ---------------------------------------------------------------------------------------------------

@dataclass
class SplineFit:
    tables: dict
    model: Model
    grid: np.ndarray
    curve: np.ndarray
    queries: pd.DataFrame | None


def fit_spline(frame, options):
    settings = read_options(frame, options)
    x, y, complete, support_x, support_y, counts = _support(frame, settings)
    queries = _check_budgets(frame, settings, len(support_x))
    model = _fit(settings, support_x, support_y, counts)
    segments = effective_segments(settings, len(support_x))
    grid = np.linspace(support_x[0], support_x[-1], segments + 1)
    curve = model.evaluate(grid)
    tables = {SUPPORT: pd.DataFrame({"X": support_x, "Y": support_y, "N": counts}),
              COORDINATES: pd.DataFrame({"X": grid, "Y": curve})}
    titles = _row_title_column(frame, {settings.x, settings.y, settings.query})
    labels = frame.index

    def leading(position):
        record = {"Source row": labels[position]}
        if titles is not None:
            record["Row title"] = frame[titles].iloc[position]
        return record

    if settings.residuals:
        rows = np.flatnonzero(complete)
        fitted = model.evaluate(x[rows])
        with np.errstate(all="ignore"):
            residual = y[rows] - fitted
        if not np.isfinite(residual).all():
            raise ValueError("A residual exceeds the representable range. Rescale Y before fitting.")
        columns = ["Source row", *(["Row title"] if titles is not None else []), "X", "Observed Y", "Fitted Y",
                   "Residual"]
        records = [leading(row) | {"X": x[row], "Observed Y": y[row], "Fitted Y": f, "Residual": r}
                   for row, f, r in zip(rows, fitted, residual, strict=True)]
        tables[RESIDUAL_SHEET] = pd.DataFrame(records, columns=columns, index=labels[rows])
    found = None
    if queries is not None:
        rows = np.flatnonzero(np.isfinite(queries))
        low, high = support_x[0], support_x[-1]
        records, solutions, plateaus = [], [], []
        for row in rows:
            target = queries[row]
            status, value = OUTSIDE, np.nan
            if settings.direction == Y_FROM_X:
                if low <= target <= high:
                    status, value = IN_RANGE, float(model.evaluate([target])[0])
            else:
                roots, flats = invert(model, target)
                if len(roots) > 1 or flats:
                    status = AMBIGUOUS
                    solutions.extend({"Source row": labels[row], "Solution": number, "X": root}
                                     for number, root in enumerate(roots, 1))
                    plateaus.extend({"Source row": labels[row], "Plateau": number, "X lower": lo, "X upper": hi}
                                    for number, (lo, hi) in enumerate(flats, 1))
                elif roots:
                    status, value = IN_RANGE, float(roots[0])
            records.append(leading(row) | {"Query": target, "Value": value, "Status": status})
        columns = ["Source row", *(["Row title"] if titles is not None else []), "Query", "Value", "Status"]
        found = pd.DataFrame(records, columns=columns, index=labels[rows])
        tables[VALUES] = found
        if solutions:
            tables[SOLUTIONS] = pd.DataFrame(solutions, columns=["Source row", "Solution", "X"])
        if plateaus:
            tables[PLATEAUS] = pd.DataFrame(plateaus, columns=["Source row", "Plateau", "X lower", "X upper"])
    return SplineFit(tables, model, grid, curve, found)
