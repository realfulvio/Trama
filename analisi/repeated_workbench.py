"""Workbench views for partial repeated measures and joint curve fits."""
import numpy as np
import pandas as pd

from .axis_breaks import mark_supported
from matplotlib.colors import is_color_like

from .curve_models import MODELS
from .fit_weights import GLOBAL_WEIGHTINGS, observed_scales, uses_observed_y
from .repeated_input import SAVED_REPLICATE_DISPLAY, _series_name, curve_input, decode_series_constraints, mixed_input
from .reporting import Result, _plot, _report
from .stats import complete

METHODS = {
    "Mixed-effects model (REML)": {
        "Input format": ("Long table", "Wide repeated measures", "Grouped replicate table"),
        "Y": "Optional", "Subject": "Optional",
        "Within factors": "Multiple (optional)", "Between factors": "Multiple (optional)",
        "Measurement columns": "Multiple (optional)", "Row labels": "Optional",
        "Repeat across": ("Columns only", "Rows only", "Rows and columns"),
        "Subject IDs": ("Unique across groups", "Restart within between groups"),
        "Denominator method": ("Satterthwaite", "Kenward–Roger"),
        "Post-hoc": ("None", "Holm", "Šídák", "Bonferroni", "Unadjusted"),
        "Comparison factor": "Optional", "Condition on factors": "Multiple (optional)",
        "Comparison families": ("Separate", "Pooled"),
    },
    "Global nonlinear regression": {
        "Input format": ("Long table", "Wide XY"), "X": None, "Y": "Optional", "Series": "Optional",
        "Y columns": "Multiple (optional)", "SD column": "Optional",
        "Model": tuple(MODELS), "X values": ("As entered", "Log10 concentrations"),
        "Replicates": ("Individual observations", "Means at each X"), "Merge numbered replicates": True,
        "Weighting": GLOBAL_WEIGHTINGS, "Parameter intervals": ("Symmetric t", "Profile likelihood"),
        "Compare with independent fits": False, "Show confidence bands": False,
    },
}


INPUT_FIELDS = {
    "Mixed-effects model (REML)": {
        "Long table": {"Y", "Subject", "Within factors", "Between factors", "Subject IDs"},
        "Wide repeated measures": {"Subject", "Between factors", "Measurement columns", "Subject IDs"},
        "Grouped replicate table": {"Measurement columns", "Row labels", "Repeat across"},
    },
    "Global nonlinear regression": {
        "Long table": {"Y", "Series"},
        "Wide XY": {"Y columns", "Merge numbered replicates"},
    },
}


def check_global_weighting(frame, options):
    """Name the Weighting field when an observed-Y weighting meets a zero response.

    The check needs no fitting, so the dialog can keep the error on its field and leave the
    calculation to the worker. Fitted-curve weightings accept a zero response.
    """
    weighting = options.get("Weighting")
    if not uses_observed_y(weighting):
        return
    data, *_ = curve_input(frame, options)
    clean = complete(data.reset_index(drop=True), ["X", "Response"], ["Series"])
    observed_scales(clean["Response"].to_numpy(), weighting)


def mixed_analysis(frame, options):
    from .mixed import mixed_effects_anova

    data, response, within, between, subject = mixed_input(frame, options)
    posthoc = {"None": None, "Holm": "holm", "Šídák": "sidak", "Bonferroni": "bonferroni",
               "Unadjusted": "unadjusted"}[options.get("Post-hoc", "None")]
    compare = options.get("Comparison factor") or None
    condition = options.get("Condition on factors") or ()
    comparison = {"compare": compare, "condition": condition,
                  "family": options.get("Comparison families", "Separate").lower()} if posthoc or compare or condition else {}
    inference = {"Satterthwaite": "satterthwaite",
                 "Kenward–Roger": "kenward-roger"}[options.get("Denominator method", "Satterthwaite")]
    tables = mixed_effects_anova(data, response, [*within, *between], subject,
                                 within=within, posthoc=posthoc, inference=inference, **comparison)
    means = tables["Estimated marginal means"]
    figure, axes = _plot("Mixed-effects estimated marginal means", "", response)
    ticks = np.arange(len(means))
    estimates = means["Estimate"].to_numpy(dtype=float)
    low, high = (means[column].to_numpy(dtype=float) for column in ("CI 95% low", "CI 95% high"))
    bounded = np.isfinite(low) & np.isfinite(high)
    axes.plot(ticks, estimates, "o", color="#2866ae")
    if bounded.any():
        limits = np.vstack([estimates[bounded] - low[bounded], high[bounded] - estimates[bounded]])
        axes.errorbar(ticks[bounded], estimates[bounded], yerr=np.maximum(limits, 0),
                      fmt="none", ecolor="#2866ae", capsize=3)
    axes.set_xticks(ticks, [f"{factor}: {level}" for factor, level in zip(means["Factor"], means["Level"], strict=True)],
                    rotation=30, ha="right")
    return Result(tables, figure)


def _labels(index):
    labels = []
    for scope, group, parameter in index:
        if scope == "Local":
            labels.append(f"{parameter} ({group})")
        else:
            labels.append(f"{parameter} ({scope.lower()})")
    return labels


def _plot_saved_replicates(axes, frame, options, label):
    display = options.get(SAVED_REPLICATE_DISPLAY)
    if (not isinstance(display, dict) or options.get("Input format") != "Wide XY"
            or not options.get("Merge numbered replicates", True)
            or options.get("Replicates", "Individual observations") != "Individual observations"
            or options.get("X values", "As entered") != "As entered"):
        return None
    style = display.get(label)
    if not isinstance(style, dict):
        return None
    marker, side, color = style.get("marker"), style.get("side"), style.get("color")
    line_color = style.get("line_color")
    if (marker not in ("s", "^") or side not in ("upper", "lower")
            or not all(isinstance(c, str) and len(c) == 7 and c.startswith("#") and is_color_like(c)
                       for c in (color, line_color))):
        return None
    # Summarise replicate subcolumns within the source row. Distinct rows can have the same X.
    columns = [c for c in options["Y columns"] if _series_name(c, True) == label]
    if not columns:
        return None
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    x = pd.to_numeric(frame[options["X"]], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    center = values.mean(axis=1).to_numpy(dtype=float, na_value=np.nan)
    deviation = values.std(axis=1, ddof=1).to_numpy(dtype=float, na_value=np.nan)
    valid = np.isfinite(x) & np.isfinite(center)
    axes.scatter(x[valid], center[valid], color=color, marker=marker, s=18)
    whiskers = valid & np.isfinite(deviation) & (deviation > 0)
    end = center[whiskers] + (1 if side == "upper" else -1) * deviation[whiskers]
    axes.vlines(x[whiskers], center[whiskers], end, color=color, linewidth=0.9)
    axes.plot(x[whiskers], end, linestyle="none", marker="_", markersize=4, color=color)
    return line_color


def global_analysis(frame, options):
    from .global_fit import global_nonlinear

    data, xlabel, ylabel, sigma = curve_input(frame, options)
    model = options["Model"]
    intervals = "profile" if options.get("Parameter intervals") == "Profile likelihood" else "symmetric"
    kwargs = {"intervals": intervals} if intervals != "symmetric" else {}
    constraints = decode_series_constraints(options.get("Series constraints", []))
    fits = global_nonlinear(
        data, "X", "Response", model, "Series",
        shared=options.get("Shared parameters", ()), fixed=options.get("Fixed parameters"),
        bounds=options.get("Parameter bounds"), weighting=options.get("Weighting", "Unweighted"),
        sigma=sigma, compare=options.get("Compare with independent fits", False),
        compare_local=options.get("Compare local parameters", ()), initial=options.get("Initial values"),
        series_constraints=constraints, **kwargs,
    )
    summary = fits.parameters.reset_index()
    outputs = {"Parameters": summary, "Joint fit": _report(fits.diagnostics)}
    if constraints:
        outputs["Series constraints"] = pd.DataFrame([
            {"Series": label, "Parameter": name, "Fixed value": settings.get("fixed"),
             "Lower": settings.get("lower"), "Upper": settings.get("upper"), "Start": settings.get("initial")}
            for label, parameters in constraints.items() for name, settings in parameters.items()
        ])
    if fits.comparison is not None:
        outputs["Shared vs independent"] = _report(fits.comparison)
    elif fits.comparison_note:
        outputs["Shared vs independent"] = _report({"Note": fits.comparison_note})
    if fits.local_comparison is not None:
        outputs["Selected parameter comparison"] = _report(fits.local_comparison)
    elif fits.local_comparison_note:
        outputs["Selected parameter comparison"] = _report({"Note": fits.local_comparison_note})
    if not fits.covariance.empty:
        labels = _labels(fits.covariance.index)
        outputs["Parameter covariance"] = fits.covariance.set_axis(labels).set_axis(labels, axis=1)

    figure, axes = _plot(f"Global fit · {model}", xlabel, ylabel)
    mark_supported(axes)
    positive = True
    residuals, predictions, by_series = [], [], []
    for label, fit in fits.groups.items():
        name = str(label)
        color = _plot_saved_replicates(axes, frame, options, label)
        curve_label = name
        if color is None:
            dots = axes.scatter(fit.data["X"], fit.data["Response"], label=name, s=18)
            color = dots.get_facecolor()[0]
            curve_label = None
        x, predicted = fit.curve.T
        axes.plot(x, predicted, color=color, label=curve_label)
        positive = positive and bool(np.all(x > 0))
        values = pd.DataFrame({"Series": label, "X": x, "Predicted": predicted})
        if fit.band is not None:
            low, high = fit.band.T
            values["CI 95% low"], values["CI 95% high"] = low, high
            if options.get("Show confidence bands", False):
                axes.fill_between(x, low, high, color=color, alpha=.15, linewidth=0)
        predictions.append(values)
        residuals.append(fit.residuals.assign(Series=label))
        by_series.append({"Series": label, **fit.diagnostics})
    if MODELS[model].log_grid and positive:
        axes.set_xscale("log")
    if len(fits.groups) <= 15:
        axes.legend()
    outputs["Per-series fit"] = pd.DataFrame(by_series).set_index("Series")
    outputs["Fit curves"] = pd.concat(predictions, ignore_index=True)
    outputs["Residuals"] = pd.concat(residuals)
    return Result(outputs, figure)
