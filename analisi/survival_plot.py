"""Kaplan–Meier presentation options. Inference stays on the survival scale."""
from dataclasses import dataclass

from matplotlib.artist import Artist
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.ticker import PercentFormatter
from matplotlib.transforms import blended_transform_factory, offset_copy
import numpy as np
import pandas as pd

from .analysis_chain import RESULT_CONTEXT
from .linked_axes import style_without_linked_y
from .processing import FieldError
from .reporting import Result, _plot
from .stats import _critical_value, ci_columns

CURVE = "Curve"
UNITS = "Display units"
MARKERS = "Observation markers"
UNCERTAINTY = "Uncertainty"
INTERVAL = "Interval method"
RISK_TABLE = "Show risk table below graph"
SURVIVAL_GRAPH = "Imported survival graph"
SURVIVAL_SERIES = "Imported survival series order"
SURVIVAL_SUMMARY = "Survival summary"
SURVIVAL, CUMULATIVE = "Survival", "Cumulative events"
FRACTION, PERCENT = "Fraction", "Percent"
CENSORED, ALL, FINAL = "Censored observations", "All observations", "Final censor only"
NO_UNCERTAINTY, ERROR_BARS, BAND = "None", "Standard error bars", "Pointwise confidence band"
CI_BARS = "Pointwise confidence bars"
LOG_LOG, GREENWOOD = "Log-log", "Symmetric Greenwood"
GRAPH_OPTIONS = {
    CURVE: (SURVIVAL, CUMULATIVE), UNITS: (FRACTION, PERCENT),
    MARKERS: (CENSORED, ALL, FINAL), UNCERTAINTY: (NO_UNCERTAINTY, ERROR_BARS, BAND, CI_BARS),
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
    elif settings[UNCERTAINTY] == CI_BARS:
        # A censor-only time does not change the estimate. Collapsed intervals
        # at a terminal step have no visible extent.
        positions = (curve["Events"].to_numpy() > 0) & (upper > lower)
        if positions.any():
            lengths = np.stack((probabilities[positions] - lower[positions],
                                upper[positions] - probabilities[positions]))
            axes.errorbar(times[positions], y[1:][positions], yerr=factor * np.maximum(lengths, 0),
                          fmt="none", capsize=2, ecolor=color, alpha=.65)
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


@dataclass(frozen=True, eq=False)
class SurvivalGraphData:
    curves: dict
    settings: dict
    time: str
    level: float
    show_risk: bool
    short_labels: bool


def draw_survival_graph(data, title, axes=None, risk_axes=None, *, order=()):
    ylabel = ordinate_label(data.settings)
    if axes is None and data.show_risk:
        figure = Figure(figsize=(8, 5.5), dpi=100, layout="constrained")
        panels = figure.add_gridspec(2, 1, height_ratios=[3, 1.2])
        axes = figure.add_subplot(panels[0])
        axes.spines[["right", "top"]].set_visible(False)
        risk_axes = figure.add_subplot(panels[1])
        axes.set(title=title, xlabel=data.time, ylabel=ylabel)
    elif axes is None:
        figure, axes = _plot(title, data.time, ylabel)
    else:
        figure = axes.figure
        axes.set(title=title, xlabel=data.time, ylabel=ylabel)
    format_ordinate(axes, data.settings)
    maximum = max(curve["Time"].max() for curve in data.curves.values())
    ticks = np.unique(np.linspace(0, maximum, 6).round(8))
    tables, risk_rows = {}, {}
    rank = {label: index for index, label in enumerate(order)}
    labels = sorted(data.curves, key=lambda label: rank.get(str(label), len(rank))) if rank else data.curves
    for label in labels:
        curve = data.curves[label]
        risk_rows[str(label)] = risk_counts(curve, ticks)
        tables[label] = display_curve(axes, label, curve, data.settings, data.level)
    if len(data.curves) > 1:
        axes.legend()
    risks = pd.DataFrame.from_dict(risk_rows, orient="index", columns=ticks).rename_axis("Group")
    if data.show_risk:
        if len(data.curves) > 8:
            raise ValueError("The plot can show a risk table for up to eight groups.")
        draw_risk_table(axes, risk_axes, {label: data.curves[label] for label in labels}, data.short_labels)
    return figure, tables, risks


def risk_counts(curve, ticks):
    indices = curve["Time"].to_numpy().searchsorted(ticks)
    return np.r_[curve["At risk"].to_numpy(), 0][indices]


class _RiskCounts(Artist):
    """Draw counts at current major ticks, including during navigation and export."""

    def __init__(self, plot, panel, curves, row_positions):
        super().__init__()
        self.plot = plot
        self.curves = curves
        self.row_positions = row_positions
        self.panel_index = panel.figure.axes.index(panel)
        self.set_gid(f"kaplan-meier-risk-counts-{self.panel_index}")
        self.transform = blended_transform_factory(plot.transData, panel.transAxes)

    def draw(self, renderer):
        if not self.get_visible():
            return
        left, right = sorted(self.plot.get_xlim())
        ticks = np.unique(self.plot.get_xticks())
        ticks = ticks[(ticks >= max(left, 0)) & (ticks <= right)]
        renderer.open_group("kaplan-meier-risk-counts", self.get_gid())
        try:
            for index, (curve, y) in enumerate(zip(self.curves.values(), self.row_positions, strict=True)):
                for column, (tick, count) in enumerate(zip(ticks, risk_counts(curve, ticks), strict=True)):
                    text = Text(x=tick, y=y, text=str(count), transform=self.transform, ha="center",
                                va="center", fontsize=8, color="#203b53",
                                gid=f"risk-count-{self.panel_index}-{index}-{column}", usetex=False, parse_math=False)
                    text.set_figure(self.get_figure())
                    text.draw(renderer)
        finally:
            renderer.close_group("kaplan-meier-risk-counts")


def draw_risk_table(plot, axes, curves, short_labels):
    axes.set_axis_off()
    positions = np.linspace(.78, .08, len(curves) + 1)
    left = offset_copy(axes.transAxes, fig=axes.figure, x=-8, units="points")
    labels = [str(label).partition(" · ")[0] if short_labels else str(label) for label in curves]
    panel_index = axes.figure.axes.index(axes)
    for index, (label, y) in enumerate(zip(["At risk", *labels], positions, strict=True)):
        axes.text(0, y, label, transform=left, ha="right", va="center", color="#203b53",
                  fontsize=8, weight="bold", gid=f"risk-label-{panel_index}-{index}", parse_math=False)
    axes.add_artist(_RiskCounts(plot, axes, curves, positions[1:]))


def linked_survival_graph(frame, title, order):
    data = frame.attrs.get(RESULT_CONTEXT)
    if not isinstance(data, SurvivalGraphData):
        raise ValueError("The input no longer provides a linked Kaplan–Meier graph.")
    if not isinstance(order, list) or any(not isinstance(label, str) for label in order):
        raise ValueError("Invalid linked Kaplan–Meier series order.")
    figure, _, _ = draw_survival_graph(data, title, order=order)
    figure.axes[0].title.set_parse_math(False)
    return Result({}, figure)


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
    # The Y quantity changed (probability, percent, cumulative events): a unit set for the old one no longer holds.
    return style_without_linked_y(updated)
