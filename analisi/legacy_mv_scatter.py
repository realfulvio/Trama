"""Restore compatible categorical scatter graphs from ZIP project metadata."""
import math
from numbers import Real
import re

import numpy as np
import pandas as pd
from matplotlib.ticker import FixedLocator

from .analysis_chain import RESULT_CONTEXT
from .hierarchical_workbench import PALETTE as HIERARCHY_PALETTE, AssignmentCoordinates

APPEARANCE = "Imported scatter appearance"
CLUSTERED_SCATTER = "Imported cluster scatter columns"
_MAX_GROUPS = 40
_MAX_TICKS = 200


def _rgba(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{8}", value):
        raise ValueError("Invalid saved scatter color.")
    return value.lower()


def _number(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError("Invalid saved scatter number.")
    return float(value)


def marker_record(raw):
    """Validate marker styling imported from a graph or reopened from a project."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid saved scatter marker.")
    return {
        "edge": _rgba(raw.get("edge")),
        "width": _number(raw.get("width"), 0, 20),
        "size": _number(raw.get("size"), .1, 100),
    }


def saved_circle_marker(symbols):
    size = symbols["sizeEvaluator"]
    mark, = symbols["rowSymbolSettings"].values()
    if (symbols["@class"] != "BubblesFigure::Settings" or size["@class"] != "SymbolSizeEvaluator"
            or set(symbols["rowSymbolSettings"]) != {"common"} or mark["symbolShape"] != "circleFill"):
        raise ValueError("Unsupported saved scatter marker.")
    return marker_record({"edge": mark["symbolBorderColor"], "width": mark["symbolBorderThickness"],
                          "size": size["symbolSize"]})


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise ValueError("Invalid saved scatter label.")
    return value


def _title(item):
    return _text(item["title"]["text"]["string"])


def _column(frame, ids):
    if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str):
        raise ValueError("Saved scatter requires one dataset per plotted variable.")
    column, = frame.attrs["legacy_columns"][ids[0]]
    return column


def _axis(axis, expected):
    segment, = axis["segments"]
    if (axis["orientation"] != expected or segment["@class"] != "LinearAxisSegment"
            or segment.get("customTicks") or segment.get("minorTicksCount", 0) != 0):
        raise ValueError("Unsupported saved scatter axis.")
    return {
        "title": _title(axis),
        "low": segment["lowerLimit"],
        "high": segment["upperLimit"],
        "start": segment["startTicksValue"],
        "step": segment["interval"],
        "reversed": segment.get("isReversed", False),
    }


def _legend(graph, symbols):
    legend, = graph["legends"]
    if (legend["@class"] != "CategoricalSymbolsLegend" or symbols["isColorLegendEnabled"] is not True
            or not isinstance(legend["children"], list) or not 1 <= len(legend["children"]) <= _MAX_GROUPS):
        raise ValueError("Unsupported saved scatter legend.")
    entries = list(legend["children"])
    if any(entry["@class"] != "SymbolLegend" or entry.get("symbolShape") != "circleFill" for entry in entries):
        raise ValueError("Unsupported saved scatter marker.")
    palette = {_title(entry): _rgba(entry["symbolFillColor"]) for entry in entries}
    colormap = symbols["colormap"]
    if (len(palette) != len(entries) or colormap["@class"] != "CategoricalColormap"
            or len(colormap["colors"]) != len(entries)
            or sorted(palette.values()) != sorted(_rgba(value) for value in colormap["colors"].values())):
        raise ValueError("Ambiguous saved scatter colors.")
    return _title(legend), palette


def fixed_axis_record(axis):
    """Validate a saved linear viewport and the explicit grid of major ticks."""
    if not isinstance(axis, dict) or type(axis.get("reversed")) is not bool:
        raise ValueError("Invalid saved scatter axes.")
    low = _number(axis.get("low"), -1e150, 1e150)
    high = _number(axis.get("high"), -1e150, 1e150)
    step = _number(axis.get("step"), 1e-150, 1e150)
    start = _number(axis.get("start"), -1e150, 1e150)
    if not low < high or not low <= start <= high or (high - start) / step >= _MAX_TICKS:
        raise ValueError("Invalid saved scatter tick range.")
    return {"title": _text(axis.get("title")), "low": low, "high": high,
            "step": step, "start": start, "reversed": axis["reversed"]}


def appearance_record(raw):
    """Validate persisted settings afresh before drawing a loaded native project."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid saved scatter appearance.")
    palette = raw.get("palette")
    if not isinstance(palette, dict) or not 1 <= len(palette) <= _MAX_GROUPS:
        raise ValueError("Invalid saved scatter palette.")
    style = {
        "palette": {_text(key): _rgba(value) for key, value in palette.items()},
        "legend": _text(raw.get("legend")), **marker_record(raw),
    }
    for key in ("x", "y"):
        style[key] = fixed_axis_record(raw.get(key))
    return style


def saved_scatter(sheet, frames, remaining_cells):
    """Return data, styling and column identities for a saved multivariable scatter."""
    try:
        graph = sheet["graph"]
        if (graph["@class"] != "MVGraph" or sheet.get("drawings") or graph.get("gdoSettingsExt")
                or graph["gdoTypes"] != {"defaults": ["symbols"]}
                or graph["gdoTypesExt"] != {"defaults": ["symbols"]}):
            return None
        frame = frames[graph["dataSheet"]]
        x, y = (_column(frame, graph[f"{axis}Variables"]) for axis in ("x", "y"))
        symbols = graph["gdoSettings"]["symbols"]
        category = _column(frame, [symbols["colorVariable"]])
        if len({x, y, category}) != 3 or not all(pd.api.types.is_numeric_dtype(frame[name]) for name in (x, y)):
            return None
        legend, palette = _legend(graph, symbols)
        style = appearance_record({
            "legend": legend, "palette": palette,
            **saved_circle_marker(symbols),
            "x": _axis(graph["axisX"], "horizontal"), "y": _axis(graph["axisY"], "vertical"),
        })
        values = frame[[x, y]].to_numpy(dtype=float, na_value=np.nan)
        keep = np.isfinite(values).all(axis=1)
        if not keep.any() or int(keep.sum()) * 5 > remaining_cells:
            return None
        groups = frame[category].loc[keep]
        if groups.isna().any():
            return None
        labels = groups.astype(str)
        if set(labels) != set(palette):
            return None
        return _points(values[keep], labels, palette), style, (x, y, category)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _points(values, labels, palette):
    ids = {label: index for index, label in enumerate(palette, 1)}
    return pd.DataFrame({"X": values[:, 0], "Y": values[:, 1], "Series": labels.to_numpy(),
                         "Dataset": labels.map(ids).to_numpy(), "Geometry": "points"})


def clustered_points(frame, binding, palette):
    """Project the current result table using its saved observation axes and cluster labels."""
    if not isinstance(binding, dict):
        raise ValueError("Invalid linked cluster scatter.")
    x, y, group = (binding.get(key) for key in ("x", "y", "group"))
    labels = binding.get("labels")
    observations = None
    if binding.get("hierarchy") is True:
        coordinates = frame.attrs.get(RESULT_CONTEXT)
        if not isinstance(coordinates, AssignmentCoordinates) or len(coordinates.observations) != len(frame):
            raise ValueError("The result no longer provides linked hierarchical assignments.")
        resolved = ([column for label, column in coordinates.features if label == name] for name in (x, y))
        x_columns, y_columns = resolved
        if len(x_columns) != 1 or len(y_columns) != 1:
            raise ValueError("The linked hierarchical scatter needs unique plotted variables.")
        x, y, group = x_columns[0], y_columns[0], coordinates.group
        observations = np.asarray(coordinates.observations)
    if (any(not isinstance(name, str) or name not in frame for name in (x, y, group))
            or len({x, y, group}) != 3):
        raise ValueError("The linked cluster result no longer provides the plotted columns.")
    if (not isinstance(labels, list) or not all(isinstance(label, str) for label in labels)
            or len(labels) != len(palette) or set(labels) != palette.keys()):
        raise ValueError("Invalid linked cluster labels.")
    values = frame[[x, y]].to_numpy(dtype=float, na_value=np.nan)
    groups = frame[group]
    keep = np.isfinite(values).all(axis=1) & groups.notna().to_numpy()
    if not keep.any():
        raise ValueError("The linked cluster result has no complete plotted observations.")
    groups = groups.loc[keep]
    names = dict(enumerate(labels, 1))
    if observations is not None:
        # A new cut can add groups. Keep the saved colors and use native colors
        # for the extra groups in this rendered view.
        extra_groups = set(groups) - names.keys()
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
               or int(value) != value for value in extra_groups):
            raise ValueError("The linked result has an unknown cluster label.")
        for group_id in sorted(map(int, extra_groups)):
            if not len(labels) < group_id <= _MAX_GROUPS:
                raise ValueError("The linked scatter can show up to forty clusters.")
            label = names[group_id] = f"Cluster {group_id}"
            palette[label] = HIERARCHY_PALETTE[(group_id - 1) % len(HIERARCHY_PALETTE)] + "80"
    mapped = groups.map(names)
    if mapped.isna().any():
        raise ValueError("The linked result has an unknown cluster label.")
    points = _points(values[keep], mapped, palette)
    if observations is not None:
        points["Observation"] = observations[keep]
    return points


def apply_axes(axes, style):
    for axis, key, set_limits in ((axes.xaxis, "x", axes.set_xlim), (axes.yaxis, "y", axes.set_ylim)):
        config = style[key]
        low, high, start, step = (config[name] for name in ("low", "high", "start", "step"))
        count = math.floor((high - start) / step + 1e-12) + 1
        axis.set_major_locator(FixedLocator(start + np.arange(count) * step))
        axis.set_label_text(config["title"])
        axis.label.set_parse_math(False)
        limits = (high, low) if config["reversed"] else (low, high)
        set_limits(*limits)
    axes.title.set_parse_math(False)
