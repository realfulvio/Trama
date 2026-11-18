"""Inverse-variance meta-analysis of effect estimates, with a native forest plot.

One worksheet row is one independent study with an estimate and its standard error, both entered by the
user. ``Measure`` says how to read them:

* **Difference**: the estimate and its SE are on the original scale and are pooled as they are.
* **Ratio**: the estimate is the ratio itself (for example 1.25) and the SE is the standard error of the
  natural logarithm of the ratio. Pooling, intervals and tests happen on ln(ratio); the exponential is
  applied once, to estimates and limits, when the results are written. The log10 axis of the graph only
  changes the drawing.

With yᵢ the estimate on the analysis scale, vᵢ = SEᵢ² and τ² the between-study variance,
wᵢ = 1/(vᵢ + τ²), m = Σwᵢyᵢ/Σwᵢ and Q(τ²) = Σwᵢ(yᵢ − m)².

* Common effect: τ² = 0 for the calculation, SE = 1/√Σwᵢ, normal interval. Tau² is not estimated and its
  cell stays empty.
* Random effects: Paule–Mandel, τ² = 0 when Q(0) ≤ k − 1, otherwise the root of Q(τ²) = k − 1. The root is
  bracketed analytically (see ``_paule_mandel``), solved with Brent's method and checked for convergence;
  there is no fallback to any other estimator.
* Random interval: Normal (SE = 1/√Σwᵢ, normal quantile) or Modified Knapp–Hartung
  (q⋆ = Q(τ²)/(k − 1), SE = √(max(1, q⋆)/Σwᵢ), t quantile with k − 1 df).
* Cochran's Q, its p value (χ² with k − 1 df) and I² always come from τ² = 0.
* Optional approximate prediction interval for k ≥ 3 in the random-effects model:
  m ± t(k − 2)·√(τ² + SE²), with the SE of the chosen interval method.

The arithmetic runs on centred values divided by a power of two near the median SE, so very large or very
small units neither overflow nor lose their representable spread; every published number is checked to
be finite. Study identity is the physical worksheet position from 1, never the frame index, and duplicate
labels are kept as separate studies.
"""
from math import fsum
from numbers import Real

from matplotlib.patches import Polygon
from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator
import numpy as np
import pandas as pd
from scipy import optimize, stats

from .category_graphs import COLORS
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .reporting import Result, _plot

META_ANALYSIS = "Meta-analysis of effect estimates"
STUDY, ESTIMATE, SE = "Study", "Estimate", "Standard error"
MEASURE, MODEL, INTERVAL, LEVEL = "Measure", "Pooling model", "Random interval", "Confidence level (%)"
PREDICTION, LEAVE_ONE_OUT, SHOW_GRAPH = "Prediction interval", "Leave one out", "Show graph"
DIFFERENCE, RATIO = MEASURES = ("Difference", "Ratio")
COMMON, RANDOM = MODELS = ("Common effect", "Random effects (Paule–Mandel)")
MODIFIED_KH, NORMAL = INTERVALS = ("Modified Knapp–Hartung", "Normal")
OPTIONAL = "Optional"

# The first entry of a choice is its default.
OPTIONS = {STUDY: OPTIONAL, ESTIMATE: None, SE: None, MEASURE: MEASURES, MODEL: MODELS, INTERVAL: INTERVALS,
           LEVEL: 95.0, PREDICTION: False, LEAVE_ONE_OUT: False, SHOW_GRAPH: True}
COLUMN_FIELDS = (STUDY, ESTIMATE, SE)
DATA_FIELDS = (STUDY, ESTIMATE, SE, MEASURE)
MODEL_FIELDS = (MODEL, INTERVAL, LEVEL, PREDICTION, LEAVE_ONE_OUT, SHOW_GRAPH)
MIN_STUDIES, MAX_STUDIES = 2, 200

STUDIES_SHEET, POOLED_SHEET, HETEROGENEITY_SHEET, LOO_SHEET = (
    "Studies", "Pooled", "Heterogeneity", "Leave one out")
STUDY_COLUMNS = ["Study", "Source row", "Estimate", "Standard error", "Lower", "Upper", "Weight (%)"]
POOLED_COLUMNS = ["Studies", "Omitted studies", "Pooling model", "Interval method", "Estimate", "SE", "Lower",
                  "Upper", "Prediction lower", "Prediction upper", "Prediction status", "Confidence level (%)"]
HETEROGENEITY_COLUMNS = ["Q", "Q df", "Q p", "I² (%)", "Tau²"]
LOO_COLUMNS = ["Omitted source row", "Omitted study", "Studies", "Estimate", "Lower", "Upper", "Tau²", "Status"]

CALCULATED = "Calculated"
PI_NOT_REQUESTED = "Not requested."
PI_COMMON = "Not available: a prediction interval applies to the random-effects model."
PI_TWO = "Not available: an approximate prediction interval needs at least 3 studies (t with k − 2 df)."
PI_DONE = "Approximate: m ± t(k − 2)·√(τ² + SE²)."
LOO_ONE = "Not calculated: only one study remains after the omission; pooling needs at least two."

# Vector ids of the figure, kept in SVG exports.
DIAMOND_GID, REFERENCE_GID = "meta-pooled-diamond", "meta-null-reference"
PREDICTION_GID, INTERVALS_GID, POINTS_GID = "meta-prediction-interval", "meta-study-intervals", "meta-study-points"
MAX_SQUARE_AREA = 260.

# Interface captions and choices. Recipes keep the English field names and values.
TAB_KEYS = {"Studies": "meta.tab.studies", "Model and output": "meta.tab.model"}
LABEL_KEYS = {STUDY: "meta.field.study", ESTIMATE: "meta.field.estimate", SE: "meta.field.se",
              MEASURE: "meta.field.measure", MODEL: "meta.field.model", INTERVAL: "meta.field.interval",
              LEVEL: "meta.field.level", PREDICTION: "meta.field.prediction", LEAVE_ONE_OUT: "meta.field.loo",
              SHOW_GRAPH: "meta.field.graph"}
RATIO_SE_KEY = "meta.field.se_ratio"
CHOICE_KEYS = {DIFFERENCE: "meta.choice.difference", RATIO: "meta.choice.ratio", COMMON: "meta.choice.common",
               RANDOM: "meta.choice.random", MODIFIED_KH: "meta.choice.mkh", NORMAL: "meta.choice.normal"}
NOTE_KEYS = {DIFFERENCE: "meta.note.difference", RATIO: "meta.note.ratio"}
MODEL_NOTE_KEY = "meta.note.model"
ERROR_PREFIX = "meta.error."

_TINY = np.finfo(float).tiny
_EPS = np.finfo(float).eps


class MetaAnalysisCancelled(MonteCarloCancelled):
    """The leave-one-out loop stopped between two omissions; nothing is published."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise MetaAnalysisCancelled("Meta-analysis cancelled.")


def visibility(model):
    """Random interval and the prediction interval apply only to the random-effects model."""
    random = model == RANDOM
    return {INTERVAL: random, PREDICTION: random}


def cancellable(method, options):
    """Leave one out runs one fit per omission and can be cancelled between omissions."""
    return method == META_ANALYSIS and isinstance(options, dict) and options.get(LEAVE_ONE_OUT) is True


def shows_graph(options):
    return isinstance(options, dict) and options.get(SHOW_GRAPH, True) is not False


# ----- options -------------------------------------------------------------------------------------------------------

def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, f"{name}: choose one of the listed options.")
    return value


def _flag(options, name):
    value = options.get(name, OPTIONS[name])
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _level(options):
    value = options.get(LEVEL, OPTIONS[LEVEL])
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(LEVEL, "Confidence level (%) must be a finite number strictly between 0 and 100.")
    value = float(value)
    if not (np.isfinite(value) and 0 < value < 100 and 0 < 100 - value < 100):
        raise FieldError(LEVEL, "Confidence level (%) must be a finite number strictly between 0 and 100.")
    return value


def _column(frame, options, field, required, used):
    name = options.get(field)
    if name is None or (isinstance(name, str) and not name.strip()):
        if required:
            raise FieldError(field, f"Choose a column for {field}.")
        return None
    if not isinstance(name, str) or name not in frame.columns:
        raise FieldError(field, f'Choose an existing column for {field}: "{name}" is not in the worksheet.')
    if isinstance(frame[name], pd.DataFrame):
        raise FieldError(field, f'Worksheet column names must be unique: "{name}" appears more than once.')
    for other, chosen in used.items():
        if chosen == name:
            raise FieldError(field, f"{field}: choose a column different from {other}.")
    used[field] = name
    return name


def settings(frame, options):
    """Validated options as a plain dict; raises FieldError naming the field to correct."""
    if not isinstance(options, dict):
        raise FieldError(ESTIMATE, "Choose a column for Estimate.")
    measure = _choice(options, MEASURE, MEASURES)
    model = _choice(options, MODEL, MODELS)
    interval = _choice(options, INTERVAL, INTERVALS) if model == RANDOM else NORMAL
    level = _level(options)
    flags = {name: _flag(options, name) for name in (PREDICTION, LEAVE_ONE_OUT, SHOW_GRAPH)}
    used = {}
    estimate = _column(frame, options, ESTIMATE, True, used)
    se = _column(frame, options, SE, True, used)
    study = _column(frame, options, STUDY, False, used)
    return {"measure": measure, "model": model, "interval": interval, "level": level,
            "prediction": flags[PREDICTION], "leave_one_out": flags[LEAVE_ONE_OUT], "graph": flags[SHOW_GRAPH],
            "estimate": estimate, "se": se, "study": study}


# ----- reading the worksheet -----------------------------------------------------------------------------------------

def _blank(raw):
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    try:
        return bool(pd.isna(raw))
    except (TypeError, ValueError):
        return False


def _shown(raw):
    text = raw.strip() if isinstance(raw, str) else repr(raw)
    return text if len(text) <= 40 else text[:37] + "..."


def _number(raw, field, row):
    """A finite float, NaN for a blank or excluded cell, or a FieldError naming the field and the row."""
    if _blank(raw):
        return np.nan
    if isinstance(raw, str):
        text = raw.strip()
        try:
            value = float(text.replace(",", ".") if text.count(",") == 1 and "." not in text else text)
        except ValueError:
            raise FieldError(field, f"{field}: source row {row} is not a number ({_shown(raw)}).") from None
    elif isinstance(raw, (bool, np.bool_)) or not isinstance(raw, (int, float, np.integer, np.floating)):
        raise FieldError(field, f"{field}: source row {row} is not a number ({_shown(raw)}).")
    else:
        value = float(raw)
    if not np.isfinite(value):
        raise FieldError(field, f"{field}: source row {row} must be a finite number.")
    return value


def _label(raw, row):
    """The literal study label; a blank cell shows the row number. Integral numbers lose their trailing .0."""
    if _blank(raw):
        return f"Row {row}"
    if isinstance(raw, (float, np.floating)) and float(raw).is_integer() and abs(raw) < 1e15:
        return str(int(raw))
    return raw.strip() if isinstance(raw, str) else str(raw)


def read_studies(frame, chosen):
    """Studies with both values, in sheet order, and the number of rows omitted for a blank or excluded cell."""
    ratio = chosen["measure"] == RATIO
    estimates = frame[chosen["estimate"]]
    errors = frame[chosen["se"]]
    labels = frame[chosen["study"]] if chosen["study"] else None
    studies, omitted = [], 0
    for position in range(len(frame)):
        row = position + 1
        estimate = _number(estimates.iloc[position], ESTIMATE, row)
        se = _number(errors.iloc[position], SE, row)
        if ratio and not np.isnan(estimate) and estimate <= 0:
            raise FieldError(ESTIMATE, f"Estimate: source row {row} must be greater than zero for a ratio "
                                       f"({estimate:g}).")
        if not np.isnan(se) and se <= 0:
            raise FieldError(SE, f"Standard error: source row {row} must be greater than zero ({se:g}).")
        if np.isnan(estimate) or np.isnan(se):
            omitted += 1
            continue
        label = _label(labels.iloc[position], row) if labels is not None else f"Row {row}"
        studies.append((label, row, estimate, se))
    count = len(studies)
    if count < MIN_STUDIES:
        raise FieldError(ESTIMATE, f"Meta-analysis needs at least 2 studies with an estimate and a standard error; "
                                   f"{count} found.")
    if count > MAX_STUDIES:
        raise FieldError(ESTIMATE, f"Meta-analysis combines up to 200 studies; {count} found.")
    return studies, omitted


# ----- arithmetic ----------------------------------------------------------------------------------------------------

class _Scaled:
    """Analysis-scale values centred on a study estimate and divided by 2**exponent (an exact operation)."""

    def __init__(self, effects, errors):
        effects, errors = np.asarray(effects, dtype=float), np.asarray(errors, dtype=float)
        # A power of two near the median SE: division by it is exact and keeps vᵢ near 1.
        self.exponent = int(np.frexp(np.median(errors))[1])
        self.center = float(effects[np.argmin(errors)])
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            se = np.ldexp(errors, -self.exponent)
            self.variance = se * se
            self.effect = np.ldexp(effects - self.center, -self.exponent)
        if not (np.isfinite(self.variance).all() and (self.variance >= _TINY).all()):
            raise FieldError(SE, "Standard error: the standard errors span too many orders of magnitude to be "
                                 "combined.")
        if not np.isfinite(self.effect).all():
            raise FieldError(ESTIMATE, "Estimate: the estimates are too far apart relative to their standard errors "
                                       "to be combined.")

    def value(self, scaled):
        """An analysis-scale estimate from a scaled one."""
        with np.errstate(over="ignore", under="ignore"):
            return self.center + float(np.ldexp(scaled, self.exponent))

    def spread(self, scaled):
        """An analysis-scale SE or interval half-width from a scaled one."""
        with np.errstate(over="ignore", under="ignore"):
            return float(np.ldexp(scaled, self.exponent))

    def variance_of(self, scaled):
        """An analysis-scale variance (τ²) from a scaled one."""
        with np.errstate(over="ignore", under="ignore"):
            return float(np.ldexp(scaled, 2 * self.exponent))


def _weighted(effect, variance, tau):
    """Σw, the weighted mean, Q at τ² and the weights, all in scaled units."""
    with np.errstate(over="ignore", invalid="ignore"):
        weight = 1.0 / (variance + tau)
        total = fsum(weight)
        mean = fsum(weight * effect) / total
        q = fsum(weight * (effect - mean) ** 2)
    if not (np.isfinite(total) and total > 0 and np.isfinite(mean)):
        raise FieldError(SE, "Standard error: the standard errors span too many orders of magnitude to be "
                             "combined.")
    return total, mean, q, weight


def _paule_mandel(effect, variance, q0):
    """τ² solving Q(τ²) = k − 1, or 0 when Q(0) ≤ k − 1.

    Q decreases in τ². With S = Σ(yᵢ − ȳ)² (ȳ unweighted), Σwᵢ(yᵢ − m)² ≤ Σwᵢ(yᵢ − ȳ)² ≤ S/(v_min + τ²) and
    Σwᵢ(yᵢ − m)² ≥ S/(v_max + τ²), so the root lies in [max(0, S/(k − 1) − v_max), S/(k − 1) − v_min].
    """
    k = len(effect)
    if q0 <= k - 1:
        return 0.0
    mean = fsum(effect) / k
    spread = fsum((effect - mean) ** 2) / (k - 1)
    low, high = max(0.0, spread - float(variance.max())), spread - float(variance.min())

    def excess(tau):
        return _weighted(effect, variance, tau)[2] - (k - 1)

    if not (np.isfinite(low) and np.isfinite(high) and high > 0):
        raise FieldError(MODEL, "Pooling model: the Paule–Mandel estimate of tau² could not be bracketed.")
    if high <= low:
        return high
    at_low, at_high = excess(low), excess(high)
    if not (np.isfinite(at_low) and np.isfinite(at_high)):
        raise FieldError(MODEL, "Pooling model: the Paule–Mandel estimate of tau² could not be bracketed.")
    # The bounds are exact; a sign at the wrong end is rounding at the root itself.
    if at_low <= 0:
        return low
    if at_high >= 0:
        return high
    tau, report = optimize.brentq(excess, low, high, xtol=max(high * 2.0 ** -60, _TINY), rtol=4 * _EPS,
                                  maxiter=500, full_output=True, disp=False)
    if not report.converged or not np.isfinite(tau) or tau < 0:
        raise FieldError(MODEL, "Pooling model: the Paule–Mandel estimate of tau² did not converge.")
    return float(tau)


def _quantile(level, df=None):
    tail = (100.0 - level) / 200.0
    return float(stats.norm.isf(tail) if df is None else stats.t.isf(tail, df))


def _pool(scaled, index, model, interval, level, prediction):
    """Pool the studies at ``index`` with the chosen model. Values are analysis-scale except ``weights``."""
    effect, variance = scaled.effect[index], scaled.variance[index]
    k = len(effect)
    _, _, q0, _ = _weighted(effect, variance, 0.0)
    if not np.isfinite(q0):
        raise FieldError(ESTIMATE, "Estimate: the estimates are too far apart relative to their standard errors "
                                   "to be combined.")
    random = model == RANDOM
    tau = _paule_mandel(effect, variance, q0) if random else 0.0
    total, mean, q, weights = _weighted(effect, variance, tau)
    if random and interval == MODIFIED_KH:
        se, quantile = np.sqrt(max(1.0, q / (k - 1)) / total), _quantile(level, k - 1)
    else:
        se, quantile = np.sqrt(1.0 / total), _quantile(level)
    result = {"k": k, "q0": q0, "tau": tau, "weights": (weights / total) * 100.0,
              "estimate": scaled.value(mean), "se": scaled.spread(se),
              "lower": scaled.value(mean - quantile * se), "upper": scaled.value(mean + quantile * se),
              "tau2": scaled.variance_of(tau) if random else np.nan,
              "prediction": (np.nan, np.nan), "status": PI_NOT_REQUESTED}
    if random and tau > 0 and result["tau2"] == 0:
        raise FieldError(SE, "Standard error: the values are too small to represent tau² on the analysis scale.")
    if random and not np.isfinite(result["tau2"]):
        raise FieldError(SE, "Standard error: the values are too large to represent tau² on the analysis scale.")
    if prediction:
        if not random:
            result["status"] = PI_COMMON
        elif k < 3:
            result["status"] = PI_TWO
        else:
            width = _quantile(level, k - 2) * np.sqrt(tau + se * se)
            result["prediction"] = (scaled.value(mean - width), scaled.value(mean + width))
            result["status"] = PI_DONE
    return result


def _back(value, ratio):
    """Original scale: the exponential is applied once, to estimates and limits only."""
    if not ratio or not np.isfinite(value):
        return value
    with np.errstate(over="ignore", under="ignore"):
        return float(np.exp(value))


def _published(fit):
    """Every number the fit publishes must be finite; empty cells are only the ones not estimated."""
    required = [fit["estimate"], fit["se"], fit["lower"], fit["upper"]]
    if not np.isnan(fit["tau2"]) or fit["tau"] != 0:
        required.append(fit["tau2"])
    if fit["status"] == PI_DONE:
        required.extend(fit["prediction"])
    if not np.isfinite(np.asarray(required, dtype=float)).all() or not fit["se"] > 0:
        raise FieldError(ESTIMATE, "Estimate: the pooled result is outside the representable range.")


# ----- analysis ------------------------------------------------------------------------------------------------------

def _prepare(frame, options):
    chosen = settings(frame, options)
    studies, omitted = read_studies(frame, chosen)
    ratio = chosen["measure"] == RATIO
    values = np.array([study[2] for study in studies])
    errors = np.array([study[3] for study in studies])
    effects = np.log(values) if ratio else values
    return chosen, studies, omitted, ratio, values, errors, effects, _Scaled(effects, errors)


def _main_fit(chosen, ratio, scaled, count):
    fit = _pool(scaled, np.arange(count), chosen["model"], chosen["interval"], chosen["level"],
                chosen["prediction"])
    _published(fit)
    back = [_back(fit[key], ratio) for key in ("estimate", "lower", "upper")]
    back += [_back(value, ratio) for value in fit["prediction"]]
    # 0 or inf after the exponential means the ratio is not representable.
    if ratio and any(not np.isnan(value) and not (0 < value < np.inf) for value in back):
        raise FieldError(ESTIMATE, "Estimate: the pooled result is outside the representable range.")
    return fit, back


def check_options(frame, options):
    """Every field and value check, and the main fit, without leave one out or the figure.

    The dialog calls it so that field errors keep the dialog open; the worker repeats the whole analysis.
    """
    chosen, studies, omitted, ratio, values, errors, effects, scaled = _prepare(frame, options)
    _main_fit(chosen, ratio, scaled, len(studies))
    return chosen


def meta_analysis(frame, options, *, cancel=None):
    chosen, studies, omitted, ratio, values, errors, effects, scaled = _prepare(frame, options)
    count = len(studies)
    fit, back = _main_fit(chosen, ratio, scaled, count)
    level = chosen["level"]
    z = _quantile(level)
    with np.errstate(over="ignore", under="ignore"):
        study_lower = np.array([_back(value, ratio) for value in effects - z * errors])
        study_upper = np.array([_back(value, ratio) for value in effects + z * errors])
    for position, (low, high) in enumerate(zip(study_lower, study_upper, strict=True)):
        if not (np.isfinite(low) and np.isfinite(high)) or (ratio and not (low > 0 and high < np.inf)):
            raise FieldError(SE, f"Standard error: source row {studies[position][1]} gives an interval outside the "
                                 "representable range.")
    table = pd.DataFrame({"Study": [study[0] for study in studies], "Source row": [study[1] for study in studies],
                          "Estimate": values, "Standard error": errors, "Lower": study_lower,
                          "Upper": study_upper, "Weight (%)": fit["weights"]}, columns=STUDY_COLUMNS)
    pooled = pd.DataFrame([{
        "Studies": count, "Omitted studies": omitted, "Pooling model": chosen["model"],
        "Interval method": chosen["interval"], "Estimate": back[0], "SE": fit["se"], "Lower": back[1],
        "Upper": back[2], "Prediction lower": back[3], "Prediction upper": back[4],
        "Prediction status": fit["status"], "Confidence level (%)": level}], columns=POOLED_COLUMNS)
    q0 = fit["q0"]
    i2 = 100.0 * max(0.0, 1.0 - (count - 1) / q0) if q0 > 0 else 0.0
    heterogeneity = pd.DataFrame([{"Q": q0, "Q df": count - 1, "Q p": float(stats.chi2.sf(q0, count - 1)),
                                   "I² (%)": i2, "Tau²": fit["tau2"]}], columns=HETEROGENEITY_COLUMNS)
    tables = {STUDIES_SHEET: table, POOLED_SHEET: pooled, HETEROGENEITY_SHEET: heterogeneity}
    check_cancel(cancel)
    if chosen["leave_one_out"]:
        tables[LOO_SHEET] = _leave_one_out(studies, chosen, ratio, scaled, cancel)
    figure = _figure(table, fit, back, chosen, ratio) if chosen["graph"] else None
    check_cancel(cancel)
    return Result(tables, figure)


def _leave_one_out(studies, chosen, ratio, scaled, cancel):
    count = len(studies)
    rows = []
    for omitted in range(count):
        check_cancel(cancel)
        label, row = studies[omitted][0], studies[omitted][1]
        record = {"Omitted source row": row, "Omitted study": label, "Studies": count - 1, "Estimate": np.nan,
                  "Lower": np.nan, "Upper": np.nan, "Tau²": np.nan, "Status": LOO_ONE}
        if count - 1 >= MIN_STUDIES:
            index = np.delete(np.arange(count), omitted)
            try:
                fit = _pool(scaled, index, chosen["model"], chosen["interval"], chosen["level"], False)
                _published(fit)
                values = [_back(fit[key], ratio) for key in ("estimate", "lower", "upper")]
                if ratio and any(not 0 < value < np.inf for value in values):
                    raise FieldError(ESTIMATE, "Estimate: the pooled result is outside the representable range.")
            except FieldError as error:
                record["Status"] = f"Not calculated: {error}"
            else:
                record.update({"Estimate": values[0], "Lower": values[1], "Upper": values[2],
                               "Tau²": fit["tau2"], "Status": CALCULATED})
        rows.append(record)
    return pd.DataFrame(rows, columns=LOO_COLUMNS)


# ----- figure --------------------------------------------------------------------------------------------------------

def _figure(table, fit, back, chosen, ratio):
    count = len(table)
    model_short = "Random effects" if chosen["model"] == RANDOM else "Common effect"
    has_prediction = not np.isnan(back[3])
    rows = count + (2 if has_prediction else 1)
    estimate = table["Estimate"].to_numpy(float)
    lower, upper = table["Lower"].to_numpy(float), table["Upper"].to_numpy(float)
    weights = table["Weight (%)"].to_numpy(float)
    level = chosen["level"]
    reference = 1.0 if ratio else 0.0
    figure, axes = _plot(META_ANALYSIS, "Ratio (log10 scale)" if ratio else "Difference", "")
    per_row = .42 if rows <= 40 else max(.16, 16.8 / rows)
    figure.set_size_inches(8, max(3.2, 1.8 + per_row * rows))
    color, pooled_color = COLORS[0], "#1f2933"
    y = np.arange(count, dtype=float)
    intervals = axes.hlines(y, lower, upper, color=color, linewidth=1.5, zorder=2, label="_study intervals")
    intervals.set_gid(INTERVALS_GID)
    caps = [axes.plot(values, y, linestyle="none", marker="|", markersize=9, markeredgewidth=1.4, color=color,
                      zorder=2, label="_caps")[0] for values in (lower, upper)]
    # Marker area proportional to the weight of the model used; positions and limits are unchanged.
    points = axes.scatter(estimate, y, s=MAX_SQUARE_AREA * weights / weights.max(), marker="s", color=color,
                          edgecolors="white", linewidths=.5, zorder=3, label="Study estimate (area ∝ weight)")
    points.set_gid(POINTS_GID)
    pooled_y = count + .6
    half = .34
    diamond = Polygon([(back[1], pooled_y), (back[0], pooled_y - half), (back[2], pooled_y),
                       (back[0], pooled_y + half)], closed=True, facecolor=pooled_color, edgecolor=pooled_color,
                      linewidth=1., zorder=4, label=f"Pooled estimate ({level:g}% CI)")
    diamond.set_gid(DIAMOND_GID)
    axes.add_patch(diamond)
    ticks = [*y, pooled_y]
    labels = [*table["Study"].astype(str), f"Pooled · {model_short}"]
    prediction = None
    if has_prediction:
        prediction_y = pooled_y + 1.
        prediction = axes.plot([back[3], back[4]], [prediction_y, prediction_y], color="#b64e69", linewidth=2.2,
                               solid_capstyle="butt", zorder=3, label=f"Prediction interval ({level:g}%)")[0]
        prediction.set_gid(PREDICTION_GID)
        ticks.append(prediction_y)
        labels.append("Prediction interval")
    null = axes.axvline(reference, color="#5f6b76", linestyle="--", linewidth=1.1, zorder=1,
                        label=f"No effect ({reference:g})")
    null.set_gid(REFERENCE_GID)
    if ratio:
        axes.set_xscale("log", base=10)
        axes.xaxis.set_major_locator(LogLocator(base=10, subs=(1., 2., 5.)))
        axes.xaxis.set_minor_locator(NullLocator())
        axes.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axes.set_yticks(ticks, labels)
    size = 9 if rows <= 40 else max(5., 9 - (rows - 40) / 40)
    for label in axes.get_yticklabels():
        label.set_parse_math(False)
        label.set_fontsize(size)
    for text in (axes.title, axes.xaxis.label):
        text.set_parse_math(False)
    axes.set_ylim(ticks[-1] + .7, -.7)  # First study on top, pooled rows at the bottom.
    axes.spines["left"].set_visible(False)
    axes.tick_params(axis="y", length=0)
    spans = [*lower, *upper, back[1], back[2], reference]
    if has_prediction:
        spans += [back[3], back[4]]
    low, high = min(spans), max(spans)
    if ratio:
        pad = (np.log10(high) - np.log10(low)) * .06 or .3
        axes.set_xlim(10 ** (np.log10(low) - pad), 10 ** (np.log10(high) + pad))
    else:
        pad = (high - low) * .06 or max(abs(high), 1.) * .1
        axes.set_xlim(low - pad, high + pad)
    legend = axes.legend(loc="best", frameon=False, fontsize=8.5)
    for text in legend.get_texts():
        text.set_parse_math(False)
    axes._tramastat_meta = {"intervals": intervals, "caps": caps, "points": points, "diamond": diamond,
                            "prediction": prediction, "reference": null}
    axes._tramastat_numeric_axes = ("x",)
    axes._tramastat_categorical_axes = ("y",)
    return figure
