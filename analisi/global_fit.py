"""Joint least-squares regression with shared, local and fixed parameters."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy import optimize, stats

from .curve_models import MODELS, CurveModel
from .fit_weights import (GLOBAL_WEIGHTINGS, INFERENCE_WEIGHTS, INVERSE_VARIANCE, iterate_weights,
                          observed_scales, uses_fitted_y, uses_observed_y)
from .stats import Fit, complete


_SOLVER_TOL = 1e-11


@dataclass
class GroupFit(Fit):
    band: np.ndarray | None


@dataclass
class GlobalFit:
    parameters: pd.DataFrame
    groups: dict
    diagnostics: dict
    covariance: pd.DataFrame
    comparison: dict | None = None
    comparison_note: str | None = None
    local_comparison: dict | None = None
    local_comparison_note: str | None = None


@dataclass
class _Solution:
    estimates: np.ndarray
    coordinates: list
    mapping: np.ndarray
    active: np.ndarray
    values: np.ndarray
    # A square root of the covariance in the optimizer's dimensionless coordinates.
    factor: np.ndarray
    scale: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    ss: float
    residual: Callable


@dataclass
class _Problem:
    spec: CurveModel
    labels: tuple
    xs: list
    ys: list
    sds: list
    lower: np.ndarray
    upper: np.ndarray
    # Rows are series, columns are model parameters, and NaN marks a free parameter.
    fixed: np.ndarray

    def solve(self, shared, initial):
        names = self.spec.parameters
        mapping = np.full((len(self.labels), len(names)), -1, dtype=int)
        coordinates = []
        lower, upper = [], []
        starts = []
        free_parameters = np.isnan(self.fixed)
        for j, name in enumerate(names):
            if name in shared:
                if not free_parameters[:, j].all():
                    raise ValueError(f"{name}: cannot share a parameter fixed for an individual series.")
                lo, hi = self.lower[:, j].max(), self.upper[:, j].min()
                if lo >= hi:
                    raise ValueError(f"{name}: series bounds must overlap to share this parameter.")
                mapping[:, j] = len(coordinates)
                coordinates.append(("Shared", None, name))
                lower.append(lo)
                upper.append(hi)
                seed = float(np.median(initial[:, j]))
                starts.append(_interior_start(seed, lo, hi, name) if not lo < seed < hi else seed)
        for i, label in enumerate(self.labels):
            for j, name in enumerate(names):
                if mapping[i, j] == -1 and free_parameters[i, j]:
                    mapping[i, j] = len(coordinates)
                    coordinates.append(("Local", label, name))
                    lower.append(self.lower[i, j])
                    upper.append(self.upper[i, j])
                    starts.append(initial[i, j])

        n_free = len(coordinates)
        n_obs = sum(map(len, self.xs))
        if n_free > 256 or n_obs * n_free > 2_000_000:
            raise ValueError("Global regression exceeds the dense Jacobian budget. Reduce rows or share more parameters.")
        df = n_obs - n_free
        if df <= 0:
            raise ValueError("Global regression requires more observations than free parameters.")

        lower, upper = np.asarray(lower), np.asarray(upper)
        start = np.clip(starts, lower, upper)
        scale = np.where(start == 0., 1., np.abs(start))
        free = mapping >= 0

        def unpack(values):
            parameters = self.fixed.copy()
            parameters[free] = (values * scale)[mapping[free]]
            return parameters

        def residual(values):
            parameters = unpack(values)
            return np.concatenate([
                (self.spec.equation(x, *p) - y) / sd
                for x, y, sd, p in zip(self.xs, self.ys, self.sds, parameters, strict=True)
            ])

        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            lower, upper = lower / scale, upper / scale
            if not n_free:
                values = active = np.empty(0)
                errors = residual(values)
                factor = np.empty((0, 0))
            else:
                optimized = _minimize(residual, start / scale, lower, upper)
                optimized = _polish_bounds(residual, optimized, lower, upper)
                values, errors = optimized.x, optimized.fun
                factor = _covariance_factor(optimized.jac, errors, df)
                # All quantities here scale together when a starting value
                # changes the optimizer units. The optimizer's absolute
                # active-mask tolerance is tied to those arbitrary units.
                typical = np.maximum(np.abs(values), np.linalg.norm(factor, axis=1))
                active = np.zeros(n_free, dtype=bool)
                for bound in (lower, upper):
                    finite = np.isfinite(bound)
                    margin = 1e-7 * np.maximum(typical[finite], np.abs(bound[finite]))
                    active[finite] |= np.abs(values[finite] - bound[finite]) <= margin
        ss = float(errors @ errors)
        if not np.isfinite(ss):
            raise ValueError("Global residual sum of squares exceeds the numerical range.")
        return _Solution(unpack(values), coordinates, mapping, active, values, factor,
                         scale, lower, upper, ss, residual)


def _minimize(residual, start, lower, upper, *, max_evaluations=20000, method="trf"):
    message = "Could not minimize the global regression reliably."
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        try:
            optimized = optimize.least_squares(residual, start, bounds=(lower, upper),
                                               jac="3-point", x_scale="jac", max_nfev=max_evaluations, method=method,
                                               ftol=_SOLVER_TOL if method == "trf" else None,
                                               xtol=_SOLVER_TOL, gtol=_SOLVER_TOL)
        except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as error:
            raise ValueError(message) from error
    if not optimized.success or not np.isfinite(optimized.x).all():
        raise ValueError(message)
    return optimized


def _polish_bounds(residual, solution, lower, upper):
    # TRF scales an outward gradient by its distance from the bound. A
    # weakly active coordinate can therefore stop about sqrt(tol) away
    # from the bound in Jacobian-scaled units. Dogbox can reach it exactly
    # or move to the nearby interior optimum without that scaling.
    slope = np.linalg.norm(solution.jac, axis=0)
    threshold = 4 * np.sqrt(_SOLVER_TOL * max(1., solution.cost))
    for distance, gradient in ((solution.x - lower, solution.grad), (upper - solution.x, -solution.grad)):
        if np.any((distance > 0) & (distance * slope <= threshold) & (gradient > 0)):
            return _minimize(residual, solution.x, lower, upper, max_evaluations=100, method="dogbox")
    return solution


def _covariance_factor(jacobian, errors, df):
    # Assess rank after normalizing each derivative column so units alone do
    # not create a singularity. Central differences have finite precision.
    norms = np.linalg.norm(jacobian, axis=0)
    if not np.isfinite(norms).all() or (norms == 0).any():
        raise ValueError("Global regression parameters are not identifiable from these observations.")
    _, singular, vectors = np.linalg.svd(jacobian / norms, full_matrices=False)
    if singular[-1] <= np.sqrt(np.finfo(float).eps) * singular[0]:
        raise ValueError("Global regression parameters are not identifiable from these observations.")
    return ((vectors.T / singular) / norms[:, None]) * np.sqrt(errors @ errors / df)


def _intersect_bounds(name, lo, hi, limits):
    try:
        lower, upper = limits
        lower = -np.inf if lower is None else float(lower)
        upper = np.inf if upper is None else float(upper)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name}: specify numeric lower and upper bounds.") from error
    if np.isnan(lower) or np.isnan(upper) or lower == np.inf or upper == -np.inf:
        raise ValueError(f"{name}: specify valid lower and upper bounds.")
    return max(lo, lower), min(hi, upper)


def _bounded_value(name, raw, lo, hi, kind):
    message = f"{name}: specify a finite {kind} value within the bounds."
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if not np.isfinite(value) or not lo <= value <= hi:
        raise ValueError(message)
    return value


def _parameter_options(spec, shared, fixed, bounds, initial, compare_local):
    names = spec.parameters
    shared, compare_local = set(shared), set(compare_local)
    fixed, bounds, initial = dict(fixed or {}), dict(bounds or {}), dict(initial or {})
    unknown = (shared | fixed.keys() | bounds.keys() | initial.keys() | compare_local) - set(names)
    if unknown:
        raise ValueError("Unknown regression parameter: " + ", ".join(map(str, unknown)))
    shared -= fixed.keys()
    if compare_local & (shared | fixed.keys()):
        raise ValueError("Select only local parameters for the additional sharing comparison.")

    lower, upper = (np.broadcast_to(bound, len(names)).astype(float) for bound in spec.bounds)
    for j, name in enumerate(names):
        if name in bounds:
            lower[j], upper[j] = _intersect_bounds(name, lower[j], upper[j], bounds[name])
        lo, hi = lower[j], upper[j]
        if lo > hi or (lo == hi and name not in fixed):
            raise ValueError(f"{name}: the lower bound must be smaller than the upper bound.")
        if name in fixed:
            fixed[name] = _bounded_value(name, fixed[name], lo, hi, "fixed")
        if name in initial:
            if name in fixed:
                raise ValueError(f"{name}: a fixed parameter does not need an initial value.")
            initial[name] = _bounded_value(name, initial[name], lo, hi, "initial")
    return shared, fixed, (lower, upper), initial, compare_local


def _series_options(labels, names, shared, fixed, bounds, initial, constraints):
    shape = (len(labels), len(names))
    lower, upper = (np.broadcast_to(limit, shape).copy() for limit in bounds)
    fixed_values = np.tile([fixed.get(name, np.nan) for name in names], (len(labels), 1))
    starts = np.tile([initial.get(name, np.nan) for name in names], (len(labels), 1))
    indices = {label: i for i, label in enumerate(labels)}
    if constraints is None:
        constraints = {}
    if not isinstance(constraints, Mapping):
        raise ValueError("Specify parameter constraints by series.")
    for label, parameters in constraints.items():
        if label not in indices:
            raise ValueError(f"Unknown regression series: {label!r}")
        i = indices[label]
        if not isinstance(parameters, Mapping):
            raise ValueError(f"{label!r}: specify series constraints by parameter.")
        for name, options in parameters.items():
            if name not in names:
                raise ValueError(f"{label!r}: unknown regression parameter {name!r}.")
            context = f"{label!r}, {name}"
            if not isinstance(options, Mapping) or options.keys() - {"fixed", "lower", "upper", "initial"}:
                raise ValueError(f"{context}: unknown series constraint option.")
            j = names.index(name)
            value, start = options.get("fixed"), options.get("initial")
            if value is not None or start is not None:
                if name in shared:
                    raise ValueError(f"{context}: a shared parameter uses a common fixed value or initial value.")
                if name in fixed:
                    raise ValueError(f"{context}: this parameter is already fixed for all series.")
            lo, hi = _intersect_bounds(context, lower[i, j], upper[i, j],
                                       (options.get("lower"), options.get("upper")))
            if lo > hi or (lo == hi and value is None and name not in fixed):
                raise ValueError(f"{context}: the lower bound must be smaller than the upper bound.")
            lower[i, j], upper[i, j] = lo, hi
            if name in fixed or value is not None:
                fixed_values[i, j] = _bounded_value(context, fixed.get(name, value), lo, hi, "fixed")
            if start is not None:
                if value is not None:
                    raise ValueError(f"{context}: a fixed parameter does not need an initial value.")
                starts[i, j] = _bounded_value(context, start, lo, hi, "initial")
    return lower, upper, fixed_values, starts


def _observations(frame, x, y, group, weighting, sigma):
    if group is None:
        raise ValueError("Select a grouping column for global regression.")
    if weighting not in GLOBAL_WEIGHTINGS:
        raise ValueError("Select a supported regression weighting.")
    if weighting != INVERSE_VARIANCE:
        return complete(frame, [x, y], [group])
    if sigma is None or sigma in (x, y, group) or sigma not in frame:
        raise ValueError("Select a separate column of positive standard deviations for weighting.")
    # Align SDs by row position even when labels are duplicated.
    data = complete(frame.reset_index(drop=True), [x, y], [group])
    sd = pd.to_numeric(frame[sigma].iloc[data.index], errors="coerce")
    message = "Weighted regression requires positive, finite standard deviations for every observation."
    if np.iscomplexobj(sd.to_numpy()):
        raise ValueError(message)
    values = sd.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(message)
    data[sigma] = values
    data.index = frame.index.take(data.index)
    return data


def _interior_start(fallback, lo, hi, name):
    if not lo < fallback < hi:
        if np.isfinite(lo) and np.isfinite(hi):
            fallback = .5 * lo + .5 * hi
        elif np.isfinite(lo):
            offset = max(abs(lo), abs(fallback)) or 1.
            fallback = lo + .1 * offset
        else:
            offset = max(abs(hi), abs(fallback)) or 1.
            fallback = hi - .1 * offset
    if not np.isfinite(fallback) or not lo < fallback < hi:
        raise ValueError(f"{name}: the bounds leave no usable interior starting value.")
    return fallback


def _initial_values(problem, overrides):
    spec, xs, ys = problem.spec, problem.xs, problem.ys

    def guess(x, y, fallback):
        if np.ptp(x) == 0 or np.ptp(y) == 0:
            return fallback
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            values = np.asarray(spec.initial(x, y), dtype=float)
        return np.where(np.isfinite(values), values, fallback)

    # A curve can contain too few observations for its own starting heuristic.
    # The pooled heuristic supplies a seed without requiring an individual fit.
    pooled = guess(np.concatenate(xs), np.concatenate(ys), np.ones(len(spec.parameters)))
    natural = np.asarray([guess(x, y, pooled) for x, y in zip(xs, ys, strict=True)])
    starts = np.where(np.isnan(overrides), natural, overrides)
    # Trust-region least squares nudges a seed at a bound by a tiny fixed
    # amount. For a far-away interior solution that can make the first step
    # negligible and trigger ftol before the search reaches the data.
    at_edge = (starts <= problem.lower) | (starts >= problem.upper)
    for i, j in zip(*np.nonzero(at_edge & np.isnan(problem.fixed)), strict=True):
        starts[i, j] = _interior_start(natural[i, j], problem.lower[i, j], problem.upper[i, j], spec.parameters[j])
    return starts


def _diagnostics(y, predicted, sd, df=None):
    residual = y - predicted
    weighted = residual / sd if sd is not None else residual
    ss = float(residual @ residual)
    weighted_ss = float(weighted @ weighted)
    if not np.isfinite([ss, weighted_ss]).all():
        raise ValueError("Global residual sums of squares exceed the numerical range.")
    response_scale = np.max(np.abs(y)) or 1.
    normalized = y / response_scale
    scaled_error = residual / response_scale
    centered = normalized - normalized.mean()
    total = centered @ centered
    result = {"N": len(y), "Residual SS": ss, "Weighted residual SS": weighted_ss,
              "R²": 1 - (scaled_error @ scaled_error) / total if total > 0 else np.nan}
    if df is not None:
        result.update({"df": df, "Residual SD": np.sqrt(ss / df)})
    if sd is not None:
        # R² is a ratio. Normalize before squaring to avoid an overflow
        # when an equivalent, very small common SD unit is supplied.
        relative_precision = sd.min() / sd
        weights = relative_precision**2
        centered = (normalized - np.average(normalized, weights=weights)) * relative_precision
        scaled_error = scaled_error * relative_precision
        total = centered @ centered
        result["Weighted R²"] = 1 - (scaled_error @ scaled_error) / total if total > 0 else np.nan
    return result, residual, weighted


def _band(spec, grid, curve, solution, i, cutoff):
    columns = np.flatnonzero(solution.mapping[i] >= 0)
    if not columns.size:
        return None
    idx = solution.mapping[i, columns]
    estimates = solution.estimates[i]
    derivatives = []
    for j, k in zip(columns, idx, strict=True):
        value = solution.values[k]
        h = np.cbrt(np.finfo(float).eps) * max(abs(value), 1.)
        left = max(value - h, solution.lower[k])
        right = min(value + h, solution.upper[k])
        lo, hi = estimates.copy(), estimates.copy()
        lo[j], hi[j] = left * solution.scale[k], right * solution.scale[k]
        derivatives.append((spec.equation(grid, *hi) - spec.equation(grid, *lo)) / (right - left))
    gradient = np.column_stack(derivatives)
    margin = cutoff * np.linalg.norm(gradient @ solution.factor[idx, :], axis=1)
    band = curve[:, None] + margin[:, None] * np.array([-1., 1.])
    return band if np.isfinite(band).all() else None


def _has_residual_variance(solution, n):
    # The objective has a common response scale. Treat a residual RMS
    # within a small multiple of floating-point precision as roundoff.
    return solution.ss > (64 * np.finfo(float).eps)**2 * n


def _profile_intervals(solution, df, cutoff):
    """Invert the one-parameter extra-SS test, refitting all nuisance parameters."""
    n_free = len(solution.coordinates)
    intervals = np.full((n_free, 2), np.nan)
    target = solution.ss * (1 + cutoff**2 / df)
    indices = np.arange(n_free)
    for k, estimate in enumerate(solution.values):
        nuisance = indices != k
        start = solution.values[nuisance]
        lower, upper = solution.lower[nuisance], solution.upper[nuisance]
        step = max(cutoff * np.linalg.norm(solution.factor[k]) / 2,
                   32 * np.spacing(abs(estimate)))

        def distance(value):
            trial = solution.values.copy()
            trial[k] = value

            def constrained(values):
                trial[nuisance] = values
                return solution.residual(trial)

            errors = (_minimize(constrained, start, lower, upper, max_evaluations=2000).fun
                      if start.size else solution.residual(trial))
            ss = errors @ errors
            if not np.isfinite(ss) or ss < solution.ss * (1 - 1e-8):
                raise ValueError("Could not profile the regression reliably.")
            return ss - target

        for column, (direction, limit) in enumerate(((-1., solution.lower[k]), (1., solution.upper[k]))):
            previous = estimate
            try:
                for power in range(32):
                    proposed = estimate + direction * step * 2**power
                    trial = max(proposed, limit) if direction < 0 else min(proposed, limit)
                    if distance(trial) >= 0:
                        low, high = sorted((previous, trial))
                        endpoint = optimize.brentq(distance, low, high, xtol=step * 1e-9)
                        intervals[k, column] = endpoint * solution.scale[k]
                        break
                    if trial == limit:
                        intervals[k, column] = limit * solution.scale[k]
                        break
                    previous = trial
            except (ValueError, RuntimeError):
                # A failed or unbracketed endpoint is left unavailable.
                continue
    return intervals


def _comparison(reduced, full, n, scale):
    df_full = n - len(full.coordinates)
    df_delta = len(full.coordinates) - len(reduced.coordinates)
    if df_delta <= 0:
        return None, "The two fits have the same number of free parameters."
    if reduced.active.any() or full.active.any():
        return None, "The extra sum-of-squares F test is unavailable at an active parameter bound."
    if not _has_residual_variance(full, n):
        return None, "The fuller model must have positive residual variance for the F test."
    improvement = reduced.ss - full.ss
    if improvement < -1e-8 * max(reduced.ss, full.ss):
        return None, "Could not minimize both nested fits reliably."
    statistic = max(0., improvement) / full.ss * df_full / df_delta
    return {**scale, "df numerator": df_delta, "df denominator": df_full,
            "F": statistic, "p": stats.f.sf(statistic, df_delta, df_full)}, None


def global_nonlinear(frame, x, y, model, group, *, shared=(), fixed=None, bounds=None, initial=None,
                     weighting="Unweighted", sigma=None, compare=False, compare_local=(),
                     intervals="symmetric", series_constraints=None, curve_grid=None):
    """Fit one objective over all complete rows in the selected groups.

    Supply shared parameter names, common fixed values and optional common
    bounds (lower, upper), with None denoting a missing limit. Initial values
    may be supplied by parameter name. The optional series_constraints maps
    group labels to parameter names and then to fixed, lower, upper or initial
    values. Series bounds intersect model and common bounds. Shared coordinates
    must satisfy every series bound. Series fixed values and starts apply to
    local coordinates, and a common start can be replaced if outside their
    bounds. SDs are relative observation scales.
    The covariance, symmetric intervals and pointwise mean bands use the
    linearized model and a common residual variance. Profile intervals instead
    invert the one-parameter extra sum-of-squares test. Bounds that are active
    at the best fit or a zero residual variance suppress inference. The optional
    comparisons relax all sharing or add equality constraints to selected local
    parameters, respectively. The additional sharing test requires the selected
    parameters to be free in every series. An optional drawing grid supplies
    common X coordinates for the curves and bands without affecting the fit.
    """
    if model not in MODELS:
        raise ValueError("Select a supported regression model.")
    if intervals not in ("symmetric", "profile"):
        raise ValueError("Select a supported confidence interval method.")
    spec = MODELS[model]
    shared, fixed, bounds, initial, compare_local = _parameter_options(
        spec, shared, fixed, bounds, initial, compare_local)
    if set(spec.required_shared) - shared - fixed.keys():
        raise ValueError(f"{model} requires shared or common fixed values for {', '.join(spec.required_shared)}.")
    data = _observations(frame, x, y, group, weighting, sigma)
    groups = data.groupby(group, sort=False, observed=True)
    if groups.ngroups > 100:
        raise ValueError("Global regression supports up to 100 series.")
    if groups.ngroups == 0:
        raise ValueError("No complete observations are available for regression.")
    if groups.ngroups < 2 and not spec.required_fixed:
        raise ValueError("Global regression requires at least two groups with complete observations.")
    if len(data) > 500_000:
        raise ValueError("Global regression supports up to 500000 complete observations.")
    parts = dict(iter(groups))
    labels = tuple(parts)
    lower, upper, fixed_values, overrides = _series_options(
        labels, spec.parameters, shared, fixed, bounds, initial, series_constraints)
    if spec.anchor_parameters:
        anchors = [spec.parameters.index(name) for name in spec.anchor_parameters]
        if np.isnan(fixed_values[:, anchors]).all():
            raise ValueError(f"{model} requires a fixed value for {' or '.join(spec.anchor_parameters)}. "
                             "Set it in Parameters or Series constraints.")
    for name in spec.required_fixed:
        missing = np.isnan(fixed_values[:, spec.parameters.index(name)])
        if missing.any():
            groups_missing = ", ".join(repr(label) for label, absent in zip(labels, missing, strict=True) if absent)
            raise ValueError(f"{model} requires a fixed {name} for {groups_missing}. "
                             "Set it in Parameters or Series constraints.")
    if intervals == "profile":
        local = [j for j, name in enumerate(spec.parameters) if name not in shared]
        n_free = len(shared) + np.isnan(fixed_values[:, local]).sum()
        if n_free > 24 or len(data) * n_free > 160_000:
            raise ValueError("Profile intervals exceed the refitting budget. Reduce the design or use symmetric intervals.")
    xs = [part[x].to_numpy() for part in parts.values()]
    ys = [part[y].to_numpy() for part in parts.values()]
    xx, yy = np.concatenate(xs), np.concatenate(ys)
    if spec.domain == "positive" and (xx <= 0).any():
        raise ValueError(f"{model} requires positive concentrations.")
    if spec.domain == "nonnegative" and (xx < 0).any():
        raise ValueError(f"{model} requires nonnegative X values.")

    # Scales of the residual in the original units. Observed-Y scales are taken here; scales from the fitted
    # curve start unweighted and are updated by the IRLS cycle below.
    if weighting == INVERSE_VARIANCE:
        sds = [part[sigma].to_numpy() for part in parts.values()]
    elif uses_observed_y(weighting):
        sds = np.split(observed_scales(yy, weighting), np.cumsum([len(values) for values in ys])[:-1])
    else:
        sds = [None] * len(parts)
    sd = np.concatenate(sds) if sds[0] is not None else None
    # Normalize the whole objective by a common factor, preserving the relative
    # influence of all observations across groups and independent of SD units.
    response_scale = np.max(np.abs(yy)) or 1.

    def fit_scales(original):
        with np.errstate(over="ignore", under="ignore", divide="ignore"):
            if original[0] is None:
                fit_sds = [response_scale] * len(original)
            else:
                flat = np.concatenate(original)
                # Use an order statistic for the median scale without averaging two
                # potentially near-maximum floating point SDs.
                sd_scale = np.partition(flat, len(flat) // 2)[len(flat) // 2]
                fit_sds = [(scales / sd_scale) * response_scale for scales in original]
        if any(not np.isfinite(values).all() or (np.asarray(values) <= 0).any() for values in fit_sds):
            raise ValueError("Regression weights exceed the numerical range.")
        return fit_sds

    problem = _Problem(spec, labels, xs, ys, fit_scales(sds), lower, upper, fixed_values)
    starts = _initial_values(problem, overrides)
    solved = problem.solve(shared, starts)
    refits = None
    if uses_fitted_y(weighting):
        units = solved.scale

        def refit(previous, scales):
            frozen = replace(previous[0], sds=fit_scales(np.split(scales, offsets)))
            return frozen, frozen.solve(shared, previous[1].estimates)

        offsets = np.cumsum([len(values) for values in xs])[:-1]
        (problem, solved), refits, final = iterate_weights(
            weighting, (problem, solved), refit,
            lambda result: np.concatenate([spec.equation(values, *p) for values, p in
                                           zip(xs, result[1].estimates, strict=True)]),
            lambda result: result[1].values * result[1].scale, units)
        sds = np.split(final, offsets)
        sd = final
    df = len(data) - len(solved.coordinates)
    cutoff = stats.t.ppf(.975, df)

    index_names = ("Scope", "Group", "Parameter")
    free_index = pd.MultiIndex.from_tuples(solved.coordinates, names=index_names)
    covariance_root = solved.factor * solved.scale[:, None]
    covariance = covariance_root @ covariance_root.T
    if not np.isfinite(covariance).all():
        raise ValueError("Global regression covariance exceeds the numerical range.")
    has_variance = _has_residual_variance(solved, len(data))
    infer = bool(solved.coordinates) and has_variance and not solved.active.any()
    se = np.sqrt(np.diag(covariance))
    estimates = solved.values * solved.scale
    if not infer:
        covariance[:] = np.nan
        se[:] = np.nan
    cov = pd.DataFrame(covariance, index=free_index, columns=free_index)
    limits = (_profile_intervals(solved, df, cutoff) if intervals == "profile" and infer else
              np.column_stack((estimates - cutoff * se, estimates + cutoff * se)))
    fixed_rows = {("Fixed", None, name): value for name, value in fixed.items()}
    for i, j in zip(*np.nonzero(~np.isnan(fixed_values)), strict=True):
        name = spec.parameters[j]
        if name not in fixed:
            fixed_rows["Fixed", labels[i], name] = fixed_values[i, j]
    parameter_index = pd.MultiIndex.from_tuples([*solved.coordinates, *fixed_rows], names=index_names)
    unavailable = np.full(len(fixed_rows), np.nan)
    table = pd.DataFrame({"Estimate": np.r_[estimates, list(fixed_rows.values())],
                          "SE": np.r_[se, unavailable],
                          "CI 95% low": np.r_[limits[:, 0], unavailable],
                          "CI 95% high": np.r_[limits[:, 1], unavailable]},
                         index=parameter_index)

    group_results = {}
    predictions = []
    for i, (label, part) in enumerate(parts.items()):
        x_values, y_values, scales, parameters = xs[i], ys[i], sds[i], solved.estimates[i]
        predicted = spec.equation(x_values, *parameters)
        predictions.append(predicted)
        if curve_grid is not None:
            grid = curve_grid
        elif spec.log_grid and np.any(x_values > 0):
            smallest_positive = x_values[x_values > 0].min()
            if x_values.min() == 0:
                grid = np.r_[0., np.geomspace(smallest_positive, x_values.max(), 299)]
            else:
                grid = np.geomspace(smallest_positive, x_values.max(), 300)
        else:
            grid = np.linspace(x_values.min(), x_values.max(), 300)
        fitted = spec.equation(grid, *parameters)
        if not np.isfinite(fitted).all():
            raise ValueError(f"{label}: fitted curve exceeds the numerical range.")
        band = _band(spec, grid, fitted, solved, i, cutoff) if infer else None
        summary, residual, scaled = _diagnostics(y_values, predicted, scales)
        summary["Weighting"] = weighting
        residuals = pd.DataFrame({"X": x_values, "Observed": y_values, "Predicted": predicted,
                                  "Residual": residual, "Weighted residual": scaled}, index=part.index)
        keys = [solved.coordinates[k] if k >= 0 else ("Fixed", None if name in fixed else label, name)
                for k, name in zip(solved.mapping[i], spec.parameters, strict=True)]
        group_table = table.loc[keys].set_axis(spec.parameters)
        group_results[label] = GroupFit(group_table, part, np.column_stack((grid, fitted)),
                                        summary["Residual SS"], summary, residuals, band)

    diagnostics, _, _ = _diagnostics(yy, np.concatenate(predictions), sd, df)
    diagnostics.update({"Weighting": weighting, "Free parameters": len(solved.coordinates),
                        "Active bounds": int(solved.active.sum()), "Confidence intervals": intervals,
                        "Positive residual variance": has_variance})
    if refits is not None:
        diagnostics.update({"Weighting iterations": refits, "Weighting converged": True,
                            "Inference weights": INFERENCE_WEIGHTS})
    if intervals == "profile":
        diagnostics["Unavailable profile limits"] = int(np.isnan(limits).sum())

    def weighted_ss(solution):
        predicted = np.concatenate([spec.equation(x, *p) for x, p in zip(xs, solution.estimates, strict=True)])
        summary, _, _ = _diagnostics(yy, predicted, sd)
        return summary["Weighted residual SS"]

    result = GlobalFit(table, group_results, diagnostics, cov)
    if compare:
        if shared.intersection(spec.required_shared):
            result.comparison_note = "Independent fits are unavailable because this model requires shared parameters."
        elif not shared:
            result.comparison_note = "Select at least one free shared parameter to compare with independent fits."
        elif solved.active.any():
            result.comparison_note = "The extra sum-of-squares F test is unavailable at an active parameter bound."
        else:
            try:
                full = problem.solve(set(), solved.estimates)
                sums = {"Shared SS": diagnostics["Weighted residual SS"], "Independent SS": weighted_ss(full)}
                result.comparison, result.comparison_note = _comparison(solved, full, len(data), sums)
            except (ValueError, OverflowError) as error:
                result.comparison_note = f"Independent fit unavailable. {error}"
    if compare_local:
        if solved.active.any():
            result.local_comparison_note = "The extra sum-of-squares F test is unavailable at an active parameter bound."
        else:
            try:
                reduced = problem.solve(shared | compare_local, solved.estimates)
                sums = {"Reduced SS": weighted_ss(reduced), "Full SS": diagnostics["Weighted residual SS"]}
                result.local_comparison, result.local_comparison_note = _comparison(reduced, solved, len(data), sums)
            except (ValueError, OverflowError) as error:
                result.local_comparison_note = f"Additional sharing fit unavailable. {error}"
    return result
