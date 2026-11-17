"""Kaplan–Meier presentation options. Inference stays on the survival scale."""
import numpy as np
from matplotlib.ticker import PercentFormatter

from .processing import FieldError
from .stats import _critical_value, ci_columns

CURVE = "Curve"
UNITS = "Display units"
MARKERS = "Observation markers"
UNCERTAINTY = "Uncertainty"
INTERVAL = "Interval method"
RISK_TABLE = "Show risk table below graph"
SURVIVAL, CUMULATIVE = "Survival", "Cumulative events"
FRACTION, PERCENT = "Fraction", "Percent"
CENSORED, ALL, FINAL = "Censored observations", "All observations", "Final censor only"
NO_UNCERTAINTY, ERROR_BARS, BAND = "None", "Standard error bars", "Pointwise confidence band"
LOG_LOG, GREENWOOD = "Log-log", "Symmetric Greenwood"
GRAPH_OPTIONS = {
    CURVE: (SURVIVAL, CUMULATIVE), UNITS: (FRACTION, PERCENT),
    MARKERS: (CENSORED, ALL, FINAL), UNCERTAINTY: (NO_UNCERTAINTY, ERROR_BARS, BAND),
    INTERVAL: (LOG_LOG, GREENWOOD), RISK_TABLE: False,
}


def survival_graph_settings(options):
    settings = {}
    for field, choices in GRAPH_OPTIONS.items():
        if isinstance(choices, tuple):
            value = options.get(field, choices[0])
            if value not in choices:
                raise FieldError(field, f"Choose a valid value for {field.lower()}.")
            settings[field] = value
    return settings


def ordinate_label(settings):
    name = "Survival probability" if settings[CURVE] == SURVIVAL else "Cumulative event probability"
    return name + (" (%)" if settings[UNITS] == PERCENT else "")


def display_curve(axes, label, curve, settings, level):
    low_name, high_name = ci_columns(level)
    survival = curve["Survival"].to_numpy()
    lower, upper = (curve[key].to_numpy() for key in (low_name, high_name))
    if settings[INTERVAL] == GREENWOOD:
        margin = _critical_value(level) * curve["Standard error"].to_numpy()
        lower, upper = np.maximum(0, survival - margin), np.minimum(1, survival + margin)

    factor = 100 if settings[UNITS] == PERCENT else 1
    cumulative = settings[CURVE] == CUMULATIVE
    probabilities = 1 - survival if cumulative else survival
    if cumulative:
        lower, upper = 1 - upper, 1 - lower

    times = curve["Time"].to_numpy()
    x, y = np.r_[0, times], factor * np.r_[int(not cumulative), probabilities]
    line = axes.step(x, y, where="post", label=str(label))[0]
    color = line.get_color()
    marker_mode = settings[MARKERS]
    if marker_mode == ALL:
        positions = np.arange(len(curve))
    else:
        positions = np.flatnonzero(curve["Censored"].to_numpy() > 0)
        if marker_mode == FINAL:
            positions = positions[positions == len(curve) - 1]
    axes.plot(times[positions], y[1:][positions], "+" if marker_mode != ALL else "o",
              markersize=5 if marker_mode == ALL else 6, color=color)

    name = settings[CURVE] + (" (%)" if factor == 100 else "")
    table = curve.drop(columns=["Survival", low_name, high_name, "Standard error"], errors="ignore")
    table[name] = y[1:]
    table[low_name], table[high_name] = factor * lower, factor * upper
    if settings[UNCERTAINTY] == BAND:
        initial = int(not cumulative)
        axes.fill_between(x, factor * np.r_[initial, lower], factor * np.r_[initial, upper],
                          step="post", color=color, alpha=.17, linewidth=0)
    elif settings[UNCERTAINTY] == ERROR_BARS:
        error = curve["Standard error"].to_numpy()
        axes.errorbar(times, y[1:], yerr=factor * np.stack((np.minimum(probabilities, error),
                                                           np.minimum(1 - probabilities, error))),
                      fmt="none", capsize=2, ecolor=color, alpha=.65)
        table["Standard error"] = factor * error
    return table


def format_ordinate(axes, settings):
    factor = 100 if settings[UNITS] == PERCENT else 1
    axes.set_ylim(-.02 * factor, 1.03 * factor)
    if factor == 100:
        axes.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))


def style_after_parameter_change(style, before, after):
    old, new = survival_graph_settings(before), survival_graph_settings(after)
    if not style or all(old[field] == new[field] for field in (CURVE, UNITS)):
        return style
    updated = {key: value for key, value in style.items() if key not in {"yscale", "axis", "reference_lines"}}
    if updated.get("ylabel") == ordinate_label(old):
        updated.pop("ylabel")
    axes = {dimension: axis for dimension, axis in style.get("axis", {}).items() if dimension != "y"}
    refs = [ref for ref in style.get("reference_lines", []) if ref["axis"] != "y"]
    if axes:
        updated["axis"] = axes
    if refs:
        updated["reference_lines"] = refs
    return updated
