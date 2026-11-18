"""ANCOVA with adjusted means: a long table, Y against a covariate X in several groups.

The groups are compared by the response each one is predicted to have at one common value of X, the
reference. Two estimators share one result contract, and the choice is the user's:

* ``Common``: one slope for every group. The columns are ``[D, z]``, with D the group indicators (no global
  intercept) and ``z = X - reference``. The adjusted means are the coefficients of D.
* ``By group``: a slope for each group, ``[D, D*z]``. Every group keeps its own line, so the differences
  between groups are specific to the reference. Nothing here assumes the lines are parallel.

The test that the slopes are equal is a diagnostic, never a gate. Both tests are extra sum-of-squares F tests
between nested fits of the same complete observations: ``((RSS_reduced - RSS_full) / numerator df) /
(RSS_full / denominator df)`` with the upper F tail.

=====================  ==================  =======================================
Test                   Reduced model       Full model and denominator
=====================  ==================  =======================================
Equal slopes           ``[D, z]``          ``[D, D*z]``, df = N - 2g
Groups at reference    Common ``[1, z]``   Common ``[D, z]``, df = N - g - 1
                       By group ``[1, D*z]``  By group ``[D, D*z]``, df = N - 2g
=====================  ==================  =======================================

Both use g - 1 numerator degrees of freedom. In the By group model the equality of groups is specific to the
reference, because the reduced model shares only the centered intercept.

Numerics. The response is centered and divided by its largest deviation, X is shifted to the reference and
divided by its largest distance from it, and the columns of every design are scaled to unit length before an
orthogonal (QR) factorization. ``Cov(beta) = s² (A'A)^-1`` is built from the triangular factor, never from an
inverted ``A'A``. Slopes, intercepts and sums of squares are converted back to the units entered. A reference so
far from the data that the design loses its precision is an error on ``Reference X``, not a wrong answer. A fit is
exact when RSS is at most 1e-12 of the total sum of squares of the response, a threshold that follows the scale
of the response; its means keep their estimates with a standard error of zero and every inferential column
(intervals, t, F, p) stays empty.

A row enters the fit only when Response, Covariate and Group are all present. The source index of each row,
the order of first appearance of the groups and the type of each group level are kept: the text ``1`` and the
number ``1`` are different groups and are told apart in the labels shown. Everything assumes independent
observations and one error variance for all groups. Confidence intervals are pointwise; the adjusted p values of
the contrasts correct for the number of comparisons with Holm or Bonferroni (or None).
"""
from dataclasses import dataclass
from decimal import Decimal
import re

import numpy as np
import pandas as pd
from scipy import linalg, stats

from .category_graphs import COLORS
from .data import decimal_comma
from .field_error import FieldError
from .processing import TEXT, _column
from .reporting import Result, _plot

ANCOVA = "ANCOVA"
RESPONSE, COVARIATE, GROUP = "Response", "Covariate", "Group"
SLOPE_MODEL, REFERENCE_X, REFERENCE_DOMAIN = "Slope model", "Reference X", "Reference domain"
COMPARISONS, CONTROL_GROUP, ADJUSTMENT = "Comparisons", "Control group", "Adjustment"
CONFIDENCE, GRAPH = "Confidence level (%)", "Graph"
COMMON, BY_GROUP = SLOPE_MODELS = ("Common", "By group")
COMMON_RANGE, EXTRAPOLATE = DOMAINS = ("Common range", "Allow extrapolation")
ALL_PAIRS, AGAINST_CONTROL, NO_COMPARISONS = COMPARISON_MODES = ("All pairs", "Against control", "None")
HOLM, BONFERRONI, NO_ADJUSTMENT = ADJUSTMENTS = ("Holm", "Bonferroni", "None")
FITTED_LINES, ADJUSTED_MEANS, RESIDUALS = GRAPHS = ("Fitted lines", "Adjusted means", "Residuals")
# The first entry of a choice is its default. Reference X is text so that it can stay empty (the mean of X).
OPTIONS = {RESPONSE: None, COVARIATE: None, GROUP: None, SLOPE_MODEL: SLOPE_MODELS, REFERENCE_X: TEXT,
           REFERENCE_DOMAIN: DOMAINS, COMPARISONS: COMPARISON_MODES, CONTROL_GROUP: "Group choice",
           ADJUSTMENT: ADJUSTMENTS, CONFIDENCE: 95.0, GRAPH: GRAPHS}
DATA_FIELDS = (RESPONSE, COVARIATE, GROUP)

MODEL_SHEET, TESTS_SHEET, MEANS_SHEET, CONTRASTS_SHEET, FITTED_SHEET = (
    "ANCOVA model", "ANCOVA tests", "Adjusted means", "ANCOVA contrasts", "ANCOVA fitted")
EQUAL_SLOPES, GROUPS_AT_REFERENCE = "Equal slopes", "Groups at reference"
OK, EXACT = "OK", "Exact fit"
MIN_GROUPS, MAX_GROUPS, MIN_ROWS, MAX_ROWS = 2, 12, 3, 50_000
MAX_CHOICES = 24
GID = "ancova:"
# A residual sum of squares at or below this fraction of the response's total sum of squares is zero.
_EXACT = 1e-12
# Nested fits may disagree by rounding; a larger gain of the smaller model is a numerical failure.
_ROUNDING = 1e-9
# The condition number of the column-scaled design beyond which a result is not trusted.
_STABLE = 1e8
# Two X values closer than this many units in the last place cannot be told apart.
_ULPS = 16
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "h")

# English sentences raised by this module. i18n registers translations under "ancova.error.".
ERRORS = {
    "unique": "Worksheet column names must be unique.",
    "choose": "Choose a column for {field}.",
    "exists": 'Choose an existing column for {field}: "{column}" is not in the worksheet.',
    "different": 'Choose three different columns for Response, Covariate and Group. {field} repeats "{column}".',
    "slope_model": "Slope model must be Common or By group.",
    "domain": "Reference domain must be Common range or Allow extrapolation.",
    "comparisons": "Comparisons must be All pairs, Against control or None.",
    "adjustment": "Adjustment must be Holm, Bonferroni or None.",
    "graph": "Graph must be Fitted lines, Adjusted means or Residuals.",
    "level": "Confidence level (%) must be a number greater than 0 and less than 100.",
    "reference": "Reference X must be a finite number, or empty to use the mean of the Covariate.",
    "complex": 'Column "{column}" contains complex data.',
    "text": 'Column "{column}" contains text or infinite values.',
    "precision": 'Column "{column}" contains integers outside the supported precision.',
    "few_groups": "ANCOVA needs at least {minimum} groups with complete values; the selected data contain {count}.",
    "many_groups": "ANCOVA compares at most {maximum} groups; the selected data contain {count}.",
    "few_rows": 'Group "{group}" has {count} complete observations. Each group needs at least {minimum}.',
    "many_rows": "ANCOVA fits at most {maximum} complete observations; the selected data contain {count}.",
    "constant": 'Group "{group}" needs at least two Covariate values that differ enough to be told apart.',
    "empty_range": "The groups share no Covariate range: the largest group minimum {low} is above the smallest "
                   "group maximum {high}. Choose Allow extrapolation, or other data.",
    "outside": "Reference X {reference} is outside the common Covariate range {low} to {high}. "
               "Enter a value inside it, or choose Allow extrapolation.",
    "outside_auto": "The mean Covariate {reference}, used as the Reference X, is outside the common range "
                    "{low} to {high}. Enter a Reference X inside it, or choose Allow extrapolation.",
    "unstable": "Reference X {reference} is too far from the observed Covariate values for a stable calculation. "
                "Enter a Reference X closer to the data.",
    "rank": "The model cannot be identified from these data. Every group needs Covariate values that vary.",
    "control_missing": "Choose the control group for Against control.",
    "control_unknown": 'Control group "{control}" is not one of the groups with complete data.',
    "control_ambiguous": 'Control group "{control}" matches more than one group. Choose one of: {choices}.',
    "range": "These values cannot be represented: the estimates leave the range of numbers the calculation supports. "
             "Check the scale of the Response and the Covariate.",
    "nested": "The nested models could not be compared reliably. Check the Covariate and the Reference X.",
}
# Field names inside a sentence are shown in the language of the dialog.
ERROR_FIELDS = (RESPONSE, COVARIATE, GROUP, SLOPE_MODEL, REFERENCE_X, REFERENCE_DOMAIN, COMPARISONS, CONTROL_GROUP,
                ADJUSTMENT, CONFIDENCE, GRAPH)
_COLUMN_PROBLEMS = re.compile(
    r'Column "(?P<column>.*)" contains (?P<kind>complex data|text or infinite values|'
    r'integers outside the supported precision)\.', re.DOTALL)
_COLUMN_KEYS = {"complex data": "complex", "text or infinite values": "text",
                "integers outside the supported precision": "precision"}
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _fail(where, key, **values):
    """A FieldError on the control ``where``; ``values`` fill the placeholders of the English sentence."""
    return FieldError(where, ERRORS[key].format(**values))


def format_error(error):
    """Translated sentence of an error of this module, prefixed by its field caption; else None."""
    from .i18n import translate_message, ui
    field = getattr(error, "field", None)
    if field not in ERROR_FIELDS:
        return None
    message = translate_message(str(error), "ancova.error.", {"field": ui})
    caption = ui(field)
    if caption and caption not in message:
        message = f"{caption}: {message}"
    return message


def visibility(comparisons):
    """The control group belongs to Against control; the adjustment to either comparison."""
    return {CONTROL_GROUP: comparisons == AGAINST_CONTROL, ADJUSTMENT: comparisons != NO_COMPARISONS}


def _fmt(value):
    return format(float(value), ".10g")


def _literal(text):
    """Keep a dollar sign as text; Matplotlib would otherwise read it as math."""
    return str(text).replace("$", r"\$")


# ----- options -------------------------------------------------------------------------------------------------------

def _finite(value, field, key):
    """A finite number from a number or from text with a decimal point or comma; never a bool."""
    if isinstance(value, str):
        text = decimal_comma(value.strip())
        if not _NUMBER.fullmatch(text):
            raise _fail(field, key)
        value = float(text)
    elif isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise _fail(field, key)
    try:
        number = float(value)
    except OverflowError:
        raise _fail(field, key) from None
    if not np.isfinite(number):
        raise _fail(field, key)
    return number


def reference_value(options):
    """The Reference X typed by the user, or None when it is empty (the mean of every complete X)."""
    value = options.get(REFERENCE_X)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _finite(value, REFERENCE_X, "reference")


def _choice(options, field, choices, key):
    value = options.get(field)
    if value is None or value == "":
        return choices[0]
    if not isinstance(value, str) or value not in choices:
        raise _fail(field, key)
    return value


@dataclass(frozen=True)
class _Setup:
    response: str
    covariate: str
    group: str
    slope: str
    domain: str
    comparisons: str
    adjustment: str
    graph: str
    level: float
    reference: float | None
    control: object


def _setup(frame, options):
    if not frame.columns.is_unique:
        raise _fail(RESPONSE, "unique")
    names = {}
    for field in DATA_FIELDS:
        name = options.get(field)
        if name is None or name == "":
            raise _fail(field, "choose", field=field)
        if not isinstance(name, str) or name not in frame.columns:
            raise _fail(field, "exists", field=field, column=name)
        names[field] = name
    # A repeated column is reported on the field of its second use, in the order Response, Covariate, Group.
    if names[COVARIATE] == names[RESPONSE]:
        raise _fail(COVARIATE, "different", field=COVARIATE, column=names[COVARIATE])
    for other in (RESPONSE, COVARIATE):
        if names[GROUP] == names[other]:
            raise _fail(GROUP, "different", field=GROUP, column=names[GROUP])
    level = _finite(options.get(CONFIDENCE, 95.0), CONFIDENCE, "level")
    if not 0 < level < 100:
        raise _fail(CONFIDENCE, "level")
    return _Setup(
        names[RESPONSE], names[COVARIATE], names[GROUP],
        _choice(options, SLOPE_MODEL, SLOPE_MODELS, "slope_model"),
        _choice(options, REFERENCE_DOMAIN, DOMAINS, "domain"),
        _choice(options, COMPARISONS, COMPARISON_MODES, "comparisons"),
        _choice(options, ADJUSTMENT, ADJUSTMENTS, "adjustment"),
        _choice(options, GRAPH, GRAPHS, "graph"),
        level, reference_value(options), options.get(CONTROL_GROUP))


# ----- data ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Level:
    key: tuple
    kind: str
    base: str
    text: str
    token: str


def _numeric(frame, name, field):
    if pd.api.types.is_complex_dtype(frame[name].dtype):
        raise _fail(field, "complex", column=name)
    try:
        return _column(frame, name, field).to_numpy(dtype=float)
    except FieldError as error:
        match = _COLUMN_PROBLEMS.fullmatch(str(error))
        if match is None:
            raise
        raise _fail(field, _COLUMN_KEYS[match["kind"]], column=match["column"]) from None


def _missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _number_text(value):
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


def _identity(value):
    """Typed identity of a group level: the text 1 and the number 1 are different groups, 1 and 1.0 are not."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return ("logical", value), "logical", str(value)
    if isinstance(value, (int, float, Decimal)):
        return ("number", value), "number", _number_text(value)
    if isinstance(value, str):
        return ("text", value), "text", value
    kind = "date" if hasattr(value, "isoformat") else type(value).__name__.lower()
    return (kind, type(value).__name__, value), kind, str(value)


def _name_levels(entries):
    """Label each level; levels with the same text show their type, and any remaining collision a number."""
    counts = {}
    for _, _, base in entries:
        counts[base] = counts.get(base, 0) + 1
    levels, used = [], set()
    for key, kind, base in entries:
        text = f"{base} ({kind})" if counts[base] > 1 else base
        unique, number = text, 1
        while unique in used:
            number += 1
            unique = f"{text} [{number}]"
        used.add(unique)
        levels.append(_Level(key, kind, base, unique, f"{kind}:{unique}"))
    return levels


@dataclass
class _Data:
    x: np.ndarray
    y: np.ndarray
    member: np.ndarray
    source: pd.Index
    levels: list
    x_min: np.ndarray
    x_max: np.ndarray
    count: np.ndarray


def _complete(frame, setup, *, strict=True):
    """Complete observations: arrays, the group index of each, the source index and the typed levels."""
    x = _numeric(frame, setup.covariate, COVARIATE)
    y = _numeric(frame, setup.response, RESPONSE)
    labels = frame[setup.group].to_numpy(dtype=object)
    rows = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    rows = rows[[not _missing(labels[i]) for i in rows]]
    if strict and len(rows) > MAX_ROWS:
        raise _fail(GROUP, "many_rows", maximum=f"{MAX_ROWS:,}", count=f"{len(rows):,}")
    identities = [_identity(labels[row]) for row in rows]
    # First appearance of each level fixes its order and the text it shows.
    firsts = {}
    for identity in identities:
        firsts.setdefault(identity[0], identity)
    position = {key: index for index, key in enumerate(firsts)}
    member = np.fromiter((position[identity[0]] for identity in identities), dtype=np.intp, count=len(rows))
    return x[rows], y[rows], member, frame.index[rows], _name_levels(list(firsts.values()))


def _data(frame, setup):
    x, y, member, source, levels = _complete(frame, setup)
    g = len(levels)
    if g < MIN_GROUPS:
        raise _fail(GROUP, "few_groups", minimum=MIN_GROUPS, count=g)
    if g > MAX_GROUPS:
        raise _fail(GROUP, "many_groups", maximum=MAX_GROUPS, count=g)
    count = np.bincount(member, minlength=g)
    x_min, x_max = np.empty(g), np.empty(g)
    for k, level in enumerate(levels):
        values = x[member == k]
        if count[k] < MIN_ROWS:
            raise _fail(GROUP, "few_rows", group=level.text, count=int(count[k]), minimum=MIN_ROWS)
        x_min[k], x_max[k] = values.min(), values.max()
        reach = max(abs(x_min[k]), abs(x_max[k]))
        if not x_max[k] - x_min[k] > _ULPS * np.finfo(float).eps * reach:
            raise _fail(COVARIATE, "constant", group=level.text)
    return _Data(x, y, member, source, levels, x_min, x_max, count)


def group_choices(frame, options):
    """Labels of the groups with complete data, for the control group list; empty while the columns are unusable."""
    try:
        names = {field: options.get(field) for field in DATA_FIELDS}
        if (any(not isinstance(name, str) or name not in frame.columns for name in names.values())
                or len(set(names.values())) < 3 or not frame.columns.is_unique):
            return []
        setup = _Setup(names[RESPONSE], names[COVARIATE], names[GROUP], COMMON, COMMON_RANGE, NO_COMPARISONS,
                       HOLM, FITTED_LINES, 95.0, None, None)
        return [level.text for level in _complete(frame, setup, strict=False)[4]][:MAX_CHOICES]
    except (ValueError, TypeError, OverflowError):
        return []


def _control(levels, value):
    """Index of the control group. A text matches the labels shown; any other value matches by type."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _fail(CONTROL_GROUP, "control_missing")
    if isinstance(value, str):
        matches = [k for k, level in enumerate(levels) if level.text == value]
        if not matches:
            matches = [k for k, level in enumerate(levels) if level.base == value and level.kind == "text"]
        if not matches:
            similar = [level.text for level in levels if level.base == value]
            if len(similar) > 1:
                raise _fail(CONTROL_GROUP, "control_ambiguous", control=value, choices=", ".join(similar))
    else:
        key = _identity(value)[0]
        matches = [k for k, level in enumerate(levels) if level.key == key]
    if not matches:
        raise _fail(CONTROL_GROUP, "control_unknown", control=value)
    return matches[0]


# ----- the fits ------------------------------------------------------------------------------------------------------

@dataclass
class _Fit:
    beta: np.ndarray
    cov_unit: np.ndarray
    rss: float
    df: int
    fitted: np.ndarray


def _factor(design, reference, ys):
    """Orthogonal fit of the column-scaled design. Rank and precision failures name the reference."""
    norms = np.linalg.norm(design, axis=0)
    scaled = design / norms
    q, r = np.linalg.qr(scaled, mode="reduced")
    singular = np.linalg.svd(r, compute_uv=False)
    if singular[-1] <= singular[0] * max(design.shape) * np.finfo(float).eps:
        raise _fail(COVARIATE, "rank")
    if singular[0] / singular[-1] > _STABLE:
        raise _fail(REFERENCE_X, "unstable", reference=_fmt(reference))
    coefficients = linalg.solve_triangular(r, q.T @ ys)
    inverse = linalg.solve_triangular(r, np.eye(r.shape[0]))
    beta = coefficients / norms
    residual = ys - scaled @ coefficients
    cov_unit = (inverse @ inverse.T) / np.outer(norms, norms)
    return _Fit(beta, cov_unit, float(residual @ residual), design.shape[0] - design.shape[1], design @ beta)


def _partial_f(reduced, full, df_num, df_den, total):
    """F, p for nested fits. Only a difference within rounding of the scale is corrected to zero."""
    gain = reduced - full
    if gain < 0:
        if -gain > _ROUNDING * max(reduced, full, _EXACT * total):
            raise _fail(REFERENCE_X, "nested")
        gain = 0.0
    f = (gain / df_num) / (full / df_den)
    return float(f), float(stats.f.sf(f, df_num, df_den))


def _adjust(p, method):
    """Holm or Bonferroni over the finite p values only; None keeps p."""
    adjusted = np.array(p, dtype=float)
    finite = np.flatnonzero(np.isfinite(adjusted))
    if method == NO_ADJUSTMENT or not len(finite):
        return adjusted
    values = adjusted[finite]
    count = len(values)
    if method == BONFERRONI:
        adjusted[finite] = np.minimum(1.0, values * count)
        return adjusted
    order = np.argsort(values, kind="stable")
    steps = np.minimum(1.0, (count - np.arange(count)) * values[order])
    adjusted[finite[order]] = np.maximum.accumulate(steps)
    return adjusted


# ----- the analysis --------------------------------------------------------------------------------------------------

def ancova(frame, options):
    """The analysis. Overflow of extreme values is reported by the finite checks below, never raised as a warning."""
    with np.errstate(over="ignore", invalid="ignore"):
        return _ancova(frame, options)


def _ancova(frame, options):
    setup = _setup(frame, options)
    data = _data(frame, setup)
    levels, g, n = data.levels, len(data.levels), len(data.x)
    lower, upper = float(data.x_min.max()), float(data.x_max.min())
    if setup.domain == COMMON_RANGE and lower > upper:
        raise _fail(REFERENCE_DOMAIN, "empty_range", low=_fmt(lower), high=_fmt(upper))
    automatic = setup.reference is None
    reference = float(np.mean(data.x)) if automatic else setup.reference
    if setup.domain == COMMON_RANGE and not lower <= reference <= upper:
        raise _fail(REFERENCE_X, "outside_auto" if automatic else "outside",
                    reference=_fmt(reference), low=_fmt(lower), high=_fmt(upper))
    control = _control(levels, setup.control) if setup.comparisons == AGAINST_CONTROL else None

    # Internal scale: the response is centered, X is shifted to the reference, both divided by their reach.
    y_center = float(np.mean(data.y))
    y_reach = float(np.max(np.abs(data.y - y_center)))
    z = data.x - reference
    x_reach = float(np.max(np.abs(z)))
    if not (np.isfinite(y_reach) and np.isfinite(x_reach) and np.isfinite(z).all()):
        raise _fail(REFERENCE_X, "range")
    y_scale = y_reach if y_reach > 0 else 1.0
    ys = (data.y - y_center) / y_scale
    zs = z / x_reach
    total = float(ys @ ys)

    indicator = (data.member[:, None] == np.arange(g)[None, :]).astype(float)
    by_group_design = np.column_stack([indicator, indicator * zs[:, None]])
    common_design = np.column_stack([indicator, zs])
    common = _factor(common_design, reference, ys)
    separate = _factor(by_group_design, reference, ys)
    chosen = common if setup.slope == COMMON else separate
    if setup.slope == COMMON:
        null = _factor(np.column_stack([np.ones(n), zs]), reference, ys)
    else:
        null = _factor(np.column_stack([np.ones(n), indicator * zs[:, None]]), reference, ys)

    def exact(rss):
        return rss <= _EXACT * total
    exact_fit = exact(chosen.rss)
    scale = y_scale
    df_num = g - 1
    rows = []
    for label, reduced, full in ((EQUAL_SLOPES, common, separate), (GROUPS_AT_REFERENCE, null, chosen)):
        if exact(full.rss):
            f = p = np.nan
            status = EXACT
        else:
            f, p = _partial_f(reduced.rss, full.rss, df_num, full.df, total)
            status = OK
        rows.append({"Test": label, "F": f, "Numerator df": df_num, "Denominator df": full.df, "p": p,
                     "Status": status})
    tests = pd.DataFrame(rows, columns=["Test", "F", "Numerator df", "Denominator df", "p", "Status"])

    df = chosen.df
    rss = 0.0 if exact_fit else chosen.rss * scale * scale
    mse = 0.0 if exact_fit else rss / df
    variance = 0.0 if exact_fit else chosen.rss / df
    beta, cov = chosen.beta, chosen.cov_unit * variance
    means = y_center + scale * beta[:g]
    slopes = (beta[g] * np.ones(g) if setup.slope == COMMON else beta[g:2 * g]) * scale / x_reach
    errors = scale * np.sqrt(np.diag(cov)[:g])
    alpha = 1 - setup.level / 100
    if exact_fit:
        low = high = np.full(g, np.nan)
    else:
        margin = stats.t.isf(alpha / 2, df) * errors
        low, high = means - margin, means + margin
    outside = (reference < data.x_min) | (reference > data.x_max)
    adjusted = pd.DataFrame({
        "Group": [level.text for level in levels], "N": data.count.astype(int), "Reference X": reference,
        "Mean": means, "SE": errors, "Lower": low, "Upper": high, "Extrapolated": outside, "Slope": slopes,
        "Status": EXACT if exact_fit else OK})

    pairs = []
    if setup.comparisons == ALL_PAIRS:
        pairs = [(i, j) for i in range(g) for j in range(i + 1, g)]
    elif setup.comparisons == AGAINST_CONTROL:
        pairs = [(i, control) for i in range(g) if i != control]
    contrasts = None
    if setup.comparisons != NO_COMPARISONS:
        records = []
        for i, j in pairs:
            difference = means[i] - means[j]
            error = scale * np.sqrt(max(cov[i, i] + cov[j, j] - 2 * cov[i, j], 0.0))
            if exact_fit:
                t = p = lo = hi = np.nan
                error = 0.0
            elif error > 0:
                t = difference / error
                p = float(2 * stats.t.sf(abs(t), df))
                half = stats.t.isf(alpha / 2, df) * error
                lo, hi = difference - half, difference + half
            else:
                t = p = lo = hi = np.nan
            records.append({"First": levels[i].text, "Second": levels[j].text, "Difference": difference,
                            "SE": error, "df": df, "Lower": lo, "Upper": hi, "t": t, "p": p})
        contrasts = pd.DataFrame(records, columns=["First", "Second", "Difference", "SE", "df", "Lower", "Upper", "t",
                                                   "p"])
        contrasts["Adjusted p"] = _adjust(contrasts["p"].to_numpy(dtype=float), setup.adjustment)
        contrasts["Status"] = EXACT if exact_fit else OK

    fitted_values = y_center + scale * chosen.fitted
    observed = data.y
    fitted = pd.DataFrame({
        "Source row": data.source, "Observed": observed, "Fitted": fitted_values, "Residual": observed - fitted_values,
        "Group": [levels[k].text for k in data.member], "Covariate": data.x})

    estimates = np.concatenate([means, slopes, errors, fitted_values])
    if not np.isfinite(estimates).all() or not np.isfinite([rss, mse]).all():
        raise _fail(REFERENCE_X, "range")
    note = _note(setup, exact_fit)
    model = pd.DataFrame([{
        "N": n, "Groups": g, "Residual df": df, "RSS": rss, "MSE": mse, "Reference X": reference,
        "Common lower": lower, "Common upper": upper, "Slope model": setup.slope,
        "Status": EXACT if exact_fit else OK, "Note": note}])
    tables = {MODEL_SHEET: model, TESTS_SHEET: tests, MEANS_SHEET: adjusted}
    if contrasts is not None:
        tables[CONTRASTS_SHEET] = contrasts
    tables[FITTED_SHEET] = fitted
    figure = _figure(setup, data, reference, means, slopes, low, high, outside, fitted)
    return Result(tables, figure)


def _note(setup, exact_fit):
    if setup.slope == COMMON:
        text = ("Common slope: the groups share one slope, so their adjusted means differ by the same amount at "
                "every X. Compare it with the equal-slopes test.")
    else:
        text = ("Separate slopes: each group keeps its own line, so the differences between groups hold at the "
                "Reference X only. The groups-at-reference test is specific to it.")
    text += (" Observations are assumed independent with one error variance. Intervals are pointwise; the adjusted "
             "p values correct the contrasts for multiple comparisons.")
    if exact_fit:
        text += (" The residual variance is zero, so the fit is exact: standard errors are zero and the intervals, "
                 "t, F and p values are empty.")
    return text


# ----- the figure ----------------------------------------------------------------------------------------------------

def _style(index):
    return COLORS[index % len(COLORS)], MARKERS[(index // len(COLORS)) % len(MARKERS)]


def _figure(setup, data, reference, means, slopes, low, high, outside, fitted):
    levels, g = data.levels, len(data.levels)
    response, covariate = setup.response, setup.covariate
    if setup.graph == FITTED_LINES:
        slope_text = "common slope" if setup.slope == COMMON else "separate slopes"
        figure, axes = _plot(f"ANCOVA fitted lines ({slope_text})", _literal(covariate), _literal(response))
        axes._tramastat_numeric_axes = ("x", "y")
        shown_extension = False
        for k, level in enumerate(levels):
            color, marker = _style(k)
            member = data.member == k
            points = axes.scatter(data.x[member], data.y[member], color=color, marker=marker, s=28, zorder=2.5,
                                  label=_literal(level.text))
            points.set_gid(f"{GID}points:{level.token}")
            ends = np.array([data.x_min[k], data.x_max[k]])
            (line,) = axes.plot(ends, means[k] + slopes[k] * (ends - reference), color=color, linewidth=1.8,
                                label="_nolegend_")
            line.set_gid(f"{GID}line:{level.token}")
            if outside[k]:
                edge = data.x_min[k] if reference < data.x_min[k] else data.x_max[k]
                (extension,) = axes.plot([edge, reference], [means[k] + slopes[k] * (edge - reference), means[k]],
                                         color=color, linewidth=1.5, linestyle=":",
                                         label="_nolegend_" if shown_extension else "Extrapolated to the reference")
                extension.set_gid(f"{GID}extension:{level.token}")
                shown_extension = True
            adjusted = axes.scatter([reference], [means[k]], color="white", edgecolor=color, marker="D", s=52,
                                    linewidth=1.6, zorder=3.5, label="_nolegend_")
            adjusted.set_gid(f"{GID}mean:{level.token}")
        guide = axes.axvline(reference, color="#475467", linestyle="--", linewidth=1.0, zorder=1,
                             label=f"Reference X = {_fmt(reference)}")
        guide.set_gid(f"{GID}reference")
        axes.legend(frameon=False, loc="best")
        return figure
    if setup.graph == ADJUSTED_MEANS:
        figure, axes = _plot("ANCOVA adjusted means", _literal(f"{setup.group} · at {covariate} = {_fmt(reference)}"),
                             _literal(f"Adjusted mean of {response}"))
        axes._tramastat_numeric_axes = ("y",)
        axes._tramastat_categorical_axes = ("x",)
        for k, level in enumerate(levels):
            color, marker = _style(k)
            if np.isfinite(low[k]):
                bars = axes.errorbar([k], [means[k]], yerr=[[means[k] - low[k]], [high[k] - means[k]]], fmt="none",
                                     ecolor=color, elinewidth=1.6, capsize=5, zorder=2)
                for part in (*bars[1], *bars[2]):
                    part.set_gid(f"{GID}interval:{level.token}")
            dot = axes.scatter([k], [means[k]], color="white" if outside[k] else color, edgecolor=color, marker=marker,
                               s=64, linewidth=1.6, zorder=3, label=_literal(level.text))
            dot.set_gid(f"{GID}mean:{level.token}")
        axes.set_xticks(range(g), [_literal(level.text) for level in levels])
        axes.set_xlim(-0.6, g - 0.4)
        if outside.any():
            names = ", ".join(level.text for level, flag in zip(levels, outside, strict=True) if flag)
            note = axes.text(0.01, 0.99, _literal(f"Extrapolated (open markers): {names}"), transform=axes.transAxes,
                             va="top", fontsize=8, color="#9a3412")
            note.set_gid(f"{GID}warning")
        return figure
    figure, axes = _plot("ANCOVA residuals against fitted values", "Fitted", "Residual")
    axes._tramastat_numeric_axes = ("x", "y")
    for k, level in enumerate(levels):
        color, marker = _style(k)
        member = data.member == k
        points = axes.scatter(fitted["Fitted"].to_numpy()[member], fitted["Residual"].to_numpy()[member], color=color,
                              marker=marker, s=28, zorder=2.5, label=_literal(level.text))
        points.set_gid(f"{GID}residuals:{level.token}")
    zero = axes.axhline(0, color="#475467", linestyle="--", linewidth=1.0, zorder=1)
    zero.set_gid(f"{GID}zero")
    axes.legend(frameon=False, loc="best")
    return figure
