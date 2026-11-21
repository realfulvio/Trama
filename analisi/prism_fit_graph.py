"""Binding and point generation for a saved graph of an imported nonlinear fit."""
from math import isfinite

from matplotlib.colors import is_color_like
import numpy as np
import pandas as pd

from .stats import MODELS, complete


FIT_GRAPH = "Imported fitted graph"
FIT_GRAPH_POINTS = "Fit graph coordinates"
FIT_GRAPH_SPEC = "Imported fit graph sampling"
FIT_INTERVAL_BAND = "Imported parameter interval band"
LOG_DOSE_MODEL = "Stimulation (standard slope, log10 X)"
MAX_SAMPLES = 2000


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


def saved_samples(parameters):
    try:
        graph = parameters["content"]["graph"]
        curve = graph["curve"]
        samples = curve["pointCount"]
        if (type(samples) is int and 2 <= samples <= MAX_SAMPLES
                and all(curve[edge]["isAuto"] is True for edge in ("minX", "maxX"))
                and graph["curveBands"]["type"] == "NONE"):
            return samples
    except (KeyError, TypeError):
        pass
    return None


def fit_graph_spec(source, options, archived, samples):
    """Confirm ownership and sampling against the archived observation and curve coordinates."""
    x = options["X"]
    response, = options["Y columns"]
    groups = options["Grouping variables"]
    data = complete(source, [x, response], groups)
    if data.empty:
        return None
    observed = archived.loc[archived["Geometry"] == "points", ["X", "Y", "Series"]]
    fitted = archived.loc[archived["Geometry"] == "line", ["X", "Y", "Series"]]
    order = observed["Series"].drop_duplicates().tolist()
    if not order or set(order) != set(fitted["Series"]):
        return None
    if groups:
        label = data[groups[0]].map(str)
        if label.nunique() != data[groups[0]].nunique() or set(label) != set(order):
            return None
    elif len(order) == 1:
        label = order[0]
    else:
        return None
    source_points = pd.DataFrame({"X": data[x], "Y": data[response], "Series": label})
    for label in order:
        native = source_points.loc[source_points["Series"] == label, ["X", "Y"]].sort_values(["X", "Y"])
        saved = observed.loc[observed["Series"] == label, ["X", "Y"]].sort_values(["X", "Y"])
        if not np.array_equal(native.to_numpy(), saved.to_numpy()):
            return None
    grid = np.linspace(data[x].min(), data[x].max(), samples)
    for _, curve in fitted.groupby("Series", sort=False):
        saved = curve["X"].to_numpy()
        if len(saved) != samples or not np.allclose(saved, grid, rtol=2e-14, atol=1e-14):
            return None
    return {"x": x, "y": response, "samples": samples, "series": order, "grouped": bool(groups)}


def fitted_graph_points(fits, model, x, y, spec):
    """Evaluate the confirmed estimates on the saved grid without fitting again."""
    if not isinstance(spec, dict) or x != spec.get("x") or y != spec.get("y"):
        return None
    samples, order, grouped = spec.get("samples"), spec.get("series"), spec.get("grouped")
    if (type(samples) is not int or not 2 <= samples <= MAX_SAMPLES or not isinstance(order, list)
            or not 1 <= len(order) <= 32 or any(not isinstance(label, str) for label in order)
            or type(grouped) is not bool):
        return None
    if grouped:
        named = {str(label): fit for label, fit in fits.items()}
        if len(named) != len(fits):
            return None
    elif len(order) == len(fits) == 1:
        named = {order[0]: next(iter(fits.values()))}
    else:
        return None
    labels = [label for label in dict.fromkeys([*order, *named]) if label in named]
    function = MODELS[model].equation
    first = min(fit.data[x].min() for fit in fits.values())
    last = max(fit.data[x].max() for fit in fits.values())
    grid = np.linspace(first, last, samples)
    points, lines = [], []
    for i, label in enumerate(labels, 1):
        fit = named[label]
        prediction = function(grid, *fit.parameters["Estimate"].to_numpy())
        if not np.isfinite(prediction).all():
            return None
        points.append(pd.DataFrame({"X": fit.data[x].to_numpy(), "Y": fit.data[y].to_numpy(), "Series": label,
                                    "Dataset": i, "Geometry": "points"}))
        lines.append(pd.DataFrame({"X": grid, "Y": prediction, "Series": label,
                                   "Dataset": len(labels) + i, "Geometry": "line"}))
    return pd.concat([*points, *lines], ignore_index=True)
