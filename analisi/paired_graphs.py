"""Before/after graphs of paired columns and subject trajectories over a shared X.

Before/after
    A pair is a Before column, an After column and an optional title. Values
    are matched by source row. A segment joins a Before and an After of the
    same row only when both are numbers that are neither missing nor
    excluded. A Subject column only labels the rows; it never matches them.
    Pair k (counted from 0) has Before at 3k + 1 and After at 3k + 2, so one
    empty position separates neighbouring pairs.

Subject trajectories
    One trace per subject, either one Y column per subject (Separate columns)
    or one replicate subcolumn per subject (Replicate subcolumns, one colour
    per data set). Rows are taken in source order and duplicate X values stay
    distinct rows. A missing or excluded X breaks every trace on that row; a
    missing or excluded Y breaks that trace only. The optional group mean is
    the mean of the group's Y values on each source row; a row with no value
    in the group breaks the mean line.
"""
from math import ceil

from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from .category_graphs import COLORS, MAX_POINTS, _REPLICATE, _title
from .data import _worksheet_roles
from .i18n import active_language, tr, ui
from .presentation import GraphGroup, register_groups
from .processing import FieldError, _column
from .reporting import Result, _plot, _report
from .stats import ci_columns


TTEST_ESTIMATION = "Show estimation plot"


def shows_paired_estimation(method, options):
    return method == "t-test" and options.get("Design") == "Paired" and options.get(TTEST_ESTIMATION) is True


def paired_estimation_figure(first, second, summary, response, *, level=95.):
    """Plot the complete pairs and the interval calculated by the same test."""
    first, second = first.to_numpy(dtype=float), second.to_numpy(dtype=float)
    figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
    values, effects = figure.subplots(1, 2, width_ratios=(3, 2))
    pairs = np.stack((np.column_stack((np.zeros(len(second)), second)),
                      np.column_stack((np.ones(len(first)), first))), axis=1)
    values.add_collection(LineCollection(pairs, colors="#a8b7c0", linewidths=.7, alpha=.65))
    values.scatter(np.zeros(len(second)), second, color="#2866ae", s=24, zorder=3)
    values.scatter(np.ones(len(first)), first, color="#087f76", s=24, zorder=3)
    reference, treatment = str(summary["Second / null"]), str(summary["First"])
    values.set_xticks([0., 1.], [reference, treatment], parse_math=False)
    values.set_xlim(-.35, 1.35)
    values.set_ylabel(response or tr("ttest.plot.measurements"), parse_math=False)
    values.set_title(tr("ttest.plot.pairs"))
    effects.axhline(0, color="#81929b", linewidth=1, linestyle="--")
    effects.scatter(np.zeros(len(first)), first - second, color="#2866ae", alpha=.55, s=22)
    estimate = summary["Difference"]
    low, high = (summary[key] for key in ci_columns(level))
    interval = effects.vlines(1., low, high, color="#087f76", linewidth=1.5)
    interval.set_gid("paired-mean-confidence-interval")
    effects.hlines([low, high], .94, 1.06, color="#087f76", linewidth=1.5)
    effects.scatter([1.], [estimate], color="#087f76", s=32, zorder=3)
    effects.set_xlim(-.45, 1.45)
    percent = repr(float(level)).removesuffix(".0")
    if active_language() == "it":
        percent = percent.replace(".", ",")
    caption = tr("ttest.ci.caption", level=percent)
    effects.set_xticks([0., 1.], [tr("ttest.plot.differences"), caption])
    effects.set_ylabel(f"{treatment} − {reference}", parse_math=False)
    effects.set_title(tr("ttest.plot.effect"))
    for axes in (values, effects):
        axes.spines[["right", "top"]].set_visible(False)
    return figure

BEFORE_AFTER = "Before/after"
TRAJECTORIES = "Subject trajectories"

# Dialog kind of the ordered list of Before/After pairs.
PAIR_LIST = "Before/after pair list"
PAIRS = "Pairs"
BEFORE, AFTER, TITLE = "Before", "After", "Title"
VERTICAL, HORIZONTAL = ORIENTATIONS = ("Vertical", "Horizontal")
SHOW_UNPAIRED = "Show unpaired observations"
MAX_PAIRS = 12
COMPLETE, BEFORE_ONLY, AFTER_ONLY = "Complete", "Incomplete: before only", "Incomplete: after only"
BEFORE_AFTER_OPTIONS = {PAIRS: PAIR_LIST, "Subject": "Optional", "Orientation": ORIENTATIONS, SHOW_UNPAIRED: False}

SEPARATE, REPLICATES = INPUT_MODES = ("Separate columns", "Replicate subcolumns")
LINE, LINE_POINTS = TRACE_STYLES = ("Line", "Line and points")
SHOW_MEAN = "Show group mean"
MAX_TRACES = 200
MAX_LEGEND = 24
ALL_SUBJECTS = "All subjects"
TRAJECTORY_OPTIONS = {"Input": INPUT_MODES, "X": None, "Y columns": "Multiple", "Style": TRACE_STYLES,
                      SHOW_MEAN: False}


def _flag(options, name):
    value = options.get(name, False)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _unique_columns(frame, field):
    if not frame.columns.is_unique:
        raise FieldError(field, "Worksheet column names must be unique.")


# ----- Before/after -------------------------------------------------------------------------------------------------

def pair_label(pair):
    return pair.get(TITLE) or f"{pair[BEFORE]} → {pair[AFTER]}"


def check_pairs(frame, pairs):
    """Return the pairs as plain records, or raise a field error that names the faulty pair."""
    if not isinstance(pairs, (list, tuple)) or not pairs:
        raise FieldError(PAIRS, "Add at least one pair: choose a Before column and an After column, then click Add.")
    if len(pairs) > MAX_PAIRS:
        raise FieldError(PAIRS, f"Plot up to {MAX_PAIRS} pairs at once.")
    checked, seen = [], {}
    for number, pair in enumerate(pairs, 1):
        if not isinstance(pair, dict) or not isinstance(pair.get(BEFORE), str) or not isinstance(pair.get(AFTER), str):
            raise FieldError(PAIRS, f"Pair {number} is not a valid Before/After pair. Remove it and add it again.")
        before, after = pair[BEFORE], pair[AFTER]
        title = pair.get(TITLE, "")
        if not isinstance(title, str):
            raise FieldError(PAIRS, f"Pair {number}: the title must be text.")
        for name in (before, after):
            if name not in frame:
                raise FieldError(PAIRS, f'Pair {number}: column "{name}" is not in this worksheet. Remove the pair.')
        if before == after:
            raise FieldError(PAIRS, f"Pair {number}: choose two different columns for Before and After.")
        key = frozenset((before, after))
        if key in seen:
            raise FieldError(PAIRS, f"Pair {number} repeats pair {seen[key]} ({before} and {after}). Remove one of them.")
        seen[key] = number
        checked.append({BEFORE: before, AFTER: after, TITLE: title.strip()})
    return checked


def _row_labels(frame, subject):
    if subject is None:
        return None
    if not isinstance(subject, str) or subject not in frame:
        raise FieldError("Subject", "Choose an existing column for the subject labels, or leave Subject empty.")
    labels = frame[subject]
    return [str(value) if pd.notna(value) else "" for value in labels]


def before_after(frame, options):
    _unique_columns(frame, PAIRS)
    pairs = check_pairs(frame, options.get(PAIRS))
    orientation = _choice(options, "Orientation", ORIENTATIONS)
    unpaired = _flag(options, SHOW_UNPAIRED)
    subject = options.get("Subject") or None
    subjects = _row_labels(frame, subject)
    if len(frame) * len(pairs) * 2 > MAX_POINTS:
        raise FieldError(PAIRS, "Select fewer rows or pairs to draw this graph.")
    vertical = orientation == VERTICAL
    figure, axes = _plot(BEFORE_AFTER, "" if vertical else "Value", "Value" if vertical else "")

    def xy(position, values):
        position = np.full(len(values), position, dtype=float)
        return (position, values) if vertical else (values, position)

    rows, summaries, groups, ticks, tick_labels = [], [], [], [], []
    any_complete = False
    for index, pair in enumerate(pairs):
        label = pair_label(pair)
        color = COLORS[index % len(COLORS)]
        before = _column(frame, pair[BEFORE], PAIRS).to_numpy(dtype=float)
        after = _column(frame, pair[AFTER], PAIRS).to_numpy(dtype=float)
        has_before, has_after = np.isfinite(before), np.isfinite(after)
        complete = has_before & has_after
        before_only, after_only = has_before & ~has_after, has_after & ~has_before
        any_complete |= bool(complete.any())
        left, right = 3. * index + 1, 3. * index + 2
        ticks += [left, right]
        tick_labels += [pair[BEFORE], pair[AFTER]]
        artists = []
        segments = [((left, b), (right, a)) if vertical else ((b, left), (a, right))
                    for b, a in zip(before[complete], after[complete])]
        lines = LineCollection(segments, colors=color, linewidths=1.4, zorder=2)
        lines.set_gid(f"before-after:{index + 1}")
        axes.add_collection(lines)
        artists.append((lines, "line"))
        for position, values in ((left, before[complete]), (right, after[complete])):
            artists.append((axes.scatter(*xy(position, values), s=26, color=color, edgecolors="white",
                                         linewidths=.6, zorder=3), "point"))
        if unpaired:
            for position, values in ((left, before[before_only]), (right, after[after_only])):
                if len(values):
                    # Hollow markers keep isolated values distinct from the ends of a segment.
                    artists.append((axes.scatter(*xy(position, values), s=30, facecolors="white", edgecolors=color,
                                                 linewidths=1.3, zorder=3), "mean"))
        groups.append(GraphGroup(f"pair:{index + 1}:{pair[BEFORE]}→{pair[AFTER]}", label, "pair",
                                 (left + right) / 2, artists))
        change = after - before
        for row in np.flatnonzero(has_before | has_after):
            status = COMPLETE if complete[row] else BEFORE_ONLY if has_before[row] else AFTER_ONLY
            record = {"Pair": label, "Source row": int(row) + 1}
            if subjects is not None:
                record["Subject"] = subjects[row]
            record.update({"Before": before[row] if has_before[row] else np.nan,
                           "After": after[row] if has_after[row] else np.nan,
                           "Change": change[row] if complete[row] else np.nan,
                           "Status": status, "Plotted": "Yes" if complete[row] or unpaired else "No"})
            rows.append(record)
        changes = change[complete]
        with np.errstate(over="ignore", invalid="ignore"):
            mean = float(np.mean(changes)) if len(changes) else np.nan
            median = float(np.median(changes)) if len(changes) else np.nan
        summaries.append({"Pair": label, "Before column": pair[BEFORE], "After column": pair[AFTER],
                          "Complete pairs": int(complete.sum()), "Before only": int(before_only.sum()),
                          "After only": int(after_only.sum()), "Mean change": mean, "Median change": median,
                          "Before position": left, "After position": right})
    if not any_complete:
        raise FieldError(PAIRS, "No row has both a Before and an After value. Check the pairs and the excluded cells.")
    for summary in summaries:
        if not np.isfinite([summary["Mean change"], summary["Median change"]]).all() and summary["Complete pairs"]:
            raise FieldError(PAIRS, "The selected values exceed the numeric range for this graph.")
    span = (.4, 3. * len(pairs) - .4)
    if vertical:
        axes.set_xticks(ticks, tick_labels, rotation=20 if len(pairs) > 3 else 0)
        axes.set_xlim(*span)
        labels = axes.get_xticklabels()
    else:
        axes.set_yticks(ticks, tick_labels)
        axes.set_ylim(span[1], span[0])
        labels = axes.get_yticklabels()
    for text in labels:
        text.set_parse_math(False)
    titled = [(3. * index + 1.5, pair[TITLE]) for index, pair in enumerate(pairs) if pair[TITLE]]
    if titled:
        # Pair titles sit on the opposite side of the column names, centred on each pair.
        secondary = axes.secondary_xaxis("top") if vertical else axes.secondary_yaxis("right")
        middles, names = zip(*titled)
        if vertical:
            secondary.set_xticks(middles, names)
            title_labels = secondary.get_xticklabels()
        else:
            secondary.set_yticks(middles, names)
            title_labels = secondary.get_yticklabels()
        secondary.tick_params(length=0)
        secondary.spines[:].set_visible(False)
        for text in title_labels:
            text.set(parse_math=False, fontweight="bold")
    axes.autoscale_view()
    register_groups(axes, [group for group in groups if len(group.key) <= 1024])
    columns = ["Pair", "Source row", *(["Subject"] if subjects is not None else []),
               "Before", "After", "Change", "Status", "Plotted"]
    settings = {"Orientation": orientation, "Show unpaired observations": "On" if unpaired else "Off",
                "Pairing": "By source row. A segment needs a Before and an After that are neither missing nor excluded.",
                "Change": "After − Before, complete rows only.",
                "Positions": "Pair k (from 1): Before at 3k − 2, After at 3k − 1."}
    if subject is not None:
        settings["Subject labels"] = f"{subject} (labels only, not used for matching)"
    return Result({"Pairs": pd.DataFrame(rows, columns=columns), "Pair summary": pd.DataFrame(summaries),
                   "Settings": _report(settings)}, figure)


# ----- Subject trajectories -----------------------------------------------------------------------------------------

def _subject_groups(frame, names, mode):
    """Return [(group, [subject columns])] in worksheet order."""
    if mode == SEPARATE:
        return [(ALL_SUBJECTS, list(names))]
    chosen = set(names)
    roles = _worksheet_roles(frame)
    known = {}
    if roles:
        for group in roles["y"]:
            members = [name for name in group if name in chosen]
            if members:
                known[_title(group[0]) if len(group) > 1 else group[0]] = members
    placed = {name for members in known.values() for name in members}
    parsed = set()
    ambiguous = {match[1] for name in frame.columns if (match := _REPLICATE.fullmatch(str(name))) and match[2]}
    for name in names:
        if name in placed:
            continue
        match = _REPLICATE.fullmatch(name)
        if not match:
            raise FieldError("Y columns", f'"{name}" is not a replicate subcolumn, so its data set is unknown. '
                                          'Select subcolumns named like "Cohort A [1]", or set Input to Separate columns.')
        if match[1] in ambiguous:
            raise FieldError("Y columns", f'The data set of "{name}" is ambiguous because several data sets are '
                                          f'named "{match[1]}". Select the subcolumns of one data set, or rename them.')
        label = _title(name)
        while label in known and label not in parsed:
            label += " (data set)"
        parsed.add(label)
        known.setdefault(label, []).append(name)
    order = {name: index for index, name in enumerate(frame.columns)}
    return sorted(((label, sorted(members, key=order.get)) for label, members in known.items()),
                  key=lambda item: order[item[1][0]])


def _legend(axes, handles, labels):
    if not handles or len(handles) > MAX_LEGEND:
        return None
    legend = axes.legend(handles, labels, fontsize="small", frameon=False, ncol=ceil(len(handles) / 8),
                         loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    for text in legend.get_texts():
        text.set_parse_math(False)
    return legend


def subject_trajectories(frame, options):
    mode = _choice(options, "Input", INPUT_MODES)
    style = _choice(options, "Style", TRACE_STYLES)
    show_mean = _flag(options, SHOW_MEAN)
    _unique_columns(frame, "Y columns")
    x_name = options.get("X")
    x = _column(frame, x_name, "X").to_numpy(dtype=float)
    names = options.get("Y columns")
    if (not isinstance(names, (list, tuple)) or not names
            or any(not isinstance(name, str) or name not in frame for name in names)):
        raise FieldError("Y columns", "Select at least one Y column, one per subject.")
    if len(set(names)) != len(names):
        raise FieldError("Y columns", "Select each subject column once.")
    if x_name in names:
        raise FieldError("Y columns", f'"{x_name}" is the X column. Deselect it from the Y columns.')
    if len(names) > MAX_TRACES:
        raise FieldError("Y columns", f"Plot up to {MAX_TRACES} subjects at once. Deselect some Y columns.")
    if len(names) * len(frame) > MAX_POINTS:
        raise FieldError("Y columns", "Select fewer subjects or rows to draw this graph.")
    groups = _subject_groups(frame, names, mode)
    usable_x = np.isfinite(x)
    if not usable_x.any():
        raise FieldError("X", f'"{x_name}" has no usable X values.')
    figure, axes = _plot(TRAJECTORIES, x_name, "Y")
    marker = "o" if style == LINE_POINTS else "None"
    width, alpha = (1.1, .55) if show_mean else (1.5, .95)
    values, means, inspector = [], [], []
    handles, labels = [], []
    plotted = 0
    subject_index = 0
    for group_index, (group, members) in enumerate(groups):
        separate = mode == SEPARATE
        group_artists = []
        stack = []
        for name in members:
            y = _column(frame, name, "Y columns").to_numpy(dtype=float)
            # A missing X breaks every trace on its row; a missing Y breaks only this trace.
            y = np.where(usable_x, y, np.nan)
            stack.append(y)
            color = COLORS[(subject_index if separate else group_index) % len(COLORS)]
            subject_index += 1
            line, = axes.plot(x, y, color=color, linewidth=width, alpha=alpha, marker=marker, markersize=4,
                              zorder=2)
            line.set_gid(f"trajectory:{name}")
            ok = np.isfinite(y)
            plotted += int(ok.sum())
            rows = np.flatnonzero(ok)
            values.append(pd.DataFrame({"Source row": rows + 1, "Subject": name, "Group": group,
                                        "X": x[rows], "Y": y[rows]}))
            if separate:
                inspector.append(GraphGroup(f"trajectory:subject:{name}", name, "trace", float(subject_index),
                                            [(line, "line")]))
                handles.append(line)
                labels.append(name)
            else:
                group_artists.append((line, "line"))
        if show_mean:
            block = np.vstack(stack)
            counts = np.isfinite(block).sum(axis=0)
            with np.errstate(over="ignore", invalid="ignore"):
                totals = np.nansum(block, axis=0)
                mean = np.where(counts > 0, totals / np.maximum(counts, 1), np.nan)
            if not np.isfinite(mean[counts > 0]).all():
                raise FieldError("Y columns", "The selected values exceed the numeric range for this graph.")
            color = "#1f2933" if separate else COLORS[group_index % len(COLORS)]
            mean_line, = axes.plot(x, mean, color=color, linewidth=3.2, solid_capstyle="round", zorder=4,
                                   marker="D" if style == LINE_POINTS else "None", markersize=5)
            mean_line.set_gid(f"trajectory-mean:{group}")
            rows = np.flatnonzero(usable_x)
            means.append(pd.DataFrame({"Source row": rows + 1, "X": x[rows], "Group": group,
                                       "N": counts[rows].astype(int), "Mean": mean[rows]}))
            if separate:
                inspector.append(GraphGroup(f"trajectory-mean:{group}", f"{group} (mean)", "mean",
                                            float(subject_index + 1), [(mean_line, "line")]))
                handles.append(mean_line)
                labels.append("Mean")
            else:
                group_artists.append((mean_line, "line"))
        if not separate:
            inspector.append(GraphGroup(f"trajectory:group:{group}", group, "data set", float(group_index + 1),
                                        group_artists))
            handles.append(Line2D([], [], color=COLORS[group_index % len(COLORS)], linewidth=2))
            labels.append(f"{group} (n = {len(members)})")
    if not plotted:
        raise FieldError("Y columns", "The selected Y columns have no values on rows with a usable X.")
    legend = _legend(axes, handles, labels)
    if legend is not None:
        # The legend keys follow the colors chosen in the Inspector.
        for group, handle in zip(inspector, legend.legend_handles, strict=True):
            group.artists.append((handle, "line"))
    register_groups(axes, [group for group in inspector if len(group.key) <= 1024])
    settings = {"Input": mode, "Style": style, "Show group mean": "On" if show_mean else "Off",
                "Row order": "Source order. Rows with the same X stay separate.",
                "Breaks": "A missing or excluded X breaks every trace on that row; "
                          "a missing or excluded Y breaks that trace only.",
                "Trace limit": MAX_TRACES}
    if show_mean:
        settings["Group mean"] = "Mean of the group's values on each source row; a row without values breaks the line."
    if legend is None and handles:
        settings["Legend"] = f"Not drawn: more than {MAX_LEGEND} entries."
    tables = {"Subject values": pd.concat(values, ignore_index=True)}
    if means:
        tables["Group means"] = pd.concat(means, ignore_index=True)
    tables["Settings"] = _report(settings)
    return Result(tables, figure)


def trajectory_defaults(frame):
    """Dialog defaults: X from the worksheet roles or the first numeric column, every other numeric column as Y."""
    roles = _worksheet_roles(frame)
    numeric = [name for name in frame.columns if pd.api.types.is_numeric_dtype(frame[name])]
    x = roles["x"][0] if roles and roles["x"] else (numeric[0] if numeric else None)
    if x is None:
        return {}
    ys = [name for name in numeric if name != x]
    replicates = (any(len(group) > 1 for group in roles["y"]) if roles
                  else any(_REPLICATE.fullmatch(str(name)) for name in ys))
    return {"Input": REPLICATES if replicates else SEPARATE, "X": x, "Y columns": ys[:MAX_TRACES]}
