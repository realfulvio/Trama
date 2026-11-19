"""Statistical analyses with explicit input validation."""
from dataclasses import dataclass, field
from itertools import combinations, product
from numbers import Integral
from math import frexp, ldexp
import warnings

import numpy as np
import pandas as pd
from patsy import build_design_matrices, dmatrix
from scipy import cluster, optimize, stats
from scipy.spatial.distance import cdist, pdist
from statsmodels.duration.survfunc import survdiff
from statsmodels.stats.multitest import multipletests

from .curve_models import MODELS, NESTED_MODELS
from .fit_weights import (INFERENCE_WEIGHTS, INVERSE_VARIANCE, NONLINEAR_WEIGHTINGS, UNWEIGHTED, iterate_weights,
                          observed_scales, uses_fitted_y, uses_observed_y)


def complete(frame, numbers, labels=()):
    """Select numeric and grouping columns, retaining only complete cases."""
    names = [*numbers, *labels]
    if not names or len(names) != len(set(names)):
        raise ValueError("Select distinct columns for the analysis.")
    data = frame.loc[:, names].copy()
    for name in numbers:
        numeric = pd.to_numeric(data[name], errors="coerce")
        if np.iscomplexobj(numeric.to_numpy()):
            raise ValueError(f'Column "{name}" contains complex data.')
        values = numeric.astype(float)
        invalid = data[name].notna() & (~np.isfinite(values))
        if invalid.any():
            raise ValueError(f'Column "{name}" contains non-numeric or infinite data.')
        data[name] = values
    return data.dropna()


def _geometric_summary(values):
    empty = {"Geometric mean": np.nan, "Geometric 95% CI low": np.nan, "Geometric 95% CI high": np.nan}
    if (values <= 0).any():
        if (values == 0).any() and (values < 0).any():
            note = "Geometric mean requires positive values (column contains zero and negative values)."
        elif (values == 0).any():
            note = "Geometric mean requires positive values (column contains zero)."
        else:
            note = "Geometric mean requires positive values (column contains negative values)."
        return {**empty, "Geometric note": note}
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        logs = np.log(values)
        mean_log = float(logs.mean())
        gmean = float(values[0]) if np.ptp(values) == 0 else float(np.exp(mean_log))
    if not (np.isfinite(gmean) and gmean > 0):
        return {**empty, "Geometric note": "Geometric mean cannot be represented as a positive finite number."}
    n = len(values)
    if n < 2:
        return {**empty, "Geometric mean": gmean,
                "Geometric note": "At least two positive observations are required for the 95% confidence interval."}
    if np.ptp(values) == 0:
        return {"Geometric mean": gmean, "Geometric 95% CI low": gmean,
                "Geometric 95% CI high": gmean, "Geometric note": ""}
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        sd_log = float(logs.std(ddof=1))
        margin = float(stats.t.ppf(.975, n - 1)) * sd_log / np.sqrt(n)
        low = float(np.exp(mean_log - margin))
        high = float(np.exp(mean_log + margin))
    if not (np.isfinite(low) and np.isfinite(high) and low > 0 and high > 0):
        return {**empty, "Geometric mean": gmean,
                "Geometric note": "The 95% confidence interval limits cannot be represented as positive finite numbers."}
    return {"Geometric mean": gmean, "Geometric 95% CI low": low,
            "Geometric 95% CI high": high, "Geometric note": ""}


def describe(frame, columns, *, geometric=False):
    rows = []
    for name in columns:
        values = complete(frame, [name])[name]
        if values.empty:
            raise ValueError(f'Column "{name}" has no observations.')
        row = {"Column": name, "N": len(values), "Missing": len(frame) - len(values),
               "Mean": values.mean(), "SD": values.std(), "SEM": values.sem(),
               "Median": values.median(), "Q1": values.quantile(.25),
               "Q3": values.quantile(.75), "Min": values.min(), "Max": values.max()}
        if geometric:
            row.update(_geometric_summary(values.to_numpy(dtype=float)))
        rows.append(row)
    return pd.DataFrame(rows).set_index("Column")


def t_test(frame, response, group=None, mode="welch", subject=None, order=None, null=0.0):
    if mode not in {"paired", "welch", "student", "one-sample"}:
        raise ValueError("Unknown t-test design.")
    if mode != "one-sample" and not group:
        raise ValueError("Select a grouping column.")
    if mode == "paired" and not subject:
        raise ValueError("Select the subject identifier column.")
    labels = [group, subject] if mode == "paired" else [group] if mode != "one-sample" else []
    data = complete(frame, [response], labels)
    if not labels:
        a, b, groups = data[response], None, ("Sample", null)
    else:
        groups = list(order) if order else data[group].drop_duplicates().tolist()
        if len(groups) != 2 or set(groups) != set(data[group].unique()):
            raise ValueError("The grouping column must contain exactly two levels.")
        if mode == "paired":
            if data.duplicated([subject, group]).any():
                raise ValueError("Found duplicate subject/group measurements.")
            wide = data.pivot(index=subject, columns=group, values=response).dropna()
            a, b = wide[groups[0]], wide[groups[1]]
        else:
            a, b = (data.loc[data[group] == label, response] for label in groups)
    return _t_test_samples(a, b, mode, groups, null)


def paired_t_test(frame, first, second):
    pairs = complete(frame, [first, second])
    return _t_test_samples(pairs[first], pairs[second], "paired", (first, second), 0.0)


def _t_test_samples(a, b, mode, groups, null):
    if len(a) < 2 or (b is not None and len(b) < 2):
        raise ValueError("At least two observations in each sample or two matched pairs are required.")
    if mode in {"one-sample", "paired"}:
        differences = a - (b if b is not None else null)
        if differences.std() == 0:
            raise ValueError("The differences have zero variance.")
        result = stats.ttest_1samp(differences, 0)
        effect = differences.mean() / differences.std()
    else:
        if a.var() + b.var() == 0:
            raise ValueError("Both groups have zero variance.")
        result = stats.ttest_ind(a, b, equal_var=mode == "student")
        pooled = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var())
                         / (len(a) + len(b) - 2))
        effect = (a.mean() - b.mean()) / pooled
    interval = result.confidence_interval()
    return {"First": groups[0], "Second / null": groups[1], "N first": len(a),
            "N second": len(b) if b is not None else None, "Mean first": a.mean(),
            "Mean second": b.mean() if b is not None else null,
            "Difference": a.mean() - (b.mean() if b is not None else null),
            "t": result.statistic, "df": result.df, "p": result.pvalue,
            "CI 95% low": interval.low, "CI 95% high": interval.high, "Cohen's d": effect}


def _linear_rescale(value, numerator, denominator=1.):
    """Apply physical units without overflowing an intermediate scale ratio."""
    a, ea = frexp(float(value))
    b, eb = frexp(float(numerator))
    c, ec = frexp(float(denominator))
    try:
        scaled = ldexp(a*b/c, ea+eb-ec)
    except OverflowError:
        raise ValueError("Linear regression exceeds the supported numeric range.") from None
    if not np.isfinite(scaled) or (scaled == 0 and value != 0):
        raise ValueError("Linear regression exceeds the supported numeric range.")
    return scaled


def linear(frame, x, y):
    data = complete(frame, [x, y])
    if len(data) < 3 or data[x].nunique() < 2:
        raise ValueError("Linear regression needs three observations and at least two X values.")
    xs, ys = float(np.max(np.abs(data[x]))), float(np.max(np.abs(data[y])))
    ex, ey = frexp(xs)[1], frexp(ys)[1] if ys else 0
    # Preserve the ordinary path bit for bit. Extreme units can erase or
    # overflow the covariance product inside linregress, falsely giving R²=1.
    scaled = abs(ex) > 450 or abs(ey) > 450 or abs(ex+ey) > 450
    result = stats.linregress(data[x]/xs, data[y]/(ys or 1.)) if scaled else stats.linregress(data[x], data[y])
    slope, intercept, se = result.slope, result.intercept, result.stderr
    if scaled:
        slope = _linear_rescale(slope, ys or 1., xs)
        intercept = _linear_rescale(intercept, ys or 1.)
        se = _linear_rescale(se, ys or 1., xs) if np.isfinite(se) else np.nan
    ci = stats.t.ppf(.975, len(data) - 2) * se
    lower, upper = slope-ci, slope+ci
    if scaled and np.isfinite(se) and not np.isfinite([lower, upper]).all():
        raise ValueError("Linear regression exceeds the supported numeric range.")
    return {"N": len(data), "Slope": slope, "Intercept": intercept,
            "R²": result.rvalue**2, "p": result.pvalue, "Slope SE": se,
            "Slope CI 95% low": lower, "Slope CI 95% high": upper}


def _anova_model(frame, response, factors, order, *, terms=None):
    if terms is not None:
        # Selected terms (0.83): its own sum-coded design, built from internal keys. The Full hierarchy
        # fit below is untouched, so recipes without the new options reproduce the earlier results.
        from .anova_terms import fit_model
        return fit_model(frame, response, factors, terms)
    data = complete(frame, [response], factors)
    if not factors or len(factors) > 8 or not 1 <= order <= min(3, len(factors)):
        raise ValueError("Select up to eight factors and an interaction order from 1 to 3.")
    keys = [f"factor{i}" for i in range(len(factors))]
    data.columns = ["response", *keys]
    for key in keys:
        if not 2 <= data[key].nunique() <= 128:
            raise ValueError("Each factor must contain between 2 and 128 levels.")
        data[key] = data[key].astype(str)
    terms = [f"C({key}, Sum)" for key in keys]
    degrees = [data[key].nunique() - 1 for key in keys]
    coefficient_count = 1 + sum(np.prod(choice, dtype=np.int64)
                                for degree in range(1, order + 1)
                                for choice in combinations(degrees, degree))
    if coefficient_count >= len(data) or coefficient_count * len(data) > 4_000_000:
        raise ValueError("The selected model is too large or has no residual degrees of freedom.")
    design = dmatrix(f"({' + '.join(terms)}) ** {order}", data, return_type="dataframe")
    y = data["response"].to_numpy()
    x = design.to_numpy()
    beta, rss, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        raise ValueError("Model is rank deficient. Check empty cells and redundant factors.")
    df = len(y) - rank
    error = float(rss[0])
    if error <= np.finfo(float).eps * np.sum((y - y.mean())**2):
        raise ValueError("The fitted model has no measurable residual variance.")
    return data, keys, terms, design, beta, error, df


def _anova_type_iii(data, factors, design, error, df, *, term_label=":".join):
    """Type III rows from one full fit. Reduced fits stay; the full model is not fitted again."""
    x, y = design.to_numpy(), data["response"].to_numpy()
    total = np.sum((y - y.mean())**2)
    keys = list(data.columns[1:])
    display = dict(zip((f"C({key}, Sum)" for key in keys), factors))
    rows = []
    for term, bounds in design.design_info.term_name_slices.items():
        if term == "Intercept":
            continue
        reduced = np.delete(x, np.arange(bounds.start, bounds.stop), axis=1)
        residual = y - reduced @ np.linalg.lstsq(reduced, y, rcond=None)[0]
        ss = max(0, float(residual @ residual) - error)
        numerator_df = bounds.stop - bounds.start
        ms = ss / numerator_df
        statistic = ms / (error / df)
        name = term_label(display[part] for part in term.split(":"))
        rows.append({"Term": name, "SS": ss, "df": numerator_df, "MS": ms, "F": statistic,
                     "p": stats.f.sf(statistic, numerator_df, df), "Eta²": ss / total,
                     "Partial eta²": ss / (ss + error)})
    rows.append({"Term": "Residual", "SS": error, "df": df, "MS": error / df})
    table = pd.DataFrame(rows).set_index("Term")
    summary = {"N": len(y), "df": df, "SST": float(total), "SSE": error}
    return table, summary


def factorial_anova(frame, response, factors, order=1, *, terms=None, sums_of_squares=None):
    return factorial_anova_fit(frame, response, factors, order, terms=terms, sums_of_squares=sums_of_squares)[0]


def factorial_anova_fit(frame, response, factors, order=1, *, terms=None, sums_of_squares=None):
    """ANOVA table (Type III unless asked otherwise) and the summary of the same fit: N, residual df, SST, SSE."""
    return _factorial_anova_components(frame, response, factors, order, terms=terms,
                                       sums_of_squares=sums_of_squares)[:2]


def _factorial_anova_components(frame, response, factors, order=1, *, terms=None, sums_of_squares=None):
    """One full fit, its ANOVA table, and the design used for that fit.

    Callers that also need diagnostics reuse ``design``, ``beta``, ``error`` and ``df``.
    The public ``factorial_anova`` and ``factorial_anova_fit`` returns stay the historical pair.
    ``terms`` (Selected terms, 0.83) fits exactly those terms instead of the Full hierarchy of ``order``.
    ``sums_of_squares`` is ``"Type I"`` or ``"Type II"``; ``None`` and ``"Type III"`` keep the historical
    Type III table. The types share the fit, so the residual SS, df and MS never depend on the type.
    """
    data, _, _, design, beta, error, df = _anova_model(frame, response, factors, order, terms=terms)
    options = {"term_label": ":".join}
    if terms is not None:
        from .anova_terms import active_factors, canonical_terms, label
        factors = active_factors(list(factors), canonical_terms(terms, factors))
        options = {"term_label": label}
    if sums_of_squares in (None, "Type III"):
        table, summary = _anova_type_iii(data, factors, design, error, df, **options)
    else:
        from .anova_ss import anova_table
        table, summary = anova_table(sums_of_squares, data, factors, design, error, df, **options)
    return table, summary, data, design, beta, error, df


def anova_effect_sizes(table, fit, alpha=0.05):
    """Effect sizes per term and the model fit, from one ANOVA table and the SST and SSE of its fit.

    The table is the one of the active sums of squares. Type I terms add up to SST − SSE; in an unbalanced
    design the Type II and Type III SS of the terms can overlap, so they need not.
    """
    terms = table.drop(index="Residual")
    error, total, n, df = fit["SSE"], fit["SST"], fit["N"], fit["df"]
    ss = terms["SS"].astype(float)
    effects = pd.DataFrame({
        "% total variation": 100 * ss / total, "Eta squared": ss / total,
        "Partial eta squared": ss / (ss + error), "Cohen f": np.sqrt(ss / error),
        "p": terms["p"].astype(float)}, index=terms.index)
    effects["Significant"] = np.where(effects["p"] < alpha, "Yes", "No")
    model = pd.DataFrame({"Value": pd.Series({
        "N": n, "Residual df": df, "Total SS (centered)": total, "Residual SS": error,
        "R²": 1 - error / total, "Adjusted R²": 1 - (error / df) / (total / (n - 1))}, dtype=object)})
    return effects, model


def _design_grid(design, table):
    """Design rows of a table of internal keys, from the design that was fitted (Patsy or selected terms)."""
    from .anova_terms import TermDesign
    if isinstance(design, TermDesign):
        return design.rows(table)
    return np.asarray(build_design_matrices([design.design_info], table)[0])


def marginal_comparisons(frame, response, factors, order, compare, method="holm", *, terms=None):
    data, keys, _, design, beta, error, df = _anova_model(frame, response, factors, order, terms=terms)
    if terms is not None:
        from .anova_terms import active_factors, canonical_terms
        factors = active_factors(list(factors), canonical_terms(terms, factors))
        if compare not in factors:
            raise ValueError("Select a comparison factor from the model terms.")
    idx = factors.index(compare)
    levels = [sorted(data[key].unique()) for key in keys]
    if np.prod([len(values) for values in levels], dtype=np.int64) > 4096 or len(levels[idx]) > 30:
        raise ValueError("Too many combinations for marginal comparisons.")
    balanced = pd.DataFrame(product(*levels), columns=keys)
    grid = _design_grid(design, balanced)
    covariance = np.linalg.pinv(design.to_numpy().T @ design.to_numpy(), hermitian=True) * error / df
    means = {label: grid[balanced[keys[idx]] == label].mean(axis=0) for label in levels[idx]}
    rows = []
    for a, b in combinations(means, 2):
        diff = means[a] - means[b]
        estimate = float(diff @ beta)
        se = np.sqrt(diff @ covariance @ diff)
        if not np.isfinite(se) or se <= 0:
            raise ValueError("Could not estimate a standard error for the comparison.")
        rows.append({"Comparison": f"{a} − {b}", "Difference": estimate, "SE": se, "df": df,
                     "t": estimate / se, "p": 2 * stats.t.sf(abs(estimate / se), df)})
    results = pd.DataFrame(rows).set_index("Comparison")
    results["Adjusted p"] = multipletests(results["p"], method=method)[1]
    return results


FIT_WEIGHTINGS = ("Unweighted", "Inverse variance (column)")


@dataclass
class Fit:
    parameters: pd.DataFrame
    data: pd.DataFrame
    curve: np.ndarray
    residual_ss: float
    diagnostics: dict
    residuals: pd.DataFrame
    # Parameter covariance in original units: raw curve_fit matrix × residual variance, scaled on both sides.
    # Keyword-only so subclasses (GroupFit) can still add positional fields.
    covariance: np.ndarray | None = field(default=None, kw_only=True)
    # Exact per-observation scales used in the confirmed WLS/last IRLS fit.
    # Retaining them avoids reconstructing weights from rounded or zero residuals.
    residual_scales: np.ndarray | None = field(default=None, kw_only=True)


def _fit_curve(part, x, y, model, label, sigma, initial=None, weighting=None):
    if uses_fitted_y(weighting):
        return _iterated_fit(part, x, y, model, label, initial, weighting)
    return _fit_once(part, x, y, model, label, sigma, initial, weighting)[0]


def _iterated_fit(part, x, y, model, label, initial, weighting):
    """Weights from the fitted curve: an unweighted fit, then WLS refits with the previous fit's scales held fixed."""
    first, units = _fit_once(part, x, y, model, label, None, initial, UNWEIGHTED, precise=True)
    spec = MODELS[model]
    xx = part[x].to_numpy()

    def refit(previous, scales):
        start = previous.parameters["Estimate"].to_numpy()
        return _fit_once(part, x, y, model, label, None, start, weighting, frozen=scales, precise=True)[0]

    fit, refits, _ = iterate_weights(
        weighting, first, refit, lambda fit: spec.equation(xx, *fit.parameters["Estimate"]),
        lambda fit: fit.parameters["Estimate"].to_numpy(), units)
    fit.diagnostics.update({"Weighting iterations": refits, "Weighting converged": True,
                            "Inference weights": INFERENCE_WEIGHTS})
    return fit


def _fit_once(part, x, y, model, label, sigma, initial=None, weighting=None, *, frozen=None, precise=False):
    """One least-squares fit. Returns the fit and the solver's parameter units (for the IRLS criterion).

    ``frozen`` supplies residual scales in the original units. ``precise`` tightens the optimizer so that
    successive IRLS refits are comparable at 1e-8.
    """
    spec = MODELS[model]
    if spec.required_fixed:
        raise ValueError(f"{model} requires fixed values for {', '.join(spec.required_fixed)}. "
                         "Use Global nonlinear regression.")
    if spec.required_shared:
        raise ValueError(f"{model} requires joint estimation. Use Global nonlinear regression.")
    fn, names = spec.equation, spec.parameters
    xx, yy = part[x].to_numpy(), part[y].to_numpy()
    if frozen is not None:
        scales = np.asarray(frozen, dtype=float)
    elif uses_observed_y(weighting):
        scales = observed_scales(yy, weighting)
    else:
        scales = part[sigma].to_numpy() if sigma is not None else None
    # Only relative precision affects the fit. Normalize the supplied SDs so
    # changing their common units does not affect the optimizer's tolerance.
    fit_scales = scales / np.median(scales) if scales is not None else None
    if len(xx) <= len(names) or len(np.unique(xx)) < len(names):
        raise ValueError(f"{label}: not enough distinct X values for the model.")
    if np.ptp(yy) <= 0 and model != "Horizontal line":
        raise ValueError(f"{label}: response values have zero variation.")
    if spec.domain == "positive" and np.any(xx <= 0):
        raise ValueError(f"{model} requires positive concentrations.")
    if spec.domain == "nonnegative" and np.any(xx < 0):
        raise ValueError(f"{model} requires nonnegative X values.")

    if initial is None:
        initial = spec.initial(xx, yy)
    initial = np.asarray(initial, dtype=float)
    # Legacy models retain their original parameterization. New models fit in
    # units of their starting magnitudes so tiny concentrations remain estimable.
    magnitudes = np.where(initial == 0, 1., np.abs(initial)) if spec.scale_parameters else np.ones_like(initial)
    lower, upper = (np.asarray(bound) / magnitudes for bound in spec.bounds)

    def equation(values, *params):
        return fn(values, *(params * magnitudes))

    tolerances = {"method": "trf", "jac": "3-point", "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12} if precise else {}
    with warnings.catch_warnings():
        warnings.simplefilter("error", optimize.OptimizeWarning)
        try:
            params, cov = optimize.curve_fit(equation, xx, yy, p0=initial / magnitudes,
                                             bounds=(lower, upper), sigma=fit_scales,
                                             maxfev=20000, absolute_sigma=True, **tolerances)
        except (RuntimeError, ValueError, FloatingPointError, optimize.OptimizeWarning) as error:
            raise ValueError(f"{label}: could not estimate the regression reliably.") from error
    sd = np.sqrt(np.diag(cov))
    if (not np.isfinite(sd).all() or (sd <= 0).any()
            or np.linalg.matrix_rank(cov / np.outer(sd, sd)) < len(names)):
        raise ValueError(f"{label}: could not estimate the regression reliably.")

    params = params * magnitudes
    predicted = fn(xx, *params)
    residual = yy - predicted
    weighted = residual / scales if scales is not None else residual
    scaled_residual = residual / fit_scales if fit_scales is not None else residual
    df = len(xx) - len(names)
    ss = float(residual @ residual)
    weighted_ss = float(weighted @ weighted)
    if not np.isfinite([ss, weighted_ss]).all():
        raise ValueError(f"{label}: residual sums of squares exceed the numerical range.")
    residual_sd = np.sqrt(ss / df)
    variance = scaled_residual @ scaled_residual / df
    se = sd * (np.sqrt(variance) * magnitudes)
    covariance = variance * cov * np.outer(magnitudes, magnitudes)
    delta = stats.t.ppf(.975, df) * se
    summary = pd.DataFrame({"Estimate": params, "SE": se, "CI 95% low": params - delta,
                            "CI 95% high": params + delta}, index=names)
    if spec.log_grid:
        if xx.min() == 0:
            grid = np.r_[0., np.geomspace(xx[xx > 0].min(), xx.max(), 299)]
        else:
            grid = np.geomspace(xx.min(), xx.max(), 300)
    else:
        grid = np.linspace(xx.min(), xx.max(), 300)
    curve = np.column_stack([grid, fn(grid, *params)])
    centered = yy - yy.mean()
    total_ss = centered @ centered
    weighting = weighting or (FIT_WEIGHTINGS[1] if scales is not None else FIT_WEIGHTINGS[0])
    diagnostics = {"N": len(xx), "df": df, "Weighting": weighting,
                   "Residual SS": ss, "Weighted residual SS": weighted_ss, "Residual SD": residual_sd,
                   "R²": 1 - ss / total_ss if total_ss > 0 else np.nan}
    if scales is not None:
        weights = (scales.min() / scales)**2
        weighted_centered = (yy - np.average(yy, weights=weights)) / scales
        weighted_total_ss = weighted_centered @ weighted_centered
        diagnostics["Weighted R²"] = 1 - weighted_ss / weighted_total_ss if weighted_total_ss > 0 else np.nan
    residuals = pd.DataFrame({"X": xx, "Observed": yy, "Predicted": predicted,
                              "Residual": residual, "Weighted residual": weighted}, index=part.index)
    retained_scales = None
    if scales is not None:
        retained_scales = np.array(scales, dtype=float, copy=True)
        retained_scales.setflags(write=False)
    return Fit(summary, part, curve, ss, diagnostics, residuals, covariance=covariance,
               residual_scales=retained_scales), magnitudes


def nonlinear(frame, x, y, model, group=None, *, weighting="Unweighted", sigma=None):
    """Fit each group with ordinary least squares, supplied relative SDs or weights from the observed Y."""
    if model not in MODELS:
        raise ValueError("Select a supported regression model.")
    if weighting not in NONLINEAR_WEIGHTINGS:
        raise ValueError("Select a supported regression weighting.")
    sigma = sigma if weighting == INVERSE_VARIANCE else None
    labels = [group] if group else []
    if weighting == INVERSE_VARIANCE:
        if sigma is None or sigma in [x, y, *labels] or sigma not in frame:
            raise ValueError("Select a separate column of positive standard deviations for weighting.")
        # Select scales by row position so duplicate index labels are preserved.
        data = complete(frame.reset_index(drop=True), [x, y], labels)
        scales = pd.to_numeric(frame[sigma].iloc[data.index], errors="coerce")
        if np.iscomplexobj(scales.to_numpy()):
            raise ValueError("Weighted regression requires positive, finite standard deviations for every observation.")
        values = scales.to_numpy(dtype=float, na_value=np.nan)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Weighted regression requires positive, finite standard deviations for every observation.")
        data[sigma] = values
        data.index = frame.index.take(data.index)
    else:
        data = complete(frame, [x, y], labels)
    if data.empty:
        raise ValueError("No complete observations.")
    if uses_observed_y(weighting):
        # Check every complete observation before fitting any group, so a zero Y is reported first.
        observed_scales(data[y].to_numpy(), weighting)
    groups = data.groupby(group, sort=False, observed=True) if group else [("All", data)]
    return {label: _fit_curve(part, x, y, model, label, sigma, weighting=weighting) for label, part in groups}


def compare_nonlinear(frame, x, y, simple, complex, group=None, *, weighting="Unweighted", sigma=None):
    """Compare supported nested fits by the approximate extra sum-of-squares F test."""
    null_values = NESTED_MODELS.get((simple, complex))
    if null_values is None:
        raise ValueError("Select a supported nested pair with the simpler model first.")
    if weighting not in FIT_WEIGHTINGS:
        raise ValueError("Select a supported regression weighting.")
    fits = nonlinear(frame, x, y, simple, group, weighting=weighting, sigma=sigma)
    sigma = sigma if weighting == FIT_WEIGHTINGS[1] else None
    rows = []
    for label, reduced in fits.items():
        initial = (*reduced.parameters["Estimate"], *null_values)
        full = _fit_curve(reduced.data, x, y, complex, label, sigma, initial, weighting)
        simple_ss = reduced.diagnostics["Weighted residual SS"]
        complex_ss = full.diagnostics["Weighted residual SS"]
        df_full = full.diagnostics["df"]
        df_delta = reduced.diagnostics["df"] - df_full
        improvement = simple_ss - complex_ss
        if improvement < -1e-8 * max(simple_ss, complex_ss):
            raise ValueError(f"{label}: could not minimize both nested models reliably.")
        if complex_ss <= 0:
            raise ValueError(f"{label}: the full model must have positive residual variance for the F test.")
        f = (max(0., improvement) / df_delta) / (complex_ss / df_full)
        rows.append({"Group": label, "Simple model": simple, "Complex model": complex,
                     "Simple SS": simple_ss, "Complex SS": complex_ss, "df numerator": df_delta,
                     "df denominator": df_full, "F": f, "p": stats.f.sf(f, df_delta, df_full)})
    return pd.DataFrame(rows).set_index("Group")


def _critical_value(level):
    if not np.isfinite(level) or not 0 < level < 100:
        raise ValueError("The confidence level must be between 0 and 100.")
    return stats.norm.isf((100 - level) / 200)


def ci_columns(level=95.0):
    """Names of the complementary log-log band columns for a confidence level."""
    label = repr(float(level)).removesuffix(".0")
    return f"CI {label}% low", f"CI {label}% high"


def survival(frame, time, event, group=None, level=95.0, strict=True, *, standard_error=False):
    data = complete(frame, [time, event], [group] if group else [])
    if data.empty or (data[time] < 0).any() or not data[event].isin([0, 1]).all():
        raise ValueError("Survival requires nonnegative time and event values 0 (censored) or 1.")
    critical = _critical_value(level)
    low_name, high_name = ci_columns(level)
    curves = {}
    for label, part in data.groupby(group, sort=False) if group else [("All", data)]:
        counts = part.groupby(time, sort=True)[event].agg(["size", "sum"])
        risk = len(part) - counts["size"].cumsum() + counts["size"]
        events = counts["sum"].astype(int)
        probabilities = (1 - events / risk).cumprod()
        intervals, errors = [], []
        greenwood = 0.
        for n, d, p in zip(risk, events, probabilities):
            if p in (0, 1):
                intervals.append((p, p))
                if standard_error:
                    errors.append(0.)
            else:
                greenwood += d / (n * (n - d))
                sigma = np.sqrt(greenwood)
                transform = np.log(-np.log(p))
                margin = critical * sigma / abs(np.log(p))
                intervals.append((np.exp(-np.exp(transform + margin)), np.exp(-np.exp(transform - margin))))
                if standard_error:
                    errors.append(p * sigma)
        curves[label] = pd.DataFrame({"Time": counts.index.to_numpy(), "At risk": risk.to_numpy(),
                                     "Events": events.to_numpy(), "Censored": (counts["size"] - events).to_numpy(),
                                     "Survival": probabilities.to_numpy(),
                                     low_name: [pair[0] for pair in intervals],
                                     high_name: [pair[1] for pair in intervals]})
        if standard_error:
            curves[label]["Standard error"] = errors
    comparison = None
    if len(curves) > 1 and data[event].sum():
        try:
            statistic, _ = survdiff(data[time], data[event], data[group])
        except np.linalg.LinAlgError as error:
            if strict:
                raise ValueError("The log-rank test is singular for these groups.") from error
        else:
            df = len(curves) - 1
            comparison = {"Log-rank χ²": statistic, "df": df, "p": stats.chi2.sf(statistic, df)}
    return curves, comparison


def survival_median(curve, level=95.0, plateau=False):
    """Median survival and its complementary log-log interval limits (NaN when not reached).

    The default estimate is the first time with S <= 0.5. With ``plateau`` the
    median is the midpoint of the first and last recorded times at which S is
    0.5 to floating-point precision, falling back to the default without one.
    """
    low_name, high_name = ci_columns(level)
    times = curve["Time"].to_numpy(dtype=float)

    def first(values):
        reached = np.flatnonzero(np.asarray(values, dtype=float) <= .5)
        return times[reached[0]] if len(reached) else np.nan

    survival_values = curve["Survival"].to_numpy(dtype=float)
    median = first(survival_values)
    if plateau:
        flat = np.flatnonzero(np.isclose(survival_values, .5, rtol=0, atol=1e-12))
        if len(flat):
            median = (times[flat[0]] + times[flat[-1]]) / 2
    return median, first(curve[low_name]), first(curve[high_name])


def _risk_sets(time, event, codes, k):
    """Subjects at risk and events per group at every distinct event time."""
    time, event, codes = np.asarray(time, float), np.asarray(event) == 1, np.asarray(codes)
    times = np.unique(time[event])
    at_risk = np.zeros((len(times), k))
    events = np.zeros_like(at_risk)
    for g in range(k):
        everyone = np.sort(time[codes == g])
        at_risk[:, g] = len(everyone) - np.searchsorted(everyone, times, side="left")
        failed = np.sort(time[(codes == g) & event])
        events[:, g] = np.searchsorted(failed, times, side="right") - np.searchsorted(failed, times, side="left")
    return times, at_risk, events


def _score_moments(at_risk, events, weighted):
    """Weighted observed-minus-expected score and its hypergeometric covariance."""
    total, failed = at_risk.sum(axis=1), events.sum(axis=1)
    share = at_risk / total[:, None]
    weights = total if weighted else np.ones_like(total)
    score = (weights[:, None] * (events - failed[:, None] * share)).sum(axis=0)
    factor = np.divide(failed * (total - failed), total - 1, out=np.zeros_like(total), where=total > 1)
    coefficient = weights**2 * factor
    covariance = np.diag((coefficient[:, None] * share).sum(axis=0)) - (coefficient[:, None] * share).T @ share
    return score, covariance


def _global_statistic(score, covariance):
    """Chi-square on k-1 contrasts, or None when the covariance lacks full rank."""
    k = len(score)
    if k < 2 or np.linalg.matrix_rank(covariance) < k - 1:
        return None
    reduced = covariance[:-1, :-1]
    if np.linalg.matrix_rank(reduced) < k - 1:
        return None
    return float(score[:-1] @ np.linalg.solve(reduced, score[:-1]))


def _unavailable(reason):
    return {"available": False, "note": reason}


def survival_comparisons(frame, time, event, group, *, gbw=False, trend_order=None,
                         hazard_numerator=None, hazard=False, level=95.0):
    """Additional two-sided comparisons that share one set of risk sets.

    Every requested comparison is a dictionary with ``available`` and either its
    values or a ``note`` giving the reason. ``trend_order`` lists the group names
    (as text) from the lowest to the highest score; ``hazard_numerator`` names
    the numerator group of the hazard ratios for exactly two groups.
    """
    data = complete(frame, [time, event], [group])
    if data.empty or (data[time] < 0).any() or not data[event].isin([0, 1]).all():
        raise ValueError("Survival requires nonnegative time and event values 0 (censored) or 1.")
    critical = _critical_value(level)
    labels = list(pd.unique(data[group]))
    names = [str(label) for label in labels]
    k = len(labels)
    results = {}
    if k < 2 or not data[event].sum():
        reason = "A comparison needs at least two groups." if k < 2 else "There are no events to compare."
        for key, wanted in (("gbw", gbw), ("trend", trend_order is not None), ("hazard", hazard)):
            if wanted:
                results[key] = _unavailable(reason)
        return results
    codes = pd.Categorical(data[group], categories=labels).codes
    times, at_risk, events = _risk_sets(data[time], data[event], codes, k)
    reason = ("The groups do not share enough risk sets with events for this comparison."
              if k > 1 else "")
    unweighted = _score_moments(at_risk, events, False)

    if gbw:
        score, covariance = _score_moments(at_risk, events, True)
        statistic = _global_statistic(score, covariance)
        if statistic is None:
            results["gbw"] = _unavailable(reason)
        else:
            results["gbw"] = {"available": True, "χ²": statistic, "df": k - 1,
                              "p": stats.chi2.sf(statistic, k - 1), "score": score}

    if trend_order is not None:
        order = [str(name) for name in trend_order]
        missing = [name for name in order if name not in names]
        extra = [name for name in names if name not in order]
        if len(set(order)) != len(order):
            results["trend"] = _unavailable("The trend order repeats a group.")
        elif len(names) != len(set(names)):
            results["trend"] = _unavailable("Group names are not unique as text.")
        elif extra or missing:
            parts = []
            if extra:
                parts.append("groups not in the trend order: " + ", ".join(extra))
            if missing:
                parts.append("groups missing from this analysis: " + ", ".join(missing))
            text = "; ".join(parts)
            results["trend"] = _unavailable(text[0].upper() + text[1:] + ".")
        elif k < 3:
            results["trend"] = _unavailable("The trend test needs at least three groups in this analysis.")
        else:
            score, covariance = unweighted
            scores = np.array([order.index(name) for name in names], dtype=float)
            variance = float(scores @ covariance @ scores)
            if np.linalg.matrix_rank(covariance) < k - 1 or not variance > 0:
                results["trend"] = _unavailable(reason)
            else:
                z = float(scores @ score / np.sqrt(variance))
                results["trend"] = {"available": True, "order": order, "z": z, "χ²": z * z, "df": 1,
                                    "p": stats.chi2.sf(z * z, 1)}

    if hazard:
        results["hazard"] = _hazard_ratios(names, hazard_numerator, at_risk, events, unweighted, critical, level)
    return results


def _hazard_ratios(names, numerator, at_risk, events, moments, critical, level):
    if len(names) != 2:
        return _unavailable("Hazard ratios need exactly two groups in this analysis.")
    if numerator is None or str(numerator) not in names:
        if numerator is not None:
            return _unavailable(f"The numerator group {numerator} is not among the groups of this analysis.")
        numerator = names[0]
    a = names.index(str(numerator))
    b = 1 - a
    total, failed = at_risk.sum(axis=1), events.sum(axis=1)
    expected = (failed[:, None] * at_risk / total[:, None]).sum(axis=0)
    observed = events.sum(axis=0)
    variance = float(moments[1][a, a])
    rows = {}

    def finish(method, log_ratio, error, note=""):
        with np.errstate(over="ignore", invalid="ignore"):
            estimates = np.array([log_ratio, log_ratio - critical * error, log_ratio + critical * error])
            ratio, lower, upper, inverse, inverse_upper, inverse_lower = np.exp(np.r_[estimates, -estimates])
        if not np.isfinite([ratio, lower, upper, inverse, inverse_lower, inverse_upper]).all():
            return unavailable(method, "The estimate or its limits cannot be represented.")
        return {"Method": method, "Status": "Estimated", "HR": ratio, "Lower": lower, "Upper": upper,
                "Inverse HR": inverse, "Inverse lower": inverse_lower, "Inverse upper": inverse_upper, "Note": note}

    def unavailable(method, note):
        return {"Method": method, "Status": "Not available", "Note": note}

    if not variance > 0:
        rows["mh"] = unavailable("Mantel–Haenszel", "There is no informative risk set for the variance estimate.")
    else:
        rows["mh"] = finish("Mantel–Haenszel", (observed[a] - expected[a]) / variance, np.sqrt(1 / variance))
    if min(observed) == 0 or min(expected) <= 0:
        rows["oe"] = unavailable("Log-rank O/E", "A group has no observed or expected events.")
    else:
        rows["oe"] = finish("Log-rank O/E", np.log((observed[a] / expected[a]) / (observed[b] / expected[b])),
                            np.sqrt(1 / expected[a] + 1 / expected[b]))
    common = {"Numerator": names[a], "Denominator": names[b], "Observed numerator": observed[a],
              "Expected numerator": expected[a], "Observed denominator": observed[b],
              "Expected denominator": expected[b], "CI level (%)": level}
    return {"available": True, "rows": [{**row, **common} for row in rows.values()]}


@dataclass
class Clusters:
    data: pd.DataFrame
    labels: pd.Series | None
    centers: pd.DataFrame | None = None
    inertia: float | None = None
    tree: np.ndarray | None = None
    scaled: pd.DataFrame | None = None
    distances: np.ndarray | None = None
    initial_centers: pd.DataFrame | None = None


def _cluster_data(frame, columns, count, standardize):
    data = complete(frame, columns)
    if len(columns) < 1 or len(data) < 2 or not 1 <= count <= len(data):
        raise ValueError("Number of clusters must be between 1 and the number of complete rows.")
    values = data.to_numpy(dtype=float)
    if standardize:
        sd = values.std(axis=0, ddof=1)
        if np.any(sd == 0):
            raise ValueError("Cannot standardize a constant variable.")
        values = (values - values.mean(axis=0)) / sd
    return data, values


def _kmeans_plus_plus_rows(values, count, rng):
    """Sample by distance to the nearest selected center, as in the Lloyd fitter."""
    positions = [rng.integers(len(values))]
    nearest = np.full(len(values), np.inf)
    while len(positions) < count:
        distance = cdist(values[positions[-1:]], values, metric="sqeuclidean")[0]
        nearest = np.minimum(nearest, distance)
        weights = (nearest / nearest.sum()).cumsum()
        positions.append(int(np.searchsorted(weights, rng.uniform())))
    return positions


def kmeans(frame, columns, count, standardize=False, seed=42, *, algorithm="lloyd",
           max_iterations=10, initial_rows=None, retain_initial=False):
    if algorithm == "hartigan-wong":
        return _hartigan_kmeans(frame, columns, count, standardize, seed, max_iterations, initial_rows, retain_initial)
    if algorithm == "macqueen":
        return _macqueen_kmeans(frame, columns, count, standardize, seed, max_iterations, initial_rows, retain_initial)
    if algorithm != "lloyd":
        raise ValueError("Choose a K-means algorithm.")
    if initial_rows is not None:
        raise ValueError("Initial rows are supported with Hartigan-Wong.")
    data, values = _cluster_data(frame, columns, count, standardize)
    if count > len(np.unique(values, axis=0)) or len(values) * count > 2_000_000:
        raise ValueError("Too many clusters for the number of distinct observations.")
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(10):
        try:
            initial = values[_kmeans_plus_plus_rows(values, count, rng)] if retain_initial else None
            centers, labels = cluster.vq.kmeans2(values, initial.copy() if initial is not None else count,
                                                iter=100, minit="matrix" if retain_initial else "++",
                                                missing="raise", rng=rng)
        except cluster.vq.ClusterError:
            continue
        inertia = float(np.sum((values - centers[labels])**2))
        if best is None or inertia < best.inertia:
            best = Clusters(data, pd.Series(labels + 1, index=data.index, name="Cluster"),
                            pd.DataFrame(centers, columns=columns), inertia,
                            initial_centers=None if initial is None else pd.DataFrame(initial, columns=columns))
    if best is None:
        raise ValueError("K-means did not converge to non-empty clusters.")
    return best


def _hartigan_kmeans(frame, columns, count, standardize, seed, max_iterations, initial_rows, retain_initial):
    from .hartigan_wong import IterationLimitError, fit_hartigan_wong

    data, values = _cluster_data(frame, columns, count, standardize)
    distinct = np.sort(np.unique(values, axis=0, return_index=True)[1])
    if count > len(distinct) or len(values) * count > 2_000_000:
        raise ValueError("Too many clusters for the number of distinct observations.")
    if initial_rows is not None:
        supplied = np.asarray(initial_rows)
        if supplied.shape != (count,):
            raise ValueError("Choose one initial row per cluster.")
        fit = fit_hartigan_wong(values, supplied, max_iterations)
        chosen = supplied
        if not fit.converged:
            raise IterationLimitError("Hartigan–Wong reached the maximum number of iterations.")
    else:
        rng = np.random.default_rng(seed)
        fit = None
        for _ in range(10):
            positions = rng.choice(distinct, count, replace=False)
            candidate = fit_hartigan_wong(values, positions, max_iterations)
            if candidate.converged and (fit is None or candidate.within.sum() < fit.within.sum()):
                fit = candidate
                chosen = positions
            if count == 1 or count == len(values):
                break
        if fit is None:
            raise IterationLimitError("Hartigan–Wong reached the maximum number of iterations.")
    return Clusters(data, pd.Series(fit.labels + 1, index=data.index, name="Cluster"),
                    pd.DataFrame(fit.centers, columns=columns), float(fit.within.sum()),
                    initial_centers=pd.DataFrame(values[chosen], columns=columns) if retain_initial else None)


def _macqueen_kmeans(frame, columns, count, standardize, seed, max_iterations, initial_rows, retain_initial):
    from .hartigan_wong import IterationLimitError

    if isinstance(max_iterations, bool) or not isinstance(max_iterations, Integral) or not 1 <= max_iterations <= 1000:
        raise ValueError("Maximum iterations must be an integer from 1 to 1000.")
    data, values = _cluster_data(frame, columns, count, standardize)
    n, width = values.shape
    if count > len(np.unique(values, axis=0)) or n * count > 2_000_000:
        raise ValueError("Too many clusters for the number of distinct observations.")
    origin = values[0]
    with np.errstate(over="ignore", invalid="ignore"):
        shifted = values - origin
    limit = np.sqrt(np.finfo(float).max / (4 * n * width))
    if not np.isfinite(shifted).all() or np.abs(shifted).max() > limit:
        raise ValueError("Variable magnitudes are too large to compute squared distances.")
    if initial_rows is None:
        positions = _kmeans_plus_plus_rows(shifted, count, np.random.default_rng(seed))
    else:
        positions = np.asarray(initial_rows)
        if positions.shape != (count,) or positions.dtype.kind not in "iu":
            raise ValueError("Choose one initial row per cluster.")
        if (positions < 0).any() or (positions >= n).any():
            raise ValueError("Initial row positions are outside the complete data.")
    initial = shifted[positions]
    if len(np.unique(initial, axis=0)) != count:
        raise ValueError("Initial observations must specify distinct centers.")

    labels = cdist(shifted, initial, "sqeuclidean").argmin(axis=1)
    counts = np.bincount(labels, minlength=count)
    if (counts == 0).any():
        raise ValueError("An initial cluster has no observations.")
    sums = np.zeros_like(initial)
    np.add.at(sums, labels, shifted)
    centers = sums / counts[:, None]
    for _ in range(max_iterations):
        moved = False
        for row, point in enumerate(shifted):
            old = labels[row]
            if counts[old] == 1:
                continue
            delta = centers - point
            distances = np.einsum("ij,ij->i", delta, delta)
            new = distances.argmin()
            if distances[new] < distances[old]:
                counts[old] -= 1
                counts[new] += 1
                sums[old] -= point
                sums[new] += point
                centers[old] = sums[old] / counts[old]
                centers[new] = sums[new] / counts[new]
                labels[row] = new
                moved = True
        if not moved:
            break
    else:
        raise IterationLimitError("MacQueen reached the maximum number of iterations.")

    # Compute the outputs from the final assignments without carrying forward transfer rounding.
    sums.fill(0)
    np.add.at(sums, labels, shifted)
    centers = sums / counts[:, None]
    inertia = float(np.sum((shifted - centers[labels]) ** 2))
    return Clusters(data, pd.Series(labels + 1, index=data.index, name="Cluster"),
                    pd.DataFrame(centers + origin, columns=columns), inertia,
                    initial_centers=pd.DataFrame(values[positions], columns=columns) if retain_initial else None)


def _scale_cluster_axis(values, mode, axis):
    if mode == "none":
        return values
    if mode not in {"center", "standardize"}:
        raise ValueError("Select none, center, or standardize for clustering scales.")
    dimension = "column" if axis == 0 else "row"
    first = values.take([0], axis=axis)
    constant = np.all(values == first, axis=axis, keepdims=True)
    if mode == "standardize" and constant.any():
        raise ValueError(f"Cannot standardize a constant {dimension}.")
    with np.errstate(over="ignore", invalid="ignore"):
        # Subtract the original value on constant slices to center them exactly.
        mean = np.where(constant, first, values.mean(axis=axis, keepdims=True))
        centered = values - mean
        if mode == "standardize":
            sd = values.std(axis=axis, ddof=1, keepdims=True)
            if not np.isfinite(sd).all() or np.any(sd == 0):
                raise ValueError(f"Cannot calculate a finite, positive {dimension} standard deviation.")
            centered = centered / sd
    if not np.isfinite(centered).all():
        raise ValueError(f"{dimension.capitalize()} scaling produced non-finite values.")
    return centered


def hierarchical(frame, columns, count, standardize=False, linkage="average", metric="euclidean",
                 *, column_scale=None, row_scale="none", axis="rows", cut_height=None):
    """Cluster a complete numeric block after scaling columns, then rows.

    Scaled data retain the original orientation. Raw data and distances use
    the clustering axis as observations. A height cut excludes equal merges.
    """
    if axis not in {"rows", "columns"}:
        raise ValueError("Select rows or columns for hierarchical clustering.")
    if linkage in {"ward", "centroid", "median"} and metric != "euclidean":
        raise ValueError(f"{linkage.capitalize()} linkage requires Euclidean distance.")
    if cut_height is not None:
        if count is not None:
            raise ValueError("Specify either a cluster count or a cut height.")
        try:
            cut_height = float(cut_height)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Cut height must be finite and non-negative.") from error
        if not np.isfinite(cut_height) or cut_height < 0:
            raise ValueError("Cut height must be finite and non-negative.")

    data = complete(frame, columns)
    observations = data if axis == "rows" else data.T
    size = len(observations)
    if data.empty or size < 2:
        raise ValueError("Hierarchical clustering requires at least two observations with complete data.")
    if size > 3000:
        raise ValueError("Hierarchical clustering is limited to 3000 observations.")
    if count is not None and (not isinstance(count, Integral) or isinstance(count, bool)
                              or not 1 <= count <= size):
        raise ValueError("Number of clusters must be an integer between 1 and the number of observations.")

    if column_scale is None:
        column_scale = "standardize" if standardize else "none"
    values = _scale_cluster_axis(data.to_numpy(dtype=float), column_scale, axis=0)
    values = _scale_cluster_axis(values, row_scale, axis=1)
    scaled = pd.DataFrame(values, index=data.index, columns=data.columns)
    vectors = values if axis == "rows" else values.T
    if metric == "correlation" and np.any(np.all(vectors == vectors[:, :1], axis=1)):
        raise ValueError("Pearson correlation distance is undefined for a constant observation.")
    if metric == "cosine" and np.any(np.all(vectors == 0, axis=1)):
        raise ValueError("Cosine distance is undefined for a zero observation vector.")
    distances = pdist(vectors, metric=metric)
    if not np.isfinite(distances).all() or np.any(distances < 0):
        raise ValueError("The distance method must yield finite, non-negative pairwise distances.")
    tree = cluster.hierarchy.linkage(distances, method=linkage)
    if not np.isfinite(tree).all():
        raise ValueError("The linkage method produced non-finite merge distances.")

    labels = None
    if cut_height is not None:
        # fcluster includes equality, so pass the preceding representable float.
        boundary = np.nextafter(cut_height, -np.inf)
        groups = cluster.hierarchy.fcluster(tree, boundary, criterion="distance")
        groups = pd.factorize(groups)[0] + 1
        labels = pd.Series(groups, index=observations.index, name="Cluster")
    elif count is not None:
        count_tree = tree
        if np.any(np.diff(tree[:, 2]) < 0):
            # Inverted heights cannot order a count cut. Use merge order here.
            count_tree = tree.copy()
            count_tree[:, 2] = np.arange(len(tree))
        groups = cluster.hierarchy.cut_tree(count_tree, n_clusters=[count]).ravel() + 1
        labels = pd.Series(groups, index=observations.index, name="Cluster")
    return Clusters(observations, labels, tree=tree, scaled=scaled, distances=distances)


def ellipse(points, level=.95, kind="mean"):
    data = np.asarray(points, dtype=float)
    if data.ndim != 2 or data.shape[1] != 2 or len(data) < 3 or not np.isfinite(data).all() or not 0 < level < 1:
        raise ValueError("An ellipse needs at least three finite XY pairs and a level between 0 and 1.")
    n = len(data)
    if kind == "mean":
        scale = 2 * (n - 1) / (n * (n - 2)) * stats.f.ppf(level, 2, n - 2)
    elif kind == "data":
        scale = stats.chi2.ppf(level, 2)
    else:
        raise ValueError("Unknown ellipse type.")
    theta = np.linspace(0, 2 * np.pi, 181)
    circle = np.column_stack([np.cos(theta), np.sin(theta)])
    epsilon = np.finfo(float).eps
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        # Keep the original sampling orientation for well-conditioned data.
        covariance = np.cov(data, rowvar=False)
        if np.isfinite(covariance).all():
            values, vectors = np.linalg.eigh(covariance)
            squared_radii = values * scale
            if values[0] > epsilon * values[1] and 0 < squared_radii[0] <= squared_radii[1] < np.inf:
                contour = data.mean(axis=0) + circle @ np.diag(np.sqrt(squared_radii)) @ vectors.T
                if np.isfinite(contour).all():
                    return contour

        # Scale each coordinate before centering or squaring it. The spreads
        # remove differences in units from the degeneracy check.
        _, exponent = np.frexp(np.max(np.abs(data), axis=0))
        scaled = np.ldexp(data, -exponent)
        center = scaled.mean(axis=0)
        centered = scaled - center
        spread = np.max(np.abs(centered), axis=0)
        if np.any(spread == 0):
            raise ValueError("The selected XY data are collinear.")
        normalized = centered / spread
        values, vectors = np.linalg.eigh(normalized.T @ normalized / (n - 1))
        if values[0] <= epsilon * values[1]:
            raise ValueError("The selected XY data are collinear.")
        offsets = circle @ np.diag(np.sqrt(values) * np.sqrt(scale)) @ vectors.T
        contour = np.ldexp(center + offsets * spread, exponent)
    if not np.isfinite(contour).all():
        raise ValueError("The selected XY data exceed the numeric range for an ellipse.")
    return contour
