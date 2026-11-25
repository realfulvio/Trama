"""Figure of Deming regression: the historical single series, several series and projection segments.

The single-series figure without projections is drawn exactly as in earlier versions. Projection segments are one
``LineCollection`` per series in the colour of that series, added below the points; they are the only line
collections of the axes. Several series get their own colour and marker, their own fitted line, and one literal
legend entry each (series names are never read as mathtext). One identity line spans the union of the X and Y
values actually used by every series.
"""
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from .deming import analyse_fit, identity_limits
from .reporting import Result, _plot

PALETTE = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
           "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#393b79", "#843c39")
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "*", "p")
IDENTITY_COLOR = "#81919b"
SEGMENT_ZORDER = 0.9


def segments(fit):
    """Observed-to-projected segments of one series as an (n, 2, 2) array."""
    observed = np.column_stack((fit.x, fit.y))
    projected = np.column_stack((fit.projected_x, fit.projected_y))
    return np.stack((observed, projected), axis=1)


def _literal(axes):
    for label in (axes.xaxis.label, axes.yaxis.label, axes.title):
        label.set_parse_math(False)


def _add_segments(axes, fit, color):
    axes.add_collection(LineCollection(segments(fit), colors=color, linewidths=1.0, zorder=SEGMENT_ZORDER))


def _single(result, frame, options):
    settings = result.settings
    fit = result.series[0]
    x, y = settings.x, settings.y
    figure, axes = _plot("Deming regression", x, y)
    if settings.extended:
        _literal(axes)
    if fit.projected_x is not None:
        _add_segments(axes, fit, PALETTE[0])
    axes.scatter(fit.x, fit.y)
    if options.get("Identity line"):
        low, high = identity_limits(fit.x, fit.y)
        domain = np.array([low, high])
        axes.plot(domain, fit.intercept + fit.slope * domain, label="Deming fit")
        axes.plot(domain, domain, linestyle="--", color=IDENTITY_COLOR, label="Identity")
        axes.set_xlim(low, high)
        axes.set_ylim(low, high)
        legend = axes.legend()
        if settings.extended:
            for text in legend.get_texts():
                text.set_parse_math(False)
    else:
        domain = np.array([fit.x.min(), fit.x.max()])
        axes.plot(domain, fit.intercept + fit.slope * domain)
    return figure


def _several(result, options):
    settings = result.settings
    names = [fit.name for fit in result.series]
    figure, axes = _plot("Deming regression", settings.x, names[0] if len(names) == 1 else "Y")
    _literal(axes)
    identity = bool(options.get("Identity line"))
    if identity:
        low, high = identity_limits(np.concatenate([fit.x for fit in result.series]),
                                    np.concatenate([fit.y for fit in result.series]))
    handles = []
    for index, fit in enumerate(result.series):
        color, marker = PALETTE[index % len(PALETTE)], MARKERS[index % len(MARKERS)]
        if fit.projected_x is not None:
            _add_segments(axes, fit, color)
        axes.scatter(fit.x, fit.y, color=color, marker=marker)
        domain = np.array([low, high]) if identity else np.array([fit.x.min(), fit.x.max()])
        axes.plot(domain, fit.intercept + fit.slope * domain, color=color)
        handles.append(Line2D([], [], color=color, marker=marker, linestyle="-", label=fit.name))
    if identity:
        axes.plot([low, high], [low, high], linestyle="--", color=IDENTITY_COLOR)
        axes.set_xlim(low, high)
        axes.set_ylim(low, high)
        handles.append(Line2D([], [], color=IDENTITY_COLOR, linestyle="--", label="Identity"))
    legend = axes.legend(handles=handles, fontsize="small" if len(handles) > 6 else None)
    for text in legend.get_texts():
        text.set_parse_math(False)
    return figure


def deming_result(frame, options, cancel=None):
    """Fit, tabulate and draw. The figure stays the series figure; a paired sheet is added only when requested."""
    result = analyse_fit(frame, options, cancel=cancel)
    figure = _single(result, frame, options) if result.settings.series is None else _several(result, options)
    return Result(result.tables, figure)
