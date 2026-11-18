"""Restricted mean survival time: the dialog options, the dispatcher entry and the native figure.

Statistics live in ``rmst``; this module declares the fields, runs that engine once and draws the optional
figure: the Kaplan–Meier step curve of each group from 0 to the horizon, the integrated area under it, shaded,
and a vertical line at the horizon. Nothing here changes the worksheet.

A recipe uses the canonical English keys of ``OPTIONS``. Missing keys take their defaults; ``Horizon`` has none
and must be declared. The dialog hides ``Reference group`` while Group is empty, and a hidden field is not saved.
"""
import numpy as np
from matplotlib.figure import Figure

from . import rmst as engine
from .category_graphs import COLORS
from .processing import OPTIONAL, TEXT
from .reporting import Result
from .rmst import (CENSOR_CODE, EVENT_CODE, GROUP, HORIZON, LEVEL, METHOD, REFERENCE, SHOW_GRAPH, STATUS, TIME,
                   show_number)
from .rmst_text import ERROR_PREFIX, PREFIX

RMST = METHOD
GROUP_CHOICE = "Group choice"  # the workbench dialog kind of a combobox filled with the groups found in the data
NUMBER_FIELDS = (HORIZON, LEVEL)  # typed numbers: the decimal comma is accepted, unparsable text reaches the engine

DEFAULTS = {EVENT_CODE: "1", CENSOR_CODE: "0"}
OPTIONS = {TIME: None, STATUS: None, GROUP: OPTIONAL, REFERENCE: GROUP_CHOICE, HORIZON: TEXT, EVENT_CODE: TEXT,
           CENSOR_CODE: TEXT, LEVEL: 95.0, SHOW_GRAPH: True}
DATA_FIELDS = (TIME, STATUS, GROUP, REFERENCE, HORIZON)
ESTIMATE_FIELDS = (EVENT_CODE, CENSOR_CODE, LEVEL, SHOW_GRAPH)

# Interface captions (catalog keys of rmst_text); recipes keep the English names and values.
TAB_KEYS = {"Data": PREFIX + "tab.data", "Options": PREFIX + "tab.options"}
LABEL_KEYS = {TIME: PREFIX + "field.time", STATUS: PREFIX + "field.status", GROUP: PREFIX + "field.group",
              REFERENCE: PREFIX + "field.reference", EVENT_CODE: PREFIX + "field.event",
              CENSOR_CODE: PREFIX + "field.censor", HORIZON: PREFIX + "field.horizon", LEVEL: PREFIX + "field.level",
              SHOW_GRAPH: PREFIX + "field.show_graph"}
HINT_KEYS = {"horizon": PREFIX + "hint.horizon", "limit": PREFIX + "hint.limit", "estimate": PREFIX + "hint.estimate",
             "codes": PREFIX + "hint.codes"}

GID_CURVE, GID_AREA, GID_HORIZON = "rmst-curve-{index}", "rmst-area-{index}", "rmst-horizon"
AREA_ALPHA = .22  # two overlapping areas stay readable


def visibility(group):
    """The reference group belongs to a two-group analysis; hidden, it is neither validated nor saved."""
    return {REFERENCE: bool(group)}


def check_options(frame, options):
    """Every value, role and budget that can be checked without integrating; raises FieldError."""
    return engine.check_options(frame, options)


# ----- figure ----------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def curve_points(estimate, tau):
    """Vertices of the drawn step curve: one per rectangle, then τ with the survival after the events at τ."""
    return np.r_[estimate.left, tau], np.r_[estimate.survival, estimate.end]


def figure(plan, estimates):
    tau = plan.settings.horizon
    fig = Figure(figsize=(8, 5), dpi=100, layout="constrained")
    axes = fig.add_subplot()
    for index, estimate in enumerate(estimates):
        color = COLORS[index % len(COLORS)]
        x, y = curve_points(estimate, tau)
        area = axes.fill_between(x, y, 0.0, step="post", color=color, alpha=AREA_ALPHA, linewidth=0, zorder=1,
                                 label="_nolegend_")
        area.set_gid(GID_AREA.format(index=index))
        line, = axes.plot(x, y, color=color, linewidth=2.0, drawstyle="steps-post", label=estimate.label,
                          clip_on=False, zorder=3)
        line.set_gid(GID_CURVE.format(index=index))
    horizon = axes.axvline(tau, color="#3d4852", linestyle="--", linewidth=1.2, zorder=2,
                           label=f"Horizon τ = {show_number(tau)}")
    horizon.set_gid(GID_HORIZON)
    axes.set_xlim(0.0, tau)
    axes.set_ylim(0.0, 1.0)
    axes.set_xlabel(str(plan.settings.time))
    axes.set_ylabel("Survival probability")
    axes.set_title(f"Restricted mean survival time up to τ = {show_number(tau)}")
    axes.spines[["right", "top"]].set_visible(False)
    axes._tramastat_numeric_axes = ("x", "y")
    legend = axes.legend(frameon=False, loc="lower left")
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label, *legend.get_texts())
    return fig


# ----- analysis --------------------------------------------------------------------------------------------------------

def rmst(frame, options):
    """Check, integrate once and report: the sheets of ``rmst.run`` and, on request, the shaded figure."""
    tables, plan, estimates = engine.run(frame, options)
    return Result(tables, figure(plan, estimates) if plan.settings.show_graph else None)


__all__ = ["DATA_FIELDS", "DEFAULTS", "ERROR_PREFIX", "ESTIMATE_FIELDS", "GROUP_CHOICE", "HINT_KEYS", "LABEL_KEYS",
           "NUMBER_FIELDS", "OPTIONS", "RMST", "TAB_KEYS", "check_options", "rmst", "visibility"]
