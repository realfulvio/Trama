"""Connect analysis options to result sheets and graphs."""
from functools import partial
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats

from . import stats as engine, ttest_options
from . import regression_range
from .advanced import anova_comparisons, kmeans_scan
from . import kmeans_archive, kmeans_options, kmeans_reports
from .legacy_fit_graph import (FIT_GRAPH, FIT_GRAPH_OBSERVATIONS, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC, FIT_GRAPH_TICKS,
                               FIT_INTERVAL_BAND, LOG_DOSE_MODEL,
                              draw_fit_interval_band, fitted_graph_points)
from .replicate_fit import MERGE_REPLICATES, stack_replicates
from .hartigan_wong import IterationLimitError
from .cluster_consensus import DIMENSION_ADJUSTED, KL_CHOICES, KL_SCALING, UNSCALED_WSS
from .kmeans_stability import METHOD as KMEANS_STABILITY, OPTIONS as KMEANS_STABILITY_OPTIONS
from .kmeans_stability import analysis as kmeans_stability
from .anova_diagnostics import OPTIONS as ANOVA_DIAG_OPTIONS
from .anova_diagnostics import active as anova_diagnostics_active, build as build_anova_diagnostics
from .anova_diagnostics import ensure_graph_budget as ensure_anova_graph_budget, graph_choice as anova_graph_choice
from .anova_diagnostics import validate as validate_anova_diagnostics
from . import anova_comparison_plot, anova_diagnostics, anova_grouped_plot
from .anova_ss import CHOICES as SS_CHOICES, KEY as SUMS_OF_SQUARES, SHEETS as ANOVA_SHEETS
from .anova_ss import sums_of_squares as anova_sums_of_squares
from . import anova_planned_contrasts as planned_contrasts
from .anova_terms import (CHOICES as TERM_CHOICES, MODEL_TERMS, SHEET as MODEL_TERMS_SHEET, TERM_LIST, TERM_SELECTION,
                          active_factors as anova_active_factors, check_comparison_controls as check_anova_comparisons,
                          selection as anova_term_selection, terms_table as anova_terms_table)
from .additional import EXTRA_METHODS, extra_analysis
from .category_graphs import (COLUMN_GRAPH, COLUMN_STYLES, GROUPED_GRAPH, GROUPED_OPTIONS, OPTIONS as CATEGORY_OPTIONS,
                              category_graph)
from .ancova import ANCOVA, OPTIONS as ANCOVA_OPTIONS, ancova
from .bubble import BUBBLE, OPTIONS as BUBBLE_OPTIONS, bubble_plot
from . import bland_altman_repeated as ba_repeated
from .cluster_silhouette import METHOD as CLUSTER_SILHOUETTE, OPTIONS as SILHOUETTE_OPTIONS, cluster_silhouette
from . import icc
from . import precision_recall
from .compare_lines import COMPARE_LINES, OPTIONS as COMPARE_LINES_OPTIONS, compare_lines
from .contingency import CONTINGENCY, CONTINGENCY_OPTIONS, contingency
from .distribution_graphs import BOX_VIOLIN, OPTIONS as BOX_VIOLIN_OPTIONS, box_violin
from .grouped_distributions import (GROUPED_DISTRIBUTIONS, OPTIONS as GROUPED_DISTRIBUTIONS_OPTIONS,
                                    grouped_distributions)
from .correlation_details import (COMPARE_INDEPENDENT, CONTROL_OPTIONS, CORRELATE_CONTROL, INDEPENDENT_OPTIONS,
                                  SINGLE_EXTRA, control_result, correlation_result, independent_result)
from .correlation_matrix import CORRELATION_MATRIX, OPTIONS as CORRELATION_MATRIX_OPTIONS, correlation_matrix
from .rmcorr import OPTIONS as RMCORR_OPTIONS, RMCORR, analyse as rmcorr_analysis
from .ellipse_workbench import ELLIPSE_OPTIONS, NONE, SEPARATE_GROUP, draw_confidence_overlays
from .extract_rearrange import (COMPLETE, EXTRACT_FIELDS, EXTRACT_FORMATS, EXTRACT_OPTIONAL_FIELDS, EXTRACT_REARRANGE,
                                OUTPUT, PREFIX, extract_rearrange)
from .fit_quality import OPTIONS as FIT_QUALITY_OPTIONS, check_options as check_fit_options, fit_quality as quality_tables
from .fit_weights import INVERSE_VARIANCE, NONLINEAR_WEIGHTINGS
from .forest_plot import FOREST_PLOT, OPTIONS as FOREST_OPTIONS, forest_plot
from .meta_analysis import META_ANALYSIS, OPTIONS as META_OPTIONS, meta_analysis
from .frequency import FREQUENCY, FREQUENCY_OPTIONS, frequency
from .category_order import preferred_levels, ranks
from .graph_legend import typed_group_token
from .heatmap import HEAT_MAP, OPTIONS as HEAT_MAP_OPTIONS, heat_map
from .reference_normalization import (METHOD as REFERENCE_NORMALIZATION, OPTIONS as REFERENCE_NORMALIZATION_OPTIONS,
                                      normalize_to_references)
from . import grouped_anova
from .hierarchical_workbench import (HIERARCHICAL_OPTIONS, HIERARCHY_GRAPH, HIERARCHY_GRAPH_OPTIONS, hierarchical_result,
                                     hierarchy_graph)
from .inference import (CHI_SQUARE_P, DUNN_OPTIONS, KRUSKAL_P, KRUSKAL_P_METHODS, dunn_comparisons,
                        kruskal_wallis, selected_pair_indices)
from .linear_diagnostics import LINEAR_OPTIONS, linear_result
from .cohen_kappa_workbench import COHEN_KAPPA, OPTIONS as COHEN_KAPPA_OPTIONS, cohen_kappa
from .equivalence_workbench import EQUIVALENCE, OPTIONS as EQUIVALENCE_OPTIONS, equivalence_test
from .mean_permutation import METHOD as MEAN_PERMUTATION, OPTIONS as MEAN_PERMUTATION_OPTIONS, permutation_test
from .yuen import METHOD as YUEN, OPTIONS as YUEN_OPTIONS, yuen_test
from .competing_risks_workbench import (COMPETING_RISKS, OPTIONS as COMPETING_RISKS_OPTIONS,
                                        competing_risks)
from .cox_exact import METHOD as COX_REGRESSION, cox_exact_result, is_exact as is_cox_exact
from .weibull_aft_workbench import WEIBULL_AFT, OPTIONS as WEIBULL_AFT_OPTIONS, weibull_aft
from .rmst_workbench import OPTIONS as RMST_OPTIONS, RMST, rmst
from .lognormal_tests import LOGNORMAL, OPTIONS as LOGNORMAL_OPTIONS, lognormal_test
from .ordinal_logit import ORDINAL_LOGIT, OPTIONS as ORDINAL_LOGIT_OPTIONS, ordinal_logit
from .variance_ratio import METHOD as VARIANCE_RATIO, SHOW as VARIANCE_SHOW, analysis as variance_ratio_analysis, attach_ttest
from .summary_anova import METHOD as SUMMARY_ANOVA, OPTIONS as SUMMARY_ANOVA_OPTIONS, summary_anova
from .summary_ttest import METHOD as SUMMARY_TTEST, OPTIONS as SUMMARY_TTEST_OPTIONS, summary_ttest
from .tolerance_intervals import TOLERANCE, OPTIONS as TOLERANCE_OPTIONS, tolerance_intervals
from .model_selection import COMPARE_MODELS, OPTIONS as COMPARE_MODELS_OPTIONS, model_selection
from .nonlinear_bands import OPTIONS as BAND_OPTIONS, band_outputs, band_settings
from .monte_carlo import MONTE_CARLO, OPTIONS as MONTE_CARLO_OPTIONS, monte_carlo
from .independent_roc import METHOD as INDEPENDENT_ROC, independent_roc
from .logistic_validation import METHOD as LOGISTIC_VALIDATION, OPTIONS as LOGISTIC_VALIDATION_OPTIONS
from .logistic_validation import analysis as logistic_validation
from .custom_fit import CUSTOM_EQUATION, custom_fit
from .linked_axes import SUPPORT_ATTR, mark_linked_axes
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION, global_custom_fit
from .plot_function import PLOT_FUNCTION
from .robust_curve import OPTIONS as ROBUST_CURVE_OPTIONS, ROBUST_CURVE, robust_curve
from .nb2_regression import NB2, OPTIONS as NB2_OPTIONS, analysis as nb2_analysis
from .transpose_xy import OPTIONS as TRANSPOSE_OPTIONS, TRANSPOSE_XY, transpose_xy
from .reshape_long_wide import METHOD as RESHAPE_LONG_WIDE, OPTIONS as RESHAPE_OPTIONS, reshape_long_wide
from .worksheet_join import METHOD as WORKSHEET_JOIN, OPTIONS as WORKSHEET_JOIN_OPTIONS, join_worksheets
from .paired_graphs import (BEFORE_AFTER, BEFORE_AFTER_OPTIONS, TRAJECTORIES, TRAJECTORY_OPTIONS, before_after,
                            subject_trajectories, TTEST_ESTIMATION, paired_estimation_figure,
                            shows_paired_estimation)
from .spline_fit import SPLINE_FIT
from .outlier_screening import OPTIONS as OUTLIER_OPTIONS, OUTLIERS, identify_outliers
from .parameter_intervals import (OPTIONS as PARAMETER_CI_OPTIONS, WALD, settings as parameter_ci_settings,
                                  parameter_outputs, ProfileBudget, REPORT_LOG_IC50,
                                  TRANSFORMED_PARAMETERS, has_ic50, log_ic50_table)
from .normality import NORMALITY, OPTIONS as NORMALITY_OPTIONS, is_legacy as legacy_normality, normality
from .paired_proportions import OPTIONS as PAIRED_PROPORTIONS_OPTIONS, PAIRED_PROPORTIONS, paired_proportions
from .nested import METHODS as NESTED_METHODS, NESTED_ANOVA, NESTED_T, nested_analysis
from .select_transform import SELECT_OPTIONS, SELECT_TRANSFORM, select_transform
from .parts_of_whole import GOODNESS_OF_FIT, GOODNESS_OPTIONS, PARTS_GRAPH, PARTS_OPTIONS, goodness_of_fit, parts_graph
from .reporting import Result, _plot, _report
from .xy_series import XY_METHOD, xy_series
from .processing import FieldError
from .rank_tests import MANN_WHITNEY, OPTIONS as RANK_OPTIONS, WILCOXON, is_legacy as legacy_rank_test, rank_test
from .row_tests import ROW_TESTS, OPTIONS as ROW_TEST_OPTIONS, row_tests
from . import fdr_control
from .survival_input import (PAIRWISE_CORRECTION, PAIRWISE_CONTROL, PAIRWISE_ADJUSTED, PAIRWISE_ALPHA,
                             PAIRWISE_METHODS, PAIRWISE_CORRECTIONS, PAIRWISE_FDR, PAIRWISE_SCOPE, PAIRWISE_SCOPES,
                             PAIRWISE_PAIRS, PAIRWISE_PAIR_LIST,
                             CONTROL_PAIRS, SELECTED_PAIRS, UNADJUSTED, pairwise_scope, CENSOR_CODE, EVENT_CODE,
                             OTHER_STATUS, STATUS_POLICIES, recode_statuses)
from .survival_bands import SHEET as SIMULTANEOUS_SHEET, join_bands
from .survival_plot import (ERROR_BARS, GRAPH_OPTIONS as SURVIVAL_GRAPH_OPTIONS, GREENWOOD, INTERVAL, RISK_TABLE,
                            SURVIVAL_GRAPH, SURVIVAL_SERIES, SURVIVAL_SUMMARY, UNCERTAINTY, SurvivalGraphData,
                            draw_survival_graph, linked_survival_graph, survival_graph_settings)
from .legacy_restore import (MAX_LAYOUT_PANEL_DATA, LEGACY_GRAPH_STYLE, LEGACY_LAYOUT_PANELS, LEGACY_PREVIEW,
                            LEGACY_RESULT_SHEET, LEGACY_TITLE, SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT,
                            SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, SAVED_XY)

GEOMETRIC_MEAN = engine.GEOMETRIC_MEAN
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


def _combined_groups(frame, predictor, responses, groups, *, numbered=True, outside=None):
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
        def combined(data):
            labels = [names.get(values) for values in data.loc[:, groups].itertuples(index=False, name=None)]
            return data.assign(**{group: labels})

        frame = combined(frame)
        if outside is not None:
            outside = combined(outside)
    return frame, group, outside


def _survival_levels(frame, time, responses, groups):
    if not groups or not responses or time not in frame or any(c not in frame for c in (*responses, *groups)):
        return []
    frame, group, _ = _combined_groups(frame, time, responses, groups, numbered=False)
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
    correction = options.get(PAIRWISE_CORRECTION, "None")
    scope = pairwise_scope(options)
    control = correction != "None" and scope == CONTROL_PAIRS
    selected = correction != "None" and scope == SELECTED_PAIRS
    if correction != "None":
        if not isinstance(correction, str) or correction not in PAIRWISE_CORRECTIONS:
            raise FieldError(PAIRWISE_CORRECTION, "Choose a supported correction for the pairwise tests.")
        if scope not in PAIRWISE_SCOPES:
            raise FieldError(PAIRWISE_SCOPE, "Choose a comparison family.")
        if correction in fdr_control.FDR_METHODS:
            fdr_control.discovery_level(options)
        elif correction == UNADJUSTED or not options.get(PAIRWISE_ADJUSTED, True):
            alpha = options.get(PAIRWISE_ALPHA, .05)
            if (isinstance(alpha, (bool, np.bool_)) or not isinstance(alpha, (int, float, np.floating))
                    or not 0 < alpha < 1):
                raise FieldError(PAIRWISE_ALPHA, "Pairwise alpha must be between zero and one.")
    if not (wants_trend or wants_hazard or control or selected):
        return coded
    levels = _survival_levels(coded, options.get("Time"), responses, roles["Grouping variables"])
    if selected:
        if len(levels) > 12:
            raise FieldError(PAIRWISE_PAIRS, "Pairwise survival tests support up to twelve groups.")
        selected_pair_indices(levels, options.get(PAIRWISE_PAIRS), PAIRWISE_PAIRS)
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
    control_name = options.get(PAIRWISE_CONTROL)
    if control and (len(levels) < 2 or not isinstance(control_name, str) or control_name not in levels):
        raise FieldError(PAIRWISE_CONTROL, "Choose a control from at least two observed groups.")
    numerator = options.get("Hazard ratio numerator")
    if wants_hazard and numerator and str(numerator) not in levels:
        raise FieldError("Hazard ratio numerator", f"Hazard ratio numerator: {numerator} is not a group in this analysis.")
    return coded


# Fields are column roles, options, or typed defaults.
METHODS = {
    "Descriptive statistics": {"Variables": MULTIPLE, engine.SUMMARY_FORMAT: (engine.FULL_REPORT, engine.GEOMETRIC_REPORT),
                               GEOMETRIC_MEAN: False, engine.SUMMARY_CONFIDENCE: 95., engine.SUMMARY_SUM: True},
    TOLERANCE: TOLERANCE_OPTIONS,
    NORMALITY: NORMALITY_OPTIONS,
    "t-test": {"Design": ("Welch", "Student", "Paired", "One-sample"), **ttest_options.OPTIONS,
               "Response": None, "Group": OPTIONAL, "Subject": OPTIONAL, "Null mean": 0.0,
               VARIANCE_SHOW: False, TTEST_ESTIMATION: False},
    "Paired t-test (columns)": {"First": None, "Second": None},
    LOGNORMAL: LOGNORMAL_OPTIONS,
    VARIANCE_RATIO: {"First": None, "Second": None, "Confidence level (%)": 95.0,
                     "Distribution": ("Normal", "Lognormal"),
                     "Graph": ("None", "Variance ratio", "SD ratio")},
    EQUIVALENCE: EQUIVALENCE_OPTIONS,
    MEAN_PERMUTATION: MEAN_PERMUTATION_OPTIONS,
    YUEN: YUEN_OPTIONS,
    COHEN_KAPPA: COHEN_KAPPA_OPTIONS,
    COMPETING_RISKS: COMPETING_RISKS_OPTIONS,
    WEIBULL_AFT: WEIBULL_AFT_OPTIONS,
    ORDINAL_LOGIT: ORDINAL_LOGIT_OPTIONS,
    RMST: RMST_OPTIONS,
    SUMMARY_ANOVA: SUMMARY_ANOVA_OPTIONS,
    SUMMARY_TTEST: SUMMARY_TTEST_OPTIONS,
    MEAN_PERMUTATION: MEAN_PERMUTATION_OPTIONS,
    MANN_WHITNEY: RANK_OPTIONS[MANN_WHITNEY],
    WILCOXON: RANK_OPTIONS[WILCOXON],
    "Kruskal–Wallis": {"Response": None, "Group": None, KRUSKAL_P: KRUSKAL_P_METHODS, **DUNN_OPTIONS},
    "Correlation": {"X": None, "Y": None, "Method": ("Pearson", "Spearman", "Kendall"), **SINGLE_EXTRA},
    CORRELATE_CONTROL: CONTROL_OPTIONS,
    COMPARE_INDEPENDENT: INDEPENDENT_OPTIONS,
    RMCORR: RMCORR_OPTIONS,
    CORRELATION_MATRIX: {"Variables": MULTIPLE, **CORRELATION_MATRIX_OPTIONS},
    ROW_TESTS: ROW_TEST_OPTIONS,
    **NESTED_METHODS,
    CONTINGENCY: CONTINGENCY_OPTIONS,
    PAIRED_PROPORTIONS: PAIRED_PROPORTIONS_OPTIONS,
    PARTS_GRAPH: PARTS_OPTIONS,
    GOODNESS_OF_FIT: GOODNESS_OPTIONS,
    "Linear regression": {"X": None, "Y": None, **LINEAR_OPTIONS, **dict.fromkeys(regression_range.FIELDS, TEXT)},
    COMPARE_LINES: COMPARE_LINES_OPTIONS,
    ANCOVA: ANCOVA_OPTIONS,
    "Nonlinear regression": {"X": None, "Y columns": MULTIPLE, "Grouping variables": OPTIONAL_MULTIPLE,
                             MERGE_REPLICATES: False,
                             "Model": tuple(name for name, spec in engine.MODELS.items()
                                            if not (spec.required_fixed or spec.required_shared)),
                             "Weighting": NONLINEAR_WEIGHTINGS, "SD column": OPTIONAL,
                             **BAND_OPTIONS, **FIT_QUALITY_OPTIONS, **PARAMETER_CI_OPTIONS,
                             REPORT_LOG_IC50: False, **dict.fromkeys(regression_range.FIELDS, TEXT),
                             regression_range.SHOW_OUTSIDE: False},
    "Compare nonlinear models": {"X": None, "Y": None, "Group": OPTIONAL,
                                 "Nested models": tuple(f"{a} → {b}" for a, b in engine.NESTED_MODELS),
                                 "Weighting": engine.FIT_WEIGHTINGS, "SD column": OPTIONAL},
    COMPARE_MODELS: COMPARE_MODELS_OPTIONS,
    ROBUST_CURVE: ROBUST_CURVE_OPTIONS,
    grouped_anova.METHOD: {grouped_anova.ROWS: None, grouped_anova.VALUES: OPTIONAL_MULTIPLE,
                          grouped_anova.ROW_NAME: TEXT, grouped_anova.COLUMN_NAME: TEXT,
                          grouped_anova.INTERACTION: True},
    NB2: NB2_OPTIONS,
    LOGISTIC_VALIDATION: LOGISTIC_VALIDATION_OPTIONS,
    "Multifactor ANOVA": {"Response": None, "Factors": MULTIPLE, TERM_SELECTION: TERM_CHOICES, "Interaction order": 1,
                         SUMS_OF_SQUARES: SS_CHOICES, MODEL_TERMS: TERM_LIST,
                         "Compare marginal means by": OPTIONAL, "Cell comparison factors": OPTIONAL_MULTIPLE,
                         "Within factors (simple effects)": OPTIONAL_MULTIPLE, "Control level(s), separated by |": TEXT,
                         "Families": ("Separate", "Pooled"), "Reverse comparisons": False,
                         "Correction": ("Holm", "Holm–Šídák", "Šídák", "Bonferroni", "Tukey", "Dunnett", "None"),
                         ANOVA_EFFECTS: False, ANOVA_ALPHA: 0.05, **ANOVA_DIAG_OPTIONS,
                         # Planned contrasts (0.96): read only when the contrast list is not empty.
                         planned_contrasts.FACTORS: planned_contrasts.FACTOR_LIST,
                         planned_contrasts.CONTRASTS: planned_contrasts.CONTRAST_LIST,
                         planned_contrasts.CORRECTION: planned_contrasts.CORRECTIONS,
                         planned_contrasts.ALPHA: planned_contrasts.DEFAULT_ALPHA},
    "Kaplan–Meier survival": {"Time": None, "Event columns": MULTIPLE, "Grouping variables": OPTIONAL_MULTIPLE,
                              PAIRWISE_CORRECTION: PAIRWISE_CORRECTIONS,
                              PAIRWISE_SCOPE: PAIRWISE_SCOPES, PAIRWISE_CONTROL: GROUP_CHOICE,
                              PAIRWISE_PAIRS: PAIRWISE_PAIR_LIST,
                              PAIRWISE_ADJUSTED: True, PAIRWISE_ALPHA: .05, PAIRWISE_FDR: 5.,
                              "Median method": MEDIAN_METHODS, "Confidence level (%)": 95.0,
                              "Gehan–Breslow–Wilcoxon": False, "Log-rank trend": False,
                              "Trend group order": GROUP_ORDER, "Hazard ratio": False,
                              "Hazard ratio numerator": GROUP_CHOICE, EVENT_CODE: TEXT, CENSOR_CODE: TEXT,
                              OTHER_STATUS: STATUS_POLICIES, **SURVIVAL_GRAPH_OPTIONS},
    "K-means model selection": {"Variables": MULTIPLE, "Minimum k": 1, "Maximum k": 8,
                                kmeans_options.SCALE: tuple(kmeans_options.SCALES), "Seed": 42,
                                "Criterion": ("Silhouette", "Elbow", "Calinski–Harabasz", "Davies–Bouldin", "Gap",
                                              "Consensus (17 indices)"),
                                "Gap simulations": 20, kmeans_options.GAP_REFERENCE: kmeans_options.GAP_GEOMETRIES,
                                KL_SCALING: KL_CHOICES,
                                kmeans_options.ALGORITHM: kmeans_options.ALGORITHMS,
                                kmeans_options.INITIALIZATION: kmeans_options.INITIALIZATIONS,
                                kmeans_options.MAX_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                                kmeans_options.MACQUEEN_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                                kmeans_options.LLOYD_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                                **dict.fromkeys((*kmeans_reports.SCAN, *kmeans_options.PLOTS), False)},
    "K-means clustering": {"Variables": MULTIPLE, "Clusters": 2,
                           kmeans_options.SCALE: tuple(kmeans_options.SCALES), "Seed": 42,
                           kmeans_options.ALGORITHM: kmeans_options.ALGORITHMS,
                           kmeans_options.INITIALIZATION: kmeans_options.INITIALIZATIONS,
                           kmeans_options.MAX_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                           kmeans_options.MACQUEEN_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                           kmeans_options.LLOYD_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
                           kmeans_options.INITIAL_ROWS: TEXT, **dict.fromkeys(kmeans_reports.COMMON, False)},
    KMEANS_STABILITY: {**KMEANS_STABILITY_OPTIONS, "Variables": MULTIPLE},
    kmeans_reports.MODEL_GRAPH: kmeans_reports.MODEL_GRAPH_OPTIONS,
    "Hierarchical clustering": {"Variables": MULTIPLE, "Observation labels": OPTIONAL, **HIERARCHICAL_OPTIONS},
    HIERARCHY_GRAPH: HIERARCHY_GRAPH_OPTIONS,
    CLUSTER_SILHOUETTE: SILHOUETTE_OPTIONS,
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
    GROUPED_DISTRIBUTIONS: GROUPED_DISTRIBUTIONS_OPTIONS,
    BUBBLE: BUBBLE_OPTIONS,
    ba_repeated.METHOD: ba_repeated.OPTIONS,
    icc.METHOD: {icc.RATERS: MULTIPLE, **icc.OPTIONS},
    precision_recall.METHOD: precision_recall.OPTIONS,
    BEFORE_AFTER: BEFORE_AFTER_OPTIONS,
    TRAJECTORIES: TRAJECTORY_OPTIONS,
    FOREST_PLOT: FOREST_OPTIONS,
    META_ANALYSIS: META_OPTIONS,
    OUTLIERS: OUTLIER_OPTIONS,
    MONTE_CARLO: MONTE_CARLO_OPTIONS,
    SELECT_TRANSFORM: SELECT_OPTIONS,
    TRANSPOSE_XY: TRANSPOSE_OPTIONS,
    RESHAPE_LONG_WIDE: RESHAPE_OPTIONS,
    EXTRACT_REARRANGE: {OUTPUT: EXTRACT_FORMATS, PREFIX: False, COMPLETE: True, **{
        field: OPTIONAL if field in EXTRACT_OPTIONAL_FIELDS else None
        for field in dict.fromkeys(field for fields in EXTRACT_FIELDS.values() for field in fields)
    }},
    REFERENCE_NORMALIZATION: REFERENCE_NORMALIZATION_OPTIONS,
    WORKSHEET_JOIN: WORKSHEET_JOIN_OPTIONS,
    **EXTRA_METHODS,
}

GROUPS = {
    "Data Processing": ("Transform", "Transform concentrations (X)", "Normalize", REFERENCE_NORMALIZATION, "Prune rows",
                        "Remove baseline and column math", "Fraction of total", EXTRACT_REARRANGE, SELECT_TRANSFORM,
                        "Reshape replicates", RESHAPE_LONG_WIDE, TRANSPOSE_XY, WORKSHEET_JOIN,
                        "Outlier test (Grubbs)", OUTLIERS),
    "Data Exploration and Summary": ("Descriptive statistics", TOLERANCE, "Row statistics", NORMALITY,
                                    "Correlation", CORRELATE_CONTROL, COMPARE_INDEPENDENT, CORRELATION_MATRIX, RMCORR,
                                    "Histogram", FREQUENCY, GOODNESS_OF_FIT,
                                    "Area under curve", "Principal component analysis",
                                    "Adjust a stack of p values", "Control false discoveries", META_ANALYSIS),
    "Regression and Curves": ("Linear regression", COMPARE_LINES, "Deming regression", "Multiple regression",
                              NB2, LOGISTIC_VALIDATION, "Nonlinear regression", "Global nonlinear regression", "Compare nonlinear models",
                              COMPARE_MODELS, ROBUST_CURVE, CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION,
                              "Interpolate a standard curve", SPLINE_FIT,
                              "Smooth / differentiate / integrate", PLOT_FUNCTION, ORDINAL_LOGIT),
    "Group Comparison": ("t-test", "Paired t-test (columns)", LOGNORMAL, VARIANCE_RATIO, EQUIVALENCE, MEAN_PERMUTATION, YUEN, SUMMARY_TTEST, "Multiple t-tests", ROW_TESTS, "Mann–Whitney", "Wilcoxon signed-rank",
                         "Kolmogorov–Smirnov", "Kruskal–Wallis", "Friedman", "One-way ANOVA", SUMMARY_ANOVA,
                         NESTED_T, NESTED_ANOVA, "Repeated measures ANOVA", "Mixed-effects model (REML)",
                         "Multifactor ANOVA", grouped_anova.METHOD, ANCOVA, "Contingency table", PAIRED_PROPORTIONS, COHEN_KAPPA,
                         "Bland–Altman", ba_repeated.METHOD, icc.METHOD, "ROC curve", "Compare paired ROC curves", INDEPENDENT_ROC,
                         precision_recall.METHOD),
    "Survival Analysis": ("Kaplan–Meier survival", "Cox regression", COMPETING_RISKS, WEIBULL_AFT, RMST),
    "Clustering": ("K-means clustering", "K-means model selection", KMEANS_STABILITY, kmeans_reports.MODEL_GRAPH, "Hierarchical clustering",
                   HIERARCHY_GRAPH, CLUSTER_SILHOUETTE),
    "Graphing": ("Scatter / confidence ellipse", "XY error bars", XY_METHOD, COLUMN_GRAPH, GROUPED_GRAPH, HEAT_MAP,
                 PARTS_GRAPH, "Box / violin plot", GROUPED_DISTRIBUTIONS, BUBBLE, BEFORE_AFTER, TRAJECTORIES, FOREST_PLOT),
    "Study Design and Simulation": ("Power and sample size", "Simulate data", MONTE_CARLO),
}

# These analyses create a graph when calculated. Keep their Graphs entry
# available while a reopened project's results are still unloaded.
GRAPH_METHODS = frozenset({
    anova_comparison_plot.METHOD, anova_diagnostics.METHOD, anova_grouped_plot.METHOD,
    *GROUPS["Graphing"], PLOT_FUNCTION, "Area under curve", "Bland–Altman", ba_repeated.METHOD, icc.METHOD, "Correlation", CORRELATE_CONTROL,
    COMPARE_INDEPENDENT, CORRELATION_MATRIX, COHEN_KAPPA, "Deming regression",
    "Global nonlinear regression", "Hierarchical clustering", HIERARCHY_GRAPH, "Histogram", FREQUENCY,
    "Interpolate a standard curve",
    "K-means clustering", "K-means model selection", KMEANS_STABILITY, kmeans_reports.MODEL_GRAPH,
    "Kaplan–Meier survival", COMPETING_RISKS, WEIBULL_AFT,
    "Linear regression", COMPARE_LINES, ANCOVA,
    "Mixed-effects model (REML)", LOGNORMAL, EQUIVALENCE, "Multiple t-tests", ROW_TESTS, "Nonlinear regression", ROBUST_CURVE, CUSTOM_EQUATION,
    MEAN_PERMUTATION,
    GLOBAL_CUSTOM_EQUATION, "Principal component analysis",
    MEAN_PERMUTATION,
    "ROC curve", "Compare paired ROC curves", INDEPENDENT_ROC, precision_recall.METHOD, LOGISTIC_VALIDATION,
    "Smooth / differentiate / integrate", SPLINE_FIT,
    *NESTED_METHODS,
    REFERENCE_NORMALIZATION, SUMMARY_ANOVA, SUMMARY_TTEST, RMST,
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
    # Sums of squares: Type III (also when the key is absent), Type I or Type II. All three share one fit.
    kind = anova_sums_of_squares(o)
    order = o.get("Interaction order", 1) if terms is not None else o["Interaction order"]
    alpha = check_anova_options(o)
    # Field errors name the diagnostic control. The full fit still happens once, on this call.
    validate_anova_diagnostics(o)
    if terms is not None:
        check_anova_comparisons(o, factors, terms)
    # Planned contrasts (0.96): None without contrasts, so the legacy path reads none of the new keys.
    model_factors = anova_active_factors(factors, terms) if terms is not None else list(factors)
    planned = planned_contrasts.check_request(o, model_factors)
    if planned is not None:
        planned_contrasts.check_categories(frame, y, model_factors)
    graph = anova_graph_choice(o)
    if graph != "None":
        count = _anova_row_count(frame, y, anova_active_factors(factors, terms) if terms is not None else factors)
        if count is not None:
            ensure_anova_graph_budget(count, graph)
    table, fit, data, design, beta, error, df = engine._factorial_anova_components(
        frame, y, factors, order, terms=terms, sums_of_squares=kind)
    tables = {ANOVA_SHEETS[kind]: table}
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
    if planned is not None:  # the same fit: design, coefficients, residual SS and df of the table above
        tables.update(planned_contrasts.tables(planned, model_factors, data, design, beta, error, df))
    primary = o.get(anova_grouped_plot.PRIMARY)
    if len(model_factors) > 1 and primary in model_factors:
        try:
            tables[anova_grouped_plot.TABLE] = anova_grouped_plot.observations(data, model_factors, primary)
        except FieldError:
            # A large grouped worksheet can exceed the data limits. Leave the ANOVA
            # available and let its linked graph report that the source table is unavailable.
            pass
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
    if group and (priority := ranks(frame, group)):
        parts = {label: part for label, part in groups}
        groups = [(label, parts[label]) for label in preferred_levels(parts, priority)]
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
    reports = kmeans_reports.requested(o)
    scale = kmeans_options.scale(o)
    fit_options = kmeans_options.fit_options(kmeans_options.CLUSTERING, frame, o)
    fit = engine.kmeans(frame, variables, o["Clusters"], seed=o["Seed"], column_scale=scale,
                        retain_initial=kmeans_reports.CENTROIDS in reports, **fit_options)
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
    _record_kmeans_algorithm(tables["Fit"], o, explicit_start="initial_rows" in fit_options)
    if reports:
        k = len(fit.centers)
        _, values = engine._cluster_data(fit.data, variables, k, scale)
        fitting_data = pd.DataFrame(values, index=fit.data.index, columns=variables)
        tables.update(kmeans_reports.result_tables({k: fit}, frame, fitting_data, reports, column_scale=scale))
    return Result(tables, figure)


def _record_kmeans_algorithm(report, options, *, explicit_start=False):
    algorithm = options.get(kmeans_options.ALGORITHM)
    field = kmeans_options.ITERATION_FIELDS.get(algorithm)
    if field:
        report.loc[kmeans_options.ALGORITHM, "Value"] = algorithm
        report.loc[field, "Value"] = options.get(field, kmeans_options.DEFAULT_ITERATIONS)
        if (not explicit_start and algorithm == kmeans_options.HARTIGAN
                and options.get(kmeans_options.INITIALIZATION) == kmeans_options.KMEANS_PLUS_PLUS):
            report.loc[kmeans_options.INITIALIZATION, "Value"] = kmeans_options.KMEANS_PLUS_PLUS


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
    if o.get(KL_SCALING) == UNSCALED_WSS:
        report[KL_SCALING] = UNSCALED_WSS
    report.update({f"Votes for k = {k}": int(votes) for k, votes in counts.items()})
    tables = {"Cluster metrics": scan.metrics, "Consensus votes": scan.votes, "Selection": _report(report)}
    _record_kmeans_algorithm(tables["Selection"], o)
    if scan.fit is not None:
        label = "Cluster"
        suffix = 2
        while label in scan.fit.data:
            label = f"Cluster ({suffix})"
            suffix += 1
        tables["Assignments"] = scan.fit.data.assign(**{label: scan.fit.labels})
    return Result(tables, figure)


def _cluster_selection(frame, o, *, cancel=None):
    plots = kmeans_options.plot_metrics(o)
    reports = kmeans_reports.requested(o, scan=True)
    scale = kmeans_options.scale(o)
    reference = o.get(kmeans_options.GAP_REFERENCE, kmeans_options.GAP_VARIABLE_RANGES)
    criterion = {"Silhouette": "silhouette", "Elbow": "elbow", "Calinski–Harabasz": "calinski-harabasz",
                 "Davies–Bouldin": "davies-bouldin", "Gap": "gap",
                 "Consensus (17 indices)": "consensus"}[o["Criterion"]]
    scan = kmeans_scan(frame, o["Variables"], o["Maximum k"], seed=o["Seed"], criterion=criterion,
                       column_scale=scale, min_k=o.get("Minimum k", 1), gap_replicates=o.get("Gap simulations", 20),
                       kl_scaling=o.get(KL_SCALING, DIMENSION_ADJUSTED), retain_fits=bool(reports),
                       retain_initial=kmeans_reports.CENTROIDS in reports,
                       include_gap="Gap" in plots, gap_reference=reference, cancel=cancel,
                       archive_options=o if kmeans_archive.ARCHIVE in o else None,
                       **kmeans_options.fit_options(kmeans_options.SELECTION, frame, o))
    result = _consensus_selection(scan, o) if criterion == "consensus" else _scan_result(scan, o, criterion)
    plot_data = kmeans_reports.ModelPlotData(scan.metrics)
    result.table_contexts.update(dict.fromkeys(
        ("Selection", "Cluster metrics" if criterion == "consensus" else "Model metrics"), plot_data))
    if kmeans_archive.ARCHIVE in o:
        if scan.restored:
            origin = "Saved partitions and Gap statistics" if "Gap" in scan.metrics else "Saved partitions"
        else:
            origin = "Recalculated in Trama"
        result.tables["Selection"].loc["Result source", "Value"] = origin
    if reference == kmeans_options.GAP_PRINCIPAL_AXES and "Gap" in scan.metrics and not scan.restored:
        result.tables["Selection"].loc[kmeans_options.GAP_REFERENCE, "Value"] = reference
        result.tables["Selection"].loc["Gap simulations", "Value"] = o.get("Gap simulations", 20)
    if reports:
        result.tables.update(kmeans_reports.result_tables(scan.report_fits, frame, scan.fitting_data, reports,
                                                          metrics=scan.metrics, column_scale=scale))
    primary = {"elbow": "WSS", "consensus": None}.get(criterion, o["Criterion"])
    extra = [metric for metric in plots if metric != primary]
    if extra:
        _add_kmeans_plots(result.figure, scan.metrics, extra)
    return result


def _add_kmeans_plots(figure, metrics, extra):
    count = len(extra) + 1
    rows = (count + 1) // 2
    grid = figure.add_gridspec(rows, 2)
    figure.set_size_inches(9, 6.5 if rows == 2 else 5)
    figure.axes[0].set_subplotspec(grid[0, :] if count == 3 else grid[0, 0])
    slots = list(grid)[2 if count == 3 else 1:]
    for metric, slot in zip(extra, slots, strict=True):
        axes = figure.add_subplot(slot)
        axes.set(title=kmeans_reports.PLOT_TITLES[metric], xlabel="Number of clusters", ylabel=metric)
        axes.spines[["right", "top"]].set_visible(False)
        kmeans_reports.draw_metric(axes, metrics, metric)


def _scan_result(scan, o, criterion):
    metric = {"elbow": "WSS", "gap": "Gap"}.get(criterion, o["Criterion"])
    figure, axes = _plot("K-means model selection", "Number of clusters", metric)
    axes.xaxis.get_major_locator().set_params(integer=True, min_n_ticks=1)
    if criterion == "gap":
        axes.errorbar(scan.metrics.index, scan.metrics[metric], yerr=scan.metrics["Gap SE"], fmt="o-", label=metric)
    else:
        axes.plot(scan.metrics.index, scan.metrics[metric], "o-", label=metric)
    if scan.recommended_k is not None:
        axes.axvline(scan.recommended_k, color="#bb5b3a", linestyle="--", label=f"Suggested k = {scan.recommended_k}")
        axes.legend()
    tables = {"Model metrics": scan.metrics,
              "Selection": _report({"Criterion": o["Criterion"], "Suggested k": scan.recommended_k})}
    _record_kmeans_algorithm(tables["Selection"], o)
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
    return bool(options.get("Log-rank trend") or options.get("Hazard ratio") or
                (options.get(PAIRWISE_CORRECTION, "None") != "None"
                 and pairwise_scope(options) in (CONTROL_PAIRS, SELECTED_PAIRS)))


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


def _pairwise_survival_fdr(report, options, method):
    level = fdr_control.discovery_level(options)
    p = report["p"].to_numpy(dtype=float)
    available = np.isfinite(p)
    report["Adjusted p"] = np.nan
    report["Discovery"] = pd.Series(pd.NA, dtype="boolean", index=report.index)
    family = {"FDR method": method, PAIRWISE_FDR: level,
              "Tests planned": len(p), "Tests used": int(available.sum()), "Discoveries": 0}
    if method == fdr_control.BKY:
        family.update({"Stage-1 discoveries": np.nan, "Estimated true nulls (m0)": np.nan})
    if available.any():
        outcome = fdr_control.adjust_family(p[available], fdr_control.METHOD_CODES[method], level / 100.)
        report.loc[available, "Adjusted p"] = outcome["adjusted"]
        report.loc[available, "Discovery"] = outcome["rejected"]
        family["Discoveries"] = sum(outcome["rejected"])
        if method == fdr_control.BKY:
            family.update({"Stage-1 discoveries": outcome["r1"], "Estimated true nulls (m0)": outcome["m0"]})
    return pd.DataFrame([family])


def _pairwise_survival(frame, options, time, event, group, curves, correction, scope):
    from itertools import combinations
    from .operations import adjust_p

    if len(curves) > 12:
        raise ValueError("Pairwise survival tests support up to twelve groups.")
    if scope == CONTROL_PAIRS:
        resolved = [label for label in curves if str(label) == options[PAIRWISE_CONTROL]]
        if len(resolved) != 1:
            raise FieldError(PAIRWISE_CONTROL, "The control group has no observations for this response.")
        control, = resolved
        pairs = ((control, label) for label in curves if label != control)
    elif scope == SELECTED_PAIRS:
        pairs = options[PAIRWISE_PAIRS]
    else:
        pairs = combinations(curves, 2)
    by_label = {str(label): label for label in curves} if scope == SELECTED_PAIRS else curves
    rows = []
    for first, second in pairs:
        row = {"Comparison": f"{first} / {second}"}
        if scope == SELECTED_PAIRS:
            row.update({"First group": first, "Second group": second})
        if first in by_label and second in by_label:
            labels = [by_label[first], by_label[second]] if scope == SELECTED_PAIRS else [first, second]
            chosen = frame[group].isin(labels)
            _, test = engine.survival(frame.loc[chosen], time, event, group, strict=False)
            row.update(test or {"p": np.nan})
        else:
            row.update(p=np.nan, Status="A selected group has no observations for this response.")
        rows.append(row)
    result = pd.DataFrame(rows)
    if correction in fdr_control.FDR_METHODS:
        family = _pairwise_survival_fdr(result, options, correction)
        return {"Pairwise log-rank": result.set_index("Comparison"), "Pairwise FDR": family}
    adjusted = options.get(PAIRWISE_ADJUSTED, True) and correction != UNADJUSTED
    p = result["p"]
    if correction != UNADJUSTED and p.notna().any():
        p = adjust_p(result, "p", PAIRWISE_METHODS[correction])["Adjusted p"]
        if adjusted:
            result["Adjusted p"] = p
    if not adjusted:
        alpha = options.get(PAIRWISE_ALPHA, .05)
        result["Significant"] = p.lt(alpha).astype("boolean").where(p.notna())
    return {"Pairwise log-rank": result.set_index("Comparison")}


def _survival(frame, o, axes=None, compact=False, risk_axes=None):
    time, event, group = o["Time"], o["Event"], o.get("Group")
    level = float(o.get("Confidence level (%)", 95.0))
    settings = survival_graph_settings(o)
    show_error = settings[UNCERTAINTY] == ERROR_BARS or settings[INTERVAL] == GREENWOOD
    curves, comparison = engine.survival(frame, time, event, group, level=level, strict=False,
                                         standard_error=show_error)
    graph_data = SurvivalGraphData(curves, settings, time, level, bool(o.get(RISK_TABLE)),
                                   compact and not _has_survival_orientation(o))
    simultaneous = {}
    figure, tables, risks = draw_survival_graph(graph_data, "Kaplan–Meier survival" if axes is None else event,
                                               axes, risk_axes, bands=simultaneous)
    plateau = o.get("Median method") == MEDIAN_METHODS[1]
    summaries = []
    for label, curve in curves.items():
        median, lower, upper = engine.survival_median(curve, level, plateau)
        summaries.append({"Group": str(label), "N": curve["At risk"].iloc[0],
                          "Events": curve["Events"].sum(), "Censored": curve["Censored"].sum(),
                          "Median survival": median, "Median CI lower": lower, "Median CI upper": upper,
                          "Median CI level (%)": level})
    risk_output = risks
    if compact:
        risk_output = risks.reset_index().melt(id_vars="Group", var_name="Time", value_name="At risk").set_index("Group")
    outputs = {SURVIVAL_SUMMARY: pd.DataFrame(summaries).set_index("Group"), "Number at risk": risk_output}
    if comparison:
        outputs["Log-rank test"] = _report(comparison).rename_axis("Metric")
    elif len(curves) > 1 and sum(curve["Events"].sum() for curve in curves.values()):
        outputs["Log-rank test"] = _report({
            "Status": "Not available",
            "Reason": "The groups do not share enough risk sets with events for this comparison."}).rename_axis("Metric")
    outputs.update(_survival_extras(frame, o, time, event, group, level, len(curves)))
    correction = o.get(PAIRWISE_CORRECTION, "None")
    scope = pairwise_scope(o)
    if group and correction != "None" and (len(curves) > 1 or scope == SELECTED_PAIRS):
        outputs.update(_pairwise_survival(frame, o, time, event, group, curves, correction, scope))
    if compact:
        outputs["Survival curves"] = pd.concat({label: table.rename_axis("Time point")
                                                for label, table in tables.items()}, names=["Group"])
    else:
        outputs.update({f"Curve: {label}": table for label, table in tables.items()})
    if simultaneous:
        outputs[SIMULTANEOUS_SHEET] = join_bands(simultaneous)
    context = {SURVIVAL_SUMMARY: graph_data} if o.get(SURVIVAL_GRAPH) is True else {}
    return Result(outputs, figure, table_contexts=context)


def _nonlinear(frame, o, axes=None, compact=False, *, parameter_budget=None, range_settings=None, outside=None,
               plot_grid=None, plot_observations=True):
    x, y, model = o["X"], o["Y"], o["Model"]
    report_log_ic50 = o.get(REPORT_LOG_IC50) is True and has_ic50(model)
    # Band fields are checked before any fit; Band=None ignores stale level and drawing.
    band = band_settings(o)
    parameter_config = parameter_ci_settings(o)
    parameter_budget = parameter_budget if parameter_budget is not None else ProfileBudget()
    range_settings = range_settings or {}
    fixed = o.get(engine.FIXED_COEFFICIENTS)
    if fixed and parameter_config.method != WALD:
        raise ValueError("Use Wald intervals for this fit with fixed coefficients.")
    fits = engine.nonlinear(frame, x, y, model, o.get("Group"),
                            weighting=o.get("Weighting", "Unweighted"), sigma=o.get("SD column"),
                            fixed=fixed, start=o.get(engine.STARTING_COEFFICIENTS),
                            series_start=o.get(engine.STARTING_COEFFICIENTS_BY_SERIES) if o.get(MERGE_REPLICATES)
                            else None)
    interval_band = o.get(FIT_INTERVAL_BAND) if (
        axes is None and model == LOG_DOSE_MODEL and len(fits) == 1 and not o.get("Group")
    ) else None
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
    fit_bounds = {field: range_settings[field] for field in regression_range.FIT_FIELDS if field in range_settings}
    observations = {}
    group = o.get("Group")
    colors = {}
    for label, fit in fits.items():
        xy = fit.data
        if outside is not None and not outside.empty:
            more = outside if not group else outside.loc[outside[group] == label]
            xy = pd.concat((xy[[x, y]], regression_range.extra_xy(more, x, y)), ignore_index=True)
        observations[label] = xy
        dots = axes.scatter(xy[x], xy[y], label=str(label), visible=plot_observations)
        if group:
            dots._tramastat_legend_key = f"group:{typed_group_token(label)}"
        colors[label] = dots.get_facecolor()[0]
        grid = regression_range.drawing_grid(fit.data[x], range_settings)
        if grid is not None:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                predicted = engine.MODELS[model].equation(grid, *fit.parameters["Estimate"])
            coords = regression_range.coordinate_table(grid, predicted, fit.data[x])
            tables.setdefault(regression_range.CURVE_SHEET, {})[label] = coords.rename_axis("Sample")
            fit.curve = coords[["X", "Predicted"]].to_numpy()
        curve_x, curve_y = fit.curve.T
        if plot_grid is not None:
            curve_x = plot_grid
            curve_y = engine.MODELS[model].equation(curve_x, *fit.parameters["Estimate"])
            if not np.isfinite(curve_y).all():
                raise FieldError(regression_range.CURVE_MAX, "The model must predict finite values on the drawn curve.")
        axes.plot(curve_x, curve_y, color=colors[label])
        if residual_axes is not None:
            residual_axes.scatter(fit.residuals["X"], fit.residuals["Residual"], color=colors[label])
        parameters, parameter_status = parameter_outputs(fit, model, parameter_config, budget=parameter_budget)
        if interval_band is not None:
            draw_fit_interval_band(axes, interval_band, parameters, parameter_config.level)
        tables["Parameters"][label] = parameters.rename_axis("Parameter")
        if parameter_status is not None:
            tables.setdefault("Parameter CI status", {})[label] = parameter_status.rename_axis("Parameter")
        if report_log_ic50:
            tables.setdefault(TRANSFORMED_PARAMETERS, {})[label] = log_ic50_table(parameters)
        tables["Fit"][label] = _report({**fit.diagnostics, **fit_bounds}).rename_axis("Metric")
        tables["Residuals"][label] = fit.residuals.rename_axis("Source row")
    if model == "Normalized inhibition" or plot_grid is not None:
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
    if FIT_GRAPH_SPEC in o:
        points = fitted_graph_points(fits, model, x, y, o[FIT_GRAPH_SPEC], observations=observations,
                                     custom_range=any(field in range_settings for field in regression_range.CURVE_FIELDS))
        if points is not None:
            outputs[FIT_GRAPH_POINTS] = points
    return Result(outputs, figure)


INDEXLESS = {SIMULTANEOUS_SHEET}  # their rows carry Group and Time as columns: no index to keep


def _by_response(title, parts):
    """One sheet for several responses: a Response variable column in front of the rows of each."""
    table = pd.concat(parts, names=["Response variable"])
    return table.reset_index(level=0).reset_index(drop=True) if title in INDEXLESS else table.reset_index()


def _classic_analysis(method, frame, options, predict, run, *, outside=None):
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
    frame, group, outside = _combined_groups(frame, options[predict], responses, groups,
                                             numbered=not stable_groups, outside=outside)
    extra_options = {"outside": outside} if outside is not None else {}
    if len(responses) == 1:
        compact = len(groups) > 1
        result = run(frame, {**options, response_key: responses[0], "Group": group}, compact=compact,
                     **extra_options)
        if compact:
            result.tables = {title: table.reset_index(drop=title in INDEXLESS) for title, table in result.tables.items()}
        return result
    rows = (len(responses) + 1) // 2
    has_risks = method == "Kaplan–Meier survival" and options.get("Show risk table below graph")
    figure = Figure(figsize=(9, (4.5 if has_risks else 3.4) * rows), dpi=100, layout="constrained")
    figure.suptitle(options["Model"] if method == "Nonlinear regression" else method)
    grid = figure.add_gridspec(rows, 2)
    tables = {}
    for i, response in enumerate(responses):
        panel = grid[i // 2, i % 2]
        extras = dict(extra_options)
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
    return Result({title: _by_response(title, parts) for title, parts in tables.items()}, figure)


def _imported_xy(frame, options, layout_data=None):
    from .legacy_binary_range import BINARY_XY_RANGE, render_binary_range
    from .legacy_mv_scatter import APPEARANCE, CLUSTERED_SCATTER, appearance_record, apply_axes, clustered_points
    from .legacy_xml_binding_layout import XML_BINDING_XY, render_binding_graph
    from .legacy_xml_qc import XML_QC, render_qc_graph
    from .legacy_xml_xy import XML_ERROR_BARS, render_xml_error_graph
    from .legacy_xml_generated import XML_GENERATED_XY, render_generated_graph
    from .legacy_zip_column import ZIP_COLUMN, render_aligned_column
    from .legacy_zip_xy import ZIP_SPARSE_XY, render_sparse_xy

    if options.get(SURVIVAL_GRAPH) is True:
        return linked_survival_graph(frame, options.get(LEGACY_TITLE, "Kaplan–Meier survival"),
                                     options.get(SURVIVAL_SERIES, []))
    if BINARY_XY_RANGE in options:
        return render_binary_range(frame, options[BINARY_XY_RANGE], options[LEGACY_TITLE])
    if XML_GENERATED_XY in options:
        return render_generated_graph(frame, options[XML_GENERATED_XY])
    if XML_QC in options:
        return render_qc_graph(frame, options[XML_QC])
    if XML_ERROR_BARS in options:
        return render_xml_error_graph(frame, options)
    if XML_BINDING_XY in options:
        binding = (layout_data or {}).get("binding")
        return render_binding_graph(frame, options[XML_BINDING_XY], options.get(LEGACY_TITLE, "Binding"),
                                    binding=binding)
    if ZIP_SPARSE_XY in options:
        return render_sparse_xy(frame, options[ZIP_SPARSE_XY], options.get(LEGACY_TITLE, "Imported XY graph"))
    if ZIP_COLUMN in options:
        return render_aligned_column(frame, options[ZIP_COLUMN])

    style = appearance_record(options[APPEARANCE]) if APPEARANCE in options else None
    if CLUSTERED_SCATTER in options:
        if style is None:
            raise ValueError("Invalid linked cluster scatter appearance.")
        frame = clustered_points(frame, options[CLUSTERED_SCATTER], style["palette"])
    text = ["Series", "Geometry"]
    if options.get(FIT_GRAPH) is True and options.get(FIT_GRAPH_OBSERVATIONS) is False:
        frame = frame.loc[frame["Geometry"] == "line"]
    if "Observation" in frame:
        text.append("Observation")
    data = engine.complete(frame, ["X", "Y", "Dataset"], text)
    if data.empty:
        raise ValueError("The saved graph has no complete XY points.")
    figure, axes = _plot(options.get(LEGACY_TITLE, "Imported XY graph"), options.get("X label", "X"),
                         options.get("Y label", "Y"))
    colors = {}
    markers, captions = [], []
    error_columns = ["Y minus", "Y plus"]
    if all(column in frame for column in error_columns):
        data = data.join(frame[error_columns], validate="one_to_one")
    for _, group in data.groupby("Dataset", sort=style is not None):
        labels, shapes = group["Series"].unique(), group["Geometry"].unique()
        if len(labels) != 1 or len(shapes) != 1:
            raise ValueError("Each saved graph series needs one label and geometry.")
        label, geometry = labels[0], shapes[0]
        if style is not None and geometry != "points":
            raise ValueError("This saved scatter requires point geometry.")
        display = str(label) if label not in colors else "_nolegend_"
        color = style["palette"].get(label) if style is not None else colors.get(label)
        if geometry == "line":
            artist, = axes.plot(group["X"], group["Y"], color=color, label=display)
            color = artist.get_color()
        elif geometry == "step":
            artist, = axes.step(group["X"], group["Y"], where="post", color=color, label=display)
            color = artist.get_color()
        elif geometry == "points":
            marker = {} if style is None else {"edgecolors": style["edge"], "linewidths": style["width"]}
            size = 20 if style is None else style["size"] ** 2
            artist = axes.scatter(group["X"], group["Y"], color=color, label=display, s=size, **marker)
            if style is not None and label not in colors:
                markers.append(artist)
                captions.append(str(label))
            color = artist.get_facecolor()[0]
        else:
            raise ValueError("Invalid geometry in a saved legacy series.")
        if all(column in group for column in error_columns):
            errors = group[error_columns].to_numpy(dtype=float, na_value=np.nan)
            valid = np.isfinite(errors) & (errors >= 0)
            present = valid.any(axis=1)
            if present.any():
                axes.errorbar(group["X"].to_numpy()[present], group["Y"].to_numpy()[present],
                              yerr=np.where(valid, errors, 0)[present].T, fmt="none", ecolor=color, alpha=.55)
        colors[label] = color
    if style is not None:
        apply_axes(axes, style)
        legend = axes.legend(markers, captions, title=style["legend"], ncols=(len(markers) + 9) // 10)
        for label in [legend.get_title(), *legend.get_texts()]:
            label.set_parse_math(False)
    elif len(colors) <= 15:
        axes.legend()
    if options.get(FIT_GRAPH) is True and type(options.get(FIT_GRAPH_TICKS)) is bool:
        from matplotlib.ticker import NullLocator

        from .axis_breaks import ConcentrationMinorLocator, PowerOfTenFormatter

        axes.xaxis.set_major_formatter(PowerOfTenFormatter())
        axes.xaxis.set_minor_locator(ConcentrationMinorLocator() if options[FIT_GRAPH_TICKS] else NullLocator())
    return Result({"Saved XY coordinates": data}, figure)


def _preview_figure(image):
    figure = Figure(figsize=(image.width / 144, image.height / 144), dpi=144)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.imshow(image)
    axes.set_axis_off()
    axes._tramastat_non_native = True
    return figure


def _imported_layout(options, layout_data=None):
    from .legacy_binary_graphs import render_binary_graph, validate_binary_graph
    from .legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_EDITS, edited_layout_preview

    if LEGACY_PREVIEW in options:
        preview = edited_layout_preview(options[LEGACY_PREVIEW], options.get(LEGACY_EDITABLE_PANELS),
                                        options.get(LEGACY_PANEL_EDITS), layout_data)
        return _preview_figure(render_binary_graph(preview, layout=True, crop=False))
    panels = options.get(LEGACY_LAYOUT_PANELS)
    if not isinstance(panels, list) or not 1 <= len(panels) <= 24:
        raise ValueError("Invalid saved legacy layout placements.")
    placements, bytes_used = [], 0
    for panel in panels:
        if not isinstance(panel, dict) or not isinstance(bounds := panel.get("bounds"), list) or len(bounds) != 4:
            raise ValueError("Invalid saved legacy layout placement.")
        if any(type(value) is not int or not -32768 <= value <= 32767 for value in bounds):
            raise ValueError("Invalid saved legacy layout coordinates.")
        x0, y0, x1, y1 = bounds
        if x0 >= x1 or y0 >= y1:
            raise ValueError("Invalid saved legacy layout rectangle.")
        preview = panel.get("preview")
        if preview is not None:
            validate_binary_graph(preview)
            bytes_used += len(preview["data"])
        placements.append((bounds, preview))
    if bytes_used == 0 or bytes_used > MAX_LAYOUT_PANEL_DATA:
        raise ValueError("Invalid saved legacy layout artwork.")
    left, top = (min(bounds[i] for bounds, _ in placements) for i in (0, 1))
    right, bottom = (max(bounds[i] for bounds, _ in placements) for i in (2, 3))
    width, height = right - left, bottom - top
    if max(width, height) > 100 * min(width, height):
        raise ValueError("Invalid saved legacy layout aspect ratio.")
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


# Linked secondary axes (analisi.linked_axes): the dimensions each analysis graph can link. Graphs that draw
# XY series, XY error bars and global fits mark their own Axes; the checks of the current figure (one plot
# panel, numeric axes, no breaks) run when the axes are drawn.
LINKED_AXES_METHODS = {
    "Linear regression": ("x", "y"), COMPARE_LINES: ("x", "y"), "Deming regression": ("x", "y"),
    "Nonlinear regression": ("x", "y"), ROBUST_CURVE: ("x", "y"), CUSTOM_EQUATION: ("x", "y"),
    GLOBAL_CUSTOM_EQUATION: ("x", "y"), SPLINE_FIT: ("x", "y"), "Kaplan–Meier survival": ("x", "y"),
    COLUMN_GRAPH: ("y",), GROUPED_GRAPH: ("y",),
}


def analyse(method, frame, options, *, layout_data=None, cancel=None, join_data=None):
    """Calculate ``method`` on ``frame`` and mark its graph for linked secondary axes."""
    result = _analyse(method, frame, options, layout_data=layout_data, cancel=cancel, join_data=join_data)
    dimensions = LINKED_AXES_METHODS.get(method)
    figure = result.figure if dimensions else None
    if figure is not None and figure.axes and not hasattr(figure.axes[0], SUPPORT_ATTR):
        mark_linked_axes(figure.axes[0], *dimensions)
    return result


def _analyse(method, frame, options, *, layout_data=None, cancel=None, join_data=None):
    """Calculate ``method`` on ``frame``. ``join_data`` is the evaluated right worksheet of
    Join worksheets by key, already resolved by the application (the engine never looks sheets up)."""
    from .legacy_xml_binding import SCATCHARD, scatchard

    o = options
    if method == WORKSHEET_JOIN:
        return join_worksheets(frame, join_data, o, cancel=cancel)
    if o.get("Linear trend") and method != "One-way ANOVA":
        from .trend_anova import reject_unless_one_way
        reject_unless_one_way(method)
    if method == SAVED_XY:
        return _imported_xy(frame, o, layout_data)
    if method == SCATCHARD:
        return scatchard(frame, o)
    if method == SAVED_BINARY_RESULT:
        return Result({o.get(LEGACY_RESULT_SHEET, "Saved results"): frame})
    if method == SAVED_BINARY_GRAPH:
        from .legacy_binary_graphs import render_binary_graph

        return Result({}, _preview_figure(render_binary_graph(o.get(LEGACY_PREVIEW))))
    if method == SAVED_BINARY_LAYOUT:
        from .legacy_layout_edit import LEGACY_PANEL_DATA
        from .legacy_zip_layout import ZIP_LAYOUT, render_positioned_layout

        if ZIP_LAYOUT in o:
            panels = (layout_data or {}) if LEGACY_PANEL_DATA in o else None
            return Result({}, render_positioned_layout(frame, o[ZIP_LAYOUT], panels))
        return Result({}, _imported_layout(o, layout_data))
    if method == SAVED_EDITABLE_GRAPH:
        from .legacy_emf_edit import CURVE, POINTS, edit_emf_preview
        from .legacy_pdf_stacks import STACK_KIND, render_pdf_stack

        style = o.get(LEGACY_GRAPH_STYLE)
        if isinstance(style, dict) and style.get("kind") == STACK_KIND:
            return Result({}, _preview_figure(render_pdf_stack(frame, style, o.get(LEGACY_PREVIEW))))
        if isinstance(style, dict) and style.get("kind") in (CURVE, POINTS):
            from .legacy_binary_graphs import render_binary_graph

            preview = edit_emf_preview(frame, style, o.get(LEGACY_PREVIEW))
            return Result({}, _preview_figure(render_binary_graph(preview)))
        if isinstance(style, dict) and style.get("kind") == "columns":
            from .legacy_binary_bars import edit_bar_preview
            from .legacy_binary_graphs import render_binary_graph

            preview = edit_bar_preview(frame, style, o.get(LEGACY_PREVIEW))
            return Result({}, _preview_figure(render_binary_graph(preview)))
        from .legacy_binary_editable import render_editable_graph

        figure = render_editable_graph(frame, style)
        figure.axes[0]._tramastat_numeric_axes = ("x", "y")
        return Result({}, figure)
    if method == "Descriptive statistics":
        if o.get(engine.SUMMARY_FORMAT) == engine.GEOMETRIC_REPORT:
            summary = engine.describe(frame, o["Variables"], geometric_report=True,
                                      level=engine.summary_confidence(o), total=o.get(engine.SUMMARY_SUM, True))
            return Result({"Summary": summary})
        from .legacy_xml_qc import QC_REFERENCE, qc_summary

        summary = engine.describe(frame, o["Variables"], geometric=bool(o.get(GEOMETRIC_MEAN)))
        tables = qc_summary(frame, summary, o[QC_REFERENCE]) if QC_REFERENCE in o else {"Summary": summary}
        return Result(tables)
    if method == TOLERANCE:
        return tolerance_intervals(frame, o)
    if method == NORMALITY:
        # Recipes saved before the test choices existed keep the Shapiro–Wilk "Normality" sheet.
        return _normality(frame, o) if legacy_normality(o) else normality(frame, o)
    if method == "t-test":
        layout, level, alternative = ttest_options.check(o)
        mode = o["Design"].lower()
        detailed = o.get(ttest_options.DETAILS) is True
        reverse = o.get(ttest_options.REVERSE) is True
        if layout == ttest_options.COLUMNS:
            first, second = o[ttest_options.FIRST], o[ttest_options.SECOND]
            if reverse:
                first, second = second, first
            summary, a, b = engine.t_test_columns(frame, first, second, mode, o.get("Subject"),
                                                  level=level, alternative=alternative, detailed=detailed)
            response = None
        else:
            response = o["Response"]
            summary, a, b = engine.t_test(frame, response, o.get("Group"), mode, o.get("Subject"),
                                          order=o.get("Group order"), null=o.get("Null mean", 0.0),
                                          return_samples=True, level=level, alternative=alternative,
                                          reverse=reverse, detailed=detailed)
        tables = {"t-test": _report(summary)}
        plot = shows_paired_estimation(method, o)
        if plot:
            return Result(tables, paired_estimation_figure(a, b, summary, response, level=level))
        attach_ttest(a, b, o, tables, level=level)
        return Result(tables)
    if method == "Paired t-test (columns)":
        return Result({"t-test": _report(engine.paired_t_test(frame, o["First"], o["Second"]))})
    if method == LOGNORMAL:
        return lognormal_test(frame, o)
    if method == VARIANCE_RATIO:
        return variance_ratio_analysis(frame, o)
    if method == EQUIVALENCE:
        return equivalence_test(frame, o)
    if method == MEAN_PERMUTATION:
        return permutation_test(frame, o, cancel=cancel)
    if method == YUEN:
        return yuen_test(frame, o)
    if method == COHEN_KAPPA:
        return cohen_kappa(frame, o, cancel=cancel)
    if method == COMPETING_RISKS:
        return competing_risks(frame, o, cancel=cancel)
    if method == COX_REGRESSION and is_cox_exact(o):
        return cox_exact_result(frame, o, cancel=cancel)
    if method == WEIBULL_AFT:
        return weibull_aft(frame, o)
    if method == ORDINAL_LOGIT:
        return ordinal_logit(frame, o)
    if method == RMST:
        return rmst(frame, o)
    if method == SUMMARY_ANOVA:
        return summary_anova(frame, o)
    if method == SUMMARY_TTEST:
        return summary_ttest(frame, o)
    if method == MEAN_PERMUTATION:
        return permutation_test(frame, o, cancel=cancel)
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
    if method == RMCORR:
        return rmcorr_analysis(frame, o, cancel=cancel)
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
    if method == PAIRED_PROPORTIONS:
        return paired_proportions(frame, o)
    if method == PARTS_GRAPH:
        return parts_graph(frame, o)
    if method == GOODNESS_OF_FIT:
        return goodness_of_fit(frame, o)
    if method == "Linear regression":
        return linear_result(frame, o)
    if method == COMPARE_LINES:
        return compare_lines(frame, o)
    if method == ANCOVA:
        return ancova(frame, o)
    if method == "Nonlinear regression":
        parameter_ci_settings(o)
        check_fit_options(o)
        ranges = regression_range.ranges(o)
        if o.get(regression_range.SHOW_OUTSIDE) is True:
            frame, outside = regression_range.fitting_rows(frame, o["X"], ranges, return_outside=True)
        else:
            frame = regression_range.fitting_rows(frame, o["X"], ranges)
            outside = None
        fit = partial(_nonlinear, parameter_budget=ProfileBudget(cancel), range_settings=ranges)
        if o.get(MERGE_REPLICATES) is True:
            data = stack_replicates(frame, o)
            settings = {**o, "X": "X", "Y": "Response", "Group": "Series", "SD column": "SD"}
            extra = None if outside is None or outside.empty else stack_replicates(outside, o)
            saved = o.get(FIT_GRAPH_SPEC)
            bound_preview = (isinstance(saved, dict) and saved.get("model") == o["Model"] and saved.get("x") == o["X"]
                             and saved.get("series") == o.get("Y columns")
                             and all(field in ranges and ranges[field] == saved.get(field)
                                     for field in regression_range.CURVE_FIELDS))
            plot_grid = None
            if (bound_preview and saved.get("spacing") == "log"
                    and ranges[regression_range.CURVE_MIN] > 0):
                plot_grid = np.geomspace(*(ranges[field] for field in regression_range.CURVE_FIELDS))
            plot_observations = not bound_preview or saved.get("observations") is not False
            result = fit(data, settings, outside=extra, plot_grid=plot_grid, plot_observations=plot_observations)
            for axes in result.figure.axes:
                axes.set_xlabel(o["X"], parse_math=False)
            return result
        return _classic_analysis(method, frame, o, "X", fit, outside=outside)
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
    if method == grouped_anova.METHOD:
        long, response, factors = grouped_anova.grouped_inputs(frame, o)
        table = engine.factorial_anova(long, response, factors, 2 if o.get(grouped_anova.INTERACTION, True) else 1)
        return Result({"ANOVA (type III)": table})
    if method == NB2:
        return nb2_analysis(frame, o)
    if method == "Multifactor ANOVA":
        return _anova(frame, o)
    if method == anova_comparison_plot.METHOD:
        return anova_comparison_plot.comparison_plot(frame)
    if method == anova_diagnostics.METHOD:
        return anova_diagnostics.linked_plot(frame, o)
    if method == anova_grouped_plot.METHOD:
        return anova_grouped_plot.graph(frame, o)
    if method == KMEANS_STABILITY:
        return kmeans_stability(frame, o, cancel=cancel)
    if method == LOGISTIC_VALIDATION:
        return logistic_validation(frame, o, cancel=cancel)
    if method in kmeans_options.METHODS:
        try:
            if method == kmeans_options.SELECTION:
                return _cluster_selection(frame, o, cancel=cancel)
            return _kmeans(frame, o)
        except IterationLimitError as error:
            field = kmeans_options.ITERATION_FIELDS[o[kmeans_options.ALGORITHM]]
            raise FieldError(field, str(error)) from error
    if method == "Kaplan–Meier survival":
        return _classic_analysis(method, frame, o, "Time", _survival)
    if method == "Hierarchical clustering":
        return hierarchical_result(frame, o, cancel=cancel)
    if method == HIERARCHY_GRAPH:
        return hierarchy_graph(frame, o, cancel=cancel)
    if method == kmeans_reports.MODEL_GRAPH:
        return kmeans_reports.model_plot(frame, o)
    if method == CLUSTER_SILHOUETTE:
        return cluster_silhouette(frame, o, cancel=cancel)
    if method == SELECT_TRANSFORM:
        return select_transform(frame, o)
    if method == EXTRACT_REARRANGE:
        return extract_rearrange(frame, o)
    if method == TRANSPOSE_XY:
        return transpose_xy(frame, o)
    if method == RESHAPE_LONG_WIDE:
        return reshape_long_wide(frame, o, cancel=cancel)
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
    if method == GROUPED_DISTRIBUTIONS:
        return grouped_distributions(frame, o)
    if method == BEFORE_AFTER:
        return before_after(frame, o)
    if method == TRAJECTORIES:
        return subject_trajectories(frame, o)
    if method == FOREST_PLOT:
        return forest_plot(frame, o)
    if method == META_ANALYSIS:
        return meta_analysis(frame, o, cancel=cancel)
    if method == OUTLIERS:
        return identify_outliers(frame, o)
    if method == MONTE_CARLO:
        return monte_carlo(frame, o)
    if method == INDEPENDENT_ROC:
        return independent_roc(frame, o, cancel=cancel)
    if method == ba_repeated.METHOD:
        return ba_repeated.analyse(frame, o, cancel=cancel)
    if method == icc.METHOD:
        return icc.analyse(frame, o, cancel=cancel)
    if method == precision_recall.METHOD:
        return precision_recall.analyse(frame, o, cancel=cancel)
    if method == "Histogram":
        return _distribution(method, frame, o)
    if method == REFERENCE_NORMALIZATION:
        return normalize_to_references(frame, o)
    return extra_analysis(method, frame, o)
