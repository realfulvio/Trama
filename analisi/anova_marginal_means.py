"""Estimated marginal means of the fixed-effects Multifactor ANOVA.

The recipe of ``Multifactor ANOVA`` gains four keys. They are read only when ``Estimated marginal
means`` is true. An absent key, or the value false, leaves the analysis as it was: no other key is
read and no sheet is added.

* ``Estimated marginal means``: true to ask for the sheet.
* ``Marginal mean factors``: ordered factor names, a subset of the factors that are in the model
  (all of ``Factors`` for Full hierarchy, the factors of the terms for Selected terms). One row is
  produced for every combination of their levels.
* ``Include overall mean``: true adds the mean of every cell of the reference grid.
* ``Marginal mean confidence``: a finite number in (0, 1), default 0.95, for the two-sided t intervals.

A mean is the equal-weight average of the design rows over every level combination of the model
factors left out of the request (the population marginal mean). Levels are those of the complete
rows of the fit. The estimate is Lβ and the variance is MSE × L (X′X)⁺ L′, from the same singular
value decomposition the planned contrasts use. The sheet says so in ``Weighting``.

A mean that is not a linear function of the fitted model is reported with empty numbers, status
``Not estimable`` and a reason. The ANOVA still refuses a rank-deficient fit, as it always has.
"""
from itertools import product
import math
from math import prod

import numpy as np
import pandas as pd

from . import anova_planned_contrasts as planned
from .field_error import FieldError
from .i18n import tr, translate_message

ENABLED = "Estimated marginal means"
FACTORS = "Marginal mean factors"
OVERALL = "Include overall mean"
CONFIDENCE = "Marginal mean confidence"
KEYS = (ENABLED, FACTORS, OVERALL, CONFIDENCE)
# Dialog kinds. The panel owns the four keys; the catalog still lists them so a recipe round-trips.
PANEL = "Estimated marginal means panel"
FACTOR_LIST = "Marginal mean factor list"
SHEET = "Estimated marginal means"
DEFAULT_CONFIDENCE = 0.95
MAX_CELLS = 4096
WEIGHTING_TEXT = "Uniform weight on each reference-grid cell"
REASON_NOT_ESTIMABLE = "This mean is not estimable from the fitted model."
REASON_NO_INFERENCE = "This mean is zero by construction, so there is no interval."
COMBINATION_ROW = "Combination"
OVERALL_ROW = "Overall"
VALUE_COLUMNS = ("Estimate", "SE", "df", "CI low", "CI high", "Confidence", "Weighting", "Status", "Reason")
_RESERVED = {"Mean", *VALUE_COLUMNS}

ERRORS = {
    "enabled": "Choose whether to report estimated marginal means.",
    "factors_type": "Choose the factors of the estimated marginal means.",
    "factors_repeat": "{factor} is chosen more than once for the estimated marginal means.",
    "factors_absent": "{factor} is not a factor of the model, so estimated marginal means cannot use it.",
    "factors_empty": "Choose at least one factor, or include the overall mean.",
    "overall": "Choose whether to include the overall mean.",
    "confidence": "The confidence level must be a finite number greater than 0 and less than 1.",
    "grid": "Estimated marginal means average over {cells} cells of the model factors. The limit is {limit}.",
    "collision": "Two different categories of {factor} read as the same text, {text}. Make the categories "
                 "distinct before using estimated marginal means.",
}

LABEL_KEYS = {ENABLED: "anova.means.field.enabled", FACTORS: "anova.means.field.factors",
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
    caption = tr(LABEL_KEYS[field])
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def _fail(field, key, **values):
    return FieldError(field, ERRORS[key].format(**values))


def _quoted(text):
    return f"“{text}”"


def _number(value):
    if isinstance(value, (bool, np.bool_)):
        return math.nan
    if not isinstance(value, (int, float, np.integer, np.floating)):
        return math.nan
    try:
        return float(value)
    except (OverflowError, ValueError):
        return math.nan


def _flag(value):
    """True or False for a real boolean; None when the recipe value is not one."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return None


def active(options):
    """True when the recipe asks for the sheet. Absent and false do not: the other keys are ignored."""
    if ENABLED not in options:
        return False
    flag = _flag(options[ENABLED])
    if flag is False:
        return False
    return True


def check_options(options, model_factors):
    """Factors, the overall mean and the confidence. None when the recipe does not ask for the sheet.

    Raises FieldError on the field that should be corrected. No data are read.
    """
    if not active(options):
        return None
    if _flag(options.get(ENABLED)) is not True:
        raise _fail(ENABLED, "enabled")
    model = list(model_factors)
    if FACTORS in options:
        chosen = options[FACTORS]
        if (not isinstance(chosen, (list, tuple)) or any(not isinstance(name, str) for name in chosen)):
            raise _fail(FACTORS, "factors_type")
        seen = set()
        for name in chosen:
            if name in seen:
                raise _fail(FACTORS, "factors_repeat", factor=_quoted(name))
            seen.add(name)
            if name not in model:
                raise _fail(FACTORS, "factors_absent", factor=_quoted(name))
        factors = list(chosen)
    else:
        factors = []
    if OVERALL in options:
        include = _flag(options[OVERALL])
        if include is None:
            raise _fail(OVERALL, "overall")
    else:
        include = False
    if not factors and not include:
        raise _fail(FACTORS, "factors_empty")
    if CONFIDENCE in options:
        confidence = _number(options[CONFIDENCE])
        if not 0 < confidence < 1:
            raise _fail(CONFIDENCE, "confidence")
    else:
        confidence = DEFAULT_CONFIDENCE
    return factors, include, confidence


def check_data(request, frame, response, model_factors):
    """Categories and the reference-grid budget, before the fit. A bad column is left to the fit."""
    from .stats import complete

    if request is None or not model_factors:
        return
    try:
        data = complete(frame, [response], list(model_factors))
    except (ValueError, KeyError, TypeError):
        return
    for name in model_factors:
        values = data[name]
        texts = values.astype(str)
        if texts.nunique() < values.nunique():
            groups = values.groupby(texts, sort=True).nunique()
            text = groups[groups > 1].index[0]
            raise _fail(FACTORS, "collision", factor=_quoted(name), text=_quoted(text))
    cells = prod(int(data[name].astype(str).nunique()) for name in model_factors)
    if cells > MAX_CELLS:
        raise _fail(FACTORS, "grid", cells=cells, limit=MAX_CELLS)


def _headers(factors):
    headers, taken = [], set(_RESERVED)
    for name in factors:
        header = name
        while header in taken:
            header = f"{header} (factor)"
        taken.add(header)
        headers.append(header)
    return headers


def _present(result, confidence):
    """One sheet row of numbers from an inference dict. Empty numbers stay empty."""
    status = result["Status"]
    if status == planned.OK:
        df = result["df"]
        df = int(df) if float(df).is_integer() else float(df)
        return {"Estimate": result["Estimate"], "SE": result["SE"], "df": df,
                "CI low": result["CI low"], "CI high": result["CI high"], "Confidence": confidence,
                "Weighting": WEIGHTING_TEXT, "Status": planned.OK, "Reason": ""}
    reason = REASON_NO_INFERENCE if status == planned.NO_INFERENCE else REASON_NOT_ESTIMABLE
    estimate = result["Estimate"] if status == planned.NO_INFERENCE else np.nan
    return {"Estimate": estimate, "SE": np.nan, "df": np.nan, "CI low": np.nan, "CI high": np.nan,
            "Confidence": confidence, "Weighting": WEIGHTING_TEXT, "Status": status, "Reason": reason}


def linear_means(rows, design, beta, error, df, confidence):
    """Estimate, SE and t interval of each design row in ``rows``. The ANOVA fit is not repeated."""
    rows = np.atleast_2d(np.asarray(rows, dtype=float))
    inferred = planned.inference(rows, np.asarray(design, dtype=float), beta, error, df,
                                 1.0 - confidence, np.ones(len(rows)))
    return [_present(result, confidence) for result in inferred]


def tables(request, model_factors, data, design, beta, error, df):
    """The ``Estimated marginal means`` sheet from the ANOVA fit (no new fit).

    ``request`` is the result of ``check_options``. ``model_factors`` follow the factor columns of
    ``data``.
    """
    factors, include_overall, confidence = request
    if len(model_factors) != len(data.columns) - 1:
        raise ValueError("The model factors do not match the fitted design.")
    levels = planned.model_levels(data, model_factors)
    cells = prod(len(levels[name]) for name in model_factors)
    if cells > MAX_CELLS:
        raise _fail(FACTORS, "grid", cells=cells, limit=MAX_CELLS)
    key_of = dict(zip(model_factors, data.columns[1:]))
    keys = [key_of[name] for name in model_factors]
    fitted = {key_of[name]: levels[name] for name in model_factors}
    blocks, meta = [], []
    if factors:
        grid = list(product(*(levels[name] for name in factors)))
        chosen = [key_of[name] for name in factors]
        blocks.append(planned.marginal_rows(design, keys, fitted, chosen, grid))
        meta.extend((COMBINATION_ROW, cell) for cell in grid)
    if include_overall:
        blocks.append(planned.marginal_rows(design, keys, fitted, [], [()]))
        meta.append((OVERALL_ROW, ()))
    presented = linear_means(np.vstack(blocks), design.to_numpy(), beta, error, df, confidence)
    headers = _headers(factors)
    records = []
    for (kind, cell), numbers in zip(meta, presented):
        factor_values = ({header: (np.nan if kind == OVERALL_ROW else level)
                          for header, level in zip(headers, cell)} if kind == COMBINATION_ROW
                         else {header: np.nan for header in headers})
        if include_overall:
            records.append({"Mean": kind, **factor_values, **numbers})
        else:
            records.append({**factor_values, **numbers})
    columns = (["Mean", *headers] if include_overall else list(headers)) + list(VALUE_COLUMNS)
    sheet = pd.DataFrame(records, columns=columns)
    for header in (["Mean"] if include_overall else []) + headers:
        sheet[header] = sheet[header].astype(object)
    return {SHEET: sheet}


__all__ = ["CONFIDENCE", "ENABLED", "FACTORS", "FACTOR_LIST", "KEYS", "OVERALL", "PANEL", "SHEET",
           "active", "check_data", "check_options", "format_error", "linear_means", "localized", "tables"]
