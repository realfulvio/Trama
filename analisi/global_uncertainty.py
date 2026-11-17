"""Response bands and forward predictions for Global fit custom equation (0.70).

Both come from the one joint fit already computed.

Nothing here fits again. The joint fit of :mod:`global_custom_fit` hands over its context: the free
coordinates θ in the order of the covariance, the map from each series' coefficients to those
coordinates, the physical covariance ``C`` (already multiplied by the residual variance), the global
RSS, N, P and df, and its decision on whether inference is available.

For series ``s`` at ``x`` the gradient ``g`` of ``f_s(x; θ)`` is taken with respect to the physical
coordinates of θ: a shared coordinate counts for every series, a local one only for its own series,
and a coefficient fixed for the whole fit or for one series has no coordinate and no variance::

    v_mean      = gᵀ C g                                   (full matrix, never only its diagonal)
    Confidence  = f ± t · sqrt(v_mean)
    Prediction  = f ± t · sqrt(v_mean + RSS / (df · k))     (k = 1 for the drawn band)

with ``t`` the two-sided Student quantile at ``Response level (%)`` on the global df. The intervals
are pointwise and asymptotic for a nonlinear equation; they are not simultaneous bands.

Gradients use central differences on the compiled equation (the safe grammar of
:mod:`custom_equations`; nothing is executed). The step of each coordinate follows its own size,
``max(|θᵢ|, SEᵢ)``, so a coefficient of size 1e-12 and one of size 1e12 are both handled; X is never
perturbed. Near a limit the difference becomes one-sided (second order) inside the limits. A
variance below ``-NEGATIVE`` times the size of the terms of the quadratic form is reported as
unavailable rather than hidden; smaller negatives are rounding and become zero.

Predictions (``Predict responses``) read new X values from ``Query X`` and assign each one to a
series through ``Query group``, normalised like the Group column of the fit. These columns never
select observations for the fit: the complete cases of X, Y, Group and SD stay the only data of the
fit, and a query row may have no observation at all. Each query row gets an outcome, in priority
order: missing X or group, unknown group, outside the observed X range of its own series (unless
``Allow extrapolation``), undefined equation, unavailable interval. For the mean of ``k`` new
observations (``Query replicate count``, Prediction only, 1 when empty) the residual term is divided
by ``k``; the variance of the fitted mean is not.

Only Unweighted fits get intervals. With an SD column the fit and the point predictions stay, and a
requested interval is a field error (the SD column does not define the variance of a new
observation away from the observed rows).
"""
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba
from scipy import stats

from .field_error import FieldError
from .fit_weights import INVERSE_VARIANCE, UNWEIGHTED

CURVE_BAND, RESPONSE_LEVEL, BAND_DRAWING = "Curve band", "Response level (%)", "Band drawing"
NONE, CONFIDENCE, PREDICTION = INTERVALS = ("None", "Confidence", "Prediction")
FILLED, LINES = DRAWINGS = ("Filled", "Lines")
DEFAULT_RESPONSE_LEVEL = 95.0
PREDICT, QUERY_X, QUERY_GROUP, QUERY_K = "Predict responses", "Query X", "Query group", "Query replicate count"
QUERY_INTERVAL, EXTRAPOLATE = "Query interval", "Allow extrapolation"
PREDICTIONS_SHEET = "Predictions"
PREDICTION_COLUMNS = ["Source row", "Group", "X", "Predicted", "SE mean", "Lower", "Upper", "Interval", "Level", "k",
                      "Extrapolated", "Status", "Reason"]
MAX_QUERIES = 10_000
MAX_REPLICATES = 2 ** 53
OK, EXTRAPOLATED, MISSING_X, MISSING_GROUP = "OK", "Extrapolated", "Missing X", "Missing group"
UNKNOWN_GROUP, OUTSIDE, UNDEFINED, NO_INTERVAL = ("Unknown group", "Outside domain", "Undefined model",
                                                  "Interval unavailable")
BANDS_SHEET, BAND_SETTINGS_SHEET = "Curve bands", "Curve band settings"
BAND_COLUMNS = ["Group", "X", "Predicted", "SE mean", "Lower", "Upper", "Status", "Reason"]
SETTINGS_COLUMNS = ["Group", "Band", "Level", "N", "df", "Available", "Status", "Reason", "Note"]
# Total gradient cells (evaluation points × max(1, free coordinates)) allowed for propagation.
MAX_PROPAGATION_CELLS = 2_000_000
GID = "trama-global-band:"
FILL_ALPHA = .18
NEGATIVE = 1e-10
CENTRAL_STEP, ONE_SIDED_STEP = 6e-6, 1e-4
NOTE = ("Pointwise intervals at the response level; Prediction is for one new observation (k = 1). "
        "They are not simultaneous bands.")


def _number(value):
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.integer, np.floating))


def _choice(options, key, choices, default, message):
    value = options.get(key, default)
    if value is None or value == "":
        value = default
    if not isinstance(value, str) or value not in choices:
        raise FieldError(key, message)
    return value


def response_level(options):
    """``Response level (%)`` as a float strictly between 0 and 100. Bool, nan and inf are refused."""
    raw = options.get(RESPONSE_LEVEL, DEFAULT_RESPONSE_LEVEL)
    if isinstance(raw, str):
        try:
            raw = float(raw.strip().replace(",", "."))
        except ValueError:
            raw = None
    if not _number(raw) or not np.isfinite(raw) or not 0 < float(raw) < 100:
        raise FieldError(RESPONSE_LEVEL, "The response level must be a number strictly between 0 and 100.")
    return float(raw)


def band_options(options, weighting):
    """``(band, level, drawing)``. Level and drawing are read only when a band is requested."""
    band = _choice(options, CURVE_BAND, INTERVALS, NONE, "Choose None, Confidence or Prediction for the curve band.")
    if band == NONE:
        return NONE, None, FILLED
    if weighting == INVERSE_VARIANCE:
        raise FieldError(CURVE_BAND, "Curve bands are available for Unweighted fits only. With an SD column the "
                                     "variance of a new observation is not defined along the curve. Use Unweighted, "
                                     "or turn the band off.")
    if weighting != UNWEIGHTED:
        raise FieldError(CURVE_BAND, "Curve bands are available for Unweighted fits only.")
    drawing = _choice(options, BAND_DRAWING, DRAWINGS, FILLED, "Choose Filled or Lines for the band drawing.")
    return band, response_level(options), drawing


def _flag(options, key):
    value = options.get(key, False)
    if value is None:
        return False
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(key, f"{key} must be on or off.")
    return bool(value)


class QuerySettings:
    """Validated query choices. Fields that the current choices do not use are ``None``."""

    def __init__(self, x, group, k, interval, level, extrapolate):
        self.x, self.group, self.k, self.interval = x, group, k, interval
        self.level, self.extrapolate = level, extrapolate

    def __eq__(self, other):
        return isinstance(other, QuerySettings) and vars(self) == vars(other)

    def __repr__(self):
        return f"QuerySettings({vars(self)!r})"


def query_options(options, columns, weighting):
    """Query choices, or ``None`` when Predict responses is off (no dependent field is then read)."""
    if not _flag(options, PREDICT):
        return None
    x, group = options.get(QUERY_X), options.get(QUERY_GROUP)
    if not isinstance(x, str) or x not in columns:
        raise FieldError(QUERY_X, "Choose the column with the X values to predict.")
    if not isinstance(group, str) or group not in columns:
        raise FieldError(QUERY_GROUP, "Choose the column that assigns each new X to a series.")
    if group == x:
        raise FieldError(QUERY_GROUP, "Query group must be a different column from Query X.")
    interval = _choice(options, QUERY_INTERVAL, INTERVALS, NONE, "Choose None, Confidence or Prediction for the "
                                                                 "query interval.")
    level = k = None
    if interval != NONE:
        if weighting != UNWEIGHTED:
            raise FieldError(QUERY_INTERVAL, "Intervals for new X values are available for Unweighted fits only. "
                                             "With an SD column only the predicted values are given: choose None.")
        level = response_level(options)
    if interval == PREDICTION:
        k = options.get(QUERY_K) or None
        if k is not None and (not isinstance(k, str) or k not in columns):
            raise FieldError(QUERY_K, "Choose an existing column for the replicate count, or leave it empty for k = 1.")
        if k in (x, group):
            raise FieldError(QUERY_K, "The replicate count column must differ from Query X and Query group.")
    return QuerySettings(x, group, k, interval, level, _flag(options, EXTRAPOLATE))


def _missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, (float, np.floating)) and np.isnan(value)


def _scalar(value):
    """A finite or infinite float, or ``None`` for text, bool and complex values."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, (int, np.integer)):
        return float(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return None if np.isnan(number) else number
    return None


def _query_x(series, column):
    """Query X as floats (nan when empty). Text, bool, complex and infinite values are field errors."""
    if series.dtype.kind in "iuf":
        values = series.to_numpy(dtype=float, na_value=np.nan)
        bad = np.isinf(values)
        if bad.any():
            raise FieldError(QUERY_X, f"Column {column} contains infinite values "
                                      f"(source row {series.index[np.flatnonzero(bad)[0]]}).")
        return values
    values = np.full(len(series), np.nan)
    for i, value in enumerate(series.to_numpy(dtype=object)):
        if _missing(value):
            continue
        number = _scalar(value)
        if number is None:
            raise FieldError(QUERY_X, f"Column {column} must hold real numbers; source row {series.index[i]} "
                                      f"contains {value!r}.")
        if not np.isfinite(number):
            raise FieldError(QUERY_X, f"Column {column} contains infinite values (source row {series.index[i]}).")
        values[i] = number
    return values


def _replicates(series, column, active):
    """k per active row: 1 when empty; otherwise a whole number from 1 to 2^53 (exact for Python ints)."""
    counts = np.ones(len(series))
    for i in np.flatnonzero(active):
        value = series.iloc[i]
        if _missing(value):
            continue
        message = (f"Column {column}: the replicate count must be a whole number from 1 to 2^53 "
                   f"(source row {series.index[i]} contains {value!r}).")
        if isinstance(value, (bool, np.bool_)):
            raise FieldError(QUERY_K, message)
        if isinstance(value, (int, np.integer)):
            if not 1 <= int(value) <= MAX_REPLICATES:
                raise FieldError(QUERY_K, message)
            counts[i] = float(value)
            continue
        number = _scalar(value)
        if number is None or not np.isfinite(number) or not number.is_integer() or not 1 <= number <= MAX_REPLICATES:
            raise FieldError(QUERY_K, message)
        counts[i] = number
    return counts


def prepare_queries(frame, settings, group_column, labels):
    """Active query rows in sheet order (duplicates kept), with their source index.

    A row is active when Query X or Query group holds a value; a replicate count alone does not make
    it active. Query group follows the normalisation of the fit: the Group values of the fitted
    series and their text labels. An empty text ``''`` is a real category, not a missing one.
    """
    x = _query_x(frame[settings.x], settings.x)
    groups = frame[settings.group].to_numpy(dtype=object)
    group_missing = np.array([_missing(value) for value in groups], dtype=bool)
    active = ~np.isnan(x) | ~group_missing
    if int(active.sum()) > MAX_QUERIES:
        raise FieldError(QUERY_X, f"Predict at most {MAX_QUERIES:,} rows at a time.")
    counts = (_replicates(frame[settings.k], settings.k, active) if settings.k is not None
              else np.ones(len(frame)))
    known = set(labels)
    levels = {}
    fitted = frame[group_column]
    for level in pd.unique(fitted[fitted.notna()]):
        if str(level) in known:
            try:
                levels[level] = str(level)
            except TypeError:
                pass
    rows = []
    for i in np.flatnonzero(active):
        value = groups[i]
        label = None
        if not group_missing[i]:
            try:
                label = levels.get(value)
            except TypeError:
                label = None
            if label is None and str(value) in known:
                label = str(value)
        rows.append({"source": frame.index[i], "x": x[i], "raw": None if group_missing[i] else value,
                     "label": label, "k": counts[i]})
    return rows


def check_budget(groups, points, band, queries, free, *, query_field=QUERY_X):
    """Refuse the propagation work before any gradient is allocated."""
    cells = (groups * points if band != NONE else 0) + queries
    if cells * max(1, free) > MAX_PROPAGATION_CELLS:
        if band != NONE:
            raise FieldError("Curve points", "The response bands exceed the uncertainty budget of "
                                             f"{MAX_PROPAGATION_CELLS:,} cells. Use fewer curve points"
                                             + (" or fewer queries." if queries else "."))
        raise FieldError(query_field, "The predictions exceed the uncertainty budget of "
                                      f"{MAX_PROPAGATION_CELLS:,} cells. Use fewer query rows.")


# --- Inference context -------------------------------------------------------------------------------

def blocked(solved):
    """Why the joint fit gives no interval, or ``None`` when its covariance can be propagated."""
    if not solved["p"]:
        return "Every coefficient is fixed, so there is no parameter uncertainty to propagate."
    if np.any(solved["active"]):
        return ("A free coefficient is at a limit, so the covariance of the global fit is omitted and "
                "no interval is reported.")
    if not solved["infer"]:
        return ("The fit is numerically perfect (residual variance within round-off of zero), so no interval "
                "is reported.")
    if not solved["df"] > 0:
        return "The global fit has no residual degrees of freedom."
    if not np.isfinite(solved["covariance"]).all():
        return "The covariance of the global fit is missing or not finite."
    return None


def quantile(level, df):
    return float(stats.t.ppf((1 + level / 100) / 2, df))


def _slots(solved, series):
    """``[(coordinate, coefficient)]`` that move series ``series``, in the order of the covariance."""
    mapping = solved["mapping"]
    return [(int(slot), name) for name, slot in zip(solved["names"], mapping[series]) if slot >= 0]


def response(compiled, solved, series, x):
    """Point values, mean variances and per-point reasons at ``x`` for one series.

    ``variance`` is nan where no interval can be given; ``reasons`` then names the cause. The point
    value is kept whenever the equation is defined. The caller has checked :func:`blocked`.
    """
    x = np.asarray(x, dtype=float)
    parameters = solved["maps"][series]
    with np.errstate(all="ignore"):
        predicted = np.asarray(compiled.evaluate(x, parameters), dtype=float)
    covariance = solved["covariance"]
    slots = _slots(solved, series)
    gradient = np.zeros((len(x), covariance.shape[0]))
    reasons = np.full(len(x), "", dtype=object)
    lower, upper = solved["bounds"]
    for slot, name in slots:
        value = float(parameters[name])
        size = max(abs(value), float(np.sqrt(covariance[slot, slot])))
        if not np.isfinite(size) or not size > 0:
            reasons[:] = "The gradient cannot be scaled for a coefficient."
            return predicted, np.full(len(x), np.nan), reasons

        def at(offset, name=name, value=value):
            shifted = dict(parameters)
            shifted[name] = value + offset
            with np.errstate(all="ignore"):
                return np.asarray(compiled.evaluate(x, shifted), dtype=float)

        step = CENTRAL_STEP * size
        down, up = value - lower[slot], upper[slot] - value
        if min(down, up) > step:
            with np.errstate(all="ignore"):
                gradient[:, slot] = (at(step) - at(-step)) / (2 * step)
            continue
        room, sign = (up, 1.) if up >= down else (down, -1.)
        step = min(ONE_SIDED_STEP * size, room / 4)
        if not step > 0:
            reasons[:] = "No admissible step for the gradient at a coefficient limit."
            return predicted, np.full(len(x), np.nan), reasons
        with np.errstate(all="ignore"):
            gradient[:, slot] = sign * (-3 * predicted + 4 * at(sign * step) - at(sign * 2 * step)) / (2 * step)
    with np.errstate(all="ignore"):
        variance = np.einsum("ij,jk,ik->i", gradient, covariance, gradient)
        magnitude = np.einsum("ij,jk,ik->i", np.abs(gradient), np.abs(covariance), np.abs(gradient))
    finite = np.isfinite(gradient).all(axis=1) & np.isfinite(variance) & np.isfinite(predicted)
    negative = finite & (variance < -NEGATIVE * magnitude)
    reasons[~finite] = "The gradient of the equation is not finite at this X."
    reasons[negative] = "The variance of the response is substantially negative here: the covariance is not valid."
    variance = np.where(finite & ~negative, np.maximum(variance, 0.), np.nan)
    return predicted, variance, reasons


def limits(predicted, variance, kind, level, solved, k=1.):
    """``(SE mean, lower, upper)``; nan wherever ``variance`` is nan."""
    with np.errstate(all="ignore"):
        return _limits(predicted, variance, kind, level, solved, k)


def _limits(predicted, variance, kind, level, solved, k):
    se = np.sqrt(variance)
    spread = variance + (solved["rss"] / (solved["df"] * np.asarray(k, dtype=float)) if kind == PREDICTION else 0.)
    half = quantile(level, solved["df"]) * np.sqrt(spread)
    return se, predicted - half, predicted + half


# --- Curve bands -------------------------------------------------------------------------------------

def band_tables(compiled, solved, curves, band, level):
    """``Curve bands`` on the grid of Curve, ``Curve band settings``, and the drawable limits per series.

    ``curves`` is ``[(label, grid, predicted)]`` in series order, exactly the rows of Curve.
    """
    reason = blocked(solved)
    rows, settings, drawn = [], [], []
    for series, (label, grid, predicted) in enumerate(curves):
        if reason is None:
            _, variance, reasons = response(compiled, solved, series, grid)
            se, lower, upper = limits(predicted, variance, band, level, solved)
            ok = np.isfinite(lower) & np.isfinite(upper)
            reasons = np.where(ok, "", np.where(reasons == "", "The interval is not finite at this X.", reasons))
        else:
            se = lower = upper = np.full(len(grid), np.nan)
            ok = np.zeros(len(grid), dtype=bool)
            reasons = np.full(len(grid), reason, dtype=object)
        for x, pred, error, low, high, good, why in zip(grid, predicted, se, lower, upper, ok, reasons):
            rows.append({"Group": label, "X": float(x), "Predicted": float(pred),
                         "SE mean": float(error) if good else np.nan, "Lower": float(low) if good else np.nan,
                         "Upper": float(high) if good else np.nan, "Status": "OK" if good else "Unavailable",
                         "Reason": "" if good else str(why)})
        count = int(ok.sum())
        status = "Available" if count == len(grid) else "Partial" if count else "Unavailable"
        why = "" if count == len(grid) else next(str(r) for r, good in zip(reasons, ok) if not good)
        if status == "Partial":
            why = f"{len(grid) - count} of {len(grid)} points have no interval. {why}"
        settings.append({"Group": label, "Band": band, "Level": level, "N": solved["n"], "df": solved["df"],
                         "Available": bool(count), "Status": status, "Reason": why, "Note": NOTE})
        drawn.append((label, grid, np.where(ok, lower, np.nan), np.where(ok, upper, np.nan)))
    table = pd.DataFrame(rows, columns=BAND_COLUMNS)
    summary = pd.DataFrame(settings, columns=SETTINGS_COLUMNS)
    summary["Available"] = summary["Available"].astype(bool)
    return table, summary, drawn


# --- Drawing and the runtime link to the fitted line --------------------------------------------------

def _source(value):
    return value.item() if hasattr(value, "item") else value


def prediction_table(compiled, solved, packed, rows, settings):
    """The Predictions sheet: one row per active query row, an outcome and a reason for each."""
    interval, level, extrapolate = settings.interval, settings.level, settings.extrapolate
    reason = blocked(solved) if interval != NONE else None
    index = {part["label"]: i for i, part in enumerate(packed)}
    domain = [(float(np.min(part["X"])), float(np.max(part["X"]))) for part in packed]
    records = []
    pending = {}
    for row in rows:
        record = {"Source row": _source(row["source"]), "Group": None, "X": row["x"], "Predicted": np.nan,
                  "SE mean": np.nan, "Lower": np.nan, "Upper": np.nan, "Interval": interval,
                  "Level": level if interval != NONE else np.nan,
                  "k": row["k"] if interval == PREDICTION else np.nan, "Extrapolated": False,
                  "Status": "", "Reason": ""}
        records.append(record)
        if row["raw"] is not None:
            record["Group"] = row["label"] if row["label"] is not None else str(row["raw"])
        if np.isnan(row["x"]):
            record.update(Status=MISSING_X, Reason="Query X is empty for this row.")
            continue
        if row["raw"] is None:
            record.update(Status=MISSING_GROUP, Reason="Query group is empty, so the row has no series.")
            continue
        if row["label"] is None:
            record.update(Status=UNKNOWN_GROUP, Reason=f"{row['raw']!s} is not a fitted series. Use one of: "
                                                       + ", ".join(repr(part["label"]) for part in packed) + ".")
            continue
        series = index[row["label"]]
        low, high = domain[series]
        outside = not low <= row["x"] <= high
        if outside and not extrapolate:
            record.update(Status=OUTSIDE, Reason=f"X = {row['x']:g} lies outside the observed X range of this series "
                                                 f"({low:g} to {high:g}). Turn on Allow extrapolation to evaluate it.")
            continue
        record["Extrapolated"] = outside
        pending.setdefault(series, []).append((record, row))
    for series, items in pending.items():
        x = np.array([row["x"] for _, row in items])
        if interval != NONE and reason is None:
            predicted, variance, why = response(compiled, solved, series, x)
            k = np.array([row["k"] for _, row in items]) if interval == PREDICTION else 1.
            se, lower, upper = limits(predicted, variance, interval, level, solved, k)
        else:
            parameters = solved["maps"][series]
            with np.errstate(all="ignore"):
                predicted = np.asarray(compiled.evaluate(x, parameters), dtype=float)
            se = lower = upper = np.full(len(x), np.nan)
            why = np.full(len(x), reason or "", dtype=object)
        for j, (record, row) in enumerate(items):
            if not np.isfinite(predicted[j]):
                record.update(Status=UNDEFINED, Reason=f"The equation is not defined at X = {row['x']:g} for this "
                                                       "series (for example a division by zero or a logarithm of a "
                                                       "non-positive value).")
                continue
            record["Predicted"] = float(predicted[j])
            done = EXTRAPOLATED if record["Extrapolated"] else OK
            note = "Extrapolated beyond the observed X range of this series." if record["Extrapolated"] else ""
            if interval == NONE:
                record.update(Status=done, Reason=note)
            elif np.isfinite(lower[j]) and np.isfinite(upper[j]):
                record.update({"SE mean": float(se[j]), "Lower": float(lower[j]), "Upper": float(upper[j]),
                               "Status": done, "Reason": note})
            else:
                text = str(why[j]) or "The interval is not finite at this X."
                record.update(Status=NO_INTERVAL, Reason=(note + " " if note else "") + text)
    table = pd.DataFrame(records, columns=PREDICTION_COLUMNS)
    for column in ("X", "Predicted", "SE mean", "Lower", "Upper", "Level", "k"):
        table[column] = table[column].astype(float)
    table["Extrapolated"] = table["Extrapolated"].astype(bool)
    for column in ("Group", "Interval", "Status", "Reason"):
        # Object columns keep a missing group as None, distinct from the empty category ''.
        table[column] = pd.Series([record[column] for record in records], index=table.index, dtype=object)
    if table.empty:
        table["Source row"] = table["Source row"].astype("int64")
    return table


def _runs(ok):
    """Start and stop of each run of consecutive drawable points (two points at least)."""
    edges = np.diff(np.concatenate([[0], ok.astype(int), [0]]))
    return [(a, b) for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)) if b - a >= 2]


def _line_hidden(line):
    no_line = line.get_linestyle() in ("None", "none", "", " ", None)
    no_marker = line.get_marker() in ("None", "none", "", " ", None)
    return not line.get_visible() or (no_line and no_marker)


def sync_bands(axes):
    """Give every band the color and visibility of its own fitted line (after any style change)."""
    for line, collection, drawing in getattr(axes, "_tramastat_response_bands", ()):
        color = line.get_color()
        if drawing == FILLED:
            collection.set_facecolor(to_rgba(color, FILL_ALPHA))
            collection.set_edgecolor("none")
        else:
            collection.set_color(color)
        collection.set_visible(not _line_hidden(line))


def draw_bands(axes, drawn, lines, drawing):
    """One PolyCollection (Filled) or LineCollection (Lines) per series with a drawable interval.

    Gaps where the interval is unavailable stay open. The collections have no legend label and are
    not Line2D or scatter artists, so the series identities of the graph do not move. Each band is
    linked to the fitted line drawn for the same series, not to its initial color.
    """
    links = []
    for (label, x, lower, upper), line in zip(drawn, lines):
        ok = np.isfinite(lower) & np.isfinite(upper)
        runs = _runs(ok)
        if not runs:
            continue
        color = line.get_color()
        if drawing == FILLED:
            polygons = [np.column_stack([np.concatenate([x[a:b], x[a:b][::-1]]),
                                         np.concatenate([lower[a:b], upper[a:b][::-1]])]) for a, b in runs]
            collection = PolyCollection(polygons, facecolors=[to_rgba(color, FILL_ALPHA)], edgecolors="none",
                                        linewidths=0, zorder=.5, label="_nolegend_")
        else:
            segments = [np.column_stack([x[a:b], edge[a:b]]) for a, b in runs for edge in (lower, upper)]
            collection = LineCollection(segments, colors=[color], linestyles="--", linewidths=1., zorder=.5,
                                        label="_nolegend_")
        collection.set_gid(f"{GID}{label}")
        axes.add_collection(collection, autolim=True)
        links.append((line, collection, drawing))
    if links:
        axes.autoscale_view()
        axes._tramastat_response_bands = links
        axes._tramastat_after_style = sync_bands
    return links
