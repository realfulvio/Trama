"""Additive numeric covariates for the multifactor ANOVA.

A recipe without ``Covariates`` (or with an empty list) never reaches this module: the factorial
fit, the sums of squares and the marginal means stay on the path they had. With one or more
covariates the same sum-to-zero factor design is fitted by ordinary least squares on the rows that
are complete for the response, the model factors and every covariate. Each covariate enters as its
own column, centred on the reference, and nowhere else: there is no covariate-by-factor product.

Type III sums of squares, diagnostics, planned contrasts, comparisons and estimated marginal means
reuse that one fit. A marginal mean holds every covariate at its reference (the centred column is
zero). Type I and Type II are refused while covariates are included, because this release only
defines the Type III tests for the extended design.

The reference is the number stored for that covariate, or the mean of the rows used by the fit when
the recipe does not give one. A reference outside the observed range is reported as an extrapolation.
A reference outside the range inside a cell is reported too. Those two marginal ranges do not say
whether two references sit inside the joint support of the covariates.
"""
from itertools import product
from math import prod

import numpy as np
import pandas as pd
from scipy import stats

from .anova_ss import KEY as SUMS_OF_SQUARES, TYPE_III
from .field_error import FieldError
from .i18n import translate_message, ui


COVARIATES = "Covariates"
REFERENCES = "Covariate references"
PANEL = "Covariate panel"
COEFFICIENTS = "Covariates"
REFERENCE_SHEET = "Covariate references"
CONFIDENCE = 0.95
EXPLICIT = "Explicit"
MEAN_SOURCE = "Mean of used rows"
JOINT = ("Marginal ranges do not establish that these references lie in the joint support of "
         "the covariates.")
EXTRAPOLATION = "A reference outside the observed range is an extrapolation."
CANCELLED = "The multifactor ANOVA fit was cancelled."

ERRORS = {
    "type": "Choose covariates as a list of column names.",
    "repeat": "Covariate {name} is listed more than once.",
    "same": "Covariate {name} is already the response or a factor.",
    "missing": "Covariate {name} is not in the table.",
    "numeric": "Covariate {name} must be a numeric column.",
    "rows": "The response, the factors and the covariates have no complete row in common.",
    "constant": "Covariate {name} is constant in the rows used by the model.",
    "redundant": "Covariate {name} repeats {other} in the rows used by the model.",
    "empty": "The design has an empty cell ({cell}).",
    "reference": "The reference for {name} must be a finite number.",
    "rank": "The model does not have full rank with these covariates.",
    "df": "The model with these covariates has no residual degrees of freedom.",
    "variance": "The fitted model has no measurable residual variance.",
    "sums": ("Type I and Type II sums of squares are not available when covariates are included. "
             "Choose Type III."),
}


class CovariateFitCancelled(Exception):
    """The worker was asked to stop before this fit finished. Nothing is published."""


class CovariateDesign:
    """Factor design plus one centred column per covariate.

    ``rows`` builds the factor row the factorial design would build and appends zeros, which is the
    design row at every covariate reference. ``to_numpy`` is the matrix of the fit.
    """

    def __init__(self, factor_design, matrix, names):
        self.factor = factor_design
        self.matrix = np.asarray(matrix, dtype=float)
        self.names = tuple(names)
        slices = dict(factor_design.design_info.term_name_slices)
        start = self.matrix.shape[1] - len(self.names)
        for offset, name in enumerate(self.names):
            slices[name] = slice(start + offset, start + offset + 1)
        self.design_info = type("DesignInfo", (), {})()
        self.design_info.term_name_slices = slices
        self.report = None

    def to_numpy(self):
        return self.matrix

    def rows(self, table):
        from .stats import _factor_design_rows

        base = np.asarray(_factor_design_rows(self.factor, table), dtype=float)
        return np.column_stack([base, np.zeros((len(base), len(self.names)))])


def format_error(error):
    """Translated sentence for an error on ``Covariates``, after its caption; else None."""
    if getattr(error, "field", None) != COVARIATES:
        return None
    message = translate_message(str(error), "anova.covariate.error.")
    caption = ui(COVARIATES)
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def _fail(key, **values):
    return FieldError(COVARIATES, ERRORS[key].format(**values))


def requested(options):
    """The covariate names of a recipe, or None when the fit must ignore this option.

    An absent key and an empty list are the historical model. Any other shape is a field error.
    """
    if options is None or COVARIATES not in options:
        return None
    names = options.get(COVARIATES)
    if names is None or names == [] or names == ():
        return None
    if (not isinstance(names, (list, tuple)) or not names
            or any(not isinstance(name, str) or not name for name in names)):
        raise _fail("type")
    seen = set()
    for name in names:
        if name in seen:
            raise _fail("repeat", name=name)
        seen.add(name)
    return list(names)


def check_request(options):
    """Names, references and the Type III limit. None when the recipe has no covariates.

    No column is read. The dialog calls this before it closes; the fit repeats it.
    """
    names = requested(options)
    if names is None:
        return None
    from .anova_ss import sums_of_squares

    if sums_of_squares(options) != TYPE_III:
        raise FieldError(SUMS_OF_SQUARES, ERRORS["sums"])
    references = options.get(REFERENCES, {})
    if references is None:
        references = {}
    if not isinstance(references, dict):
        raise _fail("reference", name=names[0])
    for name, value in references.items():
        if name not in names:
            continue
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise _fail("reference", name=name)
        if not np.isfinite(float(value)):
            raise _fail("reference", name=name)
    return names


def stopped(cancel):
    """True when the worker has asked this fit to stop."""
    if cancel is None:
        return False
    probe = getattr(cancel, "is_set", None)
    if probe is not None:
        return bool(probe())
    return bool(cancel())


def _stop(cancel):
    if stopped(cancel):
        raise CovariateFitCancelled(CANCELLED)


def _numbers(frame, names):
    """Finite numeric columns, or a field error that names the first column that is not."""
    found = []
    for name in names:
        if name not in frame.columns:
            raise _fail("missing", name=name)
        column = frame[name]
        if isinstance(column, pd.DataFrame):
            raise _fail("missing", name=name)
        numeric = pd.to_numeric(column, errors="coerce")
        values = numeric.to_numpy(dtype=float)
        original = column.to_numpy()
        present = pd.notna(original)
        if present.any() and not np.isfinite(values[present.to_numpy()]).all():
            raise _fail("numeric", name=name)
        found.append(values)
    return np.column_stack(found)


def _complete_positions(frame, response, names, factors):
    """Positions of the rows the fit uses, and the covariate values on those rows."""
    from .stats import complete

    marked = frame.copy()
    marked.insert(0, "__row", np.arange(len(frame)))
    try:
        observed = complete(marked, [response, *names, "__row"], factors)
    except ValueError as error:
        text = str(error)
        for name in names:
            if name in text:
                raise _fail("numeric", name=name) from error
        raise
    except KeyError as error:
        missing = str(error).strip("'\"")
        raise _fail("missing", name=missing if missing in names else names[0]) from error
    if observed.empty:
        raise _fail("rows")
    positions = observed["__row"].to_numpy(dtype=int)
    return positions, observed


def _empty_cell(observed, factors):
    levels = []
    columns = []
    for name in factors:
        text = observed[name].astype(str)
        columns.append(text.to_numpy())
        levels.append(sorted(text.unique()))
    if not levels:
        return
    observed_cells = set(zip(*columns))
    if len(observed_cells) == prod(len(level) for level in levels):
        return
    for combo in product(*levels):
        if combo not in observed_cells:
            cell = " / ".join(f"{name}={level}" for name, level in zip(factors, combo))
            raise _fail("empty", cell=cell)


def _references(values, names, requested):
    """Centres and where each one came from. ``requested`` maps a name to an explicit number."""
    requested = requested or {}
    centres = np.empty(len(names))
    sources = []
    for index, name in enumerate(names):
        if name in requested and requested[name] is not None and requested[name] != "":
            value = requested[name]
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
                raise _fail("reference", name=name)
            number = float(value)
            if not np.isfinite(number):
                raise _fail("reference", name=name)
            centres[index] = number
            sources.append(EXPLICIT)
        else:
            centres[index] = float(values[:, index].mean())
            sources.append(MEAN_SOURCE)
    return centres, sources


def _independent(values, names):
    """Refuse a constant covariate and one that repeats another (or the intercept) on these rows."""
    kept = []
    ones = np.ones(len(values))
    for index, name in enumerate(names):
        column = values[:, index]
        if not np.isfinite(column).all() or np.ptp(column) == 0:
            raise _fail("constant", name=name)
        for previous in kept:
            both = np.column_stack([ones, values[:, previous], column])
            if np.linalg.matrix_rank(both, tol=1e-8) < 3:
                raise _fail("redundant", name=name, other=names[previous])
        trial = np.column_stack([ones, values[:, kept], column] if kept else [ones, column])
        if np.linalg.matrix_rank(trial, tol=1e-8) < 2 + len(kept):
            raise _fail("redundant", name=name, other=names[kept[-1]] if kept else "the intercept")
        kept.append(index)


def _cell_notes(observed, factors, names, centres):
    """Cells whose own range does not contain the reference. The text names the cell."""
    if not factors:
        return [""] * len(names)
    labels = [observed[name].astype(str) for name in factors]
    grouped = pd.DataFrame({name: observed[name].to_numpy(dtype=float) for name in names})
    for name, text in zip(factors, labels):
        grouped[name] = text.to_numpy()
    outside = [[] for _ in names]
    for key, part in grouped.groupby(list(factors), sort=True):
        key = key if isinstance(key, tuple) else (key,)
        cell = " / ".join(f"{name}={level}" for name, level in zip(factors, key))
        for index, name in enumerate(names):
            low, high = float(part[name].min()), float(part[name].max())
            if centres[index] < low or centres[index] > high:
                outside[index].append(cell)
    return ["; ".join(cells) for cells in outside]


def _report(names, centres, sources, values, observed, factors, beta, covariance, df):
    count = len(values)
    critical = float(stats.t.ppf(0.5 + CONFIDENCE / 2, df))
    start = len(beta) - len(names)
    coefficients = []
    for offset, name in enumerate(names):
        estimate = float(beta[start + offset])
        se = float(np.sqrt(covariance[start + offset, start + offset]))
        coefficients.append({"Covariate": name, "Estimate": estimate, "SE": se, "df": int(df),
                             "CI low": estimate - critical * se, "CI high": estimate + critical * se,
                             "Confidence": CONFIDENCE})
    cells = _cell_notes(observed, factors, names, centres)
    joint = len(names) >= 2
    references = []
    for index, name in enumerate(names):
        column = values[:, index]
        low, high = float(column.min()), float(column.max())
        outside = centres[index] < low or centres[index] > high
        note = " ".join(part for part in (EXTRAPOLATION if outside else "", JOINT if joint else "") if part)
        references.append({
            "Covariate": name, "Reference": float(centres[index]), "Source": sources[index],
            "Minimum": low, "Maximum": high, "N": count, "Residual df": int(df),
            "Outside observed range": "Yes" if outside else "No",
            "Cells outside the observed range": cells[index], "Note": note,
        })
    return {"coefficients": pd.DataFrame(coefficients).set_index("Covariate"),
            "references": pd.DataFrame(references).set_index("Covariate")}


def augment(frame, response, factors, order, terms, names, references, cancel=None):
    """The factorial fit with centred covariate columns appended. Same tuple as ``_anova_model``."""
    from .anova_terms import active_factors, canonical_terms
    from .stats import _anova_model

    _stop(cancel)
    if not isinstance(response, str) or response not in frame.columns:
        raise _fail("same", name=names[0])
    model_factors = active_factors(list(factors), canonical_terms(terms, factors)) if terms is not None else list(factors)
    for name in names:
        if name == response or name in model_factors:
            raise _fail("same", name=name)
        if name not in getattr(frame, "columns", ()):
            raise _fail("missing", name=name)
    positions, observed = _complete_positions(frame, response, names, model_factors)
    _empty_cell(observed, model_factors)
    values = observed[names].to_numpy(dtype=float)
    _independent(values, names)
    centres, sources = _references(values, names, references)
    centered = values - centres
    subset = frame.iloc[positions]
    data, keys, term_names, design, _beta, _error, _df = _anova_model(
        subset, response, factors, order, terms=terms)
    if len(data) != len(centered):
        raise _fail("rows")
    _stop(cancel)
    factor = design.to_numpy()
    matrix = np.column_stack([factor, centered])
    y = data["response"].to_numpy(dtype=float)
    beta, rss, rank, _ = np.linalg.lstsq(matrix, y, rcond=None)
    if rank < matrix.shape[1]:
        raise _fail("rank")
    df = len(y) - int(rank)
    if df <= 0:
        raise _fail("df")
    error = float(rss[0])
    total = float(np.sum((y - y.mean())**2))
    if total <= 0 or error <= np.finfo(float).eps * total:
        raise _fail("variance")
    covariance = np.linalg.inv(matrix.T @ matrix) * (error / df)
    wrapped = CovariateDesign(design, matrix, names)
    wrapped.report = _report(names, centres, sources, values, observed, model_factors, beta, covariance, df)
    return data, keys, term_names, wrapped, beta, error, df


def preview(frame, response, factors, names, references):
    """What the dialog shows before the fit: the mean of the rows it would use, and the range notes.

    Returns None when the columns are not yet a valid selection. Nothing is fitted.
    """
    if not names or not isinstance(response, str) or not factors:
        return None
    try:
        check_names = requested({COVARIATES: list(names)})
    except FieldError:
        return None
    if any(name == response or name in factors or name not in getattr(frame, "columns", ()) for name in check_names):
        return None
    try:
        _positions, observed = _complete_positions(frame, response, check_names, list(factors))
    except (FieldError, ValueError, KeyError, TypeError):
        return None
    values = observed[check_names].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None
    try:
        centres, sources = _references(values, check_names, references)
    except FieldError:
        return None
    cells = _cell_notes(observed, list(factors), check_names, centres)
    rows = []
    for index, name in enumerate(check_names):
        low, high = float(values[:, index].min()), float(values[:, index].max())
        rows.append({"name": name, "reference": float(centres[index]), "source": sources[index],
                     "mean": float(values[:, index].mean()), "minimum": low, "maximum": high,
                     "outside": centres[index] < low or centres[index] > high,
                     "cells": cells[index]})
    return rows
