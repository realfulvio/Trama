"""Optional diagnostics from the fitted K-means partitions."""
import numpy as np
import pandas as pd
from scipy.stats import f

from .field_error import FieldError

DETAILS = "Report cluster details"
SCALED = "Report standardized observations"
DISTANCES = "Report assigned distances"
CENTROIDS = "Report initial centroids"
ANOVA = "Report cluster ANOVA"
ASSIGNMENTS = "Report assignments for every k"
GAP = "Report Gap statistics"
COMMON = (DETAILS, SCALED, DISTANCES, CENTROIDS, ANOVA)
SCAN = (*COMMON, ASSIGNMENTS, GAP)
GAP_CRITERIA = ("Gap", "Consensus (17 indices)")


def requested(options, *, scan=False):
    active = set()
    for name in SCAN if scan else COMMON:
        value = options.get(name, False)
        if type(value) is not bool:
            raise FieldError(name, "Choose whether to include this report.")
        if value:
            active.add(name)
    if not options.get("Standardize", False):
        active.discard(SCALED)
    if options.get("Criterion") not in GAP_CRITERIA:
        active.discard(GAP)
    return active


def _unique_column(frame, label):
    original = label
    index = 2
    while label in frame:
        label = f"{original} ({index})"
        index += 1
    return label


def _gap_table(metrics):
    columns = [name for name in ("WSS", "Gap", "Gap SE") if name in metrics]
    table = metrics.loc[:, columns].copy()
    log_observed = np.log(table["WSS"].where(table["WSS"] > 0))
    table["Log WSS observed"] = log_observed
    table["Mean log WSS reference"] = log_observed + table["Gap"]
    return table


def result_tables(fits, raw, fitting_data, active, *, metrics=None):
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
            assignments[_unique_column(assignments, f"Cluster (k={k})")] = memberships
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
        tables["Assignments by k"] = assignments
    if SCALED in active:
        tables["Standardized observations"] = fitting_data
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
    return tables
