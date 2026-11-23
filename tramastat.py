"""Trama desktop entry point."""
import sys

if __name__ == "__main__":
    # First statement on purpose: in the Windows portable build every calculation process starts this same
    # executable, and freeze_support() turns it into a worker before any window or import happens.
    import multiprocessing
    multiprocessing.freeze_support()

if __name__ == "__main__":
    requested = {"--tk", "--qt"}.intersection(sys.argv[1:])
    if len(requested) > 1:
        raise SystemExit("Choose either --tk or --qt.")
    sys.argv[1:] = [argument for argument in sys.argv[1:] if argument not in requested]
    classic_smoke = "--smoke" in sys.argv[1:] and "--qt" not in requested

if __name__ == "__main__" and not classic_smoke:
    if "--qt" in requested:
        from trama_qt import qt_available
        if not qt_available():
            raise SystemExit("Qt (PySide6) is not available.")
        from trama_qt.app import main as qt_main
        raise SystemExit(qt_main())
    from trama_startup import launch
    raise SystemExit(launch())

from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
from uuid import uuid4
import os
from pathlib import Path
import shutil
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import traceback

import matplotlib.colors as mcolors
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.colors import is_color_like, to_hex
import numpy as np
import pandas as pd

from analisi._version import VERSION, RELEASE_CHANNEL
from analisi.analysis_chain import MAX_ANALYSIS_NODES, ChainCancelled, ResultSource
from analisi.analysis_chain_app import AnalysisChainMixin
from analisi.family_workflow_app import FamilyWorkflowMixin
from analisi.windows_dpi import configure_native_dpi, window_dpi
from analisi.window_geometry import clamp_rect, keep_native_window_on_screen
from analisi.shape_canvas import ShapeCanvas, ShapeHistory, render_shapes
from analisi.layout_geometry import AUTO_PAPER, PAPER_SIZES, WHITE, page_size
from analisi.category_graphs import (BARS, COLUMN_GRAPH, GROUPED_GRAPH, GROUPED_STYLES, PAIRED, POINTS, RANGE,
                                     STACKED_PLACEMENTS, SUMMARIES, SUMMARY_STYLES, default_grouped_input)
from analisi.contingency import (AUTO as CONTINGENCY_AUTO, BAPTISTA_PIKE, CONTINGENCY, COUNT_MATRIX, FISHER, FISHER_RXC, MONTE_CARLO,
                                 check_contingency_options, default_count_matrix)
from analisi.nested import (CONFIRM as NESTED_CONFIRM, METHODS as NESTED_METHODS, NESTED_T,
                            SUBCOLUMNS as NESTED_SUBCOLUMNS, is_nested_worksheet, nested_defaults,
                            preferred_nested_method)
from analisi.correlation_matrix import CORRELATION_MATRIX
from analisi.data import (EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_FIXED_VALUES, MAX_CELLS, MAX_COLUMNS, Dataset, _table, decimal_comma, info_references, load_project, load_tables,
                          load_workspace, save_project)
from analisi.ellipse_workbench import (BY_GROUP as ELLIPSE_BY_GROUP, ELLIPSE_TABS, GROUP_STYLES as ELLIPSE_GROUP_STYLES,
                                     ellipse_grouping_column, ellipse_visibility)
from analisi.equation_dialog import EquationDialog
from analisi.function_editor import CurveEditor
from analisi.model_picker import ModelPicker
from analisi.model_selection import COMPARE_MODELS, MODEL_LIST, MODELS_FIELD, SHOW_GRAPH as MODELS_SHOW_GRAPH
from analisi.grouped_anova import METHOD as GROUPED_ANOVA, ROWS as GROUPED_ANOVA_ROWS
from analisi.extract_rearrange import (COMPLETE as EXTRACT_COMPLETE, EXTRACT_FIELDS, EXTRACT_REARRANGE,
                                     OUTPUT as EXTRACT_OUTPUT, PREFIX as EXTRACT_PREFIX)
from analisi.bubble import BUBBLE, MAX_AREA as BUBBLE_MAX_AREA, SHEET as BUBBLE_SHEET
from analisi.compare_lines import (COMPARE_LINES, COMPARISON_SHEET as LINE_COMPARISON_SHEET, WIDE as LINES_WIDE,
                                   visibility as compare_lines_visibility)
from analisi.distribution_graphs import (BOX_VIOLIN, SEPARATE as BOX_SEPARATE,
                                         visibility as box_violin_visibility)
from analisi.grouped_distributions import GROUPED_DISTRIBUTIONS, visibility as grouped_distribution_visibility
from analisi.paired_graphs import (AFTER, BEFORE, BEFORE_AFTER, MAX_PAIRS, PAIR_LIST, PAIRS as BEFORE_AFTER_PAIRS,
                                   TITLE as PAIR_TITLE, TRAJECTORIES, TTEST_ESTIMATION, shows_paired_estimation,
                                   trajectory_defaults)
from analisi.forest_plot import (BY_COLUMN as FOREST_BY_COLUMN, FOREST_PLOT, LIMITS_NOTE as FOREST_LIMITS_NOTE,
                                  REFERENCE_NOTE as FOREST_REFERENCE_NOTE, ROLE_ROWS as FOREST_ROLE_ROWS,
                                  ROW_CHOICE as FOREST_ROW_CHOICE, defaults_for as forest_defaults,
                                  guess_role_rows, row_choices as forest_row_choices,
                                  visibility as forest_visibility)
from analisi.auc_peaks import (HEIGHT as AUC_HEIGHT, PEAKS as AUC_PEAKS, WIDTH as AUC_WIDTH,
                               check_options as check_auc_options)
from analisi.frequency import (EXACT as EXACT_FREQUENCY, FREQUENCY, style_after_parameter_change as frequency_style,
                               visibility as frequency_visibility)
from analisi.gallery import SheetGallery, figure_thumbnail, image_thumbnail, table_thumbnail
from analisi.axis_breaks import AXIS_BREAKS, axis_breaks_reason, segment_axes
from analisi.graph_dialog import ChoiceBinding, GraphFormatDialog, pick_color
from analisi.graph_annotations import ANNOTATIONS
from analisi.graph_shapes import SHAPES, skipped_shapes
from analisi.grid_data import (clear_block, clipboard_decimal_mark, clipboard_rows, copy_block,
                               edit_cell_value, filter_clipboard_rows, grow_rows, paste_block)
from analisi.grid_widget import DataGrid, column_label
from analisi.heatmap import (CATEGORY_COLOR_LIST, CATEGORY_COLORS as HEAT_MAP_CATEGORY_COLORS,
                            COLOR_MAPPING as HEAT_MAP_MAPPING, HEAT_MAP, LEGEND_INTERVAL as HEAT_MAP_INTERVAL,
                            GRADIENT_COLORS as HEAT_MAP_GRADIENT_COLORS, MAX_COLOR as HEAT_MAP_MAX_COLOR, MID_COLOR as HEAT_MAP_MID_COLOR,
                            MIN_COLOR as HEAT_MAP_MIN_COLOR, OPTIONS as HEAT_MAP_OPTIONS, OUTSIDE as HEAT_MAP_OUTSIDE,
                            SHOW_LEGEND as HEAT_MAP_SHOW_LEGEND, TAB_LAYOUT as HEAT_MAP_TAB_LAYOUT,
                            TABS as HEAT_MAP_TABS, category_levels, visibility as heat_map_visibility)
from analisi.heatmap_dialog import CategoryColorsField
from analisi.heatmap_cell_labels import (CELL_LABEL_COLOR, CELL_LABEL_COLOR_MODE, CELL_LABEL_COLOR_MODES,
                                         CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE, CELL_LABEL_NUMBER_FORMAT,
                                         CELL_LABEL_NUMBER_FORMATS, DEFAULT_LABEL_COLOR,
                                         parse_cell_label_decimals, parse_cell_label_font_size)
from analisi.heatmap_layout import (COLUMN_GAP_MODE, COLUMN_GAP_SIZE, COLUMN_GAPS_AFTER,
                                    COLUMN_LABEL_EVERY, COLUMN_LABEL_FONT_SIZE, COLUMN_LABEL_FREQUENCY,
                                    COLUMN_LABEL_ROTATION, COLUMN_LABEL_ROTATIONS, COLUMN_LABEL_SIDE,
                                    COLUMN_LABEL_SIDES, GAP_MODES, LABEL_FREQUENCIES,
                                    ROW_GAP_MODE, ROW_GAP_SIZE, ROW_GAPS_AFTER,
                                    ROW_LABEL_EVERY, ROW_LABEL_FONT_SIZE, ROW_LABEL_FREQUENCY,
                                    ROW_LABEL_SIDE, ROW_LABEL_SIDES, SHOW_COLUMN_LABELS, SHOW_ROW_LABELS,
                                    parse_gap_size, parse_label_every, parse_label_font_size)
from analisi.heatmap_number_format import (LEGEND_DECIMALS as HEAT_MAP_LEGEND_DECIMALS,
                                           NUMBER_FORMAT as HEAT_MAP_NUMBER_FORMAT,
                                           NUMBER_FORMATS as HEAT_MAP_NUMBER_FORMATS,
                                           parse_legend_decimals as parse_heat_map_legend_decimals)
from analisi.hierarchical_gap import GAP_DATA, GAP_OPTIONS, GAP_PLOT
from analisi.hierarchical_workbench import (HIERARCHICAL_TABS, HIERARCHY_GRAPH, SILHOUETTE_DATA, SILHOUETTE_PLOT,
                                           TREE_AXIS, check_hierarchical_options, check_hierarchy_view,
                                           hierarchy_view_available, saved_hierarchical_options, uses_hierarchy_gap,
                                           uses_hierarchy_silhouette)
from analisi.leaf_order import FIELD as LEAF_ORDERING, OPTIMAL as OPTIMAL_LEAF_ORDER
from analisi.info import InfoSheet, MAX_INFO_SHEETS, info_contexts, validate_info_sheets
from analisi.info_widget import InfoDetails, InfoEditor
from analisi.inference import (AUTOMATIC_P, CHI_SQUARE_P, DUNN, DUNN_ADJUSTMENT, DUNN_ALPHA, DUNN_CONTROL,
                               DUNN_METHODS, DUNN_PAIRS, DUNN_PAIR_LIST, EXACT_P, FRIEDMAN_P, KRUSKAL_P)
from analisi.equivalence_workbench import (CHOICE_KEYS as TOST_CHOICE_KEYS, DATA_FIELDS as TOST_DATA_FIELDS,
                                           DESIGN as TOST_DESIGN, ERROR_PREFIX as TOST_ERROR_PREFIX, EQUIVALENCE,
                                           LABEL_KEYS as TOST_LABEL_KEYS, TAB_KEYS as TOST_TAB_KEYS,
                                           visibility as equivalence_visibility)
from analisi.meta_analysis import (CHOICE_KEYS as META_CHOICE_KEYS, DATA_FIELDS as META_DATA_FIELDS,
                                   LABEL_KEYS as META_LABEL_KEYS, META_ANALYSIS, SHOW_GRAPH as META_SHOW_GRAPH,
                                   TAB_KEYS as META_TAB_KEYS, cancellable as meta_cancellable,
                                   check_options as check_meta_options)
from analisi import meta_analysis_dialog
from analisi.meta_analysis_dialog import describe_error as describe_meta_error, translate_error as translate_meta_error
from analisi.paired_proportions import (CHOICE_KEYS as PAIRED_CHOICE_KEYS, DATA_FIELDS as PAIRED_DATA_FIELDS,
                                        DEFAULT_CODES as PAIRED_DEFAULT_CODES, ERROR_PREFIX as PAIRED_ERROR_PREFIX,
                                        FORMAT as PAIRED_FORMAT, GRAPH as PAIRED_GRAPH,
                                        LABEL_KEYS as PAIRED_LABEL_KEYS, PAIRED_PROPORTIONS,
                                        TAB_KEYS as PAIRED_TAB_KEYS, defaults as paired_defaults,
                                        visibility as paired_visibility)
from analisi.tolerance_intervals import (CHOICE_KEYS as TOLERANCE_CHOICE_KEYS, ERROR_PREFIX as TOLERANCE_ERROR_PREFIX,
                                         HINT_KEY as TOLERANCE_HINT, LABEL_KEYS as TOLERANCE_LABEL_KEYS,
                                         SHOW_GRAPH as TOLERANCE_SHOW_GRAPH, TAB_KEYS as TOLERANCE_TAB_KEYS, TOLERANCE)
from analisi.reference_normalization import (INPUT_FIELDS as REFERENCE_INPUT_FIELDS, METHOD as REFERENCE_NORMALIZATION,
                                             OUTPUT_FIELDS as REFERENCE_OUTPUT_FIELDS,
                                             REFERENCE_FIELDS as REFERENCE_REFERENCE_FIELDS,
                                             visibility as reference_field_visibility)
from analisi.reference_normalization_dialog import (LABEL_KEYS as REFERENCE_LABEL_KEYS,
                                                    field_caption as field_caption_for_reference,
                                                    replicate_note_key, translate_error as translate_reference_error)
from analisi.lognormal_tests import (CHOICE_KEYS as RATIO_CHOICE_KEYS, DATA_FIELDS as RATIO_DATA_FIELDS,
                                      DESIGN as RATIO_DESIGN, LABEL_KEYS as RATIO_LABEL_KEYS, LOGNORMAL,
                                      TAB_KEYS as RATIO_TAB_KEYS, visibility as lognormal_visibility)
from analisi.nonlinear_bands import (BAND as NL_BAND, BAND_NONE as NL_BAND_NONE, CHOICE_KEYS as NL_BAND_CHOICES,
                                     DRAWING as NL_BAND_DRAWING, LABEL_KEYS as NL_BAND_LABELS, LEVEL as NL_BAND_LEVEL,
                                     check_band_options)
from analisi.parameter_intervals import (METHOD as PARAM_CI_METHOD, LEVEL as PARAM_CI_LEVEL,
                                        PROFILE as PARAM_CI_PROFILE, WALD as PARAM_CI_WALD, OPTIONS as PARAM_CI_OPTIONS,
                                        LABEL_KEYS as PARAM_CI_LABELS, CHOICE_KEYS as PARAM_CI_CHOICES,
                                        REPORT_LOG_IC50, has_ic50, settings as check_parameter_ci,
                                        validate_profile_data)
from analisi.linear_diagnostics import BAND_NONE, linear_confidence_level
from analisi import regression_range
from analisi.linear_estimates import (FORWARD as LINEAR_Y_CI, INVERSE as LINEAR_X_CI,
                                     X_VALUE as LINEAR_X_VALUE, Y_VALUE as LINEAR_Y_VALUE,
                                     LABEL_KEYS as LINEAR_ESTIMATE_LABELS,
                                     check_options as check_linear_estimate_options,
                                     requested as linear_estimates_requested)
from analisi.xy_errors import (ERROR_COLOR as XY_ERROR_COLOR, XY_ERRORS, XY_ERROR_CHOICE_KEYS,
                               XY_ERROR_LABEL_KEYS, XY_ERROR_TABS, XY_ERROR_TAB_KEYS,
                               prune_xy_error_options, xy_error_visibility)
from analisi.xy_series import (RECIPE_KEYS as XY_RECIPE_KEYS, XY_METHOD, assign_colors, check_xy_options,
                               prune_options, style_after_parameter_change as xy_style, xy_series)
from analisi.parameter_dialog import GlobalParameters, SeriesConstraints
from analisi.exact_binomial import EXACT as EXACT_BINOMIAL, LEVEL_FIELD as BINOMIAL_LEVEL
from analisi.parts_of_whole import (APPLY_SEGMENT_STYLES, BORDER_COLOR, BORDER_WIDTH, CLOCKWISE, DONUT, DOTS,
                                    EXPECTED as EXPECTED_DISTRIBUTIONS, GOODNESS_OF_FIT, PARTS_GRAPH, PIE,
                                    SEGMENT_STYLES, SLICE_LABELS, START_ANGLE, TEST_METHOD, pie_value_is_default)
from analisi.graph_inspector import GraphInspector
from analisi.presentation import Layout, apply_style, compose_layout, graph_groups, graph_series
from analisi.qq_panel_dialog import QQPanelsDialog
from analisi.qq_panels import panel_axes
from analisi.pairwise_dialog import PairwiseDialog
from analisi.pairwise_graph import (LETTERS as COMPACT_LETTERS, SECTION as PAIRWISE_SECTION,
                                    attach as attach_pairwise,
                                    comparison_rows as pairwise_rows, endpoint_resolver as pairwise_endpoint,
                                    graph_anchors as pairwise_anchors, graph_problem as pairwise_graph_problem,
                                    pairwise_warning, sync_letters_table,
                                    read_section as read_pairwise, source_problem as pairwise_source_problem)
from analisi.fit_weights import INVERSE_VARIANCE, NOTE_KEYS, UNWEIGHTED, uses_fitted_y, uses_observed_y
from analisi.i18n import config_path, load_language, set_language, tr, translate_message, ui, fixed_choice_keys
from analisi.language_dialog import LanguageDialog
from analisi import parallel
from analisi.parallel_analyses import precompute as precompute_analyses
from analisi.processes_dialog import ProcessesDialog
from analisi.theme_preferences import load_ribbon_expanded, load_theme, save_ribbon_expanded, ThemeDialog
from analisi.modern_workspace import ModernWorksheet
from analisi.project_tabs import MAX_PROJECT_TABS, ProjectSession, ProjectTabs
from analisi.legacy_binary_graphs import render_binary_graph
from analisi.legacy_emf_edit import LIMIT_SOURCE
from analisi.legacy_fit_graph import FIT_GRAPH_SPEC, FIT_INTERVAL_BAND
from analisi.legacy_xml_qc import QC_REFERENCE
from analisi import icc
from analisi import precision_recall
from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_DATA, LEGACY_PANEL_EDITS, edited_layout_preview
from analisi.legacy_restore import (LEGACY_GRAPH_LINK, LEGACY_GRAPH_STYLE,
                                   LEGACY_NOTES, LEGACY_PREVIEW, LEGACY_TITLE, SAVED_BINARY_GRAPH,
                                   SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, SAVED_XY,
                                   initial_sheet_reference, layout_panel_sources, linked_panel_readers, panel_source_style,
                                   resolve_layout_panel_graphs)
from analisi.legacy_zip_layout import ZIP_LAYOUT, imported_paper
from analisi.repeated_input import SAVED_REPLICATE_DISPLAY, curve_series_labels
from analisi.repeated_workbench import INPUT_FIELDS, check_global_weighting
from analisi.replicate_fit import MERGE_REPLICATES, replicate_groups
from analisi.roc import threshold_text
from analisi.rank_tests import (CHOICE_KEYS as RANK_CHOICE_KEYS, CONTINUITY as RANK_CONTINUITY, EXACT as RANK_EXACT,
                                LABEL_KEYS as RANK_LABEL_KEYS, MANN_WHITNEY, P_VALUE as RANK_P, WILCOXON)
from analisi.row_tests import (RAW as ROW_TEST_RAW, ROW_TESTS, TESTS as ROW_TEST_CHOICES,
                               default_options as row_test_defaults, visibility as row_test_visibility)
from analisi.nonlinear_calibration import (CONCENTRATION_4PL, INVERSE_INTERVAL_MODELS, INVERSE_MODELS,
                                           calibration_choice_error)
from analisi.nonlinear_calibration import (DIRECTION as CALIBRATION_DIRECTION, DIRECTIONS as CALIBRATION_DIRECTIONS,
                                           UNCERTAINTY as CALIBRATION_UNCERTAINTY,
                                           calibration_visibility as standard_curve_visibility,
                                           check_nonlinear_inverse, forward_options, inverse_options)
from analisi.normality import (NORMALITY, QQ_PLOT, QQ_VARIABLE, check_options as check_normality_options,
                               visibility as normality_visibility)
from analisi.summary_ttest import METHOD as SUMMARY_TTEST, check_options as check_summary_ttest
from analisi import mean_permutation_dialog
from analisi.mean_permutation import (DATA_FIELDS as PERMUTATION_DATA_FIELDS, METHOD as MEAN_PERMUTATION,
                                      SEED as PERMUTATION_SEED, TAB_KEYS as PERMUTATION_TAB_KEYS,
                                      cancellable as permutation_cancellable,
                                      check_options as check_permutation_options)
from analisi.mean_permutation_dialog import (describe_error as describe_permutation_error,
                                             translate_error as translate_permutation_error)
from analisi.summary_anova import (JOINT as SUMMARY_JOINT, METHOD as SUMMARY_ANOVA,
                                   NOTE as SUMMARY_ANOVA_NOTE, ORDINARY as SUMMARY_ORDINARY,
                                   ORDINARY_POSTHOC as SUMMARY_ORDINARY_POSTHOC,
                                   UNEQUAL_POSTHOC as SUMMARY_UNEQUAL_POSTHOC, WELCH as SUMMARY_WELCH,
                                   check_options as check_summary_anova,
                                   visibility as summary_anova_visibility)
from analisi.outlier_screening import (METHOD as OUTLIER_METHOD, OUTLIERS,
                                       visibility as outlier_visibility)
from analisi.cluster_silhouette import (METHOD as CLUSTER_SILHOUETTE,
                                        check_options as check_silhouette_options,
                                        default_options as silhouette_defaults,
                                        requested_graph as silhouette_graph)
from analisi.spline_fit import (DIRECTION as SPLINE_DIRECTION, METHOD as SPLINE_METHOD, METHOD_NOTE as SPLINE_NOTE,
                                SPLINE_FIT, TABS as SPLINE_TABS, visibility as spline_visibility)
from analisi.independent_roc import (AREA as IROC_AREA, DIRECTION_A as IROC_DIRECTION_A,
                                     DIRECTION_B as IROC_DIRECTION_B, INFERENCE as IROC_INFERENCE,
                                     METHOD as INDEPENDENT_ROC, NUMBER_FIELDS as IROC_NUMBER_FIELDS,
                                     cancellable as independent_roc_cancellable,
                                     check_options as check_independent_roc,
                                     normalized_options as independent_roc_options,
                                     proposed_inference as independent_roc_inference,
                                     visibility as independent_roc_visibility)
from analisi import curve_pipeline
from analisi.curve_pipeline_dialog import (NOTE_KEYS as CURVE_NOTE_KEYS, describe_error as describe_curve_error,
                                           notes_visibility as curve_notes_visibility)
from analisi.monte_carlo import (COMMON as MONTE_CARLO_COMMON, GRAPH as MONTE_CARLO_GRAPH, GRAPH_NONE, MAX_SEED,
                                 MONTE_CARLO as MONTE_CARLO_METHOD, REPEATABLE, SEED as MONTE_CARLO_SEED,
                                 STUDY as MONTE_CARLO_STUDY,
                                 TEST_VS_TRUTH, X_COLUMN as MONTE_CARLO_X_COLUMN, X_SOURCE as MONTE_CARLO_X_SOURCE,
                                 MonteCarloCancelled, check_options as check_monte_carlo_options, monte_carlo,
                                 visibility as monte_carlo_visibility)
from analisi.plot_function import (CURVE_LIST, CURVES as FUNCTION_CURVES, EXAMPLE_CURVES as FUNCTION_EXAMPLE,
                                   GRAPH_NOTE as FUNCTION_NOTE, MODEL as FUNCTION_MODEL, PLOT_FUNCTION,
                                   TABS as FUNCTION_TABS, X_SOURCE as FUNCTION_X_SOURCE,
                                   visibility as function_visibility)
from analisi.custom_equation_dialog import (SYNTAX_CHOICE_KEYS, EquationEditor, ParameterTable,
                                           translate_error as translate_custom_error)
from analisi.custom_fit import (CUSTOM_EQUATION, DEFAULT_EQUATION, EQUATION_TEXT, EXAMPLE_PARAMETERS,
                                LEVEL as CUSTOM_LEVEL, PARAMETER_LIST, POINTS as CUSTOM_POINTS,
                                SD_COLUMN as CUSTOM_SD, SYNTAX as CUSTOM_SYNTAX, check_options as check_custom_options)
from analisi.robust_curve import (COMPARE as ROBUST_COMPARE, DEFAULTS as ROBUST_DEFAULTS, DISPLAY as ROBUST_DISPLAY,
                                  EVALUATIONS as ROBUST_EVALUATIONS, GROUP as ROBUST_GROUP, INITIAL as ROBUST_INITIAL,
                                  INITIAL_LIST, LOSS as ROBUST_LOSS, MODEL as ROBUST_MODEL, OUTPUT_FIELDS as ROBUST_OUTPUT,
                                  ROBUST_CURVE, SCALE_METHOD as ROBUST_SCALE_METHOD, VARIABLE_FIELDS as ROBUST_VARIABLES,
                                  X as ROBUST_X, Y_COLUMNS as ROBUST_Y, check_options as check_robust_options,
                                  proposed_initial as robust_proposal)
from analisi.robust_curve_dialog import (CHOICE_KEYS as ROBUST_CHOICE_KEYS, LABEL_KEYS as ROBUST_LABEL_KEYS,
                                         TAB_KEYS as ROBUST_TAB_KEYS, InitialParameters, describe_error as describe_robust_error,
                                         visibility as robust_visibility)
from analisi.nb2_regression import (MODE as NB2_MODE, NB2, check_options as check_nb2_options,
                                    visibility as nb2_visibility)
from analisi.nb2_dialog import (CHOICE_KEYS as NB2_CHOICE_KEYS, HINT_KEY as NB2_HINT, LABEL_KEYS as NB2_LABEL_KEYS,
                                describe_error as describe_nb2_error, translate_error as translate_nb2_error)
from analisi.competing_risks_workbench import (
    CAUSE_CHOICE as COMPETING_CAUSE, CHOICE_KEYS as COMPETING_CHOICE_KEYS, CODE_LIST as COMPETING_CODE_LIST,
    COMPETING_RISKS, DATA_FIELDS as COMPETING_DATA, DEFAULTS as COMPETING_DEFAULTS, ESTIMATE_FIELDS as COMPETING_ESTIMATES,
    EVENTS as COMPETING_EVENTS, GRAPH as COMPETING_GRAPH, GRAPH_CAUSE as COMPETING_GRAPH_CAUSE,
    GRAPH_FIELDS as COMPETING_GRAPH_FIELDS, LABEL_KEYS as COMPETING_LABEL_KEYS, TAB_KEYS as COMPETING_TAB_KEYS,
    TIME_LIST as COMPETING_TIME_LIST, cancellable as competing_cancellable, check_options as check_competing_options,
    visibility as competing_visibility)
from analisi.competing_risks_dialog import (CodeListEditor, TimeListEditor, describe_error as describe_competing_error,
                                            translate_error as translate_competing_error)
from analisi.rmcorr import (GRAPH as RMCORR_GRAPH, INTERVAL as RMCORR_INTERVAL, LABEL_KEYS as RMCORR_LABEL_KEYS,
                            RMCORR, SEED as RMCORR_SEED, cancellable as rmcorr_cancellable,
                            prepare as check_rmcorr_options, visibility as rmcorr_visibility)
from analisi.rmcorr_dialog import NOTE_BOOTSTRAP as RMCORR_NOTE_BOOTSTRAP, NOTE_MODEL as RMCORR_NOTE_MODEL
from analisi.rmcorr_dialog import describe_error as describe_rmcorr_error
from analisi.weibull_aft import (CATEGORICAL as WEIBULL_CATEGORICAL, NAME as WEIBULL_NAME, PREDICTORS as WEIBULL_PREDICTORS,
                                 PROFILES as WEIBULL_PROFILES, SHAPE_MODE as WEIBULL_SHAPE_MODE,
                                 SHOW_GRAPH as WEIBULL_SHOW_GRAPH)
from analisi.weibull_aft_workbench import (
    CHOICE_KEYS as WEIBULL_CHOICE_KEYS, DATA_FIELDS as WEIBULL_DATA, DEFAULTS as WEIBULL_DEFAULTS,
    HINT_KEYS as WEIBULL_HINTS, LABEL_KEYS as WEIBULL_LABEL_KEYS, MODEL_FIELDS as WEIBULL_MODEL,
    PREDICT_FIELDS as WEIBULL_PREDICT, TAB_KEYS as WEIBULL_TAB_KEYS, TIME_LIST as WEIBULL_TIME_LIST, WEIBULL_AFT,
    check_options as check_weibull_options, visibility as weibull_visibility)
from analisi.weibull_aft_dialog import (TimesEditor as WeibullTimesEditor, describe_error as describe_weibull_error,
                                        translate_error as translate_weibull_error)
from analisi.ordinal_logit import (
    CATEGORY_ORDER as ORDINAL_ORDER_KIND, GRAPH as ORDINAL_GRAPH, NAME as ORDINAL_NAME, ORDER as ORDINAL_ORDER,
    ORDINAL_LOGIT, PROFILE_FIELDS as ORDINAL_PROFILE_FIELDS, PROFILE_TAB as ORDINAL_PROFILE_TAB,
    PROFILES as ORDINAL_PROFILES, VALUES as ORDINAL_VALUES, check_options as check_ordinal_options)
from analisi.ordinal_logit_dialog import (OrderEditor, describe_error as describe_ordinal_error, read_observed,
                                          translate_error as translate_ordinal_error)
from analisi.rmst import (CENSOR_CODE as RMST_CENSOR, EVENT_CODE as RMST_EVENT, GROUP as RMST_GROUP,
                          HORIZON as RMST_HORIZON, REFERENCE as RMST_REFERENCE, SHOW_GRAPH as RMST_SHOW_GRAPH,
                          STATUS as RMST_STATUS, TIME as RMST_TIME, group_levels as rmst_group_levels,
                          horizon_limit as rmst_horizon_limit)
from analisi.rmst_workbench import (
    DATA_FIELDS as RMST_DATA, DEFAULTS as RMST_DEFAULTS, ESTIMATE_FIELDS as RMST_ESTIMATES, HINT_KEYS as RMST_HINTS,
    LABEL_KEYS as RMST_LABEL_KEYS, NUMBER_FIELDS as RMST_NUMBER_FIELDS, RMST, TAB_KEYS as RMST_TAB_KEYS,
    check_options as check_rmst_options, visibility as rmst_visibility)
from analisi.rmst_dialog import (describe_error as describe_rmst_error, limit_hint as rmst_limit_hint,
                                 read_number as read_rmst_number, shown_number as rmst_shown_number,
                                 translate_error as translate_rmst_error)
from analisi.global_custom_dialog import (GlobalCoefficientTable, SeriesConstraintEditor,
                                          translate_error as translate_global_error)
from analisi.global_custom_fit import (EXAMPLE_PARAMETERS as GLOBAL_EXAMPLE, GLOBAL_CUSTOM_EQUATION,
                                       PARAMETER_LIST as GLOBAL_PARAMETER_LIST, SERIES_LIST as GLOBAL_SERIES_LIST,
                                       TABS as GLOBAL_TABS, check_options as check_global_custom_options, series_in)
from analisi.global_uncertainty import (BAND_DRAWING as GLOBAL_DRAWING, CURVE_BAND as GLOBAL_BAND,
                                        EXTRAPOLATE as GLOBAL_EXTRAPOLATE, NONE as GLOBAL_NONE,
                                        PREDICT as GLOBAL_PREDICT, PREDICTION as GLOBAL_PREDICTION,
                                        QUERY_GROUP as GLOBAL_QUERY_GROUP, QUERY_INTERVAL as GLOBAL_QUERY_INTERVAL,
                                        QUERY_K as GLOBAL_QUERY_K, QUERY_X as GLOBAL_QUERY_X,
                                        RESPONSE_LEVEL as GLOBAL_RESPONSE_LEVEL)
from analisi.cohen_kappa import ORDER as KAPPA_ORDER, SHOW_GRAPH as KAPPA_SHOW_GRAPH, WEIGHTING as KAPPA_WEIGHTING
from analisi.cohen_kappa_workbench import (
    CHOICE_KEYS as KAPPA_CHOICE_KEYS, COHEN_KAPPA, HINT_KEYS as KAPPA_HINTS, INTERVAL_FIELDS as KAPPA_INTERVAL_FIELDS,
    LABEL_KEYS as KAPPA_LABEL_KEYS, ORDER_LIST as KAPPA_ORDER_LIST, RATING_FIELDS as KAPPA_RATING_FIELDS,
    TAB_KEYS as KAPPA_TAB_KEYS, TYPED_FIELDS as KAPPA_TYPED_FIELDS, cancellable as kappa_cancellable,
    check_options as check_kappa_options, visibility as kappa_visibility)
from analisi.cohen_kappa_dialog import (CategoryOrderEditor, defaults as kappa_defaults,
                                        describe_error as describe_kappa_error, preview as kappa_preview,
                                        read_typed as read_kappa_typed, translate_error as translate_kappa_error)
from analisi.select_transform import CALCULATED, FILTERS, SELECT_TRANSFORM
from analisi.select_transform_dialog import CalculatedVariables, RowFilters
from analisi.transpose_dialog import TransposeSets
from analisi import reshape_long_wide as reshape, reshape_tk
from analisi import worksheet_join as worksheet_join_engine, worksheet_join_tk
from analisi.worksheet_join import METHOD as WORKSHEET_JOIN
from analisi.worksheet_join_app import WorksheetJoinSources, stored_legacy_view
from analisi.worksheet_join_labels import message as translate_join_error
from analisi.transpose_xy import (ROW_TITLE as TRANSPOSE_TITLE, SETS_LIST, TRANSPOSE_XY, X as TRANSPOSE_X,
                                  Y_SETS as SETS_LIST_LABEL,
                                  propose_sets, proposed_x)
from analisi.survival_input import CENSOR_CODE, EVENT_CODE, OTHER_STATUS, STATUS_DEFAULTS
from analisi.cox_dialog import TABS as COX_TABS, ProfileEditor, cox_message, model_terms
from analisi import deming_dialog
from analisi.ols_diagnostics import (LINEAR_CI, LINEAR_DIAGNOSTICS, LINEAR_PROFILES, LINEAR_RESIDUAL_PLOT,
                                     TABS as OLS_TABS, check_weighted_profiles)
from analisi import mlr_weighting
from analisi import logistic_validation
from analisi.logistic_diagnostics import (LOGISTIC_CI, LOGISTIC_CUTOFF, LOGISTIC_DIAGNOSTICS, LOGISTIC_PROFILES,
                                          TABS as LOGISTIC_TABS)
from analisi.pca_graphs import (COLOR_GROUPS as PCA_COLOR_GROUPS, GRAPH as PCA_GRAPH,
                                HORIZONTAL as PCA_HORIZONTAL, LABEL as PCA_LABEL, ONE_DIMENSION as PCA_ONE_DIMENSION,
                                POINT_VIEWS as PCA_POINT_VIEWS, SAVED_DIRECTIONS as PCA_SAVED_DIRECTIONS,
                                SAVED_VIEWPORT as PCA_SAVED_VIEWPORT, SHOW_LABELS as PCA_SHOW_LABELS,
                                TABS as PCA_TABS, VERTICAL as PCA_VERTICAL, validate as validate_pca_graph)
from analisi.pca_regression import (CHOICE_KEYS as PCA_REGRESSION_CHOICE_KEYS, CONFIDENCE as PCR_CONFIDENCE,
                                    DEPENDENT as PCR_DEPENDENT, ENABLE as PCR_ENABLE,
                                    LABEL_KEYS as PCA_REGRESSION_LABELS, PLOT as PCR_PLOT, RESPONSE as PCR_RESPONSE,
                                    TABS as PCA_REGRESSION_TABS, requested as pcr_requested,
                                    settings as pca_regression_settings)
from analisi.pca_reports import LABEL_KEYS as PCA_REPORT_LABELS, TABS as PCA_REPORT_TABS
from analisi.ancova import (ADJUSTMENT as ANCOVA_ADJUSTMENT, ANCOVA, COMPARISONS as ANCOVA_COMPARISONS,
                            CONTROL_GROUP as ANCOVA_CONTROL, DATA_FIELDS as ANCOVA_DATA_FIELDS,
                            REFERENCE_X as ANCOVA_REFERENCE, format_error as format_ancova_error,
                            group_choices as ancova_group_choices, reference_value as ancova_reference_value,
                            visibility as ancova_visibility)
from analisi import pca_overlays, pca_parallel_archive
from analisi.pca_retention import (CHOICE_KEYS as PCA_CHOICE_KEYS, LABEL_KEYS as PCA_SELECT_LABELS,
                                  SELECTION as PCA_SELECTION, TABS as PCA_SELECTION_TABS,
                                  check as check_pca_selection, simulates as pca_simulates,
                                  visible_fields as pca_visible_fields)
from analisi.cox_exact import (EXACT as COX_EXACT, TIES as COX_TIES, check_outputs as check_cox_exact_outputs,
                               is_exact as cox_is_exact, translate_error as translate_cox_exact_error)
from analisi.cox_fit_diagnostics import COX_SNELL, SCALED as COX_SCALED
from analisi.cox_outputs import (METHOD as COX, GRAPH as COX_GRAPH, GRAPH_TERM as COX_TERM, PREDICT as COX_PREDICT, PROFILE_LIST,
                                 DIAGNOSTICS as COX_DIAGNOSTICS, FIT_DIAGNOSTICS as COX_FIT_DIAGNOSTICS,
                                 PROFILES as COX_PROFILES, SCHOENFELD as COX_SCHOENFELD,
                                 STATUS_DEFAULTS as COX_STATUS, cox_visibility)
from analisi.survival_plot import CURVE as SURVIVAL_CURVE, GRAPH_OPTIONS as SURVIVAL_GRAPH_OPTIONS, SURVIVAL_GRAPH
from analisi.survival_plot import style_after_parameter_change as survival_style
from analisi.table_setup import NewTableDialog, TEMPLATES, XY_FORMATS, TableSetup, table_frame
from analisi.text_import import TEXT_SUFFIXES
from analisi.text_import_dialog import TextImportDialog
from analisi import ui_shell, ui_theme
from analisi.workspace_icons import show_hint, workspace_icons
from analisi.worksheet_history import WorksheetState
from analisi.worksheet_formula_dialog import WorksheetFormulaDialog
from analisi.additional import bland_altman_visibility, regression_visibility
from analisi.models import DIAGNOSTICS as POISSON_DIAGNOSTICS_FIELD
from analisi.exploration import LIMIT_INTERVALS as BLAND_ALTMAN_INTERVALS
from analisi.trend_anova import ORDER as TREND_ORDER, ORDER_KIND as TREND_ORDER_KIND, TREND, group_levels
from analisi.fit_quality import (REPLICATES as FIT_REPLICATES, RESIDUAL_VIEW as FIT_RESIDUALS,
                                 RUNS as FIT_RUNS, check_options as check_fit_quality_options)
from analisi.field_error import FieldError
from analisi.power_plan import (ALLOCATION as POWER_ALLOCATION, DESIGN as POWER_DESIGN, EFFECT_INPUT as POWER_EFFECT_INPUT,
                                GOAL as POWER_GOAL, GROUP_MEANS as POWER_GROUP_MEANS, METHOD as POWER_METHOD,
                                NUMBER_FIELDS as POWER_NUMBER_FIELDS, PAIRED_SD_INPUT as POWER_PAIRED_SD_INPUT,
                                SHOW_CURVE as POWER_SHOW_CURVE, TABS as POWER_TABS, TEXT_DEFAULTS as POWER_TEXT_DEFAULTS,
                                check_options as check_power_options, normalized_options as power_options,
                                visibility as power_visibility)
from analisi.power_plan_dialog import MultilineEntry
from analisi import kmeans_archive, kmeans_options, kmeans_reports, kmeans_stability
from analisi import lognormal_anova
from analisi.unequal_anova import check_one_way_options, one_way_visibility
from analisi.variance_assumptions import (ALPHA as VARIANCE_ALPHA, BARTLETT as VARIANCE_BARTLETT,
                                          BROWN as VARIANCE_BROWN, LABEL_KEYS as VARIANCE_LABEL_KEYS,
                                          TAB as VARIANCE_TAB, format_variance_error,
                                          validate as validate_variance)
from analisi.fdr_control import (METHOD as FDR_METHOD, PLOT as FDR_PLOT, format_fdr_error,
                                 validate_request as validate_fdr_request)
from analisi.variance_ratio import (CHOICE_KEYS as VARIANCE_RATIO_CHOICES, LABEL_KEYS as VARIANCE_RATIO_LABELS,
                                    METHOD as VARIANCE_RATIO, NOTE_KEY as VARIANCE_RATIO_NOTE,
                                    SHOW as VARIANCE_SHOW, format_error as format_variance_ratio_error,
                                    shows_graph as variance_ratio_shows_graph)

TREND_HEADINGS = {TREND: "analysis.trend.heading.trend", TREND_ORDER: "analysis.trend.heading.order"}
from analisi import unequal_anova

FIT_HEADINGS = {
    FIT_RUNS: "analysis.fit.heading.runs",
    FIT_REPLICATES: "analysis.fit.heading.replicates",
    FIT_RESIDUALS: "analysis.fit.heading.residuals",
}
from analisi.spearman_exact_budget import (FIELD as SPEARMAN_BUDGET, STANDARD as SPEARMAN_STANDARD,
                                           extended_request as spearman_extended_request)
from analisi.correlation_details import (COMPARE_INDEPENDENT, CORRELATE_CONTROL, CORRELATION_METHODS,
                                         validate_request as validate_correlation_request)
from analisi.survival_input import (PAIRWISE_CORRECTION, PAIRWISE_CONTROL, PAIRWISE_ADJUSTED, PAIRWISE_SCOPE,
                                   PAIRWISE_FIELDS, PAIRWISE_PAIRS, PAIRWISE_PAIR_LIST, pairwise_corrections,
                                   pairwise_fields, pairwise_scope)
from analisi.workbench import (ANOVA_ALPHA, ANOVA_EFFECTS, CLASSIC_RESPONSES, GRAPH_METHODS, GROUP_CHOICE,
                               GROUP_ORDER, GROUPS, METHODS, MULTIPLE, OPTIONAL, OPTIONAL_MULTIPLE, TEXT, Result, analyse,
                               _anova_row_count, anova_visibility, check_anova_options, check_survival_options,
                               classic_roles, survival_levels)
from analisi.stats import GEOMETRIC_REPORT, SUMMARY_FORMAT, summary_confidence, summary_fields
from analisi.anova_diagnostics import (ALPHA as ANOVA_DIAG_ALPHA, ASSUMPTIONS as ANOVA_ASSUMPTIONS,
                                       DIAGNOSTICS as ANOVA_DIAGNOSTICS, GRAPH as ANOVA_DIAG_GRAPH,
                                       GRAPH_CHOICE_KEYS as ANOVA_GRAPH_CHOICE_KEYS, GRAPH_QQ as ANOVA_GRAPH_QQ,
                                       LABEL_KEYS as ANOVA_DIAG_LABEL_KEYS, QQ_LINE as ANOVA_QQ_LINE,
                                       TABS as ANOVA_DIAG_TABS, ensure_graph_budget as ensure_anova_graph_budget,
                                       format_anova_error, graph_choice as anova_graph_choice,
                                       validate as validate_anova_diagnostics,
                                       visibility as anova_diagnostic_visibility)
from analisi.anova_ss import KEY as ANOVA_SUMS_OF_SQUARES, TYPE_III as ANOVA_TYPE_III
from analisi.anova_ss import sums_of_squares as anova_sums_of_squares
from analisi.anova_ss_dialog import SumsOfSquaresPanel
from analisi import anova_planned_contrasts as planned_contrasts
from analisi import anova_comparison_plot, anova_diagnostics, anova_grouped_plot, lognormal_tests, ttest_options
from analisi.anova_contrast_editor import check_contrast_input, contrast_context
from analisi.anova_contrasts_tk import ContrastPanel
from analisi.anova_terms import (FULL as ANOVA_FULL_TERMS, MODEL_TERMS as ANOVA_MODEL_TERMS, TERM_LIST,
                                 TERM_SELECTION as ANOVA_TERM_SELECTION, active_factors as anova_active_factors,
                                 check_comparison_controls as check_anova_comparisons, check_options as check_anova_terms)
from analisi.anova_terms_dialog import ANOVA_MODEL_TAB, TermPicker
from analisi import rm_sphericity
from analisi.rm_sphericity import format_error as format_rm_error
from analisi.processing import (BASELINES, COMBINED_TOTALS, DENOMINATORS, FieldError, INTERVALS,
                                METHODS as PROCESSING_METHODS, PRUNE_MODES, WILSON_BROWN)

ASSETS = Path(__file__).resolve().parent / "assets"
LEGACY_GRAPH_METHODS = {SAVED_XY, SAVED_BINARY_GRAPH, SAVED_EDITABLE_GRAPH}


def extended_request(method, options):
    """Calculations that run on the worker with a cancel control: extended Spearman and the silhouettes."""
    return method == CLUSTER_SILHOUETTE or spearman_extended_request(method, options)


RUN_VIEWS = {"result", "graph", "saved-layout"}
CATEGORY_GRAPHS = {COLUMN_GRAPH, GROUPED_GRAPH}
# Dialogs that explain the chosen Weighting denominator under the field.
WEIGHTING_NOTE_METHODS = {"Nonlinear regression", "Global nonlinear regression"}
CUSTOM_WEIGHTING_KEYS = {UNWEIGHTED: "custom.weighting.unweighted", INVERSE_VARIANCE: "custom.weighting.inverse_variance"}
CUSTOM_LABEL_KEYS = {"Variables": "custom.tab.variables", "Equation": "custom.field.Equation",
                     "Parameters": "custom.field.Parameters", "Output": "custom.tab.output",
                     "Group": "custom.field.Group", "Weighting": "custom.field.Weighting",
                     CUSTOM_SD: "custom.field.SD column", CUSTOM_LEVEL: "custom.field.Confidence level (%)",
                     CUSTOM_POINTS: "custom.field.Curve points", CUSTOM_SYNTAX: "conditional.field.syntax"}
GLOBAL_WEIGHTING_KEYS = {UNWEIGHTED: "gfit.weighting.unweighted",
                         INVERSE_VARIANCE: "gfit.weighting.inverse_variance"}
# Gaussian weighting of Multiple regression: translated labels, choices and the note under the choice.
MLR_LABEL_KEYS = {mlr_weighting.GAUSSIAN_WEIGHTING: "analysis.mlr.mode", mlr_weighting.EXPONENT: "analysis.mlr.exponent",
                  mlr_weighting.SD_COLUMN: "analysis.mlr.sd", mlr_weighting.WEIGHT_COLUMN: "analysis.mlr.weight",
                  mlr_weighting.FUTURE_PRECISION: "analysis.mlr.future"}
def translate_mlr_error(text):
    """An engine message of Multiple regression in the active language, with its field names translated too."""
    text = translate_message(str(text), "mlr.error.")
    for field, key in MLR_LABEL_KEYS.items():
        text = text.replace(field, tr(key))
    return text


def translate_power_error(error):
    """A Power and sample size message in the active language; field names become captions, numbers Italian."""
    thousands = lambda value: value.replace(",", ".")
    return translate_message(str(error), "power.error.", {"field": ui, "low": thousands, "high": thousands,
                                                          "limit": thousands, "count": thousands})


def translate_equivalence_error(error):
    """An Equivalence test message in the active language; its field names become the dialog captions."""
    return translate_message(str(error), TOST_ERROR_PREFIX, {"field": lambda name: tr(TOST_LABEL_KEYS.get(name, name))})


def translate_independent_roc_error(error):
    """A Compare independent ROC curves message in the active language; its field names become the captions."""
    return translate_message(str(error), "iroc.error.", {"field": ui, "first": ui})


def translate_precision_recall_error(error):
    thousands = lambda value: value.replace(",", ".")
    return translate_message(error, precision_recall.ERROR_PREFIX, {
        "field": ui, "other": ui, **dict.fromkeys(("low", "high", "count", "limit", "a", "b"), thousands),
    })


def translate_icc_error(error):
    thousands = lambda value: value.replace(",", ".")
    return translate_message(error, icc.ERROR_PREFIX, {
        "field": ui, "raters": ui, **dict.fromkeys(("low", "high", "limit", "cells", "count"), thousands),
    })


def translate_grouped_error(error):
    """A Grouped distribution plot message in the active language; field names become the dialog captions."""
    known = {name.casefold(): name for name in METHODS[GROUPED_DISTRIBUTIONS]}
    return translate_message(str(error), "grouped.error.", {"field": lambda name: ui(known.get(name.casefold(), name))})


def translate_paired_error(error):
    """A Paired proportions message in the active language; its field names become the dialog captions."""
    return translate_message(str(error), PAIRED_ERROR_PREFIX, {"field": lambda name: tr(PAIRED_LABEL_KEYS.get(name, name))})

def translate_tolerance_error(error):
    """A Tolerance intervals message in the active language; field names become the dialog captions and worksheet
    names stay literal."""
    return translate_message(str(error), TOLERANCE_ERROR_PREFIX,
                             {"field": lambda name: tr(TOLERANCE_LABEL_KEYS.get(name, name))})


def translate_logistic_validation_error(error):
    return translate_message(str(error), logistic_validation.ERROR_PREFIX, convert={"field": ui})


def translate_kmeans_stability_error(error):
    return translate_message(str(error), kmeans_stability.ERROR_PREFIX, convert={"field": ui})


def translate_correlation_error(error):
    """A correlation message in the active language. Worksheet names inside it stay literal."""
    return translate_message(str(error), "corr.details.error.", {"field": lambda name: ui(name)})


CALIBRATION_LABELS = {
    "Uncertainty": "calib.inverse_nonlinear.field.uncertainty",
    "Confidence level (%)": "calib.inverse_nonlinear.field.level",
    "Replicate count column": "calib.inverse_nonlinear.field.replicates",
    "Unknown responses": "calib.inverse_nonlinear.field.responses",
    "Model": "calib.inverse_nonlinear.field.model",
    "Curve": "calib.inverse_nonlinear.field.curve",
    "Direction": "calib.inverse_nonlinear.field.direction",
}


def translate_calibration_error(error):
    """A standard-curve message in the active language, with the dialog caption in front of it."""
    message = translate_message(str(error), "calib.inverse_nonlinear.")
    field = getattr(error, "field", None)
    label = tr(CALIBRATION_LABELS[field]) if field in CALIBRATION_LABELS else field
    if label and label not in message:
        message = f"{label}: {message}"
    return message


HEAT_MAP_NUMBER_FORMAT_KEYS = {
    choice: f"heat.legend_number.choice.{choice}" for choice in HEAT_MAP_NUMBER_FORMATS
}
HEAT_MAP_CELL_LABEL_FORMAT_KEYS = {
    choice: f"heat.cell_label.choice.{choice}" for choice in CELL_LABEL_NUMBER_FORMATS
}
HEAT_MAP_CELL_LABEL_COLOR_MODE_KEYS = {
    choice: f"heat.cell_label.choice.{choice}" for choice in CELL_LABEL_COLOR_MODES
}
HEAT_MAP_LAYOUT_CHOICE_KEYS = {
    ROW_GAP_MODE: {choice: f"heat.layout.choice.{choice}" for choice in GAP_MODES},
    COLUMN_GAP_MODE: {choice: f"heat.layout.choice.{choice}" for choice in GAP_MODES},
    ROW_LABEL_FREQUENCY: {choice: f"heat.layout.choice.{choice}" for choice in LABEL_FREQUENCIES},
    COLUMN_LABEL_FREQUENCY: {choice: f"heat.layout.choice.{choice}" for choice in LABEL_FREQUENCIES},
    COLUMN_LABEL_ROTATION: {choice: f"heat.layout.choice.{choice}" for choice in COLUMN_LABEL_ROTATIONS},
    ROW_LABEL_SIDE: {choice: f"heat.layout.choice.{choice}" for choice in ROW_LABEL_SIDES},
    COLUMN_LABEL_SIDE: {choice: f"heat.layout.choice.{choice}" for choice in COLUMN_LABEL_SIDES},
}


def translate_heat_map_error(error):
    """A heat-map message in the active language; field names, including the lower-case ones of choice errors,
    become the dialog captions, and category names stay literal."""
    known = {name.casefold(): name for name in HEAT_MAP_OPTIONS}
    convert = {"field": lambda name: ui(known.get(name.casefold(), name))}
    for prefix in ("heat.layout.error.", "heat.cell_label.error.", "heat.legend_number.error."):
        translated = translate_message(str(error), prefix, convert)
        if translated != str(error):
            return translated
    return translate_message(str(error), "heat.error.", convert)


MLR_CHOICE_KEYS = {mlr_weighting.UNWEIGHTED: "analysis.mlr.choice.unweighted",
                   mlr_weighting.INVERSE_VARIANCE: "analysis.mlr.choice.sd",
                   mlr_weighting.FROM_COLUMN: "analysis.mlr.choice.weight"}
MLR_NOTE_KEYS = {mlr_weighting.UNWEIGHTED: "analysis.mlr.note.unweighted", mlr_weighting.ABS_Y: "analysis.mlr.note.abs_y",
                 mlr_weighting.Y_SQUARED: "analysis.mlr.note.y_squared",
                 mlr_weighting.ABS_Y_POWER: "analysis.mlr.note.power",
                 mlr_weighting.INVERSE_VARIANCE: "analysis.mlr.note.sd",
                 mlr_weighting.FROM_COLUMN: "analysis.mlr.note.weight"}
# Tab captions and the field headings that use the same English text share one key.
GLOBAL_LABEL_KEYS = {"Variables": "gfit.tab.variables", "Equation": "gfit.tab.equation",
                     "Parameters": "gfit.tab.parameters", "Series constraints": "gfit.tab.series",
                     "Output": "gfit.tab.output", "X": "gfit.field.X", "Y": "gfit.field.Y",
                     "Group": "gfit.field.Group", "Weighting": "gfit.field.Weighting",
                     CUSTOM_SD: "gfit.field.SD column", CUSTOM_LEVEL: "gfit.field.Confidence level (%)",
                     CUSTOM_POINTS: "gfit.field.Curve points", PARAM_CI_METHOD: "parameter_ci.method",
                     CUSTOM_SYNTAX: "conditional.field.syntax",
                     "Response": "gfit.tab.response",
                     **{name: "gfit.field." + name for name in GLOBAL_TABS["Response"]}}
# Response bands and predictions show translated choices; recipes keep these canonical values.
GLOBAL_RESPONSE_CHOICES = {"None": "gfit.choice.none", "Confidence": "gfit.choice.confidence",
                           "Prediction": "gfit.choice.prediction", "Filled": "gfit.choice.filled",
                           "Lines": "gfit.choice.lines"}
# A recipe saved before 0.70 stays without these keys while the new outputs remain off.
GLOBAL_RESPONSE_OFF = {GLOBAL_BAND: GLOBAL_NONE, GLOBAL_PREDICT: False}
P_VALUE_FIELDS = {"Kruskal–Wallis": KRUSKAL_P, "Friedman": FRIEDMAN_P}
RANK_METHODS = (MANN_WHITNEY, WILCOXON)
PROJECT_SUFFIXES = {".alab", ".prism", ".prismt", ".pzf", ".pzt", ".pzfx", ".xml"}


def run_view(method):
    if method == SAVED_BINARY_LAYOUT:
        return "saved-layout"
    if method in LEGACY_GRAPH_METHODS or method in {
            HIERARCHY_GRAPH, anova_comparison_plot.METHOD, anova_diagnostics.METHOD, anova_grouped_plot.METHOD}:
        return "graph"
    return "result"


def display(value):
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{value:.10g}"
    return str(value)


def safe_csv(path, frame, index=False):
    def plain(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    data = frame.map(plain).rename(columns=plain)
    if index:
        labels = data.index
        if isinstance(labels, pd.MultiIndex):
            data.index = pd.MultiIndex.from_arrays(
                [[plain(value) for value in labels.get_level_values(level)] for level in range(labels.nlevels)],
                names=[plain(name) for name in labels.names],
            )
        else:
            data.index = pd.Index([plain(str(value) if isinstance(value, tuple) else value) for value in labels],
                                  name=plain(labels.name), tupleize_cols=False)
    data.to_csv(path, index=index, encoding="utf-8-sig")


class Grid(ttk.Frame):
    def __init__(self, parent, frame, *, fit_cells=False, threshold_column=None):
        super().__init__(parent)
        self.frame = frame
        self.fit_cells = fit_cells
        self.threshold_column = threshold_column
        self.page = 0
        self.page_size = 500
        self.tree = ttk.Treeview(self, show="tree headings", selectmode="browse")
        vert = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hori = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vert.set, xscrollcommand=hori.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vert.grid(row=0, column=1, sticky="ns")
        hori.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        if len(frame) > self.page_size:
            pager = ttk.Frame(self)
            pager.grid(row=2, column=0, sticky="ew")
            self.previous = ttk.Button(pager, text=ui("Previous rows"), command=lambda: self.move(-1))
            self.previous.pack(side="left")
            self.next = ttk.Button(pager, text=ui("Next rows"), command=lambda: self.move(1))
            self.next.pack(side="left")
            self.position = ttk.Label(pager)
            self.position.pack(side="left", padx=10)
        self.refresh()

    def move(self, delta):
        self.page += delta
        self.refresh()
        self.tree.yview_moveto(0)

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        ids = [f"col{i}" for i in range(len(self.frame.columns))]
        self.tree["columns"] = ids
        index_title = str(self.frame.index.name or "Row")
        self.tree.heading("#0", text=index_title)
        index_width = 57
        if self.frame.index.dtype.kind not in {"i", "u"}:
            lengths = [len(index_title), *(len(display(value)) for value in self.frame.index[:100])]
            index_width = max(115, min(330, max(lengths) * 8 + 24))
        self.tree.column("#0", width=index_width, stretch=False)
        formatters = [threshold_text if name == self.threshold_column else display for name in self.frame.columns]
        for i, (key, name) in enumerate(zip(ids, self.frame.columns)):
            self.tree.heading(key, text=str(name), anchor="w")
            width = max(104, min(250, len(str(name)) * 8 + 26))
            numeric = pd.api.types.is_numeric_dtype(self.frame.dtypes.iat[i])
            if self.fit_cells or not numeric or name == self.threshold_column:
                lengths = (len(formatters[i](value)) for value in self.frame.iloc[:100, i])
                width = max(width, min(360, max(lengths, default=0) * 7 + 26))
            anchor = "e" if numeric else "w"
            self.tree.column(key, width=width, stretch=False, anchor=anchor)
        start = self.page * self.page_size
        page = self.frame.iloc[start:start + self.page_size]
        for offset, row in enumerate(page.itertuples(index=True, name=None), start):
            self.tree.insert("", "end", iid=str(offset), text=display(row[0]),
                             values=tuple(formatter(value) for formatter, value in zip(formatters, row[1:], strict=True)),
                             tags=("stripe",) if offset % 2 else ())
        self.tree.tag_configure("stripe", background="#f1f6fc")
        if hasattr(self, "position"):
            self.position.configure(text=tr("interface.rows_position", first=start + 1, last=start + len(page), total=len(self.frame)))
            self.previous.configure(state="normal" if self.page else "disabled")
            self.next.configure(state="normal" if start + len(page) < len(self.frame) else "disabled")


class GraphToolbar(NavigationToolbar2Tk):
    def __init__(self, canvas, parent, *, before_export):
        self.before_export = before_export
        super().__init__(canvas, parent, pack_toolbar=False)

    def save_figure(self, *args):
        if self.before_export():
            return super().save_figure(*args)


class ImportedPageToolbar(NavigationToolbar2Tk):
    def __init__(self, canvas, parent, export):
        self.export = export
        super().__init__(canvas, parent, pack_toolbar=False)

    def save_figure(self, *args):
        return self.export()


class OrderPicker(ttk.Frame):
    """Ordered list of group names with Up and Down buttons.

    The names are kept in a Python list, never read back from the Tk widget, so
    spaces, Unicode and numeric-looking names stay exactly as typed in the data.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.listbox = tk.Listbox(self, selectmode="browse", exportselection=False, height=5)
        self.listbox.pack(side="left", fill="both", expand=True)
        buttons = ttk.Frame(self)
        buttons.pack(side="right", fill="y", padx=(6, 0))
        ttk.Button(buttons, text=ui("Up"), width=6, command=lambda: self.move(-1)).pack()
        ttk.Button(buttons, text=ui("Down"), width=6, command=lambda: self.move(1)).pack(pady=(4, 0))
        self.note = ttk.Label(self, text=ui("The groups changed. Review the order."),
                              wraplength=260, foreground="#9a3412")

    def set_levels(self, levels, preferred=()):
        """Show every level once, keeping the earlier order for names still present.

        A saved order that had to be completed or trimmed is flagged on screen
        for review instead of being corrected silently.
        """
        earlier = self.items or list(preferred)
        kept = [name for name in earlier if name in levels]
        self.items = kept + [name for name in levels if name not in kept]
        self.refresh()
        if earlier and sorted(earlier) != sorted(levels):
            self.note.pack(side="bottom", anchor="w", pady=(4, 0))
        else:
            self.note.pack_forget()

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for name in self.items:
            self.listbox.insert("end", name)
        if selected is not None:
            self.listbox.selection_set(selected)

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        i, j = selection[0], selection[0] + step
        if 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.refresh(j)

    def values(self):
        return list(self.items)


def _trend_key(item):
    if item.get("kind") == "number":
        return ("number", float(item["value"]))
    return ("text", item.get("value"))


class TrendOrder(ttk.Frame):
    """Scores 1..k for typed group identities. The visible text is not the identity."""

    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self._removed = set()
        self._added = set()
        # The list is the first child so a field error focuses it. Pack the note
        # first, across the full width: a later side="left" would leave the note
        # in the cavity beside the list.
        self.listbox = tk.Listbox(self, selectmode="browse", exportselection=False, height=4, width=24)
        self.note = ttk.Label(self, text=tr("analysis.trend.note.positions"), wraplength=230,
                              foreground="#486075", justify="left")
        self.review = ttk.Label(self, text="", wraplength=230, foreground="#9a3412", justify="left")
        self.note.pack(side="bottom", anchor="w", fill="x", pady=(4, 0))
        buttons = ttk.Frame(self)
        buttons.pack(side="right", fill="y", padx=(6, 0))
        ttk.Button(buttons, text=tr("analysis.trend.up"), width=8, command=lambda: self.move(-1)).pack()
        ttk.Button(buttons, text=tr("analysis.trend.down"), width=8, command=lambda: self.move(1)).pack(pady=(4, 0))
        self.listbox.pack(side="left", fill="both", expand=True)

    def set_levels(self, levels, preferred=None):
        """Keep the user's order. New and removed levels stay visible so OK cannot drop one quietly."""
        levels = [dict(item) for item in levels if isinstance(item, dict)]
        if preferred is None and self.items:
            earlier = [dict(item) for item in self.items]
        elif isinstance(preferred, (list, tuple)):
            earlier = [dict(item) for item in preferred if isinstance(item, dict)]
        else:
            earlier = []
        current = {}
        for item in levels:
            current.setdefault(_trend_key(item), item)
        if not earlier:
            self.items = levels
            self._removed, self._added = set(), set()
        else:
            seen = set()
            self.items = []
            for item in earlier:
                token = _trend_key(item)
                if token in seen:
                    continue
                seen.add(token)
                self.items.append(dict(current.get(token, item)))
            added = []
            for item in levels:
                token = _trend_key(item)
                if token not in seen:
                    self.items.append(dict(item))
                    seen.add(token)
                    added.append(item)
            self._removed = {_trend_key(item) for item in self.items if _trend_key(item) not in current}
            self._added = {_trend_key(item) for item in added}
        self.refresh()

    def _caption(self, item):
        text = str(item["value"])
        if sum(str(other["value"]) == text for other in self.items) > 1:
            kind = tr("analysis.trend.kind.number" if item["kind"] == "number" else "analysis.trend.kind.text")
            text = f"{text} [{kind}]"
        token = _trend_key(item)
        if token in self._removed:
            text = f"{text} — {tr('analysis.trend.removed')}"
        elif token in self._added:
            text = f"{text} — {tr('analysis.trend.added')}"
        return text

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for index, item in enumerate(self.items, start=1):
            self.listbox.insert("end", f"{index}   {self._caption(item)}")
        if selected is not None and self.items:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        if self._removed or self._added:
            removed = ", ".join(str(item["value"]) for item in self.items if _trend_key(item) in self._removed)
            added = ", ".join(str(item["value"]) for item in self.items if _trend_key(item) in self._added)
            self.review.configure(text=tr("analysis.trend.review", removed=removed or "—", added=added or "—"))
            self.review.pack(side="bottom", anchor="w", fill="x", pady=(2, 0), after=self.note)
        else:
            self.review.pack_forget()

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        i, j = selection[0], selection[0] + step
        if 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.refresh(j)

    def values(self):
        return [{"kind": item["kind"], "value": item["value"]} for item in self.items]


class PairPicker(ttk.Frame):
    """Edit an ordered list of pairs without parsing their display labels."""

    def __init__(self, parent, pairs):
        super().__init__(parent)
        self.pairs = list(pairs) if isinstance(pairs, (list, tuple)) else []
        self.levels = ()
        self.first = ttk.Combobox(self, state="readonly", width=11)
        self.second = ttk.Combobox(self, state="readonly", width=11)
        self.first.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.second.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(self, text=ui("Add"), width=7, command=self.add_pair).grid(row=0, column=2, sticky="ew")
        self.listbox = tk.Listbox(self, height=4, exportselection=False, selectmode="browse")
        self.listbox.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.listbox.bind("<Delete>", lambda _: self.remove_pair())
        ttk.Button(self, text=ui("Remove"), width=7, command=self.remove_pair).grid(row=1, column=2, sticky="n", pady=(5, 0))
        self.note = ttk.Label(self, foreground="#9a3412", wraplength=260)
        self.note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(3, 0))
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def set_levels(self, levels):
        self.levels = tuple(levels)
        for control in (self.first, self.second):
            control.configure(values=self.levels)
            if control.get() not in self.levels:
                control.set("")
        self.refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        self.note.configure(text="")
        for pair in self.pairs:
            if (isinstance(pair, (list, tuple)) and len(pair) == 2
                    and all(isinstance(label, str) and label in self.levels for label in pair)):
                self.listbox.insert("end", f"{pair[0]}  →  {pair[1]}")
            else:
                self.listbox.insert("end", "Unavailable pair")
                self.note.configure(text=ui("Remove unavailable pairs and choose groups in the current data."))

    def add_pair(self):
        pair = [self.first.get(), self.second.get()]
        if pair[0] == pair[1] or any(label not in self.levels for label in pair):
            self.note.configure(text=ui("Choose two different groups."))
            return
        if any(existing == pair or existing == pair[::-1] for existing in self.pairs):
            self.note.configure(text=ui("This pair is already in the list."))
            return
        self.pairs.append(pair)
        self.refresh()
        self.listbox.see("end")

    def remove_pair(self):
        selected = self.listbox.curselection()
        if selected:
            del self.pairs[selected[0]]
            self.refresh()

    def values(self):
        return list(self.pairs)


class BeforeAfterPairs(ttk.Frame):
    """Ordered list of Before/After column pairs with optional titles.

    Pairs are kept as plain records in a Python list; the list box only shows them.
    """

    def __init__(self, parent, columns, numeric, pairs):
        super().__init__(parent)
        self.columns = tuple(columns)
        self.pairs = [dict(pair) if isinstance(pair, dict) else pair
                      for pair in (pairs if isinstance(pairs, (list, tuple)) else [])]
        ttk.Label(self, text=ui("Before")).grid(row=0, column=0, sticky="w")
        ttk.Label(self, text=ui("After")).grid(row=0, column=1, sticky="w")
        self.before = ttk.Combobox(self, state="readonly", width=13, values=self.columns)
        self.after = ttk.Combobox(self, state="readonly", width=13, values=self.columns)
        self.before.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.after.grid(row=1, column=1, sticky="ew", padx=(0, 4))
        self.title = tk.StringVar()
        ttk.Label(self, text=ui("Title (optional)")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Entry(self, textvariable=self.title).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 4))
        ttk.Button(self, text=ui("Add"), width=7, command=self.add_pair).grid(row=3, column=2, sticky="ew")
        self.listbox = tk.Listbox(self, height=5, exportselection=False, selectmode="browse")
        self.listbox.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.listbox.bind("<Delete>", lambda _: self.remove_pair())
        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=2, sticky="n", pady=(5, 0))
        for text, command in (("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)),
                              ("Remove", self.remove_pair)):
            ttk.Button(buttons, text=ui(text), width=7, command=command).pack(pady=(0, 3))
        self.note = ttk.Label(self, foreground="#9a3412", wraplength=280)
        self.note.grid(row=5, column=0, columnspan=3, sticky="w", pady=(3, 0))
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        if len(numeric) >= 2:
            self.before.set(numeric[0])
            self.after.set(numeric[1])
        self.refresh()

    def valid(self, pair):
        return (isinstance(pair, dict) and all(isinstance(pair.get(key), str) for key in (BEFORE, AFTER))
                and pair[BEFORE] in self.columns and pair[AFTER] in self.columns)

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        self.note.configure(text="")
        for number, pair in enumerate(self.pairs, 1):
            if self.valid(pair):
                title = pair.get(PAIR_TITLE) or ""
                self.listbox.insert("end", f"{number}. {pair[BEFORE]}  →  {pair[AFTER]}" + (f"  ({title})" if title else ""))
            else:
                self.listbox.insert("end", f"{number}. Unavailable pair")
                self.note.configure(text=ui("Remove unavailable pairs and choose columns in the current data."))
        if selected is not None:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)

    def add_pair(self):
        before, after = self.before.get(), self.after.get()
        if before not in self.columns or after not in self.columns or before == after:
            self.note.configure(text=ui("Choose two different columns for Before and After."))
            return
        if any(self.valid(pair) and {pair[BEFORE], pair[AFTER]} == {before, after} for pair in self.pairs):
            self.note.configure(text=ui("This pair is already in the list."))
            return
        if len(self.pairs) >= MAX_PAIRS:
            self.note.configure(text=tr("interface.max_pairs", count=MAX_PAIRS))
            return
        self.pairs.append({BEFORE: before, AFTER: after, PAIR_TITLE: self.title.get().strip()})
        self.title.set("")
        self.refresh(len(self.pairs) - 1)

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        i, j = selection[0], selection[0] + step
        if 0 <= j < len(self.pairs):
            self.pairs[i], self.pairs[j] = self.pairs[j], self.pairs[i]
            self.refresh(j)

    def remove_pair(self):
        selected = self.listbox.curselection()
        if selected:
            del self.pairs[selected[0]]
            self.refresh(min(selected[0], len(self.pairs) - 1) if self.pairs else None)

    def values(self):
        return [dict(pair) if isinstance(pair, dict) else pair for pair in self.pairs]


_INACTIVE_OMIT = object()


def format_pca_error(error, field=None):
    """Message of a PCA field error in the active language, led by the caption of its field.

    Only the regression messages and the color-group messages have a translation; every other PCA
    message keeps its English text and the English field name, exactly as before.
    """
    field = getattr(error, "field", None) if field is None else field
    message = str(error)
    if field == PCA_COLOR_GROUPS:
        return translate_message(message, "pca.graph.error.")
    if field not in PCA_REGRESSION_LABELS and field != PCA_SELECTION:
        return f"{field}: {message}" if field and field not in message else message
    translated = translate_message(message, "pca.regression.error.", {
        "name": lambda name: tr(PCA_REGRESSION_LABELS[name]) if name in PCA_REGRESSION_LABELS else name})
    if field in PCA_REGRESSION_LABELS:
        caption = tr(PCA_REGRESSION_LABELS[field])
    else:
        caption = tr(PCA_SELECT_LABELS[PCA_SELECTION]) if translated != message else field
    return f"{caption}: {translated}" if field not in translated and caption not in translated else translated


class AnalysisDialog(simpledialog.Dialog):
    def __init__(self, parent, data, current=None, only=None, initial_field=None, error=None, *,
                 join_sources=None, join_left=None, initial_pair=0):
        self.join_sources = join_sources or {}
        self.join_left = join_left
        self.initial_pair = initial_pair
        self.only = (only,) if isinstance(only, str) else only
        self.data = data
        self.current = current
        self.initial_field = initial_field
        # A field error reported by the worker for this candidate, shown above the buttons on reopening.
        self.error = error
        self.controls = {}
        self.processing_result = None
        self.global_series = None
        self.method = current[0] if current else next(iter(self.only or METHODS))
        super().__init__(parent, ui("Analyze Data"))

    def wait_visibility(self, window=None):
        super().wait_visibility(window)
        if window is None:
            self.keep_on_screen()
        # body() selects this field before mapping, when focus_set cannot yet transfer
        # keyboard focus from the parent Inspector. Complete the request once visible.
        if window is None and self.initial_field:
            self.focus_field(self.initial_field)

    def body(self, master):
        modern = ui_theme.is_modern()
        master.columnconfigure(1, weight=1)
        picker = ttk.Frame(master, padding=(12, 10, 10, 8) if modern else (2, 2, 12, 2),
                           style="AnalysisPicker.TFrame" if modern else "")
        picker.grid(row=0, column=0, sticky="nsew")
        ttk.Label(picker, text=ui("Find an analysis"),
                  style="AnalysisPicker.TLabel" if modern else "DialogTitle.TLabel").pack(anchor="w")
        self.query = tk.StringVar()
        search = ttk.Entry(picker, textvariable=self.query, width=31)
        search.pack(fill="x", pady=(4, 8))
        pane = ttk.Frame(picker)
        pane.pack(fill="both", expand=True)
        self.methods = ttk.Treeview(pane, show="tree", selectmode="browse", height=16,
                                    style="Analysis.Treeview" if modern else "")
        if modern:
            self.methods.tag_configure("category", foreground=ui_theme.MUTED, font=ui_theme.font(9, "bold"))
        self.methods.column("#0", width=244, stretch=True)
        scroll = ttk.Scrollbar(pane, orient="vertical", command=self.methods.yview)
        self.methods.configure(yscrollcommand=scroll.set)
        self.methods.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.methods.bind("<<TreeviewSelect>>", self.select_method)
        self.query.trace_add("write", lambda *_: self.fill_methods())
        workspace = master
        if modern:
            workspace = ttk.Frame(master, padding=(14, 5, 3, 2))
            workspace.grid(row=0, column=1, sticky="nsew")
            workspace.columnconfigure(0, weight=1)
            workspace.rowconfigure(1, weight=1)
        self.fields = ttk.Notebook(workspace, width=466, height=352,
                                   style="Analysis.TNotebook" if modern else "")
        self.fields.grid(row=1 if modern else 0, column=0 if modern else 1, sticky="nsew")
        self.fields.bind("<<NotebookTabChanged>>", self.refresh_series_tab)
        self.heading = ttk.Label(workspace, text=ui(self.method), style="AnalysisTitle.TLabel" if modern else "")
        self.heading.grid(row=0 if modern else 1, column=0 if modern else 1, sticky="ew" if modern else "w",
                          pady=(0, 6) if modern else (5, 0))
        self.error_label = None
        if self.error:
            banner = ttk.Frame(master, style="ErrorBanner.TFrame")
            banner.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            tk.Frame(banner, width=ui_theme.px(3), background=ui_theme.ERROR).pack(side="left", fill="y")
            self.error_label = ttk.Label(banner, text=self.error, style="ErrorBanner.TLabel",
                                         wraplength=ui_theme.px(700), justify="left")
            self.error_label.pack(side="left", fill="x", expand=True, padx=8, pady=5)
        self.fill_methods()
        self.configure_fields()
        return self.focus_field(self.initial_field) or search

    def fill_methods(self):
        self.methods.delete(*self.methods.get_children())
        self.method_by_item = {}
        search = self.query.get().strip().casefold()
        for group, methods in GROUPS.items():
            matches = [name for name in methods if (not self.only or name in self.only)
                       and (name != HIERARCHY_GRAPH or name == self.method or hierarchy_view_available(self.data))
                       and (name != kmeans_reports.MODEL_GRAPH or name == self.method
                            or kmeans_reports.model_plot_available(self.data))
                       and any(search in caption.casefold() for caption in (name, group, ui(name), ui(group)))]
            if not matches:
                continue
            folder = self.methods.insert("", "end", text=ui(group), open=True, tags=("category",))
            for name in matches:
                item = self.methods.insert(folder, "end", text=ui(name))
                self.method_by_item[item] = name
                if name == self.method:
                    self.methods.selection_set(item)
                    self.methods.see(item)

    def select_method(self, _=None):
        selection = self.methods.selection()
        if selection:
            name = self.method_by_item.get(selection[0])
            if name in METHODS and name != self.method:
                self.method = name
                self.heading.configure(text=ui(name))
                self.configure_fields()
                self.keep_on_screen()

    def keep_on_screen(self):
        """Keep the decorated dialog inside its monitor, including the taskbar."""
        if not self.winfo_ismapped():
            return
        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        if self.method == "Principal component analysis":
            # Selecting PCA can widen the notebook after the analysis picker is already mapped.
            parent = self.parent.winfo_toplevel()
            left, top = parent.winfo_rootx(), parent.winfo_rooty()
            if left >= 0 and top >= 0 and width <= parent.winfo_width() and height <= parent.winfo_height():
                x, y = self.winfo_x(), self.winfo_y()
                parent_rect = (left, top, left + parent.winfo_width(), top + parent.winfo_height())
                position = clamp_rect((x, y, x + width, y + height), parent_rect)
                if position != (x, y):
                    self.geometry(f"+{position[0]}+{position[1]}")
                    self.update_idletasks()
        if keep_native_window_on_screen(self):
            return
        x = max(0, min(self.winfo_x(), self.winfo_screenwidth() - width))
        y = max(0, min(self.winfo_y(), self.winfo_screenheight() - height))
        if (x, y) != (self.winfo_x(), self.winfo_y()):
            self.geometry(f"+{x}+{y}")

    def configure_fields(self):
        for child in self.fields.winfo_children():
            child.destroy()
        self.controls.clear()
        self.field_rows = {}
        self.choice_bindings = {}
        self.anova_order = self.contrast_panel = None
        self.select_editors = {}
        self.parameters = None
        self.series_parameters = None
        self.global_series = None
        self.mlr_note = None
        self.reference_replicate_note = None
        self.sphericity_note = None
        self.reshape = self.join = None
        wanted = (430 if self.method == GLOBAL_CUSTOM_EQUATION
                  else 470 if self.method == "Multiple regression"
                  else 500 if self.method == "One-way ANOVA"
                  else 500 if self.method == COHEN_KAPPA
                  else 470 if self.method == HEAT_MAP
                  else 470 if self.method == NORMALITY
                  else 470 if self.method == REFERENCE_NORMALIZATION
                  else 400 if self.method in {COMPETING_RISKS, curve_pipeline.CURVE_METHOD}
                  else 420 if self.method == WEIBULL_AFT
                  else 470 if self.method == ORDINAL_LOGIT
                  else 390 if self.method == RMST
                  else 440 if self.method in {"Nonlinear regression", ROBUST_CURVE} else 352)
        # Keep the title bar, the heading, an error banner and the buttons on the screen of a 1024x768 monitor.
        room = max(240, self.winfo_screenheight() - ui_theme.px(230))
        width = (620 if self.method == GLOBAL_CUSTOM_EQUATION
                 else 550 if self.method == "Global nonlinear regression" else 466)
        content_width = min(ui_theme.px(width), max(400, self.winfo_screenwidth() - ui_theme.px(330)))
        self.fields.configure(width=content_width, height=min(ui_theme.px(wanted), room))
        if ui_theme.is_modern():
            self.heading.configure(wraplength=content_width)
        scroll_variables = self.method in {icc.METHOD, reshape.METHOD, WORKSHEET_JOIN}
        variables = ttk.Frame(self.fields, padding=0 if scroll_variables else 10)
        self.fields.add(variables, text=ui("Variables"))
        if scroll_variables:
            variables = self._make_scrollable_tab(variables)
        else:
            variables.columnconfigure(1, weight=1)
        if self.method in {SUMMARY_ANOVA, WORKSHEET_JOIN, "Multifactor ANOVA",
                           kmeans_stability.METHOD, logistic_validation.METHOD}:
            # The notebook keeps a fixed height, so the extra method controls scroll
            # and Run Analysis / Cancel stay on a 1024×768 screen.
            options_page = ttk.Frame(self.fields)
            self.fields.add(options_page, text=ui("Options"))
            options = self._make_scrollable_tab(options_page)
        else:
            options = ttk.Frame(self.fields, padding=10)
            self.fields.add(options, text=ui("Options"))
            options.columnconfigure(1, weight=1)
        columns = self.data.columns.tolist()
        numeric = list(self.data.select_dtypes(include="number").columns)
        categorical = [name for name in columns if name not in numeric] or columns
        saved = self.current[1] if self.current and self.current[0] == self.method else {}
        if self.method == WORKSHEET_JOIN:
            self.join = worksheet_join_tk.JoinEditor(self, variables, options, saved)
            self._bind_scrollable_children(variables)
            self._bind_scrollable_children(options)
            return
        if self.method in kmeans_options.METHODS:
            saved = kmeans_options.saved_scaling(saved)
        if (self.method in ("Correlation", CORRELATE_CONTROL) and self.current
                and self.current[0] == self.method):
            saved = {SPEARMAN_BUDGET: SPEARMAN_STANDARD, **saved}
        if self.method in CLASSIC_RESPONSES:
            saved = {**saved, **classic_roles(self.method, saved)}
        if self.method == "Kruskal–Wallis" and self.current and self.current[0] == self.method:
            saved = {KRUSKAL_P: CHI_SQUARE_P, **saved}
        fields_by_tab = {}
        positions = {variables: 0, options: 0}
        tabs = {}
        if self.method == "Kaplan–Meier survival":
            self.fields.tab(options, text=ui("Comparisons"))
            saved = {**saved, PAIRWISE_SCOPE: pairwise_scope(saved)}
            tabs = {"Pairwise tests": PAIRWISE_FIELDS,
                    "Status coding": (EVENT_CODE, CENSOR_CODE, OTHER_STATUS),
                    "Graph": SURVIVAL_GRAPH_OPTIONS}
        elif self.method in DUNN_METHODS:
            self.fields.tab(options, text=ui("Multiple comparisons"))
            if self.method in P_VALUE_FIELDS:
                fields_by_tab[P_VALUE_FIELDS[self.method]] = variables
        elif self.method == "One-way ANOVA":
            tabs = {VARIANCE_TAB: (VARIANCE_BROWN, VARIANCE_BARTLETT, VARIANCE_ALPHA)}
            # Distribution, ratio direction and the level sit on Options with the post-hoc controls.
            # A scrollable page keeps Run Analysis on a 1024×768 screen.
            self.fields.forget(options)
            options.destroy()
            options_outer = ttk.Frame(self.fields)
            self.fields.insert("end", options_outer, text=ui("Options"))
            options = self._make_scrollable_tab(options_outer)
            positions[options] = 0
        elif self.method in (SUMMARY_ANOVA, SUMMARY_TTEST):
            fields_by_tab["Input"] = variables
        elif self.method == ANCOVA:
            # Variables / Model (slope, reference, level, graph) / Comparisons (which contrasts and their correction).
            self.fields.tab(options, text=ui("Model"))
            tabs = {"Comparisons": (ANCOVA_COMPARISONS, ANCOVA_CONTROL, ANCOVA_ADJUSTMENT)}
        elif self.method == "Multifactor ANOVA":
            # The Model page (term selection, order, term checkboxes) scrolls and sits right after Variables.
            tabs = {ANOVA_MODEL_TAB: (ANOVA_TERM_SELECTION, "Interaction order", ANOVA_SUMS_OF_SQUARES,
                                      ANOVA_MODEL_TERMS),
                    "Effect sizes": (ANOVA_EFFECTS, ANOVA_ALPHA), **ANOVA_DIAG_TABS}
        elif self.method == "Hierarchical clustering":
            saved = saved_hierarchical_options(saved)
            fields_by_tab["Direction"] = variables
            tabs = HIERARCHICAL_TABS
        elif self.method == "Scatter / confidence ellipse":
            self.fields.tab(options, text=ui("Ellipse"))
            fields_by_tab.update(dict.fromkeys(ELLIPSE_TABS["Ellipse"], options))
            tabs = {"Fill and border": ELLIPSE_TABS["Fill and border"]}
        elif self.method == SELECT_TRANSFORM:
            self.fields.tab(variables, text=ui("Select columns"))
            self.fields.tab(options, text=ui("Select rows"))
            tabs = {"Transform columns": (CALCULATED,)}
        elif self.method == ROW_TESTS:
            self.fields.tab(variables, text=ui("Worksheet"))
            self.fields.tab(options, text=ui("Tests and graph"))
            tabs = {"Multiplicity": ("Correction", "Family alpha", "False discovery rate (%)")}
            if not saved:
                saved = row_test_defaults(self.data)
        elif self.method == CLUSTER_SILHOUETTE:
            if not saved:
                saved = silhouette_defaults(self.data)
        elif self.method in NESTED_METHODS:
            self.fields.tab(variables, text=ui("Subcolumns"))
            self.fields.tab(options, text=ui("Model and inference"))
            if is_nested_worksheet(self.data):
                saved = {NESTED_SUBCOLUMNS: nested_defaults(self.data), **saved}
        elif self.method == HEAT_MAP:
            self.fields.tab(options, text=ui("Graph options"))
            tabs = HEAT_MAP_TABS
        elif self.method in CATEGORY_GRAPHS or self.method == PARTS_GRAPH:
            self.fields.tab(options, text=ui("Graph options"))
            if self.method == GROUPED_GRAPH:
                fields_by_tab["Input"] = variables
                # Recipes saved before the Input option keep raw replicates.
                if not saved and default_grouped_input(self.data) == SUMMARIES:
                    saved = {"Input": SUMMARIES}
        elif self.method == FOREST_PLOT:
            self.fields.tab(options, text=ui("Scale and reference"))
            fields_by_tab.update(dict.fromkeys(FOREST_ROLE_ROWS, variables))
            try:
                forest_rows, forest_labels = guess_role_rows(self.data, saved), forest_row_choices(self.data, saved)
            except ValueError:
                forest_rows, forest_labels = guess_role_rows(self.data, {}), forest_row_choices(self.data, {})
        elif self.method == MEAN_PERMUTATION:
            self.fields.tab(variables, text=tr(PERMUTATION_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(PERMUTATION_TAB_KEYS["Test"]))
            fields_by_tab.update(dict.fromkeys(PERMUTATION_DATA_FIELDS, variables))
        elif self.method == CONTINGENCY:
            self.fields.tab(variables, text=ui("Table"))
            self.fields.tab(options, text=ui("Test and effects"))
            if not saved and default_count_matrix(self.data):
                saved = {"Input format": COUNT_MATRIX}
        elif self.method in {BEFORE_AFTER, TRAJECTORIES}:
            self.fields.tab(options, text=ui("Graph options"))
            fields_by_tab.update(dict.fromkeys((BEFORE_AFTER_PAIRS, "Input"), variables))
            if self.method == TRAJECTORIES and not saved:
                saved = trajectory_defaults(self.data)
        elif self.method == COMPARE_LINES:
            self.fields.tab(options, text=ui("Comparison"))
            fields_by_tab["Input"] = variables
        elif self.method == LOGNORMAL:
            self.fields.tab(variables, text=tr(RATIO_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(RATIO_TAB_KEYS["Test and graph"]))
            fields_by_tab.update(dict.fromkeys(RATIO_DATA_FIELDS, variables))
        elif self.method == INDEPENDENT_ROC:
            # The four samples and their directions on the first page; the area and the inference on the second.
            self.fields.tab(options, text=ui("Area and inference"))
            fields_by_tab.update(dict.fromkeys((IROC_DIRECTION_A, IROC_DIRECTION_B), variables))
        elif self.method == precision_recall.METHOD:
            fields_by_tab.update(dict.fromkeys(precision_recall.CODE_FIELDS, variables))
        elif self.method == reshape.METHOD:
            saved = reshape_tk.defaults(columns, numeric, saved)
            fields_by_tab.update(dict.fromkeys(reshape.OPTIONS, variables))
        elif self.method == POWER_METHOD:
            # Design and goal on the first page, the expected effect on the second, the curve on a third.
            self.fields.tab(variables, text=ui("Design"))
            self.fields.tab(options, text=ui("Effect"))
            fields_by_tab.update(dict.fromkeys(POWER_TABS["Design"], variables))
            tabs = {"Curve": POWER_TABS["Curve"]}
        elif self.method == EQUIVALENCE:
            self.fields.tab(variables, text=tr(TOST_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(TOST_TAB_KEYS["Equivalence zone"]))
            fields_by_tab.update(dict.fromkeys(TOST_DATA_FIELDS, variables))
        elif self.method == META_ANALYSIS:
            self.fields.tab(variables, text=tr(META_TAB_KEYS["Studies"]))
            self.fields.tab(options, text=tr(META_TAB_KEYS["Model and output"]))
            fields_by_tab.update(dict.fromkeys(META_DATA_FIELDS, variables))
        elif self.method == PAIRED_PROPORTIONS:
            self.fields.tab(variables, text=tr(PAIRED_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(PAIRED_TAB_KEYS["Test and graph"]))
            fields_by_tab.update(dict.fromkeys(PAIRED_DATA_FIELDS, variables))
            if not saved:
                saved = paired_defaults(self.data)
        elif self.method == TOLERANCE:
            self.fields.tab(variables, text=tr(TOLERANCE_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(TOLERANCE_TAB_KEYS["Interval"]))
        elif self.method == COMPARE_MODELS:
            self.fields.tab(variables, text=ui("Data"))
            self.fields.tab(options, text=ui("Output"))
            tabs = {"Models": (MODELS_FIELD,)}
        elif self.method == EXTRACT_REARRANGE:
            self.fields.tab(variables, text=ui("Data arrangement"))
            self.fields.tab(options, text=ui("Output format"))
            fields_by_tab.update(dict.fromkeys((EXTRACT_OUTPUT, EXTRACT_PREFIX, EXTRACT_COMPLETE), options))
        elif self.method == TRANSPOSE_XY:
            self.fields.tab(variables, text=ui("Columns"))
            self.fields.tab(options, text=ui("Result"))
            fields_by_tab.update(dict.fromkeys((TRANSPOSE_X, SETS_LIST_LABEL, TRANSPOSE_TITLE), variables))
            if not saved:
                x = proposed_x(self.data) or next(iter(numeric), None)
                saved = {TRANSPOSE_X: x, SETS_LIST_LABEL: propose_sets(self.data, x)} if x else {}
        elif self.method == PLOT_FUNCTION:
            self.fields.tab(variables, text=ui("Function"))
            self.fields.tab(options, text=ui("Output"))
            fields_by_tab.update(dict.fromkeys(FUNCTION_TABS["Function"], variables))
            fields_by_tab.update(dict.fromkeys(FUNCTION_TABS["Output"], options))
            tabs = {"Curves": FUNCTION_TABS["Curves"]}
        elif self.method == MONTE_CARLO_METHOD:
            self.fields.tab(variables, text=ui("Study"))
            self.fields.tab(options, text=ui("Design"))
            fields_by_tab.update(dict.fromkeys(MONTE_CARLO_COMMON, variables))
            fields_by_tab[MONTE_CARLO_X_COLUMN] = options
        elif self.method == COX:
            self.fields.tab(options, text=ui("Model and status"))
            tabs = COX_TABS
        elif self.method == "Multiple regression":
            tabs = {**OLS_TABS, **LOGISTIC_TABS}
        elif self.method in kmeans_options.METHODS:
            tabs = {"Output": kmeans_reports.SCAN if self.method == kmeans_options.SELECTION else kmeans_reports.COMMON}
            if self.method == kmeans_options.SELECTION:
                tabs["Graph"] = tuple(kmeans_options.PLOTS)
        elif self.method == "Principal component analysis":
            tabs = {**PCA_TABS, **PCA_SELECTION_TABS, **PCA_REPORT_TABS, **pca_overlays.TABS, **PCA_REGRESSION_TABS}
        elif self.method == SPLINE_FIT:
            # Method fields first; the query direction and the drawn output have their own tabs.
            self.fields.tab(options, text=ui("Method"))
            tabs = SPLINE_TABS
        elif self.method == XY_ERRORS:
            self.fields.tab(variables, text=tr(XY_ERROR_TAB_KEYS["X errors"]))
            self.fields.tab(options, text=tr(XY_ERROR_TAB_KEYS["Y errors"]))
            fields_by_tab.update(dict.fromkeys(XY_ERROR_TABS["X errors"], variables))
            fields_by_tab.update(dict.fromkeys(XY_ERROR_TABS["Y errors"], options))
            tabs = {tr(XY_ERROR_TAB_KEYS["Error appearance"]): XY_ERROR_TABS["Error appearance"]}
        elif self.method == COHEN_KAPPA:
            # Ratings (columns, weights, category order) / Interval and graph (bootstrap and figure). The Ratings
            # page scrolls, so the order editor and its notes never push Run Analysis off a 1024×768 screen.
            self.fields.forget(variables)
            variables.destroy()
            ratings_outer = ttk.Frame(self.fields)
            self.fields.insert(0, ratings_outer, text=tr(KAPPA_TAB_KEYS["Ratings"]))
            self.fields.select(ratings_outer)
            variables = self._make_scrollable_tab(ratings_outer)
            positions = {variables: 0, options: 0}
            self.fields.tab(options, text=tr(KAPPA_TAB_KEYS["Interval and graph"]))
            fields_by_tab.update(dict.fromkeys(KAPPA_RATING_FIELDS, variables))
            fields_by_tab.update(dict.fromkeys(KAPPA_INTERVAL_FIELDS, options))
            saved = {**kappa_defaults(self.data), **saved}
        elif self.method == ROBUST_CURVE:
            # Variables (data, model, starting values) / Loss and scale / Output.
            self.fields.tab(variables, text=tr(ROBUST_TAB_KEYS["variables"]))
            self.fields.tab(options, text=tr(ROBUST_TAB_KEYS["loss"]))
            fields_by_tab.update(dict.fromkeys(ROBUST_VARIABLES, variables))
            tabs = {tr(ROBUST_TAB_KEYS["output"]): ROBUST_OUTPUT}
            starts = {ROBUST_X: numeric[0], ROBUST_Y: [numeric[1]]} if len(numeric) > 1 else {}
            saved = {**ROBUST_DEFAULTS, **starts, **saved}
        elif self.method == COMPETING_RISKS:
            # Data (columns and codes) / Estimates (times, level, Gray tests) / Graph.
            self.fields.tab(variables, text=tr(COMPETING_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(COMPETING_TAB_KEYS["Estimates"]))
            fields_by_tab.update(dict.fromkeys(COMPETING_DATA, variables))
            fields_by_tab.update(dict.fromkeys(COMPETING_ESTIMATES, options))
            tabs = {tr(COMPETING_TAB_KEYS["Graph"]): COMPETING_GRAPH_FIELDS}
        elif self.method == deming_dialog.METHOD:
            # Variables / Uncertainty / Output: the input choice, the ratio and the SDs stay together.
            self.fields.tab(options, text=ui(deming_dialog.UNCERTAINTY_TAB))
            tabs = deming_dialog.TABS
        elif self.method == WEIBULL_AFT:
            # Data (columns, codes, predictors) / Model (shape, level) / Predicted survival (profiles, times, graph).
            self.fields.tab(variables, text=tr(WEIBULL_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(WEIBULL_TAB_KEYS["Model"]))
            fields_by_tab.update(dict.fromkeys(WEIBULL_DATA, variables))
            fields_by_tab.update(dict.fromkeys(WEIBULL_MODEL, options))
            tabs = {tr(WEIBULL_TAB_KEYS["Predicted survival"]): WEIBULL_PREDICT}
        elif self.method == ORDINAL_LOGIT:
            # Variables (columns and the order of the categories) / Options (level) / Profiles (profiles and graph).
            fields_by_tab[ORDINAL_ORDER] = variables
            tabs = {ORDINAL_PROFILE_TAB: ORDINAL_PROFILE_FIELDS}
        elif self.method == RMST:
            # Data (columns, reference group, horizon) / Codes and estimate (status codes, level, graph).
            self.fields.tab(variables, text=tr(RMST_TAB_KEYS["Data"]))
            self.fields.tab(options, text=tr(RMST_TAB_KEYS["Options"]))
            fields_by_tab.update(dict.fromkeys(RMST_DATA, variables))
            fields_by_tab.update(dict.fromkeys(RMST_ESTIMATES, options))
        elif self.method == "Nonlinear regression":
            tabs = {tr("parameter_ci.tab"): (*PARAM_CI_OPTIONS, REPORT_LOG_IC50,
                                            NL_BAND, NL_BAND_LEVEL, NL_BAND_DRAWING),
                    regression_range.TAB_TITLE: (*regression_range.FIELDS, regression_range.SHOW_OUTSIDE)}
        elif self.method == "Linear regression":
            tabs = {regression_range.TAB_TITLE: (*regression_range.FIELDS, regression_range.SHOW_OUTSIDE)}
        elif self.method == CUSTOM_EQUATION:
            # Variables / Equation / Parameters / Output; the two editors get tabs of their own.
            self.fields.tab(options, text=ui("Output"))
            fields_by_tab["Weighting"] = variables
            fields_by_tab.update(dict.fromkeys((PARAM_CI_METHOD, CUSTOM_LEVEL, CUSTOM_POINTS), options))
            tabs = {"Equation": (CUSTOM_SYNTAX, "Equation"), "Parameters": ("Parameters",)}
            if not saved:
                saved = {"Equation": DEFAULT_EQUATION, "Parameters": [dict(record) for record in EXAMPLE_PARAMETERS]}
        elif self.method == GLOBAL_CUSTOM_EQUATION:
            # Variables / Equation / Parameters / Series constraints / Output.
            self.fields.tab(options, text=ui("Output"))
            fields_by_tab["Weighting"] = variables
            fields_by_tab[CUSTOM_SD] = variables
            fields_by_tab.update(dict.fromkeys(GLOBAL_TABS["Output"], options))
            tabs = {name: labels for name, labels in GLOBAL_TABS.items() if name != "Output"}
            if not saved:
                saved = {"Equation": DEFAULT_EQUATION,
                         "Parameters": [dict(record) for record in GLOBAL_EXAMPLE],
                         "Series constraints": []}
        elif self.method == REFERENCE_NORMALIZATION:
            self.fields.tab(variables, text=ui("Input"))
            self.fields.tab(options, text=ui("References"))
            fields_by_tab.update(dict.fromkeys(REFERENCE_INPUT_FIELDS, variables))
            fields_by_tab.update(dict.fromkeys(REFERENCE_REFERENCE_FIELDS, options))
            tabs = {"Output": REFERENCE_OUTPUT_FIELDS}
        for tab, labels in tabs.items():
            if self.method == HEAT_MAP and tab == HEAT_MAP_TAB_LAYOUT:
                outer = ttk.Frame(self.fields)
                self.fields.add(outer, text=tr("heat.layout.tab"))
                frame = self._make_scrollable_tab(outer)
            elif ((self.method in (CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION) and tab == "Equation")
                  or (self.method == "Multifactor ANOVA" and tab == ANOVA_MODEL_TAB)):
                # Scrollable pages: the conditional equation guide (0.81) and the ANOVA Model terms (0.83) can
                # exceed the page.
                outer = ttk.Frame(self.fields)
                self.fields.add(outer, text=ui(tab))
                frame = self._make_scrollable_tab(outer)
            else:
                frame = ttk.Frame(self.fields, padding=10)
                frame.columnconfigure(1, weight=1)
                self.fields.add(frame, text=ui(tab))
            positions[frame] = 0
            fields_by_tab.update(dict.fromkeys(labels, frame))
        if self.method == "Multifactor ANOVA":
            page = fields_by_tab[ANOVA_TERM_SELECTION]
            while page.master is not self.fields:
                page = page.master
            self.fields.insert(1, page)
        if self.method == "Multiple regression":
            # The Gaussian weighting stays on Options with its SD and weight columns (no extra tab keeps the dialog
            # narrow); the future precision of the profiles sits beside the profiles.
            fields_by_tab.update(dict.fromkeys((mlr_weighting.SD_COLUMN, mlr_weighting.WEIGHT_COLUMN), options))
            fields_by_tab[mlr_weighting.FUTURE_PRECISION] = fields_by_tab[LINEAR_CI]
        if self.method == COMPARE_MODELS:
            # Data, Models, Output: the models are chosen right after the columns.
            self.fields.insert(1, fields_by_tab[MODELS_FIELD])
        def notebook_page(frame):
            # A scrollable tab holds its fields in a frame inside a canvas; the notebook moves the outer page.
            while frame.master is not self.fields:
                frame = frame.master
            return frame

        if self.method == CUSTOM_EQUATION:
            self.fields.insert(1, notebook_page(fields_by_tab["Equation"]))
            self.fields.insert(2, fields_by_tab["Parameters"])
        if self.method == GLOBAL_CUSTOM_EQUATION:
            for index, name in enumerate(("Equation", "Parameters", "Series constraints"), start=1):
                self.fields.insert(index, notebook_page(fields_by_tab[name]))
        category_roles = {"Group", "Rows", "Columns", "Subject", "Row label", "Row factor variable",
                          "Column factor variable", "Row (treatment) variable", "Column (outcome) variable",
                          "X categories", "Y categories"}
        if self.method == precision_recall.METHOD:
            category_roles.add(precision_recall.OUTCOME)
        numeric_position, category_position = 0, 0
        for label, kind in METHODS[self.method].items():
            if self.method == "Multifactor ANOVA" and label in planned_contrasts.KEYS:
                continue  # The planned-contrast editor owns these four fields.
            use_vars = (kind in (MULTIPLE, OPTIONAL_MULTIPLE, OPTIONAL, None) or label == "Input format"
                        or (self.method == "t-test" and label in ("Design", ttest_options.INPUT))) and label not in {
                "Comparison factor", "Condition on factors",
            }
            parent = fields_by_tab.get(label, variables if use_vars else options)
            row = positions[parent]
            positions[parent] += 1
            # The new rank-test controls show translated captions; the recipe keeps the English key.
            rank_control = self.method in RANK_METHODS and label in RANK_LABEL_KEYS
            parameter_ci_control = self.method in ("Nonlinear regression", CUSTOM_EQUATION,
                                                    GLOBAL_CUSTOM_EQUATION) and label in PARAM_CI_LABELS
            band_control = self.method == "Nonlinear regression" and label in NL_BAND_LABELS
            xy_error_control = self.method == XY_ERRORS and label in XY_ERROR_LABEL_KEYS
            trend_control = self.method == "One-way ANOVA" and label in TREND_HEADINGS
            variance_control = self.method == "One-way ANOVA" and label in VARIANCE_LABEL_KEYS
            lognormal_control = self.method == "One-way ANOVA" and label in lognormal_anova.LABEL_KEYS
            fit_control = self.method == "Nonlinear regression" and label in FIT_HEADINGS
            ratio_control = self.method == LOGNORMAL and label in RATIO_LABEL_KEYS
            variance_ratio_control = self.method == VARIANCE_RATIO and label in VARIANCE_RATIO_LABELS
            tost_control = self.method == EQUIVALENCE and label in TOST_LABEL_KEYS
            meta_control = self.method == META_ANALYSIS and label in META_LABEL_KEYS
            paired_control = self.method == PAIRED_PROPORTIONS and label in PAIRED_LABEL_KEYS
            tolerance_control = self.method == TOLERANCE and label in TOLERANCE_LABEL_KEYS
            anova_diag_control = self.method == "Multifactor ANOVA" and label in ANOVA_DIAG_LABEL_KEYS
            robust_control = self.method == ROBUST_CURVE and label in ROBUST_LABEL_KEYS
            kappa_control = self.method == COHEN_KAPPA and label in KAPPA_LABEL_KEYS
            competing_control = self.method == COMPETING_RISKS and label in COMPETING_LABEL_KEYS
            nb2_control = self.method == NB2 and label in NB2_LABEL_KEYS
            weibull_control = self.method == WEIBULL_AFT and label in WEIBULL_LABEL_KEYS
            rmst_control = self.method == RMST and label in RMST_LABEL_KEYS
            reference_control = self.method == REFERENCE_NORMALIZATION and label in REFERENCE_LABEL_KEYS
            label_text = (tr(ttest_options.LABEL_KEYS[label]) if self.method == "t-test" and label in ttest_options.LABEL_KEYS
                          else tr(RANK_LABEL_KEYS[label]) if rank_control
                          else tr(ROBUST_LABEL_KEYS[label]) if robust_control
                          else tr(KAPPA_LABEL_KEYS[label]) if kappa_control
                          else tr(COMPETING_LABEL_KEYS[label]) if competing_control
                          else tr(NB2_LABEL_KEYS[label]) if nb2_control
                          else tr(WEIBULL_LABEL_KEYS[label]) if weibull_control
                          else tr(RMST_LABEL_KEYS[label]) if rmst_control
                          else tr(RATIO_LABEL_KEYS[label]) if ratio_control
                          else tr(VARIANCE_RATIO_LABELS[label]) if variance_ratio_control
                          else tr(TOST_LABEL_KEYS[label]) if tost_control
                          else tr(META_LABEL_KEYS[label]) if meta_control
                          else tr(PAIRED_LABEL_KEYS[label]) if paired_control
                          else tr(TOLERANCE_LABEL_KEYS[label]) if tolerance_control
                          else tr(PARAM_CI_LABELS[label]) if parameter_ci_control
                          else tr(NL_BAND_LABELS[label]) if band_control
                          else tr(XY_ERROR_LABEL_KEYS[label]) if xy_error_control
                          else tr(TREND_HEADINGS[label]) if trend_control
                          else tr(VARIANCE_LABEL_KEYS[label]) if variance_control
                          else tr(lognormal_anova.LABEL_KEYS[label]) if lognormal_control
                          else tr(FIT_HEADINGS[label]) if fit_control
                          else tr(ANOVA_DIAG_LABEL_KEYS[label]) if anova_diag_control
                          else tr(REFERENCE_LABEL_KEYS[label]) if reference_control else label)
            if self.method in kmeans_options.METHODS and label == kmeans_reports.SCALED:
                label_text = "Report scaled observations"
            heading = ttk.Label(parent, text=ui(label_text), wraplength=170)
            heading.grid(row=row, column=0, sticky="nw", pady=4, padx=(0, 10))
            if kind == PAIR_LIST:
                field = BeforeAfterPairs(parent, columns, numeric, saved.get(label, ()))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind in (DUNN_PAIR_LIST, PAIRWISE_PAIR_LIST):
                field = PairPicker(parent, saved.get(label, ()))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == PROFILE_LIST:
                if label == LINEAR_PROFILES:
                    field = ProfileEditor(parent, self.data, saved.get(label, ()), label_key="name",
                                          values_key="values", weight_key="weight",
                                          hint="Up to 12 profiles. Predictions use this fit and its reference levels.",
                                          on_change=self.show_regression_fields)
                elif label == LOGISTIC_PROFILES:
                    field = ProfileEditor(parent, self.data, saved.get(label, ()), label_key="name",
                                          values_key="values", hint=tr("analysis.logistic.hint"),
                                          on_change=self.show_regression_fields)
                elif self.method == WEIBULL_AFT:
                    field = ProfileEditor(parent, self.data, saved.get(label, ()), label_key=WEIBULL_NAME,
                                          hint=tr(WEIBULL_HINTS["profile"]))
                elif self.method == ORDINAL_LOGIT and label == ORDINAL_PROFILES:
                    field = ProfileEditor(parent, self.data, saved.get(label, ()), label_key=ORDINAL_NAME,
                                          values_key=ORDINAL_VALUES, hint=tr("ord.hint.profiles"))
                else:
                    field = ProfileEditor(parent, self.data, saved.get(label, ()))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind in (WEIBULL_TIME_LIST, ORDINAL_ORDER_KIND):
                # One time per line, kept as typed; the analysis names the line that cannot be used.
                if kind == WEIBULL_TIME_LIST:
                    field = WeibullTimesEditor(parent, saved.get(label))
                else:
                    field = OrderEditor(parent, saved.get(label) or ())
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == SETS_LIST:
                field = TransposeSets(parent, columns, saved.get(label, ()), lambda: propose_sets(
                    self.data, self.controls[TRANSPOSE_X][1].get()))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == EQUATION_TEXT:
                positions[parent] += 1
                checker = (self.check_global_custom_equation if self.method == GLOBAL_CUSTOM_EQUATION
                           else self.check_custom_equation)
                field = EquationEditor(parent, saved.get(label, ""), on_check=checker)
                field.grid(row=row + 1, column=0, columnspan=2, sticky="nsew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind in (COMPETING_CODE_LIST, COMPETING_TIME_LIST):
                # One value per line, kept as typed; a change of the event codes refreshes the drawn-cause choices.
                if kind == COMPETING_CODE_LIST:
                    field = CodeListEditor(parent, saved.get(label), on_change=self.refresh_competing_causes)
                else:
                    field = TimeListEditor(parent, saved.get(label))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == KAPPA_ORDER_LIST:
                # The saved order is shown as it is; the categories of the data are compared with it, not merged.
                field = CategoryOrderEditor(parent, saved.get(label) or [])
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == COMPETING_CAUSE:
                # The empty value means the first cause. Other values are literal codes, never translated.
                variable = tk.StringVar(value=saved.get(label) or "")
                field = ttk.Combobox(parent, textvariable=variable, state="readonly", width=27)
                self.choice_bindings[label] = ChoiceBinding(field, variable, [""], {"": COMPETING_CHOICE_KEYS[""]})
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, variable)
                self.field_rows[label] = heading, field
                continue
            if kind == PARAMETER_LIST:
                positions[parent] += 1
                field = ParameterTable(parent, saved.get(label, ()),
                                       equation=lambda: self.controls["Equation"][1].values(),
                                       syntax=self.equation_syntax)
                field.grid(row=row + 1, column=0, columnspan=2, sticky="nsew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == GLOBAL_PARAMETER_LIST:
                positions[parent] += 1
                field = GlobalCoefficientTable(parent, saved.get(label, ()),
                                               equation=lambda: self.controls["Equation"][1].values(),
                                               syntax=self.equation_syntax)
                field.grid(row=row + 1, column=0, columnspan=2, sticky="nsew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == GLOBAL_SERIES_LIST:
                positions[parent] += 1
                field = SeriesConstraintEditor(
                    parent, saved.get(label, []),
                    names=lambda: [row["name"] for row in self.controls["Parameters"][1].values()],
                    series=self.global_series_labels)
                field.grid(row=row + 1, column=0, columnspan=2, sticky="nsew", pady=3)
                self.global_series = field
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == CURVE_LIST:
                # The editor spans the tab under its heading; Model is already placed on the Function tab.
                positions[parent] += 1
                field = CurveEditor(parent, self.controls[FUNCTION_MODEL][1].get(),
                                    saved.get(label, FUNCTION_EXAMPLE))
                field.grid(row=row + 1, column=0, columnspan=2, sticky="nsew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == INITIAL_LIST:
                field = InitialParameters(parent, saved.get(label, {}), model=lambda: self.controls[ROBUST_MODEL][1].get(),
                                          proposal=self.robust_proposal)
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == CATEGORY_COLOR_LIST:
                field = CategoryColorsField(parent, saved.get(label), self.heat_map_levels)
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == TERM_LIST:
                # The checkboxes sit under their heading and use the width of the page.
                positions[parent] += 1
                field = TermPicker(parent, saved.get(label), factors=self.anova_factors,
                                   response=lambda: self.controls["Response"][1].get(),
                                   selected=lambda: self.controls[ANOVA_TERM_SELECTION][1].get() != ANOVA_FULL_TERMS,
                                   order=lambda: self.controls["Interaction order"][1].get(),
                                   on_build=lambda widgets, page=parent: self._bind_scrollable_widgets(page, widgets))
                field.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == MODEL_LIST:
                field = ModelPicker(parent, saved.get(label))
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == GROUP_ORDER:
                field = OrderPicker(parent)
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if kind == TREND_ORDER_KIND:
                field = TrendOrder(parent)
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = (kind, field)
                self.field_rows[label] = heading, field
                continue
            if self.method == reshape.METHOD and label in reshape_tk.ORDERED_FIELDS:
                field = reshape_tk.OrderedColumns(parent, columns, saved.get(label) or ())
                field.grid(row=row, column=1, sticky="ew", pady=3)
                self.controls[label] = kind, field
                self.field_rows[label] = heading, field
                continue
            if kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                panel = ttk.Frame(parent)
                panel.grid(row=row, column=1, sticky="ew", pady=3)
                box = tk.Listbox(panel, selectmode="extended", exportselection=False, height=4)
                scroll = ttk.Scrollbar(panel, orient="vertical", command=box.yview)
                box.configure(yscrollcommand=scroll.set)
                scroll.pack(side="right", fill="y")
                box.pack(side="left", fill="both", expand=True)
                default_columns = columns if self.method == SELECT_TRANSFORM else numeric
                # Tolerance intervals starts without a selection: the columns are a required choice.
                defaults = saved.get(label, default_columns if label in {"Variables", "Count columns"}
                                     and self.method != TOLERANCE else ())
                offered = list(dict.fromkeys([*columns, *defaults])) if label == "Condition on factors" else columns
                if label in saved:
                    available = set(offered)
                    selected = [name for name in defaults if name in available]
                    offered = list(dict.fromkeys(selected + list(offered)))
                for i, name in enumerate(offered):
                    box.insert("end", name)
                    if name in defaults:
                        box.selection_set(i)
                self.controls[label] = (kind, box)
                self.field_rows[label] = heading, panel
                continue
            if type(kind) is bool:
                variable = tk.BooleanVar(value=saved.get(label, kind))
                field = ttk.Checkbutton(parent, variable=variable)
            elif type(kind) in (int, float) or kind == TEXT:
                default = ("0" if self.method == "Prune rows" and label == "X threshold" else "") if kind == TEXT else kind
                if self.method == "Kaplan–Meier survival":
                    default = STATUS_DEFAULTS.get(label, default)
                if self.method == COX:
                    default = COX_STATUS.get(label, default)
                if self.method == COMPETING_RISKS:
                    default = COMPETING_DEFAULTS.get(label, default)
                if self.method == PAIRED_PROPORTIONS:
                    default = PAIRED_DEFAULT_CODES.get(label, default)
                if self.method == WEIBULL_AFT:
                    default = WEIBULL_DEFAULTS.get(label, default)
                if self.method == RMST:
                    default = RMST_DEFAULTS.get(label, default)
                if self.method == HEAT_MAP:
                    default = HEAT_MAP_GRADIENT_COLORS.get(label, default)
                    if label == CELL_LABEL_COLOR:
                        default = DEFAULT_LABEL_COLOR
                if self.method == POWER_METHOD:
                    default = POWER_TEXT_DEFAULTS.get(label, default)
                raw_saved = saved.get(label, default)
                variable = tk.StringVar(value=str(default if raw_saved is None else raw_saved))
                if self.method == POWER_METHOD and label == POWER_GROUP_MEANS:
                    field = MultilineEntry(parent, variable)
                elif self.method == HEAT_MAP and label == CELL_LABEL_COLOR:
                    field = ttk.Frame(parent)
                    swatch = tk.Label(field, width=3, relief="solid", borderwidth=1)
                    swatch.pack(side="left", padx=(0, 6))
                    entry = ttk.Entry(field, textvariable=variable)
                    entry.pack(side="left", fill="x", expand=True)
                    ttk.Button(field, text=ui("Pick…"), command=lambda color=variable: pick_color(self, color)).pack(
                        side="right", padx=(6, 0))

                    def _update_swatch(*_, var=variable, box=swatch):
                        text = var.get().strip()
                        try:
                            box.configure(background=to_hex(text) if text and is_color_like(text) else DEFAULT_LABEL_COLOR)
                        except ValueError:
                            box.configure(background=DEFAULT_LABEL_COLOR)

                    swatch_trace = variable.trace_add("write", _update_swatch)
                    swatch.bind("<Destroy>", lambda _e, var=variable, tid=swatch_trace: var.trace_remove("write", tid))
                    _update_swatch()
                    field.focus_target = lambda widget=entry: widget
                elif ((self.method == "Scatter / confidence ellipse" and label in {"Fill color", "Border color"})
                        or (self.method == HEAT_MAP and label in {
                            "Missing color", HEAT_MAP_OUTSIDE, HEAT_MAP_MIN_COLOR, HEAT_MAP_MID_COLOR,
                            HEAT_MAP_MAX_COLOR})
                        or (self.method == PARTS_GRAPH and label == BORDER_COLOR)
                        or (self.method == XY_ERRORS and label == XY_ERROR_COLOR)):
                    field = ttk.Frame(parent)
                    ttk.Entry(field, textvariable=variable).pack(side="left", fill="x", expand=True)
                    ttk.Button(field, text=ui("Pick…"), command=lambda color=variable: pick_color(self, color)).pack(
                        side="right", padx=(6, 0))
                else:
                    field = ttk.Entry(parent, textvariable=variable)
            else:
                choices = (kind if isinstance(kind, tuple) else [] if kind == GROUP_CHOICE
                           else forest_labels if kind == FOREST_ROW_CHOICE
                           else [""] + columns if kind == OPTIONAL else columns)
                if self.method == "Kaplan–Meier survival" and label == PAIRWISE_CORRECTION:
                    choices = pairwise_corrections(saved)
                if self.method == rm_sphericity.METHOD and label == rm_sphericity.FIELD:
                    # The one-way spelling is offered only when the opened recipe already uses it.
                    choices = rm_sphericity.choices_for(saved)
                if kind == FOREST_ROW_CHOICE:
                    default = forest_rows.get(label, "")
                elif self.method == GROUPED_ANOVA and label == GROUPED_ANOVA_ROWS:
                    title = self.data.attrs.get("row_title_column", "Row title")
                    default = title if title in columns else (categorical or columns or [""])[0]
                elif kind is None and label in category_roles and categorical:
                    default = categorical[category_position % len(categorical)]
                    category_position += 1
                elif self.method == "t-test" and label in (ttest_options.FIRST, ttest_options.SECOND) and numeric:
                    default = numeric[min(int(label == ttest_options.SECOND), len(numeric) - 1)]
                elif kind is None and numeric:
                    default = numeric[numeric_position % len(numeric)]
                    numeric_position += 1
                else:
                    default = choices[0] if choices else ""
                variable = tk.StringVar(value=saved.get(label) or default)
                if label == "Model" and self.method in {"Nonlinear regression", "Global nonlinear regression",
                                                        PLOT_FUNCTION, ROBUST_CURVE}:
                    field = ttk.Frame(parent)
                    ttk.Entry(field, textvariable=variable, state="readonly", width=27).pack(
                        side="left", fill="x", expand=True)
                    ttk.Button(field, text=ui("Browse…"), command=lambda options=choices, model=variable:
                               self.choose_equation(options, model)).pack(side="right", padx=(6, 0))
                else:
                    field = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly", width=27)
                    if rank_control:
                        # Translated labels on screen, canonical values in the variable and the recipe.
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, RANK_CHOICE_KEYS)
                    elif parameter_ci_control and label == PARAM_CI_METHOD:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, PARAM_CI_CHOICES)
                    elif band_control and label != NL_BAND_LEVEL:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, NL_BAND_CHOICES)
                    elif xy_error_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, XY_ERROR_CHOICE_KEYS)
                    elif ratio_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, RATIO_CHOICE_KEYS)
                    elif variance_ratio_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, VARIANCE_RATIO_CHOICES)
                    elif tost_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, TOST_CHOICE_KEYS)
                    elif meta_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, META_CHOICE_KEYS)
                    elif paired_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, PAIRED_CHOICE_KEYS)
                    elif tolerance_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, TOLERANCE_CHOICE_KEYS)
                    elif robust_control and isinstance(kind, tuple) and label != ROBUST_MODEL:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, ROBUST_CHOICE_KEYS)
                    elif kappa_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, KAPPA_CHOICE_KEYS)
                    elif competing_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, COMPETING_CHOICE_KEYS)
                    elif nb2_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, NB2_CHOICE_KEYS)
                    elif weibull_control and isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, WEIBULL_CHOICE_KEYS)
                    elif self.method in (CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION) and label == CUSTOM_SYNTAX:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, SYNTAX_CHOICE_KEYS)
                    elif self.method == CUSTOM_EQUATION and label == "Weighting":
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, CUSTOM_WEIGHTING_KEYS)
                    elif self.method == GLOBAL_CUSTOM_EQUATION and label == "Weighting":
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, GLOBAL_WEIGHTING_KEYS)
                    elif (self.method == GLOBAL_CUSTOM_EQUATION and isinstance(kind, tuple)
                          and label in GLOBAL_TABS["Response"]):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, GLOBAL_RESPONSE_CHOICES)
                    elif self.method == "Principal component analysis" and label == PCA_SELECTION:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, PCA_CHOICE_KEYS)
                    elif self.method == "Principal component analysis" and label in (pca_overlays.KIND, pca_overlays.GROUPING):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, pca_overlays.CHOICE_KEYS)
                    elif self.method == "Principal component analysis" and label == PCR_PLOT:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices,
                                                                    PCA_REGRESSION_CHOICE_KEYS)
                    elif self.method == "Multiple regression" and label == mlr_weighting.GAUSSIAN_WEIGHTING:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, MLR_CHOICE_KEYS)
                    elif self.method == "Multifactor ANOVA" and label == ANOVA_DIAG_GRAPH:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, ANOVA_GRAPH_CHOICE_KEYS)
                    elif self.method == "t-test" and label in {"Design", ttest_options.INPUT, ttest_options.ALTERNATIVE}:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, ttest_options.CHOICE_KEYS)
                    elif self.method == "Multifactor ANOVA" and label == anova_diagnostics.TEST_SET:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices,
                                                                    anova_diagnostics.TEST_CHOICE_KEYS)
                    elif self.method == HEAT_MAP and label == HEAT_MAP_NUMBER_FORMAT:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, HEAT_MAP_NUMBER_FORMAT_KEYS)
                    elif self.method == HEAT_MAP and label == CELL_LABEL_NUMBER_FORMAT:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices,
                                                                    HEAT_MAP_CELL_LABEL_FORMAT_KEYS)
                    elif self.method == HEAT_MAP and label == CELL_LABEL_COLOR_MODE:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices,
                                                                    HEAT_MAP_CELL_LABEL_COLOR_MODE_KEYS)
                    elif self.method == HEAT_MAP and label in HEAT_MAP_LAYOUT_CHOICE_KEYS:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices,
                                                                    HEAT_MAP_LAYOUT_CHOICE_KEYS[label])
                    elif self.method == "One-way ANOVA" and label in (
                            lognormal_anova.DISTRIBUTION, lognormal_anova.RATIO_DIRECTION):
                        self.choice_bindings[label] = ChoiceBinding(
                            field, variable, choices, lognormal_anova.CHOICE_KEYS)
                    elif self.method == SUMMARY_ANOVA and label == "Post-hoc":
                        # Both families stay translatable. set_values later shows only the compatible list
                        # and does not rewrite an incompatible value the user already chose.
                        self.choice_bindings[label] = ChoiceBinding(
                            field, variable, choices,
                            fixed_choice_keys((*SUMMARY_ORDINARY_POSTHOC, *SUMMARY_UNEQUAL_POSTHOC)))
                    elif self.method == rm_sphericity.METHOD and label == rm_sphericity.FIELD:
                        self.choice_bindings[label] = ChoiceBinding(
                            field, variable, choices,
                            {**fixed_choice_keys(choices), rm_sphericity.LEGACY: "rm.sphericity.choice.legacy"})
                    elif self.method == reshape.METHOD and label == reshape.DIRECTION:
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, reshape_tk.DIRECTION_KEYS)
                    elif isinstance(kind, tuple):
                        self.choice_bindings[label] = ChoiceBinding(field, variable, choices, fixed_choice_keys(choices))
            field.grid(row=row, column=1, sticky="ew", pady=3)
            self.controls[label] = (kind, variable)
            self.field_rows[label] = heading, field
            if self.method == "Multifactor ANOVA" and label == ANOVA_SUMS_OF_SQUARES:
                positions[parent] += 1  # the notes and the factor order of Type I use the next row
        if self.method == "Descriptive statistics":
            report = self.controls[SUMMARY_FORMAT][1]
            report.trace_add("write", lambda *_: self.show_fields(summary_fields(report.get())))
            self.show_fields(summary_fields(report.get()))
        if self.method in INPUT_FIELDS:
            input_format = self.controls["Input format"][1]
            input_format.trace_add("write", lambda *_: self.show_input_fields())
            self.show_input_fields()
        if self.method == "Kaplan–Meier survival":
            for name in ("Event columns", "Grouping variables"):
                self.controls[name][1].bind("<<ListboxSelect>>", lambda _: self.update_survival_groups())
            self.controls["Time"][1].trace_add("write", lambda *_: self.update_survival_groups())
            for name in (EVENT_CODE, CENSOR_CODE):
                self.field_rows[name][1].bind("<FocusOut>", lambda _: self.update_survival_groups())
            self.field_rows[OTHER_STATUS][1].bind("<<ComboboxSelected>>", lambda _: self.update_survival_groups())
            status_tab = fields_by_tab[OTHER_STATUS]
            ttk.Label(status_tab, text=ui("Use the same codes for all selected status columns. Text matches as written."),
                      wraplength=370, foreground="#486075").grid(
                          row=positions[status_tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            for name in ("Log-rank trend", "Hazard ratio", PAIRWISE_CORRECTION, PAIRWISE_SCOPE, PAIRWISE_ADJUSTED):
                self.controls[name][1].trace_add("write", lambda *_: self.show_survival_fields())
            self.update_survival_groups(saved.get("Trend group order") or ())
        if self.method in DUNN_METHODS:
            for name in ("Response", "Group", DUNN):
                self.controls[name][1].trace_add("write", lambda *_: self.show_dunn_fields())
            self.show_dunn_fields()
        if self.method in PROCESSING_METHODS:
            for label in ("Replace zero X", "Change units", "Baseline", "Replicate handling", "Method",
                          "Average only rows above an X threshold", "Confidence interval", "Divide by"):
                if label in self.controls:
                    self.controls[label][1].trace_add("write", lambda *_: self.show_processing_fields())
            self.show_processing_fields()
        if self.method in kmeans_options.METHODS:
            for name in (kmeans_options.ALGORITHM, kmeans_options.GAP_PLOT, "Criterion", kmeans_options.SCALE):
                if name in self.controls:
                    self.controls[name][1].trace_add("write", lambda *_: self.show_fields(self.kmeans_visibility()))
            self.show_fields(self.kmeans_visibility())
        if self.method == kmeans_stability.METHOD:
            self.controls[kmeans_stability.ALGORITHM][1].trace_add(
                "write", lambda *_: self.show_fields(self.kmeans_visibility()))
            self.show_fields(self.kmeans_visibility())
        if self.method in {kmeans_stability.METHOD, logistic_validation.METHOD}:
            self._bind_scrollable_children(options)
        if self.method == "Hierarchical clustering":
            for label in ("Direction", "Row cut", "Column cut", "Graph output", "Distance matrix",
                          "Cophenetic distances", GAP_DATA):
                self.controls[label][1].trace_add("write", lambda *_: self.show_hierarchical_fields())
            self.show_hierarchical_fields()
        if self.method == HIERARCHY_GRAPH:
            self.controls["Graph output"][1].trace_add("write", lambda *_: self.show_hierarchical_fields())
            self.show_hierarchical_fields()
        if self.method == "Scatter / confidence ellipse":
            parent = fields_by_tab["Fill"]
            row = positions[parent]
            heading = ttk.Label(parent, text=ui(ELLIPSE_GROUP_STYLES), wraplength=170)
            heading.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            editor = ttk.Button(parent, text=ui("Edit group styles…"), command=self.edit_ellipse_group_styles)
            editor.grid(row=row, column=1, sticky="w", pady=4)
            self.field_rows[ELLIPSE_GROUP_STYLES] = heading, editor
            self.ellipse_group_styles = deepcopy(saved.get(ELLIPSE_GROUP_STYLES, {}))
            for label in ("Ellipse", "Ellipse grouping", "Group", "Ellipse group", "Fill", "Border", "Center marker"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_ellipse_fields())
            self.show_ellipse_fields()
        if self.method in CATEGORY_GRAPHS:
            labels = ("Graph style", "Interval", "Overlay observations")
            if self.method == GROUPED_GRAPH:
                labels += ("Input", "Placement of groups", "Summary error")
            for label in labels:
                self.controls[label][1].trace_add("write", lambda *_: self.show_category_fields())
            self.show_category_fields()
        if self.method == ROW_TESTS:
            for label in ("Input format", "Test", "Correction"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_row_test_fields())
            self.show_row_test_fields()
        if self.method == HEAT_MAP:
            for label in ("Input format", "Color scale", HEAT_MAP_MAPPING, HEAT_MAP_INTERVAL, HEAT_MAP_SHOW_LEGEND,
                          HEAT_MAP_NUMBER_FORMAT, "Show cell values", CELL_LABEL_NUMBER_FORMAT,
                          CELL_LABEL_COLOR_MODE, ROW_GAP_MODE, COLUMN_GAP_MODE, SHOW_ROW_LABELS,
                          ROW_LABEL_FREQUENCY, SHOW_COLUMN_LABELS, COLUMN_LABEL_FREQUENCY):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.heat_map_visibility()))
            for label in ("X categories", "Y categories", "Values", "Input format"):
                self.controls[label][1].trace_add("write", lambda *_: self.controls[HEAT_MAP_CATEGORY_COLORS][1].refresh())
            for name, note in ((HEAT_MAP_MAPPING, "heat.note.colors"), (HEAT_MAP_INTERVAL, "heat.note.legend")):
                tab = fields_by_tab[name]
                ttk.Label(tab, text=tr(note), wraplength=ui_theme.px(400), foreground="#486075", justify="left").grid(
                    row=positions[tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            layout_tab = fields_by_tab[ROW_GAP_MODE]
            for offset, note in enumerate(("heat.layout.note.gaps", "heat.layout.note.labels")):
                ttk.Label(layout_tab, text=tr(note), wraplength=ui_theme.px(380), foreground="#486075",
                          justify="left").grid(
                    row=positions[layout_tab] + offset, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self._bind_scrollable_children(layout_tab)
            self.show_fields(self.heat_map_visibility())
        if self.method == REFERENCE_NORMALIZATION:
            for label in ("Input", "Replicates", "Zero reference", "One reference", "Error format"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_reference_fields())
            input_tab = fields_by_tab["Input"]
            self.reference_replicate_note = ttk.Label(input_tab, text="", wraplength=ui_theme.px(400),
                                                      foreground="#486075", justify="left")
            self.reference_replicate_note.grid(row=positions[input_tab], column=0, columnspan=2, sticky="w",
                                               pady=(8, 0))
            reference_tab = fields_by_tab["Zero reference"]
            ttk.Label(reference_tab, text=tr("reference.note.rows"), wraplength=ui_theme.px(400),
                      foreground="#486075", justify="left").grid(
                row=positions[reference_tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            output_tab = fields_by_tab["Graph results"]
            ttk.Label(output_tab, text=tr("reference.note.uncertainty"), wraplength=ui_theme.px(400),
                      foreground="#486075", justify="left").grid(
                row=positions[output_tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.show_reference_fields()
        if self.method == rm_sphericity.METHOD:
            # A note under the choice says what each correction does and what it does not add.
            self.sphericity_note = ttk.Label(options, text="", wraplength=ui_theme.px(420), foreground="#486075",
                                             justify="left")
            self.sphericity_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls[rm_sphericity.FIELD][1].trace_add("write", lambda *_: self.show_sphericity_note())
            self.show_sphericity_note()
        if self.method == CORRELATION_MATRIX:
            self.controls["Method"][1].trace_add("write", lambda *_: self.show_fields(self.correlation_visibility()))
            self.show_fields(self.correlation_visibility())
        if self.method in CORRELATION_METHODS:
            note = {"Correlation": "corr.details.note.single", CORRELATE_CONTROL: "corr.details.note.control",
                    COMPARE_INDEPENDENT: "corr.details.note.independent"}[self.method]
            ttk.Label(options, text=tr(note), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            for label in ("Detailed results", "Method", "Spearman p values"):
                if label in self.controls:
                    self.controls[label][1].trace_add("write", lambda *_: self.show_correlation_details())
            self.show_correlation_details()
        if self.method == RMCORR:
            # The model and its difference from pooled Pearson sit under the columns; the bootstrap note on Options.
            for tab, key in ((variables, RMCORR_NOTE_MODEL), (options, RMCORR_NOTE_BOOTSTRAP)):
                ttk.Label(tab, text=tr(key), wraplength=ui_theme.px(420), foreground="#486075", justify="left").grid(
                    row=positions[tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls[RMCORR_INTERVAL][1].trace_add("write", lambda *_: self.show_rmcorr_fields())
            self.show_rmcorr_fields()
        if self.method == FREQUENCY:
            for label in ("Distribution", "Units"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_frequency_fields())
            self.show_frequency_fields()
        if self.method == "Area under curve":
            self.controls[AUC_PEAKS][1].trace_add("write", lambda *_: self.show_fields(self.auc_visibility()))
            self.show_fields(self.auc_visibility())
        if self.method == "Bland–Altman":
            self.controls[BLAND_ALTMAN_INTERVALS][1].trace_add("write", lambda *_: self.show_fields(self.agreement_visibility()))
            self.show_fields(self.agreement_visibility())
        if self.method in RANK_METHODS:
            self.controls[RANK_P][1].trace_add("write", lambda *_: self.show_rank_fields())
            self.show_rank_fields()
            hint = ttk.Label(options, text=tr("rank.hint"), wraplength=370, foreground="#486075")
            hint.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == BOX_VIOLIN:
            for label in ("Input", "Style", "Whiskers", "Overlay observations"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.box_violin_visibility()))
            self.show_fields(self.box_violin_visibility())
        if self.method == GROUPED_DISTRIBUTIONS:
            for label in ("Style", "Whiskers", "Overlay observations"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.grouped_distribution_visibility()))
            self.show_fields(self.grouped_distribution_visibility())
        if self.method == "One-way ANOVA":
            for label in ("Response", "Group", "Post-hoc", unequal_anova.FAMILY, TREND, "Method",
                          VARIANCE_BROWN, VARIANCE_BARTLETT, lognormal_anova.DISTRIBUTION):
                self.controls[label][1].trace_add("write", lambda *_: self.show_one_way_fields())
            for label in ("Response", "Group"):
                self.controls[label][1].trace_add("write", lambda *_: self.refresh_trend_levels())
            self.refresh_trend_levels(saved.get(TREND_ORDER))
            note_parent = self.field_rows[VARIANCE_BROWN][0].master
            self.variance_note = ttk.Label(note_parent, text=tr("variance.assumptions.note"), wraplength=420,
                                           foreground="#486075", justify="left")
            self.variance_note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.lognormal_note = ttk.Label(options, text=tr("anova.lognormal.note"), wraplength=420,
                                            foreground="#486075", justify="left")
            self.lognormal_note.grid(row=20, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self._translate_analysis_labels(VARIANCE_LABEL_KEYS)
            self._translate_analysis_labels(lognormal_anova.LABEL_KEYS)
            self._bind_scrollable_children(options)
            self.show_one_way_fields()
        if self.method == ANCOVA:
            self.controls[ANCOVA_COMPARISONS][1].trace_add("write", lambda *_: self.show_ancova_fields())
            for label in ANCOVA_DATA_FIELDS:
                self.controls[label][1].trace_add("write", lambda *_: self.refresh_ancova_groups())
            for page, note in ((options, "ancova.note.model"), (options, "ancova.note.reference"),
                               (fields_by_tab[ANCOVA_COMPARISONS], "ancova.note.comparisons")):
                ttk.Label(page, text=tr(note), wraplength=ui_theme.px(400), foreground="#486075",
                          justify="left").grid(row=positions[page], column=0, columnspan=2, sticky="w", pady=(8, 0))
                positions[page] += 1
            self.show_ancova_fields()
        if self.method == "Multifactor ANOVA":
            self._anova_graph = self.controls[ANOVA_DIAG_GRAPH][1].get()
            for label in (ANOVA_EFFECTS, ANOVA_DIAGNOSTICS, ANOVA_ASSUMPTIONS, ANOVA_DIAG_GRAPH, ANOVA_TERM_SELECTION):
                self.controls[label][1].trace_add("write", lambda *_: self.show_anova_fields())
            picker = self.controls[ANOVA_MODEL_TERMS][1]
            self.controls["Factors"][1].bind("<<ListboxSelect>>", lambda _e: picker.refresh(), add="+")
            self.controls["Interaction order"][1].trace_add("write", lambda *_: picker.refresh())
            self.controls["Response"][1].trace_add("write", lambda *_: picker.sync())
            # Sums of squares: the note of the type, the order of the factors for Type I and the order of the terms.
            selector = self.field_rows[ANOVA_SUMS_OF_SQUARES][1]
            self.anova_order = SumsOfSquaresPanel(
                selector.master, saved.get("Factors"), kind=self.controls[ANOVA_SUMS_OF_SQUARES][1].get,
                factors=self.anova_listed, terms=picker.current_terms, on_order=picker.refresh)
            self.anova_order.grid(row=selector.grid_info()["row"] + 1, column=0, columnspan=2, sticky="ew", pady=(0, 3))
            self.controls["Factors"][1].bind("<<ListboxSelect>>", lambda _e: self.anova_order.refresh(), add="+")
            self.controls[ANOVA_SUMS_OF_SQUARES][1].trace_add("write", lambda *_: self.anova_order.sync())
            picker.listeners.append(self.anova_order.describe)
            picker.refresh()  # the term checkboxes now follow the order of the recipe being edited
            self.show_anova_fields()
            self._translate_analysis_labels(ANOVA_DIAG_LABEL_KEYS)
            model_page = self.field_rows[ANOVA_TERM_SELECTION][0].master
            self._bind_scrollable_children(model_page)
            self._bind_scrollable_widgets(model_page, picker.static_widgets())
            self._bind_scrollable_widgets(model_page, self.anova_order.static_widgets())
            self.contrast_panel = ContrastPanel(options, self, saved, self.anova_contrast_context)
            self.contrast_panel.grid(row=positions[options], column=0, columnspan=2, sticky="ew", pady=(8, 0))
            for field in planned_contrasts.KEYS:
                self.field_rows[field] = (self.contrast_panel, self.contrast_panel)
            self._bind_scrollable_children(options)
            self._bind_scrollable_widgets(options, [self.contrast_panel.button])
        if self.method == FOREST_PLOT:
            self.forest_order = [name for name in saved.get("Study columns", ()) if name in columns]
            self.controls["Study columns"][1].bind("<<ListboxSelect>>", lambda _: self.forest_columns())
            self.controls["Input"][1].trace_add("write", lambda *_: self.show_fields(self.forest_fields()))
            self.controls["Measure"][1].trace_add("write", lambda *_: self.forest_measure_defaults())
            self.controls["Row titles"][1].trace_add("write", lambda *_: self.update_forest_rows())
            ttk.Label(variables, text=FOREST_LIMITS_NOTE, wraplength=430, foreground="#486075").grid(
                row=positions[variables], column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Label(options, text=FOREST_REFERENCE_NOTE, wraplength=430, foreground="#486075").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.show_fields(self.forest_fields())
        if self.method == OUTLIERS:
            self.controls[OUTLIER_METHOD][1].trace_add("write", lambda *_: self.show_fields(self.outlier_fields()))
            self.show_fields(self.outlier_fields())
        if self.method == SPLINE_FIT:
            ttk.Label(options, text=SPLINE_NOTE, wraplength=430, foreground="#486075").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            for label in (SPLINE_METHOD, SPLINE_DIRECTION):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.spline_fields()))
            self.show_fields(self.spline_fields())
        if self.method == curve_pipeline.CURVE_METHOD:
            # The two notes sit under the fields: the pipeline note, then the smoothing note.
            self.curve_notes = [ttk.Label(options, text=tr(key), wraplength=ui_theme.px(430), foreground="#486075",
                                          justify="left") for key in CURVE_NOTE_KEYS]
            for offset, note in enumerate(self.curve_notes):
                note.grid(row=positions[options] + offset, column=0, columnspan=2, sticky="w", pady=(8, 0))
            for label in ("Method", curve_pipeline.OPERATION, curve_pipeline.SMOOTHING):
                self.controls[label][1].trace_add("write", lambda *_: self.show_curve_fields())
            self.show_curve_fields()
        if self.method == ROBUST_CURVE:
            model, editor = self.controls[ROBUST_MODEL][1], self.controls[ROBUST_INITIAL][1]
            model.trace_add("write", lambda *_: editor.set_model(model.get()))
            self.controls[ROBUST_SCALE_METHOD][1].trace_add("write", lambda *_: self.show_fields(self.robust_fields()))
            for name, key, tab in ((ROBUST_SCALE_METHOD, "analysis.robust_curve.hint.scale", options),
                                   (ROBUST_COMPARE, "analysis.robust_curve.hint.output", fields_by_tab[ROBUST_DISPLAY])):
                hint = ttk.Label(tab, text=tr(key), wraplength=ui_theme.px(400), foreground="#486075", justify="left")
                hint.grid(row=positions[tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.show_fields(self.robust_fields())
        if self.method == COHEN_KAPPA:
            self.configure_kappa_fields(variables, options, positions)
        if self.method == COMPETING_RISKS:
            self.controls[COMPETING_GRAPH][1].trace_add("write", lambda *_: self.show_fields(self.competing_fields()))
            self.show_fields(self.competing_fields())
            self.refresh_competing_causes()
        if self.method == NB2:
            # Dispersion alpha is shown (and validated) only for Fixed; the model note sits under the options.
            self.controls[NB2_MODE][1].trace_add("write", lambda *_: self.show_fields(self.nb2_fields()))
            ttk.Label(options, text=tr(NB2_HINT), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.show_fields(self.nb2_fields())
        if self.method == WEIBULL_AFT:
            self.configure_weibull_fields(variables, options, positions)
        if self.method == ORDINAL_LOGIT:
            # The order follows the response and the predictors; the profiles follow the predictors and the coding.
            self.controls["Response"][1].trace_add("write", lambda *_: self.update_ordinal_order())
            self.controls["Predictors"][1].bind("<<ListboxSelect>>", lambda _: self.update_ordinal_order(), add="+")
            self.controls["Categorical predictors"][1].bind(
                "<<ListboxSelect>>", lambda _: self.update_ordinal_profiles(), add="+")
            self.update_ordinal_order()
        if self.method == RMST:
            self.configure_rmst_fields(variables, options, positions)
        if self.method in (CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION):
            self.bind_equation_syntax()
            self._bind_scrollable_children(fields_by_tab["Equation"])
        if self.method == CUSTOM_EQUATION:
            self.controls["Weighting"][1].trace_add("write", lambda *_: self.show_fields(self.custom_fields()))
            self.show_fields(self.custom_fields())
            self._translate_analysis_labels(CUSTOM_LABEL_KEYS)
            ttk.Label(options, text=tr("custom.profile.hint"), wraplength=430,
                      foreground="#486075", justify="left").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == GLOBAL_CUSTOM_EQUATION:
            self.controls["Weighting"][1].trace_add("write", lambda *_: self.show_fields(self.global_custom_fields()))
            for name in ("X", "Y", "Group"):
                self.controls[name][1].trace_add("write", lambda *_: self.refresh_series_tab())
            for name in (GLOBAL_BAND, GLOBAL_PREDICT, GLOBAL_QUERY_INTERVAL):
                self.controls[name][1].trace_add("write", lambda *_: self.show_fields(self.global_custom_fields()))
            response = fields_by_tab[GLOBAL_BAND]
            self.global_response_note = ttk.Label(response, text=tr("gfit.response.note"), wraplength=520,
                                                  foreground="#486075", justify="left")
            self.global_response_note.grid(row=positions[response], column=0, columnspan=2, sticky="w", pady=(8, 0))
            # Wrap the note to the page width so the longer Italian text still fits at 1024x768.
            response.bind("<Configure>", lambda event: self.global_response_note.configure(
                wraplength=max(360, event.width - 24)), add="+")
            self.show_fields(self.global_custom_fields())
            self._translate_analysis_labels(GLOBAL_LABEL_KEYS)
            ttk.Label(options, text=tr("gfit.profile.hint"), wraplength=430,
                      foreground="#486075", justify="left").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.global_series.refresh_labels()
        if self.method == MONTE_CARLO_METHOD:
            for label in (MONTE_CARLO_STUDY, MONTE_CARLO_X_SOURCE):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.monte_carlo_fields()))
            ttk.Label(variables, text=ui("Reuse seed"), wraplength=170).grid(
                row=positions[variables], column=0, sticky="nw", pady=4, padx=(0, 10))
            seed = ttk.Frame(variables)
            seed.grid(row=positions[variables], column=1, sticky="w", pady=3)
            ttk.Button(seed, text=ui("New seed"), command=self.new_monte_carlo_seed).pack(side="left")
            ttk.Button(seed, text=ui("Copy seed"), command=self.copy_monte_carlo_seed).pack(side="left", padx=(6, 0))
            for row, note in enumerate((TEST_VS_TRUTH, REPEATABLE), start=positions[variables] + 1):
                ttk.Label(variables, text=note, wraplength=430, foreground="#486075").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self.show_fields(self.monte_carlo_fields())
        if self.method == NORMALITY:
            ttk.Label(options, text=tr("normality.lognormal.note"), wraplength=ui_theme.px(400),
                      foreground="#486075", justify="left").grid(
                          row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls[QQ_PLOT][1].trace_add("write", lambda *_: self.show_fields(self.normality_fields()))
            self.controls["Variables"][1].bind("<<ListboxSelect>>", lambda _: self.update_qq_choices())
            self.show_fields(self.normality_fields())
            self.update_qq_choices()
        if self.method in {PARTS_GRAPH, GOODNESS_OF_FIT}:
            if self.method == PARTS_GRAPH:
                self._install_segment_styles(saved, positions)
                if not saved.get(BORDER_COLOR):
                    self.controls[BORDER_COLOR][1].set("white")
            label = "Graph style" if self.method == PARTS_GRAPH else "Expected distribution"
            self.controls[label][1].trace_add("write", lambda *_: self.show_parts_fields())
            if self.method == GOODNESS_OF_FIT:
                # One line under the Options fields: what the exact test reports, or that the switch reset a value.
                self.goodness_note = ttk.Label(options, wraplength=ui_theme.px(400), foreground="#486075",
                                               justify="left")
                self.goodness_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
                self.controls[TEST_METHOD][1].trace_add("write", lambda *_: self.show_goodness_fields())
                self.show_goodness_fields()
            self.show_parts_fields()
        if self.method in NESTED_METHODS:
            self.show_fields(self.nested_visibility())
        if self.method == CONTINGENCY:
            for label in ("Input format", "Test", "Diagnostic measures"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_contingency_fields())
            self.show_contingency_fields()
        if self.method == EXTRACT_REARRANGE:
            self.controls[EXTRACT_OUTPUT][1].trace_add("write", lambda *_: self.show_extract_fields())
            self.show_extract_fields()
            self.fields.select(options)
        if self.method == "Linear regression":
            for label in ("Band", LINEAR_Y_CI, LINEAR_X_CI):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.linear_visibility()))
            self.show_fields(self.linear_visibility())
            self._translate_analysis_labels(LINEAR_ESTIMATE_LABELS)
        if self.method == COMPARE_LINES:
            self.controls["Input"][1].trace_add("write", lambda *_: self.show_fields(self.compare_lines_fields()))
            self.show_fields(self.compare_lines_fields())
        if self.method == LOGNORMAL:
            self.variance_ratio_note = ttk.Label(options, wraplength=360, foreground="#486075", justify="left")
            self.variance_ratio_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            for name in (RATIO_DESIGN, lognormal_tests.INPUT, *lognormal_tests.GROUP_FIELDS):
                self.controls[name][1].trace_add("write", lambda *_: self.show_lognormal_fields())
            self.show_lognormal_fields()
        if self.method == "t-test":
            self.variance_ratio_note = ttk.Label(options, wraplength=360, foreground="#486075", justify="left")
            self.variance_ratio_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls["Design"][1].trace_add("write", lambda *_: self.show_ttest_variance())
            self.controls[ttest_options.INPUT][1].trace_add("write", lambda *_: self.show_ttest_variance())
            self.show_ttest_variance()
        if self.method == VARIANCE_RATIO:
            self.variance_ratio_note = ttk.Label(options, text=tr(VARIANCE_RATIO_NOTE), wraplength=360,
                                                 foreground="#486075", justify="left")
            self.variance_ratio_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == CLUSTER_SILHOUETTE:
            ttk.Label(options, text=tr("silhouette.note"), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method in (SUMMARY_ANOVA, SUMMARY_TTEST):
            self.controls["Input"][1].trace_add("write", lambda *_: self.show_fields(self.summary_anova_fields()))
            self.show_fields(self.summary_anova_fields())
        if self.method == MEAN_PERMUTATION:
            # Captions, choices, the exchangeability and method notes; Exact hides Resamples and Seed.
            mean_permutation_dialog.attach(self, variables, options, positions)
        if self.method == SUMMARY_TTEST:
            ttk.Label(options, text=ui("Two-sided test; first complete group minus second. Groups must be independent. Summary data cannot assess pairing, normality or outliers."),
                      wraplength=350, foreground="#486075").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == SUMMARY_ANOVA:
            self.controls["Method"][1].trace_add("write", lambda *_: self._refresh_summary_posthoc())
            self._refresh_summary_posthoc()
            ttk.Label(options, text=ui(SUMMARY_ANOVA_NOTE), wraplength=ui_theme.px(400),
                      foreground="#486075", justify="left").grid(
                row=positions[options], column=0, columnspan=2, sticky="ew", pady=(8, 4))
            self._bind_scrollable_children(options)
        if self.method == INDEPENDENT_ROC:
            for label in (IROC_AREA, IROC_INFERENCE):
                self.controls[label][1].trace_add("write", lambda *_, label=label: self.show_independent_roc_fields(label))
            ttk.Label(options, text=tr("iroc.hint"), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.show_fields(self.independent_roc_fields())
        if self.method == precision_recall.METHOD:
            for label in (precision_recall.SECOND_SCORE, precision_recall.BOOTSTRAP):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.precision_recall_fields()))
            self.show_fields(self.precision_recall_fields())
        if self.method == icc.METHOD:
            self.icc_rater_order = []
            self.icc_summary = ttk.Label(variables, wraplength=ui_theme.px(400), justify="left")
            self.icc_summary.grid(row=positions[variables], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls[icc.RATERS][1].bind("<<ListboxSelect>>", lambda _: self.show_icc_summary())
            for label in (icc.DEFINITION, icc.UNIT):
                self.controls[label][1].trace_add("write", lambda *_: self.show_icc_summary())
            self.controls[icc.BOOTSTRAP][1].trace_add("write", lambda *_: self.show_fields(self.icc_fields()))
            self.show_icc_summary()
            self.show_fields(self.icc_fields())
            self._bind_scrollable_children(variables)
        if self.method == reshape.METHOD:
            options.destroy()
            self.reshape = reshape_tk.ReshapeEditor(self)
            self._bind_scrollable_children(variables)
        if self.method == POWER_METHOD:
            self.power_allocation_note = None
            for label, note in ((POWER_ALLOCATION, "power.note.design"), (POWER_GROUP_MEANS, "power.note.effect"),
                                (POWER_SHOW_CURVE, "power.note.curve")):
                tab = fields_by_tab.get(label) or options
                caption = ttk.Label(tab, text=tr(note), wraplength=ui_theme.px(400), foreground="#486075",
                                    justify="left")
                caption.grid(row=positions[tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
                positions[tab] += 1
                if label == POWER_ALLOCATION:
                    self.power_allocation_note = caption
            for label in (POWER_GOAL, POWER_DESIGN, POWER_EFFECT_INPUT, POWER_PAIRED_SD_INPUT):
                self.controls[label][1].trace_add("write", lambda *_: self.show_power_fields())
            self.show_power_fields()
        if self.method == EQUIVALENCE:
            self.controls[TOST_DESIGN][1].trace_add("write", lambda *_: self.show_fields(self.equivalence_fields()))
            self.show_fields(self.equivalence_fields())
            ttk.Label(options, text=tr("tost.hint"), wraplength=370, foreground="#486075").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == META_ANALYSIS:
            meta_analysis_dialog.attach(self, variables, options, positions)
        if self.method == PAIRED_PROPORTIONS:
            self.controls[PAIRED_FORMAT][1].trace_add("write", lambda *_: self.show_paired_fields())
            data_tab = fields_by_tab[PAIRED_FORMAT]
            self.paired_notes = {}
            for name in ("observations", "matrix"):
                note = ttk.Label(data_tab, text=tr(f"paired.note.{name}"), wraplength=ui_theme.px(400),
                                 foreground="#486075", justify="left")
                note.grid(row=positions[data_tab], column=0, columnspan=2, sticky="w", pady=(8, 0))
                self.paired_notes[name] = note
            self.show_paired_fields()
            ttk.Label(options, text=tr("paired.hint"), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == TOLERANCE:
            # The two percentages and the difference from a confidence interval of the mean, under the fields.
            ttk.Label(options, text=tr(TOLERANCE_HINT), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == FDR_METHOD:
            ttk.Label(options, text=tr("fdr.note"), wraplength=430, foreground="#486075", justify="left").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
        if self.method == "Interpolate a standard curve":
            for label in (CALIBRATION_DIRECTION, "Curve", CALIBRATION_UNCERTAINTY, "Model"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_calibration_fields())
            self.inverse_note = ttk.Label(options, wraplength=430, foreground="#486075", justify="left")
            self.inverse_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.inverse_note.grid_remove()
            options.bind("<Configure>", lambda event: self.inverse_note.configure(
                wraplength=max(280, event.width - 24)), add="+")
            self._translate_analysis_labels(CALIBRATION_LABELS)
            self.show_calibration_fields()
        if self.method == "Mixed-effects model (REML)":
            for name in ("Within factors", "Between factors", "Measurement columns"):
                self.controls[name][1].bind("<<ListboxSelect>>", lambda _: self.update_mixed_comparisons())
            for name in ("Subject", "Row labels"):
                self.controls[name][1].trace_add("write", lambda *_: self.update_mixed_comparisons())
        if self.method == "Global nonlinear regression":
            model = self.controls["Model"][1]
            self.parameters = GlobalParameters(self.fields, model.get(), saved)
            self.series_parameters = SeriesConstraints(self.fields, model.get(), saved)
            self.fields.add(self.parameters, text=ui("Parameters"))
            self.fields.add(self.series_parameters, text=ui("Series constraints"))

            def set_fit_model(*_):
                self.parameters.set_model(model.get())
                self.series_parameters.set_model(model.get())

            model.trace_add("write", set_fit_model)
        if self.method == SELECT_TRANSFORM:
            filters = RowFilters(options, columns, saved.get(FILTERS, []))
            filters.grid(row=positions[options], column=0, columnspan=2, sticky="ew", pady=(9, 0))
            transformations = CalculatedVariables(fields_by_tab[CALCULATED], saved.get(CALCULATED, []))
            transformations.grid(row=0, column=0, columnspan=2, sticky="ew")
            self.select_editors = {FILTERS: filters, CALCULATED: transformations}
            self.field_rows.update({name: (None, editor) for name, editor in self.select_editors.items()})
        if self.method == PLOT_FUNCTION:
            self.controls[FUNCTION_X_SOURCE][1].trace_add("write", lambda *_: self.show_fields(self.function_fields()))
            model, editor = self.controls[FUNCTION_MODEL][1], self.controls[FUNCTION_CURVES][1]
            model.trace_add("write", lambda *_: editor.set_model(model.get()))
            ttk.Label(options, text=FUNCTION_NOTE, wraplength=430, foreground="#486075").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.fields.insert(1, editor.master)
            self.show_fields(self.function_fields())
        if self.method in WEIGHTING_NOTE_METHODS:
            self.weighting_note = ttk.Label(options, wraplength=430, foreground="#486075", justify="left")
            self.weighting_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls["Weighting"][1].trace_add("write", lambda *_: self.show_weighting_fields())
            self.show_weighting_fields()
        if self.method == "Nonlinear regression":
            confidence_page = fields_by_tab[NL_BAND]
            hint = ttk.Label(confidence_page, text=tr("bands.hint"), wraplength=430, foreground="#486075", justify="left")
            # The Weighting note occupies the row at positions[options] without advancing it.
            hint.grid(row=positions[confidence_page], column=0, columnspan=2, sticky="w", pady=(4, 0))
            positions[confidence_page] += 1
            ttk.Label(confidence_page, text=tr("parameter_ci.hint"), wraplength=430,
                      foreground="#486075", justify="left").grid(row=positions[confidence_page],
                      column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.controls[NL_BAND][1].trace_add("write", lambda *_: self.show_fields(self.band_fields()))
            self.controls["Model"][1].trace_add("write", lambda *_: self.show_fields(self.band_fields()))
            self.show_fields(self.band_fields())
            ttk.Label(options, text=tr("analysis.fit.note.diagnostics"), wraplength=420,
                      foreground="#486075", justify="left").grid(
                row=positions[options], column=0, columnspan=2, sticky="w", pady=(4, 0))
            positions[options] += 1
        if self.method == deming_dialog.METHOD:
            self.deming_sd_note = deming_dialog.add_notes(variables, positions[variables], options, positions[options])
            for label in (deming_dialog.UNCERTAINTY, "Parameter intervals"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_deming_fields())
            self.show_deming_fields()
        if self.method == COX:
            self.configure_cox_fields()
        if self.method == "Multiple regression":
            for label in ("Family", POISSON_DIAGNOSTICS_FIELD, LOGISTIC_DIAGNOSTICS, mlr_weighting.GAUSSIAN_WEIGHTING,
                          mlr_weighting.FUTURE_PRECISION):
                self.controls[label][1].trace_add("write", lambda *_: self.show_regression_fields())
            for label in ("Predictors", "Categorical predictors"):
                self.controls[label][1].bind("<<ListboxSelect>>", lambda _: self.update_regression_profiles(), add="+")
            self.mlr_note = ttk.Label(options, wraplength=ui_theme.px(420), foreground="#486075", justify="left")
            self.mlr_note.grid(row=positions[options], column=0, columnspan=2, sticky="w", pady=(6, 0))
            positions[options] += 1
            self.show_regression_fields()
            self._translate_analysis_labels({**MLR_LABEL_KEYS,
                "Diagnostics and profiles": "analysis.logistic.tab",
                LOGISTIC_DIAGNOSTICS: "analysis.logistic.diagnostics",
                LOGISTIC_CUTOFF: "analysis.logistic.cutoff",
                LOGISTIC_PROFILES: "analysis.logistic.profiles",
                LOGISTIC_CI: "analysis.logistic.confidence",
            })
        if self.method == "Principal component analysis":
            self.controls[PCA_GRAPH][1].trace_add("write", lambda *_: self.show_pca_fields())
            self.controls[PCA_SELECTION][1].trace_add("write", lambda *_: self.show_pca_fields())
            self.controls[pca_overlays.KIND][1].trace_add("write", lambda *_: self.show_pca_fields())
            self.controls[PCR_ENABLE][1].trace_add("write", lambda *_: self.show_pca_fields())
            self.show_pca_fields()
            self._translate_analysis_labels({
                "Graph": "analysis.pca.tab",
                PCA_GRAPH: "analysis.pca.display",
                PCA_HORIZONTAL: "analysis.pca.horizontal",
                PCA_VERTICAL: "analysis.pca.vertical",
                PCA_LABEL: "analysis.pca.label",
                PCA_SHOW_LABELS: "analysis.pca.show",
                PCA_COLOR_GROUPS: "analysis.pca.color_groups",
                **PCA_SELECT_LABELS,
                **PCA_REPORT_LABELS,
                **pca_overlays.LABEL_KEYS,
                **PCA_REGRESSION_LABELS,
            })
        if self.method == XY_ERRORS:
            for label in ("X error distance", "X lower error", "X upper error", "X error values",
                          "Y lower error", "Y upper error", "Y error values"):
                self.controls[label][1].trace_add("write", lambda *_: self.show_fields(self.xy_error_fields()))
            self.show_fields(self.xy_error_fields())
        if not positions[variables]:
            self.fields.select(options)

    def update_survival_groups(self, preferred=()):
        """Offer the group names produced by the chosen time, event and grouping columns."""
        def picked(label):
            box = self.controls[label][1]
            return [box.get(i) for i in box.curselection()]

        options = {"Time": self.controls["Time"][1].get(), "Event columns": picked("Event columns"),
                   "Grouping variables": picked("Grouping variables")}
        options.update({name: self.controls[name][1].get() for name in STATUS_DEFAULTS})
        try:
            levels = survival_levels(self.data, options)
        except ValueError:
            self.show_survival_fields()
            return
        self.controls["Trend group order"][1].set_levels(levels, preferred)
        numerator = self.controls["Hazard ratio numerator"][1]
        self.field_rows["Hazard ratio numerator"][1].configure(values=levels)
        control = self.controls[PAIRWISE_CONTROL][1].get()
        choices = ["", *levels]
        if control and control not in choices:
            choices.append(control)
        self.field_rows[PAIRWISE_CONTROL][1].configure(values=choices)
        self.controls[PAIRWISE_PAIRS][1].set_levels(levels)
        if numerator.get() not in levels:
            numerator.set(levels[0] if levels else "")
        self.show_survival_fields()

    def dunn_visibility(self):
        if self.method not in DUNN_METHODS:
            return {}
        mode = self.controls[DUNN][1].get()
        return {DUNN_CONTROL: mode == "Versus control", DUNN_PAIRS: mode == DUNN_PAIRS,
                DUNN_ADJUSTMENT: mode != "None", DUNN_ALPHA: mode != "None"}

    def show_dunn_fields(self):
        self.show_fields(self.dunn_visibility())
        self.set_comparison_groups(DUNN_CONTROL, DUNN_PAIRS)

    def set_comparison_groups(self, control, pairs):
        response, group = (self.controls[field][1].get() for field in ("Response", "Group"))
        choices = []
        if response != group and response in self.data and group in self.data:
            selected = self.data.dropna(subset=[response, group])[group].unique()
            labels = pd.Index([str(label) for label in selected])
            choices = labels[~labels.duplicated(keep=False)].tolist()
        self.field_rows[control][1].configure(values=choices)
        self.controls[pairs][1].set_levels(choices)

    def survival_pairwise_fields(self):
        if self.method != "Kaplan–Meier survival":
            return {}
        return pairwise_fields(self.controls[PAIRWISE_CORRECTION][1].get(),
                               self.controls[PAIRWISE_SCOPE][1].get(), self.controls[PAIRWISE_ADJUSTED][1].get())

    def show_survival_fields(self):
        self.show_fields(self.survival_pairwise_fields())
        for check, label in (("Log-rank trend", "Trend group order"), ("Hazard ratio", "Hazard ratio numerator")):
            for widget in self.field_rows[label]:
                if self.controls[check][1].get():
                    widget.grid()
                else:
                    widget.grid_remove()

    def choose_equation(self, choices, model):
        dialog = EquationDialog(self, choices, model.get())
        self.grab_set()
        if dialog.result is not None:
            model.set(dialog.result)

    def refresh_series_tab(self, _=None):
        editor = getattr(self, "global_series", None)
        if editor is not None:
            # This page is not the global-nonlinear series editor. curve_series_labels does not apply.
            if self.fields.select() == str(editor.master):
                editor.refresh_labels()
            return
        if self.series_parameters is None or self.fields.select() != str(self.series_parameters):
            return
        names = ("Input format", "X", "Y", "Series", "Merge numbered replicates", "Model")
        options = {name: self.controls[name][1].get() for name in names}
        box = self.controls["Y columns"][1]
        options["Y columns"] = [box.get(i) for i in box.curselection()]
        self.series_parameters.set_labels(curve_series_labels(self.data, options))

    def show_input_fields(self):
        choices = INPUT_FIELDS[self.method]
        selected = choices[self.controls["Input format"][1].get()]
        for label in set.union(*choices.values()):
            for widget in self.field_rows[label]:
                if label in selected:
                    widget.grid()
                else:
                    widget.grid_remove()

        if self.method == "Mixed-effects model (REML)":
            self.update_mixed_comparisons()

    def update_mixed_comparisons(self):
        def selected(label):
            widget = self.controls[label][1]
            return [widget.get(i) for i in widget.curselection()]

        mode = self.controls["Input format"][1].get()
        if mode == "Long table":
            labels = selected("Within factors") + selected("Between factors")
        elif mode == "Wide repeated measures":
            between = selected("Between factors")
            reserved = [*between, *selected("Measurement columns"), self.controls["Subject"][1].get()]
            condition = "Condition"
            while condition in reserved:
                condition += " (within)"
            labels = [condition, *between]
        else:
            row = self.controls["Row labels"][1].get() or "Row"
            labels = [row, "Column series" if row != "Column series" else "Column series (within)"]
        labels = list(dict.fromkeys(labels))
        choice = self.controls["Comparison factor"][1]
        self.field_rows["Comparison factor"][1].configure(values=["", *labels])
        if choice.get() and choice.get() not in labels:
            choice.set("")
        box = self.controls["Condition on factors"][1]
        prior = selected("Condition on factors")
        box.delete(0, "end")
        for index, label in enumerate(labels):
            box.insert("end", label)
            if label in prior:
                box.selection_set(index)

    def buttonbox(self):
        modern = ui_theme.is_modern()
        row = ttk.Frame(self, padding=(14, 7, 14, 9) if modern else (12, 0, 12, 9),
                        style="AnalysisFooter.TFrame" if modern else "")
        ttk.Button(row, text=ui("Run Analysis"), style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(row, text=ui("Cancel"), command=self.cancel).pack(side="right")
        row.pack(fill="x")
        self.bind("<Escape>", self.cancel)

    def _make_scrollable_tab(self, outer):
        scroll = ttk.Scrollbar(outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        background = ttk.Style(self).lookup("TFrame", "background") or "#f4f6f8"
        canvas = tk.Canvas(outer, highlightthickness=0, yscrollcommand=scroll.set, background=background)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.configure(command=canvas.yview)
        content = ttk.Frame(canvas, padding=10)
        content.columnconfigure(1, weight=1)
        window = canvas.create_window(0, 0, window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        def wheel(direction):
            canvas.yview_scroll(direction, "units")
            return "break"

        def reveal(widget):
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            total = max(1, content.winfo_height())
            if widget.winfo_height() <= 0 or total <= canvas.winfo_height():
                return
            top = widget.winfo_rooty() - content.winfo_rooty()
            bottom = top + widget.winfo_height()
            first, last = canvas.yview()
            if top < first * total or bottom > last * total:
                canvas.yview_moveto(max(0.0, (top - 8) / total))

        outer._reveal = reveal
        content._scroll_canvas = canvas
        content._scroll_wheel = wheel
        content._scroll_reveal = reveal
        return content

    @staticmethod
    def _bind_scrollable_children(content):
        canvas = getattr(content, "_scroll_canvas", None)
        wheel = getattr(content, "_scroll_wheel", None)
        reveal = getattr(content, "_scroll_reveal", None)
        if canvas is None or wheel is None or reveal is None:
            return
        for widget in (canvas, content, *content.winfo_children()):
            widget.bind("<MouseWheel>", lambda event, fn=wheel: fn(-1 if event.delta > 0 else 1), add="+")
            widget.bind("<Button-4>", lambda _e, fn=wheel: fn(-1), add="+")
            widget.bind("<Button-5>", lambda _e, fn=wheel: fn(1), add="+")
            if not isinstance(widget, ttk.Label):
                widget.bind("<FocusIn>", lambda _e, w=widget, fn=reveal: fn(w), add="+")

    @staticmethod
    def _bind_scrollable_widgets(content, widgets):
        """Wheel scrolling and focus reveal for widgets created after the page was built."""
        wheel = getattr(content, "_scroll_wheel", None)
        reveal = getattr(content, "_scroll_reveal", None)
        if wheel is None or reveal is None:
            return
        for widget in widgets:
            widget.bind("<MouseWheel>", lambda event, fn=wheel: fn(-1 if event.delta > 0 else 1), add="+")
            widget.bind("<Button-4>", lambda _e, fn=wheel: fn(-1), add="+")
            widget.bind("<Button-5>", lambda _e, fn=wheel: fn(1), add="+")
            if not isinstance(widget, ttk.Label):
                widget.bind("<FocusIn>", lambda _e, w=widget, fn=reveal: fn(w), add="+")

    def focus_field(self, name, pair=None):
        """Show the tab that holds a field and move the keyboard focus to it."""
        if self.join is not None:
            widget = self.join.focus_target(name, self.initial_pair if pair is None else pair)
        else:
            _, widget = self.field_rows.get(name, (None, None))
        if widget is None:
            return
        page = widget.master
        while page is not None and page.master is not self.fields:
            page = page.master
        if page is not None:
            self.fields.select(page)
        target = widget.focus_target() if hasattr(widget, "focus_target") else (
            widget.winfo_children()[0] if isinstance(widget, ttk.Frame) and widget.winfo_children() else widget)
        # grid() stays unmapped until idle layout, and focus_set is a no-op
        # on an unmapped widget or when this dialog does not own the display.
        if not target.winfo_viewable() and self.winfo_viewable():
            self.update_idletasks()
            if not target.winfo_viewable():
                self.update()
        if page is not None and hasattr(page, "_reveal"):
            page._reveal(target)
        if target.winfo_viewable():
            target.focus_force()
        else:
            target.focus_set()
        # simpledialog.Dialog.ok() refocuses initial_focus after a failed validate(): point it at the
        # field so pressing Run Analysis leaves the keyboard on the control that needs fixing.
        self.initial_focus = target
        return target

    def processing_visibility(self):
        def value(name):
            return self.controls[name][1].get()

        if self.method == "Transform concentrations (X)":
            return {"Zero replacement (original units)": value("Replace zero X"),
                    "Unit factor": value("Change units") != "No change"}
        if self.method == "Remove baseline and column math":
            mode = value("Baseline")
            reference_rows = mode in BASELINES[3:5]
            column = mode in (BASELINES[0], BASELINES[5])
            # Replicate modes read a whole baseline dataset; Independent columns keeps the 0.48 single column.
            independent = value("Replicate handling") in ("", "Independent columns")
            return {"Baseline column": column and independent, "Baseline subcolumns": column and not independent,
                    "Rows for baseline (K)": reference_rows, "Drop baseline rows": reference_rows}
        if self.method == "Prune rows":
            average = value("Method") == PRUNE_MODES[1]
            return {"X minimum (blank = no limit)": not average, "X maximum (blank = no limit)": not average,
                    "Rows per group (K)": average, "Average only rows above an X threshold": average,
                    "X threshold": average and value("Average only rows above an X threshold")}
        if self.method == "Fraction of total":
            single = value("Divide by") in DENOMINATORS[:3]
            return {"Confidence interval": single, "Confidence level (%)": single and value("Confidence interval") != "None"}
        return {}

    def show_processing_fields(self):
        self.show_fields(self.processing_visibility())

    def kmeans_visibility(self):
        if self.method == kmeans_stability.METHOD:
            return kmeans_stability.visibility(self.controls[kmeans_stability.ALGORITHM][1].get())
        if self.method not in kmeans_options.METHODS:
            return {}
        algorithm = self.controls[kmeans_options.ALGORITHM][1].get()
        scale = self.controls[kmeans_options.SCALE][1].get()
        options = {**{field: key == algorithm for key, field in kmeans_options.ITERATION_FIELDS.items()},
                   kmeans_options.INITIALIZATION: algorithm == kmeans_options.HARTIGAN,
                   kmeans_reports.SCALED: scale != kmeans_options.UNSCALED}
        if self.method == kmeans_options.CLUSTERING:
            return {**options, kmeans_options.INITIAL_ROWS: algorithm in kmeans_options.ITERATION_FIELDS}
        from analisi.cluster_consensus import KL_SCALING

        criterion = self.controls["Criterion"][1].get()
        gap = criterion in kmeans_reports.GAP_CRITERIA or self.controls[kmeans_options.GAP_PLOT][1].get()
        return {**options, KL_SCALING: criterion == "Consensus (17 indices)",
                kmeans_reports.GAP: gap}

    def hierarchical_visibility(self):
        def value(name):
            return self.controls[name][1].get()

        if self.method == HIERARCHY_GRAPH:
            graph = value("Graph output")
            return {
                **dict.fromkeys(HIERARCHICAL_TABS["Graph"][2:], graph in ("Dendrogram", "Heat map")),
                TREE_AXIS: graph != "Heat map", "Dendrogram orientation": graph == "Dendrogram",
            }
        if self.method != "Hierarchical clustering":
            return {}
        direction = value("Direction")
        rows, columns = direction != "Columns", direction != "Rows"
        row_cut, column_cut = value("Row cut"), value("Column cut")
        graph = value("Graph output")
        tree_graph = graph in ("Dendrogram", "Heat map")
        return {
            "Row cut": rows, "Clusters": rows and row_cut == "Count",
            "Row cut height": rows and row_cut == "Cut height",
            "Column cut": columns, "Column clusters": columns and column_cut == "Count",
            "Column cut height": columns and column_cut == "Cut height",
            "Dendrogram orientation": graph == "Dendrogram",
            "Show cut line": tree_graph and (
                (rows and row_cut == "Cut height") or (columns and column_cut == "Cut height")),
            "Elbow data": graph != "Elbow plot",
            SILHOUETTE_DATA: graph != SILHOUETTE_PLOT,
            GAP_DATA: graph != GAP_PLOT,
            **dict.fromkeys(GAP_OPTIONS, graph == GAP_PLOT or value(GAP_DATA)),
            **dict.fromkeys(("Branch appearance", "Branch width", "Branch style", "Branch opacity (%)",
                             "Label type", "First label", "Label interval (0 = automatic)", "Label angle"), tree_graph),
            "Matrix format": value("Distance matrix") or value("Cophenetic distances"),
        }

    def show_hierarchical_fields(self):
        self.show_fields(self.hierarchical_visibility())

    def overlay_visibility(self):
        if self.method != "Scatter / confidence ellipse":
            return {}
        choices = ("Ellipse", "Ellipse grouping", "Fill", "Border", "Center marker")
        return ellipse_visibility({name: self.controls[name][1].get() for name in choices})

    def show_ellipse_fields(self):
        self.show_fields(self.overlay_visibility())
        tab = self.field_rows["Fill"][0].master
        enabled = self.controls["Ellipse"][1].get() != "None"
        self.fields.tab(tab, state="normal" if enabled else "disabled")
        options = self.ellipse_style_options()
        group = ellipse_grouping_column(options)
        visible = enabled and group in self.data and ELLIPSE_BY_GROUP in (options["Fill"], options["Border"])
        self.show_fields({ELLIPSE_GROUP_STYLES: visible})

    def ellipse_style_options(self):
        fields = ("Group", "Ellipse grouping", "Ellipse group", "Fill", "Border")
        return {field: self.controls[field][1].get() for field in fields}

    def edit_ellipse_group_styles(self):
        from analisi.ellipse_style_dialog import EllipseStyleDialog

        options = self.ellipse_style_options()
        column = ellipse_grouping_column(options)
        if column not in self.data:
            return
        values = self.data[column].dropna().unique()
        if not len(values):
            messagebox.showerror(ui(ELLIPSE_GROUP_STYLES), ui("The grouping column has no observed values."), parent=self)
            return
        try:
            dialog = EllipseStyleDialog(self, values, options, column, self.ellipse_group_styles)
        except FieldError as error:
            messagebox.showerror(ui(ELLIPSE_GROUP_STYLES), ui(str(error)), parent=self)
            return
        self.grab_set()
        if dialog.result is not None:
            self.ellipse_group_styles = dialog.result

    def category_visibility(self):
        if self.method not in CATEGORY_GRAPHS:
            return {}
        style = self.controls["Graph style"][1].get()
        overlay = self.controls["Overlay observations"][1].get()
        grouped = self.method == GROUPED_GRAPH
        summaries = grouped and self.controls["Input"][1].get() == SUMMARIES
        stacked = grouped and self.controls["Placement of groups"][1].get() in STACKED_PLACEMENTS
        # Stacks and summaries have no observations to overlay or to summarize again.
        raw = not (summaries or stacked)
        intervals = raw and style not in {RANGE, PAIRED}
        visibility = {"Interval": intervals,
                      "Confidence level (%)": intervals and self.controls["Interval"][1].get() == "Confidence interval",
                      "Overlay observations": raw and style not in {POINTS, PAIRED},
                      "Point placement": raw and style != PAIRED and (style == POINTS or overlay)}
        if grouped:
            errors = summaries and not stacked
            visibility.update({"Center": not summaries, "Summary error": errors,
                               "SEM source": errors and self.controls["Summary error"][1].get() == "SEM"})
        return visibility

    def category_styles(self):
        """Graph styles that the selected input and placement can draw."""
        if self.method != GROUPED_GRAPH:
            return None
        if self.controls["Placement of groups"][1].get() in STACKED_PLACEMENTS:
            return (BARS,)
        return SUMMARY_STYLES if self.controls["Input"][1].get() == SUMMARIES else GROUPED_STYLES

    def show_category_fields(self):
        styles = self.category_styles()
        if styles is not None:
            self.choice_bindings["Graph style"].set_values(styles)
            style = self.controls["Graph style"][1]
            if style.get() not in styles:
                style.set(BARS)  # Writing the style shows the fields again.
                return
        self.show_fields(self.category_visibility())

    def nested_visibility(self):
        return {NESTED_CONFIRM: not is_nested_worksheet(self.data)} if self.method in NESTED_METHODS else {}

    def contingency_visibility(self):
        if self.method != CONTINGENCY:
            return {}
        counts = self.controls["Input format"][1].get() == COUNT_MATRIX
        test = self.controls["Test"][1].get()
        return {"Rows": not counts, "Columns": not counts, "Count columns": counts, "Row titles": counts,
                "Blank cells": counts, "Fisher alternative": test in {CONTINGENCY_AUTO, FISHER},
                "Monte Carlo samples": test == MONTE_CARLO, "Seed": test == MONTE_CARLO,
                "Diagnostic interval": bool(self.controls["Diagnostic measures"][1].get())}

    def show_contingency_fields(self):
        self.show_fields(self.contingency_visibility())

    def row_test_visibility(self):
        if self.method != ROW_TESTS:
            return {}
        return row_test_visibility(*(self.controls[name][1].get() for name in ("Input format", "Test", "Correction")))

    def show_row_test_fields(self):
        raw = self.controls["Input format"][1].get() == ROW_TEST_RAW
        choices = ROW_TEST_CHOICES if raw else ROW_TEST_CHOICES[:2]
        self.choice_bindings["Test"].set_values(choices)
        selected = self.controls["Test"][1]
        if selected.get() not in choices:
            selected.set(choices[0])
        self.show_fields(self.row_test_visibility())

    def heat_map_visibility(self):
        if self.method != HEAT_MAP:
            return {}
        if HEAT_MAP_MAPPING not in self.controls:
            return {}
        return heat_map_visibility(self.controls["Input format"][1].get(), self.controls["Color scale"][1].get(),
                                   self.controls[HEAT_MAP_MAPPING][1].get(), self.controls[HEAT_MAP_INTERVAL][1].get(),
                                   self.controls[HEAT_MAP_SHOW_LEGEND][1].get(),
                                   self.controls[HEAT_MAP_NUMBER_FORMAT][1].get(),
                                   self.controls["Show cell values"][1].get(),
                                   self.controls[CELL_LABEL_NUMBER_FORMAT][1].get(),
                                   self.controls[CELL_LABEL_COLOR_MODE][1].get(),
                                   self.controls[ROW_GAP_MODE][1].get(),
                                   self.controls[COLUMN_GAP_MODE][1].get(),
                                   self.controls[SHOW_ROW_LABELS][1].get(),
                                   self.controls[ROW_LABEL_FREQUENCY][1].get(),
                                   self.controls[SHOW_COLUMN_LABELS][1].get(),
                                   self.controls[COLUMN_LABEL_FREQUENCY][1].get())

    def heat_map_levels(self):
        """Observed category texts for the current X, Y and Values choice; raises FieldError when incomplete."""
        options = {name: self.controls[name][1].get() for name in ("X categories", "Y categories", "Values")}
        return category_levels(self.data, options)

    def correlation_visibility(self):
        if self.method != CORRELATION_MATRIX:
            return {}
        return {"Spearman p values": self.controls["Method"][1].get() == "Spearman"}

    def correlation_details_visibility(self):
        if self.method == "Correlation" and "Detailed results" in self.controls:
            detailed = bool(self.controls["Detailed results"][1].get())
            return {"Alternative": detailed, "Confidence level (%)": detailed, "Spearman p values": detailed,
                    SPEARMAN_BUDGET: detailed and self.controls["Method"][1].get() == "Spearman"
                    and self.controls["Spearman p values"][1].get() != "Approximate"}
        if self.method == CORRELATE_CONTROL and "Method" in self.controls:
            spearman = self.controls["Method"][1].get() == "Spearman"
            return {"Spearman p values": spearman, SPEARMAN_BUDGET: spearman
                    and self.controls["Spearman p values"][1].get() != "Approximate"}
        return {}

    def show_correlation_details(self):
        self.show_fields(self.correlation_details_visibility())
        if self.method != "Correlation" or "Spearman p values" not in self.field_rows:
            return
        detailed = bool(self.controls["Detailed results"][1].get())
        spearman = self.controls["Method"][1].get() == "Spearman"
        if detailed:
            self.field_rows["Spearman p values"][1].configure(state="readonly" if spearman else "disabled")

    def rmcorr_fields(self):
        """Level, replicates and seed are active only with the subject bootstrap."""
        if self.method != RMCORR or RMCORR_INTERVAL not in self.controls:
            return {}
        return rmcorr_visibility(self.controls[RMCORR_INTERVAL][1].get())

    def show_rmcorr_fields(self):
        # The entries stay gridded; disabled means the chosen interval does not use them.
        for label, active in self.rmcorr_fields().items():
            self.field_rows[label][1].configure(state="normal" if active else "disabled")

    def frequency_visibility(self):
        if self.method != FREQUENCY:
            return {}
        return frequency_visibility(self.controls["Distribution"][1].get(), self.controls["Units"][1].get())

    def show_frequency_fields(self):
        self.show_fields(self.frequency_visibility())

    def auc_visibility(self):
        if self.method != "Area under curve":
            return {}
        peaks = self.controls[AUC_PEAKS][1].get() != "Off"
        return {AUC_HEIGHT: peaks, AUC_WIDTH: peaks}

    def refresh_trend_levels(self, preferred=None):
        if self.method != "One-way ANOVA" or TREND_ORDER not in self.controls:
            return
        response, group = self.controls["Response"][1].get(), self.controls["Group"][1].get()
        if response in self.data and group in self.data and response != group:
            levels = group_levels(self.data, response, group)
        else:
            levels = []
        self.controls[TREND_ORDER][1].set_levels(levels, preferred)

    def one_way_fields(self):
        if self.method != "One-way ANOVA":
            return {}
        posthoc = self.controls["Post-hoc"][1].get()
        visible = one_way_visibility(posthoc, self.controls[unequal_anova.FAMILY][1].get())
        visible[TREND_ORDER] = bool(self.controls[TREND][1].get())
        ordinary = self.controls["Method"][1].get() == "Ordinary"
        requested = bool(self.controls[VARIANCE_BROWN][1].get()) or bool(self.controls[VARIANCE_BARTLETT][1].get())
        visible[VARIANCE_BROWN] = ordinary
        visible[VARIANCE_BARTLETT] = ordinary
        visible[VARIANCE_ALPHA] = ordinary and requested
        lognormal = self.controls[lognormal_anova.DISTRIBUTION][1].get() == lognormal_anova.LOGNORMAL
        visible[lognormal_anova.RATIO_DIRECTION] = lognormal and posthoc not in (None, "", "None")
        # Tukey and Games–Howell intervals are fixed at 95% on the Normal path. Lognormal uses the chosen level.
        if lognormal and posthoc in ("Tukey", "Games–Howell"):
            visible[unequal_anova.LEVEL] = True
        return visible

    def show_one_way_fields(self):
        visible = self.one_way_fields()
        self.show_fields(visible)
        self.set_comparison_groups(unequal_anova.CONTROL, unequal_anova.PAIRS)
        if VARIANCE_BROWN not in self.field_rows:
            return
        ordinary = bool(visible.get(VARIANCE_BROWN))
        tab = self.field_rows[VARIANCE_BROWN][0].master
        if not ordinary and str(self.fields.select()) == str(tab):
            self.fields.select(0)
        self.fields.tab(tab, state="normal" if ordinary else "disabled")
        if ordinary:
            self.variance_note.grid()
        else:
            self.variance_note.grid_remove()
        note = getattr(self, "lognormal_note", None)
        if note is not None:
            lognormal = self.controls[lognormal_anova.DISTRIBUTION][1].get() == lognormal_anova.LOGNORMAL
            if lognormal:
                note.grid()
            else:
                note.grid_remove()

    def _keep_hidden_variance(self, options):
        """Remember a hidden choice. An invalid hidden alpha is omitted instead of failing the run."""
        if VARIANCE_BROWN not in self.controls:
            return
        visible = self.one_way_fields()
        if not visible.get(VARIANCE_BROWN, True):
            options[VARIANCE_BROWN] = bool(self.controls[VARIANCE_BROWN][1].get())
            options[VARIANCE_BARTLETT] = bool(self.controls[VARIANCE_BARTLETT][1].get())
        if VARIANCE_ALPHA not in options:
            raw = self.controls[VARIANCE_ALPHA][1].get()
            try:
                alpha = float(decimal_comma(raw))
            except (TypeError, ValueError):
                alpha = None
            if alpha is not None and np.isfinite(alpha) and 0 < alpha < 1:
                options[VARIANCE_ALPHA] = alpha

    def show_sphericity_note(self):
        note = self.sphericity_note
        if note is None or not note.winfo_exists() or rm_sphericity.FIELD not in self.controls:
            return
        key = {rm_sphericity.NONE: "rm.sphericity.note.none",
               rm_sphericity.LEGACY: "rm.sphericity.note.legacy",
               rm_sphericity.HF: "rm.sphericity.note.hf",
               rm_sphericity.LOWER: "rm.sphericity.note.lower"}.get(
            self.controls[rm_sphericity.FIELD][1].get(), "rm.sphericity.note.gg")
        note.configure(text=tr(key))

    def anova_fields(self):
        if self.method != "Multifactor ANOVA":
            return {}
        return anova_visibility(self.controls[ANOVA_EFFECTS][1].get())

    def anova_term_fields(self):
        """Interaction order belongs to Full hierarchy; Selected terms leaves it out of the recipe."""
        if self.method != "Multifactor ANOVA":
            return {}
        return {"Interaction order": self.controls[ANOVA_TERM_SELECTION][1].get() == ANOVA_FULL_TERMS}

    def anova_diagnostic_fields(self):
        """Diagnostic alpha follows the assumption tests. The Q–Q line follows that graph."""
        if self.method != "Multifactor ANOVA":
            return {}
        return anova_diagnostic_visibility(
            bool(self.controls[ANOVA_ASSUMPTIONS][1].get()),
            self.controls[ANOVA_DIAG_GRAPH][1].get())

    def show_anova_fields(self):
        if self.method != "Multifactor ANOVA":
            return
        graph = self.controls[ANOVA_DIAG_GRAPH][1].get()
        # Leaving Normal Q–Q drops the saved line. Coming back uses the default, which is on.
        if graph == ANOVA_GRAPH_QQ and getattr(self, "_anova_graph", graph) != ANOVA_GRAPH_QQ:
            self.controls[ANOVA_QQ_LINE][1].set(True)
        self._anova_graph = graph
        self.show_fields({**self.anova_fields(), **self.anova_term_fields(), **self.anova_diagnostic_fields()})
        # The checkboxes follow the mode; an untouched picker starts Selected terms from the Full hierarchy.
        self.controls[ANOVA_MODEL_TERMS][1].sync()

    def anova_listed(self):
        """The names ticked in Factors, in the order of the worksheet list."""
        box = self.controls["Factors"][1]
        return [box.get(index) for index in box.curselection()]

    def anova_factors(self):
        """The names ticked in Factors, in the order chosen on the Model page: the order of Factors in the recipe."""
        names = self.anova_listed()
        return self.anova_order.arrange(names) if self.anova_order is not None else names

    def anova_contrast_context(self):
        factors = self.anova_factors()
        picker = self.controls[ANOVA_MODEL_TERMS][1]
        model = anova_active_factors(factors, picker.terms()) if picker.selected() else factors
        levels, check = contrast_context(self.data, self.controls["Response"][1].get(), model)
        return model, levels, check

    def agreement_visibility(self):
        if self.method != "Bland–Altman":
            return {}
        return bland_altman_visibility(self.controls[BLAND_ALTMAN_INTERVALS][1].get())

    def configure_cox_fields(self):
        """Profiles and Schoenfeld terms follow the chosen predictors; the term picker lists the fit's terms."""
        heading, entry = self.field_rows[COX_TERM]
        layout = entry.grid_info()
        entry.destroy()
        terms = ttk.Combobox(heading.master, textvariable=self.controls[COX_TERM][1], state="readonly", width=27)
        terms.grid(**{key: layout[key] for key in ("row", "column", "sticky", "pady")})
        self.field_rows[COX_TERM] = heading, terms
        for label in ("Predictors", "Categorical predictors"):
            self.controls[label][1].bind("<<ListboxSelect>>", lambda _: self.update_cox_terms(), add="+")
        for label in (COX_PREDICT, COX_GRAPH, COX_DIAGNOSTICS, COX_SCHOENFELD, COX_SCALED, COX_SNELL):
            self.controls[label][1].trace_add("write", lambda *_: self.update_cox_terms())
        self.update_cox_terms()
        # Exact (conditional) ties fit the coefficient and model sheets only. The notes name that on the tabs of the
        # outputs it refuses; a profile list or a turned-on output stays in the dialog and is refused on Run.
        self.cox_notes = []
        for label, key in ((COX_TIES, "cox.exact.hint"), (COX_PREDICT, "cox.exact.unavailable"),
                           ("Cox diagnostics", "cox.exact.unavailable")):
            page = self.field_rows[label][0].master
            note = ttk.Label(page, text=tr(key), wraplength=ui_theme.px(420), foreground="#9a3412", justify="left")
            note.grid(row=99, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.cox_notes.append(note)
        self.controls[COX_TIES][1].trace_add("write", lambda *_: self.update_cox_notes())
        self.update_cox_notes()

    def update_cox_notes(self):
        exact = cox_is_exact({COX_TIES: self.controls[COX_TIES][1].get()})
        for note in self.cox_notes:
            if exact:
                note.grid()
            else:
                note.grid_remove()

    def update_cox_terms(self):
        def picked(label):
            box = self.controls[label][1]
            return [box.get(i) for i in box.curselection()]

        predictors, categories = picked("Predictors"), picked("Categorical predictors")
        self.controls[COX_PROFILES][1].set_predictors(predictors, categories)
        terms = model_terms(self.data, predictors, categories)
        self.field_rows[COX_TERM][1].configure(values=terms)
        term = self.controls[COX_TERM][1]
        if term.get() not in terms:
            term.set(terms[0] if terms else "")
        self.show_fields(self.cox_fields())

    def cox_fields(self):
        if self.method != COX:
            return {}
        return cox_visibility(*(self.controls[name][1].get() for name in (
            COX_PREDICT, COX_GRAPH, COX_DIAGNOSTICS, COX_SCHOENFELD, COX_SCALED, COX_SNELL)))

    def regression_visibility(self):
        if self.method != "Multiple regression":
            return {}
        family = self.controls["Family"][1].get()
        diagnostics = self.controls[POISSON_DIAGNOSTICS_FIELD][1].get()
        logistic_on = LOGISTIC_DIAGNOSTICS in self.controls and bool(self.controls[LOGISTIC_DIAGNOSTICS][1].get())
        profiles = LOGISTIC_PROFILES in self.controls and bool(self.controls[LOGISTIC_PROFILES][1].profiles)
        gaussian = (self.controls[mlr_weighting.GAUSSIAN_WEIGHTING][1].get()
                    if mlr_weighting.GAUSSIAN_WEIGHTING in self.controls else mlr_weighting.UNWEIGHTED)
        linear_profiles = LINEAR_PROFILES in self.controls and bool(self.controls[LINEAR_PROFILES][1].profiles)
        return regression_visibility(family, diagnostics, logistic_diagnostics_on=logistic_on,
                                     logistic_profiles=profiles, gaussian_mode=gaussian,
                                     linear_profiles=linear_profiles)

    def _picked(self, label):
        box = self.controls[label][1]
        return [box.get(i) for i in box.curselection()]

    def update_linear_profiles(self):
        if LINEAR_PROFILES not in self.controls:
            return
        self.controls[LINEAR_PROFILES][1].set_predictors(self._picked("Predictors"),
                                                         self._picked("Categorical predictors"))

    def update_logistic_profiles(self):
        if LOGISTIC_PROFILES not in self.controls:
            return
        self.controls[LOGISTIC_PROFILES][1].set_predictors(self._picked("Predictors"),
                                                           self._picked("Categorical predictors"))

    def update_regression_profiles(self):
        self.update_linear_profiles()
        self.update_logistic_profiles()

    def _set_method_tab(self, label, enabled):
        if label not in self.field_rows:
            return
        tab = self.field_rows[label][0].master
        if not enabled and str(self.fields.select()) == str(tab):
            self.fields.select(0)
        self.fields.tab(tab, state="normal" if enabled else "disabled")

    def _translate_analysis_labels(self, mapping):
        for label, key in mapping.items():
            row = self.field_rows.get(label)
            if row is not None and row[0] is not None:
                row[0].configure(text=tr(key))
        for index in range(self.fields.index("end")):
            caption = self.fields.tab(index, "text")
            key = next((key for label, key in mapping.items() if caption in (label, ui(label))), None)
            if key:
                self.fields.tab(index, text=tr(key))

    def show_regression_fields(self):
        visible = self.regression_visibility()
        self.show_fields(visible)
        self.update_regression_profiles()
        if LINEAR_PROFILES in self.controls:
            asked = bool(visible.get(mlr_weighting.FUTURE_PRECISION)) and bool(
                self.controls[mlr_weighting.FUTURE_PRECISION][1].get())
            self.controls[LINEAR_PROFILES][1].set_weight_visible(asked)
        if getattr(self, "mlr_note", None) is not None:
            choice = self.controls[mlr_weighting.GAUSSIAN_WEIGHTING][1].get()
            self.mlr_note.configure(text=tr(MLR_NOTE_KEYS.get(choice, MLR_NOTE_KEYS[mlr_weighting.UNWEIGHTED]))
                                    if visible.get(mlr_weighting.GAUSSIAN_WEIGHTING) else "")
        self._set_method_tab(LINEAR_DIAGNOSTICS, bool(visible.get(LINEAR_DIAGNOSTICS)))
        self._set_method_tab(LOGISTIC_DIAGNOSTICS, bool(visible.get(LOGISTIC_DIAGNOSTICS)))

    def _translate_analysis_labels(self, mapping):
        for label, key in mapping.items():
            row = self.field_rows.get(label)
            if row is not None and row[0] is not None:
                row[0].configure(text=tr(key))
        for index in range(self.fields.index("end")):
            caption = self.fields.tab(index, "text")
            key = next((key for label, key in mapping.items() if caption in (label, ui(label))), None)
            if key:
                self.fields.tab(index, text=tr(key))

    def selection_visibility(self):
        if self.method != "Principal component analysis" or PCA_SELECTION not in self.controls:
            return {}
        return pca_visible_fields(self.controls[PCA_SELECTION][1].get())

    def _inactive_controls(self):
        """Scree and proportion keep the PC selectors visible, but do not use them.

        Selection fields that do not belong to the chosen criterion stay in the recipe when they
        still parse, and an invalid hidden value is omitted instead of blocking the analysis.
        """
        if self.method == MEAN_PERMUTATION:
            # Exact ignores Resamples and Seed: values that parse stay in the recipe, others are omitted.
            return {name for name, shown in mean_permutation_dialog.fields(self).items() if not shown}
        if self.method == ROBUST_CURVE:
            # A usable hidden residual scale stays in the recipe; an invalid one is omitted instead of blocking.
            return {name for name, shown in self.robust_fields().items() if not shown}
        if self.method == RMCORR:
            # Without the bootstrap its level, replicates and seed are kept when they parse and never block.
            return {name for name, active in self.rmcorr_fields().items() if not active}
        if self.method == NB2:
            # The same for a hidden Dispersion alpha under Estimated ML.
            return {name for name, shown in self.nb2_fields().items() if not shown}
        if self.method != "Principal component analysis" or PCA_GRAPH not in self.controls:
            return set()
        inactive = {name for name, shown in self.selection_visibility().items() if not shown}
        view = self.controls[PCA_GRAPH][1].get()
        if view in PCA_ONE_DIMENSION:
            inactive.update({PCA_HORIZONTAL, PCA_VERTICAL, PCA_LABEL, PCA_SHOW_LABELS})
        if view not in PCA_POINT_VIEWS:
            inactive.add(PCA_COLOR_GROUPS)
        overlay_kind = self.controls[pca_overlays.KIND][1].get()
        inactive.update(name for name, enabled in pca_overlays.active_fields(view in PCA_POINT_VIEWS, overlay_kind).items()
                        if not enabled)
        if not self.controls[PCR_ENABLE][1].get():
            # With PCR off the response, level and plot are not used. A usable value stays in the recipe.
            inactive.update(PCR_DEPENDENT)
        return inactive

    def _inactive_value(self, kind, control):
        """Keep a usable inactive value. An unparsable number is omitted instead of failing the view."""
        if type(kind) is bool:
            return bool(control.get())
        if type(kind) is int:
            try:
                return int(str(control.get()).strip())
            except ValueError:
                return _INACTIVE_OMIT
        if type(kind) is float:
            try:
                value = float(decimal_comma(str(control.get()).strip()))
            except (TypeError, ValueError):
                return _INACTIVE_OMIT
            if not np.isfinite(value):
                return _INACTIVE_OMIT
            return value
        if kind == OPTIONAL:
            return control.get() or None
        if self.method == "Principal component analysis" and isinstance(kind, tuple) and control.get() in kind:
            return control.get()
        return _INACTIVE_OMIT

    def show_pca_fields(self):
        if self.method != "Principal component analysis" or PCA_GRAPH not in self.field_rows:
            return
        view = self.controls[PCA_GRAPH][1].get()
        inactive = view in PCA_ONE_DIMENSION
        states = {
            PCA_HORIZONTAL: "disabled" if inactive else "normal",
            PCA_VERTICAL: "disabled" if inactive else "normal",
            PCA_LABEL: "disabled" if inactive else "readonly",
            PCA_SHOW_LABELS: "disabled" if inactive else "normal",
            PCA_COLOR_GROUPS: "readonly" if view in PCA_POINT_VIEWS else "disabled",
        }
        overlay_kind = self.controls[pca_overlays.KIND][1].get()
        for label, enabled in pca_overlays.active_fields(view in PCA_POINT_VIEWS, overlay_kind).items():
            states[label] = ("normal" if label == pca_overlays.LEVEL else "readonly") if enabled else "disabled"
        for label, state in states.items():
            # The widgets stay gridded. Disabled means the view does not use them.
            self.field_rows[label][1].configure(state=state)
        if PCA_SELECTION in self.field_rows:
            self.show_fields(self.selection_visibility())
        if PCR_ENABLE in self.field_rows:
            # Same rule as the graph fields: the widgets stay gridded and PCR off disables what it does not use.
            on = bool(self.controls[PCR_ENABLE][1].get())
            for label, enabled in ((PCR_RESPONSE, "readonly"), (PCR_CONFIDENCE, "normal"), (PCR_PLOT, "readonly")):
                self.field_rows[label][1].configure(state=enabled if on else "disabled")

    def box_violin_visibility(self):
        if self.method != BOX_VIOLIN:
            return {}
        return box_violin_visibility(*(self.controls[name][1].get()
                                       for name in ("Input", "Style", "Whiskers", "Overlay observations")))

    def grouped_distribution_visibility(self):
        if self.method != GROUPED_DISTRIBUTIONS:
            return {}
        return grouped_distribution_visibility(*(self.controls[name][1].get()
                                                 for name in ("Style", "Whiskers", "Overlay observations")))

    def forest_fields(self):
        if self.method != FOREST_PLOT:
            return {}
        return forest_visibility(self.controls["Input"][1].get())

    def forest_columns(self):
        """Study columns in the order they were selected; columns added together keep sheet order."""
        box = self.controls["Study columns"][1]
        chosen = [box.get(i) for i in box.curselection()]
        self.forest_order = [name for name in self.forest_order if name in chosen] + [
            name for name in chosen if name not in self.forest_order]
        return list(self.forest_order)

    def forest_measure_defaults(self):
        scale, reference = forest_defaults(self.controls["Measure"][1].get())
        self.controls["Scale"][1].set(scale)
        self.controls["Reference"][1].set(f"{reference:g}")

    def update_forest_rows(self):
        """Relabel the role rows with the chosen row titles, keeping the chosen positions."""
        options = {"Row titles": self.controls["Row titles"][1].get() or None}
        try:
            labels = forest_row_choices(self.data, options)
        except ValueError:
            return
        for label in FOREST_ROLE_ROWS:
            self.field_rows[label][1].configure(values=labels)
            current = self.controls[label][1].get()
            position = current.split(" ", 1)[0]
            match = next((choice for choice in labels if choice.split(" ", 1)[0] == position), "")
            self.controls[label][1].set(match)

    def function_fields(self):
        """Generated grids show the limits and segments; Worksheet shows only the X column."""
        if self.method != PLOT_FUNCTION:
            return {}
        return function_visibility(self.controls[FUNCTION_X_SOURCE][1].get())

    def monte_carlo_fields(self):
        """Only the fields of the chosen design; worksheet X hides N and the X limits."""
        if self.method != MONTE_CARLO_METHOD:
            return {}
        return monte_carlo_visibility(self.controls[MONTE_CARLO_STUDY][1].get(),
                                      self.controls[MONTE_CARLO_X_SOURCE][1].get())

    def independent_roc_fields(self):
        """The cutoff belongs to the partial areas; the replicates, seed and saving to the bootstrap."""
        if self.method != INDEPENDENT_ROC or IROC_AREA not in self.controls:
            return {}
        return independent_roc_visibility(self.controls[IROC_AREA][1].get(), self.controls[IROC_INFERENCE][1].get())

    def show_independent_roc_fields(self, changed):
        """A partial area has no DeLong variance: choosing one proposes the percentile bootstrap, saved when run."""
        if changed == IROC_AREA:
            area, inference = self.controls[IROC_AREA][1], self.controls[IROC_INFERENCE][1]
            proposed = independent_roc_inference(area.get(), inference.get())
            if proposed != inference.get():
                inference.set(proposed)
        self.show_fields(self.independent_roc_fields())

    def precision_recall_fields(self):
        if self.method != precision_recall.METHOD:
            return {}
        return precision_recall.visibility(self.controls[precision_recall.SECOND_SCORE][1].get(),
                                           self.controls[precision_recall.BOOTSTRAP][1].get())

    def icc_fields(self):
        if self.method != icc.METHOD:
            return {}
        return icc.visibility(self.controls[icc.BOOTSTRAP][1].get())

    def icc_raters(self):
        control = self.controls[icc.RATERS][1]
        selected = [control.get(index) for index in control.curselection()]
        kept = [name for name in self.icc_rater_order if name in selected]
        return kept + [name for name in selected if name not in kept]

    def show_icc_summary(self):
        self.icc_rater_order = self.icc_raters()
        if len(self.icc_rater_order) < 2:
            self.icc_summary.configure(text=tr("icc.summary.none"))
            return
        counts = icc.summary(self.data, {icc.RATERS: self.icc_rater_order})
        definition, unit = (ui(self.controls[name][1].get()) for name in (icc.DEFINITION, icc.UNIT))
        self.icc_summary.configure(text="\n".join((
            tr("icc.summary.counts", **counts),
            tr("icc.summary.order", names=" → ".join(self.icc_rater_order)),
            tr("icc.summary.unit", definition=definition, unit=unit),
        )))

    def new_monte_carlo_seed(self):
        import secrets

        self.controls[MONTE_CARLO_SEED][1].set(str(secrets.randbelow(MAX_SEED + 1)))

    def copy_monte_carlo_seed(self):
        """Put the seed on the clipboard so another study can reuse the same random draws."""
        self.clipboard_clear()
        self.clipboard_append(self.controls[MONTE_CARLO_SEED][1].get().strip())

    def configure_kappa_fields(self, variables, options, positions):
        """The order editor follows the two columns and the weighting; the bootstrap fields follow the interval."""
        for label in ("First rating", "Second rating"):
            self.controls[label][1].trace_add("write", lambda *_: self.refresh_kappa_order())
        self.controls[KAPPA_WEIGHTING][1].trace_add(
            "write", lambda *_: self.controls[KAPPA_ORDER][1].set_weighting(self.controls[KAPPA_WEIGHTING][1].get()))
        self.controls["Confidence interval"][1].trace_add("write", lambda *_: self.show_fields(self.kappa_fields()))
        for page, key in ((variables, "ratings"), (options, "interval")):
            ttk.Label(page, text=tr(KAPPA_HINTS[key]), wraplength=ui_theme.px(410), foreground="#486075",
                      justify="left").grid(row=positions[page], column=0, columnspan=2, sticky="w", pady=(8, 0))
            positions[page] += 1
        self.controls[KAPPA_ORDER][1].set_weighting(self.controls[KAPPA_WEIGHTING][1].get())
        self.refresh_kappa_order()
        self.show_fields(self.kappa_fields())
        self._bind_scrollable_children(variables)

    def refresh_kappa_order(self):
        if self.method != COHEN_KAPPA or KAPPA_ORDER not in self.controls:
            return
        first, second = (self.controls[name][1].get() for name in ("First rating", "Second rating"))
        self.controls[KAPPA_ORDER][1].set_observed(*kappa_preview(self.data, first, second))

    def kappa_fields(self):
        if self.method != COHEN_KAPPA or "Confidence interval" not in self.controls:
            return {}
        return kappa_visibility(self.controls["Confidence interval"][1].get())

    def robust_fields(self):
        if self.method != ROBUST_CURVE or ROBUST_SCALE_METHOD not in self.controls:
            return {}
        return robust_visibility(self.controls[ROBUST_SCALE_METHOD][1].get())

    def nb2_fields(self):
        if self.method != NB2 or NB2_MODE not in self.controls:
            return {}
        return nb2_visibility(self.controls[NB2_MODE][1].get())

    def competing_fields(self):
        if self.method != COMPETING_RISKS or COMPETING_GRAPH not in self.controls:
            return {}
        return competing_visibility(self.controls[COMPETING_GRAPH][1].get())

    def configure_weibull_fields(self, variables, options, positions):
        """Profiles follow the chosen predictors, Shape follows the shape mode, and two notes explain the model."""
        for label in (WEIBULL_PREDICTORS, WEIBULL_CATEGORICAL):
            self.controls[label][1].bind("<<ListboxSelect>>", lambda _: self.update_weibull_profiles(), add="+")
        self.controls[WEIBULL_SHAPE_MODE][1].trace_add("write", lambda *_: self.show_fields(self.weibull_fields()))
        for page, key in ((variables, "status"), (options, "model")):
            ttk.Label(page, text=tr(WEIBULL_HINTS[key]), wraplength=ui_theme.px(400), foreground="#486075",
                      justify="left").grid(row=positions[page], column=0, columnspan=2, sticky="w", pady=(8, 0))
            positions[page] += 1
        self.update_weibull_profiles()
        self.show_fields(self.weibull_fields())

    def update_weibull_profiles(self):
        def picked(label):
            box = self.controls[label][1]
            return [box.get(i) for i in box.curselection()]

        self.controls[WEIBULL_PROFILES][1].set_predictors(picked(WEIBULL_PREDICTORS), picked(WEIBULL_CATEGORICAL))

    def weibull_fields(self):
        if self.method != WEIBULL_AFT or WEIBULL_SHAPE_MODE not in self.controls:
            return {}
        return weibull_visibility(self.controls[WEIBULL_SHAPE_MODE][1].get())

    def update_ordinal_order(self):
        """Read the categories of the chosen response again and let the order editor follow them."""
        if self.method != ORDINAL_LOGIT or ORDINAL_ORDER not in self.controls:
            return
        response = self.controls["Response"][1].get()
        self.controls[ORDINAL_ORDER][1].sync(read_observed(self.data, response, self._picked("Predictors")), response)
        self.update_ordinal_profiles()

    def update_ordinal_profiles(self):
        if self.method == ORDINAL_LOGIT and ORDINAL_PROFILES in self.controls:
            self.controls[ORDINAL_PROFILES][1].set_predictors(self._picked("Predictors"),
                                                              self._picked("Categorical predictors"))
    def configure_rmst_fields(self, variables, options, positions):
        """Reference group follows Group, Horizon shows its usable limit, and two notes explain the estimate."""
        horizon = self.controls[RMST_HORIZON][1]
        typed = read_rmst_number(horizon.get())
        if isinstance(typed, float) and np.isfinite(typed):
            horizon.set(rmst_shown_number(typed))  # a saved 6.5 reads 6,5 in Italian
        self.rmst_limit = ttk.Label(variables, text="", foreground="#486075", justify="left")
        self.rmst_limit.grid(row=positions[variables], column=1, sticky="w")
        positions[variables] += 1
        for page, keys in ((variables, ("horizon",)), (options, ("codes", "estimate"))):
            for key in keys:
                ttk.Label(page, text=tr(RMST_HINTS[key]), wraplength=ui_theme.px(400), foreground="#486075",
                          justify="left").grid(row=positions[page], column=0, columnspan=2, sticky="w", pady=(8, 0))
                positions[page] += 1
        for name in (RMST_TIME, RMST_STATUS, RMST_GROUP, RMST_EVENT, RMST_CENSOR):
            self.controls[name][1].trace_add("write", lambda *_: self.refresh_rmst())
        self.refresh_rmst()

    def refresh_rmst(self):
        """Offer the groups of the complete rows; a saved reference that is no longer a group stays shown."""
        if self.method != RMST or RMST_REFERENCE not in self.controls:
            return
        options = {name: self.controls[name][1].get()
                   for name in (RMST_TIME, RMST_STATUS, RMST_GROUP, RMST_EVENT, RMST_CENSOR)}
        levels = rmst_group_levels(self.data, options)
        self.field_rows[RMST_REFERENCE][1].configure(values=levels)
        reference = self.controls[RMST_REFERENCE][1]
        if not reference.get() and levels:
            reference.set(levels[0])
        self.show_fields(self.rmst_fields())
        self.rmst_limit.configure(text=rmst_limit_hint(rmst_horizon_limit(self.data, options)))

    def rmst_fields(self):
        if self.method != RMST or RMST_GROUP not in self.controls:
            return {}
        return rmst_visibility(self.controls[RMST_GROUP][1].get())

    def refresh_competing_causes(self):
        """Offer the typed event codes for the drawn cause; a value that is no longer a code stays shown, never rewritten."""
        binding = self.choice_bindings.get(COMPETING_GRAPH_CAUSE)
        editor = self.controls.get(COMPETING_EVENTS)
        if binding is not None and editor is not None:
            binding.set_values(["", *editor[1].codes()])

    def robust_proposal(self):
        """Catalog starting values of the first fit with the columns and the model now chosen; {} when unknown."""
        box = self.controls[ROBUST_Y][1]
        options = {ROBUST_X: self.controls[ROBUST_X][1].get(), ROBUST_Y: [box.get(i) for i in box.curselection()],
                   ROBUST_GROUP: self.controls[ROBUST_GROUP][1].get() or None,
                   ROBUST_MODEL: self.controls[ROBUST_MODEL][1].get()}
        return robust_proposal(self.data, options)

    def custom_fields(self):
        if self.method != CUSTOM_EQUATION or "Weighting" not in self.controls:
            return {}
        return {CUSTOM_SD: self.controls["Weighting"][1].get() == INVERSE_VARIANCE}

    def global_custom_fields(self):
        if self.method != GLOBAL_CUSTOM_EQUATION or "Weighting" not in self.controls:
            return {}
        visible = {CUSTOM_SD: self.controls["Weighting"][1].get() == INVERSE_VARIANCE}
        if GLOBAL_BAND in self.controls:
            band = self.controls[GLOBAL_BAND][1].get() not in ("", GLOBAL_NONE)
            predict = bool(self.controls[GLOBAL_PREDICT][1].get())
            interval = self.controls[GLOBAL_QUERY_INTERVAL][1].get() if predict else GLOBAL_NONE
            visible.update({GLOBAL_DRAWING: band,
                            GLOBAL_RESPONSE_LEVEL: band or interval not in ("", GLOBAL_NONE),
                            GLOBAL_QUERY_X: predict, GLOBAL_QUERY_GROUP: predict, GLOBAL_QUERY_INTERVAL: predict,
                            GLOBAL_EXTRAPOLATE: predict, GLOBAL_QUERY_K: interval == GLOBAL_PREDICTION})
        return visible

    def global_series_labels(self):
        """Complete-pair series for the constraint page. A half-typed recipe lists nothing."""
        needed = ("X", "Y", "Group", "Equation", "Parameters", "Weighting")
        if any(name not in self.controls for name in needed):
            return []
        weighting = self.controls["Weighting"][1].get()
        options = {"X": self.controls["X"][1].get(), "Y": self.controls["Y"][1].get(),
                   "Group": self.controls["Group"][1].get() or None,
                   "Equation": self.controls["Equation"][1].values(),
                   "Parameters": self.controls["Parameters"][1].values(),
                   "Series constraints": [], "Weighting": weighting, CUSTOM_SD: None,
                   CUSTOM_LEVEL: 95.0, CUSTOM_POINTS: 201}
        if weighting == INVERSE_VARIANCE and CUSTOM_SD in self.controls:
            options[CUSTOM_SD] = self.controls[CUSTOM_SD][1].get() or None
        return series_in(self.data, options)

    def custom_candidate(self):
        """The recipe as typed, for Check equation. Fields that this check does not use stay at their defaults."""
        def get(name):
            return self.controls[name][1].get()

        options = {"X": get("X"), "Y": get("Y"), "Group": get("Group") or None, "Weighting": get("Weighting"),
                   CUSTOM_SYNTAX: self.equation_syntax(),
                   "Equation": self.controls["Equation"][1].values(),
                   "Parameters": self.controls["Parameters"][1].values()}
        if options["Weighting"] == INVERSE_VARIANCE:
            options[CUSTOM_SD] = get(CUSTOM_SD) or None
        return options

    def equation_syntax(self):
        """The canonical Equation syntax of the dialog; Arithmetic while the control does not exist."""
        control = self.controls.get(CUSTOM_SYNTAX)
        return control[1].get() if control is not None else "Arithmetic"

    def bind_equation_syntax(self):
        """Show the conditional guide for the chosen syntax. The equation and the coefficients stay as typed."""
        variable = self.controls[CUSTOM_SYNTAX][1]
        editor = self.controls["Equation"][1]

        def changed(*_):
            editor.set_syntax(variable.get())
            table = self.controls.get("Parameters")
            if table is not None and hasattr(table[1], "mark_unused"):
                table[1].mark_unused()

        variable.trace_add("write", changed)
        editor.set_syntax(variable.get())

    def check_custom_equation(self, editor):
        """Syntax, names and domain at the starting values on the used X. No fit is started."""
        try:
            check_custom_options(self.data, self.custom_candidate())
        except (ValueError, OverflowError) as error:
            field = getattr(error, "field", None)
            prefix = f"{tr('custom.field.' + field)}: " if field and tr("custom.field." + field) != "custom.field." + field else ""
            editor.show(prefix + translate_custom_error(error), False)
        else:
            editor.show(tr("custom.check_ok"), True)

    def global_custom_candidate(self):
        """The recipe as typed, for Check equation. Confidence and curve points stay at their defaults."""
        def get(name):
            return self.controls[name][1].get()

        options = {"X": get("X"), "Y": get("Y"), "Group": get("Group") or None, "Weighting": get("Weighting"),
                   CUSTOM_SYNTAX: self.equation_syntax(),
                   "Equation": self.controls["Equation"][1].values(),
                   "Parameters": self.controls["Parameters"][1].values(),
                   "Series constraints": self.controls["Series constraints"][1].values(),
                   CUSTOM_LEVEL: 95.0, CUSTOM_POINTS: 201}
        options[CUSTOM_SD] = get(CUSTOM_SD) or None if options["Weighting"] == INVERSE_VARIANCE else None
        return options

    def check_global_custom_equation(self, editor):
        """Syntax, names, series overrides and the domain at the starting values. No fit is started."""
        try:
            check_global_custom_options(self.data, self.global_custom_candidate())
        except (ValueError, OverflowError) as error:
            field = getattr(error, "field", None)
            key = "gfit.field." + field if field else ""
            label = tr(key) if field else ""
            prefix = f"{label}: " if field and label != key else ""
            editor.show(prefix + translate_global_error(error), False)
        else:
            editor.show(tr("gfit.check_ok"), True)

    def curve_fields(self):
        """The Curve pipeline fields for Method = Curve pipeline, the LOWESS fraction for the three older choices."""
        if self.method != curve_pipeline.CURVE_METHOD:
            return {}
        return curve_pipeline.visibility(*(self.controls[label][1].get() for label in (
            "Method", curve_pipeline.OPERATION, curve_pipeline.SMOOTHING)))

    def show_curve_fields(self):
        self.show_fields(self.curve_fields())
        shown = curve_notes_visibility(self.controls["Method"][1].get(), self.controls[curve_pipeline.SMOOTHING][1].get(),
                                       curve_pipeline.PIPELINE, curve_pipeline.SAVITZKY_GOLAY)
        for note, visible in zip(self.curve_notes, shown):
            if visible:
                note.grid()
            else:
                note.grid_remove()

    def spline_fields(self):
        """Knots for the smoothing spline, fraction and iterations for LOWESS, Query for a query direction."""
        if self.method != SPLINE_FIT:
            return {}
        return spline_visibility(self.controls[SPLINE_METHOD][1].get(), self.controls[SPLINE_DIRECTION][1].get())

    def outlier_fields(self):
        """Q (%) belongs to ROUT and Alpha to the Grubbs tests."""
        if self.method != OUTLIERS:
            return {}
        return outlier_visibility(self.controls[OUTLIER_METHOD][1].get())

    def normality_fields(self):
        if self.method != NORMALITY:
            return {}
        return normality_visibility(self.controls[QQ_PLOT][1].get())

    def update_qq_choices(self):
        """Offer only the selected variables for the Q–Q plot and drop a variable that is no longer selected."""
        box = self.controls["Variables"][1]
        chosen = [box.get(i) for i in box.curselection()]
        self.field_rows[QQ_VARIABLE][1].configure(values=[""] + chosen)
        variable = self.controls[QQ_VARIABLE][1]
        if variable.get() not in chosen:
            variable.set("")

    def parts_visibility(self):
        if self.method == PARTS_GRAPH:
            style = self.controls["Graph style"][1].get()
            pie = style in {PIE, DONUT}
            return {"Donut hole (%)": style == DONUT, "Number of dots": style == DOTS,
                    START_ANGLE: pie, CLOCKWISE: pie, SLICE_LABELS: pie, BORDER_COLOR: pie,
                    BORDER_WIDTH: pie, SEGMENT_STYLES: True}
        if self.method == GOODNESS_OF_FIT:
            exact = self.controls[TEST_METHOD][1].get() == EXACT_BINOMIAL
            return {"Expected values": self.controls["Expected distribution"][1].get() != EXPECTED_DISTRIBUTIONS[0],
                    "Estimated parameters": not exact, BINOMIAL_LEVEL: exact}
        return {}

    def show_parts_fields(self):
        self.show_fields(self.parts_visibility())

    def show_goodness_fields(self):
        """Switching to the exact test sets Estimated parameters back to 0 in plain view, then shows the right fields."""
        note = ""
        if self.controls[TEST_METHOD][1].get() == EXACT_BINOMIAL:
            estimated = self.controls["Estimated parameters"][1]
            if estimated.get().strip() not in ("", "0"):
                estimated.set("0")
                note = tr("goodness.note.reset")
            else:
                note = tr("goodness.note.exact")
        self.goodness_note.configure(text=note)
        self.show_parts_fields()

    def _install_segment_styles(self, saved, positions):
        parent = self.field_rows["Graph style"][0].master
        row = positions[parent]
        positions[parent] += 1
        heading = ttk.Label(parent, text=SEGMENT_STYLES, wraplength=170)
        heading.grid(row=row, column=0, sticky="nw", pady=4, padx=(0, 10))
        panel = ttk.Frame(parent)
        panel.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(panel, text=tr("parts.style.edit_button"), command=self.edit_segment_styles).pack(side="left")
        ttk.Label(panel, text=tr("parts.style.row_hint"),
                  foreground="#486075").pack(side="left", padx=(8, 0))
        self.field_rows[SEGMENT_STYLES] = heading, panel
        stored = saved.get(SEGMENT_STYLES) or {}
        self.segment_styles = deepcopy(stored) if isinstance(stored, dict) else {}
        self.apply_segment_styles = bool(saved.get(APPLY_SEGMENT_STYLES, False))

    def edit_segment_styles(self):
        from analisi.parts_style_dialog import PartsStyleDialog

        dialog = PartsStyleDialog(self, self.data, self._parts_preview_options(), self.segment_styles)
        self.grab_set()
        if dialog.result is not None:
            self.segment_styles = dialog.result
            self.apply_segment_styles = True

    def _parts_preview_options(self):
        options = {}
        for label in ("Values", "Row titles", "Reverse order", "Graph style"):
            kind, control = self.controls[label]
            value = control.get()
            options[label] = value or None if kind == OPTIONAL else value
        return options

    def _control_value(self, label):
        kind, control = self.controls[label]
        value = control.get()
        if type(kind) is float:
            try:
                value = float(decimal_comma(value))
            except ValueError:
                raise ValueError(f"{label} must be a number.") from None
            if not np.isfinite(value):
                raise ValueError(f"{label} must be finite.")
        return value

    def _collect_pie_options(self, options):
        """Keep pie settings when the graph style hides them, and drop untouched defaults."""
        saved = self.current[1] if self.current and self.current[0] == self.method else {}
        pie = options.get("Graph style") in {PIE, DONUT}
        fields = (START_ANGLE, CLOCKWISE, SLICE_LABELS, BORDER_COLOR, BORDER_WIDTH)
        if pie:
            for label in fields:
                if label in options and label not in saved and pie_value_is_default(label, options[label]):
                    options.pop(label)
        else:
            for label in fields:
                try:
                    value = self._control_value(label)
                except ValueError:
                    if label in saved:
                        options[label] = saved[label]
                    continue
                if label in saved or not pie_value_is_default(label, value):
                    options[label] = value
        styles = self.segment_styles if isinstance(getattr(self, "segment_styles", None), dict) else {}
        if styles:
            options[SEGMENT_STYLES] = styles
        else:
            options.pop(SEGMENT_STYLES, None)
        if getattr(self, "apply_segment_styles", False):
            options[APPLY_SEGMENT_STYLES] = True
        elif APPLY_SEGMENT_STYLES in saved:
            options[APPLY_SEGMENT_STYLES] = bool(saved[APPLY_SEGMENT_STYLES])
        else:
            options.pop(APPLY_SEGMENT_STYLES, None)

    def extract_visibility(self):
        if self.method != EXTRACT_REARRANGE:
            return {}
        kind = self.controls[EXTRACT_OUTPUT][1].get()
        active = EXTRACT_FIELDS.get(kind, ())
        return {**{field: field in active for fields in EXTRACT_FIELDS.values() for field in fields},
                EXTRACT_COMPLETE: kind != "Contingency"}

    def show_extract_fields(self):
        self.show_fields(self.extract_visibility())

    def weighting_visibility(self):
        if self.method != "Nonlinear regression":
            return {}
        return {"SD column": self.controls["Weighting"][1].get() == INVERSE_VARIANCE}

    def show_weighting_fields(self):
        """Offer the SD column only for Inverse variance (column) and explain the chosen denominator.

        The global fit keeps its SD column and format controls as they are and only gains the note.
        """
        self.show_fields(self.weighting_visibility())
        choice = self.controls["Weighting"][1].get()
        self.weighting_note.configure(text=tr(NOTE_KEYS.get(choice, NOTE_KEYS[UNWEIGHTED])))

    def deming_visibility(self):
        if self.method != deming_dialog.METHOD:
            return {}
        return deming_dialog.visibility(self.controls[deming_dialog.UNCERTAINTY][1].get(),
                                        self.controls["Parameter intervals"][1].get())

    def show_deming_fields(self):
        """The ratio or the SDs, according to the input; the SD note goes with the SDs."""
        visible = self.deming_visibility()
        self.show_fields(visible)
        if visible[deming_dialog.X_SD]:
            self.deming_sd_note.grid()
        else:
            self.deming_sd_note.grid_remove()

    def _check_deming(self, options):
        deming_dialog.check_options(options, self.data)

    def lognormal_fields(self):
        if self.method != LOGNORMAL or RATIO_DESIGN not in self.controls:
            return {}
        return lognormal_visibility(self.controls[RATIO_DESIGN][1].get(),
                                    self.controls[lognormal_tests.INPUT][1].get())

    def show_lognormal_fields(self):
        visible = self.lognormal_fields()
        self.show_fields(visible)
        self._show_variance_note(visible)
        if visible[lognormal_tests.FIRST_GROUP]:
            options = {name: self.controls[name][1].get()
                       for name in (RATIO_DESIGN, *lognormal_tests.GROUP_FIELDS)}
            labels = lognormal_tests.group_choices(self.data, options)
            self.field_rows[lognormal_tests.FIRST_GROUP][1].configure(values=labels)
            first = self.controls[lognormal_tests.FIRST_GROUP][1]
            if not first.get() and labels:
                first.set(labels[0])

    def ttest_variance_fields(self):
        """Only show the graph and diagnostic options the design supports."""
        if self.method != "t-test" or VARIANCE_SHOW not in self.controls:
            return {}
        design = self.controls["Design"][1].get()
        sample_format = self.controls[ttest_options.INPUT][1].get()
        return {**ttest_options.visibility(design, sample_format),
                VARIANCE_SHOW: design in ("Welch", "Student"), TTEST_ESTIMATION: design == "Paired"}

    def show_ttest_variance(self):
        visible = self.ttest_variance_fields()
        self.show_fields(visible)
        self._show_variance_note(visible)

    def _show_variance_note(self, visible):
        note = getattr(self, "variance_ratio_note", None)
        if note is None:
            return
        if visible.get(VARIANCE_SHOW):
            note.configure(text=tr(VARIANCE_RATIO_NOTE))
            note.grid()
        else:
            note.grid_remove()

    def power_fields(self):
        """Only the inputs of the chosen goal, design and effect input; hidden ones never block the calculation."""
        if self.method != POWER_METHOD or POWER_GOAL not in self.controls:
            return {}
        return power_visibility({label: self.controls[label][1].get()
                                 for label in (POWER_GOAL, POWER_DESIGN, POWER_EFFECT_INPUT, POWER_PAIRED_SD_INPUT)})

    def show_power_fields(self):
        visibility = self.power_fields()
        self.show_fields(visibility)
        # The allocation note belongs to the allocation field: it follows it.
        if self.power_allocation_note is not None:
            if visibility.get(POWER_ALLOCATION):
                self.power_allocation_note.grid()
            else:
                self.power_allocation_note.grid_remove()

    def equivalence_fields(self):
        """Response and Reference belong to One-sample, First and Second to the other designs."""
        if self.method != EQUIVALENCE or TOST_DESIGN not in self.controls:
            return {}
        return equivalence_visibility(self.controls[TOST_DESIGN][1].get())

    def paired_fields(self):
        """Before, After and the two codes belong to Observations; the two count columns to Count matrix."""
        if self.method != PAIRED_PROPORTIONS or PAIRED_FORMAT not in self.controls:
            return {}
        return paired_visibility(self.controls[PAIRED_FORMAT][1].get())

    def show_paired_fields(self):
        visible = self.paired_fields()
        self.show_fields(visible)
        matrix = not visible.get("Before", True)
        for name, note in self.paired_notes.items():
            if (name == "matrix") == matrix:
                note.grid()
            else:
                note.grid_remove()

    def summary_anova_fields(self):
        if self.method not in (SUMMARY_ANOVA, SUMMARY_TTEST):
            return {}
        return summary_anova_visibility(self.controls["Input"][1].get())

    def _refresh_summary_posthoc(self):
        """Show the post-hoc family for the selected method without changing a stored choice."""
        binding = self.choice_bindings.get("Post-hoc")
        if binding is None or "Method" not in self.controls:
            return
        unequal = self.controls["Method"][1].get() in (SUMMARY_WELCH, SUMMARY_JOINT)
        binding.set_values(SUMMARY_UNEQUAL_POSTHOC if unequal else SUMMARY_ORDINARY_POSTHOC)

    def ancova_fields(self):
        """The control group belongs to Against control; the adjustment to either comparison."""
        if self.method != ANCOVA or ANCOVA_COMPARISONS not in self.controls:
            return {}
        return ancova_visibility(self.controls[ANCOVA_COMPARISONS][1].get())

    def show_ancova_fields(self):
        self.show_fields(self.ancova_fields())
        self.refresh_ancova_groups()

    def refresh_ancova_groups(self):
        """Offer the groups with complete data under the chosen columns; a stale choice becomes empty."""
        if ANCOVA_CONTROL not in self.field_rows:
            return
        choices = ancova_group_choices(self.data, {name: self.controls[name][1].get() for name in ANCOVA_DATA_FIELDS})
        self.field_rows[ANCOVA_CONTROL][1].configure(values=choices)
        control = self.controls[ANCOVA_CONTROL][1]
        if choices and control.get() not in choices:
            control.set("")

    def compare_lines_fields(self):
        if self.method != COMPARE_LINES:
            return {}
        return compare_lines_visibility(self.controls["Input"][1].get())

    def band_fields(self):
        """Level and drawing apply only when a band is requested."""
        if self.method != "Nonlinear regression":
            return {}
        active = self.controls[NL_BAND][1].get() != NL_BAND_NONE
        return {NL_BAND_LEVEL: active, NL_BAND_DRAWING: active,
                REPORT_LOG_IC50: has_ic50(self.controls["Model"][1].get())}

    def linear_visibility(self):
        if self.method != "Linear regression":
            return {}
        forward = bool(self.controls[LINEAR_Y_CI][1].get())
        inverse = bool(self.controls[LINEAR_X_CI][1].get())
        return {"Confidence level (%)": self.controls["Band"][1].get() != BAND_NONE or forward or inverse,
                LINEAR_X_VALUE: forward, LINEAR_Y_VALUE: inverse}

    def calibration_visibility(self):
        if self.method != "Interpolate a standard curve":
            return {}
        return standard_curve_visibility(*(self.controls[name][1].get()
                                           for name in (CALIBRATION_DIRECTION, "Curve", CALIBRATION_UNCERTAINTY)),
                                         model=self.controls["Model"][1].get())

    def show_calibration_fields(self):
        """Show interval fields for the current model, and the inverse-interval note only when it applies."""
        self.show_fields(self.calibration_visibility())
        self.show_calibration_unit()
        note = getattr(self, "inverse_note", None)
        if note is None:
            return
        model = self.controls["Model"][1].get()
        active = (self.controls[CALIBRATION_DIRECTION][1].get() != CALIBRATION_DIRECTIONS[1]
                  and self.controls["Curve"][1].get() == "Nonlinear"
                  and model in INVERSE_INTERVAL_MODELS
                  and self.controls[CALIBRATION_UNCERTAINTY][1].get() != "None")
        if active:
            note.configure(text=tr("calib.inverse_nonlinear.note"))
            note.grid()
        else:
            note.grid_remove()

    def show_calibration_unit(self):
        """Name the X unit on the model label. Saved recipe ids stay the catalog names."""
        heading = self.field_rows["Model"][0]
        model = self.controls["Model"][1].get()
        if str(model).endswith(", log10 X)"):
            key = "calib.inverse_nonlinear.field.model_log10"
        elif model in CONCENTRATION_4PL:
            key = "calib.inverse_nonlinear.field.model_concentration"
        else:
            key = "calib.inverse_nonlinear.field.model"
        heading.configure(text=tr(key))

    def show_rank_fields(self):
        """The continuity correction belongs to the normal approximation, so the exact p value switches it off."""
        exact = self.controls[RANK_P][1].get() == RANK_EXACT
        self.field_rows[RANK_CONTINUITY][1].state(["disabled" if exact else "!disabled"])

    def xy_error_fields(self):
        if self.method != XY_ERRORS:
            return {}
        return xy_error_visibility(*(self.controls[name][1].get() for name in (
            "X error distance", "X lower error", "X upper error", "X error values",
            "Y lower error", "Y upper error", "Y error values",
        )))

    def reference_visibility(self):
        if self.method != REFERENCE_NORMALIZATION:
            return {}
        controls = self.controls
        return reference_field_visibility({
            "Input": controls["Input"][1].get(),
            "Zero reference": controls["Zero reference"][1].get(),
            "One reference": controls["One reference"][1].get(),
            "Error format": controls["Error format"][1].get(),
        })

    def show_reference_fields(self):
        self.show_fields(self.reference_visibility())
        note = self.reference_replicate_note
        if note is None:
            return
        key = replicate_note_key(self.controls["Input"][1].get(), self.controls["Replicates"][1].get())
        if key is None:
            note.grid_remove()
            return
        note.configure(text=tr(key))
        note.grid()

    def show_fields(self, visibility):
        for label, visible in visibility.items():
            for widget in self.field_rows[label]:
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()

    def validate(self):
        options = {}
        name = None
        self.processing_result = None
        inactive = self._inactive_controls()
        visibility = {**self.processing_visibility(), **self.kmeans_visibility(),
                      **self.hierarchical_visibility(), **self.overlay_visibility(),
                      **self.extract_visibility(), **self.category_visibility(), **self.contingency_visibility(),
                      **self.parts_visibility(), **self.frequency_visibility(), **self.correlation_visibility(),
                      **self.correlation_details_visibility(),
                      **self.heat_map_visibility(), **self.row_test_visibility(), **self.nested_visibility(),
                      **self.survival_pairwise_fields(),
                      **self.box_violin_visibility(), **self.grouped_distribution_visibility(), **self.dunn_visibility(), **self.normality_fields(),
                      **self.outlier_fields(), **self.spline_fields(), **self.curve_fields(),
                      **self.auc_visibility(), **self.deming_visibility(), **self.linear_visibility(),
                      **self.calibration_visibility(), **self.agreement_visibility(),
                      **self.anova_fields(), **self.anova_term_fields(), **self.anova_diagnostic_fields(),
                      **self.regression_visibility(), **self.forest_fields(),
                      **self.compare_lines_fields(), **self.ancova_fields(), **self.lognormal_fields(), **self.ttest_variance_fields(),
                      **self.equivalence_fields(), **self.paired_fields(), **self.cox_fields(),
                      **(meta_analysis_dialog.fields(self) if self.method == META_ANALYSIS else {}),
                      **self.summary_anova_fields(),
                      **self.one_way_fields(),
                      **self.monte_carlo_fields(), **self.independent_roc_fields(), **self.precision_recall_fields(),
                      **self.icc_fields(), **self.power_fields(), **self.function_fields(),
                      **self.weighting_visibility(),
                      **self.band_fields(), **self.xy_error_fields(), **self.custom_fields(),
                      **self.global_custom_fields(), **self.robust_fields(), **self.competing_fields(),
                      **self.weibull_fields(), **self.rmst_fields(), **self.reference_visibility()}
        if self.method == "Descriptive statistics":
            visibility.update(summary_fields(self.controls[SUMMARY_FORMAT][1].get()))
        try:
            if self.join is not None:
                self.result = self.method, self.join.request()
                return True
            if self.reshape is not None:
                options = self.reshape.request()
                reshape.plan(self.data, options)
                self.result = self.method, options
                return True
            for name, (kind, control) in self.controls.items():
                if name in inactive:
                    value = self._inactive_value(kind, control)
                    if value is not _INACTIVE_OMIT:
                        options[name] = value
                    continue
                if not visibility.get(name, True):
                    continue
                if self.method == COHEN_KAPPA and (kind == KAPPA_ORDER_LIST or name in KAPPA_TYPED_FIELDS):
                    # Hidden bootstrap fields stay in the recipe as typed; the analysis reads them only when used.
                    options[name] = control.values() if kind == KAPPA_ORDER_LIST else read_kappa_typed(control.get())
                    continue
                if self.method == "One-way ANOVA" and name == VARIANCE_ALPHA and type(kind) is float:
                    raw = control.get()
                    try:
                        value = float(decimal_comma(raw))
                    except (TypeError, ValueError):
                        value = raw
                    options[name] = value
                    continue
                if ((self.method == INDEPENDENT_ROC and name in IROC_NUMBER_FIELDS)
                        or (self.method == precision_recall.METHOD and name in precision_recall.NUMBER_FIELDS)
                        or (self.method == icc.METHOD and name in icc.BOOTSTRAP_FIELDS)
                        or (self.method == POWER_METHOD and name in POWER_NUMBER_FIELDS)):
                    # Keep text until the engine validates and normalizes the named field.
                    options[name] = control.get()
                    continue
                if self.method == RMST and name in RMST_NUMBER_FIELDS:
                    # Decimal comma accepted; text that is not a number reaches the analysis, which names the field.
                    options[name] = read_rmst_number(control.get())
                    continue
                if self.method == FOREST_PLOT and name == "Study columns":
                    value = self.forest_columns()
                elif self.method == icc.METHOD and name == icc.RATERS:
                    value = self.icc_raters()
                elif kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                    value = (self.anova_factors() if self.method == "Multifactor ANOVA" and name == "Factors"
                             else [control.get(i) for i in control.curselection()])
                    if (kind == MULTIPLE and not value
                            and self.method not in {kmeans_stability.METHOD, logistic_validation.METHOD}):
                        raise ValueError(f"Select at least one column for {name}.")
                elif kind in (GROUP_ORDER, TREND_ORDER_KIND, DUNN_PAIR_LIST, PAIRWISE_PAIR_LIST, PAIR_LIST, PROFILE_LIST, CURVE_LIST,
                              SETS_LIST, MODEL_LIST, EQUATION_TEXT, PARAMETER_LIST, INITIAL_LIST,
                              GLOBAL_PARAMETER_LIST, GLOBAL_SERIES_LIST, CATEGORY_COLOR_LIST, TERM_LIST,
                              COMPETING_CODE_LIST, COMPETING_TIME_LIST, WEIBULL_TIME_LIST, ORDINAL_ORDER_KIND):
                    value = control.values()
                else:
                    value = control.get()
                    if (self.method in {kmeans_stability.METHOD, logistic_validation.METHOD}
                            and type(kind) in (int, float)):
                        # Each engine validates and normalizes its own numeric entries.
                        options[name] = value
                        continue
                    if self.method == "Linear regression" and name in (LINEAR_X_VALUE, LINEAR_Y_VALUE):
                        flag = LINEAR_Y_CI if name == LINEAR_X_VALUE else LINEAR_X_CI
                        value = check_linear_estimate_options({flag: True, name: decimal_comma(value)})[name]
                    if self.method == "Multifactor ANOVA" and name == ANOVA_DIAG_ALPHA:
                        # Keep nan and non-numeric text for the diagnostic FieldError instead of a generic message.
                        text = str(value).strip()
                        try:
                            options[name] = float(decimal_comma(text))
                        except ValueError:
                            options[name] = text
                        continue
                    if self.method == ANCOVA and name == ANCOVA_REFERENCE:
                        # Empty stays null (the mean of X); a number is stored as a number, never as text.
                        options[name] = ancova_reference_value({name: value})
                        continue
                    if self.method == HEAT_MAP and name == HEAT_MAP_LEGEND_DECIMALS:
                        options[name] = parse_heat_map_legend_decimals(value)
                        continue
                    if self.method == HEAT_MAP and name == CELL_LABEL_DECIMALS:
                        options[name] = parse_cell_label_decimals(value)
                        continue
                    if self.method == HEAT_MAP and name == CELL_LABEL_FONT_SIZE:
                        parsed_size = parse_cell_label_font_size(value)
                        options[name] = "" if parsed_size is None else parsed_size
                        continue
                    if self.method == HEAT_MAP and name in (ROW_GAP_SIZE, COLUMN_GAP_SIZE):
                        options[name] = parse_gap_size(value, name)
                        continue
                    if self.method == HEAT_MAP and name in (ROW_LABEL_EVERY, COLUMN_LABEL_EVERY):
                        options[name] = parse_label_every(value, name)
                        continue
                    if self.method == HEAT_MAP and name in (ROW_LABEL_FONT_SIZE, COLUMN_LABEL_FONT_SIZE):
                        parsed_size = parse_label_font_size(value, name)
                        options[name] = "" if parsed_size is None else parsed_size
                        continue
                    if self.method in kmeans_options.METHODS and name in kmeans_options.ITERATION_FIELDS.values():
                        options[name] = value
                        continue
                    if self.method == MEAN_PERMUTATION and name == PERMUTATION_SEED:
                        # Unsigned 64-bit; the test checks the range and names Seed.
                        options[name] = mean_permutation_dialog.parse_seed(value)
                        continue
                    numeric_kind = type(kind)
                    if numeric_kind in (int, float):
                        try:
                            value = numeric_kind(decimal_comma(value) if numeric_kind is float else value)
                        except ValueError:
                            raise ValueError(f"{name} must be a whole number." if numeric_kind is int
                                             else f"{name} must be a number.") from None
                        # Monte Carlo seeds are unsigned 64-bit; the study checks their own range.
                        seed = (self.method, name) in ((MONTE_CARLO_METHOD, MONTE_CARLO_SEED), (RMCORR, RMCORR_SEED))
                        if numeric_kind is int and not seed and not -(2**63) <= value < 2**63:
                            raise ValueError(f"{name} exceeds the supported integer range.")
                        if numeric_kind is float and not np.isfinite(value):
                            raise ValueError(f"{name} must be finite.")
                    elif kind == OPTIONAL:
                        value = value or None
                    elif kind is None and not value:
                        raise ValueError(f"Choose a column for {name}.")
                options[name] = value
            if self.method == "Descriptive statistics" and options.get(SUMMARY_FORMAT) == GEOMETRIC_REPORT:
                summary_confidence(options)
            if self.method == "Scatter / confidence ellipse" and self.ellipse_group_styles:
                options[ELLIPSE_GROUP_STYLES] = self.ellipse_group_styles
            if self.method == "Kaplan–Meier survival":
                check_survival_options(self.data, options)
            if self.method == "t-test":
                ttest_options.preserve_direction(options, self.data)
            if self.method == LOGNORMAL:
                lognormal_tests.check_grouped(self.data, options)
            if self.method == HIERARCHY_GRAPH:
                check_hierarchy_view(self.data, options)
            if self.method == "Hierarchical clustering":
                check_hierarchical_options(self.data, options)
            if self.method == kmeans_reports.MODEL_GRAPH:
                kmeans_reports.check_model_plot(self.data, options)
            if self.method in kmeans_options.METHODS:
                kmeans_options.scale(options)
                for report in (*kmeans_reports.SCAN, *kmeans_options.PLOTS):
                    if options.get(report) is False:
                        options.pop(report)
                request = kmeans_options.fit_options(self.method, self.data, options)
                if request:
                    field = kmeans_options.ITERATION_FIELDS[options[kmeans_options.ALGORITHM]]
                    options[field] = request["max_iterations"]
                else:
                    options.pop(kmeans_options.ALGORITHM, None)
            if self.method == kmeans_stability.METHOD:
                options = kmeans_stability.prepare(self.data, options).settings
            if self.method == logistic_validation.METHOD:
                options = logistic_validation.prepare(self.data, options).settings
            if self.method == NORMALITY:
                check_normality_options(self.data, options)
            if self.method == SUMMARY_ANOVA:
                check_summary_anova(self.data, options)
            if self.method == SUMMARY_TTEST:
                check_summary_ttest(self.data, options)
            if self.method == "Multifactor ANOVA":
                saved_terms = self.current[1] if self.current and self.current[0] == self.method else {}
                options.update(self.contrast_panel.values())
                chosen_terms = check_anova_terms(options)
                if (anova_sums_of_squares(options) == ANOVA_TYPE_III
                        and ANOVA_SUMS_OF_SQUARES not in saved_terms):
                    options.pop(ANOVA_SUMS_OF_SQUARES, None)  # Type III is the default of a recipe without the key
                if chosen_terms is None:
                    # Full hierarchy keeps the recipe free of the 0.83 keys unless the recipe already had them.
                    options.pop(ANOVA_MODEL_TERMS, None)
                    if ANOVA_TERM_SELECTION not in saved_terms:
                        options.pop(ANOVA_TERM_SELECTION, None)
                else:
                    check_anova_comparisons(options, options.get("Factors") or [], chosen_terms)
                check_anova_options(options)
                factors = options.get("Factors") or []
                model = anova_active_factors(factors, chosen_terms) if chosen_terms is not None else factors
                check_contrast_input(options, self.data, model)
                validate_anova_diagnostics(options)
                diagnostic_graph = anova_graph_choice(options)
                if diagnostic_graph != "None":
                    count = _anova_row_count(
                        self.data, options.get("Response"),
                        model)
                    if count is not None:
                        ensure_anova_graph_budget(count, diagnostic_graph)
            if self.method == "Area under curve":
                check_auc_options(options)
            if self.method == "One-way ANOVA":
                self._keep_hidden_variance(options)
                check_one_way_options(options)
                validate_variance(options)
                lognormal_anova.validate_request(options)
                if lognormal_anova.active(options):
                    lognormal_anova.check_used(self.data, options)
            if self.method == CONTINGENCY:
                check_contingency_options(self.data, options)
            if self.method == MEAN_PERMUTATION:
                # Fields, values and the exact or Monte Carlo budget; nothing is enumerated or drawn here.
                check_permutation_options(self.data, options)
            if self.method == MONTE_CARLO_METHOD:
                # Numbers, fields and the value budget only: the simulation runs once, on the worker.
                check_monte_carlo_options(self.data, options)
            if self.method == INDEPENDENT_ROC:
                # Columns, numbers and the bootstrap budget stay in the dialog; the calculation runs on the worker.
                settings, _ = check_independent_roc(self.data, options)
                options = independent_roc_options(options, settings)
            if self.method == precision_recall.METHOD:
                # Check the worksheet and budget here. Bootstrap sampling stays on the worker.
                settings = precision_recall.check_options(self.data, options).settings
                if settings.bootstrap:
                    options[precision_recall.LEVEL] = settings.level
                    options[precision_recall.REPLICATES] = settings.replicates
                    options[precision_recall.SEED] = settings.seed
            if self.method == icc.METHOD:
                options = icc.normalized_options(options)
                icc.check_options(self.data, options)
            if self.method == CLUSTER_SILHOUETTE:
                # Roles, partition and budgets only: the distances run on the worker.
                check_silhouette_options(self.data, options)
            if self.method == POWER_METHOD:
                # Every active field is checked here and the recipe keeps canonical numbers whatever the language.
                options = power_options(options, check_power_options(options))
            if self.method == deming_dialog.METHOD:
                self._check_deming(options)
                saved = self.current[1] if self.current and self.current[0] == self.method else {}
                deming_dialog.prune_options(options, saved)
            name = None
            if self.method in CORRELATION_METHODS:
                # Budget and column checks stay in the dialog. Permutations run on the worker.
                validate_correlation_request(self.method, self.data, options)
            if self.method in regression_range.METHODS:
                ranges = regression_range.normalize(options)
                fit_data = regression_range.fitting_rows(self.data, options.get("X"), ranges)
            if self.method == "Linear regression":
                if options.get("Band", BAND_NONE) != BAND_NONE or linear_estimates_requested(options):
                    linear_confidence_level(options)
                check_linear_estimate_options(options)
            if self.method == "Nonlinear regression":
                if options.get(REPORT_LOG_IC50) is False:
                    options.pop(REPORT_LOG_IC50)
                if options.get(MERGE_REPLICATES):
                    replicate_groups(fit_data, options)
                else:
                    options.pop(MERGE_REPLICATES, None)
                # Level, choices and weighting limits name their field and keep the dialog open.
                check_band_options(options)
                check_parameter_ci(options)
                if options.get(PARAM_CI_METHOD) == PARAM_CI_PROFILE:
                    check_fit_quality_options(options)
                validate_profile_data(fit_data, options, classic_roles(self.method, options))
            forward_calibration = (self.method == "Interpolate a standard curve"
                                   and options.get(CALIBRATION_DIRECTION) == CALIBRATION_DIRECTIONS[1])
            if forward_calibration:
                forward_options(options)
            # Inverse intervals: a level or replicate count error stays in the dialog on its field.
            # The nonlinear search runs on the analysis worker. Only the linear inverse still fits here.
            inverse_intervals = (self.method == "Interpolate a standard curve" and not forward_calibration
                                 and options.get(CALIBRATION_UNCERTAINTY, "None") != "None")
            nonlinear_inverse = inverse_intervals and options.get("Curve") == "Nonlinear"
            if nonlinear_inverse:
                check_nonlinear_inverse(self.data, options)
            elif inverse_intervals:
                inverse_options(options)
            if self.method == "Interpolate a standard curve" and options.get("X") == options.get("Y"):
                raise FieldError("Y", "Select distinct columns for X and Y.")
            if self.method == "Interpolate a standard curve" and options.get("Curve") == "Nonlinear":
                calibration_choice_error(self.data, options.get("X"), options.get("Y"), "Nonlinear", options.get("Model"))
            if self.method == XY_METHOD:
                # Draw styles and the bar width stay on the saved recipe: check the graph they will draw.
                saved = self.current[1] if self.current and self.current[0] == self.method else {}
                check_xy_options(self.data, prune_options(
                    {**{key: saved[key] for key in XY_RECIPE_KEYS if key in saved}, **options}))
            if self.method == XY_ERRORS:
                saved = self.current[1] if self.current and self.current[0] == self.method else {}
                options = prune_xy_error_options(options, saved)
            if self.method == CUSTOM_EQUATION:
                # Syntax, names, limits and the domain at the starting values; the fit itself runs on the worker.
                check_custom_options(self.data, options)
                saved = self.current[1] if self.current and self.current[0] == self.method else {}
                if PARAM_CI_METHOD not in saved and options.get(PARAM_CI_METHOD) == PARAM_CI_WALD:
                    options.pop(PARAM_CI_METHOD, None)
                # Like the interval method: an Arithmetic recipe stays exactly the recipe of earlier versions.
                if CUSTOM_SYNTAX not in saved and options.get(CUSTOM_SYNTAX) == "Arithmetic":
                    options.pop(CUSTOM_SYNTAX, None)
            if self.method == COHEN_KAPPA:
                # Columns, categories, order, bootstrap fields and the size budgets; the bootstrap runs on the worker.
                check_kappa_options(self.data, options)
            if self.method == ROBUST_CURVE:
                # Columns, limits, the domain and the starting values; the fits run on the worker.
                check_robust_options(self.data, options)
            if self.method == COMPETING_RISKS:
                # Columns, codes, times, level and the size budgets; no curve is calculated here.
                check_competing_options(self.data, options)
            if self.method == RMCORR:
                # Columns, values, subjects, limits and the bootstrap budget; the resampling runs on the worker.
                check_rmcorr_options(self.data, options)
            if self.method == META_ANALYSIS:
                # Fields, cell values and the main fit; leave one out and the figure run on the worker.
                check_meta_options(self.data, options)
            if self.method == NB2:
                # Recipe, cells, budgets and the rank of the design; the fit itself runs on the worker.
                check_nb2_options(self.data, options)
            if self.method == WEIBULL_AFT:
                # Columns, codes, profiles, times, level and the size budgets; the fit itself runs on the worker.
                check_weibull_options(self.data, options)
            if self.method == ORDINAL_LOGIT:
                # Roles, order, profiles, rank and budgets; the model itself is fitted on the worker.
                check_ordinal_options(self.data, options)
            if self.method == RMST:
                # Columns, codes, groups, reference, horizon against the follow-up and the row budget.
                check_rmst_options(self.data, options)
            if self.method == GLOBAL_CUSTOM_EQUATION:
                if options.get("Weighting") != INVERSE_VARIANCE:
                    options[CUSTOM_SD] = None
                saved = self.current[1] if self.current and self.current[0] == self.method else {}
                for key, off in GLOBAL_RESPONSE_OFF.items():
                    if key not in saved and options.get(key, off) == off:
                        options.pop(key, None)
                # Syntax, sharing, series limits and the domain at the start; the fit itself runs on the worker.
                check_global_custom_options(self.data, options)
                if PARAM_CI_METHOD not in saved and options.get(PARAM_CI_METHOD) == PARAM_CI_WALD:
                    options.pop(PARAM_CI_METHOD, None)
                if CUSTOM_SYNTAX not in saved and options.get(CUSTOM_SYNTAX) == "Arithmetic":
                    options.pop(CUSTOM_SYNTAX, None)
            if self.select_editors:
                options.update({name: editor.values() for name, editor in self.select_editors.items()})
            grouped_validation = self.method == GROUPED_GRAPH and (
                options.get("Input") == SUMMARIES or options.get("Placement of groups") in STACKED_PLACEMENTS)
            dunn_validation = self.method in DUNN_METHODS and (
                options.get(DUNN) != "None" or options.get(P_VALUE_FIELDS[self.method]) == EXACT_P)
            # Poisson exposure and count errors name their field, so they stay in the dialog.
            poisson_validation = self.method == "Multiple regression" and options.get("Family") == "Poisson"
            linear_keys = (LINEAR_DIAGNOSTICS, LINEAR_RESIDUAL_PLOT, LINEAR_PROFILES, LINEAR_CI)
            weighted_linear = (self.method == "Multiple regression" and options.get("Family") == "Linear"
                               and mlr_weighting.weighted(options))
            if weighted_linear:
                weighted_data, _ = mlr_weighting.prepare(self.data, options)
                check_weighted_profiles(weighted_data, options)
            linear_validation = (self.method == "Multiple regression" and options.get("Family") == "Linear"
                                 and not weighted_linear and any(key in options for key in linear_keys))
            logistic_keys = (LOGISTIC_DIAGNOSTICS, LOGISTIC_CUTOFF, LOGISTIC_PROFILES, LOGISTIC_CI)
            check_logistic_diagnostics = (self.method == "Multiple regression" and options.get("Family") == "Logistic"
                                          and any(key in options for key in logistic_keys))
            pca_keys = (PCA_GRAPH, PCA_HORIZONTAL, PCA_VERTICAL, PCA_LABEL, PCA_SHOW_LABELS)
            pca_validation = self.method == "Principal component analysis" and any(key in options for key in pca_keys)
            if self.method == "Principal component analysis":
                # Field and budget errors stay in the dialog. Parallel replicates run on the worker.
                check_pca_selection(self.data, options)
                # The response, level and plot are checked here without any estimation, also for parallel
                # analysis. Rank and degrees of freedom are known only after the fit.
                pca_regression_settings(self.data, options)
                if pca_simulates(options):
                    validate_pca_graph(self.data, options)
                    pca_validation = False
            if self.method == PARTS_GRAPH:
                self._collect_pie_options(options)
            # A zero response under an observed-Y weighting names the Weighting field and stays in the dialog.
            observed_weighting = (self.method == "Nonlinear regression" and uses_observed_y(options.get("Weighting"))
                                  and options.get(PARAM_CI_METHOD) != PARAM_CI_PROFILE)
            fit_diagnostics = (self.method == "Nonlinear regression"
                               and (options.get(FIT_RUNS) or options.get(FIT_REPLICATES))
                               and options.get(PARAM_CI_METHOD) != PARAM_CI_PROFILE)
            if self.method == FDR_METHOD:
                # Columns, domains and budgets stay in the dialog. Adjustment and the figure run on the worker.
                validate_fdr_request(self.data, options)
            cox_exact_request = self.method == COX and cox_is_exact(options)
            if cox_exact_request:
                # The exact fit runs on the worker, where it can be cancelled and where its row, column and work limits
                # are checked. The dialog refuses only what the options alone decide: an output it does not build.
                check_cox_exact_outputs(options)
            if (observed_weighting or fit_diagnostics or grouped_validation or dunn_validation or poisson_validation
                    or linear_validation
                    or check_logistic_diagnostics or pca_validation or self.method in RANK_METHODS
                    or forward_calibration or (inverse_intervals and not nonlinear_inverse)
                    or self.method in PROCESSING_METHODS
                    or self.method in {PLOT_FUNCTION, TRANSPOSE_XY, POWER_METHOD}
                    or (self.method == curve_pipeline.CURVE_METHOD and options.get("Method") == curve_pipeline.PIPELINE)
                    or (self.method == deming_dialog.METHOD and deming_dialog.extended(options))
                    or self.method == PARTS_GRAPH or (self.method == COX and not cox_exact_request)
                    or (self.method == GOODNESS_OF_FIT and options.get(TEST_METHOD) == EXACT_BINOMIAL)
                    or self.method in {SELECT_TRANSFORM, EXTRACT_REARRANGE, GROUPED_ANOVA, GROUPED_DISTRIBUTIONS, BOX_VIOLIN, BUBBLE, "Bland–Altman", HEAT_MAP,
                                       BEFORE_AFTER, TRAJECTORIES, FOREST_PLOT, COMPARE_LINES, ANCOVA, LOGNORMAL, VARIANCE_RATIO, EQUIVALENCE, PAIRED_PROPORTIONS, TOLERANCE, OUTLIERS,
                                       "One-way ANOVA", REFERENCE_NORMALIZATION, rm_sphericity.METHOD,
                                       SPLINE_FIT, COMPARE_MODELS, XY_ERRORS}):
                # Keep field errors in the dialog and reuse the successful result.
                self.configure(cursor="watch")
                self.update_idletasks()
                try:
                    self.processing_result = analyse(self.method, self.data, options)
                finally:
                    self.configure(cursor="")
            if self.method == "Global nonlinear regression":
                # A zero response under 1/abs(Y) or 1/Y² names the Weighting field; the fit itself runs on the worker.
                check_global_weighting(self.data, options)
            if self.parameters is not None:
                options.update(self.parameters.values())
                self.series_parameters.set_labels(curve_series_labels(self.data, options))
                records = self.series_parameters.values()
                if records:
                    options["Series constraints"] = records
        except (ValueError, OverflowError) as error:
            field = getattr(error, "field", name)
            message = str(error)
            if self.method == CUSTOM_EQUATION:
                message = translate_custom_error(error)
                label = tr("custom.field." + field) if field else ""
                if field and label != "custom.field." + field:
                    message = f"{label}: {message}"
                elif field and field not in message:
                    message = f"{field}: {message}"
            elif self.method == GLOBAL_CUSTOM_EQUATION:
                message = translate_global_error(error)
                label = tr(GLOBAL_LABEL_KEYS[field]) if field in GLOBAL_LABEL_KEYS else ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
                elif field and field not in message:
                    message = f"{field}: {message}"
            elif self.method == "Multiple regression":
                message = translate_mlr_error(message)
                label = tr(MLR_LABEL_KEYS[field]) if field in MLR_LABEL_KEYS else field
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == "Principal component analysis" and (
                    field == PCA_COLOR_GROUPS or field in PCA_REGRESSION_LABELS or field == PCA_SELECTION):
                message = format_pca_error(error, field)
            elif self.method == MEAN_PERMUTATION:
                message = describe_permutation_error(error, field)
            elif self.method == HEAT_MAP:
                message = translate_heat_map_error(error)
                label = ui(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == COHEN_KAPPA:
                message = describe_kappa_error(error, field)
            elif self.method == ROBUST_CURVE:
                message = describe_robust_error(error, field)
            elif self.method == COMPETING_RISKS:
                message = describe_competing_error(error, field)
            elif self.method == curve_pipeline.CURVE_METHOD and self.controls["Method"][1].get() == curve_pipeline.PIPELINE:
                message = describe_curve_error(error, field)
            elif self.method == "Kaplan–Meier survival" and field in PAIRWISE_FIELDS:
                message = f"{ui(field)}: {ui(message)}"
            elif self.method == RMCORR:
                message = describe_rmcorr_error(error, field)
            elif self.method == META_ANALYSIS:
                message = describe_meta_error(error, field)
            elif self.method == COX and cox_is_exact(options):
                message = translate_cox_exact_error(error)
                label = ui(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == NB2:
                message = describe_nb2_error(error, field)
            elif self.method == WEIBULL_AFT:
                message = describe_weibull_error(error, field)
            elif self.method == ORDINAL_LOGIT:
                message = describe_ordinal_error(error, field)
            elif self.method == RMST:
                message = describe_rmst_error(error, field)
            elif self.method == EQUIVALENCE:
                message = translate_equivalence_error(error)
                label = tr(TOST_LABEL_KEYS[field]) if field in TOST_LABEL_KEYS else field
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == INDEPENDENT_ROC:
                message = translate_independent_roc_error(error)
                label = ui(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == precision_recall.METHOD:
                message = translate_precision_recall_error(error)
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == icc.METHOD:
                message = translate_icc_error(error)
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == WORKSHEET_JOIN:
                message = translate_join_error(error)
            elif self.method == reshape.METHOD:
                message = reshape_tk.format_error(error)
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == PAIRED_PROPORTIONS:
                message = translate_paired_error(error)
                label = tr(PAIRED_LABEL_KEYS[field]) if field in PAIRED_LABEL_KEYS else field
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == POWER_METHOD:
                message = translate_power_error(error)
                label = ui(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == TOLERANCE:
                message = translate_tolerance_error(error)
                label = tr(TOLERANCE_LABEL_KEYS[field]) if field in TOLERANCE_LABEL_KEYS else field
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == REFERENCE_NORMALIZATION:
                message = translate_reference_error(error)
                label = field_caption_for_reference(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == "Nonlinear regression" and (field in PARAM_CI_LABELS or message.startswith("Parameter profile")
                    or (options.get(PARAM_CI_METHOD) == PARAM_CI_PROFILE and field in {'Weighting', 'SD column'})):
                message = translate_message(message, "parameter_ci.error.")
                label = tr(PARAM_CI_LABELS[field]) if field in PARAM_CI_LABELS else ui(field)
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == GOODNESS_OF_FIT:
                message = ui(translate_message(message, "goodness.error."))
                label = ui(field) if field else ""
                if label and label.casefold() not in message.casefold():
                    message = f"{label}: {message}"
            elif self.method == CLUSTER_SILHOUETTE:
                message = translate_message(message, "silhouette.error.", convert={"field": ui})
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == kmeans_stability.METHOD:
                message = translate_kmeans_stability_error(error)
            elif self.method == logistic_validation.METHOD:
                message = translate_logistic_validation_error(error)
            elif self.method in (NORMALITY, SUMMARY_ANOVA, SUMMARY_TTEST, HIERARCHY_GRAPH,
                                 "Hierarchical clustering", *kmeans_options.METHODS):
                message = ui(message)
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method in CORRELATION_METHODS:
                message = translate_correlation_error(error)
                label = ui(field) if field else ""
                if field and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method == GROUPED_DISTRIBUTIONS:
                message = translate_grouped_error(error)
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == deming_dialog.METHOD:
                message = deming_dialog.format_error(error, field)
            elif self.method == "Interpolate a standard curve":
                message = translate_calibration_error(error)
            elif self.method == ANCOVA:
                # Sentences of the engine have catalog entries; a text typed in a number field is translated whole.
                message = format_ancova_error(error) or ui(message)
            elif self.method == XY_METHOD:
                message = translate_message(message, "xy.error.")
                label = ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == "Multifactor ANOVA" and (formatted := format_anova_error(error)):
                message = formatted
            elif self.method == "t-test":
                message = translate_message(message, "ttest.error.")
                label = tr(ttest_options.LABEL_KEYS[field]) if field in ttest_options.LABEL_KEYS else ui(field) if field else ""
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == LOGNORMAL and options.get(lognormal_tests.INPUT) == lognormal_tests.GROUPED:
                message = lognormal_tests.format_error(error)
                label = tr(RATIO_LABEL_KEYS[field]) if field in RATIO_LABEL_KEYS else field
                if label and label not in message:
                    message = f"{label}: {message}"
            elif self.method == rm_sphericity.METHOD and (formatted := format_rm_error(error)):
                message = formatted
            elif self.method == "One-way ANOVA" and (
                    formatted := lognormal_anova.format_error(error) or format_variance_error(error)):
                message = formatted
            elif self.method == FDR_METHOD and (formatted := format_fdr_error(error)):
                message = formatted
            elif self.method == VARIANCE_RATIO and (formatted := format_variance_ratio_error(error)):
                message = formatted
            elif self.method == COX:
                message = cox_message(error)
                label = ui(field) if field else ""
                if label and field not in message and label not in message:
                    message = f"{label}: {message}"
            elif self.method in regression_range.METHODS and field in regression_range.FIELDS:
                message = f"{ui(field)}: {ui(message)}"
            elif field and field not in message:
                message = f"{field}: {message}"
            messagebox.showerror(ui("Check parameters"), message, parent=self)
            if isinstance(error, worksheet_join_engine.JoinKeyError):
                self.focus_field(field, pair=error.pair)
            else:
                self.focus_field(field)
            return False
        if options.get(TTEST_ESTIMATION) is False:
            options.pop(TTEST_ESTIMATION)
        self.result = self.method, options
        return True


class PasteSpecialDialog(simpledialog.Dialog):
    """Choose the source rows to keep before pasting the clipboard snapshot."""

    def __init__(self, parent, rows, address):
        self.rows, self.address = rows, address
        super().__init__(parent, ui("Paste Special"))

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        body = ttk.Frame(master, padding=(10, 8, 10, 4))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr("interface.paste_into", address=self.address), style="DialogTitle.TLabel").pack(anchor="w")
        count, width = len(self.rows), len(self.rows[0])
        ttk.Label(body, text=tr("interface.clipboard_size", rows=f"{count:,}", columns=f"{width:,}")).pack(anchor="w", pady=(3, 10))
        fields = ttk.LabelFrame(body, text=ui("Filter rows"), padding=(10, 7))
        fields.pack(fill="x")
        self.bounds = []
        for row, (caption, value) in enumerate((("First row", 1), ("Last row", count), ("Rows to skip", 0))):
            ttk.Label(fields, text=ui(caption)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            entry = ttk.Entry(fields, width=11, justify="right")
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky="w", pady=3)
            self.bounds.append(entry)
        ttk.Label(body, text=ui("Keep the first selected row, then skip the specified number between rows."),
                  wraplength=320).pack(anchor="w", pady=(8, 0))
        return self.bounds[2]

    def buttonbox(self):
        row = ttk.Frame(self, padding=(15, 0, 15, 12))
        ttk.Button(row, text=ui("Paste"), style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(row, text=ui("Cancel"), command=self.cancel).pack(side="right")
        row.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        try:
            first, last, skip = (int(entry.get()) for entry in self.bounds)
        except ValueError:
            messagebox.showerror(ui("Check the row filter"), ui("Enter whole numbers for the row range and rows to skip."), parent=self)
            return False
        try:
            self.result = filter_clipboard_rows(self.rows, first=first, last=last, skip=skip)
        except ValueError as error:
            messagebox.showerror(ui("Check the row filter"), str(error), parent=self)
            return False
        return True


class LegacyPanelDialog(simpledialog.Dialog):
    def __init__(self, parent, panels, edits, prepare):
        self.panels, self.edits, self.prepare = panels, edits, prepare
        super().__init__(parent, ui("Edit imported layout panel"))

    def body(self, master):
        ttk.Label(master, text=ui("Panel")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.selector = ttk.Combobox(master, state="readonly", width=40,
                                    values=[f'{p["id"]} · {p["title"]}' for p in self.panels])
        self.selector.grid(row=0, column=1, sticky="ew")
        self.selector.current(0)
        self.selector.bind("<<ComboboxSelected>>", lambda _event: self.load_bounds())
        self.fields = []
        for row, title in enumerate(("Left", "Top", "Width", "Height"), 1):
            ttk.Label(master, text=ui(title)).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(master, width=12)
            entry.grid(row=row, column=1, sticky="w")
            self.fields.append(entry)
        ttk.Button(master, text=ui("Restore original position"), command=lambda: self.load_bounds(original=True)
                   ).grid(row=5, column=1, sticky="w", pady=(5, 0))
        ttk.Label(master, text=ui("Coordinates use the original layout units.\n"
                              "Apply one panel at a time."), justify="left").grid(row=6, columnspan=2, sticky="w", pady=6)
        self.load_bounds()
        return self.selector

    def load_bounds(self, *, original=False):
        panel = self.panels[self.selector.current()]
        bounds = panel["bounds"] if original else self.edits.get(panel["id"], panel["bounds"])
        left, top, right, bottom = bounds
        for entry, value in zip(self.fields, (left, top, right - left, bottom - top), strict=True):
            entry.delete(0, "end")
            entry.insert(0, str(value))

    def validate(self):
        panel = self.panels[self.selector.current()]
        try:
            left, top, width, height = (int(entry.get()) for entry in self.fields)
        except ValueError:
            messagebox.showerror(ui("Check panel"), ui("Enter whole numbers for the position and size."), parent=self)
            return False
        bounds = [left, top, left + width, top + height]
        edits = dict(self.edits)
        if bounds == panel["bounds"]:
            edits.pop(panel["id"], None)
        else:
            edits[panel["id"]] = bounds
        try:
            self.result = self.prepare(edits)
        except ValueError as error:
            messagebox.showerror(ui("Check panel"), str(error), parent=self)
            return False
        return True


class LayoutDialog(simpledialog.Dialog):
    def __init__(self, parent, runs, current=None):
        self.runs, self.current = runs, current
        by_reference = {run.reference: index for index, run in enumerate(runs)}
        self.order = [by_reference[ref] for ref in current.panels] if current else []
        counts, self.labels = {}, []
        for run in runs:
            counts[run.name] = counts.get(run.name, 0) + 1
            self.labels.append(run.name if counts[run.name] == 1 else f"{run.name} ({counts[run.name]})")
        super().__init__(parent, tr("layout.edit" if current else "layout.create"))

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        self.name = tk.StringVar(value=self.current.name if self.current else "Figure 1")
        self.columns = tk.StringVar(value=str(self.current.columns if self.current else 2))
        self.paper_names = {paper: tr(f"layout.paper.{paper}") for paper in PAPER_SIZES}
        self.paper = tk.StringVar(value=self.paper_names[self.current.paper if self.current else AUTO_PAPER])
        self.background = tk.StringVar(value=self.current.background if self.current else WHITE)
        page = ttk.LabelFrame(master, text=tr("layout.page"), padding=(9, 5))
        page.pack(fill="x")
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text=tr("layout.name")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        title = ttk.Entry(page, textvariable=self.name)
        title.grid(row=0, column=1, columnspan=3, sticky="ew")
        ttk.Label(page, text=tr("layout.paper")).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Combobox(page, textvariable=self.paper, values=tuple(self.paper_names.values()), state="readonly",
                     width=19).grid(row=1, column=1, sticky="w", pady=(5, 0))
        ttk.Label(page, text=tr("layout.columns")).grid(row=1, column=2, sticky="w", padx=(12, 6), pady=(5, 0))
        ttk.Combobox(page, textvariable=self.columns, values=(1, 2, 3, 4), state="readonly", width=4
                     ).grid(row=1, column=3, sticky="w", pady=(5, 0))
        ttk.Label(page, text=tr("layout.background")).grid(row=2, column=0, sticky="w", pady=(5, 0))
        color = ttk.Frame(page)
        color.grid(row=2, column=1, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Entry(color, textvariable=self.background, width=10).pack(side="left")
        swatch = tk.Label(color, width=2, relief="solid", borderwidth=1)
        swatch.pack(side="left", padx=(5, 0))

        def update_swatch(*_):
            try:
                swatch.configure(background=self.background.get())
            except tk.TclError:
                swatch.configure(background=WHITE)

        trace = self.background.trace_add("write", update_swatch)
        swatch.bind("<Destroy>", lambda _event: self.background.trace_remove("write", trace))
        update_swatch()
        ttk.Button(color, text=tr("layout.choose"), command=self.choose_background).pack(side="left", padx=(5, 0))

        panels = ttk.Frame(master)
        panels.pack(fill="both", expand=True, pady=(9, 0))
        panels.columnconfigure((0, 2), weight=1)
        available = ttk.LabelFrame(panels, text=tr("layout.available"), padding=5)
        available.grid(row=0, column=0, sticky="nsew")
        selected = ttk.LabelFrame(panels, text=tr("layout.panels"), padding=5)
        selected.grid(row=0, column=2, sticky="nsew")
        self.list = self.panel_listbox(available, "extended")
        self.list.insert("end", *self.labels)
        self.panel_list = self.panel_listbox(selected, "browse")
        commands = ttk.Frame(panels, padding=(5, 0))
        commands.grid(row=0, column=1)
        for label, command in (("layout.add", self.add_selected), ("layout.remove", self.remove_selected),
                               ("layout.up", lambda: self.move_selected(-1)),
                               ("layout.down", lambda: self.move_selected(1))):
            ttk.Button(commands, text=tr(label), command=command).pack(fill="x", pady=2)
        self.problem = ttk.Label(master, foreground="#b00020", wraplength=500)
        self.problem.pack(anchor="w", pady=(5, 0))
        self.list.bind("<Double-Button-1>", lambda _event: self.add_selected())
        self.panel_list.bind("<Delete>", lambda _event: self.remove_selected())
        self.panel_list.bind("<Alt-Up>", lambda _event: self.move_selected(-1))
        self.panel_list.bind("<Alt-Down>", lambda _event: self.move_selected(1))
        self.fill_panels()
        return title

    @staticmethod
    def panel_listbox(parent, selectmode):
        box = tk.Listbox(parent, width=29, height=9, selectmode=selectmode, exportselection=False)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=box.yview)
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=box.xview)
        box.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        box.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return box

    def buttonbox(self):
        row = ttk.Frame(self, padding=(6, 5))
        row.pack(fill="x")
        ttk.Button(row, text=tr("language.ok"), style="Action.TButton", command=self.ok).pack(side="right", padx=(6, 0))
        ttk.Button(row, text=tr("setup.cancel"), command=self.cancel).pack(side="right")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def choose_background(self):
        value = self.background.get()
        try:
            self.winfo_rgb(value)
        except tk.TclError:
            value = WHITE
        _, color = colorchooser.askcolor(value, parent=self)
        if color:
            self.background.set(color)

    def fill_panels(self, selection=None):
        self.panel_list.delete(0, "end")
        for i, graph in enumerate(self.order):
            self.panel_list.insert("end", f"{chr(ord('A') + i)} · {self.labels[graph]}")
        if selection is not None and self.order:
            selection = min(selection, len(self.order) - 1)
            self.panel_list.selection_set(selection)
            self.panel_list.activate(selection)
            self.panel_list.see(selection)
        self.problem.configure(text="")

    def add_selected(self):
        chosen = self.list.curselection()
        if len(self.order) + len(chosen) > 12:
            self.problem.configure(text=tr("layout.panel_limit"))
            return
        if chosen:
            self.order.extend(chosen)
            self.fill_panels(len(self.order) - 1)

    def remove_selected(self):
        chosen = self.panel_list.curselection()
        if chosen:
            index = chosen[0]
            del self.order[index]
            self.fill_panels(index)

    def move_selected(self, step):
        chosen = self.panel_list.curselection()
        if chosen:
            index = chosen[0]
            target = index + step
            if 0 <= target < len(self.order):
                self.order[index], self.order[target] = self.order[target], self.order[index]
                self.fill_panels(target)

    def validate(self):
        if not self.order:
            self.problem.configure(text=tr("layout.select"))
            self.list.focus_set()
            return False
        paper = next((key for key, label in self.paper_names.items() if label == self.paper.get()), "")
        try:
            self.result = Layout(self.name.get().strip(), int(self.columns.get()),
                                 [self.runs[i].reference for i in self.order], paper, self.background.get().strip())
            return True
        except ValueError as error:
            self.problem.configure(text=str(error))
            return False


class CalculationControl:
    """Progress and cancellation shared by a worker job and the UI thread. The worker never touches Tk."""

    def __init__(self):
        self.cancel = threading.Event()
        self._lock = threading.Lock()
        self._done = self._total = 0

    def report(self, done, total):
        with self._lock:
            self._done, self._total = max(self._done, done), total

    def progress(self):
        with self._lock:
            return self._done, self._total


@dataclass
class Run:
    method: str
    title: str
    options: dict
    result: Result | None = None
    slot: int = -1
    style: dict | None = None
    shape_history: ShapeHistory = field(default_factory=ShapeHistory, repr=False, compare=False)
    calculation_error: str | None = field(default=None, repr=False, compare=False)
    uid: str = field(default_factory=lambda: str(uuid4()), repr=False)
    source: ResultSource | None = None
    label: str | None = None

    @property
    def reference(self):
        return self.title, self.slot

    @property
    def name(self):
        source_title = self.source.table if self.source is not None else self.title
        return self.label or self.options.get(LEGACY_TITLE) or f"{self.method} of {source_title}"


def cox_exact_run(run):
    """True for a Cox recipe with exact conditional ties: its limits and fit errors are known on the worker."""
    return run.method == COX and cox_is_exact(run.options)


def uses_optimal_leaf_order(method, options):
    return method == "Hierarchical clustering" and options.get(LEAF_ORDERING) == OPTIMAL_LEAF_ORDER


def uses_hierarchy_diagnostics(method, options):
    return (uses_optimal_leaf_order(method, options) or uses_hierarchy_silhouette(method, options)
            or uses_hierarchy_gap(method, options))


def uses_planned_contrasts(method, options):
    return method == "Multifactor ANOVA" and planned_contrasts.active(options)


def cancellable_run(method, options):
    """Identify analyses that expose cancellation during calculation."""
    return (method in {MONTE_CARLO_METHOD, reshape.METHOD, WORKSHEET_JOIN,
                       kmeans_stability.METHOD, logistic_validation.METHOD}
            or extended_request(method, options)
            or competing_cancellable(method, options) or kappa_cancellable(method, options) or icc.cancellable(method, options)
            or permutation_cancellable(method, options) or independent_roc_cancellable(method, options)
            or rmcorr_cancellable(method, options) or meta_cancellable(method, options)
            or precision_recall.cancellable(method, options) or uses_hierarchy_diagnostics(method, options)
            or (method == COX and cox_is_exact(options)))


@dataclass
class AnalysisRecovery:
    """Where to reopen the dialog when the worker reports a field error for a candidate analysis.

    ``confirmed`` is the run being edited (None for a new analysis); the candidate never replaces it
    until a calculation succeeds.
    """
    project: object
    index: int | None
    confirmed: Run | None
    only: object = None


class App(AnalysisChainMixin, FamilyWorkflowMixin, WorksheetJoinSources):
    @staticmethod
    def make_chain_control():
        return CalculationControl()

    def chain_analysis_dialog(self, frame, *, title, source=None, **options):
        return AnalysisDialog(self.root, frame, join_left=title, join_sources=self.join_sources(title, source),
                              **options)

    def __init__(self, root, *, standard_only=False):
        self.root = root
        self.standard_only = standard_only
        self.root.title("Trama beta")
        width = max(820, min(1130, self.root.winfo_screenwidth() - 32))
        height = max(570, min(725, self.root.winfo_screenheight() - 125))
        self.root.geometry(f"{width}x{height}+12+12")
        self.root.minsize(820, 570)
        self.icon = tk.PhotoImage(master=root, file=ASSETS / "trama.png")
        root.iconphoto(True, self.icon)
        self.projects = {}
        self.active_project = None
        self.project_number = 1
        ProjectSession().install(self)
        self.nodes = {}
        self.show_navigator = True
        self.combined_navigator = True
        self.nav_filter_active = False
        self.gallery = None
        self.gallery_original = ()
        self.gallery_focus = None
        self.gallery_refresh = False
        self.gallery_sections = {}
        self.worksheet_history_buttons = {}
        self.pending = None
        self.calculation = None
        self.calculation_shown = None
        self.current_grid = None
        self.modern_workspace = None
        self.current_info = None
        self.layout_figure = None
        self.inspector = None
        self.inspector_wanted = False
        self.inspector_button = None
        self.inspector_reason = None
        self.inspector_element = None
        self.graph_canvas = None
        self.graph_toolbar = None
        self.shape_controller = None
        self.shape_popup = None
        self.shape_mode = tk.StringVar(root, value=tr("shape.button"))
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Trama")
        self.status = tk.StringVar(value=tr("status.welcome"))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_navigator())
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)

    @property
    def dirty(self):
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        self._dirty = value
        if self.active_project is not None:
            self.refresh_project_tabs()

    def _build(self):
        ui_theme.configure(self.root, "standard" if self.standard_only else load_theme(config_path()))
        if ui_theme.is_modern():
            self.combined_navigator = False

        menu = self.menu = tk.Menu(self.root)
        commands = {
            "File": [("New project", self.new_project), ("New table", self.new_table), ("Open…", self.open_dialog),
                     ("Import into project…", lambda: self.open_dialog(import_data=True)),
                     ("Save project", self.save), ("Save project as…", lambda: self.save(as_new=True)),
                     ("Export…", self.export), ("Export with options…", self.export_with_options),
                     ("Export multiple sheets to PDF…", self.export_pdf_bundle), ("Close project", self.close_project), ("Exit", self.close)],
            "Edit": [("Undo", self.apply_worksheet_history), ("Redo", lambda: self.apply_worksheet_history(redo=True)),
                     ("Cut cells", lambda: self.clear_selection(cut=True)), ("Copy cells", self.copy_selection),
                     ("Paste into table", self.paste_selection),
                     ("Paste Special…", lambda: self.paste_selection(special=True)),
                     ("Paste Transpose", lambda: self.paste_selection(transpose=True)),
                     ("Clear selected cells", self.clear_selection),
                     ("Paste as new table", self.paste_table),
                     ("Exclude / include selected cell", self.toggle_exclusion),
                     ("Language…", self.choose_language)],
            "View": [("Show or hide Navigator", self.toggle_navigator),
                     ("Show or hide Data + Results", self.toggle_combined_navigator),
                     ("Sheet gallery", self.toggle_gallery),
                     ("Previous sheet", lambda: self.step_history(-1)),
                     ("Next sheet", lambda: self.step_history(1))],
            "Insert": [("New table…", self.new_table), ("New Info sheet…", self.new_info), ("Add row", self.add_row),
                       ("Add column…", self.add_column), ("Calculated column…", self.add_formula),
                       ("New graph…", self.new_graph), ("Pairwise Comparisons…", self.pairwise_comparisons),
                       ("Compact Letter Display…", self.compact_letter_display),
                       ("Graph annotations…", self.edit_graph_annotations), ("Graph shapes…", self.edit_graph_shapes),
                       ("New layout…", self.new_layout)],
            "Analyze": [("Analyze data…", self.choose_analysis), ("Change parameters…", self.edit_analysis),
                        ("Analyze result table…", self.analyze_result_table),
                        ("Source analysis", self.source_analysis), ("Change input result…", self.change_input_result),
                        ("Load example", self.example)],
            "Change": [("Format graph…", self.format_graph), ("Edit layout…", lambda: self.new_layout(edit=True)),
                       ("Info sheet properties…", self.info_properties)],
            "Arrange": [("Arrange drawing objects…", self.arrange_graph_shapes), ("New layout…", self.new_layout),
                        ("Edit layout…", lambda: self.new_layout(edit=True))],
            "Family": [("Source data table", lambda: self.show_section("data")),
                       ("Family gallery", lambda: self.open_gallery("Family")),
                       ("Linked Info sheet", lambda: self.show_section("info")),
                       ("Analysis results", lambda: self.show_section("result")),
                       ("Graphs", lambda: self.show_section("graph")),
                       ("Duplicate family…", self.duplicate_family), ("Save family as…", self.save_family_as)],
            "Tools": [("Power and sample size…", self.power_planning),
                      ("Simulate data…", lambda: self.standalone("Simulate data")),
                      ("Monte Carlo study…", lambda: self.choose_analysis(only=(MONTE_CARLO_METHOD,))),
                      ("Transpose X and Y…", lambda: self.choose_analysis(only=(TRANSPOSE_XY,))),
                      ("Plot a function…", self.plot_function)],
        }
        edit_shortcuts = {"Undo": "Ctrl+Z", "Redo": "Ctrl+Y", "Cut cells": "Ctrl+X", "Copy cells": "Ctrl+C",
                          "Paste into table": "Ctrl+V", "Paste Special…": "Ctrl+Shift+V",
                          "Paste Transpose": "Ctrl+Shift+T", "Clear selected cells": "Delete"}
        file_shortcuts = {"New project": "Ctrl+Shift+N", "New table": "Ctrl+N", "Open…": "Ctrl+O",
                          "Save project": "Ctrl+S", "Close project": "Ctrl+W"}
        shortcuts = {"Edit": edit_shortcuts, "File": file_shortcuts}
        self.menu_entries = {}  # (English menu, English label) -> (popup, index): labels may be translated
        menus = {}
        for title, entries in commands.items():
            popup = tk.Menu(menu, tearoff=False)
            menus[title] = popup
            for label, command in entries:
                # The English label stays the dispatch key (shortcuts, tests); only the display is translated.
                popup.add_command(label=ui(label), command=command,
                                  accelerator=shortcuts.get(title, {}).get(label, ""))
                self.menu_entries[title, label] = popup, popup.index("end")
            if title == "Edit":
                self.edit_menu = popup
            menu.add_cascade(label=ui(title), menu=popup)
        settings = tk.Menu(menu, tearoff=False)
        if not self.standard_only:
            settings.add_command(label=tr("theme.command"), command=self.choose_theme)
            self.menu_entries["Settings", "Theme…"] = settings, settings.index("end")
        settings.add_command(label=ui("Language…"), command=self.choose_language)
        settings.add_command(label=tr("processes.command"), command=self.choose_processes)
        menu.add_cascade(label=tr("theme.settings"), menu=settings)
        menus["Settings"] = settings
        self.root.config(menu=menu)
        self.root.bind("<Control-n>", lambda _: self.new_table())
        self.root.bind("<Control-Shift-N>", lambda _: self.new_project())
        self.root.bind("<Control-w>", lambda _: self.close_project())
        self.root.bind("<Control-F4>", lambda _: self.close_project())
        self.root.bind("<Control-Tab>", lambda _: self.step_project(1))
        self.root.bind("<Control-Shift-Tab>", lambda _: self.step_project(-1))
        self.root.bind("<Control-ISO_Left_Tab>", lambda _: self.step_project(-1))
        self.root.bind("<Control-o>", lambda _: self.open_dialog())
        self.root.bind("<Control-s>", lambda _: self.save())
        self.root.bind("<Control-e>", lambda _: self.toggle_exclusion())
        self.root.bind("<Alt-Left>", lambda _: self.step_history(-1))
        self.root.bind("<Alt-Right>", lambda _: self.step_history(1))
        self.root.bind("<Control-Prior>", lambda _: self.step_history(-1))
        self.root.bind("<Control-Next>", lambda _: self.step_history(1))
        self.workspace_icons = workspace_icons(self.root)
        self.build_ribbon(menus)
        self.build_bottom_bar()
        self.project_tabs = ProjectTabs(self.root, self.switch_project, self.new_project, self.close_project)
        layout = ttk.Panedwindow(self.root, orient="horizontal")
        layout.pack(fill="both", expand=True)
        navigator = ttk.Frame(layout, width=ui_theme.px(232))
        self.workspace, self.navigator = layout, navigator
        layout.add(navigator, weight=0)
        if ui_theme.is_modern():
            ttk.Label(navigator, text=tr("theme.project"), style="ModernNav.TLabel").pack(fill="x", padx=12, pady=(14, 6))
        search_row = ttk.Frame(navigator, style="Ribbon.TFrame", padding=(6, 4))
        search_row.pack(fill="x")
        self.search_placeholder = True
        self.search_input = tk.StringVar(value=tr("nav.search"))
        self.search_input.trace_add("write", self.update_search)
        ttk.Label(search_row, image=self.workspace_icons["search"], style="Ribbon.TLabel").pack(side="left", padx=(0, 5))
        self.search_box = ttk.Entry(search_row, width=19, textvariable=self.search_input, style="NavSearch.TEntry")
        self.search_box.pack(side="left", fill="x", expand=True)
        self.search_box.bind("<FocusIn>", self.focus_search)
        self.search_box.bind("<FocusOut>", self.blur_search)
        self.search_box.bind("<Escape>", lambda _: self.clear_search())
        self.root.bind("<Control-f>", lambda _: self.search_box.focus_set() if self.selected else None)
        ttk.Separator(navigator).pack(fill="x")
        self.nav = ttk.Treeview(navigator, show="tree", selectmode="browse", height=14, style="Navigator.Treeview")
        self.nav.column("#0", width=ui_theme.px(225), minwidth=ui_theme.px(164))
        nav_scroll = ttk.Scrollbar(navigator, orient="vertical", command=self.nav.yview)
        nav_scroll.pack(side="right", fill="y")
        self.nav.configure(yscrollcommand=nav_scroll.set)
        self.nav.pack(side="left", fill="both", expand=True)
        self.nav.tag_configure("section", background=ui_theme.HEADING, foreground="#33454f", font=ui_theme.font(9, "bold"))
        self.nav.tag_configure("action", foreground=ui_theme.ACCENT_STRONG, font=ui_theme.font(9, slant="italic"))
        self.nav.tag_configure("current", font=ui_theme.font(9, "bold"))
        self.nav.tag_configure("linked", font=ui_theme.font(9, "bold"))
        self.nav_menu = tk.Menu(self.nav, tearoff=False)
        self.nav_menu.add_command(command=self.toggle_combined_navigator)
        self.nav_menu.add_separator()
        self.nav_menu.add_command(label=tr("nav.expand_all"), command=lambda: self.expand_navigator(True))
        self.nav_menu.add_command(label=tr("nav.collapse_all"), command=lambda: self.expand_navigator(False))
        self.nav_menu.add_separator()
        self.nav_menu_ref = None  # the sheet under the pointer when the menu opened; the selection is untouched
        self.nav_menu.add_command(label=ui("Duplicate family…"),
                                  command=lambda: self.duplicate_family(self.nav_menu_ref))
        self.nav_menu.add_command(label=ui("Save family as…"),
                                  command=lambda: self.save_family_as(self.nav_menu_ref))
        self.nav.bind("<<TreeviewSelect>>", self.navigate)
        self.nav.bind("<ButtonRelease-1>", self.activate_nav_action)
        self.nav.bind("<Return>", self.activate_nav_action)
        self.nav.bind("<Button-3>", self.navigator_menu)
        self.page = ttk.Frame(layout)
        layout.add(self.page, weight=1)
        self.nav_actions = {}
        self.active_project = self.project_tabs.add()
        self.projects[self.active_project] = ProjectSession()
        self.refresh_navigator()
        self.home()

    def ribbon_button(self, parent, label, icon, command, *, text=False, lead=False, primary=False):
        icons = self.workspace_icons
        image = (icons.white[icon], "disabled", icons.disabled[icon]) if primary else icons.state(icon)
        style = "Primary.Ribbon.TButton" if primary else "Lead.Ribbon.TButton" if lead else "Ribbon.TButton"
        button = ttk.Button(parent, text=ui(label), image=image, width=0,
                            compound="top" if lead else "left" if text else "image", style=style, command=command)
        show_hint(button, ui(label))
        return button

    def build_ribbon(self, menus):
        # (group, top row, bottom row[, lead row]); a lead button is the tall one, the rest are two rows of small ones.
        groups = (
            ("File", (("New", "new", self.new_table), ("Open", "open", self.open_dialog)),
             (("Save", "save", self.save), ("Save as…", "saveas", lambda: self.save(as_new=True)))),
            ("Sheet", (("Add row", "add-row", self.add_row), ("Add column…", "add-column", self.add_column),
                       ("New Info sheet…", "info", self.new_info)),
             (("Exclude / include cell", "exclude", self.toggle_exclusion), ("Formula…", "formula", self.add_formula))),
            ("Undo", (("Undo", "undo", self.apply_worksheet_history),),
             (("Redo", "redo", lambda: self.apply_worksheet_history(redo=True)),)),
            ("Clipboard", (("Cut cells", "cut", lambda: self.clear_selection(cut=True)),
                           ("Copy", "copy", self.copy_into_workspace)),
             (("Paste Special…", "paste-special", lambda: self.paste_selection(special=True)),
              ("Paste as new table", "pastetable", self.paste_table)),
             (("Paste", "paste", self.paste_into_workspace),)),
            ("Analysis", (("Linear regression", "linreg", lambda: self.choose_analysis("Linear regression")),
                          ("Nonlinear regression", "curve", lambda: self.choose_analysis("Nonlinear regression"))),
             (("Descriptive statistics", "bars", lambda: self.choose_analysis("Descriptive statistics")),
              ("Correlation matrix", "heatmap", lambda: self.choose_analysis(CORRELATION_MATRIX))),
             (("Analyze…", "analyze", self.choose_analysis),)),
            ("Change", (("Change parameters…", "format", self.edit_analysis), ("Format", "style", self.format_graph)),
             (("Add formula…", "formula", self.add_formula),)),
            ("Import / Export", (("Export", "export", self.export),),
             (("Export with options…", "export-options", self.export_with_options),),
             (("Import…", "import", lambda: self.open_dialog(import_data=True)),)),
            ("Graph", (("Layout", "layout", self.new_layout),), (("Pairwise Comparisons…", "pairwise", self.pairwise_comparisons),),
             (("New graph…", "graph", self.new_graph),)),
        )
        if ui_theme.is_modern():
            section_menus = {key: menus[title] for key, title in (
                ("file", "File"), ("home", "Edit"), ("insert", "Insert"), ("analyze", "Analyze"),
                ("graph", "Change"), ("arrange", "Arrange"), ("family", "Family"), ("tools", "Tools"),
                ("view", "View"), ("format", "Change"), ("annotations", "Insert"),
            )}
            extra_actions = {
                "Graph annotations…": ("annotation", self.edit_graph_annotations),
                "Graph shapes…": ("shapes", self.edit_graph_shapes),
                "Arrange drawing objects…": ("shapes", self.arrange_graph_shapes),
                "Inspector": ("inspector", self.toggle_inspector),
                "Family gallery": ("family", lambda: self.open_gallery("Family")),
                "Duplicate family…": ("copy", self.duplicate_family),
                "Save family as…": ("saveas", self.save_family_as),
                "Power and sample size…": ("bars", lambda: self.standalone("Power and sample size")),
                "Plot a function…": ("curve", self.plot_function),
                "Monte Carlo study…": ("analyze", lambda: self.choose_analysis(only=(MONTE_CARLO_METHOD,))),
                "Show or hide Navigator": ("navigator", self.toggle_navigator),
                "Sheet gallery": ("gallery", self.toggle_gallery),
                "Previous sheet": ("previous", lambda: self.step_history(-1)),
                "Next sheet": ("following", lambda: self.step_history(1)),
            }
            ribbon = ui_shell.ModernRibbon(self.root, groups, self.ribbon_button, ui, section_menus, extra_actions,
                                           command_menus=tuple(menus.values()),
                                           expanded=load_ribbon_expanded(config_path()),
                                           save_expanded=self.save_ribbon_expanded)
            self.root.bind("<Control-F1>", lambda _: ribbon.toggle_expanded() if ribbon.winfo_ismapped() else None)
            self.root.bind("<Control-k>", lambda _: ribbon.open_search() if ribbon.winfo_ismapped() else None)
        else:
            ribbon = ui_shell.Ribbon(self.root, groups, self.ribbon_button, ui)
        self.ribbon = ribbon
        for label in ("Undo", "Redo"):
            self.worksheet_history_buttons[label] = ribbon.buttons[label]
        # Wider labels (Italian) can need more than the default minimum for the icon-only ribbon.
        self.root.minsize(min(max(820, ribbon.minimum_width() + 4), self.root.winfo_screenwidth()), 570)

    def save_ribbon_expanded(self, expanded):
        try:
            save_ribbon_expanded(config_path(), expanded)
        except OSError as error:
            self.error(tr("language.error", error=error))

    def build_bottom_bar(self):
        bar = self.bottom_bar = ttk.Frame(self.root, style="Ribbon.TFrame", padding=(4, 2))
        ttk.Frame(bar, height=1, style="StatusRule.TFrame").pack(side="top", fill="x", pady=(0, 2))
        self.ribbon_button(bar, "Show or hide Navigator", "navigator", self.toggle_navigator).pack(side="left")
        self.ribbon_button(bar, "Sheet gallery", "gallery", self.toggle_gallery).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=4, pady=2)
        self.previous_sheet = self.ribbon_button(bar, "Previous sheet", "previous", lambda: self.step_history(-1))
        self.previous_sheet.pack(side="left")
        self.next_sheet = self.ribbon_button(bar, "Next sheet", "following", lambda: self.step_history(1))
        self.next_sheet.pack(side="left")
        self.family_button = self.ribbon_button(bar, "Linked sheets", "link", self.family_menu)
        self.family_button.pack(side="left")
        self.family_popup = tk.Menu(self.family_button, tearoff=False)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=4, pady=2)
        self.section_buttons = {}
        for kind, label in (("data", "Data tables"), ("info", "Info sheets"), ("result", "Results"),
                            ("graph", "Graphs"), ("layout", "Layouts")):
            button = self.ribbon_button(bar, label, kind, lambda item=kind: self.show_section(item))
            button.pack(side="left")
            self.section_buttons[kind] = button
        self.sheet_picker = ttk.Combobox(bar, state="readonly", width=23)
        self.sheet_picker.pack(side="left", padx=(5, 9))
        self.sheet_picker.bind("<<ComboboxSelected>>", self.pick_sheet)
        self.cell_address = ttk.Label(bar, style="Status.TLabel")
        self.cell_address.pack(side="left", padx=(0, 7))
        show_hint(self.cell_address, tr("bar.cell_hint"))
        self.cancel_button = ttk.Button(bar, text=tr("bar.cancel_calculation"), command=self.cancel_calculation)
        self.status_label = ttk.Label(bar, textvariable=self.status, style="Status.TLabel")
        self.status_label.pack(side="left", fill="x", expand=True)

    def begin_calculation(self, control):
        """Offer Cancel calculation while a cancellable job runs on the worker."""
        self.calculation, self.calculation_shown = control, None
        if control is not None:
            self.cancel_button.configure(state="normal")
            self.cancel_button.pack(side="right", padx=(6, 2), before=self.status_label)

    def end_calculation(self):
        self.calculation = self.calculation_shown = None
        self.cancel_button.pack_forget()

    def cancel_calculation(self):
        if self.calculation is not None and not self.calculation.cancel.is_set():
            self.calculation.cancel.set()
            self.cancel_button.configure(state="disabled")
            self.status.set(ui("Cancelling calculation…"))

    def show_calculation_progress(self, method):
        """Read the worker's counter; the status changes only when another block is done."""
        control = self.calculation
        if control is None or control.cancel.is_set():
            return
        done, total = control.progress()
        if total and (done, total) != self.calculation_shown:
            self.calculation_shown = done, total
            self.status.set(tr("interface.progress", method=ui(method), done=f"{done:,}", total=f"{total:,}"))

    def focus_search(self, _event):
        if self.search_placeholder:
            self.search_placeholder = False
            self.search_input.set("")

    def blur_search(self, _event):
        if not self.search.get():
            self.search_placeholder = True
            self.search_input.set(tr("nav.search"))

    def update_search(self, *_):
        value = "" if self.search_placeholder else self.search_input.get()
        if value != self.search.get():
            self.search.set(value)

    def clear_search(self):
        self.search_input.set("")
        return "break"

    def _clear(self, title, subtitle=""):
        if self.modern_workspace is not None:
            self.modern_workspace.dispose()
            self.modern_workspace = None
        if self.shape_popup is not None:
            self.shape_popup.destroy()
            self.shape_popup = None
        if self.shape_controller is not None:
            self.shape_controller.close()
            self.shape_controller = None
        self.shape_mode.set(tr("shape.button"))
        self.gallery = None
        self.gallery_original = ()
        self.gallery_focus = None
        self.gallery_refresh = False
        self.current_grid = None
        if self.current_info is not None:
            self.current_info.notes_changed()
            self.current_info = None
        self.layout_figure = None
        # The page is rebuilt: an unapplied Inspector draft never reaches the next graph.
        self.dispose_inspector()
        self.cell_address.configure(text="")
        for child in self.page.winfo_children():
            child.destroy()
        self.page.configure(padding=(10, 8) if title else 0)
        if not title:
            return
        ttk.Label(self.page, text=title, style="SheetTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(self.page, text=subtitle).pack(anchor="w", pady=(2, 8))

    def home(self):
        if str(self.navigator) in self.workspace.panes():
            self.workspace.forget(self.navigator)
        self.root.config(menu="")
        self.ribbon.pack_forget()
        self.bottom_bar.pack_forget()
        self._clear("")
        self.root.title("Trama beta")
        setup = TableSetup(self.page, create=self.create_worksheet, open_project=self.open_dialog,
                           create_info=self.new_info, brand=self.icon, version=f"{VERSION} {RELEASE_CHANNEL}")
        setup.pack(fill="both", expand=True)
        if not self.standard_only:
            ttk.Button(self.page, text=tr("theme.settings") + " · " + tr("theme.title"),
                       command=self.choose_theme).pack(anchor="e", padx=12, pady=6)
        self.refresh_project_tabs()

    def sheet_sections(self):
        return (
            ("Data Tables", [(title, ("data", title)) for title, dataset in self.tables.items()
                             if not stored_legacy_view(dataset)], "New Data Table…", self.new_table),
            ("Info", [(sheet.title, ("info", uid)) for uid, sheet in self.info_sheets.items()],
             "New Info Sheet…", self.new_info),
            ("Results", [(run.name, ("result", i)) for i, run in enumerate(self.runs)
                         if run_view(run.method) == "result"], "New Analysis…", self.choose_analysis),
            ("Graphs", [(run.name, ("graph", i)) for i, run in enumerate(self.runs)
                        if run.method in LEGACY_GRAPH_METHODS
                        or (run.method != SAVED_BINARY_LAYOUT and
                            (run.result.figure is not None if run.result
                             else run.method in GRAPH_METHODS or (run.method == NORMALITY and run.options.get(QQ_PLOT))
                             or (run.method == COMPARE_MODELS and run.options.get(MODELS_SHOW_GRAPH, True))
                             or (run.method == RMCORR and run.options.get(RMCORR_GRAPH, True))
                             or (run.method == META_ANALYSIS and run.options.get(META_SHOW_GRAPH, True))
                             or (run.method == POWER_METHOD and run.options.get(POWER_SHOW_CURVE))
                             or (run.method == TOLERANCE and run.options.get(TOLERANCE_SHOW_GRAPH))
                             or shows_paired_estimation(run.method, run.options)
                             or (run.method == MONTE_CARLO_METHOD
                                 and run.options.get(MONTE_CARLO_GRAPH, GRAPH_NONE) != GRAPH_NONE)
                             or (run.method == "Multifactor ANOVA"
                                 and run.options.get(ANOVA_DIAG_GRAPH) not in (None, "", "None"))
                             or (run.method == ORDINAL_LOGIT and run.options.get(ORDINAL_GRAPH))
                             or (run.method == FDR_METHOD and run.options.get(FDR_PLOT))
                             or (run.method == VARIANCE_RATIO and variance_ratio_shows_graph(run.options))
                             or (run.method == CLUSTER_SILHOUETTE and silhouette_graph(run.options))
                             or (run.method == PAIRED_PROPORTIONS and run.options.get(PAIRED_GRAPH) is True)))],
             "New Graph…", self.new_graph),
            ("Layouts", [(layout.name, ("layout", i)) for i, layout in enumerate(self.layouts)]
                        + [(run.name, ("saved-layout", i)) for i, run in enumerate(self.runs)
                           if run.method == SAVED_BINARY_LAYOUT], "New Layout…", self.new_layout),
        )

    def add_sheet_node(self, parent, name, ref, **options):
        icon = "layout" if ref[0] == "saved-layout" else ref[0]
        tags = ("current",) if ref == self.selected else ()
        node = self.nav.insert(parent, "end", text=name, image=self.workspace_icons[icon], tags=tags, **options)
        self.nodes[node] = ref
        return node

    def navigator_label(self, name, ref):
        if ref[0] not in RUN_VIEWS:
            return name
        run = self.runs[ref[1]]
        short = {"Global nonlinear regression": "Global fit",
                 "Mixed-effects model (REML)": "Mixed model"}.get(run.method)
        source_title = run.source.table if run.source is not None else run.title
        return f"{short} · {source_title}" if short and not (run.label or run.options.get(LEGACY_TITLE)) else name

    def navigator_section(self, name, needle):
        node = f"section:{name}"
        icon = {"Family": "family", "Search results": "search"}.get(name, "folder")
        expanded = bool(needle) or self.nav_expansion.get(node, name != "Search results")
        self.nav.insert("", "end", iid=node, text=ui(name), image=self.workspace_icons[icon],
                        open=expanded, tags=("section",))
        self.gallery_sections[node] = name
        return node

    def navigator_action(self, parent, label, action):
        node = self.nav.insert(parent, "end", text=ui(label), image=self.workspace_icons["plus"], tags=("action",))
        self.nav_actions[node] = action

    def remember_navigator_expansion(self):
        if not self.nav_filter_active:
            roots = self.nav.get_children()
            branches = self.nav.get_children("section:Data + Results") if self.nav.exists("section:Data + Results") else ()
            for node in (*roots, *branches):
                if node.startswith(("section:", "source:")):
                    self.nav_expansion[node] = self.nav.item(node, "open")

    def refresh_navigator(self):
        if not hasattr(self, "nav"):
            return
        self.sync_analysis_links()
        self.remember_navigator_expansion()
        self.nav.delete(*self.nav.get_children())
        self.nodes.clear()
        self.nav_actions.clear()
        self.gallery_sections.clear()
        needle = self.search.get().strip().casefold()
        self.nav_filter_active = bool(needle)

        def matches(name, ref):
            return needle in name.casefold() or needle in self.navigator_label(name, ref).casefold()

        sections = self.sheet_sections()
        if not ui_theme.is_modern():
            self.navigator_section("Family", "")
        search = self.navigator_section("Search results", needle) if needle or not ui_theme.is_modern() else None
        if needle:
            for _, entries, _, _ in sections:
                for name, ref in entries:
                    if matches(name, ref):
                        self.add_sheet_node(search, self.navigator_label(name, ref), ref)
        _, result_entries, result_label, result_action = next(section for section in sections if section[0] == "Results")
        for category, entries, label, action in sections:
            if self.combined_navigator and category == "Data Tables":
                parent = self.navigator_section("Data + Results", needle)
                if self._chain_node_ids:
                    self.populate_chain_results(parent, entries, result_entries, matches, source_ids=True)
                else:
                    results_by_source = {}
                    for name, ref in result_entries:
                        title = self.runs[ref[1]].title
                        results_by_source.setdefault(title, []).append((name, ref))
                    for title, ref in entries:
                        results = results_by_source.pop(title, ())
                        children = [(name, child) for name, child in results if matches(name, child)]
                        if not matches(title, ref) and not children:
                            continue
                        iid = f"source:{title}"
                        node = self.add_sheet_node(parent, title, ref, iid=iid,
                                                   open=bool(needle) or self.nav_expansion.get(iid, True))
                        for name, child in children:
                            self.add_sheet_node(node, self.navigator_label(name, child), child)
                    for results in results_by_source.values():
                        for name, ref in results:
                            if matches(name, ref):
                                self.add_sheet_node(parent, self.navigator_label(name, ref), ref)
                if not needle:
                    self.navigator_action(parent, label, action)
                    self.navigator_action(parent, result_label, result_action)
            parent = self.navigator_section(category, needle)
            for name, ref in entries:
                if matches(name, ref):
                    self.add_sheet_node(parent, self.navigator_label(name, ref), ref)
            if not needle and (not self.combined_navigator or category not in {"Data Tables", "Results"}):
                self.navigator_action(parent, label, action)
        self.refresh_family()
        self.select_current_nav(reveal=False)
        self.update_sheet_picker()
        self.update_worksheet_history_buttons()

    def set_combined_navigator(self, combined):
        if self.combined_navigator != combined:
            self.combined_navigator = combined
            self.refresh_navigator()

    def toggle_combined_navigator(self):
        self.set_combined_navigator(not self.combined_navigator)

    def update_nav_menu(self, row):
        """Prepare the context menu for the navigator row under the pointer (None: empty space)."""
        label = tr("nav.hide_data_results") if self.combined_navigator else tr("nav.show_data_results")
        self.nav_menu.entryconfigure(0, label=label)
        self.nav_menu_ref = self.nodes.get(row)
        state = ("normal" if self.nav_menu_ref is not None and self.family_ref(self.nav_menu_ref) is not None
                 else "disabled")
        for entry in (5, 6):
            self.nav_menu.entryconfigure(entry, state=state)

    def navigator_menu(self, event):
        self.update_nav_menu(self.nav.identify_row(event.y))
        try:
            self.nav_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.nav_menu.grab_release()

    def expand_navigator(self, expanded):
        roots = self.nav.get_children()
        for root in roots:
            for branch in self.nav.get_children(root):
                if self.nav.get_children(branch):
                    self.nav.item(branch, open=expanded)
            self.nav.item(root, open=expanded)

    def family_sheets(self):
        title = self.active_data
        if title not in self.tables:
            return []
        if getattr(self, '_chain_node_ids', ()):
            graph = self.analysis_graph()
            related = set(graph.affected([run.uid for run in self.runs if run.title == title]))
            by_id = {run.uid: run for run in self.runs}
            pending = list(related)
            while pending:
                source = by_id[pending.pop()].source
                if source is not None and source.analysis_id not in related:
                    related.add(source.analysis_id)
                    pending.append(source.analysis_id)
            titles = {title, *(by_id[key].title for key in related)}
            return [(name, ref) for _, entries, _, _ in self.sheet_sections() for name, ref in entries
                    if (ref[0] == 'data' and ref[1] in titles
                        or ref[0] == 'info' and self.info_sheets[ref[1]].table in titles
                        or ref[0] in RUN_VIEWS and self.runs[ref[1]].uid in related
                        or ref[0] == 'layout' and any(panel[0] in titles for panel in self.layouts[ref[1]].panels))]
        return [(name, ref) for _, entries, _, _ in self.sheet_sections() for name, ref in entries
                if (ref == ("data", title)
                    or (ref[0] == "info" and self.info_sheets[ref[1]].table == title)
                    or (ref[0] in RUN_VIEWS and self.runs[ref[1]].title == title)
                    or (ref[0] == "layout" and any(panel[0] == title for panel in self.layouts[ref[1]].panels)))]

    def refresh_family(self):
        parent = "section:Family"
        if not self.nav.exists(parent):
            return
        children = self.nav.get_children(parent)
        pending = list(children)
        while pending:
            node = pending.pop()
            pending.extend(self.nav.get_children(node))
            self.nodes.pop(node, None)
        self.nav.delete(*children)
        if self.search.get().strip():
            return
        if getattr(self, '_chain_node_ids', ()):
            entries = self.family_sheets()
            roots, results = self.populate_chain_results(
                parent, [(name, ref) for name, ref in entries if ref[0] == 'data'],
                [(name, ref) for name, ref in entries if ref[0] == 'result'], lambda *_: True)
            for name, ref in entries:
                if ref[0] in {'data', 'result'}:
                    continue
                if ref[0] in RUN_VIEWS:
                    run = self.runs[ref[1]]
                    owner = results.get(run.uid) if run.source is not None else roots.get(run.title)
                elif ref[0] == 'info':
                    owner = roots.get(self.info_sheets[ref[1]].table)
                else:
                    owner = None
                self.add_sheet_node(owner or parent, self.navigator_label(name, ref), ref)
            return
        for name, ref in self.family_sheets():
            if ref[0] == "data":
                parent = self.add_sheet_node(parent, name, ref, open=True)
            else:
                self.add_sheet_node(parent, self.navigator_label(name, ref), ref)

    def select_current_nav(self, *, reveal=True):
        related = {ref for _, ref in self.family_sheets()}
        self.family_button.state(["!disabled" if related else "disabled"])
        selected_node = None
        for node, ref in self.nodes.items():
            self.nav.item(node, tags=("current",) if ref == self.selected else ("linked",) if ref in related else ())
            if selected_node is None and ref == self.selected:
                selected_node = node
        if selected_node is not None:
            self.nav.selection_set(selected_node)
            if reveal:
                self.nav.see(selected_node)
        else:
            self.nav.selection_remove(*self.nav.selection())

    def family_menu(self):
        menu = self.family_popup
        menu.delete(0, "end")
        entries = self.family_sheets()
        for name, ref in entries[:24]:
            icon = self.workspace_icons[self.section_kind(ref[0])]
            menu.add_command(label=name, image=icon, compound="left", command=lambda item=ref: self.open_sheet(item))
        if entries:
            menu.add_separator()
        menu.add_command(label=tr("bar.view_family_gallery"), command=lambda: self.open_gallery("Family"))
        menu.add_separator()
        menu.add_command(label=ui("Duplicate family…"), command=self.duplicate_family)
        menu.add_command(label=ui("Save family as…"), command=self.save_family_as)
        try:
            menu.tk_popup(self.family_button.winfo_rootx(), self.family_button.winfo_rooty())
        finally:
            menu.grab_release()

    def toggle_navigator(self):
        if self.selected is not None:
            self.show_navigator = not self.show_navigator
            self.update_navigator_visibility()

    def update_navigator_visibility(self):
        mapped = str(self.navigator) in self.workspace.panes()
        if self.show_navigator and not mapped:
            self.workspace.insert(0, self.navigator, weight=0)
        elif mapped and not self.show_navigator:
            self.workspace.forget(self.navigator)

    @staticmethod
    def section_kind(kind):
        return "layout" if kind == "saved-layout" else kind

    def section_sheets(self, kind):
        return [(name, ref) for _, entries, _, _ in self.sheet_sections()
                for name, ref in entries if self.section_kind(ref[0]) == kind]

    def update_sheet_picker(self):
        self.previous_sheet.state(["!disabled" if self.history_position > 0 else "disabled"])
        self.next_sheet.state(["!disabled" if self.history_position + 1 < len(self.history) else "disabled"])
        active = self.section_kind(self.selected[0]) if self.selected else None
        for kind, button in self.section_buttons.items():
            button.configure(style="SectionActive.TButton" if kind == active else "Ribbon.TButton")
        if active is None:
            self.sheet_picker.configure(values=())
            self.sheet_picker.set("")
            return
        choices = self.section_sheets(active)
        self.sheet_picker.configure(values=[name for name, _ in choices])
        for index, (_, ref) in enumerate(choices):
            if ref == self.selected:
                self.sheet_picker.current(index)
                break

    def pick_sheet(self, _event):
        index = self.sheet_picker.current()
        if self.selected is not None and index >= 0:
            _, ref = self.section_sheets(self.section_kind(self.selected[0]))[index]
            self.open_sheet(ref)

    def show_section(self, kind):
        choices = self.section_sheets(kind)
        if choices:
            if kind == "info":
                linked = [ref for _, ref in choices if self.info_sheets[ref[1]].table == self.active_data]
                target = linked[0] if linked else choices[0][1]
            else:
                target = next((ref for _, ref in choices if kind == "data" and ref[1] == self.active_data), choices[0][1])
            self.open_sheet(target)

    def toggle_gallery(self):
        if self.selected is None:
            return
        if self.gallery is not None:
            if self.gallery_refresh:
                self.show(*self.selected, record_history=False)
                return
            self.gallery.destroy()
            self.gallery = None
            for child, options in self.gallery_original:
                child.pack(**options)
            self.gallery_original = ()
            if self.gallery_focus is not None and self.gallery_focus.winfo_exists():
                self.gallery_focus.focus_set()
            self.gallery_focus = None
            return
        category = {"data": "Data Tables", "info": "Info", "result": "Results", "graph": "Graphs",
                    "layout": "Layouts", "saved-layout": "Layouts"}[self.selected[0]]
        self.open_gallery(category)

    def open_gallery(self, category):
        if self.selected is None:
            return
        sections = {name: entries for name, entries, _, _ in self.sheet_sections()}
        if category == "Family":
            entries = self.family_sheets()
        elif category == "Data + Results":
            entries = sections["Data Tables"] + sections["Results"]
        elif category == "Search results":
            entries = [(self.nav.item(node, "text"), self.nodes[node])
                       for node in self.nav.get_children("section:Search results") if node in self.nodes]
        else:
            entries = sections[category]
        gallery = SheetGallery(self.page, category, entries, self.gallery_thumbnail, self.open_sheet, self.toggle_gallery)
        if self.gallery is not None:
            self.gallery.destroy()
        else:
            self.gallery_focus = self.root.focus_get()
            self.gallery_original = tuple((child, child.pack_info()) for child in self.page.pack_slaves())
            for child, _ in self.gallery_original:
                child.pack_forget()
        self.gallery = gallery
        self.gallery.pack(fill="both", expand=True)
        self.gallery.focus_first()

    def gallery_thumbnail(self, ref):
        kind, index = ref
        if kind == "data":
            return table_thumbnail(self.tables[index].raw, display)
        if kind == "info":
            return table_thumbnail(pd.DataFrame(self.info_sheets[index].fields, columns=["Constant", "Value"]), display)
        if kind == "layout" and self.selected == ref and self.layout_figure is not None:
            return figure_thumbnail(self.layout_figure)
        if kind in RUN_VIEWS:
            run = self.runs[index]
            result = run.result
            if result is not None:
                if kind == "result" and result.tables:
                    return table_thumbnail(next(iter(result.tables.values())), display, index=True)
                if result.figure is not None:
                    return figure_thumbnail(result.figure)
            preview = run.options.get(LEGACY_PREVIEW)
            if preview is not None and sys.platform == "win32" and run.method in {SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT}:
                layout = run.method == SAVED_BINARY_LAYOUT
                if layout:
                    preview = edited_layout_preview(preview, run.options.get(LEGACY_EDITABLE_PANELS),
                                                    run.options.get(LEGACY_PANEL_EDITS), self.layout_panel_data(run))
                drawing = render_binary_graph(preview, layout=layout, crop=not layout, max_side=448)
                return image_thumbnail(drawing)
        return None

    def step_history(self, delta):
        index = self.history_position + delta
        if 0 <= index < len(self.history):
            self.history_position = index
            self.open_sheet(self.history[index], record_history=False)
        return "break"

    def activate_nav_action(self, event):
        if event.type == tk.EventType.ButtonRelease:
            node = self.nav.identify_row(event.y)
            if self.nav.identify_element(event.x, event.y).endswith("indicator"):
                return
        else:
            node = self.nav.focus()
        if action := self.nav_actions.get(node):
            action()
            return "break"
        if category := self.gallery_sections.get(node):
            self.open_gallery(category)
            return "break"
        if self.gallery is not None and self.nodes.get(node) == self.selected:
            self.toggle_gallery()
            return "break"

    def navigate(self, _=None):
        selection = self.nav.selection()
        ref = self.nodes.get(selection[0]) if selection else None
        if ref and ref != self.selected:
            self.open_sheet(ref)

    def open_sheet(self, ref, *, record_history=True):
        if ref == self.selected:
            if self.gallery is not None:
                self.toggle_gallery()
            return
        self.show(*ref, record_history=record_history)
        kind, index = ref
        if self.pending is None and kind in RUN_VIEWS and self.runs[index].result is None:
            self.recalculate(index)
        elif self.pending is None and kind == "layout":
            panels = self.layout_runs(self.layouts[index])
            if (any(run.result is None for run in panels)
                    and any(run.uid in getattr(self, '_chain_node_ids', ()) for run in panels)):
                self.recalculate_layout(index)

    def show(self, kind, key, *, record_history=True):
        if not self.ribbon.winfo_manager():
            self.root.config(menu=self.menu)
            first = (self.project_tabs if not ui_theme.is_modern() and self.project_tabs.winfo_manager()
                     else self.workspace)
            self.ribbon.pack(fill="x", before=first)
            self.bottom_bar.pack(fill="x", side="bottom", before=self.workspace)
        if ui_theme.is_modern():
            self.ribbon.set_graph_context(kind == "graph")
        self.update_navigator_visibility()
        if record_history and self.selected != (kind, key):
            self.history = [*self.history[:self.history_position + 1], (kind, key)][-200:]
            self.history_position = len(self.history) - 1
        self.selected = kind, key
        self.refresh_project_tabs()
        if kind == "data":
            self.active_data = key
            dataset = self.tables[key]
            frame = dataset.frame()
            self._clear(key if ui_theme.is_modern() else "")
            if ui_theme.is_modern():
                row = ttk.Frame(self.page, padding=(0, 7, 0, 9))
                row.pack(fill="x")
                ttk.Label(row, text=ui("Data tables"), foreground=ui_theme.ACCENT,
                          font=ui_theme.font(10, "bold")).pack(side="left", padx=(0, 20))
                linked = [(i, run) for i, run in enumerate(self.runs) if run.title == key]
                for target, caption in (("result", "Results"), ("graph", "Graphs")):
                    choices = [(i, run) for i, run in linked
                               if target == "result" or run.result is not None and run.result.figure is not None]
                    button = ttk.Button(row, text=ui(caption),
                        command=lambda target=target, choices=choices: self.open_sheet((target, choices[-1][0])))
                    button.pack(side="left", padx=(0, 10))
                    if not choices:
                        button.state(["disabled"])
            self.root.title(f"{key} — {self.path.name if self.path else 'Trama beta'}")
            grid_parent = self.page
            if ui_theme.is_modern():
                self.modern_workspace = ModernWorksheet(self.page, self, key)
                self.modern_workspace.pack(fill="both", expand=True)
                grid_parent = self.modern_workspace.grid_host
            locks = set(dataset.locked_columns)
            sources = dataset.source_indices
            self.current_grid = DataGrid(grid_parent, frame, self.edit_cell, self.copy_selection, self.paste_selection,
                                         display, excluded=dataset.worksheet_excluded,
                                         source_columns=len(dataset.raw.columns),
                                         table_format=dataset.table_format,
                                         address_widget=self.cell_address,
                                         read_only_columns=[column for column, source in enumerate(sources)
                                                            if source in locks],
                                         calculated_columns=[column for column, source in enumerate(sources)
                                                             if source is None])
            self.current_grid.pack(fill="both", expand=True)
            canvas = self.current_grid.canvas
            if dataset.table_format == "multivariable":
                canvas.bind("<KeyPress-equal>", self.enter_worksheet_formula)
                self.calculated_column_popup = tk.Menu(canvas, tearoff=False)
                self.calculated_column_popup.add_command(label=tr("worksheet.formula.freeze"))
                canvas.bind("<Button-3>", self.calculated_column_menu)
            for sequence, command in (
                ("<Control-z>", self.apply_worksheet_history),
                ("<Control-y>", lambda: self.apply_worksheet_history(redo=True)),
                ("<Control-x>", lambda: self.clear_selection(cut=True)),
                ("<Control-Shift-T>", lambda: self.paste_selection(transpose=True)),
                ("<Control-Shift-V>", lambda: self.paste_selection(special=True)),
                ("<Delete>", self.clear_selection),
                ("<BackSpace>", self.clear_selection),
            ):
                canvas.bind(sequence, lambda _event, action=command: action())
        elif kind == "info":
            sheet = self.info_sheets[key]
            self.active_data = sheet.table
            self._clear(sheet.title, tr("interface.linked_to", table=sheet.table) if sheet.table else ui("Project Info"))
            self.current_info = InfoEditor(
                self.page, sheet, self.change_info, self.error, self.info_properties, self.remove_info,
                self.move_info, self.cell_address,
            )
            self.current_info.pack(fill="both", expand=True)
        elif kind == "layout":
            layout = self.layouts[key]
            self._clear(layout.name, tr("interface.layout_panels", count=len(layout.panels)))
            bar = ttk.Frame(self.page)
            bar.pack(fill="x", pady=(0, 5))
            ttk.Button(bar, text=tr("command.edit_layout"), command=lambda: self.new_layout(edit=True)).pack(side="left")
            graphs = self.layout_runs(layout)
            if all(run.result and run.result.figure for run in graphs):
                self.layout_figure = self.layout_rendering(layout)
                self.show_figure(self.layout_figure, fit_page=True)
            else:
                ttk.Button(bar, text=ui("Recalculate panels"), command=lambda: self.recalculate_layout(key)
                           ).pack(side="left", padx=(6, 0))
        else:
            run = self.runs[key]
            self.active_data = run.title
            result = run.result
            subtitle = run.options.get(LEGACY_NOTES) or ui("Analysis results" if kind == "result" else "Graph")
            self._clear(run.name, subtitle)
            if run.source is not None:
                source_bar = ttk.Frame(self.page)
                source_bar.pack(fill="x", pady=(0, 5))
                ttk.Button(source_bar, text=tr("chain.source_analysis"), command=self.source_analysis).grid(row=0, column=0, sticky="w")
                ttk.Button(source_bar, text=tr("chain.change_input"), command=self.change_input_result).grid(row=0, column=1, sticky="w", padx=6)
                source = next((other for other in self.runs if other.uid == run.source.analysis_id), None)
                name = source.name if source is not None else tr("chain.missing_source")
                ttk.Label(source_bar, text=tr("chain.input_label", analysis=name, table=run.source.table),
                          wraplength=630).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
            if result is None:
                if run.method in {SAVED_BINARY_GRAPH, SAVED_BINARY_RESULT, SAVED_BINARY_LAYOUT, SAVED_EDITABLE_GRAPH}:
                    label = "Open saved view"
                else:
                    ttk.Label(self.page, text=ui("Calculate this analysis using the current data.")).pack(anchor="w")
                    label = "Recalculate"
                ttk.Button(self.page, text=ui(label), command=lambda: self.recalculate(key)).pack(anchor="w", pady=8)
            elif kind == "result":
                bar = ttk.Frame(self.page)
                bar.pack(fill="x", pady=(0, 7))
                if run.method != SAVED_BINARY_RESULT:
                    ttk.Button(bar, text=ui("Change Parameters…"), command=self.edit_analysis).pack(side="left")
                ttk.Button(bar, text=ui("Use Result as Data"), command=self.use_result_as_data).pack(side="left", padx=6)
                chain_bar = ttk.Frame(self.page)
                chain_bar.pack(fill="x", pady=(0, 7))
                ttk.Button(chain_bar, text=tr("chain.analyze_result"), command=self.analyze_result_table).pack(side="left")
                if run.source is None:
                    ttk.Button(chain_bar, text=tr("chain.change_input"), command=self.change_input_result).pack(side="left", padx=6)
                self.result_tabs = ttk.Notebook(self.page)
                self.result_tabs.pack(fill="both", expand=True)
                for title, frame in result.tables.items():
                    threshold_column = "Threshold" if run.method == "ROC curve" and title == "Diagnostic thresholds" else None
                    grid = Grid(self.result_tabs, frame, fit_cells=run.method == SAVED_BINARY_RESULT,
                                threshold_column=threshold_column)
                    self.result_tabs.add(grid, text=title)
            elif kind == "saved-layout":
                bar = ttk.Frame(self.page)
                bar.pack(fill="x", pady=(0, 5))
                if run.options.get(LEGACY_EDITABLE_PANELS):
                    ttk.Button(bar, text=ui("Edit panel…"), command=lambda: self.edit_legacy_panel(key)).pack(side="left")
                self.layout_panel_actions(run, bar)
                if ZIP_LAYOUT not in run.options and (run.options.get(LEGACY_PANEL_EDITS)
                                                      or run.options.get(LEGACY_PANEL_DATA)):
                    ttk.Button(bar, text=tr("layout.export_current_emf"),
                               command=lambda: self.export_current_layout_emf(key)).pack(side="left", padx=(8, 0))
                    ttk.Label(self.page, text=tr("layout.export_original_emf")).pack(anchor="w", pady=(0, 5))
                self.show_figure(result.figure, export=self.export if imported_paper(run) is not None else None)
            else:
                bar = ttk.Frame(self.page)
                bar.pack(fill="x", pady=(0, 5))
                if run.method in LEGACY_GRAPH_METHODS:
                    self.graph_view_actions(run, bar)
                else:
                    shortcut = {"Kaplan–Meier survival": ("Graph settings…", SURVIVAL_CURVE),
                                "Scatter / confidence ellipse": ("Confidence overlays…", "Ellipse"),
                                HEAT_MAP: ("Graph settings…", self.heat_map_settings_field(run)),
                                COHEN_KAPPA: ("Graph settings…", KAPPA_SHOW_GRAPH),
                                ROBUST_CURVE: ("Graph settings…", ROBUST_DISPLAY),
                                COMPETING_RISKS: ("Graph settings…", COMPETING_GRAPH),
                                WEIBULL_AFT: ("Graph settings…", WEIBULL_SHOW_GRAPH),
                                RMST: ("Graph settings…", RMST_SHOW_GRAPH)}.get(run.method)
                    if shortcut is None and (run.method in CATEGORY_GRAPHS or run.method == PARTS_GRAPH):
                        shortcut = "Graph settings…", "Graph style"
                    if shortcut:
                        ttk.Button(bar, text=ui(shortcut[0]), command=lambda field=shortcut[1]: self.edit_analysis(
                            initial_field=field)).pack(side="left", padx=(0, 6))
                if run.method not in LEGACY_GRAPH_METHODS and panel_axes(result.figure):
                    ttk.Button(bar, text=tr("qq.panels.button"), command=self.edit_qq_panels
                               ).pack(side="left", padx=(0, 6))
                if run.method not in LEGACY_GRAPH_METHODS and pairwise_graph_problem(run.method, run.options) is None:
                    ttk.Button(bar, text=ui("Pairwise comparisons…"), command=self.pairwise_comparisons
                               ).pack(side="left", padx=(0, 6))
                if run.method not in LEGACY_GRAPH_METHODS:
                    ttk.Button(bar, text=tr("annotation.button"), command=self.edit_graph_annotations
                               ).pack(side="left", padx=(0, 6))
                    draw = ttk.Menubutton(bar, textvariable=self.shape_mode)
                    drawing_menu = tk.Menu(draw, tearoff=False)
                    drawing_menu.add_command(label=tr("shape.canvas.manage"), command=self.edit_graph_shapes)
                    drawing_menu.add_command(label=tr("command.arrange_shapes"), command=self.arrange_graph_shapes)
                    drawing_menu.add_separator()
                    for mode in ("select", "line", "arrow", "rectangle", "ellipse"):
                        drawing_menu.add_command(label=tr("shape.canvas." + mode),
                                                 command=lambda mode=mode: self.start_shape_mode(mode))
                    drawing_menu.add_separator()
                    for action in ("cut", "copy", "paste"):
                        drawing_menu.add_command(label=tr("shape.clipboard." + action),
                            command=lambda action=action: self.shape_clipboard_action(action))
                    drawing_menu.add_separator()
                    drawing_menu.add_command(label=tr("shape.canvas.stop"), command=lambda: self.start_shape_mode(None))
                    draw.configure(menu=drawing_menu)
                    draw.pack(side="left", padx=(0, 6))
                from analisi.hierarchical_style import describe_hierarchical_artists

                if run.method not in LEGACY_GRAPH_METHODS and describe_hierarchical_artists(result.figure):
                    self.hierarchical_style_button = ttk.Button(
                        bar, text=tr("hierarchy.style.button"), command=self.edit_hierarchical_style)
                    self.hierarchical_style_button.pack(side="left", padx=(0, 6))
                self.inspector_button = ttk.Button(bar, text=tr("graph.inspector.title"), command=self.toggle_inspector)
                self.inspector_button.pack(side="left")
                self.inspector_reason = ttk.Label(bar, foreground="#506575")
                self.inspector_reason.pack(side="left", padx=8)
                if warning := pairwise_warning(result.figure):
                    ttk.Label(self.page, text=warning, foreground="#8a4b0f", wraplength=760
                              ).pack(anchor="w", pady=(0, 4))
                self.show_figure(result.figure, run)
                self.refresh_inspector_button()
        if kind != "data":
            if note := self.stale_calculation_note((kind, key)):
                children = self.page.winfo_children()
                ttk.Label(self.page, text=note, foreground="#8a4b0f", wraplength=760).pack(
                    fill="x", pady=(0, 6), **({"before": children[0]} if children else {}))
            title = sheet.title if kind == "info" else self.layouts[key].name if kind == "layout" else self.runs[key].name
            self.root.title(f"{title} — Trama beta")
        self.refresh_family()
        self.select_current_nav()
        self.update_sheet_picker()
        self.update_worksheet_history_buttons()

    @staticmethod
    def heat_map_settings_field(run):
        """Graph settings opens on the colors of the map: the category table for categories, else the mapping."""
        categories = run.options.get("Input format") == "Long categories"
        return HEAT_MAP_CATEGORY_COLORS if categories else HEAT_MAP_MAPPING

    def graph_view_actions(self, run, bar):
        from analisi.legacy_binary_range import BINARY_XY_RANGE

        if run.method == SAVED_XY and BINARY_XY_RANGE in run.options:
            ttk.Button(bar, text=ui("Edit graph data"), command=lambda: self.show("data", run.title)).pack(
                side="left", padx=5)
            return
        link = run.options.get(LEGACY_GRAPH_LINK)
        if not link:
            return
        editable = run.method == SAVED_EDITABLE_GRAPH
        target = SAVED_BINARY_GRAPH if editable else SAVED_EDITABLE_GRAPH
        related = next((i for i, other in enumerate(self.runs)
                        if other.method == target and other.options.get(LEGACY_GRAPH_LINK) == link), None)
        if related is None and not editable:
            return
        if related is not None:
            ttk.Button(bar, text=ui("View original" if editable else "Open editable graph"),
                       command=lambda: self.open_graph_view(related)).pack(side="left")
        if editable:
            ttk.Button(bar, text=ui("Edit graph data"), command=lambda: self.show("data", run.title)).pack(side="left", padx=5)
            if self.tables[run.title].table_format not in EDITABLE_LEGACY_FIXED_VALUES and LEGACY_PREVIEW not in run.options:
                ttk.Button(bar, text=ui("Format…"), command=self.format_graph).pack(side="left", padx=(0, 6))

    def layout_panel_graphs(self, run):
        return resolve_layout_panel_graphs(run, self.runs, self.tables)

    def layout_panel_data(self, run):
        if not isinstance(run.options.get(LEGACY_PANEL_DATA), dict):
            return None
        return {panel: (self.tables[graph.title].frame(mask_excluded=True),
                        panel_source_style(graph.method, graph.options))
                for panel, graph in self.layout_panel_graphs(run).items()}

    def layout_panel_actions(self, run, bar):
        entries = layout_panel_sources(run, self.layout_panel_graphs(run))
        if not entries:
            return
        choice = ttk.Combobox(bar, state="readonly", width=32,
                              values=[caption for caption, _ in entries])
        choice.current(0)
        choice.pack(side="left", padx=(8, 4))
        ttk.Button(bar, text=ui("Edit panel data…"), command=lambda: self.open_sheet(
            ("data", entries[choice.current()][1]))).pack(side="left")

    def open_graph_view(self, index):
        self.show("graph", index)
        if self.pending is None and self.runs[index].result is None:
            self.recalculate(index)

    def show_figure(self, figure, run=None, *, fit_page=False, export=None):
        container = ttk.Frame(self.page) if fit_page else self.page
        canvas = FigureCanvasTkAgg(figure, master=container)
        if export is not None:
            toolbar = ImportedPageToolbar(canvas, self.page, export)
        elif run is None:
            toolbar = NavigationToolbar2Tk(canvas, self.page, pack_toolbar=False)
        else:
            toolbar = GraphToolbar(canvas, self.page, before_export=lambda: self.settle_graph_draft("exporting"))
        toolbar.pack(side="bottom", fill="x")
        widget = canvas.get_tk_widget()
        if fit_page:
            ratio = figure.get_figwidth() / figure.get_figheight()

            def resize(event):
                if min(event.width, event.height) > 12:
                    width = min(event.width - 12, max(1, round((event.height - 12) * ratio)))
                    height = max(1, round(width / ratio))
                    widget.place(relx=.5, rely=.5, anchor="center", width=width, height=height)

            container.bind("<Configure>", resize)
            container.pack(side="top", fill="both", expand=True)
        else:
            widget.pack(side="top", fill="both", expand=True)
        canvas.draw()
        self.graph_canvas, self.graph_toolbar = (canvas, toolbar) if run is not None else (None, None)
        if run is not None and run.method not in LEGACY_GRAPH_METHODS and figure.axes:
            self.shape_controller = ShapeCanvas(
                canvas, figure.axes[0], records=lambda: deepcopy((run.style or {}).get(SHAPES, [])),
                commit=lambda records: self.commit_canvas_shapes(run, records), status=self.status.set,
                allowed=lambda: self.pending is None and not toolbar.mode and not segment_axes(figure) and
                                not (self.inspector is not None and self.inspector.has_draft),
                undo=lambda redo: self.apply_shape_history(run, redo=redo), edit=self.edit_canvas_shape,
                context=self.show_shape_context,
                clipboard=lambda action: self.shape_clipboard_action(action, run=run),
                mode_changed=self.shape_mode_changed)
            widget.bind("<Control-z>", lambda event: self.apply_worksheet_history())
            widget.bind("<Control-y>", lambda event: self.apply_worksheet_history(redo=True))
        if run is not None and self.inspector_wanted and self.graph_format_problem(run) is None:
            self.open_inspector(run)

    def graph_format_problem(self, run=None):
        """Why the displayed graph cannot be formatted now, or None. Shared by Format Graph and the Inspector."""
        if run is None:
            if not self.selected or self.selected[0] != "graph":
                return "Select a graph first."
            run = self.runs[self.selected[1]]
        if run.method == SAVED_BINARY_GRAPH:
            return "Use Open editable graph when available, or export the original drawing in its saved vector format."
        if run.method == SAVED_EDITABLE_GRAPH and (
                self.tables[run.title].table_format in EDITABLE_LEGACY_FIXED_VALUES or LEGACY_PREVIEW in run.options):
            return "Use Edit graph data to change values in the recovered drawing."
        if self.pending is not None:
            return "Wait for the current calculation to finish."
        if run.result is None or run.result.figure is None or not run.result.figure.axes:
            return "Calculate the graph first."
        return None

    def refresh_inspector_button(self):
        button = self.inspector_button
        if button is None or not button.winfo_exists():
            return
        run = self.runs[self.selected[1]] if self.selected and self.selected[0] == "graph" else None
        problem = self.graph_format_problem(run) if run is not None else "Select a graph first."
        button.state(["disabled" if problem else "!disabled"])
        button.configure(style="SectionActive.TButton" if self.inspector is not None else "TButton")
        self.inspector_reason.configure(text=problem or "")

    def toggle_inspector(self):
        if self.shape_controller is not None:
            self.shape_controller.set_mode(None)
        if self.inspector is not None:
            self.inspector.cancel()
            return
        problem = self.graph_format_problem()
        if problem:
            self.status.set(problem)
            return
        self.inspector_wanted = True
        self.open_inspector(self.runs[self.selected[1]], focus=True)

    def open_inspector(self, run, *, focus=False):
        if self.graph_canvas is None or self.inspector is not None:
            return
        from analisi.hierarchical_style import describe_hierarchical_artists

        self.inspector = GraphInspector(
            self.page, run, self.graph_canvas, self.graph_toolbar, confirmed=lambda: run.style,
            commit=lambda style: self.commit_graph_style(run, style), closed=self.close_inspector,
            remember=lambda key: setattr(self, "inspector_element", key), element=self.inspector_element,
            colors=(lambda: self.edit_heat_map_colors(run)) if run.method == HEAT_MAP else None,
            qq_panels=self.edit_qq_panels if panel_axes(self.graph_canvas.figure) else None,
            hierarchical_style=self.edit_hierarchical_style
            if describe_hierarchical_artists(self.graph_canvas.figure) else None)
        self.inspector.pack(side="right", fill="y", before=self.graph_toolbar)
        self.refresh_inspector_button()
        if focus:
            self.inspector.selector.focus_set()

    def edit_heat_map_colors(self, run):
        """Inspector shortcut: the heat map's color and legend editor, after the draft is applied or dropped."""
        if self.pending is None and self.settle_graph_draft("opening the heat-map colors"):
            self.edit_analysis(initial_field=self.heat_map_settings_field(run))

    def edit_hierarchical_style(self):
        """Open the dendrogram and heat-map editor after settling any Inspector draft."""
        from analisi.hierarchical_style import describe_hierarchical_artists
        from analisi.hierarchical_style_dialog import HierarchicalStyleDialog

        if self.pending is not None:
            return
        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return
        run = self.runs[self.selected[1]]
        if not describe_hierarchical_artists(run.result.figure):
            return
        if not self.settle_graph_draft("editing the dendrogram style"):
            return
        dialog = HierarchicalStyleDialog(self.root, run.result.figure, self.graph_canvas, run.style or {})
        if dialog.result is None:
            return
        self.commit_graph_style(run, dialog.result, record_shapes=False)
        self.graph_canvas.draw_idle()
        if self.inspector is not None:
            self.inspector.draft = deepcopy(run.style or {})
            self.inspector._load()

    def edit_qq_panels(self):
        """Open the dedicated per-panel formatter for Q–Q graphs after settling any Inspector draft."""
        if self.pending is not None:
            return
        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return
        run = self.runs[self.selected[1]]
        if not panel_axes(run.result.figure):
            return
        if not self.settle_graph_draft("editing Q–Q panels"):
            return
        dialog = QQPanelsDialog(self.root, run.result.figure, self.graph_canvas, run.style)
        if dialog.result is not None:
            self.commit_graph_style(run, dialog.result, record_shapes=False)
            self.graph_canvas.draw_idle()
            if self.inspector is not None:
                self.inspector.draft = deepcopy(run.style or {})
                self.inspector._load()

    def close_inspector(self):
        # The user closed the panel: keep it closed for the next graph.
        self.inspector_wanted = False
        self.dispose_inspector()
        self.refresh_inspector_button()

    def dispose_inspector(self):
        inspector, self.inspector = self.inspector, None
        if inspector is not None:
            inspector.dispose()
            inspector.destroy()

    def commit_graph_style(self, run, style, *, record_shapes=True):
        changed = style != (run.style or {})
        if record_shapes:
            run.shape_history.record((run.style or {}).get(SHAPES, []), style.get(SHAPES, []))
        run.style = style
        run.result.style_warning = self.breaks_warning(run.result.figure, style)
        self.tables[run.title].graph_styles[run.slot] = style
        # The Comparison letters sheet follows the applied visibility, never an Inspector preview.
        sync_letters_table(run.result)
        if changed:
            self.dirty = True
        self.status.set(ui("Graph style applied."))
        self.update_worksheet_history_buttons()

    def settle_graph_draft(self, action):
        """Before saving or exporting: apply or discard an Inspector draft, or stay on the graph."""
        if self.shape_controller is not None:
            self.shape_controller.cancel()
        inspector = self.inspector
        if inspector is None or not inspector.has_draft:
            return True
        answer = messagebox.askyesnocancel(
            "Graph inspector", f"The Inspector has changes that are not applied.\n\nYes applies them before {action}."
            "\nNo discards them.\nCancel returns to the graph.", parent=self.root)
        if answer is None:
            return False
        if answer:
            return inspector.apply()
        inspector.discard()
        return True

    def sync_inspector(self):
        if self.inspector is not None:
            self.inspector.set_busy("Calculation in progress…" if self.pending is not None else None)
        self.refresh_inspector_button()

    def toggle_exclusion(self):
        if self.gallery is not None or not self.selected or self.selected[0] != "data" or not self.current_grid.active_cell:
            self.error("Select a data cell first.")
            return
        dataset = self.get_dataset()
        if dataset is None:
            return
        row, column = self.current_grid.active_cell
        if dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES:
            self.error("Edit the numerical values directly in the recovered graph worksheet.")
            return
        indices = dataset.source_indices
        if (row >= len(dataset.raw) or column >= len(indices) or (source := indices[column]) is None
                or source in dataset.locked_columns):
            self.error("Select an existing source cell to exclude.")
            return
        before = self.worksheet_state(dataset)
        dataset.excluded = dataset.excluded ^ {(row, source)}
        self.finish_worksheet_edit(dataset, before, "Change exclusions")

    def format_graph(self):
        if self.modern_workspace is not None and self.selected and self.selected[0] == "data":
            self.modern_workspace.show_format()
            return
        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return
        run = self.runs[self.selected[1]]
        if self.inspector is not None:
            # The dialog edits the confirmed style; an unapplied Inspector draft is not carried over.
            self.inspector.discard()
        style = dict(run.style or {})
        xy = None
        if run.method == XY_METHOD:
            # Show recipe limits in the left-axis fields without changing the graph until Apply.
            axis = dict(style.get("axis") or {})
            y_axis = dict(axis.get("y") or {})
            if "Y minimum" in run.options and "min" not in y_axis:
                y_axis["min"] = run.options["Y minimum"]
                y_axis["max"] = run.options["Y maximum"]
                axis["y"] = y_axis
                style["axis"] = axis
            xy = {"frame": self.tables[run.title].frame(mask_excluded=True), "options": dict(run.options)}
        dialog = GraphFormatDialog(self.root, run.result.figure.axes[0], style, xy=xy)
        if dialog.result is not None:
            if run.method == XY_METHOD and dialog.xy_update is not None:
                run.options = dialog.xy_update
                run.result = dialog.xy_result
                self.tables[run.title].analyses[run.slot] = (run.method, run.options)
            else:
                try:
                    apply_style(run.result.figure, dialog.result)
                except ValueError as error:
                    self.error(error)
                    return
            run.style = dialog.result
            run.result.style_warning = self.breaks_warning(run.result.figure, run.style)
            self.tables[run.title].graph_styles[run.slot] = run.style
            self.dirty = True
            self.show(*self.selected)

    def edit_graph_annotations(self):
        from analisi.graph_annotation_dialog import GraphAnnotationsDialog

        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return
        run = self.runs[self.selected[1]]
        if run.method in LEGACY_GRAPH_METHODS:
            self.error(tr("annotation.native"))
            return
        if not self.settle_graph_draft("editing annotations"):
            return
        style = dict(run.style or {})
        figure = run.result.figure
        dialog = GraphAnnotationsDialog(self.root, figure.axes[0], style.get(ANNOTATIONS, []))
        if dialog.result is None or dialog.result == style.get(ANNOTATIONS, []):
            return
        if dialog.result:
            style[ANNOTATIONS] = dialog.result
        else:
            style.pop(ANNOTATIONS, None)
        try:
            apply_style(figure, style)
        except ValueError as error:
            self.error(error)
            return
        self.commit_graph_style(run, style)
        self.show(*self.selected)
        self.status.set(tr("annotation.applied"))

    def shape_mode_changed(self, mode):
        self.shape_mode.set(tr("shape.canvas." + mode) if mode else tr("shape.button"))
        self.update_worksheet_history_buttons()

    def start_shape_mode(self, mode):
        if mode is None and self.shape_controller is not None:
            self.shape_controller.set_mode(None)
            self.update_worksheet_history_buttons()
            return True
        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return False
        if self.shape_controller is None:
            self.error(tr("shape.native"))
            return False
        if segment_axes(self.runs[self.selected[1]].result.figure):
            self.error(tr("axis_breaks.canvas_note"))
            return False
        if not self.settle_graph_draft("drawing shapes"):
            return False
        self.inspector_wanted = False
        self.dispose_inspector()
        if self.graph_toolbar.mode:
            if str(self.graph_toolbar.mode) == "pan/zoom":
                self.graph_toolbar.pan()
            else:
                self.graph_toolbar.zoom()
        self.shape_controller.set_mode(mode)
        self.update_worksheet_history_buttons()
        return True

    def commit_canvas_shapes(self, run, records):
        style = deepcopy(run.style or {})
        if records:
            style[SHAPES] = deepcopy(records)
        else:
            style.pop(SHAPES, None)
        self.commit_graph_style(run, style)

    def shape_context_available(self, run):
        return bool(self.selected and self.selected[0] == "graph"
                    and 0 <= self.selected[1] < len(self.runs) and self.runs[self.selected[1]] is run
                    and run.method not in LEGACY_GRAPH_METHODS and self.shape_controller is not None
                    and self.pending is None and self.shape_controller.allowed())

    def shape_clipboard_action(self, action, *, run=None, shape_id=None):
        """Transfer one native drawing through the system clipboard, with graph-local history."""
        from analisi.graph_shapes import on_axis_domain
        from analisi.shape_clipboard import dump_shape, paste_shape

        if run is None:
            if not self.selected or self.selected[0] != "graph" or not 0 <= self.selected[1] < len(self.runs):
                return False
            run = self.runs[self.selected[1]]
        if not self.shape_context_available(run):
            return False
        confirmed = (run.style or {}).get(SHAPES, [])
        try:
            if action in ("copy", "cut"):
                selected = shape_id or self.shape_controller.selected
                record = next((r for r in confirmed if r["id"] == selected), None)
                if record is None:
                    raise ValueError(tr("shape.clipboard.select"))
                self.set_clipboard_text(dump_shape(record))
                if action == "cut":
                    return self.apply_shape_context(run, selected, "remove")
                self.status.set(tr("shape.clipboard.copied"))
                return True
            if action != "paste":
                return False
            records, selected = paste_shape(confirmed, self.root.clipboard_get())
            if not on_axis_domain(run.result.figure.axes[0], records[-1]):
                raise ValueError(tr("shape.error.axis_domain"))
            self.shape_controller.cancel()
            render_shapes(run.result.figure.axes[0], records)
        except (ValueError, TypeError, OverflowError, tk.TclError) as error:
            self.error(error)
            return False
        self.commit_canvas_shapes(run, records)
        self.shape_controller.set_mode("select")
        self.shape_controller.selected = selected
        self.graph_canvas.draw_idle()
        self.status.set(tr("shape.clipboard.pasted"))
        return True

    def apply_shape_context(self, run, shape_id, action, value=None):
        from analisi.shape_context import edit_records
        if not self.shape_context_available(run):
            return False
        confirmed = (run.style or {}).get(SHAPES, [])
        try:
            records, selected = edit_records(confirmed, shape_id, action, value)
            if records == confirmed:
                return False
            self.shape_controller.cancel()
            render_shapes(run.result.figure.axes[0], records)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
            return False
        self.commit_canvas_shapes(run, records)
        self.shape_controller.set_mode("select")
        self.shape_controller.selected = selected
        self.graph_canvas.draw_idle()
        self.status.set(tr("shape.canvas.changed"))
        return True

    def choose_shape_context_color(self, run, shape_id, key):
        if not self.shape_context_available(run) or key not in ("stroke", "fill", "hatch_color"):
            return False
        record = next((r for r in (run.style or {}).get(SHAPES, []) if r["id"] == shape_id), None)
        if record is None:
            return False
        initial = record.get(key) or (record["stroke"] if key == "hatch_color" else "#ffffff")
        from matplotlib.colors import to_hex
        initial = to_hex(initial, keep_alpha=False)
        _, color = colorchooser.askcolor(color=initial, parent=self.root)
        return color is not None and self.apply_shape_context(run, shape_id, key, color)

    def make_shape_context_menu(self, run, shape_id):
        from analisi.shape_context import build_menu
        if not self.shape_context_available(run):
            return None
        record = next((r for r in (run.style or {}).get(SHAPES, []) if r["id"] == shape_id), None)
        if record is None:
            return None
        if self.shape_popup is not None:
            self.shape_popup.destroy()
        self.shape_popup = build_menu(self.root, record,
            change=lambda action, value=None: self.apply_shape_context(run, shape_id, action, value),
            format_object=lambda: self.edit_canvas_shape(shape_id),
            color=lambda key: self.choose_shape_context_color(run, shape_id, key),
            clipboard=lambda action: self.shape_clipboard_action(action, run=run, shape_id=shape_id))
        return self.shape_popup

    def show_shape_context(self, shape_id, event):
        if not self.selected or self.selected[0] != "graph" or not self.start_shape_mode("select"):
            return
        run = self.runs[self.selected[1]]
        self.shape_controller.selected = shape_id
        menu = self.make_shape_context_menu(run, shape_id)
        if menu is None:
            return
        widget = self.graph_canvas.get_tk_widget()
        gui = event.guiEvent
        ratio = self.graph_canvas.device_pixel_ratio
        x = gui.x_root if gui is not None else widget.winfo_rootx() + round(event.x / ratio)
        y = gui.y_root if gui is not None else widget.winfo_rooty() + widget.winfo_height() - round(event.y / ratio)
        try:
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass  # A page or window close may already have disposed the popup.

    def apply_shape_history(self, run, *, redo=False):
        if self.pending is not None or run.result is None:
            return "break"
        if self.shape_controller is not None:
            self.shape_controller.cancel()
        position = run.shape_history.position
        records = run.shape_history.apply((run.style or {}).get(SHAPES, []), redo=redo)
        if records is not None:
            try:
                if segment_axes(run.result.figure):
                    draft = deepcopy(run.style or {})
                    draft.pop(SHAPES, None)
                    if records:
                        draft[SHAPES] = records
                    apply_style(run.result.figure, draft)
                else:
                    render_shapes(run.result.figure.axes[0], records)
            except (ValueError, TypeError, OverflowError) as error:
                run.shape_history.position = position
                self.error(error)
                return "break"
            style = deepcopy(run.style or {})
            if records:
                style[SHAPES] = records
            else:
                style.pop(SHAPES, None)
            self.commit_graph_style(run, style, record_shapes=False)
            if self.graph_canvas is not None:
                self.graph_canvas.draw_idle()
            self.status.set(tr("shape.canvas.redo" if redo else "shape.canvas.undo"))
        self.update_worksheet_history_buttons()
        return "break"

    def edit_canvas_shape(self, shape_id):
        from analisi.graph_shape_dialog import ShapeEditor
        if self.shape_controller is None or self.pending is not None:
            return
        self.shape_controller.cancel()
        run = self.runs[self.selected[1]]
        confirmed = deepcopy((run.style or {}).get(SHAPES, []))
        selected = next((r for r in confirmed if r["id"] == shape_id), None)
        if selected is None:
            return
        axes = run.result.figure.axes[0]
        def preview(record):
            records = confirmed if record is None else [record if r["id"] == shape_id else r for r in confirmed]
            render_shapes(axes, records)
            self.graph_canvas.draw_idle()
        dialog = ShapeEditor(self.root, axes, selected, preview=preview)
        records = confirmed if dialog.result is None else [dialog.result if r["id"] == shape_id else r for r in confirmed]
        render_shapes(axes, records)
        if records != confirmed:
            self.commit_canvas_shapes(run, records)
        self.graph_canvas.draw_idle()
        self.graph_canvas.get_tk_widget().focus_set()

    @staticmethod
    def shape_warning(figure, style):
        """A localized note when saved data shapes are outside the current axis domain, otherwise None."""
        records = (style or {}).get(SHAPES) or []
        if not records or figure is None or not figure.axes:
            return None
        return tr("shape.domain_warning") if skipped_shapes(figure.axes[0], records) else None

    def arrange_graph_shapes(self):
        return self.edit_graph_shapes(arrange=True)

    def edit_graph_shapes(self, *, arrange=False):
        from analisi.graph_shape_dialog import GraphShapesDialog

        problem = self.graph_format_problem()
        if problem:
            self.error(problem)
            return
        run = self.runs[self.selected[1]]
        if run.method in LEGACY_GRAPH_METHODS:
            self.error(tr("shape.native"))
            return
        if not self.settle_graph_draft("editing shapes"):
            return
        figure = run.result.figure
        confirmed = deepcopy(run.style or {})

        def with_shapes(records):
            style = deepcopy(confirmed)
            if records:
                style[SHAPES] = deepcopy(records)
            else:
                style.pop(SHAPES, None)
            return style

        def preview(records):
            # A preview draws on the figure only; run.style, the dataset and the dirty flag change on Apply.
            candidate = deepcopy(confirmed) if records is None else with_shapes(records)
            apply_style(figure, candidate)
            if self.graph_canvas is not None:
                self.graph_canvas.draw_idle()
            return self.shape_warning(figure, candidate)

        if arrange:
            from analisi.shape_arrange_dialog import ArrangeShapesDialog
            editor = ArrangeShapesDialog
        else:
            editor = GraphShapesDialog
        dialog = editor(self.root, figure.axes[0], confirmed.get(SHAPES, []), preview=preview)
        if dialog.result is None or dialog.result == confirmed.get(SHAPES, []):
            if dialog.shown is not None:
                preview(None)
            return
        style = with_shapes(dialog.result)
        try:
            apply_style(figure, style)
        except ValueError as error:
            preview(None)
            self.error(error)
            return
        self.commit_graph_style(run, style)
        self.show(*self.selected)
        self.status.set(" ".join(filter(None, (tr("shape.applied"), self.shape_warning(figure, style)))))

    def layout_runs(self, layout):
        by_ref = {run.reference: run for run in self.runs}
        return [by_ref[reference] for reference in layout.panels]

    def layout_panel_figures(self, layout):
        runs = self.layout_runs(layout)
        if not all(run.result and run.result.figure for run in runs):
            raise ValueError("Recalculate the layout panels before exporting the layout.")
        return tuple(run.result.figure for run in runs)

    def layout_rendering(self, layout, *, transparent=False):
        return compose_layout(layout.name, layout.columns, self.layout_panel_figures(layout), paper=layout.paper,
                              background=WHITE if transparent else layout.background)

    def layout_pdf_page(self, layout):
        from analisi.layout_pdf import PdfLayoutPage

        return PdfLayoutPage(layout.name, layout.columns, self.layout_panel_figures(layout), layout.paper, layout.background)

    def export_vector_layout(self, layout, path, settings):
        if any(run.calculation_error for run in self.layout_runs(layout)):
            raise ValueError(tr("reference.stale_export"))
        if settings["format"] == "pdf":
            from analisi.figure_export import export_pdf_bundle

            export_pdf_bundle([self.layout_pdf_page(layout)], path, settings)
        else:
            from analisi.layout_svg import export_layout_svg

            export_layout_svg(layout.name, layout.columns, self.layout_panel_figures(layout), path, settings,
                              paper=layout.paper, background=layout.background)

    def new_layout(self, edit=False):
        if self.pending is not None:
            self.error("Wait for the current calculation to finish.")
            return
        key = self.selected[1] if edit and self.selected and self.selected[0] == "layout" else None
        if edit and key is None:
            self.error("Select a layout first.")
            return
        current = self.layouts[key] if key is not None else None
        if current is None and len(self.layouts) >= 128:
            self.error("A project supports up to 128 layouts.")
            return
        candidates = [run for run in self.runs if (run.result and run.result.figure)
                      or (current and run.reference in current.panels)]
        if not candidates:
            self.error("Create one or more graphs before composing a layout.")
            return
        dialog = LayoutDialog(self.root, candidates, current)
        if dialog.result is not None and dialog.result != current:
            if key is None:
                key = len(self.layouts)
                self.layouts.append(dialog.result)
            else:
                self.layouts[key] = dialog.result
            self.dirty = True
            self.refresh_navigator()
            self.show("layout", key)

    def recalculate_layout(self, key):
        if self.pending is not None:
            return
        layout = self.layouts[key]
        distinct = {run.reference: run for run in self.layout_runs(layout)}
        needed = [(run, None) for run in distinct.values() if run.result is None or run.calculation_error]
        if needed and self.refresh_chain_calculations(needed, inputs_changed=False):
            return
        missing = [(run, self.tables[run.title].frame(mask_excluded=True), self.pairwise_snapshot(run))
                   for run in distinct.values() if run.result is None]
        self.status.set(tr("interface.updating", name=layout.name))

        def calculate():
            prepared = precompute_analyses([(id(run), run.method, frame, run.options) for run, frame, _ in missing])
            return [(run, self.compute(run, frame, self.prepared_result(prepared, run), pairwise=pairwise))
                    for run, frame, pairwise in missing]

        self.pending = self.worker.submit(calculate)

        def check():
            if not self.pending.done():
                self.root.after(60, check)
                return
            future, self.pending = self.pending, None
            try:
                results = future.result()
                if any(not result.figure for _, result in results):
                    raise ValueError("An analysis no longer generates a graph.")
                for run, result in results:
                    run.result = result
                self.refresh_navigator()
                if self.selected == ("layout", key):
                    self.show("layout", key)
                self.status.set(tr("interface.updated", name=layout.name))
            except Exception as error:
                self.status.set(ui("Layout could not be updated."))
                self.error(error)

        self.root.after(60, check)

    def use_result_as_data(self):
        if not self.require_current_calculation():
            return
        run = self.runs[self.selected[1]]
        sheet = self.result_tabs.index("current")
        name, frame = list(run.result.tables.items())[sheet]
        if frame.empty or frame.columns.empty:
            self.error("The result does not contain a data table.")
            return
        if not isinstance(frame.index, pd.RangeIndex):
            labels = frame.index
            columns = set(frame.columns)
            names = []
            for level, title in enumerate(labels.names, 1):
                column = title or ("Label" if labels.nlevels == 1 else f"Level {level}")
                while column in columns:
                    column += " (index)"
                columns.add(column)
                names.append(column)
            if isinstance(labels, pd.MultiIndex):
                frame = frame.reset_index(names=names)
            else:
                frame = frame.set_axis(pd.Index([str(value) if isinstance(value, tuple) else value for value in labels],
                                               name=names[0], tupleize_cols=False)).reset_index()
        editable = frame.rename(columns=str)
        if run.method == SAVED_BINARY_RESULT:
            editable.attrs.clear()
        self._add_tables({name: editable})

    def _unique_title(self, title):
        proposed, i = title, 2
        while proposed in self.tables:
            proposed = f"{title} ({i})"
            i += 1
        return proposed

    def update_info_sheets(self, sheets):
        validate_info_sheets(tuple(sheets.values()), self.tables)
        contexts, frames = {}, {}
        scoped = info_contexts(sheets.values())
        for title, dataset in self.tables.items():
            context = scoped.get(title, scoped[None])
            if context == dataset.info:
                continue
            contexts[title] = context
            references = {name for expression in dataset.formulas.values() for name in info_references(expression)}
            missing = object()
            if any(context.get(name, missing) != dataset.info.get(name, missing) for name in references):
                if self.pending is not None:
                    raise ValueError("Wait for the current analysis before updating a linked Info constant.")
                candidate = copy(dataset)
                candidate.info = context
                frames[title] = candidate.frame(mask_excluded=True)
        self.info_sheets = sheets
        for title, context in contexts.items():
            self.tables[title].info = context
        self.dirty = True
        self.refresh_calculations([(run, frames[run.title]) for run in self.runs if run.title in frames])

    def change_info(self, sheet):
        current = self.info_sheets[sheet.uid]
        if (sheet.table, sheet.fields) != (current.table, current.fields):
            self.update_info_sheets({**self.info_sheets, sheet.uid: sheet})
        else:
            self.info_sheets[sheet.uid] = sheet
            self.dirty = True

    def info_tables(self):
        return [name for name, dataset in self.tables.items() if not stored_legacy_view(dataset)]

    def new_info(self):
        if len(self.info_sheets) >= MAX_INFO_SHEETS:
            self.error("A project supports up to 500 Info sheets.")
            return
        tables = self.info_tables()
        title = f"Project info {len(self.info_sheets) + 1}"
        dialog = InfoDetails(self.root, title, self.active_data, tables, creating=True)
        if dialog.result is None:
            return
        sheet = InfoSheet.new(*dialog.result)
        try:
            self.update_info_sheets({**self.info_sheets, sheet.uid: sheet})
        except (ValueError, OverflowError) as error:
            self.error(error)
            return
        self.refresh_navigator()
        self.show("info", sheet.uid)

    def info_properties(self):
        if not self.selected or self.selected[0] != "info":
            self.error("Select an Info sheet first.")
            return
        self.current_info.notes_changed()
        sheet = self.current_info.sheet
        dialog = InfoDetails(self.root, sheet.title, sheet.table, self.info_tables())
        if dialog.result is None:
            return
        title, table = dialog.result
        if self.current_info.commit(title=title, table=table):
            self.refresh_navigator()
            self.show("info", sheet.uid)

    def move_info(self, direction):
        uid = self.selected[1]
        sheets = list(self.info_sheets.items())
        row = list(self.info_sheets).index(uid)
        other = row + direction
        if 0 <= other < len(sheets):
            sheets[row], sheets[other] = sheets[other], sheets[row]
            self.info_sheets = dict(sheets)
            self.dirty = True
            self.refresh_navigator()

    def remove_info(self):
        uid = self.selected[1]
        sheet = self.info_sheets[uid]
        if not messagebox.askyesno("Delete Info sheet", f'Delete "{sheet.title}"?', parent=self.root):
            return
        self.current_info.notes_changed()
        remaining = {key: value for key, value in self.info_sheets.items() if key != uid}
        try:
            self.update_info_sheets(remaining)
        except (ValueError, OverflowError) as error:
            self.error(error)
            return
        self.history = [ref for ref in self.history[:self.history_position + 1] if ref != ("info", uid)]
        self.history_position = len(self.history) - 1
        self.selected = None
        self.active_data = None
        self.refresh_navigator()
        if self.history:
            self.open_sheet(self.history[-1], record_history=False)
        elif self.tables or remaining:
            self.show_imported_tables(self.tables)
        else:
            self.home()

    @staticmethod
    def runs_for(title, dataset):
        """The Run of every stored analysis of a table, with the identity, source and name it was saved with."""
        return [Run(method, title, options, slot=index, style=dataset.graph_styles.get(index),
                    uid=dataset.analysis_ids.get(index, str(uuid4())), source=dataset.analysis_sources.get(index),
                    label=dataset.analysis_labels.get(index))
                for index, (method, options) in enumerate(dataset.analyses)]

    def _add_tables(self, tables, info_sheets=(), *, initial_sheet=None):
        if not tables and not info_sheets:
            raise ValueError("No data tables were found.")
        if len(self.tables) + len(tables) > 256:
            raise ValueError("A project supports up to 256 data tables.")
        if info_sheets:
            self.update_info_sheets({**self.info_sheets, **{sheet.uid: sheet for sheet in info_sheets}})
        contexts = info_contexts(self.info_sheets.values())
        skipped = []
        warnings = []
        titles = []
        for name, frame in tables.items():
            title = self._unique_title(name)
            titles.append(title)
            dataset = self.tables[title] = Dataset(frame.reset_index(drop=True),
                                                   info=contexts.get(title, contexts[None]))
            self.runs.extend(self.runs_for(title, dataset))
            skipped.extend(frame.attrs.get("skipped", []))
            warnings.extend(frame.attrs.get("import_warnings", []))
        self.dirty = True
        self.refresh_navigator()
        if focus := initial_sheet_reference(initial_sheet, self.runs, run_view):
            self.open_sheet(focus)
        else:
            self.show_imported_tables(titles if initial_sheet is not None else reversed(titles))
        if skipped:
            warnings.insert(0, tr("status.unsupported", names=", ".join(dict.fromkeys(skipped))))
        methods = [method for title in titles for method, _ in self.tables[title].analyses]
        sources = sum(not stored_legacy_view(self.tables[title])
                      and self.tables[title].table_format != EDITABLE_LEGACY_EMF for title in titles)
        summary = [tr("status.imported", count=sources)]
        if info_sheets:
            summary.append(tr("status.info_sheets", count=len(info_sheets)))
        for method, label in ((SAVED_BINARY_RESULT, "saved results"), (SAVED_BINARY_GRAPH, "original graphs"),
                              (SAVED_EDITABLE_GRAPH, "editable graphs"), (SAVED_BINARY_LAYOUT, "layouts")):
            if count := methods.count(method):
                summary.append(f"{count} {label}.")
        self.status.set(" ".join([*summary, *dict.fromkeys(warnings)]))

    def show_imported_tables(self, titles):
        titles = tuple(titles)
        worksheets = [title for title in titles if not stored_legacy_view(self.tables[title])]
        if worksheets:
            source = next((title for title in worksheets if self.tables[title].table_format != EDITABLE_LEGACY_EMF),
                          worksheets[0])
            self.show("data", source)
            return
        for index, run in enumerate(self.runs):
            if run.title in titles:
                self.show(run_view(run.method), index)
                if self.pending is None:
                    self.recalculate(index)
                return
        if self.info_sheets:
            self.show("info", next(iter(self.info_sheets)))
        elif not self.tables:
            self.home()

    def import_file(self, filename, *, open_project=False):
        if self.current_info is not None:
            self.current_info.notes_changed()
        if Path(filename).suffix.lower() == ".alab":
            if self.pending is not None:
                raise ValueError("Wait for the current analysis to finish.")
            loaded, layouts, info_sheets = load_workspace(filename, include_info=True)
            self.tables, self.path, self.layouts = loaded, Path(filename), layouts
            self.info_sheets = {sheet.uid: sheet for sheet in info_sheets}
            self.runs = [run for name, table in loaded.items() for run in self.runs_for(name, table)]
            self.selected = None
            self.active_data = None
            self.history.clear()
            self.history_position = -1
            self.worksheet_history.clear()
            self.dirty = False
            self.refresh_navigator()
            self.show_imported_tables(loaded)
            self.status.set(tr("status.opened", name=self.path.name))
        else:
            info_sheets = []
            initial_sheet = [] if open_project else None
            tables = load_tables(filename, restore_legacy=True, info_sheets=info_sheets, initial_sheet=initial_sheet)
            self._add_tables(tables, info_sheets, initial_sheet=initial_sheet)

    def refresh_project_tabs(self):
        active = self.projects[self.active_project]
        active.path, active.dirty = self.path, self.dirty
        for key, project in self.projects.items():
            self.project_tabs.caption(key, project.title, project.dirty)
        visible = self.selected is not None or len(self.projects) > 1
        if visible and not self.project_tabs.winfo_manager():
            first = self.ribbon if ui_theme.is_modern() and self.ribbon.winfo_manager() else self.workspace
            self.project_tabs.pack(fill="x", before=first)
        elif not visible:
            self.project_tabs.pack_forget()

    def prepare_project_change(self):
        if self.pending is None and self.current_grid is not None:
            self.current_grid.commit_edit()
        if self.pending is not None:
            self.status.set(ui("Wait for the current calculation before switching projects."))
            return False
        if self.current_info is not None:
            self.current_info.notes_changed()
        return self.pending is None

    def restore_project_view(self, key):
        self._clear("")
        self.nav.delete(*self.nav.get_children())
        self.nav_filter_active = False
        self.active_project = key
        self.project_tabs.select(key)
        project = self.projects[key]
        project.install(self)
        self.search_placeholder = not project.search
        self.search_input.set(project.search or tr("nav.search"))
        self.refresh_navigator()
        if project.selected is None:
            self.home()
        else:
            self.show(*project.selected, record_history=False)
            if project.grid_view is not None and self.current_grid is not None:
                self.current_grid.update_idletasks()
                self.current_grid.restore(project.grid_view, focus=True)
        self.status.set(project.status)

    def switch_project(self, key):
        if key == self.active_project:
            return True
        if key not in self.projects or not self.prepare_project_change():
            self.project_tabs.select(self.active_project)
            return False
        self.remember_navigator_expansion()
        self.projects[self.active_project].capture(self)
        self.restore_project_view(key)
        return True

    def add_project(self):
        if not self.prepare_project_change():
            return None
        if len(self.projects) >= MAX_PROJECT_TABS:
            self.error(f"Close a project before opening more than {MAX_PROJECT_TABS} at once.")
            return None
        key = self.project_tabs.add()
        self.project_number += 1
        self.projects[key] = ProjectSession(number=self.project_number)
        if self.switch_project(key):
            return key
        self.remove_project_tab(key)
        return None

    def new_project(self):
        self.add_project()
        return "break"

    def step_project(self, offset):
        keys = self.project_tabs.keys()
        if len(keys) > 1:
            self.switch_project(keys[(keys.index(self.active_project) + offset) % len(keys)])
        return "break"

    def close_project(self):
        if not self.prepare_project_change() or not self.confirm_saved():
            return "break"
        key = self.active_project
        keys = self.project_tabs.keys()
        if len(keys) == 1:
            self.projects[key] = ProjectSession(number=self.projects[key].number)
            self.restore_project_view(key)
        else:
            position = keys.index(key)
            target = keys[position - 1] if position else keys[1]
            if self.switch_project(target):
                self.remove_project_tab(key)
        return "break"

    def remove_project_tab(self, key):
        self.project_tabs.remove(key)
        del self.projects[key]
        self.refresh_project_tabs()

    def open_project_for_path(self, path, *, include_imports=False):
        canonical = path.resolve()
        for key, project in self.projects.items():
            current = self.path if key == self.active_project else project.path
            if ((current and current.resolve() == canonical)
                    or (include_imports and project.origin == canonical)):
                return key
        return None

    def open_document(self, filename, *, import_data=False):
        if not self.prepare_project_change():
            return False
        path = Path(filename).resolve()
        project_file = path.suffix.lower() == ".alab" or (path.suffix.lower() in PROJECT_SUFFIXES and not import_data)
        if not project_file:
            if import_data and path.suffix.lower() in TEXT_SUFFIXES:
                dialog = TextImportDialog(self.root, path)
                if dialog.result is None:
                    return False
                self._add_tables({path.stem: dialog.result})
            else:
                self.import_file(path)
            return True
        if existing := self.open_project_for_path(path, include_imports=True):
            return self.switch_project(existing)
        previous, key = self.active_project, None
        if self.tables or self.info_sheets or self.path or self.dirty:
            key = self.add_project()
            if key is None:
                return False
        try:
            self.import_file(path, open_project=True)
        except Exception:
            if key is not None and self.switch_project(previous):
                self.remove_project_tab(key)
            raise
        self.projects[self.active_project].origin = path
        self.refresh_project_tabs()
        return True

    def open_dialog(self, *, import_data=False):
        filename = filedialog.askopenfilename(filetypes=[
            (tr("prompt.data_files"), "*.alab *.csv *.tsv *.txt *.xlsx *.prism *.prismt *.pzt *.pzfx *.pzf *.xml"),
            (tr("prompt.legacy_files"), "*.prism *.prismt *.pzt *.pzfx *.pzf *.xml"), (tr("prompt.all_files"), "*.*")])
        if filename:
            try:
                self.open_document(filename, import_data=import_data)
            except Exception as error:
                self.error(error)

    def new_table(self):
        setup = NewTableDialog(self.root, tr("setup.dialog_title"))
        if setup.result is not None:
            self.create_worksheet(*setup.result)

    def create_worksheet(self, template, sample):
        title = f"{template.name} example" if sample else template.name
        self._add_tables({title: table_frame(template, sample)})
        if (template.kind.casefold().startswith("xy") and template.columns[0] == "Row title"
                and self.current_grid is not None):
            self.current_grid.select((0, 1))

    def paste_table(self):
        try:
            import csv
            from io import StringIO

            rows = list(csv.reader(StringIO(self.root.clipboard_get()), dialect="excel-tab"))
            if len(rows) < 2:
                raise ValueError("Copy a tab-delimited table including a header and at least one data row.")
            self._add_tables({"Pasted data": _table(rows[0], rows[1:])})
        except (ValueError, tk.TclError) as error:
            self.error(error)

    def paste_into_workspace(self):
        if self.selected and self.selected[0] == "graph":
            return self.shape_clipboard_action("paste")
        if self.current_info is not None or self.current_grid is not None or self.gallery is not None:
            return self.paste_selection()
        return self.paste_table()

    def copy_into_workspace(self):
        if self.selected and self.selected[0] == "graph":
            return self.shape_clipboard_action("copy")
        return self.copy_selection()

    def copy_selection(self):
        if self.gallery is not None:
            self.error("Open a sheet before copying cells.")
            return "break"
        if self.current_info is not None:
            return self.current_info.copy()
        grid = self.current_grid
        if grid is None:
            self.error("Select a data range first.")
            return "break"
        try:
            text = copy_block(grid.frame, grid.selection, grid.excluded, decimal_mark=clipboard_decimal_mark())
            self.set_clipboard_text(text)
            self.status.set(ui("Selected cell values copied."))
        except (ValueError, tk.TclError) as error:
            self.error(error)
        return "break"

    def set_clipboard_text(self, text):
        self.root.clipboard_clear()
        # Tk inserts CR before every LF when rendering the Windows clipboard.
        self.root.clipboard_append(text.replace("\r\n", "\n") if sys.platform == "win32" else text)

    def clear_selection(self, *, cut=False):
        grid = self.current_grid
        if grid is None:
            self.error("Select a source cell range first.")
            return "break"
        dataset = self.get_dataset()
        if dataset is None:
            return "break"
        before = self.worksheet_state(dataset)
        candidate = copy(dataset)
        try:
            clear_block(candidate, grid.selection)
            if cut:
                text = copy_block(grid.frame, grid.selection, (), decimal_mark=clipboard_decimal_mark())
                self.set_clipboard_text(text)
        except (ValueError, TypeError, OverflowError, tk.TclError) as error:
            self.error(error)
        else:
            dataset.raw, dataset.excluded = candidate.raw, candidate.excluded
            self.finish_worksheet_edit(dataset, before, "Cut cells" if cut else "Clear cells")
        return "break"

    def paste_selection(self, *, transpose=False, special=False):
        if self.gallery is not None:
            self.error("Open a sheet before pasting cells.")
            return "break"
        if self.current_info is not None and not (transpose or special):
            return self.current_info.paste()
        grid = self.current_grid
        if grid is None:
            self.error("Select a destination cell first.")
            return "break"
        dataset = self.get_dataset()
        if dataset is None:
            return "break"
        top, left, _, _ = grid.selection
        before = self.worksheet_state(dataset)
        try:
            rows = clipboard_rows(self.root.clipboard_get(), max_columns=max(MAX_COLUMNS, len(dataset.raw.columns)),
                                  transpose=transpose)
            if special:
                dialog = PasteSpecialDialog(self.root, rows, f"{column_label(left)}{top + 1}")
                if dialog.result is None:
                    return "break"
                rows = dialog.result
            paste_block(dataset, top, left, rows)
        except (ValueError, TypeError, OverflowError, tk.TclError) as error:
            self.error(error)
        else:
            label = "Paste special" if special else "Paste transpose" if transpose else "Paste"
            self.finish_worksheet_edit(dataset, before, label,
                                       (top, left, top + len(rows) - 1, left + len(rows[0]) - 1))
        return "break"

    def example(self):
        self._add_tables({"Dose and response": pd.DataFrame({
            "Dose": [1., 2., 3., 4., 5., 6., 1., 2., 3., 4., 5., 6.],
            "Response": [2.0, 5.5, 5.9, 8.4, 9.6, 11.4, 3.0, 6.2, 7.1, 8.9, 11.2, 13.8],
            "Group": ["Control"] * 6 + ["Treatment"] * 6,
        })})

    def get_dataset(self):
        if self.gallery is not None or (self.selected and self.selected[0] == "info"):
            self.error("Select a data table to use this command.")
            return None
        if self.active_data is None:
            self.error("Open or create a data table first.")
            return None
        if self.pending is not None:
            self.error("Wait for the current analysis to finish.")
            return None
        dataset = self.tables[self.active_data]
        if stored_legacy_view(dataset):
            self.error("Select a source table or use Result as Data to create an editable table.")
            return None
        return dataset

    def worksheet_state(self, dataset):
        view = self.current_grid.view_state() if self.current_grid is not None else None
        return WorksheetState.capture(dataset, view)

    def finish_worksheet_edit(self, dataset, before, label, selection=None):
        view = before.view
        if selection is not None and view is not None:
            top, left, bottom, right = selection
            view = (top, left), (bottom, right), *view[2:]
        after = WorksheetState.capture(dataset, view)
        if self.worksheet_history.record(self.active_data, label, before, after):
            self.invalidate()
            if selection is not None:
                self.current_grid.select_block(*selection)

    def shape_history_context(self):
        if self.selected and self.selected[0] == "graph":
            run = self.runs[self.selected[1]]
            active = self.shape_controller is not None and self.shape_controller.mode is not None
            if run.method not in LEGACY_GRAPH_METHODS and (run.shape_history.changes or active):
                return run
        return None

    def update_worksheet_history_buttons(self):
        run = self.shape_history_context()
        history = run.shape_history if run is not None else self.worksheet_history
        for label, button in self.worksheet_history_buttons.items():
            enabled = (self.pending is None and self.current_info is None
                       and history.can_apply(redo=label == "Redo"))
            button.state(["!disabled" if enabled else "disabled"])
            popup, index = self.menu_entries["Edit", label]
            popup.entryconfigure(index, state="normal" if enabled else "disabled")

    def apply_worksheet_history(self, *, redo=False):
        shape_run = self.shape_history_context()
        if shape_run is not None:
            return self.apply_shape_history(shape_run, redo=redo)
        if self.pending is not None or self.current_info is not None:
            return "break"
        try:
            change = self.worksheet_history.apply(self.tables, redo=redo)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
            return "break"
        if change is not None:
            self.active_data = change.title
            self.invalidate()
            state = change.after if redo else change.before
            if state.view is not None:
                self.current_grid.update_idletasks()
                self.current_grid.restore(state.view, focus=True)
            if self.pending is None:
                self.status.set(f"{'Redid' if redo else 'Undid'} {change.label.lower()}.")
        return "break"

    def invalidate(self):
        title = self.active_data
        grid = self.current_grid if self.selected == ("data", title) else None
        state = grid.view_state() if grid is not None else None
        focused = grid is not None and self.root.focus_get() == grid.canvas
        affected = [run for run in self.runs if run.title == title
                    or (run.method == WORKSHEET_JOIN and worksheet_join_engine.right_title(run.options) == title)]
        if any(isinstance(run.options.get(LEGACY_GRAPH_LINK), str) for run in affected):
            affected.extend(linked_panel_readers(title, self.runs, self.tables))
        for run in affected:
            # refresh_calculations keeps the previous result when the edit cannot be calculated.
            # Clearing it first would snapshot None. Reference normalization, lognormal one-way
            # and false-discovery control restore that result.
            if not self._keeps_failed_result(run):
                run.result = None
        self.dirty = True
        self.show("data", title)
        self.refresh_navigator()
        if state is not None:
            self.current_grid.update_idletasks()
            self.current_grid.restore(state, focus=focused)
        if not affected:
            self.status.set(ui("Data updated."))
            return
        frames = {name: self.tables[name].frame(mask_excluded=True) for name in {run.title for run in affected}}
        self.refresh_calculations([(run, frames[run.title]) for run in affected])

    def refresh_calculations(self, affected):
        if not affected:
            return
        if self.refresh_chain_calculations(affected):
            return
        previous = {}
        for run, _ in affected:
            if self._keeps_failed_result(run):
                # Read back only if this edit fails. The worker does not change the saved result.
                previous[id(run)] = run.result
            run.result = None
        # Comparison sources run before the graphs that read them, so each graph reuses the new result.
        affected = sorted(affected, key=lambda item: PAIRWISE_SECTION in item[0].options)
        snapshots = [self.pairwise_snapshot(run) for run, _ in affected]
        joins = {id(run): self.join_data(run) for run, _ in affected if run.method == WORKSHEET_JOIN}
        panels = {id(run): self.layout_panel_data(run) for run, _ in affected if LEGACY_PANEL_DATA in run.options}
        self.status.set(f"Updating {len(affected)} linked analysis result(s)…")
        control = CalculationControl() if any(cancellable_run(run.method, run.options) for run, _ in affected) else None

        def calculate():
            results, fresh = [], {}
            # Several processes compute the analyses themselves; styles, comparison brackets and errors are
            # still handled below, one run at a time and in this order.
            prepared = precompute_analyses([(id(run), run.method, frame, run.options) for run, frame in affected],
                                           cancel=control.cancel if control is not None else None)
            for (run, frame), pairwise in zip(affected, snapshots, strict=True):
                if pairwise and pairwise.get("tables") is None and pairwise.get("key") in fresh:
                    pairwise = {**pairwise, "tables": fresh[pairwise["key"]]}
                try:
                    extras = {"join_data": joins[id(run)]} if id(run) in joins else {}
                    if id(run) in panels:
                        extras["layout_data"] = panels[id(run)]
                    result = self.compute(run, frame, self.prepared_result(prepared, run), control=control,
                                          pairwise=pairwise, **extras)
                    results.append((run, result, None))
                    fresh[run.title, run.slot] = result.tables
                except (MonteCarloCancelled, ChainCancelled):
                    results.append((run, None, None))
                except Exception as error:
                    if run.method == REFERENCE_NORMALIZATION or uses_hierarchy_diagnostics(run.method, run.options):
                        results.append((run, previous.get(id(run)), error))
                    elif (run.method in {WORKSHEET_JOIN, kmeans_stability.METHOD, logistic_validation.METHOD}
                          or uses_planned_contrasts(run.method, run.options)
                          or (self._reopens_field_error(run) and isinstance(error, FieldError))):
                        results.append((run, previous.get(id(run)), error))
                    elif run.method == SAVED_BINARY_LAYOUT or LEGACY_PANEL_DATA in run.options:
                        results.append((run, previous.get(id(run)), str(error)))
                    elif run.method == HEAT_MAP:
                        results.append((run, None, error))
                    else:
                        results.append((run, None, str(error)))
            return results

        def check():
            if not self.pending.done():
                if (len(affected) == 1
                        and affected[0][0].method in {kmeans_stability.METHOD, logistic_validation.METHOD}):
                    self.show_calculation_progress(affected[0][0].method)
                self.root.after(60, check)
                return
            future, self.pending = self.pending, None
            self.end_calculation()
            cancelled = control is not None and control.cancel.is_set()
            failures = []
            recovered = False
            for run, result, error in future.result():
                if cancelled and cancellable_run(run.method, run.options):
                    if (run.method in {INDEPENDENT_ROC, precision_recall.METHOD, icc.METHOD, reshape.METHOD,
                                       WORKSHEET_JOIN, kmeans_stability.METHOD, logistic_validation.METHOD}
                            or uses_hierarchy_diagnostics(run.method, run.options)):
                        run.result = previous.get(id(run))
                        run.calculation_error = "The update was cancelled." if run.result is not None else None
                    elif cox_exact_run(run) and previous.get(id(run)) is not None:
                        # The last valid fit stays on screen, marked as not current until it is recalculated.
                        run.result = previous[id(run)]
                        run.calculation_error = "The exact Cox recalculation was cancelled."
                    continue
                run.result = result
                run.calculation_error = str(error) if error and self._keeps_failed_result(run) else None
                if error:
                    if self._reopens_field_error(run) and isinstance(error, FieldError):
                        index = next((i for i, item in enumerate(self.runs) if item is run), None)
                        recovery = self.weighting_recovery(run.method, run.options, index)
                        if recovery is not None and self.recover_analysis(run, error, recovery):
                            recovered = True
                            continue
                    if run.method == REFERENCE_NORMALIZATION and not isinstance(error, str):
                        failures.append(translate_reference_error(error))
                    elif run.method == INDEPENDENT_ROC:
                        failures.append(translate_independent_roc_error(error))
                    elif run.method == precision_recall.METHOD:
                        failures.append(translate_precision_recall_error(error))
                    elif run.method == icc.METHOD:
                        failures.append(translate_icc_error(error))
                    elif run.method == kmeans_stability.METHOD:
                        failures.append(translate_kmeans_stability_error(error))
                    elif run.method == logistic_validation.METHOD:
                        failures.append(translate_logistic_validation_error(error))
                    elif run.method == WORKSHEET_JOIN:
                        failures.append(translate_join_error(error))
                    elif run.method == reshape.METHOD:
                        failures.append(reshape_tk.format_error(error))
                    elif run.method == HEAT_MAP and not isinstance(error, str):
                        failures.append(translate_heat_map_error(error))
                    elif run.method == ANCOVA and not isinstance(error, str):
                        failures.append(format_ancova_error(error) or str(error))
                    else:
                        failures.append(error if isinstance(error, str) else str(error))
            self.refresh_navigator()
            if self.modern_workspace is not None:
                self.modern_workspace.refresh()
            if self.selected and self.selected[0] in RUN_VIEWS | {"layout"}:
                if self.gallery is None:
                    self.show(*self.selected)
                else:
                    self.gallery_refresh = True
            if failures:
                self.status.set(f"{len(failures)} linked analyses need attention. {failures[0]}")
            elif recovered:
                pass
            elif cancelled:
                methods = {run.method for run, _ in affected if cancellable_run(run.method, run.options)}
                if methods == {INDEPENDENT_ROC}:
                    kept = any(previous.get(id(run)) is not None for run, _ in affected if run.method == INDEPENDENT_ROC)
                    self.status.set(tr("iroc.cancelled", kept=tr("iroc.kept_result" if kept else "iroc.kept_none")))
                elif methods == {COX}:
                    self.status.set(tr("cox.exact.cancelled.recalculation"))
                elif methods and methods <= {COMPETING_RISKS, RMCORR, META_ANALYSIS, COHEN_KAPPA, MEAN_PERMUTATION}:
                    names = " and ".join(sorted(methods))
                    self.status.set(f"{names} recalculation cancelled. Open the analysis to calculate again.")
                else:
                    self.status.set(ui("Calculation cancelled."))
            else:
                self.status.set(f"Updated {len(affected)} linked analysis result(s).")

        self.pending = self.worker.submit(calculate)
        self.begin_calculation(control)
        self.update_worksheet_history_buttons()
        if self.modern_workspace is not None:
            self.modern_workspace.refresh()
        self.root.after(60, check)

    def edit_cell(self, row, column, value):
        dataset = self.get_dataset()
        if dataset is not None:
            before = self.worksheet_state(dataset)
            try:
                edit_cell_value(dataset, row, column, value)
            except (ValueError, TypeError, OverflowError) as error:
                self.error(error)
            else:
                self.finish_worksheet_edit(dataset, before, "Edit cell")

    def add_row(self):
        data = self.get_dataset()
        if data is not None:
            if data.locked_columns:
                self.error("Edit the existing recovered graph values in this worksheet.")
                return
            if (len(data.raw) + 1) * len(data.raw.columns) > MAX_CELLS:
                self.error("Adding a row would exceed the table size limit.")
                return
            before = self.worksheet_state(data)
            data.raw = grow_rows(data.raw, len(data.raw) + 1)
            self.finish_worksheet_edit(data, before, "Add row")

    def add_column(self):
        data = self.get_dataset()
        if data is None:
            return
        if data.table_format in EDITABLE_LEGACY_FIXED_VALUES:
            self.error("This worksheet keeps the columns of the recovered graph.")
            return
        if len(data.raw.columns) >= MAX_COLUMNS:
            self.error(f"New tables support up to {MAX_COLUMNS} source columns.")
            return
        if len(data.raw) * (len(data.raw.columns) + 1) > MAX_CELLS:
            self.error("Adding a column would exceed the table size limit.")
            return
        name = simpledialog.askstring(ui("New column"), ui("Column name"), parent=self.root)
        if name and name.strip() and name.strip() not in data.frame():
            before = self.worksheet_state(data)
            candidate = data.raw.copy()
            name = name.strip()
            candidate[name] = np.nan
            if data.column_order is not None:
                order = data.column_order
                position = order.index(data.raw.columns[-1]) + 1
                data.column_order = (*order[:position], name, *order[position:])
            data.raw = candidate
            self.finish_worksheet_edit(data, before, "Add column")
        elif name:
            self.error("Choose a nonempty, unused column name.")

    def add_formula(self):
        data = self.get_dataset()
        if data is None:
            return
        if data.table_format in EDITABLE_LEGACY_FIXED_VALUES:
            self.error("Edit the recovered values directly in this worksheet.")
            return
        name = simpledialog.askstring(ui("Calculated column"), ui("New or existing calculated column name"),
                                      parent=self.root)
        if not name:
            return
        name = name.strip()
        dialog = WorksheetFormulaDialog(self.root, data, name=name)
        if dialog.result is not None:
            before = self.worksheet_state(data)
            try:
                data.set_formula(name, dialog.result)
            except (ValueError, TypeError) as error:
                self.error(error)
            else:
                self.finish_worksheet_edit(data, before, "Edit formula")

    def enter_worksheet_formula(self, _event=None):
        dataset = self.get_dataset()
        cell = self.current_grid.active_cell if self.current_grid is not None else None
        if dataset is not None and cell is not None and dataset.can_enter_formula(cell[1]):
            column = cell[1]
            dialog = WorksheetFormulaDialog(self.root, dataset, column)
            if dialog.result is not None:
                before = self.worksheet_state(dataset)
                try:
                    dataset.set_worksheet_formula(column, dialog.result, replace_values=dialog.replace_values)
                except (ValueError, TypeError, OverflowError) as error:
                    self.error(error)
                else:
                    self.finish_worksheet_edit(dataset, before, "Edit formula")
            if self.current_grid is not None:
                self.current_grid.canvas.focus_set()
        return "break"

    def calculated_column_menu(self, event):
        grid = self.current_grid
        if self.pending is not None or grid is None or not self.selected or self.selected[0] != "data":
            return
        data = self.tables[self.active_data]
        _, column = grid.cell_at(event.x, event.y)
        if not data.can_freeze_worksheet_formula(column):
            return
        menu = self.calculated_column_popup
        menu.entryconfigure(0, command=lambda: self.freeze_worksheet_formula(column))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def freeze_worksheet_formula(self, column):
        data = self.get_dataset()
        if data is None or not data.can_freeze_worksheet_formula(column):
            return
        before = self.worksheet_state(data)
        try:
            data.freeze_worksheet_formula(column)
        except (ValueError, TypeError, OverflowError) as error:
            self.error(error)
        else:
            self.finish_worksheet_edit(data, before, tr("worksheet.formula.freeze"))

    def standalone(self, method):
        if self.pending is not None:
            self.error("Wait for the current calculation to finish.")
            return
        data = pd.DataFrame()
        dialog = AnalysisDialog(self.root, data, current=(method, {}), only=method)
        if dialog.result:
            try:
                report = analyse(method, data, dialog.result[1])
                tables = {}
                for name, table in report.tables.items():
                    if not isinstance(table.index, pd.RangeIndex):
                        table = table.rename_axis("Parameter").reset_index()
                    tables[name] = table
                self._add_tables(tables)
            except (ValueError, TypeError, OverflowError) as error:
                self.error(error)

    def new_graph(self):
        self.choose_analysis(only=GROUPS["Graphing"], prefer_worksheet_graph=True)

    def plot_function(self):
        """Tools → Plot a function. Works on an empty table too; a project without tables gets one after OK."""
        if self.pending is not None:
            self.error("Wait for the current calculation to finish.")
            return
        dataset = None
        if self.active_data is not None:
            dataset = self.get_dataset()
            if dataset is None:
                return
        frame = dataset.frame(mask_excluded=True) if dataset is not None else pd.DataFrame()
        dialog = AnalysisDialog(self.root, frame, current=(PLOT_FUNCTION, {}), only=PLOT_FUNCTION)
        if not dialog.result:
            return
        if dataset is None:
            title = self._unique_title("Function plot")
            self._add_tables({title: pd.DataFrame({"X": pd.Series(dtype=float)})})
            dataset = self.tables[title]
            self.active_data = title
        if len(dataset.analyses) >= 256:
            self.error("A table supports up to 256 analyses.")
            return
        self.start_analysis(Run(PLOT_FUNCTION, self.active_data, dialog.result[1]), frame,
                            result=dialog.processing_result)

    def power_planning(self):
        """Tools → Power and sample size…: a native result, attached to the active table or to an empty table.

        It works in a project without a data table, like Plot a function. The sheet, the optional power curve and
        its graph are an ordinary analysis, so they are saved with the project, reopened with their recipe and
        usable in layouts and with Use Result as Data.
        """
        if self.pending is not None:
            self.error("Wait for the current calculation to finish.")
            return
        dataset = None
        if self.active_data is not None:
            dataset = self.get_dataset()
            if dataset is None:
                return
        frame = dataset.frame(mask_excluded=True) if dataset is not None else pd.DataFrame()
        dialog = AnalysisDialog(self.root, frame, current=(POWER_METHOD, {}), only=POWER_METHOD)
        if not dialog.result:
            return
        if dataset is None:
            title = self._unique_title("Power analysis")
            self._add_tables({title: pd.DataFrame({"A": pd.Series(dtype=float)})})
            dataset = self.tables[title]
            self.active_data = title
        if len(dataset.analyses) >= 256:
            self.error("A table supports up to 256 analyses.")
            return
        self.start_analysis(Run(POWER_METHOD, self.active_data, dialog.result[1]), frame,
                            result=dialog.processing_result)

    def choose_analysis(self, only=None, *, prefer_worksheet_graph=False):
        current = (self.runs[self.selected[1]] if self.selected and self.selected[0] in {'result', 'graph'} else None)
        source = current.source if current is not None else None
        if source is not None:
            if self.pending is not None:
                self.error(tr('chain.wait'))
                return
            try:
                frame = self.input_frame(current)
            except ValueError as error:
                self.error(error)
                return
            table_format = frame.attrs.get('table_format', 'multivariable')
        else:
            dataset = self.get_dataset()
            if dataset is None:
                return
            frame = dataset.frame(mask_excluded=True)
            table_format = dataset.table_format
        if frame.empty:
            self.error("Enter some data first.")
            return
        preferred = None
        if prefer_worksheet_graph:
            preferred = {"column": COLUMN_GRAPH, "grouped": GROUPED_GRAPH,
                         "twoway": GROUPED_GRAPH, "two way": GROUPED_GRAPH,
                         "parts_of_whole": PARTS_GRAPH, "parts of whole": PARTS_GRAPH}.get(table_format.casefold())
        elif only is None and table_format.casefold() == "nested":
            preferred = preferred_nested_method(frame)
        dialog = self.chain_analysis_dialog(frame, title=self.active_data, source=source, only=only,
                                            current=(preferred, {}) if preferred else None)
        if dialog.result:
            self.submit_new_analysis(self.active_data, frame, dialog, only, source=source)

    def submit_new_analysis(self, title, frame, dialog, only=None, *, source=None):
        method, options = dialog.result
        dataset = self.tables[title]
        if source is None and len(dataset.analyses) - len(dataset.analysis_sources) >= 256:
            self.error("A table supports up to 256 analyses.")
            return
        if len(self.runs) >= MAX_ANALYSIS_NODES:
            self.error(tr("chain.node_budget"))
            return
        self.start_analysis(Run(method, title, options, source=source), frame, result=dialog.processing_result,
                            recovery=self.weighting_recovery(method, options, None, only))

    def _lognormal_one_way(self, run):
        """True when a confirmed one-way recipe asked for the lognormal model."""
        return (run.method == "One-way ANOVA"
                and run.options.get(lognormal_anova.DISTRIBUTION) == lognormal_anova.LOGNORMAL)

    @staticmethod
    def _pca_regression(run):
        """True when a confirmed PCA recipe explicitly asked for the principal component regression."""
        return run.method == "Principal component analysis" and run.options.get(PCR_ENABLE) is True

    @staticmethod
    def _cox_fit_diagnostics(run):
        """True when a confirmed Cox recipe asked for the scaled Schoenfeld residuals or the Cox–Snell diagnostics."""
        return run.method == COX and any(run.options.get(name) is True for name in COX_FIT_DIAGNOSTICS)

    def _keeps_failed_result(self, run):
        """Keep the last good result when a later edit cannot be calculated."""
        return (run.method in {REFERENCE_NORMALIZATION, SAVED_BINARY_LAYOUT} or LEGACY_PANEL_DATA in run.options
                or self._lognormal_one_way(run)
                or uses_planned_contrasts(run.method, run.options)
                or run.method in (FDR_METHOD, VARIANCE_RATIO, COMPETING_RISKS, RMST, INDEPENDENT_ROC, ANCOVA, RMCORR,
                                  META_ANALYSIS, NB2, WEIBULL_AFT, ORDINAL_LOGIT, precision_recall.METHOD, icc.METHOD,
                                  reshape.METHOD, WORKSHEET_JOIN, kmeans_stability.METHOD, logistic_validation.METHOD)
                or self._pca_regression(run) or uses_hierarchy_diagnostics(run.method, run.options)
                or cox_exact_run(run) or self._cox_fit_diagnostics(run)
                or (run.method in kmeans_options.METHODS
                    and run.options.get(kmeans_options.ALGORITHM) in kmeans_options.ITERATION_FIELDS)
                or run.method == COHEN_KAPPA
                or getattr(run, 'source', None) is not None
                or run.method == MEAN_PERMUTATION
                or getattr(run, 'uid', None) in getattr(self, '_chain_node_ids', ()))

    def _reopens_field_error(self, run):
        """Field errors reopen the dialog. Reference normalization keeps its own message path."""
        return (self._lognormal_one_way(run)
                or run.method in (FDR_METHOD, VARIANCE_RATIO, COMPETING_RISKS, RMST, INDEPENDENT_ROC, ANCOVA, RMCORR,
                                  META_ANALYSIS, NB2, WEIBULL_AFT, ORDINAL_LOGIT, precision_recall.METHOD, icc.METHOD,
                                  reshape.METHOD)
                or self._pca_regression(run)
                or cox_exact_run(run) or self._cox_fit_diagnostics(run)
                or run.method == COHEN_KAPPA
                or (run.method in kmeans_options.METHODS
                    and run.options.get(kmeans_options.ALGORITHM) in kmeans_options.ITERATION_FIELDS)
                or run.method == MEAN_PERMUTATION)

    def weighting_recovery(self, method, options, index, only=None):
        """Reopen the dialog when a field error is first known on the worker."""
        if method in kmeans_options.METHODS and options.get(kmeans_options.ALGORITHM) in kmeans_options.ITERATION_FIELDS:
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == COX and cox_is_exact(options):
            # Row, column and work limits, separation and refused outputs are known only on the worker.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method in CORRELATION_METHODS or method in (
                CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION, ROBUST_CURVE, COMPETING_RISKS, RMST, RMCORR, META_ANALYSIS, NB2, WEIBULL_AFT, ORDINAL_LOGIT,
                "Multifactor ANOVA", ANCOVA,
                REFERENCE_NORMALIZATION, HEAT_MAP, SUMMARY_ANOVA, SUMMARY_TTEST, rm_sphericity.METHOD, WORKSHEET_JOIN):
            # Rank, convergence, domain and layout field errors reopen the candidate dialog.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == MEAN_PERMUTATION:
            # Too few values after an edit, or a budget the new data exceed, reopen on the field.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if (method == "Multiple regression" and options.get("Family") == "Linear"
                and options.get(mlr_weighting.GAUSSIAN_WEIGHTING, mlr_weighting.UNWEIGHTED)
                != mlr_weighting.UNWEIGHTED):
            # A fixed Gaussian weight can become invalid after a data edit; the dialog reopens on its field.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == COHEN_KAPPA:
            # An edited or excluded cell can change the categories, so the order is fixed in the reopened dialog.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == "One-way ANOVA":
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method in (FDR_METHOD, VARIANCE_RATIO, INDEPENDENT_ROC, precision_recall.METHOD, icc.METHOD,
                      reshape.METHOD, kmeans_stability.METHOD, logistic_validation.METHOD):
            # A data edit can leave a sample with too few values or a bootstrap beyond its budget.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == "Principal component analysis" and options.get(PCR_ENABLE) is True:
            # Rank and degrees of freedom of the regression are known only after the fit, on the worker.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method == COX and any(options.get(name) is True for name in COX_FIT_DIAGNOSTICS):
            # A covariance or residual that stops being finite after a worksheet edit names its control.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if (method == "Interpolate a standard curve" and options.get("Curve") == "Nonlinear"
                and options.get(CALIBRATION_UNCERTAINTY, "None") not in (None, "None")):
            # A replicate count or query budget can fail only after the worksheet changes.
            return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)
        if method not in WEIGHTING_NOTE_METHODS or not uses_fitted_y(options.get("Weighting")):
            return None
        return AnalysisRecovery(self.active_project, index, self.runs[index] if index is not None else None, only)

    def recover_analysis(self, run, error, recovery):
        """Offer the candidate again with the failing field focused. False when its target is gone."""
        field = getattr(error, "field", None)
        if (field is None or recovery.project != self.active_project or run.title not in self.tables
                or (recovery.index is not None and (recovery.index >= len(self.runs)
                                                    or self.runs[recovery.index] is not recovery.confirmed))):
            return False
        kept = "No analysis was added." if recovery.index is None else "The confirmed analysis is kept."
        self.status.set(f"{run.method} could not be completed. {kept} Correct {field} and run again.")
        self.root.after_idle(lambda: self.reopen_analysis(run, error, recovery))
        return True

    def reopen_analysis(self, run, error, recovery):
        if recovery.project != self.active_project or run.title not in self.tables:
            return
        try:
            frame = self.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        message = (translate_global_error(error) if run.method == GLOBAL_CUSTOM_EQUATION
                   else translate_mlr_error(error) if run.method == "Multiple regression"
                   else translate_reference_error(error) if run.method == REFERENCE_NORMALIZATION
                   else translate_correlation_error(error) if run.method in CORRELATION_METHODS
                   else translate_calibration_error(error) if run.method == "Interpolate a standard curve"
                   else ui(str(error)) if run.method in (SUMMARY_ANOVA, SUMMARY_TTEST)
                   else translate_heat_map_error(error) if run.method == HEAT_MAP
                   else translate_independent_roc_error(error) if run.method == INDEPENDENT_ROC
                   else translate_precision_recall_error(error) if run.method == precision_recall.METHOD
                   else translate_icc_error(error) if run.method == icc.METHOD
                   else translate_join_error(error) if run.method == WORKSHEET_JOIN
                   else reshape_tk.format_error(error) if run.method == reshape.METHOD
                   else translate_logistic_validation_error(error) if run.method == logistic_validation.METHOD
                   else translate_kmeans_stability_error(error) if run.method == kmeans_stability.METHOD
                   else ui(str(error)) if run.method in kmeans_options.METHODS
                   else translate_cox_exact_error(error) if cox_exact_run(run)
                   else cox_message(error) if run.method == COX else str(error))
        formatted = (format_anova_error(error) if run.method == "Multifactor ANOVA"
                     else format_rm_error(error) if run.method == rm_sphericity.METHOD
                     else (lognormal_anova.format_error(error) or format_variance_error(error))
                     if run.method == "One-way ANOVA"
                     else describe_kappa_error(error) if run.method == COHEN_KAPPA
                     else describe_robust_error(error, error.field) if run.method == ROBUST_CURVE
                     else describe_competing_error(error) if run.method == COMPETING_RISKS
                     else describe_rmcorr_error(error) if run.method == RMCORR
                     else describe_meta_error(error) if run.method == META_ANALYSIS
                     else describe_nb2_error(error) if run.method == NB2
                     else describe_weibull_error(error) if run.method == WEIBULL_AFT
                     else describe_ordinal_error(error) if run.method == ORDINAL_LOGIT
                     else describe_rmst_error(error) if run.method == RMST
                     else format_fdr_error(error) if run.method == FDR_METHOD
                     else describe_permutation_error(error) if run.method == MEAN_PERMUTATION
                     else format_variance_ratio_error(error) if run.method == VARIANCE_RATIO
                     else format_ancova_error(error) if run.method == ANCOVA
                     else format_pca_error(error) if run.method == "Principal component analysis" else None)
        if formatted:
            message = formatted
        elif run.method in {"Interpolate a standard curve", WORKSHEET_JOIN}:
            pass
        elif error.field and error.field not in message:
            label = (tr("gfit.field." + error.field) if run.method == GLOBAL_CUSTOM_EQUATION
                     else tr(MLR_LABEL_KEYS[error.field]) if run.method == "Multiple regression"
                     and error.field in MLR_LABEL_KEYS
                     else field_caption_for_reference(error.field) if run.method == REFERENCE_NORMALIZATION
                     else ui(error.field) if run.method in (HEAT_MAP, SUMMARY_ANOVA, SUMMARY_TTEST, INDEPENDENT_ROC, COX,
                                                             precision_recall.METHOD, icc.METHOD, reshape.METHOD,
                                                             kmeans_stability.METHOD, logistic_validation.METHOD,
                                                             *kmeans_options.METHODS,
                                                             *CORRELATION_METHODS)
                     else error.field)
            if not label or label == "gfit.field." + error.field:
                label = error.field
            if label not in message:
                message = f"{label}: {message}"
        dialog = self.chain_analysis_dialog(frame, title=run.title, source=run.source,
                                            current=(run.method, run.options), only=recovery.only,
                                            initial_field=error.field, error=message,
                                            initial_pair=getattr(error, "pair", 0))
        if not dialog.result:
            kept = "No analysis was added." if recovery.index is None else "The confirmed analysis is kept."
            self.status.set(f"Change discarded. {kept}")
            return
        if recovery.index is None:
            self.submit_new_analysis(run.title, frame, dialog, recovery.only, source=run.source)
        elif self.runs[recovery.index] is recovery.confirmed:
            self.submit_edit(recovery.index, frame, dialog, recovery.only, source=run.source,
                             change_source=run.source != recovery.confirmed.source)

    def recalculate(self, index):
        if self.pending is not None:
            return
        run = self.runs[index]
        if self.refresh_chain_calculations([(run, None)], inputs_changed=False):
            return
        recovery = (self.weighting_recovery(run.method, run.options, index)
                    if run.method in {"Interpolate a standard curve", HEAT_MAP, FDR_METHOD, VARIANCE_RATIO,
                                      INDEPENDENT_ROC, ANCOVA, rm_sphericity.METHOD, precision_recall.METHOD,
                                      icc.METHOD, reshape.METHOD, WORKSHEET_JOIN, kmeans_stability.METHOD,
                                      logistic_validation.METHOD}
                    or self._pca_regression(run) or cox_exact_run(run) or self._cox_fit_diagnostics(run)
                    or uses_planned_contrasts(run.method, run.options) else None)
        self.start_analysis(run, self.tables[run.title].frame(mask_excluded=True), index, recovery=recovery)

    def edit_analysis(self, *, initial_field=None):
        if not self.selected or self.selected[0] not in {"result", "graph"}:
            self.error("Select an analysis or graph first.")
            return
        index = self.selected[1]
        run = self.runs[index]
        if run.method in {anova_comparison_plot.METHOD, anova_diagnostics.METHOD, anova_grouped_plot.METHOD}:
            self.format_graph()
            return
        if run.source is not None:
            if self.pending is not None:
                self.error(tr('chain.wait'))
                return
        elif self.get_dataset() is None:
            return
        if run.method in LEGACY_GRAPH_METHODS:
            self.error(ui("Use Format Graph for an imported XY graph, or Export for its original preview."))
            return
        try:
            frame = self.input_frame(run)
        except ValueError as error:
            self.error(error)
            return
        only = run.method if initial_field else None
        dialog = self.chain_analysis_dialog(frame, title=run.title, source=run.source,
                                            current=(run.method, run.options), only=only, initial_field=initial_field)
        if dialog.result:
            self.submit_edit(index, frame, dialog, only)

    def submit_edit(self, index, frame, dialog, only=None, *, source=None, change_source=False):
        run = self.runs[index]
        method, options = dialog.result
        if method == run.method:
            for key in (LEGACY_TITLE, LEGACY_NOTES, PAIRWISE_SECTION, SAVED_REPLICATE_DISPLAY,
                        pca_overlays.SAVED_APPEARANCE, PCA_SAVED_DIRECTIONS, pca_parallel_archive.ARCHIVE,
                        PCA_SAVED_VIEWPORT, kmeans_archive.ARCHIVE,
                        FIT_GRAPH_SPEC, FIT_INTERVAL_BAND, SURVIVAL_GRAPH, QC_REFERENCE, anova_grouped_plot.PRIMARY):
                if key in run.options:
                    options[key] = run.options[key]
            if options.get("Group") == run.options.get("Group") and "Group order" in run.options:
                options["Group order"] = run.options["Group order"]
            if method == XY_METHOD:
                for key in XY_RECIPE_KEYS:
                    if key in run.options and key not in options:
                        options[key] = run.options[key]
                options = prune_options(options)
                options["Series color"] = assign_colors(options.get("Y columns") or [], options.get("Series color"))
        if method != run.method and any(run.reference in layout.panels for layout in self.layouts):
            self.error("Change parameters for this method or create a new analysis for the layout.")
            return
        style = run.style
        if method == run.method == FREQUENCY:
            style = frequency_style(style, run.options, options)
        elif method == run.method == "Kaplan–Meier survival":
            style = survival_style(style, run.options, options)
        elif method == run.method == XY_METHOD:
            style = xy_style(style, options)
        self.start_analysis(Run(method, run.title, options, slot=run.slot, style=style,
                                uid=run.uid, source=source if change_source else run.source), frame, index,
                            result=dialog.processing_result,
                            recovery=self.weighting_recovery(method, options, index, only),
                            source_override=change_source)

    def pairwise_snapshot(self, run):
        """Resolve the comparison source of a graph on the UI thread: the worker gets a consistent copy."""
        settings, problem = read_pairwise(run.options)
        if settings is None:
            return None if problem is None else {"message": problem}
        problem = pairwise_graph_problem(run.method, run.options)
        if problem:
            return {"message": problem}
        recipes = self.tables[run.title].analyses if run.title in self.tables else []
        slot = settings["slot"]
        if slot == run.slot or slot >= len(recipes):
            return {"message": "The comparison source is no longer in this table. "
                               "Open Pairwise Comparisons to choose another source."}
        method, options = recipes[slot]
        if method != settings["method"]:
            return {"message": f"The comparison source is now {method}. Open Pairwise Comparisons to choose a source."}
        problem = pairwise_source_problem(run.method, run.options, method, options)
        if problem:
            return {"message": f"{problem} The graph is shown without comparisons."}
        source = next((other for other in self.runs if other.title == run.title and other.slot == slot), None)
        if source is not None and source.source != run.source:
            return {"message": "The comparison source analyzes a different input table. "
                               "Choose an analysis of this graph's input, or remove the comparisons."}
        # A stored result is current: editing data or the source clears it before anything reads it.
        tables = source.result.tables if source is not None and source.result is not None else None
        return {"settings": settings, "method": method, "options": deepcopy(options), "tables": tables,
                "key": (run.title, slot)}

    def compact_letter_display(self):
        """Insert → Compact Letter Display…: the Pairwise Comparisons dialog opened on Compact letters."""
        self.pairwise_comparisons(display=COMPACT_LETTERS)

    def pairwise_comparisons(self, display=None):
        """Insert → Pairwise Comparisons…: label pairs of a calculated graph with an analysis of the same table."""
        if not self.selected or self.selected[0] != "graph":
            self.error("Select a box, violin or column graph first.")
            return
        if self.pending is not None:
            self.error("Wait for the current calculation to finish.")
            return
        index = self.selected[1]
        run = self.runs[index]
        problem = (pairwise_graph_problem(run.method, run.options) if run.method not in LEGACY_GRAPH_METHODS
                   else "Pairwise comparisons are available on native box, violin and column graphs.")
        if problem:
            self.error(problem)
            return
        if run.result is None or run.result.figure is None or not run.result.figure.axes:
            self.error("Calculate the graph first.")
            return
        settings, _ = read_pairwise(run.options)
        sources = []
        for other in self.runs:
            if (other is run or other.title != run.title
                    or pairwise_source_problem(run.method, run.options, other.method, other.options)):
                continue
            detail = (f"Post-hoc: {other.options.get('Post-hoc')}" if other.method == "One-way ANOVA"
                      else f"Dunn: {other.options.get(DUNN_ADJUSTMENT, 'Bonferroni')}" if other.method == "Kruskal–Wallis"
                      else f"{other.options.get('First')} vs {other.options.get('Second')}")
            sources.append((other.slot, other.method, f"{other.name}  ·  {detail}  ·  analysis {other.slot + 1}"))
        if not sources and PAIRWISE_SECTION not in run.options:
            self.error("Analyze this table first with a one-way ANOVA with multiple comparisons, a Kruskal–Wallis "
                       "test with Dunn comparisons, or a paired t-test of two graphed columns. FDR is not used.")
            return
        if not self.settle_graph_draft("changing comparisons"):
            return
        frame = self.tables[run.title].frame(mask_excluded=True)
        endpoint = pairwise_endpoint(run.method)

        def load_rows(slot):
            source = next(other for other in self.runs if other.title == run.title and other.slot == slot)
            if source.result is None:
                # The same data revision as the graph: the dialog result is kept for the source sheet.
                source.result = self.compute(source, frame)
            return pairwise_rows(source.method, source.result.tables, source.options, endpoint)

        dialog = PairwiseDialog(self.root, sources, settings, pairwise_anchors(run.result.figure.axes[0]), load_rows,
                                display=display)
        if dialog.result is None:
            return
        action, record = dialog.result
        options = dict(run.options)
        if action == "remove":
            options.pop(PAIRWISE_SECTION, None)
        else:
            options[PAIRWISE_SECTION] = record
        if options == run.options:
            self.status.set(ui("Pairwise comparisons unchanged."))
            return
        self.start_analysis(Run(run.method, run.title, options, slot=run.slot, style=run.style), frame, index)

    def pairwise_dependents(self, run):
        """Graphs of the same table that read their comparisons from this analysis."""
        found = []
        for other in self.runs:
            if other is run or other.title != run.title or PAIRWISE_SECTION not in other.options:
                continue
            settings, _ = read_pairwise(other.options)
            if settings is not None and settings["slot"] == run.slot:
                found.append(other)
        return found

    @staticmethod
    def apply_pairwise(run, result, frame, pairwise):
        """On the worker: read the comparisons of the source and draw them on the graph."""
        if pairwise is None or result.figure is None or not result.figure.axes:
            sync_letters_table(result)
            return
        try:
            App._attach_pairwise(run, result, frame, pairwise)
        finally:
            # Compact letters add a Comparison letters sheet; any other state removes it.
            sync_letters_table(result)

    @staticmethod
    def _attach_pairwise(run, result, frame, pairwise):
        if "message" in pairwise:
            attach_pairwise(result.figure, (), None, message=pairwise["message"])
            return
        tables = pairwise["tables"]
        if tables is None:
            try:
                tables = analyse(pairwise["method"], frame, pairwise["options"]).tables
            except Exception as error:
                attach_pairwise(result.figure, (), None, message=f"The comparison source could not be calculated. {error}")
                return
        rows = pairwise_rows(pairwise["method"], tables, pairwise["options"], pairwise_endpoint(run.method))
        message = None if rows else "The comparison source has no valid P values for this graph."
        attach_pairwise(result.figure, rows, pairwise["settings"], message=message)

    @staticmethod
    def breaks_warning(figure, style):
        """A localized note when saved axis breaks are kept but cannot be drawn on ``figure``, otherwise None."""
        from analisi.axis_breaks_dialog import translate_breaks_error

        reason = axis_breaks_reason(figure) if figure is not None and (style or {}).get(AXIS_BREAKS) else None
        if not reason:
            return None
        return tr("axis_breaks.status.ignored", reason=translate_breaks_error(ValueError(reason)))

    @staticmethod
    def prepared_result(prepared, run):
        """The result a worker process computed for ``run``, None to compute it here, or its error raised."""
        outcome = prepared.get(id(run))
        if outcome is None:
            return None
        if outcome.error is not None:
            raise outcome.error
        return outcome.value

    @staticmethod
    def compute(run, frame, result=None, control=None, layout_data=None, pairwise=None, *, join_data=None):
        if isinstance(join_data, FieldError):
            raise join_data
        if result is None:
            if run.method == MONTE_CARLO_METHOD and control is not None:
                result = monte_carlo(frame, run.options, progress=control.report, cancel=control.cancel)
            elif run.method == kmeans_stability.METHOD and control is not None:
                result = kmeans_stability.analysis(frame, run.options, cancel=control.cancel, progress=control.report)
            elif run.method == logistic_validation.METHOD and control is not None:
                result = logistic_validation.analysis(frame, run.options, cancel=control.cancel, progress=control.report)
            elif run.method == XY_METHOD:
                result = xy_series(frame, run.options, left_scale=(run.style or {}).get("yscale", "linear"))
            else:
                result = analyse(run.method, frame, run.options, layout_data=layout_data,
                                 cancel=control.cancel if control is not None else None, join_data=join_data)
        if result.figure is not None and run.style:
            try:
                apply_style(result.figure, run.style)
            except ValueError as error:
                result.style_warning = str(error)
            else:
                result.style_warning = App.breaks_warning(result.figure, run.style)
        App.apply_pairwise(run, result, frame, pairwise)
        return result

    def edit_legacy_panel(self, index):
        if self.pending is not None:
            self.error("Wait for the current calculation before editing the layout.")
            return
        run = self.runs[index]
        edits = run.options.get(LEGACY_PANEL_EDITS, {})

        def prepare(changes):
            if changes == edits:
                return None
            options = dict(run.options)
            if changes:
                options[LEGACY_PANEL_EDITS] = changes
            else:
                options.pop(LEGACY_PANEL_EDITS, None)
            candidate = Run(run.method, run.title, options, slot=run.slot, style=run.style)
            return candidate, self.compute(candidate, self.tables[run.title].frame(),
                                           layout_data=self.layout_panel_data(run))

        dialog = LegacyPanelDialog(self.root, run.options[LEGACY_EDITABLE_PANELS], edits, prepare)
        if dialog.result is not None:
            candidate, result = dialog.result
            self.add_result(candidate, result, index)

    def export_current_layout_emf(self, index):
        from analisi.legacy_layout_edit import export_edited_layout

        run = self.runs[index]
        options = run.options
        try:
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".emf",
                                                initialfile="layout-current.emf",
                                                filetypes=[("EMF", "*.emf")])
            if path:
                export_edited_layout(path, options[LEGACY_PREVIEW], options.get(LEGACY_EDITABLE_PANELS),
                                     options.get(LEGACY_PANEL_EDITS), self.layout_panel_data(run))
                self.status.set(tr("interface.exported", name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def start_analysis(self, run, frame, index=None, *, result=None, recovery=None, source_override=False):
        if index is not None and self.runs[index] is not run:
            run.uid = self.runs[index].uid
            if run.label is None:
                run.label = self.runs[index].label
            if not source_override:
                run.source = self.runs[index].source
        if run.source is not None or getattr(self, '_chain_node_ids', ()):
            try:
                self.analysis_graph(replacement=(index, run) if index is not None else None,
                                    additional=run if index is None else None)
            except ValueError as error:
                self.error(error)
                return
        pairwise = self.pairwise_snapshot(run)
        if result is not None:
            self.add_result(run, self.compute(run, frame, result, pairwise=pairwise), index)
            return
        self.status.set(tr("interface.running", method=ui(run.method)))
        # A Monte Carlo study reports its blocks and stops between them when cancelled.
        parameter_profile = (run.method in ("Nonlinear regression", CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION)
                             and run.options.get(PARAM_CI_METHOD) == PARAM_CI_PROFILE)
        control = CalculationControl() if (parameter_profile or cancellable_run(run.method, run.options)) else None
        layout_data = self.layout_panel_data(run) if isinstance(run.options.get(LEGACY_PANEL_DATA), dict) else None
        extra = {"join_data": self.join_data(run)} if run.method == WORKSHEET_JOIN else {}
        self.pending = self.worker.submit(self.compute, run, frame, None, control, layout_data, pairwise, **extra)
        self.begin_calculation(control)
        self.update_worksheet_history_buttons()
        self.sync_inspector()
        if self.modern_workspace is not None:
            self.modern_workspace.refresh()
        self.root.after(60, lambda: self.poll(run, index, recovery))

    def poll(self, run, index, recovery=None):
        if not self.pending.done():
            self.show_calculation_progress(run.method)
            self.root.after(60, lambda: self.poll(run, index, recovery))
            return
        future, self.pending = self.pending, None
        cancelled = self.calculation is not None and self.calculation.cancel.is_set()
        self.end_calculation()
        try:
            if cancelled:
                raise MonteCarloCancelled
            reveal = index is None or (self.selected and self.selected[0] in RUN_VIEWS and self.selected[1] == index)
            self.add_result(run, future.result(), index, reveal=reveal)
        except (MonteCarloCancelled, ChainCancelled):
            # Nothing is recorded: a new study adds no recipe and an existing one keeps its last results.
            noun = ("analysis" if run.method in (COMPETING_RISKS, RMCORR, META_ANALYSIS, COX, COHEN_KAPPA,
                                                 MEAN_PERMUTATION, reshape.METHOD, icc.METHOD, precision_recall.METHOD,
                                                 WORKSHEET_JOIN, kmeans_stability.METHOD, logistic_validation.METHOD)
                    else "study")
            if index is None:
                detail = f"No {noun} was added."
            elif self.runs[index].result is not None:
                detail = "The last completed results are kept."
            else:
                detail = f"Open the {noun} to calculate again."
            if run.method == INDEPENDENT_ROC:
                detail = tr("iroc.kept_new" if index is None else "iroc.kept_result"
                            if self.runs[index].result is not None else "iroc.kept_none")
                self.status.set(tr("iroc.cancelled", kept=detail))
            elif cox_exact_run(run):
                self.status.set(tr("cox.exact.cancelled." + ("new" if index is None else "kept"
                                                            if self.runs[index].result is not None else "again")))
            else:
                self.status.set(f"{run.method} cancelled. {detail}")
        except Exception as error:
            shown = (translate_correlation_error(error) if run.method in CORRELATION_METHODS
                     else describe_kappa_error(error) if run.method == COHEN_KAPPA
                     else format_fdr_error(error) or error if run.method == FDR_METHOD
                     else describe_permutation_error(error) if run.method == MEAN_PERMUTATION
                     else format_variance_ratio_error(error) or error if run.method == VARIANCE_RATIO
                     else describe_competing_error(error) if run.method == COMPETING_RISKS
                     else translate_independent_roc_error(error) if run.method == INDEPENDENT_ROC
                     else translate_precision_recall_error(error) if run.method == precision_recall.METHOD
                     else translate_icc_error(error) if run.method == icc.METHOD
                     else translate_logistic_validation_error(error) if run.method == logistic_validation.METHOD
                     else translate_kmeans_stability_error(error) if run.method == kmeans_stability.METHOD
                     else translate_join_error(error) if run.method == WORKSHEET_JOIN
                     else reshape_tk.format_error(error) if run.method == reshape.METHOD
                     else format_ancova_error(error) or error if run.method == ANCOVA
                     else describe_rmcorr_error(error) if run.method == RMCORR
                     else describe_meta_error(error) if run.method == META_ANALYSIS
                     else translate_cox_exact_error(error) if cox_exact_run(run)
                     else describe_nb2_error(error) if run.method == NB2
                     else describe_weibull_error(error) if run.method == WEIBULL_AFT
                     else describe_ordinal_error(error) if run.method == ORDINAL_LOGIT
                     else describe_rmst_error(error) if run.method == RMST else error)
            # Manual recalculation uses the confirmed Run itself. A failed
            # candidate with edited options is a different object and must not
            # invalidate the still-current confirmed analysis.
            if (index is not None and index < len(self.runs) and self.runs[index] is run
                    and self._keeps_failed_result(run) and run.result is not None):
                run.calculation_error = str(error)
                if self.selected == ("result", index) or self.selected == ("graph", index):
                    self.show(*self.selected)
            if recovery is None or not self.recover_analysis(run, error, recovery):
                self.status.set(ui("Analysis could not be completed."))
                self.error(shown)
        finally:
            self.update_worksheet_history_buttons()
            self.sync_inspector()

    def add_result(self, run, result, index=None, *, reveal=True):
        run.result = result
        run.calculation_error = None
        recipes = self.tables[run.title].analyses
        new_run = index is None
        dependents = []
        if index is None:
            run.slot = len(recipes)
            self.runs.append(run)
            recipes.append((run.method, run.options))
            self.dirty = True
            index = len(self.runs) - 1
        elif self.runs[index] is not run:
            run.uid = self.runs[index].uid
            if run.label is None:
                run.label = self.runs[index].label
            self.runs[index] = run
            recipes[run.slot] = run.method, run.options
            self.dirty = True
            dependents = self.pairwise_dependents(run)
        self.sync_analysis_links(persist=True)
        if not new_run:
            dependents = list({other.uid: other for other in
                               [*dependents, *self.chain_dependents(run)]}.values())
        self.refresh_navigator()
        if reveal:
            if self.gallery is None or new_run:
                view = "graph" if self.selected == ("graph", index) else run_view(run.method)
                self.show(view, index)
            else:
                self.gallery_refresh = True
        if not reveal and self.modern_workspace is not None:
            self.modern_workspace.refresh()
        status = f"{run.method} complete."
        if result.style_warning:
            status += f" Saved graph settings need review. {result.style_warning}"
        elif shape_warning := self.shape_warning(result.figure, run.style):
            status += f" {shape_warning}"
        if warning := pairwise_warning(result.figure):
            status += f" {warning}"
        self.status.set(status)
        if dependents:
            # Graphs that label pairs with this analysis are recalculated from the new source options.
            if self.pending is None:
                frame = self.tables[run.title].frame(mask_excluded=True)
                self.refresh_calculations([(graph, frame) for graph in dependents])
            else:
                for graph in dependents:
                    graph.result = None

    def save(self, as_new=False):
        if not self.settle_graph_draft("saving"):
            return False
        self.sync_analysis_links(persist=True)
        if self.current_grid is not None and self.pending is None:
            self.current_grid.commit_edit()
        if self.current_info is not None:
            self.current_info.notes_changed()
        if not self.tables and not self.info_sheets and not self.dirty:
            return False
        path = self.path if not as_new else None
        if not path:
            path = filedialog.asksaveasfilename(defaultextension=".alab",
                                                filetypes=[(tr("prompt.project_filetype"), "*.alab")])
        if not path:
            return False
        path = Path(path)
        if path.suffix.lower() != ".alab":
            self.error(tr("error.alab_name"))
            return False
        try:
            existing = self.open_project_for_path(path)
            if existing is not None and existing != self.active_project:
                self.error(tr("error.open_elsewhere"))
                return False
            save_project(path, self.tables, layouts=self.layouts, info_sheets=tuple(self.info_sheets.values()))
        except (ValueError, OSError, TypeError) as error:
            self.error(error)
            return False
        self.path = Path(path)
        self.dirty = False
        self.status.set(tr("status.saved", name=self.path.name))
        return True

    def stale_calculation_note(self, ref=None):
        """Keep a retained result visibly distinct from results of the current data."""
        ref = ref or self.selected
        if ref is None:
            return None
        kind, key = ref
        runs = (self.layout_runs(self.layouts[key]) if kind == "layout"
                else [self.runs[key]] if kind in {"result", "graph", "saved-layout"} else [])
        failures = [(translate_message(run.calculation_error, 'fdr.error.') if run.method == FDR_METHOD
                     else translate_message(run.calculation_error, 'variance.ratio.error.')
                     if run.method == VARIANCE_RATIO
                     else translate_permutation_error(run.calculation_error) if run.method == MEAN_PERMUTATION
                     else translate_message(run.calculation_error, 'anova.lognormal.error.')
                     if run.method == "One-way ANOVA"
                     else translate_kappa_error(run.calculation_error) if run.method == COHEN_KAPPA
                     else translate_competing_error(run.calculation_error) if run.method == COMPETING_RISKS
                     else translate_independent_roc_error(run.calculation_error) if run.method == INDEPENDENT_ROC
                     else translate_precision_recall_error(run.calculation_error) if run.method == precision_recall.METHOD
                     else translate_icc_error(run.calculation_error) if run.method == icc.METHOD
                     else planned_contrasts.localized(run.calculation_error)
                     if uses_planned_contrasts(run.method, run.options)
                     else translate_logistic_validation_error(run.calculation_error)
                     if run.method == logistic_validation.METHOD
                     else translate_kmeans_stability_error(run.calculation_error)
                     if run.method == kmeans_stability.METHOD
                     else translate_join_error(run.calculation_error) if run.method == WORKSHEET_JOIN
                     else reshape_tk.format_error(run.calculation_error) if run.method == reshape.METHOD
                     else translate_message(run.calculation_error, 'ancova.error.', {"field": ui})
                     if run.method == ANCOVA
                     else translate_meta_error(run.calculation_error) if run.method == META_ANALYSIS
                     else translate_cox_exact_error(run.calculation_error) if cox_exact_run(run)
                     else cox_message(run.calculation_error) if run.method == COX
                     else translate_nb2_error(run.calculation_error) if run.method == NB2
                     else translate_weibull_error(run.calculation_error) if run.method == WEIBULL_AFT
                     else translate_ordinal_error(run.calculation_error) if run.method == ORDINAL_LOGIT
                     else translate_rmst_error(run.calculation_error) if run.method == RMST
                     else translate_reference_error(run.calculation_error))
                    for run in runs if run.calculation_error]
        return tr("reference.stale_result", error="; ".join(failures)) if failures else None

    def require_current_calculation(self):
        if note := self.stale_calculation_note():
            self.error(note)
            return False
        return True

    def export(self):
        if not self.selected:
            self.error("Select a table, result or graph to export.")
            return
        if not self.require_current_calculation():
            return
        if not self.settle_graph_draft("exporting"):
            return
        kind, key = self.selected
        try:
            if kind == "info":
                self.current_info.notes_changed()
                sheet = self.info_sheets[key]
                path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Info text", "*.txt")])
                if path:
                    lines = [f"Info sheet · {sheet.title}", "", "Constants"]
                    for name, value in sheet.fields:
                        lines.extend(f"• {line}" for line in f"{name} = {value}".splitlines())
                    lines.extend(["", "Notes", *(f"> {line}" for line in sheet.notes.splitlines())])
                    Path(path).write_text("\n".join(lines).expandtabs(4) + "\n", encoding="utf-8")
            elif kind in {"graph", "layout", "saved-layout"}:
                run = self.runs[key] if kind != "layout" else None
                original = (run is not None and run.method in {SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT}
                            and LEGACY_PREVIEW in run.options)
                editable_emf = (run is not None and run.method == SAVED_EDITABLE_GRAPH
                                and (self.tables[run.title].table_format == EDITABLE_LEGACY_EMF
                                     or LIMIT_SOURCE in (run.options.get(LEGACY_GRAPH_STYLE) or {})))
                figure = self.layout_figure if run is None else run.result.figure if run.result else None
                filetypes = [("PNG image", "*.png"), ("SVG", "*.svg"), ("PDF", "*.pdf")] if figure else []
                original_suffix = None
                if editable_emf:
                    original_suffix = ".emf"
                    filetypes.insert(0, (ui("Edited imported vector image"), "*.emf"))
                elif original:
                    preview = run.options[LEGACY_PREVIEW]
                    preview_format = preview.get("format") if isinstance(preview, dict) else None
                    if preview_format in ("emf", "pdf"):
                        original_suffix = f".{preview_format}"
                        filetypes = [item for item in filetypes if item[1] != f"*{original_suffix}"]
                        filetypes.insert(0, (ui("Original imported vector image"), f"*{original_suffix}"))
                if not filetypes:
                    raise ValueError("Open the graph or calculate the layout before exporting.")
                edited_page = (run is not None and run.method == SAVED_BINARY_LAYOUT
                               and (run.options.get(LEGACY_PANEL_EDITS) or run.options.get(LEGACY_PANEL_DATA)))
                path = filedialog.asksaveasfilename(defaultextension=".png" if edited_page else original_suffix or ".png",
                                                    filetypes=filetypes)
                if path and original_suffix and Path(path).suffix.lower() == original_suffix:
                    from analisi.legacy_binary_graphs import validate_binary_graph

                    preview = run.options[LEGACY_PREVIEW]
                    if editable_emf:
                        from analisi.legacy_emf_edit import edit_emf_preview

                        frame = self.tables[run.title].frame(mask_excluded=True)
                        preview = edit_emf_preview(frame, run.options[LEGACY_GRAPH_STYLE], preview)
                    Path(path).write_bytes(validate_binary_graph(preview, layout=run.method == SAVED_BINARY_LAYOUT))
                elif path and kind == "layout":
                    fmt = Path(path).suffix[1:].lower()
                    if fmt in {"pdf", "svg"}:
                        self.export_vector_layout(self.layouts[key], path, {"format": fmt})
                    else:
                        self.layout_rendering(self.layouts[key]).savefig(path, dpi=300)
                elif path and figure is not None:
                    if (paper := imported_paper(run)) is None:
                        figure.savefig(path, dpi=300)
                    else:
                        from analisi.figure_export import export_figure

                        export_figure(figure, path, {"format": Path(path).suffix[1:].lower()}, size_inches=paper)
                elif path:
                    raise ValueError("Open the graph before exporting a rendered image.")
            else:
                if kind == "data":
                    frame, use_index = self.tables[key].frame(mask_excluded=True), False
                else:
                    result = self.runs[key].result
                    if result is None:
                        raise ValueError("Calculate the analysis before exporting.")
                    sheets = list(result.tables.values())
                    frame, use_index = sheets[self.result_tabs.index("current")], True
                path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
                if path:
                    safe_csv(path, frame, index=use_index)
            if path:
                self.status.set(tr("interface.exported", name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def export_with_options(self):
        """File → Export with options…: publication export of a native graph or layout figure."""
        if not self.selected or self.selected[0] not in {"graph", "layout", "saved-layout"}:
            self.error("Select a calculated graph or layout to export with options.")
            return
        if not self.require_current_calculation():
            return
        if not self.settle_graph_draft("exporting"):
            return
        kind, key = self.selected
        run = self.runs[key] if kind != "layout" else None
        figure = self.layout_figure if run is None else run.result.figure if run.result else None
        if figure is None or not figure.axes:
            self.error("Export with options is available for calculated native graphs and layouts. "
                       "Imported graphs and layouts keep their original export.")
            return
        from analisi.figure_export import check_destination, export_figure
        from analisi.figure_export_dialog import FORMAT_NAMES, FigureExportDialog

        layout = self.layouts[key] if kind == "layout" else None
        layout_size = page_size(layout.columns, len(layout.panels), layout.paper) if layout is not None else None
        paper = imported_paper(run)
        dialog = FigureExportDialog(self.root, paper or tuple(figure.get_size_inches()),
                                    raster_panels=kind == "saved-layout" and paper is None,
                                    layout_size=layout_size)
        settings = dialog.result
        if settings is None:
            return
        fmt = settings["format"]
        label = next(name for name, value in FORMAT_NAMES.items() if value == fmt)
        suffixes = {"tiff": "*.tif *.tiff"}.get(fmt, f"*.{fmt}")
        try:
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".tif" if fmt == "tiff" else f".{fmt}",
                                                filetypes=[(f"{label} image" if fmt in {"png", "tiff"} else label, suffixes)])
            if not path:
                return
            check_destination(path, fmt)
            if layout is not None and fmt in {"pdf", "svg"}:
                self.export_vector_layout(layout, path, settings)
            elif layout is not None:
                export_figure(self.layout_rendering(layout, transparent=settings["transparent"]), path, settings)
            else:
                export_figure(figure, path, settings, size_inches=paper)
            self.status.set(tr("interface.exported", name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def pdf_bundle_sheets(self):
        """Ready native graphs and layouts of the active project, plus notes on the sheets left out."""
        from analisi.pdf_bundle_dialog import BundleEntry

        def raster(figure):
            return bool(figure.images) or any(axes.images for axes in figure.axes)

        entries, stale, imported = [], [], []
        for _, sheets, _, _ in self.sheet_sections():
            for name, ref in sheets:
                kind, key = ref
                if kind == "graph":
                    run = self.runs[key]
                    if run.method in LEGACY_GRAPH_METHODS:
                        imported.append(name)
                    elif (not run.calculation_error and run.result is not None
                          and run.result.figure is not None and run.result.figure.axes):
                        figure = run.result.figure
                        entries.append(BundleEntry(ref, "Graph", name, tuple(figure.get_size_inches()), raster(figure)))
                    else:
                        stale.append(name)
                elif kind == "layout":
                    layout = self.layouts[key]
                    runs = self.layout_runs(layout)
                    if runs and all(run.result and run.result.figure and not run.calculation_error for run in runs):
                        entries.append(BundleEntry(ref, "Layout", name, page_size(layout.columns, len(runs), layout.paper),
                                                   any(raster(run.result.figure) for run in runs)))
                    else:
                        stale.append(name)
                elif kind == "saved-layout":
                    imported.append(name)
        notes = []
        if stale:
            notes.append(tr("pdf.stale", names=", ".join(stale)))
        if imported:
            notes.append(tr("pdf.imported", names=", ".join(imported)))
        return entries, notes

    def export_pdf_bundle(self):
        """File → Export multiple sheets to PDF…: selected native graphs and layouts as the pages of one PDF."""
        if self.pending is not None:
            self.error(tr("pdf.wait"))
            return
        if not self.settle_graph_draft("exporting"):
            return
        entries, notes = self.pdf_bundle_sheets()
        if not entries:
            self.error(" ".join([tr("pdf.empty"), *notes]))
            return
        from analisi.figure_export import check_destination, export_pdf_bundle
        from analisi.pdf_bundle_dialog import PdfBundleDialog

        dialog = PdfBundleDialog(self.root, entries, notes)
        if dialog.result is None:
            return
        by_ref = {entry.ref: entry for entry in entries}
        chosen = [by_ref[ref] for ref in dialog.result["refs"]]
        try:
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
            if not path:
                return
            check_destination(path, "pdf")
            figures = []
            for entry in chosen:
                kind, key = entry.ref
                if kind == "graph":
                    figures.append(self.runs[key].result.figure)
                else:
                    figures.append(self.layout_pdf_page(self.layouts[key]))
            export_pdf_bundle(figures, path, dialog.result["settings"], [entry.label for entry in chosen])
            pages = tr("pdf.one_page") if len(figures) == 1 else tr("pdf.many_pages", count=len(figures))
            self.status.set(tr("pdf.exported", pages=pages, name=Path(path).name))
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def error(self, error):
        messagebox.showerror("Trama", str(error), parent=self.root)

    def choose_theme(self):
        dialog = ThemeDialog(self.root, config_path(), error=self.error)
        if dialog.saved:
            self.status.set(tr("theme.saved"))

    def choose_processes(self):
        """Settings → Multicore calculation…: applies at once; the pool is rebuilt on the next calculation."""
        dialog = ProcessesDialog(self.root, config_path(), error=self.error)
        if dialog.saved:
            parallel.configure(dialog.result)
            self.status.set(tr("processes.saved", count=parallel.process_count()))
        return dialog.result

    def choose_language(self):
        """Edit → Language…: store the preference for the next start; the open session is untouched."""
        dialog = LanguageDialog(self.root, config_path(), error=self.error)
        if dialog.result is None:
            self.status.set(tr("language.unchanged"))
        elif dialog.saved:
            self.status.set(tr("language.saved"))
        return dialog.result

    def confirm_saved(self):
        if not self.dirty:
            return True
        name = self.projects[self.active_project].title
        result = messagebox.askyesnocancel(tr("prompt.unsaved_title"), tr("prompt.save_changes", name=name),
                                           parent=self.root)
        return result is False or (result is True and self.save())

    def close(self):
        if not self.prepare_project_change():
            return
        original = self.active_project
        self.projects[original].capture(self)
        for key, project in self.projects.items():
            if project.dirty and (not self.switch_project(key) or not self.confirm_saved()):
                self.switch_project(original)
                return
        self.worker.shutdown(wait=False)
        parallel.shutdown()
        self.root.destroy()


def smoke(root, app, directory, legacy_reference=None):
    from analisi.distribution_formulas_smoke import drive_formula_editor
    import json
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    from zipfile import ZipFile

    from analisi.clipboard_smoke import WindowsClipboardFixture
    from analisi.unequal_anova_smoke import check_unequal_anova

    directory.mkdir(parents=True, exist_ok=True)
    if os.environ.get("TRAMASTAT_SMOKE_TRACE"):
        import faulthandler
        trace_stream = (directory / "thread-stacks.txt").open("w", encoding="utf-8")
        faulthandler.dump_traceback_later(45, repeat=True, file=trace_stream)
        def close_trace(event):
            if event.widget is root:
                faulthandler.cancel_dump_traceback_later()
                trace_stream.close()
        root.bind("<Destroy>", close_trace, add="+")
    errors = []
    app.error = lambda error: errors.append(str(error))

    def wait_for_calculation():
        deadline = time.monotonic() + 25
        while app.pending is not None:
            if time.monotonic() > deadline:
                raise TimeoutError("Analysis did not complete")
            root.update()
            time.sleep(.02)
        assert not errors, errors

    def capture(window, name):
        if sys.platform == "win32":
            from ctypes import byref, sizeof, windll
            from ctypes.wintypes import HWND, RECT

            from PIL import ImageGrab

            window.update_idletasks()
            window.update()
            time.sleep(.12)
            handle = int(window.wm_frame(), 0)
            frame = RECT()
            # Capture the visible frame including Windows' native menu bar.
            if windll.dwmapi.DwmGetWindowAttribute(HWND(handle), 9, byref(frame), sizeof(frame)) == 0:
                image = ImageGrab.grab(bbox=(frame.left, frame.top, frame.right, frame.bottom))
            else:
                image = ImageGrab.grab(window=handle)
            image.save(directory / name)
        elif os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS") and shutil.which("import"):
            import subprocess

            window.update_idletasks()
            window.update()
            time.sleep(.2)
            subprocess.run(["import", "-window", "root", str(directory / name)], check=True, timeout=30)

    windows_clipboard = None
    if sys.platform == "win32":
        windows_clipboard = WindowsClipboardFixture(app.worker, root.update, directory / "clipboard-helper.log")

    def put_clipboard(text):
        if windows_clipboard is not None:
            # Discard an earlier process's formats before setting a fresh fixture.
            # The external process still supplies the actual data under test.
            root.clipboard_clear()
            root.update()
            windows_clipboard.put(text)
        else:
            root.clipboard_clear()
            root.clipboard_append(text)

    def get_clipboard():
        if windows_clipboard is not None:
            return windows_clipboard.get()
        return root.clipboard_get()

    def page_button(text):
        pending, found = [app.page], None
        while pending and found is None:
            widget = pending.pop(0)
            if isinstance(widget, ttk.Button) and widget.cget("text") == text:
                found = widget
            pending.extend(widget.winfo_children())
        assert found is not None, text
        return found

    def click_cell(grid, row, column, sequence="<ButtonPress-1>"):
        left, top, right, bottom = grid.cell_box(row, column)
        x = int((left + right) / 2 - grid.canvas.canvasx(0))
        y = int((top + bottom) / 2 - grid.canvas.canvasy(0))
        grid.canvas.event_generate(sequence, x=x, y=y)
        root.update()

    def check_workspace_setup():
        setup = next(child for child in app.page.winfo_children() if isinstance(child, TableSetup))
        assert not app.ribbon.winfo_ismapped()
        capture(root, "window-worksheet-options.png")
        setup.mode.set(True)
        setup.refresh()
        assert setup.preview.item(setup.preview.get_children()[0], "values") == ("0.1", "2.4", "2.1")
        capture(root, "window-worksheet-setup.png")
        setup.mode.set(True)
        setup.refresh()
        setup.example_list.selection_set("example:2")
        setup.choose_example()
        assert setup.selection()[0].kind == "XY with precomputed error"
        root.update_idletasks()
        assert setup.chart.winfo_rootx() + setup.chart.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        last_row = setup.preview.get_children()[-1]
        _, top, _, height = setup.preview.bbox(last_row)
        assert top + height <= setup.preview.winfo_height()
        capture(root, "window-worksheet-examples.png")
        setup.xy_format.set(next(iter(XY_FORMATS)))
        setup.refresh()
        setup.xy_format.set("Replicates in side-by-side subcolumns")
        template, use_sample = setup.selection()
        assert "Control [2]" in table_frame(template, use_sample)
        setup.mode.set(False)
        setup.dataset_count.set("1")
        setup.replicate_count.set("256")
        setup.refresh()
        blank, sample = setup.selection()
        assert not sample and len(blank.columns) == 258 and blank.columns[-1] == "Control [256]"
        setup.dataset_count.set("3")
        setup.replicate_count.set("3")
        setup.row_titles.set(False)
        setup.refresh()
        assert setup.selection()[0].columns[:2] == ("X", "Control [1]")
        setup.row_titles.set(True)
        setup.refresh()
        blank, sample = setup.selection()
        assert blank.columns[:2] == ("Row title", "X") and blank.columns[-1] == "Series 3 [3]"
        assert setup.preview_note.cget("text") == "Preview shows 8 of 11 columns"
        root.update()
        assert setup.selection() == (blank, sample)
        assert setup.preview.winfo_ismapped() and setup.preview_note.winfo_ismapped()
        capture(root, "window-xy-setup.png")
        app.create_worksheet(blank, sample)
        grid = app.current_grid
        assert grid.row_titles and grid.active_cell == (0, 1)
        app.edit_cell(0, 0, "Sample A")
        app.edit_cell(1, 0, "0012")
        grid = app.current_grid
        grid.select((0, 1))
        put_clipboard("0,1\t2,4\t2,6\t2,5\t2,1\t2,7\t2,4\r\n"
                      "1,0\t4,1\t4,5\t4,3\t5,3\t5,9\t5,6")
        app.paste_selection()
        xy = app.tables["XY replicates"]
        assert xy.raw.iloc[:2, 0].tolist() == ["Sample A", "0012"]
        np.testing.assert_allclose(xy.raw.iloc[0, 1:8].astype(float), [0.1, 2.4, 2.6, 2.5, 2.1, 2.7, 2.4])
        assert pd.isna(xy.raw.iat[0, 8])
        capture(root, "window-xy-worksheet.png")
        xy_path = directory / "xy-row-titles.alab"
        save_project(xy_path, {"XY": xy})
        restored = load_project(xy_path)["XY"]
        assert restored.table_format == xy.table_format
        pd.testing.assert_frame_equal(restored.raw, xy.raw, check_dtype=False)
        app.tables.pop("XY replicates")
        app.selected = None
        app.home()
        setup = next(child for child in app.page.winfo_children() if isinstance(child, TableSetup))
        setup.mode.set(True)
        setup.types.selection_clear(0, "end")
        setup.types.selection_set(2)
        setup.refresh()
        app.create_worksheet(*setup.selection())
        table = app.tables["Grouped example"]
        assert table.table_format == "grouped"
        assert table.raw.iloc[0].tolist() == ["Week 1", 4.1, 4.4, 5.6, 5.9]
        geometry = root.geometry()
        root.geometry("820x570")
        root.update()

        def check_visible_commands(labels):
            # The selected font can raise the window's minimum above 820 px.
            # Check the actual visible viewport, including the screen bound.
            assert root.winfo_width() <= root.winfo_screenwidth()
            edge = root.winfo_rootx() + root.winfo_width()
            for label in labels:
                button = app.ribbon.buttons[label]
                assert button.winfo_ismapped() and button.winfo_rootx() + button.winfo_width() <= edge, label

        if ui_theme.is_modern():
            for tab, labels in (("file", ("New",)), ("home", ("Paste", "Analyze…", "New graph…", "Export"))):
                assert app.ribbon.tabs[tab].winfo_ismapped(), tab
                app.ribbon.tabs[tab].invoke()
                root.update()
                check_visible_commands(labels)
        else:
            check_visible_commands(("New", "Paste", "Analyze…", "Layout", "Export"))
        expected_sections = (["Data Tables", "Info", "Results", "Graphs", "Layouts"] if ui_theme.is_modern() else
            ["Family", "Search results", "Data + Results", "Data Tables", "Info", "Results", "Graphs", "Layouts"])
        assert [app.nav.item(node, "text") for node in app.nav.get_children()] == expected_sections
        assert len(app.nav_actions) == 5
        app.toggle_navigator()
        assert str(app.navigator) not in app.workspace.panes()
        app.toggle_navigator()
        assert str(app.navigator) in app.workspace.panes()
        root.geometry(geometry)
        root.update()
        app.tables.pop("Grouped example")
        app.selected = None
        app.active_data = None
        app.history.clear()
        app.history_position = -1

    def check_info_workflow(reference):
        if reference is not None and (reference / "ec-proliferation.pzf").is_file():
            imported = []
            load_tables(reference / "ec-proliferation.pzf", info_sheets=imported)
            assert [sheet.title for sheet in imported] == ["Project info 1", "alles Project info 1"]
            assert all(sheet.fields[0] == ("Experiment Date", "jul-15-2013") for sheet in imported)

        study = "Dose response"
        seed = directory / "info-workflow.alab"
        save_project(seed, {study: Dataset(pd.DataFrame({"Dose": [1, 2], "Response": [10, 20]}))})
        app.import_file(seed)
        if reference is not None and (reference / "il33-s3.pzf").is_file():
            app.import_file(reference / "il33-s3.pzf")
            app.show_section("info")
            notes = app.current_info.notes.get("1.0", "end-1c")
            assert notes.startswith("GR-1 depletion on d-1 with 350µg")
            assert notes.count("\n") == 5 and "Verdünnung für mMCPT-1 ELISA 1:20" in notes
            capture(root, "window-imported-info.png")
            app.current_info.notes.insert("end", "\nReviewed in TramaStat.")
            app.path = directory / "legacy-info.alab"
            assert app.save()
            app.import_file(app.path)
            app.show_section("info")
            assert app.current_info.notes.get("1.0", "end-1c") == notes + "\nReviewed in TramaStat."
            app.import_file(seed)

        def details(dialog):
            dialog.title_field.delete(0, "end")
            dialog.title_field.insert(0, "Experiment details")
            dialog.scope.current(1)

        drive_dialog(InfoDetails, details)
        app.new_info()
        assert app.selected[0] == "info"
        uid = app.selected[1]
        editor = app.current_info
        assert editor.sheet.table == study and editor.sheet.title == "Experiment details"
        editor.edit(1, 1, "007")
        editor.edit(3, 1, "Dose–response validation")
        editor.edit(4, 1, "Lab team")
        editor.grid.select((6, 0), reveal=True)
        root.update()
        put_clipboard("Dilution factor\t2,5\r\nBuffer lot\tA-203\r\n")
        editor.paste()
        editor.grid.select((7, 0), reveal=True)
        editor.move_row(-1)
        assert editor.sheet.fields[6:] == (("Buffer lot", "A-203"), ("Dilution factor", "2,5"))
        editor.notes.insert("end", "Prepared 2 replicates per dose.\n\nStock solutions were stored at 4 °C.")
        editor.notes_changed()
        editor.notes.focus_force()
        root.update()
        editor.notes.tag_add("sel", "1.0", "1.8")
        editor.notes.event_generate("<Control-b>")
        editor.notes.tag_remove("sel", "1.0", "end")
        editor.notes.tag_add("sel", "3.0", "3.15")
        editor.notes.event_generate("<Control-i>")
        editor.notes.tag_remove("sel", "1.0", "end")
        note_styles = editor.sheet.note_styles
        assert note_styles[0] == (0, 8, 1) and note_styles[1][2] == 2
        app.tables[study].set_formula("Adjusted", '=Response * INFO("Dilution factor")')
        assert app.tables[study].frame()["Adjusted"].tolist() == [25, 50]
        editor.edit(7, 1, "3")
        assert app.tables[study].frame()["Adjusted"].tolist() == [30, 60]
        if ui_theme.is_modern():
            assert ("info", uid) in [ref for _, ref in app.family_sheets()]
            assert not app.family_button.instate(['disabled'])
        else:
            assert ("info", uid) in [app.nodes.get(child) for node in app.nav.get_children("section:Family")
                                     for child in app.nav.get_children(node)]
        capture(root, "window-info-sheet.png")
        assert app.save()
        app.import_file(seed)
        app.show_section("info")
        assert app.selected == ("info", uid)
        assert app.current_info.sheet.fields[1] == ("Experiment ID", "007")
        assert "4 °C" in app.current_info.notes.get("1.0", "end-1c")
        assert app.current_info.sheet.note_styles == note_styles
        assert app.tables[study].frame()["Adjusted"].tolist() == [30, 60]

    def check_worksheet_statistics():
        title = "Responses by cohort"
        path = directory / "worksheet-statistics.alab"
        source = pd.DataFrame({
            "Response": [10, 40, 20, 60, 30, 80],
            "Visit": [1, 2, 3, 1, 2, 3],
            "Cohort": ["A", "B", "A", "B", "A", "B"],
        })
        save_project(path, {title: Dataset(source)})
        app.import_file(path)
        recipes = {
            "Cumulative response": "SUM(Response) OVER Cohort ORDER BY Visit ROWS UNBOUNDED PRECEDING",
            "Rounded score": "ROUND(Response / 3, 2) + (Visit MOD 2) + FACT(Visit)",
            "Row total": "SUM(Response, Visit, 1)",
            "Mean through visit 2": "MEANIF(Response, Visit <= 2) OVER Cohort",
        }
        for name, recipe in recipes.items():
            drive_formula_editor(root, recipe, errors)
            with patch.object(simpledialog, "askstring", return_value=name):
                app.add_formula()
            assert not errors, errors

        def assert_values(cumulative, means, first_score, first_total):
            data = app.tables[title].frame(mask_excluded=True)
            np.testing.assert_allclose(data["Cumulative response"], cumulative)
            np.testing.assert_allclose(data["Mean through visit 2"], means)
            np.testing.assert_allclose(data["Rounded score"], [first_score, 15.33, 13.67, 22, 12, 33.67])
            np.testing.assert_allclose(data["Row total"], [first_total, 43, 24, 62, 33, 84])

        assert_values([10, 100, 60, 60, 40, 180], [20, 50, 20, 50, 20, 50], 5.33, 12)
        app.edit_cell(0, 0, "12")
        assert_values([12, 100, 62, 60, 42, 180], [21, 50, 21, 50, 21, 50], 6, 14)
        app.current_grid.active_cell = (0, 0)
        app.toggle_exclusion()
        expected = [0, 100, 50, 60, 30, 180], [30, 50, 30, 50, 30, 50]
        assert_values(*expected, np.nan, 2)
        assert app.save()
        app.import_file(path)
        assert app.tables[title].formulas == recipes
        assert_values(*expected, np.nan, 2)
        target = directory / "worksheet-statistics.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = load_tables(target)["worksheet-statistics"]
        np.testing.assert_allclose(exported["Cumulative response"], expected[0])
        np.testing.assert_allclose(exported["Row total"], [2, 43, 24, 62, 33, 84])
        capture(root, "window-worksheet-statistics.png")

    def check_distribution_formulas_smoke():
        from analisi.distribution_formulas_smoke import check_distribution_formulas
        geometry = root.geometry()
        check_distribution_formulas(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, filedialog=filedialog,
            errors=errors))
        root.geometry(geometry)
        root.update()

    def check_data_grid():
        title = "Dose response worksheet"
        doses = np.array([0, .025, .05, .1, .15, .25, .4, .6, .8, 1.2, 1.6, 2.4, 3.2, 4.8, 6.4, 9.6])
        response = 15 + 60 * doses / (1 + doses)
        frame = pd.DataFrame({"Dose (µM)": doses, "Control [1]": np.round(response, 2),
                              "Control [2]": np.round(response + .28, 2),
                              "Treatment [1]": np.round(response * 1.12 + 4, 2),
                              "Treatment [2]": np.round(response * 1.12 + 4.65, 2)})
        app._add_tables({title: frame})
        data = app.tables[title]
        data.table_format = "XY with replicates"
        data.set_formula("Control mean", '=(COL("Control [1]") + COL("Control [2]")) / 2')
        app.invalidate()
        root.update()
        grid = app.current_grid
        grid.canvas.focus_force()
        click_cell(grid, 2, 1)
        click_cell(grid, 2, 1, "<ButtonRelease-1>")
        assert grid.active_cell == (2, 1)
        clipboard = "17,85\t18,29\t25,15\r\n20,31\t20,87\t28,49\r\n22,93\t\t31,04\r\n27,18\t27,51\t36,26\r\n"
        put_clipboard(clipboard)
        grid.canvas.event_generate("<Control-v>")
        root.update()
        grid = app.current_grid
        assert grid.selection == (2, 1, 5, 3)
        assert grid.address.cget("text").startswith("B3:D6")
        assert data.raw.iat[2, 1] == 17.85 and data.raw.iat[5, 3] == 36.26
        assert pd.isna(data.raw.iat[4, 2]) and data.raw.iat[4, 4] == frame.iat[4, 4]
        grid.canvas.event_generate("<Control-c>")
        root.update()
        copied = get_clipboard()
        assert "\r\r\n" not in copied
        decimal_mark = clipboard_decimal_mark()
        expected_copy = [
            ["17.85", "18.29", "25.15"], ["20.31", "20.87", "28.49"],
            ["22.93", "", "31.04"], ["27.18", "27.51", "36.26"],
        ]
        assert clipboard_rows(copied) == [[cell.replace(".", decimal_mark) for cell in row] for row in expected_copy]

        click_cell(grid, 5, 3)
        click_cell(grid, 2, 1, "<B1-Motion>")
        click_cell(grid, 2, 1, "<ButtonRelease-1>")
        assert grid.selection == (2, 1, 5, 3)
        grid.canvas.event_generate("<Shift-Down>")
        root.update()
        assert grid.selection == (3, 1, 5, 3)
        click_cell(grid, 5, 3)
        click_cell(grid, 2, 1, "<B1-Motion>")
        click_cell(grid, 2, 1, "<ButtonRelease-1>")
        assert grid.selection == (2, 1, 5, 3)
        if sys.platform == "win32":
            # Show an actual row-title column in the screenshot without
            # moving the clipboard fixture's source or destination cells.
            titled = data.raw.copy()
            titled.insert(0, "Row title", [f"Well {i:02d}" for i in range(1, len(titled) + 1)])
            showcase = Dataset(titled, dict(data.formulas), table_format=data.table_format)
            with patch.dict(app.tables, {title: showcase}):
                app.show("data", title)
                app.current_grid.select_block(2, 2, 5, 4)
                app.status.set("Data updated.")
                capture(root, "window-data-grid.png")
            app.show("data", title)
            root.update()
            grid = app.current_grid

        click_cell(grid, 0, 0)
        click_cell(grid, 0, 0, "<ButtonRelease-1>")
        grid.canvas.event_generate("<F2>")
        root.update()
        assert grid.editor is not None
        grid.editor.delete(0, "end")
        grid.editor.insert(0, "0,005")
        grid.editor.event_generate("<Return>")
        root.update()
        assert data.raw.iat[0, 0] == .005 and app.current_grid.active_cell == (0, 0)

        app.path = directory / "clipboard.alab"
        assert app.save()
        app.import_file(app.path)
        assert app.tables[title].raw.iat[5, 3] == 36.26
        assert pd.isna(app.tables[title].raw.iat[4, 2])

        app._add_tables({"Large grid": pd.DataFrame(np.zeros((552, 12)))})
        root.update()
        grid = app.current_grid
        grid.select((551, 11), reveal=True)
        root.update()
        x, y = grid.view_state()[2:]
        assert x > 0 and y > 0
        put_clipboard("10\t20\r\n30\t40\r\n")
        incoming = clipboard_rows(root.clipboard_get())
        assert incoming == [["10", "20"], ["30", "40"]], incoming
        app.paste_selection()
        root.update()
        grid = app.current_grid
        assert not errors, errors
        assert grid.selection == (551, 11, 552, 12), grid.selection
        assert grid.view_state()[2:] == (x, y), (grid.view_state(), x, y)
        assert grid.frame.shape == (553, 13) and grid.frame.iat[552, 12] == 40

    def check_preserved_legacy_graphs(reference):
        from analisi.legacy_binary_graphs import validate_binary_graph

        def index(method, title, *, start=0, link=None):
            return next(i for i in range(start, len(app.runs))
                        if app.runs[i].method == method and app.runs[i].name == title
                        and (link is None or app.runs[i].options.get(LEGACY_GRAPH_LINK) == link))

        for filename, title, label, value, lengths, series, delta in (
            ("438.pzf", "Data 1", "pzf", "65", None, None, None),
            ("Exponential.pzt", "Curve: Nonlin fit of Yo to plateau", "pzt", "215", None, None, None),
            ("vascular1.pzf", "Fig.3C:  PE Force/CSA: *PUBLISH Transform of *PE Force/CSA graph",
             "pzf-multiseries", None, [150, 150], ["smPPARγOE", "Lit Cont"], 0.5),
            ("EnzymekineticsInhibition.pzt", "*Competitive", "pzt-multiseries", None,
             [150] * 4, ["0 mM", "10 mM", "20 mM", "40 mM"], -0.001),
        ):
            source = reference / filename
            if not source.is_file():
                continue
            start = len(app.runs)
            app.import_file(source)
            wait_for_calculation()
            original = app.runs[index(SAVED_BINARY_GRAPH, title, start=start)]
            baseline = validate_binary_graph(original.options[LEGACY_PREVIEW])
            edited_title = f"{title} · Editable"
            link = original.options[LEGACY_GRAPH_LINK]
            edited_index = index(SAVED_EDITABLE_GRAPH, edited_title, start=start, link=link)
            app.open_graph_view(edited_index)
            wait_for_calculation()
            edited = app.runs[edited_index]
            assert original.options[LEGACY_GRAPH_LINK] == edited.options[LEGACY_GRAPH_LINK]
            table = app.tables[edited.title]
            assert table.table_format == EDITABLE_LEGACY_EMF
            before = np.asarray(edited.result.figure.axes[0].images[0].get_array()).copy()
            capture(root, f"window-{label}-preserved-before.png")
            app.show("data", edited.title)
            assert app.current_grid.read_only_columns == {len(table.raw.columns) - 1}
            app.edit_cell(0, 1, "10000")
            assert "inside the saved axes" in errors.pop()
            if lengths is None:
                changes = {0: value}
            else:
                assert edited.options[LEGACY_GRAPH_STYLE]["series_lengths"] == lengths
                assert table.raw["Series"].drop_duplicates().tolist() == series
                assert edited.options[LEGACY_GRAPH_STYLE]["fixed_overlays"] == (2 if label == "pzf-multiseries" else 0)
                rows = np.cumsum([0, *lengths[:-1]]) + 45
                changes = {int(row): repr(float(table.raw.iat[row, 1]) + delta) for row in rows}
            for row, new_value in changes.items():
                app.edit_cell(row, 1, new_value)
                wait_for_calculation()
            if label == "pzf":
                app.edit_cell(0, 2, "14")
                wait_for_calculation()
                app.edit_cell(0, 3, "9")
                wait_for_calculation()
            app.open_graph_view(edited_index)
            wait_for_calculation()
            edited = app.runs[edited_index]
            changed = np.asarray(edited.result.figure.axes[0].images[0].get_array())
            assert changed.shape == before.shape and np.count_nonzero(changed != before) > 100
            capture(root, f"window-{label}-preserved-after.png")
            vector = directory / f"{label}-edited.emf"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(vector)):
                app.export()
            assert vector.read_bytes() != baseline and len(vector.read_bytes()) == len(baseline)
            assert validate_binary_graph(original.options[LEGACY_PREVIEW]) == baseline
            # Also retain the actual rendered image when testing from a hidden SSH desktop.
            edited.result.figure.savefig(directory / f"{label}-edited.png", dpi=140)
            path = directory / f"{label}-preserved.alab"
            app.path = path
            assert app.save()
            app.import_file(path)
            reopened_index = index(SAVED_EDITABLE_GRAPH, edited_title, link=link)
            app.open_graph_view(reopened_index)
            wait_for_calculation()
            reopened = app.runs[reopened_index]
            for row, new_value in changes.items():
                assert np.isclose(float(app.tables[reopened.title].raw.iat[row, 1]), float(new_value),
                                  rtol=0, atol=1e-13)
            with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / f"{label}-reopened.emf")):
                app.export()
            assert (directory / f"{label}-reopened.emf").read_bytes() == vector.read_bytes()

    def check_binary_views(reference):
        from analisi.legacy_binary_graphs import validate_binary_graph

        def open_view(method, title):
            wait_for_calculation()
            ref = next((kind, key) for kind, key in app.nodes.values() if kind in RUN_VIEWS
                       and app.runs[key].method == method and app.runs[key].name == title)
            node = next(node for node, value in app.nodes.items() if value == ref)
            app.nav.selection_set(node)
            app.navigate()
            wait_for_calculation()
            assert app.selected == ref
            return app.runs[ref[1]]

        analysis_title = "t test of CAT-Peak PPP:Tabular results"
        graph_title = "Curve: Nonlin fit of Yo to plateau"
        app.import_file(reference / "plos-s2.pzf")
        result = open_view(SAVED_BINARY_RESULT, analysis_title)
        saved_values = next(iter(result.result.tables.values())).to_numpy().ravel()
        assert any(isinstance(value, str) and value == "0.0821" for value in saved_values)
        capture(root, "window-binary-analysis.png")
        app.use_result_as_data()
        assert app.selected[0] == "data" and app.current_grid is not None
        assert not app.tables[app.selected[1]].analyses

        app.import_file(reference / "Exponential.pzt")
        pending_graph = next(index for index, run in enumerate(app.runs)
                             if run.method == SAVED_BINARY_GRAPH and run.name == graph_title)
        assert app.runs[pending_graph].result is None
        thumbnail = app.gallery_thumbnail(("graph", pending_graph))
        assert thumbnail is not None and len(thumbnail.getcolors(100_000)) > 20
        assert app.runs[pending_graph].result is None
        graph = open_view(SAVED_BINARY_GRAPH, graph_title)
        preview = validate_binary_graph(graph.options[LEGACY_PREVIEW])
        image = graph.result.figure.axes[0].images[0].get_array()
        assert np.ptp(np.asarray(image, dtype=float)) > 40
        exported = directory / "original-imported-graph.emf"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(exported)):
            app.export()
        assert exported.read_bytes() == preview
        capture(root, "window-binary-graph.png")
        layout_title = "Layout-1"
        layout = open_view(SAVED_BINARY_LAYOUT, layout_title)
        layout_preview = validate_binary_graph(layout.options[LEGACY_PREVIEW], layout=True)
        assert layout_preview in (reference / "Exponential.pzt").read_bytes()
        exported = directory / "original-imported-layout.emf"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(exported)):
            app.export()
        assert exported.read_bytes() == layout_preview
        if (reference / "Figure4-S4_final.pzf").is_file():
            sample = reference / "Figure4-S4_final.pzf"
            app.import_file(sample)
            original_page = open_view(SAVED_BINARY_LAYOUT, "Figure S4")
            assert validate_binary_graph(original_page.options[LEGACY_PREVIEW], layout=True) in sample.read_bytes()
            capture(root, "window-imported-layout.png")
        if (reference / "Sinewaves.pzt").is_file():
            app.import_file(reference / "Sinewaves.pzt")
            sine = open_view(SAVED_BINARY_RESULT, "Sine wave")
            series = next(iter(sine.result.tables.values()))
            np.testing.assert_allclose(series["X"].iloc[[0, -1]].astype(float), [0, 10])
            original_sine = open_view(SAVED_BINARY_GRAPH, "Sine wave")
            editable = open_view(SAVED_EDITABLE_GRAPH, "Sine wave · Editable")
            assert editable.options[LEGACY_GRAPH_LINK] == original_sine.options[LEGACY_GRAPH_LINK]
            axes = editable.result.figure.axes[0]
            limits = axes.get_xlim()
            x_ticks = [label.get_text() for label in axes.get_xticklabels()]
            data_line = axes.lines[-1]
            np.testing.assert_allclose(data_line.get_ydata(), np.sin(np.pi * np.arange(151) / 15), atol=2e-14)
            capture(root, "window-editable-imported-graph.png")

            def edit_axis(dialog):
                assert all(dialog.axis_fields["y"][field].get() == "" for field in ("min", "max"))
                dialog.inputs["xlabel"].set("Time (edited)")

            drive_dialog(GraphFormatDialog, edit_axis)
            app.format_graph()
            assert axes.get_xlabel() == "Time (edited)"
            assert axes.get_xlim() == limits and [label.get_text() for label in axes.get_xticklabels()] == x_ticks

            def edit_range(dialog):
                dialog.axis_fields["y"]["min"].set("-2")
                dialog.axis_fields["y"]["max"].set("2")

            drive_dialog(GraphFormatDialog, edit_range)
            app.format_graph()
            assert axes.get_ylim() == (-2, 2)
            app.show("data", editable.title)
            app.edit_cell(0, 2, "Changed label")
            assert "Use Format" in errors.pop()
            app.edit_cell(1, 1, "0.5")
            wait_for_calculation()
            assert editable.result.figure.axes[0].lines[-1].get_ydata()[1] == .5

        app.path = directory / "binary-views.alab"
        assert app.save()
        app.import_file(app.path)
        graph = open_view(SAVED_BINARY_GRAPH, graph_title)
        assert validate_binary_graph(graph.options[LEGACY_PREVIEW]) == preview
        layout = open_view(SAVED_BINARY_LAYOUT, layout_title)
        assert validate_binary_graph(layout.options[LEGACY_PREVIEW], layout=True) == layout_preview
        if (reference / "Sinewaves.pzt").is_file():
            editable = open_view(SAVED_EDITABLE_GRAPH, "Sine wave · Editable")
            assert editable.result.figure.axes[0].get_xlabel() == "Time (edited)"
            assert editable.result.figure.axes[0].get_ylim() == (-2, 2)
            assert editable.result.figure.axes[0].lines[-1].get_ydata()[1] == .5
        reopened = open_view(SAVED_BINARY_RESULT, analysis_title)
        saved_values = next(iter(reopened.result.tables.values())).to_numpy().ravel()
        assert any(isinstance(value, str) and value == "0.0821" for value in saved_values)

        source = reference / "ec-proliferation.pzf"
        if source.is_file():
            from analisi.legacy_binary_bars import edit_bar_preview
            from analisi.legacy_restore import LEGACY_GRAPH_STYLE

            def rendered(run):
                return np.asarray(run.result.figure.axes[0].images[0].get_array())

            def same_render(actual, expected):
                assert actual.shape == expected.shape
                # GDI+ can vary antialiasing at glyph edges between passes.
                difference = np.abs(actual.astype(np.int16) - expected)
                assert (difference != 0).mean() < .0002 and difference.max() < 64

            def draw_data(run):
                options = run.options
                return edit_bar_preview(app.tables[run.title].raw, options[LEGACY_GRAPH_STYLE], options[LEGACY_PREVIEW])

            app.import_file(source)
            original = open_view(SAVED_BINARY_GRAPH, "*C bFGF")
            editable = open_view(SAVED_EDITABLE_GRAPH, "*C bFGF · Editable")
            assert original.options[LEGACY_GRAPH_LINK] == editable.options[LEGACY_GRAPH_LINK]
            archived = original.options[LEGACY_PREVIEW]
            assert draw_data(editable) == archived
            pixels = rendered(original)
            same_render(rendered(editable), pixels)
            capture(root, "window-editable-pzf-columns.png")
            app.show("data", editable.title)
            assert app.current_grid.read_only_columns == {2}
            app.edit_cell(2, 1, "-1")
            assert "nonnegative" in errors.pop()
            app.edit_cell(2, 0, "4")
            wait_for_calculation()
            app.edit_cell(2, 1, "1.5")
            wait_for_calculation()
            editable = open_view(SAVED_EDITABLE_GRAPH, "*C bFGF · Editable")
            changed = rendered(editable)
            edited_preview = draw_data(editable)
            assert edited_preview != archived
            assert changed.shape == pixels.shape and np.count_nonzero(changed != pixels) > 1000
            capture(root, "window-edited-pzf-columns.png")
            app.path = directory / "edited-pzf-columns.alab"
            assert app.save()
            app.import_file(app.path)
            reopened = open_view(SAVED_EDITABLE_GRAPH, "*C bFGF · Editable")
            assert draw_data(reopened) == edited_preview
            same_render(rendered(reopened), changed)
            original = open_view(SAVED_BINARY_GRAPH, "*C bFGF")
            assert original.options[LEGACY_PREVIEW] == archived
            same_render(rendered(original), pixels)

            newer_profiles = ("*D VEGF",)
            if (reference / "vascular1.pzf").is_file():
                app.import_file(reference / "vascular1.pzf")
                newer_profiles += ("Fig.3B:  Maximum KCl F/CSA: *PUBLISH *Maximum KCl F/CSA graph",
                                   "Fig.3D:  Maximum PE F/CSA: *PUBLISH *Maximum PE F/CSA graph")
            amended_profiles = {}
            for title in newer_profiles:
                original = open_view(SAVED_BINARY_GRAPH, title)
                editable = open_view(SAVED_EDITABLE_GRAPH, title + " · Editable")
                original_preview = original.options[LEGACY_PREVIEW]
                assert draw_data(editable) == original_preview
                same_render(rendered(editable), rendered(original))
                raw = app.tables[editable.title].raw
                app.show("data", editable.title)
                app.edit_cell(0, 0, str(raw.iat[0, 0] / 2))
                wait_for_calculation()
                app.edit_cell(0, 1, str(raw.iat[0, 1] / 2))
                wait_for_calculation()
                changed_preview = draw_data(editable)
                assert changed_preview != original_preview
                assert rendered(editable).shape == rendered(original).shape
                amended_profiles[title] = (original_preview, changed_preview)
            app.path = directory / "expanded-pzf-bars.alab"
            assert app.save()
            app.import_file(app.path)
            for title, (before, after) in amended_profiles.items():
                assert draw_data(open_view(SAVED_EDITABLE_GRAPH, title + " · Editable")) == after
                assert open_view(SAVED_BINARY_GRAPH, title).options[LEGACY_PREVIEW] == before

            directional_source = reference / "controlled-direction-bars.pzf"
            if directional_source.is_file():
                title = "Directional error-bar QA"
                app.import_file(directional_source)
                original = open_view(SAVED_BINARY_GRAPH, title)
                archived = original.options[LEGACY_PREVIEW]
                pixels = rendered(original)
                editable = open_view(SAVED_EDITABLE_GRAPH, title + " · Editable")
                assert draw_data(editable) == archived
                same_render(rendered(editable), pixels)
                app.show("data", editable.title)
                assert app.current_grid.read_only_columns == {3}
                app.edit_cell(1, 1, "0.5")
                assert "absent" in errors.pop()
                app.edit_cell(1, 2, "0.75")
                wait_for_calculation()
                app.current_grid.select((4, 1))
                put_clipboard("1.25\t0.50")
                app.paste_selection()
                wait_for_calculation()
                editable = open_view(SAVED_EDITABLE_GRAPH, title + " · Editable")
                amended = draw_data(editable)
                assert amended != archived
                changed = rendered(editable)
                assert changed.shape == pixels.shape and np.count_nonzero(changed != pixels) > 1000
                capture(root, "window-directional-pzf.png")
                app.path = directory / "directional-pzf.alab"
                assert app.save()
                app.import_file(app.path)
                editable = open_view(SAVED_EDITABLE_GRAPH, title + " · Editable")
                assert draw_data(editable) == amended
                same_render(rendered(editable), changed)
                assert open_view(SAVED_BINARY_GRAPH, title).options[LEGACY_PREVIEW] == archived

    def check_grouped_pzf(sample):
        from analisi.legacy_binary_graphs import validate_binary_graph

        graph_title = "B. Grouped data for two stacks of bars"
        original_project = app.active_project
        assert app.open_document(sample)
        assert app.active_project != original_project
        grouped = app.tables[graph_title]
        assert grouped.table_format == "grouped"
        assert grouped.raw["Row title"].tolist() == ["First game", "Last game"]
        assert grouped.raw.iloc[1, 1:].tolist() == [34, 21, 21, 23]

        result = next(index for index, run in enumerate(app.runs) if run.method == SAVED_BINARY_RESULT
                      and run.name.startswith("Fraction of Total of C. Grouped data"))
        app.open_sheet(("result", result))
        wait_for_calculation()
        saved = next(iter(app.runs[result].result.tables.values()))
        np.testing.assert_allclose(saved.iloc[0].astype(float), np.array([23, 34, 56, 67]) / 1.8, rtol=1e-6)

        graph = next(index for index, run in enumerate(app.runs)
                     if run.method == SAVED_BINARY_GRAPH and run.name == graph_title)
        assert app.runs[graph].result is None
        thumbnail = app.gallery_thumbnail(("graph", graph))
        assert thumbnail is not None and len(thumbnail.getcolors(100_000)) > 20
        app.open_sheet(("graph", graph))
        wait_for_calculation()
        run = app.runs[graph]
        preview = validate_binary_graph(run.options[LEGACY_PREVIEW])
        assert preview.startswith(b"%PDF-") and preview in sample.read_bytes()
        assert np.ptp(run.result.figure.axes[0].images[0].get_array()) > 40
        exported = directory / "original-grouped-graph.pdf"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(exported)) as save:
            app.export()
        assert save.call_args.kwargs["defaultextension"] == ".pdf"
        assert exported.read_bytes() == preview
        capture(root, "window-grouped-pzf-pdf.png")

        editable = next(index for index, run in enumerate(app.runs)
                        if run.method == SAVED_EDITABLE_GRAPH and run.name == graph_title + " · Editable")
        app.open_graph_view(editable)
        wait_for_calculation()
        run = app.runs[editable]
        image = np.asarray(run.result.figure.axes[0].images[0].get_array()).copy()
        app.show("data", run.title)
        assert app.current_grid.read_only_columns == {0}
        app.edit_cell(0, 1, "101")
        assert "total of at most 100" in errors.pop()
        app.current_grid.select((0, 1))
        put_clipboard("30\t20")
        app.paste_selection()
        wait_for_calculation()
        app.open_graph_view(editable)
        wait_for_calculation()
        changed = np.asarray(run.result.figure.axes[0].images[0].get_array()).copy()
        assert image.shape == changed.shape and np.count_nonzero(changed != image) > 1000
        assert grouped.raw.iloc[0, 1:3].tolist() == [23, 27]
        capture(root, "window-editable-pzf-pdf.png")

        app.path = directory / "imported-grouped-pzf.alab"
        assert app.save()
        app.import_file(app.path)
        graph = next(index for index, run in enumerate(app.runs)
                     if run.method == SAVED_BINARY_GRAPH and run.name == graph_title)
        app.open_sheet(("graph", graph))
        wait_for_calculation()
        assert validate_binary_graph(app.runs[graph].options[LEGACY_PREVIEW]) == preview
        editable = next(index for index, run in enumerate(app.runs)
                        if run.method == SAVED_EDITABLE_GRAPH and run.name == graph_title + " · Editable")
        app.open_graph_view(editable)
        wait_for_calculation()
        reopened = np.asarray(app.runs[editable].result.figure.axes[0].images[0].get_array())
        np.testing.assert_array_equal(reopened, changed)
        app.close_project()
        assert app.active_project == original_project

    def check_worksheet_edits():
        title = "Worksheet edit QA"
        source = pd.DataFrame({"X": [1, 2, 3, 4], "A": [2., 4., 6., 8.], "B": [5., 6., 7., 8.]})
        app._add_tables({title: source})
        options = {"X": "X", "Y": "A"}
        run = Run("Linear regression", title, options)
        app.add_result(run, analyse(run.method, source, options), reveal=False)
        data = app.tables[title]

        def press(sequence):
            root.update()
            app.current_grid.canvas.focus_force()
            app.current_grid.canvas.event_generate(sequence)
            wait_for_calculation()

        app.current_grid.select((1, 1))
        put_clipboard("2,50\t\t4,75\r\n-1,25\t3,0\t\r\n")
        press("<Control-Shift-T>")
        assert app.current_grid.selection == (1, 1, 3, 2)
        assert data.raw.iat[1, 1] == 2.5 and data.raw.iat[1, 2] == -1.25
        assert pd.isna(data.raw.iat[2, 1]) and pd.isna(data.raw.iat[3, 2])
        transposed = data.raw.copy()
        changed = run.result.tables["Regression"].loc["Slope", "Value"]
        assert changed != 2
        assert app.worksheet_history_buttons["Undo"].instate(["!disabled"])
        app.open_gallery("Data Tables")
        app.clear_selection()
        assert "Select a data table" in errors.pop()
        assert app.gallery is not None
        pd.testing.assert_frame_equal(data.raw, transposed)
        app.toggle_gallery()
        press("<Control-z>")
        pd.testing.assert_frame_equal(data.raw, source)
        assert run.result.tables["Regression"].loc["Slope", "Value"] == 2
        assert app.current_grid.selection == (1, 1, 1, 1)
        press("<Control-y>")
        pd.testing.assert_frame_equal(data.raw, transposed)
        assert run.result.tables["Regression"].loc["Slope", "Value"] == changed
        capture(root, "window-worksheet-edits.png")

        app.current_grid.select((1, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        app.current_grid.select_block(1, 2, 2, 2)
        press("<Control-x>")
        mark = clipboard_decimal_mark()
        assert clipboard_rows(get_clipboard()) == [[f"-1{mark}25"], [f"3{mark}0"]]
        assert data.raw.iloc[1:3, 2].isna().all() and not data.excluded
        press("<Control-z>")
        pd.testing.assert_frame_equal(data.raw, transposed)
        assert data.excluded == {(1, 2)}

        app._add_tables({"Exact counts": pd.DataFrame({"Count": [2**53 + 3]})})
        app.add_row()
        assert app.tables["Exact counts"].raw.iat[0, 0] == 2**53 + 3
        assert len(app.tables["Exact counts"].raw) == 2
        press("<Control-z>")
        assert len(app.tables["Exact counts"].raw) == 1
        press("<Control-z>")
        assert app.selected == ("data", title) and not data.excluded
        assert app.current_grid.active_cell == (1, 2)
        app.current_grid.select((2, 2))
        press("<Delete>")
        assert pd.isna(data.raw.iat[2, 2])
        assert not app.worksheet_history.can_apply(redo=True)
        press("<Control-z>")
        assert data.raw.iat[2, 2] == 3

        app.path = directory / "worksheet-edits.alab"
        assert app.save()
        app.import_file(app.path)
        assert not app.worksheet_history.can_apply()
        pd.testing.assert_frame_equal(app.tables[title].raw, transposed, check_dtype=False)

    def check_old_legacy_xy(reference):
        from analisi.legacy_binary_graphs import validate_binary_graph

        fixture = reference / "438.pzf"
        if not fixture.is_file():
            return
        start = len(app.runs)
        app.import_file(fixture)
        assert app.selected[0] == "data"
        table = app.tables[app.selected[1]].raw
        assert table.shape == (5, 7) and table.iloc[:2].isna().all().all()
        assert table.iloc[2].tolist() == [3, 33, 57, 67, 87, 89, 120]
        assert table.iat[3, 0] == 4 and table.iloc[3, 1:].isna().all()
        capture(root, "window-legacy-xy.png")
        wait_for_calculation()
        graph = next(index for index in range(start, len(app.runs)) if app.runs[index].method == SAVED_BINARY_GRAPH)
        app.open_sheet(("graph", graph))
        wait_for_calculation()
        drawing = validate_binary_graph(app.runs[graph].options[LEGACY_PREVIEW])
        assert len(drawing) == 21476 and drawing in fixture.read_bytes()
        pixels = app.runs[graph].result.figure.axes[0].images[0].get_array()
        assert np.ptp(np.asarray(pixels, dtype=float)) > 100
        capture(root, "window-legacy-graph.png")
        # Exercise the actual command against a real imported, non-native drawing.
        # The native shapes editor must never open and the imported style must stay intact.
        before_shape_refusal = (deepcopy(app.runs[graph].style), app.dirty, app.selected)
        with patch("analisi.graph_shape_dialog.GraphShapesDialog",
                   side_effect=AssertionError("Native editor opened for an imported drawing")):
            app.edit_graph_shapes()
        refusal = errors.pop()
        assert "Open editable graph" in refusal, refusal
        assert (app.runs[graph].style, app.dirty, app.selected) == before_shape_refusal
        from hashlib import sha256
        (directory / "imported-shape-refusal.txt").write_text(
            f"PASS: actual imported PZF graph command rejected without mutation\n"
            f"source_sha256={sha256(fixture.read_bytes()).hexdigest()}\n{refusal}\n", encoding="utf-8")
        old_columns = reference / "1646.pzf"
        if old_columns.is_file():
            app.import_file(old_columns)
            assert app.selected[0] == "data"
            columns = app.tables[app.selected[1]]
            assert columns.table_format == "column" and not columns.excluded
            assert list(columns.raw.columns) == ["Cats", "dogs", "mice"]
            assert columns.raw["mice"].tolist() == [44, 55, 44, 66, 23, 45]
            assert "Unavailable imported graph previews (2)" in app.status.get()
            capture(root, "window-legacy-columns.png")

    def check_data_processing():
        from scipy.stats import binomtest

        title = "Data processing QA"
        path = directory / "data-processing.alab"
        original = pd.DataFrame({
            "Dose": [0., 1e-9, 1e-8, np.nan], "A": [6, 79, 2, 3],
            "B": [3, 12, 4, 5], "Background": [2, 4, 1, 1],
        })
        save_project(path, {title: Dataset(original)})
        app.import_file(path)

        def concentrations(dialog):
            pick_method(dialog, "Transform concentrations (X)")
            dialog.controls["X"][1].set("Dose")
            dialog.controls["Replace zero X"][1].set(True)
            field = "Zero replacement (original units)"
            dialog.controls[field][1].set("-1")
            with patch.object(messagebox, "showerror") as show_error:
                assert not dialog.validate()
            assert field in show_error.call_args.args[1]
            assert dialog.fields.select() == str(dialog.field_rows[field][1].master)
            dialog.controls[field][1].set("0,00000000001")
            dialog.controls["Change units"][1].set("Multiply by")
            dialog.controls["Unit factor"][1].set("1e9")
            dialog.controls["Logarithm"][1].set("Log10")

        def baseline(dialog):
            pick_method(dialog, "Remove baseline and column math")
            select_columns(dialog, "Data columns", {"A"})
            dialog.controls["Baseline column"][1].set("Background")
            dialog.controls["X"][1].set("Dose")

        def prune(dialog):
            pick_method(dialog, "Prune rows")
            dialog.controls["X"][1].set("Dose")
            dialog.controls["X minimum (blank = no limit)"][1].set("1e-9")
            dialog.controls["X maximum (blank = no limit)"][1].set("1e-8")
            dialog.controls["Rows per group (K)"][1].set("ignored in range mode")
            assert not dialog.processing_visibility()["Rows per group (K)"]

        def fraction(dialog):
            pick_method(dialog, "Fraction of total")
            select_columns(dialog, "Variables", {"A", "B"})
            dialog.controls["Confidence interval"][1].set(WILSON_BROWN)
            dialog.focus_field("Confidence interval")
            capture(dialog, "window-processing-options.png")

        tested = {}
        for select in (concentrations, baseline, prune, fraction):
            app.show("data", title)
            drive_dialog(AnalysisDialog, select)
            app.choose_analysis()
            assert app.pending is None and not errors, errors
            run = app.runs[-1]
            tested[run.method] = run
            if select is concentrations:
                values = run.result.tables["Transformed data"]["Dose"]
                np.testing.assert_allclose(values, [-2, 0, 1, np.nan], equal_nan=True)
                app.use_result_as_data()
                assert app.selected[0] == "data" and app.selected[1] != title
                np.testing.assert_allclose(app.tables[app.selected[1]].raw["Dose"], values, equal_nan=True)
            elif select is baseline:
                assert run.result.tables["Processed data"]["A"].tolist() == [4, 75, 1, 2]
            elif select is prune:
                assert run.result.tables["Pruned data"]["A"].tolist() == [79, 2]
            else:
                assert np.isclose(run.result.tables["Fraction of column total"].iat[0, 0], 6 / 90)
                interval = binomtest(6, 90).proportion_ci(method="wilson")
                np.testing.assert_allclose([run.result.tables["Lower 95% limit"].iat[0, 0],
                                            run.result.tables["Upper 95% limit"].iat[0, 0]], interval)
                from scipy.stats import poisson

                assert np.isclose(poisson.cdf(1, 90 * run.result.tables["Lower 95% limit"].iat[2, 0]), .95)
                capture(root, "window-data-processing.png")

        app.show("data", title)
        app.edit_cell(0, 1, "9")
        wait_for_calculation()
        assert tested["Remove baseline and column math"].result.tables["Processed data"]["A"].iloc[0] == 7
        assert np.isclose(tested["Fraction of total"].result.tables["Fraction of column total"].iat[0, 0], 9 / 93)
        assert app.save()
        app.import_file(path)
        for method, previous in tested.items():
            index = next(i for i, run in enumerate(app.runs) if run.method == method and run.title == title)
            app.open_sheet(("result", index))
            wait_for_calculation()
            reopened = app.runs[index]
            assert reopened.options == previous.options
            for name, expected in previous.result.tables.items():
                pd.testing.assert_frame_equal(reopened.result.tables[name], expected, check_dtype=False)

        def combined(dialog):
            dialog.controls["Divide by"][1].set(COMBINED_TOTALS)
            assert not dialog.processing_visibility()["Confidence interval"]
            assert not dialog.processing_visibility()["Confidence level (%)"]

        index = next(i for i, run in enumerate(app.runs) if run.method == "Fraction of total")
        app.open_sheet(("result", index))
        wait_for_calculation()
        drive_dialog(AnalysisDialog, combined)
        app.edit_analysis()
        result = app.runs[index].result.tables["Fraction of all totals"]
        assert np.isclose(result.iloc[0]["A · column total"], 9 / 93)
        capture(root, "window-fraction-all-totals.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", index))
        wait_for_calculation()
        pd.testing.assert_frame_equal(app.runs[index].result.tables["Fraction of all totals"], result)

    def check_hierarchical_workflow():
        title = "Cluster demonstration"
        path = directory / "cluster-workflow.alab"
        source = pd.DataFrame({
            "Sample": ["Aster", "Birch", "Cedar", "Dahlia", "Elm", "Fern", "Ginkgo", "Hazel"],
            "Marker A": [1.0, 1.2, 1.1, 5.0, 5.3, 5.2, 8.9, 9.2],
            "Marker B": [1.1, 1.3, 1.2, 5.0, 5.2, 5.1, 9.2, 9.4],
            "Marker C": [8.1, 8.4, 8.2, 4.0, 4.3, 4.2, 1.0, 1.2],
            "Marker D": [8.3, 8.6, 8.4, 4.1, 4.2, 4.3, 1.1, 1.3],
        })
        save_project(path, {title: Dataset(source)})
        app.import_file(path)
        method = "Hierarchical clustering"
        variables = {"Marker A", "Marker B", "Marker C", "Marker D"}

        def common(dialog):
            pick_method(dialog, method)
            select_columns(dialog, "Variables", variables)
            dialog.controls["Observation labels"][1].set("Sample")

        def dendrogram(dialog):
            common(dialog)
            dialog.controls["Scale columns"][1].set("None")
            dialog.controls["Row cut"][1].set("Cut height")
            dialog.controls["Row cut height"][1].set("1,5")
            dialog.controls["Dendrogram orientation"][1].set("Horizontal")
            dialog.controls["Branch width"][1].set("2")
            assert not dialog.hierarchical_visibility()["Column cut"]
            dialog.focus_field("Dendrogram orientation")
            capture(dialog, "window-clustering-options.png")

        drive_dialog(AnalysisDialog, dendrogram)
        app.choose_analysis()
        wait_for_calculation()
        row_run = app.runs[-1]
        assert row_run.result.tables["Assignments"]["Cluster"].tolist() == [1, 1, 1, 2, 2, 2, 3, 3]
        axis, = row_run.result.figure.axes
        assert axis.get_xlabel() == "Merge distance"
        assert "Cedar" in [tick.get_text() for tick in axis.get_yticklabels()]
        np.testing.assert_allclose(axis.lines[0].get_xdata(), [1.5, 1.5])
        assert axis.collections[0].get_linewidth()[0] == 2
        app.show("graph", len(app.runs) - 1)
        capture(root, "window-dendrogram.png")

        def heat_map(dialog):
            common(dialog)
            dialog.controls["Direction"][1].set("Rows and columns")
            dialog.controls["Clusters"][1].set("3")
            dialog.controls["Column clusters"][1].set("2")
            dialog.controls["Graph output"][1].set("Heat map")
            dialog.controls["Scaled data"][1].set(True)
            dialog.controls["Distance matrix"][1].set(True)
            dialog.controls["Cophenetic distances"][1].set(True)
            dialog.controls["Cophenetic correlation"][1].set(True)
            dialog.controls["Matrix format"][1].set("Lower triangle")
            assert not dialog.hierarchical_visibility()["Dendrogram orientation"]

        app.show("data", title)
        drive_dialog(AnalysisDialog, heat_map)
        app.choose_analysis()
        wait_for_calculation()
        dual = app.runs[-1]
        tables = dual.result.tables
        assert tables["Row Assignments"]["Cluster"].nunique() == 3
        assert tables["Column Assignments"]["Cluster"].tolist() == [1, 1, 2, 2]
        assert tables["Row Distance matrix"].shape == (8, 8)
        assert np.isnan(tables["Row Cophenetic distances"].iat[0, 1])
        assert .85 < tables["Column Cophenetic correlation"].iat[0, 0] <= 1
        np.testing.assert_allclose(tables["Scaled data"].std().to_numpy(), 1.)
        heat, left, top, _ = dual.result.figure.axes
        assert heat.get_ylim() == left.get_ylim() and heat.get_xlim() == top.get_xlim()
        assert heat.images[0].get_array().shape == (8, 4)
        app.show("graph", len(app.runs) - 1)
        capture(root, "window-cluster-heat-map.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 1))
        wait_for_calculation()
        reopened = app.runs[1]
        assert reopened.options == dual.options
        for name, expected in tables.items():
            pd.testing.assert_frame_equal(reopened.result.tables[name], expected)

    def check_confidence_overlays():
        from matplotlib.colors import to_rgba

        from analisi.ellipse_style_dialog import EllipseStyleDialog

        title, method = "Response by cohort", "Scatter / confidence ellipse"
        path = directory / "confidence-overlays.alab"
        rng = np.random.default_rng(74)
        first = rng.normal(size=(20, 2)) @ np.array([[.8, .5], [0., .35]]) + [3., 4.]
        second = rng.normal(size=(20, 2)) @ np.array([[.7, -.35], [0., .45]]) + [7., 6.]
        source = pd.DataFrame(np.vstack([first, second]), columns=["Dose", "Response"])
        source["Treatment"] = ["Control", "Treated"] * 20
        source["Cohort"] = ["Cohort A"] * 20 + ["Cohort B"] * 20
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def choose_overlay(dialog):
            pick_method(dialog, method)
            variables = {name: control for name, (_, control) in dialog.controls.items()}
            variables["X"].set("Dose")
            variables["Y"].set("Response")
            variables["Group"].set("Treatment")
            assert dialog.fields.tab(dialog.field_rows["Fill"][0].master, "state") == "disabled"
            variables["Ellipse"].set("Data ellipse")
            variables["Ellipse grouping"].set("Separate categorical variable")
            variables["Ellipse group"].set("Cohort")
            variables["Level (%)"].set("90")
            variables["Fill"].set("By group")
            variables["Fill opacity (%)"].set("25")
            variables["Border style"].set("Dashed")
            variables["Border width"].set("2,5")
            variables["Center marker"].set("Diamond")
            variables["Center size"].set("8")
            assert dialog.overlay_visibility()["Ellipse group"]
            assert not dialog.overlay_visibility()["Fill color"]
            dialog.focus_field("Border width")
            capture(dialog, "window-ellipse-options.png")

        drive_dialog(AnalysisDialog, choose_overlay)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs) == 1
        run = app.runs[0]
        summary = run.result.tables["Confidence overlays"]
        assert summary["Group"].tolist() == ["Cohort A", "Cohort B"]
        assert summary["N"].tolist() == [20, 20]
        assert summary["Status"].tolist() == ["Drawn", "Drawn"]
        axis, = run.result.figure.axes
        assert len(axis.collections) == 2
        assert [shape.get_facecolor()[3] for shape in axis.patches] == [.25, .25]
        assert [border.get_linewidth() for border in axis.lines[:2]] == [2.5, 2.5]
        assert [marker.get_marker() for marker in axis.lines[2:]] == ["D", "D"]
        assert [label.get_text() for label in axis.get_legend().get_texts()] == [
            "Control", "Treated", "Cohort · Cohort A", "Cohort · Cohort B",
        ]
        app.show("graph", 0)
        capture(root, "window-confidence-ellipses.png")

        def edit_group_styles(editor):
            assert editor.groups.get() == "Cohort A"
            editor.variables["Fill color"].set("#14758f")
            editor.variables["Fill opacity (%)"].set("21")
            editor.variables["Border width"].set("2,25")
            editor.groups.current(1)
            editor.groups.event_generate("<<ComboboxSelected>>")
            assert editor.groups.get() == "Cohort B"
            editor.variables["Fill color"].set("#d36b3a")
            editor.variables["Fill opacity (%)"].set("13")
            editor.variables["Border style"].set("Solid")
            capture(editor, "window-ellipse-group-styles.png")

        def edit_overlays(dialog):
            button = dialog.field_rows[ELLIPSE_GROUP_STYLES][1]
            dialog.fields.select(button.master)
            drive_dialog(EllipseStyleDialog, edit_group_styles)
            button.invoke()

        def check_group_styles():
            axis, = app.runs[0].result.figure.axes
            assert [shape.get_facecolor() for shape in axis.patches] == [
                to_rgba("#14758f", .21), to_rgba("#d36b3a", .13),
            ]
            assert [border.get_linewidth() for border in axis.lines[:2]] == [2.25, 2.5]
            assert [border.get_linestyle() for border in axis.lines[:2]] == ["--", "-"]

        drive_dialog(AnalysisDialog, edit_overlays)
        page_button("Confidence overlays…").invoke()
        wait_for_calculation()
        check_group_styles()
        capture(root, "window-confidence-group-styles.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        check_group_styles()

        def use_one_overlay(dialog):
            assert dialog.fields.tab(dialog.fields.select(), "text") == "Ellipse"
            assert dialog.controls["Ellipse group"][1].get() == "Cohort"
            dialog.controls["Ellipse grouping"][1].set("All XY data")
            assert not dialog.overlay_visibility()["Ellipse group"]
            dialog.controls["Fill"][1].set("Single color")
            dialog.controls["Fill color"][1].set("#20a080")
            dialog.controls["Border"][1].set("None")

        shortcut = page_button("Confidence overlays…")
        drive_dialog(AnalysisDialog, use_one_overlay)
        shortcut.invoke()
        wait_for_calculation()
        assert app.selected == ("graph", 0)
        edited = app.runs[0]
        assert edited.result.tables["Confidence overlays"]["N"].tolist() == [40]
        assert "Ellipse group" not in edited.options and "Border width" not in edited.options
        axis, = edited.result.figure.axes
        assert len(axis.patches) == len(axis.lines) == 1 and axis.lines[0].get_marker() == "D"
        edited.result.figure.savefig(directory / "confidence-overlays.svg")
        assert (directory / "confidence-overlays.svg").stat().st_size > 1000
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].options == edited.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Confidence overlays"],
                                      edited.result.tables["Confidence overlays"])

    def check_multiple_variable_processing():
        title = "Training observations"
        path = directory / "multiple-variable-processing.alab"
        source = pd.DataFrame({
            "ID": ["01", "02", "03", "04", "05", "06", "07", "08"],
            "Cohort": ["Junior"] * 4 + ["Senior"] * 4,
            "Program": ["Control", "Control", "Training", "Training"] * 2,
            "Age": [31, 34, 29, 34, 59, 62, 61, 65],
            "Score": [1.2, 1.8, 2.2, 2.4, 3.2, 3.7, 4.0, 4.7],
        })
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def select_rows(dialog):
            pick_method(dialog, SELECT_TRANSFORM)
            select_columns(dialog, "Variables", {"ID", "Program", "Score"})
            dialog.controls["First row"][1].set("2")
            filters = dialog.select_editors[FILTERS]
            for column, operator, target, value in (
                ("Age", ">", "Number", "60"),
                ("Program", "=", "Text", "Training"),
            ):
                filters.add_button.invoke()
                for key, setting in zip(("column", "operator", "target", "value"), (column, operator, target, value)):
                    filters.variables[key].set(setting)
            assert len(filters.values()) == 2
            dialog.focus_field(FILTERS)
            capture(dialog, "window-select-rows.png")
            calculated = dialog.select_editors[CALCULATED]
            calculated.add_button.invoke()
            calculated.variables["name"].set("Scaled score")
            calculated.variables["expression"].set("Score * 2")

        drive_dialog(AnalysisDialog, select_rows)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs) == 1
        selected = app.runs[0].result.tables["Selected data"]
        assert selected["ID"].tolist() == ["07", "08"]
        np.testing.assert_allclose(selected["Scaled score"], [8.0, 9.4])
        app.use_result_as_data()
        assert app.tables["Selected data"].table_format == "multivariable"
        app.show("data", title)

        def arrange_groups(dialog):
            pick_method(dialog, EXTRACT_REARRANGE)
            dialog.controls[EXTRACT_OUTPUT][1].set("Grouped")
            assert not dialog.extract_visibility()["Independent (X) variable"]
            assert dialog.extract_visibility()["Row factor variable"]
            for name, column in (("Response variable", "Score"), ("Row factor variable", "Cohort"),
                                 ("Column factor variable", "Program")):
                dialog.controls[name][1].set(column)

        drive_dialog(AnalysisDialog, arrange_groups)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs) == 2
        rearranged = app.runs[1].result.tables["Rearranged data"]
        assert rearranged["Row title"].tolist() == ["Junior", "Senior"]
        np.testing.assert_allclose(rearranged.iloc[:, 1:].to_numpy(dtype=float),
                                   [[1.2, 1.8, 2.2, 2.4], [3.2, 3.7, 4.0, 4.7]])
        app.use_result_as_data()
        dataset = app.tables["Rearranged data"]
        assert dataset.table_format == "grouped"
        assert dataset.raw.attrs["worksheet_roles"]["y"] == [
            ["Control [1]", "Control [2]"], ["Training [1]", "Training [2]"],
        ]
        capture(root, "window-rearranged-grid.png")
        assert app.save()
        app.import_file(path)
        for index, name, expected in ((0, "Selected data", selected), (1, "Rearranged data", rearranged)):
            app.open_sheet(("result", index))
            wait_for_calculation()
            pd.testing.assert_frame_equal(app.runs[index].result.tables[name], expected, check_dtype=False)
        assert app.tables["Rearranged data"].raw.attrs["worksheet_roles"] == dataset.raw.attrs["worksheet_roles"]

    def check_project_tabs():
        from types import SimpleNamespace

        first_path, second_path = directory / "Cell growth.alab", directory / "Follow-up.alab"
        first = pd.DataFrame({
            "Minutes": [0, 5, 10, 15, 20, 25],
            "Control [1]": [1.25, 1.41, 1.56, 1.59, 1.77, 1.83],
            "Control [2]": [1.24, 1.39, 1.52, 1.67, 1.74, 1.86],
            "Treated [1]": [1.23, 1.53, 1.91, 2.19, 2.52, 2.84],
            "Treated [2]": [1.22, 1.55, 1.94, 2.25, 2.54, 2.92],
        })
        first.attrs.update(table_format="XY with replicates", worksheet_roles={
            "x": ["Minutes"], "y": [["Control [1]", "Control [2]"], ["Treated [1]", "Treated [2]"]],
        })
        second = pd.DataFrame({"Week": [1, 2], "Response": [4.2, 5.0]})
        save_project(first_path, {"Dose response": Dataset(first)})
        save_project(second_path, {"Measurements": Dataset(second)})
        original_first, original_second = first_path.read_bytes(), second_path.read_bytes()
        app.import_file(first_path)
        first_key = app.active_project
        options = {"Variables": ["Control [1]", "Treated [1]"]}
        method = "Descriptive statistics"
        app.add_result(Run(method, "Dose response", options), analyse(method, first, options))
        app.show("data", "Dose response")
        app.edit_cell(0, 1, "1,35")
        assert not app.open_document(second_path)
        wait_for_calculation()
        app.current_grid.select_block(1, 1, 4, 2)
        app.search_placeholder = False
        app.search_input.set("Dose")
        assert app.open_document(second_path)
        second_key = app.active_project
        assert second_key != first_key and len(app.projects) == 2
        assert list(app.tables) == ["Measurements"] and not app.runs and not app.dirty
        assert not app.search.get() and not app.worksheet_history.can_apply()
        assert first_path.read_bytes() == original_first

        app.current_grid.select((0, 1), reveal=True)
        app.current_grid.start_edit(SimpleNamespace(type=tk.EventType.KeyPress))
        app.current_grid.editor.delete(0, "end")
        app.current_grid.editor.insert(0, "4,8")
        app.step_project(-1)
        assert app.active_project == first_key
        assert app.projects[second_key].tables["Measurements"].raw.iat[0, 1] == 4.8
        assert app.projects[second_key].dirty
        assert app.current_grid.selection == (1, 1, 4, 2)
        assert app.search.get() == "Dose"
        assert app.worksheet_history.can_apply()
        assert app.tables["Dose response"].raw.iat[0, 1] == 1.35
        assert len(app.runs) == 1 and app.runs[0].result is not None
        capture(root, "window-project-tabs.png")
        app.clear_search()
        app.blur_search(None)
        app.nav.yview_moveto(0)
        capture(root, "window-workspace.png")

        app.project_tabs.notebook.select(second_key)
        root.update()
        assert app.active_project == second_key and app.tables["Measurements"].raw.iat[0, 1] == 4.8
        with patch.object(filedialog, "asksaveasfilename", return_value=str(first_path)):
            assert not app.save(as_new=True)
        assert "open in another tab" in errors.pop()
        assert first_path.read_bytes() == original_first

        assert app.open_document(first_path)
        assert len(app.projects) == 2 and app.active_project == first_key
        bad = directory / "Invalid.alab"
        bad.write_text("{", encoding="utf-8")
        try:
            app.open_document(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected an invalid project to fail")
        assert len(app.projects) == 2 and app.active_project == first_key
        assert app.tables["Dose response"].raw.iat[0, 1] == 1.35

        assert app.switch_project(second_key)
        with patch.object(messagebox, "askyesnocancel", side_effect=[False, None]) as confirm:
            app.close()
        assert confirm.call_count == 2 and app.active_project == second_key and len(app.projects) == 2
        with patch.object(messagebox, "askyesnocancel", return_value=None):
            app.close_project()
        assert app.active_project == second_key and app.dirty
        with patch.object(messagebox, "askyesnocancel", return_value=False):
            app.close_project()
        assert app.active_project == first_key and len(app.projects) == 1
        assert app.current_grid.selection == (1, 1, 4, 2)
        assert second_path.read_bytes() == original_second
        assert app.save() and first_path.read_bytes() != original_first

        app.project_tabs.new_button.invoke()
        assert len(app.projects) == 2 and not app.tables and app.selected is None
        assert app.project_tabs.winfo_manager()
        app.project_tabs.close_button.invoke()
        assert len(app.projects) == 1 and app.active_project == first_key
        assert app.tables["Dose response"].raw.iat[0, 1] == 1.35

    def check_category_graphs(reference):
        path = directory / "category-graphs.alab"
        fixture = reference / "1646.pzf" if reference is not None else None
        if fixture is not None and fixture.is_file():
            source = load_tables(fixture)["sample"]
        else:
            source = pd.DataFrame({
                "Cats": [23.4, 34.6, 45.5, 32.0, 21.8, 54.6],
                "dogs": [63.5, 34.5, 45.6, 46.5, 55.7, 51.4],
                "mice": [44, 55, 44, 66, 23, 45],
            })
            source.attrs["table_format"] = "column"
        grouped = table_frame(next(template for template in TEMPLATES if template.kind == "grouped"), True)
        save_project(path, {"Animal measurements": Dataset(source), "Weekly response": Dataset(grouped)})
        app.import_file(path)

        def choose_range(dialog):
            assert dialog.method == COLUMN_GRAPH
            dialog.controls["Graph style"][1].set("Floating range")
            dialog.controls["Overlay observations"][1].set(True)
            assert not dialog.category_visibility()["Interval"]
            assert dialog.category_visibility()["Point placement"]

        drive_dialog(AnalysisDialog, choose_range)
        app.new_graph()
        wait_for_calculation()
        column = app.runs[0]
        assert column.method == COLUMN_GRAPH
        summary = column.result.tables["Graph data"]
        assert summary["N"].tolist() == [6, 6, 6]
        np.testing.assert_allclose(summary[["Lower", "Upper"]], [[21.8, 54.6], [34.5, 63.5], [23., 66.]], rtol=1e-7)
        axis, = column.result.figure.axes
        assert len(axis.patches) == 3 and [len(points.get_offsets()) for points in axis.collections] == [6, 6, 6]
        app.show("graph", 0)
        capture(root, "window-column-range.png")

        app.show("data", "Weekly response")

        def choose_grouped(dialog):
            assert dialog.method == GROUPED_GRAPH
            dialog.controls["Interval"][1].set("SEM")
            dialog.controls["Overlay observations"][1].set(True)
            assert not dialog.category_visibility()["Confidence level (%)"]

        drive_dialog(AnalysisDialog, choose_grouped)
        app.new_graph()
        wait_for_calculation()
        grouped_run = app.runs[1]
        axis, = grouped_run.result.figure.axes
        assert len(axis.patches) == 6 and [label.get_text() for label in axis.get_xticklabels()] == ["Week 1", "Week 2", "Week 3"]
        np.testing.assert_allclose(grouped_run.result.tables["Graph data"]["Mean"], [4.25, 4.8, 5.35, 5.75, 7.35, 8.45])
        app.show("graph", 1)
        capture(root, "window-grouped-bars.png")

        def edit_grouped(dialog):
            assert dialog.fields.tab(dialog.fields.select(), "text") == "Graph options"
            dialog.controls["Graph style"][1].set("Center and interval")
            dialog.controls["Interval"][1].set("Confidence interval")
            dialog.controls["Confidence level (%)"][1].set("90,5")
            assert dialog.category_visibility()["Confidence level (%)"]

        shortcut = page_button("Graph settings…")
        drive_dialog(AnalysisDialog, edit_grouped)
        shortcut.invoke()
        wait_for_calculation()
        edited = app.runs[1]
        assert edited.options["Confidence level (%)"] == 90.5 and app.selected == ("graph", 1)
        assert not edited.result.figure.axes[0].patches
        edited.result.figure.savefig(directory / "grouped-graph.svg")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 1))
        wait_for_calculation()
        assert app.runs[1].options == edited.options
        pd.testing.assert_frame_equal(app.runs[1].result.tables["Graph data"], edited.result.tables["Graph data"])

    def check_grouped_summaries_and_stacks():
        from io import StringIO
        from matplotlib.container import ErrorbarContainer
        from analisi.table_setup import GROUPED_FORMATS

        def sheet(text):
            frame = pd.read_csv(StringIO(text))
            frame.attrs["table_format"] = "grouped"
            return frame

        def whiskers(axis, series):
            container = [c for c in axis.containers if isinstance(c, ErrorbarContainer)][series]
            return [sorted((a[1], b[1])) for a, b in container.lines[2][0].get_segments()]

        # New Table offers a Grouped variant for every supported statistic layout.
        setup = TableSetup(root)
        setup.types.selection_clear(0, "end")
        setup.types.selection_set(2)
        setup.grouped_format.set("Mean, SD and N")
        setup.refresh()
        template, _ = setup.selection()
        assert template.columns[:4] == ("Row title", "Control [Mean]", "Control [SD]", "Control [N]")
        assert set(GROUPED_FORMATS) >= {"Mean and SEM", "Mean with minus and plus distances",
                                        "Mean with lower and upper limits"}
        setup.destroy()
        app.create_worksheet(template, False)
        created = app.active_data
        assert app.tables[created].table_format == "grouped"
        paste_block(app.tables[created], 0, 0, [  # Clipboard cells are text, as when pasting from Excel.
            ["Day 1", "10", "2", "4", "15", "3", "9"], ["Day 2", "20", "4", "16", "18", "2", "4"],
            ["Day 3", "30", "", "25", "", "", ""]])
        app.invalidate()
        summaries = "Summaries QA"
        raw = "Composition QA"
        a2 = "Asymmetric QA"
        app.tables[summaries] = app.tables.pop(created)
        app._add_tables({raw: sheet(
            "Row title,A [1],A [2],B [1],B [2],C [1],C [2]\nNorth,1,3,4,8,2,2\nSouth,3,,0,0,7,\n"
            "Zero,0,0,0,0,0,0\nEmpty,,,,,,\n"),
            a2: sheet("Row title,A [Center],A [Minus],A [Plus],B [Mean],B [Lower],B [Upper]\n"
                      "First,4,1,3,8,6,13\nSecond,5,0,2,9,9,9\nThird,6,1,,10,,11\n")})
        app.refresh_navigator()
        app.show("data", summaries)

        def summary_dialog(dialog):
            assert dialog.method == GROUPED_GRAPH
            assert dialog.controls["Input"][1].get() == SUMMARIES  # Chosen from the subcolumn names.
            visible = dialog.category_visibility()
            assert visible["Summary error"] and not visible["Interval"] and not visible["Center"]
            assert not visible["Overlay observations"] and not visible["SEM source"]
            assert tuple(dialog.field_rows["Graph style"][1].cget("values")) == ("Bars", "Center and interval")
            dialog.controls["Summary error"][1].set("Limits on axis (lower/upper)")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False  # The dialog stays open and names the field.
            assert "Summary error" in shown.call_args.args[1] and "[Lower]" in shown.call_args.args[1]
            dialog.controls["Summary error"][1].set("SEM")
            assert dialog.category_visibility()["SEM source"]
            dialog.controls["Placement of groups"][1].set("Stacked")
            assert not dialog.category_visibility()["Summary error"]
            dialog.controls["Placement of groups"][1].set("Interleaved")

        drive_dialog(AnalysisDialog, summary_dialog)
        app.new_graph()
        wait_for_calculation()
        sem_run = len(app.runs) - 1
        axis, = app.runs[sem_run].result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0), [[9, 11], [19, 21]], atol=1e-10)
        np.testing.assert_allclose(whiskers(axis, 1), [[14, 16], [17, 19]], atol=1e-10)
        app.show("graph", sem_run)
        capture(root, "window-grouped-summaries-sem.png")

        # Editing a source cell recalculates the open graph without recreating the recipe.
        app.show("data", summaries)
        app.edit_cell(0, 3, "16")
        app.show("graph", sem_run)
        wait_for_calculation()
        axis, = app.runs[sem_run].result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0)[0], [9.5, 10.5], atol=1e-10)

        app.show("data", a2)

        def asymmetric_dialog(dialog):
            assert dialog.controls["Input"][1].get() == SUMMARIES
            select_columns(dialog, "Variables", ["A [Center]", "A [Minus]", "A [Plus]"])
            dialog.controls["Summary error"][1].set("Distances from estimate (minus/plus)")

        drive_dialog(AnalysisDialog, asymmetric_dialog)
        app.new_graph()
        wait_for_calculation()
        asymmetric = len(app.runs) - 1
        axis, = app.runs[asymmetric].result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0), [[3, 7], [5, 7]], atol=1e-10)
        app.show("graph", asymmetric)
        capture(root, "window-grouped-asymmetric-errors.png")

        app.show("data", raw)

        def percent_dialog(dialog):
            assert dialog.controls["Input"][1].get() == "Raw replicates"
            assert tuple(dialog.field_rows["Graph style"][1].cget("values")) == (
                "Bars", "Individual points", "Center and interval", "Floating range")
            dialog.controls["Placement of groups"][1].set("100% stacked")
            visible = dialog.category_visibility()
            assert not any(visible[name] for name in ("Interval", "Overlay observations", "Point placement"))
            assert tuple(dialog.field_rows["Graph style"][1].cget("values")) == ("Bars",)

        drive_dialog(AnalysisDialog, percent_dialog)
        app.new_graph()
        wait_for_calculation()
        stack = len(app.runs) - 1
        table = app.runs[stack].result.tables["Graph data"].set_index(["Row", "Group"])
        np.testing.assert_allclose(table.loc["North", "Percent"], [20, 60, 20], atol=1e-10)
        app.show("graph", stack)
        capture(root, "window-grouped-percent-stacked.png")
        app.show("data", raw)
        app.edit_cell(0, 2, "7")
        app.recalculate(stack)
        wait_for_calculation()
        table = app.runs[stack].result.tables["Graph data"].set_index(["Row", "Group"])
        np.testing.assert_allclose(table.loc["North", "Percent"], [100 / 3, 50, 100 / 6], atol=1e-10)
        app.show("graph", stack)
        app.recalculate(stack)
        wait_for_calculation()

        # Format, save, close and reopen: modes, whiskers, quotas and edits survive.
        axis, = app.runs[stack].result.figure.axes
        style = {"title": "Percent composition", "ylabel": "Share (%)",
                 "series": {next(item.key for item in graph_series(axis) if item.name.endswith("(1)")
                                 and "A" in item.name): {"color": "#356547"}}}
        apply_style(app.runs[stack].result.figure, style)
        app.runs[stack].style = style
        app.tables[raw].graph_styles[app.runs[stack].slot] = style
        app.dirty = True
        path = directory / "grouped-summaries-stacks.alab"
        app.path = path
        assert app.save()
        app.import_file(path)
        # Runs are listed by table after reopening, so find them by sheet.
        sem_run, stack, asymmetric = (next(i for i, run in enumerate(app.runs) if run.title == title)
                                      for title in (summaries, raw, a2))
        for key in (sem_run, asymmetric, stack):
            app.open_sheet(("graph", key))
            wait_for_calculation()
        reopened = app.runs[sem_run]
        assert reopened.options["Input"] == SUMMARIES and reopened.options["Summary error"] == "SEM"
        axis, = reopened.result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0)[0], [9.5, 10.5], atol=1e-10)
        axis, = app.runs[stack].result.figure.axes
        assert axis.get_title() == "Percent composition" and app.runs[stack].options["Placement of groups"] == "100% stacked"
        axis, = app.runs[asymmetric].result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0), [[3, 7], [5, 7]], atol=1e-10)
        assert app.tables[summaries].raw.columns.tolist()[1:4] == ["Control [Mean]", "Control [SD]", "Control [N]"]
        app.show("data", summaries)
        app.edit_cell(1, 3, "4")
        app.recalculate(sem_run)
        wait_for_calculation()
        axis, = app.runs[sem_run].result.figure.axes
        np.testing.assert_allclose(whiskers(axis, 0)[1], [18, 22], atol=1e-10)

        for key, name in ((asymmetric, "grouped-asymmetric"), (stack, "grouped-percent")):
            figure = app.runs[key].result.figure
            figure.savefig(directory / f"{name}.svg")
            figure.savefig(directory / f"{name}.png", dpi=150)
            svg = (directory / f"{name}.svg").read_text(encoding="utf-8")
            assert svg.count('id="patch_') >= 3 and "<image" not in svg
            assert (directory / f"{name}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def check_contingency_workflow():
        path = directory / "contingency.alab"
        title = "Recorded outcomes"
        source = pd.DataFrame({"Group": ["Cases", "Cases", "Controls", "Controls"],
                               "Outcome": ["Event", "No event", "Event", "No event"],
                               "Frequency": [688, 21, 650, 59]})
        save_project(path, {title: Dataset(source)})
        app.import_file(path)
        options = {EXTRACT_OUTPUT: "Contingency", "Row (treatment) variable": "Group",
                   "Column (outcome) variable": "Outcome", "Count variable": "Frequency"}
        app.add_result(Run(EXTRACT_REARRANGE, title, options), analyse(EXTRACT_REARRANGE, source, options))
        app.use_result_as_data()
        assert app.tables["Rearranged data"].table_format == "contingency"
        assert default_count_matrix(app.tables["Rearranged data"].frame())
        assert app.save()
        app.import_file(path)
        app.show("data", "Rearranged data")
        assert default_count_matrix(app.tables["Rearranged data"].frame())

        def choose_fisher(dialog):
            pick_method(dialog, CONTINGENCY)
            assert dialog.controls["Input format"][1].get() == COUNT_MATRIX
            assert not dialog.contingency_visibility()["Rows"]
            assert dialog.contingency_visibility()["Count columns"]
            dialog.controls["Test"][1].set(FISHER)
            assert dialog.contingency_visibility()["Fisher alternative"]

        drive_dialog(AnalysisDialog, choose_fisher)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[1]
        tables = run.result.tables
        assert tables["Counts"].to_numpy().tolist() == [[688, 21], [650, 59]]
        assert tables["Comparison order"].loc["Event column", "Value"] == "Event"
        assert np.isclose(tables["Tests"].loc["p", "Value"], 1.4763034416458248e-5)
        effects = tables["2 × 2 effects"]
        np.testing.assert_allclose(effects.loc["Odds ratio", ["Estimate", "Lower", "Upper"]].astype(float),
                                   [2.973772893772894, 1.78673703018007, 4.94942740558030])
        app.result_tabs.select(list(tables).index("2 × 2 effects"))
        effects_grid = app.result_tabs.nametowidget(app.result_tabs.select())
        assert int(effects_grid.tree.column("#0", "width")) >= 200
        app.search_placeholder = True
        app.search_input.set("Search sheets…")
        capture(root, "window-contingency-effects.png")

        def change_test(dialog):
            assert dialog.controls["Input format"][1].get() == COUNT_MATRIX
            dialog.controls["Test"][1].set(MONTE_CARLO)
            dialog.controls["Monte Carlo samples"][1].set("1999")
            dialog.controls["Seed"][1].set("719")
            assert dialog.contingency_visibility()["Seed"]
            assert not dialog.contingency_visibility()["Fisher alternative"]
            dialog.focus_field("Seed")
            capture(dialog, "window-contingency-options.png")

        drive_dialog(AnalysisDialog, change_test)
        app.edit_analysis()
        wait_for_calculation()
        edited = app.runs[1]
        assert edited.result.tables["Tests"].loc["Seed", "Value"] == 719
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 1))
        wait_for_calculation()
        assert app.runs[1].options == edited.options
        pd.testing.assert_frame_equal(app.runs[1].result.tables["Tests"], edited.result.tables["Tests"])

        table = pd.DataFrame({"Row title": ["Control", "Treatment"], "Improved": [0, 3],
                              "Stable": [2, 0], "Worse": [1, 1]})
        table.attrs["table_format"] = "contingency"
        app._add_tables({"Three outcome categories": table})

        def exact_rxc(dialog):
            pick_method(dialog, CONTINGENCY)
            assert dialog.controls["Input format"][1].get() == COUNT_MATRIX
            dialog.controls["Test"][1].set(FISHER_RXC)
            assert not dialog.contingency_visibility()["Fisher alternative"]
            assert not dialog.contingency_visibility()["Seed"]

        drive_dialog(AnalysisDialog, exact_rxc)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[-1]
        test = run.result.tables["Tests"]["Value"]
        assert test["p"] == 1 / 7 and test["Fixed-margin tables"] == 8
        app.result_tabs.select(list(run.result.tables).index("Tests"))
        result_grid = app.result_tabs.nametowidget(app.result_tabs.select())
        assert int(result_grid.tree.column("col0", "width")) > 104
        capture(root, "window-fisher-exact-rxc.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", len(app.runs) - 1))
        wait_for_calculation()
        pd.testing.assert_series_equal(app.runs[-1].result.tables["Tests"]["Value"], test)

    def check_contingency_intervals_workflow():
        path = directory / "contingency-intervals.alab"
        title = "Screening results"
        # First row = positive test, first column = condition present: TP, FP / FN, TN.
        table = pd.DataFrame({"Row title": ["Positive test", "Negative test"], "Present": [12, 5], "Absent": [18, 20]})
        table.attrs["table_format"] = "contingency"
        save_project(path, {title: Dataset(table)})
        app.import_file(path)

        def koopman_dialog(dialog):
            pick_method(dialog, CONTINGENCY)
            assert dialog.controls["Input format"][1].get() == COUNT_MATRIX
            assert dialog.controls["Relative risk interval"][1].get() == "Katz"
            assert dialog.controls["Diagnostic measures"][1].get() is False
            assert not dialog.contingency_visibility()["Diagnostic interval"]
            dialog.controls["Relative risk interval"][1].set("Koopman score")
            dialog.controls["Diagnostic measures"][1].set(True)
            assert dialog.contingency_visibility()["Diagnostic interval"]
            dialog.controls["Diagnostic interval"][1].set(WILSON_BROWN)
            dialog.controls["Confidence level (%)"][1].set("40")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False  # The dialog stays open on the level field.
            assert "Wilson–Brown requires" in shown.call_args.args[1]
            assert dialog.fields.select() == str(dialog.field_rows["Confidence level (%)"][1].master)
            capture(dialog, "window-contingency-level-error.png")
            dialog.controls["Confidence level (%)"][1].set("95")
            dialog.controls["Diagnostic interval"][1].set(INTERVALS[1])
            capture(dialog, "window-contingency-diagnostic-options.png")

        drive_dialog(AnalysisDialog, koopman_dialog)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[-1]
        tables = run.result.tables
        risk = tables["2 × 2 effects"].loc["Relative risk"]
        assert risk["Interval method"] == "Koopman score"
        np.testing.assert_allclose(risk[["Estimate", "Lower", "Upper"]].astype(float),
                                   [2, 0.8652526331656134, 4.933971535197795], rtol=1e-12)
        order = tables["Comparison order"]["Value"]
        assert order["Relative risk numerator row"] == "Positive test" and order["Event column"] == "Present"
        measures = tables["Diagnostic measures"]
        np.testing.assert_allclose(measures["Estimate"].astype(float), [12 / 17, 20 / 38, 12 / 30, 20 / 25, 32 / 55])
        assert set(measures["Interval method"]) == {INTERVALS[1]}
        assert tables["Diagnostic orientation"].loc["Condition present (column)", "Value"] == "Present"
        app.result_tabs.select(list(tables).index("Diagnostic measures"))
        capture(root, "window-contingency-diagnostic-measures.png")
        app.result_tabs.select(list(tables).index("2 × 2 effects"))
        capture(root, "window-contingency-koopman.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", len(app.runs) - 1))
        wait_for_calculation()
        reopened = app.runs[-1]
        assert reopened.options == run.options
        pd.testing.assert_frame_equal(reopened.result.tables["Diagnostic measures"], measures)
        # Edit a source count: every sheet is recalculated from the new table.
        app.show("data", title)
        app.edit_cell(0, 1, "14")
        app.recalculate(len(app.runs) - 1)
        wait_for_calculation()
        edited = app.runs[-1].result.tables
        assert np.isclose(edited["Diagnostic measures"].loc["Sensitivity", "Estimate"], 14 / 19)
        assert edited["2 × 2 effects"].loc["Relative risk", "Estimate"] > risk["Estimate"]

        # A table that is not 2 × 2 explains the problem on the field.
        three = pd.DataFrame({"Row title": ["Control", "Treatment"], "Improved": [0, 3], "Stable": [2, 0], "Worse": [1, 1]})
        three.attrs["table_format"] = "contingency"
        app._add_tables({"Three-way outcomes": three})

        def not_two_by_two(dialog):
            pick_method(dialog, CONTINGENCY)
            dialog.controls["Diagnostic measures"][1].set(True)
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "exactly two rows" in shown.call_args.args[1]
            assert dialog.fields.select() == str(dialog.field_rows["Diagnostic measures"][1].master)
            capture(dialog, "window-contingency-diagnostic-not-2x2.png")
            dialog.controls["Diagnostic measures"][1].set(False)

        drive_dialog(AnalysisDialog, not_two_by_two)
        app.choose_analysis()
        wait_for_calculation()
        assert "Diagnostic measures" not in app.runs[-1].result.tables

    def check_baptista_pike_workflow():
        path = directory / "baptista-pike.alab"
        title = "Outcomes by group"
        table = pd.DataFrame({"Row title": ["Group A", "Group B"], "Event": [0, 5], "No event": [10, 5]})
        table.attrs["table_format"] = "contingency"
        save_project(path, {title: Dataset(table)})
        app.import_file(path)

        def select_exact_interval(dialog):
            pick_method(dialog, CONTINGENCY)
            assert dialog.controls["Input format"][1].get() == COUNT_MATRIX
            interval = dialog.focus_field("Odds ratio interval")
            assert interval.get() == "Woolf (logit)"
            interval.current(interval["values"].index(BAPTISTA_PIKE))
            capture(dialog, "window-baptista-pike-options.png")

        drive_dialog(AnalysisDialog, select_exact_interval)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[-1]
        sheets = run.result.tables
        effects = sheets["2 × 2 effects"]
        odds = effects.loc["Odds ratio"]
        assert odds["Interval method"] == BAPTISTA_PIKE
        np.testing.assert_allclose(odds[["Estimate", "Lower", "Upper"]].astype(float),
                                   [0, 0, 0.6384347568185281], rtol=1e-12)
        app.result_tabs.select(list(sheets).index("2 × 2 effects"))
        capture(root, "window-baptista-pike-results.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", len(app.runs) - 1))
        wait_for_calculation()
        reopened = app.runs[-1]
        assert reopened.options == run.options
        pd.testing.assert_frame_equal(reopened.result.tables["2 × 2 effects"], effects)
        app.show("data", title)
        app.edit_cell(0, 1, "1")
        app.recalculate(len(app.runs) - 1)
        wait_for_calculation()
        edited = app.runs[-1].result.tables["2 × 2 effects"].loc["Odds ratio"]
        assert edited["Interval method"] == BAPTISTA_PIKE
        assert edited["Estimate"] == 0.1
        assert 0 < edited["Lower"] < edited["Estimate"] < edited["Upper"]

    def check_nested_workflow(reference):
        source = reference.parent / "nestedttest-031.xml" if reference is not None else None
        if source is not None and source.is_file():
            title, frame = next(iter(load_tables(source).items()))
        else:
            title = "Nested example"
            template = next(item for item in TEMPLATES if item.kind == "nested")
            frame = table_frame(template, True)
        path = directory / "nested-workflow.alab"
        save_project(path, {title: Dataset(frame)})
        app.import_file(path)
        assert app.tables[title].table_format.casefold() == "nested"
        assert [band[2] for band in app.current_grid.bands] == ["Group A"] * 3 + ["Group B"] * 3

        def options(dialog):
            assert dialog.method == NESTED_T
            box = dialog.controls[NESTED_SUBCOLUMNS][1]
            assert len(box.curselection()) == 6
            assert dialog.controls["Denominator method"][1].get() == "Kenward–Roger"
            dialog.controls["Confidence level (%)"][1].set("90,5")
            dialog.focus_field("Confidence level (%)")
            capture(dialog, "window-nested-options.png")

        drive_dialog(AnalysisDialog, options)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        first = run.result.tables["Difference of means"].copy()
        assert "CI 90.5% low" in first and np.isfinite(first["p"]).all()
        app.show("data", title)
        app.edit_cell(0, 0, str(float(frame.iat[0, 0]) + .5))
        wait_for_calculation()
        updated = run.result.tables["Difference of means"].copy()
        assert first.iat[0, 0] != updated.iat[0, 0]
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        root.update_idletasks()
        toolbar = next(child for child in app.page.winfo_children() if isinstance(child, NavigationToolbar2Tk))
        assert toolbar.winfo_height() >= toolbar.winfo_reqheight()
        capture(root, "window-nested-estimates.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Difference of means"], updated)

    def check_parts_of_whole():
        path = directory / "composition.alab"
        title = "Seed categories"
        template = next(item for item in TEMPLATES if item.kind == "parts_of_whole")
        assert table_frame(template, True).columns.tolist() == ["Row title", "Count"]
        data = pd.DataFrame({"Row title": ["Round yellow", "Round green", "Angular yellow", "Angular green"],
                             "Count": [315, 108, 101, 32], "Expected weight": [9, 3, 3, 1]})
        data.attrs["table_format"] = template.kind
        save_project(path, {title: Dataset(data)})
        app.import_file(path)
        app.search_placeholder = True
        app.search_input.set("Search sheets…")

        def donut(dialog):
            assert dialog.method == PARTS_GRAPH
            dialog.controls["Values"][1].set("Count")
            dialog.controls["Donut hole (%)"][1].set("45,5")
            assert dialog.parts_visibility()["Donut hole (%)"]
            assert not dialog.parts_visibility()["Number of dots"]

        drive_dialog(AnalysisDialog, donut)
        app.new_graph()
        wait_for_calculation()
        run = app.runs[0]
        assert run.method == PARTS_GRAPH and run.result.tables["Total"].iat[0, 0] == 556
        assert all(np.isclose(wedge.width, .545) for wedge in run.result.figure.axes[0].patches)
        app.show("graph", 0)
        capture(root, "window-parts-donut.png")

        def compare(dialog):
            pick_method(dialog, GOODNESS_OF_FIT)
            dialog.controls["Observed counts"][1].set("Count")
            dialog.controls["Expected distribution"][1].set(EXPECTED_DISTRIBUTIONS[1])
            dialog.controls["Expected values"][1].set("Expected weight")
            assert dialog.parts_visibility()["Expected values"]

        app.show("data", title)
        drive_dialog(AnalysisDialog, compare)
        app.choose_analysis()
        wait_for_calculation()
        result = app.runs[1]
        assert np.isclose(result.result.tables["Test"].loc["Pearson χ²", "Value"], .470023980815)
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].options == run.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Composition"], run.result.tables["Composition"])

    def check_frequency_distribution():
        path = directory / "frequency.alab"
        title = "Measurements"
        data = pd.DataFrame({"Control": [3.5, 4.0, 4.5, 4.5, 5.5, None],
                             "Treatment": [3.4, 3.5, 4.5, 5.2, 5.5, 7.0]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def binned(dialog):
            pick_method(dialog, FREQUENCY)
            select_columns(dialog, "Variables", {"Control", "Treatment"})
            dialog.controls["Bin width (blank = automatic)"][1].set("1")
            dialog.controls["First bin center (blank = automatic)"][1].set("4")
            dialog.controls["Maximum value (blank = no limit)"][1].set("5,5")

        drive_dialog(AnalysisDialog, binned)
        app.choose_analysis()
        wait_for_calculation()
        result = app.runs[0].result
        assert result.tables["Frequencies"]["Counts"].tolist() == [2, 2, 1, 1, 2, 1]
        assert result.tables["Observation counts"]["Omitted"].tolist() == [0, 2]

        def exact(dialog):
            dialog.controls["Distribution"][1].set(EXACT_FREQUENCY)
            dialog.controls["Units"][1].set("Percentages")
            assert dialog.frequency_visibility()["Y scale"]
            dialog.controls["Y scale"][1].set("Gaussian probability")
            assert not dialog.frequency_visibility()["Bin width (blank = automatic)"]

        drive_dialog(AnalysisDialog, exact)
        app.edit_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert "Bin width (blank = automatic)" not in run.options
        table = run.result.tables["Frequencies"]
        assert table.groupby("Variable")["Percentages"].last().tolist() == [100., 100.]
        app.show("graph", 0)
        assert run.result.figure.axes[0].get_yscale() == "probability %"
        capture(root, "window-frequency-distribution.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Frequencies"], table)

    def check_rank_comparisons():
        import math

        path = directory / "dunn-comparisons.alab"
        title = "Treatment ranks"
        data = pd.DataFrame({"Value": [1, 2, 2, 3, 3, 4, 4, 5, 6], "Arm": list("AAABBBCCC")})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def select_pairs(dialog):
            pick_method(dialog, "Kruskal–Wallis")
            assert not dialog.dunn_visibility()[DUNN_PAIRS]
            assert dialog.controls[KRUSKAL_P][1].get() == "Automatic"
            dialog.controls["Response"][1].set("Value")
            dialog.controls["Group"][1].set("Arm")
            dialog.controls[DUNN][1].set(DUNN_PAIRS)
            assert dialog.dunn_visibility()[DUNN_PAIRS]
            dialog.controls[KRUSKAL_P][1].set(EXACT_P)
            picker = dialog.controls[DUNN_PAIRS][1]
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert DUNN_PAIRS in report.call_args.args[1]
            for first, second in (("C", "A"), ("B", "A"), ("A", "C")):
                picker.first.set(first)
                picker.second.set(second)
                picker.add_pair()
            assert picker.values() == [["C", "A"], ["B", "A"]]
            picker.listbox.selection_set(1)
            picker.remove_pair()
            picker.first.set("C")
            picker.second.set("B")
            picker.add_pair()
            dialog.controls[DUNN_ALPHA][1].set("0,05")
            dialog.fields.select(dialog.field_rows[DUNN][1].master)
            capture(dialog, "window-dunn-selected-pairs.png")

        drive_dialog(AnalysisDialog, select_pairs)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        summary = run.result.tables["Kruskal–Wallis"]["Value"]
        assert summary["p method"] == EXACT_P
        pairs = run.result.tables[DUNN]
        assert list(zip(pairs["First"], pairs["Second"])) == [("C", "A"), ("C", "B")]
        assert np.isclose(pairs.iloc[0]["Adjusted p"], 2 * math.erfc((35 / 6) / math.sqrt(9.75)))
        app.show("result", 0)
        capture(root, "window-kruskal-exact.png")
        app.show("result", 0)
        app.result_tabs.select(1)
        capture(root, "window-dunn-results.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        assert app.runs[0].options == run.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables[DUNN], pairs)
        app.show("data", title)
        app.edit_cell(0, 0, "9")
        app.show("result", 0)
        wait_for_calculation()
        changed = app.runs[0].result.tables[DUNN]
        assert changed.iloc[0]["Adjusted p"] > pairs.iloc[0]["Adjusted p"]

    def check_normality_qq():
        from analisi.normality import ALPHA, QQ_LINE, QQ_SHEET, SHAPIRO, TESTS

        path = directory / "normality.alab"
        title = "Assay readings"
        control = [1, 2, 3, 4, 6, 9, 10, 12, 15, 18, 25, 45]
        drug = [4.1, 5.2, 5.0, 6.3, 7.1, 6.8, 5.9, 7.7, 8.2, 6.1, 9.4, 7.0]
        data = pd.DataFrame({"Control": control, "Drug A": drug, "Flat": [3.0] * 12})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def choose(dialog):
            pick_method(dialog, NORMALITY)
            assert dialog.controls[SHAPIRO][1].get() is True
            assert not any(dialog.controls[test][1].get() for test in TESTS[1:])
            assert dialog.controls[ALPHA][1].get() == "0.05"
            assert dialog.normality_fields() == {QQ_VARIABLE: False, QQ_LINE: False}
            select_columns(dialog, "Variables", {"Control", "Drug A", "Flat"})
            for test in TESTS:
                dialog.controls[test][1].set(True)
            # A bad significance level keeps the dialog open on its field.
            for text in ("0", "1", "1,5", "-0,1", "abc", "nan"):
                dialog.controls[ALPHA][1].set(text)
                with patch.object(messagebox, "showerror") as report:
                    assert dialog.validate() is False, text
                assert "Alpha" in report.call_args.args[1], report.call_args
                assert dialog.fields.select() == str(dialog.field_rows[ALPHA][1].master)
                if text == "abc":
                    capture(dialog, "window-normality-alpha-error.png")
            dialog.controls[ALPHA][1].set("0,05")
            for test in TESTS:
                dialog.controls[test][1].set(False)
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "at least one normality test" in report.call_args.args[1], report.call_args
            for test in TESTS:
                dialog.controls[test][1].set(True)
            capture(dialog, "window-normality-options.png")
            dialog.controls[QQ_PLOT][1].set(True)
            assert dialog.normality_fields() == {QQ_VARIABLE: True, QQ_LINE: True}
            assert list(dialog.field_rows[QQ_VARIABLE][1].cget("values")) == ["", "Control", "Drug A", "Flat"]
            # Several variables need an explicit Q–Q variable.
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert QQ_VARIABLE in report.call_args.args[1], report.call_args
            dialog.controls[QQ_VARIABLE][1].set("Drug A")
            select_columns(dialog, "Variables", {"Control", "Flat"})
            dialog.update_qq_choices()
            assert dialog.controls[QQ_VARIABLE][1].get() == ""
            select_columns(dialog, "Variables", {"Control", "Drug A", "Flat"})
            dialog.update_qq_choices()
            dialog.controls[QQ_VARIABLE][1].set("Drug A")
            capture(dialog, "window-normality-qq-variable.png")
            dialog.focus_field(QQ_PLOT)
            capture(dialog, "window-normality-qq-options.png")

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        table = run.result.tables[NORMALITY]
        assert table["Variable"].tolist() == ["Control"] * 4 + ["Drug A"] * 4 + ["Flat"] * 4
        assert table["Test"].tolist() == list(TESTS) * 3
        assert abs(table.iloc[0]["Statistic"] - 0.8237707988021571) < 1e-12
        assert abs(table.iloc[3]["p"] - 0.3330429843534023) < 1e-12
        assert table[table["Variable"] == "Flat"]["Decision"].eq("Not tested").all()
        assert run.options[QQ_PLOT] is True and run.options[QQ_VARIABLE] == "Drug A" and run.options[ALPHA] == 0.05
        coordinates = run.result.tables[QQ_SHEET]
        assert coordinates["Observed value"].tolist() == sorted(drug)
        assert coordinates["Source row"].tolist() == [int(i) + 1 for i in np.argsort(drug, kind="stable")]
        assert run.result.figure.axes[0].get_ylabel() == "Observed value (Drug A)"
        app.show("result", 0)
        capture(root, "window-normality-results.png")
        app.show("graph", 0)
        capture(root, "window-qq-plot.png")

        # Exports go through the real dialog flow.
        for suffix in ("png", "svg"):
            target = directory / f"qq-plot.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, target
        assert b"<svg " in (directory / "qq-plot.svg").read_bytes()

        # The variable moves to another column and the choice persists.
        def other_column(dialog):
            dialog.controls[QQ_VARIABLE][1].set("Control")
            dialog.controls[QQ_LINE][1].set(False)

        drive_dialog(AnalysisDialog, other_column)
        app.edit_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert run.options[QQ_VARIABLE] == "Control" and run.options[QQ_LINE] is False
        assert run.result.tables[QQ_SHEET]["Observed value"].tolist() == sorted(control)
        assert not run.result.figure.axes[0].lines
        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options[QQ_VARIABLE] == "Control" and reopened.options[QQ_PLOT] is True
        pd.testing.assert_frame_equal(reopened.result.tables[QQ_SHEET], run.result.tables[QQ_SHEET])
        pd.testing.assert_frame_equal(reopened.result.tables[NORMALITY], table)

        # An excluded cell and an edited value both change the linked results.
        app.show("data", title)
        app.current_grid.select((11, 0))
        app.toggle_exclusion()
        wait_for_calculation()
        shorter = app.runs[0].result.tables[QQ_SHEET]
        assert len(shorter) == 11 and 45 not in shorter["Observed value"].tolist()
        app.show("data", title)
        app.edit_cell(0, 0, "7")
        wait_for_calculation()
        edited = app.runs[0].result.tables[QQ_SHEET]
        assert edited["Source row"].tolist()[edited["Observed value"].tolist().index(7.0)] == 1
        assert app.runs[0].result.tables[NORMALITY].iloc[0]["N"] == 11

        # The Q–Q sheet becomes ordinary worksheet data.
        app.show("result", 0)
        app.result_tabs.select(1)
        app.use_result_as_data()
        assert app.tables[QQ_SHEET].raw["Observed value"].tolist() == edited["Observed value"].tolist()
        assert app.tables[QQ_SHEET].raw["Theoretical quantile"].notna().all()

        # Recipes saved before the test choices existed keep the Shapiro–Wilk sheet.
        legacy = directory / "normality-legacy.alab"
        save_project(legacy, {"Old": Dataset(data, analyses=[(NORMALITY, {"Variables": ["Control", "Drug A"]})])})
        app.import_file(legacy)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        old = app.runs[0].result
        assert list(old.tables) == ["Normality"] and old.figure is None
        assert old.tables["Normality"].index.tolist() == ["Control", "Drug A"]
        assert abs(old.tables["Normality"].loc["Control", "Shapiro–Wilk W"] - 0.8237707988021571) < 1e-12

    def check_friedman_exact():
        from analisi import friedman_exact

        path = directory / "friedman-exact.alab"
        title = "Friedman ties"
        scores = [[1, 1, 3], [2, 1, 3], [1, 3, 3], [1, 2, 4]]
        data = pd.DataFrame([(f"S{i + 1}", arm, value) for i, row in enumerate(scores) for arm, value in zip("ABC", row)],
                            columns=["Subject", "Treatment", "Score"])
        roles = {"Response": "Score", "Group": "Treatment", "Subject": "Subject"}
        # A recipe saved before the P value option is recalculated with Automatic.
        save_project(path, {title: Dataset(data, analyses=[("Friedman", dict(roles))])})
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        assert FRIEDMAN_P not in app.runs[0].options
        legacy = app.runs[0].result.tables["Friedman"].iloc[0]
        assert legacy["p method"] == EXACT_P and legacy["p"] == 5 / 54 and "p method reason" not in legacy.index

        def exact_all_pairs(dialog):
            pick_method(dialog, "Friedman")
            assert dialog.controls[FRIEDMAN_P][1].get() == "Automatic"
            assert dialog.field_rows[FRIEDMAN_P][1].master is dialog.field_rows["Response"][1].master
            for label, value in roles.items():
                dialog.controls[label][1].set(value)
            dialog.controls[DUNN][1].set("All pairs")
            dialog.fields.select(dialog.field_rows["Response"][1].master)
            capture(dialog, "window-friedman-options.png")

        drive_dialog(AnalysisDialog, exact_all_pairs)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[1]
        summary = run.result.tables["Friedman"].iloc[0]
        assert summary["p method"] == EXACT_P and summary["p"] == 5 / 54
        assert abs(summary["Statistic"] - 39 / 7) < 1e-12 and summary["df"] == 2
        dunn = run.result.tables[DUNN]
        assert len(dunn) == 3
        app.show("result", 1)
        capture(root, "window-friedman-exact.png")

        # Saving, reopening, editing the source and exporting keep the method.
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 1))
        wait_for_calculation()
        assert app.runs[1].options == run.options
        pd.testing.assert_frame_equal(app.runs[1].result.tables["Friedman"], run.result.tables["Friedman"])
        pd.testing.assert_frame_equal(app.runs[1].result.tables[DUNN], dunn)
        app.show("data", title)
        app.edit_cell(0, 2, "2")
        app.show("result", 1)
        wait_for_calculation()
        edited = np.array([[2, 1, 3], [2, 1, 3], [1, 3, 3], [1, 2, 4]])
        extreme, total = friedman_exact.friedman_exact_tail(edited)
        changed = app.runs[1].result.tables["Friedman"].iloc[0]
        assert changed["p method"] == EXACT_P and changed["p"] == extreme / total != summary["p"]
        target = directory / "friedman-exact.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.result_tabs.select(0)
            app.export()
        exported = pd.read_csv(target)
        assert exported["p method"].iloc[0] == EXACT_P and exported["p"].iloc[0] == changed["p"]
        app.edit_cell(0, 2, "1")

        def chi_square(dialog):
            assert dialog.controls[FRIEDMAN_P][1].get() == "Automatic"
            dialog.controls[FRIEDMAN_P][1].set(CHI_SQUARE_P)

        app.show("result", 1)
        wait_for_calculation()
        drive_dialog(AnalysisDialog, chi_square)
        app.edit_analysis()
        wait_for_calculation()
        chi = app.runs[1].result.tables["Friedman"].iloc[0]
        assert chi["p method"] == CHI_SQUARE_P and abs(chi["p"] - 0.06168501256797605) < 1e-12
        assert "p method reason" not in chi.index
        # The global p value does not change Dunn's comparisons.
        pd.testing.assert_frame_equal(app.runs[1].result.tables[DUNN], dunn)

        def over_budget(dialog):
            dialog.controls[FRIEDMAN_P][1].set(EXACT_P)
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert FRIEDMAN_P in report.call_args.args[1] and "limit" in report.call_args.args[1], report.call_args
            assert dialog.fields.select() == str(dialog.field_rows[FRIEDMAN_P][1].master)
            capture(dialog, "window-friedman-error.png")
            dialog.controls[FRIEDMAN_P][1].set(AUTOMATIC_P)

        with patch.object(friedman_exact, "_MAX_STATES", 1):
            drive_dialog(AnalysisDialog, over_budget)
            app.edit_analysis()
            wait_for_calculation()
            fallback = app.runs[1].result.tables["Friedman"].iloc[0]
            assert fallback["p method"] == CHI_SQUARE_P and "work limit" in fallback["p method reason"]
            app.show("result", 1)
            capture(root, "window-friedman-fallback.png")

    def check_bland_altman_agreement():
        from analisi.exploration import (CONFIDENCE as BA_CONFIDENCE, CONFIDENCE_BANDS as BA_BANDS,
                                         COVERAGE as BA_COVERAGE, LOG_RATIO)

        method, title = "Bland–Altman", "Method comparison"
        data = pd.DataFrame({"First": [1., 2, 8, 16, 5], "Second": [2., 2, 4, 4, np.nan],
                             "WithZero": [1., 0, 8, 16, 5]})
        path = directory / "bland-altman.alab"
        # A recipe saved before coverage, intervals and the log ratio existed carries none of the new keys.
        save_project(path, {title: Dataset(data, analyses=[(method, {"First": "First", "Second": "Second",
                                                                    "Method": "Difference"})])})
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        old = app.runs[0].result.tables["Agreement"]["Value"]
        assert old["N"] == 4 and abs(old["Bias CI 95% low"]) < 100 and "Lower limit CI low" not in old.index
        assert [t.get_text() for t in app.runs[0].result.figure.axes[0].get_legend().get_texts()] == [
            "Bias", "Lower agreement limit", "Upper agreement limit"]

        def configure(dialog):
            assert dialog.controls[BA_COVERAGE][1].get() == "95.0" and dialog.controls[BA_CONFIDENCE][1].get() == "95.0"
            # Hidden until the limit intervals are on.
            assert not dialog.field_rows[BA_CONFIDENCE][1].grid_info() and not dialog.field_rows[BA_BANDS][1].grid_info()
            dialog.controls["First"][1].set("First")
            dialog.controls["Second"][1].set("First")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "distinct" in shown.call_args.args[1], shown.call_args
            assert dialog.fields.select() == str(dialog.field_rows["Second"][1].master)
            dialog.controls["Second"][1].set("Second")
            dialog.controls[BA_COVERAGE][1].set("100")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert BA_COVERAGE in shown.call_args.args[1], shown.call_args
            assert dialog.fields.select() == str(dialog.field_rows[BA_COVERAGE][1].master)
            capture(dialog, "window-bland-altman-coverage-error.png")
            dialog.controls[BA_COVERAGE][1].set("95")
            dialog.controls[BLAND_ALTMAN_INTERVALS][1].set(True)
            assert dialog.field_rows[BA_CONFIDENCE][1].grid_info() and dialog.field_rows[BA_BANDS][1].grid_info()
            dialog.controls[BA_CONFIDENCE][1].set("0")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert BA_CONFIDENCE in shown.call_args.args[1], shown.call_args
            assert dialog.fields.select() == str(dialog.field_rows[BA_CONFIDENCE][1].master)
            dialog.controls[BA_CONFIDENCE][1].set("95")
            dialog.controls["Method"][1].set(LOG_RATIO)
            dialog.controls["First"][1].set("WithZero")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "WithZero" in shown.call_args.args[1] and "row 2" in shown.call_args.args[1], shown.call_args
            assert dialog.fields.select() == str(dialog.field_rows["First"][1].master)
            capture(dialog, "window-bland-altman-nonpositive-error.png")
            dialog.controls["First"][1].set("First")
            dialog.controls[BA_BANDS][1].set(True)
            dialog.focus_field(BA_BANDS)
            capture(dialog, "window-bland-altman-options.png")
            assert dialog.validate() is True
            dialog.result = None

        drive_dialog(AnalysisDialog, lambda dialog: (pick_method(dialog, method), configure(dialog)))
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[-1]
        report = run.result.tables["Agreement"]["Value"]
        assert run.options["Method"] == LOG_RATIO and run.options[BLAND_ALTMAN_INTERVALS] is True
        assert report["N"] == 4 and abs(report["Bias"] - 2 ** .5) < 1e-12
        assert abs(report["Upper limit CI high"] / 119.9926744066 - 1) < 1e-8
        axis = run.result.figure.axes[0]
        assert axis.get_yscale() == "log" and axis.get_ylabel() == "First / Second" and len(axis.patches) == 2
        legend = [t.get_text() for t in run.result.figure.legends[0].get_texts()]
        assert {"Bias", "Lower limit CI", "Upper limit CI"} <= set(legend), legend
        new = len(app.runs) - 1
        app.show("result", new)
        capture(root, "window-bland-altman-agreement.png")
        app.show("graph", new)
        capture(root, "window-bland-altman-graph.png")
        for suffix in ("png", "svg"):
            target = directory / f"bland-altman.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, target
        assert b"<svg " in (directory / "bland-altman.svg").read_bytes()
        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("result", new))
        wait_for_calculation()
        assert app.runs[-1].options[BLAND_ALTMAN_INTERVALS] is True and app.runs[-1].options["Method"] == LOG_RATIO
        # Editing a cell recalculates: the first ratio becomes 1, so the geometric bias is 2 ** .75.
        app.edit_cell(0, 0, "2")
        wait_for_calculation()
        assert abs(app.runs[-1].result.tables["Agreement"]["Value"]["Bias"] - 2 ** .75) < 1e-12
        # Excluding one pair removes it from N.
        app.show("data", title)
        app.current_grid.select((3, 1))
        app.toggle_exclusion()
        wait_for_calculation()
        assert app.runs[-1].result.tables["Agreement"]["Value"]["N"] == 3

    def check_anova_effect_sizes():
        from analisi.workbench import ANOVA_MODEL_FIT

        path = directory / "anova-effect-sizes.alab"
        title = "Two-way balanced"
        data = pd.DataFrame({"A": ["Low"] * 4 + ["High"] * 4, "B": ["Low", "Low", "High", "High"] * 2,
                             "Y": [5, 7, 9, 11, 7, 9, 15, 17]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def choose(dialog):
            pick_method(dialog, "Multifactor ANOVA")
            assert dialog.controls[ANOVA_EFFECTS][1].get() is False
            assert dialog.anova_fields() == {ANOVA_ALPHA: False}
            dialog.controls["Response"][1].set("Y")
            select_columns(dialog, "Factors", {"A", "B"})
            dialog.controls["Interaction order"][1].set("2")
            dialog.controls["Compare marginal means by"][1].set("A")
            dialog.controls[ANOVA_EFFECTS][1].set(True)
            assert dialog.anova_fields() == {ANOVA_ALPHA: True}
            assert dialog.controls[ANOVA_ALPHA][1].get() == "0.05"
            # A bad significance level keeps the dialog open on its field.
            for text in ("0", "1", "1,5", "-0,1", "abc", "nan", "inf"):
                dialog.controls[ANOVA_ALPHA][1].set(text)
                with patch.object(messagebox, "showerror") as report:
                    assert dialog.validate() is False, text
                assert "Alpha" in report.call_args.args[1], report.call_args
                assert dialog.fields.select() == str(dialog.field_rows[ANOVA_ALPHA][1].master)
                if text == "1,5":
                    capture(dialog, "window-anova-alpha-error.png")
            dialog.controls[ANOVA_ALPHA][1].set("0,05")
            capture(dialog, "window-anova-effect-options.png")

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        run = app.runs[index]
        assert run.options[ANOVA_EFFECTS] is True and run.options[ANOVA_ALPHA] == 0.05
        assert list(run.result.tables) == ["ANOVA (type III)", ANOVA_EFFECTS, ANOVA_MODEL_FIT,
                                           "Multiple comparisons"], list(run.result.tables)
        effects = run.result.tables[ANOVA_EFFECTS]
        np.testing.assert_allclose(effects["Eta squared"], [32 / 120, 72 / 120, 8 / 120])
        np.testing.assert_allclose(effects["Partial eta squared"], [.8, .9, .5])
        np.testing.assert_allclose(effects["Cohen f"], [2, 3, 1])
        assert effects["Significant"].tolist() == ["Yes", "Yes", "No"]
        fit = run.result.tables[ANOVA_MODEL_FIT]["Value"]
        assert fit["N"] == 8 and fit["Residual df"] == 4
        assert abs(fit["R²"] - 14 / 15) < 1e-12 and abs(fit["Adjusted R²"] - 53 / 60) < 1e-12
        comparisons = run.result.tables["Multiple comparisons"]
        app.show("result", index)
        app.result_tabs.select(1)
        capture(root, "window-anova-effect-sizes.png")
        app.result_tabs.select(2)
        capture(root, "window-anova-model-fit.png")

        # Alpha changes only the Significant column and the post-hoc sheet stays.
        def stricter(dialog):
            assert dialog.anova_fields() == {ANOVA_ALPHA: True}
            dialog.controls[ANOVA_ALPHA][1].set("0,01")

        drive_dialog(AnalysisDialog, stricter)
        app.edit_analysis()
        wait_for_calculation()
        strict = app.runs[index].result
        assert strict.tables[ANOVA_EFFECTS]["Significant"].tolist() == ["No", "Yes", "No"]
        pd.testing.assert_frame_equal(strict.tables[ANOVA_EFFECTS].drop(columns="Significant"),
                                      effects.drop(columns="Significant"))
        pd.testing.assert_frame_equal(strict.tables["Multiple comparisons"], comparisons)

        target = directory / "anova-effect-sizes.csv"
        app.show("result", index)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.result_tabs.select(1)
            app.export()
        exported = pd.read_csv(target)
        assert exported.columns.tolist() == ["Term", "% total variation", "Eta squared", "Partial eta squared",
                                             "Cohen f", "p", "Significant"], exported.columns.tolist()
        assert exported["Significant"].tolist() == ["No", "Yes", "No"]
        np.testing.assert_allclose(exported["Cohen f"], [2, 3, 1])

        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("result", index))
        wait_for_calculation()
        reopened = app.runs[index]
        assert reopened.options[ANOVA_EFFECTS] is True and reopened.options[ANOVA_ALPHA] == 0.01
        for name in strict.tables:
            pd.testing.assert_frame_equal(reopened.result.tables[name], strict.tables[name])

        # An excluded cell recalculates on the complete cases.
        app.show("data", title)
        app.current_grid.select((7, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        masked = app.runs[index].result
        assert masked.tables[ANOVA_MODEL_FIT]["Value"]["N"] == 7
        assert masked.tables[ANOVA_MODEL_FIT]["Value"]["Residual df"] == 3
        assert "Multiple comparisons" in masked.tables
        app.show("data", title)
        app.current_grid.select((7, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        assert app.runs[index].result.tables[ANOVA_MODEL_FIT]["Value"]["N"] == 8

        # The effect sizes become ordinary worksheet data.
        app.show("result", index)
        app.result_tabs.select(1)
        app.use_result_as_data()
        sheet = app.tables[ANOVA_EFFECTS].raw
        assert sheet["Term"].tolist() == ["A", "B", "A:B"], sheet.columns.tolist()
        np.testing.assert_allclose(sheet["Cohen f"].astype(float), [2, 3, 1])

        # Recipes saved before Effect sizes keep the single ANOVA sheet and open with the option off.
        legacy = directory / "anova-legacy.alab"
        save_project(legacy, {"Old": Dataset(data, analyses=[("Multifactor ANOVA", {
            "Response": "Y", "Factors": ["A", "B"], "Interaction order": 2})])})
        app.import_file(legacy)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        old = app.runs[0]
        assert list(old.result.tables) == ["ANOVA (type III)"], list(old.result.tables)
        assert abs(old.result.tables["ANOVA (type III)"].loc["A:B", "SS"] - 8) < 1e-9

        def legacy_dialog(dialog):
            assert dialog.controls[ANOVA_EFFECTS][1].get() is False
            assert dialog.anova_fields() == {ANOVA_ALPHA: False}

        drive_dialog(AnalysisDialog, legacy_dialog)
        app.edit_analysis()
        wait_for_calculation()
        assert list(app.runs[0].result.tables) == ["ANOVA (type III)"]

    def check_poisson_exposure():
        from analisi.models import DIAGNOSTICS, EXPOSURE, POISSON_DIAGNOSTICS, RESIDUAL_PLOT

        method, title = "Multiple regression", "Event counts"
        path = directory / "poisson-exposure.alab"
        # The synthetic fixture (rates 1 and 3) plus a row without a count whose spare exposure is 0.
        data = pd.DataFrame({"Count": [0, 2, 4, 0, 3, 6, np.nan], "Group": ["A", "A", "A", "B", "B", "B", "B"],
                             "Exposure": [1., 2, 3, 1, 1, 1, 2], "Spare exposure": [1., 2, 3, 1, 1, 1, 0]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def configure(dialog):
            pick_method(dialog, method)
            dialog.controls["Response"][1].set("Count")
            select_columns(dialog, "Predictors", {"Group"})
            select_columns(dialog, "Categorical predictors", {"Group"})
            dialog.controls["Family"][1].set("Linear")
            assert not dialog.field_rows[EXPOSURE][1].grid_info() and not dialog.field_rows[DIAGNOSTICS][1].grid_info()
            dialog.controls["Family"][1].set("Poisson")
            assert dialog.field_rows[EXPOSURE][1].grid_info() and dialog.field_rows[DIAGNOSTICS][1].grid_info()
            assert dialog.controls[DIAGNOSTICS][1].get() is False and not dialog.field_rows[RESIDUAL_PLOT][1].grid_info()
            # Zero exposure is reported on its field although the count in that row is missing.
            dialog.controls[EXPOSURE][1].set("Spare exposure")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert EXPOSURE in shown.call_args.args[1] and "row 7" in shown.call_args.args[1], shown.call_args
            assert dialog.fields.select() == str(dialog.field_rows[EXPOSURE][1].master)
            capture(dialog, "window-poisson-exposure-error.png")
            dialog.controls[EXPOSURE][1].set("Count")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "distinct" in shown.call_args.args[1], shown.call_args
            dialog.controls[EXPOSURE][1].set("Exposure")
            dialog.controls[DIAGNOSTICS][1].set(True)
            assert dialog.field_rows[RESIDUAL_PLOT][1].grid_info()
            dialog.controls[RESIDUAL_PLOT][1].set(True)
            dialog.focus_field(DIAGNOSTICS)
            capture(dialog, "window-poisson-options.png")
            assert dialog.validate() is True
            dialog.result = None

        drive_dialog(AnalysisDialog, configure)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert run.options[EXPOSURE] == "Exposure" and run.options[DIAGNOSTICS] is True
        coeff = run.result.tables["Coefficients"]
        assert np.allclose(coeff["Estimate"], [0, np.log(3)], atol=1e-8), coeff
        assert abs(coeff.loc["Group [B]", "Exp(estimate)"] - 3) < 1e-8
        report = run.result.tables[POISSON_DIAGNOSTICS]["Value"]
        assert abs(report["Deviance"] - 10.6192227463) < 1e-8 and abs(report["Pearson χ²"] - 7.3333333333) < 1e-8
        assert report["Residual df"] == 4
        fitted = run.result.tables["Fitted values"]
        assert list(fitted.columns) == ["Observed", "Fitted", "Residual", "Source row", "Exposure", "Fitted rate",
                                        "Pearson residual", "Deviance residual"], list(fitted.columns)
        assert np.allclose(fitted["Fitted"], [1, 2, 3, 3, 3, 3]) and fitted["Source row"].tolist() == list(range(6))
        assert abs(fitted["Pearson residual"].iat[0] + 1) < 1e-8 and abs(fitted["Deviance residual"].iat[0] + 2 ** .5) < 1e-8
        axis = run.result.figure.axes[0]
        assert np.allclose(axis.collections[0].get_offsets(), fitted[["Fitted", "Pearson residual"]].to_numpy())
        assert list(axis.lines[0].get_ydata()) == [0, 0] and axis.get_ylabel() == "Pearson residual"
        app.show("result", 0)
        app.result_tabs.select(list(run.result.tables).index(POISSON_DIAGNOSTICS))
        capture(root, "window-poisson-diagnostics.png")
        app.result_tabs.select(list(run.result.tables).index("Fitted values"))
        capture(root, "window-poisson-fitted.png")
        target = directory / "poisson-fitted.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0)
        assert np.allclose(exported["Fitted rate"], [1, 1, 1, 3, 3, 3]), exported
        app.show("graph", 0)
        capture(root, "window-poisson-residuals.png")
        for suffix in ("png", "svg"):
            target = directory / f"poisson-residuals.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, target
        assert b"<svg " in (directory / "poisson-residuals.svg").read_bytes()

        # Editing a count recalculates: group A becomes 7 events over 6 units of exposure.
        app.show("data", title)
        app.edit_cell(0, 0, "1")
        wait_for_calculation()
        assert np.allclose(app.runs[0].result.tables["Fitted values"]["Fitted rate"].iloc[:3], 7 / 6)
        # An excluded exposure drops its row and keeps the identity of the others.
        app.show("data", title)
        app.current_grid.select((1, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        rows = app.runs[0].result.tables["Fitted values"]
        assert rows["Source row"].tolist() == [0, 2, 3, 4, 5], rows["Source row"].tolist()
        assert np.allclose(rows["Fitted rate"].iloc[:2], 5 / 4)
        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options[EXPOSURE] == "Exposure" and reopened.options[RESIDUAL_PLOT] is True
        pd.testing.assert_frame_equal(reopened.result.tables["Fitted values"], rows)

        # The fitted sheet becomes ordinary worksheet data.
        app.show("result", 0)
        app.result_tabs.select(list(reopened.result.tables).index("Fitted values"))
        app.use_result_as_data()
        sheet = app.tables["Fitted values"].raw
        assert sheet["Source row"].tolist() == [0, 2, 3, 4, 5] and np.allclose(sheet["Fitted rate"], rows["Fitted rate"])

        # Clearing Exposure returns to unit exposure.
        def unit(dialog):
            assert dialog.controls[EXPOSURE][1].get() == "Exposure"
            dialog.controls[EXPOSURE][1].set("")

        drive_dialog(AnalysisDialog, unit)
        app.show("result", 0)
        app.edit_analysis()
        wait_for_calculation()
        plain = app.runs[0]
        assert plain.options[EXPOSURE] is None
        # The excluded cell belonged to the exposure, so its row returns: group A counts 1, 2 and 4.
        assert np.allclose(plain.result.tables["Fitted values"]["Fitted"], [7 / 3] * 3 + [3] * 3)
        assert np.allclose(plain.result.tables["Fitted values"]["Exposure"], 1)

        # Recipes saved before exposure and diagnostics keep the three fitted columns and no graph.
        legacy = directory / "poisson-legacy.alab"
        recipe = {"Response": "Count", "Predictors": ["Group"], "Categorical predictors": ["Group"], "Family": "Poisson"}
        save_project(legacy, {"Old": Dataset(data, analyses=[(method, recipe)])})
        app.import_file(legacy)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        old = app.runs[0].result
        assert list(old.tables) == ["Coefficients", "Model", "Reference levels", "Fitted values"], list(old.tables)
        assert list(old.tables["Fitted values"].columns) == ["Observed", "Fitted", "Residual"]
        assert old.figure is None and np.allclose(old.tables["Fitted values"]["Fitted"], [2, 2, 2, 3, 3, 3])

    def check_compare_lines():
        path = directory / "compare-lines.alab"
        title, wide_title = "Lines", "Lines wide"
        long = pd.DataFrame({"X": [0., 1, 2, 3, 0, 1, 2, 3, 4],
                             "Y": [3., 2, 7, 8, -1, 2, 11, 16, None],
                             "Group": ["Control"] * 4 + ["Treated"] * 5})
        wide = pd.DataFrame({"X": [0., 1, 2, 3], "Control": [3., 2, 7, 8], "Treated": [7., 6, 11, 12]})
        legacy = Dataset(long.copy())
        legacy.analyses.append(("Linear regression", {"X": "X", "Y": "Y"}))
        save_project(path, {title: legacy, wide_title: Dataset(wide)})
        app.import_file(path)
        assert [run.method for run in app.runs] == ["Linear regression"]
        app.show("data", title)

        def configure(dialog):
            pick_method(dialog, COMPARE_LINES)
            assert dialog.controls["Input"][1].get() == "Long table"
            dialog.update()
            assert not dialog.field_rows["Y columns"][1].winfo_ismapped()
            dialog.controls["Input"][1].set(LINES_WIDE)
            dialog.update()
            assert dialog.field_rows["Y columns"][1].winfo_ismapped()
            assert not dialog.field_rows["Group"][1].winfo_ismapped()
            dialog.controls["Input"][1].set("Long table")
            for name in ("X", "Y", "Group"):
                dialog.controls[name][1].set(name)
            # Errors keep the dialog open on the field to correct.
            for field, value, correct in (("Alpha", "1.5", "0.05"), ("Group", "X", "Group"), ("Y", "Group", "Y")):
                dialog.controls[field][1].set(value)
                with patch.object(messagebox, "showerror") as report:
                    assert dialog.validate() is False
                assert dialog.winfo_exists()
                assert field in report.call_args.args[1], report.call_args
                if field == "Alpha":
                    capture(dialog, "window-lines-alpha-error.png")
                dialog.controls[field][1].set(correct)
            dialog.fields.select(dialog.field_rows["Alpha"][0].master)
            capture(dialog, "window-lines-options.png")
            dialog.fields.select(dialog.field_rows["X"][0].master)
            capture(dialog, "window-lines-variables.png")

        drive_dialog(AnalysisDialog, configure)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        run = app.runs[index]
        assert run.method == COMPARE_LINES
        lines = run.result.tables["Regression lines"]
        assert lines["N"].tolist() == [4, 4] and np.allclose(lines[["Intercept", "Slope"]], [[2, 2], [-2, 6]])
        report = run.result.tables[LINE_COMPARISON_SHEET].set_index("Comparison")
        assert np.allclose(report.loc["Slopes", ["F", "df1", "df2", "p"]].astype(float),
                           [40 / 3, 1, 4, .0217429785], rtol=1e-8)
        assert report.loc["Elevations", "Status"] == "Not tested"
        assert [line.get_gid() for line in run.result.figure.axes[0].lines] == ["lines:line:Control",
                                                                                "lines:line:Treated"]
        app.show("graph", index)
        capture(root, "window-lines-divergent.png")
        for suffix in ("png", "svg"):
            target = directory / f"lines-divergent.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.show("graph", index)
                app.export()
            assert target.stat().st_size > 1000, target
        assert b"<svg " in (directory / "lines-divergent.svg").read_bytes()
        app.show("result", index)
        app.result_tabs.select(1)
        capture(root, "window-lines-comparison.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "line-comparison.csv")):
            app.export()
        exported = (directory / "line-comparison.csv").read_text(encoding="utf-8-sig")
        assert "Slopes" in exported and "Not tested" in exported

        # Exclude a Treated Y, then edit another: both recalculate the comparison.
        app.show("data", title)
        app.current_grid.select((4, 1))
        app.toggle_exclusion()
        wait_for_calculation()
        assert app.runs[index].result.tables["Regression lines"]["N"].tolist() == [4, 3]
        app.show("data", title)
        app.edit_cell(8, 1, "20")
        wait_for_calculation()
        changed = app.runs[index].result.tables["Regression lines"]
        assert changed["N"].tolist() == [4, 4] and np.allclose(changed["X max"], [3, 4])
        comparison = app.runs[index].result.tables[LINE_COMPARISON_SHEET]
        app.show("graph", index)
        capture(root, "window-lines-recalculated.png")

        assert app.save()
        app.import_file(app.path)
        for position, saved in enumerate(app.runs):
            app.open_sheet(("graph", position))
            wait_for_calculation()
        methods = [saved.method for saved in app.runs]
        assert methods == ["Linear regression", COMPARE_LINES], methods
        assert set(app.runs[0].options) == {"X", "Y"} and app.runs[0].result.figure is not None
        reopened = app.runs[1]
        assert reopened.options["Input"] == "Long table" and reopened.options["Group"] == "Group"
        pd.testing.assert_frame_equal(reopened.result.tables[LINE_COMPARISON_SHEET], comparison)
        app.show("result", 1)
        app.result_tabs.select(1)
        app.use_result_as_data()
        assert app.tables[LINE_COMPARISON_SHEET].raw["Comparison"].tolist() == ["Slopes", "Elevations"]

        # Wide XY: shared X with one Y column per line, the parallel case.
        app.show("data", wide_title)

        def configure_wide(dialog):
            pick_method(dialog, COMPARE_LINES)
            dialog.controls["Input"][1].set(LINES_WIDE)
            dialog.controls["X"][1].set("X")
            dialog.update()
            select_columns(dialog, "Y columns", ["X", "Control", "Treated"])
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "Y columns" in report.call_args.args[1], report.call_args
            select_columns(dialog, "Y columns", ["Control", "Treated"])
            dialog.controls["Model view"][1].set("Model chosen by the comparison")
            capture(dialog, "window-lines-wide.png")

        drive_dialog(AnalysisDialog, configure_wide)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        wide_run = app.runs[index]
        report = wide_run.result.tables[LINE_COMPARISON_SHEET].set_index("Comparison")
        assert report["Status"].tolist() == ["Tested", "Tested"]
        assert np.allclose(report.loc["Elevations", ["F", "df1", "df2", "p"]].astype(float),
                           [40 / 3, 1, 5, .0147254010], rtol=1e-8)
        assert np.isclose(wide_run.result.tables["Summary"]["Value"]["Common slope"], 2)
        app.show("graph", index)
        capture(root, "window-lines-parallel.png")
        for suffix in ("png", "svg"):
            target = directory / f"lines-parallel.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.show("graph", index)
                app.export()
            assert target.stat().st_size > 1000, target

    def check_cox_outputs():
        from types import SimpleNamespace

        from analisi.cox_smoke import check_cox_outputs as run

        run(SimpleNamespace(app=app, root=root, directory=directory, capture=capture, wait=wait_for_calculation,
                            drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
                            save_project=save_project, Dataset=Dataset, AnalysisDialog=AnalysisDialog,
                            messagebox=messagebox, filedialog=filedialog))

    def check_cox_exact_ties_smoke():
        from analisi.cox_exact_smoke import check_cox_exact_ties

        check_cox_exact_ties(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, save_project=save_project,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_cox_fit_diagnostics():
        from types import SimpleNamespace

        from analisi.cox_fit_diagnostics_smoke import check_cox_fit_diagnostics as run

        run(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, AnalysisDialog=AnalysisDialog,
            drive_dialog=drive_dialog, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_bubble_plot():
        path = directory / "bubble.alab"
        title = "Bubbles"
        data = pd.DataFrame({"X": [1., 2., 3., 4., 5., 6., 2.5], "Y": [2., 4., 1., 2., None, 2., 3.],
                             "Size": [1., 4., 9., 0., 16., None, 2.],
                             "Group": ["Alpha", "Beta", "Alpha", "Alpha", "Beta", "Beta", "Beta"],
                             "Label": ["A", "B", None, "D", "E", "F", "Ünïcode"]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def configure(dialog):
            # Scatter and XY series keep their own fields.
            pick_method(dialog, "Scatter / confidence ellipse")
            assert "Size" not in dialog.controls and "Group" in dialog.controls
            pick_method(dialog, XY_METHOD)
            assert "Size" not in dialog.controls and "Y columns" in dialog.controls
            pick_method(dialog, BUBBLE)
            assert [dialog.controls[name][1].get() for name in ("X", "Y", "Size")] == ["X", "Y", "Size"]
            dialog.controls["Group"][1].set("Group")
            dialog.controls["Label"][1].set("Label")
            # A text Size column and an invalid area keep the dialog open on the field.
            for field, value in (("Size", "Label"), ("Size", "X"), (BUBBLE_MAX_AREA, "abc"), (BUBBLE_MAX_AREA, "0")):
                previous = dialog.controls[field][1].get()
                dialog.controls[field][1].set(value)
                with patch.object(messagebox, "showerror") as report:
                    assert dialog.validate() is False
                assert field in report.call_args.args[1], report.call_args
                dialog.controls[field][1].set(previous)
            capture(dialog, "window-bubble-options.png")

        drive_dialog(AnalysisDialog, configure)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        sheet = run.result.tables[BUBBLE_SHEET]
        assert sheet["Source row"].tolist() == [1, 2, 3, 7]
        assert np.allclose(sheet["Marker area (pt²)"], [400 / 9, 1600 / 9, 400, 800 / 9])
        axes = run.result.figure.axes[0]
        bubbles = [c for c in axes.collections if c.get_gid() and c.get_gid().startswith("bubble:")]
        assert [c.get_label() for c in bubbles] == ["Alpha", "Beta"]
        assert [len(c.get_offsets()) for c in bubbles] == [2, 2]
        assert [t.get_text() for t in axes.get_legend().get_texts()] == ["Alpha", "Beta"]
        assert [t.get_text() for t in axes._tramastat_size_legend.get_texts()] == ["9", "3", "1"]
        assert [t.get_text() for t in axes.texts] == ["A", "B", "Ünïcode"]
        app.show("graph", 0)
        capture(root, "window-bubble-graph.png")
        app.show("result", 0)
        capture(root, "window-bubble-values.png")
        for suffix in ("png", "svg"):
            target = directory / f"bubble.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.show("graph", 0)
                app.export()
            assert target.stat().st_size > 1000, target
        assert b"<svg " in (directory / "bubble.svg").read_bytes()
        app.show("result", 0)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "bubble-values.csv")):
            app.export()
        assert "Marker area" in (directory / "bubble-values.csv").read_text(encoding="utf-8-sig")

        # Excluding the size 9 rescales the shared maximum to 4.
        app.show("data", title)
        app.current_grid.select((2, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        assert np.allclose(app.runs[0].result.tables[BUBBLE_SHEET]["Marker area (pt²)"], [100, 400, 200])
        # Editing a Size recalculates the graph and its sheet.
        app.show("data", title)
        app.edit_cell(0, 2, "4")
        wait_for_calculation()
        changed = app.runs[0].result.tables[BUBBLE_SHEET]
        assert np.allclose(changed["Marker area (pt²)"], [400, 400, 200])
        sizes = [c.get_sizes().tolist() for c in app.runs[0].result.figure.axes[0].collections
                 if c.get_gid() and c.get_gid().startswith("bubble:")]
        assert sizes == [[400.]] + [[400., 200.]], sizes
        app.show("graph", 0)
        capture(root, "window-bubble-recalculated.png")

        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.method == BUBBLE and reopened.options["Group"] == "Group"
        pd.testing.assert_frame_equal(reopened.result.tables[BUBBLE_SHEET], changed)
        app.show("result", 0)
        app.use_result_as_data()
        assert app.tables[BUBBLE_SHEET].raw["Label"].tolist()[-1] == "Ünïcode"

        # Only zero sizes: the error names the Size field.
        save_project(directory / "bubble-zero.alab", {"Zero": Dataset(pd.DataFrame(
            {"X": [1., 2.], "Y": [1., 2.], "Size": [0., 0.]}))})
        app.import_file(directory / "bubble-zero.alab")

        def zero_sizes(dialog):
            pick_method(dialog, BUBBLE)
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "size of zero" in report.call_args.args[1], report.call_args
            capture(dialog, "window-bubble-zero-error.png")
            dialog.controls["Size"][1].set("X")
            dialog.controls["X"][1].set("Y")
            dialog.controls["Y"][1].set("Size")

        drive_dialog(AnalysisDialog, zero_sizes)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs[0].result.tables[BUBBLE_SHEET]) == 2

    def check_paired_graphs():
        from matplotlib.collections import LineCollection

        def pair_segments(figure):
            return {c.get_gid(): [s.tolist() for s in c.get_segments()]
                    for c in figure.axes[0].collections if isinstance(c, LineCollection)}

        def export_sheet(index, name):
            target = directory / name
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.result_tabs.select(index)
                app.export()
            return pd.read_csv(target)

        # Before/after: two pairs matched by source row, Subject only labels the rows.
        path = directory / "before-after.alab"
        title = "Before after"
        data = pd.DataFrame({"Subject": ["s1", "s2", "s3", "s4", "s5"],
                             "Before A": [1, 4, 2, 5, None], "After A": [4, 3, 2, None, 7],
                             "Before B": [1, 2, 4, None, 3], "After B": [3, 6, 6, 8, None]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def build_pairs(dialog):
            pick_method(dialog, BEFORE_AFTER)
            pairs = dialog.controls[BEFORE_AFTER_PAIRS][1]
            assert isinstance(pairs, BeforeAfterPairs) and pairs.values() == []
            assert dialog.fields.index(dialog.field_rows[BEFORE_AFTER_PAIRS][1].master) == 0
            # An empty pair list keeps the dialog open and points at the pairs.
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert BEFORE_AFTER_PAIRS in report.call_args.args[1], report.call_args
            pairs.before.set("Before A")
            pairs.after.set("After A")
            pairs.title.set("A")
            pairs.add_pair()
            pairs.before.set("After A")
            pairs.after.set("Before A")
            pairs.add_pair()
            assert len(pairs.values()) == 1 and "already" in pairs.note.cget("text")
            # A duplicate that reaches the recipe is rejected by the calculation too.
            pairs.pairs.append({BEFORE: "Before A", AFTER: "After A", PAIR_TITLE: ""})
            pairs.refresh()
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "repeats pair 1" in report.call_args.args[1], report.call_args
            capture(dialog, "window-before-after-duplicate.png")
            pairs.listbox.selection_set(1)
            pairs.remove_pair()
            pairs.before.set("Before B")
            pairs.after.set("After B")
            pairs.add_pair()
            pairs.listbox.selection_clear(0, "end")
            pairs.listbox.selection_set(1)
            pairs.move(-1)
            assert [p[BEFORE] for p in pairs.values()] == ["Before B", "Before A"]
            pairs.listbox.selection_set(0)
            pairs.move(1)
            assert pairs.values() == [{BEFORE: "Before A", AFTER: "After A", PAIR_TITLE: "A"},
                                      {BEFORE: "Before B", AFTER: "After B", PAIR_TITLE: ""}]
            dialog.controls["Subject"][1].set("Subject")
            capture(dialog, "window-before-after-pairs.png")

        drive_dialog(AnalysisDialog, build_pairs)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert run.method == BEFORE_AFTER
        assert [pair[BEFORE] for pair in run.options[BEFORE_AFTER_PAIRS]] == ["Before A", "Before B"]
        summary = run.result.tables["Pair summary"]
        assert summary["Complete pairs"].tolist() == [3, 3]
        assert summary["Before only"].tolist() == [1, 1] and summary["After only"].tolist() == [1, 1]
        assert np.allclose(summary["Mean change"], [2 / 3, 8 / 3])
        changes = run.result.tables["Pairs"].dropna(subset=["Change"])
        assert changes["Change"].tolist() == [3, -1, 0, 2, 4, 2]
        assert pair_segments(run.result.figure) == {
            "before-after:1": [[[1, 1], [2, 4]], [[1, 4], [2, 3]], [[1, 2], [2, 2]]],
            "before-after:2": [[[4, 1], [5, 3]], [[4, 2], [5, 6]], [[4, 4], [5, 6]]]}
        app.show("graph", 0)
        capture(root, "window-before-after-vertical.png")

        def horizontal(dialog):
            assert dialog.controls[BEFORE_AFTER_PAIRS][1].values()[0][PAIR_TITLE] == "A"
            dialog.controls["Orientation"][1].set("Horizontal")
            dialog.controls["Show unpaired observations"][1].set(True)

        drive_dialog(AnalysisDialog, horizontal)
        app.edit_analysis()
        wait_for_calculation()
        run = app.runs[0]
        figure = run.result.figure
        assert pair_segments(figure) == {
            "before-after:1": [[[1, 1], [4, 2]], [[4, 1], [3, 2]], [[2, 1], [2, 2]]],
            "before-after:2": [[[1, 4], [3, 5]], [[2, 4], [6, 5]], [[4, 4], [6, 5]]]}
        hollow = sorted(tuple(p) for c in figure.axes[0].collections if not isinstance(c, LineCollection)
                        and tuple(c.get_facecolor()[0]) == (1., 1., 1., 1.) for p in c.get_offsets().tolist())
        assert hollow == [(3., 4.), (5., 1.), (7., 2.), (8., 5.)], hollow
        app.show("graph", 0)
        capture(root, "window-before-after-horizontal.png")
        figure.savefig(directory / "before-after.svg")
        figure.savefig(directory / "before-after.png", dpi=100)
        assert b"<svg " in (directory / "before-after.svg").read_bytes()
        assert (directory / "before-after.png").stat().st_size > 1000

        # Excluding s1's After A removes one segment and recalculates the summary.
        app.show("data", title)
        app.current_grid.select((0, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        changed = app.runs[0].result.tables["Pair summary"]
        assert changed["Complete pairs"].tolist() == [2, 3] and changed["Before only"].tolist() == [2, 1]
        assert len(pair_segments(app.runs[0].result.figure)["before-after:1"]) == 2
        app.show("result", 0)
        exported = export_sheet(0, "before-after-pairs.csv")
        assert exported["Status"].tolist().count("Complete") == 5
        assert exported["Subject"].tolist()[:5] == ["s1", "s2", "s3", "s4", "s5"]
        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options["Orientation"] == "Horizontal" and reopened.options["Show unpaired observations"]
        pd.testing.assert_frame_equal(reopened.result.tables["Pair summary"], changed)
        app.show("result", 0)
        app.result_tabs.select(1)
        app.use_result_as_data()
        assert app.tables["Pair summary"].raw["Complete pairs"].tolist() == [2, 3]

        # Subject trajectories from replicate subcolumns, with a gap and two rows at X = 2.
        path = directory / "trajectories.alab"
        title = "Curves"
        curves = pd.DataFrame({"X": [0, 1, 2, 2, 3], "Cohort A [1]": [10, 11, 12, 14, 13],
                               "Cohort A [2]": [9, None, 11, 12, 14], "Cohort B [1]": [8, 9, None, 10, 12]})
        save_project(path, {title: Dataset(curves)})
        app.import_file(path)
        subjects = ["Cohort A [1]", "Cohort A [2]", "Cohort B [1]"]

        def trajectories(dialog):
            pick_method(dialog, TRAJECTORIES)
            assert dialog.controls["Input"][1].get() == "Replicate subcolumns"
            assert dialog.controls["X"][1].get() == "X"
            box = dialog.controls["Y columns"][1]
            assert [box.get(i) for i in box.curselection()] == subjects
            select_columns(dialog, "Y columns", set())
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "Y columns" in report.call_args.args[1], report.call_args
            select_columns(dialog, "Y columns", {"X", *subjects})
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "X column" in report.call_args.args[1], report.call_args
            capture(dialog, "window-trajectories-error.png")
            select_columns(dialog, "Y columns", set(subjects))
            dialog.controls["Show group mean"][1].set(True)
            capture(dialog, "window-trajectories-options.png")

        drive_dialog(AnalysisDialog, trajectories)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        means = run.result.tables["Group means"]
        cohort_a = means[means["Group"] == "Cohort A"]
        assert np.allclose(cohort_a["Mean"], [9.5, 11, 11.5, 13, 13.5]) and cohort_a["N"].tolist() == [2, 1, 2, 2, 2]
        cohort_b = means[means["Group"] == "Cohort B"]
        assert cohort_b["N"].tolist() == [1, 1, 0, 1, 1] and np.isnan(cohort_b["Mean"].iat[2])
        values = run.result.tables["Subject values"]
        assert values.loc[values["Subject"] == "Cohort A [1]", "Source row"].tolist() == [1, 2, 3, 4, 5]
        assert values.loc[values["Subject"] == "Cohort B [1]", "Source row"].tolist() == [1, 2, 4, 5]
        app.show("graph", 0)
        capture(root, "window-trajectories-replicates.png")
        # The Inspector colors a whole data set: its traces, its mean and its legend key.
        app.toggle_inspector()
        panel = app.inspector
        assert [item["name"] for item in panel.elements] == ["Cohort A", "Cohort B"]
        panel.select_group("trajectory:group:Cohort A")
        panel.vars["element:color"].set("#9b4174")
        panel._now("element:color")
        assert panel.apply()
        assert run.style["groups"] == {"trajectory:group:Cohort A": {"color": "#9b4174"}}
        capture(root, "window-trajectories-inspector.png")
        app.toggle_inspector()

        # Excluding Cohort A [1] on the second X = 2 row breaks that trace and the mean uses one value.
        app.show("data", title)
        app.current_grid.select((3, 1))
        app.toggle_exclusion()
        wait_for_calculation()
        lines = {line.get_gid(): np.asarray(line.get_ydata(), dtype=float)
                 for line in app.runs[0].result.figure.axes[0].lines}
        assert np.isnan(lines["trajectory:Cohort A [1]"]).tolist() == [False, False, False, True, False]
        assert np.allclose(lines["trajectory-mean:Cohort A"], [9.5, 11, 11.5, 12, 13.5])
        recolored = {line.get_gid(): mcolors.to_hex(line.get_color()) for line in app.runs[0].result.figure.axes[0].lines}
        assert recolored["trajectory:Cohort A [2]"] == recolored["trajectory-mean:Cohort A"] == "#9b4174", recolored
        app.show("result", 0)
        exported = export_sheet(1, "trajectory-group-means.csv")
        assert exported.loc[exported["Group"] == "Cohort A", "N"].tolist() == [2, 1, 2, 1, 2]

        def separate(dialog):
            dialog.controls["Input"][1].set("Separate columns")
            dialog.controls["Style"][1].set("Line and points")

        drive_dialog(AnalysisDialog, separate)
        app.edit_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert run.result.tables["Subject values"]["Group"].unique().tolist() == ["All subjects"]
        figure = run.result.figure
        assert len({line.get_color() for line in figure.axes[0].lines if line.get_gid().startswith("trajectory:")}) == 3
        app.show("graph", 0)
        capture(root, "window-trajectories-separate.png")
        figure.savefig(directory / "trajectories.svg")
        figure.savefig(directory / "trajectories.png", dpi=100)
        assert b"<svg " in (directory / "trajectories.svg").read_bytes()
        assert (directory / "trajectories.png").stat().st_size > 1000
        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options["Input"] == "Separate columns" and reopened.options["Show group mean"]
        pd.testing.assert_frame_equal(reopened.result.tables["Subject values"], run.result.tables["Subject values"])
        app.show("result", 0)
        app.result_tabs.select(0)
        app.use_result_as_data()
        assert len(app.tables["Subject values"].raw) == 12

    def check_forest_plot():
        """Forest plot from precomputed limits, by row and by column, through the real dialog."""
        path = directory / "forest-plot.alab"
        long = pd.DataFrame({"Study": ["A", "B", "C", "D"], "Estimate": [.5, 2., 1., 1.2],
                             "Lower": [.25, 1., 1., None], "Upper": [1., 4., 1., 1.8]})
        wide = pd.DataFrame({"Role": ["Upper", "Estimate", "Lower"], "A": [1., .5, .25], "B": [4., 2., 1.],
                             "C": [1., 1., 1.]})
        save_project(path, {"Long intervals": Dataset(long), "Wide intervals": Dataset(wide)})
        app.import_file(path)
        app.show("data", "Long intervals")

        def complain(dialog, field):
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert field in report.call_args.args[1], report.call_args
            return report.call_args.args[1]

        def by_row(dialog):
            pick_method(dialog, FOREST_PLOT)
            visible = dialog.forest_fields()
            assert visible["Estimate"] and visible["Weight"] and not visible["Study columns"]
            assert not visible["Estimate row"]
            assert [dialog.controls[name][1].get() for name in ("Estimate", "Lower limit", "Upper limit")] == [
                "Estimate", "Lower", "Upper"]
            assert dialog.controls["Scale"][1].get() == "Log10" and dialog.controls["Reference"][1].get() == "1.0"
            dialog.controls["Study"][1].set("Study")
            # Inverted limits on a study keep the dialog open on the field.
            dialog.controls["Lower limit"][1].set("Upper")
            dialog.controls["Upper limit"][1].set("Lower")
            message = complain(dialog, "Lower limit")
            assert '"A"' in message, message
            dialog.controls["Lower limit"][1].set("Lower")
            dialog.controls["Upper limit"][1].set("Upper")
            # A difference on a log axis is refused; the measure resets scale and reference.
            dialog.controls["Measure"][1].set("Difference")
            assert dialog.controls["Scale"][1].get() == "Linear" and dialog.controls["Reference"][1].get() == "0"
            dialog.controls["Scale"][1].set("Log10")
            dialog.controls["Reference"][1].set("1")
            dialog.controls["Measure"][1].set("Ratio")
            assert dialog.controls["Scale"][1].get() == "Log10" and dialog.controls["Reference"][1].get() == "1"
            capture(dialog, "window-forest-options.png")

        drive_dialog(AnalysisDialog, by_row)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        run = app.runs[index]
        assert run.method == FOREST_PLOT and run.options["Input"] == "One study per row"
        values = run.result.tables["Forest values"]
        assert values["Study"].tolist() == ["A", "B", "C"]
        assert values[["Estimate", "Lower", "Upper"]].to_numpy().tolist() == [[.5, .25, 1.], [2., 1., 4.], [1., 1., 1.]]
        summary = run.result.tables["Summary"]["Value"]
        assert summary["Studies drawn"] == 3 and summary["Incomplete or excluded (omitted)"] == 1
        axes = run.result.figure.axes[0]
        parts = axes._tramastat_forest
        assert axes.get_xscale() == "log"
        assert [segment[:, 0].tolist() for segment in parts["intervals"].get_segments()] == [
            [.25, 1.], [1., 4.], [1., 1.]]
        assert parts["caps"][0].get_xdata().tolist() == [.25, 1., 1.]
        assert parts["caps"][1].get_xdata().tolist() == [1., 4., 1.]
        assert parts["points"].get_offsets().tolist() == [[.5, 0.], [2., 1.], [1., 2.]]
        assert [line.get_xdata()[0] for line in axes.lines if line.get_linestyle() == "--"] == [1.]
        assert [label.get_text() for label in axes.get_yticklabels()] == ["A", "B", "C"]
        app.show("graph", index)
        capture(root, "window-forest-log.png")
        run.result.figure.savefig(directory / "forest-log.svg")
        run.result.figure.savefig(directory / "forest-log.png", dpi=100)
        assert b"<svg" in (directory / "forest-log.svg").read_bytes()
        assert (directory / "forest-log.png").stat().st_size > 1000
        app.show("result", index)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "forest-values.csv")):
            app.export()
        exported = pd.read_csv(directory / "forest-values.csv")
        assert exported["Lower"].tolist() == [.25, 1., 1.], exported

        # Editing a limit and excluding a cell recalculate the graph with the entered values.
        app.show("data", "Long intervals")
        app.edit_cell(1, 3, "3.5")
        wait_for_calculation()
        assert app.runs[index].result.tables["Forest values"]["Upper"].tolist() == [1., 3.5, 1.]
        app.current_grid.active_cell = (0, 1)
        app.toggle_exclusion()
        wait_for_calculation()
        changed = app.runs[index].result.tables["Forest values"]
        assert changed["Study"].tolist() == ["B", "C"]
        assert app.runs[index].result.tables["Summary"]["Value"]["Incomplete or excluded (omitted)"] == 2

        # One study per column: explicit role rows, duplicate roles refused, selection order kept.
        app.show("data", "Wide intervals")

        def by_column(dialog):
            pick_method(dialog, FOREST_PLOT)
            dialog.controls["Input"][1].set(FOREST_BY_COLUMN)
            visible = dialog.forest_fields()
            assert visible["Study columns"] and visible["Estimate row"] and not visible["Estimate"]
            assert not dialog.field_rows["Weight"][1].winfo_ismapped()
            assert [dialog.controls[name][1].get() for name in FOREST_ROLE_ROWS] == [
                "2 · Estimate", "3 · Lower", "1 · Upper"]
            box = dialog.controls["Study columns"][1]
            names = box.get(0, "end")
            dialog.update()  # Tk delivers selection events only to a mapped list.
            assert box.winfo_viewable()
            for name in ("C", "A", "B"):
                box.selection_set(names.index(name))
                box.event_generate("<<ListboxSelect>>", when="tail")
                dialog.update()
            dialog.controls["Lower row"][1].set("2 · Estimate")
            complain(dialog, "Lower row")
            dialog.controls["Lower row"][1].set("3 · Lower")
            capture(dialog, "window-forest-columns.png")

        drive_dialog(AnalysisDialog, by_column)
        app.choose_analysis()
        wait_for_calculation()
        wide_index = len(app.runs) - 1
        wide_run = app.runs[wide_index]
        assert wide_run.options["Study columns"] == ["C", "A", "B"], wide_run.options
        assert wide_run.options["Estimate row"] == "2 · Estimate"
        assert "Estimate" not in wide_run.options and "Weight" not in wide_run.options
        wide_values = wide_run.result.tables["Forest values"]
        assert wide_values["Study"].tolist() == ["C", "A", "B"]
        assert wide_values[["Estimate", "Lower", "Upper"]].to_numpy().tolist() == [
            [1., 1., 1.], [.5, .25, 1.], [2., 1., 4.]]
        app.show("graph", wide_index)
        capture(root, "window-forest-columns-graph.png")

        def to_difference(dialog):
            dialog.controls["Measure"][1].set("Difference")
            dialog.controls["Show reference"][1].set(False)

        drive_dialog(AnalysisDialog, to_difference)
        app.edit_analysis()
        wait_for_calculation()
        assert app.runs[wide_index].options["Scale"] == "Linear"
        assert app.runs[wide_index].result.figure.axes[0].get_xscale() == "linear"

        assert app.save()
        app.import_file(app.path)
        for key in (index, wide_index):
            app.open_sheet(("graph", key))
            wait_for_calculation()
        reopened = app.runs[wide_index]
        assert reopened.options["Study columns"] == ["C", "A", "B"] and reopened.options["Measure"] == "Difference"
        pd.testing.assert_frame_equal(app.runs[index].result.tables["Forest values"], changed)
        app.show("result", wide_index)
        app.use_result_as_data()
        assert app.tables["Forest values"].raw["Study"].tolist() == ["C", "A", "B"]

        # A Column graph project saved by 0.47.0 still opens and draws.
        legacy = directory / "forest-legacy-column.alab"
        column = pd.DataFrame({"Control": [3.1, 4.2, 5.0], "Treated": [5.5, 6.1, 7.4]})
        column.attrs["table_format"] = "column"
        save_project(legacy, {"Column data": Dataset(column, analyses=[
            (COLUMN_GRAPH, {"Variables": ["Control", "Treated"], "Graph style": "Bars", "Interval": "SEM"})])})
        app.import_file(legacy)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].result.tables["Graph data"]["N"].tolist() == [3, 3]

    def check_box_violin():
        path = directory / "box-violin.alab"
        title = "Treatments"
        data = pd.DataFrame({"Control": [4.1, 4.8, 5.0, 5.2, 5.9, 6.1, None, 14.0],
                             "Drug A": [5.5, 6.0, 6.2, 6.8, 7.0, 7.5, 7.9, 30.0],
                             "Drug B": [3.0, 3.3, 3.9, 4.2, 4.4, 4.9, 5.1, 5.6]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)
        shown = []

        def separate_box(dialog):
            pick_method(dialog, BOX_VIOLIN)
            assert dialog.box_violin_visibility()["Response"] and not dialog.box_violin_visibility()["Variables"]
            dialog.controls["Input"][1].set(BOX_SEPARATE)
            visible = dialog.box_violin_visibility()
            assert visible["Variables"] and not visible["Response"] and not visible["Group"]
            assert visible["Whiskers"] and not visible["Bandwidth multiplier"]
            select_columns(dialog, "Variables", {"Control", "Drug A", "Drug B"})
            dialog.controls["Show mean"][1].set(True)
            capture(dialog, "window-box-options.png")
            dialog.controls["Style"][1].set("Violin")
            visible = dialog.box_violin_visibility()
            assert visible["Bandwidth multiplier"] and not visible["Whiskers"]
            # An unusable bandwidth keeps the dialog open and points at the field.
            for text in ("0", "-1", "abc", "inf"):
                dialog.controls["Bandwidth multiplier"][1].set(text)
                with patch.object(messagebox, "showerror") as report:
                    assert dialog.validate() is False
                assert "Bandwidth multiplier" in report.call_args.args[1], report.call_args
            dialog.controls["Bandwidth multiplier"][1].set("1")
            select_columns(dialog, "Variables", set())
            with patch.object(messagebox, "showerror") as report:
                assert dialog.validate() is False
            assert "Variables" in report.call_args.args[1], report.call_args
            select_columns(dialog, "Variables", {"Control", "Drug A", "Drug B"})
            dialog.controls["Style"][1].set("Box")

        drive_dialog(AnalysisDialog, separate_box)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        summary = run.result.tables["Group summary"]
        assert summary["Group"].tolist() == ["Control", "Drug A", "Drug B"]
        assert summary["N"].tolist() == [7, 8, 8]
        assert summary["Outside whiskers"].tolist() == [1, 1, 0]
        assert run.options["Input"] == BOX_SEPARATE
        app.show("graph", 0)
        capture(root, "window-box-columns.png")

        def to_violin(dialog):
            dialog.controls["Style"][1].set("Violin")
            dialog.controls["Overlay observations"][1].set(True)
            dialog.controls["Point placement"][1].set("Jitter")
            dialog.controls["Bandwidth multiplier"][1].set("1,5")

        drive_dialog(AnalysisDialog, to_violin)
        app.edit_analysis()
        wait_for_calculation()
        run = app.runs[0]
        assert run.options["Style"] == "Violin" and run.options["Bandwidth multiplier"] == 1.5
        assert "Whiskers" not in run.options
        violin = run.result.tables["Group summary"]
        assert violin["Bandwidth"].notna().all()
        assert len(run.result.tables["Plotted observations"]) == 23
        app.show("graph", 0)
        capture(root, "window-violin-columns.png")
        figure = run.result.figure
        figure.savefig(directory / "box-violin.svg")
        figure.savefig(directory / "box-violin.png", dpi=100)
        assert b"<svg " in (directory / "box-violin.svg").read_bytes()
        assert (directory / "box-violin.png").stat().st_size > 1000

        # A change to the source worksheet recalculates the graph and its sheets.
        app.show("data", title)
        app.current_grid.select((7, 2))
        app.toggle_exclusion()
        wait_for_calculation()
        assert app.runs[0].result.tables["Group summary"]["N"].tolist() == [7, 8, 7]
        app.show("data", title)
        app.edit_cell(6, 0, "5.4")
        wait_for_calculation()
        changed = app.runs[0].result.tables["Group summary"]
        assert changed["N"].tolist() == [8, 8, 7]

        assert app.save()
        app.import_file(app.path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options["Style"] == "Violin" and reopened.options["Input"] == BOX_SEPARATE
        pd.testing.assert_frame_equal(reopened.result.tables["Group summary"], changed)
        app.show("result", 0)
        app.use_result_as_data()
        assert app.tables["Group summary"].raw["N"].tolist() == [8, 8, 7]

        # Projects saved before the input mode existed hold one response and an optional group.
        long = pd.DataFrame({"Value": [1., 2., 3., 4., 5., 6., 7., 8., 30.], "Arm": list("xxxxxxxxy")})
        legacy = directory / "box-long.alab"
        save_project(legacy, {"Long": Dataset(long, analyses=[(BOX_VIOLIN, {"Response": "Value", "Group": "Arm",
                                                                            "Style": "Box"})])})
        app.import_file(legacy)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        old = app.runs[0].result.tables["Group summary"]
        assert old["Group"].tolist() == ["x", "y"] and old["N"].tolist() == [8, 1]
        assert old["Median"].tolist() == [4.5, 30.0]

    def commit_field(widget, variable, value):
        variable.set(value)
        widget.focus_force()
        root.update()
        widget.event_generate("<Return>")
        root.update()

    def edge_color(group):
        return np.atleast_2d(group.artists[0][0].get_edgecolor())[0][:3].tolist()

    def click_figure(canvas, x, y):
        from matplotlib.backend_bases import MouseEvent

        pixel = canvas.figure.axes[0].transData.transform((x, y))
        canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", canvas, *pixel, button=1))
        root.update()

    def check_graph_inspector():
        from analisi.legacy_restore import SAVED_XY

        root.geometry("1024x768+0+0")
        rows = [{"X": x, "Y": y, "Dataset": index, "Series": name, "Geometry": "line"}
                for index, (name, values) in enumerate({"Control": [2, 3, 5, 7], "Drug": [2, 4, 8, 16]}.items(), 1)
                for x, y in zip([1, 2, 3, 4], values)]
        saved_style = {"title": "Growth", "reference_lines": [{"axis": "y", "value": 6.0, "label": ""}]}
        first, second = directory / "inspector-a.alab", directory / "inspector-b.alab"
        for path, name, style in ((first, "Growth", saved_style),
                                  (second, "Other", {"series": {"line:1:Control": {"color": "#112233"}}})):
            data = Dataset(pd.DataFrame(rows), analyses=[(SAVED_XY, {})])
            data.graph_styles[0] = deepcopy(style)
            save_project(path, {name: data})
        app.import_file(first)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        run = app.runs[0]
        figure = run.result.figure
        axes = figure.axes[0]
        initial_limits = tuple(axes.get_ylim())
        initial_colors = [line.get_color() for line in axes.lines]
        assert app.inspector is None and not app.dirty

        # A: the panel opens on the right and keeps the page and the figure toolbar.
        app.toggle_inspector()
        root.update()
        panel = app.inspector
        assert panel is not None and 280 <= panel.winfo_width() <= 320, panel.winfo_width()
        assert panel.winfo_rootx() > app.graph_canvas.get_tk_widget().winfo_rootx()
        toolbar = app.graph_toolbar
        assert toolbar.winfo_ismapped() and toolbar.winfo_rootx() + toolbar.winfo_width() <= panel.winfo_rootx() + 1
        buttons = [child for child in toolbar.winfo_children() if isinstance(child, (tk.Button, tk.Checkbutton))]
        assert buttons and all(button.winfo_x() + button.winfo_width() <= toolbar.winfo_width() for button in buttons), (
            toolbar.winfo_width(), [(button.winfo_x(), button.winfo_width()) for button in buttons])
        assert app.selected == ("graph", 0)
        capture(root, "window-inspector-open.png")
        chain, widget = [], panel.selector
        for _ in range(200):
            chain.append(widget)
            widget = widget.tk_focusNext()
            if widget is panel.apply_button:
                break
        assert widget is panel.apply_button and all(str(item).startswith(str(panel)) for item in chain), chain[-3:]
        assert [item["name"] for item in panel.elements] == ["Line · Control (1)", "Line · Drug (1)"]
        panel.select_group("line:1:Drug")
        shown = {key for key, field in panel.fields.items() if field["widget"].winfo_ismapped()}
        assert {"color", "line_style", "width", "marker", "marker_size", "marker_color", "label"} <= shown
        assert "visible" not in shown

        # Preview in place: figure updates, the confirmed style and the project flag do not.
        canvas_before = app.graph_canvas
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#9b4174")
        commit_field(panel.widgets["ymin"], panel.vars["ymin"], "1")
        commit_field(panel.widgets["ymax"], panel.vars["ymax"], "20")
        assert app.graph_canvas is canvas_before and run.result.figure is figure
        assert axes.lines[1].get_color() == "#9b4174" and axes.lines[0].get_color() == initial_colors[0]
        assert tuple(axes.get_ylim()) == (1, 20) and len(axes._tramastat_references) == 1
        assert axes.get_title() == "Growth"
        assert run.style == saved_style and app.tables["Growth"].graph_styles[0] == saved_style and not app.dirty
        capture(root, "window-inspector-preview.png")

        # An invalid range keeps the last valid preview, reports the field and writes nothing.
        commit_field(panel.widgets["ymin"], panel.vars["ymin"], "20")
        commit_field(panel.widgets["ymax"], panel.vars["ymax"], "1")
        assert "yrange" in panel.errors and panel.messages["yrange"].winfo_ismapped()
        assert tuple(axes.get_ylim()) == (1, 20) and run.style == saved_style and not app.dirty
        assert panel.apply() is False and run.style == saved_style
        commit_field(panel.widgets["ymax"], panel.vars["ymax"], "")
        assert "yrange" in panel.errors and "both limits" in panel.errors["yrange"]
        capture(root, "window-inspector-error.png")
        # Escape cancels: everything returns to the confirmed style and the panel closes.
        panel.widgets["ymax"].focus_force()
        root.update()
        panel.widgets["ymax"].event_generate("<Escape>")
        root.update()
        assert app.inspector is None and not app.inspector_wanted
        assert tuple(axes.get_ylim()) == initial_limits and [line.get_color() for line in axes.lines] == initial_colors
        assert axes.get_title() == "Growth" and run.style == saved_style and not app.dirty

        # Repeat and apply: both stores change, unmanaged keys stay, the project becomes modified.
        app.toggle_inspector()
        panel = app.inspector
        assert panel.current["key"] == "line:1:Drug"
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#9b4174")
        commit_field(panel.widgets["ymin"], panel.vars["ymin"], "1")
        commit_field(panel.widgets["ymax"], panel.vars["ymax"], "20")
        assert panel.apply() is True
        expected = {"title": "Growth", "reference_lines": saved_style["reference_lines"],
                    "series": {"line:1:Drug": {"color": "#9b4174"}}, "axis": {"y": {"min": 1.0, "max": 20.0}}}
        assert run.style == expected and app.tables["Growth"].graph_styles[0] == expected and app.dirty
        assert panel.apply() is True and run.style == expected
        assert app.save() and not app.dirty
        # Applying an unchanged draft does not touch the project flag.
        assert panel.apply() and not app.dirty
        # Reset section removes only what the section manages.
        panel.reset_section("axes")
        assert panel.draft.get("axis") is None and panel.draft["series"] and panel.draft["title"] == "Growth"
        assert tuple(axes.get_ylim()) == initial_limits
        panel.cancel()
        assert run.style == expected and tuple(axes.get_ylim()) == (1, 20)

        app.import_file(first)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].style == expected
        app.show("data", "Growth")
        app.edit_cell(0, 1, "2.5")
        wait_for_calculation()
        edited = app.runs[0]
        axes = edited.result.figure.axes[0]
        assert axes.lines[1].get_color() == "#9b4174" and tuple(axes.get_ylim()) == (1, 20)
        coordinates = edited.result.tables["Saved XY coordinates"]
        assert coordinates.loc[coordinates["Series"] == "Control", "Y"].tolist() == [2.5, 3, 5, 7]
        assert coordinates.loc[coordinates["Series"] == "Drug", "Y"].tolist() == [2, 4, 8, 16]
        app.dirty = False

        # Leaving the graph with a color still in preview: no leakage to the other tab or back.
        app.show("graph", 0)
        app.toggle_inspector()
        panel = app.inspector
        panel.select_group("line:1:Control")
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#00aa00")
        assert edited.result.figure.axes[0].lines[0].get_color() == "#00aa00" and panel.has_draft
        assert app.open_document(second)
        wait_for_calculation()
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        other = app.runs[0]
        assert other.style == {"series": {"line:1:Control": {"color": "#112233"}}}
        assert other.result.figure.axes[0].lines[0].get_color() == "#112233"
        assert edited.style == expected and not app.projects[app.project_tabs.keys()[0]].dirty
        assert edited.result.figure.axes[0].lines[0].get_color() == initial_colors[0]
        assert app.inspector is not None and app.inspector.run is other  # the panel preference follows the user
        app.close_project()
        root.update()
        assert app.runs[0].style == expected
        assert app.runs[0].result.figure.axes[0].lines[0].get_color() == initial_colors[0]
        app.close_inspector()

        # Format Graph sees the last confirmed style, and the panel follows what the dialog applies.
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        app.toggle_inspector()
        panel = app.inspector
        panel.select_group("line:1:Control")
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#00aa00")
        seen = {}

        def use_dialog(dialog):
            seen["values"] = {key: dict(value) for key, value in dialog.series_values.items()}
            seen["title"] = dialog.inputs["title"].get()
            dialog.series_selector.current(0)
            dialog._select_series()
            dialog.series_fields["color"].set("#336699")

        drive_dialog(GraphFormatDialog, use_dialog)
        app.format_graph()
        assert seen["values"] == {"line:1:Drug": {"color": "#9b4174"}}, seen
        assert seen["title"] == "Growth"
        assert app.runs[0].style["series"]["line:1:Control"] == {"color": "#336699"}
        panel = app.inspector
        assert panel is not None and panel.draft == app.runs[0].style
        panel.select_group("line:1:Control")
        assert panel.vars["element:color"].get() == "#336699"
        # Saving with a draft asks: discarding keeps the confirmed style in the file.
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#00aa00")
        with patch.object(messagebox, "askyesnocancel", return_value=False) as ask:
            assert app.save()
        assert ask.called and not panel.has_draft
        assert app.runs[0].result.figure.axes[0].lines[0].get_color() == "#336699"
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#00aa00")
        with patch.object(messagebox, "askyesnocancel", return_value=None):
            assert app.save() is False
        assert panel.has_draft
        with patch.object(messagebox, "askyesnocancel", return_value=True):
            assert app.save()
        assert app.runs[0].style["series"]["line:1:Control"] == {"color": "#00aa00"}
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#b04026")
        with (patch.object(messagebox, "askyesnocancel", return_value=None),
              patch.object(NavigationToolbar2Tk, "save_figure") as export):
            app.graph_toolbar._buttons["Save"].invoke()
            assert not export.called and panel.has_draft
        with (patch.object(messagebox, "askyesnocancel", return_value=False),
              patch.object(NavigationToolbar2Tk, "save_figure") as export):
            app.graph_toolbar._buttons["Save"].invoke()
            assert export.called and not panel.has_draft
            assert panel.axes.lines[0].get_color() == "#00aa00"
        app.close_inspector()

        # Enter on the focused Apply button applies; the panel survives the gallery.
        app.toggle_inspector()
        panel = app.inspector
        panel.select_group("line:1:Control")
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#445566")
        panel.apply_button.focus_force()
        root.update()
        panel.apply_button.event_generate("<Return>")
        root.update()
        assert app.runs[0].style["series"]["line:1:Control"] == {"color": "#445566"} and not panel.has_draft
        app.toggle_gallery()
        root.update()
        app.toggle_gallery()
        root.update()
        assert app.inspector.winfo_ismapped() and app.graph_canvas.get_tk_widget().winfo_width() > 100
        # A draft does not survive recalculation: the new figure shows the confirmed style.
        panel = app.inspector
        panel.select_group("line:1:Drug")
        commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#00aa00")
        old_figure = app.runs[0].result.figure
        app.show("data", "Growth")
        assert old_figure.axes[0].lines[1].get_color() == "#9b4174"
        app.edit_cell(1, 1, "3.5")
        wait_for_calculation()
        app.open_sheet(("graph", 0))
        assert app.runs[0].result.figure is not old_figure and app.inspector is not None
        assert app.runs[0].result.figure.axes[0].lines[1].get_color() == "#9b4174"
        assert not app.inspector.has_draft and app.inspector.draft == app.runs[0].style
        app.close_inspector()

        # While an analysis runs the panel is disabled with a reason; the graph stays as it was.
        app.toggle_inspector()
        app.pending = object()
        app.sync_inspector()
        assert app.inspector.status.cget("text") and "disabled" in app.inspector.apply_button.state()
        assert "disabled" in app.inspector_button.state() and app.inspector_reason.cget("text")
        assert app.graph_format_problem() == app.inspector_reason.cget("text")
        app.pending = None
        app.sync_inspector()
        assert "disabled" not in app.inspector.apply_button.state()
        app.close_inspector()
        if root.winfo_screenwidth() >= 1920 and root.winfo_screenheight() >= 1080:
            root.geometry("1920x1080+0+0")
            app.toggle_inspector()
            root.update()
            assert 280 <= app.inspector.winfo_width() <= 320
            assert app.graph_canvas.get_tk_widget().winfo_width() > 1100
            capture(root, "window-inspector-1920.png")
            app.close_inspector()
            root.geometry("1024x768+0+0")
            root.update()

    def check_graph_inspector_groups():
        columns = {"Control": [1, 2, 3, 4, 5, 6, 7, 30.], "Drug A": [4, 5, 6, 7, 8, 9, 10, 11.],
                   "Drug B": [3.] * 8}
        path = directory / "inspector-groups.alab"
        title = "Groups"
        data = Dataset(pd.DataFrame(columns))
        recipe = {"Input": BOX_SEPARATE, "Variables": list(columns), "Style": "Box"}
        data.analyses.extend([(BOX_VIOLIN, recipe), (BOX_VIOLIN, {**recipe, "Style": "Violin", "Overlay observations": True,
                                                                  "Point placement": "Jitter"})])
        save_project(path, {title: data})
        app.import_file(path)
        for slot, kind in enumerate(("box", "violin")):
            app.open_sheet(("graph", slot))
            wait_for_calculation()
            run = app.runs[slot]
            figure = run.result.figure
            axes = figure.axes[0]
            summary = run.result.tables["Group summary"].copy()
            limits = axes.get_xlim(), axes.get_ylim()
            app.toggle_inspector()
            panel = app.inspector
            assert [item["name"] for item in panel.elements] == ["Control", "Drug A", "Drug B"]
            assert [group.key for group in graph_groups(axes)] == [f"{kind}:column:{name}" for name in columns]
            click_figure(app.graph_canvas, 2, 8)
            assert panel.current["name"] == "Drug A", panel.current
            # The click follows zoom: after zooming in, the same box is hit at its new position.
            panel.select_group(f"{kind}:column:Control")
            axes.set_ylim(4, 12)
            app.graph_canvas.draw()
            click_figure(app.graph_canvas, 2, 11)
            assert panel.current["name"] == "Drug A", panel.current
            panel.select_group(f"{kind}:column:Control")
            click_figure(app.graph_canvas, 3, 3.2)
            assert panel.current["name"] == "Control", "a click outside the artists must not change the selection"
            axes.set_ylim(*limits[1])
            app.graph_canvas.draw()
            click_figure(app.graph_canvas, 2, 8)
            assert panel.current["name"] == "Drug A", panel.current
            assert "visible" in {key for key, field in panel.fields.items() if field["widget"].winfo_ismapped()}
            commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#9b4174")
            panel.select_group(f"{kind}:column:Control")
            panel.vars["element:visible"].set(False)
            panel._now("element:visible")
            control, drug_a, drug_b = graph_groups(axes)
            assert not any(artist.get_visible() for artist, _ in control.artists)
            assert all(artist.get_visible() for artist, _ in drug_b.artists)
            assert edge_color(drug_a) == list(mcolors.to_rgb("#9b4174"))
            figure.canvas.draw()
            assert (axes.get_xlim(), axes.get_ylim()) == limits
            assert [label.get_text() for label in axes.get_xticklabels()] == list(columns)
            if kind == "violin":
                click_figure(app.graph_canvas, 3, 3)
                assert panel.current["name"] == "Drug B"
                commit_field(panel.fields["color"]["widget"], panel.vars["element:color"], "#2b8a73")
                assert any(artist.get_visible() for artist, _ in drug_b.artists)
            assert panel.apply()
            groups_style = run.style["groups"]
            assert groups_style[f"{kind}:column:Control"] == {"visible": False}
            assert groups_style[f"{kind}:column:Drug A"] == {"color": "#9b4174"}
            pd.testing.assert_frame_equal(run.result.tables["Group summary"], summary)
            if kind == "box":
                assert run.result.tables["Group summary"]["Outside whiskers"].tolist() == [1, 0, 0]
            else:
                assert run.result.tables["Group summary"].loc[2, "Note"].endswith("constant values, no density.")
            capture(root, f"window-inspector-{kind}.png")
            drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set(f"Formatted {kind}"))
            app.format_graph()
            assert run.style["groups"] == groups_style
            assert axes.get_title() == f"Formatted {kind}"
            assert not any(artist.get_visible() for artist, _ in control.artists)
            # Excluding every Control cell and recalculating keeps Drug A's color on its column.
            for row in range(8):
                app.show("data", title)
                app.current_grid.select((row, 0))
                app.toggle_exclusion()
                wait_for_calculation()
            run = app.runs[slot]
            assert run.result.tables["Group summary"]["Group"].tolist() == ["Drug A", "Drug B"]
            axes = run.result.figure.axes[0]
            assert [group.key for group in graph_groups(axes)] == [f"{kind}:column:Drug A", f"{kind}:column:Drug B"]
            assert edge_color(graph_groups(axes)[0]) == list(mcolors.to_rgb("#9b4174"))
            for row in range(8):
                app.show("data", title)
                app.current_grid.select((row, 0))
                app.toggle_exclusion()
                wait_for_calculation()
            run = app.runs[slot]
            assert run.result.tables["Group summary"]["Group"].tolist() == ["Control", "Drug A", "Drug B"]
            pd.testing.assert_frame_equal(run.result.tables["Group summary"], summary)
            control, *_ = graph_groups(run.result.figure.axes[0])
            assert not any(artist.get_visible() for artist, _ in control.artists)
            app.close_inspector()
        assert app.save()
        app.import_file(path)
        for slot, kind in enumerate(("box", "violin")):
            app.open_sheet(("graph", slot))
            wait_for_calculation()
            figure = app.runs[slot].result.figure
            control, drug_a, _ = graph_groups(figure.axes[0])
            assert not any(artist.get_visible() for artist, _ in control.artists)
            assert app.runs[slot].style["groups"][f"{kind}:column:Drug A"] == {"color": "#9b4174"}
            figure.savefig(directory / f"inspector-{kind}.svg")
            figure.savefig(directory / f"inspector-{kind}.png", dpi=100)
            assert b"<svg " in (directory / f"inspector-{kind}.svg").read_bytes()
            assert (directory / f"inspector-{kind}.png").stat().st_size > 1000
            # Reset: default colors and limits return, the results are untouched.
            app.toggle_inspector()
            app.inspector.reset_section("data")
            assert all(artist.get_visible() for artist, _ in graph_groups(figure.axes[0])[0].artists)
            app.inspector.cancel()
        # A recipe saved before 0.37.0 keeps its geometry; the panel offers series, not groups.
        long = pd.DataFrame({"Value": [1., 2., 3., 4., 5., 6., 7., 8., 30.], "Arm": list("xxxxxxxxy")})
        legacy = directory / "inspector-legacy.alab"
        save_project(legacy, {"Long": Dataset(long, analyses=[(BOX_VIOLIN, {"Response": "Value", "Group": "Arm",
                                                                            "Style": "Box"})])})
        app.import_file(legacy)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert not graph_groups(app.runs[0].result.figure.axes[0])
        app.toggle_inspector()
        assert app.inspector is not None and app.inspector.elements
        assert all(item["kind"] == "series" for item in app.inspector.elements)
        app.close_inspector()

    def check_correlation_matrix():
        path = directory / "correlation.alab"
        title = "Laboratory measurements"
        data = pd.DataFrame({"Temperature": [16, 18, 20, 22, 24, 26, 28],
                             "Growth": [2, 3, 4, 4, 6, 8, None],
                             "Enzyme activity": [8, 5, 7, 4, 3, None, 2],
                             "Recovery": [7, 7, 10, 12, 16, 15, 17]})
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def select_spearman(dialog):
            pick_method(dialog, CORRELATION_MATRIX)
            select_columns(dialog, "Variables", set(data.columns))
            assert not dialog.correlation_visibility()["Spearman p values"]
            dialog.controls["Method"][1].set("Spearman")
            assert dialog.correlation_visibility()["Spearman p values"]
            dialog.controls["Confidence level (%)"][1].set("90")
            dialog.focus_field("Spearman p values")
            capture(dialog, "window-correlation-options.png")

        drive_dialog(AnalysisDialog, select_spearman)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        original = run.result.tables
        assert original["Sample sizes"].loc["Growth", "Enzyme activity"] == 5
        assert original["P value type"].loc["Temperature", "Growth"] == "Exact"
        assert np.isclose(original["P values"].loc["Temperature", "Growth"], 4 / 720)
        app.show("graph", 0)
        capture(root, "window-correlation-heatmap.png")
        app.show("data", title)
        app.edit_cell(6, 1, "9")
        app.show("result", 0)
        wait_for_calculation()
        updated = app.runs[0].result.tables
        assert updated["Sample sizes"].loc["Temperature", "Growth"] == 7
        assert updated["P values"].loc["Temperature", "Growth"] < original["P values"].loc["Temperature", "Growth"]
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].options == run.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Coefficients"], updated["Coefficients"])

    def check_heat_map():
        path = directory / "heat-map.alab"
        title = "Expression panel"
        frame = pd.DataFrame({"Row title": ["Heart", "Lung", "Liver", "Brain", "Kidney", "Intestine"],
                              "Gene A [1]": [112., 116., 98., 96., 113., 110.],
                              "Gene A [2]": [110., 114., 100., 92., 115., 108.],
                              "Gene B": [88., 91., 114., 86., 89., 91.],
                              "Gene C": [111., 101., 110., None, 92., 113.],
                              "Gene D": [85., 96., 111., 84., 86., 112.],
                              "Gene E": [85., 96., 107., 78., 102., 114.],
                              "Gene F": [98., 115., 109., 93., 89., 100.]})
        frame.attrs["table_format"] = "grouped"
        save_project(path, {title: Dataset(frame)})
        app.import_file(path)

        def setup(dialog):
            pick_method(dialog, HEAT_MAP)
            assert dialog.heat_map_visibility()["Variables"]
            assert not dialog.heat_map_visibility()["X categories"]
            select_columns(dialog, "Variables", set(frame.columns[1:]))
            dialog.controls["Show cell values"][1].set(True)
            dialog.controls["Mark missing cells"][1].set(True)
            dialog.controls["Cell borders"][1].set(True)
            dialog.controls["Palette"][1].set("Blue–red")
            dialog.controls["Color scale"][1].set("Diverging")
            dialog.controls["Color midpoint (blank = automatic)"][1].set("100")
            dialog.focus_field("Color midpoint (blank = automatic)")
            capture(dialog, "window-heat-map-options.png")

        drive_dialog(AnalysisDialog, setup)
        app.new_graph()
        wait_for_calculation()
        run = app.runs[0]
        table = run.result.tables["Heat map data"]
        assert table.loc["Heart", "Gene A"] == 111
        assert np.isnan(table.loc["Brain", "Gene C"])
        app.show("graph", 0)
        capture(root, "window-heat-map.png")
        run.result.figure.savefig(directory / "heat-map.svg")
        app.show("data", title)
        app.edit_cell(0, 1, "116")
        app.show("result", 0)
        wait_for_calculation()
        changed = run.result.tables["Heat map data"]
        assert changed.loc["Heart", "Gene A"] == 113
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].options == run.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Heat map data"], changed)

    def check_row_tests():
        path = directory / "row-tests.alab"
        title = "Treatment by week"
        data = pd.DataFrame({"Row title": ["Week 1", "Week 2", "Week 3", "Week 4"],
                             "Control [1]": [4., 9., 2., 8.], "Control [2]": [5., None, 2.5, 8.5],
                             "Control [3]": [8., 6., 2.2, 8.3], "Treatment [1]": [1., 2., 3., 4.],
                             "Treatment [2]": [5., 8., 3., 4.1], "Treatment [3]": [5., 4., 2., 4.2]})
        data.attrs["table_format"] = "grouped"
        save_project(path, {title: Dataset(data)})
        app.import_file(path)

        def choose_row_tests(dialog):
            pick_method(dialog, ROW_TESTS)
            for field in ("First replicates", "Second replicates"):
                assert len(dialog.controls[field][1].curselection()) == 3
            dialog.controls["Test"][1].set("Paired t-test")
            dialog.controls["Input format"][1].set("Mean, SD and N")
            assert dialog.controls["Test"][1].get() == "Welch t-test"
            assert not dialog.row_test_visibility()["First replicates"]
            dialog.controls["Input format"][1].set("Raw replicates")
            dialog.controls["Test"][1].set("Paired t-test")
            dialog.controls["Correction"][1].set("Benjamini–Krieger–Yekutieli")
            assert dialog.row_test_visibility()["False discovery rate (%)"]
            assert not dialog.row_test_visibility()["Family alpha"]
            dialog.controls["Graph"][1].set("Differences and intervals")
            dialog.focus_field("False discovery rate (%)")
            capture(dialog, "window-row-tests-options.png")

        drive_dialog(AnalysisDialog, choose_row_tests)
        app.choose_analysis()
        wait_for_calculation()
        run = app.runs[0]
        first = run.result.tables["Row comparisons"]
        assert first.loc["Week 2", "N first"] == 2
        assert first.loc["Week 2", "Difference"] == 4.5
        assert first.loc["Week 4", "Discovery"]
        app.show("graph", 0)
        capture(root, "window-row-tests-graph.png")
        app.show("result", 0)
        capture(root, "window-row-tests-results.png")
        app.show("data", title)
        app.edit_cell(1, 2, "5")
        app.show("result", 0)
        wait_for_calculation()
        updated = app.runs[0].result.tables["Row comparisons"]
        assert updated.loc["Week 2", "N first"] == 3
        assert np.isclose(updated.loc["Week 2", "Difference"], 2)
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        assert app.runs[0].options == run.options
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Row comparisons"], updated)

    def check_xy_dual_axis():
        source = pd.DataFrame({
            "X": [0, 1, 2, 3, 4],
            "Temperatura": [18., 19, np.nan, 22, 21],
            "Pressione": [1000., 1020, 1050, np.nan, 1100],
        })
        path = directory / "xy-series.alab"
        save_project(path, {"Climate": Dataset(source)})
        app.import_file(path)

        def choose(dialog):
            pick_method(dialog, "XY series")
            dialog.controls["X"][1].set("X")
            select_columns(dialog, "Y columns", ["Temperatura", "Pressione"])

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs[0].result.figure.axes) == 1, "default XY series should use one axes"
        assert not app.runs[0].result.tables["Series values"].empty

        def open_format(action, *, accept):
            def find(parent):
                for child in parent.winfo_children():
                    if isinstance(child, GraphFormatDialog):
                        return child
                    found = find(child)
                    if found is not None:
                        return found
                return None

            def enter():
                dialog = find(root)
                if dialog is None:
                    errors.append("GraphFormatDialog did not open")
                    return
                try:
                    action(dialog)
                    if dialog.winfo_exists():
                        dialog.ok() if accept else dialog.cancel()
                except Exception as error:
                    errors.append(str(error))
                    try:
                        dialog.cancel()
                    except Exception:
                        pass

            before = len(errors)
            root.after(200, enter)
            app.format_graph()
            assert errors[before:] == [], errors[before:]

        def select_series(dialog, name):
            names = list(dialog.series_selector["values"])
            dialog.series_selector.current(names.index(name))
            dialog._select_series()

        def format_dual(dialog):
            select_series(dialog, "Temperatura")
            dialog.draw_style.set("Line and points")
            dialog.side.set("Left")
            select_series(dialog, "Pressione")
            dialog.draw_style.set("Points")
            dialog.side.set("Right")
            dialog.axis_fields["y"]["min"].set("15")
            dialog.axis_fields["y"]["max"].set("25")
            dialog.right_title.set("kPa")
            dialog.right_scale.set("Log")
            dialog.right_min.set("0")
            dialog.right_max.set("1200")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
                assert "positive" in shown.call_args.args[1]
            dialog.right_scale.set("Linear")
            dialog.right_min.set("900")
            dialog.notebook.select(2)
            capture(dialog, "window-xy-format.png")

        app.show("graph", 0)
        open_format(format_dual, accept=True)
        result = app.runs[0].result
        left, right = result.figure.axes
        np.testing.assert_allclose(left.get_ylim(), (15, 25))
        np.testing.assert_allclose(right.get_ylim(), (900, 1200))
        assert left.get_ylabel() == "Temperatura"
        assert right.get_ylabel() == "kPa"
        assert np.isnan(left.lines[0].get_ydata()[2])
        assert [text.get_text() for text in left.get_legend().get_texts()] == ["Temperatura", "Pressione"]
        sheet = result.tables["Series values"]
        np.testing.assert_allclose(sheet.loc[sheet["Y column"] == "Temperatura", "X"], [0, 1, 3, 4])
        np.testing.assert_allclose(sheet.loc[sheet["Y column"] == "Pressione", "X"], [0, 1, 2, 4])
        app.show("graph", 0)
        capture(root, "window-xy-graph.png")

        left.set_xlim(0.2, 3.8)
        zoom = tuple(left.get_xlim())
        confirmed = (dict(app.runs[0].options["Series side"]), dict(app.runs[0].options["Series style"]),
                     app.runs[0].options["Right title"])

        def abandon(dialog):
            select_series(dialog, "Pressione")
            dialog.side.set("Left")
            dialog.draw_style.set("Line")
            dialog.axis_fields["x"]["min"].set("1")
            dialog.axis_fields["x"]["max"].set("3")
            dialog.right_title.set("discarded")

        open_format(abandon, accept=False)
        assert tuple(app.runs[0].result.figure.axes[0].get_xlim()) == zoom
        assert app.runs[0].options["Series side"] == confirmed[0]
        assert app.runs[0].options["Series style"] == confirmed[1]
        assert app.runs[0].options["Right title"] == confirmed[2]
        assert len(app.runs[0].result.figure.axes) == 2

        app.path = path
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        assert app.runs[0].options["Series side"]["Pressione"] == "Right"
        assert app.runs[0].options["Series style"]["Temperatura"] == "Line and points"
        assert app.runs[0].options["Y minimum"] == 15
        assert app.runs[0].options["Right maximum"] == 1200
        assert app.runs[0].options["Right title"] == "kPa"
        app.show("data", "Climate")
        app.edit_cell(0, 1, "16")
        wait_for_calculation()
        edited = app.runs[0]
        assert edited.options["Right title"] == "kPa"
        assert edited.options["Series side"]["Pressione"] == "Right"
        assert float(edited.result.tables["Series values"].iloc[0]["Y"]) == 16
        app.show("graph", 0)
        svg_path = directory / "xy-series.svg"
        png_path = directory / "xy-series.png"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(svg_path)):
            app.export()
        with patch.object(filedialog, "asksaveasfilename", return_value=str(png_path)):
            app.export()
        assert svg_path.stat().st_size > 1000 and png_path.stat().st_size > 1000
        svg_text = svg_path.read_text(encoding="utf-8")
        assert "Temperatura" in svg_text and "kPa" in svg_text

        def place(side):
            def action(dialog):
                for name in list(dialog.series_selector["values"]):
                    select_series(dialog, name)
                    dialog.side.set(side)
                    dialog.draw_style.set("Line and points" if name == "Temperatura" else "Points")
                dialog.axis_fields["y"]["min"].set("15")
                dialog.axis_fields["y"]["max"].set("25")
                dialog.right_title.set("kPa")
                dialog.right_min.set("900")
                dialog.right_max.set("1200")
            open_format(action, accept=True)
            figure = app.runs[0].result.figure
            assert sum(len(ax.lines) for ax in figure.axes) == 2
            return len(figure.axes)

        assert [place(side) for side in ("Left", "Right", "Left", "Right", "Left")] == [1, 2, 1, 2, 1]

        classic_path = directory / "classic-column.alab"
        save_project(classic_path, {"Growth": Dataset(pd.DataFrame({"x": [1., 2, 3, 4], "z": [2., 3, 4, 5]}))})
        app.import_file(classic_path)

        def choose_column(dialog):
            pick_method(dialog, "Column graph")
            select_columns(dialog, "Variables", ["x", "z"])

        drive_dialog(AnalysisDialog, choose_column)
        app.choose_analysis()
        wait_for_calculation()
        classic = app.runs[0].result.figure
        assert len(classic.axes) == 1
        artist_count = len(classic.axes[0].lines) + len(classic.axes[0].collections) + len(classic.axes[0].patches)

        def retitle(dialog):
            dialog.inputs["title"].set("Classic column")
            assert dialog.draw_style is None

        app.show("graph", 0)
        open_format(retitle, accept=True)
        assert len(app.runs[0].result.figure.axes) == 1
        axis = app.runs[0].result.figure.axes[0]
        assert len(axis.lines) + len(axis.collections) + len(axis.patches) == artist_count
        assert app.runs[0].style["title"] == "Classic column"
        assert "Series side" not in app.runs[0].options

        bad_path = directory / "xy-nonpositive.alab"
        save_project(bad_path, {"Signs": Dataset(pd.DataFrame({
            "X": [1., 2, 3], "Left": [1., -2, 3], "Right": [-1., -2, -3]}))})
        app.import_file(bad_path)

        def choose_signs(dialog):
            pick_method(dialog, "XY series")
            dialog.controls["X"][1].set("X")
            select_columns(dialog, "Y columns", ["Left", "Right"])

        drive_dialog(AnalysisDialog, choose_signs)
        app.choose_analysis()
        wait_for_calculation()
        assert len(app.runs[0].result.figure.axes) == 1
        # import_file clears the selection, and a new analysis opens on its result sheet.
        app.show("graph", 0)

        def reject_log(dialog):
            select_series(dialog, "Right")
            dialog.side.set("Right")
            dialog.right_scale.set("Log")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "positive" in shown.call_args.args[1]
            dialog.side.set("Left")
            dialog.right_scale.set("Linear")

        open_format(reject_log, accept=True)
        assert len(app.runs[0].result.figure.axes) == 1
        assert app.runs[0].options.get("Right scale", "Linear") == "Linear"

        def use_left_log(dialog):
            select_series(dialog, "Right")
            dialog.side.set("Right")
            dialog.inputs["yscale"].set("log")

        open_format(use_left_log, accept=True)
        result = app.runs[0].result
        left, right = result.figure.axes
        assert left.get_yscale() == "log" and right.get_yscale() == "linear"
        assert np.isnan(left.lines[0].get_ydata()[1])
        values = result.tables["Series values"]
        assert values.loc[values["Y column"] == "Left", "Y"].tolist() == [1., 3.]
        app.toggle_inspector()
        assert app.inspector.widgets["yscale"].instate(["disabled"])
        app.inspector.reset_section("axes")
        assert app.inspector.apply() and left.get_yscale() == "log"
        app.toggle_inspector()
        open_format(lambda dialog: dialog._reset(), accept=False)
        result = app.runs[0].result
        assert len(result.figure.axes) == 1 and result.figure.axes[0].get_yscale() == "linear"
        values = result.tables["Series values"]
        assert values.loc[values["Y column"] == "Left", "Y"].tolist() == [1., -2., 3.]
        assert app.save()
        app.import_file(bad_path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        result = app.runs[0].result
        assert len(result.figure.axes) == 1 and result.figure.axes[0].get_yscale() == "linear"
        assert result.tables["Series values"]["Y"].tolist() == [1., -2., 3., -1., -2., -3.]

    def check_nonlinear_calibration_workflow():
        from analisi.stats import linear as linear_fit

        title = "Standard curve"
        concentration = np.array([0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        response = 2.0 + 8.0 * np.exp(-0.7 * concentration)

        def truth(value):
            return 2.0 + 8.0 * np.exp(-0.7 * value)

        unknown = [truth(1.25), np.nan, truth(4.5), truth(0.0), 11.0, np.nan, np.nan, np.nan]
        source = pd.DataFrame({"Row titles": list("ABCDEFGH"), "Concentration": concentration,
                               "Response": response, "Unknown": unknown})
        path = directory / "nonlinear-calibration.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def choose(dialog):
            pick_method(dialog, "Interpolate a standard curve")
            dialog.controls["X"][1].set("Concentration")
            dialog.controls["Y"][1].set("Concentration")
            y_field = dialog.field_rows["Y"][1]
            dialog.fields.select(dialog.field_rows["Curve"][1].master)
            with patch.object(messagebox, "showerror") as shown:
                accepted = dialog.validate()
            if accepted is not False:
                raise AssertionError("duplicate X and Y columns were accepted")
            if not dialog.winfo_exists():
                raise AssertionError("dialog closed after a duplicate column choice")
            message = "" if shown.call_args is None else shown.call_args.args[1]
            if "Y" not in str(message):
                raise AssertionError(f"error message does not name Y: {message!r}")
            # Readonly comboboxes do not take keyboard focus here. The field error
            # still returns the dialog to the tab that holds Y.
            if dialog.fields.select() != str(y_field.master):
                raise AssertionError(f"dialog did not stay on Y: tab={dialog.fields.select()!r}")
            dialog.controls["Y"][1].set("Response")
            dialog.controls["Unknown responses"][1].set("Unknown")
            dialog.controls["Curve"][1].set("Linear")
            visible = dialog.calibration_visibility()
            if visible != {"Unknown responses": True, "Unknown X": False, "Model": False, "Uncertainty": True,
                           "Confidence level (%)": False, "Replicate count column": False}:
                raise AssertionError(f"Model stayed visible for a linear curve: {visible!r}")

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        linear_run = app.runs[0]
        linear_table = linear_run.result.tables["Interpolated values"]
        assert list(linear_table.columns) == ["Response", "Interpolated X", "Outside calibration"]
        assert linear_run.options["Curve"] == "Linear" and "Model" not in linear_run.options
        expected = linear_fit(app.tables[title].frame(mask_excluded=True), "Concentration", "Response")
        np.testing.assert_allclose(linear_run.result.tables["Linear calibration"].at["Slope", "Value"], expected["Slope"])

        def edit(dialog):
            if dialog.calibration_visibility().get("Model") is not False:
                raise AssertionError(f"Model visible before switching curve: {dialog.calibration_visibility()!r}")
            dialog.controls["Curve"][1].set("Nonlinear")
            if dialog.calibration_visibility().get("Model") is not True:
                raise AssertionError(f"Model hidden for a nonlinear curve: {dialog.calibration_visibility()!r}")
            dialog.controls["Model"][1].set("One-phase decay")
            dialog.fields.select(dialog.field_rows["Model"][0].master)
            capture(dialog, "window-nonlinear-calibration-options.png")

        drive_dialog(AnalysisDialog, edit)
        app.edit_analysis()
        wait_for_calculation()
        result = app.runs[0].result
        table = result.tables["Interpolated values"]
        assert table["Source row"].tolist() == [0, 2, 3, 4]
        assert table["Row title"].tolist() == ["A", "C", "D", "E"]
        assert table["Status"].tolist() == ["In range", "In range", "In range", "Out of range"]
        np.testing.assert_allclose(table["Interpolated X"].iloc[:3].to_numpy(dtype=float), [1.25, 4.5, 0.0],
                                   atol=1e-6, rtol=0)
        assert pd.isna(table["Interpolated X"].iloc[3])
        assert np.allclose(table["Domain low"].to_numpy(dtype=float), 0.0)
        assert np.allclose(table["Domain high"].to_numpy(dtype=float), 6.0)
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"].to_numpy(dtype=float),
                                   [2.0, 8.0, 0.7], atol=1e-6, rtol=0)
        assert result.tables["Fit diagnostics"].at["N", "Value"] == 8
        axis = result.figure.axes[0]
        assert [text.get_text() for text in axis.get_legend().get_texts()] == [
            "Standards", "One-phase decay", "Estimates"]
        assert len(axis.lines[0].get_xdata()) > len(concentration)
        assert len(axis.collections[1].get_offsets()) == 3
        app.show("graph", 0)
        capture(root, "window-nonlinear-calibration.png")
        svg = directory / "nonlinear-calibration.svg"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(svg)):
            app.export()
        assert "<svg" in svg.read_text(encoding="utf-8")

        saved_options = dict(app.runs[0].options)
        statuses = table["Status"].tolist()
        solved = table["Interpolated X"].to_numpy(dtype=float).copy()
        app.path = path
        assert app.save()
        app.import_file(path)
        assert app.runs[0].options == saved_options
        app.open_sheet(("result", 0))
        wait_for_calculation()
        reloaded = app.runs[0].result.tables["Interpolated values"]
        assert reloaded["Status"].tolist() == statuses
        assert reloaded["Row title"].tolist() == ["A", "C", "D", "E"]
        np.testing.assert_allclose(reloaded["Interpolated X"].to_numpy(dtype=float), solved, equal_nan=True)
        before = float(reloaded["Interpolated X"].iloc[0])
        app.show("data", title)
        column = list(app.tables[title].raw.columns).index("Response")
        current = float(app.tables[title].raw.iat[4, column])
        app.edit_cell(4, column, f"{current + 0.45:.8f}")
        wait_for_calculation()
        moved = float(app.runs[0].result.tables["Interpolated values"]["Interpolated X"].iloc[0])
        assert abs(moved - before) > 1e-4
        app.show("result", 0)
        root.update()
        assert app.result_tabs.tab(app.result_tabs.select(), "text") == "Interpolated values"
        grid = app.result_tabs.nametowidget(app.result_tabs.select())
        seen = False
        for item in grid.tree.get_children():
            values = grid.tree.item(item, "values")
            if "Out of range" in values:
                assert values[3] == ""
                seen = True
        assert seen
        capture(root, "window-nonlinear-calibration-results.png")

    def check_4pl_calibration_workflow():
        from analisi.nonlinear_calibration import POWER_COLUMN

        dose = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        signal = 2.0 + 16.0 * dose**2 / (16.0 + dose**2)
        at_32 = 2.0 + 16.0 * 1024.0 / 1040.0
        unknown = [2.0, np.nan, 5.2, np.nan, 10.0, 14.8, at_32, 17.9]
        source = pd.DataFrame({"Row titles": list("ABCDEFGH"), "Dose": dose, "Signal": signal, "Unknown": unknown})
        path = directory / "four-pl-calibration.alab"
        save_project(path, {"Standard curve": Dataset(source)})
        app.import_file(path)

        def choose(dialog):
            pick_method(dialog, "Interpolate a standard curve")
            dialog.controls["X"][1].set("Dose")
            dialog.controls["Y"][1].set("Signal")
            dialog.controls["Unknown responses"][1].set("Unknown")
            dialog.controls["Curve"][1].set("Linear")
            if dialog.calibration_visibility().get("Model") is not False:
                raise AssertionError("Model stayed visible for a linear curve")
            dialog.controls["Curve"][1].set("Nonlinear")
            values = tuple(dialog.field_rows["Model"][1]["values"])
            if values != INVERSE_MODELS or "One-phase decay" not in values or "One-phase association" not in values:
                raise AssertionError(f"model menu is {values!r}")
            dialog.controls["Model"][1].set("Stimulation (variable slope, log10 X)")
            if dialog.field_rows["Model"][0].cget("text") != "Model (log10 X)":
                raise AssertionError(dialog.field_rows["Model"][0].cget("text"))
            dialog.controls["Model"][1].set("Stimulation (variable slope)")
            if dialog.field_rows["Model"][0].cget("text") != "Model (concentration X)":
                raise AssertionError(dialog.field_rows["Model"][0].cget("text"))
            dialog.fields.select(dialog.field_rows["Model"][0].master)
            capture(dialog, "window-4pl-calibration-options.png")

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        result = app.runs[0].result
        table = result.tables["Interpolated values"]
        assert table["Status"].tolist() == ["In range"] * 5 + ["Out of range"]
        assert table["Row title"].tolist() == ["A", "C", "E", "F", "G", "H"]
        np.testing.assert_allclose(table["Interpolated X"].iloc[:5].to_numpy(dtype=float),
                                   [0.0, 2.0, 4.0, 8.0, 32.0], atol=1e-5, rtol=0)
        assert pd.isna(table["Interpolated X"].iloc[5])
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"].to_numpy(dtype=float),
                                   [2.0, 18.0, 4.0, 2.0], atol=1e-5, rtol=0)
        axis = result.figure.axes[0]
        assert [text.get_text() for text in axis.get_legend().get_texts()] == [
            "Standards", "Stimulation (variable slope)", "Estimates"]
        assert len(axis.collections[1].get_offsets()) == 5
        assert not np.any(np.isclose(axis.collections[1].get_offsets()[:, 1], 17.9))
        app.show("graph", 0)
        capture(root, "window-4pl-calibration.png")
        svg = directory / "four-pl-calibration.svg"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(svg)):
            app.export()
        assert "<svg" in svg.read_text(encoding="utf-8")
        app.show("result", 0)
        root.update()
        assert app.result_tabs.tab(app.result_tabs.select(), "text") == "Interpolated values"
        grid = app.result_tabs.nametowidget(app.result_tabs.select())
        seen = False
        for item in grid.tree.get_children():
            values = grid.tree.item(item, "values")
            if "Out of range" in values:
                assert values[3] == ""
                seen = True
        assert seen
        capture(root, "window-4pl-calibration-results.png")
        csv_path = directory / "four-pl-calibration.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        exported = csv_path.read_text(encoding="utf-8-sig")
        assert "Interpolated X" in exported and "Out of range" in exported
        assert "17.9" in exported

        saved_options = dict(app.runs[0].options)
        solved = table["Interpolated X"].to_numpy(dtype=float).copy()
        app.path = path
        assert app.save()
        app.import_file(path)
        assert app.runs[0].options == saved_options
        app.open_sheet(("result", 0))
        wait_for_calculation()
        reloaded = app.runs[0].result.tables["Interpolated values"]
        np.testing.assert_allclose(reloaded["Interpolated X"].to_numpy(dtype=float), solved, equal_nan=True)
        before = float(reloaded.loc[reloaded["Row title"] == "C", "Interpolated X"].iloc[0])
        app.show("data", "Standard curve")
        column = list(app.tables["Standard curve"].raw.columns).index("Signal")
        current = float(app.tables["Standard curve"].raw.iat[1, column])
        app.edit_cell(1, column, f"{current + 0.75:.8f}")
        wait_for_calculation()
        moved = app.runs[0].result.tables["Interpolated values"]
        after = float(moved.loc[moved["Row title"] == "C", "Interpolated X"].iloc[0])
        assert abs(after - before) > 1e-4
        assert moved["Status"].iloc[-1] == "Out of range" and pd.isna(moved["Interpolated X"].iloc[-1])
        axis = app.runs[0].result.figure.axes[0]
        drawn = axis.collections[1].get_offsets()
        assert len(drawn) == int(moved["Interpolated X"].notna().sum())
        outside = moved.loc[moved["Status"] != "In range", "Response"].to_numpy(dtype=float)
        assert all(not np.any(np.isclose(drawn[:, 1], value)) for value in outside)

        log_x = np.array([-4.0, -3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 1.0])
        log_y = 5.0 + 40.0 / (1.0 + 10.0 ** (1.5 * (log_x + 1.0)))
        query_x = np.array([-4.0, -2.25, -1.0, 0.5, 1.0])
        query_y = 5.0 + 40.0 / (1.0 + 10.0 ** (1.5 * (query_x + 1.0)))
        log_unknown = np.full(log_x.shape, np.nan)
        log_unknown[:5] = query_y
        log_unknown[5] = 45.0
        log_unknown[6] = 5.0
        log_source = pd.DataFrame({"Row titles": list("ABCDEFGH"), "log dose": log_x, "Signal": log_y,
                                   "Unknown": log_unknown})
        log_path = directory / "four-pl-log10.alab"
        save_project(log_path, {"Log standard": Dataset(log_source)})
        app.path = path
        assert app.save()
        app.import_file(log_path)

        def choose_log(dialog):
            pick_method(dialog, "Interpolate a standard curve")
            dialog.controls["X"][1].set("log dose")
            dialog.controls["Y"][1].set("Signal")
            dialog.controls["Unknown responses"][1].set("Unknown")
            dialog.controls["Curve"][1].set("Nonlinear")
            dialog.controls["Model"][1].set("Stimulation (variable slope)")
            model_field = dialog.field_rows["Model"][1]
            with patch.object(messagebox, "showerror") as shown:
                accepted = dialog.validate()
            if accepted is not False:
                raise AssertionError("negative concentration X was accepted")
            message = "" if shown.call_args is None else shown.call_args.args[1]
            if "Model" not in str(message) or "nonnegative" not in str(message):
                raise AssertionError(f"domain error does not name the model: {message!r}")
            if dialog.fields.select() != str(model_field.master):
                raise AssertionError(f"dialog did not stay on Model: tab={dialog.fields.select()!r}")
            dialog.controls["Model"][1].set("Inhibition (variable slope, log10 X)")
            if dialog.field_rows["Model"][0].cget("text") != "Model (log10 X)":
                raise AssertionError(dialog.field_rows["Model"][0].cget("text"))
            capture(dialog, "window-4pl-log10-options.png")

        drive_dialog(AnalysisDialog, choose_log)
        app.choose_analysis()
        wait_for_calculation()
        log_result = app.runs[0].result
        log_table = log_result.tables["Interpolated values"]
        assert log_table["Status"].tolist() == ["In range"] * 5 + ["Out of range", "Out of range"]
        np.testing.assert_allclose(log_table["Interpolated X"].iloc[:5].to_numpy(dtype=float), query_x,
                                   atol=1e-5, rtol=0)
        assert POWER_COLUMN in log_table.columns
        np.testing.assert_allclose(log_table[POWER_COLUMN].iloc[:5].to_numpy(dtype=float), 10.0 ** query_x,
                                   rtol=1e-6, atol=0)
        assert log_table[POWER_COLUMN].iloc[5:].isna().all()
        assert not np.any(np.isclose(log_table["Interpolated X"].iloc[:5].to_numpy(dtype=float), 10.0 ** query_x))
        log_axis = log_result.figure.axes[0]
        assert log_axis.get_xscale() == "linear"
        assert log_axis.lines[0].get_ydata()[0] > log_axis.lines[0].get_ydata()[-1]
        assert len(log_axis.collections[1].get_offsets()) == 5
        assert log_axis.collections[1].get_offsets()[:, 0].min() < 0
        app.show("graph", 0)
        capture(root, "window-4pl-log10.png")
        log_svg = directory / "four-pl-log10.svg"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(log_svg)):
            app.export()
        assert "<svg" in log_svg.read_text(encoding="utf-8")

    def pick_method(dialog, method):
        dialog.query.set(method)
        node = next(child for folder in dialog.methods.get_children()
                    for child in dialog.methods.get_children(folder)
                    if dialog.method_by_item.get(child) == method)
        dialog.methods.selection_set(node)
        dialog.select_method()

    def select_columns(dialog, label, names):
        box = dialog.controls[label][1]
        box.selection_clear(0, "end")
        for index in range(box.size()):
            if box.get(index) in names:
                box.selection_set(index)

    def drive_dialog(dialog_type, action):
        from analisi.graph_language_smoke import drive_mapped_dialog

        def enter(dialog):
            try:
                # Deliver the focus-in event after the modal grab has been acquired.
                dialog.update()
                action(dialog)
                dialog.ok()
            except Exception as error:
                errors.append(f"{dialog_type.__name__}: {error!r}\n{traceback.format_exc()}")
                dialog.cancel()

        # Mapping alone does not mean simpledialog has completed focus/grab initialization.
        drive_mapped_dialog(root, dialog_type, enter, errors)

    def check_text_import():
        source = directory / "Assay runs.csv"
        source.write_text(
            'Sample;Comment;Response;Rack;Control\n'
            'A001;Warmup;0,5;1;1,4\n'
            'A002;"read;repeat";1,25*;1;999\n'
            'A003;Rinse;2,5;2;1,8\n'
            'A004;Keep;4,125;2;2,5\n'
            'A005;Cool down;9,5;3;9,1\n', encoding="utf-8-sig")
        before = set(app.tables)

        def options(dialog):
            dialog.separator.set("Semicolon")
            dialog.bounds["last_row"].set("6")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "row range" in shown.call_args.args[1]
            for key, value in (("first_row", "2"), ("last_row", "4"), ("skip_rows", "1"), ("skip_columns", "1")):
                dialog.bounds[key].set(value)
            dialog.mark_excluded.set(True)
            dialog.missing_code.set("999")
            dialog.after_cancel(dialog.preview_job)
            dialog.refresh_preview()
            assert dialog.summary.cget("text") == "2 rows × 3 columns"
            first = dialog.tree.get_children()[0]
            assert tuple(dialog.tree.item(first, "values")) == ("A002", "* 1.25", "")
            capture(dialog, "window-text-import-preview.png")

        drive_dialog(TextImportDialog, options)
        with patch.object(filedialog, "askopenfilename", return_value=str(source)):
            app.open_dialog(import_data=True)
        assert not errors, errors
        assert set(app.tables) == before | {"Assay runs"}
        data = app.tables["Assay runs"]
        assert list(data.raw) == ["Sample", "Response", "Control"]
        assert data.raw["Sample"].tolist() == ["A002", "A004"]
        assert data.raw["Response"].tolist() == [1.25, 4.125]
        assert data.excluded == {(0, 1)} and pd.isna(data.raw.iat[0, 2])
        assert pd.isna(data.frame(mask_excluded=True).iat[0, 1])
        path = directory / "filtered-text.alab"
        app.path = path
        assert app.save()
        app.import_file(path)
        assert app.tables["Assay runs"].excluded == {(0, 1)}
        assert app.tables["Assay runs"].raw.iat[0, 1] == 1.25

    def check_paste_special():
        title = "Worksheet filters"
        source = pd.DataFrame({"Row title": ["one", "two", "three", "four"], "Time": [1, 2, 3, 4],
                               "Control [1]": [10., 20., 30., 40.], "Control [2]": [11., 21., 31., 41.]})
        source.attrs["table_format"] = "XY with replicates"
        path = directory / "worksheet-filter.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)
        grid = app.current_grid
        root.update()

        def click_header(x, y):
            grid.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
            grid.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)

        click_header(grid.edges[2] + 5, grid.band_height // 2)
        assert grid.selection == (0, 2, 3, 3)
        click_header(grid.edges[3] + 5, grid.header_height - 5)
        assert grid.selection == (0, 3, 3, 3)
        click_header(8, grid.header_height + grid.row_height + 5)
        assert grid.selection == (1, 0, 1, 3)
        click_header(8, 5)
        assert grid.selection == (0, 0, 3, 3)
        grid.active_cell = (1, 2)
        grid.canvas.focus_force()
        root.update()
        grid.canvas.event_generate("<Shift-KeyPress-space>")
        assert grid.selection == (1, 0, 1, 3)
        grid.active_cell = (1, 2)
        grid.canvas.event_generate("<Control-KeyPress-space>")
        assert grid.selection == (0, 2, 3, 2)
        capture(root, "window-worksheet-column-selection.png")

        grid.active_cell = (1, 2)
        app.set_clipboard_text("100,25\t101\r\n200\t201\r\n\t301,5\r\n400\t401\r\n")

        def filter_paste(dialog):
            assert dialog.address == "C2"
            field = dialog.bounds[2]
            field.delete(0, "end")
            field.insert(0, "-1")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "zero or more" in shown.call_args.args[1]
            field.delete(0, "end")
            field.insert(0, "1")
            capture(dialog, "window-paste-special.png")

        drive_dialog(PasteSpecialDialog, filter_paste)
        app.paste_selection(special=True)
        data = app.tables[title].raw
        assert data.iat[1, 2] == 100.25 and data.iat[2, 3] == 301.5 and pd.isna(data.iat[2, 2])
        assert data.iat[3, 2] == 40
        assert app.current_grid.selection == (1, 2, 2, 3)
        app.apply_worksheet_history()
        assert app.tables[title].raw.iat[2, 2] == 30
        app.apply_worksheet_history(redo=True)
        assert app.save()
        app.import_file(path)
        assert pd.isna(app.tables[title].raw.iat[2, 2])

    def check_auc_peaks():
        method, title = "Area under curve", "Pulse trace"
        source = pd.DataFrame({"X": [0., 1, 2, 3, 4, 5], "Y": [0., 2, 0, -2, 0, 6]})
        path = directory / "auc-peaks.alab"
        # A project saved before Peaks existed: no peak fields, one excluded pair that must stay out.
        save_project(path, {title: Dataset(source, excluded={(5, 1)},
                                           analyses=[(method, {"X": "X", "Y": "Y", "Baseline": 0.0})])})
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        old = app.runs[0].result
        assert list(old.tables) == [method, "Data"], list(old.tables)
        totals = old.tables[method]["Value"]
        assert (totals["Area above baseline"], totals["Area below baseline"], totals["N"]) == (2, 2, 5)

        def add_peaks(dialog):
            assert dialog.controls[AUC_PEAKS][1].get() == "Off"
            assert not dialog.auc_visibility()[AUC_HEIGHT] and not dialog.field_rows[AUC_HEIGHT][1].grid_info()
            dialog.controls[AUC_PEAKS][1].set("Above and below")
            assert dialog.auc_visibility()[AUC_HEIGHT] and dialog.field_rows[AUC_HEIGHT][1].grid_info()
            assert dialog.controls[AUC_HEIGHT][1].get() == "10.0", dialog.controls[AUC_HEIGHT][1].get()
            dialog.controls[AUC_HEIGHT][1].set("150")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert AUC_HEIGHT in shown.call_args.args[1]
            assert dialog.fields.select() == str(dialog.field_rows[AUC_HEIGHT][1].master)
            capture(dialog, "window-auc-peaks-error.png")
            dialog.controls[AUC_HEIGHT][1].set("40")
            dialog.controls[AUC_WIDTH][1].set("1,5")
            capture(dialog, "window-auc-peaks-dialog.png")

        drive_dialog(AnalysisDialog, add_peaks)
        app.edit_analysis()
        wait_for_calculation()
        options = app.runs[0].options
        assert (options[AUC_PEAKS], options[AUC_HEIGHT], options[AUC_WIDTH]) == ("Above and below", 40.0, 1.5)
        tables = app.runs[0].result.tables
        assert list(tables) == [method, "Peaks", "Data"]
        np.testing.assert_allclose(tables["Peaks"]["Area"], [2, 2])
        app.show("graph", 0)
        capture(root, "window-auc-peaks-graph.png")
        app.show("result", 0)
        app.result_tabs.select(1)
        capture(root, "window-auc-peaks-table.png")
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 0))
        wait_for_calculation()
        assert app.runs[0].options[AUC_HEIGHT] == 40.0
        # Editing the source recalculates the saved recipe: the range grows to 6, so the 40% cut drops the
        # below-baseline region (height 2 < 2.4) from the peaks while the totals still count it.
        app.edit_cell(1, 1, "4")
        app.open_sheet(("result", 0))
        wait_for_calculation()
        reopened = app.runs[0].result.tables
        np.testing.assert_allclose(reopened["Peaks"]["Area"], [4])
        values = reopened[method]["Value"]
        assert (values["Retained peak area"], values["Area below baseline"], values["Total area (geometric)"]) == (4, 2, 6)

    def check_roc_workflow():
        title = "Diagnostic scores"
        source = pd.DataFrame({"Control A": [1, 2, 2, 4, 5, np.nan], "Control B": [2, 4, 1, 3, 5, np.nan],
                               "Patient A": [2, 3, 4, 4, 6, 7], "Patient B": [1, 5, 2, 6, 7, 5]})
        path = directory / "diagnostic-scores.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def pick_roc(dialog):
            pick_method(dialog, "ROC curve")
            for field, value in (("Control", "Control A"), ("Patient", "Patient A"),
                                 ("Confidence level (%)", "90"), ("Confidence interval", WILSON_BROWN),
                                 ("Show as", "Percentages")):
                dialog.controls[field][1].set(value)

        drive_dialog(AnalysisDialog, pick_roc)
        app.choose_analysis()
        wait_for_calculation()
        result = app.runs[0].result
        thresholds = result.tables["Diagnostic thresholds"].set_index("Threshold")
        np.testing.assert_allclose(thresholds.loc[5.5, ["Sensitivity CI 90% low (%)", "Sensitivity CI 90% high (%)"]]
                                   .to_numpy(dtype=float), [8.8635, 65.2985], atol=.0001)
        assert thresholds.at[2.5, "Youden candidate"] == "Yes"
        app.show("graph", 0)
        capture(root, "window-roc-curve.png")
        app.show("result", 0)
        app.result_tabs.select(2)
        capture(root, "window-roc-thresholds.png")

        def pick_paired(dialog):
            pick_method(dialog, "Compare paired ROC curves")
            for field in source.columns:
                dialog.controls[field][1].set(field)

        app.show("data", title)
        drive_dialog(AnalysisDialog, pick_paired)
        app.choose_analysis()
        wait_for_calculation()
        assert app.save()
        app.import_file(path)
        app.open_sheet(("result", 1))
        wait_for_calculation()
        np.testing.assert_allclose(app.runs[1].result.tables["Paired ROC comparison"].at["p (normal approximation)", "Value"],
                                   .826751112261351)
        app.show("data", title)
        app.edit_cell(5, 2, "0")
        app.open_sheet(("result", 0))
        wait_for_calculation()
        np.testing.assert_allclose(app.runs[0].result.tables["ROC summary"].at["AUC", "Value"], 17 / 30)

    def check_survival_workflow():
        method = "Kaplan–Meier survival"
        title = "Time to event"
        source = pd.DataFrame({"Time": [1, 2, 2, 5, 2, 3, 4, 7, 2, 4, 6, 8],
                               "Event": [1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1],
                               "Group": ["Low"] * 4 + ["Mid"] * 4 + ["High"] * 4})
        original = legacy_reference.parent / "reference" / "MVSimplesurvivalKaplanMeieranalysis.prismt" if legacy_reference else None
        order, statistic = ["Low", "Mid", "High"], 1.8903730248081347**2
        if original is not None and original.is_file():
            source = next(iter(load_tables(original).values())).rename(columns={"Time (days)": "Time", "Treatment": "Group"})
            order, statistic = ["Vehicle", "Drug_B", "Drug_A"], 11.517414060394536
        source["Event"] = source["Event"].map({1: "Occurred", 0: "Censored"})
        pending = source.iloc[:1].assign(Event="Pending", Group="Pending cases")
        source = pd.concat((source, pending), ignore_index=True)
        path = directory / "time-to-event.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def pick_survival(dialog):
            pick_method(dialog, method)
            dialog.controls["Time"][1].set("Time")
            select_columns(dialog, "Event columns", ["Event"])
            select_columns(dialog, "Grouping variables", ["Group"])
            dialog.controls[EVENT_CODE][1].set("Occurred")
            dialog.controls[CENSOR_CODE][1].set("Censored")
            dialog.controls[OTHER_STATUS][1].set("Treat as missing")
            dialog.update_survival_groups()
            dialog.controls["Gehan–Breslow–Wilcoxon"][1].set(True)
            dialog.controls["Log-rank trend"][1].set(True)
            dialog.controls["Show risk table below graph"][1].set(True)
            dialog.controls[SURVIVAL_CURVE][1].set("Cumulative events")
            dialog.controls["Display units"][1].set("Percent")
            dialog.controls["Uncertainty"][1].set("Pointwise confidence band")
            picker = dialog.controls["Trend group order"][1]
            picker.items.pop()
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "Trend group order" in shown.call_args.args[1]
            picker.set_levels(order, order)
            for index, group in enumerate(order):
                while picker.items.index(group) > index:
                    picker.listbox.selection_clear(0, "end")
                    picker.listbox.selection_set(picker.items.index(group))
                    picker.move(-1)
            assert picker.values() == order
            dialog.focus_field(SURVIVAL_CURVE)
            capture(dialog, "window-survival-graph-options.png")

        drive_dialog(AnalysisDialog, pick_survival)
        app.choose_analysis()
        wait_for_calculation()
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        result = app.runs[0].result
        assert app.runs[0].options["Trend group order"] == order
        assert app.runs[0].options[EVENT_CODE] == "Occurred"
        assert app.runs[0].options[CENSOR_CODE] == "Censored"
        assert app.tables[title].raw["Event"].iloc[-1] == "Pending"
        np.testing.assert_allclose(result.tables["Log-rank trend"].at["Trend χ²", "Value"], statistic)
        assert len(result.figure.axes) == 2
        assert app.runs[0].options["Display units"] == "Percent"
        curve_axes = result.figure.axes[0]
        assert curve_axes.get_ylabel() == "Cumulative event probability (%)"
        assert len(curve_axes.collections) == 3
        assert curve_axes.lines[0].get_ydata()[0] == 0.
        assert "Cumulative events (%)" in result.tables[f"Curve: {order[0]}"]
        capture(root, "window-survival-cumulative.png")

    def check_hartigan_wong():
        from unittest.mock import patch

        choice = kmeans_options
        title = "Synthetic clusters"
        source = pd.DataFrame({"Signal": [0., 1., float("nan"), 2., 9., 10., 11., 19., 20., 21.]})
        path = directory / "hartigan-wong.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def configure(dialog, method):
            pick_method(dialog, method)
            select_columns(dialog, "Variables", {"Signal"})
            assert not dialog.field_rows[choice.MAX_ITERATIONS][1].winfo_manager()
            dialog.controls[choice.ALGORITHM][1].set(choice.HARTIGAN)
            assert dialog.field_rows[choice.MAX_ITERATIONS][1].winfo_manager()
            dialog.controls[choice.SCALE][1].set(choice.UNSCALED)

        def pick_fit(dialog):
            configure(dialog, choice.CLUSTERING)
            dialog.controls["Clusters"][1].set(3)
            rows = dialog.controls[choice.INITIAL_ROWS][1]
            rows.set("1, 3, 8")
            with patch.object(messagebox, "showerror") as error:
                assert not dialog.validate() and error.called
            rows.set("1, 5, 8")
            capture(dialog, "window-hartigan-wong-analysis.png")

        def pick_scan(dialog):
            configure(dialog, choice.SELECTION)
            dialog.controls["Criterion"][1].set("Consensus (17 indices)")
            dialog.controls["Gap simulations"][1].set(5)
            dialog.controls["Maximum k"][1].set(4)

        def verify():
            fit, scan = app.runs
            assert fit.options[choice.INITIAL_ROWS] == "1, 5, 8"
            assert scan.options[choice.ALGORITHM] == choice.HARTIGAN
            np.testing.assert_allclose(fit.result.tables["Centers (fitting scale)"].iloc[:, 0], [1, 10, 20])
            assert fit.result.tables["Fit"].loc["Within-cluster SS", "Value"] == 6
            assert scan.result.tables["Selection"].loc["Suggested k", "Value"] == 3
            assert scan.result.tables["Cluster metrics"].loc[3, "WSS"] == 6
            assert np.isfinite(scan.result.tables["Cluster metrics"].loc[3, "Gap"])

        app.show("data", title)
        drive_dialog(AnalysisDialog, pick_fit)
        app.choose_analysis()
        wait_for_calculation()
        app.show("data", title)
        drive_dialog(AnalysisDialog, pick_scan)
        app.choose_analysis()
        wait_for_calculation()
        verify()
        assert app.save()
        app.import_file(path)
        for index in range(2):
            app.open_sheet(("graph", index))
            wait_for_calculation()
        verify()
        app.show("graph", 0)
        capture(root, "window-hartigan-wong-plot.png")
        app.show("graph", 1)
        capture(root, "window-hartigan-wong-consensus.png")

    def check_macqueen():
        choice = kmeans_options
        title = "Sequential clusters"
        source = pd.DataFrame({"Signal": [0., 1., 2., 3., 4., 6.]})
        path = directory / "macqueen.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def configure(dialog):
            pick_method(dialog, choice.CLUSTERING)
            select_columns(dialog, "Variables", {"Signal"})
            dialog.controls[choice.ALGORITHM][1].set(choice.MACQUEEN)
            assert not dialog.field_rows[choice.MAX_ITERATIONS][1].winfo_manager()
            assert dialog.field_rows[choice.MACQUEEN_ITERATIONS][1].winfo_manager()
            dialog.controls[choice.SCALE][1].set(choice.UNSCALED)
            dialog.controls[choice.INITIAL_ROWS][1].set("1, 2")
            dialog.controls[kmeans_reports.CENTROIDS][1].set(True)
            dialog.focus_field(choice.MACQUEEN_ITERATIONS)
            assert dialog.field_rows[choice.MACQUEEN_ITERATIONS][1].winfo_viewable()
            capture(dialog, "window-macqueen-analysis.png")

        def verify():
            run = app.runs[0]
            assert run.options[choice.ALGORITHM] == choice.MACQUEEN
            assert run.options[choice.MACQUEEN_ITERATIONS] == choice.DEFAULT_ITERATIONS
            assert choice.MAX_ITERATIONS not in run.options
            assert run.options[choice.INITIAL_ROWS] == "1, 2"
            tables = run.result.tables
            np.testing.assert_allclose(tables["Centers (fitting scale)"]["Signal"], [1., 13 / 3])
            np.testing.assert_allclose(tables["Fit"].loc["Within-cluster SS", "Value"], 20 / 3)
            np.testing.assert_array_equal(tables["Initial centroids"]["Initial center"], [0., 1.])

        app.show("data", title)
        drive_dialog(AnalysisDialog, configure)
        app.choose_analysis()
        wait_for_calculation()
        verify()
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        verify()
        capture(root, "window-macqueen-plot.png")

    def check_kmeans_reports():
        from unittest.mock import patch

        title = "Clustering reports"
        path = directory / "kmeans-reports.alab"
        csv_path = directory / "kmeans-cluster-details.csv"
        svg_path = directory / "kmeans-diagnostics.svg"
        source = pd.DataFrame({"Signal": [0., 1., 2., 9., 10., 11., 19., 20., 21.]})
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def choose_reports(dialog):
            pick_method(dialog, kmeans_options.SELECTION)
            select_columns(dialog, "Variables", {"Signal"})
            dialog.controls[kmeans_options.ALGORITHM][1].set(kmeans_options.HARTIGAN)
            dialog.controls["Criterion"][1].set("Silhouette")
            assert not dialog.field_rows[kmeans_reports.GAP][1].winfo_manager()
            dialog.controls[kmeans_options.GAP_PLOT][1].set(True)
            assert dialog.field_rows[kmeans_reports.GAP][1].winfo_manager()
            dialog.controls["Criterion"][1].set("Consensus (17 indices)")
            dialog.controls["Maximum k"][1].set(4)
            dialog.controls["Gap simulations"][1].set(5)
            dialog.controls[kmeans_options.SCALE][1].set(kmeans_options.UNSCALED)
            assert not dialog.field_rows[kmeans_reports.SCALED][1].winfo_manager()
            dialog.controls[kmeans_options.SCALE][1].set(kmeans_options.STANDARDIZED)
            assert dialog.field_rows[kmeans_reports.SCALED][1].winfo_manager()
            for plot in kmeans_options.PLOTS:
                dialog.controls[plot][1].set(True)
            for report in kmeans_reports.SCAN:
                dialog.controls[report][1].set(True)
            button = dialog.field_rows[kmeans_options.GAP_PLOT][1]
            dialog.fields.select(button.master)
            dialog.update_idletasks()
            capture(dialog, "window-kmeans-plot-options.png")

        def verify():
            result = app.runs[0].result
            tabs = result.tables
            assert [axes.get_title() for axes in result.figure.axes] == [
                "K-means consensus votes", "WSS elbow", "Mean silhouette", "Gap statistic",
            ]
            assert tabs["Assignments by k"].shape == (9, 5)
            assert len(tabs["Cluster details"]) == len(tabs["Initial centroids"]) == 10
            assert len(tabs["Cluster ANOVA"]) == len(tabs["Gap statistics"]) == 4
            assert np.isclose(tabs["Standardized observations"]["Signal"].std(), 1.0)
            for count in (1, 2, 3, 4):
                assert np.isclose((tabs["Assigned distances"][f"Distance (k={count})"] ** 2).sum(),
                                  tabs["Cluster metrics"].loc[count, "WSS"])
            return tabs

        app.show("data", title)
        drive_dialog(AnalysisDialog, choose_reports)
        app.choose_analysis()
        wait_for_calculation()
        before = verify()
        app.show("result", 0)
        app.result_tabs.select(list(before).index("Cluster details"))
        root.update()
        capture(root, "window-kmeans-cluster-details.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        assert "Within SS" in csv_path.read_text(encoding="utf-8-sig")
        app.show("graph", 0)
        root.update()
        capture(root, "window-kmeans-diagnostics.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(svg_path)):
            app.export()
        assert all(title in svg_path.read_text(encoding="utf-8") for title in ("WSS elbow", "Mean silhouette",
                                                                               "Gap statistic"))
        assert app.save()
        app.import_file(path)
        app.open_sheet(("graph", 0))
        wait_for_calculation()
        after = verify()
        assert all(app.runs[0].options.get(plot) is True for plot in kmeans_options.PLOTS)
        assert kmeans_reports.requested(app.runs[0].options, scan=True) == set(kmeans_reports.SCAN)
        for name in before:
            pd.testing.assert_frame_equal(before[name], after[name])
        app.show("result", 0)
        app.result_tabs.select(list(after).index("Assignments by k"))
        root.update()
        capture(root, "window-kmeans-assignments-by-k.png")

    def check_kmeans_consensus():
        from analisi.cluster_consensus import KL_SCALING, UNSCALED_WSS, WSS_DROP_RATIO

        offsets = np.array([[0., 0.], [6., 0.], [3., 5.]])
        jitter = np.array([[-.3, -.2], [.2, -.3], [.3, .2], [-.2, .3], [0., 0.], [.1, -.1]])
        points = (offsets[:, None, :] + jitter).reshape(-1, 2)
        title = "Cluster sample"
        app._add_tables({title: pd.DataFrame(points, columns=["Cluster", "Marker"])})
        single = {"Variables": ["Cluster", "Marker"], "Minimum k": 1, "Maximum k": 5, "Standardize": True,
                  "Seed": 42, "Criterion": "Silhouette", "Gap simulations": 20}
        frame = app.tables[title].frame(mask_excluded=True)
        app.add_result(Run("K-means model selection", title, single), analyse("K-means model selection", frame, single))
        before_single = app.runs[-1].result.tables["Model metrics"]

        def pick_consensus(dialog):
            pick_method(dialog, "K-means model selection")
            select_columns(dialog, "Variables", {"Cluster", "Marker"})
            assert not dialog.field_rows[KL_SCALING][1].winfo_manager()
            dialog.controls["Criterion"][1].set("Consensus (17 indices)")
            assert dialog.field_rows[KL_SCALING][1].winfo_manager()
            dialog.controls["Maximum k"][1].set("5")
            dialog.controls["Gap simulations"][1].set("5")

        drive_dialog(AnalysisDialog, pick_consensus)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        tables = app.runs[index].result.tables
        assert {"Cluster metrics", "Consensus votes", "Selection", "Assignments"} <= set(tables)
        assert tables["Selection"].loc["Suggested k", "Value"] == 3
        assert len(tables["Consensus votes"]) == 17 and tables["Cluster metrics"].index.tolist() == [1, 2, 3, 4, 5]
        assignments = tables["Assignments"]
        pd.testing.assert_series_equal(assignments["Cluster"], frame["Cluster"])
        assert assignments.iloc[:, -1].nunique() == 3
        app.show("result", index)
        capture(root, "window-kmeans-metrics.png")
        app.show("graph", index)
        axis, = app.runs[index].result.figure.axes
        np.testing.assert_array_equal(axis.get_xticks(), [2, 3, 4, 5])
        np.testing.assert_array_equal([bar.get_height() for bar in axis.patches], [1, 16, 0, 0])
        np.testing.assert_allclose(axis.lines[0].get_xdata(), [3, 3])
        capture(root, "window-kmeans-consensus.png")
        app.show("result", index)

        def narrow_scan(dialog):
            assert dialog.controls["Criterion"][1].get() == "Consensus (17 indices)"
            dialog.controls["Maximum k"][1].set("4")
            dialog.controls[KL_SCALING][1].set(UNSCALED_WSS)

        drive_dialog(AnalysisDialog, narrow_scan)
        app.edit_analysis()
        wait_for_calculation()
        edited = app.runs[index].result.tables["Cluster metrics"]
        assert edited.index.tolist() == [1, 2, 3, 4]
        assert WSS_DROP_RATIO in edited
        assert app.runs[index].options["Criterion"] == "Consensus (17 indices)"
        assert app.runs[index].options[KL_SCALING] == UNSCALED_WSS
        app.path = directory / "kmeans-consensus.alab"
        assert app.save()
        app.import_file(app.path)
        runs = [i for i, run in enumerate(app.runs) if run.method == "K-means model selection"]
        assert [app.runs[i].options["Criterion"] for i in runs] == ["Silhouette", "Consensus (17 indices)"]
        for position in runs:
            app.recalculate(position)
            wait_for_calculation()
        pd.testing.assert_frame_equal(app.runs[runs[0]].result.tables["Model metrics"], before_single)
        pd.testing.assert_frame_equal(app.runs[runs[1]].result.tables["Cluster metrics"], edited)

    def check_deming_workflow():
        from analisi.deming import RESIDUAL_COLUMN

        title = "Deming pairs"
        source = pd.DataFrame({"X": [0, 1, np.nan, 2, 3, 4], "Y": [1, 3, 9, 2, 5, 7]})
        path = directory / "deming-pairs.alab"
        save_project(path, {title: Dataset(source)})
        app.import_file(path)

        def pick_deming(dialog):
            pick_method(dialog, "Deming regression")
            assert dialog.method == "Deming regression", dialog.method
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            assert dialog.controls["Parameter intervals"][1].get() == "None", dialog.controls["Parameter intervals"][1].get()
            assert dialog.deming_visibility() == {"Y / X error variance": True, "X error SD": False, "Y error SD": False,
                                                  "Confidence level (%)": False}, dialog.deming_visibility()
            dialog.controls["Y / X error variance"][1].set("0")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False, "zero ratio was accepted"
            assert dialog.result is None and dialog.winfo_exists(), dialog.result
            assert shown.call_args is not None and "Y / X error variance" in shown.call_args.args[1], shown.call_args
            dialog.controls["Y / X error variance"][1].set("1")
            dialog.controls["Parameter intervals"][1].set("Jackknife (t)")
            assert dialog.deming_visibility()["Confidence level (%)"], dialog.deming_visibility()
            dialog.controls["Confidence level (%)"][1].set("120")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False, "level 120 was accepted"
            assert dialog.result is None and dialog.winfo_exists(), dialog.result
            assert shown.call_args is not None and "Confidence level (%)" in shown.call_args.args[1], shown.call_args
            entry = dialog.field_rows["Confidence level (%)"][1]
            focused = dialog.focus_get()
            assert focused == entry, (focused, entry, entry.winfo_viewable(), dialog.fields.select())
            dialog.controls["Confidence level (%)"][1].set("95")
            dialog.controls["Identity line"][1].set(True)
            dialog.focus_field("Parameter intervals")
            capture(dialog, "window-deming-options.png")

        drive_dialog(AnalysisDialog, pick_deming)
        app.choose_analysis()
        wait_for_calculation()
        index = len(app.runs) - 1
        result = app.runs[index].result
        summary = result.tables["Deming regression"]["Value"]
        np.testing.assert_allclose(summary["Slope"], 1.5769804236540488, rtol=1e-12)
        np.testing.assert_allclose(summary["Slope SE"], 0.32862363, atol=5e-9)
        np.testing.assert_allclose(summary["Intercept SE"], 1.04511970, atol=5e-9)
        pairs = result.tables["Pairs"]
        np.testing.assert_allclose(pairs[RESIDUAL_COLUMN], pairs["Y"] - pairs["Fitted Y"])
        assert pairs["Source row"].tolist() == [0, 1, 3, 4, 5], pairs["Source row"].tolist()
        axis = result.figure.axes[0]
        identity = [line for line in axis.lines if line.get_label() == "Identity"]
        assert len(identity) == 1 and identity[0].get_linestyle() in {"--", "dashed"}, [
            (line.get_label(), line.get_linestyle()) for line in axis.lines]
        assert any(line.get_label() == "Deming fit" for line in axis.lines), [line.get_label() for line in axis.lines]
        app.show("graph", index)
        root.update()
        capture(root, "window-deming-regression.png")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "deming-fit.svg")):
            app.export()
        assert b"<svg" in (directory / "deming-fit.svg").read_bytes(), "SVG export did not contain an svg element"
        width = float(summary["Slope CI high"]) - float(summary["Slope CI low"])

        def set_level(dialog):
            assert dialog.method == "Deming regression", dialog.method
            assert dialog.controls["Parameter intervals"][1].get() == "Jackknife (t)", dialog.controls["Parameter intervals"][1].get()
            dialog.controls["Confidence level (%)"][1].set("90")

        drive_dialog(AnalysisDialog, set_level)
        app.edit_analysis()
        wait_for_calculation()
        edited = app.runs[index].result.tables["Deming regression"]["Value"]
        edited_width = float(edited["Slope CI high"]) - float(edited["Slope CI low"])
        assert edited_width < width, (edited_width, width)
        np.testing.assert_allclose(edited["Slope"], summary["Slope"])

        def clear_intervals(dialog):
            dialog.controls["Parameter intervals"][1].set("None")
            assert dialog.deming_visibility()["Confidence level (%)"] is False, dialog.deming_visibility()

        drive_dialog(AnalysisDialog, clear_intervals)
        app.edit_analysis()
        wait_for_calculation()
        cleared = app.runs[index].result.tables["Deming regression"]
        assert list(cleared.index) == ["N", "Slope", "Intercept", "Y / X measurement error variance"], list(cleared.index)
        assert "Pairs" in app.runs[index].result.tables, list(app.runs[index].result.tables)
        assert "Confidence level (%)" not in app.runs[index].options, app.runs[index].options
        assert app.runs[index].options["Parameter intervals"] == "None", app.runs[index].options
        assert app.save(), "project save failed"
        app.import_file(path)
        app.show("data", title)
        app.edit_cell(0, 1, "10")
        app.open_sheet(("result", 0))
        wait_for_calculation()
        updated = app.runs[0].result
        assert updated is not None, "reopened result was not calculated"
        assert not np.isclose(float(updated.tables["Deming regression"]["Value"]["Slope"]), float(summary["Slope"]))
        assert list(updated.tables) == ["Deming regression", "Data", "Pairs"], list(updated.tables)

    def check_deming_multiseries_smoke():
        from analisi.deming_smoke import check_deming_multiseries

        check_deming_multiseries(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation, errors=errors, filedialog=filedialog, messagebox=messagebox))

    def check_linear_diagnostics_workflow():
        line = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [1, 3, 2, 5, 7]})
        exact = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [3, 5, 7, 9, 11]})
        legacy = Dataset(line.copy())
        legacy.analyses.append(("Linear regression", {"X": "X", "Y": "Y"}))
        path = directory / "linear-diagnostics.alab"
        save_project(path, {"Line": legacy, "Exact line": Dataset(exact)})
        app.import_file(path)
        assert not errors, errors
        assert [run.method for run in app.runs] == ["Linear regression"]
        assert set(app.runs[0].options) == {"X", "Y"}
        app.show("data", "Line")

        def choose(dialog):
            pick_method(dialog, "Linear regression")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            assert dialog.linear_visibility()["Confidence level (%)"] is False
            dialog.controls["Band"][1].set("Confidence (mean)")
            level = dialog.field_rows["Confidence level (%)"][1]
            dialog.fields.select(level.master)
            dialog.update_idletasks()
            assert dialog.linear_visibility()["Confidence level (%)"] is True
            assert level.winfo_ismapped()
            dialog.controls["Confidence level (%)"][1].set("abc")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert dialog.winfo_exists()
            assert "Confidence level (%)" in shown.call_args.args[1]
            dialog.update_idletasks()
            assert dialog.focus_get() == level
            dialog.controls["Confidence level (%)"][1].set("0")
            with patch.object(messagebox, "showerror") as shown:
                assert dialog.validate() is False
            assert "Confidence level (%)" in shown.call_args.args[1]
            assert "between" in shown.call_args.args[1]
            dialog.update_idletasks()
            assert dialog.focus_get() == level
            dialog.controls["Confidence level (%)"][1].set("95")
            dialog.controls["Residual diagnostics"][1].set(True)
            dialog.controls["Graph"][1].set("Fit")
            dialog.fields.select(dialog.field_rows["Band"][0].master)
            capture(dialog, "window-linear-diagnostics.png")

        drive_dialog(AnalysisDialog, choose)
        app.choose_analysis()
        wait_for_calculation()
        fitted = next(i for i, run in enumerate(app.runs)
                      if run.title == "Line" and run.options.get("Residual diagnostics"))
        tables = app.runs[fitted].result.tables
        assert "Regression" in tables
        summary = tables["Regression"]["Value"]
        assert np.isclose(summary["Intercept"], 0.8)
        assert np.isclose(summary["Slope"], 1.4)
        np.testing.assert_allclose(tables["Residuals"]["Cook's distance"],
                                   [0.0625, 0.16326531, 0.33333333, 0, 0.5625], rtol=1e-6, atol=1e-8)
        mean_band = tables["Pointwise confidence band"]
        center = mean_band.loc[np.isclose(mean_band["X"], 2)].iloc[0]
        np.testing.assert_allclose([center["Fitted Y"], center["Lower"], center["Upper"]],
                                   [3.6, 2.040926, 5.159074], atol=1e-6)
        assert "prediction" not in center["Band"].lower()
        app.show("result", fitted)
        capture(root, "window-linear-diagnostics-results.png")
        app.show("graph", fitted)
        capture(root, "window-linear-diagnostics-fit.png")

        def switch_view(dialog):
            assert dialog.controls["Residual diagnostics"][1].get() is True
            dialog.controls["Graph"][1].set("Residuals vs fitted")
            dialog.controls["Band"][1].set("Prediction (new observation)")
            dialog.controls["Confidence level (%)"][1].set("95")

        drive_dialog(AnalysisDialog, switch_view)
        app.edit_analysis()
        wait_for_calculation()
        edited = app.runs[fitted]
        assert edited.options["Graph"] == "Residuals vs fitted"
        assert edited.options["Band"] == "Prediction (new observation)"
        assert "Regression" in edited.result.tables
        prediction = edited.result.tables["Pointwise prediction band"]
        predicted = prediction.loc[np.isclose(prediction["X"], 2)].iloc[0]
        np.testing.assert_allclose([predicted["Lower"], predicted["Upper"]], [-0.218936, 7.418936], atol=1e-6)
        assert len(edited.result.figure.axes) == 1
        axis = edited.result.figure.axes[0]
        assert axis.get_xlabel() == "Fitted Y" and axis.get_ylabel() == "Residual"
        assert any(np.allclose(line.get_ydata(), 0) for line in axis.lines)
        app.show("graph", fitted)
        capture(root, "window-linear-diagnostics-residuals.png")

        app.show("data", "Exact line")

        def choose_exact(dialog):
            pick_method(dialog, "Linear regression")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Residual diagnostics"][1].set(True)
            assert dialog.controls["Band"][1].get() == "None"
            assert dialog.linear_visibility()["Confidence level (%)"] is False

        drive_dialog(AnalysisDialog, choose_exact)
        app.choose_analysis()
        wait_for_calculation()
        exact_index = next(i for i, run in enumerate(app.runs) if run.title == "Exact line")
        exact_tables = app.runs[exact_index].result.tables
        assert exact_tables["Residuals"]["Internally studentized residual"].isna().all()
        assert exact_tables["Residuals"]["Cook's distance"].isna().all()
        assert exact_tables["Residuals"]["Leverage"].notna().all()
        assert np.allclose(exact_tables["Residuals"]["Residual"], 0)
        assert "blank" in exact_tables["Regression"].loc["Diagnostics note", "Value"]

        saved_options = dict(edited.options)
        saved_tables = {name: frame.copy(deep=True) for name, frame in edited.result.tables.items()}
        exact_options = dict(app.runs[exact_index].options)
        exact_saved = {name: frame.copy(deep=True) for name, frame in exact_tables.items()}
        assert app.save()
        app.import_file(path)
        assert not errors, errors
        fitted = next(i for i, run in enumerate(app.runs) if run.options == saved_options)
        exact_index = next(i for i, run in enumerate(app.runs) if run.options == exact_options)
        legacy_index = next(i for i, run in enumerate(app.runs)
                            if run.title == "Line" and set(run.options) == {"X", "Y"})
        assert app.runs[fitted].options == saved_options
        assert app.runs[exact_index].options == exact_options
        for position, expected in ((fitted, saved_tables), (exact_index, exact_saved)):
            app.recalculate(position)
            wait_for_calculation()
            for name, frame in expected.items():
                pd.testing.assert_frame_equal(app.runs[position].result.tables[name], frame)
        app.show("data", "Line")
        app.edit_cell(4, 1, "14")
        wait_for_calculation()
        slope = app.runs[fitted].result.tables["Regression"].loc["Slope", "Value"]
        assert slope > 1.4
        app.show("graph", fitted)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "linear-diagnostics.svg")):
            app.export()
        assert b"<svg" in (directory / "linear-diagnostics.svg").read_bytes()

        def old_recipe(dialog):
            assert dialog.method == "Linear regression"
            assert dialog.controls["X"][1].get() == "X" and dialog.controls["Y"][1].get() == "Y"
            assert dialog.controls["Graph"][1].get() == "Fit"
            assert dialog.controls["Band"][1].get() == "None"
            assert dialog.linear_visibility()["Confidence level (%)"] is False
            dialog.update_idletasks()
            assert not dialog.field_rows["Confidence level (%)"][1].winfo_ismapped()
            dialog.controls["Confidence level (%)"][1].set("abc")
            assert dialog.validate() is True
            assert "Confidence level (%)" not in dialog.result[1]
            capture(dialog, "window-linear-legacy.png")

        app.show("result", legacy_index)
        drive_dialog(AnalysisDialog, old_recipe)
        app.edit_analysis()
        wait_for_calculation()
        assert "Confidence level (%)" not in app.runs[legacy_index].options
        assert app.runs[legacy_index].options["Band"] == "None"
        assert app.runs[legacy_index].options["Graph"] == "Fit"
        assert list(app.runs[legacy_index].result.tables) == ["Regression"]

    def check_language():
        from analisi.language_smoke import check_language as run_language_check
        run_language_check(root, app, directory, SimpleNamespace(
            App=App, AnalysisDialog=AnalysisDialog, TextImportDialog=TextImportDialog, LayoutDialog=LayoutDialog,
            capture=capture, drive_dialog=drive_dialog, pick_method=pick_method, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_graph_language():
        from analisi.graph_language_smoke import check_graph_language as run_graph_language_check
        run_graph_language_check(root, app, directory, SimpleNamespace(
            App=App, AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, messagebox=messagebox, filedialog=filedialog,
            Dataset=Dataset, save_project=save_project, errors=errors))

    def check_lognormal_tests_smoke():
        from analisi.lognormal_smoke import check_lognormal_tests
        check_lognormal_tests(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_heat_map_colors_smoke():
        from analisi.heatmap_smoke import check_heat_map_colors
        check_heat_map_colors(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_heat_map_number_format_smoke():
        from analisi.heatmap_number_format_smoke import check_heat_map_number_format
        check_heat_map_number_format(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_heat_map_cell_labels_smoke():
        from analisi.heatmap_cell_labels_smoke import check_heat_map_cell_labels
        check_heat_map_cell_labels(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_heat_map_layout_smoke():
        from analisi.heatmap_layout_smoke import check_heat_map_layout
        check_heat_map_layout(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_grouped_distributions_smoke():
        from analisi.grouped_distributions_smoke import check_grouped_distributions
        check_grouped_distributions(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_equivalence_smoke():
        from analisi.equivalence_smoke import check_equivalence
        check_equivalence(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_independent_roc_smoke():
        from analisi.independent_roc_smoke import check_independent_roc as run_independent_roc_smoke
        run_independent_roc_smoke(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_paired_proportions_smoke():
        from analisi.paired_proportions_smoke import check_paired_proportions
        check_paired_proportions(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_tolerance_smoke():
        from analisi.tolerance_smoke import check_tolerance
        check_tolerance(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_summary_ttest_smoke():
        from analisi.summary_ttest_smoke import check_summary_ttest
        check_summary_ttest(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_mean_permutation_smoke():
        from analisi.mean_permutation_smoke import check_mean_permutation
        check_mean_permutation(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_summary_anova_smoke():
        from analisi.summary_anova_smoke import check_summary_anova
        check_summary_anova(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, GraphFormatDialog=GraphFormatDialog, capture=capture,
            drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_lognormality_smoke():
        from analisi.lognormality_smoke import check_lognormality
        check_lognormality(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_lognormal_anova_smoke():
        from analisi.lognormal_anova_smoke import check_lognormal_anova
        check_lognormal_anova(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture, messagebox=messagebox,
            filedialog=filedialog, save_project=save_project, wait_for_calculation=wait_for_calculation))

    def check_qq_panels_smoke():
        from analisi.qq_panels_smoke import check_qq_panels
        check_qq_panels(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            QQPanelsDialog=QQPanelsDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_qq_artist_styles_smoke():
        from analisi.qq_panels_smoke import check_qq_artist_styles
        check_qq_artist_styles(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            QQPanelsDialog=QQPanelsDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_spearman_extended_smoke():
        from analisi.spearman_extended_smoke import check_spearman_extended
        check_spearman_extended(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, errors=errors))

    def check_cohen_kappa_smoke():
        from analisi.cohen_kappa_smoke import check_cohen_kappa
        check_cohen_kappa(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_correlation_details_smoke():
        from analisi.correlation_details_smoke import check_correlation_details
        check_correlation_details(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_robust_curve_smoke():
        from analisi.robust_curve_smoke import check_robust_curve
        check_robust_curve(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_nb2_smoke():
        from analisi.nb2_smoke import check_nb2_regression
        check_nb2_regression(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_competing_risks_smoke():
        from analisi.competing_risks_smoke import check_competing_risks
        check_competing_risks(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_rmcorr_smoke():
        from analisi.rmcorr_smoke import check_rmcorr
        check_rmcorr(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_meta_analysis_smoke():
        from analisi.meta_analysis_smoke import check_meta_analysis
        check_meta_analysis(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_weibull_aft_smoke():
        from analisi.weibull_aft_smoke import check_weibull_aft
        check_weibull_aft(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_ordinal_logit_smoke():
        from analisi.ordinal_logit_smoke import check_ordinal_logit
        check_ordinal_logit(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_rmst_smoke():
        from analisi.rmst_smoke import check_rmst
        check_rmst(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Run=Run, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_reference_normalization_smoke():
        from analisi.reference_normalization_smoke import check_reference_normalization
        check_reference_normalization(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_nonlinear_weighting_smoke():
        from analisi.nonlinear_weighting_smoke import check_nonlinear_weighting
        check_nonlinear_weighting(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_nonlinear_bands_smoke():
        from analisi.nonlinear_bands_smoke import check_nonlinear_bands
        check_nonlinear_bands(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_custom_profiles_smoke():
        from analisi.custom_profiles_smoke import check_custom_profiles
        check_custom_profiles(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_global_profiles_smoke():
        from analisi.global_custom_profiles_smoke import check_global_custom_profiles
        check_global_custom_profiles(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_parameter_weighting_smoke():
        from analisi.parameter_weighting_smoke import check_parameter_weighting
        check_parameter_weighting(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_parameter_intervals_smoke():
        from analisi.parameter_intervals_smoke import check_parameter_intervals
        check_parameter_intervals(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_global_irls_smoke():
        from analisi.global_irls_smoke import check_global_irls
        check_global_irls(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_custom_equation_smoke():
        from analisi.custom_equation_smoke import check_custom_equation
        check_custom_equation(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_piecewise_equations_smoke():
        from analisi.piecewise_equation_smoke import check_piecewise_equations
        check_piecewise_equations(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_global_custom_smoke():
        from analisi.global_custom_smoke import check_global_custom
        check_global_custom(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_global_uncertainty_smoke():
        from analisi.global_uncertainty_smoke import check_global_uncertainty
        check_global_uncertainty(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors))

    def check_linear_estimates_smoke():
        from analisi.linear_estimates_smoke import check_linear_estimates
        check_linear_estimates(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_mlr_weighting_smoke():
        from analisi.mlr_weighting_smoke import check_mlr_weighting
        check_mlr_weighting(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, GraphFormatDialog=GraphFormatDialog, capture=capture,
            drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_analysis_chains_smoke():
        from analisi.analysis_chain_smoke import check_analysis_chains
        check_analysis_chains(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture,
            drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, errors=errors))

    def check_hierarchical_import_smoke():
        from analisi.hierarchical_import_smoke import check_hierarchical_import
        check_hierarchical_import(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, errors=errors))

    def check_hierarchical_style_smoke():
        from analisi.hierarchical_style_smoke import check_hierarchical_style
        check_hierarchical_style(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, GraphFormatDialog=GraphFormatDialog, capture=capture,
            drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, errors=errors))

    def check_binomial_goodness_smoke():
        from analisi.binomial_goodness_smoke import check_binomial_goodness
        check_binomial_goodness(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset, errors=errors))

    def check_family_workflow_smoke():
        from analisi.family_workflow_smoke import check_family_workflow
        check_family_workflow(root, app, directory, SimpleNamespace(
            App=App, capture=capture, messagebox=messagebox, filedialog=filedialog, errors=errors))

    def check_cluster_silhouette_smoke():
        from analisi.cluster_silhouette_smoke import check_cluster_silhouette
        check_cluster_silhouette(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, capture=capture,
            drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog, errors=errors, Dataset=Dataset, save_project=save_project))

    try:
        screen = (root.winfo_screenwidth(), root.winfo_screenheight())
        (directory / "display.json").write_text(json.dumps({"width": screen[0], "height": screen[1],
            "native_dpi": window_dpi(root), "ui_scale": ui_theme.scale(), "font": ui_theme.family()}), encoding="utf-8")
        if screen[0] < 1024 or screen[1] < 768:
            raise RuntimeError(
                f"GUI smoke requires a display of at least 1024x768; actual display is {screen[0]}x{screen[1]}. "
                "On Linux use xvfb-run -a -s '-screen 0 1024x768x24'.")
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "hierarchical-import":
            check_hierarchical_import_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "hierarchical-style":
            # Dendrogram and heat-map presentation:
            # TRAMASTAT_SMOKE_ONLY=hierarchical-style python tramastat.py --smoke DIR
            check_hierarchical_style_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "analysis-chains":
            check_analysis_chains_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "cluster-silhouette":
            # The Cluster silhouette check alone: TRAMASTAT_SMOKE_ONLY=cluster-silhouette python tramastat.py --smoke DIR
            check_cluster_silhouette_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "family-workflow":
            # The experiment-family check alone: TRAMASTAT_SMOKE_ONLY=family-workflow python tramastat.py --smoke DIR
            check_family_workflow_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "modern-theme":
            from analisi.modern_theme_smoke import check_modern_theme
            check_modern_theme(root, app, directory, SimpleNamespace(
                Run=Run, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "global-profiles":
            check_global_profiles_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "custom-profiles":
            check_custom_profiles_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "parameter-weighting":
            check_parameter_weighting_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "parameter-intervals":
            check_parameter_intervals_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "linear-estimates":
            check_linear_estimates_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "graph-language":
            # The 0.59 Format Graph and Inspector language check alone:
            # TRAMASTAT_SMOKE_ONLY=graph-language python tramastat.py --smoke DIR
            check_graph_language()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "language":
            # The Edit → Language… check alone: TRAMASTAT_SMOKE_ONLY=language python tramastat.py --smoke DIR
            check_language()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "cox":
            # The Cox check alone: TRAMASTAT_SMOKE_ONLY=cox python tramastat.py --smoke DIR
            check_cox_outputs()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "deming-multiseries":
            # The Deming known SDs, several series and projections check alone:
            # TRAMASTAT_SMOKE_ONLY=deming-multiseries python tramastat.py --smoke DIR
            check_deming_multiseries_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "cox-exact-ties":
            # Cox exact conditional ties alone: TRAMASTAT_SMOKE_ONLY=cox-exact-ties python tramastat.py --smoke DIR
            check_cox_exact_ties_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "cox-fit-diagnostics":
            # The scaled Schoenfeld and Cox-Snell check alone:
            # TRAMASTAT_SMOKE_ONLY=cox-fit-diagnostics python tramastat.py --smoke DIR
            check_cox_fit_diagnostics()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "plot-function":
            # The Plot a function check alone: TRAMASTAT_SMOKE_ONLY=plot-function python tramastat.py --smoke DIR
            from analisi.plot_function_smoke import check_plot_function
            check_plot_function(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "power-from-summary":
            # The Tools → Power and sample size check alone: TRAMASTAT_SMOKE_ONLY=power-from-summary python tramastat.py --smoke DIR
            from analisi.power_plan_smoke import check_power_plan
            check_power_plan(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "model-selection":
            # The Compare models (AICc) check alone: TRAMASTAT_SMOKE_ONLY=model-selection python tramastat.py --smoke DIR
            from analisi.model_selection_smoke import check_model_selection
            check_model_selection(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "calibration-prediction":
            # The Y from X check alone: TRAMASTAT_SMOKE_ONLY=calibration-prediction python tramastat.py --smoke DIR
            from analisi.calibration_prediction_smoke import check_calibration_prediction
            check_calibration_prediction(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "calibration-intervals":
            # The 0.53 interval check alone: TRAMASTAT_SMOKE_ONLY=calibration-intervals python tramastat.py --smoke DIR
            from analisi.calibration_053_smoke import check_calibration_intervals
            check_calibration_intervals(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "nonlinear-inverse":
            # The inverse-interval check alone: TRAMASTAT_SMOKE_ONLY=nonlinear-inverse python tramastat.py --smoke DIR
            from analisi.nonlinear_inverse_smoke import check_nonlinear_inverse
            check_nonlinear_inverse(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
                capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog,
                errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "spline":
            # The 0.54 spline/LOWESS check alone: TRAMASTAT_SMOKE_ONLY=spline python tramastat.py --smoke DIR
            from analisi.spline_smoke import check_spline_fit
            check_spline_fit(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "curve-pipeline":
            # The 0.93 Curve pipeline check alone: TRAMASTAT_SMOKE_ONLY=curve-pipeline python tramastat.py --smoke DIR
            from analisi.curve_pipeline_smoke import check_curve_pipeline
            check_curve_pipeline(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "letters":
            # The 0.57 compact letter display check alone: TRAMASTAT_SMOKE_ONLY=letters python tramastat.py --smoke DIR
            from analisi.letters_smoke import check_compact_letters
            check_compact_letters(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, PairwiseDialog=PairwiseDialog, capture=capture,
                drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "exact-rank-tests":
            # The 0.60 exact Mann–Whitney and Wilcoxon check alone:
            # TRAMASTAT_SMOKE_ONLY=exact-rank-tests python tramastat.py --smoke DIR
            from analisi.exact_rank_smoke import check_exact_rank_tests
            check_exact_rank_tests(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
                select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "transpose":
            # The 0.57 Transpose X and Y check alone: TRAMASTAT_SMOKE_ONLY=transpose python tramastat.py --smoke DIR
            from analisi.transpose_smoke import check_transpose_xy
            check_transpose_xy(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
                select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pdf-bundle":
            # The 0.58 multi-page PDF check alone: TRAMASTAT_SMOKE_ONLY=pdf-bundle python tramastat.py --smoke DIR
            from analisi.pdf_bundle_smoke import check_pdf_bundle
            check_pdf_bundle(root, app, directory, SimpleNamespace(
                capture=capture, wait_for_calculation=wait_for_calculation, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "graph-annotations":
            from analisi.graph_annotation_smoke import check_graph_annotations
            check_graph_annotations(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "imported-shapes":
            # Requires an actual legacy fixture; never report a skipped import as a pass.
            assert legacy_reference is not None and (legacy_reference / "438.pzf").is_file()
            check_old_legacy_xy(legacy_reference)
            assert (directory / "imported-shape-refusal.txt").is_file()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "shape-arrange":
            from analisi.shape_arrange_smoke import check_shape_arrange
            check_shape_arrange(SimpleNamespace(app=app, root=root, directory=directory, capture=capture,
                drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
                filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pattern-color":
            from analisi.shape_pattern_color_smoke import check_shape_pattern_color
            check_shape_pattern_color(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "shape-clipboard":
            from analisi.shape_clipboard_smoke import check_shape_clipboard
            check_shape_clipboard(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog,
                put_clipboard=put_clipboard, get_clipboard=get_clipboard,
                drive_dialog=drive_dialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "shape-context":
            from analisi.shape_context_smoke import check_shape_context
            check_shape_context(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "shape-editor-pages":
            from analisi.shape_editor_pages_smoke import check_shape_editor_pages
            check_shape_editor_pages(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "line-caps":
            from analisi.line_caps_smoke import check_line_caps
            check_line_caps(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "canvas-shapes":
            from analisi.shape_canvas_smoke import check_shape_canvas
            check_shape_canvas(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "shape-options":
            from analisi.shape_options_smoke import check_shape_options
            check_shape_options(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "axis-guides":
            from analisi.axis_guides_smoke import check_axis_guides
            check_axis_guides(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog,
                LayoutDialog=LayoutDialog, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "axis-breaks":
            # The XY axis breaks check alone: TRAMASTAT_SMOKE_ONLY=axis-breaks python tramastat.py --smoke DIR
            from analisi.axis_breaks_smoke import check_axis_breaks
            check_axis_breaks(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog,
                LayoutDialog=LayoutDialog, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "legend-formatting":
            from analisi.legend_formatting_smoke import check_legend_formatting
            check_legend_formatting(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog,
                LayoutDialog=LayoutDialog, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "graph-shapes":
            # The 0.61 native shapes check alone: TRAMASTAT_SMOKE_ONLY=graph-shapes python tramastat.py --smoke DIR
            from analisi.graph_shape_smoke import check_graph_shapes
            check_graph_shapes(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
                wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "layout-svg":
            # The 0.59 vector layout SVG check alone: TRAMASTAT_SMOKE_ONLY=layout-svg python tramastat.py --smoke DIR
            from analisi.layout_svg_smoke import check_layout_svg
            check_layout_svg(SimpleNamespace(
                app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
                select_columns=select_columns, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
                filedialog=filedialog, LayoutDialog=LayoutDialog, AnalysisDialog=AnalysisDialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "figure-export":
            # The 0.57 export check alone: TRAMASTAT_SMOKE_ONLY=figure-export python tramastat.py --smoke DIR
            from analisi.figure_export_smoke import check_figure_export
            check_figure_export(root, app, directory, SimpleNamespace(
                capture=capture, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
                messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "nonlinear-weighting":
            # The 0.60 observed-Y weighting check alone: TRAMASTAT_SMOKE_ONLY=nonlinear-weighting python tramastat.py --smoke DIR
            check_nonlinear_weighting_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "nonlinear-bands":
            # The 0.61 nonlinear bands check alone: TRAMASTAT_SMOKE_ONLY=nonlinear-bands python tramastat.py --smoke DIR
            check_nonlinear_bands_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "custom-equation":
            # The 0.61 custom equation check alone: TRAMASTAT_SMOKE_ONLY=custom-equation python tramastat.py --smoke DIR
            check_custom_equation_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "piecewise-equations":
            # The 0.81 conditional equations check alone (window = screen size, theme from the preferences):
            # TRAMASTAT_SMOKE_ONLY=piecewise-equations python tramastat.py --smoke DIR
            check_piecewise_equations_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "global-custom":
            # The global custom equation check alone: TRAMASTAT_SMOKE_ONLY=global-custom python tramastat.py --smoke DIR
            check_global_custom_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "global-uncertainty":
            # The 0.70 response bands and predictions check alone:
            # TRAMASTAT_SMOKE_ONLY=global-uncertainty python tramastat.py --smoke DIR
            check_global_uncertainty_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "global-irls":
            # The 0.60 global weights check alone: TRAMASTAT_SMOKE_ONLY=global-irls python tramastat.py --smoke DIR
            check_global_irls_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "heatmap-colors":
            # The 0.72 heat-map colors and legends check alone: TRAMASTAT_SMOKE_ONLY=heatmap-colors python tramastat.py --smoke DIR
            check_heat_map_colors_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "heatmap-number-format":
            # The heat-map legend number format check alone:
            # TRAMASTAT_SMOKE_ONLY=heatmap-number-format python tramastat.py --smoke DIR
            check_heat_map_number_format_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "heatmap-cell-labels":
            # The heat-map cell value label check alone:
            # TRAMASTAT_SMOKE_ONLY=heatmap-cell-labels python tramastat.py --smoke DIR
            check_heat_map_cell_labels_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "heatmap-layout":
            # The heat-map gaps and axis layout check alone:
            # TRAMASTAT_SMOKE_ONLY=heatmap-layout python tramastat.py --smoke DIR
            check_heat_map_layout_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "summary-ttest":
            check_summary_ttest_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "summary-anova":
            check_summary_anova_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "lognormality":
            check_lognormality_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "lognormal-anova":
            # Lognormal one-way ANOVA alone:
            # TRAMASTAT_SMOKE_ONLY=lognormal-anova python tramastat.py --smoke DIR
            check_lognormal_anova_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "qq-panels":
            # TRAMASTAT_SMOKE_ONLY=qq-panels python tramastat.py --smoke DIR
            check_qq_panels_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "qq-artist-styles":
            # TRAMASTAT_SMOKE_ONLY=qq-artist-styles python tramastat.py --smoke DIR
            check_qq_artist_styles_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "mean-permutation":
            # The permutation test alone: TRAMASTAT_SMOKE_ONLY=mean-permutation python tramastat.py --smoke DIR
            check_mean_permutation_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "spearman-extended":
            check_spearman_extended_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "cohen-kappa":
            # The Cohen's kappa check alone: TRAMASTAT_SMOKE_ONLY=cohen-kappa python tramastat.py --smoke DIR
            check_cohen_kappa_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "correlation-details":
            # Detailed correlation, control and independent correlations:
            # TRAMASTAT_SMOKE_ONLY=correlation-details python tramastat.py --smoke DIR
            check_correlation_details_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "grouped-distributions":
            # The grouped box and violin plots check alone: TRAMASTAT_SMOKE_ONLY=grouped-distributions python tramastat.py --smoke DIR
            check_grouped_distributions_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "equivalence":
            # The 0.71 Equivalence test (TOST) check alone: TRAMASTAT_SMOKE_ONLY=equivalence python tramastat.py --smoke DIR
            check_equivalence_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") in {"competing-risks", "independent-roc"}:
            if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "competing-risks":
                check_competing_risks_smoke()
            else:
                check_independent_roc_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "tolerance-intervals":
            # The 0.93 Tolerance intervals check alone: TRAMASTAT_SMOKE_ONLY=tolerance-intervals python tramastat.py --smoke DIR
            check_tolerance_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "nb2-regression":
            # The 0.93 Negative binomial regression check alone:
            # TRAMASTAT_SMOKE_ONLY=nb2-regression python tramastat.py --smoke DIR
            check_nb2_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "rmcorr":
            # The Repeated-measures correlation check alone: TRAMASTAT_SMOKE_ONLY=rmcorr python tramastat.py --smoke DIR
            check_rmcorr_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "meta-analysis":
            # The Meta-analysis check alone: TRAMASTAT_SMOKE_ONLY=meta-analysis python tramastat.py --smoke DIR
            check_meta_analysis_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "paired-proportions":
            # The Paired proportions (McNemar) check alone: TRAMASTAT_SMOKE_ONLY=paired-proportions python tramastat.py --smoke DIR
            check_paired_proportions_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "weibull-aft":
            # The Weibull AFT regression check alone: TRAMASTAT_SMOKE_ONLY=weibull-aft python tramastat.py --smoke DIR
            check_weibull_aft_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "ordinal-logit":
            # The Ordinal logistic regression check alone: TRAMASTAT_SMOKE_ONLY=ordinal-logit python tramastat.py --smoke DIR
            check_ordinal_logit_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "rmst":
            # The Restricted mean survival time check alone: TRAMASTAT_SMOKE_ONLY=rmst python tramastat.py --smoke DIR
            check_rmst_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") in {"robust-curve", "reference-normalization"}:
            if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "robust-curve":
                check_robust_curve_smoke()
            else:
                check_reference_normalization_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "lognormal-tests":
            # The 0.70 lognormal t-test check alone: TRAMASTAT_SMOKE_ONLY=lognormal-tests python tramastat.py --smoke DIR
            check_lognormal_tests_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pairwise":
            # The 0.56 pairwise comparisons check alone: TRAMASTAT_SMOKE_ONLY=pairwise python tramastat.py --smoke DIR
            from analisi.pairwise_smoke import check_pairwise_comparisons
            check_pairwise_comparisons(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, PairwiseDialog=PairwiseDialog, capture=capture,
                drive_dialog=drive_dialog, pick_method=pick_method, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "monte-carlo":
            # The Monte Carlo check alone: TRAMASTAT_SMOKE_ONLY=monte-carlo python tramastat.py --smoke DIR
            from analisi.monte_carlo_smoke import check_monte_carlo_study
            check_monte_carlo_study(root, app, directory, SimpleNamespace(
                CalculationControl=CalculationControl, AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
                wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "mlr-weighting":
            # The 0.70 Gaussian weights of Multiple regression alone:
            # TRAMASTAT_SMOKE_ONLY=mlr-weighting python tramastat.py --smoke DIR
            check_mlr_weighting_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "anova-selected-terms":
            # The multifactor ANOVA selected-terms check alone:
            # TRAMASTAT_SMOKE_ONLY=anova-selected-terms python tramastat.py --smoke DIR
            from analisi.anova_terms_smoke import check_anova_selected_terms
            check_anova_selected_terms(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "anova-ss-types":
            # The multifactor ANOVA sums of squares check alone:
            # TRAMASTAT_SMOKE_ONLY=anova-ss-types python tramastat.py --smoke DIR
            from analisi.anova_ss_smoke import check_anova_ss_types
            check_anova_ss_types(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "rm-two-way-sphericity":
            # The Greenhouse–Geisser correction of two within-subject factors alone:
            # TRAMASTAT_SMOKE_ONLY=rm-two-way-sphericity python tramastat.py --smoke DIR
            from analisi.rm_sphericity_smoke import check_rm_two_way_sphericity
            check_rm_two_way_sphericity(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "confidence-overlays":
            check_confidence_overlays()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "anova-diagnostics":
            # The multifactor ANOVA residual-diagnostics check alone:
            # TRAMASTAT_SMOKE_ONLY=anova-diagnostics python tramastat.py --smoke DIR
            from analisi.anova_diagnostics_smoke import check_anova_diagnostics
            check_anova_diagnostics(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "ols-diagnostics":
            # The 0.59 multiple linear diagnostics check alone:
            # TRAMASTAT_SMOKE_ONLY=ols-diagnostics python tramastat.py --smoke DIR
            from analisi.ols_smoke import check_ols_diagnostics
            check_ols_diagnostics(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "logistic-profiles":
            # The logistic diagnostics check alone:
            # TRAMASTAT_SMOKE_ONLY=logistic-profiles python tramastat.py --smoke DIR
            from analisi.logistic_smoke import check_logistic_profiles
            check_logistic_profiles(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pca-import":
            from analisi.legacy_pca_smoke import check_restored_pca
            check_restored_pca(root, app, directory, capture, wait_for_calculation)
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "categorical-scatter-import":
            from analisi.legacy_mv_scatter_smoke import check_saved_scatter
            check_saved_scatter(root, app, directory, capture, wait_for_calculation)
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pca-graphs":
            # The PCA graph check alone:
            # TRAMASTAT_SMOKE_ONLY=pca-graphs python tramastat.py --smoke DIR
            from analisi.pca_graphs_smoke import check_pca_graphs
            check_pca_graphs(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pca-selection":
            # The PCA selection check alone:
            # TRAMASTAT_SMOKE_ONLY=pca-selection python tramastat.py --smoke DIR
            from analisi.pca_selection_smoke import check_pca_selection
            check_pca_selection(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
                AnalysisDialog=AnalysisDialog, GraphFormatDialog=GraphFormatDialog,
                messagebox=messagebox, filedialog=filedialog, errors=errors,
                screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "pca-regression":
            # The principal component regression check alone:
            # TRAMASTAT_SMOKE_ONLY=pca-regression python tramastat.py --smoke DIR
            from analisi.pca_regression_smoke import check_pca_regression
            check_pca_regression(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, AnalysisDialog=AnalysisDialog,
                messagebox=messagebox, filedialog=filedialog, errors=errors,
                screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "ancova":
            # The ANCOVA check alone: TRAMASTAT_SMOKE_ONLY=ancova python tramastat.py --smoke DIR
            from analisi.ancova_smoke import check_ancova
            check_ancova(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, AnalysisDialog=AnalysisDialog,
                messagebox=messagebox, filedialog=filedialog, errors=errors,
                screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "variance-assumptions":
            # The one-way variance check alone:
            # TRAMASTAT_SMOKE_ONLY=variance-assumptions python tramastat.py --smoke DIR
            from analisi.variance_assumptions_smoke import check_variance_assumptions
            check_variance_assumptions(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "fdr-control":
            # The false-discovery check alone:
            # TRAMASTAT_SMOKE_ONLY=fdr-control python tramastat.py --smoke DIR
            from analisi.fdr_control_smoke import check_fdr_control
            check_fdr_control(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "binomial-goodness":
            # The 0.93 exact binomial test of Compare observed distribution with expected, alone:
            # TRAMASTAT_SMOKE_ONLY=binomial-goodness python tramastat.py --smoke DIR
            check_binomial_goodness_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "variance-ratio":
            # The two-sample variance comparison alone:
            # TRAMASTAT_SMOKE_ONLY=variance-ratio python tramastat.py --smoke DIR
            from analisi.variance_ratio_smoke import check_variance_ratio
            check_variance_ratio(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "anova-trend":
            # The ordinal ANOVA trend check alone:
            # TRAMASTAT_SMOKE_ONLY=anova-trend python tramastat.py --smoke DIR
            from analisi.trend_anova_smoke import check_anova_trend
            check_anova_trend(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "fit-quality":
            # The nonlinear fit-quality check alone:
            # TRAMASTAT_SMOKE_ONLY=fit-quality python tramastat.py --smoke DIR
            from analisi.fit_quality_smoke import check_fit_quality
            check_fit_quality(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method, select_columns=select_columns,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") in {"parts-styles", "composition-styles"}:
            # The composition slice-style check alone:
            # TRAMASTAT_SMOKE_ONLY=composition-styles python tramastat.py --smoke DIR
            from analisi.parts_style_smoke import check_parts_segment_styles
            check_parts_segment_styles(root, app, directory, SimpleNamespace(
                capture=capture, pick_method=pick_method,
                drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
                wait_for_calculation=wait_for_calculation))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "xy-formatting":
            # The XY series formatting check alone:
            # TRAMASTAT_SMOKE_ONLY=xy-formatting python tramastat.py --smoke DIR
            from analisi.xy_format_smoke import check_xy_formatting
            check_xy_formatting(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture,
                drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
                pick_method=pick_method, save_project=save_project, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "xy-errors":
            # The XY error bars check alone:
            # TRAMASTAT_SMOKE_ONLY=xy-errors python tramastat.py --smoke DIR
            from analisi.xy_error_smoke import check_xy_errors
            check_xy_errors(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture,
                drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
                pick_method=pick_method, save_project=save_project, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "xy-mixed":
            # Bars, steps, lines and points on one XY graph alone:
            # TRAMASTAT_SMOKE_ONLY=xy-mixed python tramastat.py --smoke DIR
            from analisi.xy_mixed_smoke import check_xy_mixed
            check_xy_mixed(root, app, directory, SimpleNamespace(
                AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, Dataset=Dataset, capture=capture,
                drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
                pick_method=pick_method, save_project=save_project, select_columns=select_columns,
                wait_for_calculation=wait_for_calculation, errors=errors))
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "worksheet-clipboard":
            check_workspace_setup()
            check_data_grid()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "worksheet-statistics":
            check_worksheet_statistics()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "linked-grouped-anova":
            from analisi.grouped_anova_smoke import check_linked_grouped_anova
            check_linked_grouped_anova(root, app, directory, capture, wait_for_calculation)
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "distribution-formulas":
            check_distribution_formulas_smoke()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "kmeans-reports":
            check_kmeans_reports()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "hartigan-wong":
            check_hartigan_wong()
            check_macqueen()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "kmeans-consensus":
            check_kmeans_consensus()
            assert not errors, errors
            (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
            app.worker.shutdown(wait=False)
            root.after(1500, root.destroy)
            return
        check_workspace_setup()
        path = directory / "fixture.csv"
        path.write_text("x,y\n1,3\n2,5\n3,7\n4,9\n5,11\n", encoding="utf-8")
        app.import_file(path)
        app.tables["fixture"].set_formula("doubled", "=x*2")
        app.invalidate()
        drive_formula_editor(root, "MEAN(y) WHERE x <= 2", errors)
        with patch.object(simpledialog, "askstring", return_value="Lower-range mean"):
            app.add_formula()
        assert app.tables["fixture"].frame()["Lower-range mean"].eq(4).all()
        app.edit_cell(0, 0, "1.5")
        assert app.tables["fixture"].frame()["doubled"].iloc[0] == 3
        app.edit_cell(1, 0, "2.5")
        assert app.tables["fixture"].frame()["Lower-range mean"].eq(3).all()
        app.edit_cell(1, 0, "2")
        app.edit_cell(0, 0, "1")
        app.current_grid.active_cell = (0, 0)
        app.toggle_exclusion()
        assert pd.isna(app.tables["fixture"].frame(mask_excluded=True).iloc[0, 0])
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "masked.csv")):
            app.export()
        assert pd.isna(load_tables(directory / "masked.csv")["masked"].iloc[0, 0])
        app.current_grid.active_cell = (0, 0)
        app.toggle_exclusion()
        root.update()
        capture(root, "window-data.png")

        def pick_linear(dialog):
            pick_method(dialog, "Linear regression")
            dialog.controls["X"][1].set("x")
            dialog.controls["Y"][1].set("y")
            dialog.update_idletasks()
            capture(dialog, "window-analysis.png")

        drive_dialog(AnalysisDialog, pick_linear)
        app.choose_analysis()
        wait_for_calculation()
        assert app.runs[0].result.tables["Regression"].loc["Slope", "Value"] == 2
        app.show("graph", 0)

        def format_graph(dialog):
            dialog.inputs["title"].set("Dose and response")
            dialog.grid_lines.set(True)
            for key, value in {"min": "0", "max": "6", "step": "2"}.items():
                dialog.axis_fields["x"][key].set(value)
            dialog.series_fields["color"].set("#176676")
            dialog.series_fields["width"].set("2")
            dialog.references.insert("1.0", "Y, 6, Target")
            dialog.notebook.select(1)
            capture(dialog, "window-axis-format.png")

        drive_dialog(GraphFormatDialog, format_graph)
        app.format_graph()
        assert app.runs[0].result.figure.axes[0].get_title() == "Dose and response"
        frame = app.tables["fixture"].frame(mask_excluded=True)
        app.add_result(Run("Histogram", "fixture", {"Response": "y", "Bins": 3}),
                       analyse("Histogram", frame, {"Response": "y", "Bins": 3}))

        def choose_panels(dialog):
            dialog.name.set("Figure 1")
            dialog.list.selection_set(0, 1)
            dialog.add_selected()

        drive_dialog(LayoutDialog, choose_panels)
        app.new_layout()
        assert len(app.layout_figure.axes) == 2
        app.path = directory / "fixture.alab"
        assert app.save()
        app.import_file(app.path)
        assert app.tables["fixture"].frame()["doubled"].iloc[0] == 2
        assert app.tables["fixture"].frame()["Lower-range mean"].eq(4).all()
        assert len(app.runs) == 2 and len(app.layouts) == 1
        app.open_gallery("Graphs")
        assert len(app.gallery.cards) == 2 and app.gallery.rendered_previews == 0
        assert all(run.result is None for run in app.runs)
        app.toggle_gallery()
        app.show("layout", 0)
        app.recalculate_layout(0)
        wait_for_calculation()
        axes = app.runs[0].result.figure.axes[0]
        assert axes.get_title() == "Dose and response"
        assert axes.get_xlim() == (0, 6)
        assert app.runs[0].style["reference_lines"][0]["label"] == "Target"
        assert app.runs[0].style["series"]
        assert len(app.layout_figure.axes) == 2
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "layout.pdf")):
            app.export()
        assert (directory / "layout.pdf").read_bytes().startswith(b"%PDF")
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "layout.svg")):
            app.export()
        assert b"<svg " in (directory / "layout.svg").read_bytes()
        root.update()
        capture(root, "window-layout.png")

        # Both Navigator modes reach the same sheets. Searching for an
        # analysis keeps its source table visible in the combined tree.
        combined = "section:Data + Results"
        result_ref = ("result", 0)
        app.set_combined_navigator(True)
        source = next(node for node in app.nav.get_children(combined)
                      if app.nodes.get(node) == ("data", "fixture"))
        assert any(app.nodes.get(node) == result_ref for node in app.nav.get_children(source))
        app.nav.item(source, open=False)
        app.search.set("linear regression")
        source = next(node for node in app.nav.get_children(combined)
                      if app.nodes.get(node) == ("data", "fixture"))
        assert app.nav.item(source, "open")
        assert [app.nodes[node] for node in app.nav.get_children(source)] == [result_ref]
        found = [app.nodes[node] for node in app.nav.get_children("section:Search results")]
        assert result_ref in found
        app.search.set("")
        source = next(node for node in app.nav.get_children(combined)
                      if app.nodes.get(node) == ("data", "fixture"))
        assert not app.nav.item(source, "open")
        app.nav.item(source, open=True)
        app.open_sheet(("data", "fixture"))
        capture(root, "window-combined-navigator.png")
        original_grid = app.current_grid
        original_grid.select((1, 1))
        history = tuple(app.history)
        app.nav.see("section:Graphs")
        root.update()
        left, top, width, height = app.nav.bbox("section:Graphs")
        app.nav.event_generate("<ButtonRelease-1>", x=left + min(70, width - 1), y=top + height // 2)
        assert app.gallery is not None and tuple(app.history) == history
        assert len(app.gallery.cards) == 2 and app.gallery.rendered_previews == 2
        gallery = app.gallery
        app.search.set("fixture")
        root.update()
        assert app.gallery is gallery
        app.search.set("")
        root.update()
        app.toggle_gallery()
        assert app.current_grid is original_grid and app.current_grid.active_cell == (1, 1)
        app.open_gallery("Graphs")
        app.gallery.cards[0].invoke()
        assert app.gallery is None and app.selected == ("graph", 0)
        app.toggle_gallery()
        assert app.gallery is not None
        app.toggle_gallery()
        assert app.gallery is None and app.selected == ("graph", 0)
        app.set_combined_navigator(False)
        assert any(app.nodes.get(node) == result_ref for node in app.nav.get_children("section:Results"))
        app.set_combined_navigator(True)

        app.show("data", "fixture")
        app.edit_cell(4, 1, "13")
        wait_for_calculation()
        assert app.runs[0].result.tables["Regression"].loc["Slope", "Value"] > 2
        app.show("graph", 0)
        root.update()
        capture(root, "window-graph.png")
        offsets = np.array([1, -4, 7, 2, -2, 3, -5, 2.])
        sequence = np.arange(len(offsets))
        measurements = pd.DataFrame({"Subject ID": [f"S{i}" for i in sequence],
                                     "Baseline": 10 + offsets + .6 * np.sin(sequence),
                                     "Week 1": 13 + offsets + .8 * np.cos(sequence),
                                     "Week 2": 16 + offsets + .5 * np.cos(1.4 * sequence)})
        measurements.loc[2, "Week 1"] = np.nan
        app._add_tables({"Follow-up": measurements})

        def pick_mixed(dialog):
            pick_method(dialog, "Mixed-effects model (REML)")
            dialog.controls["Input format"][1].set("Wide repeated measures")
            dialog.controls["Subject"][1].set("Subject ID")
            dialog.controls["Post-hoc"][1].set("Holm")
            dialog.controls["Denominator method"][1].set("Kenward–Roger")
            select_columns(dialog, "Measurement columns", {"Baseline", "Week 1", "Week 2"})

        drive_dialog(AnalysisDialog, pick_mixed)
        app.choose_analysis()
        wait_for_calculation()
        mixed_run = app.runs[-1]
        assert mixed_run.result.tables["Model"]["Subjects used"].iloc[0] == 8
        assert mixed_run.result.tables["Model"]["Subjects partial"].iloc[0] == 1
        assert mixed_run.result.tables["Model"]["Denominator df"].iloc[0] == "Kenward–Roger"
        assert np.isfinite(mixed_run.result.tables["Fixed effects"]["F scaling"]).all()
        app.show("graph", len(app.runs) - 1)
        root.update()
        capture(root, "window-mixed.png")

        dose = np.geomspace(.1, 100, 20)
        noise = np.sin(np.arange(len(dose))) * .1
        curves = pd.DataFrame({"Dose": dose, "Control": 2 + 30 / (1 + (4 / dose)**1.3) + noise,
                              "Treated": 1.8 + 30.2 / (1 + (12 / dose)**1.3) - noise})
        app._add_tables({"Dose response": curves})

        def pick_global(dialog):
            pick_method(dialog, "Global nonlinear regression")
            dialog.controls["Input format"][1].set("Wide XY")
            dialog.controls["X"][1].set("Dose")
            select_columns(dialog, "Y columns", {"Control", "Treated"})
            dialog.controls["Model"][1].set("Stimulation (variable slope)")
            for parameter in ("Top", "Hill slope"):
                dialog.parameters.rows[parameter][0].set("Shared")
            dialog.parameters.rows["EC50"][-1].set(True)
            dialog.controls["Show confidence bands"][1].set(True)
            panel = dialog.series_parameters
            dialog.fields.select(panel)
            dialog.refresh_series_tab()
            assert panel.labels == ["Control", "Treated"]
            panel.rows["Bottom"]["fixed"].set("2")
            panel.choices.current(1)
            panel.choices.event_generate("<<ComboboxSelected>>")
            panel.rows["Bottom"]["fixed"].set("1,8")
            for name, value in {"lower": "4", "upper": "16", "initial": "10"}.items():
                panel.rows["EC50"][name].set(value)
            capture(dialog, "window-series.png")

        drive_dialog(AnalysisDialog, pick_global)
        app.choose_analysis()
        wait_for_calculation()
        joint_run = app.runs[-1]
        assert joint_run.options["Shared parameters"] == ["Top", "Hill slope"]
        applied = joint_run.result.tables["Series constraints"]
        assert applied["Fixed value"].dropna().tolist() == [2, 1.8]
        assert joint_run.result.tables["Selected parameter comparison"].loc["p", "Value"] < .001
        app.show("graph", len(app.runs) - 1)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "global-fit.svg")):
            app.export()
        assert b"<svg " in (directory / "global-fit.svg").read_bytes()
        root.update()
        capture(root, "window-global.png")
        app.open_gallery("Graphs")
        assert len(app.gallery.cards) == app.gallery.rendered_previews == 4
        capture(root, "window-graph-gallery.png")
        geometry, divider = root.geometry(), app.workspace.sashpos(0)
        root.geometry("820x570")
        root.update()
        app.workspace.sashpos(0, 490)
        root.update()
        assert app.gallery.columns == 1 and len(app.gallery.cards) == 2
        app.gallery.next_button.invoke()
        assert app.gallery.page == 1 and app.gallery.rendered_previews == 2
        root.geometry(geometry)
        root.update()
        app.workspace.sashpos(0, divider)
        root.update()
        app.toggle_gallery()

        assert app.save()
        app.import_file(app.path)
        restored = next(run for run in app.runs if run.method == "Global nonlinear regression")
        assert restored.options == joint_run.options
        restored_index = app.runs.index(restored)
        app.show("result", restored_index)
        app.recalculate(restored_index)
        wait_for_calculation()
        assert restored.result.tables["Joint fit"].loc["Free parameters", "Value"] == 4
        assert restored.result.tables["Series constraints"].equals(applied)

        app.show("data", "Dose response")

        def pick_classic(dialog):
            pick_method(dialog, "Nonlinear regression")
            dialog.controls["X"][1].set("Dose")
            dialog.controls["Model"][1].set("Stimulation (variable slope)")
            select_columns(dialog, "Y columns", {"Control", "Treated"})

        drive_dialog(AnalysisDialog, pick_classic)
        app.choose_analysis()
        wait_for_calculation()
        classic_run = app.runs[-1]
        assert classic_run.result.tables["Parameters"]["Response variable"].unique().tolist() == ["Control", "Treated"]
        app.show("graph", len(app.runs) - 1)
        capture(root, "window-classic.png")

        prepared = directory / "summary.pzt"
        prepared.write_text(
            '<GraphPadPrismFile><Table ID="Source" TableType="XY" XFormat="numbers" YFormat="SD">'
            '<Title>Prepared error bars</Title><XColumn><Title>Hours</Title>'
            '<Subcolumn><d>1</d><d>2</d><d>3</d></Subcolumn></XColumn><YColumn><Title>Signal</Title>'
            '<Subcolumn><d>4</d><d>6</d><d>8</d></Subcolumn><Subcolumn><d>1</d><d>1</d><d>2</d></Subcolumn>'
            '</YColumn></Table></GraphPadPrismFile>', encoding="utf-8")
        app.import_file(prepared)
        assert list(app.tables["Prepared error bars"].raw) == ["Hours", "Signal [Mean]", "Signal [SD]"]

        def pick_errors(dialog):
            pick_method(dialog, "XY error bars")
            for name, value in {"X": "Hours", "Y": "Signal [Mean]", "Y lower error": "Signal [SD]"}.items():
                dialog.controls[name][1].set(value)

        drive_dialog(AnalysisDialog, pick_errors)
        app.choose_analysis()
        wait_for_calculation()
        error_graph = app.runs[-1].result.figure.axes[0]
        assert error_graph.containers[0].has_yerr
        app.show("graph", len(app.runs) - 1)
        capture(root, "window-summary-errors.png")

        x = np.linspace(-11., -4., 65)
        response = 4. + 90. / (1. + (2**(1 / 1.5) - 1) * 10**((-7.8 - x) * 1.3))**1.5
        app._add_tables({"Asymmetric response": pd.DataFrame({"Log dose": x, "Signal": response})})

        def pick_asymmetric(dialog):
            pick_method(dialog, "Nonlinear regression")
            dialog.controls["X"][1].set("Log dose")
            select_columns(dialog, "Y columns", {"Signal"})
            model = dialog.controls["Model"][1]

            def find_equation(picker):
                picker.search.set("Asymmetric dose-response (log10 X)")
                assert picker.selected_model() == "Asymmetric dose-response (log10 X)"
                capture(picker, "window-equation-picker.png")

            drive_dialog(EquationDialog, find_equation)
            dialog.choose_equation(dialog.controls["Model"][0], model)

        drive_dialog(AnalysisDialog, pick_asymmetric)
        app.choose_analysis()
        wait_for_calculation()
        fit = app.runs[-1].result.tables["Parameters: All"]["Estimate"]
        np.testing.assert_allclose(fit[["Log EC50", "Hill slope", "Asymmetry"]], [-7.8, 1.3, 1.5], rtol=1e-5)

        check_kmeans_consensus()
        check_hartigan_wong()
        check_macqueen()
        check_kmeans_reports()

        source = directory / "saved-graph.prism"
        with ZipFile(source, "w") as archive:
            def write(path, record):
                archive.writestr(path, json.dumps(record))

            write("document.json", {"sheets": {"data": ["sheet"], "graphs": ["graph"]}})
            write("data/sheets/sheet/sheet.json", {"title": "Imported data", "table": {
                "uid": "table", "format": "xy", "dataFormat": "y_single", "xDataSet": "x", "dataSets": ["y"]}})
            write("data/sets/x.json", {"title": "Time"})
            write("data/sets/y.json", {"title": "Control"})
            archive.writestr("data/tables/table/data.csv", "1,4\n2,6\n3,7\n")
            write("graphs/graph/sheet.json", {"title": "Original imported XY", "inputDataSets": ["y"]})
        app.import_file(source)
        assert app.save()
        app.import_file(app.path)
        saved = next(i for i, run in enumerate(app.runs) if run.method == SAVED_XY)
        node = next(node for node, ref in app.nodes.items() if ref == ("graph", saved))
        app.nav.selection_set(node)
        app.navigate()
        wait_for_calculation()
        restored_graph = app.runs[saved].result.figure.axes[0]
        assert restored_graph.get_title() == "Original imported XY"
        assert app.selected == ("graph", saved)
        np.testing.assert_equal(restored_graph.collections[0].get_offsets().data.tolist(), [[1, 4], [2, 6], [3, 7]])
        capture(root, "window-restored-xy.png")

        check_data_grid()
        check_worksheet_edits()
        check_worksheet_statistics()
        check_distribution_formulas_smoke()
        check_paste_special()
        check_text_import()
        if legacy_reference is not None:
            if (legacy_reference / "plos-s2.pzf").is_file():
                check_binary_views(legacy_reference)
            if sys.platform == "win32":
                check_preserved_legacy_graphs(legacy_reference)
            grouped_sample = legacy_reference.parent / "Grouped-1944.pzf"
            if grouped_sample.is_file():
                check_grouped_pzf(grouped_sample)
        check_info_workflow(legacy_reference)
        if legacy_reference is not None:
            check_old_legacy_xy(legacy_reference)
        check_data_processing()
        check_hierarchical_workflow()
        check_confidence_overlays()
        check_multiple_variable_processing()
        check_project_tabs()
        check_category_graphs(legacy_reference)
        check_grouped_summaries_and_stacks()
        check_roc_workflow()
        check_auc_peaks()
        check_survival_workflow()
        check_contingency_workflow()
        check_contingency_intervals_workflow()
        check_baptista_pike_workflow()
        check_nested_workflow(legacy_reference)
        check_parts_of_whole()
        check_frequency_distribution()
        check_correlation_matrix()
        check_heat_map()
        check_heat_map_colors_smoke()
        check_heat_map_number_format_smoke()
        check_heat_map_cell_labels_smoke()
        check_heat_map_layout_smoke()
        check_row_tests()
        check_normality_qq()
        check_friedman_exact()
        check_bland_altman_agreement()
        check_anova_effect_sizes()
        check_poisson_exposure()
        check_compare_lines()
        check_cox_outputs()
        check_cox_exact_ties_smoke()
        check_cox_fit_diagnostics()
        check_bubble_plot()
        check_paired_graphs()
        check_forest_plot()
        from types import SimpleNamespace
        from analisi.smoke_replicate_baseline import check_replicate_baseline

        check_replicate_baseline(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.transpose_smoke import check_transpose_xy

        check_transpose_xy(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        check_unequal_anova(SimpleNamespace(
            app=app, root=root, directory=directory, dialog_type=AnalysisDialog, drive_dialog=drive_dialog,
            pick_method=pick_method, wait=wait_for_calculation, capture=capture,
            save_project=save_project, Dataset=Dataset))

        from analisi.outlier_smoke import check_outlier_screening
        check_outlier_screening(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            select_columns=select_columns, wait_for_calculation=wait_for_calculation, messagebox=messagebox,
            filedialog=filedialog))
        from analisi.monte_carlo_smoke import check_monte_carlo_study
        check_monte_carlo_study(root, app, directory, SimpleNamespace(
            CalculationControl=CalculationControl, AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.plot_function_smoke import check_plot_function
        check_plot_function(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.power_plan_smoke import check_power_plan
        check_power_plan(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.model_selection_smoke import check_model_selection
        check_model_selection(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.calibration_prediction_smoke import check_calibration_prediction
        check_calibration_prediction(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.calibration_053_smoke import check_calibration_intervals
        check_calibration_intervals(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.nonlinear_inverse_smoke import check_nonlinear_inverse
        check_nonlinear_inverse(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, GraphFormatDialog=GraphFormatDialog,
            capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog,
            errors=errors))
        from analisi.spline_smoke import check_spline_fit
        check_spline_fit(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog))
        from analisi.curve_pipeline_smoke import check_curve_pipeline
        check_curve_pipeline(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, drive_dialog=drive_dialog, pick_method=pick_method,
            wait_for_calculation=wait_for_calculation, messagebox=messagebox, filedialog=filedialog, errors=errors))
        from analisi.pairwise_smoke import check_pairwise_comparisons
        check_pairwise_comparisons(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, PairwiseDialog=PairwiseDialog, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, wait_for_calculation=wait_for_calculation))
        from analisi.letters_smoke import check_compact_letters
        check_compact_letters(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, PairwiseDialog=PairwiseDialog, capture=capture, drive_dialog=drive_dialog,
            pick_method=pick_method, select_columns=select_columns, wait_for_calculation=wait_for_calculation,
            filedialog=filedialog))
        check_lognormal_tests_smoke()
        check_equivalence_smoke()
        check_independent_roc_smoke()
        check_paired_proportions_smoke()
        check_tolerance_smoke()
        check_lognormality_smoke()
        check_lognormal_anova_smoke()
        check_summary_anova_smoke()
        check_summary_ttest_smoke()
        check_mean_permutation_smoke()
        check_qq_panels_smoke()
        check_qq_artist_styles_smoke()
        check_correlation_details_smoke()
        check_spearman_extended_smoke()
        check_robust_curve_smoke()
        check_cohen_kappa_smoke()
        check_competing_risks_smoke()
        check_rmcorr_smoke()
        check_meta_analysis_smoke()
        check_nb2_smoke()
        check_weibull_aft_smoke()
        check_ordinal_logit_smoke()
        check_rmst_smoke()
        check_nonlinear_weighting_smoke()
        check_global_irls_smoke()
        check_nonlinear_bands_smoke()
        check_parameter_intervals_smoke()
        check_parameter_weighting_smoke()
        check_custom_profiles_smoke()
        check_global_profiles_smoke()
        check_custom_equation_smoke()
        check_global_custom_smoke()
        check_global_uncertainty_smoke()
        from analisi.figure_export_smoke import check_figure_export
        check_figure_export(root, app, directory, SimpleNamespace(
            capture=capture, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            messagebox=messagebox, filedialog=filedialog))
        check_language()
        check_graph_language()
        from analisi.pdf_bundle_smoke import check_pdf_bundle
        check_pdf_bundle(root, app, directory, SimpleNamespace(
            capture=capture, wait_for_calculation=wait_for_calculation, filedialog=filedialog))
        from analisi.layout_svg_smoke import check_layout_svg
        check_layout_svg(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            filedialog=filedialog, LayoutDialog=LayoutDialog, AnalysisDialog=AnalysisDialog))
        from analisi.graph_annotation_smoke import check_graph_annotations
        check_graph_annotations(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog))
        from analisi.graph_shape_smoke import check_graph_shapes
        check_graph_shapes(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.shape_options_smoke import check_shape_options
        check_shape_options(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.shape_canvas_smoke import check_shape_canvas
        check_shape_canvas(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.line_caps_smoke import check_line_caps
        check_line_caps(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.shape_editor_pages_smoke import check_shape_editor_pages
        check_shape_editor_pages(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog))
        from analisi.shape_context_smoke import check_shape_context
        check_shape_context(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog))
        from analisi.shape_clipboard_smoke import check_shape_clipboard
        check_shape_clipboard(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog,
            put_clipboard=put_clipboard, get_clipboard=get_clipboard,
            drive_dialog=drive_dialog, LayoutDialog=LayoutDialog))
        from analisi.shape_pattern_color_smoke import check_shape_pattern_color
        check_shape_pattern_color(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.shape_arrange_smoke import check_shape_arrange
        check_shape_arrange(SimpleNamespace(app=app, root=root, directory=directory, capture=capture,
            drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            filedialog=filedialog, LayoutDialog=LayoutDialog))
        from analisi.exact_rank_smoke import check_exact_rank_tests

        check_exact_rank_tests(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, pick_method=pick_method,
            select_columns=select_columns, drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        check_grouped_distributions_smoke()
        check_box_violin()
        check_rank_comparisons()
        check_graph_inspector()
        check_graph_inspector_groups()
        check_deming_workflow()
        check_deming_multiseries_smoke()
        check_linear_diagnostics_workflow()
        check_linear_estimates_smoke()
        check_nonlinear_calibration_workflow()
        check_4pl_calibration_workflow()
        check_xy_dual_axis()
        from analisi.ols_smoke import check_ols_diagnostics
        check_ols_diagnostics(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        check_mlr_weighting_smoke()
        from analisi.logistic_smoke import check_logistic_profiles
        check_logistic_profiles(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.pca_graphs_smoke import check_pca_graphs
        check_pca_graphs(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.pca_selection_smoke import check_pca_selection
        check_pca_selection(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=drive_dialog, wait_for_calculation=wait_for_calculation,
            AnalysisDialog=AnalysisDialog, GraphFormatDialog=GraphFormatDialog,
            messagebox=messagebox, filedialog=filedialog, errors=errors,
            screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
        from analisi.pca_regression_smoke import check_pca_regression
        check_pca_regression(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, AnalysisDialog=AnalysisDialog,
            messagebox=messagebox, filedialog=filedialog, errors=errors,
            screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
        from analisi.ancova_smoke import check_ancova
        check_ancova(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, AnalysisDialog=AnalysisDialog,
            messagebox=messagebox, filedialog=filedialog, errors=errors,
            screenshots=bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))))
        from analisi.trend_anova_smoke import check_anova_trend
        check_anova_trend(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.anova_diagnostics_smoke import check_anova_diagnostics
        check_anova_diagnostics(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.anova_terms_smoke import check_anova_selected_terms
        check_anova_selected_terms(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.anova_ss_smoke import check_anova_ss_types
        check_anova_ss_types(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.rm_sphericity_smoke import check_rm_two_way_sphericity
        check_rm_two_way_sphericity(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.variance_assumptions_smoke import check_variance_assumptions
        check_variance_assumptions(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
        from analisi.fdr_control_smoke import check_fdr_control
        check_fdr_control(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
        from analisi.variance_ratio_smoke import check_variance_ratio
        check_variance_ratio(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, capture=capture, pick_method=pick_method,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation, save_project=save_project, Dataset=Dataset))
        check_binomial_goodness_smoke()
        from analisi.fit_quality_smoke import check_fit_quality
        check_fit_quality(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method, select_columns=select_columns,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.parts_style_smoke import check_parts_segment_styles
        check_parts_segment_styles(root, app, directory, SimpleNamespace(
            capture=capture, pick_method=pick_method,
            drive_dialog=lambda action: drive_dialog(AnalysisDialog, action),
            wait_for_calculation=wait_for_calculation))
        from analisi.xy_format_smoke import check_xy_formatting
        check_xy_formatting(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture,
            drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
            pick_method=pick_method, save_project=save_project, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, errors=errors))
        from analisi.xy_error_smoke import check_xy_errors
        check_xy_errors(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, Dataset=Dataset, capture=capture,
            drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
            pick_method=pick_method, save_project=save_project, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, errors=errors))
        from analisi.xy_mixed_smoke import check_xy_mixed
        check_xy_mixed(root, app, directory, SimpleNamespace(
            AnalysisDialog=AnalysisDialog, LayoutDialog=LayoutDialog, Dataset=Dataset, capture=capture,
            drive_dialog=drive_dialog, filedialog=filedialog, messagebox=messagebox,
            pick_method=pick_method, save_project=save_project, select_columns=select_columns,
            wait_for_calculation=wait_for_calculation, errors=errors))
        from analisi.axis_guides_smoke import check_axis_guides
        check_axis_guides(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog,
            LayoutDialog=LayoutDialog, errors=errors))
        from analisi.axis_breaks_smoke import check_axis_breaks
        check_axis_breaks(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog,
            LayoutDialog=LayoutDialog, errors=errors))
        from analisi.legend_formatting_smoke import check_legend_formatting
        check_legend_formatting(SimpleNamespace(
            app=app, root=root, directory=directory, capture=capture, drive_dialog=drive_dialog,
            wait_for_calculation=wait_for_calculation, filedialog=filedialog,
            LayoutDialog=LayoutDialog, errors=errors))
        check_reference_normalization_smoke()
        check_analysis_chains_smoke()
        check_hierarchical_import_smoke()
        check_hierarchical_style_smoke()
        check_family_workflow_smoke()
        check_cluster_silhouette_smoke()
        check_piecewise_equations_smoke()
        from analisi.legacy_mv_scatter_smoke import check_saved_scatter
        check_saved_scatter(root, app, directory, capture, wait_for_calculation)
        from analisi.legacy_pca_smoke import check_restored_pca
        check_restored_pca(root, app, directory, capture, wait_for_calculation)
        from analisi.grouped_anova_smoke import check_linked_grouped_anova
        check_linked_grouped_anova(root, app, directory, capture, wait_for_calculation)
        assert app.nav.winfo_ismapped()
        assert not errors, errors
        (directory / "status.txt").write_text("PASS\n", encoding="utf-8")
        app.worker.shutdown(wait=False)
        root.after(1500, root.destroy)
    except Exception:
        (directory / "status.txt").write_text(traceback.format_exc(), encoding="utf-8")
        app.worker.shutdown(wait=False)
        root.destroy()
    finally:
        if windows_clipboard is not None:
            windows_clipboard.close()


def main(*, root=None, on_ready=None, standard_only=False):
    # Read once at startup: Edit → Language… changes the file, the running window keeps its language.
    set_language(load_language(config_path()))
    parallel.configure(parallel.load_setting(config_path()))
    configure_native_dpi()
    root = tk.Tk() if root is None else root
    app = App(root, standard_only=standard_only)
    root.report_callback_exception = lambda kind, error, trace: app.error(error)
    smoke_path = None
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--smoke":
        smoke_path = Path(sys.argv[2])
        legacy_reference = Path(sys.argv[3]) if len(sys.argv) == 4 else None
        root.after(300, lambda: smoke(root, app, smoke_path, legacy_reference))
    elif len(sys.argv) == 2:
        root.after(0, lambda: app.open_document(sys.argv[1]))
    if on_ready is not None:
        root.deiconify()
        root.update_idletasks()
        on_ready()
    root.mainloop()
    if smoke_path is not None:
        status = smoke_path / "status.txt"
        if not status.is_file() or status.read_text(encoding="utf-8").strip() != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
