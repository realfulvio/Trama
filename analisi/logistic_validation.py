"""Out-of-fold validation of a binary logistic model: options, folds, fits, metrics, sheets and figure.

Regression and Curves → *Validate binary logistic model*. The diagnostics and profiles of Multiple regression
(Logistic family) describe one fit on all rows. This analysis estimates how the same modelling procedure predicts
rows it has not seen: K-fold cross-validation on this worksheet, an *internal* validation. It is not an external
or independent validation, and it reports no confidence intervals (out-of-fold predictions share training rows,
so they are not independent observations).

Rows and positions
    ``Source row`` is the 1-based position of a row in the frame the dispatcher receives (the application's masked
    frame: exclusions and conversions already applied), counted before incomplete rows are set aside. Pandas labels
    are never used. A row is *usable* when the response is 0 or 1, every numeric predictor is a finite number and
    every categorical predictor has a value. Every other row stays in Predictions with status ``Incomplete`` and
    no fold or prediction.

Folds
    Automatic (Validation fold empty): ``Generator(PCG64(Seed))``; the usable positions with outcome 0, in source
    order, are permuted and dealt round-robin to folds 1…K starting at fold 1; then the same for outcome 1, again
    from fold 1, with the same generator. Each outcome therefore needs at least K usable rows. With a Validation
    fold column every usable row needs a whole-number code from 1 to K, every fold must occur, and the test rows of
    every fold must hold both outcomes. All of this is checked by :func:`prepare` before anything is fitted.

Fits
    Every fold fits the Bernoulli GLM of the Logistic family (``analisi.models.binomial_fit``) on its own training
    rows only: the categorical coding (levels sorted as text, the first one the reference) is compiled from the
    training rows and applied unchanged to the test rows. A test level absent from training stops the analysis
    with that fold and that predictor named; so does a training design that is rank deficient.

    Separation and non-convergence are told apart in this order, on the training rows of the fold:

    1. *Separation* (complete or quasi-complete): a linear programme looks for a direction b, with |b_j| ≤ 1 on
       the standardized design, such that s_i = (2y_i − 1)·x_i·b ≥ 0 for every training row and s_i > 0 for at
       least one. Such a b exists exactly when the maximum likelihood estimate does not exist (Albert and Anderson
       1984). The fold is reported as separated when the programme finds max s_i > 1e-7 with min s_i ≥ −1e-9.
    2. *No convergence*: no separating direction, but IRLS did not converge in 100 iterations, statsmodels warned
       about perfect prediction, a step was singular or a coefficient is not finite.
    3. *Ill-conditioned*: the fit converged, but the Fisher information X'WX of the standardized design has a
       condition number above 1e10.

    Any of these stops the analysis with an error that names the fold and the field to change. No overall score is
    ever computed on a subset of the folds.

Metrics (all on the pooled out-of-fold predictions, never averaged over folds)
    z is the out-of-fold logit, p = expit(z). Brier = mean((p − y)²). Log loss = mean(logaddexp(0, z) − y·z),
    which stays finite and exact for extreme logits. ROC AUC is the Mann–Whitney probability with half credit for
    ties; average precision is Σ (R_k − R_{k−1})·P_k over the distinct thresholds in decreasing order (no
    trapezoids). Scores are ranked by logit, so two rows whose probabilities both round to 1 are still ordered;
    Predictions keeps the logit. The confusion matrix uses p ≥ Threshold as the positive class, with the observed
    outcome on the rows and the predicted class on the columns. Calibration bins are equal-width on [0, 1],
    closed on the left, the last one closed on both sides; empty bins stay in the table.

Every user-correctable error is a ``FieldError`` naming its dialog field; messages are English and the catalog
``analisi.logistic_validation_catalog`` words them in Italian under ``ERROR_PREFIX``.
"""
from dataclasses import dataclass
from numbers import Integral, Real
import re

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from scipy.optimize import linprog
from scipy.special import expit

from .data import decimal_comma
from .field_error import FieldError
from .models import binomial_fit
from .monte_carlo import MonteCarloCancelled
from .reporting import Result, _report

METHOD = "Validate binary logistic model"
RESPONSE, PREDICTORS, CATEGORIES = "Response", "Predictors", "Categorical predictors"
FOLDS, SEED, FOLD_COLUMN = "Folds", "Seed", "Validation fold"
THRESHOLD, BINS, VIEW = "Threshold", "Calibration bins", "Graph view"
CALIBRATION_VIEW, ROC_VIEW, PR_VIEW, ALL_VIEWS = "Calibration", "ROC", "Precision–recall", "All panels"
VIEWS = (CALIBRATION_VIEW, ROC_VIEW, PR_VIEW, ALL_VIEWS)

# Dialog fields in order (``analisi.workbench.METHODS``): column roles, then typed defaults and choices.
OPTIONS = {RESPONSE: None, PREDICTORS: "Multiple", CATEGORIES: "Multiple (optional)", FOLDS: 5, SEED: 0,
           FOLD_COLUMN: "Optional", THRESHOLD: 0.5, BINS: 10, VIEW: VIEWS}
DEFAULTS = {CATEGORIES: [], FOLDS: 5, SEED: 0, FOLD_COLUMN: None, THRESHOLD: 0.5, BINS: 10, VIEW: CALIBRATION_VIEW}

VALIDATION, PREDICTIONS, FOLD_SHEET = "Validation", "Predictions", "Folds"
CALIBRATION, CONFUSION, COEFFICIENTS, SETTINGS = ("Calibration", "Confusion matrix", "Fold coefficients",
                                                  "Settings")
SHEETS = (VALIDATION, PREDICTIONS, FOLD_SHEET, CALIBRATION, CONFUSION, COEFFICIENTS, SETTINGS)
VALIDATION_COLUMNS = ["Design", "N", "Events", "Prevalence", "Brier score", "Log loss", "ROC AUC",
                      "Average precision", "Threshold", "TN", "FP", "FN", "TP", "Sensitivity", "Specificity"]
PREDICTION_COLUMNS = ["Source row", "Fold", "Observed", "Logit", "Probability", "Predicted", "Status"]
FOLD_COLUMNS = ["Fold", "Train N", "Train events", "Test N", "Test events", "Brier score", "Log loss",
                "Iterations", "Status"]
CALIBRATION_COLUMNS = ["Bin", "Lower", "Upper", "N", "Events", "Mean predicted", "Observed fraction"]
PREDICTED, INCOMPLETE, OK = "Predicted", "Incomplete", "OK"

MIN_FOLDS, MAX_FOLDS, MIN_BINS, MAX_BINS = 2, 20, 3, 20
MAX_SEED = 2**32 - 1
MAX_ROWS, MAX_COEFFICIENTS, MAX_LEVELS = 50_000, 32, 100
SEPARATION_TOLERANCE, FEASIBILITY_TOLERANCE = 1e-7, 1e-9
CONDITION_LIMIT = 1e10

INTERPRETATION = ("Internal validation: K-fold cross-validation on this worksheet estimates how the modelling "
                  "procedure predicts rows it was not fitted on. It is not an external or independent validation. "
                  "No confidence intervals are reported, because out-of-fold predictions share training rows and "
                  "are not independent.")
SEPARATION_RULE = ("Per fold, on the training rows: separation when a linear programme finds b (|b_j| ≤ 1, "
                   "standardized design) with (2y − 1)·Xb ≥ 0 on every row and > 0 on one; otherwise no "
                   "convergence when IRLS fails within 100 iterations; otherwise ill-conditioned when "
                   "cond(X'WX) > 1e10.")
AUTOMATIC = ("Automatic: Generator(PCG64(Seed)) permutes the usable rows of outcome 0, then of outcome 1 "
             "(source order), each dealt round-robin to folds 1…K from fold 1")
COLUMN_SPLIT = 'Column "{name}": codes 1…K'

ERROR_PREFIX = "logval.error."
_INTEGER = re.compile(r"\s*\+?[0-9]+\s*")


class LogisticValidationCancelled(MonteCarloCancelled, InterruptedError):
    """Cancelled between folds, before any sheet was built.

    ``MonteCarloCancelled`` is the single path through which the application keeps the last confirmed result of a
    cancellable job; ``InterruptedError`` serves callers of the dispatcher.
    """


def check_cancel(cancel):
    if cancel is None:
        return
    if bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel()):
        raise LogisticValidationCancelled("Logistic validation cancelled.")


# ----- options -----------------------------------------------------------------------------------------------------

def _get(options, name):
    value = options.get(name, DEFAULTS.get(name))
    return DEFAULTS[name] if value is None and name in DEFAULTS and name != FOLD_COLUMN else value


def _whole(options, name, low, high):
    value = _get(options, name)
    if isinstance(value, str):
        value = int(value) if _INTEGER.fullmatch(value) else None
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or not low <= value <= high:
        raise FieldError(name, f"{name}: enter a whole number from {low} to {high}.")
    return int(value)


def _threshold(options):
    value = _get(options, THRESHOLD)
    if isinstance(value, str):
        try:
            value = float(decimal_comma(value.strip()))
        except ValueError:
            value = None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(float(value)) \
            or not 0 <= float(value) <= 1:
        raise FieldError(THRESHOLD, f"{THRESHOLD}: enter a number from 0 to 1.")
    return float(value)


def _names(options, name, *, required):
    value = options.get(name, [] if not required else None)
    if value is None:
        value = []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise FieldError(name, f"{name}: choose columns from the table.")
    if len(set(value)) != len(value):
        raise FieldError(name, "Select each column only once.")
    if required and not value:
        raise FieldError(name, "Choose at least one predictor.")
    return list(value)


def _column(frame, name, field):
    positions = [index for index, title in enumerate(frame.columns) if str(title) == name]
    if not positions:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    if len(positions) > 1:
        raise FieldError(field, f'More than one column is called "{name}".')
    return frame.iloc[:, positions[0]]


def _numbers(column, name, field):
    """Floats by position; text is an error, not a gap. NaN marks an empty (or excluded) cell."""
    numeric = pd.to_numeric(column, errors="coerce")
    if np.iscomplexobj(numeric.to_numpy()):
        raise FieldError(field, f'Column "{name}" contains complex data.')
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    present = column.notna().to_numpy()
    text = present & np.isnan(values)
    if text.any():
        row = int(np.flatnonzero(text)[0]) + 1
        raise FieldError(field, f'Column "{name}" contains text (source row {row}).')
    infinite = present & np.isinf(values)
    if infinite.any():
        row = int(np.flatnonzero(infinite)[0]) + 1
        raise FieldError(field, f'Column "{name}" contains an infinite value (source row {row}).')
    return values


def _labels(column):
    """Categorical values as text (as Multiple regression codes them); None marks an empty cell."""
    present = column.notna().to_numpy()
    return np.array([str(value) if keep else None for value, keep in zip(column.tolist(), present, strict=True)],
                    dtype=object), present


@dataclass
class Plan:
    """Checked options and data; nothing fitted yet."""
    response: str
    predictors: list
    categories: list
    folds: int
    seed: int
    fold_column: str | None
    threshold: float
    bins: int
    view: str
    worksheet_rows: int
    usable: np.ndarray       # 0-based source positions of the usable rows, ascending
    y: np.ndarray            # outcomes of the usable rows (0.0 / 1.0)
    numeric: dict            # name -> float values of the usable rows
    labels: dict             # name -> text values of the usable rows
    assignment: np.ndarray   # fold (1…K) of each usable row
    terms: int               # coefficients after expansion, intercept included
    settings: dict           # canonical options, as stored in the recipe

    @property
    def n(self):
        return len(self.usable)


def _assign(y, folds, seed):
    """Stratified round-robin folds (see the module docstring); positions are indices into the usable rows."""
    generator = np.random.Generator(np.random.PCG64(seed))
    assignment = np.zeros(len(y), dtype=np.int64)
    for outcome in (0.0, 1.0):
        positions = np.flatnonzero(y == outcome)
        shuffled = generator.permutation(positions)
        assignment[shuffled] = np.arange(len(shuffled)) % folds + 1
    return assignment


def _design(plan, rows, levels):
    """Design matrix (intercept first) of the usable rows ``rows`` with the given categorical levels."""
    columns, names = [np.ones(len(rows))], ["Intercept"]
    for name in plan.predictors:
        if name in plan.categories:
            values = plan.labels[name][rows]
            for level in levels[name][1:]:
                columns.append((values == level).astype(float))
                names.append(f"{name} [{level}]")
        else:
            columns.append(plan.numeric[name][rows])
            names.append(name)
    return np.column_stack(columns), names


def prepare(frame, options):
    """Read and check options, data, folds and budgets. Nothing is fitted; allocations stay O(rows × columns)."""
    if not isinstance(options, dict):
        raise ValueError("Logistic validation options must be a mapping.")
    response = options.get(RESPONSE)
    if not isinstance(response, str) or not response:
        raise FieldError(RESPONSE, "Choose the response column (0 or 1).")
    predictors = _names(options, PREDICTORS, required=True)
    categories = _names(options, CATEGORIES, required=False)
    if not set(categories).issubset(predictors):
        raise FieldError(CATEGORIES, "Categorical predictors must also be selected as predictors.")
    if response in predictors:
        raise FieldError(PREDICTORS, "The response cannot also be a predictor.")
    folds = _whole(options, FOLDS, MIN_FOLDS, MAX_FOLDS)
    seed = _whole(options, SEED, 0, MAX_SEED)
    threshold = _threshold(options)
    bins = _whole(options, BINS, MIN_BINS, MAX_BINS)
    view = _get(options, VIEW)
    if view not in VIEWS:
        raise FieldError(VIEW, "Choose a graph view.")
    fold_column = options.get(FOLD_COLUMN) or None
    if fold_column is not None and not isinstance(fold_column, str):
        raise FieldError(FOLD_COLUMN, "Choose a column for the validation folds, or none.")
    if fold_column is not None and (fold_column == response or fold_column in predictors):
        raise FieldError(FOLD_COLUMN, "The validation fold column must differ from the response and the predictors.")

    outcome = _numbers(_column(frame, response, RESPONSE), response, RESPONSE)
    with np.errstate(invalid="ignore"):
        wrong = ~np.isnan(outcome) & (outcome != 0) & (outcome != 1)
    if wrong.any():
        row = int(np.flatnonzero(wrong)[0])
        raise FieldError(RESPONSE, f'Response "{response}" must hold 0 or 1 (source row {row + 1}: '
                                   f"{outcome[row]:g}).")
    usable = ~np.isnan(outcome)
    numeric, labels = {}, {}
    for name in predictors:
        column = _column(frame, name, CATEGORIES if name in categories else PREDICTORS)
        if name in categories:
            labels[name], present = _labels(column)
            usable &= present
        else:
            numeric[name] = _numbers(column, name, PREDICTORS)
            usable &= ~np.isnan(numeric[name])
    rows = np.flatnonzero(usable)
    n = len(rows)
    if n == 0:
        raise FieldError(PREDICTORS, "No row has a value in the response and in every predictor.")
    if n > MAX_ROWS:
        raise FieldError(PREDICTORS, f"Use at most {MAX_ROWS} usable rows (this selection has {n}).")
    y = outcome[rows]
    events = int(y.sum())
    if events == 0 or events == n:
        raise FieldError(RESPONSE, "The usable rows need both outcomes, 0 and 1.")
    numeric = {name: values[rows] for name, values in numeric.items()}
    labels = {name: values[rows] for name, values in labels.items()}

    levels = {}
    terms = 1
    for name in predictors:
        if name in categories:
            levels[name] = sorted(set(labels[name]))
            if not 2 <= len(levels[name]) <= MAX_LEVELS:
                raise FieldError(CATEGORIES, f'Categorical predictor "{name}" needs 2 to {MAX_LEVELS} levels '
                                             f"(it has {len(levels[name])}).")
            terms += len(levels[name]) - 1
        else:
            terms += 1
    if terms > MAX_COEFFICIENTS:
        raise FieldError(PREDICTORS, f"The model has {terms} coefficients after expanding the categories; "
                                     f"the limit is {MAX_COEFFICIENTS}.")

    if fold_column is None:
        smallest = min(events, n - events)
        if smallest < folds:
            outcome_label = 1 if events < n - events else 0
            raise FieldError(FOLDS, f"Each outcome needs at least {folds} usable rows for {folds} folds "
                                    f"(outcome {outcome_label} has {smallest}).")
        assignment = _assign(y, folds, seed)
    else:
        codes = _numbers(_column(frame, fold_column, FOLD_COLUMN), fold_column, FOLD_COLUMN)[rows]
        missing = np.isnan(codes)
        if missing.any():
            row = int(rows[np.flatnonzero(missing)[0]]) + 1
            raise FieldError(FOLD_COLUMN, f"Source row {row} has no fold code.")
        with np.errstate(invalid="ignore"):
            invalid = (codes != np.round(codes)) | (codes < 1) | (codes > folds)
        if invalid.any():
            at = int(np.flatnonzero(invalid)[0])
            raise FieldError(FOLD_COLUMN, f"Source row {int(rows[at]) + 1}: fold code {codes[at]:g} is not a whole "
                                          f"number from 1 to {folds}.")
        assignment = codes.astype(np.int64)
        for fold in range(1, folds + 1):
            test = assignment == fold
            if not test.any():
                raise FieldError(FOLD_COLUMN, f"Fold {fold} has no usable rows: use codes 1 to {folds}.")
            if y[test].min() == y[test].max():
                raise FieldError(FOLD_COLUMN, f"The test rows of fold {fold} need both outcomes, 0 and 1.")

    plan = Plan(response, predictors, categories, folds, seed, fold_column, threshold, bins, view, len(frame),
                rows, y, numeric, labels, assignment, terms, {})
    for fold in range(1, folds + 1):  # categorical coverage of every fold, before anything is fitted
        _fold_levels(plan, fold)
    design, _ = _design(plan, np.arange(n), levels)
    if n <= terms:
        raise FieldError(PREDICTORS, f"The model has {terms} coefficients and only {n} usable rows.")
    if np.linalg.matrix_rank(design) < design.shape[1]:
        raise FieldError(PREDICTORS, "The model is rank deficient. Remove redundant or constant predictors.")
    plan.settings = {RESPONSE: response, PREDICTORS: predictors, CATEGORIES: categories, FOLDS: folds, SEED: seed,
                     FOLD_COLUMN: fold_column, THRESHOLD: threshold, BINS: bins, VIEW: view}
    return plan


# ----- one fold ----------------------------------------------------------------------------------------------------

def _standardized(design):
    """Invertible rescaling of the non-intercept columns: separation and conditioning do not depend on units."""
    scaled = design.copy()
    if design.shape[1] > 1:
        centre = design[:, 1:].mean(axis=0)
        spread = design[:, 1:].std(axis=0)
        spread[spread == 0] = 1.0
        scaled[:, 1:] = (design[:, 1:] - centre) / spread
    return scaled


def separation_direction(design, y):
    """A direction b with (2y − 1)·Xb ≥ 0 everywhere and > 0 somewhere, or None (the MLE exists)."""
    scaled = _standardized(design)
    signed = (2 * y - 1)[:, None] * scaled
    found = linprog(-signed.sum(axis=0), A_ub=-signed, b_ub=np.zeros(len(y)), bounds=(-1, 1), method="highs")
    if found.status != 0 or found.x is None:
        return None
    scores = signed @ found.x
    if scores.max() > SEPARATION_TOLERANCE and scores.min() >= -FEASIBILITY_TOLERANCE:
        return found.x
    return None


def _fold_error(fold, kind, detail=None):
    """The FieldError of a failed fold: the fold, the cause and the field that can fix it."""
    if kind == "separation":
        return FieldError(PREDICTORS, f"Fold {fold}: the training rows are separated (complete or quasi-complete "
                                      f"separation), so the logistic fit has no finite estimate. Change the "
                                      f"predictors, the folds or the seed.")
    if kind == "convergence":
        return FieldError(PREDICTORS, f"Fold {fold}: the logistic fit did not converge on the training rows "
                                      f"(no separation was found). Check the scale and variance of the predictors.")
    if kind == "condition":
        return FieldError(PREDICTORS, f"Fold {fold}: the logistic fit is ill-conditioned on the training rows. "
                                      f"Remove nearly redundant predictors.")
    if kind == "rank":
        return FieldError(PREDICTORS, f"Fold {fold}: the training design is rank deficient. A predictor is "
                                      f"constant or redundant in the training rows of this fold.")
    if kind == "level":
        name, level = detail
        return FieldError(CATEGORIES, f'Fold {fold}: level "{level}" of "{name}" occurs in the test rows but not '
                                      f"in the training rows. Merge rare levels, or change the folds or the seed.")
    if kind == "pure":
        name, level, outcome = detail
        return FieldError(CATEGORIES, f'Fold {fold}: every training row with level "{level}" of "{name}" has '
                                      f"outcome {outcome} (quasi-complete separation). Merge rare levels, or "
                                      f"change the folds or the seed.")
    if kind == "single":
        return FieldError(CATEGORIES, f'Fold {fold}: "{detail}" has a single level in the training rows.')
    return FieldError(PREDICTORS, f"Fold {fold}: {detail} training rows are not enough for the model coefficients.")


def _fold_levels(plan, fold):
    """Categorical coding compiled from the training rows of ``fold``; every test level must occur there."""
    train = plan.assignment != fold
    levels = {}
    for name in plan.categories:
        seen = sorted(set(plan.labels[name][train]))
        if len(seen) < 2:
            raise _fold_error(fold, "single", name)
        unseen = sorted(set(plan.labels[name][~train]) - set(seen))
        if unseen:
            raise _fold_error(fold, "level", (name, unseen[0]))
        levels[name] = seen
    return levels


def _pure_level(plan, train, levels):
    """A non-reference training level whose rows all share one outcome (a categorical cause of separation)."""
    y = plan.y[train]
    for name in plan.categories:
        values = plan.labels[name][train]
        for level in levels[name]:
            outcomes = y[values == level]
            if outcomes.min() == outcomes.max():
                return name, level, int(outcomes[0])
    return None


def fit_fold(plan, fold):
    """Fit fold ``fold`` on its training rows and predict its test rows. Raises FieldError for a failed fold."""
    train = np.flatnonzero(plan.assignment != fold)
    test = np.flatnonzero(plan.assignment == fold)
    levels = _fold_levels(plan, fold)
    design, names = _design(plan, train, levels)
    if len(train) <= design.shape[1]:
        raise _fold_error(fold, "rows", len(train))
    if np.linalg.matrix_rank(design) < design.shape[1]:
        raise _fold_error(fold, "rank")
    y = plan.y[train]
    if separation_direction(design, y) is not None:
        pure = _pure_level(plan, train, levels)
        raise _fold_error(fold, "separation") if pure is None else _fold_error(fold, "pure", pure)
    try:
        model = binomial_fit(y, design)
    except ValueError as error:
        raise _fold_error(fold, "convergence") from error
    params = np.asarray(model.params, dtype=float)
    if not np.isfinite(params).all():
        raise _fold_error(fold, "convergence")
    fitted = expit(design @ params)
    scaled = _standardized(design)
    information = scaled.T @ (scaled * (fitted * (1 - fitted))[:, None])
    if not np.isfinite(information).all() or np.linalg.cond(information) > CONDITION_LIMIT:
        raise _fold_error(fold, "condition")
    test_design, _ = _design(plan, test, levels)
    logit = test_design @ params
    return {"fold": fold, "train": train, "test": test, "names": names, "params": params, "logit": logit,
            "iterations": int((getattr(model, "fit_history", None) or {}).get("iteration", 0))}


# ----- metrics -----------------------------------------------------------------------------------------------------

def log_loss_terms(y, logit):
    """−log likelihood of each row from the logit: logaddexp(0, z) − y·z, finite for any finite z."""
    return np.logaddexp(0.0, logit) - y * logit


def roc_auc(y, score):
    """Mann–Whitney AUC with half credit for ties (average ranks)."""
    order = np.argsort(score, kind="mergesort")
    ranked = score[order]
    ranks = np.empty(len(score))
    start = 0
    while start < len(ranked):
        stop = start + 1
        while stop < len(ranked) and ranked[stop] == ranked[start]:
            stop += 1
        ranks[order[start:stop]] = (start + stop + 1) / 2
        start = stop
    positives = y == 1
    n1, n0 = int(positives.sum()), int((~positives).sum())
    return float((ranks[positives].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def curve_points(y, score):
    """Cumulative counts at each distinct threshold, from the highest score down: (thresholds, TP, FP)."""
    order = np.argsort(-score, kind="mergesort")
    ordered, outcome = score[order], y[order]
    last = np.r_[np.flatnonzero(np.diff(ordered) != 0), len(ordered) - 1]
    tp = np.cumsum(outcome)[last]
    fp = np.cumsum(1 - outcome)[last]
    return ordered[last], tp, fp


def average_precision(y, score):
    """Σ (R_k − R_{k−1})·P_k over the distinct thresholds in decreasing order; no interpolation."""
    _thresholds, tp, fp = curve_points(y, score)
    recall = tp / y.sum()
    precision = tp / (tp + fp)
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def calibration_table(y, probability, bins):
    edges = np.arange(bins + 1) / bins  # i / B, correctly rounded: 3 / 10 is the double nearest 0.3
    index = np.clip(np.searchsorted(edges, probability, side="right") - 1, 0, bins - 1)
    rows = []
    for position in range(bins):
        members = index == position
        count = int(members.sum())
        rows.append({"Bin": position + 1, "Lower": edges[position], "Upper": edges[position + 1], "N": count,
                     "Events": int(y[members].sum()),
                     "Mean predicted": float(probability[members].mean()) if count else np.nan,
                     "Observed fraction": float(y[members].mean()) if count else np.nan})
    return pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)


def confusion(y, probability, threshold):
    predicted = probability >= threshold
    positive = y == 1
    return {"TN": int((~positive & ~predicted).sum()), "FP": int((~positive & predicted).sum()),
            "FN": int((positive & ~predicted).sum()), "TP": int((positive & predicted).sum())}


# ----- analysis ----------------------------------------------------------------------------------------------------

def calculate(plan, cancel=None):
    """Fit every fold in order on the calling thread, polling ``cancel`` before each fit.

    The shared process pool is not used: on 20,000 rows × 10 folds it gave no gain over this loop and its folds
    can differ from the serial ones in the last bits (BLAS threading differs between the window process and the
    workers), which would break bit-identical results across settings. See the benchmark in the PR.
    """
    outcomes = []
    for fold in range(1, plan.folds + 1):
        check_cancel(cancel)
        outcomes.append(fit_fold(plan, fold))
    check_cancel(cancel)
    return outcomes


def analysis(frame, options, *, cancel=None):
    plan = prepare(frame, options)
    return build(plan, calculate(plan, cancel))


def build(plan, outcomes):
    n = plan.n
    logit = np.empty(n)
    for outcome in outcomes:
        logit[outcome["test"]] = outcome["logit"]
    probability = expit(logit)
    y = plan.y
    losses = log_loss_terms(y, logit)
    squared = (probability - y) ** 2
    events = int(y.sum())
    counts = confusion(y, probability, plan.threshold)
    design = (f"Internal: {plan.folds}-fold cross-validation, "
              + ("automatic stratified split" if plan.fold_column is None else f'folds from "{plan.fold_column}"'))
    validation = pd.DataFrame([{
        "Design": design, "N": n, "Events": events, "Prevalence": events / n,
        "Brier score": float(squared.mean()), "Log loss": float(losses.mean()),
        "ROC AUC": roc_auc(y, logit), "Average precision": average_precision(y, logit),
        "Threshold": plan.threshold, **counts,
        "Sensitivity": counts["TP"] / events, "Specificity": counts["TN"] / (n - events),
    }], columns=VALIDATION_COLUMNS, index=pd.Index(["Out-of-fold"], name="Predictions"))

    rows = plan.worksheet_rows
    fold_of = np.full(rows, np.nan)
    observed = np.full(rows, np.nan)
    logits = np.full(rows, np.nan)
    probabilities = np.full(rows, np.nan)
    predicted = np.full(rows, np.nan)
    fold_of[plan.usable] = plan.assignment
    observed[plan.usable] = y
    logits[plan.usable] = logit
    probabilities[plan.usable] = probability
    predicted[plan.usable] = (probability >= plan.threshold).astype(float)
    status = np.full(rows, INCOMPLETE, dtype=object)
    status[plan.usable] = PREDICTED
    predictions = pd.DataFrame({"Source row": np.arange(1, rows + 1), "Fold": fold_of, "Observed": observed,
                                "Logit": logits, "Probability": probabilities, "Predicted": predicted,
                                "Status": status}, columns=PREDICTION_COLUMNS)

    fold_rows, coefficient_rows = [], []
    for outcome in outcomes:
        test = outcome["test"]
        fold_rows.append({"Fold": outcome["fold"], "Train N": len(outcome["train"]),
                          "Train events": int(y[outcome["train"]].sum()), "Test N": len(test),
                          "Test events": int(y[test].sum()), "Brier score": float(squared[test].mean()),
                          "Log loss": float(losses[test].mean()), "Iterations": outcome["iterations"], "Status": OK})
        coefficient_rows.extend({"Fold": outcome["fold"], "Term": name, "Estimate": float(value)}
                                for name, value in zip(outcome["names"], outcome["params"], strict=True))
    folds = pd.DataFrame(fold_rows, columns=FOLD_COLUMNS)
    coefficients = pd.DataFrame(coefficient_rows, columns=["Fold", "Term", "Estimate"])
    calibration = calibration_table(y, probability, plan.bins)
    matrix = pd.DataFrame({"Predicted 0": [counts["TN"], counts["FN"]], "Predicted 1": [counts["FP"], counts["TP"]]},
                          index=pd.Index(["Observed 0", "Observed 1"], name="Observed \\ predicted"))
    matrix["Total"] = matrix.sum(axis=1)
    settings = _report({
        "Validation": INTERPRETATION,
        "Split": AUTOMATIC if plan.fold_column is None else COLUMN_SPLIT.format(name=plan.fold_column),
        "Folds": plan.folds, "Seed": plan.seed if plan.fold_column is None else "Not used (fold column)",
        "Positive class": f"p ≥ {plan.threshold:g}", "Calibration bins": f"{plan.bins} equal-width bins on [0, 1]",
        "Coefficients per fit": plan.terms, "Usable rows": n,
        "Incomplete rows": plan.worksheet_rows - n,
        "Metrics": "Pooled out-of-fold predictions; AUC with half credit for ties; AP without interpolation",
        "Fit failures": SEPARATION_RULE,
    })
    tables = {VALIDATION: validation, PREDICTIONS: predictions, FOLD_SHEET: folds, CALIBRATION: calibration,
              CONFUSION: matrix, COEFFICIENTS: coefficients, SETTINGS: settings}
    return Result(tables, figure(plan, y, logit, probability, calibration, validation.iloc[0]))


# ----- figure ------------------------------------------------------------------------------------------------------

def _calibration_axes(axes, plan, calibration, summary):
    axes.plot([0, 1], [0, 1], linestyle="--", color="0.45", linewidth=1, label="Perfect calibration")
    filled = calibration[calibration["N"] > 0]
    largest = max(int(filled["N"].max()), 1)
    axes.scatter(filled["Mean predicted"], filled["Observed fraction"], s=24 + 220 * filled["N"] / largest,
                 color="C0", alpha=.8, edgecolor="white", linewidth=.6, zorder=3)
    marker = Line2D([], [], linestyle="none", marker="o", color="C0", markersize=8,
                    label=f"Bins (area ∝ N); N = {int(summary['N'])}, events = {int(summary['Events'])}")
    axes.set(xlim=(-.02, 1.02), ylim=(-.02, 1.02), xlabel="Mean predicted probability",
             ylabel="Observed fraction", title="Calibration (out-of-fold)")
    handles, _ = axes.get_legend_handles_labels()
    axes.legend(handles=[*handles, marker], loc="upper left", frameon=False, fontsize="small")


def _roc_axes(axes, y, logit, summary):
    _thresholds, tp, fp = curve_points(y, logit)
    tpr = np.r_[0.0, tp / y.sum()]
    fpr = np.r_[0.0, fp / (len(y) - y.sum())]
    axes.plot([0, 1], [0, 1], linestyle="--", color="0.45", linewidth=1, label="Chance")
    axes.plot(fpr, tpr, color="C1", linewidth=1.8, label=f"Out-of-fold ROC (AUC = {summary['ROC AUC']:.3f})")
    axes.set(xlim=(-.02, 1.02), ylim=(-.02, 1.02), xlabel="1 − specificity", ylabel="Sensitivity", title="ROC")
    axes.legend(loc="lower right", frameon=False, fontsize="small")


def _pr_axes(axes, y, logit, summary):
    _thresholds, tp, fp = curve_points(y, logit)
    recall = np.r_[0.0, tp / y.sum()]
    precision = tp / (tp + fp)
    precision = np.r_[precision[0], precision]
    axes.step(recall, precision, where="pre", color="C2", linewidth=1.8,
              label=f"Out-of-fold (AP = {summary['Average precision']:.3f})")
    axes.axhline(summary["Prevalence"], linestyle="--", color="0.45", linewidth=1,
                 label=f"Prevalence = {summary['Prevalence']:.3f}")
    axes.set(xlim=(-.02, 1.02), ylim=(-.02, 1.02), xlabel="Recall", ylabel="Precision", title="Precision–recall")
    axes.legend(loc="lower left", frameon=False, fontsize="small")


def figure(plan, y, logit, probability, calibration, summary):
    panels = {CALIBRATION_VIEW: (CALIBRATION_VIEW,), ROC_VIEW: (ROC_VIEW,), PR_VIEW: (PR_VIEW,),
              ALL_VIEWS: (CALIBRATION_VIEW, ROC_VIEW, PR_VIEW)}[plan.view]
    width = 5.6 * len(panels) + (1.4 if len(panels) == 1 else 0)
    result = Figure(figsize=(width, 5.4), dpi=100, layout="constrained")
    for position, panel in enumerate(panels, 1):
        axes = result.add_subplot(1, len(panels), position)
        axes.spines[["right", "top"]].set_visible(False)
        axes.set_aspect("equal", adjustable="box")
        if panel == CALIBRATION_VIEW:
            _calibration_axes(axes, plan, calibration, summary)
        elif panel == ROC_VIEW:
            _roc_axes(axes, y, logit, summary)
        else:
            _pr_axes(axes, y, logit, summary)
    result.suptitle(f"Internal validation: {plan.folds}-fold cross-validation of {plan.response}", fontsize="medium")
    return result
