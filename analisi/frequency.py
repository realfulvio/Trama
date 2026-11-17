"""Frequency distributions with common bins and exact cumulative counts."""
from decimal import Decimal, ROUND_FLOOR, localcontext
from math import log2

import numpy as np
import pandas as pd

from .category_graphs import _SUMMARY
from .data import decimal_comma
from .processing import FieldError, _column
from .probability_scale import FRACTION_SCALE, PERCENT_SCALE
from .reporting import Result, _plot, _report
from .worksheet_series import series_columns, series_labels


FREQUENCY = "Frequency distribution"
HISTOGRAM, CUMULATIVE, EXACT = "Binned frequency", "Binned cumulative", "Exact cumulative"
MODES = (HISTOGRAM, CUMULATIVE, EXACT)
UNITS = ("Counts", "Fractions", "Percentages")
SEPARATE, POOLED, ROW_MEAN = REPLICATES = ("Separate variables", "Pool within each series", "Mean by worksheet row")
PLOT_STYLES = ("Default", "XY points", "XY spikes", "Bars")
Y_SCALES = ("Linear", "Gaussian probability")
FREQUENCY_OPTIONS = {
    "Variables": "Multiple", "Distribution": MODES, "Units": UNITS,
    "Bin width (blank = automatic)": "Text", "First bin center (blank = automatic)": "Text",
    "Maximum value (blank = no limit)": "Text", "Replicates": REPLICATES,
    "Graph style": PLOT_STYLES, "Y scale": Y_SCALES,
}
MAX_BINS = 512
MAX_SERIES = 24
MAX_EXACT_POINTS = 100_000


def _limit(options, field):
    text = options.get(field, "")
    if isinstance(text, str):
        text = decimal_comma(text.strip())
    if text in ("", None):
        return None
    try:
        value = float(text)
    except (ValueError, TypeError, OverflowError):
        value = np.nan
    if not np.isfinite(value):
        raise FieldError(field, "Enter a finite number or leave the field blank.")
    return value


def _decimal(value):
    return Decimal(str(float(value)))


def _nice_width(arrays):
    # Per-series Sturges widths are averaged before rounding down to 1, 2 or 5.
    sizes = [(_decimal(array.max()) - _decimal(array.min())) / Decimal(str(1 + log2(len(array))))
             for array in arrays if len(array)]
    average = sum(sizes) / len(sizes)
    if average == 0:
        position = max(abs(_decimal(array[0])) for array in arrays if len(array))
        average = max(Decimal(1), position.scaleb(-6))
    scale = Decimal(1).scaleb(average.adjusted())
    width = max(step * scale for step in (1, 2, 5) if step * scale <= average)
    if all(np.equal(array, np.trunc(array)).all() for array in arrays):
        width = max(Decimal(1), width.to_integral_value(rounding=ROUND_FLOOR))
    return width


def _edges(arrays, options):
    width_field = "Bin width (blank = automatic)"
    origin_field = "First bin center (blank = automatic)"
    width_value = _limit(options, width_field)
    center = _limit(options, origin_field)
    if width_value is not None and width_value <= 0:
        raise FieldError(width_field, "The bin width must be positive.")
    smallest = min(_decimal(array.min()) for array in arrays if len(array))
    largest = max(_decimal(array.max()) for array in arrays if len(array))
    with localcontext() as context:
        context.prec = 40
        width = _nice_width(arrays) if width_value is None else _decimal(width_value)
        start = ((smallest / width).to_integral_value(rounding=ROUND_FLOOR) * width
                 if center is None else _decimal(center) - width / 2)
        bins = ((largest - start) / width).to_integral_value(rounding=ROUND_FLOOR) + 1
        if bins <= 0:
            raise FieldError(origin_field, "The first bin starts above all observations.")
        if bins > MAX_BINS:
            raise FieldError(width_field, f"Use a wider bin or select a range of up to {MAX_BINS} bins.")
        edges = np.array([float(start + width * index) for index in range(int(bins) + 1)])
    with np.errstate(over="ignore", invalid="ignore"):
        spacing = np.diff(edges)
    if (not np.isfinite(edges).all() or not np.isfinite(spacing).all()
            or (spacing <= 0).any() or edges[-1] <= float(largest)):
        raise FieldError(width_field, "The bin edges cannot be represented at this numeric precision.")
    return edges, float(width)


def visibility(mode, units):
    binned = mode != EXACT
    return {"Bin width (blank = automatic)": binned, "First bin center (blank = automatic)": binned,
            "Graph style": mode == HISTOGRAM, "Y scale": mode != HISTOGRAM and units != UNITS[0]}


def _observations(frame, names, mode):
    matrix = {name: _column(frame, name, "Variables").to_numpy(dtype=float) for name in names}
    if mode == SEPARATE:
        return [(name, values[np.isfinite(values)]) for name, values in matrix.items()]
    kind = str(frame.attrs.get("table_format") or "").casefold()
    infer = kind.startswith("xy") or kind in {"grouped", "twoway", "two way"}
    groups = series_columns(frame, names, recognize_replicates=infer)
    series = []
    for name, group in zip(series_labels(groups), groups, strict=True):
        if len(group) > 1 and any(_SUMMARY.fullmatch(name) for name in group):
            raise FieldError("Variables", "Select a single precomputed measure per worksheet series.")
        data = np.column_stack([matrix[name] for name in group])
        if mode == POOLED:
            values = data[np.isfinite(data)]
        else:
            observed = np.isfinite(data)
            count = observed.sum(axis=1)
            data = np.where(observed, data, 0.)[count > 0]
            scale = np.max(abs(data), axis=1)
            scaled = data / np.where(scale, scale, 1.)[:, None]
            values = (scaled.sum(axis=1) / count[count > 0]) * scale
        series.append((name, values))
    return series


def _ylabel(units, scale):
    return f"{units} · Normal probability" if scale == Y_SCALES[1] else units


def style_after_parameter_change(style, before, after):
    defaults = {"Distribution": HISTOGRAM, "Units": UNITS[0], "Y scale": Y_SCALES[0]}
    if not style or all(before.get(key, default) == after.get(key, default) for key, default in defaults.items()):
        return style
    updated = {key: value for key, value in style.items() if key not in {"yscale", "axis"}}
    remaining_axes = {dimension: axis for dimension, axis in style.get("axis", {}).items() if dimension != "y"}
    if remaining_axes:
        updated["axis"] = remaining_axes
    if updated.get("ylabel") == _ylabel(before.get("Units", UNITS[0]), before.get("Y scale", Y_SCALES[0])):
        updated.pop("ylabel")
    return updated


def frequency(frame, options):
    names = options.get("Variables", [])
    if (not isinstance(names, list) or not 1 <= len(names) <= MAX_SERIES
            or any(not isinstance(name, str) or name not in frame for name in names) or len(set(names)) != len(names)):
        raise FieldError("Variables", f"Choose 1 to {MAX_SERIES} distinct numeric variables.")
    mode, units = options.get("Distribution", HISTOGRAM), options.get("Units", UNITS[0])
    if mode not in MODES or units not in UNITS:
        raise FieldError("Distribution", "Choose a distribution type and frequency unit.")
    replicates = options.get("Replicates", SEPARATE)
    style = options.get("Graph style", PLOT_STYLES[0]) if mode == HISTOGRAM else PLOT_STYLES[0]
    scale = options.get("Y scale", Y_SCALES[0])
    if replicates not in REPLICATES:
        raise FieldError("Replicates", "Choose how to combine replicate observations.")
    if style not in PLOT_STYLES:
        raise FieldError("Graph style", "Choose a frequency graph style.")
    if scale not in Y_SCALES or (scale != Y_SCALES[0] and not visibility(mode, units)["Y scale"]):
        raise FieldError("Y scale", "A probability axis requires cumulative fractions or percentages.")
    probability = scale == Y_SCALES[1]
    maximum = _limit(options, "Maximum value (blank = no limit)")
    series = _observations(frame, names, replicates)
    names, arrays = zip(*series)
    retained = [array if maximum is None else array[array <= maximum] for array in arrays]
    if not any(len(array) for array in retained):
        raise FieldError("Variables", "No observations remain within the selected range.")
    if mode == EXACT and sum(len(array) for array in retained) > MAX_EXACT_POINTS:
        raise FieldError("Variables", "Use fewer observations or a binned cumulative distribution.")
    edges, width = (None, None) if mode == EXACT else _edges(retained, options)
    figure, axes = _plot(FREQUENCY, "Value", _ylabel(units, scale))
    factor = 100 if units == UNITS[2] else 1
    probability_low, probability_high = .001 * factor, .999 * factor
    if probability:
        axes.set_yscale(PERCENT_SCALE if units == UNITS[2] else FRACTION_SCALE)
    summary, results = [], []
    for index, (name, original, values) in enumerate(zip(names, arrays, retained, strict=True)):
        if edges is None:
            coordinate, counts = np.unique(values, return_counts=True)
            valid_count = len(values)
            sheet = {"Value": coordinate}
        else:
            valid = values[(values >= edges[0]) & (values < edges[-1])]
            valid_count = len(valid)
            bins = np.searchsorted(edges, valid, side="right") - 1
            counts = np.bincount(bins, minlength=len(edges) - 1)
            coordinate = edges[:-1] + np.diff(edges) / 2
            sheet = {"Lower edge": edges[:-1], "Upper edge": edges[1:], "Bin center": coordinate}
        summary.append({"Variable": name, "Observed": len(original), "Included": valid_count,
                        "Omitted": len(original) - valid_count})
        if mode != HISTOGRAM:
            counts = counts.cumsum()
        if units == UNITS[0]:
            height = counts
        elif valid_count:
            height = counts / valid_count * factor
        else:
            height = np.full(len(counts), np.nan)
        result = pd.DataFrame({"Variable": name, **sheet, units: height})
        results.append(result)
        if valid_count:
            if mode == HISTOGRAM:
                if style == "XY points":
                    axes.plot(coordinate, height, "o", label=name)
                elif style == "XY spikes":
                    axes.vlines(coordinate, 0, height, color=f"C{index % 10}", label=name)
                else:
                    axes.bar(edges[:-1], height, width=np.diff(edges), align="edge", alpha=.56, label=name)
            else:
                x = coordinate if edges is None else edges[1:]
                if probability:
                    inside = height[(height > 0) & (height < factor)]
                    if len(inside):
                        probability_low = min(probability_low, inside.min())
                        probability_high = max(probability_high, inside.max())
                    axes.plot(x, height, "o-", markersize=4, label=name)
                else:
                    axes.step(x, height, where="post", label=name)
    if not sum(record["Included"] for record in summary):
        raise FieldError("Variables", "No observations remain in the selected bins.")
    if probability:
        axes.set_ylim(probability_low, probability_high)
    if len(names) > 1:
        axes.legend()
    settings = {"Distribution": mode, "Units": units, "Bin width": width, "Replicates": replicates}
    if mode == HISTOGRAM:
        settings["Graph style"] = style
    elif units != UNITS[0]:
        settings["Y scale"] = scale
        if probability:
            settings["Probability endpoints"] = "0 and 100% remain in results and are outside the plot scale."
    tables = {"Frequencies": pd.concat(results, ignore_index=True),
              "Observation counts": pd.DataFrame(summary),
              "Settings": _report(settings)}
    return Result(tables, figure)
