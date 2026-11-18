"""Cohen's kappa: the dialog options, the dispatcher entry and the figure of the agreement matrix.

Statistics live in ``cohen_kappa``; this module declares the fields, runs that engine once and draws the optional
figure. Nothing here changes the worksheet.

A recipe uses the canonical English keys of ``OPTIONS``. Missing keys take their defaults. The bootstrap fields
are read only with ``Bootstrap percentile``, so the dialog hides them otherwise and keeps whatever they hold.
"""
import numpy as np
from matplotlib import colormaps
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from . import cohen_kappa as engine
from .cohen_kappa import (BOOTSTRAP, DEFAULTS, FIRST, INTERVAL, LEVEL, LINEAR, METHOD, NO_INTERVAL, ORDER,
                          QUADRATIC, RESAMPLES, SECOND, SEED, SHOW_GRAPH, UNWEIGHTED, WEIGHTING, WEIGHTINGS, INTERVALS)
from .cohen_kappa_text import ERROR_PREFIX, PREFIX
from .reporting import Result

COHEN_KAPPA = METHOD
ORDER_LIST = "Kappa category order"  # dialog kind of the Category order field (the editor of cohen_kappa_dialog)
GID_COUNTS = "kappa-counts"
GID_DIAGONAL = "kappa-diagonal"
GID_COUNT = "kappa-count-{row}-{column}"

OPTIONS = {FIRST: None, SECOND: None, WEIGHTING: WEIGHTINGS, ORDER: ORDER_LIST, INTERVAL: INTERVALS,
           LEVEL: DEFAULTS[LEVEL], RESAMPLES: DEFAULTS[RESAMPLES], SEED: DEFAULTS[SEED],
           SHOW_GRAPH: DEFAULTS[SHOW_GRAPH]}
RATING_FIELDS = (FIRST, SECOND, WEIGHTING, ORDER)
INTERVAL_FIELDS = (INTERVAL, LEVEL, RESAMPLES, SEED, SHOW_GRAPH)
TYPED_FIELDS = engine.BOOTSTRAP_FIELDS  # read by the dialog itself: numbers when they parse, the text otherwise

# Interface captions and choices (catalog keys of cohen_kappa_text); recipes keep the English names and values.
TAB_KEYS = {"Ratings": PREFIX + "tab.ratings", "Interval and graph": PREFIX + "tab.interval"}
LABEL_KEYS = {FIRST: PREFIX + "field.first", SECOND: PREFIX + "field.second", WEIGHTING: PREFIX + "field.weighting",
              ORDER: PREFIX + "field.order", INTERVAL: PREFIX + "field.interval", LEVEL: PREFIX + "field.level",
              RESAMPLES: PREFIX + "field.resamples", SEED: PREFIX + "field.seed",
              SHOW_GRAPH: PREFIX + "field.show_graph"}
CHOICE_KEYS = {UNWEIGHTED: PREFIX + "choice.unweighted", LINEAR: PREFIX + "choice.linear",
               QUADRATIC: PREFIX + "choice.quadratic", NO_INTERVAL: PREFIX + "choice.none",
               BOOTSTRAP: PREFIX + "choice.bootstrap"}
HINT_KEYS = {"ratings": PREFIX + "hint.ratings", "interval": PREFIX + "hint.interval"}

CMAP = "Blues"
DIAGONAL_EDGE = "#14324a"


def visibility(interval):
    """Level, resamples and seed belong to the bootstrap; hidden, they are neither validated nor rewritten."""
    shown = interval == BOOTSTRAP
    return dict.fromkeys(TYPED_FIELDS, shown)


def cancellable(method, options):
    """True when the run can take long enough to deserve a Cancel button: the bootstrap."""
    return method == COHEN_KAPPA and isinstance(options, dict) and options.get(INTERVAL, NO_INTERVAL) == BOOTSTRAP


def check_options(frame, options):
    """Every value, role, category and budget that can be checked without the bootstrap; raises FieldError."""
    return engine.check_options(frame, options)


# ----- figure ----------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _font(size):
    return 11.0 if size <= 6 else 9.5 if size <= 10 else 8.0 if size <= 15 else 7.0


def _title(weighting, point):
    if np.isnan(point):
        return f"{weighting} kappa undefined (a single category)"
    return f"{weighting} kappa = {point:.3f}"


def figure(plan, point):
    """The counts as a vector matrix: rows are the first rating (top to bottom), columns the second rating.

    The orientation, the labels and the numbers are those of the Counts sheet. The diagonal of agreement is
    outlined so it stays visible whatever the colour of its cells, and every cell writes its count.
    """
    counts, labels, size = plan.counts, plan.labels, plan.size
    side = max(5.8, .36 * size + 3.4)
    result = Figure(figsize=(side + 1.2, side), dpi=100, layout="constrained")
    axes = result.add_subplot()
    cmap = colormaps[CMAP]
    top = max(1, int(counts.max()))
    mesh = axes.pcolormesh(np.arange(size + 1), np.arange(size + 1), counts, cmap=cmap, vmin=0, vmax=top,
                           edgecolors="#ffffff", linewidth=.8, shading="flat")
    mesh.set_gid(GID_COUNTS)
    for index in range(size):
        cell = Rectangle((index, index), 1, 1, fill=False, edgecolor=DIAGONAL_EDGE, linewidth=1.8, zorder=3)
        cell.set_gid(f"{GID_DIAGONAL}-{index + 1}")
        axes.add_patch(cell)
    font = _font(size)
    for (row, column), value in np.ndenumerate(counts):
        shade = cmap(value / top)
        brightness = shade[0] * .2126 + shade[1] * .7152 + shade[2] * .0722
        text = axes.text(column + .5, row + .5, str(int(value)), ha="center", va="center", fontsize=font,
                         color="#13212d" if brightness > .55 else "#ffffff",
                         fontweight="bold" if row == column else "normal", parse_math=False, zorder=4)
        text.set_gid(GID_COUNT.format(row=row + 1, column=column + 1))
    positions = np.arange(size) + .5
    rotate = size > 6 or max((len(name) for name in labels), default=0) > 10
    axes.set_xticks(positions, labels, rotation=40 if rotate else 0, ha="right" if rotate else "center",
                    rotation_mode="anchor", parse_math=False, fontsize=font + 1)
    axes.set_yticks(positions, labels, parse_math=False, fontsize=font + 1)
    axes.set_xlim(0, size)
    axes.set_ylim(size, 0)  # the first category on top, as in the sheet
    axes.set_aspect("equal")
    axes.tick_params(length=0)
    for spine in axes.spines.values():
        spine.set_visible(False)
    axes.set_xlabel(str(plan.settings.second))
    axes.set_ylabel(str(plan.settings.first))
    axes.set_title(_title(plan.settings.weighting, point))
    axes._tramastat_categorical_axes = ("x", "y")
    bar = result.colorbar(mesh, ax=axes, shrink=.8, pad=.03)
    bar.set_label("Count of pairs")
    bar.solids.set_rasterized(False)  # a long colour scale is rasterized by default; keep the whole figure vector
    bar.ax.yaxis.get_major_locator().set_params(integer=True)
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label, bar.ax.yaxis.label)
    return result


# ----- analysis --------------------------------------------------------------------------------------------------------

def cohen_kappa(frame, options, *, cancel=None):
    """Check, calculate (with the bootstrap on request) and report the sheets and, on request, the matrix."""
    tables, plan, point = engine.run(frame, options, cancel)
    return Result(tables, figure(plan, point) if plan.settings.show_graph else None)


__all__ = ["CHOICE_KEYS", "COHEN_KAPPA", "ERROR_PREFIX", "HINT_KEYS", "INTERVAL_FIELDS", "LABEL_KEYS", "OPTIONS",
           "ORDER_LIST", "RATING_FIELDS", "TAB_KEYS", "TYPED_FIELDS", "cancellable", "check_options", "cohen_kappa",
           "figure", "visibility"]
