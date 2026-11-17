"""One-way inference and balanced within-subject analyses."""
from itertools import combinations
from math import comb, factorial, lcm, prod

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.oneway import anova_oneway

from .advanced import dunnett_scores
from .friedman_exact import ExactBudgetExceeded, friedman_exact_tail
from .processing import FieldError
from .stats import complete
from . import unequal_anova
from .unequal_anova import DEFAULT_LEVEL, UNEQUAL_POSTHOC, brown_forsythe, check_group_variances, confidence_level


_ADJUSTMENTS = {"holm": "Holm", "bonferroni": "Bonferroni", "fdr_bh": "Benjamini–Hochberg"}
_EXACT_FRIEDMAN_LIMIT = 1_000_000_000
_EXACT_KRUSKAL_LIMIT = 100_000
_EXACT_KRUSKAL_MAX_N = 30

KRUSKAL_P = "Kruskal–Wallis p value"
FRIEDMAN_P = "P value"
AUTOMATIC_P, EXACT_P, CHI_SQUARE_P = KRUSKAL_P_METHODS = (
    "Automatic", "Exact permutation", "Chi-square approximation")

DUNN_METHODS = {"Kruskal–Wallis", "Friedman"}
DUNN, DUNN_CONTROL, DUNN_ADJUSTMENT, DUNN_ALPHA = "Dunn comparisons", "Control group", "Dunn adjustment", "Dunn alpha"
DUNN_PAIRS = "Selected pairs"
DUNN_PAIR_LIST = "Group pair list"
DUNN_MODES = ("None", "All pairs", "Versus control", DUNN_PAIRS)
DUNN_ADJUSTMENTS = ("Bonferroni", "Uncorrected")
DUNN_OPTIONS = {DUNN: DUNN_MODES, DUNN_CONTROL: "Group choice", DUNN_PAIRS: DUNN_PAIR_LIST,
                DUNN_ADJUSTMENT: DUNN_ADJUSTMENTS, DUNN_ALPHA: .05}


def _selected_pair_indices(groups, selected, field):
    if not isinstance(selected, (list, tuple)) or not selected:
        raise FieldError(field, "Add at least one pair of groups.")
    by_label = {}
    for i, label in enumerate(groups):
        by_label.setdefault(str(label), []).append(i)
    pairs, seen = [], set()
    for pair in selected:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(not isinstance(label, str) or len(by_label.get(label, ())) != 1 for label in pair)):
            raise FieldError(field, "Choose two observed groups with unambiguous labels for each pair.")
        first, second = (by_label[label][0] for label in pair)
        key = tuple(sorted((first, second)))
        if first == second or key in seen:
            raise FieldError(field, "Choose distinct groups and add each pair only once.")
        pairs.append((first, second))
        seen.add(key)
    return pairs


def _control_pairs(groups, control, field):
    matches = [i for i, label in enumerate(groups) if str(label) == control]
    if len(matches) != 1:
        raise FieldError(field, "Choose an observed group with an unambiguous label.")
    first = matches[0]
    return [(first, second) for second in range(len(groups)) if second != first]


def dunn_comparisons(groups, values, options, *, matched=False):
    """Return two-sided Dunn contrasts after independent or matched rank tests."""
    mode = options.get(DUNN, DUNN_MODES[0])
    if mode == DUNN_MODES[0]:
        return {}
    if mode not in DUNN_MODES:
        raise FieldError(DUNN, "Choose a comparison family.")
    count = len(groups)
    if count > 100:
        raise FieldError(DUNN, "Compare up to 100 groups at once.")
    if mode == "Versus control":
        pairs = _control_pairs(groups, options.get(DUNN_CONTROL), DUNN_CONTROL)
    elif mode == DUNN_PAIRS:
        pairs = _selected_pair_indices(groups, options.get(DUNN_PAIRS), DUNN_PAIRS)
    else:
        pairs = list(combinations(range(count), 2))
    adjustment = options.get(DUNN_ADJUSTMENT, DUNN_ADJUSTMENTS[0])
    if adjustment not in DUNN_ADJUSTMENTS:
        raise FieldError(DUNN_ADJUSTMENT, "Choose Bonferroni or uncorrected Dunn comparisons.")
    alpha = options.get(DUNN_ALPHA, DUNN_OPTIONS[DUNN_ALPHA])
    if isinstance(alpha, (bool, np.bool_)) or not isinstance(alpha, (int, float, np.integer, np.floating)) or not 0 < alpha < 1:
        raise FieldError(DUNN_ALPHA, "Enter a significance level between 0 and 1.")

    left, right = np.asarray(pairs).T
    if matched:
        means = stats.rankdata(values, axis=1).mean(axis=0)
        se = np.sqrt(count * (count + 1) / (6 * len(values)))
    else:
        sizes = np.array([len(sample) for sample in values])
        ranks = stats.rankdata(np.concatenate(values))
        means = np.array([sample.mean() for sample in np.split(ranks, sizes.cumsum()[:-1])])
        variance = len(ranks) * (len(ranks) + 1) / 12 * stats.tiecorrect(ranks)
        se = np.sqrt(variance * (1 / sizes[left] + 1 / sizes[right]))
    differences = means[left] - means[right]
    z = np.abs(differences) / se
    p = 2 * stats.norm.sf(z)
    adjusted = np.minimum(1., p * len(pairs)) if adjustment == "Bonferroni" else p
    return {DUNN: pd.DataFrame({
        "First": [groups[i] for i in left], "Second": [groups[i] for i in right],
        "Mean rank first": means[left], "Mean rank second": means[right], "Rank difference": differences,
        "z": z, "p": p, "Adjusted p": adjusted, "Adjustment": adjustment, "Alpha": alpha,
        "Significant": adjusted <= alpha,
    })}


def _exact_kruskal_p(samples, sizes, allocations):
    # Scaling by twice the rank and the LCM of the group sizes makes the
    # comparison of sum(R_i² / n_i) exact, including boundary ties.
    ranks = tuple(map(int, 2 * stats.rankdata(np.concatenate(samples))))
    scale = lcm(*sizes)
    weights = tuple(scale // size for size in sizes)
    start = 0
    observed = 0
    for size, weight in zip(sizes, weights):
        observed += weight * sum(ranks[start:start + size]) ** 2
        start += size

    def tail(remaining, depth, score, total):
        if depth == len(sizes) - 1:
            return int(score + weights[depth] * total ** 2 >= observed)
        extreme = 0
        for indices in combinations(range(len(remaining)), sizes[depth]):
            picked = set(indices)
            rank_sum = sum(remaining[i] for i in indices)
            rest = tuple(rank for i, rank in enumerate(remaining) if i not in picked)
            extreme += tail(rest, depth + 1, score + weights[depth] * rank_sum ** 2, total - rank_sum)
        return extreme

    # Tied observations still occupy distinct positions, so each allocation
    # of observation labels has equal probability under the null.
    return tail(ranks, 0, 0, sum(ranks)) / allocations


def kruskal_wallis(samples, method=CHI_SQUARE_P):
    """Use exact conditional allocations for bounded independent samples."""
    if method not in KRUSKAL_P_METHODS:
        raise FieldError(KRUSKAL_P, "Choose automatic, exact permutation or chi-square.")
    sizes = tuple(map(len, samples))
    n = sum(sizes)
    allocations = _EXACT_KRUSKAL_LIMIT + 1
    if method != CHI_SQUARE_P and n <= _EXACT_KRUSKAL_MAX_N:
        remaining = n
        allocations = 1
        for size in sizes:
            allocations *= comb(remaining, size)
            remaining -= size
    exact = allocations <= _EXACT_KRUSKAL_LIMIT
    if method == EXACT_P and not exact:
        raise FieldError(KRUSKAL_P, f"Exact permutation supports up to {_EXACT_KRUSKAL_MAX_N} observations and "
                                    f"{_EXACT_KRUSKAL_LIMIT:,} allocations. Choose Automatic or Chi-square approximation.")
    omnibus = stats.kruskal(*samples)
    p = _exact_kruskal_p(samples, sizes, allocations) if exact else omnibus.pvalue
    return {"Statistic": omnibus.statistic, "p": p, "N": n,
            "p method": EXACT_P if exact else CHI_SQUARE_P}


def one_way_anova(frame, response, group, *, method="ordinary", posthoc=None, level=DEFAULT_LEVEL, family=None):
    """Compare independent group means using ordinary, Welch or Welch and Brown–Forsythe ANOVA.

    Comparisons are two-sided. Tamhane T2 and Dunnett T3 accept a prespecified family.
    The ordinary design uses the
    ANOVA residual mean square. Welch uses pair-specific standard errors and df.
    ``welch-bf`` reports Welch and the original Brown–Forsythe F* together.
    Tamhane T2 uses a Šidák family adjustment. Dunnett T3 uses the studentized maximum modulus.
    """
    if method not in {"ordinary", "welch", "welch-bf"}:
        raise ValueError("Select ordinary, Welch or Welch and Brown–Forsythe one-way ANOVA.")
    welch = method != "ordinary"
    range_test = "games-howell" if welch else "tukey"
    posthoc_choices = UNEQUAL_POSTHOC if welch else {"dunnett"}
    if posthoc not in {None, range_test, *_ADJUSTMENTS, *posthoc_choices}:
        raise FieldError("Post-hoc", "The selected post-hoc test is unavailable for this ANOVA method.")
    if posthoc in posthoc_choices:
        level = confidence_level(level)

    data = complete(frame, [response], [group])
    groups = {label: part[response].to_numpy() for label, part in data.groupby(group, sort=False, observed=True)}
    count = len(groups)
    if count < 2:
        raise ValueError("One-way ANOVA requires at least two groups.")
    if posthoc is not None and count > 30:
        raise ValueError("All-pairs comparisons support up to 30 groups.")

    origin = data[response].iloc[0]
    samples = [values - origin for values in groups.values()]
    sizes = np.array([len(sample) for sample in samples])
    means = np.array([sample.mean() for sample in samples])
    within_ss = np.array([np.square(sample - mean).sum() for sample, mean in zip(samples, means)])
    if welch:
        check_group_variances(list(groups), sizes, within_ss, response)
        variances = within_ss / (sizes - 1)
        omnibus = anova_oneway(samples, use_var="unequal")
        rows = [{"Term": group, "Method": "Welch one-way ANOVA",
                 "F": omnibus.statistic, "F df1": omnibus.df_num,
                 "F df2": omnibus.df_denom, "p": omnibus.pvalue}]
        if method == "welch-bf":
            statistic, df1, df2, p = brown_forsythe(sizes, means, variances)
            rows.append({"Term": group, "Method": "Brown–Forsythe one-way ANOVA",
                         "F": statistic, "F df1": df1, "F df2": df2, "p": p})
        table = pd.DataFrame(rows).set_index("Term")
    else:
        residual_df = int(sizes.sum() - count)
        residual_ss = within_ss.sum()
        if residual_df <= 0 or residual_ss <= 0:
            raise ValueError("Ordinary ANOVA requires positive pooled residual variance.")
        residual_ms = residual_ss / residual_df
        ss = np.sum(sizes * (means - np.average(means, weights=sizes)) ** 2)
        df = count - 1
        statistic = (ss / df) / residual_ms
        table = pd.DataFrame([{"Term": group, "Method": "Ordinary one-way ANOVA",
                               "SS": ss, "df": df, "MS": ss / df,
                               "F": statistic, "F df1": df, "F df2": residual_df,
                               "p": stats.f.sf(statistic, df, residual_df)},
                              {"Term": "Residual", "SS": residual_ss, "df": residual_df,
                               "MS": residual_ms}]).set_index("Term")

    if not np.isfinite(table.iloc[:len(table) if welch else 1][["F", "F df1", "F df2", "p"]]
                       .to_numpy(dtype=float)).all():
        raise ValueError("The ANOVA statistic is outside the supported numeric range.")
    result = {"ANOVA": table}
    if posthoc is None:
        return result

    if family is None or posthoc not in posthoc_choices:
        family = {}
    mode = unequal_anova.VERSUS_CONTROL if posthoc == "dunnett" else family.get(unequal_anova.FAMILY, unequal_anova.ALL_PAIRS)
    if mode == unequal_anova.VERSUS_CONTROL:
        pairs = _control_pairs(groups, family.get(unequal_anova.CONTROL), unequal_anova.CONTROL)
    elif mode == unequal_anova.PAIRS:
        pairs = _selected_pair_indices(groups, family.get(unequal_anova.PAIRS), unequal_anova.PAIRS)
    elif mode == unequal_anova.ALL_PAIRS:
        pairs = list(combinations(range(count), 2))
    else:
        raise FieldError(unequal_anova.FAMILY, "Choose a comparison family.")
    if posthoc == "dunnett" and len(pairs) > 16:
        raise FieldError("Post-hoc", "Dunnett supports up to 16 comparisons against the control.")
    first, second = np.array(pairs).T
    differences = means[first] - means[second]
    if welch:
        group_error = variances / sizes
        variance = group_error[first] + group_error[second]
        weight_first = group_error[first] / variance
        weight_second = group_error[second] / variance
        degrees = 1 / (weight_first**2 / (sizes[first] - 1) + weight_second**2 / (sizes[second] - 1))
        se = np.sqrt(variance)
    else:
        se = np.sqrt(residual_ms * (1 / sizes[first] + 1 / sizes[second]))
        degrees = residual_df

    labels = list(groups)
    comparisons = pd.DataFrame({"Comparison": [f"{labels[a]} − {labels[b]}" for a, b in zip(first, second)],
                                "First": [labels[i] for i in first], "Second": [labels[i] for i in second],
                                "Difference": differences, "SE": se, "df": degrees}).set_index("Comparison")
    t = np.abs(differences / se)
    if posthoc in posthoc_choices:
        if posthoc == "dunnett":
            raw = 2 * stats.t.sf(t, degrees)
            coordinates = np.zeros((len(pairs), count))
            row = np.arange(len(pairs))
            coordinates[row, first] = 1 / np.sqrt(sizes[first])
            coordinates[row, second] = -1 / np.sqrt(sizes[second])
            standardized = coordinates / np.linalg.norm(coordinates, axis=1)[:, None]
            adjusted, critical = dunnett_scores(t, raw, standardized, degrees, 1 - level / 100)
            half_width = critical * se
            name, low, high = unequal_anova.DUNNETT, differences - half_width, differences + half_width
        else:
            name, test = UNEQUAL_POSTHOC[posthoc]
            raw, adjusted, low, high = test(differences, se, degrees, level)
        comparisons["Method"] = name
        comparisons["p"] = raw
        comparisons["Adjusted p"] = adjusted
        comparisons["CI low"] = low
        comparisons["CI high"] = high
        comparisons[unequal_anova.LEVEL] = level
        if name == unequal_anova.DUNNETT_T3:
            comparisons["Distribution df"] = unequal_anova.dunnett_t3_df(degrees)
    elif posthoc == range_test:
        comparisons["Method"] = "Games–Howell" if welch else "Tukey–Kramer"
        comparisons["Adjusted p"] = stats.studentized_range.sf(np.sqrt(2) * t, count, degrees)
        half_width = stats.studentized_range.ppf(.95, count, degrees) * se / np.sqrt(2)
        comparisons["CI 95% low"] = differences - half_width
        comparisons["CI 95% high"] = differences + half_width
    else:
        comparisons["Method"] = _ADJUSTMENTS[posthoc]
        comparisons["p"] = 2 * stats.t.sf(t, degrees)
        comparisons["Adjusted p"] = multipletests(comparisons["p"], method=posthoc)[1]
    result["Multiple comparisons"] = comparisons
    return result


def _matched_values(frame, response, factors, subject):
    """Return a complete matched array and the labels in each dimension."""
    keys = [subject, *factors]
    rows = frame.dropna(how="all", subset=[response, *keys])
    data = complete(rows, [response], keys)
    if len(data) != len(rows):
        raise ValueError("Matched data contain a missing subject, factor level or response.")
    if data.duplicated(keys).any():
        raise ValueError("Found duplicate measurements in a subject cell.")
    levels = [data[key].drop_duplicates().tolist() for key in keys]
    shape = tuple(map(len, levels))
    if min(shape) < 2:
        raise ValueError("Matched data require at least two subjects and two levels of each factor.")
    if prod(shape) != len(data):
        raise ValueError("Matched data must contain a complete set of factor combinations for every subject.")
    cells = pd.MultiIndex.from_product(levels, names=keys)
    return data.set_index(keys)[response].reindex(cells).to_numpy().reshape(shape), levels


def _effect_ss(values, axes):
    """Project a balanced array onto the centered effect for the selected axes."""
    averaged = tuple(axis for axis in range(values.ndim) if axis not in axes)
    effect = values.mean(axis=averaged, keepdims=True)
    for axis in axes:
        effect -= effect.mean(axis=axis, keepdims=True)
    return np.square(effect).sum() * (values.size // effect.size)


def _gg_epsilon(values):
    # Geisser–Greenhouse epsilon uses the covariance in the contrast space.
    contrasts = values - values.mean(axis=1, keepdims=True)
    contrasts -= contrasts.mean(axis=0, keepdims=True)
    # Both Gram matrices have the same nonzero eigenvalues.
    if contrasts.shape[1] > contrasts.shape[0]:
        contrasts = contrasts.T
    covariance = contrasts.T @ contrasts
    covariance /= np.trace(covariance)
    df = values.shape[1] - 1
    return float(np.clip(1 / (df * np.square(covariance).sum()), 1 / df, 1))


def repeated_measures_anova(frame, response, factors, subject, *, correction=None):
    """Fit a balanced one- or two-factor design with every factor within subject.

    Set correction="gg" for one-way Geisser–Greenhouse adjusted test degrees
    of freedom. The df used to compute mean squares remain unadjusted.
    """
    factors = tuple(factors)
    if len(factors) not in {1, 2}:
        raise ValueError("Select one or two within-subject factors.")
    if correction is not None and (correction != "gg" or len(factors) != 1):
        raise ValueError("Geisser–Greenhouse correction is available for one within-subject factor.")
    values, _ = _matched_values(frame, response, factors, subject)
    subject_df = values.shape[0] - 1
    ss_subject = _effect_ss(values - values.flat[0], (0,))
    rows = [{"Term": subject, "SS": ss_subject, "df": subject_df, "MS": ss_subject / subject_df}]
    # Remove each subject's baseline before averaging across subjects. Large
    # between-subject shifts should not affect within-subject contrasts.
    baseline_cell = (slice(None),) + (slice(0, 1),) * len(factors)
    within = values - values[baseline_cell]
    total_ss = np.square(within - within.mean()).sum()
    effects = [(name, (i,)) for i, name in enumerate(factors, start=1)]
    if len(factors) == 2:
        effects.append((":".join(factors), (1, 2)))
    for name, axes in effects:
        ss = _effect_ss(within, axes)
        df = prod(values.shape[axis] - 1 for axis in axes)
        error_ss = _effect_ss(within, (0, *axes))
        error_df = df * subject_df
        if not np.isfinite(error_ss) or error_ss <= np.finfo(float).eps**2 * total_ss:
            raise ValueError(f'No measurable subject-by-effect residual variance for "{name}".')
        statistic = (ss / df) / (error_ss / error_df)
        row = {"Term": name, "SS": ss, "df": df, "MS": ss / df, "F": statistic,
               "F df1": df, "F df2": error_df}
        if correction == "gg":
            epsilon = _gg_epsilon(within)
            row.update({"GG ε": epsilon, "F df1": df * epsilon, "F df2": error_df * epsilon})
        row["p"] = stats.f.sf(statistic, row["F df1"], row["F df2"])
        rows.extend([row, {"Term": f"{subject}:{name}", "SS": error_ss, "df": error_df,
                           "MS": error_ss / error_df}])
    return {"ANOVA": pd.DataFrame(rows).set_index("Term")}


def _friedman_assignments_within_limit(subjects, groups):
    """Check (groups!)^subjects <= limit with bounded integers."""
    total = 1
    for _ in range(subjects):
        total *= factorial(groups)
        if total > _EXACT_FRIEDMAN_LIMIT:
            return False
    return True


def friedman(frame, response, group, subject, *, comparisons=None):
    """Perform the tie-corrected Friedman test on complete matched sets.

    The P value option matches Kruskal–Wallis. Automatic uses the exact
    conditional permutation p when (groups!)^subjects is at most one billion
    and the counting stays within its state and transition budget, otherwise
    the chi-square approximation with the reason. Exact permutation reports a
    field error when it cannot be computed. Dunn comparisons do not depend on it.
    """
    options = comparisons or {}
    method = options.get(FRIEDMAN_P, AUTOMATIC_P)
    if method not in KRUSKAL_P_METHODS:
        raise FieldError(FRIEDMAN_P, "Choose automatic, exact permutation or chi-square.")
    values, (_, labels) = _matched_values(frame, response, [group], subject)
    subjects, groups = values.shape
    if groups < 3:
        raise ValueError("Friedman's test requires at least three matched groups.")
    if not np.any(values != values[:, :1]):
        raise ValueError("Friedman's statistic is undefined when every subject has only ties.")
    test = stats.friedmanchisquare(*values.T)
    p, used, reason = test.pvalue, CHI_SQUARE_P, None
    if method == CHI_SQUARE_P:
        pass
    elif method == AUTOMATIC_P and not _friedman_assignments_within_limit(subjects, groups):
        reason = (f"Too many equally likely rank assignments: ({groups}!)^{subjects} exceeds "
                  f"{_EXACT_FRIEDMAN_LIMIT:,}.")
    else:
        try:
            extreme, total = friedman_exact_tail(values)
        except ExactBudgetExceeded as error:
            if method == EXACT_P:
                raise FieldError(FRIEDMAN_P, f"Exact permutation exceeds the calculation limit ({error}) "
                                             "Choose Automatic or Chi-square approximation.") from error
            reason = f"The exact calculation exceeded its work limit. {error}"
        else:
            p, used = extreme / total, EXACT_P
    row = {"Subjects": subjects, "Groups": groups, "Statistic": test.statistic,
           "df": groups - 1, "p": p, "p method": used}
    if reason:
        row["p method reason"] = reason
    return {"Friedman": pd.DataFrame([row]), **dunn_comparisons(labels, values, options, matched=True)}
