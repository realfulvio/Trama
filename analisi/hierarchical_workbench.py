"""Options, diagnostics and plots for a fitted hierarchical clustering tree."""

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from scipy.cluster.hierarchy import cophenet
from scipy.spatial.distance import squareform

from .data import _headers
from .reporting import Result
from .stats import hierarchical


CUT_MODES = ("Count", "Cut height", "No cut")
SCALES = ("None", "Center", "Standardize")
HIERARCHICAL_OPTIONS = {
    "Direction": ("Rows", "Columns", "Rows and columns"),
    "Scale columns": ("Standardize", "None", "Center"),
    "Scale rows": SCALES,
    "Linkage": ("average", "complete", "single", "ward", "weighted", "centroid", "median"),
    "Distance": ("euclidean", "cityblock", "chebyshev", "cosine", "correlation"),
    "Row cut": CUT_MODES, "Clusters": 2, "Row cut height": 1.0,
    "Column cut": CUT_MODES, "Column clusters": 2, "Column cut height": 1.0,
    "Graph output": ("Dendrogram", "Heat map"),
    "Dendrogram orientation": ("Vertical", "Horizontal"),
    "Branch appearance": ("By cluster", "Single color"),
    "Branch width": 1.4, "Branch style": ("Solid", "Dashed", "Dotted"), "Branch opacity (%)": 100.0,
    "Label type": ("Values", "Numbers", "Letters"),
    "First label": 1, "Label interval (0 = automatic)": 0,
    "Label angle": 0.0, "Show cut line": True,
    "Scaled data": False, "Distance matrix": False, "Merge map": False, "Cophenetic distances": False,
    "Cophenetic correlation": False, "Matrix format": ("Full", "Lower triangle"),
}
HIERARCHICAL_TABS = {
    "Clusters": ("Row cut", "Clusters", "Row cut height", "Column cut", "Column clusters", "Column cut height"),
    "Graph": ("Graph output", "Dendrogram orientation", "Branch appearance", "Label type",
              "Branch width", "Branch style", "Branch opacity (%)", "First label",
              "Label interval (0 = automatic)", "Label angle", "Show cut line"),
    "Output": ("Scaled data", "Distance matrix", "Merge map", "Cophenetic distances",
               "Cophenetic correlation", "Matrix format"),
}
PALETTE = ("#156978", "#b65a39", "#5b5aa7", "#36815b", "#a77b25", "#b34c73", "#456e9a", "#626b35")
MIXED_BRANCH = "#637584"
MAX_MATRIX_OBSERVATIONS = 512


def saved_hierarchical_options(options):
    if "Scale columns" in options or "Standardize" not in options:
        return options
    return {**options, "Scale columns": "Standardize" if options["Standardize"] else "None"}


def _cut(options, direction):
    mode = options.get(f"{direction} cut", "Count")
    if mode not in CUT_MODES:
        raise ValueError("Select count, cut height, or no cut for each clustering direction.")
    field = "Clusters" if direction == "Row" else "Column clusters"
    count = options.get(field, 2) if mode == "Count" else None
    height = options.get(f"{direction} cut height", 1.0) if mode == "Cut height" else None
    return count, height


def _row_names(frame, fit, variables, label):
    if not label:
        return [f"Row {index + 1}" if isinstance(index, (int, np.integer)) else str(index) for index in fit.scaled.index]
    keep = frame.loc[:, variables].notna().all(axis=1).to_numpy()
    rows = frame.loc[keep, label]
    return [str(value) if pd.notna(value) and str(value) else f"Row {i + 1}"
            for i, value in zip(np.flatnonzero(keep), rows, strict=True)]


def _letter(index):
    result = ""
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def _coordinates(tree, cluster_ids):
    """Lay out leaves and U-shaped branches in merge order without recursion."""
    n = len(tree) + 1
    children = tree[:, :2].astype(int)
    leaves, pending = [], [2 * n - 2]
    while pending:
        node = pending.pop()
        if node < n:
            leaves.append(node)
        else:
            left, right = children[node - n]
            pending.extend((right, left))
    x = np.empty(2 * n - 1)
    x[leaves] = np.arange(n) + .5
    height = np.r_[np.zeros(n), tree[:, 2]]
    groups = np.zeros(2 * n - 1, dtype=int)
    if cluster_ids is not None:
        groups[:n] = cluster_ids
    paths = np.empty((n - 1, 4, 2))
    for index, (left, right) in enumerate(children):
        node = n + index
        x[node] = (x[left] + x[right]) / 2
        if groups[left] == groups[right]:
            groups[node] = groups[left]
        paths[index] = ((x[left], height[left]), (x[left], height[node]),
                        (x[right], height[node]), (x[right], height[right]))
    return np.asarray(leaves), paths, groups[n:]


def _labels_in_order(names, order, options):
    first = options.get("First label", 1)
    interval = options.get("Label interval (0 = automatic)", 0)
    angle = options.get("Label angle", 0.0)
    if first < 1 or interval < 0 or not np.isfinite(angle) or not -90 <= angle <= 90:
        raise ValueError("Enter a positive first label, a non-negative interval and a label angle from −90 to 90°.")
    interval = interval or max(1, (len(order) + 54) // 55)
    positions = range(first - 1, len(order), interval)
    mode = options.get("Label type", "Values")
    if mode == "Letters":
        labels = [_letter(i + 1) for i in positions]
    elif mode == "Numbers":
        labels = [str(i + 1) for i in positions]
    else:
        labels = [names[order[i]] for i in positions]
    return [i + .5 for i in positions], labels, angle


def _draw_tree(ax, fit, names, options, cut_height, *, horizontal=False, margin=False):
    labels = fit.labels if options.get("Branch appearance", "By cluster") == "By cluster" else None
    order, paths, groups = _coordinates(fit.tree, labels)
    colors = [PALETTE[(group - 1) % len(PALETTE)] if group else MIXED_BRANCH for group in groups]
    width, opacity = options.get("Branch width", 1.4), options.get("Branch opacity (%)", 100.) / 100
    if not 0 < width <= 12 or not 0 <= opacity <= 1:
        raise ValueError("Branch width must be greater than zero and up to 12, and opacity between 0 and 100%.")
    style = options.get("Branch style", "Solid").lower()
    lines = LineCollection(paths[:, :, ::-1] if horizontal else paths, colors=colors,
                           linewidths=width, alpha=opacity, linestyles=style)
    ax.add_collection(lines)
    extent = max(fit.tree[:, 2].max(), float(cut_height or 0))
    distance_max = min(float(extent) * 1.04, np.finfo(float).max) if extent > 0 else 1.
    n = len(names)
    if horizontal:
        ax.set_xlim((distance_max, 0) if margin else (0, distance_max))
        ax.set_ylim(n, 0)
    else:
        ax.set(xlim=(0, n), ylim=(0, distance_max))
    if cut_height is not None and options.get("Show cut line", True):
        draw_cut = ax.axvline if horizontal else ax.axhline
        draw_cut(cut_height, color="#a95830", linewidth=1.15, linestyle="--", label="Cut height")
    if margin:
        ax.set_axis_off()
    else:
        ticks, names, angle = _labels_in_order(names, order, options)
        if horizontal:
            ax.set_yticks(ticks, names, rotation=angle, parse_math=False)
            ax.set(xlabel="Merge distance")
        else:
            ax.set_xticks(ticks, names, rotation=angle, parse_math=False)
            ax.set(ylabel="Merge distance")
        ax.spines[["top", "right"]].set_visible(False)
        if labels is not None:
            leaf_labels = ax.get_yticklabels() if horizontal else ax.get_xticklabels()
            for text, tick in zip(leaf_labels, ticks, strict=True):
                group = labels.iloc[order[int(tick)]]
                text.set_color(PALETTE[(group - 1) % len(PALETTE)])
    return order


def _dendrograms(fits, names, heights, options):
    horizontal = options.get("Dendrogram orientation", "Vertical") == "Horizontal"
    count = len(fits)
    n_axes = (count, 1) if horizontal else (1, count)
    fig = Figure(figsize=(8.6 if count == 2 else 7.4, 6.8 if horizontal and count == 2 else 4.8), layout="constrained")
    axes = fig.subplots(*n_axes, squeeze=False).ravel()
    for ax, (key, fit) in zip(axes, fits.items(), strict=True):
        _draw_tree(ax, fit, names[key], options, heights[key], horizontal=horizontal)
        ax.set_title(f"Dendrogram of {key.lower()}s")
    return fig


def _heat_map(fits, names, heights, options, row_names, column_names):
    fig = Figure(figsize=(8.4, 6.4), layout="constrained")
    grid = fig.add_gridspec(2, 3, height_ratios=(1.25 if "Column" in fits else .02, 5),
                           width_ratios=(1.35 if "Row" in fits else .02, 5, .22))
    ax = fig.add_subplot(grid[1, 1])
    scale = next(iter(fits.values())).scaled
    rows, cols = np.arange(len(scale)), np.arange(len(scale.columns))
    if "Row" in fits:
        tree = fig.add_subplot(grid[1, 0], sharey=ax)
        rows = _draw_tree(tree, fits["Row"], row_names, options, heights["Row"], horizontal=True, margin=True)
    if "Column" in fits:
        tree = fig.add_subplot(grid[0, 1], sharex=ax)
        cols = _draw_tree(tree, fits["Column"], column_names, options, heights["Column"], margin=True)
    raster = ax.imshow(scale.to_numpy()[np.ix_(rows, cols)], extent=(0, len(cols), len(rows), 0),
                       cmap="viridis", aspect="auto", interpolation="nearest")
    x, x_names, angle = _labels_in_order(column_names, cols, options)
    y, y_names, _ = _labels_in_order(row_names, rows, options)
    ax.set_xticks(x, x_names, rotation=angle, parse_math=False)
    ax.set_yticks(y, y_names, parse_math=False)
    fig.colorbar(raster, cax=fig.add_subplot(grid[1, 2]), label="Value")
    fig.suptitle("Hierarchical clustering · Heat map", fontweight="bold")
    return fig


def _matrix(distances, names, lower):
    values = squareform(distances)
    if lower:
        values[np.triu_indices(len(names), 1)] = np.nan
    labels = _headers(names)
    return pd.DataFrame(values, index=pd.Index(labels, name="Observation"), columns=labels)


def _merge_map(tree, names):
    """Name each child by its observation label or its earlier merge number."""
    n = len(names)
    last_leaf = list(range(n))
    labels = list(names)
    rows = []
    for step, (left, right, height, _) in enumerate(tree, 1):
        first, second = int(left), int(right)
        # The report orders children by the last source observation they contain.
        if last_leaf[first] > last_leaf[second]:
            first, second = second, first
        rows.append((step, labels[first], labels[second], height))
        last_leaf.append(last_leaf[second])
        labels.append(f"Cluster {step}")
    return pd.DataFrame(rows, columns=["Merge order", "Node 1", "Node 2", "Cophenetic distance"])


def _diagnostics(fit, names, options):
    outputs = {}
    distance = options.get("Distance matrix", False)
    coph_distance = options.get("Cophenetic distances", False)
    coph_correlation = options.get("Cophenetic correlation", False)
    if (distance or coph_distance) and len(names) > MAX_MATRIX_OBSERVATIONS:
        raise ValueError(f"Distance matrices are limited to {MAX_MATRIX_OBSERVATIONS} observations.")
    lower = options.get("Matrix format") == "Lower triangle"
    if distance:
        outputs["Distance matrix"] = _matrix(fit.distances, names, lower)
    if options.get("Merge map", False):
        outputs["Merge map"] = _merge_map(fit.tree, names)
    if coph_distance or coph_correlation:
        coph = cophenet(fit.tree)
        if coph_distance:
            outputs["Cophenetic distances"] = _matrix(coph, names, lower)
        if coph_correlation:
            value = np.nan
            if len(names) >= 3 and np.ptp(fit.distances) > 0 and np.ptp(coph) > 0:
                distances = fit.distances / fit.distances.max()
                cophenetic = coph / coph.max()
                value = float(np.clip(np.corrcoef(distances, cophenetic)[0, 1], -1, 1))
            outputs["Cophenetic correlation"] = pd.DataFrame({"Coefficient": [value]})
    return outputs


def hierarchical_result(frame, options):
    options = saved_hierarchical_options(options)
    direction = options.get("Direction", "Rows")
    axes = {"Rows": ("Row",), "Columns": ("Column",), "Rows and columns": ("Row", "Column")}.get(direction)
    if axes is None:
        raise ValueError("Select rows, columns, or both for hierarchical clustering.")
    variables = options["Variables"]
    fits, heights, names, tables = {}, {}, {}, {}
    for axis in axes:
        count, height = _cut(options, axis)
        fits[axis] = hierarchical(frame, variables, count, linkage=options.get("Linkage", "average"),
                                  metric=options.get("Distance", "euclidean"),
                                  column_scale=options.get("Scale columns", "None").lower(),
                                  row_scale=options.get("Scale rows", "None").lower(),
                                  axis=axis.lower() + "s", cut_height=height)
        heights[axis] = height
    scale = next(iter(fits.values()))
    row_names = _row_names(frame, scale, variables, options.get("Observation labels"))
    column_names = list(map(str, scale.scaled.columns))
    if options.get("Scaled data", False):
        tables["Scaled data"] = scale.scaled
    for axis, fit in fits.items():
        names[axis] = row_names if axis == "Row" else column_names
        prefix = f"{axis} " if len(axes) > 1 else ""
        if fit.labels is not None:
            label = "Cluster"
            while label in fit.data:
                label += " (assigned)"
            tables[prefix + "Assignments"] = fit.data.assign(**{label: fit.labels})
        tables[prefix + "Merges"] = pd.DataFrame(fit.tree, columns=["Node A", "Node B", "Distance", "Count"])
        tables.update({prefix + title: table for title, table in _diagnostics(fit, names[axis], options).items()})
    if options.get("Graph output") == "Heat map":
        figure = _heat_map(fits, names, heights, options, row_names, column_names)
    else:
        figure = _dendrograms(fits, names, heights, options)
    return Result(tables, figure)
