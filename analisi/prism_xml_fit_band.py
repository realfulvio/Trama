"""Restore a fit and the parameter interval linked to its saved XML graph."""

from hashlib import sha256
from struct import error as StructError, unpack, unpack_from

from pandas.api.types import is_numeric_dtype

from .prism_binary import _DATASET
from .prism_binary_editable import _axis_config, _one, _require, _subgroups
from .prism_binary_graphs import _read_title
from .prism_fit_graph import FIT_INTERVAL_BAND, LOG_DOSE_MODEL
from .prism_restore import PRISM_NOTES, PRISM_TITLE

_FIT_KIND = (0, 5, 0, 1, 255, 1, 65535, 0)
_FIT_SETTINGS = "7c9c7d20775c21d9c53a2328866276726263fbe4fba4da38114c2003132dced1"
_FIT_OPTIONS = (1, 0, 2, 0, 59, 16, 0, 10, 1, 1, 1, 1, -1, -1)
_CONSTRAINTS = {
    0xC4: "f3889a701b4325c10c5b1f422ecacaea6aa01c22844253db317349f9b26ec983",
    0xC9: "d35139a725d1f1255177fc3250b247facd829a45541391a612ebd875f45eb68d",
}
_EQUATION = b"Y=Bottom+(Top-Bottom)/(1+10^((LogEC50-X)))"


def _column(records, table, producer, *, role):
    headers = [_DATASET.unpack(raw) for tag, path, raw in records if tag == 0x800F and not path]
    storage = 101 if producer == -1 else 102
    _require(headers and all(row[3:6] == (producer, table, storage) for row in headers))
    data_id, = (row[0] for row in headers if row[7:11] == role)
    position, linked, repeats = unpack_from("<3I", _one(records, 0x0D))
    _require((position, linked, repeats) == (0, data_id, 1))
    return data_id


def _band_appearance(graph, producer, summary):
    x, y = _axis_config(graph)
    _require(x["scale"] == y["scale"] == "linear" and not y["custom_ticks"])
    tick_handles = [raw for tag, path, raw in graph if tag == 0x17 and not path]
    x_scale, = unpack_from("<H", tick_handles[0], 54)
    records, = (records for raw, records in _subgroups(graph, 0x8025) if unpack_from("<H", raw)[0] == x_scale)
    guide_values = []
    for raw in x["custom_ticks"]:
        _require(len(raw) == 34 and raw[8:10].tobytes() == b"\x03\x00")
        guide_values.append(unpack_from("<d", raw)[0])
    lower, upper = guide_values
    _require(x["bounds"][0] < lower < upper < x["bounds"][1])

    # Confirm the two parameter references and the fill between their guides.
    # A static axis guide has no result reference and must not become a fit interval.
    references = [unpack("<11I", raw) for tag, path, raw in records if tag == 0xA9 and not path]
    selected = [ref for ref in references if ref[1] != 0xFFFFFFFF]
    _require(selected == [(4, 7, producer, summary, 0, 0, 0, 0, 0, 4, 0x01020001),
                          (4, 12, producer, summary, 0, 0, 0, 0, 0, 4, 0x02020001)])
    start, stop = (raw for tag, path, raw in records if tag == 0xA2 and not path)
    _require(len(start) == len(stop) == 102 and unpack_from("<Hd", start) == (6, lower)
             and unpack_from("<Hd", stop) == (6, upper)
             and unpack_from("<H", start, 36)[0] == 1 and unpack_from("<H", stop, 36)[0] == 0
             and start[40:43].tobytes() == stop[40:43].tobytes() and start[43] == stop[43] == 0)
    return {"color": "#" + bytes(start[40:43]).hex(), "limits": [x["bounds"], y["bounds"]]}


def attach_fit_interval_bands(sources, analyses, fit_sheets, tables, views, encoding):
    """Rebuild the supported asymptotic log-EC50 graph from its source sheet."""
    for producer, source, kind, contents in analyses:
        if kind != _FIT_KIND:
            continue
        frame, x, groups = sources[source]
        if len(groups) != 1 or len(groups[0][1]) != 1:
            continue
        y, = groups[0][1]
        if not is_numeric_dtype(frame[x]) or not is_numeric_dtype(frame[y]):
            continue
        try:
            _require(sha256(_one(contents, 0x46)).hexdigest() == _FIT_SETTINGS)
            _require(unpack("<7H", _one(contents, 0x3D)) == (1, 1, 0, 65535, 65535, 65535, 65535))
            (settings, model_records), = _subgroups(contents, 0x8047)
            _require(unpack("<4i4B6i", settings) == _FIT_OPTIONS)
            models = list(_subgroups(model_records, 0x8048))
            _require(len(models) == 2)
            for _, model in models:
                _require(b"".join(bytes(_one(model, 0x49)).split()).rstrip(b"\0") == _EQUATION)
                _require(all(sha256(_one(model, tag)).hexdigest() == digest for tag, digest in _CONSTRAINTS.items()))
            summary, curve = fit_sheets[producer]
            _require(len({source, summary, curve}) == 3)
            observed = _column(tables[source], source, -1, role=(1, 8, 10, 1))
            _column(tables[summary], summary, producer, role=(2, 8, 12, 1))
            fitted = _column(tables[curve], curve, producer, role=(1, 40, 10, 1))
            graph = views[source, curve]
            _require(graph is not None)
            drawings = _one(graph, 0x16)
            _require(len(drawings) == 26 and unpack_from("<H", drawings)[0] == 2
                     and unpack_from("<i", drawings, 2)[0] == observed
                     and unpack_from("<i", drawings, 14)[0] == fitted)
            band = _band_appearance(graph, producer, summary)
            title = _read_title(_one(graph, 9), encoding)[:160]
        except (IndexError, KeyError, TypeError, ValueError, StructError):
            continue
        recipes = frame.attrs.setdefault("prism_recipes", [])
        if len(recipes) < 256:
            recipes.append(("Nonlinear regression", {
                "X": x, "Y columns": [y], "Grouping variables": [], "Model": LOG_DOSE_MODEL,
                "Weighting": "Unweighted", FIT_INTERVAL_BAND: {**band, "title": title},
                PRISM_TITLE: title,
                PRISM_NOTES: "The shaded region follows the confidence interval of Log EC50.",
            }))
