"""Nested comparisons for stacked observations within independent subcolumns."""

import numpy as np
import pandas as pd
from scipy import stats

from .category_graphs import _REPLICATE, _SUMMARY, _title
from .data import _worksheet_roles
from .mixed import _ADJUSTMENTS, _adjust_comparisons, _comparison_rows, _fit_reml, _omnibus
from .processing import FieldError
from .reporting import Result, _plot, _report


NESTED_T = "Nested t test"
NESTED_ANOVA = "Nested one-way ANOVA"
DENOMINATORS = {"Kenward–Roger": "kenward-roger", "Satterthwaite": "satterthwaite", "Legacy": "legacy"}
POSTHOC = {"None": None, **{label: code for code, label in _ADJUSTMENTS.items()}}
SUBCOLUMNS = "Stacked subcolumns"
CONFIRM = "Each subcolumn is an independent unit"
OPTIONS = {SUBCOLUMNS: "Multiple", CONFIRM: False, "Denominator method": tuple(DENOMINATORS),
           "Confidence level (%)": 95.}
METHODS = {NESTED_T: OPTIONS, NESTED_ANOVA: {**OPTIONS, "Post-hoc": tuple(POSTHOC)}}
_MAX_CLUSTERS = 256
_MAX_REPLICATES = 128
_MAX_GROUPS = 24


def is_nested_worksheet(frame):
    return str(frame.attrs.get("table_format", "")).casefold() == "nested"


def nested_defaults(frame):
    roles = _worksheet_roles(frame)
    if roles:
        return [name for group in roles["y"] if len(group) > 1 and not any(_SUMMARY.fullmatch(name) for name in group)
                for name in group]
    return [name for name in frame if _REPLICATE.fullmatch(str(name))]


def preferred_nested_method(frame):
    roles = _worksheet_roles(frame)
    groups = len(roles["y"]) if roles else len({_title(name) for name in nested_defaults(frame)})
    return NESTED_ANOVA if groups > 2 else NESTED_T


def _data(frame, names, method):
    if (not isinstance(names, list) or not 4 <= len(names) <= _MAX_CLUSTERS
            or any(not isinstance(name, str) or name not in frame for name in names)
            or len(set(names)) != len(names) or any(_SUMMARY.fullmatch(name) for name in names)):
        raise FieldError(SUBCOLUMNS, f"Select 4 to {_MAX_CLUSTERS} distinct stacked subcolumns.")
    selected = set(names)
    roles = _worksheet_roles(frame)
    if roles:
        groups = [[name for name in group if name in selected] for group in roles["y"]]
        groups = [group for group in groups if group]
        if {name for group in groups for name in group} != selected:
            raise FieldError(SUBCOLUMNS, "Choose only nested measurement subcolumns.")
    else:
        grouped = {}
        ambiguous = {match[1] for name in frame.columns if (match := _REPLICATE.fullmatch(str(name))) and match[2]}
        for name in frame.columns:
            if name not in selected:
                continue
            replicate = _REPLICATE.fullmatch(name)
            if not replicate:
                raise FieldError(SUBCOLUMNS, "Use stacked subcolumns named like Control [1] and Control [2].")
            if replicate[1] in ambiguous:
                raise FieldError(SUBCOLUMNS, "Subcolumn labels are ambiguous. Reopen the original Nested file or use distinct treatment labels.")
            grouped.setdefault(_title(name), []).append(name)
        groups = list(grouped.values())

    minimum = 2 if method == NESTED_T else 3
    maximum = 2 if method == NESTED_T else _MAX_GROUPS
    if not minimum <= len(groups) <= maximum:
        message = "Choose exactly two treatment groups." if minimum == maximum else f"Choose {minimum} to {maximum} treatment groups."
        raise FieldError(SUBCOLUMNS, message)
    labels, blocks, records = [], [], []
    cell, clusters = [], []
    for treatment, group in enumerate(groups):
        label = _title(group[0])
        while label in labels:
            label += " (group)"
        labels.append(label)
        used = 0
        for name in group:
            raw = frame[name].dropna()
            if any(isinstance(value, (bool, np.bool_, complex)) for value in raw):
                raise FieldError(SUBCOLUMNS, f"Enter numerical measurements in {name}.")
            values = pd.to_numeric(raw, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            if len(values) > _MAX_REPLICATES or not np.isfinite(values).all():
                raise FieldError(SUBCOLUMNS, f"Use at most {_MAX_REPLICATES} finite values in {name}.")
            records.append((label, name, len(values), float(values.mean()) if len(values) else np.nan))
            if len(values):
                cell.extend([treatment] * len(values))
                clusters.extend([len(blocks)] * len(values))
                blocks.append(values)
                used += 1
        if used < 2:
            raise FieldError(SUBCOLUMNS, f"{label} needs at least two nonempty independent subcolumns.")
    if all(len(block) == 1 for block in blocks):
        raise FieldError(SUBCOLUMNS, "Include repeated observations in at least one subcolumn.")
    sizes = pd.DataFrame(records, columns=["Treatment", "Subcolumn", "N", "Mean"]).set_index("Subcolumn")
    return np.concatenate(blocks), np.asarray(cell), np.asarray(clusters), labels, sizes


def _estimates(fit, contrasts, labels, level):
    values, se, df = fit.estimates(contrasts)
    error = stats.t.isf((1 - level) / 2, df) * se
    return pd.DataFrame({"Estimate": values, "SE": se, "df": df,
                         f"CI {level * 100:g}% low": values - error,
                         f"CI {level * 100:g}% high": values + error}, index=labels)


def nested_analysis(method, frame, options):
    if not is_nested_worksheet(frame) and options.get(CONFIRM) is not True:
        raise FieldError(CONFIRM, "Confirm that repeated measurements are stacked within each independent unit.")
    y, cell, cluster, labels, sizes = _data(frame, options.get(SUBCOLUMNS, nested_defaults(frame)), method)
    denominator = options.get("Denominator method", next(iter(DENOMINATORS)))
    if denominator not in DENOMINATORS:
        raise FieldError("Denominator method", "Choose Kenward–Roger, Satterthwaite or Legacy.")
    try:
        level = float(options.get("Confidence level (%)", 95.)) / 100
    except (ValueError, TypeError, OverflowError):
        level = np.nan
    if not 0 < level < 1:
        raise FieldError("Confidence level (%)", "Choose a confidence level strictly between 0 and 100.")
    adjustment = options.get("Post-hoc", "None")
    if adjustment not in POSTHOC:
        raise FieldError("Post-hoc", "Choose a valid adjustment.")
    shape = (len(labels),)
    factor = ["Treatment"]
    fit = _fit_reml(y, cell, cluster, shape, factor, (), inference=DENOMINATORS[denominator], nested=True)
    tests = _omnibus(fit, factor, shape)
    variances = pd.Series({"Nested subcolumn": fit.variances["Subject random intercept"],
                           "Residual": fit.variances["Residual"]}, name="Variance").to_frame()
    variances["SD"] = np.sqrt(variances["Variance"])
    identity = np.eye(len(labels))
    means = _estimates(fit, identity, pd.Index(labels, name="Treatment"), level)
    status = fit.status
    if denominator == "Legacy" and sizes.loc[sizes["N"] > 0, "N"].nunique() > 1:
        status += " Legacy degrees of freedom are approximate with unequal subcolumn sizes."
    summary = _report({"Model": "REML with a random intercept for each independent subcolumn",
                       "Denominator method": denominator, "Status": status, "Observations used": len(y),
                       "Subcolumns used": int(sizes["N"].gt(0).sum()), "Empty subcolumns": int(sizes["N"].eq(0).sum())})
    tables = {"Fixed effect": tests, "Treatment means": means, "Variance components": variances,
              "Subcolumns": sizes, "Model": summary}
    estimates = means
    if method == NESTED_T:
        contrast = identity[1:] - identity[:1]
        estimates = _estimates(fit, contrast, pd.Index([f"{labels[1]} − {labels[0]}"], name="Contrast"), level)
        ratio = estimates["Estimate"] / estimates["SE"]
        tables = {"Difference of means": estimates.assign(t=ratio, p=2 * stats.t.sf(abs(ratio), estimates["df"])),
                  **tables}
    elif POSTHOC[adjustment] is not None:
        comparisons = _comparison_rows(fit, identity, "Treatment", labels, "", "separate")
        _adjust_comparisons(comparisons, POSTHOC[adjustment], level=level)
        tables["Multiple comparisons"] = comparisons

    figure, axes = _plot(method, "", "Mean difference" if method == NESTED_T else "Estimated mean")
    positions = np.arange(len(estimates))
    values = estimates["Estimate"].to_numpy()
    bounds = estimates.iloc[:, 3:5].to_numpy()
    finite = np.isfinite(bounds).all(axis=1)
    axes.plot(positions, values, "o", color="#216a94")
    if finite.any():
        limits = np.abs((bounds[finite] - values[finite, None]).T)
        axes.errorbar(positions[finite], values[finite], yerr=limits, fmt="none", capsize=4, color="#216a94")
    axes.set_xticks(positions, estimates.index.tolist(), rotation=20, ha="right", parse_math=False)
    if method == NESTED_T:
        axes.axhline(0, color="#99a7b6", linewidth=1)
    return Result(tables, figure)
