"""Estimated marginal means of the fixed-effects Multifactor ANOVA.

The recipe of ``Multifactor ANOVA`` gains four keys, read only when estimation is requested:

* ``Estimated marginal means``: ``True`` to add the sheet. Absent or ``False`` leaves the analysis
  unchanged, and the other three keys are not read.
* ``Marginal mean factors``: ordered factor names, a subset of the factors in the model. One row is
  produced for every combination of their levels.
* ``Include overall mean``: ``True`` adds the mean of every cell in the reference grid.
* ``Marginal mean confidence``: a finite number in (0, 1), default 0.95. The dialog shows it as a
  percentage; the recipe stores the proportion.

A mean is the equal-weight average of the fitted design rows over the reference grid (every
combination of the levels of the model factors), the same population marginal mean the planned
contrasts already use. With unbalanced data this is not the raw mean of the rows. The estimate is
``Lβ`` from the ANOVA fit already made, and the standard error comes from ``MSE × L(X′X)⁺L′`` with
the residual degrees of freedom of that fit. Intervals are two-sided t intervals. No second fit is
made.

The reference grid is limited to 4096 cells, the same budget as planned contrasts. A mean that is
not a linear function of the fitted coefficients is reported with empty numbers and a reason.
"""
from itertools import product
import math
from math import prod

import numpy as np
import pandas as pd

from .anova_planned_contrasts import NOT_ESTIMABLE, OK, inference, marginal_rows, model_levels
from .field_error import FieldError
from .i18n import tr, translate_message

ENABLED = "Estimated marginal means"
FACTORS = "Marginal mean factors"
OVERALL = "Include overall mean"
CONFIDENCE = "Marginal mean confidence"
KEYS = (ENABLED, FACTORS, OVERALL, CONFIDENCE)
# Dialog kinds. The panel owns the last three keys; the catalog still lists them.
PANEL = "Estimated marginal means panel"
FACTOR_LIST = "Marginal mean factor list"
HELD = (FACTORS, OVERALL, CONFIDENCE)
SHEET = "Estimated marginal means"
MEAN, COMBINATION, GRAND = "Mean", "Combination", "Overall"
WEIGHTING = "Weighting"
WEIGHTING_TEXT = "Equal weight on each cell of the reference grid"
STATUS, REASON = "Status", "Reason"
REASON_NOT_ESTIMABLE = "This mean is not estimable from the fitted model."
STAT_COLUMNS = ("Estimate", "SE", "df", "CI low", "CI high", "Confidence", WEIGHTING, STATUS, REASON)
MAX_CELLS = 4096
DEFAULT_CONFIDENCE = 0.95

ERRORS = {
    "enabled": "Choose whether to estimate marginal means.",
    "factors_type": "Choose the factors of the marginal means.",
    "factors_repeat": "{factor} is chosen more than once for the marginal means.",
    "factors_absent": "{factor} is not a factor of the model, so marginal means cannot use it.",
    "empty": "Choose at least one factor, or include the overall mean.",
    "grid": "Marginal means average over {cells} cells of the model factors. The limit is {limit}.",
    "collision": "Two different categories of {factor} read as the same text, {text}. Make the "
                 "categories distinct before estimating marginal means.",
    "overall": "Choose whether to include the overall mean.",
    "confidence": "The confidence level must be a finite number greater than 0 and less than 1.",
    "confidence_percent": "Enter a confidence percentage greater than 0 and less than 100.",
}

LABEL_KEYS = {ENABLED: "anova.means.field", FACTORS: "anova.means.field.factors",
              OVERALL: "anova.means.field.overall", CONFIDENCE: "anova.means.field.confidence"}


def localized(text):
    """An English message of this module in the active language."""
    return translate_message(str(text), "anova.means.error.")


def format_error(error):
    """Translated sentence of an error on one of the four fields, after its caption; else None."""
    field = getattr(error, "field", None)
    if field not in LABEL_KEYS:
        return None
    message = localized(error)
    key = LABEL_KEYS[field]
    shown = tr(key)
    caption = field if shown == key else shown
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def _fail(field, key, **values):
    return FieldError(field, ERRORS[key].format(**values))


def _quoted(text):
    return f"“{text}”"


def _number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        return math.nan
    try:
        return float(value)
    except OverflowError:
        return math.nan


def active(options):
    """True only when the recipe explicitly asks for estimated marginal means."""
    return isinstance(options, dict) and options.get(ENABLED, False) is True


def _factors(options, model_factors):
    chosen = options.get(FACTORS, ())
    if chosen is None:
        chosen = ()
    if not isinstance(chosen, (list, tuple)) or any(not isinstance(name, str) for name in chosen):
        raise _fail(FACTORS, "factors_type")
    seen = set()
    model = list(model_factors)
    for name in chosen:
        if name in seen:
            raise _fail(FACTORS, "factors_repeat", factor=_quoted(name))
        seen.add(name)
        if name not in model:
            raise _fail(FACTORS, "factors_absent", factor=_quoted(name))
    return list(chosen)


def _overall(options):
    value = options.get(OVERALL, False)
    if value is not True and value is not False:
        raise _fail(OVERALL, "overall")
    return value


def confidence(options):
    """The interval confidence as a proportion. Raises FieldError on the confidence field."""
    value = _number(options.get(CONFIDENCE, DEFAULT_CONFIDENCE))
    if not 0 < value < 1:
        raise _fail(CONFIDENCE, "confidence")
    return value


def ensure_grid(levels, model_factors):
    """Reject a reference grid above ``MAX_CELLS`` before any mean is computed."""
    names = list(model_factors)
    cells = prod(len(levels[name]) for name in names) if names else 1
    if cells > MAX_CELLS:
        raise _fail(FACTORS, "grid", cells=cells, limit=MAX_CELLS)
    return cells


def _categories(frame, response, model_factors):
    """Levels the fit would see, or None when the columns are not ready for a fit."""
    from .anova_planned_contrasts import frame_levels
    from .stats import complete

    try:
        data = complete(frame, [response], list(model_factors))
    except (ValueError, KeyError, TypeError):
        return None
    for name in model_factors:
        values = data[name]
        texts = values.astype(str)
        if texts.nunique() < values.nunique():
            groups = values.groupby(texts, sort=True).nunique()
            text = groups[groups > 1].index[0]
            raise _fail(FACTORS, "collision", factor=_quoted(name), text=_quoted(text))
    try:
        return frame_levels(frame, response, model_factors)
    except (ValueError, KeyError, TypeError):
        return None


def check_request(options, model_factors, frame=None, response=None):
    """Validate factors, the overall mean, confidence and the reference grid.

    Returns ``(factors, include_overall, confidence)``, or None when the recipe does not ask for
    means. Data checks run only when ``frame`` is supplied; a column the fit will reject is left
    for the fit. The grid check needs no coefficients.
    """
    if not isinstance(options, dict) or ENABLED not in options:
        return None
    enabled = options[ENABLED]
    if enabled is False:
        return None
    if enabled is not True:
        raise _fail(ENABLED, "enabled")
    factors = _factors(options, model_factors)
    include_overall = _overall(options)
    if not factors and not include_overall:
        raise _fail(FACTORS, "empty")
    level = confidence(options)
    if frame is not None and response is not None:
        levels = _categories(frame, response, model_factors)
        if levels is not None:
            ensure_grid(levels, model_factors)
    return factors, include_overall, level


def _headers(factors):
    """Factor names, with `` (factor)`` appended while a name is already a fixed column."""
    taken = {MEAN, *STAT_COLUMNS}
    headers = []
    for name in factors:
        header = name
        while header in taken:
            header = f"{header} (factor)"
        taken.add(header)
        headers.append(header)
    return headers


def _estimate(rows, design, beta, error, df, level):
    """Estimate, SE and t interval of each marginal row. ``level`` is the confidence proportion."""
    return inference(np.atleast_2d(rows), np.asarray(design.to_numpy(), dtype=float), beta, error, df,
                     1 - level, [1.0] * len(np.atleast_2d(rows)))


def _values(result, level):
    """Numbers for one row. A mean that is not estimable contributes empty numbers and a reason."""
    if result.get("Status") == OK:
        return {"Estimate": result["Estimate"], "SE": result["SE"], "df": result["df"],
                "CI low": result["CI low"], "CI high": result["CI high"], "Confidence": level,
                WEIGHTING: WEIGHTING_TEXT, STATUS: OK, REASON: ""}
    return {"Estimate": np.nan, "SE": np.nan, "df": np.nan, "CI low": np.nan, "CI high": np.nan,
            "Confidence": level, WEIGHTING: WEIGHTING_TEXT, STATUS: NOT_ESTIMABLE,
            REASON: REASON_NOT_ESTIMABLE}


def present(headers, cells, results, level, overall=None):
    """The sheet: one row per combination, then the overall mean when ``overall`` is a result."""
    records = []
    for cell, result in zip(cells, results):
        records.append({MEAN: COMBINATION, **dict(zip(headers, cell)), **_values(result, level)})
    if overall is not None:
        records.append({MEAN: GRAND, **dict.fromkeys(headers, ""), **_values(overall, level)})
    table = pd.DataFrame(records, columns=[MEAN, *headers, *STAT_COLUMNS])
    for column in (MEAN, *headers, WEIGHTING, STATUS, REASON):
        table[column] = table[column].astype(object)
    return table


def sheet(request, model_factors, data, design, beta, error, df):
    """Estimated marginal means from the ANOVA fit (no new fit).

    ``request`` is the result of ``check_request``. ``model_factors`` are the factor names of the
    fit, in the order of ``data``'s internal columns. Levels and complete rows are those of the fit.
    """
    factors, include_overall, level = request
    levels = model_levels(data, model_factors)
    ensure_grid(levels, model_factors)
    key_of = dict(zip(model_factors, data.columns[1:]))
    keys = [key_of[name] for name in model_factors]
    fitted = {key_of[name]: levels[name] for name in model_factors}
    headers = _headers(factors)
    cells = list(product(*(levels[name] for name in factors))) if factors else []
    results = []
    if cells:
        chosen = [key_of[name] for name in factors]
        results = _estimate(marginal_rows(design, keys, fitted, chosen, cells), design, beta, error, df, level)
    overall = None
    if include_overall:
        overall = _estimate(marginal_rows(design, keys, fitted, [], [()]), design, beta, error, df, level)[0]
    return present(headers, cells, results, level, overall)


__all__ = ["CONFIDENCE", "ENABLED", "FACTORS", "KEYS", "OVERALL", "SHEET", "active", "check_request",
           "format_error", "present", "sheet"]
