"""Synthetic source and drawing records exercise the verified joint fit binding."""
from hashlib import sha256
from struct import pack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import legacy_binary_global as legacy
from analisi import regression_range as rr
from analisi.curve_models import MODELS
from analisi.legacy_binary import _DATASET
from analisi.legacy_fit_graph import FIT_GRAPH_SPEC
from analisi.legacy_restore import LEGACY_GRAPH_LINK, SAVED_BINARY_GRAPH, paired_graph_index
from analisi.workbench import analyse


def record(tag, payload):
    return tag, (), payload


def columns(ids):
    return [(0x0D, pack("<6I", slot, uid, 1, 0, 0, 0)) for slot, uid in enumerate(ids)]


def header(uid, drawing, result, sheet, kind, role, mode, x, points):
    storage = 101 if result == -1 else 102
    return _DATASET.pack(uid, 0, drawing, result, sheet, storage, 0, kind, role, mode, 1, x, 0, points, points)


def drawing(key, dataset, flags, values):
    fields = pack("<4H", key, 0, dataset, 1) + bytes(50) + pack("<H", flags) + bytes(84)
    pairs = np.rint(values * 100).astype("<i4")
    cache = pack("<I", pairs.size) + pairs.tobytes()
    return [(0x8020, (24,), pack("<H", 9) + bytes(28)), (0x8028, (24, 32), fields), (0x29, (24, 32, 40), cache)]


class LegacySchildConstraintTests(unittest.TestCase):
    def test_fixed_concentrations_require_agreement_with_the_saved_report(self):
        names = ["Control", "Low", "Medium", "High", "Highest"]
        concentrations = [0, 3e-10, 1e-9, 3e-9, 1e-8]
        report = pd.DataFrame([
            ["Schild", *([None] * 6)],
            ["Best-fit values", *([None] * 6)],
            [" B", *(f"= {value:.3e}" for value in concentrations), None],
            ["Constraints", *([None] * 6)],
            [" B", *(f"B = {value:g}" for value in concentrations), None],
        ], columns=["Parameter", *names, "Global"])
        expected = [{"series": name, "parameters": {"B": {"fixed": value}}}
                    for name, value in zip(names, concentrations, strict=True)]
        self.assertEqual(legacy._fixed_concentration_constraints(report, names), expected)
        report.loc[4, "Low"] = "B = 9e-10"
        with self.assertRaises(ValueError):
            legacy._fixed_concentration_constraints(report, names)


class LegacyIndependentFitPlotTests(unittest.TestCase):
    def test_probability_drawing_uses_quantiles_and_never_charts_an_endpoint(self):
        from scipy.special import ndtr
        from analisi.legacy_binary_dose import _matching_grid
        from analisi.probability_scale import FRACTION_SCALE, PERCENT_SCALE

        x = np.arange(3, dtype=float)
        quantiles = np.array([-2., 0., 2.])
        cache = np.column_stack((x * 100, (quantiles + 2.) * 100))
        base = {"bounds": [-2., 2.], "length": 400, "unit": .01}
        for scale, divisor in [(FRACTION_SCALE, 1.), (PERCENT_SCALE, 100.)]:
            axes = [{"bounds": [0., 2.], "length": 200, "unit": .01, "scale": "linear"},
                    {**base, "scale": scale}]
            values = np.column_stack((x, ndtr(quantiles) * divisor))
            self.assertTrue(_matching_grid(cache, values, axes, high_anchored=True))
            values[0, 1] = 0.
            self.assertFalse(_matching_grid(cache, values, axes, high_anchored=True))

    def test_semilog_starting_estimates_follow_names_in_either_saved_order(self):
        candidate = SimpleNamespace(options={"Y columns": ["Y1"]})
        report = pd.DataFrame([["Semilog line", None], ["Best-fit values", None],
                               ["Slope", 1.5], ["Yintercept", 1.833]])
        expected = {"Y1": {"Intercept": 1.833, "Slope": 1.5}}
        self.assertEqual(legacy._log_line_starts(candidate, report), expected)
        self.assertEqual(legacy._log_line_starts(candidate, report.iloc[[0, 1, 3, 2]]), expected)
        report.iloc[3, 0] = "Slope"
        with self.assertRaises(ValueError):
            legacy._log_line_starts(candidate, report)

    def test_saved_curve_only_view_hides_observations_until_its_sampling_changes(self):
        x = np.geomspace(1., 100., 12)
        frame = pd.DataFrame({"X": x, "Y": 3. + .8 * np.log10(x)})
        model = "Semilog line (log X)"
        settings = {rr.CURVE_MIN: 1., rr.CURVE_MAX: 100., rr.CURVE_POINTS: 25}
        options = {
            "X": "X", "Y columns": ["Y"], "Model": model, "Merge numbered replicates": True,
            FIT_GRAPH_SPEC: {"x": "X", "series": ["Y"], "model": model, "spacing": "log",
                             "observations": False, **settings},
            **settings,
        }
        fit = analyse("Nonlinear regression", frame, options)
        axes = fit.figure.axes[0]
        self.assertTrue(all(not artist.get_visible() for artist in axes.collections))
        np.testing.assert_array_equal(axes.lines[0].get_xdata(), np.geomspace(1., 100., 25))
        edited = analyse("Nonlinear regression", frame, {**options, rr.CURVE_POINTS: 31})
        self.assertTrue(all(artist.get_visible() for artist in edited.figure.axes[0].collections))
        pd.testing.assert_frame_equal(edited.tables["Parameters: Y"], fit.tables["Parameters: Y"])


class LegacyGlobalFitTests(unittest.TestCase):
    def setUp(self):
        names = ["X", "Control $", "Treatment"]
        self.source = pd.DataFrame([[-3, 5, 6], [-2, 4, 9], [-1, 3, 12]], columns=names)
        self.source.attrs.update(table_format="xy", worksheet_roles={"x": ["X"], "y": [[name] for name in names[1:]]})
        self.curve = pd.DataFrame([[-3, 5, 6], [-2, 4, 9], [-1, 3, 12], [0, 2, 15]], columns=names)
        observed, fitted = [(11, 1, 7), (12, 2, 7)], [(21, 4, 9), (22, 5, 9)]
        raw_source = [header(10, 7, -1, 1, 1, 4, 10, 10, 3)]
        raw_source += [header(uid, draw, -1, 1, 1, 8, 10, 10, 3) for uid, draw, _ in observed]
        source_records = [record(tag, value) for tag, value in columns((11, 12))]
        source_records.extend(record(0x800F, value) for value in raw_source)
        raw_curve = [(header(20, 9, 3, 5, 4, 4, 11, 20, 4), ())]
        raw_curve += [(header(uid, draw, 3, 5, 1, 40, 10, 20, 4), ()) for uid, draw, _ in fitted]
        self.sheets = {1: (columns((11, 12)), []), 5: (columns((21, 22)), raw_curve)}
        self.snapshots = {4: (3, 1, 1), 5: (3, 1, 2)}
        kind = (0, 5, 6, 1, 127, 1, 65535, 65535)
        settings, model = bytes(1348), b"synthetic model profile"
        self.analysis = [
            record(0x3A, pack("<8H", *kind)), record(0x46, settings), record(0x8047, model),
            record(0x3B, pack("<2i", 1, 1)), record(0x3C, pack("<10i", 9, -1, 4, 5, *([-1] * 6))),
            record(0x3D, pack("<H6i", 2, 11, 1, 7, 12, 2, -1)),
        ]

        graph = [record(0x14, pack("<3i", 2, 5, 1)), record(0x15, pack("<5i", 4, 1, 2, 3, 4)),
                 record(0x16, pack("<H12i", 4, *(value for link in fitted + observed for value in link))),
                 record(0x13, bytes(48)), record(0x8018, bytes(12))]
        for key, (part, table, column) in enumerate(((observed, self.source, 1), (observed, self.source, 2),
                                                     (fitted, self.curve, 1), (fitted, self.curve, 2)), 1):
            values = table.iloc[:, [0, column]].to_numpy(dtype=float, copy=True)
            values[:, 0] += 3
            graph.extend(drawing(key, part[column - 1][0], 0x08 if key <= 2 else 0x88, values))
        axes = [{"bounds": bounds, "unit": .01, "length": (bounds[1] - bounds[0]) * 100,
                 "title": num, "scale": "linear"} for num, bounds in enumerate(([-3, 0], [0, 20]))]
        self.enterContext(patch.object(legacy, "_PROFILES", {sha256(settings + pack("<I", len(model)) + model).hexdigest():
                                                           "Allosteric competition"}))
        self.enterContext(patch.object(legacy, "indexed_analyses", return_value=({1}, [(3, 1, kind, self.analysis)])))
        self.enterContext(patch.object(legacy, "_project_records", return_value=({}, "ascii", {7: graph}, {1: source_records})))
        self.enterContext(patch.object(legacy, "_axis_config", return_value=axes))
        self.graph = graph

    def restore(self):
        candidates = legacy.global_candidates(b"", {1: self.source}, self.sheets, self.snapshots, {3})
        return legacy.restore_global_graphs(b"", [{"id": 7, "title": "Synthetic binding"}],
                                            {7: "example:7"}, candidates, {5: self.curve})

    def test_graph_recovers_joint_fit_and_exact_drawing_range(self):
        self.assertEqual(self.restore(), ({7}, {3}))
        (method, options), = self.source.attrs["legacy_recipes"]
        self.assertEqual(method, "Global nonlinear regression")
        self.assertEqual(options["Y columns"], ["Control $", "Treatment"])
        self.assertEqual(options["Shared parameters"], ["Y0"])
        self.assertEqual(options["Fixed parameters"], {"Hot (nM)": 1.0, "Hot Kd (nM)": 1.0})
        self.assertEqual(options[FIT_GRAPH_SPEC][rr.CURVE_FIELDS[0]], -3.0)
        self.assertEqual(options[FIT_GRAPH_SPEC][rr.CURVE_POINTS], 4)
        edited = SimpleNamespace(method=method, options=options)
        archive = SimpleNamespace(method=SAVED_BINARY_GRAPH, options={LEGACY_GRAPH_LINK: "example:7"})
        self.assertEqual(paired_graph_index(archive, [archive, edited]), 1)
        self.assertEqual(paired_graph_index(edited, [archive, edited]), 0)

    def test_mismatched_tracer_profile_or_snapshot_owner_remains_archived(self):
        original = self.analysis[1]
        self.analysis[1] = record(0x46, bytes([1]) * 1348)
        self.assertEqual(self.restore(), (set(), set()))
        self.analysis[1] = original
        self.snapshots[5] = None
        self.assertEqual(self.restore(), (set(), set()))
        self.assertNotIn("legacy_recipes", self.source.attrs)

    def test_all_four_series_must_agree_with_the_drawing_cache(self):
        self.curve.loc[3, "Treatment"] += 1
        self.assertEqual(self.restore(), (set(), set()))
        self.assertNotIn("legacy_recipes", self.source.attrs)

    def test_sparse_observations_keep_their_row_positions(self):
        axes = [{"bounds": [0., maximum], "length": maximum, "unit": 1., "scale": "linear"}
                for maximum in (3., 20.)]
        values = np.array([[0., 10.], [1., np.nan], [2., 20.], [3., np.nan]])
        cache = np.array([[0, 10], [-1, -1], [2, 20]])
        self.assertTrue(legacy._matching_observations(cache, values, axes))
        self.assertFalse(legacy._matching_observations(cache[[0, 2, 1]], values, axes))
        self.assertFalse(legacy._matching_observations(cache[:2], values, axes))


    def test_joint_fit_samples_a_log_drawing_without_changing_the_estimates(self):
        from analisi.repeated_workbench import global_analysis

        model = "Operational model (depletion) (concentration X)"
        equation = MODELS[model].equation
        x = np.geomspace(1e-8, .001, 12)
        frame = pd.DataFrame({"X": x, "Control": equation(x, 100, 16000, 1e-5, 10, 1.3),
                              "Treatment": equation(x, 100, 16000, 1e-5, .5, 1.3)})
        options = {"Model": model, "Input format": "Wide XY", "X": "X", "Y columns": ["Control", "Treatment"],
                   "Shared parameters": ["Basal", "Effect max", "KA", "Transducer slope"]}
        baseline = global_analysis(frame, options)
        grid = {"model": model, "x": "X", "series": options["Y columns"], "spacing": "log",
                rr.CURVE_MIN: 1e-8, rr.CURVE_MAX: .001, rr.CURVE_POINTS: 63}
        restored = global_analysis(frame, {**options, FIT_GRAPH_SPEC: grid})
        pd.testing.assert_frame_equal(restored.tables["Parameters"], baseline.tables["Parameters"])
        for series in options["Y columns"]:
            curve = restored.tables["Fit curves"].query("Series == @series")
            np.testing.assert_array_equal(curve["X"], np.geomspace(1e-8, .001, 63))

    def test_imported_bell_recipe_keeps_each_fit_and_the_two_sampling_grids(self):
        x = np.geomspace(1e-11, .01, 24)
        model = "Bell-shaped dose-response with signed slopes (concentration X)"
        spec = MODELS[model]
        negative = (30., 110., 90., 10**-8.5, 1e-4, -.8, -1.3)
        positive = (90., 10., 30., 10**-8.5, 1e-4, .8, 1.3)
        y = ["Control $", "Treatment"]
        frame = pd.DataFrame({"Dose": x})
        starts = {}
        for series, values in zip(y, [negative, positive], strict=True):
            starts[series] = dict(zip(spec.parameters, values, strict=True))
            frame[series] = spec.equation(x, *values) + .001 * np.sin(np.arange(len(x)))
        ranges = {rr.CURVE_MIN: 1e-11, rr.CURVE_MAX: .01, rr.CURVE_POINTS: 63}
        options = {
            "X": "Dose", "Y columns": y, "Model": model, "Merge numbered replicates": True,
            "Starting coefficients by series": starts, **ranges,
            FIT_GRAPH_SPEC: {"x": "Dose", "series": y, "model": model, "spacing": "log", **ranges},
            LEGACY_GRAPH_LINK: "example:7",
        }
        result = analyse("Nonlinear regression", frame, options)
        for index, (series, values) in enumerate(zip(y, [negative, positive], strict=True)):
            estimates = result.tables[f"Parameters: {series}"]["Estimate"]
            np.testing.assert_allclose(estimates, values, rtol=2e-4, atol=1e-7)
            self.assertEqual(result.tables[f"Fit: {series}"].loc["df", "Value"], len(x) - len(values))
            table = result.tables[f"{rr.CURVE_SHEET}: {series}"]
            np.testing.assert_allclose(table["X"], np.linspace(1e-11, .01, 63), atol=1e-16)
            np.testing.assert_array_equal(result.figure.axes[0].lines[index].get_xdata(),
                                          np.geomspace(1e-11, .01, 63))
        archive = SimpleNamespace(method=SAVED_BINARY_GRAPH, options={LEGACY_GRAPH_LINK: "example:7"})
        edited = SimpleNamespace(method="Nonlinear regression", options=options)
        self.assertEqual(paired_graph_index(archive, [archive, edited]), 1)

    def test_fractional_dose_drawing_can_omit_observations_without_changing_the_fit(self):
        x = np.linspace(-9., -3., 12)
        model = "ECanything (log10 X)"
        y = MODELS[model].equation(x, 2., 80., -5., 1.2, 75.)
        frame = pd.DataFrame({"Dose": x, "Signal": y + .001 * np.sin(x)})
        options = {"Model": model, "Input format": "Wide XY", "X": "Dose", "Y columns": ["Signal"],
                   "Fixed parameters": {"F": 75.}}
        original = analyse("Global nonlinear regression", frame, options)
        saved = {"model": model, "x": "Dose", "series": ["Signal"], "observations": False,
                 rr.CURVE_MIN: -9., rr.CURVE_MAX: -3., rr.CURVE_POINTS: 51}
        restored = analyse("Global nonlinear regression", frame, {**options, FIT_GRAPH_SPEC: saved})
        pd.testing.assert_frame_equal(original.tables["Parameters"], restored.tables["Parameters"])
        self.assertEqual(restored.tables["Joint fit"].loc["df", "Value"], 8)
        self.assertEqual(len(restored.figure.axes[0].collections), 0)
        saved_axis = np.linspace(-9., -3., 51)
        np.testing.assert_allclose(restored.figure.axes[0].lines[0].get_xdata(), saved_axis, rtol=2e-15)
        np.testing.assert_allclose(restored.tables["Fit curves"]["X"], saved_axis, rtol=2e-15)
