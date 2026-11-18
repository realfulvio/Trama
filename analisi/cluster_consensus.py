"""Seventeen internal validity indices and their consensus vote for k-means.

The partition indices use condensed Euclidean distances in the fitting scale.
``w`` holds the distances between pairs in the same cluster and ``b`` the
distances between pairs in different clusters. An index that meets a zero
denominator or a non-finite result is left empty and may abstain.

Only k >= 2 can receive votes. A k = 1 fit can still supply the WSS that an
index needs for k - 1. Indices built from differences use only k values that
are actually consecutive and valid.
"""
from collections import Counter

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist, pdist, squareform

BALL_HALL = "Ball–Hall"
C_INDEX = "C index"
CALINSKI = "Calinski–Harabasz"
DAVIES_RMS = "Davies–Bouldin (RMS)"
DUNN = "Dunn"
FREY = "Frey"
GAMMA = "Gamma"
GAP = "Gap"
GPLUS = "GPlus"
HARTIGAN = "Hartigan"
KRZANOWSKI_LAI = "Krzanowski–Lai"
WSS_DROP_RATIO = "WSS-drop ratio"
KL_SCALING = "Krzanowski–Lai scaling"
DIMENSION_ADJUSTED, UNSCALED_WSS = "Dimension-adjusted", "Unscaled WSS"
KL_CHOICES = (DIMENSION_ADJUSTED, UNSCALED_WSS)
MCCLAIN_RAO = "McClain–Rao"
POINT_BISERIAL = "Point-biserial"
RATKOWSKY = "Ratkowsky"
SILHOUETTE = "Silhouette"
TAU = "Tau"
TRACE_W = "Trace W"

INDEX_COLUMNS = (BALL_HALL, C_INDEX, CALINSKI, DAVIES_RMS, DUNN, FREY, GAMMA, GAP, GPLUS, HARTIGAN,
                 KRZANOWSKI_LAI, MCCLAIN_RAO, POINT_BISERIAL, RATKOWSKY, SILHOUETTE, TAU, TRACE_W)
# Mean within and between distances feed Frey; they stay out of the displayed table.
MEAN_WITHIN = "Mean within distance"
MEAN_BETWEEN = "Mean between distance"

RULES = {
    BALL_HALL: "Largest absolute change between consecutive k; right k",
    C_INDEX: "Minimum",
    CALINSKI: "Maximum",
    DAVIES_RMS: "Minimum",
    DUNN: "Maximum",
    FREY: "First k with ratio < 1",
    GAMMA: "Maximum",
    GAP: "First k with Gap(k) ≥ Gap(k+1) − SE(k+1)",
    GPLUS: "Minimum",
    HARTIGAN: "Largest positive drop between consecutive k; right k",
    KRZANOWSKI_LAI: "Maximum",
    MCCLAIN_RAO: "Minimum",
    POINT_BISERIAL: "Maximum",
    RATKOWSKY: "Maximum",
    SILHOUETTE: "Maximum",
    TAU: "Maximum",
    TRACE_W: "Largest positive second difference of WSS; middle k",
}
_MAXIMUM = {CALINSKI, DUNN, GAMMA, KRZANOWSKI_LAI, POINT_BISERIAL, RATKOWSKY, SILHOUETTE, TAU}
_MINIMUM = {C_INDEX, DAVIES_RMS, GPLUS, MCCLAIN_RAO}


def _finite(value):
    value = float(value)
    return value if np.isfinite(value) else np.nan


def _ratio(numerator, denominator):
    if denominator == 0 or not np.isfinite(denominator):
        return np.nan
    return _finite(numerator / denominator)


def _check_values(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or len(values) < 2 or values.shape[1] < 1:
        raise ValueError("Cluster indices need a matrix with at least two observations.")
    if not np.isfinite(values).all():
        raise ValueError("Cluster indices need finite values; remove missing observations first.")
    return values


class PairDistances:
    """Condensed distances between all observations, sorted once for every k."""

    def __init__(self, values):
        values = _check_values(values)
        self.n = len(values)
        self.distances = pdist(values)
        self.count = len(self.distances)
        index_type = np.int32 if self.n < 2**31 else np.int64
        rows, columns = np.triu_indices(self.n, 1)
        self.rows, self.columns = rows.astype(index_type), columns.astype(index_type)
        self.order = np.argsort(self.distances, kind="stable")
        self.sorted = self.distances[self.order]
        self.sd = float(self.distances.std(ddof=1)) if self.count > 1 else np.nan

    def split(self, labels):
        """Return within distances and sorted between distances for one partition."""
        labels = np.asarray(labels)
        if labels.shape != (self.n,):
            raise ValueError("Provide one cluster label per observation.")
        same = labels[self.rows] == labels[self.columns]
        return self.distances[same], self.sorted[~same[self.order]]


def concordance(within, between_sorted):
    """Count pairs (w, b) with w < b (C) and with w > b (D), ignoring ties."""
    within = np.asarray(within, dtype=float)
    between_sorted = np.asarray(between_sorted, dtype=float)
    smaller = np.searchsorted(between_sorted, within, side="left")
    larger = len(between_sorted) - np.searchsorted(between_sorted, within, side="right")
    return int(larger.sum(dtype=np.int64)), int(smaller.sum(dtype=np.int64))


def silhouette(square, labels):
    """Mean silhouette from a square distance matrix; a singleton scores zero."""
    labels = np.unique(np.asarray(labels), return_inverse=True)[1]
    count = labels.max() + 1
    if count < 2:
        return np.nan
    sizes = np.bincount(labels, minlength=count)
    sums = np.stack([square[:, labels == group].sum(axis=1) for group in range(count)], axis=1)
    rows = np.arange(len(labels))
    own = sizes[labels]
    within = np.divide(sums[rows, labels], own - 1, out=np.zeros(len(labels)), where=own > 1)
    means = sums / sizes
    means[rows, labels] = np.inf
    between = means.min(axis=1)
    denominator = np.maximum(within, between)
    scores = np.divide(between - within, denominator, out=np.zeros(len(labels)),
                       where=(own > 1) & (denominator > 0))
    return float(scores.mean())


def partition_indices(values, labels, pairs=None, *, silhouette_value=None):
    """Indices that depend on one partition only.

    Returns WSS, BSS, TSS, the partition indices, and the mean within and
    between distances needed by Frey. ``pairs`` reuses distances across k.
    """
    values = _check_values(values)
    labels = np.asarray(labels)
    if labels.shape != (len(values),):
        raise ValueError("Provide one cluster label per observation.")
    pairs = PairDistances(values) if pairs is None else pairs
    if pairs.n != len(values):
        raise ValueError("The distance cache does not match the observations.")
    labels = np.unique(labels, return_inverse=True)[1]
    n = len(values)
    k = int(labels.max()) + 1
    sizes = np.bincount(labels, minlength=k)
    centers = np.zeros((k, values.shape[1]))
    np.add.at(centers, labels, values)
    centers /= sizes[:, None]
    grand_mean = values.mean(axis=0)
    residual_ss = np.sum((values - centers[labels])**2, axis=1)
    wss = float(residual_ss.sum())
    tss_by_variable = np.sum((values - grand_mean)**2, axis=0)
    bss_by_variable = sizes @ (centers - grand_mean)**2
    bss, tss = float(bss_by_variable.sum()), float(tss_by_variable.sum())
    result = {"WSS": wss, "BSS": bss, "TSS": tss, BALL_HALL: wss / k}

    result[CALINSKI] = _ratio(bss / (k - 1), wss / (n - k)) if 1 < k < n else np.nan

    davies = np.nan
    if k > 1:
        radii = np.sqrt(np.bincount(labels, weights=residual_ss, minlength=k) / sizes)
        separation = cdist(centers, centers)
        off_diagonal = ~np.eye(k, dtype=bool)
        if (separation[off_diagonal] > 0).all():
            ratios = (radii[:, None] + radii) / np.where(off_diagonal, separation, np.inf)
            davies = _finite(ratios.max(axis=1).mean())
    result[DAVIES_RMS] = davies

    within, between = pairs.split(labels)
    q, total = len(within), pairs.count
    both = q > 0 and len(between) > 0
    if q:
        smallest, largest = pairs.sorted[:q].sum(), pairs.sorted[total - q:].sum()
        result[C_INDEX] = _ratio(within.sum() - smallest, largest - smallest)
    else:
        result[C_INDEX] = np.nan
    result[DUNN] = _ratio(between[0], within.max()) if both else np.nan
    comparisons = total * (total - 1) / 2
    if both:
        concordant, discordant = concordance(within, between)
        result[GAMMA] = _ratio(concordant - discordant, concordant + discordant)
        result[GPLUS] = _ratio(discordant, comparisons)
        result[TAU] = _ratio(concordant - discordant, comparisons)
        mean_within, mean_between = float(within.mean()), float(between.mean())
        result[MCCLAIN_RAO] = _ratio(mean_within, mean_between)
        result[POINT_BISERIAL] = _ratio((mean_between - mean_within) * np.sqrt(q * len(between)),
                                        pairs.sd * total)
    else:
        result.update(dict.fromkeys((GAMMA, GPLUS, TAU, MCCLAIN_RAO, POINT_BISERIAL), np.nan))
        mean_within = float(within.mean()) if q else np.nan
        mean_between = float(between.mean()) if len(between) else np.nan
    result[MEAN_WITHIN], result[MEAN_BETWEEN] = mean_within, mean_between

    # Constant variables have no total sum of squares and leave the average.
    varying = np.ptp(values, axis=0) > 0
    result[RATKOWSKY] = (_finite(np.sqrt(np.mean(bss_by_variable[varying] / tss_by_variable[varying]) / k))
                         if varying.any() else np.nan)

    if silhouette_value is None:
        silhouette_value = silhouette(squareform(pairs.distances), labels) if 1 < k < n else np.nan
    result[SILHOUETTE] = _finite(silhouette_value)
    return result


def _get(series, k):
    value = series.get(k, np.nan)
    return float(value) if pd.notna(value) else np.nan


def sequence_indices(table, n, dimensions, *, kl_scaling=DIMENSION_ADJUSTED):
    """Add indices that compare neighbouring k values to a table indexed by k."""
    table = table.sort_index()
    wss = table["WSS"]
    within, between = table[MEAN_WITHIN], table[MEAN_BETWEEN]
    columns = {name: {} for name in (BALL_HALL, FREY, HARTIGAN, KRZANOWSKI_LAI, TRACE_W)}
    if kl_scaling not in KL_CHOICES:
        raise ValueError("Choose a supported Krzanowski–Lai scaling.")
    power = 0 if kl_scaling == UNSCALED_WSS else 2 / dimensions

    def difference(k):
        return (k - 1)**power * _get(wss, k - 1) - k**power * _get(wss, k)

    for k in table.index:
        current, following = _get(wss, k), _get(wss, k + 1)
        columns[BALL_HALL][k] = _finite(current / k)
        columns[TRACE_W][k] = _finite(current)
        columns[HARTIGAN][k] = _finite((current / following - 1) * (n - k - 1)) if following > 0 else np.nan
        columns[KRZANOWSKI_LAI][k] = (_finite(abs(_ratio(difference(k), difference(k + 1))))
                                      if k >= 2 else np.nan)
        columns[FREY][k] = _ratio(_get(between, k + 1) - _get(between, k),
                                  _get(within, k + 1) - _get(within, k))
    return table.assign(**{name: pd.Series(values, dtype=float) for name, values in columns.items()})


def _valid(series, low=2):
    series = pd.Series(series, dtype=float).sort_index()
    series = series[series.index >= low]
    return series[np.isfinite(series)]


def _consecutive_pairs(series):
    return [(k, k + 1) for k in series.index if k + 1 in series.index]


def vote_extreme(series, maximize):
    values = _valid(series)
    if values.empty:
        return None, "No valid value for k ≥ 2"
    return int(values.idxmax() if maximize else values.idxmin()), ""


def vote_ball_hall(series):
    values = _valid(series)
    pairs = _consecutive_pairs(values)
    if not pairs:
        return None, "Needs two consecutive valid k ≥ 2"
    changes = [abs(values[b] - values[a]) for a, b in pairs]
    return int(pairs[int(np.argmax(changes))][1]), ""


def vote_hartigan(series):
    values = _valid(series)
    pairs = _consecutive_pairs(values)
    if not pairs:
        return None, "Needs two consecutive valid k ≥ 2"
    drops = np.array([values[a] - values[b] for a, b in pairs])
    if not (drops > 0).any():
        return None, "No positive drop between consecutive k"
    return int(pairs[int(np.argmax(drops))][1]), ""


def vote_trace_w(series):
    # k = 1 may supply WSS(k − 1), but only k ≥ 2 can win.
    values = _valid(series, low=1)
    centers = [k for k in values.index if k >= 2 and k - 1 in values.index and k + 1 in values.index]
    if not centers:
        return None, "Needs WSS at k − 1, k and k + 1 for some k ≥ 2"
    second = np.array([(values[k - 1] - values[k]) - (values[k] - values[k + 1]) for k in centers])
    if not (second > 0).any():
        return None, "No positive second difference"
    return int(centers[int(np.argmax(second))]), ""


def vote_frey(series):
    values = _valid(series)
    if values.empty:
        return None, "No valid ratio (needs the k + 1 model)"
    below = values[values < 1]
    if below.empty:
        return None, "No ratio below 1"
    return int(below.index[0]), ""


def vote_gap(gap, se):
    gap = pd.Series(gap, dtype=float)
    se = pd.Series(se, dtype=float)
    values = _valid(gap)
    if values.empty:
        return None, "No valid Gap for k ≥ 2"
    for k in values.index:
        following, error = _get(gap, k + 1), _get(se, k + 1)
        if np.isfinite(following) and np.isfinite(error) and values[k] >= following - error:
            return int(k), ""
    return int(values.index[-1]), "Fallback: largest k with a valid Gap"


def index_votes(table):
    """Return one row per index with its vote, the value at that k, and a note."""
    rows = []
    for name in INDEX_COLUMNS:
        series = table[name] if name in table else pd.Series(dtype=float)
        if name in _MAXIMUM or name in _MINIMUM:
            k, note = vote_extreme(series, name in _MAXIMUM)
        elif name == BALL_HALL:
            k, note = vote_ball_hall(series)
        elif name == HARTIGAN:
            k, note = vote_hartigan(series)
        elif name == TRACE_W:
            k, note = vote_trace_w(series)
        elif name == FREY:
            k, note = vote_frey(series)
        else:
            k, note = vote_gap(series, table["Gap SE"] if "Gap SE" in table else pd.Series(dtype=float))
        value = _get(series, k) if k is not None else np.nan
        rows.append((name, RULES[name], k, value, note or ("" if k is not None else "Abstained")))
    votes = pd.DataFrame(rows, columns=["Index", "Rule", "Recommended k", "Value", "Note"]).set_index("Index")
    votes["Recommended k"] = votes["Recommended k"].astype("Int64")
    return votes


def tally(votes, candidates):
    """Count at most one vote per index; ties go to the smallest k."""
    candidates = sorted(int(k) for k in candidates if k >= 2)
    chosen = [int(k) for k in votes["Recommended k"].dropna()]
    counts = Counter(chosen)
    table = pd.Series({k: counts.get(k, 0) for k in sorted({*candidates, *counts})}, dtype=int, name="Votes")
    table.index.name = "k"
    top = max(counts.values(), default=0)
    tied = sorted(k for k, value in counts.items() if value == top) if top else []
    return {
        "counts": table,
        "recommended": tied[0] if tied else None,
        "tied": tied,
        "voting": len(chosen),
        "abstaining": len(votes) - len(chosen),
    }


def consensus_table(partitions, wss, n, dimensions, *, gap=None, gap_se=None, overrides=None,
                    kl_scaling=DIMENSION_ADJUSTED):
    """Build the per-k table: WSS, the 17 indices, and Gap SE.

    ``partitions`` maps k to the result of :func:`partition_indices` (or is
    missing for k where partition indices are undefined). ``wss`` is the WSS
    of every fitted k. ``overrides`` replaces columns with values that the
    existing scan already computes, such as Silhouette.
    """
    wss = pd.Series(wss, dtype=float).sort_index()
    table = pd.DataFrame(index=wss.index, columns=[MEAN_WITHIN, MEAN_BETWEEN, *INDEX_COLUMNS], dtype=float)
    table.index.name = "k"
    table.insert(0, "WSS", wss)
    for k, measures in partitions.items():
        for name, value in measures.items():
            if name in table.columns and name != "WSS":
                table.loc[k, name] = value
    table = sequence_indices(table, n, dimensions, kl_scaling=kl_scaling)
    for name, values in (overrides or {}).items():
        table[name] = pd.Series(values, dtype=float).reindex(table.index)
    table[GAP] = (pd.Series(gap, dtype=float).reindex(table.index) if gap is not None else np.nan)
    table["Gap SE"] = (pd.Series(gap_se, dtype=float).reindex(table.index) if gap_se is not None else np.nan)
    table = table.where(np.isfinite(table))
    hidden = table[[MEAN_WITHIN, MEAN_BETWEEN]]
    return table[["WSS", *INDEX_COLUMNS, "Gap SE"]], hidden
