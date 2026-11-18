"""Silhouettes of a given partition, per observation and per cluster.

The analysis measures a partition that already exists in a column of the worksheet. It never fits a clustering, never
changes a label and does not depend on the settings of the K-means or hierarchical analysis that produced the column:
the distance and the scale are chosen here and reported in the summary.

Contract (Rousseeuw 1987)
    For observation i of cluster C, ``a(i)`` is the mean distance to the other members of C, ``b(i)`` is the smallest
    mean distance to the members of any other cluster, and ``s(i) = (b − a) / max(a, b)``. When ``a = b = 0`` the
    silhouette is 0. A singleton has ``s = 0`` and no ``a``; its ``b`` and nearest cluster are computed as usual. When
    several other clusters have exactly the same minimum mean distance the first one in order of appearance among the
    complete rows is the nearest. Negative values are kept. The global value is the mean over observations, so every
    cluster weighs by its size.

Input
    Rows with a missing or excluded value in a variable or in the cluster column are dropped and counted. A present
    value that is not a finite number in a variable is a field error. Cluster labels are non-blank text or finite
    numbers; the number 1 and the text "1" are different clusters (the product's typed identities), and the sheets keep
    the original values. The observation label is optional and a missing one becomes an empty string. The number of
    clusters must be between 2 and N − 1.

Scale and metric
    ``Standardize`` uses the mean and the population SD of the complete rows (a constant column becomes zero). The
    metric is Euclidean or Manhattan. Coordinates are divided by a power of two before any distance is formed, so
    squares and sums cannot overflow or underflow on an extreme scale; the reported distances are scaled back, and
    distances that cannot be represented are a field error on Variables.

Budget
    At most 5 000 complete rows and ``N² · p ≤ 200 000 000`` scalar operations, checked before any distance array is
    allocated. The graph needs at most 2 000 observations; without it the tables are available up to the budget.
    Distances are computed in blocks of B rows against all N points: one pair-wise distance per block cell and a
    reduction by cluster (``np.add.reduceat`` over the columns ordered by cluster), never a distance per cluster and
    never an N × N × p tensor. The arrays of a block take at most 32 MiB. The cancel event is read before every
    block and before the result is built.
"""
from collections import Counter
from dataclasses import dataclass
import math
import numbers

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist

from .analysis_chain import ChainCancelled
from .field_error import FieldError
from .graph_legend import typed_group_token
from .monte_carlo import MonteCarloCancelled
from .processing import _column
from .reporting import Result, _plot, _report

METHOD = "Cluster silhouette"
VARIABLES, CLUSTER, LABELS = "Variables", "Cluster", "Observation labels"
DISTANCE, STANDARDIZE, GRAPH = "Distance", "Standardize", "Graph"
EUCLIDEAN, MANHATTAN = DISTANCES = ("Euclidean", "Manhattan")
# Role strings are the ones the workbench uses ("Multiple", "Optional", None for one column).
OPTIONS = {VARIABLES: "Multiple", CLUSTER: None, LABELS: "Optional", DISTANCE: DISTANCES,
           STANDARDIZE: False, GRAPH: True}

OBSERVATIONS, CLUSTERS, SUMMARY = "Observation silhouettes", "Cluster silhouettes", "Silhouette summary"
OBSERVATION_COLUMNS = ["Source row", "Observation", "Cluster", "Within mean distance", "Nearest other cluster",
                       "Nearest mean distance", "Silhouette"]
CLUSTER_COLUMNS = ["Cluster", "N", "Mean silhouette", "Negative samples"]
ORIGINAL_UNITS = "Original units"
STANDARDIZED_UNITS = "Standardized (mean 0, population SD 1)"
INDEPENDENT_NOTE = "The distance and the scale are set here. They do not depend on the analysis that made the partition."

MAX_VARIABLES, MAX_ROWS, MAX_SCALARS, MAX_GRAPH_ROWS = 32, 5_000, 200_000_000, 2_000
BLOCK_BYTES = 32 * 2**20
MAX_CAPTIONS = 40
_METRICS = {EUCLIDEAN: "euclidean", MANHATTAN: "cityblock"}


class SilhouetteCancelled(ChainCancelled, MonteCarloCancelled):
    """The cancel event was set. It is a ChainCancelled for linked analyses and a MonteCarloCancelled for the
    desktop's calculation control, so a stopped calculation is never published."""


def requested_graph(options):
    """True when the recipe asks for the graph; the Graphs list uses it before the results are loaded."""
    return options.get(GRAPH, True) is not False


def suggest_cluster(columns):
    """The evident assignment column of a result table, or None. The user always keeps the choice.

    K-means and hierarchical results name it ``Cluster``, ``Cluster (2)`` or ``Cluster (assigned)``, after the
    variables; the last such column is the newest assignment. A plain ``Group`` is the usual hand-made partition.
    """
    names = [str(name) for name in columns]
    starts = [name for name in names if name.casefold().startswith("cluster")]
    if starts:
        return starts[-1]
    for wanted in ("assignments", "assignment", "partition", "group", "groups"):
        for name in names:
            if name.casefold() == wanted:
                return name
    return None


def default_options(frame):
    """Starting selection for a new analysis: the evident cluster column and every other numeric column."""
    cluster = suggest_cluster(frame.columns)
    numeric = [str(name) for name in frame.select_dtypes(include="number").columns if str(name) != cluster]
    chosen = {VARIABLES: numeric[:MAX_VARIABLES]} if numeric else {}
    if cluster is not None:
        chosen[CLUSTER] = cluster
    return chosen


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name} must be on or off.")
    return bool(value)


def _stop(cancel):
    if cancel is not None and cancel.is_set():
        raise SilhouetteCancelled("The silhouette calculation was cancelled.")


def _roles(frame, options):
    """Validate the column roles. Returns (variables, cluster, labels)."""
    names = options.get(VARIABLES)
    if not isinstance(names, (list, tuple)) or not names:
        raise FieldError(VARIABLES, f"Select between 1 and {MAX_VARIABLES} numeric columns for Variables.")
    if any(not isinstance(name, str) or name not in frame for name in names) or len(set(names)) != len(names):
        raise FieldError(VARIABLES, "Choose distinct existing columns for Variables.")
    if len(names) > MAX_VARIABLES:
        raise FieldError(VARIABLES, f"Select at most {MAX_VARIABLES} columns for Variables.")
    if not frame.columns.is_unique:
        raise FieldError(VARIABLES, "Worksheet column names must be unique.")
    cluster = options.get(CLUSTER)
    if not isinstance(cluster, str) or not cluster or cluster not in frame:
        raise FieldError(CLUSTER, f"Choose a column for {CLUSTER}.")
    if cluster in names:
        raise FieldError(CLUSTER, f'Column "{cluster}" is already a variable. Choose a different Cluster column.')
    labels = options.get(LABELS)
    if labels in ("", None):
        labels = None
    elif not isinstance(labels, str) or labels not in frame:
        raise FieldError(LABELS, "Choose an existing column for Observation labels, or none.")
    elif labels in names or labels == cluster:
        raise FieldError(LABELS, f'Column "{labels}" is already used. Choose a different column for Observation labels.')
    return list(names), cluster, labels


def _cluster_values(frame, name, usable):
    """Original label values of the complete rows and the typed identity of each, in row order."""
    values, tokens = [], []
    for value in frame[name].to_numpy(dtype=object)[usable]:
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, str):
            valid = bool(value.strip())
        elif isinstance(value, (bool, np.bool_)):
            valid = False
        else:
            valid = isinstance(value, numbers.Real) and math.isfinite(value)
        if not valid:
            raise FieldError(CLUSTER, f'Column "{name}" must hold cluster labels as text or finite numbers.')
        values.append(value)
        tokens.append(typed_group_token(value))
    return values, tokens


@dataclass
class Plan:
    """Everything checked before the first distance is formed."""
    variables: list
    cluster: str
    metric: str
    standardize: bool
    graph: bool
    source_rows: np.ndarray      # 1-based positions of the complete rows in the input
    matrix: np.ndarray           # complete rows × variables, as floats
    membership: np.ndarray       # cluster index of each complete row, in order of first appearance
    clusters: list               # original value of the first row of each cluster
    observations: list           # observation label of each complete row, '' when absent
    dropped: int


def prepare(frame, options):
    """Validate the request and gather the complete rows. Allocates no distance array."""
    variables, cluster, label_column = _roles(frame, options)
    metric = options.get(DISTANCE, EUCLIDEAN)
    if metric not in _METRICS:
        raise FieldError(DISTANCE, "Choose Euclidean or Manhattan.")
    standardize = _flag(options, STANDARDIZE, False)
    graph = _flag(options, GRAPH, True)
    columns = [_column(frame, name, VARIABLES).to_numpy(dtype=float) for name in variables]
    matrix = np.column_stack(columns)
    usable = ~np.isnan(matrix).any(axis=1) & frame[cluster].notna().to_numpy()
    rows = int(usable.sum())
    if rows > MAX_ROWS:
        raise FieldError(VARIABLES, f"Silhouettes use at most {MAX_ROWS} complete rows; this input has {rows}.")
    scalars = rows * rows * len(variables)
    if scalars > MAX_SCALARS:
        raise FieldError(VARIABLES, f"Rows² × variables is {scalars:,}, above the limit of {MAX_SCALARS:,}. "
                                    "Select fewer variables or use fewer rows.")
    if rows < 3:
        raise FieldError(CLUSTER, f"Silhouettes need at least 3 complete rows; this input has {rows}.")
    values, tokens = _cluster_values(frame, cluster, usable)
    index, first = {}, []
    for position, token in enumerate(tokens):
        if token not in index:
            index[token] = len(index)
            first.append(values[position])
    count = len(index)
    if not 2 <= count <= rows - 1:
        raise FieldError(CLUSTER, f"Clusters in the partition: {count}. "
                                  f"Silhouettes need between 2 and {rows - 1} clusters among {rows} complete rows.")
    if graph and rows > MAX_GRAPH_ROWS:
        raise FieldError(GRAPH, f"The graph shows at most {MAX_GRAPH_ROWS} observations; this input has {rows}. "
                                "Turn Graph off to keep the tables.")
    membership = np.fromiter((index[token] for token in tokens), dtype=np.int64, count=rows)
    if label_column is None:
        observations = [""] * rows
    else:
        found = frame[label_column]
        missing = found.isna().to_numpy()[usable]
        observations = ["" if gone else item for item, gone in zip(found.to_numpy(dtype=object)[usable], missing)]
    return Plan(variables, cluster, metric, standardize, graph, np.flatnonzero(usable) + 1, matrix[usable],
                membership, first, observations, len(frame) - rows)


def check_options(frame, options):
    """Field and budget errors for the dialog. The distances run later on the worker."""
    prepare(frame, options)


def scaled_points(matrix, standardize):
    """Coordinates of magnitude below 1, and the exponent of the power of two that restores distances.

    Dividing by a power of two is exact, so a distance of the scaled points times ``2 ** exponent`` equals the distance
    of the original ones, without squares or sums beyond the floating-point range. Standardizing removes the scale of
    each column altogether (exponent 0). A constant column becomes zero.
    """
    if not standardize:
        peak = float(np.max(np.abs(matrix)))
        if peak == 0:
            return np.zeros_like(matrix), 0
        exponent = math.frexp(peak)[1]
        return np.ldexp(matrix, -exponent), exponent
    points = np.zeros_like(matrix)
    for j in range(matrix.shape[1]):
        column = matrix[:, j]
        peak = float(np.max(np.abs(column)))
        if peak == 0 or column.min() == column.max():
            continue
        y = np.ldexp(column, -math.frexp(peak)[1])
        centered = y - y.mean()
        spread = float(np.sqrt(np.mean(centered * centered)))
        if spread > 0:
            points[:, j] = centered / spread
    return points, 0


def block_rows(rows, clusters):
    """Rows per block so that the distance block, its cluster sums and means stay within 32 MiB."""
    return max(1, BLOCK_BYTES // (8 * (rows + 2 * clusters)))


def silhouette_arrays(points, membership, clusters, metric, exponent=0, *, cancel=None, rows_per_block=None):
    """Silhouettes of ``points`` in the order of their rows. Distances are those of the scaled points.

    Returns ``(within, nearest, rival, silhouette)``: the mean distance to the own cluster (NaN for a singleton), the
    mean distance to the nearest other cluster, its index and the silhouette. Both distances are in scaled units.
    """
    rows = len(points)
    order = np.argsort(membership, kind="stable")
    ordered, labels = np.ascontiguousarray(points[order]), membership[order]
    sizes = np.bincount(membership, minlength=clusters)
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    step = rows_per_block or block_rows(rows, clusters)
    within, nearest = np.full(rows, np.nan), np.empty(rows)
    rival = np.empty(rows, dtype=np.int64)
    kernel = _METRICS[metric]
    for first in range(0, rows, step):
        _stop(cancel)
        chunk = ordered[first:first + step]
        size = len(chunk)
        distances = cdist(chunk, ordered, kernel)
        with np.errstate(over="ignore"):
            if not math.isfinite(float(np.ldexp(distances.max(), exponent))):
                raise FieldError(VARIABLES, "The distances cannot be represented with these variables.")
        sums = np.add.reduceat(distances, starts, axis=1)
        del distances
        own = labels[first:first + size]
        line = np.arange(size)
        own_sizes = sizes[own]
        # The own sum includes the zero distance of the point to itself, so the other members are n − 1.
        mean_within = np.full(size, np.nan)
        many = own_sizes > 1
        mean_within[many] = sums[line, own][many] / (own_sizes[many] - 1)
        np.divide(sums, sizes, out=sums)
        sums[line, own] = np.inf
        choice = np.argmin(sums, axis=1)  # the first of exactly tied minima, in order of appearance
        best = sums[line, choice]
        positions = order[first:first + size]
        within[positions], nearest[positions], rival[positions] = mean_within, best, choice
    _stop(cancel)
    wider = np.fmax(within, nearest)
    with np.errstate(invalid="ignore", divide="ignore"):
        silhouette = np.where(np.isnan(within) | (wider == 0), 0.0, (nearest - within) / wider)
    return within, nearest, rival, silhouette


def _restore(values, exponent):
    """Distances back in the units of the variables; a distance that cannot be represented is a field error."""
    if exponent == 0:
        return values
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        restored = np.ldexp(values, exponent)
    broken = (np.isfinite(values) & ~np.isfinite(restored)) | ((values > 0) & (restored == 0))
    if broken.any():
        raise FieldError(VARIABLES, "The distances cannot be represented with these variables.")
    return restored


def _text(value):
    return repr(value) if isinstance(value, float) else str(value)


def captions(values):
    """Distinct display texts for the cluster labels. Equal texts of different identities are told apart."""
    texts = [_text(value) for value in values]
    totals = Counter(texts)
    result = [f"{text} ({'text' if isinstance(value, str) else 'number'})" if totals[text] > 1 else text
              for value, text in zip(values, texts)]
    again = Counter(result)
    seen = Counter()
    for position, text in enumerate(result):
        if again[text] > 1:
            seen[text] += 1
            result[position] = f"{text} #{seen[text]}"
    return result


def _literal(text):
    """Keep a dollar sign as text. Matplotlib would otherwise read it as math."""
    return str(text).replace("$", r"\$")


def silhouette_figure(names, sizes, order_by_cluster, silhouette, mean, distance, scaled):
    """Horizontal bars on [−1, 1]: one block per cluster in sheet order, bars from the lowest silhouette up."""
    count = len(names)
    rows = int(sum(sizes))
    gap = max(2, math.ceil(.02 * rows))
    total = rows + gap * (count - 1)
    figure, axes = _plot("Silhouette by observation", "Silhouette", "Cluster")
    figure.set_size_inches(8, min(14, max(5, 3 + .1 * total)))
    base = 0
    blocks = []
    for position in range(count - 1, -1, -1):
        blocks.append((position, base))
        base += sizes[position] + gap
    placed = {position: origin for position, origin in blocks}
    centres = []
    for position in range(count):
        members = order_by_cluster[position]
        heights = placed[position] + np.arange(len(members))
        axes.barh(heights, silhouette[members], height=.9, label=_literal(names[position]))
        centres.append(placed[position] + (len(members) - 1) / 2)
    axes.axvline(0, color="#333333", linewidth=.8)
    axes.axvline(mean, color="#bb5b3a", linestyle="--", linewidth=1.2, label=f"Mean silhouette {mean:.3f}")
    axes.set_xlim(-1, 1)
    axes.set_ylim(-1.5, total + .5)
    stride = max(1, math.ceil(count / MAX_CAPTIONS))
    shown = list(range(0, count, stride))
    axes.set_yticks([centres[position] for position in shown],
                    [_literal(f"{names[position]}\nn = {sizes[position]}") if stride == 1 else _literal(names[position])
                     for position in shown])
    if stride > 1:
        axes.set_ylabel(f"Cluster (every {stride}th of {count} labelled)")
    axes.legend(handles=[line for line in axes.lines if line.get_label().startswith("Mean")], loc="lower right",
                fontsize=8)
    axes.set_title(f"Silhouette by observation ({distance}, {'standardized' if scaled else 'original units'})")
    axes._tramastat_numeric_axes = ("x",)
    axes._tramastat_categorical_axes = ("y",)
    return figure


def cluster_silhouette(frame, options, *, cancel=None):
    """Silhouettes of the partition in a column. ``cancel`` is an Event the worker checks between blocks."""
    _stop(cancel)
    plan = prepare(frame, options)
    points, exponent = scaled_points(plan.matrix, plan.standardize)
    count = len(plan.clusters)
    within, nearest, rival, silhouette = silhouette_arrays(
        points, plan.membership, count, plan.metric, exponent, cancel=cancel)
    within_units, nearest_units = _restore(within, exponent), _restore(nearest, exponent)
    rows = len(points)
    mean = float(silhouette.mean())
    table = pd.DataFrame({
        "Source row": plan.source_rows.astype(np.int64),
        "Observation": pd.Series(plan.observations, dtype=object),
        "Cluster": pd.Series([plan.clusters[group] for group in plan.membership], dtype=object),
        "Within mean distance": within_units,
        "Nearest other cluster": pd.Series([plan.clusters[group] for group in rival], dtype=object),
        "Nearest mean distance": nearest_units,
        "Silhouette": silhouette,
    })
    sizes = np.bincount(plan.membership, minlength=count)
    per_cluster = [np.flatnonzero(plan.membership == group) for group in range(count)]
    summary = pd.DataFrame({
        "Cluster": pd.Series(plan.clusters, dtype=object),
        "N": sizes.astype(np.int64),
        "Mean silhouette": [float(silhouette[members].mean()) for members in per_cluster],
        "Negative samples": np.array([int((silhouette[members] < 0).sum()) for members in per_cluster], dtype=np.int64),
    })
    report = _report({
        "N": rows, "Clusters": count, "Dropped rows": plan.dropped, "Mean silhouette": mean,
        "Negative samples": int((silhouette < 0).sum()),
        "Distance": plan.metric, "Scale": STANDARDIZED_UNITS if plan.standardize else ORIGINAL_UNITS,
        "Variables": ", ".join(plan.variables), "Cluster column": plan.cluster, "Note": INDEPENDENT_NOTE,
    })
    figure = None
    if plan.graph:
        names = captions(plan.clusters)
        ordered = [members[np.lexsort((plan.source_rows[members], silhouette[members]))] for members in per_cluster]
        figure = silhouette_figure(names, [int(size) for size in sizes], ordered, silhouette, mean, plan.metric,
                                   plan.standardize)
    _stop(cancel)
    return Result({OBSERVATIONS: table, CLUSTERS: summary, SUMMARY: report}, figure)
