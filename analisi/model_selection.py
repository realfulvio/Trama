"""Compare nonlinear models with the small-sample Akaike criterion (AICc).

Two to eight catalog equations are fitted to the same complete observations of every
group, always unweighted, and ranked by AICc. The candidates may be non-nested.

With ``p`` free coefficients the model has ``K = p + 1`` estimated parameters: the
coefficients plus the Gaussian error variance. ``RSS`` is the raw residual sum of squares and

    AIC  = N ln(RSS / N) + 2K            (the constant common to every model is omitted)
    AICc = AIC + 2K(K + 1) / (N − K − 1)

AICc needs ``N > K + 1``. A perfect fit (RSS numerically zero compared with the total sum of
squares, or exactly zero) makes the logarithm meaningless, so that row is unavailable with the
reason in ``Status``. A fit that fails (a domain error, no convergence) leaves an informative
row and the other candidates are kept.

Among the valid rows ``Delta AICc = AICc − min(AICc)`` and the Akaike weight is
``exp(−Δ/2) / Σ exp(−Δ/2)``. Only differences are exponentiated, so nothing overflows and the
weights sum to one. A weight is a share relative to the selected candidates, not the
probability that a model is true, and no p value is produced. Rows are sorted by AICc; ties
(equal within rounding) keep the order of the selection and unavailable rows follow, also in
selection order. A group with fewer than two valid models keeps its fits and reports the
comparison as unavailable in the Summary instead of weights.
"""
from dataclasses import dataclass
import math
import warnings

import numpy as np
import pandas as pd

from . import stats as engine
from .category_graphs import COLORS
from .curve_models import MODEL_GROUPS, MODELS
from .processing import FieldError, _column
from .reporting import Result, _plot

COMPARE_MODELS = "Compare models (AICc)"
MODELS_FIELD, SHOW_GRAPH = "Models", "Show graph"
MODEL_LIST = "Model list"  # Dialog kind of the Models field: an ordered list of catalog names.
MIN_MODELS, MAX_MODELS = 2, 8
MAX_GROUPS = 12
RANKING, PARAMETERS, SUMMARY = "Model ranking", "Model parameters", "Summary"
RANKING_COLUMNS = ["Group", "Model", "N", "Parameters", "K", "RSS", "AIC", "AICc", "Delta AICc", "Akaike weight",
                   "Status"]
OK = "OK"
GID = "model-selection:"
NOTE = ("Akaike weights are shares relative to the selected models, not the probability that a model is true. "
        "AICc is calculated from unweighted fits and gives no p value.")

# Selectable equations: those Nonlinear regression can fit alone, in catalog family order.
_ORDERED = tuple(dict.fromkeys(name for names in MODEL_GROUPS.values() for name in names))
CANDIDATES = tuple(name for name in dict.fromkeys((*_ORDERED, *MODELS))
                   if not (MODELS[name].required_fixed or MODELS[name].required_shared))
OPTIONS = {"X": None, "Y": None, "Group": "Optional", MODELS_FIELD: MODEL_LIST, SHOW_GRAPH: True}

# RSS at or below this fraction of the total sum of squares counts as numerically zero.
_PERFECT = 1e-12
# AICc values closer than this (relative) are ties.
_TIE = 1e-9


@dataclass
class Candidate:
    """One model fitted to one group."""
    model: str
    position: int
    parameters: int
    fit: object = None
    rss: float = np.nan
    aic: float = np.nan
    aicc: float = np.nan
    status: str = OK

    @property
    def valid(self):
        return self.status == OK and math.isfinite(self.aicc)


def criteria(rss, n, parameters, total):
    """Return ``(AIC, AICc, status)``; undefined criteria are NaN and the status says why."""
    k = parameters + 1
    if not math.isfinite(rss):
        return np.nan, np.nan, "RSS is not finite, so AIC and AICc are undefined."
    if rss <= 0 or rss <= _PERFECT * total:
        return np.nan, np.nan, "Perfect fit: RSS is numerically zero, so AIC and AICc are undefined."
    with np.errstate(all="ignore"):
        aic = float(n * np.log(rss / n) + 2 * k)
    if not math.isfinite(aic):
        return np.nan, np.nan, "RSS is too small to take its logarithm, so AIC and AICc are undefined."
    if n - k - 1 <= 0:
        return aic, np.nan, (f"AICc is unavailable: N = {n} must be greater than K + 1 = {k + 1} "
                             f"(K counts the {parameters} coefficient{'s' if parameters != 1 else ''} "
                             "and the error variance).")
    return aic, float(aic + 2 * k * (k + 1) / (n - k - 1)), OK


def akaike_weights(aicc):
    """Delta AICc and Akaike weights of valid criteria. Only differences are exponentiated."""
    aicc = np.asarray(aicc, dtype=float)
    delta = aicc - aicc.min()
    weight = np.exp(-delta / 2)
    return delta, weight / weight.sum()


def rank(candidates):
    """Order by AICc, ties in selection order, then unavailable rows in selection order."""
    valid = sorted((c for c in candidates if c.valid), key=lambda c: c.aicc)
    ordered, block = [], []
    for candidate in valid:
        if block and abs(candidate.aicc - block[-1].aicc) > _TIE * max(1., abs(candidate.aicc), abs(block[-1].aicc)):
            ordered.extend(sorted(block, key=lambda c: c.position))
            block = []
        block.append(candidate)
    ordered.extend(sorted(block, key=lambda c: c.position))
    ordered.extend(sorted((c for c in candidates if not c.valid), key=lambda c: c.position))
    return ordered


def _models(options):
    names = options.get(MODELS_FIELD)
    if names is None or isinstance(names, str) or not isinstance(names, (list, tuple)):
        raise FieldError(MODELS_FIELD, f"Choose {MIN_MODELS} to {MAX_MODELS} models to compare.")
    names = list(names)
    if not all(isinstance(name, str) for name in names):
        raise FieldError(MODELS_FIELD, "Choose equations from the catalog.")
    if len(names) < MIN_MODELS:
        raise FieldError(MODELS_FIELD, f"Choose at least {MIN_MODELS} models to compare "
                                       f"(this selection has {len(names)}).")
    if len(names) > MAX_MODELS:
        raise FieldError(MODELS_FIELD, f"Compare at most {MAX_MODELS} models at a time "
                                       f"(this selection has {len(names)}).")
    for position, name in enumerate(names):
        if name not in MODELS:
            raise FieldError(MODELS_FIELD, f"{name} is not an equation of the catalog.")
        if name in names[:position]:
            raise FieldError(MODELS_FIELD, f"{name} is selected more than once. Choose each model once.")
        if name not in CANDIDATES:
            spec = MODELS[name]
            raise FieldError(MODELS_FIELD, f"{name} needs "
                                           f"{'fixed values' if spec.required_fixed else 'a joint fit'} and cannot be "
                                           "compared here. Use Global nonlinear regression.")
    return names


def _text(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = value if isinstance(value, str) else str(value.item() if isinstance(value, np.generic) else value)
    return text if text.strip() else None


def _groups(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("X", "Worksheet column names must be unique.")
    names = {}
    for field in ("X", "Y"):
        value = options.get(field) or None
        if not isinstance(value, str) or value not in frame:
            raise FieldError(field, f"Choose an existing column for {field}.")
        names[field] = value
    if names["X"] == names["Y"]:
        raise FieldError("Y", "Choose different columns for X and Y.")
    group = options.get("Group") or None
    if group is not None:
        if not isinstance(group, str) or group not in frame:
            raise FieldError("Group", "Choose an existing column for Group.")
        if group in names.values():
            raise FieldError("Group", "Choose a Group column different from X and Y.")
    x = _column(frame, names["X"], "X").to_numpy(dtype=float)
    y = _column(frame, names["Y"], "Y").to_numpy(dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    if group is None:
        labels = ["All"] * len(frame)
    else:
        labels = [_text(value) for value in frame[group].to_numpy(dtype=object)]
        keep &= np.array([label is not None for label in labels], dtype=bool)
    rows = np.flatnonzero(keep)
    if not len(rows):
        raise FieldError("X", "There are no complete observations: every row misses an X, a Y or a group.")
    order = list(dict.fromkeys(labels[i] for i in rows))
    if len(order) > MAX_GROUPS:
        raise FieldError("Group", f"Compare at most {MAX_GROUPS} groups at a time (the data have {len(order)}).")
    data = [(label, x[members], y[members])
            for label in order for members in [rows[[labels[i] == label for i in rows]]]]
    return data, names["X"], names["Y"]


def _reason(error, label):
    text = str(error) or error.__class__.__name__
    return text.removeprefix(f"{label}: ")


def _fit(x, y, model, position):
    spec = MODELS[model]
    candidate = Candidate(model, position, len(spec.parameters))
    # Every candidate sees the same complete rows; the fit itself is unweighted.
    part = pd.DataFrame({"X": x, "Y": y})
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            candidate.fit = engine.nonlinear(part, "X", "Y", model)["All"]
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        candidate.status = f"Not fitted: {_reason(error, 'All')}"
        return candidate
    candidate.rss = float(candidate.fit.diagnostics["Residual SS"])
    centered = y - y.mean()
    candidate.aic, candidate.aicc, candidate.status = criteria(candidate.rss, len(y), candidate.parameters,
                                                               float(centered @ centered))
    return candidate


def _draw(axes, label, x, y, ranked, models, single):
    points = axes.scatter(x, y, color="#4a4f57", s=26, alpha=.85, zorder=2.5,
                          label="Observations" if single else "_nolegend_")
    points.set_gid(f"{GID}points:{label}")
    drawn = {c.model: c for c in ranked if c.fit is not None and c.valid}
    for position, model in enumerate(models):
        if model not in drawn:
            continue
        grid, values = drawn[model].fit.curve.T
        values = np.where(np.isfinite(values), values, np.nan)
        (line,) = axes.plot(grid, values, color=COLORS[position % len(COLORS)], linewidth=1.8, label=model)
        line.set_gid(f"{GID}curve:{label}:{model}")
    if axes.get_legend_handles_labels()[0]:
        axes.legend(frameon=False, loc="best", fontsize=None if single else 8)


def _graph(results, x_name, y_name, models):
    single = len(results) == 1
    if single:
        figure, axes = _plot(COMPARE_MODELS, x_name, y_name)
        label, x, y, ranked = results[0]
        _draw(axes, label, x, y, ranked, models, True)
        return figure
    from matplotlib.figure import Figure
    columns = min(3, len(results))
    rows = math.ceil(len(results) / columns)
    figure = Figure(figsize=(4.2 * columns + .6, 3.4 * rows + .6), dpi=100, layout="constrained")
    figure.suptitle(COMPARE_MODELS)
    for index, (label, x, y, ranked) in enumerate(results):
        axes = figure.add_subplot(rows, columns, index + 1)
        axes.set(title=label, xlabel=x_name, ylabel=y_name)
        axes.spines[["right", "top"]].set_visible(False)
        _draw(axes, label, x, y, ranked, models, False)
    return figure


def model_selection(frame, options):
    models = _models(options)
    show = options.get(SHOW_GRAPH, True)
    if not isinstance(show, (bool, np.bool_)):
        raise FieldError(SHOW_GRAPH, "Show graph must be on or off.")
    data, x_name, y_name = _groups(frame, options)

    ranking, parameters, summary, results = [], [], [], []
    for label, x, y in data:
        n = len(x)
        candidates = [_fit(x, y, model, position) for position, model in enumerate(models)]
        ranked = rank(candidates)
        valid = [c for c in ranked if c.valid]
        comparable = len(valid) >= 2
        delta = weights = None
        if comparable:
            delta, weights = akaike_weights([c.aicc for c in valid])
        shares = {id(c): (d, w) for c, d, w in zip(valid, delta, weights)} if comparable else {}
        for c in ranked:
            d, w = shares.get(id(c), (np.nan, np.nan))
            ranking.append({"Group": label, "Model": c.model, "N": n, "Parameters": c.parameters,
                            "K": c.parameters + 1, "RSS": c.rss, "AIC": c.aic, "AICc": c.aicc,
                            "Delta AICc": d, "Akaike weight": w, "Status": c.status})
            if c.fit is not None:
                for name, row in c.fit.parameters.iterrows():
                    parameters.append({"Group": label, "Model": c.model, "Parameter": name,
                                       "Estimate": float(row["Estimate"]), "SE": float(row["SE"])})
        unavailable = len(candidates) - len(valid)
        if comparable:
            note = f"Akaike weights are relative to the {len(valid)} valid models of this group."
            if unavailable:
                note += f" {unavailable} unavailable (see Status in {RANKING})."
        else:
            found = "no model has" if not valid else "only one model has"
            note = (f"Comparison unavailable: {found} a valid AICc (see Status in {RANKING}). "
                    "The fits are kept without Delta AICc or weights.")
        summary.append({"Group": label, "Best model": valid[0].model if comparable else None,
                        "Valid models": len(valid), "Note": note})
        results.append((label, x, y, ranked))

    tables = {RANKING: pd.DataFrame(ranking, columns=RANKING_COLUMNS),
              PARAMETERS: pd.DataFrame(parameters, columns=["Group", "Model", "Parameter", "Estimate", "SE"]),
              SUMMARY: pd.DataFrame(summary, columns=["Group", "Best model", "Valid models", "Note"])}
    return Result(tables, _graph(results, x_name, y_name, models) if show else None)
