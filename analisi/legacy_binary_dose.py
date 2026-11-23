"""Restore single-series dose fits, normalization and linked curves from PCFFGRA4 projects."""
from hashlib import sha256
from struct import Struct, error as StructError, pack, unpack, unpack_from

import numpy as np
from scipy.special import ndtri
import pandas as pd

from pandas.api.types import is_numeric_dtype

from . import regression_range as rr, stats
from .legacy_binary import _DATASET, _record_once
from .legacy_binary_editable import _axis_config, _id_array, _one, _project_records, _require, _scene, _subgroups
from .legacy_binary_results import _column_ids, _title
from .legacy_fit_graph import FIT_GRAPH, FIT_GRAPH_OBSERVATIONS, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC
from .legacy_restore import LEGACY_GRAPH_LINK, LEGACY_NOTES, LEGACY_TITLE, SAVED_XY, _append_linked_recipe
from .legacy_xml_binding import indexed_analyses
from .presentation import validated_style
from .probability_scale import PROBABILITY_SCALES
from .reference_normalization import INDEPENDENT, KEEP, MAXIMUM, METHOD, MINIMUM, NORMALIZED, PERCENTAGES, RAW


# Verified profiles include the solver settings and the entire model/constraint group.
# A different equation, weight, constraint or confidence setting needs separate verification.
_PROFILES = {
    "f04c3279ac8c191d88a9b747caa6225c7a68f6b3260b363a3c455de683ab13b0": "Inhibition (standard slope)",
    "32556fad554e88638605b30435ee5b4ba6495db2b59308adddfed7aab388f049": "Inhibition (standard slope, log10 X)",
    "5c57872f1692212ed2e23cb874b3e7b0792883497b4dafb58dc0e9e2d03b49a6": "Inhibition (variable slope)",
    "6818de067ac49d738c94a7ee479e46b2757b27b2fc07fc07b0d2e547bd197f8a": "Inhibition (variable slope, log10 X)",
    "d5fc64ab35abc09358f75b3ef828b6bf586ca4553082a24fd406e48810fee521": "Normalized inhibition (standard slope)",
    "73a4cc22b914eee060d646bd2acd79afd73a9ab0d8480392f2346980b489c5ab": "Normalized inhibition (standard slope, log10 X)",
    "115d1d8bca767633a765e81dbc50a3a74e2c8039b94eb55ed50754133ba37392": "Normalized inhibition (variable slope)",
    "2fdead24263eced73f71ad2ed981f6f0c24601060f42eac5ba5b3db684d36240": "Normalized inhibition (variable slope, log10 X)",
    "6077a82968fd7453abbea87b063262374ebd4ba793cdd32ae3c76e92c57a9587": "Normalized stimulation (standard slope)",
    "608d8dc4c27c67916273e8cf58d50dc078dd54120426881f0b891ad7784a88ae": "Normalized stimulation (standard slope, log10 X)",
    "d4c87fd18a867d685897b3e170df5dc2872fd2ccc329335c072106d67112af08": "Normalized stimulation (variable slope)",
    "0316c927f25f1e263fd4e02a73dcd98cdc477e9e06d322030ee8d78a2a994054": "Normalized stimulation (variable slope, log10 X)",
    "b12a5f1ed9a19db12ebbe9d21f526caa895bf78930d31ad14f1c35a5561fe060": "Stimulation (standard slope)",
    "fcdfb5b6bfd1430f453779c4628ef39d0482aff1e7d3fd1e07dfa5be0c0d1094": "Stimulation (standard slope, log10 X)",
    "fc1206fa4cce5e0ce81bb87adc3a4f854f42d16ec84e989b1f70b32086faa47e": "Stimulation (variable slope)",
    "12c8a0eef04bef32a03fc27dbe027a46af7015d94422cdf248f99ca3c57dbfa3": "Stimulation (variable slope, log10 X)",
}
_NORMALIZATIONS = {
    "11a6a5f92e1e06d0ccd3b39278046970dd922142635b33e6d3aa3fa511141f84",
    "d1cdccc48615e7d72dddd3368637a8eed01f4af74fdb57e2b0be5a7acadc595d",
}
_BIPHASIC_PROFILES = {
    "dc3fc420ab207688d846606d6fcd2bb88f699bd509932f43a537acc3f89e16aa": "Biphasic dose-response (concentration X)",
    "af7eed14d291c937bddb125ddcc1cd9fc65964b4e4aab734463f5dacee7510e6": "Biphasic dose-response (log10 X)",
}
_CALIBRATION_POLYNOMIALS = {
    "7db973bdf5567b217bc1c9b5bd49297cf4cc86803e1aaf888e0c9aa9dd9185c4": "Polynomial (order 2)",
    "a1fbe90d9874e4694a062fb09305c78f6f5143d4838fcca50f3aca9a0159a512": "Polynomial (order 3)",
}
_CALIBRATION_PROFILES = {
    **_CALIBRATION_POLYNOMIALS,
    "b08e5e2f3ed686173631fc329a4a41d51315f3c6a5427bbf49f7f16bb0451142": "Stimulation (variable slope, log10 X)",
    "fc0d53b1d95f29c2642811d8ae9b4f352087d40f89ba252d2d81f9ee39aff5d1": "Asymmetric dose-response (log10 X)",
}


# Earlier indexed fits include their source drawing IDs in the analysis selection.
_CLASSIC_PROFILES = {
    "5db328633de62186aba20601607e2559d26297def50a645be6924ac001985199": "One-site specific binding",
    "613e84a3a0422db2a705102f75c546be14d47edd556bfc4b99c94da503dc1823": "Two-site specific binding",
    "98d3e06b7d32ec0a1ef05ac98f4d75a61202f4d0a6a7feba4ceeb2979f4ff019": "Stimulation (standard slope, log10 X)",
    "348b97875353cc94896885dd19a76e69d404897423702022b5129f60c6aab15e": "Stimulation (variable slope, log10 X)",
    "5e0f97c1d233c9fda6d90ddb45a08741d32d5d74ca68962c2a527a431a5d1a58": "One-site competition (log IC50)",
    "0bbfda213dc4f566976b5512b9e73de36c8078b0415848a65788fae9bad66045": "Two-site competition (log IC50)",
    "87aea3ae6438b9495f82bb96a1e7f8bf86ed4b599d4ae5c10e3d3bbff8de43cd": "Boltzmann sigmoid",
    "7529fda17591bef4f26b91bd7e131cdb8fa67572aca922836932db3ee887a35b": "One-phase decay",
    "0f767bf231fccf164f5dc01be404c888eaf7070f0c0bdc6e7f0325c2f8b600f5": "Classic one-phase association",
    "bd585b2f2a28970a75622297cdb46d15aa358b5039575328183d89b191ab8740": "Classic two-phase association",
    "c71fc7826a74d64b56f891af650903fd10da4d0936c02659cc122426c2e1f68b": "Exponential growth",
    "00ac65c978ec925b299c2b6780df487cfed23a2bd68ec356fba76dabaca13a1c": "Polynomial (order 1)",
    "828e5beab032b3930a185841d4d76d098c5029ae152f56ffaacae313798771ba": "Polynomial (order 2)",
    "b7c455fd011af0ed01cbfdd6fa8c7ff0cb4dcbbbeadc02b6c52b390b4232c891": "Polynomial (order 3)",
    "807b95e91e88a76eca0772c6a3854e82077522d2ef0d40db9e8c05cf43a0b502": "Polynomial (order 4)",
    "bf33db03caf44f656909c5f7ad988f9a4cb693945233533fd34fd0d0843a99ed": "Classic sine wave (angular frequency)",
    "53d16027c57ab68c84e58358e438b795e0900340e190623d7c7fa94d4a68704c": "Classic Gaussian (area)",
    "ec7d62ee3622e63da2511d82b9c0213d9790378fdafc9a9d1c04317879cd6de9": "Classic two-phase decay",
    "28c4d689a2a0b9b1da09ed38b8d85ebd50e3c28fc930993cfb0f4afc92e143bc": "Power series",
}
# Positive rates and fractions are bounded by the native models. Keep the saved
# equalities and seed symmetric terms in the order used in their saved reports.
_CLASSIC_COEFFICIENTS = {
    "Two-site specific binding": ({"Bmax 1": 100., "Bmax 2": 100.}, {"Kd 1": .5, "Kd 2": 50.}),
    "One-phase decay": ({"Span": 90., "Plateau": 10.}, {"Rate": .8}),
    "Classic two-phase association": ({"Y max 1": 100., "Y max 2": 100.}, {"K1": .1, "K2": .5}),
    "Power series": ({"A": 1., "C": 1.}, {"B": 3., "D": .2}),
}


def _model(records, settings, profiles):
    (header, contents), = _subgroups(records, 0x8047)
    fingerprint = sha256(settings)
    fingerprint.update(pack("<I", len(header)))
    fingerprint.update(header)
    for tag, parents, data in contents:
        fingerprint.update(pack("<H", len(parents)))
        for parent in parents:
            fingerprint.update(pack("<H", parent))
        fingerprint.update(pack("<HI", tag, len(data)))
        fingerprint.update(data)
    return profiles.get(fingerprint.hexdigest())


def classic_fit_models(data):
    """Recognize the complete archived equation, solver and constraint profile."""
    try:
        _, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        return {}
    models = {}
    for uid, _, kind, records in analyses:
        if kind[:2] != (0, 5):
            continue
        try:
            settings = _one(records, 0x46)
            if len(settings) != 1348:
                continue
            # The calibration profile's third field is a local model number.
            if (kind[3:] == (1, 255, 1, 65535, 0)
                    and (model := _model(records, settings, _CALIBRATION_PROFILES))):
                models[uid] = model, True
            elif (kind in ((0, 5, uid, 1, 127, 1, 65535, 65535), (0, 5, uid, 1, 255, 1, 65535, 0))
                  and (model := _model(records, settings, _CLASSIC_PROFILES))):
                models[uid] = model, False
        except (ValueError, StructError):
            continue
    return models


def early_fit_inputs(data, companions, indexed, *, profiles=None):
    """Resolve matching analysis companions carrying the worksheet and column selection."""
    profiles = _BIPHASIC_PROFILES | (profiles or {})
    try:
        _, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        return {}
    found = {}
    for uid, _, kind, records in analyses:
        if kind[:2] != (0, 0) or kind[3:] != (1, 255, 1, 65535, 0) or not companions.get(uid):
            continue
        companion, _ = companions[uid]
        try:
            if _one(records, 0x3B) != bytes(4) or _one(records, 0x3D) != bytes(2):
                continue
            if any(_one(records, tag) != _record_once(companion, tag) for tag in (9, 0x3A, 0x3C, 0x46)):
                continue
            count, sheet = unpack("<2i", _record_once(companion, 0x3B))
            if count != 1 or sheet not in indexed:
                continue
            model = _model(records, _one(records, 0x46), profiles)
            if model:
                found[uid] = sheet, model, _record_once(companion, 0x3D)
        except (ValueError, StructError):
            continue
    return found


def restore_dose_recipes(data, sources, sheets, snapshots, pending, *, curves=None,
                         early_inputs=None, classic_models=None, classic_curves=None, calibration_curves=None):
    """Attach native recipes only where the input, output and saved column selection agree."""
    try:
        indexed, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        return set()
    normalized = {}
    restored = set()
    early_inputs = early_inputs or {}
    classic_models = classic_models or {}
    if any(not calibration for _, calibration in classic_models.values()):
        try:
            _, _, _, source_records = _project_records(data, sources)
        except (StructError, ValueError):
            classic_models = {key: value for key, value in classic_models.items() if value[1]}
    # Normalizations may follow the models that consume them in the project index.
    for uid, sheet, kind, records in sorted(analyses, key=lambda a: a[2][0] != 4):
        early = early_inputs.get(uid)
        classic, calibration = classic_models.get(uid, (None, False))
        if classic == "Classic two-phase decay":
            # The fast rate is not identified by the saved observations.
            continue
        if early:
            sheet, early_model, selection = early
            if early_model not in _BIPHASIC_PROFILES.values():
                continue
        if uid not in pending or sheets.get(sheet) is None:
            continue
        parent = normalized.get(sheet)
        frame = parent[0] if parent else sources.get(sheet)
        if (frame is None or frame.attrs.get("table_format") != "xy" or len(frame.columns) != 2
                or not all(is_numeric_dtype(dtype) for dtype in frame.dtypes)):
            continue
        x, y = frame.columns
        try:
            count, column, first, last = unpack("<H3i", selection if early else _one(records, 0x3D))
            if count != 1 or (column,) != _column_ids(sheets[sheet][0]):
                continue
            if classic and not calibration:
                headers = [(payload, ()) for tag, _, payload in source_records.get(sheet) or () if tag == 0x800F]
                if parent is not None or (column, first, last) != _dataset_link((None, headers), column, 8):
                    continue
            elif first != last or first < 0 or (parent is None and first != 0):
                continue
            settings = _one(records, 0x46)
            if len(settings) != 1348:
                continue
            outputs = _one(records, 0x3C)
            title = _title(_one(records, 9))[:160]
            recipes = frame.attrs.get("legacy_recipes", [])
            if len(recipes) >= 256:
                continue
            if kind[:2] == (4, 255) and kind[2:6] == (uid, 1, 191, 0) and kind[-1] == 65535:
                if parent or sha256(settings).hexdigest() not in _NORMALIZATIONS:
                    continue
                slots, output, *rest = unpack("<11i", outputs)
                if (slots != 10 or output in indexed or output < 0 or set(rest) != {-1}
                        or snapshots.get(output) != (uid, sheet, 0)):
                    continue
                normalized[output] = frame, len(recipes)
                frame.attrs.setdefault("legacy_recipes", []).append((METHOD, {
                    LEGACY_TITLE: title, "Input": RAW, "X": x, "Variables": [y], "Replicates": INDEPENDENT,
                    "Zero reference": MINIMUM, "One reference": MAXIMUM, "Units": PERCENTAGES,
                    "Reference values in output": KEEP, "Graph results": False,
                }))
            elif classic or early or kind == (0, 5, uid, 1, 255, 1, 65535, 0):
                slots, first_slot, report, curve, *rest = unpack("<10i", outputs)
                if early and rest[0] >= 0 and snapshots.get(rest[0]) == (uid, sheet, 3):
                    rest = rest[1:]
                if (slots != 9 or first_slot != -1 or set(rest) != {-1} or curve < 0 or curve == report
                        or snapshots.get(report) != (uid, sheet, 1)):
                    continue
                model = early_model if early else classic or _model(records, settings, _PROFILES)
                if not model or model.startswith("Normalized ") != (parent is not None):
                    continue
                options = {
                    LEGACY_TITLE: title, "Model": model, "X": x, "Y": y, "Weighting": "Unweighted",
                    "Runs test": True, LEGACY_NOTES: "Refits the curve from the linked observations. "
                                                   "The saved result tables retain the original estimates.",
                }
                if classic in _CLASSIC_COEFFICIENTS:
                    fixed, start = _CLASSIC_COEFFICIENTS[classic]
                    options[stats.FIXED_COEFFICIENTS] = fixed.copy()
                    options[stats.STARTING_COEFFICIENTS] = start.copy()
                slot = len(recipes)
                if parent:
                    if not _append_linked_recipe(frame, parent[1], NORMALIZED, "Nonlinear regression", options):
                        continue
                else:
                    frame.attrs.setdefault("legacy_recipes", []).append(("Nonlinear regression", options))
                if ((curves is not None or classic_curves is not None or calibration_curves is not None)
                        and snapshots.get(curve) == (uid, sheet, 2)):
                    columns = _column_ids(sheets[curve][0])
                    if len(columns) == 1 and (link := _dataset_link(sheets[curve], columns[0], 40)) is not None:
                        if early:
                            # The companion layout numbers the drawing slots from zero.
                            link = link[0], link[1] - 1, link[2] - 1
                        observations = _dataset_link(sheets[sheet], column, 8) if parent else (column, 0, 0)
                        owner = (curve, sheet, observations, frame, slot)
                        if calibration and calibration_curves is not None:
                            calibration_curves[link] = None if link in calibration_curves else owner
                        elif classic and not calibration and classic_curves is not None:
                            key = curve, link[0]
                            classic_curves[key] = None if key in classic_curves else (frame, slot)
                        elif not classic and curves is not None:
                            curves[link] = None if link in curves else owner
            else:
                continue
            restored.add(uid)
        except (ValueError, StructError, TypeError, KeyError):
            continue
    return restored


_GRAPH_SERIES = Struct("<3i")
_DISABLED_SERIES = (-1, -4, -4)


def _dataset_link(sheet, column, expected_role):
    """Translate a validated result dataset to its three drawing identifiers."""
    identifiers = {}
    response = None
    for header, _ in sheet[1]:
        dataset, _, drawing_id, _, _, _, _, kind, role, _, _, linked_x, _, _, _ = _DATASET.unpack(header)
        if role == 4:
            identifiers[dataset] = drawing_id
        if dataset == column and (kind, role) == (1, expected_role):
            response = drawing_id, linked_x
    if response is not None and response[1] in identifiers:
        return column, response[0], identifiers[response[1]]
    return None


def _graph_curve(graph, curves, *, verify_series=False):
    sheet_ids = set(_id_array(_one(graph, 0x14)))
    order = _id_array(_one(graph, 0x15))
    payload = _one(graph, 0x16)
    _require(len(set(order)) == len(order) and len(payload) == 2 + len(order) * _GRAPH_SERIES.size
             and unpack_from("<H", payload)[0] == len(order))
    links = [link for link in _GRAPH_SERIES.iter_unpack(payload[2:]) if link != _DISABLED_SERIES]
    curve_link, = (link for link in links if curves.get(link) is not None)
    curve, sheet, observations, source, slot = curves[curve_link]
    extra = [link for link in links if link != curve_link]
    detached = (verify_series and source.attrs["legacy_recipes"][slot][1]["Model"]
                in _CALIBRATION_POLYNOMIALS.values())
    _require(curve in sheet_ids and (not extra or extra == [observations] and (sheet in sheet_ids or detached))
             and sheet_ids <= {curve, sheet})
    return curve, source, slot, curve_link[0], observations[0] if extra else None


def _sample_settings(frame, options):
    values = frame.to_numpy(dtype=float)
    _require(values.shape[1] == 2 and 2 <= len(values) <= rr.MAX_POINTS and np.isfinite(values).all())
    x = values[:, 0]
    _require(x[0] < x[-1])
    _require(np.allclose(x, np.linspace(x[0], x[-1], len(x)), rtol=0,
                         atol=8 * np.finfo(float).eps * max(abs(x[0]), abs(x[-1]))))
    return rr.ranges({**options, rr.CURVE_MIN: float(x[0]), rr.CURVE_MAX: float(x[-1]), rr.CURVE_POINTS: len(x)})


def _matching_grid(cache, values, axes, *, high_anchored=False):
    if values.shape != cache.shape:
        return False
    values = values.copy()
    for index, axis in enumerate(axes):
        if axis["scale"] == "log":
            if np.any(values[:, index] <= 0):
                return False
            values[:, index] = np.log10(values[:, index])
        elif axis["scale"] in PROBABILITY_SCALES:
            probabilities = values[:, index] / PROBABILITY_SCALES[axis["scale"]]
            if np.any((probabilities <= 0.) | (probabilities >= 1.)):
                return False
            values[:, index] = ndtri(probabilities)
    units = [axis["unit"] for axis in axes]
    if high_anchored:
        # A lower tick may be inset from the drawing origin.
        origin = [axis["bounds"][1] - axis["length"] * axis["unit"] for axis in axes]
    else:
        origin = [axis["bounds"][0] for axis in axes]
    with np.errstate(over="ignore", invalid="ignore"):
        return bool(np.all(np.abs((values - origin) / units - cache) <= 2))


def _classic_graph(graph, encoding, candidates, result_frames):
    """Match a single drawing to one generated output and corroborate every cached point."""
    curve, = _id_array(_one(graph, 0x14))
    key, = _id_array(_one(graph, 0x15))
    count, dataset, _, _ = unpack("<H3i", _one(graph, 0x16))
    source, slot = candidates.get((curve, dataset)) or (None, None)
    _require(count == 1 and source is not None)
    texts, _, _, scene = _scene(graph, encoding)
    _require(set(scene) == {key} and scene[key][0] == dataset)
    cache = scene[key][1]
    axes = _axis_config(graph, viewport_only=True)
    samples = result_frames[curve]
    grid = samples.to_numpy(dtype=float)
    options = source.attrs["legacy_recipes"][slot][1]
    if not _matching_grid(cache, grid, axes):
        # This decay profile stores a second drawing sampled over the observations.
        model, x, y = options["Model"], options["X"], options["Y"]
        _require(model == "One-phase decay" and len(cache) == len(grid))
        fit = stats.nonlinear(source, x, y, model, fixed=options[stats.FIXED_COEFFICIENTS],
                              start=options[stats.STARTING_COEFFICIENTS])["All"]
        x_grid = np.linspace(fit.data[x].min(), fit.data[x].max(), len(cache))
        predicted = stats.MODELS[model].equation(x_grid, *fit.parameters["Estimate"])
        grid = np.column_stack((x_grid, predicted))
        _require(_matching_grid(cache, grid, axes))
        samples = pd.DataFrame(grid, columns=samples.columns)
    return source, slot, samples, axes, {dim + "label": texts[axis["title"]] for dim, axis in zip("xy", axes)}


def _calibration_labels(graph, encoding, axes, curve_id, observed_id, samples, source, options):
    observation_ids = () if observed_id is None else (observed_id,)
    texts, _, _, scene = _scene(graph, encoding, observation_ids=observation_ids)
    cache = {dataset: values for dataset, values in scene.values()}
    expected = {curve_id: samples.to_numpy(dtype=float)}
    if observed_id is not None:
        expected[observed_id] = source[[options["X"], options["Y"]]].to_numpy(dtype=float)
    _require(set(scene) == set(_id_array(_one(graph, 0x15)))
             and cache.keys() == expected.keys() and len(scene) == len(expected))
    _require(all(_matching_grid(cache[dataset], values, axes, high_anchored=True)
                 for dataset, values in expected.items()))
    return {dim + "label": texts[axis["title"]] for dim, axis in zip("xy", axes) if axis["title"] in texts}


def restore_dose_graphs(data, graphs, links, curves, result_frames, *, classic_curves=None, verify_series=False):
    """Attach an editable graph to each verified fitted-curve output referenced by the drawing."""
    try:
        _, encoding, records, _ = _project_records(data, ())
    except (ValueError, StructError):
        return set()
    restored = set()
    for graph in graphs:
        uid = graph["id"]
        if uid not in links or not records.get(uid):
            continue
        try:
            if classic_curves is not None:
                source, slot, samples, axes, labels = _classic_graph(records[uid], encoding, classic_curves, result_frames)
                show_points = False
            else:
                curve, source, slot, curve_id, observed_id = _graph_curve(records[uid], curves,
                                                                        verify_series=verify_series)
                samples = result_frames[curve]
                axes = _axis_config(records[uid], viewport_only=True)
                show_points = observed_id is not None
                labels = {}
                if verify_series:
                    options = source.attrs["legacy_recipes"][slot][1]
                    labels = _calibration_labels(records[uid], encoding, axes, curve_id, observed_id, samples, source,
                                                 options)
                    model = options["Model"]
                    if model in _CALIBRATION_POLYNOMIALS.values():
                        fit = stats.nonlinear(source, options["X"], options["Y"], model)["All"]
                        x_values, expected = samples.to_numpy(dtype=float).T
                        predicted = stats.MODELS[model].equation(x_values, *fit.parameters["Estimate"])
                        _require(np.allclose(predicted, expected, rtol=1e-6, atol=1e-6))
            options = source.attrs["legacy_recipes"][slot][1]
            grid = _sample_settings(samples, options)
            style = {"axis": {}, "legend": "hidden", **labels}
            for dim, axis in zip("xy", axes, strict=True):
                low, high = axis["bounds"]
                scale = axis["scale"]
                style[dim + "scale"] = scale
                if scale == "log":
                    low, high = 10. ** low, 10. ** high
                style["axis"][dim] = {"min": low, "max": high}
            style = validated_style(style)
        except (KeyError, TypeError, ValueError, StructError, OverflowError):
            continue
        x, y = options["X"], options["Y"]
        child = len(source.attrs["legacy_recipes"])
        if _append_linked_recipe(source, slot, FIT_GRAPH_POINTS, SAVED_XY, {
            LEGACY_TITLE: graph["title"][:150] + " · Linked",
            LEGACY_NOTES: "Curve recalculated from the linked fit. The archived drawing remains available.",
            LEGACY_GRAPH_LINK: links[uid], FIT_GRAPH: True, FIT_GRAPH_OBSERVATIONS: show_points,
            "X label": x, "Y label": y,
        }):
            options.update(grid)
            options[FIT_GRAPH_SPEC] = {"x": x, "y": y, "samples": grid[rr.CURVE_POINTS], "series": [y], "grouped": False}
            source.attrs.setdefault("legacy_graph_styles", {})[child] = style
            restored.add(uid)
    return restored
