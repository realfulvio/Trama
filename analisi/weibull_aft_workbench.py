"""Weibull AFT regression: the dialog options, the dispatcher entry and the figure of the survival profiles.

Statistics live in ``weibull_aft``; this module declares the fields, runs that engine once and draws the optional
figure. Nothing here changes the worksheet.

A recipe uses the canonical English keys of ``OPTIONS``. Missing keys take their defaults (``Shape`` is read only
when ``Shape mode`` is ``Fixed``, so the dialog hides it otherwise and a hidden field is never validated).
"""
import numpy as np
from matplotlib.figure import Figure

from . import weibull_aft as engine
from .category_graphs import COLORS
from .cox_outputs import CENSOR_VALUE, EVENT_VALUE, PROFILE_LIST
from .processing import OPTIONAL_MULTIPLE, TEXT
from .reporting import Result
from .weibull_aft import (CATEGORICAL, ESTIMATED, EVENT, FIXED, LEVEL, METHOD, PREDICTORS, PROFILES, SHAPE, SHAPE_MODE,
                          SHAPE_MODES, SHOW_GRAPH, TIME, TIMES)
from .weibull_aft_text import ERROR_PREFIX, PREFIX

WEIBULL_AFT = METHOD
TIME_LIST = "Weibull AFT times"  # dialog kind of the Times field (a line editor, see weibull_aft_dialog)
GID_PROFILE = "aft-profile-{number}"
GID_EXTRAPOLATED = "aft-extrapolated"

DEFAULTS = {EVENT_VALUE: "1", CENSOR_VALUE: "0"}
OPTIONS = {TIME: None, EVENT: None, EVENT_VALUE: TEXT, CENSOR_VALUE: TEXT, PREDICTORS: OPTIONAL_MULTIPLE,
           CATEGORICAL: OPTIONAL_MULTIPLE, SHAPE_MODE: SHAPE_MODES, SHAPE: 1.5, LEVEL: 95.0, PROFILES: PROFILE_LIST,
           TIMES: TIME_LIST, SHOW_GRAPH: False}
DATA_FIELDS = (TIME, EVENT, EVENT_VALUE, CENSOR_VALUE, PREDICTORS, CATEGORICAL)
MODEL_FIELDS = (SHAPE_MODE, SHAPE, LEVEL)
PREDICT_FIELDS = (PROFILES, TIMES, SHOW_GRAPH)

# Interface captions and choices (catalog keys of weibull_aft_text); recipes keep the English names and values.
TAB_KEYS = {"Data": PREFIX + "tab.data", "Model": PREFIX + "tab.model", "Predicted survival": PREFIX + "tab.predicted"}
LABEL_KEYS = {TIME: PREFIX + "field.time", EVENT: PREFIX + "field.event", EVENT_VALUE: PREFIX + "field.event_value",
              CENSOR_VALUE: PREFIX + "field.censor_value", PREDICTORS: PREFIX + "field.predictors",
              CATEGORICAL: PREFIX + "field.categorical", SHAPE_MODE: PREFIX + "field.shape_mode",
              SHAPE: PREFIX + "field.shape", LEVEL: PREFIX + "field.level", PROFILES: PREFIX + "field.profiles",
              TIMES: PREFIX + "field.times", SHOW_GRAPH: PREFIX + "field.show_graph"}
CHOICE_KEYS = {ESTIMATED: PREFIX + "choice.estimated", FIXED: PREFIX + "choice.fixed"}
HINT_KEYS = {"model": PREFIX + "hint.model", "profiles": PREFIX + "hint.profiles", "times": PREFIX + "hint.times",
             "status": PREFIX + "hint.status", "profile": PREFIX + "profile.hint"}

PALETTE = (*COLORS, "#6f6f9a", "#a5693d", "#3b8ea5", "#8a8f35")
DASHES = ("-", "--", ":", "-.")
MARKER_LIMIT = 15  # an explicit short list of times is drawn with its points visible


def visibility(shape_mode):
    """Shape belongs to the fixed mode; hidden, it is neither validated nor saved."""
    return {SHAPE: shape_mode == FIXED}


def check_options(frame, options):
    """Every value, role and budget that can be checked without a fit; raises FieldError."""
    return engine.check_options(frame, options)


# ----- figure ----------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _figure(plan, tables, time_label):
    """One vector line per profile through the points of the Survival curves sheet, on the scale 0 to 1."""
    names, times = plan.profile_names, plan.times
    survival = tables[engine.CURVES_SHEET]["Survival"].to_numpy(dtype=float).reshape(len(names), len(times))
    figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
    axes = figure.add_subplot()
    marker = "o" if len(plan.settings.times) and len(times) <= MARKER_LIMIT else None
    for index, name in enumerate(names):
        color, dash = PALETTE[index % len(PALETTE)], DASHES[index // len(PALETTE) % len(DASHES)]
        line, = axes.plot(times, survival[index], color=color, linestyle=dash, linewidth=2.0, marker=marker,
                          markersize=4.5, label=name, clip_on=False, zorder=3)
        line.set_gid(GID_PROFILE.format(number=index + 1))
    longest = plan.data.maximum_time
    right = float(times[-1])
    handles, labels = axes.get_legend_handles_labels()
    if right > longest:
        shade = axes.axvspan(longest, right, color="#6b7785", alpha=.09, linewidth=0, zorder=0)
        shade.set_gid(GID_EXTRAPOLATED)
        shade.set_label("Extrapolated beyond the longest observed time")
        handles.append(shade)
        labels.append(shade.get_label())
    axes.set_xlim(0.0, right if right > 0 else 1.0)
    axes.set_ylim(0.0, 1.0)
    axes.set_xlabel(time_label)
    axes.set_ylabel("Survival probability")
    axes.set_title("Predicted survival (Weibull AFT)")
    axes.spines[["right", "top"]].set_visible(False)
    axes._tramastat_numeric_axes = ("x", "y")
    legend = axes.legend(handles, labels, title="Profile", frameon=False, loc="best")
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label, legend.get_title(), *legend.get_texts())
    return figure


# ----- analysis --------------------------------------------------------------------------------------------------------

def weibull_aft(frame, options):
    """Check, fit once and report: the sheets of ``weibull_aft.run`` and, on request, the profile figure."""
    tables, plan, _ = engine.run(frame, options)
    figure = _figure(plan, tables, str(plan.settings.time)) if plan.settings.show_graph else None
    return Result(tables, figure)


__all__ = ["CHOICE_KEYS", "DATA_FIELDS", "DEFAULTS", "ERROR_PREFIX", "HINT_KEYS", "LABEL_KEYS", "MODEL_FIELDS",
           "OPTIONS", "PREDICT_FIELDS", "TAB_KEYS", "TIME_LIST", "WEIBULL_AFT", "check_options", "visibility",
           "weibull_aft"]
