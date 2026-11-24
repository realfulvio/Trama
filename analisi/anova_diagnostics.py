"""Residual diagnostics and assumption checks for one multifactor ANOVA fit.

The sheets reuse the full model's design, coefficients and residual sum of squares.
They do not fit that model again. Leverage is the diagonal of Q Q' from a reduced QR,
so the n×n hat matrix is never formed. A point with leverage indistinguishable from 1,
or a residual variance indistinguishable from 0, is reported as missing with a reason.
It is never stored as infinity or as a invented zero.

The five assumption p values describe estimated residuals. Their reference distributions
do not correct for the model projection matrix. The rows are not independent tests and
are not adjusted for multiplicity.

The normal Q–Q plot uses Blom positions (i − 0.375) / (N + 0.25). Ties keep the order of
the source rows, not the numeric order of the index. The optional reference line is the
mean of the plotted residuals plus their sample standard deviation (N − 1) times the
theoretical quantile. That is not the model residual standard deviation.

``ANOVA Q–Q reference line`` is saved only while the graph is Normal Q–Q. The four
canonical options do not name that line. Choosing Normal Q–Q again restores the default,
which is on.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .i18n import tr, translate_message
from .normality import ANDERSON, DAGOSTINO, DOMAINS, LILLIEFORS, SHAPIRO, _compute, _method_note
from .reporting import Result, _plot

DIAGNOSTICS = "ANOVA residual diagnostics"
ASSUMPTIONS = "ANOVA assumption tests"
TEST_SET = "ANOVA assumption tests included"
ALPHA = "ANOVA diagnostic alpha"
GRAPH = "ANOVA diagnostic graph"
QQ_LINE = "ANOVA Q–Q reference line"
GRAPH_NONE = "None"
GRAPH_RESIDUALS = "Residuals vs fitted"
GRAPH_HOMO = "Homoscedasticity"
GRAPH_QQ = "Normal Q–Q"
GRAPHS = (GRAPH_NONE, GRAPH_RESIDUALS, GRAPH_HOMO, GRAPH_QQ)
METHOD = "ANOVA diagnostic plot"
ALL_TESTS, NORMALITY_TESTS, VARIANCE_TEST = "All assumption tests", "Normality tests only", "Variance test only"
TEST_SETS = (ALL_TESTS, NORMALITY_TESTS, VARIANCE_TEST)
SHEET = "ANOVA residual diagnostics"
SUMMARY = "ANOVA diagnostic summary"
ASSUMPTION_SHEET = "ANOVA assumptions"
QQ_SHEET = "ANOVA Q–Q coordinates"
SPEARMAN = "Spearman |residual| vs fitted"
TESTS = (SPEARMAN, SHAPIRO, DAGOSTINO, ANDERSON, LILLIEFORS)
MAX_POINTS = 60_000
# 1 − h at or below this is treated as a perfect leverage point.
_LEVERAGE_GAP = 1e-12
_FLAT = 32 * np.finfo(float).eps
OPTIONS = {DIAGNOSTICS: False, ASSUMPTIONS: False, TEST_SET: TEST_SETS, ALPHA: 0.05, GRAPH: GRAPHS, QQ_LINE: True}
TABS = {"Diagnostics": (DIAGNOSTICS, ASSUMPTIONS, TEST_SET, ALPHA, GRAPH, QQ_LINE)}
LABEL_KEYS = {
    "Diagnostics": "anova.diag.tab",
    DIAGNOSTICS: "anova.diag.field.diagnostics",
    ASSUMPTIONS: "anova.diag.field.assumptions",
    TEST_SET: "anova.diag.field.test_set",
    ALPHA: "anova.diag.field.alpha",
    GRAPH: "anova.diag.field.graph",
    QQ_LINE: "anova.diag.field.qq_line",
}
GRAPH_CHOICE_KEYS = {
    GRAPH_NONE: "anova.diag.graph.none",
    GRAPH_RESIDUALS: "anova.diag.graph.residuals",
    GRAPH_HOMO: "anova.diag.graph.homo",
    GRAPH_QQ: "anova.diag.graph.qq",
}
TEST_CHOICE_KEYS = {
    ALL_TESTS: "anova.diag.tests.all",
    NORMALITY_TESTS: "anova.diag.tests.normality",
    VARIANCE_TEST: "anova.diag.tests.variance",
}
CAVEAT = (
    "Diagnostic p value for estimated residuals: the reference distribution does not correct "
    "for the model projection matrix. When several tests are shown, their p values are "
    "unadjusted and the tests are dependent."
)
SPEARMAN_NOTE = (
    "Two-sided Spearman correlation of the absolute residual with the fitted value. "
    "It describes association between residual size and the fitted value. "
    "It is not a causal test and it is not proof of homoscedasticity."
)
_COLUMNS = (
    "Source row", "Observed", "Fitted", "Residual", "Leverage",
    "Internally studentized residual", "Cook's distance", "PRESS residual",
)
_SUMMARY_ROWS = ("N", "Model rank", "Residual df", "Residual SS", "Residual variance", "PRESS")


def visibility(assumptions, graph):
    """Alpha applies only to assumption tests. The Q–Q line applies only to that graph."""
    return {TEST_SET: bool(assumptions), ALPHA: bool(assumptions), QQ_LINE: graph == GRAPH_QQ}


def _flag(options, name, default=False):
    if name not in options:
        return default
    value = options[name]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise FieldError(name, "Choose yes or no.")


def graph_choice(options):
    if GRAPH not in options or options[GRAPH] in (None, ""):
        return GRAPH_NONE
    choice = options[GRAPH]
    if choice not in GRAPHS:
        raise FieldError(GRAPH, "Choose a diagnostic graph.")
    return choice


def _alpha(options):
    value = options.get(ALPHA, 0.05)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(ALPHA, "Alpha must be a number between 0 and 1.")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(ALPHA, "Alpha must be a number between 0 and 1.") from None
    if not np.isfinite(value) or not 0 < value < 1:
        raise FieldError(ALPHA, "Alpha must be a finite number greater than 0 and less than 1.")
    return value


def validate(options):
    """Check the diagnostic keys without fitting. A hidden alpha is ignored."""
    diagnostics = _flag(options, DIAGNOSTICS)
    assumptions = _flag(options, ASSUMPTIONS)
    graph = graph_choice(options)
    if graph != GRAPH_NONE and not diagnostics:
        raise FieldError(GRAPH, "Turn on ANOVA residual diagnostics before choosing a diagnostic graph.")
    alpha = _alpha(options) if assumptions else None
    if assumptions and options.get(TEST_SET, ALL_TESTS) not in TEST_SETS:
        raise FieldError(TEST_SET, "Choose which assumption tests to include.")
    line = _flag(options, QQ_LINE, default=True) if graph == GRAPH_QQ else False
    return diagnostics, assumptions, alpha, graph, line


def active(options):
    """True when the recipe asks for a sheet or a graph beyond the historical ANOVA."""
    diagnostics, assumptions, _, graph, _ = validate(options)
    return diagnostics or assumptions or graph != GRAPH_NONE


def ensure_graph_budget(n, graph):
    """Refuse a diagnostic graph before any large array for that graph is allocated."""
    if graph != GRAPH_NONE and n > MAX_POINTS:
        raise FieldError(GRAPH, f"A diagnostic graph accepts at most {MAX_POINTS:,} points.")


def translate_anova_error(error):
    """English engine text, shown in the active language when the catalog has that sentence."""
    return translate_message(str(error), "anova.diag.error.")


def format_anova_error(error):
    """Translated diagnostic sentence, prefixed with the translated field caption.

    Returns None when the error does not name one of these fields, so effect-size alpha
    keeps the dialog's existing wording. Errors on the model terms of Selected terms go to
    ``anova_terms.format_error``.
    """
    field = getattr(error, "field", None)
    if field not in LABEL_KEYS or field not in (DIAGNOSTICS, ASSUMPTIONS, ALPHA, GRAPH, QQ_LINE):
        # Model terms and the comparison controls (0.83) and the sums of squares word their own errors.
        from .anova_marginal_means import format_error as format_marginal_error
        from .anova_planned_contrasts import format_error as format_contrast_error
        from .anova_ss import format_error as format_ss_error
        from .anova_terms import format_error
        return (format_ss_error(error) or format_error(error) or format_contrast_error(error)
                or format_marginal_error(error))
    message = translate_anova_error(error)
    label = tr(LABEL_KEYS[field])
    if label and label not in message:
        message = f"{label}: {message}"
    return message


def _flat(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        return True
    scale = float(np.max(np.abs(values)))
    return float(np.ptp(values)) <= _FLAT * scale


def _projection(design):
    """Reduced-QR leverage and numerical rank. Null columns are left out of the hat diagonal."""
    design = np.asarray(design, dtype=float)
    q, r = np.linalg.qr(design, mode="reduced")
    diagonal = np.abs(np.diag(r)) if r.size else np.array([], dtype=float)
    scale = float(diagonal.max()) if diagonal.size else 0.0
    tolerance = np.finfo(float).eps * max(design.shape) * scale
    keep = diagonal > tolerance
    if keep.any():
        basis = q[:, keep]
        leverage = np.sum(basis * basis, axis=1)
    else:
        leverage = np.zeros(design.shape[0])
    return leverage, int(keep.sum())


def _blank(size):
    return np.full(size, np.nan)


def observation_diagnostics(index, observed, design, beta, sse=None, df=None):
    """Diagnostics for one supplied fit, including rank-deficient and zero-variance fits.

    The ANOVA dispatcher does not call this on a fit it has already rejected. Tests call it
    directly so a perfect leverage point or a zero residual variance becomes missing data
    with a reason, never an infinity or a placeholder zero.
    """
    design = np.asarray(design, dtype=float)
    observed = np.asarray(observed, dtype=float)
    beta = np.asarray(beta, dtype=float).reshape(-1)
    n, width = design.shape
    fitted = design @ beta
    residual = observed - fitted
    leverage, rank = _projection(design)
    if df is None:
        df = n - rank
    if sse is None:
        sse = float(residual @ residual)
    sse = float(sse)
    gap = 1.0 - leverage
    perfect = ~np.isfinite(gap) | (gap <= _LEVERAGE_GAP)
    centered = float(np.sum((observed - np.mean(observed))**2))
    # The same relative rule as the ANOVA rejection, so a real residual at a small scale stays defined.
    zero_variance = df <= 0 or not np.isfinite(sse) or centered == 0 or sse <= np.finfo(float).eps * centered
    variance = sse / df if df > 0 and np.isfinite(sse) else np.nan
    student, cook, press = _blank(n), _blank(n), _blank(n)
    defined = ~perfect
    if defined.any():
        press[defined] = residual[defined] / gap[defined]
    if not zero_variance and defined.any():
        scale = np.sqrt(variance)
        student[defined] = residual[defined] / (scale * np.sqrt(gap[defined]))
        cook[defined] = residual[defined]**2 * leverage[defined] / (width * variance * gap[defined]**2)
    notes = []
    if zero_variance:
        notes.append("Internally studentized residuals and Cook's distance are blank because the residual variance is zero.")
    if perfect.any():
        notes.append("Leverage is one: the internally studentized residual, Cook's distance and the PRESS residual are blank.")
    if rank < width:
        notes.append("Model rank is below the number of design columns.")
    press_sum = float(press @ press) if np.isfinite(press).all() else np.nan
    if not np.isfinite(press).all() and not perfect.any():
        notes.append("PRESS is blank because a PRESS residual is not finite.")
    rows = pd.DataFrame({
        "Source row": np.asarray(index),
        "Observed": observed,
        "Fitted": fitted,
        "Residual": residual,
        "Leverage": leverage,
        "Internally studentized residual": student,
        "Cook's distance": cook,
        "PRESS residual": press,
    })
    shown_variance = variance if not zero_variance else (0.0 if df > 0 and sse == 0 else np.nan)
    summary = pd.DataFrame({"Value": pd.Series({
        "N": n, "Model rank": rank, "Residual df": df, "Residual SS": sse,
        "Residual variance": shown_variance, "PRESS": press_sum,
    }, dtype=object)})
    if notes:
        summary["Note"] = " ".join(notes)
    return rows, summary


def _reason(*parts):
    return " ".join(part for part in parts if part)


def _assumption_row(test, statistic, p, alpha, decision, reason):
    return {"Test": test, "Statistic": statistic, "p": p, "Alpha": alpha, "Decision": decision, "Reason": reason}


def _missing(test, alpha, reason):
    return _assumption_row(test, np.nan, np.nan, alpha, "NA", reason)


def _decision(p, alpha):
    if not np.isfinite(p):
        return "NA"
    return "Reject" if p < alpha else "Do not reject"


def _spearman_row(residual, fitted, alpha):
    if _flat(fitted):
        return _missing(SPEARMAN, alpha, "Fitted values are constant relative to their scale, so the Spearman correlation is undefined.")
    try:
        result = stats.spearmanr(np.abs(residual), fitted)
        statistic, p = float(result.statistic), float(result.pvalue)
    except (ArithmeticError, ValueError):
        statistic, p = np.nan, np.nan
    if not (np.isfinite(statistic) and np.isfinite(p)):
        return _missing(SPEARMAN, alpha, "The Spearman correlation is not finite for these residuals.")
    return _assumption_row(SPEARMAN, statistic, p, alpha, _decision(p, alpha), _reason(SPEARMAN_NOTE, CAVEAT))


def _normality_row(test, residual, alpha):
    n = len(residual)
    low, high = DOMAINS[test]
    if n < low:
        return _missing(test, alpha, f"{test} needs at least {low} residuals.")
    if high is not None and n > high:
        return _missing(test, alpha, f"{test} is limited to {low} to {high} residuals.")
    if n > 0 and np.min(residual) == np.max(residual):
        return _missing(test, alpha, "All residuals are identical, so the variance is zero.")
    computed = _compute(test, residual)
    if computed is None:
        return _missing(test, alpha, "The residuals are too extreme for a finite result.")
    statistic, p, rescaled = computed
    note = _method_note(test, n, p)
    if rescaled:
        note = _reason(note, "Values were rescaled before testing to avoid overflow or underflow.")
    return _assumption_row(test, statistic, p, alpha, _decision(p, alpha), _reason(note, CAVEAT))


def assumption_table(residual, fitted, alpha, tests=ALL_TESTS):
    """Requested tests in contract order. One undefined test does not remove the others."""
    residual = np.asarray(residual, dtype=float)
    fitted = np.asarray(fitted, dtype=float)
    rows = []
    if tests != NORMALITY_TESTS:
        rows.append(_spearman_row(residual, fitted, alpha))
    if tests != VARIANCE_TEST:
        rows.extend(_normality_row(test, residual, alpha) for test in TESTS[1:])
    return pd.DataFrame(rows)


def qq_coordinates(index, residual):
    """Stable order by residual. Equal residuals keep the source-row order already in ``index``."""
    residual = np.asarray(residual, dtype=float)
    order = np.argsort(residual, kind="stable")
    n = len(residual)
    position = (np.arange(1, n + 1) - 0.375) / (n + 0.25)
    return pd.DataFrame({
        "Source row": np.asarray(index)[order],
        "Residual": residual[order],
        "Theoretical quantile": stats.norm.ppf(position),
        "Plotting position": position,
    })


def _figure(graph, fitted, residual, theoretical=None, line=False):
    if graph == GRAPH_HOMO:
        figure, axes = _plot(graph, "Fitted", "|Residual| (raw response units)")
        axes.scatter(fitted, np.abs(residual), label="Observations")
        return figure
    if graph == GRAPH_QQ:
        figure, axes = _plot(graph, "Theoretical normal quantile", "Residual (raw response units)")
        axes.scatter(theoretical, residual, label="Observations")
        mean = float(np.mean(residual))
        deviation = float(np.std(residual, ddof=1)) if len(residual) > 1 else np.nan
        if line and np.isfinite(mean) and np.isfinite(deviation) and deviation > 0:
            axes.axline((0, mean), slope=deviation, color="#bc4040", linewidth=1.5, zorder=2,
                        label="Mean + SD (N−1) × theoretical quantile")
            axes.legend(loc="upper left", frameon=False)
        return figure
    figure, axes = _plot(graph, "Fitted", "Residual")
    axes.scatter(fitted, residual, label="Observations")
    axes.axhline(0, color="#667085", linewidth=1, zorder=1)
    return figure


def linked_plot(frame, options):
    """Plot an existing multifactor ANOVA diagnostic table without fitting a second model."""
    graph = graph_choice(options)
    if graph == GRAPH_NONE or not set(_COLUMNS).issubset(frame) or frame.empty:
        raise FieldError(GRAPH, "Select a diagnostic graph and its ANOVA residual table.")
    ensure_graph_budget(len(frame), graph)
    fitted = frame["Fitted"].to_numpy(dtype=float)
    residual = frame["Residual"].to_numpy(dtype=float)
    if graph == GRAPH_QQ:
        coordinates = qq_coordinates(frame["Source row"], residual)
        plot = _figure(graph, fitted, coordinates["Residual"], coordinates["Theoretical quantile"], True)
    else:
        plot = _figure(graph, fitted, residual)
    return Result({}, plot)


def build(options, index, observed, design, beta, sse, df):
    """Sheets and the optional figure for a fit the ANOVA has already accepted."""
    diagnostics, assumptions, alpha, graph, line = validate(options)
    observed = np.asarray(observed, dtype=float)
    ensure_graph_budget(len(observed), graph)
    design = np.asarray(design, dtype=float)
    beta = np.asarray(beta, dtype=float).reshape(-1)
    fitted = design @ beta
    residual = observed - fitted
    tables = {}
    if diagnostics:
        # p in Cook's distance is the column count of this full-rank design.
        rows, summary = observation_diagnostics(index, observed, design, beta, sse, df)
        tables[SHEET] = rows.loc[:, list(_COLUMNS)]
        tables[SUMMARY] = summary.loc[list(_SUMMARY_ROWS)]
    if assumptions:
        tables[ASSUMPTION_SHEET] = assumption_table(residual, fitted, alpha, options.get(TEST_SET, ALL_TESTS))
    figure = None
    if graph == GRAPH_QQ:
        coordinates = qq_coordinates(index, residual)
        tables[QQ_SHEET] = coordinates
        figure = _figure(graph, fitted, coordinates["Residual"].to_numpy(),
                         coordinates["Theoretical quantile"].to_numpy(), line)
    elif graph != GRAPH_NONE:
        figure = _figure(graph, fitted, residual)
    return tables, figure
