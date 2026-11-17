"""Forest plot from precomputed estimates and interval limits.

Each study supplies an estimate and the absolute lower and upper limits of its
interval. Nothing is pooled or recomputed: the graph draws the values entered,
on a log scale for ratios or a linear scale for differences.
"""
import re

from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator
import numpy as np
import pandas as pd

from .category_graphs import COLORS
from .processing import FieldError
from .reporting import Result, _plot, _report


FOREST_PLOT = "Forest plot"
BY_ROW, BY_COLUMN = INPUT_MODES = ("One study per row", "One study per column")
RATIO, DIFFERENCE = MEASURES = ("Ratio", "Difference")
LOG10, LINEAR = SCALES = ("Log10", "Linear")
ROW_CHOICE = "Row choice"
ROLE_ROWS = ("Estimate row", "Lower row", "Upper row")
LIMITS = ("Estimate", "Lower limit", "Upper limit")
OPTIONS = {
    "Input": INPUT_MODES, "Study": "Optional", "Estimate": None, "Lower limit": None, "Upper limit": None,
    "Weight": "Optional", "Study columns": "Multiple (optional)", "Row titles": "Optional",
    "Estimate row": ROW_CHOICE, "Lower row": ROW_CHOICE, "Upper row": ROW_CHOICE,
    "Measure": MEASURES, "Scale": SCALES, "Reference": 1.0, "Show reference": True,
}
DEFAULT_SCALE = {RATIO: LOG10, DIFFERENCE: LINEAR}
DEFAULT_REFERENCE = {RATIO: 1.0, DIFFERENCE: 0.0}
MAX_STUDIES = 200
MARKER_AREA = 46.
MAX_WEIGHT_AREA = 260.
LIMITS_NOTE = ("Lower and upper limits are absolute interval endpoints on the measure scale, "
               "not distances from the estimate.")
REFERENCE_NOTE = "The reference line marks no effect: 1 for ratios, 0 for differences."
_ROLE_WORDS = {"Lower row": ("lower", "low", "lcl", "ll"), "Upper row": ("upper", "high", "ucl", "ul"),
               "Estimate row": ("estimate", "point", "ratio", "risk", "odds", "difference", "mean", "effect")}


def visibility(input_mode):
    """Fields that apply to the chosen input layout."""
    rows = input_mode != BY_COLUMN
    return {"Study": rows, "Estimate": rows, "Lower limit": rows, "Upper limit": rows, "Weight": rows,
            "Study columns": not rows, **dict.fromkeys(ROLE_ROWS, not rows)}


def defaults_for(measure):
    """Scale and reference line that suit a measure."""
    return DEFAULT_SCALE.get(measure, LOG10), DEFAULT_REFERENCE.get(measure, 1.0)


def _choice(options, name, choices, default=None):
    value = options.get(name, default if default is not None else choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def row_title_column(frame, options):
    """The chosen row title column, or a leading column named like one."""
    name = options.get("Row titles") or None
    if name is None and len(frame.columns):
        first = frame.columns[0]
        if isinstance(first, str) and first.strip().casefold() in {"row title", "row titles", "role", "roles"}:
            name = first
    if name is not None and name not in frame:
        raise FieldError("Row titles", "Choose an existing row title column.")
    return name


def _text(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).strip()


def row_choices(frame, options):
    """Label each worksheet row with its 1-based position and title, as stored in saved recipes."""
    titles = row_title_column(frame, options)
    labels = []
    for position in range(len(frame)):
        title = _text(frame[titles].iloc[position]) if titles else ""
        labels.append(f"{position + 1} · {title}" if title else f"{position + 1}")
    return labels


def guess_role_rows(frame, options):
    """Suggest role rows from row titles. Numbers are never sorted to guess a role."""
    labels = row_choices(frame, options)
    titles = row_title_column(frame, options)
    if not titles or len(labels) < 3:
        return dict(zip(ROLE_ROWS, labels[:3]))
    found = {}
    for role in ("Lower row", "Upper row", "Estimate row"):
        for position, label in enumerate(labels):
            words = re.findall(r"[a-z]+", _text(frame[titles].iloc[position]).casefold())
            if label not in found.values() and any(word in _ROLE_WORDS[role] for word in words):
                found[role] = label
                break
    if len(found) == 2 and "Estimate row" not in found:
        rest = [label for label in labels[:3] if label not in found.values()]
        if len(rest) == 1:
            found["Estimate row"] = rest[0]
    if len(found) != 3:
        return dict(zip(ROLE_ROWS, labels[:3]))
    return {role: found[role] for role in ROLE_ROWS}


def _row_position(value, field, count):
    """Accept a saved row label such as '2 · Estimate', 'Row 2' or the number 2."""
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(field, f"{field}: choose a worksheet row.")
    if isinstance(value, (int, np.integer)):
        position = int(value)
    else:
        match = re.match(r"\s*(?:row\s+)?(\d+)\b", str(value or ""), flags=re.IGNORECASE)
        if not match:
            raise FieldError(field, f"{field}: choose a worksheet row.")
        position = int(match.group(1))
    if not 1 <= position <= count:
        raise FieldError(field, f"{field}: row {position} is not in the worksheet.")
    return position - 1


def _number(raw, study, field):
    """Return a finite float, NaN for a blank cell, or raise a FieldError naming the study."""
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return np.nan
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return np.nan
        try:
            value = float(text.replace(",", ".") if text.count(",") == 1 and "." not in text else text)
        except ValueError:
            raise FieldError(field, f'{field}: study "{study}" has a value that is not a number ({raw!r}).') from None
    elif isinstance(raw, (bool, np.bool_)) or not isinstance(raw, (int, float, np.integer, np.floating)):
        raise FieldError(field, f'{field}: study "{study}" has a value that is not a number ({raw!r}).')
    else:
        value = float(raw)
    if not np.isfinite(value):
        raise FieldError(field, f'{field}: study "{study}" has a value that is not finite.')
    return value


def _distinct_columns(frame, options, fields):
    chosen = {}
    for field in fields:
        name = options.get(field)
        if not name or name not in frame:
            raise FieldError(field, f"Choose a column for {field}.")
        if name in chosen.values():
            raise FieldError(field, f"{field}: choose a column not already used for another role.")
        chosen[field] = name
    return chosen


def _studies_by_row(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("Estimate", "Worksheet column names must be unique.")
    columns = _distinct_columns(frame, options, LIMITS)
    study = options.get("Study") or None
    if study is not None and study not in frame:
        raise FieldError("Study", "Choose an existing study column.")
    if study in columns.values():
        raise FieldError("Study", "Choose a study column different from the estimate and limits.")
    weight = options.get("Weight") or None
    if weight is not None and (weight not in frame or weight in columns.values() or weight == study):
        raise FieldError("Weight", "Choose a numeric weight column different from the other roles.")
    titles = row_title_column(frame, options)
    if titles in columns.values() or titles == study:
        titles = None
    studies, incomplete = [], []
    for position in range(len(frame)):
        name = _text(frame[study].iloc[position]) if study else ""
        if not name and titles:
            name = _text(frame[titles].iloc[position])
        name = name or f"Row {position + 1}"
        values = [_number(frame[columns[field]].iloc[position], name, field) for field in LIMITS]
        size = _number(frame[weight].iloc[position], name, "Weight") if weight else 1.
        if np.isnan(values).all() and (not weight or np.isnan(size)) and not _text(
                frame[study].iloc[position] if study else None):
            continue
        if np.isnan(values).any() or np.isnan(size):
            incomplete.append(name)
            continue
        if weight and size <= 0:
            raise FieldError("Weight", f'Weight: study "{name}" needs a weight greater than zero.')
        studies.append({"Study": name, "Source row": position + 1, "Estimate": values[0],
                        "Lower": values[1], "Upper": values[2], "Weight": size})
    return studies, incomplete, weight


def _studies_by_column(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("Study columns", "Worksheet column names must be unique.")
    names = options.get("Study columns", [])
    if (not isinstance(names, (list, tuple)) or not names
            or any(not isinstance(name, str) or name not in frame for name in names)
            or len(set(names)) != len(names)):
        raise FieldError("Study columns", "Choose distinct study columns, one study per column.")
    titles = row_title_column(frame, options)
    if titles in names:
        raise FieldError("Study columns", "The row title column cannot also be a study column.")
    positions = {}
    for field in ROLE_ROWS:
        position = _row_position(options.get(field), field, len(frame))
        if position in positions.values():
            raise FieldError(field, f"{field}: each role needs a different worksheet row.")
        positions[field] = position
    studies, incomplete = [], []
    for name in names:  # The selection order is the plotting order.
        values = [_number(frame[name].iloc[positions[role]], name, label)
                  for role, label in zip(ROLE_ROWS, LIMITS, strict=True)]
        if np.isnan(values).any():
            incomplete.append(str(name))
            continue
        studies.append({"Study": str(name), "Source column": name, "Estimate": values[0],
                        "Lower": values[1], "Upper": values[2], "Weight": 1.})
    return studies, incomplete, None


def _check(studies, scale, field_for):
    for study in studies:
        name = study["Study"]
        if not study["Lower"] <= study["Estimate"] <= study["Upper"]:
            field = field_for["Lower limit"] if study["Lower"] > study["Estimate"] else field_for["Upper limit"]
            raise FieldError(field, f'{field}: study "{name}" needs lower ≤ estimate ≤ upper '
                                    f'({study["Lower"]:g}, {study["Estimate"]:g}, {study["Upper"]:g}).')
        if scale == LOG10:
            for key, label in (("Lower", "Lower limit"), ("Estimate", "Estimate"), ("Upper", "Upper limit")):
                if study[key] <= 0:
                    field = field_for[label]
                    raise FieldError(field, f'{field}: study "{name}" has {label.lower()} {study[key]:g}; '
                                            "a log scale needs values greater than zero.")


def forest_plot(frame, options):
    mode = _choice(options, "Input", INPUT_MODES)
    measure = _choice(options, "Measure", MEASURES)
    scale_default, reference_default = defaults_for(measure)
    scale = _choice(options, "Scale", SCALES, scale_default)
    show_reference = _flag(options, "Show reference", True)
    reference = options.get("Reference", reference_default)
    if isinstance(reference, (bool, np.bool_)) or not isinstance(reference, (int, float, np.integer, np.floating)):
        raise FieldError("Reference", "The reference must be a number.")
    reference = float(reference)
    if show_reference and not np.isfinite(reference):
        raise FieldError("Reference", "The reference must be finite.")
    if mode == BY_ROW:
        studies, incomplete, weight = _studies_by_row(frame, options)
        field_for = {label: label for label in LIMITS}
    else:
        studies, incomplete, weight = _studies_by_column(frame, options)
        field_for = dict(zip(LIMITS, ROLE_ROWS, strict=True))
    first_field = "Estimate" if mode == BY_ROW else "Study columns"
    if not studies:
        raise FieldError(first_field, "No study has an estimate with both limits.")
    if len(studies) > MAX_STUDIES:
        raise FieldError(first_field, f"Plot up to {MAX_STUDIES} studies at once.")
    _check(studies, scale, field_for)
    if show_reference and scale == LOG10 and reference <= 0:
        raise FieldError("Reference", "On a log scale the reference must be greater than zero.")

    count = len(studies)
    estimate = np.array([s["Estimate"] for s in studies])
    lower = np.array([s["Lower"] for s in studies])
    upper = np.array([s["Upper"] for s in studies])
    y = np.arange(count, dtype=float)
    color = COLORS[0]
    figure, axes = _plot(FOREST_PLOT, f"{measure} ({'log10 scale' if scale == LOG10 else 'linear scale'})", "")
    figure.set_size_inches(8, max(3., 1.6 + .42 * count))
    # Interval segments and caps use the entered limits directly; the axis applies the scale once.
    intervals = axes.hlines(y, lower, upper, color=color, linewidth=1.6, zorder=2, label="_intervals")
    caps = [axes.plot(values, y, linestyle="none", marker="|", markersize=11, markeredgewidth=1.6,
                      color=color, zorder=2, label="_caps")[0] for values in (lower, upper)]
    if weight:
        weights = np.array([s["Weight"] for s in studies])
        sizes = MAX_WEIGHT_AREA * weights / weights.max()
        point_label = f"Estimate (marker area ∝ {weight})"
    else:
        sizes = np.full(count, MARKER_AREA)
        point_label = "Estimate"
    points = axes.scatter(estimate, y, s=sizes, marker="s", color=color, edgecolors="white", linewidths=.6,
                          zorder=3, label=point_label)
    if show_reference:
        axes.axvline(reference, color="#5f6b76", linestyle="--", linewidth=1.1, zorder=1,
                     label=f"Reference ({reference:g})")
    if scale == LOG10:
        axes.set_xscale("log", base=10)
        axes.xaxis.set_major_locator(LogLocator(base=10, subs=(1., 2., 5.)))
        axes.xaxis.set_minor_locator(NullLocator())
        axes.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axes.set_yticks(y, [s["Study"] for s in studies])
    for label in axes.get_yticklabels():
        label.set_parse_math(False)
    axes.set_ylim(count - .5, -.5)  # First study on top.
    axes.spines["left"].set_visible(False)
    axes.tick_params(axis="y", length=0)
    low = min(lower.min(), reference) if show_reference else lower.min()
    high = max(upper.max(), reference) if show_reference else upper.max()
    if scale == LOG10:
        pad = (np.log10(high) - np.log10(low)) * .08 or .3
        axes.set_xlim(10 ** (np.log10(low) - pad), 10 ** (np.log10(high) + pad))
    else:
        pad = (high - low) * .08 or max(abs(high), 1.) * .1
        axes.set_xlim(low - pad, high + pad)
    if weight or show_reference:
        axes.legend(loc="best", frameon=False, fontsize=9)
    axes._tramastat_forest = {"intervals": intervals, "caps": caps, "points": points}

    source = "Source row" if mode == BY_ROW else "Source column"
    values = pd.DataFrame({"Study": [s["Study"] for s in studies], source: [s[source] for s in studies],
                           "Estimate": estimate, "Lower": lower, "Upper": upper})
    if weight:
        values["Weight"] = [s["Weight"] for s in studies]
    summary = {"Studies drawn": count, "Incomplete or excluded (omitted)": len(incomplete),
               "Measure": measure, "Scale": scale,
               "Reference line": f"{reference:g}" if show_reference else "Hidden",
               "Input": mode, "Limits": LIMITS_NOTE}
    if weight:
        summary["Marker size"] = f"Area proportional to {weight}; estimates, limits and order are unchanged."
    else:
        summary["Marker size"] = "Constant."
    if incomplete:
        summary["Omitted studies"] = ", ".join(incomplete)
    summary["Pooling"] = "None: the graph shows the entered intervals; no studies are combined."
    return Result({"Forest values": values, "Summary": _report(summary)}, figure)
