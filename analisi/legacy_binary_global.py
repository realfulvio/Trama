"""Rebind verified multi-series curve fits to their worksheets and original graphs."""
from dataclasses import dataclass, replace
from struct import error as StructError, unpack, unpack_from

import numpy as np
from pandas import DataFrame
from scipy.special import ndtr

from . import regression_range as rr
from .legacy_binary_dose import _GRAPH_SERIES, _dataset_link, _matching_grid, _model, _sample_settings
from .legacy_binary_editable import (
    _axis_config, _id_array, _one, _project_records, _require, _scene, _series_columns, _subgroups,
)
from .legacy_binary_results import _column_ids, _read_groups
from .legacy_emf_edit import _xy_group_links
from .legacy_fit_graph import FIT_GRAPH_SPEC
from .legacy_restore import LEGACY_GRAPH_LINK, LEGACY_NOTES, LEGACY_TITLE
from .legacy_xml_binding import indexed_analyses
from .presentation import validated_style
from .probability_scale import FRACTION_SCALE, PERCENT_SCALE, PROBABILITY_SCALES
from .repeated_input import _series_name
from .replicate_fit import MERGE_REPLICATES, stack_replicates
from .stats import STARTING_COEFFICIENTS_BY_SERIES


# Only the complete least-squares profile is known here, including common
# baseline, fixed tracer concentrations and independent affinity parameters.
_MODEL = "Allosteric competition"
_PROFILES = {"fda09a3d405a97517309b19d2413bf3aae37c8a7a422d4eb85faed10604a2ed9": _MODEL}
_ASSOCIATION_MULTIPLE = "Association kinetics (multiple ligand concentrations)"
_ASSOCIATION_SINGLE = "Association kinetics (one ligand concentration)"
_ASSOCIATION_MODELS = {_ASSOCIATION_MULTIPLE, _ASSOCIATION_SINGLE}
_KCAT = "Michaelis–Menten (kcat)"
_MORRISON = "Morrison tight-binding inhibition"
_MORRISON_SAVED_POINTS = 10_000
_NONCOMPETITIVE = "Noncompetitive enzyme inhibition"
_MIXED_INHIBITION = "Mixed-model enzyme inhibition"
_SUMMARY_INHIBITION = {
    _NONCOMPETITIVE: (2, ("Vmax", "Km", "Ki")),
    _MIXED_INHIBITION: (4, ("Vmax", "Km", "Ki", "Alpha")),
}
_LOG_LINE_AXES = {
    "Semilog line (log X)": ("log", "linear"),
    "Log-log line": ("log", "log"),
}
_CUMULATIVE_PERCENT = "Cumulative Gaussian (percent)"
_CUMULATIVE_FRACTION = "Cumulative Gaussian (fraction)"
_PROBABILITY_AXES = {_CUMULATIVE_PERCENT: PERCENT_SCALE, _CUMULATIVE_FRACTION: FRACTION_SCALE}
_INDEPENDENT_CURVE_ONLY = _LOG_LINE_AXES.keys() | _PROBABILITY_AXES.keys()
_SEMILOG_CALIBRATION = "7072c5954ac350b00bc2d2ff8af23742715539d23d04c43dc36141e91cd407b8"
_CURVE_ONLY_PROFILES = {
    "70793d39c59909c1092fdcd69ce7b1755da2d81afc0d4c14566e7b1acc4dc21a": _CUMULATIVE_PERCENT,
    "585492a071b986d7ef7d47533e5aace47c908f8dd35e92e9602668016e109747": _CUMULATIVE_FRACTION,
    _SEMILOG_CALIBRATION: "Semilog line (log X)",
    "8910bd7a1f9138e6bdb4c8364bf4d5f00e19d9f24c7ec4fd39af93f0c4b11e7b": _MORRISON,
    "a94c143a7358d76227ef62c6f10ad1c45b0263ceafde8f3eb6b0d6be381a852b": _NONCOMPETITIVE,
    "ecc2bbb8a3e0e31c995ba20eb5726a3af9d75f48f99c0259f82744e5b2542342": _MIXED_INHIBITION,
    "abd5e38d0ea76a364de7d9cfda9aba7b4459133eba3ec3daa56198c57401ec31": _ASSOCIATION_MULTIPLE,
    "2e813a3be32f156857b32bd07eb6ec362c9a8f6171ae52ec459d81b5f07726a3": _ASSOCIATION_SINGLE,
    "64232d060896042ceed14fab12ec6bdc295e7c30ab3b3e2afc628c2014e032aa": _KCAT,
    "6427877c5675a8f7e90f13652e093cba593df347ce4207c22f99fc09aef30112": "Semilog line (log X)",
    "a0d56b5a8943638c994c213a6f4909d64a6266d0e9e87136d6aa7f32949b3af6": "Log-log line",
}
_CURVE_ONLY_MODELS = set(_CURVE_ONLY_PROFILES.values())
_DEPLETION_X = "Operational model (depletion) (concentration X)"
_DEPLETION_LOG_X = "Operational model (depletion) (log10 X)"
_BELL_X = "Bell-shaped dose-response with signed slopes (concentration X)"
_BELL_LOG_X = "Bell-shaped dose-response with signed slopes (log10 X)"
_BELL_MODELS = {_BELL_X, _BELL_LOG_X}
_EC_X = "ECanything (concentration X)"
_EC_LOG_X = "ECanything (log10 X)"
_EC_MODELS = {_EC_X, _EC_LOG_X}
_SHIFT_X = "EC50 shift from control (concentration X)"
_SHIFT_LOG_X = "EC50 shift from control (log10 X)"
_SHIFT_MODELS = {_SHIFT_X, _SHIFT_LOG_X}
_SCHILD_X = "Gaddum/Schild EC50 shift (concentration X)"
_SCHILD_LOG_X = "Gaddum/Schild EC50 shift (log10 X)"
_SCHILD_MODELS = {_SCHILD_X, _SCHILD_LOG_X}
_ALLOSTERIC_X = "Allosteric EC50 shift (concentration X)"
_ALLOSTERIC_LOG_X = "Allosteric EC50 shift (log10 X)"
_ALLOSTERIC_MODELS = {_ALLOSTERIC_X, _ALLOSTERIC_LOG_X}
_DOSE_SERIES_MODELS = _SCHILD_MODELS | _ALLOSTERIC_MODELS
_SPARSE_MODELS = _SHIFT_MODELS | _DOSE_SERIES_MODELS
_LOG_DRAWING_MODELS = {_DEPLETION_X, _BELL_X, _EC_X, _SHIFT_X, _SCHILD_X, _ALLOSTERIC_X}
_FIXED_SCHILD_PROFILES = {
    "ade9befbcd7f193903381e7d5b4cd7208c156a4bcaf9cd680ab00011c525ae06": _SCHILD_X,
    "b21b59994f1bb9f7876511f1b4e1872ae0f84ae1322d00e8478af99b45563b59": _SCHILD_LOG_X,
}
EARLY_GLOBAL_PROFILES = {
    "051a64eca3df3bcb1596b6760f6cee23bf4304167209df7fafc1581116a2babb": _DEPLETION_X,
    "4ba3139b04a84f5cd0da662be8a8bbb680e54d692d9ace9052162f52e3cb3146": _DEPLETION_LOG_X,
    "7a8566026b70236ebf0da2e865bb71aa7f9fa575a513f2ddb6739ac7638cf24c": _BELL_X,
    "87def584540d7750875d3e803a0ed2e2538830717828c29698058fa6d2ec131b": _BELL_LOG_X,
    "e1ed3184c0cea3c8e7dd137a4033f46964f9adf591eefa1a1f79be9808fe978b": _EC_X,
    "d8e720cf9690cb560759fc03006300d68c04e1bf8921c0af71b007f4be2b7dd1": _EC_LOG_X,
    "bd78eaee2c830b0229eadde0750a4fae3e0973c3733f16d0c92bf4e5ecb5ccf9": _SHIFT_X,
    "0c0b33d21bc9cfa12c6f797971ce8e533cee9a0f4a0b3fc9d8af33331fe1ce4b": _SHIFT_LOG_X,
    "c86ddcf19bfd73f5c2fefd3613acbe61201732cce5eb46a0b8f95bf2a77cb21c": _SCHILD_X,
    "739f75ef0b91cbe2cc3dfd3e2ba5b28e618ed9a161d2daa9e39ec1a683f69477": _SCHILD_LOG_X,
    "595f575313834974531a67c8e0e1f87087ce0bf5cdf9e1b3cd40d8e88cd890c4": _ALLOSTERIC_X,
    "c1464d5d5789cd7a22ddbe76ee8077a65ac840ff4f8625ab6e9d8b905bab0e74": _ALLOSTERIC_LOG_X,
    **_FIXED_SCHILD_PROFILES,
}
_METHOD = "Global nonlinear regression"
_UNSUPPORTED = (KeyError, TypeError, ValueError, StructError, OverflowError)


@dataclass(frozen=True)
class Candidate:
    analysis: int
    source_sheet: int
    curve_sheet: int
    report_sheet: int
    frame: DataFrame
    observed: tuple
    fitted: tuple
    options: dict
    companion: bool


def _curve_only_candidate(analysis, records, sources, sheets, snapshots, model):
    count, source = unpack("<2i", _one(records, 0x3B))
    _require(count == 1)
    frame = sources[source]
    _require(frame.attrs.get("table_format") == "xy" and 3 <= len(frame) <= 128 and frame.columns.is_unique)
    summary = model in _SUMMARY_INHIBITION
    if model in _ASSOCIATION_MODELS or summary or model == _MORRISON:
        x, groups = _xy_group_links(frame, [(tag, (), data) for tag, data in sheets[source][0]], link_size=36)
        repeats = 2
    else:
        roles = frame.attrs["worksheet_roles"]
        x, = roles["x"]
        groups = {dataset: (1, names) for dataset, names in zip(_column_ids(sheets[source][0]), roles["y"],
                                                              strict=True)}
        repeats = 1
    count, unused, report, curve, *rest = unpack("<10i", _one(records, 0x3C))
    _require(count == 9 and unused == -1 and set(rest) == {-1}
             and snapshots.get(report) == (analysis, source, 1)
             and snapshots.get(curve) == (analysis, source, 2))
    count = 4 if summary else 2 if model == _ASSOCIATION_MULTIPLE else 1
    selected = _one(records, 0x3D)
    _require(len(selected) == 2 + count * _GRAPH_SERIES.size and unpack_from("<H", selected)[0] == count)
    observed = tuple(_GRAPH_SERIES.iter_unpack(selected[2:]))
    _require(len({link[0] for link in observed}) == count)
    response = []
    for dataset, _, _ in observed:
        repeat, names = groups[dataset]
        _require(repeat == len(names) == repeats)
        if summary:
            mean, sd = names
            _require(mean.endswith(" [Mean]") and sd == mean.removesuffix(" [Mean]") + " [SD]")
            response.append(mean)
        else:
            _require(len({_series_name(name, repeats > 1) for name in names}) == 1)
            response.extend(names)
    fitted = tuple(_dataset_link(sheets[curve], column, 40) for column in _column_ids(sheets[curve][0]))
    _require(len(fitted) == count and all(fitted))
    if model in _ASSOCIATION_MODELS:
        fitted = tuple((dataset, drawing - 1, axis - 1) for dataset, drawing, axis in fitted)
    shared = _SUMMARY_INHIBITION[model][1] if summary else ("Bmax", "Kon", "Koff") if count == 2 else ()
    options = {
        "Input format": "Wide XY", "Model": model, "X": x, "Y columns": response,
        MERGE_REPLICATES: (repeats > 1 and not summary) or model in _INDEPENDENT_CURVE_ONLY,
        "Shared parameters": list(shared),
        LEGACY_NOTES: "Refits the selected observations. The paired original retains its drawing and saved tables.",
    }
    return Candidate(analysis, source, curve, report, frame, observed, fitted, options, False)


def _candidate(analysis, records, sources, sheets, snapshots, early):
    if early:
        source, model, selected = early
        _require(model in EARLY_GLOBAL_PROFILES.values())
    else:
        kind = unpack("<8H", _one(records, 0x3A))
        settings = _one(records, 0x46)
        if (len(settings) == 1348 and kind[:2] == (0, 5) and kind[3] in (0, 1)
                and kind[4:] == (255, 1, 65535, 0)
                and (curve_only := _model(records, settings, _CURVE_ONLY_PROFILES))):
            if curve_only == _KCAT:
                profile = (8, 0)
            elif curve_only == _MORRISON:
                profile = (9, 0)
            elif curve_only in _LOG_LINE_AXES:
                # The calibration profile's local equation numbers can differ from its analysis ID.
                calibration = _model(records, settings, {_SEMILOG_CALIBRATION: True})
                profile = (16 if calibration else analysis + 1, 1)
            elif curve_only in _PROBABILITY_AXES:
                profile = (6 if curve_only == _CUMULATIVE_PERCENT else 7, 1)
            elif curve_only in _SUMMARY_INHIBITION:
                profile = (_SUMMARY_INHIBITION[curve_only][0], 1)
            else:
                profile = (analysis, int(curve_only == _ASSOCIATION_MULTIPLE))
            _require(kind[2:4] == profile)
            return _curve_only_candidate(analysis, records, sources, sheets, snapshots, curve_only)
        _require(kind[:2] == (0, 5) and kind[3:] == (1, 127, 1, 65535, 65535))
        model = _model(records, settings, _PROFILES) if len(settings) == 1348 else None
        _require(model == _MODEL)
        count, source = unpack("<2i", _one(records, 0x3B))
        _require(count == 1)
        selected = _one(records, 0x3D)
    frame = sources[source]
    responses = 5 if model in _DOSE_SERIES_MODELS else 1 if model in _EC_MODELS else 2
    _require(frame.attrs.get("table_format") == "xy" and 3 <= len(frame) <= 250_000
             and len(frame.columns) == responses + 1 and frame.columns.is_unique)
    x, *response = frame.columns
    _require(frame.attrs.get("worksheet_roles") == {"x": [x], "y": [[name] for name in response]})

    count, unused, report, curve, *rest = unpack("<10i", _one(records, 0x3C))
    if early and rest[0] >= 0:
        residual, *rest = rest
        _require(residual not in sources and sheets.get(residual) is not None
                 and (residual not in snapshots or snapshots[residual] == (analysis, source, 3)))
    _require(count == 9 and unused == -1 and set(rest) == {-1}
             and snapshots.get(report) == (analysis, source, 1)
             and snapshots.get(curve) == (analysis, source, 2))
    _require(len(selected) == 2 + responses * _GRAPH_SERIES.size and unpack_from("<H", selected)[0] == responses)
    observed = tuple(_GRAPH_SERIES.iter_unpack(selected[2:]))
    _require(tuple(link[0] for link in observed) == _column_ids(sheets[source][0]))
    fitted = tuple(_dataset_link(sheets[curve], column, 40) for column in _column_ids(sheets[curve][0]))
    _require(len(fitted) == responses and all(fitted))
    if early:
        # The companion layout numbers its drawing slots from zero.
        fitted = tuple((dataset, y - 1, axis - 1) for dataset, y, axis in fitted)
        if model in _BELL_MODELS:
            scope = {MERGE_REPLICATES: True, "Grouping variables": []}
        elif model in _EC_MODELS:
            scope = {}
        elif model in _SHIFT_MODELS:
            midpoint = "EC50 control" if model == _SHIFT_X else "Log EC50 control"
            scope = {
                "Shared parameters": ["Bottom", "Top", midpoint, "Hill slope"],
                "Series constraints": [{"series": response[0], "parameters": {"EC50 ratio": {"fixed": 1.}}}],
            }
        elif model in _SCHILD_MODELS:
            midpoint = "EC50" if model == _SCHILD_X else "Log EC50"
            shared = ["Bottom", "Top", midpoint, "Hill slope", "pA2"]
            fixed = _model(records, _one(records, 0x46), _FIXED_SCHILD_PROFILES) == model
            scope = {"Shared parameters": shared, LEGACY_NOTES: "Refits the original observations. "
                     "The saved tables, arrow and annotation remain in the paired original."}
            if fixed:
                scope["Fixed parameters"] = {"Schild slope": 1.0}
            else:
                shared.append("Schild slope")
        elif model in _ALLOSTERIC_MODELS:
            prefix = "Log " if model == _ALLOSTERIC_LOG_X else ""
            scope = {
                "Shared parameters": ["Top", "Hill slope", *(prefix + name for name in ("EC50", "KB", "Alpha"))],
                LEGACY_NOTES: "Refits the original observations. The paired original retains the saved arrow.",
            }
        else:
            affinity = "KA" if model == _DEPLETION_X else "Log KA"
            scope = {"Shared parameters": ["Basal", "Effect max", affinity, "Transducer slope"]}
    else:
        scope = {
            "Shared parameters": ["Y0"], "Fixed parameters": {"Hot (nM)": 1.0, "Hot Kd (nM)": 1.0},
            "Initial values": {"Log KB": -7},
            # Seed the declining and rising series separately. Fit the estimates from the observations.
            "Series constraints": [{"series": name, "parameters": {"Log alpha": {"initial": start}}}
                                   for name, start in zip(response, (-1, 1), strict=True)],
        }
    return Candidate(analysis, source, curve, report, frame, observed, fitted, {
        "Input format": "Wide XY", "Model": model, "X": x, "Y columns": response, MERGE_REPLICATES: False,
        LEGACY_NOTES: "Refits the curves from the original observations. "
                      "The original graph and saved result tables remain available.",
        **scope,
    }, bool(early))


def global_candidates(data, sources, sheets, snapshots, pending, *, early_inputs=None):
    early_inputs = early_inputs or {}
    possible = {analysis for analysis, source, slot in filter(None, snapshots.values())
                if analysis in pending and slot == 2 and source in sources
                and (len(sources[source].columns) in (2, 3, 5, 9) or analysis in early_inputs)}
    if not possible:
        return {}
    try:
        _, analyses = indexed_analyses(data)
    except _UNSUPPORTED:
        return {}
    recovered = {}
    for analysis, _, _, records in analyses:
        if analysis not in possible:
            continue
        try:
            candidate = _candidate(analysis, records, sources, sheets, snapshots, early_inputs.get(analysis))
        except _UNSUPPORTED:
            continue
        key = candidate.source_sheet, candidate.curve_sheet
        recovered[key] = None if key in recovered else candidate
    return recovered



def _bell_starts(candidate, report):
    """Read the seven saved estimates as series-specific starting values."""
    logarithmic = candidate.options["Model"] == _BELL_LOG_X
    old_mid = "LogEC50" if logarithmic else "EC50"
    new_mid = "Log EC50" if logarithmic else "EC50"
    labels = {"Plateau1": "Plateau 1", "Dip": "Dip", "Plateau2": "Plateau 2",
              f"{old_mid}_1": f"{new_mid} 1", "nH1": "Hill slope 1",
              f"{old_mid}_2": f"{new_mid} 2", "nH2": "Hill slope 2"}
    _require(report.shape[0] >= 2 + len(labels) and report.shape[1] == 3 and report.iat[1, 0] == "Best-fit values")
    values = report.iloc[2:2 + len(labels)]
    _require([str(label).strip() for label in values.iloc[:, 0]] == list(labels))
    return {series: {name: float(value) for name, value in zip(labels.values(), values.iloc[:, position], strict=True)}
            for position, series in enumerate(candidate.options["Y columns"], 1)}


def _fixed_fraction(report):
    _require(report.shape[1] == 2 and len(report) > 2 and report.iat[1, 0] == "Best-fit values")
    fitted, constraint = (str(value).strip() for label, value in report.itertuples(index=False, name=None)
                          if str(label).strip() == "F")
    _require(fitted.startswith("=") and constraint.startswith("F ="))
    value = float(fitted[1:])
    _require(0 < value < 100 and value == float(constraint[3:]))
    return {"F": value}


def _log_line_starts(candidate, report):
    _require(report.shape[1] == 2 and len(report) >= 4 and report.iat[1, 0] == "Best-fit values")
    estimates = {str(name).strip().lower(): value for name, value in report.iloc[2:4].itertuples(index=False)}
    _require(estimates.keys() == {"yintercept", "slope"})
    intercept, slope = float(estimates["yintercept"]), float(estimates["slope"])
    _require(np.isfinite([intercept, slope]).all())
    series, = candidate.options["Y columns"]
    return {series: {"Intercept": intercept, "Slope": slope}}


def _cumulative_starts(candidate, report):
    _require(report.shape[1] == 2 and len(report) >= 4 and report.iat[1, 0] == "Best-fit values"
             and [str(name).strip() for name in report.iloc[2:4, 0]] == ["Mean", "SD"])
    mean, sd = map(float, report.iloc[2:4, 1])
    _require(np.isfinite([mean, sd]).all() and sd > 0)
    series, = candidate.options["Y columns"]
    return {series: {"Mean": mean, "SD": sd}}


def _fixed_concentration_constraints(report, response):
    """Match saved fixed concentrations to the selected response columns."""
    _require(report.columns[1:-1].tolist() == response)
    return [{"series": name, "parameters": {"B": {"fixed": value}}}
            for name, value in zip(response, _saved_fixed_values(report, "B", len(response)), strict=True)]


def _saved_fixed_values(report, name, count):
    _require(len(report) > 2 and report.iat[1, 0] == "Best-fit values")
    fitted, constrained = (values[:count] for label, *values in report.itertuples(index=False, name=None)
                           if str(label).strip() == name)
    prefix = f"{name} ="
    values = []
    for estimate, setting in zip(fitted, constrained, strict=True):
        estimate, setting = str(estimate).strip(), str(setting).strip()
        _require(estimate.startswith("=") and setting.startswith(prefix))
        value = float(setting[len(prefix):])
        _require(np.isfinite(value) and value >= 0 and value == float(estimate[1:]))
        values.append(value)
    _require(len(values) == count)
    return values


def _verify_drawing(candidate, samples, scene, axes, grid, *, logarithmic, starts=None, fixed=None):
    """Verify estimates against both the saved result table and the drawing."""
    from .curve_models import MODELS
    from .global_fit import global_nonlinear
    from .repeated_input import curve_input, decode_series_constraints
    from .stats import nonlinear

    minimum, maximum, points = (grid[field] for field in rr.CURVE_FIELDS)
    _require(minimum < maximum and (not logarithmic or minimum > 0) and len(candidate.frame) <= 128
             and points <= rr.MAX_POINTS)
    opts = candidate.options
    model = opts["Model"]
    stored_count = len(samples) if model == _MORRISON else points
    _require(all(len(scene[dataset]) == stored_count for dataset, _, _ in candidate.fitted))
    if starts is None:
        frame, _, _, _ = curve_input(candidate.frame, opts)
        fits = global_nonlinear(frame, "X", "Response", model, "Series",
                                shared=opts.get("Shared parameters", ()), fixed=fixed,
                                series_constraints=decode_series_constraints(opts.get("Series constraints", []))).groups
    else:
        frame = stack_replicates(candidate.frame, opts)
        fits = nonlinear(frame, "X", "Response", model, "Series", series_start=starts)
    x = np.geomspace(minimum, maximum, points) if logarithmic else samples[:, 0]
    names = dict.fromkeys(_series_name(name, opts.get(MERGE_REPLICATES, False)) for name in opts["Y columns"])
    for position, (series, (dataset, _, _)) in enumerate(zip(names, candidate.fitted, strict=True), 1):
        estimates = fits[series].parameters["Estimate"]
        predicted = MODELS[model].equation(samples[:, 0], *estimates)
        _require(np.allclose(predicted, samples[:, position], rtol=1e-6, atol=1e-6))
        plotted = MODELS[model].equation(x, *estimates)
        _require(_matching_grid(scene[dataset], np.column_stack((x, plotted)), axes, high_anchored=True))
        if stored_count != points:
            # The editable line must still agree with the archived drawing between its samples.
            preview_x = rr.drawing_grid(x, grid)
            preview_y = MODELS[model].equation(preview_x, *estimates)
            interpolated = np.interp(x, preview_x, preview_y)
            _require(_matching_grid(scene[dataset], np.column_stack((x, interpolated)), axes, high_anchored=True))
    return {**grid, "spacing": "log" if logarithmic else "linear"}


def _matching_observations(cache, values, axes):
    """A missing response has a drawing placeholder or is omitted after the last point."""
    present = np.isfinite(values[:, 1])
    length = len(cache)
    if length > len(values) or present[length:].any() or not present.any():
        return False
    visible = present[:length]
    return bool(np.all(cache[~visible] == -1) and
                _matching_grid(cache[visible], values[present], axes, high_anchored=True))


def _curve_only_graph(candidate, source_records, curve, report, graph, encoding, *, starts=None, invisible=None):
    model = candidate.options["Model"]
    summary = model in _SUMMARY_INHIBITION
    source_headers = [(payload, ()) for tag, _, payload in source_records if tag == 0x800F]
    for position, (dataset, drawing, axis) in enumerate(candidate.observed):
        source = _dataset_link((None, source_headers), dataset, 8)
        _require(source is not None and drawing == source[1])
        revisions = (source[2],) if position == 0 else (-1, source[2]) if summary else (-1,)
        _require(axis in revisions)
    merge = candidate.options[MERGE_REPLICATES]
    names = list(dict.fromkeys(_series_name(column, merge) for column in candidate.options["Y columns"]))
    saved_names = [name.removesuffix(" [Mean]") for name in names] if summary else names
    count = len(candidate.fitted)
    _require(count == len(names) and list(curve.columns) == [candidate.options["X"], *saved_names])
    fixed = {}
    if summary:
        _require(report.columns[1:1 + count].tolist() == saved_names)
        concentrations = _saved_fixed_values(report, "I", count)
        constraints = [{"series": name, "parameters": {"Inhibitor": {"fixed": value}}}
                       for name, value in zip(names, concentrations, strict=True)]
        notes = "Refits the original response means without weighting. The SD columns remain available in the worksheet."
        if model == _NONCOMPETITIVE:
            notes += " The paired original retains the annotation."
        candidate = replace(candidate, options={**candidate.options, "Series constraints": constraints,
                                                LEGACY_NOTES: notes})
    elif model == _MORRISON:
        _require(report.shape[1] == 2)
        fixed = {name: _saved_fixed_values(report, saved, 1)[0]
                 for name, saved in (("Et", "Et"), ("Substrate", "S"), ("Km", "Km"))}
        _require(fixed["Et"] > 0 and fixed["Km"] > 0)
        candidate = replace(candidate, options={**candidate.options, LEGACY_NOTES: (
            "Refits the original replicates. The editable graph uses up to 2,000 points. "
            "The original graph and its 10,000-point result table remain available."
        )})
    elif model not in _INDEPENDENT_CURVE_ONLY:
        _require(report.columns[1:1 + count].tolist() == names)
        parameter = "Et" if model == _KCAT else "Hotnm"
        concentrations = _saved_fixed_values(report, parameter, count)
        _require(all(value > 0 for value in concentrations))
        if model == _KCAT:
            fixed = {"Et": concentrations[0]}
        elif model == _ASSOCIATION_SINGLE:
            rate, = _saved_fixed_values(report, "Koff", 1)
            _require(rate > 0)
            fixed = {"Koff": rate, "Hot (nM)": concentrations[0]}
        else:
            constraints = [{"series": name, "parameters": {"Hot (nM)": {"fixed": value}}}
                           for name, value in zip(names, concentrations, strict=True)]
            candidate = replace(candidate, options={**candidate.options, "Series constraints": constraints})

    links = _one(graph, 0x16)
    order = set(_id_array(_one(graph, 0x15)))
    _require(len(links) == 2 + len(order) * _GRAPH_SERIES.size and unpack_from("<H", links)[0] == len(order))
    saved = set(_GRAPH_SERIES.iter_unpack(links[2:]))
    empty_keys = ()
    if model == _ASSOCIATION_SINGLE and saved - set(candidate.fitted) == {(-1, -1, 40)}:
        saved.remove((-1, -1, 40))
        (_, scene), = _subgroups(graph, 0x8018)
        keys = []
        for object_header, records in _subgroups(scene, 0x8020):
            if unpack_from("<H", object_header)[0] != 9:
                continue
            key, _, dataset = unpack_from("<3H", _one(records, 0x8028))
            if dataset == 0xFFFD:
                keys.append(key)
        empty_keys = tuple(keys)
        _require(len(empty_keys) == 1)
    _require(saved == set(candidate.fitted) | ({invisible[0]} if invisible else set()))
    texts, _, _, scene = _scene(graph, encoding, empty_series=empty_keys, empty_drawing=0x88,
                               curve_drawing=0x80 if model == _MORRISON else 0x88,
                               annotated=model == _NONCOMPETITIVE)
    probability = _PROBABILITY_AXES.get(model)
    axes = _axis_config(graph, viewport_only=True, probability_y=probability)
    scales = _LOG_LINE_AXES.get(model, ("linear", probability or "linear"))
    _require(set(scene) | set(empty_keys) == order and len(scene) == count + int(invisible is not None)
             and set(dataset for dataset, _ in scene.values()) == {link[0] for link in saved}
             and tuple(axis["scale"] for axis in axes) == scales)
    if invisible:
        link, points = invisible
        cache = dict(scene.values())[link[0]]
        _require(len(cache) == points and np.all(cache == -1))
        candidate = replace(candidate, options={**candidate.options, LEGACY_NOTES: (
            "Refits the original response data. The paired original retains the saved out-of-scale function."
        )})
    samples = curve.to_numpy(dtype=float, na_value=np.nan)
    _require(np.isfinite(samples).all())
    if model == _MORRISON:
        x = samples[:, 0]
        lo, hi = float(x[0]), float(x[-1])
        _require(len(x) == _MORRISON_SAVED_POINTS and lo == 0 < hi
                 and np.allclose(x, np.linspace(lo, hi, len(x)), rtol=0., atol=8 * np.finfo(float).eps * hi))
        grid = rr.ranges({rr.CURVE_MIN: lo, rr.CURVE_MAX: hi, rr.CURVE_POINTS: rr.MAX_POINTS, "Model": model})
    else:
        grid = _sample_settings(curve.iloc[:, :2], candidate.options)
    grid = _verify_drawing(candidate, samples, dict(scene.values()), axes, grid,
                           logarithmic=scales[0] == "log", fixed=fixed, starts=starts)
    style = {"legend": "hidden", "axis": {}}
    for dim, axis in zip("xy", axes, strict=True):
        low, high = axis["bounds"]
        style[dim + "scale"] = axis["scale"]
        if axis["scale"] == "log":
            low, high = 10. ** low, 10. ** high
        elif axis["scale"] in PROBABILITY_SCALES:
            low, high = (float(value) for value in ndtr([low, high]) * PROBABILITY_SCALES[axis["scale"]])
        style["axis"][dim] = {"min": low, "max": high}
        if axis["title"] in texts:
            style[dim + "label"] = texts[axis["title"]]
    return candidate, fixed, grid, validated_style(style)


def _graph_binding(candidate, source_records, curve, graph, encoding, *, starts=None, fixed=None, curve_only=False):
    source, frame = candidate.source_sheet, candidate.frame
    _require(curve.columns.equals(frame.columns))
    data = frame.to_numpy(dtype=float, na_value=np.nan)
    samples = curve.to_numpy(dtype=float, na_value=np.nan)
    model = candidate.options["Model"]
    sparse = model in _SPARSE_MODELS
    _require(np.isfinite(samples).all() and np.isfinite(data[:, 0]).all()
             and (not np.isinf(data).any() if sparse else np.isfinite(data).all()))
    columns = _series_columns(source, source_records, frame, -1)
    raw_headers = [(payload, ()) for tag, _, payload in source_records if tag == 0x800F]
    observed = []
    for position, (dataset, drawing, axis) in enumerate(candidate.observed, start=1):
        _require(columns[dataset][2:] == (0, position))
        if candidate.companion:
            axis_slots = (0,) if position == 1 else (-1, -65536)
            _require(drawing == 0 and axis in axis_slots)
            observed.append((dataset, 0, 0))
        else:
            link = _dataset_link((None, raw_headers), dataset, 8)
            _require(link is not None and link[1] == drawing and axis in (link[2], -1))
            observed.append(link)
    if curve_only:
        observed.clear()
    series_count = len(observed) + len(candidate.fitted)
    links = _one(graph, 0x16)
    _require(len(links) == 2 + series_count * _GRAPH_SERIES.size and unpack_from("<H", links)[0] == series_count)
    graph_links = set(_GRAPH_SERIES.iter_unpack(links[2:]))
    observed_links = set(observed)
    # Saved companions can number the drawing slots differently. Both
    # fields shift together, while dataset ownership stays exact.
    offsets = (-1, 0, 1) if model in _SCHILD_MODELS else (0,)
    _require(any(graph_links == observed_links | {(dataset, drawing + offset, axis + offset)
                                                   for dataset, drawing, axis in candidate.fitted}
                 for offset in offsets))
    expected = {link[0]: values[:, [0, position]]
                for group, values in ((observed, data), (candidate.fitted, samples))
                for position, link in enumerate(group, start=1)}
    _require(len(expected) == series_count)
    texts, _, _, scene = _scene(graph, encoding, observation_ids={link[0] for link in observed},
                               annotated=model in _DOSE_SERIES_MODELS)
    order = _id_array(_one(graph, 0x15))
    axes = _axis_config(graph, viewport_only=True)
    logarithmic = model in _LOG_DRAWING_MODELS
    scales = ["log" if logarithmic else "linear", "linear"]
    _require(len(order) == len(scene) == series_count and set(order) == set(scene)
             and {dataset for dataset, _ in scene.values()} == expected.keys()
             and [axis["scale"] for axis in axes] == scales)
    cached = dict(scene.values())
    _require(all(_matching_observations(cached[dataset], expected[dataset], axes)
                 for dataset, _, _ in observed))
    grid = _sample_settings(curve.iloc[:, :2], candidate.options)
    if starts is not None or fixed is not None or sparse:
        grid = _verify_drawing(candidate, samples, cached, axes, grid, logarithmic=logarithmic,
                               starts=starts, fixed=fixed)
    elif not all(_matching_grid(cached[dataset], expected[dataset], axes, high_anchored=True)
                 for dataset, _, _ in candidate.fitted):
        _require(model == _DEPLETION_X)
        grid = _verify_drawing(candidate, samples, cached, axes, grid, logarithmic=True)
    style = {"axis": {}}
    if curve_only:
        style["legend"] = "hidden"
    for dim, axis in zip("xy", axes, strict=True):
        if axis["title"] in texts:
            style[dim + "label"] = texts[axis["title"]]
        values = [table[:, 0] if dim == "x" else table[:, 1:] for table in (data, samples)]
        lower, upper = axis["bounds"]
        style[dim + "scale"] = axis["scale"]
        if axis["scale"] == "log":
            lower, upper = 10. ** lower, 10. ** upper
        # The outermost tick need not be the edge of the archived drawing.
        if all(np.nanmin(values_) >= lower and np.nanmax(values_) <= upper for values_ in values):
            style["axis"][dim] = {"min": lower, "max": upper}
    return grid, validated_style(style)


def _invisible_probability_overlay(result, sheet):
    """The paired drawing preserves a horizontal trace outside its fractional range."""
    _require(len(result.columns) == 2 and 3 <= len(result) <= 10_000
             and not result.attrs["legacy_binary_result"]["source_ids"])
    x, y = result.to_numpy(dtype=float).T
    _require(np.isfinite(x).all() and np.isfinite(y).all() and np.all(np.diff(x) > 0)
             and y[0] >= 1. and np.all(y == y[0]))
    column, = _column_ids(sheet[0])
    link = _dataset_link(sheet, column, 40)
    _require(link is not None)
    return link, len(result)


def restore_global_graphs(data, graphs, graph_links, candidates, result_frames):
    """Attach a fit only when every saved series and its ownership can be verified."""
    if not any(candidates.values()):
        return set(), set()
    try:
        table_ids = {source for source, _ in candidates}
        _, encoding, records, sources = _project_records(data, table_ids)
        fractions = {candidate.curve_sheet: candidate for candidate in candidates.values()
                     if candidate and candidate.options["Model"] == _CUMULATIVE_FRACTION}
        sheets = _read_groups(data)[1] if fractions else {}
    except _UNSUPPORTED:
        return set(), set()
    restored, analyses = set(), set()
    for graph in graphs:
        uid = graph["id"]
        try:
            members = _id_array(_one(records[uid], 0x14))
            _require(len(members) == len(set(members)) in (1, 2))
            curve_only = len(members) == 1
            invisible = None
            if not curve_only and (fraction := fractions.get(members[0])) and members[1] in result_frames:
                overlay = members[1]
                invisible = _invisible_probability_overlay(result_frames[overlay], sheets[overlay])
                matches = [fraction]
                curve_only = True
            elif curve_only:
                matches = [candidate for candidate in candidates.values()
                           if candidate and candidate.curve_sheet == members[0]
                           and candidate.options["Model"] in _CURVE_ONLY_MODELS | {_EC_LOG_X, _ALLOSTERIC_LOG_X}]
            else:
                matches = [candidates[key] for key in (tuple(members), tuple(reversed(members))) if candidates.get(key)]
            candidate, = matches
            if candidate.analysis in analyses:
                continue
            recipes = candidate.frame.attrs.get("legacy_recipes", [])
            _require(len(recipes) < 256)
            model = candidate.options["Model"]
            independent = model in _BELL_MODELS or model in _INDEPENDENT_CURVE_ONLY
            starts = None
            if model in _BELL_MODELS:
                starts = _bell_starts(candidate, result_frames[candidate.report_sheet])
            elif model in _LOG_LINE_AXES:
                starts = _log_line_starts(candidate, result_frames[candidate.report_sheet])
            elif model in _PROBABILITY_AXES:
                starts = _cumulative_starts(candidate, result_frames[candidate.report_sheet])
            fixed = _fixed_fraction(result_frames[candidate.report_sheet]) if model in _EC_MODELS else None
            if model in _DOSE_SERIES_MODELS:
                report = result_frames[candidate.report_sheet]
                response = candidate.options["Y columns"]
                constraints = _fixed_concentration_constraints(report, response)
                candidate = replace(candidate, options={**candidate.options, "Series constraints": constraints})
                fixed = candidate.options.get("Fixed parameters")
                if model in _ALLOSTERIC_MODELS:
                    _require(set(_saved_fixed_values(report, "Bottom", len(response))) == {0.0})
                    fixed = {"Bottom": 0.0}
            if model in _CURVE_ONLY_MODELS:
                _require(curve_only)
                candidate, fixed, grid, style = _curve_only_graph(
                    candidate, sources[candidate.source_sheet], result_frames[candidate.curve_sheet],
                    result_frames[candidate.report_sheet], records[uid], encoding, starts=starts, invisible=invisible,
                )
            else:
                grid, style = _graph_binding(candidate, sources[candidate.source_sheet],
                                             result_frames[candidate.curve_sheet], records[uid], encoding,
                                             starts=starts, fixed=fixed, curve_only=curve_only)
            ranges = {key: grid[key] for key in rr.CURVE_FIELDS}
            options = {**candidate.options, LEGACY_TITLE: graph["title"][:150] + " · Linked",
                       LEGACY_GRAPH_LINK: graph_links[uid], FIT_GRAPH_SPEC: {
                           "model": model, "x": candidate.options["X"],
                           "series": candidate.options["Y columns"],
                           **ranges,
                           "spacing": grid.get("spacing", "linear"),
                       }}
            if fixed is not None:
                options["Fixed parameters"] = fixed
            if curve_only:
                options[FIT_GRAPH_SPEC]["observations"] = False
            method = _METHOD
            if independent:
                method = "Nonlinear regression"
                options.pop("Input format")
                options.update(ranges)
                options[STARTING_COEFFICIENTS_BY_SERIES] = starts
        except _UNSUPPORTED:
            continue
        candidate.frame.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
        candidate.frame.attrs.setdefault("legacy_recipes", []).append((method, options))
        restored.add(uid)
        analyses.add(candidate.analysis)
    return restored, analyses
