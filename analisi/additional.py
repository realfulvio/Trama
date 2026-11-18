"""Additional Standard analysis workflows for the desktop workbench."""
import numpy as np
from matplotlib.ticker import PercentFormatter
from scipy import stats

from . import (auc_peaks, cox_outputs, design, exploration, inference, logistic_diagnostics, lognormal_anova, mlr_weighting,
               models, ols_diagnostics, operations, pca_graphs, pca_overlays, pca_regression, pca_reports,
               pca_retention, trend_anova, unequal_anova, variance_assumptions, roc as roc_module)
from . import plot_function as function_plot
from .deming import identity_limits, jackknife_deming
from . import nonlinear_calibration as calibration
from .nonlinear_calibration import CURVES, INVERSE_MODELS, interpolate_standard_curve
from .processing import METHODS as PROCESSING_METHODS, processing_analysis
from .reporting import Result, _plot, _report
from .repeated_workbench import METHODS as REPEATED_METHODS, global_analysis, mixed_analysis
from . import curve_pipeline, custom_fit, global_custom_fit, spline_fit
from .stats import complete
from . import fdr_control

MULTIPLE, OPTIONAL, OPTIONAL_MULTIPLE = "Multiple", "Optional", "Multiple (optional)"
CORRECTIONS = {"Holm": "holm", "Bonferroni": "bonferroni", "FDR (Benjamini–Hochberg)": "fdr_bh",
               "Holm–Šídák": "holm-sidak"}

EXTRA_METHODS = {
    **REPEATED_METHODS,
    **PROCESSING_METHODS,
    "One-way ANOVA": {"Response": None, "Group": None,
                      lognormal_anova.DISTRIBUTION: lognormal_anova.DISTRIBUTIONS,
                      "Method": tuple(unequal_anova.METHOD_KEYS),
                      "Post-hoc": ("None", "Tukey", unequal_anova.DUNNETT, "Games–Howell",
                                   *unequal_anova.UNEQUAL_POSTHOC_KEYS, "Holm", "Bonferroni",
                                   "FDR (Benjamini–Hochberg)"),
                      unequal_anova.FAMILY: unequal_anova.FAMILIES, unequal_anova.CONTROL: inference.DUNN_OPTIONS[inference.DUNN_CONTROL],
                      unequal_anova.PAIRS: inference.DUNN_PAIR_LIST,
                      lognormal_anova.RATIO_DIRECTION: lognormal_anova.DIRECTIONS,
                      unequal_anova.LEVEL: unequal_anova.DEFAULT_LEVEL,
                      trend_anova.TREND: False, trend_anova.ORDER: trend_anova.ORDER_KIND,
                      variance_assumptions.BROWN: False, variance_assumptions.BARTLETT: False,
                      variance_assumptions.ALPHA: variance_assumptions.DEFAULT_ALPHA},
    "Repeated measures ANOVA": {"Response": None, "Factors": MULTIPLE, "Subject": None,
                                "Sphericity correction": ("None", "Geisser–Greenhouse (one-way)")},
    "Friedman": {"Response": None, "Group": None, "Subject": None,
                 inference.FRIEDMAN_P: inference.KRUSKAL_P_METHODS, **inference.DUNN_OPTIONS},
    "ROC curve": {"Control": None, "Patient": None, "Direction": roc_module.DIRECTIONS,
                  "Confidence level (%)": roc_module.DEFAULT_LEVEL, "Confidence interval": roc_module.ROC_INTERVALS,
                  "Show as": roc_module.SHOW_AS},
    "Compare paired ROC curves": {"Control A": None, "Control B": None, "Patient A": None, "Patient B": None,
                                  "Direction A": roc_module.PAIRED_DIRECTIONS,
                                  "Direction B": roc_module.PAIRED_DIRECTIONS,
                                  "Confidence level (%)": roc_module.DEFAULT_LEVEL},
    "Bland–Altman": {"First": None, "Second": None, "Method": exploration.AGREEMENT_METHODS,
                     exploration.COVERAGE: exploration.DEFAULT_PERCENT,
                     exploration.CONFIDENCE: exploration.DEFAULT_PERCENT,
                     exploration.LIMIT_INTERVALS: False, exploration.CONFIDENCE_BANDS: False},
    "Deming regression": {"X": None, "Y": None, "Y / X error variance": 1.0,
                          # None is first so a saved recipe without this key keeps the point fit.
                          "Parameter intervals": ("None", "Jackknife (t)"),
                          "Confidence level (%)": 95.0, "Identity line": False},
    "Area under curve": {"X": None, "Y": None, "Baseline": 0.0, auc_peaks.PEAKS: auc_peaks.MODES,
                         auc_peaks.HEIGHT: auc_peaks.DEFAULT_HEIGHT, auc_peaks.WIDTH: 0.0},
    # Direction comes first in its tab so recipes without it keep X from Y (0.52.0).
    "Interpolate a standard curve": {"X": None, "Y": None, "Unknown responses": None,
                                    calibration.UNKNOWN_X: None,
                                    calibration.DIRECTION: calibration.DIRECTIONS,
                                    "Curve": CURVES, "Model": INVERSE_MODELS,
                                    calibration.UNCERTAINTY: calibration.UNCERTAINTIES,
                                    calibration.LEVEL: calibration.DEFAULT_LEVEL,
                                    # Empty means k = 1, the 0.53.0 prediction limits.
                                    calibration.COUNT: OPTIONAL},
    spline_fit.SPLINE_FIT: spline_fit.OPTIONS,
    # The fourth choice is last, so LOWESS stays the default and the three older choices keep their fields.
    "Smooth / differentiate / integrate": {"X": None, "Y": None,
                                          "Method": ("LOWESS", "Differentiate", "Cumulative integral",
                                                     curve_pipeline.PIPELINE),
                                          "LOWESS fraction": .5, **curve_pipeline.OPTIONS},
    function_plot.PLOT_FUNCTION: function_plot.OPTIONS,
    custom_fit.CUSTOM_EQUATION: custom_fit.OPTIONS,
    global_custom_fit.GLOBAL_CUSTOM_EQUATION: global_custom_fit.OPTIONS,
    "Principal component analysis": {"Variables": MULTIPLE, "Standardize": True,
                                    pca_graphs.GRAPH: pca_graphs.VIEWS,
                                    pca_graphs.HORIZONTAL: 1, pca_graphs.VERTICAL: 2,
                                    pca_graphs.LABEL: OPTIONAL, pca_graphs.SHOW_LABELS: False,
                                    pca_graphs.COLOR_GROUPS: OPTIONAL,
                                    **pca_retention.OPTIONS, **pca_reports.OPTIONS, **pca_overlays.OPTIONS,
                                    # Off (and missing keys) keeps every PCA output; the rest is read only when on.
                                    pca_regression.ENABLE: False, pca_regression.RESPONSE: OPTIONAL,
                                    pca_regression.CONFIDENCE: pca_regression.DEFAULT_CONFIDENCE,
                                    pca_regression.PLOT: pca_regression.PLOTS},
    "Multiple regression": {"Response": None, "Predictors": MULTIPLE,
                            "Categorical predictors": OPTIONAL_MULTIPLE, "Family": ("Linear", "Logistic", "Poisson"),
                            # Poisson only; older recipes carry none of these keys and keep unit exposure.
                            models.EXPOSURE: OPTIONAL, models.DIAGNOSTICS: False, models.RESIDUAL_PLOT: False,
                            # Linear only. Unweighted (also when the keys are missing) keeps the historical fit.
                            mlr_weighting.GAUSSIAN_WEIGHTING: mlr_weighting.MODES,
                            mlr_weighting.EXPONENT: mlr_weighting.DEFAULT_EXPONENT,
                            mlr_weighting.SD_COLUMN: OPTIONAL, mlr_weighting.WEIGHT_COLUMN: OPTIONAL,
                            # Linear only. Missing keys keep the coefficient sheets and add no diagnostic view.
                            ols_diagnostics.LINEAR_DIAGNOSTICS: False,
                            ols_diagnostics.LINEAR_RESIDUAL_PLOT: ols_diagnostics.PLOTS,
                            ols_diagnostics.LINEAR_PROFILES: cox_outputs.PROFILE_LIST,
                            ols_diagnostics.LINEAR_CI: 95.0,
                            mlr_weighting.FUTURE_PRECISION: False,
                            # Logistic only. Missing keys keep the coefficient sheets.
                            logistic_diagnostics.LOGISTIC_DIAGNOSTICS: False,
                            logistic_diagnostics.LOGISTIC_CUTOFF: logistic_diagnostics.DEFAULT_CUTOFF,
                            logistic_diagnostics.LOGISTIC_PROFILES: cox_outputs.PROFILE_LIST,
                            logistic_diagnostics.LOGISTIC_CI: logistic_diagnostics.DEFAULT_LEVEL},
    "Cox regression": {"Time": None, "Event": None, "Predictors": MULTIPLE,
                       "Categorical predictors": OPTIONAL_MULTIPLE, "Ties": ("Efron", "Breslow"),
                       # Recipes without the status codes and the new outputs keep the original sheets.
                       **cox_outputs.OPTIONS},
    "Kolmogorov–Smirnov": {"First": None, "Second": None},
    "Multiple t-tests": {"Variables": MULTIPLE, "Group": None, "Subject": OPTIONAL,
                         "Design": ("Welch", "Student", "Paired"), "Correction": tuple(CORRECTIONS)},
    "Adjust a stack of p values": {"p value": None, "Correction": tuple(CORRECTIONS)},
    fdr_control.METHOD: {fdr_control.P_COLUMNS: MULTIPLE, fdr_control.FAMILY_COLUMNS: OPTIONAL_MULTIPLE,
                         fdr_control.SCOPE: fdr_control.SCOPES, fdr_control.FDR_METHOD: fdr_control.FDR_METHODS,
                         fdr_control.LEVEL: 5.0, fdr_control.PLOT: False},
    "Normalize": {"Variables": MULTIPLE,
                  "Method": ("Percent of range", "Z score", "Percent of first value", "Subtract first value")},
    "Transform": {"Variables": MULTIPLE,
                  "Operation": ("Log10", "Natural log", "Square root", "Reciprocal", "Absolute value", "Square")},
    "Row statistics": {"Variables": MULTIPLE},
    "Reshape replicates": {"Variables": MULTIPLE, "Row label": OPTIONAL},
    "Outlier test (Grubbs)": {"Response": None, "Alpha": .05},
    "Power and sample size": {"Goal": ("Sample size", "Power"),
                              "Design": ("One-sample t", "Paired t", "Independent t", "One-way ANOVA"),
                              "Standardized effect": .5, "Alpha": .05, "Target power": .8,
                              "N (per group, if independent)": 30, "ANOVA groups": 3},
    "Simulate data": {"Distribution": ("Normal", "XY with normal noise", "2 × 2 contingency"),
                      "N": 30, "Seed": 42, "Mean": 0., "SD": 1., "X minimum": 0., "X maximum": 1.,
                      "Intercept": 0., "Slope": 1., "Success probability A": .5, "Success probability B": .5},
}


def _roc(frame, o):
    report, curve, table = roc_module.roc_analysis(
        frame, o["Control"], o["Patient"], o["Direction"], o.get("Confidence level (%)", roc_module.DEFAULT_LEVEL),
        o.get("Confidence interval", roc_module.ROC_INTERVALS[0]), o.get("Show as", roc_module.SHOW_AS[0]))
    percent = o.get("Show as") == "Percentages"
    fig, ax = _plot("Receiver operating characteristic",
                    "False positive rate" + (" (%)" if percent else ""), "True positive rate" + (" (%)" if percent else ""))
    ax.plot(curve["False positive rate"], curve["True positive rate"], label=f'AUC {report["AUC"]:.4g}')
    ax.plot([0, 1], [0, 1], "--", color="#81919b")
    best = table["Youden candidate"] == "Yes"
    if best.any():
        n, m = report["Control N"], report["Patient N"]
        ax.scatter((table["FP"][best] / n).to_numpy(), (table["TP"][best] / m).to_numpy(), s=60, zorder=3,
                   color="#aa5440", label="Youden candidate")
    if percent:
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.legend(loc="lower right")
    return Result({"ROC summary": _report(report), "Curve points": curve, "Diagnostic thresholds": table}, fig)


def _paired_roc(frame, o):
    report, curve_a, curve_b = roc_module.compare_paired_roc(
        frame, o["Control A"], o["Control B"], o["Patient A"], o["Patient B"], o["Direction A"], o["Direction B"],
        o.get("Confidence level (%)", roc_module.DEFAULT_LEVEL))
    fig, ax = _plot("Paired ROC curves", "False positive rate", "True positive rate")
    for curve, name, label in ((curve_a, o["Patient A"], "A"), (curve_b, o["Patient B"], "B")):
        ax.plot(curve["False positive rate"], curve["True positive rate"],
                label=f'{label} ({name}) AUC {report["AUC " + label]:.4g}')
    ax.plot([0, 1], [0, 1], "--", color="#81919b")
    ax.legend(loc="lower right")
    return Result({"Paired ROC comparison": _report(report), "Curve points A": curve_a, "Curve points B": curve_b}, fig)


def bland_altman_visibility(limit_intervals):
    """The confidence level and bands only matter once the intervals of the agreement limits are requested."""
    return {exploration.CONFIDENCE: bool(limit_intervals), exploration.CONFIDENCE_BANDS: bool(limit_intervals)}


def _bland_altman(frame, o):
    """Old recipes lack the new keys and get 95% coverage and confidence, no intervals and no bands."""
    method = o["Method"]
    intervals = o.get(exploration.LIMIT_INTERVALS, False)
    found = exploration.agreement(frame, o["First"], o["Second"], method, o.get(exploration.COVERAGE, 95.0),
                                  o.get(exploration.CONFIDENCE, 95.0), intervals)
    report, points, show = found["report"], found["points"], found["display"]
    logs = show["log"]
    fig, ax = _plot("Bland–Altman agreement", "Geometric mean of First and Second" if logs else "Paired mean",
                    "First / Second" if logs else method)
    ax.scatter(points["Mean"], points[method])
    if logs:
        ax.set_yscale("log")
        ax.axhline(1, color="#9aa5ab", linewidth=.8, zorder=0, label="Equal values (1)")
    if intervals and o.get(exploration.CONFIDENCE_BANDS, False):
        for key, label, color in (("lower_band", "Lower limit CI", "#3b7ea1"), ("upper_band", "Upper limit CI", "#c08a2e")):
            ax.axhspan(*show[key], color=color, alpha=.2, linewidth=0, label=label)
    for key, label in (("bias", "Bias"), ("lower", "Lower agreement limit"), ("upper", "Upper agreement limit")):
        ax.axhline(show[key], linestyle="-" if key == "bias" else "--", color="#aa5440", label=label)
    if logs or intervals:
        # Up to seven entries: keep them below the axes so they never hide observations.
        fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=3, frameon=False)
    else:
        ax.legend()
    return Result({"Agreement": _report(report), "Paired values": points}, fig)


def _deming_result(frame, o, fig, ax):
    x, y = o["X"], o["Y"]
    report, points, pairs = jackknife_deming(
        frame, x, y, o["Y / X error variance"],
        intervals=o.get("Parameter intervals", "None"), level=o.get("Confidence level (%)", 95.0))
    ax.scatter(points[x], points[y])
    slope, intercept = report["Slope"], report["Intercept"]
    if o.get("Identity line"):
        low, high = identity_limits(points[x], points[y])
        domain = np.array([low, high])
        ax.plot(domain, intercept + slope * domain, label="Deming fit")
        ax.plot(domain, domain, linestyle="--", color="#81919b", label="Identity")
        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.legend()
    else:
        domain = np.array([points[x].min(), points[x].max()])
        ax.plot(domain, intercept + slope * domain)
    return Result({"Deming regression": _report(report), "Data": points, "Pairs": pairs}, fig)


def _xy(method, frame, o):
    x, y = o["X"], o["Y"]
    fig, ax = _plot(method, x, y)
    if method == "Deming regression":
        return _deming_result(frame, o, fig, ax)
    report, points = exploration.area_under_curve(frame, x, y, o["Baseline"])
    ax.plot(points[x], points[y], "o-")
    ax.axhline(o["Baseline"], color="#aaa")
    ax.fill_between(points[x], o["Baseline"], points[y], alpha=.22)
    return Result({method: _report(report), "Data": points}, fig)


def regression_visibility(family, diagnostics, logistic_diagnostics_on=False, logistic_profiles=False,
                          gaussian_mode=mlr_weighting.UNWEIGHTED, linear_profiles=False):
    """Exposure and diagnostics belong to the Poisson family; the residual plot needs the diagnostics.

    Linear diagnostics, the residual plot, profiles and the confidence level belong to the linear family.
    Logistic diagnostics and profiles belong to the logistic family. The cutoff is active with
    diagnostics, and the confidence level is active when at least one profile is present.
    The Gaussian weighting belongs to the linear family: K shows for the power, the SD or weight column for its own
    mode, and the future precision of the profiles only for a weighted fit that has at least one profile.
    """
    poisson = family == "Poisson"
    linear = family == "Linear"
    logistic = family == "Logistic"
    weighted = linear and gaussian_mode != mlr_weighting.UNWEIGHTED
    return {mlr_weighting.GAUSSIAN_WEIGHTING: linear,
            mlr_weighting.EXPONENT: linear and gaussian_mode == mlr_weighting.ABS_Y_POWER,
            mlr_weighting.SD_COLUMN: linear and gaussian_mode == mlr_weighting.INVERSE_VARIANCE,
            mlr_weighting.WEIGHT_COLUMN: linear and gaussian_mode == mlr_weighting.FROM_COLUMN,
            mlr_weighting.FUTURE_PRECISION: weighted and bool(linear_profiles),
            models.EXPOSURE: poisson, models.DIAGNOSTICS: poisson,
            models.RESIDUAL_PLOT: poisson and bool(diagnostics),
            ols_diagnostics.LINEAR_DIAGNOSTICS: linear, ols_diagnostics.LINEAR_RESIDUAL_PLOT: linear,
            ols_diagnostics.LINEAR_PROFILES: linear, ols_diagnostics.LINEAR_CI: linear,
            logistic_diagnostics.LOGISTIC_DIAGNOSTICS: logistic,
            logistic_diagnostics.LOGISTIC_CUTOFF: logistic and bool(logistic_diagnostics_on),
            logistic_diagnostics.LOGISTIC_PROFILES: logistic,
            logistic_diagnostics.LOGISTIC_CI: logistic and bool(logistic_profiles)}


def _multiple_regression(frame, o):
    family = o["Family"]
    if family == "Linear":
        # The Family check comes first: Logistic and Poisson never read the Gaussian keys, even stale invalid ones.
        weighted = mlr_weighting.weighted(o)
        if weighted:
            ols_diagnostics.validate(o)
            fit, weights = mlr_weighting.weighted_linear_fit(frame, o)
            return ols_diagnostics.linear_result(o, fit, weights)
    if family == "Linear" and ols_diagnostics.present(o):
        ols_diagnostics.validate(o)
        if ols_diagnostics.requested(o):
            fit = models.linear_fit(frame, o["Response"], o["Predictors"], o["Categorical predictors"])
            return ols_diagnostics.linear_result(o, fit)
    if family == "Logistic" and logistic_diagnostics.present(o):
        logistic_diagnostics.validate(o)
        if logistic_diagnostics.requested(o):
            fit = models.logistic_fit(frame, o["Response"], o["Predictors"], o["Categorical predictors"])
            return logistic_diagnostics.logistic_result(o, fit)
    poisson = family == "Poisson"
    diagnostics = poisson and bool(o.get(models.DIAGNOSTICS, False))
    tables = models.regression(frame, o["Response"], o["Predictors"], o["Categorical predictors"], family,
                               exposure=(o.get(models.EXPOSURE) or None) if poisson else None,
                               diagnostics=diagnostics)
    if not (diagnostics and o.get(models.RESIDUAL_PLOT, False)):
        return Result(tables)
    fitted = tables["Fitted values"]
    fig, ax = _plot("Poisson residuals", "Fitted count", "Pearson residual")
    ax.axhline(0, color="#7f8c99", linewidth=1, zorder=1)
    ax.scatter(fitted["Fitted"], fitted["Pearson residual"], zorder=2)
    return Result(tables, fig)


def _pca(frame, o):
    # Recipes without the graph keys keep the historical sheets and the PC1/PC2 scatter.
    if pca_graphs.present(o):
        return pca_graphs.pca_result(frame, o)
    regression = pca_regression.settings(frame, o)
    parts, loadings, scores = exploration.pca(frame, o["Variables"], o["Standardize"])
    retention = pca_retention.assess(frame, o, parts, loadings, scores)
    fig, ax = _plot("Principal component scores", "PC1", "PC2")
    ax.scatter(scores["PC1"], scores["PC2"])
    tables = {"Explained variance": parts, "Eigenvectors": loadings, "Scores": scores}
    tables.update(retention.tables)
    tables.update(pca_reports.optional_tables(frame, o, parts, loadings, scores, retention))
    if regression is not None:
        found = pca_regression.regress(frame, o, regression, parts, loadings, scores, retention)
        tables.update(found.tables)
        fig = found.figure or fig
    return Result(tables, fig)


def _calibration_figure(frame, o, calibrated):
    x, y = o["X"], o["Y"]
    if calibrated.model is None:
        fit = calibrated.linear
        estimates = calibrated.tables["Interpolated values"]
        fig, ax = _plot("Linear calibration", x, y)
        calibration = complete(frame, [x, y])
        ax.scatter(calibration[x], calibration[y], label="Standards")
        endpoints = np.array([calibration[x].min(), calibration[x].max()])
        ax.plot(endpoints, fit["Intercept"] + fit["Slope"] * endpoints)
        ax.scatter(estimates["Interpolated X"], estimates["Response"], marker="x", label="Unknowns")
        ax.legend()
        return fig
    fig, ax = _plot("Nonlinear calibration", x, y)
    calibration = complete(frame, [x, y])
    ax.scatter(calibration[x], calibration[y], label="Standards")
    ax.plot(calibrated.curve[:, 0], calibrated.curve[:, 1], label=calibrated.model)
    found = calibrated.tables["Interpolated values"]["Interpolated X"].notna()
    estimates = calibrated.tables["Interpolated values"].loc[found]
    if not estimates.empty:
        ax.scatter(estimates["Interpolated X"], estimates["Response"], marker="x", label="Estimates", zorder=3)
    _draw_inverse_intervals(ax, calibrated)
    ax.legend()
    return fig


def _draw_inverse_intervals(ax, calibrated):
    """Horizontal segments at each query. Disconnected components stay separate."""
    table = calibrated.tables["Interpolated values"]
    if calibrated.uncertainty == "None" or calibration.INTERVAL_STATUS not in table.columns or calibrated.level is None:
        return
    kind = "mean response" if calibrated.uncertainty == calibration.UNCERTAINTIES[1] else "prediction"
    label = f"{calibrated.level:g}% {kind} interval"
    segments = []
    components = calibrated.tables.get(calibration.COMPONENTS)
    if components is not None:
        response = {row["Source row"]: float(row["Response"])
                    for _, row in table.iterrows() if row[calibration.INTERVAL_STATUS] == calibration.DISCONNECTED}
        for _, piece in components.iterrows():
            y = response.get(piece["Source row"])
            if y is None or not np.isfinite((piece["X lower"], piece["X upper"], y)).all():
                continue
            segments.append((float(piece["X lower"]), float(piece["X upper"]), y))
    for _, row in table.iterrows():
        if row[calibration.INTERVAL_STATUS] == calibration.DISCONNECTED:
            continue
        left, right, y = row["X lower"], row["X upper"], row["Response"]
        if not np.isfinite((left, right, y)).all():
            continue
        segments.append((float(left), float(right), float(y)))
    color = "#9a3412"
    for index, (left, right, y) in enumerate(segments):
        caption = label if index == 0 else "_nolegend_"
        if left == right:
            ax.plot([left], [y], marker="|", markersize=12, color=color, linestyle="none",
                    label=caption, zorder=4)
        else:
            ax.plot([left, right], [y, y], color=color, linewidth=2.0, solid_capstyle="butt",
                    label=caption, zorder=4)


def _prediction_figure(frame, o, calibrated):
    x, y = o["X"], o["Y"]
    fig, ax = _plot("Linear calibration" if calibrated.model is None else "Nonlinear calibration", x, y)
    standards = complete(frame, [x, y])
    ax.scatter(standards[x], standards[y], label="Standards", zorder=3)
    bands = calibrated.tables.get(calibration.BANDS)
    if bands is not None:
        kind = "mean response" if calibrated.uncertainty == calibration.UNCERTAINTIES[1] else "prediction"
        # Queries may average k replicates; the drawn band is always for one new observation.
        single = " (k = 1)" if calibrated.replicates else ""
        ax.fill_between(bands["X"], bands["Y lower"], bands["Y upper"], color="#3b7ea1", alpha=.2, linewidth=0,
                        label=f"{calibrated.level:g}% {kind} band{single}")
    ax.plot(calibrated.curve[:, 0], calibrated.curve[:, 1], label=calibrated.model or "Linear fit")
    predictions = calibrated.tables[calibration.PREDICTIONS]
    inside = predictions.loc[predictions["Predicted Y"].notna()]
    if not inside.empty:
        ax.scatter(inside["X"], inside["Predicted Y"], marker="x", label="Predictions", zorder=4)
    ax.legend()
    return fig


def _standard_curve(frame, o):
    if calibration.calibration_direction(o) == calibration.DIRECTIONS[1]:
        curve, model, uncertainty, level = calibration.forward_options(o)
        predicted = calibration.predict_standard_curve(frame, o["X"], o["Y"], o[calibration.UNKNOWN_X], curve,
                                                       model, uncertainty, level,
                                                       calibration.replicate_option(o, uncertainty))
        return Result(predicted.tables, _prediction_figure(frame, o, predicted))
    curve, model, uncertainty, level, count = calibration.inverse_options(o)
    calibrated = interpolate_standard_curve(frame, o["X"], o["Y"], o["Unknown responses"], curve, model,
                                            uncertainty, level, count)
    return Result(calibrated.tables, _calibration_figure(frame, o, calibrated))


def _spline_fit(frame, o):
    fitted = spline_fit.fit_spline(frame, o)
    method = fitted.model.method
    fig, ax = _plot(f"{method} fit", o["X"], o["Y"])
    support = fitted.tables[spline_fit.SUPPORT]
    ax.scatter(support["X"], support["Y"], zorder=3, label="Support points")
    ax.plot(fitted.grid, fitted.curve, label=method, zorder=2)
    queries = fitted.queries
    if o.get(spline_fit.DIRECTION) == spline_fit.Y_FROM_X and queries is not None:
        inside = queries.loc[queries["Status"] == spline_fit.IN_RANGE]
        # Direct queries stay readable up to a few dozen markers.
        if 0 < len(inside) <= 50:
            ax.scatter(inside["Query"].to_numpy(dtype=float), inside["Value"].to_numpy(dtype=float), marker="x",
                       zorder=4, label="Y from X queries")
    ax.legend()
    return Result(fitted.tables, fig)


def extra_analysis(method, frame, o):
    if method == spline_fit.SPLINE_FIT:
        return _spline_fit(frame, o)
    if method == "Mixed-effects model (REML)":
        return mixed_analysis(frame, o)
    if method == "Global nonlinear regression":
        return global_analysis(frame, o)
    if method == function_plot.PLOT_FUNCTION:
        return function_plot.plot_function(frame, o)
    if method == custom_fit.CUSTOM_EQUATION:
        return custom_fit.custom_fit(frame, o)
    if method == global_custom_fit.GLOBAL_CUSTOM_EQUATION:
        return global_custom_fit.global_custom_fit(frame, o)
    if method in PROCESSING_METHODS:
        return processing_analysis(method, frame, o)
    if method == "One-way ANOVA":
        if lognormal_anova.active(o):
            return lognormal_anova.analysis(frame, o)
        adjustment = {"None": None, "Tukey": "tukey", unequal_anova.DUNNETT: "dunnett", "Games–Howell": "games-howell",
                      **unequal_anova.UNEQUAL_POSTHOC_KEYS, **CORRECTIONS}
        unequal_anova.check_one_way_options(o)
        variance_assumptions.validate(o)
        requested = bool(o.get(trend_anova.TREND))
        if requested:
            # Zero pooled variance must be a field error, before the legacy ValueError.
            trend_anova.check_options(frame, o)
        tables = inference.one_way_anova(frame, o["Response"], o["Group"],
                                         method=unequal_anova.METHOD_KEYS[o["Method"]],
                                         posthoc=adjustment[o["Post-hoc"]],
                                         level=o.get(unequal_anova.LEVEL, unequal_anova.DEFAULT_LEVEL), family=o)
        if requested:
            tables.update(trend_anova.trend_tables(frame, o["Response"], o["Group"], o.get(trend_anova.ORDER)))
        tables.update(variance_assumptions.sheets(frame, o["Response"], o["Group"], o))
        return Result(tables)
    if method == "Repeated measures ANOVA":
        lognormal_anova.reject_repeated(o)
        return Result(inference.repeated_measures_anova(frame, o["Response"], o["Factors"], o["Subject"],
                                                        correction=None if o["Sphericity correction"] == "None" else "gg"))
    if method == "Friedman":
        return Result(inference.friedman(frame, o["Response"], o["Group"], o["Subject"], comparisons=o))
    if method == "ROC curve":
        return _roc(frame, o)
    if method == "Compare paired ROC curves":
        return _paired_roc(frame, o)
    if method == "Bland–Altman":
        return _bland_altman(frame, o)
    if method == "Area under curve":
        return auc_peaks.auc_result(frame, o)
    if method == "Deming regression":
        return _xy(method, frame, o)
    if method == "Interpolate a standard curve":
        return _standard_curve(frame, o)
    if method == "Smooth / differentiate / integrate":
        if o["Method"] == curve_pipeline.PIPELINE:
            return curve_pipeline.analysis(frame, o)
        values = exploration.curve_operation(frame, o["X"], o["Y"], o["Method"], o["LOWESS fraction"])
        fig, ax = _plot(o["Method"], o["X"], o["Y"] if o["Method"] == "LOWESS" else o["Method"])
        if o["Method"] == "LOWESS":
            ax.scatter(values["X"], values["Original Y"], alpha=.5)
        ax.plot(values["X"], values[o["Method"]])
        return Result({"Curve": values}, fig)
    if method == "Principal component analysis":
        return _pca(frame, o)
    if method == "Multiple regression":
        return _multiple_regression(frame, o)
    if method == "Cox regression":
        return cox_outputs.cox_result(frame, o)
    if method == "Kolmogorov–Smirnov":
        a, b = o["First"], o["Second"]
        if a == b:
            raise ValueError("Choose two distinct columns.")
        lhs, rhs = complete(frame, [a])[a], complete(frame, [b])[b]
        if min(len(lhs), len(rhs)) < 2:
            raise ValueError("Select at least two values per sample.")
        test = stats.ks_2samp(lhs, rhs)
        return Result({"KS test": _report({"D": test.statistic, "p": test.pvalue, "First N": len(lhs), "Second N": len(rhs)})})
    if method == "Multiple t-tests":
        table = operations.multiple_tests(frame, o["Variables"], o["Group"], o["Design"].lower(),
                                          CORRECTIONS[o["Correction"]], o.get("Subject"))
        fig, ax = _plot("Multiple t-tests", "Difference of means", "−log₁₀(adjusted p)")
        ax.scatter(table["Difference"], -np.log10(np.maximum(table["Adjusted p"], np.finfo(float).tiny)))
        return Result({method: table}, fig)
    if method == "Adjust a stack of p values":
        return Result({"Adjusted p values": operations.adjust_p(frame, o["p value"], CORRECTIONS[o["Correction"]])})
    if method == fdr_control.METHOD:
        return fdr_control.analysis(frame, o)
    if method == "Normalize":
        return Result({"Normalized": operations.normalize(frame, o["Variables"], o["Method"])})
    if method == "Transform":
        return Result({"Transformed": operations.transform(frame, o["Variables"], o["Operation"])})
    if method == "Row statistics":
        return Result({method: operations.row_statistics(frame, o["Variables"])})
    if method == "Reshape replicates":
        return Result({"Long format": operations.reshape_replicates(frame, o["Variables"], o.get("Row label"))})
    if method == "Outlier test (Grubbs)":
        return Result({"Grubbs' test": _report(operations.grubbs(frame, o["Response"], o["Alpha"]))})
    if method == "Power and sample size":
        label = {"One-sample t": "one-sample", "Paired t": "paired",
                 "Independent t": "independent", "One-way ANOVA": "anova"}[o["Design"]]
        args = {"alpha": o["Alpha"], "groups": o["ANOVA groups"]}
        if o["Goal"] == "Sample size":
            report = design.sample_size(label, o["Standardized effect"], target=o["Target power"], **args)
        else:
            report = design.power(label, o["Standardized effect"], o["N (per group, if independent)"], **args)
        return Result({method: _report(report)})
    if method == "Simulate data":
        kind = {"Normal": "normal", "XY with normal noise": "xy", "2 × 2 contingency": "contingency"}[o["Distribution"]]
        values = design.simulate(kind, o["N"], seed=o["Seed"], mean=o["Mean"], sd=o["SD"],
                                 x_min=o["X minimum"], x_max=o["X maximum"],
                                 intercept=o["Intercept"], slope=o["Slope"],
                                 p_a=o["Success probability A"], p_b=o["Success probability B"])
        return Result({"Simulated data": values})
    raise ValueError("Unknown analysis.")
