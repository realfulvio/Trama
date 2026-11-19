"""Planned contrasts of the Multifactor ANOVA (0.96).

A planned contrast combines estimated marginal means of the fitted model with coefficients chosen
before looking at the results: a treatment against the mean of two others, a quadratic trend, a
difference of differences. The recipe of ``Multifactor ANOVA`` gains four keys:

* ``Planned contrast factors``: ordered list of distinct factor names, a subset of the factors that
  are in the model (all of ``Factors`` for Full hierarchy, the factors of the terms for Selected
  terms). The levels of a weight follow this order.
* ``Planned contrasts``: ordered list of ``{"name": ..., "weights": [{"levels": [...],
  "coefficient": ...}, ...]}``. Names and levels are literal text; a level is the text of the
  category after the model's own conversion (``str`` of the value), as in the rest of the ANOVA.
* ``Planned contrast correction``: ``Holm`` (default), ``Bonferroni`` or ``None``.
* ``Planned contrast alpha``: a finite number in (0, 1), default 0.05, for the t intervals.

An absent or empty ``Planned contrasts`` list leaves the analysis exactly as before: no key is read,
no sheet is added. The other three keys are only read when contrasts are present.

Computation. The fit is the one of the ANOVA (same design, coefficients, residual SS and df); no
second fit is made. The marginal mean of a cell of the chosen factors is the average, with equal
weight, of the design rows over every combination of the levels of the model factors left out of
the contrast (Searle, Speed and Milliken's population marginal means). The levels are the ones of
the complete rows of the fit. A contrast row is ``L = sum(coefficient × marginal row)``; its
estimate is ``L @ beta`` and its variance ``MSE × L (X'X)^+ L'``, computed from the singular value
decomposition of the fitted design ``X = U S V'`` as ``MSE × ||S^-1 V' L'||²`` (no normal
equations). Intervals are pointwise t intervals at ``1 − alpha`` with the residual df.

Numerical thresholds (documented in docs/anova-planned-contrasts.md):

* ``ZERO_TOLERANCE``: ``L`` is zero by construction when ``max|L| <= 1e-9 × sum|coefficients|``.
  Every entry of a sum-coded marginal row is −1, 0 or 1, so ``sum|coefficients|`` bounds ``|L|``.
  Such a contrast (for example an interaction contrast in an additive model) is reported with
  status ``No inference``, estimate 0 and empty inference. A contrast whose estimate happens to be 0
  with a positive SE is ``OK`` with t = 0 and p = 1.
* ``ESTIMABLE_TOLERANCE``: ``L`` is estimable when its component outside the row space of ``X``
  is at most ``1e-8 × ||L||``. Trama rejects rank-deficient ANOVA fits before this point, so with
  the current engine every nonzero contrast is estimable; the ``Not estimable`` status and its
  empty inference are kept for completeness.

Corrections apply jointly to the finite p values of the recipe's contrasts (Holm's step-down or
Bonferroni); rows stay in recipe order, ties included. Intervals stay pointwise.
"""
from itertools import product
import math
from math import prod

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .i18n import tr, translate_message

FACTORS = "Planned contrast factors"
CONTRASTS = "Planned contrasts"
CORRECTION = "Planned contrast correction"
ALPHA = "Planned contrast alpha"
KEYS = (FACTORS, CONTRASTS, CORRECTION, ALPHA)
HOLM, BONFERRONI, NONE = "Holm", "Bonferroni", "None"
CORRECTIONS = (HOLM, BONFERRONI, NONE)
DEFAULT_ALPHA = 0.05
# Dialog kinds of the two compound fields (``analisi.workbench.METHODS``).
FACTOR_LIST = "Planned contrast factor list"
CONTRAST_LIST = "Planned contrast list"
SHEET = "Planned contrasts"
WEIGHTS_SHEET = "Planned contrast weights"
COLUMNS = ("Contrast", "Estimate", "SE", "df", "t", "p", "Adjusted p", "CI low", "CI high", "Status")
OK, NO_INFERENCE, NOT_ESTIMABLE = "OK", "No inference", "Not estimable"
STATUSES = (OK, NO_INFERENCE, NOT_ESTIMABLE)
MAX_CONTRASTS, MAX_NAME, MAX_WEIGHTS, MAX_CELLS = 32, 120, 256, 4096
SUM_TOLERANCE = 1e-12
ZERO_TOLERANCE = 1e-9
ESTIMABLE_TOLERANCE = 1e-8

# English sentences raised by this module. i18n registers translations under "anova.contrasts.error.".
ERRORS = {
    "factors_type": "Choose the factors of the planned contrasts.",
    "factors_repeat": "{factor} is chosen more than once for the planned contrasts.",
    "factors_absent": "{factor} is not a factor of the model, so planned contrasts cannot use it.",
    "grid": "Planned contrasts average over {cells} cells of the model factors. The limit is {limit}.",
    "collision": "Two different categories of {factor} read as the same text, {text}. Make the categories "
                 "distinct before using planned contrasts.",
    "list": "Planned contrasts must be a list of contrasts, each with a name and a list of weights.",
    "count": "Define from 1 to 32 planned contrasts.",
    "name_empty": "Contrast {index} needs a name.",
    "name_long": "The name of contrast {index} is longer than 120 characters.",
    "name_repeat": "The name {name} is used by more than one contrast.",
    "weights_few": "{name} needs at least two weights.",
    "weights_many": "{name} has more than 256 weights.",
    "levels": "{name}, weight {row}: choose one level of each factor ({factors}).",
    "unknown": "{name}, weight {row}: {factor} has no level {level} in the rows used by the model.",
    "cell_repeat": "{name}, weight {row}: the cell {cell} is already used by weight {first}.",
    "coefficient": "{name}, weight {row}: the coefficient must be a finite number.",
    "zero": "{name}, weight {row}: the coefficient must not be zero.",
    "sum": "{name}: the coefficients add up to {total}. They must add up to 0.",
    "overflow": "{name}: the coefficients are too large to add up.",
    "correction": "Choose Holm, Bonferroni or None.",
    "alpha": "The level of the intervals must be a finite number greater than 0 and less than 1.",
}


# Captions of the four fields (``trama_qt.labels`` collects LABEL_KEYS) and of the fixed choices.
LABEL_KEYS = {FACTORS: "anova.contrasts.field.factors", CONTRASTS: "anova.contrasts.field.contrasts",
              CORRECTION: "anova.contrasts.field.correction", ALPHA: "anova.contrasts.field.alpha"}
CHOICE_KEYS = {HOLM: "anova.contrasts.choice.holm", BONFERRONI: "anova.contrasts.choice.bonferroni",
               NONE: "anova.contrasts.choice.none"}


def localized(text):
    """An English message of this module in the active language; numbers take the decimal comma in Italian."""
    from .i18n import active_language

    comma = (lambda value: value.replace(".", ",")) if active_language() == "it" else (lambda value: value)
    return translate_message(str(text), "anova.contrasts.error.", convert={"total": comma})


def format_error(error):
    """Translated sentence of an error on one of the four fields, after its caption; else None."""
    field = getattr(error, "field", None)
    if field not in LABEL_KEYS:
        return None
    message = localized(error)
    caption = tr(LABEL_KEYS[field])
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


class ContrastError(FieldError):
    """A FieldError that also says which contrast (0-based) and weight row (0-based) it is about."""

    def __init__(self, field, message, *, contrast=None, weight=None, part=None):
        super().__init__(field, message)
        self.contrast, self.weight, self.part = contrast, weight, part


def _fail(field, key, *, contrast=None, weight=None, part=None, **values):
    return ContrastError(field, ERRORS[key].format(**values), contrast=contrast, weight=weight, part=part)


def _quoted(text):
    return f"“{text}”"


def _number(value):
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def active(options):
    """True when the recipe asks for planned contrasts: a non-empty ``Planned contrasts`` value."""
    value = options.get(CONTRASTS)
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return bool(value)
    return True  # Anything else is a malformed request, reported by ``check_request``.


def correction(options):
    value = options.get(CORRECTION, HOLM)
    if value not in CORRECTIONS:
        raise _fail(CORRECTION, "correction")
    return value


def alpha(options):
    value = options.get(ALPHA, DEFAULT_ALPHA)
    if not _number(value) or not math.isfinite(float(value)) or not 0 < float(value) < 1:
        raise _fail(ALPHA, "alpha")
    return float(value)


def check_factors(options, model_factors):
    """The ``Planned contrast factors`` as a list. Raises FieldError on that field."""
    chosen = options.get(FACTORS)
    if (not isinstance(chosen, (list, tuple)) or not chosen
            or any(not isinstance(name, str) for name in chosen)):
        raise _fail(FACTORS, "factors_type")
    seen = set()
    for name in chosen:
        if name in seen:
            raise _fail(FACTORS, "factors_repeat", factor=_quoted(name))
        seen.add(name)
        if name not in model_factors:
            raise _fail(FACTORS, "factors_absent", factor=_quoted(name))
    return list(chosen)


def _sum(coefficients, name, index):
    """Stable sum and sum of absolute values; an overflow is a field error, never inf."""
    try:
        total = math.fsum(coefficients)
        scale = math.fsum(abs(value) for value in coefficients)
    except OverflowError:
        raise _fail(CONTRASTS, "overflow", contrast=index, part="sum", name=name) from None
    if not math.isfinite(total) or not math.isfinite(scale):
        raise _fail(CONTRASTS, "overflow", contrast=index, part="sum", name=name)
    return total, scale


def check_contrasts(options, factors):
    """Validate the shape of ``Planned contrasts`` against the chosen factors.

    Returns ``[(name, [(levels tuple, coefficient float), ...]), ...]`` in recipe order. Raises a
    ``ContrastError`` on ``Planned contrasts`` that names the contrast and the weight row. Levels are
    checked against the data later by ``check_levels``.
    """
    raw = options.get(CONTRASTS)
    if not isinstance(raw, (list, tuple)):
        raise _fail(CONTRASTS, "list")
    if not 1 <= len(raw) <= MAX_CONTRASTS:
        raise _fail(CONTRASTS, "count")
    names, checked = {}, []
    for index, record in enumerate(raw):
        if not isinstance(record, dict) or not isinstance(record.get("weights"), (list, tuple)):
            raise _fail(CONTRASTS, "list", contrast=index)
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _fail(CONTRASTS, "name_empty", contrast=index, part="name", index=index + 1)
        if len(name) > MAX_NAME:
            raise _fail(CONTRASTS, "name_long", contrast=index, part="name", index=index + 1)
        if name in names:
            raise _fail(CONTRASTS, "name_repeat", contrast=index, part="name", name=_quoted(name))
        names[name] = index
        weights = record["weights"]
        shown = _quoted(name)
        if len(weights) < 2:
            raise _fail(CONTRASTS, "weights_few", contrast=index, part="weights", name=shown)
        if len(weights) > MAX_WEIGHTS:
            raise _fail(CONTRASTS, "weights_many", contrast=index, part="weights", name=shown)
        cells, rows = {}, []
        for row, weight in enumerate(weights):
            where = {"contrast": index, "weight": row}
            levels = weight.get("levels") if isinstance(weight, dict) else None
            if (not isinstance(levels, (list, tuple)) or len(levels) != len(factors)
                    or any(not isinstance(level, str) for level in levels)):
                raise _fail(CONTRASTS, "levels", part="levels", name=shown, row=row + 1,
                            factors=", ".join(factors), **where)
            coefficient = weight.get("coefficient")
            if not _number(coefficient) or not math.isfinite(float(coefficient)):
                raise _fail(CONTRASTS, "coefficient", part="coefficient", name=shown, row=row + 1, **where)
            if float(coefficient) == 0:
                raise _fail(CONTRASTS, "zero", part="coefficient", name=shown, row=row + 1, **where)
            cell = tuple(levels)
            if cell in cells:
                raise _fail(CONTRASTS, "cell_repeat", part="levels", name=shown, row=row + 1,
                            cell=" × ".join(_quoted(level) for level in cell), first=cells[cell] + 1, **where)
            cells[cell] = row
            rows.append((cell, float(coefficient)))
        total, scale = _sum([value for _, value in rows], shown, index)
        if abs(total) > SUM_TOLERANCE * scale:
            raise _fail(CONTRASTS, "sum", contrast=index, part="sum", name=shown, total=f"{total:.6g}")
        checked.append((name, rows))
    return checked


def check_request(options, model_factors):
    """Every check that needs no data: factors, contrasts, correction and alpha.

    Returns ``(factors, contrasts, correction, alpha)``, or None when the recipe has no contrasts.
    """
    if not active(options):
        return None
    factors = check_factors(options, list(model_factors))
    contrasts = check_contrasts(options, factors)
    return factors, contrasts, correction(options), alpha(options)


def check_categories(frame, response, model_factors):
    """Distinct categories that the model's text conversion would merge are an error on the factors."""
    from .stats import complete

    data = complete(frame, [response], list(model_factors))
    for name in model_factors:
        values = data[name]
        texts = values.astype(str)
        if texts.nunique() < values.nunique():
            groups = values.groupby(texts, sort=True).nunique()
            text = groups[groups > 1].index[0]
            raise _fail(FACTORS, "collision", factor=_quoted(name), text=_quoted(text))


def frame_levels(frame, response, model_factors):
    """Levels of each model factor in ``frame`` as the fit would see them (for the dialog, before the fit)."""
    from .stats import complete

    data = complete(frame, [response], list(model_factors))
    return {name: sorted(data[name].astype(str).unique()) for name in model_factors}


def model_levels(data, model_factors):
    """Levels of each model factor, as the fit sees them: sorted text of the complete rows."""
    return {name: sorted(data[key].unique()) for name, key in zip(model_factors, data.columns[1:])}


def check_levels(contrasts, factors, levels, model_factors):
    """Grid budget (on the factors), then every level of every weight against the fitted levels."""
    cells = prod(len(levels[name]) for name in model_factors)
    if cells > MAX_CELLS:
        raise _fail(FACTORS, "grid", cells=cells, limit=MAX_CELLS)
    known = {name: set(levels[name]) for name in factors}
    for index, (name, rows) in enumerate(contrasts):
        for row, (cell, _coefficient) in enumerate(rows):
            for factor, level in zip(factors, cell):
                if level not in known[factor]:
                    raise _fail(CONTRASTS, "unknown", contrast=index, weight=row, part="levels",
                                name=_quoted(name), row=row + 1, factor=_quoted(factor), level=_quoted(level))


def marginal_rows(design, keys, levels, chosen, cells):
    """Equal-weight marginal design rows of ``cells`` (tuples of levels of the ``chosen`` keys).

    ``keys`` are the internal keys of the model factors and ``levels`` their fitted levels. Each
    cell is averaged over every combination of the levels of the other keys.
    """
    from .stats import _design_grid

    omitted = [key for key in keys if key not in chosen]
    combos = list(product(*(levels[key] for key in omitted))) or [()]
    records = []
    for cell in cells:
        fixed = dict(zip(chosen, cell))
        for combo in combos:
            values = {**fixed, **dict(zip(omitted, combo))}
            records.append([values[key] for key in keys])
    table = pd.DataFrame(records, columns=keys, dtype=object)
    grid = np.asarray(_design_grid(design, table), dtype=float)
    return grid.reshape(len(cells), len(combos), -1).mean(axis=1)


def inference(rows, x, beta, error, df, level_alpha, scales):
    """Estimate, SE, t, p and t interval of each contrast row of ``rows`` (a 2-D array).

    ``scales`` is ``sum|coefficients|`` of each contrast, the bound of ``|L|`` used by the zero test.
    Returns a list of dicts with the columns of the sheet except Contrast and Adjusted p.
    """
    x = np.asarray(x, dtype=float)
    u, singular, vt = np.linalg.svd(x, full_matrices=False)
    del u
    cutoff = (singular[0] if singular.size else 0.0) * max(x.shape) * np.finfo(float).eps
    rank = int(np.sum(singular > cutoff))
    basis, kept = vt[:rank], singular[:rank]
    mse = error / df
    critical = stats.t.ppf(1 - level_alpha / 2, df)
    empty = {"SE": np.nan, "df": np.nan, "t": np.nan, "p": np.nan, "CI low": np.nan, "CI high": np.nan}
    results = []
    for row, scale in zip(np.atleast_2d(rows), scales):
        if np.max(np.abs(row)) <= ZERO_TOLERANCE * scale:
            results.append({"Estimate": 0.0, **empty, "Status": NO_INFERENCE})
            continue
        coordinates = basis @ row
        outside = row - coordinates @ basis
        if np.linalg.norm(outside) > ESTIMABLE_TOLERANCE * np.linalg.norm(row):
            results.append({"Estimate": np.nan, **empty, "Status": NOT_ESTIMABLE})
            continue
        estimate = float(row @ beta)
        variance = mse * float(np.sum((coordinates / kept) ** 2))
        se = math.sqrt(variance) if variance > 0 else 0.0
        if not math.isfinite(se) or se <= 0 or not math.isfinite(estimate):
            results.append({"Estimate": estimate if math.isfinite(estimate) else np.nan, **empty,
                            "Status": NOT_ESTIMABLE})
            continue
        statistic = estimate / se
        results.append({"Estimate": estimate, "SE": se, "df": float(df), "t": statistic,
                        "p": float(min(1.0, 2 * stats.t.sf(abs(statistic), df))),
                        "CI low": estimate - critical * se, "CI high": estimate + critical * se, "Status": OK})
    return results


def adjust(pvalues, method):
    """Holm or Bonferroni over the finite p values only; NaN stays NaN; recipe order is kept."""
    values = np.asarray(pvalues, dtype=float)
    adjusted = np.full(values.shape, np.nan)
    finite = np.flatnonzero(np.isfinite(values))
    m = len(finite)
    if not m:
        return adjusted
    if method == NONE:
        adjusted[finite] = values[finite]
    elif method == BONFERRONI:
        adjusted[finite] = np.minimum(1.0, m * values[finite])
    else:
        order = sorted(finite, key=lambda i: (values[i], i))  # stable: ties keep recipe order
        running = 0.0
        for position, i in enumerate(order):
            running = max(running, min(1.0, (m - position) * values[i]))
            adjusted[i] = running
    return adjusted


def weights_table(contrasts, factors):
    """``Planned contrast weights``: one row per weight, factor columns in recipe order.

    A factor named like a fixed column (``Contrast`` or ``Coefficient``) gets ``(factor)`` after its
    name in this header only.
    """
    headers, taken = [], {"Contrast", "Coefficient"}
    for name in factors:
        header = name
        while header in taken:
            header = f"{header} (factor)"
        taken.add(header)
        headers.append(header)
    records = [(name, *cell, coefficient) for name, rows in contrasts for cell, coefficient in rows]
    table = pd.DataFrame(records, columns=["Contrast", *headers, "Coefficient"])
    for header in headers:
        table[header] = table[header].astype(object)
    return table


def tables(request, model_factors, data, design, beta, error, df):
    """The two sheets of the planned contrasts from the ANOVA fit (no new fit).

    ``request`` is the result of ``check_request``; ``model_factors`` the factor names of the fit in
    the order of ``data``'s internal columns.
    """
    factors, contrasts, method, level_alpha = request
    levels = model_levels(data, model_factors)
    check_levels(contrasts, factors, levels, model_factors)
    key_of = dict(zip(model_factors, data.columns[1:]))
    keys = [key_of[name] for name in model_factors]
    chosen = [key_of[name] for name in factors]
    fitted = {key_of[name]: levels[name] for name in model_factors}
    cells = list(dict.fromkeys(cell for _, rows in contrasts for cell, _ in rows))
    position = {cell: index for index, cell in enumerate(cells)}
    marginal = marginal_rows(design, keys, fitted, chosen, cells)
    combined, scales = [], []
    for _name, rows in contrasts:
        coefficients = np.array([coefficient for _, coefficient in rows])
        members = marginal[[position[cell] for cell, _ in rows]]
        combined.append(coefficients @ members)
        scales.append(float(math.fsum(abs(value) for value in coefficients)))
    results = inference(np.vstack(combined), design.to_numpy(), beta, error, df, level_alpha, scales)
    adjusted = adjust([row["p"] for row in results], method)
    sheet = pd.DataFrame([{"Contrast": name, **row} for (name, _), row in zip(contrasts, results)])
    sheet.insert(sheet.columns.get_loc("p") + 1, "Adjusted p", adjusted)
    sheet = sheet[list(COLUMNS)]
    return {SHEET: sheet, WEIGHTS_SHEET: weights_table(contrasts, factors)}


__all__ = ["format_error", "frame_levels", "ALPHA", "CONTRASTS", "CORRECTION", "CORRECTIONS", "ContrastError", "FACTORS", "KEYS", "SHEET",
           "WEIGHTS_SHEET", "active", "adjust", "check_categories", "check_request", "inference", "tables"]
