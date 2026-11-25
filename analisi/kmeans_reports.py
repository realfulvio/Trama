"""Reports and plots from the fitted K-means partitions."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import f

from .analysis_chain import RESULT_CONTEXT
from .field_error import FieldError
from .kmeans_options import GAP_PLOT, scale
from .reporting import Result, _plot

DETAILS = "Report cluster details"
SCALED = "Report standardized observations"
DISTANCES = "Report assigned distances"
CENTROIDS = "Report initial centroids"
ANOVA = "Report cluster ANOVA"
ASSIGNMENTS = "Report assignments for every k"
ASSIGNMENTS_TABLE = "Assignments by k"
GAP = "Report Gap statistics"
FIT_DIAGNOSTICS = "Report K-means fit diagnostics"
FIT_DIAGNOSTICS_TABLE = "K-means fit diagnostics"
FIT_REASON = "Stop reason"
FIT_SOURCE = "Fit source"
COMMON = (DETAILS, SCALED, DISTANCES, CENTROIDS, ANOVA, FIT_DIAGNOSTICS)
SCAN = (*COMMON, ASSIGNMENTS, GAP)
GAP_CRITERIA = ("Gap", "Consensus (17 indices)")
MODEL_GRAPH = "K-means metric plot"
METRIC = "Cluster metric"
PLOT_TITLES = {"WSS": "WSS elbow", "Silhouette": "Mean silhouette", "Gap": "Gap statistic"}
MODEL_GRAPH_OPTIONS = {METRIC: tuple(PLOT_TITLES)}


@dataclass(frozen=True, eq=False)
class ModelPlotData:
    metrics: pd.DataFrame


def model_plot_available(frame):
    return isinstance(frame.attrs.get(RESULT_CONTEXT), ModelPlotData)


def check_model_plot(frame, options):
    data = frame.attrs.get(RESULT_CONTEXT)
    if not isinstance(data, ModelPlotData):
        raise FieldError(METRIC, "Choose a linked result from K-means model selection.")
    metric = options.get(METRIC, "WSS")
    if not isinstance(metric, str) or metric not in PLOT_TITLES:
        raise FieldError(METRIC, "Choose a K-means metric.")
    if metric not in data.metrics:
        raise FieldError(METRIC, "The source analysis does not provide this metric.")
    return data.metrics, metric


def draw_metric(axes, metrics, metric):
    axes.xaxis.get_major_locator().set_params(integer=True, min_n_ticks=1)
    values = metrics[metric].to_numpy(dtype=float)
    if metric == "Gap":
        axes.errorbar(metrics.index, values, yerr=metrics["Gap SE"].to_numpy(dtype=float), fmt="o-")
    else:
        axes.plot(metrics.index, values, "o-")


def model_plot(frame, options):
    metrics, metric = check_model_plot(frame, options)
    figure, axes = _plot(PLOT_TITLES[metric], "Number of clusters", metric)
    draw_metric(axes, metrics, metric)
    columns = ["Gap", "Gap SE"] if metric == "Gap" else [metric]
    return Result({"Plot values": metrics.loc[:, columns].copy()}, figure)


def requested(options, *, scan=False):
    active = set()
    for name in SCAN if scan else COMMON:
        value = options.get(name, False)
        if type(value) is not bool:
            raise FieldError(name, "Choose whether to include this report.")
        if value:
            active.add(name)
    if scale(options) == "none":
        active.discard(SCALED)
    if options.get("Criterion") not in GAP_CRITERIA and options.get(GAP_PLOT) is not True:
        active.discard(GAP)
    return active


def _unique_column(frame, label):
    original = label
    index = 2
    while label in frame:
        label = f"{original} ({index})"
        index += 1
    return label


def assignment_column(frame, count):
    return _unique_column(frame, f"Cluster (k={count})")


def _gap_table(metrics):
    columns = [name for name in ("WSS", "Gap", "Gap SE") if name in metrics]
    table = metrics.loc[:, columns].copy()
    log_observed = np.log(table["WSS"].where(table["WSS"] > 0))
    table["Log WSS observed"] = log_observed
    table["Mean log WSS reference"] = log_observed + table["Gap"]
    return table


def result_tables(fits, raw, fitting_data, active, *, metrics=None, column_scale="standardize", restored=False):
    """Generate report tables from existing fits; all fits share complete observations."""
    variables = list(fitting_data.columns)
    values = fitting_data.to_numpy()
    n = len(values)
    grand_mean = values.mean(axis=0)
    total_ss = np.sum((values - grand_mean) ** 2, axis=0)
    details, comparisons, starts, summary = [], [], [], []
    distances = fitting_data.copy() if DISTANCES in active else None
    assignments = raw.copy() if ASSIGNMENTS in active else None
    if assignments is not None:
        complete = raw[variables].notna().all(axis=1).to_numpy()

    for k, fit in fits.items():
        if assignments is not None:
            memberships = pd.array(np.full(len(raw), np.nan), dtype="Int64")
            memberships[complete] = fit.labels.to_numpy()
            assignments[assignment_column(assignments, k)] = memberships
        labels = fit.labels.to_numpy() - 1
        centers = fit.centers.to_numpy()
        sizes = np.bincount(labels, minlength=k)
        within = np.zeros_like(centers)
        if active & {DETAILS, ANOVA, DISTANCES}:
            squared = (values - centers[labels]) ** 2
            if distances is not None:
                distances[_unique_column(distances, f"Distance (k={k})")] = np.sqrt(squared.sum(axis=1))
            if active & {DETAILS, ANOVA}:
                np.add.at(within, labels, squared)
        if DETAILS in active:
            details.append(pd.DataFrame({
                "k": k, "Cluster": np.repeat(np.arange(1, k + 1), len(variables)),
                "Variable": variables * k, "N": np.repeat(sizes, len(variables)),
                "Center": centers.ravel(), "Within SS": within.ravel(),
            }))
        if CENTROIDS in active:
            starts.append(pd.DataFrame({
                "k": k, "Cluster": np.repeat(np.arange(1, k + 1), len(variables)),
                "Variable": variables * k, "Initial center": fit.initial_centers.to_numpy().ravel(),
            }))
        if ANOVA in active:
            between_ss = sizes @ ((centers - grand_mean) ** 2)
            residual_ss = within.sum(axis=0)
            df_model, df_error = k - 1, n - k
            ms_model = between_ss / df_model if df_model else np.full(len(variables), np.nan)
            ms_error = residual_ss / df_error if df_error else np.full(len(variables), np.nan)
            statistic = np.divide(ms_model, ms_error, out=np.full(len(variables), np.nan), where=ms_error > 0)
            comparisons.append(pd.DataFrame({
                "k": k, "Variable": variables, "Between SS": between_ss, "Within SS": residual_ss,
                "Total SS": total_ss, "Between df": df_model, "Within df": df_error,
                "Between MS": ms_model, "Within MS": ms_error, "F": statistic,
                "Nominal p": f.sf(statistic, df_model, df_error),
                "Interpretation": "Descriptive only: partitions were fitted to these variables.",
            }))
        total, residual = float(total_ss.sum()), fit.inertia
        summary.append({"k": k, "N": n, "Within SS": residual, "Total SS": total,
                        "Within variation (%)": 100 * residual / total if total > 0 else np.nan,
                        "Explained variation (%)": 100 * (1 - residual / total) if total > 0 else np.nan})

    tables = {"Cluster variation": pd.DataFrame(summary).set_index("k")}
    if assignments is not None:
        tables[ASSIGNMENTS_TABLE] = assignments
    if SCALED in active:
        title = "Centered observations" if column_scale == "center" else "Standardized observations"
        tables[title] = fitting_data
    if details:
        tables["Cluster details"] = pd.concat(details, ignore_index=True)
    if distances is not None:
        tables["Assigned distances"] = distances
    if starts:
        tables["Initial centroids"] = pd.concat(starts, ignore_index=True)
    if comparisons:
        tables["Cluster ANOVA"] = pd.concat(comparisons, ignore_index=True)
    if GAP in active:
        tables["Gap statistics"] = _gap_table(metrics)
    if FIT_DIAGNOSTICS in active:
        reasons = {True: "Converged", False: "Iteration limit reached", None: "Fixed passes completed"}
        tables[FIT_DIAGNOSTICS_TABLE] = pd.DataFrame({
            "Iterations": pd.array([fit.iterations for fit in fits.values()], dtype="Int64"),
            FIT_REASON: ["Not recorded" if restored else reasons[fit.converged] for fit in fits.values()],
            FIT_SOURCE: "Saved fit" if restored else "Current fit",
        }, index=pd.Index(fits.keys(), name="k"))
    return tables
