"""Reopen verified source-free dose-response simulations as native function plots."""
from hashlib import sha256
from struct import error as StructError, unpack

import numpy as np

from . import plot_function as plotting
from .legacy_binary_dose import _dataset_link, _matching_grid
from .legacy_binary_editable import _axis_config, _id_array, _one, _project_records, _require, _scene, _subgroups
from .legacy_binary_results import _column_ids, _read_groups
from .legacy_xml_generated import _generator_records
from .presentation import validated_style


_INHIBITION = "6175738bcacd57b1356182d392b4bc1a2b6302c83b6c6560731217724a3347e9"
_ASYMMETRIC = "0bc50a860cccfb552653a35ca81c5773d306163a6d36c449214cf9a251770314"


def _simulation_options(records, frame):
    """Translate a known equation and confirm its parameters against every saved value."""
    (header, expression_group), = _subgroups(records, 0x8047)
    _require(len(header) == 44 and unpack("<3I", header[:12]) == (1, 0, 1))
    (_, expression), = _subgroups(expression_group, 0x8048)
    text = bytes(_one(expression, 0x49)).rstrip(b"\r\n\0").decode("ascii")
    signature = sha256("".join(text.split()).encode("ascii")).hexdigest()
    payload = _one(expression, 0x54)
    _require(len(payload) in (32, 40))
    values = unpack(f"<{len(payload) // 8}d", payload)
    raw_names = bytes(_one(expression, 0x53)).split(b"\0", len(values))
    _require(len(raw_names) == len(values) + 1 and np.isfinite(values).all())
    parameters = dict(zip((name.decode("ascii") for name in raw_names[:-1]), values, strict=True))
    if signature == _INHIBITION and parameters.keys() == {"Bottom", "Top", "IC50", "HillSlope"}:
        model = "Inhibition (variable slope)"
        native = {"Bottom": parameters["Top"], "Top": parameters["Bottom"], "IC50": parameters["IC50"],
                  "Hill slope": -parameters["HillSlope"]}
    elif signature == _ASYMMETRIC and parameters.keys() == {"Bottom", "Top", "EC50", "HillSlope", "S"}:
        model = "Asymmetric dose-response (concentration X)"
        native = {"Bottom": parameters["Bottom"], "Top": parameters["Top"], "EC50": parameters["EC50"],
                  "Hill slope": parameters["HillSlope"], "Asymmetry": parameters["S"]}
    else:
        raise ValueError("The saved simulation equation is not supported.")
    x_column, name = frame.columns
    options = {plotting.MODEL: model, plotting.X_SOURCE: plotting.WORKSHEET, plotting.X_COLUMN: x_column,
               plotting.CURVES: [{"name": name, "parameters": native}]}
    curves = plotting.check_curves(model, options[plotting.CURVES])
    x = plotting.worksheet_grid(frame, options, len(curves))
    plotting.check_domain(model, x, plotting.X_COLUMN)
    observed = frame[name].to_numpy(dtype=float)
    # Older result tables can store their regular X step at single precision.
    _require(x.shape == observed.shape and np.isfinite(observed).all()
             and np.allclose(plotting.evaluate(model, x, native), observed, rtol=3e-8, atol=1e-10))
    return options


def _matches_drawing(cache, values, axes):
    if cache.shape != values.shape:
        return False
    if axes[0]["scale"] == "log" and values[0, 0] == 0:
        if not np.array_equal(cache[0], [-1, -1]):
            return False
        # A zero concentration can be evaluated but it has no log-axis position.
        cache, values = cache[1:], values[1:]
    return _matching_grid(cache, values, axes, high_anchored=True)


def read_simulation_graphs(data, result_frames, graph_ids, remaining_cells):
    """Yield editable X tables for verified simulations and their drawing identity."""
    source_free = {uid: frame for uid, frame in result_frames.items()
                   if frame.attrs["legacy_binary_result"]["source_ids"] == [] and frame.shape[1] == 2}
    if not source_free:
        return
    try:
        _, encoding, drawings, _ = _project_records(data, ())
        _, sheets, _, listed, _ = _read_groups(data)
        generators = _generator_records(data)
    except (ValueError, StructError):
        return
    for graph_id, graph in drawings.items():
        if graph_id not in graph_ids or not graph:
            continue
        try:
            sheet, = _id_array(_one(graph, 0x14))
            samples = source_free[sheet]
            _require(3 <= len(samples) <= min(remaining_cells, plotting.MAX_EVALUATIONS))
            analysis = samples.attrs["legacy_binary_result"]["analysis_id"]
            _require(analysis in (listed or ()) and generators[analysis] is not None)
            records = generators[analysis]
            kind = unpack("<8H", _one(records, 0x3A))
            _require(kind[:2] == (15, 255) and kind[3:] == (0, 251, 0, 65535, 0)
                     and _one(records, 0x3B) == bytes(4)
                     and unpack("<11i", _one(records, 0x3C)) == (10, sheet, *([-1] * 9)))
            column, = _column_ids(sheets[sheet][0])
            link = _dataset_link(sheets[sheet], column, 40)
            _require(link is not None and unpack("<H3i", _one(graph, 0x16)) == (1, *link))
            series, = _id_array(_one(graph, 0x15))
            texts, _, _, drawn = _scene(graph, encoding)
            _require(drawn.keys() == {series} and drawn[series][0] == column)
            axes = _axis_config(graph, viewport_only=True)
            _require(_matches_drawing(drawn[series][1], samples.to_numpy(dtype=float), axes))
            options = _simulation_options(records, samples)
            style = {"legend": "hidden", "axis": {}}
            for name, axis in zip("xy", axes, strict=True):
                scale = axis["scale"]
                low, high = axis["bounds"]
                style[name + "scale"] = scale
                style[name + "label"] = texts.get(axis["title"], "")
                style["axis"][name] = {"min": 10. ** low if scale == "log" else low,
                                       "max": 10. ** high if scale == "log" else high}
            style = validated_style(style)
        except (KeyError, TypeError, ValueError, StructError, OverflowError):
            continue
        remaining_cells -= len(samples)
        grid = samples[[options[plotting.X_COLUMN]]].copy()
        grid.attrs.clear()
        yield graph_id, analysis, grid, options, style
