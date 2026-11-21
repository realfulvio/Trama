"""Cox regression with status codes, predicted survival curves and residual sheets.

The proportional hazards fit is the one of ``models.cox_regression``. This module adds what is built on it:
event and censor codes read as the column's type, a Breslow baseline hazard, survival curves for explicit
covariate profiles, and martingale, deviance and Schoenfeld residuals. Scaled Schoenfeld residuals and the
Cox–Snell diagnostics of ``cox_fit_diagnostics`` reuse the same single fit. Recipes without any of the new options
call the original function and return exactly its sheets.
"""
from dataclasses import dataclass
import numbers
import warnings

import numpy as np
import pandas as pd
from pandas.api.types import is_complex_dtype, is_numeric_dtype
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from . import models
from .cox_fit_diagnostics import (COX_SNELL, SCALED, SCALED_GRAPH, SCALED_SHEET, SNELL_GRAPH, SNELL_HAZARD_SHEET,
                                  SNELL_SHEET, X_AXES, X_AXIS, cox_snell_figure, cox_snell_hazard,
                                  cox_snell_residuals, scaled_figure, scaled_schoenfeld, stable_expected_events,
                                  x_axis)
from .i18n import translate_message, ui
from .processing import TEXT, FieldError
from .reporting import Result, _plot

METHOD = "Cox regression"
EVENT_VALUE, CENSOR_VALUE = "Event value", "Censor value"
PREDICT, PROFILES = "Predict survival", "Profiles"
DIAGNOSTICS, SCHOENFELD = "Cox diagnostics", "Schoenfeld residuals"
GRAPH, GRAPH_TERM = "Graph display", "Schoenfeld term"
PROFILE_LIST = "Profile list"
LABEL, VALUES = "Label", "Values"
MAX_PROFILES = 12
AUTOMATIC, CURVES, DEVIANCE_GRAPH, SCHOENFELD_GRAPH = (
    "Automatic", "Predicted survival", "Deviance vs linear predictor", "Schoenfeld vs time")
GRAPHS = (AUTOMATIC, CURVES, DEVIANCE_GRAPH, SCHOENFELD_GRAPH, SCALED_GRAPH, SNELL_GRAPH)
STATUS_DEFAULTS = {EVENT_VALUE: "1", CENSOR_VALUE: "0"}
BASELINE_SHEET, PREDICTED_SHEET = "Baseline survival", "Predicted survival"
RESIDUAL_SHEET, SCHOENFELD_SHEET = "Cox residuals", "Schoenfeld residuals"

# Merged after the original Time, Event, Predictors, Categorical predictors and Ties fields. The scaled Schoenfeld
# and Cox–Snell outputs are independent of the earlier checkboxes and default to off.
OPTIONS = {EVENT_VALUE: TEXT, CENSOR_VALUE: TEXT, PREDICT: False, PROFILES: PROFILE_LIST,
           DIAGNOSTICS: False, SCHOENFELD: False, SCALED: False, COX_SNELL: False,
           GRAPH: GRAPHS, GRAPH_TERM: TEXT, X_AXIS: X_AXES}
NEW_OPTIONS = frozenset(OPTIONS)
FIT_DIAGNOSTICS = (SCALED, COX_SNELL)
OUTPUT_FIELDS = (PREDICT, DIAGNOSTICS, SCHOENFELD, SCALED, COX_SNELL)


def cox_message(error):
    """Translate graph names and output captions while keeping worksheet text literal."""
    def view_caption(text):
        canonical = next((view for view in GRAPHS if view.lower() == text), None)
        return ui(canonical).lower() if canonical else text

    return translate_message(error, "cox.error.", convert={"output": ui, "view": view_caption})


def effective_graph(choice, predict=False, diagnostics=False, schoenfeld=False, scaled=False, snell=False):
    """The view that will be drawn: an explicit choice, or the Automatic precedence over the active outputs.

    Predicted survival comes first, then the deviance residuals, the raw Schoenfeld residuals, the scaled ones and
    last the Cox–Snell plot. None when Automatic has no output that draws a graph.
    """
    if choice and choice != AUTOMATIC:
        return choice
    for view, active in ((CURVES, predict), (DEVIANCE_GRAPH, diagnostics), (SCHOENFELD_GRAPH, schoenfeld),
                         (SCALED_GRAPH, scaled), (SNELL_GRAPH, snell)):
        if active:
            return view
    return None


def cox_visibility(predict, graph, diagnostics=False, schoenfeld=False, scaled=False, snell=False):
    """Profiles belong to predicted survival; the term picker to both Schoenfeld views, the x axis to the scaled one.

    A field that an error can point to is shown: the term and the axis follow the view that is really drawn, also
    when the graph choice is Automatic.
    """
    view = effective_graph(graph, predict, diagnostics, schoenfeld, scaled, snell)
    return {PROFILES: bool(predict), GRAPH_TERM: view in (SCHOENFELD_GRAPH, SCALED_GRAPH),
            X_AXIS: view == SCALED_GRAPH}


@dataclass
class CoxFit:
    """One fit shared by every sheet and the graph."""
    data: pd.DataFrame
    design: pd.DataFrame
    references: dict
    beta: np.ndarray
    time: np.ndarray
    event: np.ndarray
    ties: str
    tables: dict
    # Covariance of the coefficients from the same fit (naive, from the information of the ties method).
    cov: np.ndarray | None = None

    @property
    def eta(self):
        return self.design.to_numpy(dtype=float) @ self.beta


def _missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def categories_of(data, name):
    """The worksheet's category labels, before complete-case filtering."""
    if name not in data:
        return []
    values = data[name][[not _missing(value) for value in data[name]]]
    return sorted(pd.unique(values.astype(str)).tolist())


def model_terms(data, predictors, categories):
    """Continuous names and non-reference category names in model order."""
    terms = []
    for name in predictors:
        if name in categories:
            terms.extend(f"{name} [{level}]" for level in categories_of(data, name)[1:])
        else:
            terms.append(name)
    return terms


def _number(value):
    """A finite float from a number or numeric text, or None."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, numbers.Real):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    return number if np.isfinite(number) else None


def _code(options, field):
    value = options.get(field, STATUS_DEFAULTS[field])
    if _missing(value):
        raise FieldError(field, f"Enter a value for {field.lower()}.")
    return value


def _matches(raw, code, field, column):
    """Rows equal to a status code, compared as the column's type."""
    if is_complex_dtype(raw.dtype):
        raise FieldError("Event", f'Column "{column}" contains complex data.')
    if is_numeric_dtype(raw.dtype):
        number = _number(code)
        if number is None:
            raise FieldError(field, f'{field} must be a number because column "{column}" is numeric.')
        return raw.astype(float).eq(number).fillna(False).to_numpy(dtype=bool)
    text, number = str(code).strip() if isinstance(code, str) else str(code), _number(code)

    def equal(value):
        if _missing(value):
            return False
        if isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)):
            return number is not None and float(value) == number
        return str(value) == text

    return np.fromiter((equal(value) for value in raw), dtype=bool, count=len(raw))


def code_statuses(frame, column, options):
    """1 for the event value, 0 for the censor value and NaN for empty cells; anything else is an error."""
    if column not in frame:
        raise FieldError("Event", "Choose an existing column for Event.")
    raw = frame[column]
    event, censor = _code(options, EVENT_VALUE), _code(options, CENSOR_VALUE)
    is_event = _matches(raw, event, EVENT_VALUE, column)
    is_censor = _matches(raw, censor, CENSOR_VALUE, column)
    same = str(event).strip() == str(censor).strip() or (
        is_numeric_dtype(raw.dtype) and _number(event) == _number(censor))
    if same or (is_event & is_censor).any():
        raise FieldError(CENSOR_VALUE, "Event and censor values must be different.")
    present = np.fromiter((not _missing(value) for value in raw), dtype=bool, count=len(raw))
    unknown = present & ~(is_event | is_censor)
    codes = pd.unique(pd.Series([str(value) for value in raw[present]], dtype=object))
    shown = ", ".join(repr(code) for code in codes[:8]) + (", …" if len(codes) > 8 else "")
    if unknown.any():
        row = int(np.flatnonzero(unknown)[0])
        raise FieldError("Event", f'Column "{column}" contains {str(raw.iloc[row])!r} at row {row + 1}, which is '
                                  f"neither the event value nor the censor value. Values present: {shown}.")
    if present.any() and not is_event.any():
        raise FieldError(EVENT_VALUE, f'No row of "{column}" equals the event value {str(event)!r}. '
                                      f"Values present: {shown}.")
    return pd.Series(np.where(is_event, 1., np.where(is_censor, 0., np.nan)), index=frame.index)


def fit_cox(frame, options):
    """Fit once with the coded statuses; the coefficient sheets are those of the original analysis."""
    time, event = options["Time"], options["Event"]
    predictors = list(options["Predictors"])
    categories = list(options.get("Categorical predictors") or [])
    ties = str(options.get("Ties", "Efron")).lower()
    if time == event:
        raise FieldError("Event", "Choose different columns for Time and Event.")
    if event in predictors:
        raise FieldError("Predictors", "The Event column cannot also be a predictor.")
    # Positional rows: Source row is the 1-based position in the worksheet, before missing cells are masked.
    source = frame.reset_index(drop=True)
    source = source.assign(**{event: code_statuses(source, event, options)})
    data, design, references = models._inputs(source, [time, event], predictors, categories, intercept=False)
    if (data[time] < 0).any() or data[event].sum() < 2:
        raise ValueError("Cox regression needs nonnegative times and at least two events.")
    if ties not in {"breslow", "efron"}:
        raise ValueError("Choose Breslow or Efron ties handling.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model = PHReg(data[time], design, status=data[event], ties=ties).fit(maxiter=100)
    except (ConvergenceWarning, np.linalg.LinAlgError) as error:
        raise ValueError("The Cox regression did not converge.") from error
    tables = models._report(model, design, references, len(frame), True)
    return CoxFit(data, design, references, np.asarray(model.params, dtype=float),
                  data[time].to_numpy(dtype=float), data[event].to_numpy(dtype=float) == 1, ties, tables,
                  np.asarray(model.cov_params(), dtype=float))


def _risk_sums(fit, weights):
    """Sum of weights over T_j >= t for each distinct event time, accumulated from the longest time down."""
    order = np.argsort(-fit.time, kind="stable")
    descending = -fit.time[order]
    times = np.unique(fit.time[fit.event])
    count = np.searchsorted(descending, -times, side="right")
    return times, np.cumsum(weights[order], axis=0)[count - 1]


def baseline(fit):
    """Breslow increments d_t / sum(exp(eta_j), T_j >= t) at the X = 0 reference of the coefficient sheet."""
    eta = fit.eta
    shift = float(eta.max())
    times, risk = _risk_sums(fit, np.exp(eta - shift))
    deaths = np.array([np.count_nonzero(fit.event & (fit.time == t)) for t in times], dtype=float)
    with np.errstate(over="ignore", divide="ignore"):
        jumps = np.exp(np.log(deaths) - np.log(risk) - shift)
    hazard = np.cumsum(jumps)
    if not (np.isfinite(jumps).all() and np.isfinite(hazard).all() and (jumps > 0).all()):
        raise ValueError("The baseline hazard is not representable for these data. Center or rescale the "
                         "continuous predictors.")
    return pd.DataFrame({"Time": times, "Events": deaths.astype(int), "Baseline hazard increment": jumps,
                         "Baseline cumulative hazard": hazard, "Baseline survival": np.exp(-hazard)})


def _category(data, name, value, label):
    series = data[name]
    levels = sorted(series.astype(str).unique())
    if isinstance(value, str) and value in levels:
        return value
    number = _number(value)
    for original in series.unique():
        if str(original) == str(value) or (number is not None and _number(original) == number):
            return str(original)
    raise FieldError(PROFILES, f'Profile "{label}": {value!r} is not a category of {name}. '
                               f"Categories: {', '.join(levels)}.")


def profile_rows(fit, profiles, predictors, categories):
    """Design rows coded exactly as the fit: same dummy columns, same reference level."""
    if not isinstance(profiles, (list, tuple)) or not 1 <= len(profiles) <= MAX_PROFILES:
        raise FieldError(PROFILES, f"Add 1 to {MAX_PROFILES} profiles to predict survival.")
    labels, rows = [], []
    for number, profile in enumerate(profiles, 1):
        if not isinstance(profile, dict) or not isinstance(profile.get(VALUES), dict):
            raise FieldError(PROFILES, f"Profile {number} is not a valid profile.")
        label = str(profile.get(LABEL, "")).strip()
        if not label:
            raise FieldError(PROFILES, f"Profile {number} needs a label.")
        if label in labels:
            raise FieldError(PROFILES, f'Profile labels must be unique: "{label}" appears twice.')
        values = profile[VALUES]
        unknown = [name for name in values if name not in predictors]
        if unknown:
            raise FieldError(PROFILES, f'Profile "{label}" sets {unknown[0]!r}, which is not a predictor of this '
                                       "fit.")
        row = {}
        for name in predictors:
            if name not in values or _missing(values[name]):
                raise FieldError(PROFILES, f'Profile "{label}" needs a value for {name}.')
            if name in categories:
                level = _category(fit.data, name, values[name], label)
                for other in sorted(fit.data[name].astype(str).unique())[1:]:
                    row[f"{name} [{other}]"] = float(level == other)
            else:
                number = _number(values[name])
                if number is None:
                    raise FieldError(PROFILES, f'Profile "{label}": {name} needs a finite number.')
                row[name] = number
        labels.append(label)
        rows.append([row[column] for column in fit.design.columns])
    return labels, np.asarray(rows, dtype=float)


def predicted_survival(fit, sheet, labels, rows):
    """S(t | x) = exp(-H0(t) exp(x b)) on the event times of the baseline, profile by profile."""
    hazard = sheet["Baseline cumulative hazard"].to_numpy()
    records = []
    with np.errstate(over="ignore"):
        for label, row in zip(labels, rows, strict=True):
            eta = float(row @ fit.beta)
            cumulative = np.exp(np.log(hazard) + eta)
            if not (np.isfinite(eta) and np.isfinite(cumulative).all()):
                raise FieldError(PROFILES, f'Predicted survival for profile "{label}" is not representable: its '
                                           "hazard ratio overflows. Check the profile values.")
            records.append(pd.DataFrame({"Profile": label, "Time": sheet["Time"].to_numpy(),
                                         "Survival": np.exp(-cumulative)}))
    return pd.concat(records, ignore_index=True)


def _deviance(martingale, event, mu):
    log_term = np.zeros_like(mu)
    log_term[event] = np.log(mu[event])
    argument = -2 * (martingale + np.where(event, log_term, 0.))
    tolerance = 1e-10 * (1 + np.abs(martingale) + np.abs(log_term))
    if (argument < -tolerance).any():
        raise ValueError("A deviance residual is not real for these data.")
    return np.sign(martingale) * np.sqrt(np.maximum(argument, 0.))


def expected_events(fit, sheet):
    """mu_i = H0(T_i) exp(eta_i) in source order: the Breslow baseline at the row's time times its hazard ratio.

    The product is formed on the log scale so that a small baseline and a large hazard ratio do not overflow
    before they meet. A time before the first jump has a real zero.
    """
    eta = fit.eta
    times, hazard = sheet["Time"].to_numpy(), sheet["Baseline cumulative hazard"].to_numpy()
    row_hazard = np.r_[0., hazard][np.searchsorted(times, fit.time, side="right")]
    with np.errstate(over="ignore", divide="ignore"):
        mu = np.where(row_hazard > 0, np.exp(np.log(np.where(row_hazard > 0, row_hazard, 1.)) + eta), 0.)
    if not (np.isfinite(mu).all() and np.isfinite(eta).all()):
        raise ValueError("Cox diagnostics are not finite for these data. Center or rescale the continuous "
                         "predictors.")
    return mu


def residuals(fit, sheet, time_name, event_name, mu=None):
    """Martingale and deviance residuals in source order, with mu_i = H0(T_i) exp(eta_i)."""
    eta = fit.eta
    mu = expected_events(fit, sheet) if mu is None else mu
    event = fit.event
    martingale = event - mu
    deviance = _deviance(martingale, event, mu)
    with np.errstate(over="ignore"):
        ratio = np.exp(eta)
    return pd.DataFrame({"Source row": fit.data.index.to_numpy() + 1, "Time": fit.time,
                         "Event": event.astype(int), "Linear predictor": eta, "Hazard ratio": ratio,
                         "Expected events": mu, "Martingale residual": martingale, "Deviance residual": deviance})


def schoenfeld(fit):
    """Raw residuals x_i minus the risk-set mean weighted by exp(eta), event rows only, in source order.

    Efron averages the d risk-set means obtained by removing r/d of the tied events' weights, r = 0 … d − 1;
    Breslow uses the full risk set.
    """
    x = fit.design.to_numpy(dtype=float)
    eta = fit.eta
    w = np.exp(eta - eta.max())
    weighted = np.column_stack([w, w[:, None] * x])
    times, risk = _risk_sums(fit, weighted)
    out = np.full_like(x, np.nan)
    for t, sums in zip(times, risk, strict=True):
        deaths = fit.event & (fit.time == t)
        d = int(deaths.sum())
        tied = weighted[deaths].sum(axis=0)
        fractions = np.arange(d) / d if fit.ties == "efron" else np.zeros(1)
        totals = sums[None, :] - fractions[:, None] * tied[None, :]
        means = (totals[:, 1:] / totals[:, :1]).mean(axis=0)
        out[deaths] = x[deaths] - means
    rows = fit.event
    if not np.isfinite(out[rows]).all():
        raise ValueError("Schoenfeld residuals are not finite for these data.")
    sheet = pd.DataFrame({"Source row": fit.data.index.to_numpy()[rows] + 1, "Time": fit.time[rows]})
    for position, name in enumerate(fit.design.columns):
        sheet[name] = out[rows, position]
    return sheet


def graph_view(o):
    """Validate the graph choice and return the view it would draw."""
    choice = o.get(GRAPH, AUTOMATIC) or AUTOMATIC
    if choice not in GRAPHS:
        raise FieldError(GRAPH, "Choose a graph to display.")
    if choice == AUTOMATIC:
        return effective_graph(choice, *(o.get(name, False) for name in OUTPUT_FIELDS))
    needed = {CURVES: PREDICT, DEVIANCE_GRAPH: DIAGNOSTICS, SCHOENFELD_GRAPH: SCHOENFELD,
              SCALED_GRAPH: SCALED, SNELL_GRAPH: COX_SNELL}[choice]
    if not o.get(needed):
        raise FieldError(GRAPH, f"Turn on {needed} to display {choice.lower()}.")
    return choice


def _curves_figure(fit, predicted, time_name):
    figure, axes = _plot("Predicted survival (Cox)", time_name, "Survival probability")
    last = float(fit.time.max())
    for label, group in predicted.groupby("Profile", sort=False):
        # The start (0, 1) and the extension to the last observed time are drawing points, not event rows.
        times = np.r_[0., group["Time"].to_numpy(), last]
        survival = np.r_[1., group["Survival"].to_numpy(), group["Survival"].iat[-1]]
        axes.step(times, survival, where="post", label=label)
    axes.set_ylim(0, 1.02)
    axes.set_xlim(left=0)
    axes.legend(title="Profile", frameon=False)
    return figure


def _term(o, fit):
    names = list(fit.design.columns)
    term = str(o.get(GRAPH_TERM) or "").strip()
    if not term:
        return names[0]
    if term not in names:
        raise FieldError(GRAPH_TERM, f"Choose one of the model terms: {', '.join(names)}.")
    return term


def _guard(field, legacy, call):
    """Run ``call``; a failure of a value that only a new output needs names that output's control.

    An output that already existed (``legacy``) keeps the plain error it always raised.
    """
    try:
        return call()
    except FieldError:
        raise
    except ValueError as error:
        if legacy:
            raise
        raise FieldError(field, str(error)) from error


def snell_expectation(fit, sheet=None):
    """The Cox–Snell residuals, mu_i = H0(T_i) exp(eta_i), for a recipe that did not ask for the residual sheet.

    The Breslow baseline sheet gives them directly. When that sheet is not representable, or a product
    underflows, the same quantity is formed on the log scale, which only fails when the values themselves do.
    """
    try:
        mu = expected_events(fit, baseline(fit) if sheet is None else sheet)
        if not ((mu == 0) & (fit.time >= fit.time[fit.event].min())).any():
            return mu
    except ValueError:
        pass
    return stable_expected_events(fit)


def cox_result(frame, o):
    """Dispatcher for the Cox regression dialog."""
    if not NEW_OPTIONS & o.keys():
        return Result(models.cox_regression(frame, o["Time"], o["Event"], o["Predictors"],
                                            o["Categorical predictors"], o["Ties"].lower()))
    predict, diagnostics, raw, scaled, snell = (bool(o.get(name, False)) for name in OUTPUT_FIELDS)
    graph = graph_view(o)
    axis = x_axis(o) if graph == SCALED_GRAPH else None
    fit = fit_cox(frame, o)
    tables = dict(fit.tables)
    sheet = baseline(fit) if predict or diagnostics else None
    if predict:
        predictors, categories = list(o["Predictors"]), list(o.get("Categorical predictors") or [])
        labels, rows = profile_rows(fit, o.get(PROFILES), predictors, categories)
        tables[BASELINE_SHEET] = sheet
        tables[PREDICTED_SHEET] = predicted_survival(fit, sheet, labels, rows)
    # The expected events are the Cox–Snell residuals: the residual sheet, when asked for, serves both outputs.
    expected = expected_events(fit, sheet) if diagnostics else None
    if diagnostics:
        tables[RESIDUAL_SHEET] = residuals(fit, sheet, o["Time"], o["Event"], expected)
    if raw or scaled:
        # One raw residual matrix for both sheets.
        schoenfeld_sheet = _guard(SCALED, raw, lambda: schoenfeld(fit))
        if raw:
            tables[SCHOENFELD_SHEET] = schoenfeld_sheet
        if scaled:
            tables[SCALED_SHEET] = scaled_schoenfeld(fit, schoenfeld_sheet)
    if snell:
        tables[SNELL_SHEET] = cox_snell_residuals(fit, snell_expectation(fit, sheet) if expected is None else expected)
        tables[SNELL_HAZARD_SHEET] = cox_snell_hazard(tables[SNELL_SHEET])
    figure = None
    if graph == CURVES:
        figure = _curves_figure(fit, tables[PREDICTED_SHEET], o["Time"])
    elif graph == DEVIANCE_GRAPH:
        rows = tables[RESIDUAL_SHEET]
        figure, axes = _plot("Cox deviance residuals", "Linear predictor", "Deviance residual")
        axes.axhline(0, color="#7f8c99", linewidth=1, zorder=1)
        axes.scatter(rows["Linear predictor"], rows["Deviance residual"], zorder=2)
    elif graph == SCHOENFELD_GRAPH:
        term = _term(o, fit)
        rows = tables[SCHOENFELD_SHEET]
        figure, axes = _plot(f"Schoenfeld residuals: {term}", o["Time"], f"Schoenfeld residual ({term})")
        axes.axhline(0, color="#7f8c99", linewidth=1, zorder=1)
        axes.scatter(rows["Time"], rows[term], zorder=2)
    elif graph == SCALED_GRAPH:
        figure = scaled_figure(tables[SCALED_SHEET], _term(o, fit), axis, o["Time"])
    elif graph == SNELL_GRAPH:
        figure = cox_snell_figure(tables[SNELL_HAZARD_SHEET])
    return Result(tables, figure)
