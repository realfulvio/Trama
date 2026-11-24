"""Binding and point generation for a saved graph of an imported nonlinear fit."""
from math import isfinite

from matplotlib.colors import is_color_like
import numpy as np
import pandas as pd

from .i18n import ui
from .stats import MODELS, complete
from . import regression_range as rr
from .replicate_fit import MERGE_REPLICATES, stack_replicates


FIT_GRAPH = "Imported fitted graph"
FIT_GRAPH_POINTS = "Fit graph coordinates"
FIT_GRAPH_SPEC = "Imported fit graph sampling"
FIT_GRAPH_TICKS = "Imported fit concentration ticks"
FIT_GRAPH_OBSERVATIONS = "Imported fit observations visible"
FIT_INTERVAL_BAND = "Imported parameter interval band"
LOG_DOSE_MODEL = "Stimulation (standard slope, log10 X)"
MAX_SAMPLES = 2000


def absolute_fit_overlay(model, spec):
    """Validate the saved reference points before adding them to a live fit."""
    logarithmic = model == "Absolute IC50 (log10 X)"
    if not logarithmic and model != "Absolute IC50 (concentration X)":
        return None
    points = spec.get("control overlay")
    colors = tuple(spec.get(key) for key in ("control color", "response color", "curve color"))
    if (not isinstance(points, list) or not 1 <= len(points) <= 64
            or any(not isinstance(point, list) or len(point) != 2 or
                   any(type(v) not in (int, float) or not -1e100 < v < 1e100 for v in point)
                   for point in points)
            or not all(isinstance(color, str) and len(color) == 7 and color.startswith("#")
                       and is_color_like(color) for color in colors)):
        return None
    coords = np.array(points, dtype=float)
    if not logarithmic and np.any(coords[:, 0] <= 0):
        return None
    return coords, colors


def draw_absolute_fit_midpoints(axes, fit, model, color):
    """Show the current absolute and relative midpoint on the fitted line."""
    top_excess, bottom_gap, absolute, steepness, baseline = fit.parameters["Estimate"]
    half_top = top_excess / 2
    shift = (np.log(bottom_gap) - np.log(half_top)) / steepness
    log_x = model == "Absolute IC50 (log10 X)"
    with np.errstate(over="ignore", under="ignore"):
        relative = absolute + shift / np.log(10.) if log_x else np.exp(np.log(absolute) + shift)
    bottom = baseline + half_top - bottom_gap
    x = fit.curve[:, 0]
    for pos, response, offset, align, title in (
            (absolute, baseline + half_top, 12, "left", "Absolute IC50"),
            (relative, bottom + (half_top + bottom_gap) / 2, -12, "right", "Relative IC50")):
        if x[0] <= pos <= x[-1] and np.isfinite(response):
            axes.annotate(ui(title), (pos, response), xytext=(offset, 24), textcoords="offset points",
                          ha=align, color=color, fontsize="small", annotation_clip=True,
                          arrowprops={"arrowstyle": "-", "color": color, "linewidth": .8})


def draw_fit_interval_band(axes, spec, parameters, level):
    """Render the saved band using the current fit's Log EC50 limits."""
    if not isinstance(spec, dict):
        return
    title, color, limits = (spec.get(key) for key in ("title", "color", "limits"))
    if not (isinstance(title, str) and len(title) <= 160 and isinstance(color, str)
            and len(color) == 7 and color.startswith("#") and is_color_like(color)
            and isinstance(limits, list) and len(limits) == 2):
        return
    for pair in limits:
        if not (isinstance(pair, list) and len(pair) == 2
                and all(type(value) in (float, int) and -1e100 < value < 1e100 for value in pair)
                and pair[0] < pair[1]):
            return
    axes.set_title(title, parse_math=False)
    axes.set_xlim(limits[0])
    axes.set_ylim(limits[1])
    label = str(int(level)) if level.is_integer() else repr(level)
    low, high = parameters.loc["Log EC50", [f"CI {label}% low", f"CI {label}% high"]]
    if isfinite(low) and isfinite(high) and low < high:
        axes.axvspan(low, high, facecolor=color, edgecolor="none", zorder=0, gid="linked-parameter-interval")


def saved_curve_range(parameters):
    """Translate a supported drawing grid without validating it against a fit."""
    try:
        graph = parameters["content"]["graph"]
        curve = graph["curve"]
        samples = curve["pointCount"]
        if (type(samples) is not int or not 2 <= samples <= MAX_SAMPLES
                or graph["curveBands"]["type"] != "NONE"):
            return None
        found = {rr.CURVE_POINTS: samples}
        for edge, field in (("minX", rr.CURVE_MIN), ("maxX", rr.CURVE_MAX)):
            auto = curve[edge]["isAuto"]
            if type(auto) is not bool:
                return None
            if not auto:
                value = curve[edge]["value"]
                if type(value) not in (int, float) or not isfinite(value):
                    return None
                found[field] = value
        return rr.ranges(found)
    except (KeyError, TypeError, OverflowError, ValueError):
        pass
    return None


def saved_samples(parameters):
    found = saved_curve_range(parameters)
    return found[rr.CURVE_POINTS] if found else None


def _observations(data, x, response, groups, labels):
    if groups:
        category = data[groups[0]].map(str)
        if category.nunique() != data[groups[0]].nunique() or set(category) != set(labels):
            return None
    elif len(labels) == 1:
        category = labels[0]
    else:
        return None
    return pd.DataFrame({"X": data[x], "Y": data[response], "Series": category})


def _same_points(source, archived):
    return (source is not None and len(source) == len(archived)
            and np.array_equal(source.sort_values(["Series", "X", "Y"]).to_numpy(),
                               archived.sort_values(["Series", "X", "Y"]).to_numpy()))


def fit_graph_spec(source, options, archived, samples):
    """Confirm ownership and sampling against the archived observation and curve coordinates."""
    pooled = options.get(MERGE_REPLICATES) is True
    if pooled:
        source = stack_replicates(source, options)
        x, response, groups = "X", "Response", ["Series"]
    else:
        x = options["X"]
        response, = options["Y columns"]
        groups = options["Grouping variables"]
    ranges = rr.ranges(options)
    data = complete(rr.fitting_rows(source, x, ranges), [x, response], groups)
    if data.empty:
        return None
    observed = archived.loc[archived["Geometry"] == "points", ["X", "Y", "Series"]]
    fitted = archived.loc[archived["Geometry"] == "line", ["X", "Y", "Series"]]
    order = observed["Series"].drop_duplicates().tolist()
    if pooled:
        # A saved curve caption can omit trailing whitespace from its XY series.
        names = {name.rstrip(): name for name in order}
        curve_names = fitted["Series"].unique()
        if (len(names) != len(order) or len(curve_names) != len(order)
                or {name.rstrip() for name in curve_names} != set(names)):
            return None
        fitted = fitted.assign(Series=fitted["Series"].map(lambda name: names[name.rstrip()]))
    if not order or set(order) != set(fitted["Series"]):
        return None
    source_points = _observations(data, x, response, groups, order)
    if source_points is None:
        return None
    show_outside = not _same_points(source_points, observed)
    if show_outside:
        all_points = _observations(complete(source, [x, response], groups), x, response, groups, order)
        if not _same_points(all_points, observed):
            return None
    grid = np.linspace(data[x].min(), data[x].max(), samples)
    for label in order:
        native_x = source_points.loc[source_points["Series"] == label, "X"]
        expected = rr.drawing_grid(native_x, ranges)
        if expected is None:
            expected = grid[(grid >= native_x.min()) & (grid <= native_x.max())] if pooled else grid
        saved_x = fitted.loc[fitted["Series"] == label, "X"].to_numpy()
        if len(saved_x) != len(expected) or not np.allclose(saved_x, expected, rtol=2e-14, atol=1e-14):
            return None
    spec = {"x": x, "y": response, "samples": samples, "series": order, "grouped": bool(groups)}
    if pooled:
        spec["clip to series"] = True
    return spec, show_outside


def fitted_graph_points(fits, model, x, y, spec, *, observations=None, custom_range=False):
    """Evaluate the confirmed estimates on the saved grid without fitting again."""
    if not isinstance(spec, dict) or x != spec.get("x") or y != spec.get("y"):
        return None
    samples, order, grouped = spec.get("samples"), spec.get("series"), spec.get("grouped")
    if (type(samples) is not int or not 2 <= samples <= MAX_SAMPLES or not isinstance(order, list)
            or not 1 <= len(order) <= 32 or any(not isinstance(label, str) for label in order)
            or type(grouped) is not bool):
        return None
    if grouped:
        named = {str(label): label for label in fits}
        if len(named) != len(fits):
            return None
    elif len(order) == len(fits) == 1:
        named = {order[0]: next(iter(fits))}
    else:
        return None
    labels = [label for label in dict.fromkeys([*order, *named]) if label in named]
    function = MODELS[model].equation
    first = min(fit.data[x].min() for fit in fits.values())
    last = max(fit.data[x].max() for fit in fits.values())
    grid = np.linspace(first, last, samples)
    points, lines = [], []
    for i, label in enumerate(labels, 1):
        key = named[label]
        fit = fits[key]
        fitted_x = fit.data[x].to_numpy()
        if custom_range:
            curve_x, prediction = fit.curve.T
        else:
            curve_x = grid
            if spec.get("clip to series") is True:
                curve_x = grid[(grid >= fitted_x.min()) & (grid <= fitted_x.max())]
            prediction = function(curve_x, *fit.parameters["Estimate"].to_numpy())
        if not np.isfinite(prediction).all():
            return None
        xy = fit.data if observations is None else observations[key]
        points.append(pd.DataFrame({"X": xy[x].to_numpy(), "Y": xy[y].to_numpy(), "Series": label,
                                    "Dataset": i, "Geometry": "points"}))
        lines.append(pd.DataFrame({"X": curve_x, "Y": prediction, "Series": label,
                                   "Dataset": len(labels) + i, "Geometry": "line"}))
    return pd.concat([*points, *lines], ignore_index=True)
