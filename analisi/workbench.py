"""Connect analysis options to result sheets and graphs."""
from functools import partial
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats

from . import stats as engine
from .advanced import anova_comparisons, kmeans_scan
from .anova_diagnostics import OPTIONS as ANOVA_DIAG_OPTIONS
from .anova_diagnostics import active as anova_diagnostics_active, build as build_anova_diagnostics
from .anova_diagnostics import ensure_graph_budget as ensure_anova_graph_budget, graph_choice as anova_graph_choice
from .anova_diagnostics import validate as validate_anova_diagnostics
from .anova_terms import (CHOICES as TERM_CHOICES, MODEL_TERMS, SHEET as MODEL_TERMS_SHEET, TERM_LIST, TERM_SELECTION,
                          active_factors as anova_active_factors, check_comparison_controls as check_anova_comparisons,
                          selection as anova_term_selection, terms_table as anova_terms_table)
from .additional import EXTRA_METHODS, extra_analysis
from .category_graphs import (COLUMN_GRAPH, COLUMN_STYLES, GROUPED_GRAPH, GROUPED_OPTIONS, OPTIONS as CATEGORY_OPTIONS,
                              category_graph)
from .bubble import BUBBLE, OPTIONS as BUBBLE_OPTIONS, bubble_plot
from .compare_lines import COMPARE_LINES, OPTIONS as COMPARE_LINES_OPTIONS, compare_lines
from .contingency import CONTINGENCY, CONTINGENCY_OPTIONS, contingency
from .distribution_graphs import BOX_VIOLIN, OPTIONS as BOX_VIOLIN_OPTIONS, box_violin
from .correlation_details import (COMPARE_INDEPENDENT, CONTROL_OPTIONS, CORRELATE_CONTROL, INDEPENDENT_OPTIONS,
                                  SINGLE_EXTRA, control_result, correlation_result, independent_result)
from .correlation_matrix import CORRELATION_MATRIX, OPTIONS as CORRELATION_MATRIX_OPTIONS, correlation_matrix
from .ellipse_workbench import ELLIPSE_OPTIONS, NONE, SEPARATE_GROUP, draw_confidence_overlays
from .extract_rearrange import (COMPLETE, EXTRACT_FIELDS, EXTRACT_FORMATS, EXTRACT_OPTIONAL_FIELDS, EXTRACT_REARRANGE,
                                OUTPUT, PREFIX, extract_rearrange)
from .fit_quality import OPTIONS as FIT_QUALITY_OPTIONS, check_options as check_fit_options, fit_quality as quality_tables
from .fit_weights import INVERSE_VARIANCE, NONLINEAR_WEIGHTINGS
from .forest_plot import FOREST_PLOT, OPTIONS as FOREST_OPTIONS, forest_plot
from .frequency import FREQUENCY, FREQUENCY_OPTIONS, frequency
from .graph_legend import typed_group_token
from .heatmap import HEAT_MAP, OPTIONS as HEAT_MAP_OPTIONS, heat_map
from .reference_normalization import (METHOD as REFERENCE_NORMALIZATION, OPTIONS as REFERENCE_NORMALIZATION_OPTIONS,
                                      normalize_to_references)
from .hierarchical_workbench import HIERARCHICAL_OPTIONS, hierarchical_result
from .inference import CHI_SQUARE_P, DUNN_OPTIONS, KRUSKAL_P, KRUSKAL_P_METHODS, dunn_comparisons, kruskal_wallis
from .linear_diagnostics import LINEAR_OPTIONS, linear_result
from .equivalence_workbench import EQUIVALENCE, OPTIONS as EQUIVALENCE_OPTIONS, equivalence_test
from .lognormal_tests import LOGNORMAL, OPTIONS as LOGNORMAL_OPTIONS, lognormal_test
from .variance_ratio import METHOD as VARIANCE_RATIO, SHOW as VARIANCE_SHOW, analysis as variance_ratio_analysis, attach_ttest
from .summary_anova import METHOD as SUMMARY_ANOVA, OPTIONS as SUMMARY_ANOVA_OPTIONS, summary_anova
from .summary_ttest import METHOD as SUMMARY_TTEST, OPTIONS as SUMMARY_TTEST_OPTIONS, summary_ttest
from .model_selection import COMPARE_MODELS, OPTIONS as COMPARE_MODELS_OPTIONS, model_selection
from .nonlinear_bands import OPTIONS as BAND_OPTIONS, band_outputs, band_settings
from .monte_carlo import MONTE_CARLO, OPTIONS as MONTE_CARLO_OPTIONS, monte_carlo
from .custom_fit import CUSTOM_EQUATION, custom_fit
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION, global_custom_fit
from .plot_function import PLOT_FUNCTION
from .robust_curve import OPTIONS as ROBUST_CURVE_OPTIONS, ROBUST_CURVE, robust_curve
from .transpose_xy import OPTIONS as TRANSPOSE_OPTIONS, TRANSPOSE_XY, transpose_xy
from .paired_graphs import (BEFORE_AFTER, BEFORE_AFTER_OPTIONS, TRAJECTORIES, TRAJECTORY_OPTIONS, before_after,
                            subject_trajectories)
from .spline_fit import SPLINE_FIT
from .outlier_screening import OPTIONS as OUTLIER_OPTIONS, OUTLIERS, identify_outliers
from .parameter_intervals import (OPTIONS as PARAMETER_CI_OPTIONS, settings as parameter_ci_settings,
                                  parameter_outputs, ProfileBudget)
from .normality import NORMALITY, OPTIONS as NORMALITY_OPTIONS, is_legacy as legacy_normality, normality
from .nested import METHODS as NESTED_METHODS, NESTED_ANOVA, NESTED_T, nested_analysis
from .select_transform import SELECT_OPTIONS, SELECT_TRANSFORM, select_transform
from .parts_of_whole import GOODNESS_OF_FIT, GOODNESS_OPTIONS, PARTS_GRAPH, PARTS_OPTIONS, goodness_of_fit, parts_graph
from .reporting import Result, _plot, _report
from .xy_series import XY_METHOD, xy_series
from .processing import FieldError
from .rank_tests import MANN_WHITNEY, OPTIONS as RANK_OPTIONS, WILCOXON, is_legacy as legacy_rank_test, rank_test
from .row_tests import ROW_TESTS, OPTIONS as ROW_TEST_OPTIONS, row_tests
from .survival_input import CENSOR_CODE, EVENT_CODE, OTHER_STATUS, STATUS_POLICIES, recode_statuses
from .survival_plot import (ERROR_BARS, GRAPH_OPTIONS as SURVIVAL_GRAPH_OPTIONS, GREENWOOD, INTERVAL, UNCERTAINTY,
                            display_curve, format_ordinate, ordinate_label, survival_graph_settings)
from .prism_restore import (MAX_LAYOUT_PANEL_DATA, PRISM_GRAPH_STYLE, PRISM_LAYOUT_PANELS, PRISM_PREVIEW,
                            PRISM_RESULT_SHEET, PRISM_TITLE, SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT,
                            SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, SAVED_XY)

GEOMETRIC_MEAN = "Geometric mean and 95% CI"
ANOVA_EFFECTS, ANOVA_ALPHA, ANOVA_MODEL_FIT = "Effect sizes", "Alpha", "Model fit"
OPTIONAL = "Optional"
MULTIPLE = "Multiple"
OPTIONAL_MULTIPLE = "Multiple (optional)"
TEXT = "Text"

# Survival options whose choices are the group names found in the data.
GROUP_ORDER = "Group order"
GROUP_CHOICE = "Group choice"
MEDIAN_METHODS = ("First time with S ≤ 0.5", "Midpoint of recorded 50% plateau")

CLASSIC_RESPONSES = {"Nonlinear regression": ("Y columns", "Y"), "Kaplan–Meier survival": ("Event columns", "Event")}


def classic_roles(method, options):
    """Translate recipes made before multiple responses and groupings were available."""
    columns, legacy = CLASSIC_RESPONSES[method]
    return {
        columns: options.get(columns, [options[legacy]] if options.get(legacy) else []),
        "Grouping variables": options.get("Grouping variables", [options["Group"]] if options.get("Group") else []),
    }


def _combined_groups(frame, predictor, responses, groups, *, numbered=True):
    """Return the frame and the column holding the effective group of each row.

    One grouping variable with one response uses the raw values. Otherwise rows
    receive labels naming each observed combination.
    """
    group = groups[0] if groups else None
    if groups and (len(groups) > 1 or len(responses) > 1):
        group = "Grouping combination"
        while group in frame:
            group += " (groups)"
        retain = frame[predictor].notna() & frame[responses].notna().any(axis=1)
        factors = frame.loc[retain, groups].dropna()
        patterns = factors.drop_duplicates()
        if len(patterns) > 32:
            raise ValueError("Select grouping variables with up to 32 observed combinations.")
        names = {
            values: (f"{index} · " if numbered else "") + ", ".join(
                f"{key}={value!r}" for key, value in zip(groups, values, strict=True))
            for index, values in enumerate(patterns.itertuples(index=False, name=None), 1)
        }
        labels = [names.get(values) for values in frame.loc[:, groups].itertuples(index=False, name=None)]
        frame = frame.assign(**{group: labels})
    return frame, group


def _survival_levels(frame, time, responses, groups):
    if not groups or not responses or time not in frame or any(c not in frame for c in (*responses, *groups)):
        return []
    frame, group = _combined_groups(frame, time, responses, groups, numbered=False)
    numeric = frame[[time, *responses]].apply(pd.to_numeric, errors="coerce")
    keep = numeric[time].notna() & numeric[responses].notna().any(axis=1) & frame[group].notna()
    return [str(label) for label in pd.unique(frame.loc[keep, group])]


def survival_levels(frame, options):
    """Preview effective groups using the same status mapping as the analysis."""
    roles = classic_roles("Kaplan–Meier survival", options)
    responses = roles["Event columns"]
    groups = roles["Grouping variables"]
    if not groups or any(column not in frame for column in responses):
        return []
    coded = recode_statuses(frame, responses, options)
    return _survival_levels(coded, options.get("Time"), responses, groups)


def check_survival_options(frame, options):
    """Normalize statuses and validate the saved orientation of comparisons."""
    roles = classic_roles("Kaplan–Meier survival", options)
    responses = roles["Event columns"]
    if any(column not in frame for column in responses):
        raise FieldError("Event columns", "Choose existing status columns.")
    coded = recode_statuses(frame, responses, options)
    wants_trend, wants_hazard = options.get("Log-rank trend"), options.get("Hazard ratio")
    if not (wants_trend or wants_hazard):
        return coded
    levels = _survival_levels(coded, options.get("Time"), responses, roles["Grouping variables"])
    if len(levels) != len(set(levels)):
        raise ValueError("Group names must stay distinct when written as text.")
    if wants_trend:
        order = options.get("Trend group order")
        if len(levels) < 3:
            raise FieldError("Log-rank trend", "Log-rank trend needs at least three groups.")
        if not isinstance(order, (list, tuple)) or not all(isinstance(name, str) for name in order):
            raise FieldError("Trend group order", "Trend group order: list every group once, from lowest to highest score.")
        if len(set(order)) != len(order):
            raise FieldError("Trend group order", "Trend group order: a group appears more than once.")
        missing = [name for name in levels if name not in order]
        unknown = [name for name in order if name not in levels]
        if missing or unknown:
            detail = ([f"missing {', '.join(missing)}"] if missing else []) + (
                [f"unknown {', '.join(unknown)}"] if unknown else [])
            raise FieldError("Trend group order", "Trend group order: list every group once (" + "; ".join(detail) + ").")
    numerator = options.get("Hazard ratio numerator")
    if wants_hazard and numerator and str(numerator) not in levels:
        raise FieldError("Hazard ratio numerator", f"Hazard ratio numerator: {numerator} is not a group in this analysis.")
    return coded


# Fields are column roles, options, or typed defaults.
METHODS = {
    "Descriptive statistics": {"Variables": MULTIPLE, GEOMETRIC_MEAN: False},
    NORMALITY: NORMALITY_OPTIONS,
    "t-test": {"Design": ("Welch", "Student", "Paired", "One-sample"),
               "Response": None, "Group": OPTIONAL, "Subject": OPTIONAL, "Null mean": 0.0,
               VARIANCE_SHOW: False},
    "Paired t-test (columns)": {"First": None, "Second": None},
    LOGNORMAL: LOGNORMAL_OPTIONS,
    VARIANCE_RATIO: {"First": None, "Second": None, "Confidence level (%)": 95.0,
                     "Distribution": ("Normal", "Lognormal"),
                     "Graph": ("None", "Variance ratio", "SD ratio")},
    EQUIVALENCE: EQUIVALENCE_OPTIONS,
    SUMMARY_ANOVA: SUMMARY_ANOVA_OPTIONS,
    SUMMARY_TTEST: SUMMARY_TTEST_OPTIONS,
    MANN_WHITNEY: RANK_OPTIONS[MANN_WHITNEY],
    WILCOXON: RANK_OPTIONS[WILCOXON],
    "Kruskal–Wallis": {"Response": None, "Group": None, KRUSKAL_P: KRUSKAL_P_METHODS, **DUNN_OPTIONS},
    "Correlation": {"X": None, "Y": None, "Method": ("Pearson", "Spearman", "Kendall"), **SINGLE_EXTRA},
    CORRELATE_CONTROL: CONTROL_OPTIONS,
    COMPARE_INDEPENDENT: INDEPENDENT_OPTIONS,
    CORRELATION_MATRIX: {"Variables": MULTIPLE, **CORRELATION_MATRIX_OPTIONS},
    ROW_TESTS: ROW_TEST_OPTIONS,
    **NESTED_METHODS,
    CONTINGENCY: CONTINGENCY_OPTIONS,
    PARTS_GRAPH: PARTS_OPTIONS,
    GOODNESS_OF_FIT: GOODNESS_OPTIONS,
    "Linear regression": {"X": None, "Y": None, **LINEAR_OPTIONS},
    COMPARE_LINES: COMPARE_LINES_OPTIONS,
    "Nonlinear regression": {"X": None, "Y columns": MULTIPLE, "Grouping variables": OPTIONAL_MULTIPLE,
                             "Model": tuple(name for name, spec in engine.MODELS.items()
                                            if not (spec.required_fixed or spec.required_shared)),
                             "Weighting": NONLINEAR_WEIGHTINGS, "SD column": OPTIONAL,
                             **BAND_OPTIONS, **FIT_QUALITY_OPTIONS, **PARAMETER_CI_OPTIONS},
    "Compare nonlinear models": {"X": None, "Y": None, "Group": OPTIONAL,
                                 "Nested models": tuple(f"{a} → {b}" for a, b in engine.NESTED_MODELS),
                                 "Weighting": engine.FIT_WEIGHTINGS, "SD column": OPTIONAL},
    COMPARE_MODELS: COMPARE_MODELS_OPTIONS,
    ROBUST_CURVE: ROBUST_CURVE_OPTIONS,
    "Multifactor ANOVA": {"Response": None, "Factors": MULTIPLE, TERM_SELECTION: TERM_CHOICES, "Interaction order": 1,
                         MODEL_TERMS: TERM_LIST,
                         "Compare marginal means by": OPTIONAL, "Cell comparison factors": OPTIONAL_MULTIPLE,
                         "Within factors (simple effects)": OPTIONAL_MULTIPLE, "Control level(s), separated by |": TEXT,
                         "Families": ("Separate", "Pooled"), "Reverse comparisons": False,
                         "Correction": ("Holm", "Holm–Šídák", "Šídák", "Bonferroni", "Tukey", "Dunnett", "None"),
                         ANOVA_EFFECTS: False, ANOVA_ALPHA: 0.05, **ANOVA_DIAG_OPTIONS},
    "Kaplan–Meier survival": {"Time": None, "Event columns": MULTIPLE, "Grouping variables": OPTIONAL_MULTIPLE,
                              "Pairwise correction": ("None", "Holm", "Bonferroni", "FDR"),
                              "Median method": MEDIAN_METHODS, "Confidence level (%)": 95.0,
                              "Gehan–Breslow–Wilcoxon": False, "Log-rank trend": False,
                              "Trend group order": GROUP_ORDER, "Hazard ratio": False,
                              "Hazard ratio numerator": GROUP_CHOICE, EVENT_CODE: TEXT, CENSOR_CODE: TEXT,
                              OTHER_STATUS: STATUS_POLICIES, **SURVIVAL_GRAPH_OPTIONS},
    "K-means model selection": {"Variables": MULTIPLE, "Minimum k": 1, "Maximum k": 8,
                                "Standardize": True, "Seed": 42,
                                "Criterion": ("Silhouette", "Elbow", "Calinski–Harabasz", "Davies–Bouldin", "Gap",
                                              "Consensus (17 indices)"),
                                "Gap simulations": 20},
    "K-means clustering": {"Variables": MULTIPLE, "Clusters": 2, "Standardize": True, "Seed": 42},
    "Hierarchical clustering": {"Variables": MULTIPLE, "Observation labels": OPTIONAL, **HIERARCHICAL_OPTIONS},
    "Scatter / confidence ellipse": {"X": None, "Y": None, "Group": OPTIONAL, **ELLIPSE_OPTIONS},
    COLUMN_GRAPH: {"Variables": MULTIPLE, "Graph style": COLUMN_STYLES, **CATEGORY_OPTIONS},
    HEAT_MAP: HEAT_MAP_OPTIONS,
    GROUPED_GRAPH: {"Variables": MULTIPLE, "Row titles": OPTIONAL, **GROUPED_OPTIONS},
    "XY error bars": {
        "X": None, "Y": None, "X error distance": OPTIONAL,
        "X lower error": OPTIONAL, "X upper error": OPTIONAL,
        "X error values": ("Distances", "Endpoints"),
        "X error direction": ("Both", "Negative only", "Positive only"),
        "Y lower error": OPTIONAL, "Y upper error": OPTIONAL,
        "Y error values": ("Distances", "Endpoints"),
        "Y error direction": ("Both", "Negative only", "Positive only"),
        "Group": OPTIONAL,
        "Error cap size": 4.0, "Error width": TEXT, "Error color": TEXT,
        "Error line style": ("solid", "dashed", "dotted", "dash-dot"),
    },
    XY_METHOD: {"X": None, "Y columns": MULTIPLE},
    "Histogram": {"Response": None, "Bins": 10},
    FREQUENCY: FREQUENCY_OPTIONS,
    BOX_VIOLIN: BOX_VIOLIN_OPTIONS,
    BUBBLE: BUBBLE_OPTIONS,
    BEFORE_AFTER: BEFORE_AFTER_OPTIONS,
    TRAJECTORIES: TRAJECTORY_OPTIONS,
    FOREST_PLOT: FOREST_OPTIONS,
    OUTLIERS: OUTLIER_OPTIONS,
    MONTE_CARLO: MONTE_CARLO_OPTIONS,
    SELECT_TRANSFORM: SELECT_OPTIONS,
    TRANSPOSE_XY: TRANSPOSE_OPTIONS,
    EXTRACT_REARRANGE: {OUTPUT: EXTRACT_FORMATS, PREFIX: False, COMPLETE: True, **{
        field: OPTIONAL if field in EXTRACT_OPTIONAL_FIELDS else None
        for field in dict.fromkeys(field for fields in EXTRACT_FIELDS.values() for field in fields)
    }},
    REFERENCE_NORMALIZATION: REFERENCE_NORMALIZATION_OPTIONS,
    **EXTRA_METHODS,
}

GROUPS = {
    "Data Processing": ("Transform", "Transform concentrations (X)", "Normalize", REFERENCE_NORMALIZATION, "Prune rows",
                        "Remove baseline and column math", "Fraction of total", EXTRACT_REARRANGE, SELECT_TRANSFORM,
                        "Reshape replicates", TRANSPOSE_XY,
                        "Outlier test (Grubbs)", OUTLIERS),
    "Data Exploration and Summary": ("Descriptive statistics", "Row statistics", NORMALITY,
                                    "Correlation", CORRELATE_CONTROL, COMPARE_INDEPENDENT, CORRELATION_MATRIX,
                                    "Histogram", FREQUENCY, GOODNESS_OF_FIT,
                                    "Area under curve", "Principal component analysis",
                                    "Adjust a stack of p values", "Control false discoveries",
                                    "Smooth / differentiate / integrate"),
    "Regression and Curves": ("Linear regression", COMPARE_LINES, "Deming regression", "Multiple regression",
                              "Nonlinear regression", "Global nonlinear regression", "Compare nonlinear models",
                              COMPARE_MODELS, ROBUST_CURVE, CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION,
                              "Interpolate a standard curve", SPLINE_FIT, PLOT_FUNCTION),
    "Group Comparison": ("t-test", "Paired t-test (columns)", LOGNORMAL, VARIANCE_RATIO, EQUIVALENCE, SUMMARY_TTEST, "Multiple t-tests", ROW_TESTS, "Mann–Whitney", "Wilcoxon signed-rank",
                         "Kolmogorov–Smirnov", "Kruskal–Wallis", "Friedman", "One-way ANOVA", SUMMARY_ANOVA,
                         NESTED_T, NESTED_ANOVA, "Repeated measures ANOVA", "Mixed-effects model (REML)",
                         "Multifactor ANOVA", "Contingency table",
                         "Bland–Altman", "ROC curve", "Compare paired ROC curves"),
    "Survival Analysis": ("Kaplan–Meier survival", "Cox regression"),
    "Clustering": ("K-means clustering", "K-means model selection", "Hierarchical clustering"),
    "Graphing": ("Scatter / confidence ellipse", "XY error bars", XY_METHOD, COLUMN_GRAPH, GROUPED_GRAPH, HEAT_MAP,
                 PARTS_GRAPH, "Box / violin plot", BUBBLE, BEFORE_AFTER, TRAJECTORIES, FOREST_PLOT),
    "Study Design and Simulation": ("Power and sample size", "Simulate data", MONTE_CARLO),
}

# These analyses create a graph when calculated. Keep their Graphs entry
# available while a reopened project's results are still unloaded.
GRAPH_METHODS = frozenset({
    *GROUPS["Graphing"], PLOT_FUNCTION, "Area under curve", "Bland–Altman", "Correlation", CORRELATE_CONTROL,
    COMPARE_INDEPENDENT, CORRELATION_MATRIX, "Deming regression",
    "Global nonlinear regression", "Hierarchical clustering", "Histogram", FREQUENCY, "Interpolate a standard curve",
    "K-means clustering", "K-means model selection", "Kaplan–Meier survival", "Linear regression", COMPARE_LINES,
    "Mixed-effects model (REML)", LOGNORMAL, EQUIVALENCE, "Multiple t-tests", ROW_TESTS, "Nonlinear regression", ROBUST_CURVE, CUSTOM_EQUATION,
    GLOBAL_CUSTOM_EQUATION, "Principal component analysis",
    "ROC curve", "Compare paired ROC curves", "Smooth / differentiate / integrate", SPLINE_FIT, *NESTED_METHODS,
    REFERENCE_NORMALIZATION, SUMMARY_ANOVA, SUMMARY_TTEST,
})


def _normality(frame, o):
    rows = []
    for col in o["Variables"]:
        data = engine.complete(frame, [col])[col]
        if not 3 <= len(data) <= 5000 or data.nunique() < 2:
            raise ValueError("Shapiro–Wilk requires 3 to 5000 values and positive variance.")
        result = stats.shapiro(data)
        rows.append({"Variable": col, "N": len(data), "Shapiro–Wilk W": result.statistic, "p": result.pvalue})
    return Result({"Normality": pd.DataFrame(rows).set_index("Variable")})


def _nonparametric(method, frame, o):
    if method == "Wilcoxon signed-rank":
        a, b = o["First"], o["Second"]
        data = engine.complete(frame, [a, b])
        if not len(data) or (data[a] == data[b]).all():
            raise ValueError("Wilcoxon needs at least one nonzero paired difference.")
        test = stats.wilcoxon(data[a], data[b])
    else:
        y, group = o["Response"], o["Group"]
        data = engine.complete(frame, [y], [group])
        groups = {label: part[y].to_numpy() for label, part in data.groupby(group, sort=False, observed=True)}
        if len(groups) < 2 or (method == "Mann–Whitney" and len(groups) != 2):
            raise ValueError("Mann–Whitney needs exactly two groups. Kruskal–Wallis needs at least two.")
        if method == "Kruskal–Wallis":
            samples = list(groups.values())
            report = kruskal_wallis(samples, o.get(KRUSKAL_P, CHI_SQUARE_P))
            return Result({method: _report(report), **dunn_comparisons(list(groups), samples, o)})
        test = stats.mannwhitneyu(*groups.values())
    return Result({method: _report({"Statistic": test.statistic, "p": test.pvalue, "N": len(data)})})


def anova_visibility(effect_sizes):
    """Alpha applies only to the Significant column of the effect sizes."""
    return {ANOVA_ALPHA: bool(effect_sizes)}


def check_anova_options(options):
    """Validate the effect-size fields. Raises FieldError naming the field. Returns alpha or None when off."""
    if not options.get(ANOVA_EFFECTS, False):
        return None
    alpha = options.get(ANOVA_ALPHA, 0.05)
    if isinstance(alpha, (bool, np.bool_)) or not isinstance(alpha, (int, float, np.integer, np.floating)):
        raise FieldError(ANOVA_ALPHA, "Alpha must be a number between 0 and 1.")
    if not np.isfinite(alpha) or not 0 < alpha < 1:
        raise FieldError(ANOVA_ALPHA, "Alpha must be a finite number greater than 0 and less than 1.")
    return float(alpha)


def _anova_row_count(frame, response, factors):
    """Complete rows, or None when the columns are not yet a valid ANOVA selection."""
    try:
        return len(engine.complete(frame, [response], factors))
    except (ValueError, KeyError):
        return None


def _anova(frame, o):
    y, factors = o["Response"], o["Factors"]
    # Selected terms (0.83): None means Full hierarchy, whose Interaction order and Patsy fit are unchanged.
    terms = anova_term_selection(o)
    order = o.get("Interaction order", 1) if terms is not None else o["Interaction order"]
    alpha = check_anova_options(o)
    # Field errors name the diagnostic control. The full fit still happens once, on this call.
    validate_anova_diagnostics(o)
    if terms is not None:
        check_anova_comparisons(o, factors, terms)
    graph = anova_graph_choice(o)
    if graph != "None":
        count = _anova_row_count(frame, y, anova_active_factors(factors, terms) if terms is not None else factors)
        if count is not None:
            ensure_anova_graph_budget(count, graph)
    table, fit, data, design, beta, error, df = engine._factorial_anova_components(
        frame, y, factors, order, terms=terms)
    tables = {"ANOVA (type III)": table}
    if terms is not None:
        tables[MODEL_TERMS_SHEET] = anova_terms_table(terms, anova_active_factors(factors, terms), data)
    if alpha is not None:
        tables[ANOVA_EFFECTS], tables[ANOVA_MODEL_FIT] = engine.anova_effect_sizes(table, fit, alpha)
    compare = o.get("Cell comparison factors") or o.get("Compare marginal means by")
    within = o.get("Within factors (simple effects)") or []
    control = o.get("Control level(s), separated by |", "").strip()
    if compare:
        correction = {"Holm": "holm", "Holm–Šídák": "holm-sidak", "Šídák": "sidak",
                      "Bonferroni": "bonferroni", "Tukey": "tukey", "Dunnett": "dunnett",
                      "None": "none"}[o.get("Correction", "Holm")]
        if isinstance(compare, list) and len(compare) > 1 and control:
            control = tuple(item.strip() for item in control.split("|"))
        tables["Multiple comparisons"] = anova_comparisons(
            frame, y, factors, order, compare, within=within,
            method=correction, family=o.get("Families", "Separate").lower(), control=control or None,
            reverse=o.get("Reverse comparisons", False), terms=terms)
    elif within or control:
        raise ValueError("Choose which factor or cells to compare.")
    figure = None
    if anova_diagnostics_active(o):
        extra, figure = build_anova_diagnostics(
            o, data.index, data["response"].to_numpy(), design.to_numpy(), beta, error, df)
        tables.update(extra)
    return Result(tables, figure)


def _scatter(frame, o):
    x, y, group = o["X"], o["Y"], o.get("Group")
    data = engine.complete(frame, [x, y], [group] if group else ())
    if data.empty:
        raise ValueError("No complete XY pairs.")
    figure, axes = _plot("Scatter plot", x, y)
    groups = data.groupby(group, sort=False, observed=True) if group else [("All", data)]
    separate_overlay = o.get("Ellipse", NONE) != NONE and o.get("Ellipse grouping") == SEPARATE_GROUP
    point_colors = {}
    for label, part in groups:
        legend_label = str(label) if group or not separate_overlay else "_nolegend_"
        dots = axes.scatter(part[x], part[y], label=legend_label)
        if group:
            dots._tramastat_legend_key = f"group:{typed_group_token(label)}"
        point_colors[label] = dots.get_facecolor()[0]
    overlays = draw_confidence_overlays(axes, frame, o, point_colors)
    if group or separate_overlay:
        axes.legend()
    tables = {"Observations": data}
    if not overlays.empty:
        tables["Confidence overlays"] = overlays
    return Result(tables, figure)


def _xy_errors(frame, o):
    from .xy_errors import xy_errors

    return xy_errors(frame, o)


def _distribution(method, frame, o):
    y, group = o["Response"], o.get("Group")
    data = engine.complete(frame, [y], [group] if group else [])
    if not len(data):
        raise ValueError("No complete observations.")
    if method == "Histogram":
        if not 1 <= o["Bins"] <= 500:
            raise ValueError("Choose 1 to 500 bins.")
        figure, axes = _plot(method, y, "Count")
        counts, edges, _ = axes.hist(data[y], bins=o["Bins"], color="#2866ae", edgecolor="white")
        return Result({"Bins": pd.DataFrame({"Lower edge": edges[:-1], "Upper edge": edges[1:],
                                             "Count": counts.astype(int)})}, figure)
    figure, axes = _plot(o["Style"] + " plot", group or "", y)
    groups = list(data.groupby(group, sort=False)) if group else [("All", data)]
    if len(groups) > 40:
        raise ValueError("Plot up to 40 groups at once.")
    values = [part[y].to_numpy() for _, part in groups]
    if o["Style"] == "Box":
        axes.boxplot(values)
    else:
        if any(len(part) < 2 or np.ptp(part) == 0 for part in values):
            raise ValueError("A violin plot requires at least two distinct values per group.")
        axes.violinplot(values, showmedians=True)
    axes.set_xticks(range(1, len(groups) + 1), [str(label) for label, _ in groups], rotation=20)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)
    return Result({"Group summary": pd.DataFrame({"Group": [label for label, _ in groups],
                                                  "N": [len(v) for v in values],
                                                  "Median": [np.median(v) for v in values]})}, figure)


def _kmeans(frame, o):
    variables = o["Variables"]
    fit = engine.kmeans(frame, variables, o["Clusters"], o["Standardize"], o["Seed"])
    figure, axes = _plot("K-means", variables[0], variables[1] if len(variables) > 1 else "Cluster")
    for label in sorted(fit.labels.unique()):
        subset = fit.data[fit.labels == label]
        y = subset[variables[1]] if len(variables) > 1 else [label] * len(subset)
        axes.scatter(subset[variables[0]], y, label=f"Cluster {label}")
    if o["Clusters"] <= 12:
        axes.legend()
    tables = {"Assignments": fit.data.assign(Cluster=fit.labels),
              "Centers (fitting scale)": fit.centers.set_axis(range(1, len(fit.centers) + 1)),
              "Fit": _report({"Within-cluster SS": fit.inertia, "N": len(fit.data)})}
    return Result(tables, figure)


def _consensus_selection(scan, o):
    selection = scan.selection
    counts = selection["counts"]
    figure, axes = _plot("K-means consensus votes", "Number of clusters", "Votes")
    if len(counts):
        axes.bar(counts.index, counts.to_numpy(), color="#4c78a8", label="Votes")
        axes.set_xticks(counts.index)
    axes.yaxis.get_major_locator().set_params(integer=True)
    axes.set_ylim(0, max(1, int(counts.max()) if len(counts) else 0) + .5)
    if scan.recommended_k is not None:
        axes.axvline(scan.recommended_k, color="#bb5b3a", linestyle="--", label=f"Suggested k = {scan.recommended_k}")
        axes.legend()
    tied = selection["tied"]
    report = {"Criterion": o["Criterion"], "Suggested k": scan.recommended_k,
              "Tied candidates": ", ".join(map(str, tied)) if len(tied) > 1 else "None",
              "Indices voting": selection["voting"], "Indices abstaining": selection["abstaining"]}
    report.update({f"Votes for k = {k}": int(votes) for k, votes in counts.items()})
    tables = {"Cluster metrics": scan.metrics, "Consensus votes": scan.votes, "Selection": _report(report)}
    if scan.fit is not None:
        label = "Cluster"
        suffix = 2
        while label in scan.fit.data:
            label = f"Cluster ({suffix})"
            suffix += 1
        tables["Assignments"] = scan.fit.data.assign(**{label: scan.fit.labels})
    return Result(tables, figure)


def _cluster_selection(frame, o):
    criterion = {"Silhouette": "silhouette", "Elbow": "elbow", "Calinski–Harabasz": "calinski-harabasz",
                 "Davies–Bouldin": "davies-bouldin", "Gap": "gap",
                 "Consensus (17 indices)": "consensus"}[o["Criterion"]]
    scan = kmeans_scan(frame, o["Variables"], o["Maximum k"], o["Standardize"], o["Seed"],
                       criterion, min_k=o.get("Minimum k", 1), gap_replicates=o.get("Gap simulations", 20))
    if criterion == "consensus":
        return _consensus_selection(scan, o)
    metric = {"elbow": "WSS", "gap": "Gap"}.get(criterion, o["Criterion"])
    figure, axes = _plot("K-means model selection", "Number of clusters", metric)
    if criterion == "gap":
        axes.errorbar(scan.metrics.index, scan.metrics[metric], yerr=scan.metrics["Gap SE"], fmt="o-", label=metric)
    else:
        axes.plot(scan.metrics.index, scan.metrics[metric], "o-", label=metric)
    if scan.recommended_k is not None:
        axes.axvline(scan.recommended_k, color="#bb5b3a", linestyle="--", label=f"Suggested k = {scan.recommended_k}")
        axes.legend()
    tables = {"Model metrics": scan.metrics,
              "Selection": _report({"Criterion": o["Criterion"], "Suggested k": scan.recommended_k})}
    if scan.fit is not None:
        tables["Assignments"] = scan.fit.data.assign(Cluster=scan.fit.labels)
    return Result(tables, figure)


def _comparison_sheet(result, labels):
    """Metric/value sheet for a comparison, or the reason it is not available."""
    if not result["available"]:
        return _report({"Status": "Not available", "Reason": result["note"]}).rename_axis("Metric")
    return _report({label: result[key] if not isinstance(result[key], list) else " → ".join(result[key])
                    for label, key in labels}).rename_axis("Metric")


def _has_survival_orientation(options):
    return bool(options.get("Log-rank trend") or options.get("Hazard ratio"))


def _survival_extras(frame, o, time, event, group, level, group_count):
    """Optional Gehan–Breslow–Wilcoxon, ordered-trend and hazard-ratio sheets for one response."""
    gbw, trend, hazard = (bool(o.get(name)) for name in ("Gehan–Breslow–Wilcoxon", "Log-rank trend", "Hazard ratio"))
    if not (gbw or trend or hazard):
        return {}
    if not group or group_count < 2:
        results = {key: {"available": False, "note": "A comparison needs at least two groups."}
                   for key, wanted in (("gbw", gbw), ("trend", trend), ("hazard", hazard)) if wanted}
    else:
        results = engine.survival_comparisons(
            frame, time, event, group, gbw=gbw, trend_order=o.get("Trend group order") if trend else None,
            hazard=hazard, hazard_numerator=o.get("Hazard ratio numerator") or None, level=level)
    outputs = {}
    if "gbw" in results:
        outputs["Gehan–Breslow–Wilcoxon test"] = _comparison_sheet(
            results["gbw"], (("Gehan–Breslow–Wilcoxon χ²", "χ²"), ("df", "df"), ("p", "p")))
    if "trend" in results:
        outputs["Log-rank trend"] = _comparison_sheet(
            results["trend"], (("Group order", "order"), ("z", "z"), ("Trend χ²", "χ²"), ("df", "df"), ("p", "p")))
    if "hazard" in results:
        found = results["hazard"]
        if found["available"]:
            table = pd.DataFrame(found["rows"]).set_index("Method")
            table.insert(0, "Orientation", [f"{row['Numerator']} / {row['Denominator']}" for row in found["rows"]])
        else:
            table = pd.DataFrame({"Status": "Not available", "Note": found["note"]},
                                 index=pd.Index(["Mantel–Haenszel", "Log-rank O/E"], name="Method"))
        outputs["Hazard ratio"] = table
    return outputs


def _survival(frame, o, axes=None, compact=False, risk_axes=None):
    from itertools import combinations
    from .operations import adjust_p

    time, event, group = o["Time"], o["Event"], o.get("Group")
    level = float(o.get("Confidence level (%)", 95.0))
    settings = survival_graph_settings(o)
    show_error = settings[UNCERTAINTY] == ERROR_BARS or settings[INTERVAL] == GREENWOOD
    curves, comparison = engine.survival(frame, time, event, group, level=level, strict=False,
                                         standard_error=show_error)
    ylabel = ordinate_label(settings)
    plateau = o.get("Median method") == MEDIAN_METHODS[1]
    if axes is None and o.get("Show risk table below graph"):
        figure = Figure(figsize=(8, 5.5), dpi=100, layout="constrained")
        panels = figure.add_gridspec(2, 1, height_ratios=[3, 1.2])
        axes = figure.add_subplot(panels[0])
        axes.spines[["right", "top"]].set_visible(False)
        risk_axes = figure.add_subplot(panels[1])
        axes.set(title="Kaplan–Meier survival", xlabel=time, ylabel=ylabel)
    elif axes is None:
        figure, axes = _plot("Kaplan–Meier survival", time, ylabel)
    else:
        figure = axes.figure
        axes.set(title=event, xlabel=time, ylabel=ylabel)
    format_ordinate(axes, settings)
    tables, summaries, risk_rows = {}, [], {}
    maximum = max(curve["Time"].max() for curve in curves.values())
    ticks = np.unique(np.linspace(0, maximum, 6).round(8))
    for label, curve in curves.items():
        median, lower, upper = engine.survival_median(curve, level, plateau)
        summaries.append({"Group": str(label), "N": curve["At risk"].iloc[0],
                          "Events": curve["Events"].sum(), "Censored": curve["Censored"].sum(),
                          "Median survival": median, "Median CI lower": lower, "Median CI upper": upper,
                          "Median CI level (%)": level})
        indices = curve["Time"].to_numpy().searchsorted(ticks)
        risk_rows[str(label)] = np.r_[curve["At risk"].to_numpy(), 0][indices]
        tables[label] = display_curve(axes, label, curve, settings, level)
    if len(curves) > 1:
        axes.legend()
    risks = pd.DataFrame.from_dict(risk_rows, orient="index", columns=ticks).rename_axis("Group")
    if o.get("Show risk table below graph"):
        if len(curves) > 8:
            raise ValueError("The plot can show a risk table for up to eight groups.")
        risk_axes.set_axis_off()
        labels = [label.partition(" · ")[0] if compact and not _has_survival_orientation(o) else label
                  for label in risks.index]
        values = np.column_stack([labels, risks.to_numpy()])
        risk = risk_axes.table(cellText=values, colLabels=["Group", *(f"{tick:g}" for tick in ticks)],
                               cellLoc="center", bbox=[0, 0, 1, 1])
        risk.auto_set_font_size(False)
        risk.set_fontsize(8)
        for (row, column), cell in risk.get_celld().items():
            cell.set_edgecolor("#d3dde7")
            cell.set_linewidth(.6)
            if row == 0 or column == 0:
                cell.set_facecolor("#eaf2fa")
                cell.get_text().set_color("#203b53")
                cell.get_text().set_weight("bold")
            elif row % 2 == 0:
                cell.set_facecolor("#f6f9fc")
    risk_output = risks
    if compact:
        risk_output = risks.reset_index().melt(id_vars="Group", var_name="Time", value_name="At risk").set_index("Group")
    outputs = {"Survival summary": pd.DataFrame(summaries).set_index("Group"), "Number at risk": risk_output}
    if comparison:
        outputs["Log-rank test"] = _report(comparison).rename_axis("Metric")
    elif len(curves) > 1 and sum(curve["Events"].sum() for curve in curves.values()):
        outputs["Log-rank test"] = _report({
            "Status": "Not available",
            "Reason": "The groups do not share enough risk sets with events for this comparison."}).rename_axis("Metric")
    outputs.update(_survival_extras(frame, o, time, event, group, level, len(curves)))
    correction = o.get("Pairwise correction", "None")
    if group and len(curves) > 1 and correction != "None":
        if len(curves) > 12:
            raise ValueError("Pairwise survival tests support up to twelve groups.")
        pairwise = []
        for left, right in combinations(curves, 2):
            _, test = engine.survival(frame[frame[group].isin([left, right])], time, event, group, strict=False)
            pairwise.append({"Comparison": f"{left} / {right}", **(test or {"p": np.nan})})
        pairs = pd.DataFrame(pairwise).set_index("Comparison")
        if pairs["p"].notna().any():
            method = {"Holm": "holm", "Bonferroni": "bonferroni", "FDR": "fdr_bh"}[correction]
            pairs["Adjusted p"] = adjust_p(pairs, "p", method)["Adjusted p"]
        outputs["Pairwise log-rank"] = pairs
    if compact:
        outputs["Survival curves"] = pd.concat({label: table.rename_axis("Time point")
                                                for label, table in tables.items()}, names=["Group"])
    else:
        outputs.update({f"Curve: {label}": table for label, table in tables.items()})
    return Result(outputs, figure)


def _nonlinear(frame, o, axes=None, compact=False, *, parameter_budget=None):
    x, y, model = o["X"], o["Y"], o["Model"]
    # Band fields are checked before any fit; Band=None ignores stale level and drawing.
    band = band_settings(o)
    parameter_config = parameter_ci_settings(o)
    parameter_budget = parameter_budget if parameter_budget is not None else ProfileBudget()
    fits = engine.nonlinear(frame, x, y, model, o.get("Group"),
                            weighting=o.get("Weighting", "Unweighted"), sigma=o.get("SD column"))
    show_residuals = bool(o.get("Residuals versus X"))
    if axes is None and not show_residuals:
        figure, axes = _plot(model, x, y)
        residual_axes = None
    elif axes is None:
        figure = Figure(figsize=(8, 6.2), dpi=100, layout="constrained")
        grid = figure.add_gridspec(2, 1, height_ratios=[3, 1.2])
        axes = figure.add_subplot(grid[0])
        residual_axes = figure.add_subplot(grid[1], sharex=axes)
        axes.set(title=model, xlabel=x, ylabel=y)
    else:
        figure = axes.figure
        if show_residuals:
            # The caller does not reuse this axes object. Split its cell.
            spec = axes.get_subplotspec()
            axes.remove()
            grid = spec.subgridspec(2, 1, height_ratios=[3, 1.2])
            axes = figure.add_subplot(grid[0])
            residual_axes = figure.add_subplot(grid[1], sharex=axes)
        else:
            residual_axes = None
        axes.set(title=y, xlabel=x, ylabel="Response")
    if residual_axes is not None:
        for panel in (axes, residual_axes):
            panel.spines[["right", "top"]].set_visible(False)
        weighted = o.get("Weighting", "Unweighted") not in (None, "", "Unweighted")
        residual_axes.set_ylabel("Residual, raw Y units" if weighted else "Residual")
        residual_axes.axhline(0, color="#334155", linewidth=1)
    tables = {"Parameters": {}, "Fit": {}, "Residuals": {}}
    colors = {}
    for label, fit in fits.items():
        dots = axes.scatter(fit.data[x], fit.data[y], label=str(label))
        if o.get("Group"):
            dots._tramastat_legend_key = f"group:{typed_group_token(label)}"
        colors[label] = dots.get_facecolor()[0]
        axes.plot(*fit.curve.T, color=colors[label])
        if residual_axes is not None:
            residual_axes.scatter(fit.residuals["X"], fit.residuals["Residual"], color=colors[label])
        parameters, parameter_status = parameter_outputs(fit, model, parameter_config, budget=parameter_budget)
        tables["Parameters"][label] = parameters.rename_axis("Parameter")
        if parameter_status is not None:
            tables.setdefault("Parameter CI status", {})[label] = parameter_status.rename_axis("Parameter")
        tables["Fit"][label] = _report(fit.diagnostics).rename_axis("Metric")
        tables["Residuals"][label] = fit.residuals.rename_axis("Source row")
    if model == "Normalized inhibition":
        axes.set_xscale("log")
    if len(fits) > 1:
        axes.legend()
    # Diagnostics and bands read the same fitted objects without another optimization.
    runs = bool(o.get("Runs test"))
    replicates = bool(o.get("Replicate lack of fit"))
    if runs or replicates:
        for label, fit in fits.items():
            for title, metrics in quality_tables(fit, runs=runs, replicates=replicates).items():
                tables.setdefault(title, {})[label] = _report(metrics).rename_axis("Metric")
    if compact:
        outputs = {title: pd.concat(parts, names=["Group"]) for title, parts in tables.items()}
    else:
        outputs = {f"{title}: {label}": parts[label] for label in fits for title, parts in tables.items()}
    # Additions below receive the Fits already computed. Never refit here: other packages hook in as well.
    if band:
        sheets, status = band_outputs(fits, model, y, band, o.get("Weighting", "Unweighted"), axes, colors)
        if compact:
            outputs["Band"] = pd.concat(sheets, names=["Group"])
        else:
            outputs.update({f"Band: {label}": sheet for label, sheet in sheets.items()})
        outputs["Band status"] = status
    return Result(outputs, figure)


def _classic_analysis(method, frame, options, predict, run):
    response_field, response_key = CLASSIC_RESPONSES[method]
    roles = classic_roles(method, options)
    responses, groups = roles[response_field], roles["Grouping variables"]
    columns = [options[predict], *responses, *groups]
    if method == "Nonlinear regression" and options.get("Weighting") == INVERSE_VARIANCE:
        columns.append(options.get("SD column"))
    if not responses or len(set(columns)) != len(columns) or any(column not in frame for column in columns):
        raise ValueError("Select distinct columns for the predictor, responses, grouping and optional SD.")
    if len(responses) > 8 or len(groups) > 4:
        raise ValueError("Select up to eight responses and four grouping variables.")
    if method == "Kaplan–Meier survival":
        frame = check_survival_options(frame, {**options, **roles})
    stable_groups = method == "Kaplan–Meier survival" and _has_survival_orientation(options)
    frame, group = _combined_groups(frame, options[predict], responses, groups, numbered=not stable_groups)
    if len(responses) == 1:
        compact = len(groups) > 1
        result = run(frame, {**options, response_key: responses[0], "Group": group}, compact=compact)
        if compact:
            result.tables = {title: table.reset_index() for title, table in result.tables.items()}
        return result
    rows = (len(responses) + 1) // 2
    has_risks = method == "Kaplan–Meier survival" and options.get("Show risk table below graph")
    figure = Figure(figsize=(9, (4.5 if has_risks else 3.4) * rows), dpi=100, layout="constrained")
    figure.suptitle(options["Model"] if method == "Nonlinear regression" else method)
    grid = figure.add_gridspec(rows, 2)
    tables = {}
    for i, response in enumerate(responses):
        panel = grid[i // 2, i % 2]
        extras = {}
        if has_risks:
            panel, risk_panel = panel.subgridspec(2, 1, height_ratios=[3, 1.2])
        axes = figure.add_subplot(panel)
        if has_risks:
            extras["risk_axes"] = figure.add_subplot(risk_panel)
        axes.spines[["right", "top"]].set_visible(False)
        try:
            result = run(frame, {**options, response_key: response, "Group": group}, axes, compact=True, **extras)
        except FieldError as error:
            raise FieldError(error.field, f"{response}: {error}") from error
        except ValueError as error:
            raise ValueError(f"{response}: {error}") from error
        for title, table in result.tables.items():
            tables.setdefault(title, {})[response] = table
    return Result({title: pd.concat(parts, names=["Response variable"]).reset_index()
                   for title, parts in tables.items()}, figure)


def _imported_xy(frame, options):
    data = engine.complete(frame, ["X", "Y", "Dataset"], ["Series", "Geometry"])
    if data.empty:
        raise ValueError("The saved graph has no complete XY points.")
    figure, axes = _plot(options.get(PRISM_TITLE, "Prism XY graph"), options.get("X label", "X"), "Y")
    colors = {}
    error_columns = ["Y minus", "Y plus"]
    if all(column in frame for column in error_columns):
        data = data.join(frame[error_columns], validate="one_to_one")
    for _, group in data.groupby("Dataset", sort=False):
        labels, shapes = group["Series"].unique(), group["Geometry"].unique()
        if len(labels) != 1 or len(shapes) != 1:
            raise ValueError("Each saved graph series needs one label and geometry.")
        label, geometry = labels[0], shapes[0]
        display = str(label) if label not in colors else "_nolegend_"
        color = colors.get(label)
        if geometry == "line":
            artist, = axes.plot(group["X"], group["Y"], color=color, label=display)
            color = artist.get_color()
        elif geometry == "step":
            artist, = axes.step(group["X"], group["Y"], where="post", color=color, label=display)
            color = artist.get_color()
        elif geometry == "points":
            artist = axes.scatter(group["X"], group["Y"], color=color, label=display, s=20)
            color = artist.get_facecolor()[0]
        else:
            raise ValueError("Invalid geometry in a saved Prism series.")
        if all(column in group for column in error_columns):
            errors = group[error_columns].to_numpy(dtype=float, na_value=np.nan)
            present = np.isfinite(errors).all(axis=1) & (errors >= 0).all(axis=1)
            if present.any():
                axes.errorbar(group["X"].to_numpy()[present], group["Y"].to_numpy()[present],
                              yerr=errors[present].T, fmt="none", ecolor=color, alpha=.55)
        colors[label] = color
    if len(colors) <= 15:
        axes.legend()
    return Result({"Saved XY coordinates": data}, figure)


def _preview_figure(image):
    figure = Figure(figsize=(image.width / 144, image.height / 144), dpi=144)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.imshow(image)
    axes.set_axis_off()
    axes._tramastat_non_native = True
    return figure


def _imported_layout(options, layout_data=None):
    from .prism_binary_graphs import render_binary_graph, validate_binary_graph
    from .prism_layout_edit import PRISM_EDITABLE_PANELS, PRISM_PANEL_EDITS, edited_layout_preview

    if PRISM_PREVIEW in options:
        preview = edited_layout_preview(options[PRISM_PREVIEW], options.get(PRISM_EDITABLE_PANELS),
                                        options.get(PRISM_PANEL_EDITS), layout_data)
        return _preview_figure(render_binary_graph(preview, layout=True, crop=False))
    panels = options.get(PRISM_LAYOUT_PANELS)
    if not isinstance(panels, list) or not 1 <= len(panels) <= 24:
        raise ValueError("Invalid saved Prism layout placements.")
    placements, bytes_used = [], 0
    for panel in panels:
        if not isinstance(panel, dict) or not isinstance(bounds := panel.get("bounds"), list) or len(bounds) != 4:
            raise ValueError("Invalid saved Prism layout placement.")
        if any(type(value) is not int or not -32768 <= value <= 32767 for value in bounds):
            raise ValueError("Invalid saved Prism layout coordinates.")
        x0, y0, x1, y1 = bounds
        if x0 >= x1 or y0 >= y1:
            raise ValueError("Invalid saved Prism layout rectangle.")
        preview = panel.get("preview")
        if preview is not None:
            validate_binary_graph(preview)
            bytes_used += len(preview["data"])
        placements.append((bounds, preview))
    if bytes_used == 0 or bytes_used > MAX_LAYOUT_PANEL_DATA:
        raise ValueError("Invalid saved Prism layout artwork.")
    left, top = (min(bounds[i] for bounds, _ in placements) for i in (0, 1))
    right, bottom = (max(bounds[i] for bounds, _ in placements) for i in (2, 3))
    width, height = right - left, bottom - top
    if max(width, height) > 100 * min(width, height):
        raise ValueError("Invalid saved Prism layout aspect ratio.")
    scale = 10 / max(width, height)
    figure = Figure(figsize=(scale * width, scale * height), dpi=144)
    axes = figure.add_axes((0, 0, 1, 1))
    for (x0, y0, x1, y1), preview in placements:
        if preview is not None:
            axes.imshow(render_binary_graph(preview, crop=False), extent=(x0, x1, y1, y0), origin="upper")
    axes.set(xlim=(left, right), ylim=(bottom, top), aspect="equal")
    axes.set_axis_off()
    axes._tramastat_non_native = True
    return figure


def analyse(method, frame, options, *, layout_data=None, cancel=None):
    o = options
    if o.get("Linear trend") and method != "One-way ANOVA":
        from .trend_anova import reject_unless_one_way
        reject_unless_one_way(method)
    if method == SAVED_XY:
        return _imported_xy(frame, o)
    if method == SAVED_BINARY_RESULT:
        return Result({o.get(PRISM_RESULT_SHEET, "Saved results"): frame})
    if method == SAVED_BINARY_GRAPH:
        from .prism_binary_graphs import render_binary_graph

        return Result({}, _preview_figure(render_binary_graph(o.get(PRISM_PREVIEW))))
    if method == SAVED_BINARY_LAYOUT:
        return Result({}, _imported_layout(o, layout_data))
    if method == SAVED_EDITABLE_GRAPH:
        from .prism_emf_edit import CURVE, POINTS, edit_emf_preview
        from .prism_pdf_stacks import STACK_KIND, render_pdf_stack

        style = o.get(PRISM_GRAPH_STYLE)
        if isinstance(style, dict) and style.get("kind") == STACK_KIND:
            return Result({}, _preview_figure(render_pdf_stack(frame, style, o.get(PRISM_PREVIEW))))
        if isinstance(style, dict) and style.get("kind") in (CURVE, POINTS):
            from .prism_binary_graphs import render_binary_graph

            preview = edit_emf_preview(frame, style, o.get(PRISM_PREVIEW))
            return Result({}, _preview_figure(render_binary_graph(preview)))
        if isinstance(style, dict) and style.get("kind") == "columns":
            from .prism_binary_bars import edit_bar_preview
            from .prism_binary_graphs import render_binary_graph

            preview = edit_bar_preview(frame, style, o.get(PRISM_PREVIEW))
            return Result({}, _preview_figure(render_binary_graph(preview)))
        from .prism_binary_editable import render_editable_graph

        figure = render_editable_graph(frame, style)
        figure.axes[0]._tramastat_numeric_axes = ("x", "y")
        return Result({}, figure)
    if method == "Descriptive statistics":
        return Result({"Summary": engine.describe(frame, o["Variables"], geometric=bool(o.get(GEOMETRIC_MEAN)))})
    if method == NORMALITY:
        # Recipes saved before the test choices existed keep the Shapiro–Wilk "Normality" sheet.
        return _normality(frame, o) if legacy_normality(o) else normality(frame, o)
    if method == "t-test":
        result = engine.t_test(frame, o["Response"], o.get("Group"), o["Design"].lower(),
                               o.get("Subject"), order=o.get("Group order"), null=o.get("Null mean", 0.0))
        tables = {"t-test": _report(result)}
        attach_ttest(frame, o, tables)
        return Result(tables)
    if method == "Paired t-test (columns)":
        return Result({"t-test": _report(engine.paired_t_test(frame, o["First"], o["Second"]))})
    if method == LOGNORMAL:
        return lognormal_test(frame, o)
    if method == VARIANCE_RATIO:
        return variance_ratio_analysis(frame, o)
    if method == EQUIVALENCE:
        return equivalence_test(frame, o)
    if method == SUMMARY_ANOVA:
        return summary_anova(frame, o)
    if method == SUMMARY_TTEST:
        return summary_ttest(frame, o)
    if method in {MANN_WHITNEY, WILCOXON} and not legacy_rank_test(o):
        return rank_test(method, frame, o)
    if method in {MANN_WHITNEY, WILCOXON, "Kruskal–Wallis"}:
        return _nonparametric(method, frame, o)
    if method == "Correlation":
        # Detailed results is opt-in. A missing or false flag keeps this legacy sheet and ignores new fields.
        if o.get("Detailed results") is True:
            return correlation_result(frame, o, cancel=cancel)
        x, y = o["X"], o["Y"]
        data = engine.complete(frame, [x, y])
        if len(data) < 3 or min(data[x].nunique(), data[y].nunique()) < 2:
            raise ValueError("Correlation requires three XY pairs and nonconstant variables.")
        fn = {"Pearson": stats.pearsonr, "Spearman": stats.spearmanr, "Kendall": stats.kendalltau}[o["Method"]]
        test = fn(data[x], data[y])
        figure, axes = _plot(f"{o['Method']} correlation", x, y)
        axes.scatter(data[x], data[y])
        return Result({"Correlation": _report({"N": len(data), "Coefficient": test.statistic, "p": test.pvalue})},
                      figure)
    if method == CORRELATE_CONTROL:
        return control_result(frame, o, cancel=cancel)
    if method == COMPARE_INDEPENDENT:
        return independent_result(frame, o)
    if method == CORRELATION_MATRIX:
        return correlation_matrix(frame, o)
    if method == ROW_TESTS:
        return row_tests(frame, o)
    if method in NESTED_METHODS:
        return nested_analysis(method, frame, o)
    if method == HEAT_MAP:
        return heat_map(frame, o)
    if method == CONTINGENCY:
        return contingency(frame, o)
    if method == PARTS_GRAPH:
        return parts_graph(frame, o)
    if method == GOODNESS_OF_FIT:
        return goodness_of_fit(frame, o)
    if method == "Linear regression":
        return linear_result(frame, o)
    if method == COMPARE_LINES:
        return compare_lines(frame, o)
    if method == "Nonlinear regression":
        parameter_ci_settings(o)
        check_fit_options(o)
        return _classic_analysis(method, frame, o, "X", partial(_nonlinear, parameter_budget=ProfileBudget(cancel)))
    if method == CUSTOM_EQUATION:
        return custom_fit(frame, o, cancel=cancel)
    if method == GLOBAL_CUSTOM_EQUATION:
        return global_custom_fit(frame, o, cancel=cancel)
    if method == "Compare nonlinear models":
        pair = next(pair for pair in engine.NESTED_MODELS if " → ".join(pair) == o["Nested models"])
        return Result({"Extra sum-of-squares F test": engine.compare_nonlinear(
            frame, o["X"], o["Y"], *pair, o.get("Group"),
            weighting=o.get("Weighting", "Unweighted"), sigma=o.get("SD column"))})
    if method == COMPARE_MODELS:
        return model_selection(frame, o)
    if method == ROBUST_CURVE:
        return robust_curve(frame, o)
    if method == "Multifactor ANOVA":
        return _anova(frame, o)
    if method == "K-means model selection":
        return _cluster_selection(frame, o)
    if method == "Kaplan–Meier survival":
        return _classic_analysis(method, frame, o, "Time", _survival)
    if method == "K-means clustering":
        return _kmeans(frame, o)
    if method == "Hierarchical clustering":
        return hierarchical_result(frame, o)
    if method == SELECT_TRANSFORM:
        return select_transform(frame, o)
    if method == EXTRACT_REARRANGE:
        return extract_rearrange(frame, o)
    if method == TRANSPOSE_XY:
        return transpose_xy(frame, o)
    if method == "Scatter / confidence ellipse":
        return _scatter(frame, o)
    if method == "XY error bars":
        return _xy_errors(frame, o)
    if method == XY_METHOD:
        return xy_series(frame, o)
    if method == BUBBLE:
        return bubble_plot(frame, o)
    if method in {COLUMN_GRAPH, GROUPED_GRAPH}:
        return category_graph(frame, o, grouped=method == GROUPED_GRAPH)
    if method == FREQUENCY:
        return frequency(frame, o)
    if method == BOX_VIOLIN:
        # Saved recipes from before input modes retain their original rendering.
        if o.keys() <= {"Response", "Group", "Style"}:
            return _distribution(method, frame, o)
        return box_violin(frame, o)
    if method == BEFORE_AFTER:
        return before_after(frame, o)
    if method == TRAJECTORIES:
        return subject_trajectories(frame, o)
    if method == FOREST_PLOT:
        return forest_plot(frame, o)
    if method == OUTLIERS:
        return identify_outliers(frame, o)
    if method == MONTE_CARLO:
        return monte_carlo(frame, o)
    if method == "Histogram":
        return _distribution(method, frame, o)
    if method == REFERENCE_NORMALIZATION:
        return normalize_to_references(frame, o)
    return extra_analysis(method, frame, o)
