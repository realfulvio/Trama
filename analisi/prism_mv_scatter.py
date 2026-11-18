"""Restore compatible categorical scatter graphs from ZIP project metadata."""
import math
import re

import numpy as np
import pandas as pd
from matplotlib.ticker import FixedLocator

APPEARANCE = "Imported scatter appearance"
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


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise ValueError("Invalid saved scatter label.")
    return value


def _title(item):
    return _text(item["title"]["text"]["string"])


def _column(frame, ids):
    if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str):
        raise ValueError("Saved scatter requires one dataset per plotted variable.")
    column, = frame.attrs["prism_columns"][ids[0]]
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


def appearance_record(raw):
    """Validate persisted settings afresh before drawing a loaded native project."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid saved scatter appearance.")
    palette = raw.get("palette")
    if not isinstance(palette, dict) or not 1 <= len(palette) <= _MAX_GROUPS:
        raise ValueError("Invalid saved scatter palette.")
    style = {
        "palette": {_text(key): _rgba(value) for key, value in palette.items()},
        "edge": _rgba(raw.get("edge")), "width": _number(raw.get("width"), 0, 20),
        "size": _number(raw.get("size"), .1, 100), "legend": _text(raw.get("legend")),
    }
    for key in ("x", "y"):
        axis = raw.get(key)
        if not isinstance(axis, dict) or type(axis.get("reversed")) is not bool:
            raise ValueError("Invalid saved scatter axes.")
        low = _number(axis.get("low"), -1e150, 1e150)
        high = _number(axis.get("high"), -1e150, 1e150)
        step = _number(axis.get("step"), 1e-150, 1e150)
        start = _number(axis.get("start"), -1e150, 1e150)
        if not low < high or not low <= start <= high or (high - start) / step >= _MAX_TICKS:
            raise ValueError("Invalid saved scatter tick range.")
        style[key] = {"title": _text(axis.get("title")), "low": low, "high": high,
                      "step": step, "start": start, "reversed": axis["reversed"]}
    return style


def saved_scatter(sheet, frames, remaining_cells):
    """Return data and styling for supported, unambiguous multivariable scatter graphs."""
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
        size = symbols["sizeEvaluator"]
        mark = symbols["rowSymbolSettings"]["common"]
        if (symbols["@class"] != "BubblesFigure::Settings" or size["@class"] != "SymbolSizeEvaluator"
                or mark["symbolShape"] != "circleFill" or set(symbols["rowSymbolSettings"]) != {"common"}):
            return None
        legend, palette = _legend(graph, symbols)
        style = appearance_record({
            "legend": legend, "palette": palette,
            "size": size["symbolSize"], "edge": mark["symbolBorderColor"], "width": mark["symbolBorderThickness"],
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
        ids = {label: index for index, label in enumerate(palette, 1)}
        points = pd.DataFrame({"X": values[keep, 0], "Y": values[keep, 1], "Series": labels.to_numpy(),
                               "Dataset": labels.map(ids).to_numpy(), "Geometry": "points"})
        return points, style
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def apply_axes(axes, style):
    for axis, key in ((axes.xaxis, "x"), (axes.yaxis, "y")):
        config = style[key]
        low, high, start, step = (config[name] for name in ("low", "high", "start", "step"))
        count = math.floor((high - start) / step + 1e-12) + 1
        axis.set_major_locator(FixedLocator(start + np.arange(count) * step))
        axis.set_label_text(config["title"])
        axis.label.set_parse_math(False)
        limits = (high, low) if config["reversed"] else (low, high)
        if key == "x":
            axes.set_xlim(*limits)
        else:
            axes.set_ylim(*limits)
    axes.title.set_parse_math(False)
