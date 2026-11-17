"""REML for factorial repeated measurements with independent subject effects."""

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, product
from math import comb, prod

import numpy as np
import pandas as pd
from scipy import linalg, optimize, stats
from statsmodels.stats.multitest import multipletests

from .kenward_roger import _KenwardRoger
from .stats import complete


_INFERENCE_METHODS = {"satterthwaite": "Satterthwaite", "kenward-roger": "Kenward–Roger"}

_ADJUSTMENTS = {
    "unadjusted": "Unadjusted",
    "bonferroni": "Bonferroni",
    "sidak": "Šídák",
    "holm": "Holm",
    "holm-sidak": "Holm–Šídák",
}


def _design(frame, response, factors, subject, within):
    keys = [subject, *factors]
    columns = [response, *keys]
    if len(set(columns)) != len(columns) or any(name not in frame.columns for name in columns):
        raise ValueError("Select distinct response, subject and factor columns.")
    rows = frame.loc[:, columns].dropna(how="all")
    if rows[keys].isna().any().any():
        raise ValueError("Repeated measurements contain a missing subject or factor level.")
    between = [factor for factor in factors if factor not in within]
    if between and (rows.groupby(subject, sort=False, observed=True)[between].nunique() > 1).any().any():
        raise ValueError("Each subject must have a constant level for every between-subject factor.")
    if rows.duplicated([subject, *within]).any():
        raise ValueError("Found duplicate measurements in a subject cell.")

    observed = complete(rows, [response], keys)
    levels = [rows[factor].drop_duplicates().tolist() for factor in factors]
    shape = tuple(map(len, levels))
    if min(shape) < 2:
        raise ValueError("Each model factor must have at least two levels.")
    if len(observed[list(factors)].drop_duplicates()) != prod(shape):
        raise ValueError("The full factorial model has an empty fixed-effect cell.")
    if prod(shape) > 256:
        raise ValueError("The mixed model supports up to 256 fixed-effect cells.")

    cell_codes = [pd.Categorical(observed[factor], categories=values).codes
                  for factor, values in zip(factors, levels)]
    cell = np.ravel_multi_index(cell_codes, shape)
    subjects, _ = pd.factorize(observed[subject], sort=False)
    expected = prod(len(values) for factor, values in zip(factors, levels) if factor in within)
    counts = pd.DataFrame({
        "Rows supplied": rows.groupby(subject, sort=False, observed=True).size(),
        "Observations used": observed.groupby(subject, sort=False, observed=True).size(),
    }).fillna(0).astype(int)
    counts["Response rows omitted"] = counts["Rows supplied"] - counts["Observations used"]
    counts["Cells missing"] = expected - counts["Observations used"]
    return observed[response].to_numpy(), cell, subjects, levels, counts


class _RestrictedLikelihood:
    """Profiled Gaussian restricted likelihood using subject block projections."""

    def __init__(self, y, cell, subject, n_cells):
        self.y, self.cell, self.subject = y, cell, subject
        self.df = len(y) - n_cells
        size = np.bincount(subject)
        self.root_size = np.sqrt(size)
        self.sizes, self.blocks, self.multiplicity = np.unique(size, return_inverse=True, return_counts=True)
        means = np.bincount(subject, weights=y) / size
        x_mean = np.zeros((len(size), n_cells))
        np.add.at(x_mean, (subject, cell), 1)
        self.x_mean = x_mean / self.root_size[:, None]
        y_mean = means * self.root_size
        mean_gram, mean_rhs = [], []
        for i in range(len(self.sizes)):
            mask = self.blocks == i
            matrix = self.x_mean[mask]
            mean_gram.append(matrix.T @ matrix)
            mean_rhs.append(matrix.T @ y_mean[mask])
        self.mean_gram = np.stack(mean_gram)
        self.mean_rhs = np.stack(mean_rhs)
        self.within_gram = np.diag(np.bincount(cell)) - self.mean_gram.sum(axis=0)
        self.within_rhs = np.bincount(cell, weights=y - means[subject])

    def profile(self, log_ratio, *, details=False, derivative=False):
        # V = sigma²(I + ratio ZZ'), ratio = tau²/sigma². Per subject, the
        # projection onto its mean has inverse weight 1/(1 + size*ratio).
        ratio = np.expm1(log_ratio)
        block_scale = 1 + self.sizes * ratio
        weight = 1 / block_scale
        gram = self.within_gram + np.einsum("b,bij->ij", weight, self.mean_gram)
        rhs = self.within_rhs + weight @ self.mean_rhs
        factor = linalg.cho_factor(gram, check_finite=False)
        beta = linalg.cho_solve(factor, rhs, check_finite=False)
        residual = self.y - beta[self.cell]
        projected = np.bincount(self.subject, weights=residual) / self.root_size
        centered = residual - (projected / self.root_size)[self.subject]
        projected_ss = np.bincount(self.blocks, weights=projected**2)
        sigma2 = (centered @ centered + weight @ projected_ss) / self.df
        if sigma2 <= np.finfo(float).eps**2:
            raise ValueError("No measurable residual variation for the mixed model.")
        objective = (self.df * np.log(sigma2) + self.multiplicity @ np.log(block_scale)
                     + 2 * np.log(np.diag(factor[0])).sum())
        if not (details or derivative):
            return objective

        # Analytic derivatives in (log(sigma²), log(1 + ratio)). At an
        # interior optimum, the inverse observed REML Hessian estimates
        # the covariance of these parameters for the Satterthwaite method.
        rate = self.sizes * np.exp(log_ratio) * weight
        first = -weight * rate
        gram_first = np.einsum("b,bij->ij", first, self.mean_gram)
        ss_first = first @ projected_ss
        if derivative:
            relative = linalg.cho_solve(factor, gram_first, check_finite=False)
            return ss_first / sigma2 + self.multiplicity @ rate + np.trace(relative)

        inverse = linalg.cho_solve(factor, np.eye(len(beta)), check_finite=False)
        second = weight * (2 * rate**2 - rate)
        gram_second = np.einsum("b,bij->ij", second, self.mean_gram)
        relative = inverse @ gram_first
        determinant_second = (self.multiplicity @ (rate - rate**2)
                              + np.trace(inverse @ gram_second - relative @ relative))
        rhs_first = self.x_mean.T @ (first[self.blocks] * projected)
        ss_second = second @ projected_ss - 2 * rhs_first @ inverse @ rhs_first
        hessian = .5 * np.array([[self.df, -ss_first / sigma2],
                                 [-ss_first / sigma2, determinant_second + ss_second / sigma2]])
        covariance = sigma2 * inverse
        return beta, covariance, sigma2, ratio * sigma2, -relative @ covariance, hessian


@dataclass
class _Fit:
    beta: np.ndarray
    covariance: np.ndarray
    variance_gradient: np.ndarray
    parameter_covariance: np.ndarray | None
    origin: float
    scale: float
    variances: dict
    status: str
    inference: str
    kr: _KenwardRoger | None = None
    legacy_df: int | None = None

    def degrees(self, contrasts, variances):
        if self.legacy_df is not None:
            return np.full(len(contrasts), self.legacy_df, dtype=float)
        if self.parameter_covariance is None:
            return np.full(len(contrasts), np.nan)
        # Use the gradient of log contrast variance to avoid squaring a
        # small variance. The rows correspond to separate contrasts.
        derivatives = (np.einsum("ni,kij,nj->nk", contrasts, self.variance_gradient, contrasts)
                       / variances[:, None])
        denominator = np.einsum("ni,ij,nj->n", derivatives, self.parameter_covariance, derivatives)
        if np.any(~np.isfinite(denominator) | (denominator <= 0)):
            raise ValueError("Could not estimate valid Satterthwaite degrees of freedom.")
        return 2 / denominator

    def estimates(self, contrasts):
        values = self.origin * contrasts.sum(axis=1) + self.scale * (contrasts @ self.beta)
        if self.inference == "kenward-roger":
            if self.kr is None:
                return values, np.full(len(contrasts), np.nan), np.full(len(contrasts), np.nan)
            variances = np.einsum("ni,ij,nj->n", contrasts, self.kr.covariance, contrasts)
            df = self.kr.degrees(contrasts)
            return values, np.where(np.isfinite(df), self.scale * np.sqrt(variances), np.nan), df
        variances = np.einsum("ni,ij,nj->n", contrasts, self.covariance, contrasts)
        standard_errors = self.scale * np.sqrt(variances)
        return values, standard_errors, self.degrees(contrasts, variances)


def _fit_intercept(y, cell, subject, n_cells):
    model = _RestrictedLikelihood(y, cell, subject, n_cells)
    # Search the one-dimensional profile including the zero-variance boundary.
    # Refine each sampled minimum; unbalanced data need not have a unimodal profile.
    near_zero = np.geomspace(1e-6, 1, 33)
    grid = np.unique(np.r_[0., near_zero, np.linspace(1, np.log1p(1e10), 41)])
    scores = np.array([model.profile(value) for value in grid])
    if np.ptp(scores) < 1e-9:
        raise ValueError("The residual and subject variances are not separately identifiable.")
    candidates = list(zip(scores, grid))

    def slope(value):
        return model.profile(value, derivative=True)

    slopes = np.array([slope(value) for value in grid])
    # Bracket consecutive slopes. A three-point window around a sampled
    # minimum can contain a nearby maximum as well, hiding the change of sign.
    for index in np.flatnonzero((slopes[:-1] < 0) & (slopes[1:] > 0)):
        root = optimize.brentq(slope, grid[index], grid[index + 1])
        candidates.append((model.profile(root), root))
    score, location = min(candidates)
    if location >= grid[-1] - 1e-4:
        raise ValueError("The residual variance approaches zero or the variance ratio is too large to fit reliably.")
    if scores[0] - score < 1e-10:
        location = 0.
    beta, cov, sigma2, tau2, gradient, hessian = model.profile(location, details=True)
    return beta, cov, np.stack((cov, gradient)), hessian, np.array([sigma2, tau2])


class _FactorialLikelihood:
    """REML with crossed random subject effects, grouped by observed cell pattern."""

    def __init__(self, y, cell, subject, shape, terms):
        self.n_cells = prod(shape)
        self.n_variances = 2 + len(terms)
        patterns = defaultdict(list)
        order = np.lexsort((cell, subject))
        ends = np.flatnonzero(np.diff(subject[order])) + 1
        for rows in np.split(order, ends):
            patterns[tuple(cell[rows])].append(y[rows])
        self.patterns = []
        for codes, observations in patterns.items():
            cells = np.asarray(codes)
            axes = np.unravel_index(cells, shape)
            bases = [np.eye(len(cells)), np.ones((len(cells), len(cells)))]
            for term in terms:
                matches = [axes[i][:, None] == axes[i] for i in term]
                bases.append(np.logical_and.reduce(matches))
            values = np.asarray(observations)
            self.patterns.append((cells, np.stack(bases), values, values.sum(axis=0)))

    def evaluate(self, variances, *, details=False):
        gram = np.zeros((self.n_cells, self.n_cells))
        rhs = np.zeros(self.n_cells)
        gram_derivative = np.zeros((self.n_variances, self.n_cells, self.n_cells))
        score = np.zeros(self.n_variances)
        log_det = 0.
        precisions = []
        for cells, bases, values, totals in self.patterns:
            v = np.einsum("k,kij->ij", variances, bases)
            factor = linalg.cho_factor(v, check_finite=False)
            inverse = linalg.cho_solve(factor, np.eye(len(cells)), check_finite=False)
            count = len(values)
            weighted_bases = inverse @ bases
            gram[np.ix_(cells, cells)] += count * inverse
            rhs[cells] += inverse @ totals
            gram_derivative[:, cells[:, None], cells] += count * (weighted_bases @ inverse)
            score += count * np.trace(weighted_bases, axis1=1, axis2=2)
            log_det += 2 * count * np.log(np.diag(factor[0])).sum()
            precisions.append(inverse)

        fixed = linalg.cho_factor(gram, check_finite=False)
        beta = linalg.cho_solve(fixed, rhs, check_finite=False)
        covariance = linalg.cho_solve(fixed, np.eye(self.n_cells), check_finite=False)
        log_det += 2 * np.log(np.diag(fixed[0])).sum()
        score -= np.einsum("ij,kji->k", covariance, gram_derivative)
        for (cells, bases, values, _), inverse in zip(self.patterns, precisions):
            residual = values - beta[cells]
            weighted = residual @ inverse
            log_det += np.sum(residual * weighted)
            score -= np.einsum("ni,kij,nj->k", weighted, bases, weighted)
        if details:
            covariance_gradient = (covariance @ gram_derivative @ covariance) * variances[:, None, None]
            return beta, covariance, covariance_gradient
        return .5 * log_det, .5 * score


def _fit_factorial(y, model, *, satterthwaite):
    count = model.n_variances
    total = np.var(y)
    lower = total * 1e-10
    bounds = [(lower, None)] + [(0, None)] * (count - 1)
    starts = [np.full(count, total / count),
              np.r_[.2 * total, .7 * total, np.full(count - 2, .1 * total / (count - 2))]]
    fits = [optimize.minimize(model.evaluate, start, jac=True, bounds=bounds, method="L-BFGS-B",
                              options={"ftol": 1e-13, "gtol": 1e-8, "maxiter": 1200})
            for start in starts]
    successful = [result for result in fits if result.success and np.isfinite(result.fun)]
    if not successful:
        raise ValueError("REML optimization did not converge for the factorial covariance model.")
    variances = min(successful, key=lambda result: result.fun).x
    if variances[0] <= 10 * lower:
        raise ValueError("The residual variance approaches zero or the variance ratio is too large to fit reliably.")
    variances[1:] = np.where(variances[1:] <= lower, 0, variances[1:])
    beta, covariance, gradient = model.evaluate(variances, details=True)
    hessian = None
    if satterthwaite and (variances > 0).all():
        # Differentiate the analytic score in log variance coordinates.
        columns = []
        for step in np.eye(count) * 1e-4:
            plus, minus = variances * np.exp(step), variances * np.exp(-step)
            score_plus, score_minus = model.evaluate(plus)[1], model.evaluate(minus)[1]
            columns.append((score_plus * plus - score_minus * minus) / 2e-4)
        numerical = np.column_stack(columns)
        hessian = (numerical + numerical.T) / 2
    return beta, covariance, gradient, hessian, variances


def _fit_reml(y, cell, subject, shape, factors, within, *, inference="satterthwaite", nested=False):
    n_cells = prod(shape)
    if len(y) - n_cells < 2 or len(np.unique(subject)) < 2 or np.bincount(subject).max() < 2:
        raise ValueError("Too few independent subjects, repeated observations or residual degrees of freedom.")
    origin = float(y[0])
    with np.errstate(over="ignore"):
        centered = y - origin
    scale = float(np.max(np.abs(centered)))
    if not np.isfinite(scale):
        raise ValueError("Responses exceed the supported numeric range.")
    if scale == 0:
        raise ValueError("No measurable residual variation for the mixed model.")
    y = centered / scale

    axes = [i for i, factor in enumerate(factors) if factor in within]
    terms = [term for order in range(1, len(axes)) for term in combinations(axes, order)]
    names = ["Residual", "Subject random intercept", *(
        "Subject × " + ":".join(factors[i] for i in term) for term in terms)]
    model = _FactorialLikelihood(y, cell, subject, shape, terms) if terms else None
    if model is not None:
        beta, covariance, gradient, hessian, estimates = _fit_factorial(
            y, model, satterthwaite=inference == "satterthwaite")
    else:
        beta, covariance, gradient, hessian, estimates = _fit_intercept(y, cell, subject, n_cells)

    with np.errstate(over="ignore", under="ignore"):
        estimates_scaled = np.square(scale * np.sqrt(estimates))
    if not np.isfinite(estimates_scaled).all() or np.any((estimates > 0) & (estimates_scaled <= 0)):
        raise ValueError("The fitted variance is outside the supported numeric range.")

    parameter_covariance = kr = legacy_df = None
    zero = ", ".join(name for name, estimate in zip(names, estimates) if estimate == 0)
    boundary = f"Estimated variance is zero for {zero}." if zero else ""
    if nested and inference == "legacy":
        legacy_df = len(np.unique(subject)) - n_cells
        status = boundary or "Converged"
    elif zero and not (nested and inference == "kenward-roger"):
        status = f"Singular fit. {boundary} {_INFERENCE_METHODS[inference]} inference unavailable."
    elif inference == "kenward-roger":
        if model is None:
            model = _FactorialLikelihood(y, cell, subject, shape, terms)
        patterns = [(cells, bases, len(values)) for cells, bases, values, _ in model.patterns]
        try:
            kr = _KenwardRoger.fit(covariance, estimates, patterns)
            status = boundary or "Converged"
        except ValueError as error:
            status = f"{error} Kenward–Roger inference unavailable."
        except linalg.LinAlgError:
            status = "Could not compute the adjusted covariance. Kenward–Roger inference unavailable."
    else:
        eigenvalues = linalg.eigvalsh(hessian)
        if eigenvalues[0] <= 1e-10 * eigenvalues[-1]:
            status = "Variance uncertainty is not estimable. Satterthwaite inference unavailable."
        else:
            parameter_covariance = linalg.solve(hessian, np.eye(len(estimates)), assume_a="pos")
            status = "Converged"
    variance_table = dict(zip(names[1:] + names[:1], np.r_[estimates_scaled[1:], estimates_scaled[0]]))
    return _Fit(beta, covariance, gradient, parameter_covariance, origin, scale, variance_table, status,
                inference, kr, legacy_df)


def _satterthwaite_test(fit, contrasts):
    tested = contrasts @ fit.covariance @ contrasts.T
    variances, vectors = linalg.eigh(tested)
    rotated = vectors.T @ contrasts
    df1 = len(rotated)
    f = np.sum((rotated @ fit.beta)**2 / variances) / df1
    df = fit.degrees(rotated, variances)
    # Fai–Cornelius moment matching, as implemented by lmerTest
    # (Kuznetsova et al. 2017, doi:10.18637/jss.v082.i13).
    df2 = df.mean()
    if df1 > 1 and np.isfinite(df2) and np.ptp(df) > 1e-8:
        df2 = 2. if np.any(df <= 2) else 2 + df1 / np.sum(1 / (df - 2))
    return f, df2


def _omnibus(fit, factors, shape):
    rows = []
    kenward_roger = fit.inference == "kenward-roger"
    columns = ["Term", "F", "F df1", "F df2", "p"]
    if kenward_roger:
        columns.append("F scaling")
    for order in range(1, len(shape) + 1):
        for axes in combinations(range(len(shape)), order):
            # Helmert contrasts span the differences of equally weighted cell
            # means, marginalizing over the factors outside the tested term.
            contrasts = np.ones((1, 1))
            for axis, size in enumerate(shape):
                basis = linalg.helmert(size) if axis in axes else np.full((1, size), 1 / size)
                contrasts = np.kron(contrasts, basis)
            df1 = len(contrasts)
            if kenward_roger:
                f, df2, scaling = (np.nan, np.nan, np.nan) if fit.kr is None else fit.kr.test(contrasts, fit.beta)
            else:
                f, df2 = _satterthwaite_test(fit, contrasts)
            row = [":".join(factors[i] for i in axes), f, df1, df2, stats.f.sf(f, df1, df2)]
            if kenward_roger:
                row.append(scaling)
            rows.append(row)
    return pd.DataFrame(rows, columns=columns).set_index("Term")


def _estimate_table(fit, contrasts, index):
    estimate, se, df = fit.estimates(contrasts)
    half_width = stats.t.isf(.025, df) * se
    return pd.DataFrame({"Estimate": estimate, "SE": se, "df": df,
                         "CI 95% low": estimate - half_width, "CI 95% high": estimate + half_width},
                        index=index)


def _comparison_rows(fit, contrasts, factor, levels, condition, family):
    pairs = list(combinations(range(len(levels)), 2))
    left, right = np.asarray(pairs).T
    differences = contrasts[left] - contrasts[right]
    label = f"{condition} | {factor}" if condition else factor
    index = pd.Index([f"{label} | {levels[a]} − {levels[b]}" for a, b in pairs], name="Comparison")
    diff, se, df = fit.estimates(differences)
    t = diff / se
    p = 2 * stats.t.sf(np.abs(t), df)
    return pd.DataFrame({"Factor": factor, "Condition": condition, "Family": label if family == "separate" else "All",
                         "First": [levels[i] for i in left], "Second": [levels[i] for i in right],
                         "Difference": diff, "SE": se, "df": df, "t": t, "p": p}, index=index)


def _adjust_comparisons(table, method, *, level=.95):
    p = table["p"].to_numpy()
    alpha = 1 - level
    table["Method"] = _ADJUSTMENTS[method]
    if method == "unadjusted":
        table["Adjusted p"] = p
    else:
        table["Adjusted p"] = multipletests(p, method=method)[1] if np.isfinite(p).all() else np.nan
    if method == "bonferroni":
        alpha /= len(table)
    elif method == "sidak":
        alpha = -np.expm1(np.log1p(-alpha) / len(table))
    elif method in {"holm", "holm-sidak"}:
        alpha = np.nan  # No simultaneous interval for the sequential adjustment.
    margin = stats.t.isf(alpha / 2, table["df"]) * table["SE"]
    table[f"CI {level * 100:g}% low"] = table["Difference"] - margin
    table[f"CI {level * 100:g}% high"] = table["Difference"] + margin


def _comparisons(fit, factors, levels, grid, method, compare, condition, family):
    strata = [factors.index(factor) for factor in condition]
    strata_levels = [levels[i] for i in strata]
    conditions = list(product(*strata_levels))
    compared = range(len(factors)) if compare is None else [factors.index(compare)]
    tables = []
    for axis in compared:
        labels = levels[axis]
        selected = [*strata, axis]
        remaining = [i for i in range(len(factors)) if i not in selected]
        ordered = grid.transpose(*selected, *remaining, len(factors))
        weights = ordered.reshape(len(conditions), len(labels), -1, grid.shape[-1]).mean(axis=2)
        for values, contrasts in zip(conditions, weights):
            label = ", ".join(f"{factor}={value}" for factor, value in zip(condition, values))
            tables.append(_comparison_rows(fit, contrasts, factors[axis], labels, label, family))
    if family == "pooled":
        tables = [pd.concat(tables)]
    for table in tables:
        _adjust_comparisons(table, method)
    return pd.concat(tables)


def mixed_effects_anova(frame, response, factors, subject, *, within=None, posthoc=None,
                        compare=None, condition=(), family="separate", inference="satterthwaite"):
    """Fit all fixed interactions and random subject effects by REML.

    Factors outside within are between subjects. Omitted or absent responses
    leave the rest of a subject's measurements in the fit. Fixed effects use
    equal-cell-weight Type III hypotheses. Pairwise comparisons, when
    requested, default to all levels of each factor with separate adjustment
    families. Select compare and condition for simple effects, or family
    "pooled" to adjust across strata. Multiple within-subject factors add
    random effects for the proper subsets of the within factors. Select
    inference="kenward-roger" for adjusted covariance and scaled F tests.
    """
    factors = (factors,) if isinstance(factors, str) else tuple(factors)
    within = factors if within is None else (within,) if isinstance(within, str) else tuple(within)
    if len(factors) not in {1, 2, 3}:
        raise ValueError("Select one to three model factors.")
    if not within or len(set(within)) != len(within) or set(within) - set(factors):
        raise ValueError("Select at least one distinct within-subject factor from the model.")
    if inference not in _INFERENCE_METHODS:
        raise ValueError("Unknown inference method for mixed-model analysis.")
    if posthoc not in {None, *_ADJUSTMENTS}:
        raise ValueError("Unknown adjustment for mixed-model comparisons.")
    condition = (condition,) if isinstance(condition, str) else tuple(condition)
    if family not in {"separate", "pooled"}:
        raise ValueError("Select separate or pooled comparison families.")
    if posthoc is None and (compare is not None or condition or family == "pooled"):
        raise ValueError("Enable multiple comparisons to select a factor or family scope.")
    if (compare is not None and compare not in factors) or (condition and (
            compare is None or compare in condition or len(set(condition)) != len(condition)
            or set(condition) - set(factors))):
        raise ValueError("Select distinct comparison and conditioning factors from the model.")

    y, cell, subjects, levels, counts = _design(frame, response, factors, subject, within)
    shape = tuple(map(len, levels))
    if posthoc is not None:
        by_factor = dict(zip(factors, shape))
        pairs = (sum(comb(n, 2) for n in shape) if compare is None else
                 comb(by_factor[compare], 2) * prod(by_factor[factor] for factor in condition))
        if pairs > 1000:
            raise ValueError("The mixed model supports up to 1000 pairwise comparisons.")
    n_cells = prod(shape)
    fit = _fit_reml(y, cell, subjects, shape, factors, within, inference=inference)

    used = counts["Observations used"] > 0
    incomplete = counts["Cells missing"] > 0
    summary = pd.DataFrame([{
        "Method": "Restricted maximum likelihood (REML)",
        "Covariance": ("Compound symmetry (one subject random intercept)" if len(within) == 1 else
                       "Independent subject and subject-by-within variance components"),
        "Fixed effects": "Full factorial, Type III (equal cell weights)",
        "Denominator df": (_INFERENCE_METHODS[inference]
                           if fit.parameter_covariance is not None or fit.kr is not None else "Unavailable"),
        "Within-subject factors": ", ".join(within),
        "Between-subject factors": ", ".join(factor for factor in factors if factor not in within),
        "Status": fit.status,
        "Observations used": len(y),
        "Response rows omitted": counts["Response rows omitted"].sum(),
        "Subject cells missing": counts["Cells missing"].sum(),
        "Subjects used": used.sum(),
        "Subjects partial": (used & incomplete).sum(),
        "Subjects excluded": (~used).sum(),
    }])
    variances = pd.Series(fit.variances, name="Variance").rename_axis("Component").to_frame()
    variances["SD"] = np.sqrt(variances["Variance"])
    identity = np.eye(n_cells)
    estimates = _estimate_table(fit, identity, pd.RangeIndex(n_cells))
    cell_labels = pd.DataFrame(product(*levels), columns=factors)
    reserved = set(cell_labels.columns) | set(estimates.columns)
    for factor in set(cell_labels.columns) & set(estimates.columns):
        label = f"{factor} (factor)"
        while label in reserved:
            label += " (factor)"
        cell_labels.rename(columns={factor: label}, inplace=True)
        reserved.add(label)
    estimates = pd.concat([cell_labels, estimates], axis=1)
    grid = identity.reshape(*shape, n_cells)
    means = []
    for axis, (factor, labels) in enumerate(zip(factors, levels)):
        other_axes = tuple(i for i in range(len(shape)) if i != axis)
        weights = grid.mean(axis=other_axes)
        names = pd.Index([f"{factor}={value}" for value in labels], name="Mean")
        marginal = _estimate_table(fit, weights, names)
        marginal.insert(0, "Level", labels)
        marginal.insert(0, "Factor", factor)
        means.append(marginal)

    result = {"Model": summary, "Fixed effects": _omnibus(fit, factors, shape),
              "Variance components": variances, "Fixed estimates": estimates,
              "Estimated marginal means": pd.concat(means), "Subjects": counts}
    if posthoc is not None:
        result["Multiple comparisons"] = _comparisons(fit, factors, levels, grid, posthoc, compare, condition, family)
    if fit.kr is not None and (result["Fixed effects"]["F df2"].isna().any()
                               or any(table["df"].isna().any() for table in result.values() if "df" in table)):
        summary.loc[0, "Status"] = "Converged. Kenward–Roger inference unavailable for some hypotheses."
    return result
