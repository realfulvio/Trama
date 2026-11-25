"""Rebuild verified legacy XY ranges as live, vector graphs."""

from struct import unpack_from

from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from .legacy_binary_editable import _axis_config, _one, _subgroups, _text_object
from .legacy_emf_edit import _MAX_POINTS, _emf_records, _project, _require
from .reporting import Result


BINARY_XY_RANGE = "Binary XY shaded range"


def _band_values(frame, x, columns, *, sort_x=False):
    values = frame[[x, *columns]].to_numpy(dtype=float, na_value=np.nan)
    _require(2 <= len(values) <= _MAX_POINTS and np.isfinite(values[:, [0, 2, 3]]).all(),
             "Enter finite X values and both endpoints for every point of the shaded range.")
    if sort_x and not (np.diff(values[:, 0]) > 0).all():
        values = values[np.argsort(values[:, 0], kind="stable")]
    _require((np.diff(values[:, 0]) > 0).all(),
             "X values for the shaded range must be distinct." if sort_x
             else "X values for the shaded range must be increasing.")
    _require((values[:, 2] >= values[:, 3]).all(),
             "Keep the upper endpoint of the shaded range at or above its lower endpoint.")
    return values


def verify_band(frame, x, columns, cache, raw, style):
    """Require the table, cached coordinates and the drawn polygon to agree."""
    values = _band_values(frame, x, columns)
    n = len(values)
    left, _, _, bottom = style["chart"]
    center, upper, lower = (_project(values[:, [0, i]], style) for i in (1, 2, 3))
    expected = np.column_stack((upper[:, 0] - left, bottom - center[:, 1],
                                bottom - upper[:, 1], bottom - lower[:, 1]))
    _require(cache.size >= n * 4 and not cache[n * 4:].any()
             and np.all(np.abs(cache[:n * 4].reshape(n, 4) - expected) <= 2))
    _require((upper[:, 1] + 2 < lower[:, 1]).any())
    polygon = np.concatenate((upper, lower[::-1]))
    matches = 0
    for kind, size, offset in _emf_records(raw):
        if kind != 86 or size != 28 + 8 * n or unpack_from("<I", raw, offset + 24)[0] != 2 * n:
            continue
        pixels = np.frombuffer(raw, dtype="<i2", count=4 * n, offset=offset + 28).reshape(-1, 2)
        if np.all(np.abs(pixels - polygon) <= 2):
            matches += 1
    _require(matches == 1, "The shaded range does not match a unique saved polygon.")


def range_axes(graph, encoding, style):
    """Recover the axis captions and only unambiguous legacy tick labels."""
    _, scene = next(_subgroups(graph, 0x8018))
    axes = _axis_config(graph)
    titles = {axis["title"] for axis in axes}
    labels, tick_texts = {}, []
    for header, records in _subgroups(scene, 0x8020):
        kind, = unpack_from("<H", header)
        if kind not in (2, 15):
            continue
        try:
            flags, = unpack_from("<H", header, 28)
            uid, label = _text_object(records, encoding, flags)
        except ValueError:
            continue
        if uid in titles:
            labels[uid] = label
        elif kind == 15 and label:
            bounds = unpack_from("<4h", header, 2)
            tick_texts.append((bounds[0], bounds[2], label))

    settings = []
    for index, axis in enumerate(axes):
        low, high = axis["bounds"]
        log = axis["scale"] == "log"
        bounds = [10.0 ** low, 10.0 ** high] if log else [low, high]
        ticks = {}
        if index == 0 and not log:
            for record in axis["custom_ticks"]:
                if len(record) != 20:
                    continue
                value, = unpack_from("<d", record)
                prefix = bytes(record[10:]).split(b"\0", 1)[0].decode(encoding)
                if not prefix or not low <= value <= high:
                    continue
                pixel = style["chart"][0] + (value - low) / axis["unit"]
                matches = [label for left, right, label in tick_texts
                           if left <= pixel <= right and label.startswith(prefix)]
                if len(matches) == 1:
                    ticks[value] = matches[0].replace("\N{NO-BREAK SPACE}", " ")
        if len(ticks) != len(axis["custom_ticks"]):
            ticks.clear()
        settings.append({"scale": axis["scale"], "bounds": bounds, "label": labels.get(axis["title"], ""),
                         "ticks": sorted(ticks.items())})
    return settings


def render_binary_range(frame, style, title):
    """Follow the original worksheet when either the range or observations change."""
    from .legacy_emf_limits import points_from_limit_source

    try:
        binding = style["source"]
        band = _band_values(frame, binding["x"], style["columns"], sort_x=True)
        points = points_from_limit_source(frame, binding)
        plot_x = points[:, 0] + np.asarray(style["nudges"], dtype=float)
        scales = style["axes"]
        if scales[1]["scale"] == "log":
            bottom = points[:, 1] - np.nan_to_num(points[:, 3], nan=0.)
            _require((band[:, 3] > 0).all() and (bottom > 0).all(),
                     "A logarithmic axis requires positive values and endpoints.")
    except (IndexError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid source columns or settings for the shaded XY range.") from error

    figure = Figure(figsize=(7.5, 5), layout="constrained")
    axes = figure.add_subplot()
    axes._tramastat_numeric_axes = ("x", "y")
    axes.set_title(title, parse_math=False)
    axes.spines[["top", "right"]].set_visible(False)
    for dimension, set_scale, config in zip((axes.xaxis, axes.yaxis), (axes.set_xscale, axes.set_yscale),
                                             scales, strict=True):
        set_scale(config["scale"])
        dimension.set_label_text(config["label"], parse_math=False)
        if config["ticks"]:
            positions, labels = zip(*config["ticks"], strict=True)
            dimension.set_ticks(positions, labels, parse_math=False)
    axes.set_xlim(scales[0]["bounds"])
    axes.set_ylim(scales[1]["bounds"])
    shade = axes.fill_between(band[:, 0], band[:, 3], band[:, 2], color=style["color"],
                              linewidth=0, label=style["label"])
    shade.set_gid("linked-xy-range")
    start = 0
    labels = []
    for group, appearance in zip(binding["groups"], style["series"], strict=True):
        stop = start + len(group["points"])
        rows = points[start:stop]
        label = str(group["columns"][0]).removesuffix(" [Center]")
        axes.errorbar(plot_x[start:stop], rows[:, 1], yerr=np.nan_to_num(rows[:, [3, 2]].T, nan=0.),
                      fmt=appearance["marker"], color=appearance["color"], capsize=0, label=label)
        labels.extend([label] * len(rows))
        start = stop
    for label in axes.legend().get_texts():
        label.set_parse_math(False)
    return Result({"Shaded range": pd.DataFrame({"X": band[:, 0], "Lower": band[:, 3], "Upper": band[:, 2]}),
                   "XY coordinates": pd.DataFrame({"Series": labels, "X": points[:, 0], "Plotted X": plot_x,
                                                   "Y": points[:, 1], "Lower error": points[:, 3],
                                                   "Upper error": points[:, 2]})}, figure)
