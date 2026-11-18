"""Competing risks: options, result sheets and the cumulative-incidence figure.

Statistics live in ``competing_risks``; this module reads the recipe, runs that engine and writes the sheets
(fractions, never percent) and a native Matplotlib figure. Nothing here changes the worksheet.

A recipe uses the canonical English keys of ``OPTIONS``. Missing keys take their defaults, so a short recipe
written by hand or by an older version still runs. The dialog hides ``Graph cause`` when every cause is drawn,
and a hidden field is never validated.
"""
from numbers import Real

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from . import competing_risks as engine
from .category_graphs import COLORS
from .field_error import FieldError
from .reporting import Result

COMPETING_RISKS = "Competing risks"
TIME, STATUS, GROUP = "Time", "Status", "Group"
CENSOR, EVENTS, TIMES = "Censor code", "Event codes", "Times"
LEVEL, GRAY, GRAPH = "Confidence level (%)", "Gray tests", "Graph"
GRAPH_CAUSE, DISPLAY, BANDS = "Graph cause", "Display", "Show confidence bands"

GRAY_OFF, GRAY_OMNIBUS, GRAY_PAIRWISE = GRAY_CHOICES = ("Off", "Omnibus", "Omnibus and pairwise")
SELECTED, ALL_CAUSES = GRAPH_CHOICES = ("Selected cause", "All causes")
FRACTION, PERCENT = DISPLAY_CHOICES = ("Fraction", "Percent")

# Dialog kinds of the three fields that are not plain entries ("Optional" and "Text" are the kind names of workbench).
CODE_LIST = "Competing risks codes"
TIME_LIST = "Competing risks times"
CAUSE_CHOICE = "Competing risks cause"

DEFAULTS = {CENSOR: "0", EVENTS: ["1", "2"], TIMES: [], LEVEL: 95.0, GRAY: GRAY_OFF, GRAPH: SELECTED,
            GRAPH_CAUSE: "", DISPLAY: FRACTION, BANDS: False}
OPTIONS = {TIME: None, STATUS: None, GROUP: "Optional", CENSOR: "Text", EVENTS: CODE_LIST, TIMES: TIME_LIST,
           LEVEL: 95.0, GRAY: GRAY_CHOICES, GRAPH: GRAPH_CHOICES, GRAPH_CAUSE: CAUSE_CHOICE, DISPLAY: DISPLAY_CHOICES,
           BANDS: False}
DATA_FIELDS = (TIME, STATUS, GROUP, CENSOR, EVENTS)
ESTIMATE_FIELDS = (TIMES, LEVEL, GRAY)
GRAPH_FIELDS = (GRAPH, GRAPH_CAUSE, DISPLAY, BANDS)

CURVES_SHEET, TIMES_SHEET, GRAY_SHEET, PAIRWISE_SHEET, SETTINGS_SHEET = (
    "Cumulative incidence", "Time estimates", "Gray tests", "Gray pairwise", "Settings")
CURVE_COLUMNS = ["Group", "Time", "Cause", "At risk", "Cause events", "All events", "Censored", "Event-free", "CIF",
                 "Variance", "CI lower", "CI upper"]
TIME_COLUMNS = ["Group", "Time", "Cause", "CIF", "Variance", "CI lower", "CI upper", "Status"]
GRAY_COLUMNS = ["Cause", "Chi square", "df", "p", "Status", "Reason"]
PAIR_COLUMNS = ["Cause", "First", "Second", "Chi square", "df", "p", "Adjusted p", "Status", "Reason"]
OK, UNAVAILABLE = "OK", "Unavailable"
TIME_OK, TIME_NO_INTERVAL, TIME_BEYOND = "OK", "CI unavailable", "Beyond follow-up"

GID_CURVE, GID_BAND = "competing-risk-curve-g{group}-c{cause}", "competing-risk-band-g{group}-c{cause}"
PALETTE = (*COLORS, "#6f6f9a", "#a5693d", "#3b8ea5", "#8a8f35")
DASHES = ("-", "--", ":", "-.", (0, (5, 2, 1, 2, 1, 2)), (0, (1, 1, 5, 1)))
SINGLE_AXES_LIMIT = 12  # groups × causes drawn on one axes; more are split into one panel per cause

# Interface captions and choices; recipes keep the English field names and values.
TAB_KEYS = {"Data": "cr.tab.data", "Estimates": "cr.tab.estimates", "Graph": "cr.tab.graph"}
LABEL_KEYS = {TIME: "cr.field.time", STATUS: "cr.field.status", GROUP: "cr.field.group", CENSOR: "cr.field.censor",
              EVENTS: "cr.field.events", TIMES: "cr.field.times", LEVEL: "cr.field.level", GRAY: "cr.field.gray",
              GRAPH: "cr.field.graph", GRAPH_CAUSE: "cr.field.graph_cause", DISPLAY: "cr.field.display",
              BANDS: "cr.field.bands"}
CHOICE_KEYS = {GRAY_OFF: "cr.choice.off", GRAY_OMNIBUS: "cr.choice.omnibus", GRAY_PAIRWISE: "cr.choice.pairwise",
               SELECTED: "cr.choice.selected", ALL_CAUSES: "cr.choice.all", FRACTION: "cr.choice.fraction",
               PERCENT: "cr.choice.percent", "": "cr.choice.first_cause"}
ERROR_PREFIX = "cr.error."


def visibility(graph):
    """Graph cause belongs to the selected-cause view; hidden, it is neither validated nor saved."""
    return {GRAPH_CAUSE: graph != ALL_CAUSES}


def cancellable(method, options):
    """True when the run can take long enough to deserve a Cancel button: any Gray test."""
    return method == COMPETING_RISKS and isinstance(options, dict) and options.get(GRAY, GRAY_OFF) != GRAY_OFF


# ----- options ---------------------------------------------------------------------------------------------------------

def _typed(value):
    """A rejected time as the user would have typed it: 3.0 is shown as 3."""
    if isinstance(value, float) and np.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _finite_real(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if np.isfinite(number) else None


class Settings:
    """The recipe read and checked, before any worksheet value is looked at."""

    def __init__(self, options):
        get = lambda key: options.get(key, DEFAULTS.get(key))
        self.time, self.status = options.get(TIME), options.get(STATUS)
        self.group = options.get(GROUP) or ""
        self.censor = get(CENSOR)
        events = get(EVENTS)
        self.events = list(events) if isinstance(events, (list, tuple)) else events
        self.level = self._level(get(LEVEL))
        self.gray = self._choice(GRAY, get(GRAY), GRAY_CHOICES)
        self.graph = self._choice(GRAPH, get(GRAPH), GRAPH_CHOICES)
        self.display = self._choice(DISPLAY, get(DISPLAY), DISPLAY_CHOICES)
        bands = get(BANDS)
        if not isinstance(bands, (bool, np.bool_)):
            raise FieldError(BANDS, f"{BANDS} must be on or off.")
        self.bands = bool(bands)
        self.times = self._times(get(TIMES))
        self.graph_cause = get(GRAPH_CAUSE)

    @staticmethod
    def _level(value):
        number = _finite_real(value)
        if number is None or not 0 < number < 100:
            raise FieldError(LEVEL, f"{LEVEL} must be a number greater than 0 and less than 100.")
        return number

    @staticmethod
    def _choice(field, value, choices):
        if not isinstance(value, str) or value not in choices:
            raise FieldError(field, f"{field}: choose one of the listed options.")
        return value

    @staticmethod
    def _times(value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise FieldError(TIMES, f"{TIMES}: enter a list of times.")
        if len(value) > engine.MAX_QUERIES:
            raise FieldError(TIMES, f"{TIMES}: enter at most {engine.MAX_QUERIES} times; {len(value)} were given.")
        out = []
        for position, item in enumerate(value, 1):
            number = _finite_real(item)
            if number is None or number < 0:
                shown = item if isinstance(item, str) else _typed(item)
                raise FieldError(TIMES, f"{TIMES}: value {position} ({shown}) must be a finite number of 0 or more.")
            out.append(number)
        return out

    def cause_index(self):
        """Position of the cause drawn in the selected-cause view; the empty value means the first."""
        events = self.events
        cause = self.graph_cause
        if cause is None or cause == "":
            return 0
        if not isinstance(cause, str) or cause not in events:
            raise FieldError(GRAPH_CAUSE, f"{GRAPH_CAUSE}: {cause!r} is not one of the event codes.")
        return events.index(cause)


class Plan:
    def __init__(self, settings, dataset, work):
        self.settings, self.dataset, self.gray_work = settings, dataset, work


def check_options(frame, options):
    """Every value, role and budget that can be checked without calculating a curve; raises FieldError."""
    settings = Settings(options)
    dataset = engine.prepare(frame, settings.time, settings.status, settings.group, settings.censor, settings.events)
    if settings.graph == SELECTED:
        settings.cause_index()
    engine.check_curve_budget(dataset)
    work = engine.check_gray_budget(dataset, settings.gray == GRAY_PAIRWISE) if settings.gray != GRAY_OFF else 0
    return Plan(settings, dataset, work)


# ----- sheets ----------------------------------------------------------------------------------------------------------

def _intervals(curves, level):
    return [engine.interval(curve.incidence, curve.variance, level) for curve in curves]


def curve_table(dataset, curves, intervals):
    causes = dataset.causes
    parts = []
    for curve, (lower, upper) in zip(curves, intervals):
        steps, k = len(curve.times), len(causes)
        parts.append(pd.DataFrame({
            "Group": np.full(steps * k, curve.label, dtype=object),
            "Time": np.repeat(curve.times, k),
            "Cause": np.tile(np.array(causes, dtype=object), steps),
            "At risk": np.repeat(curve.at_risk.astype(np.int64), k),
            "Cause events": curve.events.T.reshape(-1).astype(np.int64),
            "All events": np.repeat(curve.all_events.astype(np.int64), k),
            "Censored": np.repeat(curve.censored.astype(np.int64), k),
            "Event-free": np.repeat(curve.survival, k),
            "CIF": curve.incidence.T.reshape(-1),
            "Variance": curve.variance.T.reshape(-1),
            "CI lower": lower.T.reshape(-1),
            "CI upper": upper.T.reshape(-1)}))
    return pd.concat(parts, ignore_index=True)[CURVE_COLUMNS]


def time_table(dataset, curves, queries, level):
    """One row per group, requested time (in the order given, repeats kept) and declared cause."""
    queries = np.asarray(queries, dtype=float)
    frames = []
    for curve in curves:
        per_cause = []
        for k in range(len(dataset.causes)):
            estimate, variance, beyond = engine.estimate_at(curve, k, queries)
            lower, upper = engine.interval(estimate, variance, level)
            status = np.where(beyond, TIME_BEYOND, np.where(np.isfinite(lower), TIME_OK, TIME_NO_INTERVAL))
            blank = lambda values: np.where(beyond, np.nan, values)
            per_cause.append((blank(estimate), blank(variance), blank(lower), blank(upper), status))
        steps, k = len(queries), len(dataset.causes)
        stacked = [np.stack([cause[column] for cause in per_cause], axis=1).reshape(-1) for column in range(5)]
        frames.append(pd.DataFrame({
            "Group": np.full(steps * k, curve.label, dtype=object), "Time": np.repeat(queries, k),
            "Cause": np.tile(np.array(dataset.causes, dtype=object), steps), "CIF": stacked[0],
            "Variance": stacked[1], "CI lower": stacked[2], "CI upper": stacked[3],
            "Status": stacked[4].astype(object)}))
    return pd.concat(frames, ignore_index=True)[TIME_COLUMNS]


def _gray_values(result):
    if result.available:
        return result.statistic, float(result.df), result.p, OK, ""
    return np.nan, np.nan, np.nan, UNAVAILABLE, result.reason


def gray_tables(dataset, pairwise, cancel):
    groups = len(dataset.groups)
    tracks = engine.gray_tracks(dataset) if groups > 1 else None
    everyone = list(range(groups))
    omnibus = []
    for k, cause in enumerate(dataset.causes):
        engine.check_cancel(cancel)
        omnibus.append((cause, *_gray_values(engine.gray_test(dataset, k, everyone, tracks, cancel))))
    tables = {GRAY_SHEET: pd.DataFrame(omnibus, columns=GRAY_COLUMNS)}
    if not pairwise:
        return tables
    rows = []
    for k, cause in enumerate(dataset.causes):
        results = []
        for a, b in engine.pair_sets(groups):
            engine.check_cancel(cancel)
            results.append((a, b, engine.gray_test(dataset, k, [a, b], tracks, cancel)))
        adjusted = engine.holm([result.p if result.available else None for _, _, result in results])
        for (a, b, result), adjusted_p in zip(results, adjusted):
            chi, df, p, status, reason = _gray_values(result)
            rows.append((cause, dataset.groups[a], dataset.groups[b], chi, df, p,
                         np.nan if adjusted_p is None else adjusted_p, status, reason))
    tables[PAIRWISE_SHEET] = pd.DataFrame(rows, columns=PAIR_COLUMNS)
    return tables


def settings_table(plan):
    s, d = plan.settings, plan.dataset
    rows = [
        ("Time column", s.time), ("Status column", s.status), ("Group column", s.group or "None (single series All)"),
        ("Censor code", s.censor), ("Event codes", "; ".join(s.events)),
        ("Complete cases", d.complete), ("Omitted cases", d.omitted),
        ("Groups", len(d.groups)), ("Causes", len(d.causes)),
        ("CI level (%)", s.level),
        ("CI method", f"Pointwise Wald interval of the cumulative incidence at the {s.level:g}% level, truncated to "
                      "[0, 1]. The limits are empty when the estimate is 0 or 1 or when the variance is zero or "
                      "unavailable."),
        ("Variance method", "Aalen delta-method variance with the hypergeometric tie correction of cmprsk::cuminc. "
                            "It is evaluated at the failure times of the cause and carried to the times in between; "
                            "it is zero before the first failure of the cause."),
        ("Ties convention", "Subjects tied in time form one step. The number at risk counts every subject with an "
                            "observed time of at least t, tied censorings included. Curves are right-continuous."),
        ("Gray tests", s.gray),
        ("Gray method", "Gray (1988) k-sample test of the subdistribution hazard, rho = 0, unstratified, referred to "
                        "chi-square with G − 1 df. A singular covariance, a single group or a cause without "
                        "events gives Unavailable."),
        ("Multiplicity", "Holm over the available pairwise p values, separately for each cause. Omnibus p values "
                         "are not adjusted."),
        ("Times requested", len(s.times)), ("Graph", s.graph), ("Display", s.display),
        ("Show confidence bands", "Yes" if s.bands else "No"),
        ("Not included", "Fine–Gray regression, recurrent events, delayed entry, weights and simultaneous "
                         "inference."),
    ]
    return pd.DataFrame({"Setting": [name for name, _ in rows], "Value": pd.Series([v for _, v in rows], dtype=object)})


# ----- figure ----------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _vertices(curve, cause, lower, upper):
    """Step vertices of one cause: the origin, every failure of the cause, and the end of follow-up."""
    failed = curve.events[cause] > 0
    x = np.r_[0.0, curve.times[failed]]
    y = np.r_[0.0, curve.incidence[cause][failed]]
    lo = np.r_[np.nan, lower[cause][failed]]
    hi = np.r_[np.nan, upper[cause][failed]]
    end = curve.times[-1]
    if x[-1] < end:
        x, y = np.r_[x, end], np.r_[y, y[-1]]
        lo, hi = np.r_[lo, lo[-1]], np.r_[hi, hi[-1]]
    return x, y, lo, hi


def _band(axes, x, lo, hi, color, gid, scale):
    """Shade the interval along the step; the band stops where the interval is missing."""
    valid = np.isfinite(lo) & np.isfinite(hi)
    if not valid.any():
        return None
    lo, hi, shown = lo.copy(), hi.copy(), valid.copy()
    for i in np.flatnonzero(valid[:-1] & ~valid[1:]):
        # An interval holds up to the next vertex, so that vertex closes the shaded step.
        shown[i + 1], lo[i + 1], hi[i + 1] = True, lo[i], hi[i]
    band = axes.fill_between(x, lo * scale, hi * scale, where=shown, step="post", color=color, alpha=.16,
                             linewidth=0, zorder=1)
    band.set_gid(gid)
    return band


def _draw(axes, plan, curves, intervals, group, cause, scale, color, dash, label):
    lower, upper = intervals[group]
    x, y, lo, hi = _vertices(curves[group], cause, lower, upper)
    ids = {"group": group + 1, "cause": cause + 1}
    line, = axes.plot(x, y * scale, color=color, linestyle=dash, linewidth=2.0, drawstyle="steps-post", label=label,
                      zorder=3)
    line.set_gid(GID_CURVE.format(**ids))
    if plan.settings.bands:
        _band(axes, x, lo, hi, color, GID_BAND.format(**ids), scale)
    return hi[np.isfinite(hi)].max(initial=0.0), y.max()


def _finish(axes, top, scale, time_label, ylabel, title):
    axes.set_xlim(left=0)
    axes.set_ylim(0, min(1.0, max(top, 0.05) * 1.08) * scale)
    axes.set_xlabel(time_label)
    axes.set_ylabel(ylabel)
    axes.set_title(title)
    axes.spines[["right", "top"]].set_visible(False)
    axes._tramastat_numeric_axes = ("x", "y")
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label)


def _band_handle(level):
    return Patch(facecolor="#6b7785", alpha=.25, linewidth=0, label=f"{level:g}% pointwise confidence band")


def _figure(plan, curves, intervals):
    s, d = plan.settings, plan.dataset
    groups, causes = len(d.groups), len(d.causes)
    scale = 100.0 if s.display == PERCENT else 1.0
    ylabel = "Cumulative incidence (%)" if s.display == PERCENT else "Cumulative incidence"
    time_label = str(s.time)
    colors = [PALETTE[i % len(PALETTE)] for i in range(groups)]
    shown = [s.cause_index()] if s.graph == SELECTED else list(range(causes))
    split = s.graph == ALL_CAUSES and groups * causes > SINGLE_AXES_LIMIT
    top = 0.0
    if not split:
        figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
        axes = figure.add_subplot()
        handles = []
        for cause in shown:
            dash = DASHES[cause % len(DASHES)] if s.graph == ALL_CAUSES else "-"
            for group in range(groups):
                label = d.groups[group] if s.graph == SELECTED else "_nolegend_"
                bounds = _draw(axes, plan, curves, intervals, group, cause, scale, colors[group], dash, label)
                top = max(top, *bounds)
        if s.graph == SELECTED:
            title = f"Cumulative incidence · cause {d.causes[shown[0]]}"
            if groups > 1:
                handles = [Line2D([], [], color=colors[g], linewidth=2.0, label=d.groups[g]) for g in range(groups)]
        else:
            title = "Cumulative incidence by cause"
            handles = ([Line2D([], [], color=colors[g], linewidth=2.0, label=d.groups[g]) for g in range(groups)]
                       if groups > 1 else [])
            handles += [Line2D([], [], color="#3d4852" if groups > 1 else colors[0], linewidth=2.0,
                               linestyle=DASHES[c % len(DASHES)], label=f"Cause {d.causes[c]}") for c in range(causes)]
        if s.bands:
            handles.append(_band_handle(s.level))
        _finish(axes, top, scale, time_label, ylabel, title)
        if handles:
            _plain(*axes.legend(handles=handles, frameon=False, loc="upper left").get_texts())
        return figure
    columns = 3 if causes > 4 else 2 if causes > 1 else 1
    rows = -(-causes // columns)
    figure = Figure(figsize=(4.4 * columns + 1.8, 3.3 * rows + .6), dpi=100, layout="constrained")
    panels = figure.subplots(rows, columns, sharex=True, sharey=True, squeeze=False)
    for cause in range(causes):
        axes = panels[cause // columns][cause % columns]
        for group in range(groups):
            bounds = _draw(axes, plan, curves, intervals, group, cause, scale, colors[group],
                           DASHES[cause % len(DASHES)], "_nolegend_")
            top = max(top, *bounds)
    for cause in range(causes):
        axes = panels[cause // columns][cause % columns]
        _finish(axes, top, scale, time_label if cause // columns == rows - 1 else "",
                ylabel if cause % columns == 0 else "", f"Cause {d.causes[cause]}")
    for index in range(causes, rows * columns):
        panels[index // columns][index % columns].set_axis_off()
    handles = [Line2D([], [], color=colors[g], linewidth=2.0, label=d.groups[g]) for g in range(groups)]
    if s.bands:
        handles.append(_band_handle(s.level))
    legend = figure.legend(handles=handles, loc="outside right center", frameon=False, title="Group")
    _plain(legend.get_title(), *legend.get_texts())
    return figure


# ----- analysis --------------------------------------------------------------------------------------------------------

def competing_risks(frame, options, *, cancel=None):
    plan = check_options(frame, options)
    settings, dataset = plan.settings, plan.dataset
    curves = engine.cumulative_incidence(dataset, cancel)
    intervals = _intervals(curves, settings.level)
    tables = {CURVES_SHEET: curve_table(dataset, curves, intervals)}
    if settings.times:
        tables[TIMES_SHEET] = time_table(dataset, curves, settings.times, settings.level)
    if settings.gray != GRAY_OFF:
        tables.update(gray_tables(dataset, settings.gray == GRAY_PAIRWISE, cancel))
    engine.check_cancel(cancel)
    tables[SETTINGS_SHEET] = settings_table(plan)
    return Result(tables, _figure(plan, curves, intervals))
