"""Reopen verified saved simulations as native function plots."""
from hashlib import sha256
from struct import error as StructError, unpack, unpack_from

import numpy as np

from . import plot_function as plotting
from .curve_models import CELL_DEATH_MODELS
from .legacy_binary_dose import _GRAPH_SERIES, _dataset_link, _matching_grid
from .legacy_binary_editable import (_axis_config, _id_array, _one, _project_records, _require, _scene,
                                      _series_columns, _subgroups)
from .legacy_binary_results import _column_ids, _read_groups
from .legacy_xml_generated import _generator_records
from .presentation import validated_style


_INHIBITION = "6175738bcacd57b1356182d392b4bc1a2b6302c83b6c6560731217724a3347e9"
_ASYMMETRIC = "0bc50a860cccfb552653a35ca81c5773d306163a6d36c449214cf9a251770314"
_ASYMMETRIC_MODEL = "Asymmetric dose-response (concentration X)"
_COMPETITION_KI = "One-site competition (log Ki)"
_COMPETITION_IC50 = "One-site competition (log IC50)"
_HOMOLOGOUS = "Homologous one-site competition"
_DEPLETION = "One-site competition with depletion"
_TWO_SITE_KI = "Two-site competition (log Ki)"
_TWO_SITE_IC50 = "Two-site competition (log IC50)"
_SPECIFIC_BINDING = "One-site specific binding"
_TOTAL_BINDING = "One-site total binding"
_ALLOSTERIC_ENZYME = "Allosteric sigmoidal enzyme kinetics"
_DISSOCIATION = "One-phase binding dissociation"
_RESAMPLED = {_SPECIFIC_BINDING, _TOTAL_BINDING, _DISSOCIATION}
_SIMULATION_FLAGS = (0, 251, 0, 65535, 0)
_SURVIVAL_FRACTION = "Linear-quadratic cell survival"
_SURVIVAL_PERCENT = "Linear-quadratic cell survival (percent)"
_SURVIVAL_COUNT = "Linear-quadratic cell survival (counts)"
_FRACTIONAL_DEATH, _PERCENT_DEATH, _DEATH_COUNT = CELL_DEATH_MODELS
_OVERLAID_SURVIVAL = {
    7: _SURVIVAL_FRACTION, 8: _SURVIVAL_PERCENT, 9: _SURVIVAL_COUNT,
    10: _FRACTIONAL_DEATH, 11: _PERCENT_DEATH, 12: _DEATH_COUNT,
}
_FORMATTED_PROFILES = {
    (0, 1, 251, 0, 65535, 0): {_DISSOCIATION},
    (3, 0, 127, 1, 65535, 0): {_DEPLETION},
    (5, 0, 127, 0, 65535, 0): {_TWO_SITE_KI},
    (23, 0, 127, 1, 65535, 0): {_TWO_SITE_IC50},
    (0, *_SIMULATION_FLAGS): {"Standard sine wave", "Gaussian"},
    (1, *_SIMULATION_FLAGS): {"Damped sine wave", "Sum of two Gaussians"},
    (2, *_SIMULATION_FLAGS): {"Sinc wave", "Lognormal"},
    (3, *_SIMULATION_FLAGS): {"Lorentzian"},
    (4, *_SIMULATION_FLAGS): {"Sum of two Lorentzians"},
    (5, *_SIMULATION_FLAGS): {"Michaelis–Menten"},
    (8, *_SIMULATION_FLAGS): {"Horizontal line"},
    (9, *_SIMULATION_FLAGS): {_SPECIFIC_BINDING, "Line through origin"},
    (10, *_SIMULATION_FLAGS): {_TOTAL_BINDING, _ALLOSTERIC_ENZYME, "Line through point"},
    (17, *_SIMULATION_FLAGS): {_COMPETITION_KI},
    (19, *_SIMULATION_FLAGS): {_HOMOLOGOUS},
    (22, *_SIMULATION_FLAGS): {_COMPETITION_IC50},
}
_FORMATTED_MODELS = frozenset().union(*_FORMATTED_PROFILES.values())
_DECLARED_GRID_MODELS = {"Gaussian", "Sum of two Gaussians", "Lognormal", "Sum of two Lorentzians"}
_NAMED_EQUATIONS = {
    "a9d69436efab589f74b9fbf5aa684f0128337d902e0b221fb83caeb79f5e3a4a": (
        _SURVIVAL_FRACTION, {"A": "Alpha", "B": "Beta"}),
    "4e8caee4af91b9edc5e3db19a53728182bf9346190c4ca1b962e598810857931": (
        _PERCENT_DEATH, {"A": "Alpha", "B": "Beta"}),
    "a5e440302261ace33d0fffd3b50bc9b43377c3a4c527035af55b853127c30ea1": (
        _DEATH_COUNT, {"Y0": "Initial count", "A": "Alpha", "B": "Beta"}),
    "b5b18e04c865ba28d6ebb3910ac1516c8a71e2bb57306d7805170ce55db7be8c": (
        _SURVIVAL_PERCENT, {"A": "Alpha", "B": "Beta"}),
    "dd77561ff0fe7bf8c066222bd823cefaa880bacb0da26f3cb332442c8ead932b": (
        _SURVIVAL_COUNT, {"Y0": "Initial count", "A": "Alpha", "B": "Beta"}),
    "114fe33eac3f1ee54e1830dc867348e90f46d1afa8fa81095c7bffbd4691233c": (
        _FRACTIONAL_DEATH, {"A": "Alpha", "B": "Beta"}),
    "cd7940064b96802336a6ae10ec12655ff4a7e13ad968a54f4b36d79f46c1d28e": (
        _ALLOSTERIC_ENZYME, {"Vmax": "Vmax", "Khalf": "K half", "h": "Hill slope"}),
    "4b257d45bff54e884f71c0129bd99dfe69349c1ea97d6bb28df1c57f389a8c89": (
        _DISSOCIATION, {"Y0": "Y0", "NS": "NS", "K": "Rate"}),
    "fb6f8da1997cc0ff48e203f4b9e27f47e12ff8c871733259ada6ebb41cff82d5": (
        _SPECIFIC_BINDING, {"Bmax": "Bmax", "Kd": "Kd"}),
    "4c40e21565a02d1b254ebcdcdb820cebb268b099a36f04ea7134a0d9aa2ffc60": (
        _TOTAL_BINDING, {"Bmax": "Bmax", "Kd": "Kd", "NS": "Nonspecific slope", "Background": "Background"}),
    "02694ea87d9e330ae3ff0ee7db5c2c1c7f3a32365f7f7af870953d81182ef305": (
        _DEPLETION, {"KDNM": "Hot Kd (nM)", "SPACT": "Specific activity", "VOL": "Volume", "NS": "NS",
                     "LOGKI": "Log Ki", "HOT": "Hot (cpm)", "BMAX": "Bmax"}),
    "4b39effbcffab4959484d63187bfbdc146b019b633e05e066ec30d564ff6393e": (
        _TWO_SITE_KI, {"logKiHi": "Log Ki 1", "logKiLo": "Log Ki 2", "HotNM": "Hot (nM)",
                       "HotKdNMHi": "Hot Kd 1 (nM)", "HotKdNMLo": "Hot Kd 2 (nM)", "Top": "Top",
                       "Bottom": "Bottom", "FractionHi": "Fraction 1"}),
    "d23d3f6951d47bfa5871d56ae8a8c1eeede91c9368231cff79ca4a8cc6cc9571": (
        _TWO_SITE_IC50, {"TOP": "Top", "BOTTOM": "Bottom", "FRACTIONHI": "Fraction 1",
                         "LOGIC50HI": "Log IC50 1", "LOGIC50LO": "Log IC50 2"}),
    "2117d00a9e76f4df8be962e34946a12490611988e3b7243d76867e8fc90cbdb4": (
        _COMPETITION_KI, {"Bottom": "Bottom", "Top": "Top", "logKi": "Log Ki",
                          "HotNM": "Hot (nM)", "HotKdNM": "Hot Kd (nM)"}),
    "d1cda9ad3e0704e5f61b54b1820328c0a6706faffb505d78c740cf77e0421071": (
        _COMPETITION_IC50, {"Bottom": "Bottom", "Top": "Top", "LogIC50": "Log IC50"}),
    "60d17593fba6729dcd60c948fc26226cce592a039febad591a1d9f85c5388516": (
        _HOMOLOGOUS, {"logKD": "Log Kd", "NS": "NS", "HotnM": "Hot (nM)", "Bmax": "Bmax"}),
    "dbda4d94c4648611be5161e89749097e30f67085ce1ec0402d4b70b52d09996c": (
        "Gaussian", {"Amplitude": "Amplitude", "Mean": "Mean", "SD": "SD"}),
    "d438b8d091500216d510807fc70c6944259d2d0ad07999b070a0531751b83774": (
        "Sum of two Gaussians", {"Amplitude1": "Amplitude 1", "Mean1": "Mean 1", "SD1": "SD 1",
                                 "Amplitude2": "Amplitude 2", "Mean2": "Mean 2", "SD2": "SD 2"}),
    "4979a83ac511b4c56729412b5603ab2eba8769c53581aa8e47ef71b7a34f3618": (
        "Lognormal", {"A": "A", "GeoMean": "Geometric mean", "GeoSD": "Geometric SD"}),
    "8ee1836a0e73085adc9adb4127c488b7599d253054ae9463128fde713917deda": (
        "Sum of two Lorentzians", {"Amplitude1": "Amplitude 1", "Center1": "Center 1", "Width1": "Width 1",
                                  "Amplitude2": "Amplitude 2", "Center2": "Center 2", "Width2": "Width 2"}),
    "476fb86104d483a19ca6cbee2bed7e71a19d3183e258af5693a29aea535bad61": (
        "Lorentzian", {"Amplitude": "Amplitude", "Center": "Center", "Width": "Width"}),
    "815459ba61f23339bb9266b8c03de833e7c77f2f4365d0cdee7048865c6e35ff": (
        "Michaelis–Menten", {"Vmax": "Vmax", "Km": "Km"}),
    "6d399f9031452f5f4bdd6f4606683941679687147d6029fe8d5c11387b72f6d4": (
        "Line through point", {"Slope": "Slope", "X0": "X0", "Y0": "Y0"}),
    "4ecede9a8e8470e7b2fd0631932ad987feb5c8af238adac7d340b11231c6afa3": (
        "Line through origin", {"Slope": "Slope"}),
    "ccd2f187fac5c1c65c04c49a0a4f08d40337168fdb11e1c1cc99c1da8648c0ad": (
        "Horizontal line", {"Mean": "Mean"}),
    "36bde89735288a35bcae028ef37ae711aed7085605883cc1e9eebd92faaae014": (
        "Standard sine wave", {"Amplitude": "Amplitude", "Wavelength": "Wavelength", "PhaseShift": "Phase shift"}),
    "584bf12c199fe72ffa2ef7947a92654c7e2032730a359180fa0ab8a0931ecaee": (
        "Damped sine wave", {"Amplitude": "Amplitude", "Wavelength": "Wavelength", "PhaseShift": "Phase shift",
                             "K": "Rate"}),
    "9ec682a65b35da6230956c588251bd6774059fbf85af5b46bf53a40b77905aaa": (
        "Sinc wave", {"Amplitude": "Amplitude", "Wavelength": "Wavelength"}),
    "c49eca20bb758166dbd58b3a3becbdf8ef1580eef56232919a3d5a55ee190e60": (
        "Sine wave with baseline", {"Amplitude": "Amplitude", "Wavelength": "Wavelength",
                                   "PhaseShift": "Phase shift", "Baseline": "Baseline"}),
}
_SINGLE_PRECISION = float(np.finfo(np.float32).eps)


def _decode_equation(expression):
    text = bytes(_one(expression, 0x49)).rstrip(b"\r\n\0").decode("ascii")
    signature = sha256("".join(text.split()).encode("ascii")).hexdigest()
    payload = _one(expression, 0x54)
    _require(len(payload) in (8, 16, 24, 32, 40, 48, 56, 64))
    values = unpack(f"<{len(payload) // 8}d", payload)
    raw_names = bytes(_one(expression, 0x53)).split(b"\0", len(values))
    _require(len(raw_names) == len(values) + 1 and np.isfinite(values).all())
    parameters = dict(zip((name.decode("ascii") for name in raw_names[:-1]), values, strict=True))
    _require(len(parameters) == len(values))
    if signature == _INHIBITION and parameters.keys() == {"Bottom", "Top", "IC50", "HillSlope"}:
        model = "Inhibition (variable slope)"
        native = {"Bottom": parameters["Top"], "Top": parameters["Bottom"], "IC50": parameters["IC50"],
                  "Hill slope": -parameters["HillSlope"]}
    elif signature == _ASYMMETRIC and parameters.keys() == {"Bottom", "Top", "EC50", "HillSlope", "S"}:
        model = _ASYMMETRIC_MODEL
        native = {"Bottom": parameters["Bottom"], "Top": parameters["Top"], "EC50": parameters["EC50"],
                  "Hill slope": parameters["HillSlope"], "Asymmetry": parameters["S"]}
    elif signature in _NAMED_EQUATIONS:
        model, names = _NAMED_EQUATIONS[signature]
        _require(parameters.keys() == names.keys())
        native = {caption: parameters[key] for key, caption in names.items()}
    else:
        raise ValueError("The saved simulation equation is not supported.")
    return model, native


def _simulation_grid(records, x, model):
    if model not in _DECLARED_GRID_MODELS:
        return x
    settings = _one(records, 0x46)
    _require(len(settings) == 1348)
    segments, low, high = unpack_from("<3d", settings, 1100)
    _require(segments == len(x) - 1 and segments >= 2 and np.isfinite([low, high]).all() and low < high)
    # The generator settings store the actual bounds. The table stores a
    # single-precision copy of the origin and step, even for double-precision Y.
    with np.errstate(over="ignore", invalid="ignore"):
        origin = float(np.float32(low))
        step = float(np.float32((high - low) / segments))
        encoded = origin + np.arange(len(x)) * step
    _require(np.array_equal(x, encoded))
    grid = np.linspace(low, high, len(x))
    _require((np.diff(grid) > 0).all())
    return grid


def _simulation_options(records, frame):
    """Translate verified parameter sets and check each column against its own equation."""
    x_column, *names = frame.columns
    count = len(names)
    groups = list(_subgroups(records, 0x8047))
    _require(len(groups) == count and 1 <= count <= plotting.MAX_CURVES)
    model = None
    curves = {}
    for header, group in groups:
        _require(len(header) == 44)
        kind, position, total = unpack("<3I", header[:12])
        _require(kind == 1 and total == count and position < count and position not in curves)
        expressions = list(_subgroups(group, 0x8048))
        _require(bool(expressions))
        name = names[position]
        current, parameters = _decode_equation(expressions[0][1])
        _require(model is None or current == model)
        model = current
        if model == _HOMOLOGOUS:
            _require(len(expressions) == 2)
            saved_name = bytes(_one(expressions[1][1], 0x49)).rstrip(b"\0").decode("ascii")
            _require(saved_name == name)
        else:
            _require(count == len(expressions) == 1)
        curves[position] = {"name": name, "parameters": parameters}
    options = {plotting.MODEL: model, plotting.X_SOURCE: plotting.WORKSHEET, plotting.X_COLUMN: x_column,
               plotting.CURVES: [curves[index] for index in range(count)]}
    checked = plotting.check_curves(model, options[plotting.CURVES])
    x = _simulation_grid(records, plotting.worksheet_grid(frame, options, count), model)
    plotting.check_domain(model, x, plotting.X_COLUMN)
    # Older two-site curves round both the X step and the stored response to single precision.
    if model in (_TWO_SITE_KI, _TWO_SITE_IC50):
        tolerance = 4 * _SINGLE_PRECISION
    else:
        tolerance = _SINGLE_PRECISION if model in _FORMATTED_MODELS else 3e-8
    for name, parameters in checked:
        observed = frame[name].to_numpy(dtype=float)
        _require(x.shape == observed.shape and np.isfinite(observed).all()
                 and np.allclose(plotting.evaluate(model, x, parameters), observed, rtol=tolerance, atol=1e-10))
    return options


def _matches_drawing(cache, values, axes):
    if cache.shape != values.shape:
        return False
    invisible = np.zeros(len(values), dtype=bool)
    for dimension, axis in enumerate(axes):
        if axis["scale"] == "log":
            invisible |= values[:, dimension] == 0
    # Zero is a valid result, with an explicit sentinel in a log drawing.
    return (np.all(cache[invisible] == -1) and not invisible.all()
            and _matching_grid(cache[~invisible], values[~invisible], axes, high_anchored=True))


def _competition_drawing_grid(samples, cache, axes, options):
    """Verify a saved drawing from a separate revision of the same two plateaus."""
    _require(len(cache) == len(samples) - 1 and len(cache) >= 3
             and all(axis["scale"] == "linear" for axis in axes))
    low, high = axes[0]["bounds"]
    name = options[plotting.X_COLUMN]
    _require(np.allclose(samples[name], np.linspace(low, high, len(samples)), rtol=0,
                         atol=_SINGLE_PRECISION * max(abs(low), abs(high))))
    x = np.linspace(low, high, len(cache))
    curve, = options[plotting.CURVES]
    parameters = curve["parameters"]
    alternate = {**parameters, "Bottom": parameters["Top"], "Top": parameters["Bottom"]}
    model = options[plotting.MODEL]
    original = np.column_stack((x, plotting.evaluate(model, x, parameters)))
    drawn = np.column_stack((x, plotting.evaluate(model, x, alternate)))
    _require(not _matches_drawing(cache, original, axes) and _matches_drawing(cache, drawn, axes))
    grid = samples[[name]].iloc[:-1].copy()
    grid[name] = x
    return grid, {**options, plotting.CURVES: [{**curve, "parameters": alternate}]}


def _resampled_drawing_grid(samples, cache, axes, options):
    """The saved drawing samples the same range with one fewer point."""
    _require(len(cache) == len(samples) - 1 and len(cache) >= 3
             and all(axis["scale"] == "linear" for axis in axes))
    name = options[plotting.X_COLUMN]
    lo, hi = samples[name].iloc[[0, -1]]
    _require(lo == 0 and hi > 0 and np.allclose(samples[name], np.linspace(lo, hi, len(samples)),
                                               rtol=_SINGLE_PRECISION, atol=1e-10))
    x = np.linspace(lo, hi, len(cache))
    curve, = options[plotting.CURVES]
    y = plotting.evaluate(options[plotting.MODEL], x, curve["parameters"])
    _require(_matches_drawing(cache, np.column_stack((x, y)), axes))
    grid = samples[[name]].iloc[:-1].copy()
    grid[name] = x
    return grid


def _restore_overlaid_survival(graph, encoding, source_uid, source, raw, samples, records, kind, expected):
    """Bind the simulated line and its observation markers to their own verified data."""
    model = _OVERLAID_SURVIVAL.get(kind[2])
    _require(kind[:2] == (15, 255) and kind[3:] == _SIMULATION_FLAGS and model is not None)
    _require(len(expected) == 1 and len(samples.columns) == 2)
    _require(len(source.columns) == 2 and len(source.attrs.get("legacy_recipes", ())) < 256)
    (source_id, (_, _, x, y)), = _series_columns(source_uid, raw, source, -1).items()
    links = _one(graph, 0x16)
    _require(len(links) == 2 + 2 * _GRAPH_SERIES.size and unpack("<H", links[:2]) == (2,))
    curve_id, y_revision, x_revision = expected[0]
    delta = int(model in CELL_DEATH_MODELS)
    curve_link = curve_id, y_revision - delta, x_revision - delta
    observed_link = _dataset_link((None, [(header, None) for tag, _, header in raw if tag == 0x800F]),
                                  source_id, 8)
    _require(observed_link is not None
             and set(_GRAPH_SERIES.iter_unpack(links[2:])) == {curve_link, observed_link})
    series = _id_array(_one(graph, 0x15))
    texts, _, _, drawn = _scene(graph, encoding, observation_ids=(source_id,))
    _require(len(series) == 2 and drawn.keys() == set(series))
    by_dataset = {dataset: cache for dataset, cache in drawn.values()}
    _require(by_dataset.keys() == {curve_id, source_id})
    axes = _axis_config(graph, viewport_only=True)
    options = _simulation_options(records, samples)
    _require(options[plotting.MODEL] == model)
    values = samples.to_numpy(dtype=float)
    options.pop(plotting.X_COLUMN)
    options.update({plotting.X_SOURCE: plotting.LINEAR, plotting.X_MIN: values[0, 0],
                    plotting.X_MAX: values[-1, 0], plotting.SEGMENTS: len(values) - 1,
                    plotting.OBSERVATION_COLUMNS: [source.columns[x], source.columns[y]]})
    grid = plotting.generated_grid(options, 1)
    curve, = options[plotting.CURVES]
    curve_y = plotting.evaluate(model, grid, curve["parameters"])
    _require(np.allclose(grid, values[:, 0], rtol=8 * np.finfo(float).eps, atol=0.)
             and _matches_drawing(by_dataset[curve_id], np.column_stack((grid, curve_y)), axes)
             and _matches_drawing(by_dataset[source_id], source.iloc[:, [x, y]].to_numpy(dtype=float), axes))
    return options, axes, texts


def _graph_style(axes, texts, hidden):
    style = {"axis": {}}
    if hidden:
        style["legend"] = "hidden"
    for name, axis in zip("xy", axes, strict=True):
        scale = axis["scale"]
        low, high = axis["bounds"]
        style[name + "scale"] = scale
        style[name + "label"] = texts.get(axis["title"], "")
        style["axis"][name] = {"min": 10. ** low if scale == "log" else low,
                               "max": 10. ** high if scale == "log" else high}
    return validated_style(style)


def read_simulation_graphs(data, result_frames, graph_ids, remaining_cells, *, observations=None):
    """Yield verified simulations on an original observation table or on their saved X grid."""
    observations = observations or {}
    candidates = {}
    for uid, frame in result_frames.items():
        sources = frame.attrs["legacy_binary_result"]["source_ids"]
        if (not sources and 2 <= frame.shape[1] <= plotting.MAX_CURVES + 1
                or len(sources) == 1 and frame.shape[1] == 2 and frame.iloc[:, 1].dtype.kind in "fiu"):
            candidates[uid] = frame
    if not candidates:
        return
    try:
        _, encoding, drawings, source_records = _project_records(data, observations)
        _, sheets, indexed, listed, _ = _read_groups(data)
        generators = _generator_records(data)
    except (ValueError, StructError):
        return
    for graph_id, graph in drawings.items():
        if graph_id not in graph_ids or not graph:
            continue
        try:
            member_data = _one(graph, 0x14)
            # Some fractional survival graphs reserve a final slot without a data set.
            has_empty_slot = len(member_data) == 16 and unpack("<i", member_data[-4:]) == (-2,)
            if has_empty_slot:
                count, first, second, _ = unpack("<4i", member_data)
                _require(count == 3 and min(first, second) >= 0)
                members = [first, second]
            else:
                members = _id_array(member_data)
            sheet, = (uid for uid in members if uid in candidates)
            samples = candidates[sheet]
            _require(1 <= len(members) <= 2 and 3 <= len(samples) <= plotting.MAX_EVALUATIONS)
            analysis = samples.attrs["legacy_binary_result"]["analysis_id"]
            _require(analysis in (listed or ()) and generators[analysis] is not None)
            records = generators[analysis]
            kind = unpack("<8H", _one(records, 0x3A))
            _require(not has_empty_slot or kind == (15, 255, 7, *_SIMULATION_FLAGS))
            formatted_asymmetric = kind == (15, 0, 14, *_SIMULATION_FLAGS)
            profiles = _FORMATTED_PROFILES.get(kind[2:], ()) if kind[:2] == (15, 0) else ()
            dissociation = _DISSOCIATION in profiles
            sources = samples.attrs["legacy_binary_result"]["source_ids"]
            input_links = _one(records, 0x3B)
            if dissociation:
                # This generator stores a worksheet reference and its own fixed coefficients.
                _require(len(sources) == 1 and sources[0] in indexed and _id_array(input_links) == sources)
            else:
                _require(not sources and input_links == bytes(4))
            standalone = kind[:2] == (15, 255) and kind[3:] == _SIMULATION_FLAGS
            _require((standalone or profiles or formatted_asymmetric)
                     and unpack("<11i", _one(records, 0x3C)) == (10, sheet, *([-1] * 9)))
            columns = _column_ids(sheets[sheet][0])
            expected_links = tuple(_dataset_link(sheets[sheet], column, 40) for column in columns)
            _require(None not in expected_links)
            if len(members) == 2:
                uid, = (uid for uid in members if uid != sheet)
                source = observations[uid]
                options, axes, texts = _restore_overlaid_survival(
                    graph, encoding, uid, source, source_records[uid], samples, records, kind, expected_links)
                yield graph_id, analysis, source, options, _graph_style(axes, texts, hidden=True)
                continue
            _require(len(samples) <= remaining_cells)
            series = _id_array(_one(graph, 0x15))
            links = _one(graph, 0x16)
            count = len(columns)
            total = len(series)
            _require(len(set(series)) == total and len(links) == 2 + total * _GRAPH_SERIES.size
                     and unpack("<H", links[:2]) == (total,))
            graph_links = tuple(_GRAPH_SERIES.iter_unpack(links[2:]))
            empty_series = ()
            if (_TWO_SITE_KI in profiles and count == 1 and total == 2
                    and graph_links[1][:2] == (-1, -1) and graph_links[1][2] >= 0):
                empty_series = series[1:]
                series = series[:1]
                graph_links = graph_links[:1]
            _require(count == samples.shape[1] - 1 == len(series))
            _require(tuple(link[0] for link in graph_links) == columns)
            options = _simulation_options(records, samples)
            # A local slot can represent different equations in different projects.
            profile = options[plotting.MODEL] if profiles else None
            _require(not profiles or profile in profiles)
            _require(not formatted_asymmetric or options[plotting.MODEL] == _ASYMMETRIC_MODEL)
            texts, _, _, drawn = _scene(graph, encoding, empty_series=empty_series,
                                        curve_drawing=0x80 if dissociation else 0x88,
                                        annotated=profile == "Gaussian")
            _require(drawn.keys() == set(series) and tuple(drawn[key][0] for key in series) == columns)
            axes = _axis_config(graph, viewport_only=True)
            if profile in (_COMPETITION_KI, _COMPETITION_IC50):
                (_, y_revision, x_revision), = graph_links
                (_, expected_y, expected_x), = expected_links
                _require(y_revision >= 0 and x_revision >= 0 and y_revision != expected_y and x_revision != expected_x)
                grid, options = _competition_drawing_grid(samples, drawn[series[0]][1], axes, options)
            elif profile in _RESAMPLED:
                (dataset, y, x), = expected_links
                dy, dx = (3, 4) if profile == _DISSOCIATION else (1, 2)
                _require(y >= dy and x >= dx and graph_links == ((dataset, y - dy, x - dx),))
                grid = _resampled_drawing_grid(samples, drawn[series[0]][1], axes, options)
            else:
                points = samples.to_numpy(dtype=float, copy=True)
                points[:, 0] = _simulation_grid(records, points[:, 0], options[plotting.MODEL])
                # The older simulation drawing can have different revisions of the same
                # linked data set. Match every point to the verified table in either case.
                revisions_match = graph_links == expected_links or (
                    formatted_asymmetric and all(y >= 0 and x >= 0 for _, y, x in graph_links))
                _require(revisions_match and all(
                    _matches_drawing(drawn[key][1], points[:, [0, index]], axes)
                    for index, key in enumerate(series, 1)))
                grid = samples[[options[plotting.X_COLUMN]]].copy()
                grid[options[plotting.X_COLUMN]] = points[:, 0]
            style = _graph_style(axes, texts, hidden=count == 1)
        except (KeyError, TypeError, ValueError, StructError, OverflowError):
            continue
        remaining_cells -= len(grid)
        grid.attrs.clear()
        yield graph_id, analysis, grid, options, style
