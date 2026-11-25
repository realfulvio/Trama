"""K-means model selection and estimated marginal mean comparisons."""
from dataclasses import dataclass
from itertools import combinations, product
from math import comb, prod
from numbers import Integral

import numpy as np
import pandas as pd
from scipy import integrate, linalg, optimize, stats
from scipy.spatial.distance import cdist, pdist, squareform
from statsmodels.stats.multitest import multipletests

from . import cluster_consensus as consensus, dunnett_exact, kmeans_archive
from .analysis_chain import ChainCancelled
from .anova_terms import CONTROL_FIELD
from .field_error import FieldError
from .kmeans_options import GAP_GEOMETRIES, GAP_PRINCIPAL_AXES, GAP_REFERENCE, GAP_VARIABLE_RANGES
from .parallel import run_tasks
from .stats import Clusters, _anova_model, _cluster_data, _design_grid, kmeans


_CLUSTER_METRICS = {
    "silhouette": "Silhouette",
    "calinski-harabasz": "Calinski–Harabasz",
    "davies-bouldin": "Davies–Bouldin",
}
_ADJUSTMENTS = {"none", "bonferroni", "sidak", "holm", "holm-sidak", "tukey", "dunnett"}


@dataclass
class ClusterScan:
    metrics: pd.DataFrame
    recommended_k: int | None
    fit: Clusters | None
    # Consensus only: one row per index, and the vote tally.
    votes: pd.DataFrame | None = None
    selection: dict | None = None
    report_fits: dict[int, Clusters] | None = None
    fitting_data: pd.DataFrame | None = None
    restored: bool = False


def _cluster_scores(values, distances, fit):
    labels = fit.labels.to_numpy() - 1
    centers = fit.centers.to_numpy()
    count = len(centers)
    sizes = np.bincount(labels, minlength=count)
    starts = np.r_[0, sizes.cumsum()[:-1]]
    order = np.argsort(labels)
    means = np.add.reduceat(distances[order], starts, axis=0).T / sizes
    rows = np.arange(len(values))
    same_size = sizes[labels]
    within = means[rows, labels] * same_size / np.maximum(1, same_size - 1)
    means[rows, labels] = np.inf
    between = means.min(axis=1)
    denominator = np.maximum(within, between)
    silhouettes = np.divide(between - within, denominator, out=np.zeros_like(within),
                            where=(same_size > 1) & (denominator > 0))

    grand_mean = values.mean(axis=0)
    between_ss = float(sizes @ np.sum((centers - grand_mean)**2, axis=1))
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        calinski = np.divide(between_ss, fit.inertia) * (len(values) - count) / (count - 1)
    radii = np.linalg.norm(values - centers[labels], axis=1)
    scatter = np.bincount(labels, weights=radii, minlength=count) / sizes
    separation = cdist(centers, centers)
    np.fill_diagonal(separation, np.inf)
    ratios = np.divide(scatter[:, None] + scatter, separation,
                       out=np.full_like(separation, np.inf), where=separation > 0)
    davies = ratios.max(axis=1).mean()
    return silhouettes.mean(), calinski, davies


def _check_scan_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ChainCancelled("K-means model selection cancelled.")


def _reference_inertias(job, cancel=None):
    """WSS of one Gap reference set for every eligible k, or the error of that fit (worker task).

    Errors are returned, not raised: whether one matters depends on the earlier replicates, which the
    caller replays in the original order."""
    values, columns, counts, seed, fit_options = job
    reference = pd.DataFrame(values, columns=columns)
    found = []
    for count in counts:
        _check_scan_cancel(cancel)
        try:
            found.append(kmeans(reference, columns, count, seed=seed, **fit_options).inertia)
        except Exception as error:
            found.append(error)
    return found


def _scan_fit(job, cancel=None):
    """One observed k-means fit of the scan (worker task)."""
    _check_scan_cancel(cancel)
    data, columns, count, standardize, seed, retain_initial, fit_options = job
    return kmeans(data, columns, count, standardize, seed, retain_initial=retain_initial, **fit_options)


def _gap_scores(metrics, values, columns, seed, replicates, *, allow_failed_references=False,
                fit_options, reference_geometry=GAP_VARIABLE_RANGES, cancel=None):
    metrics["Gap"] = np.nan
    metrics["Gap SE"] = np.nan
    eligible = metrics.index[(metrics.index < len(values)) & (metrics["WSS"] > 0)]
    if eligible.empty:
        return
    if reference_geometry == GAP_PRINCIPAL_AXES:
        # Distances are Euclidean. Fit the simulated points directly in the
        # orthogonal coordinates where they were drawn.
        centered = values - values.mean(axis=0)
        left, singular, right = np.linalg.svd(centered, full_matrices=False)
        pivots = np.argmax(np.abs(right), axis=1)
        signs = np.where(right[np.arange(len(right)), pivots] < 0, -1, 1)
        values = left * (singular * signs)
        columns = list(columns)[:values.shape[1]]
    low, high = values.min(axis=0), values.max(axis=0)
    rng = np.random.default_rng(seed)
    reference_wss = np.full((replicates, len(eligible)), np.nan)
    failed = set()
    # The reference sets come from one random stream: draw them here, in the original order, and fit them on
    # several processes. Every fit uses its own generator from ``seed``, so the WSS values do not depend on
    # the number of processes. A reference fit that fails is skipped in the later replicates, as before.
    counts = tuple(eligible)
    jobs = [(rng.uniform(low, high, size=values.shape), columns, counts, seed, fit_options)
            for _ in range(replicates)]
    for replica, found in enumerate(run_tasks(_reference_inertias, jobs, cancel=cancel, with_cancel=True)):
        for index, inertia in enumerate(found):
            if index in failed:
                continue
            if isinstance(inertia, ValueError):
                if not allow_failed_references:
                    raise inertia
                failed.add(index)
                continue
            if isinstance(inertia, Exception):
                raise inertia
            if allow_failed_references and (not np.isfinite(inertia) or inertia <= 0):
                failed.add(index)
            else:
                reference_wss[replica, index] = inertia
    valid = (reference_wss > 0).all(axis=0)
    counts = eligible[valid]
    log_reference = np.log(reference_wss[:, valid])
    metrics.loc[counts, "Gap"] = log_reference.mean(axis=0) - np.log(metrics.loc[counts, "WSS"])
    metrics.loc[counts, "Gap SE"] = log_reference.std(axis=0) * np.sqrt(1 + 1 / replicates)


def _recommend_clusters(metrics, criterion):
    if criterion == "gap":
        gap = metrics["Gap"]
        within_one_se = gap >= gap.shift(-1) - metrics["Gap SE"].shift(-1)
        if within_one_se.any():
            return int(gap.index[within_one_se][0])
        fallback = gap.last_valid_index()
        return int(fallback) if fallback is not None else None

    if criterion != "elbow":
        scores = metrics[_CLUSTER_METRICS[criterion]].dropna()
        if scores.empty:
            return None
        return int(scores.idxmin() if criterion == "davies-bouldin" else scores.idxmax())

    wss = metrics["WSS"].to_numpy()
    span = wss[0] - wss[-1]
    if len(wss) < 3 or span <= 0:
        return None
    # The largest vertical gap below the line joining the scaled WSS endpoints.
    gaps = (wss[0] - wss) / span - np.linspace(0, 1, len(wss))
    offset = int(np.argmax(gaps[1:-1])) + 1
    return int(metrics.index[offset]) if gaps[offset] > 1e-12 else None


def gap_replicate_limit(n, dimensions, candidates):
    reference_cost = n * dimensions * sum(k for k in candidates if k < n)
    return min(100, 3_000_000 // reference_cost) if reference_cost else 100


def _check_scan_budget(n, dimensions, candidates, pairwise, *, simulate_gap, gap_replicates):
    fit_cost = n * dimensions * sum(candidates)
    if n > 3000 or fit_cost > 1_000_000 or (pairwise and n * n * dimensions > 40_000_000):
        raise ValueError("K-means scan exceeds its work budget. Reduce rows, variables, or maximum k.")
    if simulate_gap:
        if (isinstance(gap_replicates, bool) or not isinstance(gap_replicates, Integral)
                or not 5 <= gap_replicates <= 100):
            raise ValueError("Gap reference datasets must be an integer between 5 and 100.")
        if gap_replicates > gap_replicate_limit(n, dimensions, candidates):
            raise ValueError("Gap reference fits exceed the work budget. Reduce rows, variables, k, or references.")


def kmeans_scan(frame, columns, max_k=8, standardize=False, seed=42, criterion="silhouette",
                *, min_k=1, gap_replicates=20, kl_scaling=consensus.DIMENSION_ADJUSTED,
                algorithm="lloyd", max_iterations=10, retain_fits=False, retain_initial=False,
                include_gap=False, column_scale=None, gap_reference=GAP_VARIABLE_RANGES, cancel=None,
                kmeans_plus_plus=False, archive_options=None):
    """Compare fits from min_k through max_k, capped at the distinct row count.

    The silhouette, Calinski–Harabasz and Davies–Bouldin scores require
    2 <= k < N. The recommendation can be absent for the selected criterion.

    The optional Gap criterion fits the same k-means procedure to B reference
    datasets with the observed row count and independent uniform variables
    over their observed ranges in the analysis scale. Alternatively, the
    ranges can be taken along the principal components of the scaled data.
    Gap is mean log reference WSS minus log observed WSS. Gap SE is
    sqrt(1 + 1/B) times the population
    SD of log reference WSS. Select the first k with Gap(k) >= Gap(k+1) minus
    Gap SE(k+1), falling back to the largest k with a finite Gap.
    include_gap also computes these columns for display with another criterion.

    The "consensus" criterion reuses each observed fit to compute the 17
    indices in analisi.cluster_consensus, lets each index vote once for a
    k >= 2, and recommends the k with most votes (the smallest on a tie).
    Its metrics hold WSS, the 17 indices and Gap SE.
    """
    _check_scan_cancel(cancel)
    if criterion not in {*_CLUSTER_METRICS, "elbow", "gap", "consensus"}:
        raise ValueError("Unknown cluster recommendation criterion.")
    if criterion == "consensus" and kl_scaling not in consensus.KL_CHOICES:
        raise FieldError(consensus.KL_SCALING, "Choose a supported Krzanowski–Lai scaling.")
    if not isinstance(gap_reference, str) or gap_reference not in GAP_GEOMETRIES:
        raise FieldError(GAP_REFERENCE, "Choose a supported Gap reference geometry.")
    if (any(isinstance(k, bool) or not isinstance(k, Integral) for k in (min_k, max_k))
            or not 1 <= min_k <= max_k <= 30):
        raise ValueError("Cluster limits must be integers with 1 ≤ minimum k ≤ maximum k ≤ 30.")
    data, raw = _cluster_data(frame, columns, 1)
    n, dimensions = raw.shape
    # Bound squared distances and within-cluster sums in float64 arithmetic.
    if np.abs(raw).max() > np.sqrt(np.finfo(float).max / (4 * n * dimensions)):
        raise ValueError("Variable magnitudes are too large to compute squared distances.")
    scale = column_scale if column_scale is not None else ("standardize" if standardize else "none")
    _, values = _cluster_data(data, columns, 1, scale) if scale != "none" else (data, raw)
    upper = min(max_k, len(np.unique(values, axis=0)))
    if min_k > upper:
        raise ValueError("Minimum cluster count exceeds the number of distinct observations.")
    candidates = range(min_k, upper + 1)
    score_distances = max(2, min_k) <= min(upper, n - 1)
    score_consensus = criterion == "consensus" and max(2, min_k) <= upper
    simulate_gap = include_gap or criterion in {"gap", "consensus"}
    _check_scan_budget(n, dimensions, candidates, score_distances or score_consensus,
                       simulate_gap=simulate_gap, gap_replicates=gap_replicates)
    pairs = consensus.PairDistances(values) if score_consensus else None
    distances = squareform(pairs.distances if pairs is not None else pdist(values)) if score_distances else None
    rows, fits, partitions = [], {}, {}
    archive = kmeans_archive.matching(frame, archive_options, data, values, candidates, retain_initial) if archive_options else None
    fit_options = {"algorithm": algorithm, "max_iterations": max_iterations}
    if kmeans_plus_plus:
        fit_options["kmeans_plus_plus"] = True
    # The fits are independent (each one seeds its own generator); scores follow in k order, as before.
    observed_options = {**fit_options, "column_scale": scale}
    jobs = [(data, columns, count, standardize, seed, retain_initial, observed_options) for count in candidates]
    if archive is None:
        computed = run_tasks(_scan_fit, jobs, cancel=cancel, with_cancel=True, outcomes=True)
        outcomes = ((outcome.value, outcome.error) for outcome in computed)
    else:
        outcomes = ((fit, None) for fit in archive[0].values())
    for count, (fit, error) in zip(candidates, outcomes, strict=True):
        _check_scan_cancel(cancel)
        if error is not None:
            raise error
        fits[count] = fit
        scores = _cluster_scores(values, distances, fit) if 1 < count < n else (np.nan,) * 3
        # The archived one-cluster report uses zero; this convention cannot vote for k=1.
        if archive is not None and count == 1:
            scores = (0.0, np.nan, np.nan)
        rows.append((count, fit.inertia, *scores))
        if pairs is not None and count >= 2:
            partitions[count] = consensus.partition_indices(values, fit.labels.to_numpy(), pairs,
                                                            silhouette_value=scores[0])
    metrics = pd.DataFrame(rows, columns=["k", "WSS", *_CLUSTER_METRICS.values()]).set_index("k")
    if simulate_gap:
        if archive is not None:
            metrics[["Gap", "Gap SE"]] = pd.DataFrame.from_dict(archive[1], orient="index")
        else:
            _gap_scores(metrics, values, columns, seed, gap_replicates,
                        allow_failed_references=criterion != "gap", fit_options=fit_options,
                        reference_geometry=gap_reference, cancel=cancel)
    _check_scan_cancel(cancel)
    if criterion == "consensus":
        outcome = _consensus_scan(metrics, partitions, fits, n, dimensions, kl_scaling=kl_scaling)
    else:
        recommended = _recommend_clusters(metrics, criterion)
        outcome = ClusterScan(metrics, recommended, fits.get(recommended))
    outcome.restored = archive is not None
    if retain_fits:
        outcome.report_fits = fits
        outcome.fitting_data = pd.DataFrame(values, index=data.index, columns=columns)
    return outcome


def _consensus_scan(metrics, partitions, fits, n, dimensions, *, kl_scaling=consensus.DIMENSION_ADJUSTED):
    # Calinski–Harabasz and Silhouette keep the values of the existing criteria.
    overrides = {name: metrics[name] for name in (consensus.CALINSKI, consensus.SILHOUETTE)}
    table, _ = consensus.consensus_table(partitions, metrics["WSS"], n, dimensions, gap=metrics["Gap"],
                                         gap_se=metrics["Gap SE"], overrides=overrides, kl_scaling=kl_scaling)
    votes = consensus.index_votes(table)
    selection = consensus.tally(votes, table.index)
    if kl_scaling == consensus.UNSCALED_WSS:
        label = {consensus.KRZANOWSKI_LAI: consensus.WSS_DROP_RATIO}
        table = table.rename(columns=label)
        votes = votes.rename(index=label)
    recommended = selection["recommended"]
    return ClusterScan(table, recommended, fits.get(recommended), votes, selection)


def _bounded_family_p(approximation, raw, count):
    # Subtracting a numerical CDF from one can lose the tail entirely. If
    # integration leaves the valid range, use the conservative union bound.
    upper = np.minimum(1, count * raw)
    return np.where((approximation >= raw) & (approximation <= upper), approximation, upper)


def _tukey_scores(t, p, coordinates, df, confidence):
    groups = len(coordinates)
    # Tukey–Kramer applies if the joint distribution of these contrasts
    # matches differences of independent means, possibly with unequal variances.
    distances = squareform(pdist(coordinates, metric="sqeuclidean"))
    row_sums = distances.sum(axis=1)
    variances = (row_sums - row_sums.sum() / (2 * (groups - 1))) / (groups - 2)
    off_diagonal = ~np.eye(groups, dtype=bool)
    tolerance = distances.max() * 1e-9
    expected = variances[:, None] + variances
    if (variances.min() < -tolerance or
            not np.allclose(distances[off_diagonal], expected[off_diagonal],
                            rtol=1e-9, atol=tolerance)):
        raise ValueError("Tukey requires a family of means with independent difference structure.")
    adjusted = stats.studentized_range.sf(np.sqrt(2) * np.abs(t), groups, df)
    critical = stats.studentized_range.ppf(confidence, groups, df) / np.sqrt(2)
    return _bounded_family_p(adjusted, p, len(p)), critical


def _two_contrast_tail(threshold, angle, df):
    # In the plane of two standardized contrasts the underlying spherical t
    # has uniform angle and P(R > r) = (1 + r²/df)^(-df/2). In each sector
    # the nearer contrast axis gives max(|T1|, |T2|) = R cos(theta).
    if threshold == 0:
        return 1.
    if not np.isfinite(threshold):
        return 0. if np.isinf(threshold) else np.nan
    log_ratio = 2 * np.log(threshold) - np.log(df)

    def radial_tail(theta):
        log_r2_over_df = log_ratio - 2 * np.log(np.cos(theta))
        return np.exp(-.5 * df * np.logaddexp(0., log_r2_over_df))

    sectors = (angle / 2, (np.pi - angle) / 2)
    return (2 / np.pi) * sum(integrate.quad(radial_tail, 0., end, epsabs=1e-300, epsrel=1e-12)[0]
                             for end in sectors)


def dunnett_scores(t, p, standardized, df, alpha):
    """Return adjusted p values and the common critical value for standardized control contrasts."""
    count = len(t)
    if count == 1:
        return p, stats.t.isf(alpha / 2, df)
    correlation = np.clip(standardized @ standardized.T, -1, 1)
    np.fill_diagonal(correlation, 1)

    if count == 2:
        rho = abs(correlation[0, 1])
        if rho == 1.:
            return p, stats.t.isf(alpha / 2, df)
        angle = np.arccos(rho)

        def tail(x):
            return _two_contrast_tail(x, angle, df)

        adjusted = np.clip([tail(x) for x in np.abs(t)], p, np.minimum(count * p, 1.))
        tolerance = 1e-12
    elif (loadings := dunnett_exact.one_factor_loadings(correlation)) is not None:
        # Comparisons with one control: deterministic quadrature, about 1e-11 (0.109.x).
        def tail(x):
            return dunnett_exact.tail(x, loadings, df)

        adjusted = _bounded_family_p(np.array([tail(x) for x in np.abs(t)]), p, count)
        tolerance = 1e-12
    else:
        def tail(x):
            bound = np.full(count, x, dtype=float)
            # Keep the quasi-random integration reproducible across analyses.
            inside = stats.multivariate_t.cdf(bound, shape=correlation, df=df, allow_singular=True,
                                              lower_limit=-bound, random_state=42, maxpts=40_000)
            return 1 - inside

        adjusted = _bounded_family_p(np.array([tail(x) for x in np.abs(t)]), p, count)
        tolerance = 1e-5

    lower, upper = stats.t.isf(alpha / 2, df), stats.t.isf(alpha / (2 * count), df)
    if tail(lower) <= alpha:
        critical = lower
    elif tail(upper) >= alpha:
        critical = upper
    else:
        critical = optimize.brentq(lambda x: tail(x) - alpha, lower, upper, xtol=tolerance)
    return adjusted, critical


def _adjust(method, t, p, df, confidence, coordinates, standardized):
    count = len(p)
    alpha = 1 - confidence
    if method in {"holm", "holm-sidak"}:
        return multipletests(p, method=method)[1], np.nan
    if method == "none" or count == 1:
        return p, stats.t.isf(alpha / 2, df)
    if method == "tukey":
        return _tukey_scores(t, p, coordinates, df, confidence)
    if method == "dunnett":
        return dunnett_scores(t, p, standardized, df, alpha)
    single_alpha = alpha / count if method == "bonferroni" else -np.expm1(np.log1p(-alpha) / count)
    return multipletests(p, method=method)[1], stats.t.isf(single_alpha / 2, df)


def _format_levels(factors, levels):
    return ", ".join(f"{factor}={level}" for factor, level in zip(factors, levels))


def anova_comparisons(frame, response, factors, order, compare, *, within=(), method="holm",
                      family="separate", confidence=.95, control=None, reverse=False, terms=None):
    """Compare equal-weight estimated means from the ordinary factorial model.

    Select one compared factor for main/simple effects or multiple factors for
    cell means. Conditioning factors define strata, and the remaining factors
    are averaged. Separate families adjust within strata; a pooled family
    adjusts across them. Reverse swaps the two levels in each contrast.
    Sequential Holm adjustments have no CI here.

    ``terms`` (Selected terms, 0.83) uses the design of exactly those terms. The averaged factors
    are then the other factors of that model, and factors outside it are not part of the model.
    """
    if terms is not None:
        from .anova_terms import active_factors, canonical_terms
        factors = active_factors(list(factors), canonical_terms(terms, factors))
    compared = (compare,) if isinstance(compare, str) else tuple(compare)
    within = (within,) if isinstance(within, str) else tuple(within)
    selected = (*within, *compared)
    if not compared or len(set(selected)) != len(selected) or set(selected) - set(factors):
        raise ValueError("Select distinct comparison and conditioning factors from the model.")
    if method not in _ADJUSTMENTS or family not in {"separate", "pooled"} or not 0 < confidence < 1:
        raise ValueError("Unknown correction, unknown family scope, or invalid confidence level.")
    if method == "tukey" and (control is not None or (within and family == "pooled")):
        raise ValueError("Tukey requires all pairwise comparisons within each stratum.")
    if method == "dunnett" and control is None:
        raise FieldError(CONTROL_FIELD, "Dunnett requires a control level or cell.")

    data, keys, _, design, beta, error, df = _anova_model(frame, response, factors, order, terms=terms)
    key_by_factor = dict(zip(factors, keys))
    grid_factors = (*selected, *(factor for factor in factors if factor not in selected))
    grid_keys = [key_by_factor[factor] for factor in grid_factors]
    levels = [sorted(data[key].unique()) for key in grid_keys]
    counts = [len(level) for level in levels]
    strata = prod(counts[:len(within)])
    groups = prod(counts[len(within):len(selected)])
    pair_count = comb(groups, 2) if control is None else groups - 1
    if (pair_count < 1 or prod(counts) > 4096 or prod(counts) * len(beta) > 4_000_000
            or strata * pair_count > 1000):
        raise ValueError("Too many combinations or too few levels for post-hoc comparisons.")
    if method == "dunnett" and (
        pair_count * (strata if family == "pooled" else 1) > 16 or strata * pair_count > 64
    ):
        raise ValueError("Dunnett supports up to 16 comparisons per family and 64 total.")

    conditions = list(product(*levels[:len(within)]))
    labels = list(product(*levels[len(within):len(selected)]))
    if control is None:
        pairs = list(combinations(range(groups), 2))
    else:
        raw_levels = control if isinstance(control, (tuple, list)) else (control,)
        control_levels = tuple(map(str, raw_levels))
        if control_levels not in labels:
            raise FieldError(CONTROL_FIELD, "The selected control level or cell does not exist.")
        control_idx = labels.index(control_levels)
        pairs = [(i, control_idx) for i in range(groups) if i != control_idx]
    if reverse:
        pairs = [(b, a) for a, b in pairs]

    balanced = pd.DataFrame(product(*levels), columns=grid_keys)
    grid = _design_grid(design, balanced)
    means = grid.reshape(strata * groups, -1, len(beta)).mean(axis=1)
    # If X = QR, then L(X'X)^-1 L' = (R^-T L')'(R^-T L').
    triangular = np.linalg.qr(design.to_numpy(), mode="r")
    coordinates = linalg.solve_triangular(triangular.T, means.T, lower=True).T.reshape(strata, groups, -1)
    means = means.reshape(strata, groups, -1)

    rows, normalized = [], []
    first, second = np.asarray(pairs).T
    for index, condition in enumerate(conditions):
        name = _format_levels(within, condition)
        family_name = name if name and family == "separate" else "All"
        differences = (means[index, first] - means[index, second]) @ beta
        contrasts = coordinates[index, first] - coordinates[index, second]
        length = np.linalg.norm(contrasts, axis=1)
        se = length * np.sqrt(error / df)
        if not np.isfinite(se).all() or (se <= 0).any():
            raise ValueError("Could not estimate a standard error for the comparison.")
        if method == "dunnett":
            normalized.append(contrasts / length[:, None])
        for (a, b), estimate, uncertainty in zip(pairs, differences, se):
            left, right = (labels[a][0], labels[b][0]) if len(compared) == 1 else (
                _format_levels(compared, labels[a]), _format_levels(compared, labels[b]))
            comparison = f"{left} − {right}"
            if name:
                comparison = f"{name} | {comparison}"
            rows.append((comparison, family_name, estimate, uncertainty, df, estimate / uncertainty))

    results = pd.DataFrame(rows, columns=["Comparison", "Family", "Difference", "SE", "df", "t"])
    results["p"] = 2 * stats.t.sf(np.abs(results["t"]), df)
    adjusted = np.empty(len(results))
    critical = np.empty(len(results))
    families = [slice(None)] if family == "pooled" else [
        slice(i * pair_count, (i + 1) * pair_count) for i in range(strata)]
    normalized = np.vstack(normalized) if normalized else None
    for index, bounds in enumerate(families):
        adjusted[bounds], critical[bounds] = _adjust(
            method, results["t"].to_numpy()[bounds], results["p"].to_numpy()[bounds], df,
            confidence, coordinates[index], normalized[bounds] if normalized is not None else None)
    results["Adjusted p"] = adjusted
    margin = critical * results["SE"]
    results["CI low"] = results["Difference"] - margin
    results["CI high"] = results["Difference"] + margin
    return results.set_index("Comparison")
