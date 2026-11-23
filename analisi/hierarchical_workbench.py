"""Options, diagnostics and plots for a fitted hierarchical clustering tree."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from scipy.cluster.hierarchy import cophenet
from scipy.spatial.distance import pdist, squareform

from .analysis_chain import RESULT_CONTEXT
from .data import _headers
from .field_error import FieldError
from .hierarchical_gap import (GAP_DATA, GAP_OPTIONS, GAP_PLOT, check_gap_cancel, check_gap_settings,
                               gap_data, wcss_by_cut)
from .hierarchical_style import bind_matrix_labels, register_heatmap, register_tree, set_leaf_ticks
from .leaf_order import (CHOICES as LEAF_ORDER_CHOICES, FIELD as LEAF_ORDERING, OPTIMAL, check_cancel, check_mode,
                         check_size, order_leaves)
from .monte_carlo import MonteCarloCancelled
from .reporting import Result
from .stats import hierarchical


DIRECTIONS = {"Rows": ("Row",), "Columns": ("Column",), "Rows and columns": ("Row", "Column")}
CUT_MODES = ("Count", "Cut height", "No cut")
SCALES = ("None", "Center", "Standardize")
SILHOUETTE_DATA = "Silhouette data"
SILHOUETTE_PLOT = "Silhouette plot"
CLUSTERED_DATA_PLOT = "Clustered data plot"
HIERARCHICAL_OPTIONS = {
    "Direction": tuple(DIRECTIONS),
    "Scale columns": ("Standardize", "None", "Center"),
    "Scale rows": SCALES,
    "Linkage": ("average", "complete", "single", "ward", "weighted", "centroid", "median"),
    "Distance": ("euclidean", "cityblock", "chebyshev", "cosine", "correlation"),
    LEAF_ORDERING: LEAF_ORDER_CHOICES,
    "Row cut": CUT_MODES, "Clusters": 2, "Row cut height": 1.0,
    "Column cut": CUT_MODES, "Column clusters": 2, "Column cut height": 1.0,
    "Graph output": ("Dendrogram", "Heat map", CLUSTERED_DATA_PLOT, "Elbow plot", SILHOUETTE_PLOT, GAP_PLOT),
    "Dendrogram orientation": ("Vertical", "Horizontal"),
    "Branch appearance": ("By cluster", "Single color"),
    "Branch width": 1.4, "Branch style": ("Solid", "Dashed", "Dotted"), "Branch opacity (%)": 100.0,
    "Label type": ("Values", "Numbers", "Letters"),
    "First label": 1, "Label interval (0 = automatic)": 0,
    "Label angle": 0.0, "Show cut line": True,
    "Scaled data": False, "Distance matrix": False, "Merge map": False, "Cophenetic distances": False,
    "Cophenetic correlation": False, "Elbow data": False, SILHOUETTE_DATA: False,
    GAP_DATA: False, **GAP_OPTIONS,
    "Matrix format": ("Full", "Lower triangle"),
}
HIERARCHICAL_TABS = {
    "Clusters": ("Row cut", "Clusters", "Row cut height", "Column cut", "Column clusters", "Column cut height"),
    "Graph": ("Graph output", "Dendrogram orientation", "Branch appearance", "Label type",
              "Branch width", "Branch style", "Branch opacity (%)", "First label",
              "Label interval (0 = automatic)", "Label angle", "Show cut line"),
    "Output": ("Scaled data", "Distance matrix", "Merge map", "Cophenetic distances",
               "Cophenetic correlation", "Elbow data", SILHOUETTE_DATA, GAP_DATA, *GAP_OPTIONS, "Matrix format"),
}
HIERARCHY_GRAPH = "Hierarchy graph"
TREE_AXIS = "Hierarchy axis"
ALL_TREES = "All fitted axes"
HIERARCHY_GRAPH_OPTIONS = {
    "Graph output": HIERARCHICAL_OPTIONS["Graph output"],
    TREE_AXIS: (ALL_TREES, "Rows", "Columns"),
    **{key: HIERARCHICAL_OPTIONS[key] for key in HIERARCHICAL_TABS["Graph"] if key != "Graph output"},
}
PALETTE = ("#156978", "#b65a39", "#5b5aa7", "#36815b", "#a77b25", "#b34c73", "#456e9a", "#626b35")
MIXED_BRANCH = "#637584"
MAX_MATRIX_OBSERVATIONS = 512


@dataclass(frozen=True, eq=False)
class _Tree:
    tree: np.ndarray
    labels: pd.Series | None
    layout: np.ndarray | None = None  # the same tree with children swapped to draw an optimal leaf order


@dataclass(frozen=True, eq=False)
class _HierarchyView:
    trees: dict[str, _Tree]
    names: dict[str, list[str]]
    heights: dict[str, float | None]
    scaled: pd.DataFrame
    raw: pd.DataFrame
    row_names: list[str]
    column_names: list[str]
    metric: str
    silhouettes: dict[str, pd.DataFrame]
    linkage: str
    gap_options: dict[str, int]
    gaps: dict[str, pd.DataFrame]


@dataclass(frozen=True)
class AssignmentCoordinates:
    features: tuple[tuple[str, str], ...]
    observations: tuple[str, ...]
    group: str


def uses_hierarchy_silhouette(method, options):
    plot = options.get("Graph output") == SILHOUETTE_PLOT
    if method == "Hierarchical clustering":
        return plot or options.get(SILHOUETTE_DATA, False)
    return method == HIERARCHY_GRAPH and plot


def uses_hierarchy_gap(method, options):
    plot = options.get("Graph output") == GAP_PLOT
    if method == "Hierarchical clustering":
        return plot or options.get(GAP_DATA, False)
    return method == HIERARCHY_GRAPH and plot


def hierarchy_view_available(frame):
    return isinstance(frame.attrs.get(RESULT_CONTEXT), _HierarchyView)


def check_hierarchy_view(frame, options):
    view = frame.attrs.get(RESULT_CONTEXT)
    if not isinstance(view, _HierarchyView):
        raise FieldError("Graph output", "Choose a linked Merges result from hierarchical clustering.")
    output = options.get("Graph output", "Dendrogram")
    if output not in HIERARCHY_GRAPH_OPTIONS["Graph output"]:
        raise FieldError("Graph output", "Choose a hierarchy graph type.")
    if output != "Heat map":
        axis = options.get(TREE_AXIS, ALL_TREES)
        if axis != ALL_TREES and not any(axis == key + "s" for key in view.trees):
            raise FieldError(TREE_AXIS, "Choose an axis fitted by the source hierarchy.")
        if output == CLUSTERED_DATA_PLOT:
            selected = view.trees.values() if axis == ALL_TREES else (view.trees[axis[:-1]],)
            if not any(tree.labels is not None for tree in selected):
                raise FieldError(TREE_AXIS, "Choose an axis with clusters defined by count or height.")
    if output == GAP_PLOT:
        check_gap_settings(view.gap_options)
    return view


def saved_hierarchical_options(options):
    """Older recipes used raw columns unless standardization was explicitly enabled."""
    if not options or "Scale columns" in options:
        return options
    return {**options, "Scale columns": "Standardize" if options.get("Standardize") else "None"}


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


def _leaf_label_texts(names, order, options):
    """Every leaf caption in dendrogram order. The fit chooses the text; the style only hides some."""
    mode = options.get("Label type", "Values")
    if mode == "Letters":
        return tuple(_letter(index + 1) for index in range(len(order)))
    if mode == "Numbers":
        return tuple(str(index + 1) for index in range(len(order)))
    return tuple(names[index] for index in order)


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


def _draw_tree(ax, fit, names, options, cut_height, *, horizontal=False, margin=False, component=None):
    labels = fit.labels if options.get("Branch appearance", "By cluster") == "By cluster" else None
    drawn = fit.tree if fit.layout is None else fit.layout
    order, paths, groups = _coordinates(drawn, labels)
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
        ticks, captions, angle = _labels_in_order(names, order, options)
        auto_labels = options.get("Label interval (0 = automatic)", 0) == 0
        leaf_labels = set_leaf_ticks(ax, "y" if horizontal else "x", ticks, captions,
                                     automatic=auto_labels, fit_preview=True, rotation=angle)
        if horizontal:
            ax.set_xlabel("Merge distance")
        else:
            ax.set_ylabel("Merge distance")
        ax.spines[["top", "right"]].set_visible(False)
        if labels is not None:
            for text, tick in zip(leaf_labels, ticks, strict=True):
                group = labels.iloc[order[int(tick)]]
                text.set_color(PALETTE[(group - 1) % len(PALETTE)])
    if component in ("row", "column"):
        cluster_ids = None if fit.labels is None else tuple(int(value) for value in np.asarray(fit.labels))
        label_colors = None
        if labels is not None:
            label_colors = tuple(PALETTE[(int(labels.iloc[leaf]) - 1) % len(PALETTE)] for leaf in order)
        register_tree(
            ax.figure, component, ax, lines, horizontal=horizontal, margin=margin, order=order,
            cluster_ids=cluster_ids, children=drawn[:, :2],
            leaf_labels=_leaf_label_texts(names, order, options), label_colors=label_colors, options=options,
            palette=PALETTE, mixed_color=MIXED_BRANCH)
    return order


def _dendrograms(fits, names, heights, options):
    horizontal = options.get("Dendrogram orientation", "Vertical") == "Horizontal"
    count = len(fits)
    n_axes = (count, 1) if horizontal else (1, count)
    fig = Figure(figsize=(8.6 if count == 2 else 7.4, 6.8 if horizontal and count == 2 else 4.8), layout="constrained")
    axes = fig.subplots(*n_axes, squeeze=False).ravel()
    for ax, (key, fit) in zip(axes, fits.items(), strict=True):
        _draw_tree(ax, fit, names[key], options, heights[key], horizontal=horizontal, component=key.lower())
        ax.set_title(f"Dendrogram of {key.lower()}s")
    return fig


def _heat_map(fits, heights, options, scale, row_names, column_names):
    fig = Figure(figsize=(8.4, 6.4), layout="constrained")
    grid = fig.add_gridspec(2, 3, height_ratios=(1.25 if "Column" in fits else .02, 5),
                           width_ratios=(1.35 if "Row" in fits else .02, 5, .22))
    ax = fig.add_subplot(grid[1, 1])
    rows, cols = np.arange(len(scale)), np.arange(len(scale.columns))
    if "Row" in fits:
        tree = fig.add_subplot(grid[1, 0], sharey=ax)
        rows = _draw_tree(tree, fits["Row"], row_names, options, heights["Row"], horizontal=True, margin=True,
                          component="row")
    if "Column" in fits:
        tree = fig.add_subplot(grid[0, 1], sharex=ax)
        cols = _draw_tree(tree, fits["Column"], column_names, options, heights["Column"], margin=True,
                          component="column")
    raster = ax.imshow(scale.to_numpy()[np.ix_(rows, cols)], extent=(0, len(cols), len(rows), 0),
                       cmap="viridis", aspect="auto", interpolation="nearest")
    x, x_names, angle = _labels_in_order(column_names, cols, options)
    y, y_names, _ = _labels_in_order(row_names, rows, options)
    auto_labels = options.get("Label interval (0 = automatic)", 0) == 0
    set_leaf_ticks(ax, "x", x, x_names, automatic=auto_labels, fit_preview=True, rotation=angle)
    set_leaf_ticks(ax, "y", y, y_names, automatic=auto_labels, fit_preview=True)
    colorbar = fig.colorbar(raster, cax=fig.add_subplot(grid[1, 2]), label="Value")
    register_heatmap(fig, ax, raster, colorbar)
    captions = {}
    if "Row" not in fits:
        captions["row"] = _leaf_label_texts(row_names, rows, options)
    if "Column" not in fits:
        captions["column"] = _leaf_label_texts(column_names, cols, options)
    bind_matrix_labels(fig, ax, captions, options)
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


def _elbow_data(tree, observations):
    costs = wcss_by_cut(tree, observations)
    if not np.isfinite(costs).all():
        raise ValueError("Elbow data require finite within-cluster sums of squares.")
    return pd.DataFrame({"Number of clusters": np.arange(1, len(observations)), "WCSS": costs})


def _check_silhouette_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise MonteCarloCancelled("Hierarchical silhouette cancelled.")


def _silhouette_data(tree, distances, cancel):
    """Update the per-observation means as each pair of clusters joins."""
    _check_silhouette_cancelled(cancel)
    n = len(tree) + 1
    scores = np.full(n - 1, np.nan)  # With one cluster the nearest alternative is undefined.
    if n > 2:
        means = squareform(distances)
        points = np.arange(n)
        owner = points.copy()
        nodes = points.copy()
        slots = np.empty(2 * n - 1, dtype=int)
        slots[:n] = points
        sizes = np.ones(n, dtype=int)
        for node, (left, right, _, _) in enumerate(tree[:-1], n):
            k = 2 * n - node - 1
            _check_silhouette_cancelled(cancel)
            first, second = sorted((slots[int(left)], slots[int(right)]))
            sizes[first] += sizes[second]
            means[:, first] += (means[:, second] - means[:, first]) * (sizes[second] / sizes[first])
            owner[owner == second] = first
            # Reuse the removed cluster's slot so only the leading k columns are active.
            if second != k:
                means[:, second] = means[:, k]
                sizes[second], nodes[second] = sizes[k], nodes[k]
                slots[nodes[second]] = second
                owner[owner == k] = second
            nodes[first], slots[node] = node, first

            own = means[points, owner]
            means[points, owner] = np.inf
            other = means[:, :k].min(axis=1)
            means[points, owner] = own
            members = sizes[owner]
            # Form the ratio in local units before adjusting for the zero self-distance.
            scale = np.maximum(own, other)
            within = np.divide(own, scale, out=np.zeros(n), where=scale > 0)
            within *= np.divide(members, members - 1, out=np.zeros(n), where=members > 1)
            between = np.divide(other, scale, out=np.zeros(n), where=scale > 0)
            denominator = np.maximum(within, between)
            values = np.divide(between - within, denominator, out=np.zeros(n),
                               where=(members > 1) & (denominator > 0))
            scores[k - 1] = values.mean()
    _check_silhouette_cancelled(cancel)
    return pd.DataFrame({"Number of clusters": np.arange(1, n), "Mean silhouette": scores})


def _cluster_count_plot(reports, output):
    silhouette = output == SILHOUETTE_PLOT
    gap = output == GAP_PLOT
    metric = "Gap" if gap else "Mean silhouette" if silhouette else "WCSS"
    figure = Figure(figsize=(8.6 if len(reports) == 2 else 7.4, 4.8), layout="constrained")
    axes = figure.subplots(1, len(reports), squeeze=False).ravel()
    for ax, (axis, table) in zip(axes, reports.items(), strict=True):
        counts = table["Number of clusters"]
        if gap:
            ax.errorbar(counts, table[metric], yerr=table["Gap SE"].to_numpy(), fmt="o-", markersize=3)
            chosen = table.loc[table["Recommended"]]
            if not chosen.empty:
                ax.scatter(chosen["Number of clusters"], chosen[metric], color="#b65a39", zorder=4)
                ax.axvline(chosen["Number of clusters"].iat[0], color="#b65a39", linewidth=0.8, zorder=0)
        else:
            ax.plot(counts, table[metric], marker="o", markersize=3)
        ax.set(title=f"{output} ({axis.lower()}s)", xlabel="Number of clusters", ylabel=metric)
        if silhouette or gap:
            ax.set_xlim(0.8, max(1.2, len(table) + 0.2))
            ax.xaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=1, prune="both"))
        if silhouette:
            ax.set_ylim(-1.05, 1.05)
            ax.axhline(0, color="#637584", linewidth=0.8, zorder=0)
        ax.spines[["top", "right"]].set_visible(False)
    return figure


def _clustered_data_plot(trees, raw, row_names, column_names):
    cuts = [(axis, tree.labels.to_numpy()) for axis, tree in trees.items() if tree.labels is not None]
    figure = Figure(figsize=(8.6 if len(cuts) == 2 else 7.4, 4.8), layout="constrained")
    axes = figure.subplots(1, len(cuts), squeeze=False).ravel()
    for ax, (axis, groups) in zip(axes, cuts, strict=True):
        points, features = (raw, column_names) if axis == "Row" else (raw.T, row_names)
        x, y = ((points.iloc[:, 0], points.iloc[:, 1]) if len(features) > 1
                else (groups, points.iloc[:, 0]))
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        cluster_ids = np.unique(groups)
        if len(cluster_ids) <= 2 * len(PALETTE):
            for index, group in enumerate(cluster_ids):
                selected = groups == group
                ax.scatter(x[selected], y[selected], s=25, color=PALETTE[index % len(PALETTE)],
                           marker="o" if index < len(PALETTE) else "D", label=f"Cluster {group}")
            if len(features) > 1:
                ax.legend(title="Cluster", fontsize="small", ncols=2 if len(cluster_ids) > 8 else 1)
        elif len(features) > 1:
            points_artist = ax.scatter(x, y, c=groups, s=22, cmap="viridis")
            scale = figure.colorbar(points_artist, ax=ax, label="Cluster", ticks=MaxNLocator(integer=True))
            scale.solids.set_rasterized(False)
        else:
            ax.scatter(x, y, c=groups, s=22, cmap="viridis")

        x_label, y_label = features[:2] if len(features) > 1 else ("Cluster", features[0])
        ax.set(title=f"Clustered data ({axis.lower()}s)", xlabel=x_label, ylabel=y_label)
        for label in (ax.xaxis.label, ax.yaxis.label):
            label.set_parse_math(False)
        if len(features) == 1:
            ax.xaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=1))
        ax.spines[["top", "right"]].set_visible(False)
    return figure


def hierarchy_graph(frame, options, *, cancel=None):
    view = check_hierarchy_view(frame, options)
    output = options.get("Graph output", "Dendrogram")
    if output == "Heat map":
        return Result({}, _heat_map(view.trees, view.heights, options, view.scaled,
                                    view.row_names, view.column_names))
    axis = options.get(TREE_AXIS, ALL_TREES)
    trees = view.trees if axis == ALL_TREES else {axis[:-1]: view.trees[axis[:-1]]}
    if output == CLUSTERED_DATA_PLOT:
        return Result({}, _clustered_data_plot(trees, view.raw, view.row_names, view.column_names))
    if output == "Elbow plot":
        values = view.scaled.to_numpy()
        reports = {key: _elbow_data(fit.tree, values if key == "Row" else values.T)
                   for key, fit in trees.items()}
        return Result({}, _cluster_count_plot(reports, output))
    if output == SILHOUETTE_PLOT:
        values = view.scaled.to_numpy()
        reports = {}
        for key, fit in trees.items():
            _check_silhouette_cancelled(cancel)
            if key in view.silhouettes:
                reports[key] = view.silhouettes[key]
            else:
                points = values if key == "Row" else values.T
                reports[key] = _silhouette_data(fit.tree, pdist(points, metric=view.metric), cancel)
        return Result({}, _cluster_count_plot(reports, output))
    if output == GAP_PLOT:
        settings = check_gap_settings(view.gap_options)
        values = view.scaled.to_numpy()
        reports = {}
        for key, fit in trees.items():
            check_gap_cancel(cancel)
            if key in view.gaps:
                reports[key] = view.gaps[key]
            else:
                points = values if key == "Row" else values.T
                reports[key] = gap_data(fit.tree, points, view.metric, view.linkage, settings, cancel)
        return Result({}, _cluster_count_plot(reports, output))
    return Result({}, _dendrograms(trees, view.names, view.heights, options))


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


def _leaf_orders(fits, names, cancel):
    """The optimal leaf order of every fitted axis: layouts, one report each and the costs. Nothing is refitted."""
    layouts, tables, costs = {}, {}, []
    for axis, fit in fits.items():
        check_cancel(cancel)
        layouts[axis], tables[f"{axis} leaf order"], before, after = order_leaves(fit, names[axis], cancel=cancel)
        costs.append((axis, len(names[axis]), before, after))
    tables["Leaf order costs"] = pd.DataFrame(costs, columns=["Axis", "Leaves", "Original cost", "Final cost"])
    return layouts, tables


def check_leaf_options(frame, options):
    """The cheap checks of the dialog: the choice and the size of every axis, before any worker starts."""
    if check_mode(options) != OPTIMAL:
        return
    direction = options.get("Direction", "Rows")
    variables = options.get("Variables") or []
    if direction in ("Rows", "Rows and columns") and variables and all(name in frame.columns for name in variables):
        check_size(int(frame[list(variables)].notna().all(axis=1).sum()))
    if direction in ("Columns", "Rows and columns"):
        check_size(len(variables))


def _check_clustered_data_cut(options, axes):
    if (options.get("Graph output") == CLUSTERED_DATA_PLOT
            and all(options.get(f"{axis} cut", "Count") == "No cut" for axis in axes)):
        raise FieldError("Graph output", "Define clusters by count or height to plot clustered data.")


def check_hierarchical_options(frame, options):
    check_leaf_options(frame, options)
    _check_clustered_data_cut(options, DIRECTIONS.get(options.get("Direction", "Rows"), ()))
    if uses_hierarchy_gap("Hierarchical clustering", options):
        check_gap_settings(options)


def hierarchical_result(frame, options, *, cancel=None):
    options = saved_hierarchical_options(options)
    direction = options.get("Direction", "Rows")
    axes = DIRECTIONS.get(direction)
    if axes is None:
        raise ValueError("Select rows, columns, or both for hierarchical clustering.")
    _check_clustered_data_cut(options, axes)
    ordering = check_mode(options)
    variables = options["Variables"]
    metric = options.get("Distance", "euclidean")
    method = options.get("Linkage", "average")
    gap_options = {key: options.get(key, default) for key, default in GAP_OPTIONS.items()}
    gap_settings = check_gap_settings(gap_options) if uses_hierarchy_gap("Hierarchical clustering", options) else None
    fits, heights, tables = {}, {}, {}
    for axis in axes:
        check_cancel(cancel)
        count, height = _cut(options, axis)
        fits[axis] = hierarchical(frame, variables, count, linkage=method,
                                  metric=metric,
                                  column_scale=options.get("Scale columns", "None").lower(),
                                  row_scale=options.get("Scale rows", "None").lower(),
                                  axis=axis.lower() + "s", cut_height=height)
        heights[axis] = height
        if ordering == OPTIMAL:
            check_size(len(fits[axis].tree) + 1)  # before any matrix of the ordering exists
    scale = next(iter(fits.values()))
    raw = scale.data if "Row" in fits else scale.data.T
    row_names = _row_names(frame, scale, variables, options.get("Observation labels"))
    column_names = list(map(str, scale.scaled.columns))
    names = {axis: row_names if axis == "Row" else column_names for axis in fits}
    graph_output = options.get("Graph output", "Dendrogram")
    elbow_reports, silhouettes, gaps = {}, {}, {}
    contexts = {}
    layouts, leaf_tables = _leaf_orders(fits, names, cancel) if ordering == OPTIMAL else ({}, {})
    check_cancel(cancel)
    if options.get("Scaled data", False):
        tables["Scaled data"] = scale.scaled
    for axis, fit in fits.items():
        prefix = f"{axis} " if len(axes) > 1 else ""
        if fit.labels is not None:
            label = "Cluster"
            while label in fit.data:
                label += " (assigned)"
            name = prefix + "Assignments"
            tables[name] = fit.data.assign(**{label: fit.labels})
            features = column_names if axis == "Row" else row_names
            contexts[name] = AssignmentCoordinates(tuple(zip(features, map(str, fit.data.columns), strict=True)),
                                                   tuple(names[axis]), label)
        tables[prefix + "Merges"] = pd.DataFrame(fit.tree, columns=["Node A", "Node B", "Distance", "Count"])
        tables.update({prefix + title: table for title, table in _diagnostics(fit, names[axis], options).items()})
        scaled = fit.scaled.to_numpy()
        observations = scaled if axis == "Row" else scaled.T
        if options.get("Elbow data", False) or graph_output == "Elbow plot":
            elbow_reports[axis] = _elbow_data(fit.tree, observations)
            tables[prefix + "Elbow data"] = elbow_reports[axis]
        if options.get(SILHOUETTE_DATA, False) or graph_output == SILHOUETTE_PLOT:
            silhouettes[axis] = _silhouette_data(fit.tree, fit.distances, cancel)
            tables[prefix + SILHOUETTE_DATA] = silhouettes[axis]
        if gap_settings is not None:
            gaps[axis] = gap_data(fit.tree, observations, metric, method, gap_settings, cancel)
            tables[prefix + GAP_DATA] = gaps[axis]
    tables.update(leaf_tables)
    trees = {axis: _Tree(fit.tree, fit.labels, layouts.get(axis)) for axis, fit in fits.items()}
    if graph_output == "Heat map":
        figure = _heat_map(trees, heights, options, scale.scaled, row_names, column_names)
    elif graph_output == CLUSTERED_DATA_PLOT:
        figure = _clustered_data_plot(trees, raw, row_names, column_names)
    elif graph_output == "Elbow plot":
        figure = _cluster_count_plot(elbow_reports, graph_output)
    elif graph_output == SILHOUETTE_PLOT:
        figure = _cluster_count_plot(silhouettes, graph_output)
    elif graph_output == GAP_PLOT:
        figure = _cluster_count_plot(gaps, graph_output)
    else:
        figure = _dendrograms(trees, names, heights, options)
    check_cancel(cancel)
    view = _HierarchyView(trees, names, heights, scale.scaled, raw, row_names, column_names, metric, silhouettes,
                          method, gap_options, gaps)
    contexts.update({name: view for name in ("Merges", "Row Merges", "Column Merges") if name in tables})
    return Result(tables, figure, table_contexts=contexts)
