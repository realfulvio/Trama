"""A native graph of the differences and intervals of a linked ANOVA result."""

import numpy as np

from .reporting import Result, _plot

METHOD = "ANOVA comparison intervals"
SOURCE_TABLE = "Multiple comparisons"
FIELDS = ("Comparison", "Family", "Difference", "CI low", "CI high")


def comparison_plot(frame):
    if not set(FIELDS).issubset(frame.columns) or frame.empty:
        raise ValueError("The source analysis does not provide comparison intervals.")
    if len(frame) > 200:
        raise ValueError("Plot up to 200 comparison intervals at once.")
    table = frame.loc[:, list(FIELDS)].copy()
    difference, low, high = table.loc[:, ["Difference", "CI low", "CI high"]].to_numpy(dtype=float).T
    valid = np.isfinite(difference) & np.isfinite(low) & np.isfinite(high) & (low <= difference) & (difference <= high)
    if not valid.all():
        raise ValueError("The source comparison intervals are undefined or invalid.")

    labels = [str(label) if family == "All" else f"{family} · {label}"
              for label, family in zip(table["Comparison"], table["Family"], strict=True)]
    figure, axes = _plot("Comparison intervals", "Mean difference", "")
    rows = np.arange(len(table))
    axes.axvline(0, color="#8998a2", linestyle="--", linewidth=1)
    axes.errorbar(difference, rows, xerr=[difference - low, high - difference], fmt="o", capsize=3)
    axes.set_yticks(rows, labels)
    for label in axes.get_yticklabels():
        label.set_parse_math(False)
    axes.invert_yaxis()
    axes._tramastat_numeric_axes = ("x",)
    axes._tramastat_categorical_axes = ("y",)
    return Result({"Comparison intervals": table}, figure)
