"""0.53 standard curve: inverse intervals on the line, 4PL Y from X and replicate counts.

The fixtures and expected values in data/calibration_053 come from independent references
(QR least squares and polynomial roots for the line, a 4PL refit in log coordinates with its own
Jacobian). The remaining tests check properties that do not need a reference: brute-force band
inversion, invariance to shifts and scales, gradients by finite differences and option handling.
"""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi import nonlinear_calibration as cal
from analisi.curve_models import MODELS
from analisi.processing import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "calibration_053"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = "Interpolate a standard curve"
INV, PRED = cal.INTERPOLATED, cal.PREDICTIONS
FOUR_PL = {"stim": "Stimulation", "inhib": "Inhibition"}


def fixture(name):
    return pd.read_csv(DATA / f"{name}.csv")


def inverse(frame, uncertainty="Mean response", level=95.0, **extra):
    options = {"X": "X", "Y": "Y", "Direction": "X from Y", "Curve": "Linear", "Unknown responses": "Query Y",
               "Uncertainty": uncertainty, "Confidence level (%)": level, **extra}
    return analyse(METHOD, frame, options)


def forward(frame, model=None, uncertainty="Prediction", level=90.0, **extra):
    options = {"X": "X", "Y": "Y", "Direction": "Y from X", "Unknown X": "Query X", "Uncertainty": uncertainty,
               "Confidence level (%)": level, "Curve": "Linear" if model is None else "Nonlinear", **extra}
    if model is not None:
        options["Model"] = model
    return analyse(METHOD, frame, options)


def records(table, fields):
    chosen = table[fields].astype(object)
    return chosen.where(chosen.notna(), None).to_dict(orient="records")


def assert_records(case, actual, expected, tolerance):
    case.assertEqual(len(actual), len(expected))
    for got, want in zip(actual, expected, strict=True):
        for key, value in want.items():
            if isinstance(value, float):
                np.testing.assert_allclose(got[key], value, rtol=tolerance, atol=tolerance, err_msg=key)
            else:
                case.assertEqual(got[key], value, key)


def brute_force(frame, response, kind, level, k=1, points=200001):
    """X in the observed range whose band at X contains the response, on a dense grid."""
    data = frame[["X", "Y"]].dropna().to_numpy(dtype=float)
    x, y = data.T
    n = len(x)
    slope, intercept = np.polyfit(x, y, 1)
    s2 = np.sum((y - intercept - slope * x)**2) / (n - 2)
    q = stats.t.isf((100 - level) / 200, n - 2)
    grid = np.linspace(x.min(), x.max(), points)
    r = 0.0 if kind == "Mean response" else 1.0 / k
    half = q * np.sqrt(s2 * (1 / n + r + (grid - x.mean())**2 / np.sum((x - x.mean())**2)))
    inside = np.abs(response - (intercept + slope * grid)) <= half
    edges = np.flatnonzero(np.diff(inside.astype(int)))
    pieces, start = [], grid[0] if inside[0] else None
    for edge in edges:
        if inside[edge]:
            pieces.append((start, grid[edge]))
            start = None
        else:
            start = grid[edge + 1]
    if start is not None:
        pieces.append((start, grid[-1]))
    return pieces, grid[1] - grid[0]


class PackageFixtureTests(unittest.TestCase):
    """The fixture cases of the 0.53 package, through the dispatcher."""

    def test_inverse_cases(self):
        cases = {"linear-inverse-mean": ("linear", "Mean response", 95.0, False),
                 "linear-inverse-prediction": ("linear", "Prediction", 95.0, True),
                 "linear-inverse-high-confidence": ("linear", "Mean response", np.nextafter(100., 0.), False),
                 "linear-inverse-disconnected": ("disconnected", "Mean response", 95.0, False),
                 "linear-inverse-exact-fit": ("exact", "Prediction", 95.0, False)}
        for name, (data, kind, level, counted) in cases.items():
            with self.subTest(name):
                extra = {cal.COUNT: "K"} if counted else {}
                result = inverse(fixture(data), kind, level, **extra)
                table = result.tables[INV]
                expected = EXPECTED[name]
                self.assertEqual(list(table.columns[3:6]), ["X lower", "X upper", cal.INTERVAL_STATUS])
                if counted:
                    self.assertEqual(table.columns[-1], cal.REPLICATES)
                assert_records(self, records(table, list(expected["rows"][0])), expected["rows"], 3e-5)
                if expected["components"]:
                    components = result.tables[cal.COMPONENTS]
                    self.assertEqual(list(components.columns), ["Source row", "Component", "X lower", "X upper"])
                    assert_records(self, records(components, list(components.columns)), expected["components"], 1e-8)
                else:
                    self.assertNotIn(cal.COMPONENTS, result.tables)

    def test_legacy_inverse_is_unchanged(self):
        frame = fixture("linear")
        legacy = analyse(METHOD, frame, {"X": "X", "Y": "Y", "Unknown responses": "Query Y", "Curve": "Linear"})
        explicit = inverse(frame, "None", 500, **{cal.COUNT: "Row title"})
        self.assertEqual(list(legacy.tables), [INV, "Linear calibration"])
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], explicit.tables[name])
        assert_records(self, records(legacy.tables[INV], list(legacy.tables[INV].columns)),
                       EXPECTED["linear-legacy"]["rows"], 1e-12)

    def test_forward_cases(self):
        for name, expected in EXPECTED.items():
            if name.startswith("linear-inverse") or name == "linear-legacy":
                continue
            data, _, rest = name.partition("-")
            if data in FOUR_PL:
                unit, _, kind = rest.partition("-")
                model = f"{FOUR_PL[data]} (variable slope{', log10 X' if unit == 'log10' else ''})"
                frame = fixture(f"{data}-{unit}")
            else:
                model = None if data == "linear" else "One-phase decay"
                frame = fixture(data)
                kind = "prediction"
            kind = {"none": "None", "mean-response": "Mean response", "prediction": "Prediction"}[kind]
            level = 95.0 if data == "linear" else 90.0
            counted = kind == "Prediction"
            with self.subTest(name):
                result = forward(frame, model, kind, level, **({cal.COUNT: "K"} if counted else {}))
                table = result.tables[PRED]
                if counted:
                    self.assertEqual(table.columns[-1], cal.REPLICATES)
                else:
                    self.assertNotIn(cal.REPLICATES, table.columns)
                assert_records(self, records(table, list(expected["rows"][0])), expected["rows"], 3e-5)
                self.assertEqual(cal.BANDS in result.tables, kind != "None")


class InverseIntervalTests(unittest.TestCase):
    def test_components_of_the_quadratic(self):
        pieces = cal._inverse_components
        # Positive leading coefficient: one piece, clipped or not.
        self.assertEqual(pieces(1, 0, -.25, -1, 1), [(-.5, .5, False, False)])
        self.assertEqual(pieces(1, 0, -4, -1, 1), [(-1, 1, True, True)])
        # Negative leading coefficient: up to two pieces at the bounds.
        self.assertEqual(pieces(-1, 0, .25, -1, 1), [(-1, -.5, True, False), (.5, 1, False, True)])
        self.assertEqual(pieces(-1, 1, 0, -1, .5), [(-1, 0, True, False)])
        # A tangent does not split the set; neither does a constant.
        self.assertEqual(pieces(-1, 0, 0, -1, 1), [(-1, 1, True, True)])
        self.assertEqual(pieces(0, 0, -1, -1, 1), [(-1, 1, True, True)])
        self.assertEqual(pieces(0, 0, 1, -1, 1), [])
        # Linear: a half-line.
        self.assertEqual(pieces(0, 2, -1, -1, 1), [(-1, .5, True, False)])
        # An exact root on a bound belongs to the set, also when it is isolated.
        self.assertEqual(pieces(1, 0, -1, -1, 1), [(-1, 1, True, True)])
        self.assertEqual(pieces(-1, 0, 1, -1, 2), [(-1, -1, True, False), (1, 2, False, True)])
        # Coefficients that cannot be represented leave the interval unavailable.
        self.assertIsNone(pieces(np.inf, 0, 1, -1, 1))
        # Scaling all coefficients does not change the answer.
        self.assertEqual(pieces(-1e-300, 0, .25e-300, -1, 1), pieces(-1, 0, .25, -1, 1))
        # Roots of very different size keep their digits.
        small = pieces(1, -1e8, 1, -1, 1)
        np.testing.assert_allclose(small[0][0], 1e-8, rtol=1e-15)

    def test_positive_quadratic_tangent_is_an_isolated_point(self):
        pieces = cal._inverse_components
        self.assertEqual(pieces(1, 0, 0, -1, 1), [(0, 0, False, False)])
        self.assertEqual(pieces(1, -1, .25, -1, 1), [(.5, .5, False, False)])
        self.assertEqual(pieces(1, -2, 1, -1, 1), [(1, 1, False, True)])

    def test_intervals_match_band_inversion(self):
        rng = np.random.default_rng(530)
        for trial in range(12):
            n = int(rng.integers(4, 12))
            x = np.sort(rng.uniform(-5, 20, n))
            y = 3 + rng.normal(0.4, 0.8) * x + rng.normal(0, 2.5, n)
            queries = np.r_[rng.uniform(y.min(), y.max(), 4), np.nan * np.ones(n - 4)] if n > 4 else \
                rng.uniform(y.min(), y.max(), n)
            frame = pd.DataFrame({"X": x, "Y": y, "Query Y": queries[:n], "K": rng.integers(1, 6, n)})
            for kind in ("Mean response", "Prediction"):
                level = float(rng.choice([80., 95., 99.]))
                extra = {cal.COUNT: "K"} if kind == "Prediction" else {}
                try:
                    result = inverse(frame, kind, level, **extra)
                except ValueError:
                    continue
                table = result.tables[INV]
                components = result.tables.get(cal.COMPONENTS)
                for position, (label, row) in enumerate(table.iterrows()):
                    if row["Outside calibration"]:
                        self.assertEqual(row[cal.INTERVAL_STATUS], cal.OUTSIDE_CALIBRATION)
                        continue
                    k = int(frame.at[label, "K"]) if kind == "Prediction" else 1
                    expected, step = brute_force(frame, row["Response"], kind, level, k)
                    if row[cal.INTERVAL_STATUS] == cal.DISCONNECTED:
                        part = components.loc[components["Source row"] == label, ["X lower", "X upper"]]
                        found = [tuple(pair) for pair in part.to_numpy()]
                    else:
                        found = [(row["X lower"], row["X upper"])]
                    with self.subTest(trial=trial, kind=kind, row=position):
                        self.assertEqual(len(found), len(expected))
                        np.testing.assert_allclose(np.ravel(found), np.ravel(expected), atol=2 * step, rtol=0)

    def test_shift_and_scale_of_x(self):
        frame = fixture("linear")
        base = inverse(frame, "Prediction", 95, **{cal.COUNT: "K"}).tables[INV]
        for shift, scale in ((1e7, 1.0), (-3e5, 1e-3), (0.0, 1e9), (0.0, 1e-12)):
            moved = frame.assign(X=frame["X"] * scale + shift)
            table = inverse(moved, "Prediction", 95, **{cal.COUNT: "K"}).tables[INV]
            with self.subTest(shift=shift, scale=scale):
                self.assertEqual(table[cal.INTERVAL_STATUS].tolist(), base[cal.INTERVAL_STATUS].tolist())
                # The 0.53.0 point estimate is uncentered and keeps its own rounding; the limits are centered.
                np.testing.assert_allclose((table["Interpolated X"] - shift) / scale, base["Interpolated X"],
                                           rtol=1e-3, atol=1e-3)
                for column in ("X lower", "X upper"):
                    np.testing.assert_allclose((table[column] - shift) / scale, base[column], rtol=1e-5, atol=1e-5)

    def test_more_replicates_narrow_the_interval(self):
        frame = fixture("linear")
        table = inverse(frame, "Prediction", 95, **{cal.COUNT: "K"}).tables[INV]
        self.assertEqual(table[cal.REPLICATES].tolist(), [1, 4, 1, 1, 2])
        width = table["X upper"] - table["X lower"]
        self.assertLess(width.iloc[1], width.iloc[0])
        mean = inverse(frame, "Mean response", 95, **{cal.COUNT: "K"}).tables[INV]
        self.assertNotIn(cal.REPLICATES, mean.columns)
        self.assertTrue((mean["X upper"] - mean["X lower"] <= width + 1e-12).iloc[:2].all())

    def test_unavailable_and_horizontal(self):
        exact = pd.DataFrame({"X": [0., 1., 2.], "Y": [1., 3., 5.], "Query Y": [2., np.nan, np.nan]})
        table = inverse(exact, "Mean response").tables[INV]
        self.assertEqual(table[cal.INTERVAL_STATUS].tolist(), [cal.UNCERTAINTY_UNAVAILABLE])
        self.assertAlmostEqual(table["Interpolated X"].iloc[0], .5)
        self.assertTrue(table[["X lower", "X upper"]].isna().all().all())
        flat = pd.DataFrame({"X": [0., 1., 2.], "Y": [1., 1., 1.], "Query Y": [1., np.nan, np.nan]})
        with self.assertRaisesRegex(ValueError, "horizontal"):
            inverse(flat, "Mean response")

    def test_decay_inverse_intervals_keep_the_none_path_and_association_stays_point_only(self):
        frame = fixture("decay").assign(**{"Query Y": [5., 3., np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]})
        options = {"X": "X", "Y": "Y", "Direction": "X from Y", "Unknown responses": "Query Y", "Curve": "Nonlinear",
                   "Model": "One-phase decay"}
        # A stale level on None must not change the point-estimate tables.
        legacy = analyse(METHOD, frame, {**options, "Uncertainty": "None", "Confidence level (%)": 500})
        self.assertIn(INV, legacy.tables)
        self.assertNotIn("X lower", legacy.tables[INV].columns)
        result = analyse(METHOD, frame, {**options, "Uncertainty": "Mean response", "Confidence level (%)": 95})
        table = result.tables[INV]
        self.assertEqual(table[cal.INTERVAL_STATUS].tolist(), [cal.COMPLETE, cal.COMPLETE])
        self.assertTrue((table["X lower"] < table["Interpolated X"]).all())
        self.assertTrue((table["Interpolated X"] < table["X upper"]).all())
        association = {**options, "Model": "One-phase association", "Uncertainty": "Mean response"}
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, association)
        self.assertEqual(raised.exception.field, cal.UNCERTAINTY)

    def test_source_rows_and_duplicates(self):
        frame = fixture("disconnected")
        # A row with only a query, under a label that the first row also carries.
        frame = pd.concat([frame, pd.DataFrame({"Query Y": [5.72]})])
        frame.index = [10, 11, 12, 13, 14, 15, 16, 17, 10]
        result = inverse(frame, "Mean response")
        table = result.tables[INV]
        self.assertEqual(list(table.index), [10, 10])
        components = result.tables[cal.COMPONENTS]
        self.assertEqual(components["Source row"].tolist(), [10, 10, 10, 10])
        self.assertEqual(components["Component"].tolist(), [1, 2, 1, 2])
        self.assertTrue((np.diff(components["X lower"].to_numpy()[:2]) > 0).all())


class ReplicateCountTests(unittest.TestCase):
    def test_invalid_counts_name_the_field_and_row(self):
        frame = fixture("linear")
        for value in (None, 0, -1, 1.5, np.inf, np.nan, "bad", "1,5", True, np.True_):
            invalid = frame.astype({"K": object})
            invalid.loc[4, "K"] = value  # The response 40 is outside the calibration range.
            for run in (lambda data: inverse(data, "Prediction", **{cal.COUNT: "K"}),
                        lambda data: forward(data, None, "Prediction", **{cal.COUNT: "K"})):
                with self.subTest(value=value), self.assertRaises(FieldError) as raised:
                    run(invalid)
                self.assertEqual(raised.exception.field, cal.COUNT)
                self.assertIn("row 5", str(raised.exception))

    def test_replicates_are_checked_before_float_rounding(self):
        frame = fixture("linear").astype({"K": object})
        for value in (2**53 + 1, str(2**53 + 1), "9007199254740991.5"):
            with self.subTest(value=value):
                frame.loc[0, "K"] = value
                with self.assertRaises(FieldError):
                    inverse(frame, "Prediction", **{cal.COUNT: "K"})
        frame.loc[0, "K"] = str(2**53)
        self.assertEqual(inverse(frame, "Prediction", **{cal.COUNT: "K"}).tables[INV][cal.REPLICATES].iloc[0], 2**53)

    def test_forward_titles_and_counts_align_with_duplicate_index_labels(self):
        frame = fixture("linear")
        frame.index = [10, 10, 11, 12, 13, 14, 15, 16]
        table = forward(frame, None, "Prediction", 95, **{cal.COUNT: "K"}).tables[PRED]
        self.assertEqual(table["Source row"].tolist(), [10, 10, 11, 12, 13])
        self.assertEqual(table["Row title"].tolist(), frame["Row title"].iloc[:5].tolist())
        self.assertEqual(table[cal.REPLICATES].tolist(), [1, 4, 1, 1, 2])

    def test_accepted_counts(self):
        frame = fixture("linear").astype({"K": object})
        frame.loc[:4, "K"] = ["1", "4,0", 1.0, np.int64(1), "2"]
        frame.loc[6, "K"] = "text without a query"
        table = inverse(frame, "Prediction", **{cal.COUNT: "K"}).tables[INV]
        self.assertEqual(table[cal.REPLICATES].tolist(), [1, 4, 1, 1, 2])
        # An excluded query needs no count; an excluded count on a used query is missing.
        excluded = fixture("linear")
        excluded.loc[1, "Query Y"] = np.nan
        excluded.loc[1, "K"] = np.nan
        self.assertEqual(inverse(excluded, "Prediction", **{cal.COUNT: "K"}).tables[INV][cal.REPLICATES].tolist(),
                         [1, 1, 1, 2])
        missing = fixture("linear")
        missing.loc[2, "K"] = np.nan
        with self.assertRaises(FieldError):
            inverse(missing, "Prediction", **{cal.COUNT: "K"})

    def test_counts_are_read_only_for_prediction(self):
        frame = fixture("linear").assign(K="bad")
        for kind in ("None", "Mean response"):
            inverse(frame, kind, **{cal.COUNT: "K"})
            result = forward(frame, None, kind, **{cal.COUNT: "K"})
            self.assertNotIn(cal.REPLICATES, result.tables[PRED].columns)
        with self.assertRaises(FieldError) as raised:
            inverse(fixture("linear"), "Prediction", **{cal.COUNT: "Missing column"})
        self.assertEqual(raised.exception.field, cal.COUNT)
        with self.assertRaises(FieldError) as raised:
            inverse(fixture("linear"), "Prediction", **{cal.COUNT: "Query Y"})
        self.assertEqual(raised.exception.field, cal.COUNT)

    def test_forward_counts_keep_rows_and_the_band(self):
        frame = fixture("linear")
        counted = forward(frame, None, "Prediction", 95, **{cal.COUNT: "K"})
        single = forward(frame, None, "Prediction", 95)
        table = counted.tables[PRED]
        self.assertEqual(table["Source row"].tolist(), [0, 1, 2, 3, 4])
        width = table["Y upper"] - table["Y lower"]
        self.assertLess(width.iloc[1], width.iloc[0])
        pd.testing.assert_frame_equal(counted.tables[cal.BANDS], single.tables[cal.BANDS])
        pd.testing.assert_frame_equal(table.drop(columns=cal.REPLICATES).iloc[[0, 2, 3, 4]],
                                      single.tables[PRED].iloc[[0, 2, 3, 4]])
        labels = [text.get_text() for text in counted.figure.axes[0].get_legend().get_texts()]
        self.assertIn("95% prediction band (k = 1)", labels)
        labels = [text.get_text() for text in single.figure.axes[0].get_legend().get_texts()]
        self.assertIn("95% prediction band", labels)


class FourParameterTests(unittest.TestCase):
    def test_gradient_by_finite_differences(self):
        for model, theta, values in (
                ("Stimulation (variable slope)", (1.5, 10., .3, 1.4), [0., 1e-3, .3, 2., 20.]),
                ("Inhibition (variable slope)", (1.5, 10., .3, -1.4), [0., 1e-3, .3, 2., 20.]),
                ("Stimulation (variable slope, log10 X)", (1.5, 10., -.5, 1.4), [-3., -.5, 1.3]),
                ("Inhibition (variable slope, log10 X)", (1.5, 10., -.5, -1.4), [-3., -.5, 1.3])):
            gradient = cal._four_pl_gradient(model, theta, values)
            self.assertTrue(np.isfinite(gradient).all())
            for j in range(4):
                step = 1e-6 * max(abs(theta[j]), 1e-3)
                up, down = list(theta), list(theta)
                up[j] += step
                down[j] -= step
                numeric = (MODELS[model].equation(np.array(values), *up)
                           - MODELS[model].equation(np.array(values), *down)) / (2 * step)
                with self.subTest(model=model, parameter=j):
                    np.testing.assert_allclose(gradient[:, j], numeric, rtol=1e-6, atol=1e-8)
        zero = cal._four_pl_gradient("Inhibition (variable slope)", (1.5, 10., .3, -1.4), [0.])
        np.testing.assert_array_equal(zero, [[0., 1., 0., 0.]])

    def test_small_concentrations_keep_their_band(self):
        frame = fixture("stim-concentration")
        model = "Stimulation (variable slope)"
        base = forward(frame, model, "Prediction", 90, **{cal.COUNT: "K"})
        for scale in (1e-9, 1e-15):
            scaled = frame.assign(X=frame["X"] * scale, **{"Query X": frame["Query X"] * scale})
            result = forward(scaled, model, "Prediction", 90, **{cal.COUNT: "K"})
            with self.subTest(scale=scale):
                table, reference = result.tables[PRED], base.tables[PRED]
                self.assertEqual(table["Status"].tolist(), reference["Status"].tolist())
                np.testing.assert_allclose(table[["Predicted Y", "Y lower", "Y upper"]].to_numpy(dtype=float),
                                           reference[["Predicted Y", "Y lower", "Y upper"]].to_numpy(dtype=float),
                                           rtol=1e-4, atol=1e-4, equal_nan=True)
                self.assertFalse(cal._at_bound(model, result.tables["Calibration parameters"]["Estimate"]))

    def test_parameters_on_a_bound(self):
        tiny = np.finfo(float).tiny
        self.assertTrue(cal._at_bound("Stimulation (variable slope)", (1., 2., tiny, 1.)))
        self.assertTrue(cal._at_bound("Stimulation (variable slope)", (1., 2., 1., tiny * (1 + 1e-12))))
        self.assertTrue(cal._at_bound("Inhibition (variable slope)", (1., 2., 1., -tiny)))
        self.assertFalse(cal._at_bound("Stimulation (variable slope)", (1., 2., 1e-12, 1.)))
        self.assertFalse(cal._at_bound("Inhibition (variable slope, log10 X)", (1., 2., -300., -1.)))

    def test_covariance_checks(self):
        self.assertTrue(cal._usable_covariance(np.eye(4), 4))
        self.assertFalse(cal._usable_covariance(None, 4))
        self.assertFalse(cal._usable_covariance(np.eye(3), 4))
        self.assertFalse(cal._usable_covariance(np.diag([1., 1., 0., 1.]), 4))
        self.assertFalse(cal._usable_covariance(np.diag([1., 1., np.nan, 1.]), 4))
        skew = np.eye(4)
        skew[0, 1] = .5
        self.assertFalse(cal._usable_covariance(skew, 4))
        indefinite = np.eye(4)
        indefinite[0, 1] = indefinite[1, 0] = 1.5
        self.assertFalse(cal._usable_covariance(indefinite, 4))

    def test_band_domain_includes_zero_and_matches_the_standards(self):
        for name, model in (("stim-concentration", "Stimulation (variable slope)"),
                            ("inhib-log10", "Inhibition (variable slope, log10 X)")):
            frame = fixture(name)
            result = forward(frame, model, "Mean response", 90)
            grid = result.tables[cal.BANDS]["X"].to_numpy()
            with self.subTest(name):
                self.assertEqual((grid[0], grid[-1]), (frame["X"].min(), frame["X"].max()))
                self.assertTrue((np.diff(grid) > 0).all())
                line = result.figure.axes[0]
                self.assertEqual(line.get_xscale(), "linear")
                low, high = line.get_xlim()
                self.assertLessEqual(low, frame["X"].min())
                self.assertGreaterEqual(high, frame["X"].max())

    def test_domains(self):
        frame = fixture("stim-concentration")
        table = forward(frame, "Stimulation (variable slope)", "None").tables[PRED]
        self.assertEqual(table["Status"].tolist(), ["In range", "In range", "In range", "In range",
                                                    cal.OUTSIDE_CALIBRATION])
        negative = frame.assign(X=frame["X"] - 1)
        with self.assertRaises(FieldError) as raised:
            forward(negative, "Stimulation (variable slope)", "None")
        self.assertEqual(raised.exception.field, "Model")
        logged = forward(fixture("stim-log10"), "Stimulation (variable slope, log10 X)", "None").tables[PRED]
        self.assertEqual(logged["Status"].iloc[2], "In range")
        self.assertLess(logged["X"].iloc[2], 0)

    def test_inverse_4pl_is_unchanged(self):
        frame = fixture("inhib-concentration").assign(**{"Query Y": [5., 9., 1., np.nan] + [np.nan] * 7})
        options = {"X": "X", "Y": "Y", "Unknown responses": "Query Y", "Curve": "Nonlinear",
                   "Model": "Inhibition (variable slope)"}
        legacy = analyse(METHOD, frame, options)
        dialog = analyse(METHOD, frame, {**options, "Direction": "X from Y", "Uncertainty": "None"})
        self.assertEqual(list(legacy.tables), [INV, "Calibration parameters", "Fit diagnostics"])
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], dialog.tables[name])


class LegacyRecipeTests(unittest.TestCase):
    """Recipes that 0.53.0 could save give the same tables, legends and titles.

    data/calibration_053/legacy-0530.json was written by the 0.53.0 tag (7350cfc) from the recipes below.
    """

    def test_tables_match_0530(self):
        reference = json.loads((DATA / "legacy-0530.json").read_text(encoding="utf-8"))
        linear, decay = fixture("linear"), fixture("decay")
        empty = [np.nan] * 7
        recipes = {
            "linear-inverse": (linear, {"Unknown responses": "Query Y", "Curve": "Linear"}),
            "linear-inverse-dialog": (linear, {"Direction": "X from Y", "Unknown responses": "Query Y",
                                               "Curve": "Linear"}),
            "decay-inverse": (decay.assign(**{"Query Y": [5., 3., 9., *empty[:6]]}),
                              {"Unknown responses": "Query Y", "Curve": "Nonlinear", "Model": "One-phase decay"}),
            "stim-inverse": (fixture("stim-concentration").assign(**{"Query Y": [2.5, 5., 9., 12., *empty]}),
                             {"Unknown responses": "Query Y", "Curve": "Nonlinear",
                              "Model": "Stimulation (variable slope)"}),
            "inhib-log-inverse": (fixture("inhib-log10").assign(**{"Query Y": [3., 6., 9.5, *empty]}),
                                  {"Unknown responses": "Query Y", "Curve": "Nonlinear",
                                   "Model": "Inhibition (variable slope, log10 X)"}),
            "linear-forward": (linear, {"Direction": "Y from X", "Unknown X": "Query X", "Curve": "Linear",
                                        "Uncertainty": "Prediction", "Confidence level (%)": 95.0}),
            "decay-forward": (decay, {"Direction": "Y from X", "Unknown X": "Query X", "Curve": "Nonlinear",
                                      "Model": "One-phase decay", "Uncertainty": "Mean response",
                                      "Confidence level (%)": 90.0}),
            "decay-forward-none": (decay, {"Direction": "Y from X", "Unknown X": "Query X", "Curve": "Nonlinear",
                                           "Model": "One-phase decay", "Uncertainty": "None"}),
        }
        self.assertEqual(set(recipes), set(reference))
        for name, (frame, options) in recipes.items():
            result = analyse(METHOD, frame, {"X": "X", "Y": "Y", **options})
            expected = reference[name]
            with self.subTest(name):
                self.assertEqual(list(result.tables), list(expected["tables"]))
                for sheet, table in result.tables.items():
                    stored = expected["tables"][sheet]
                    self.assertEqual([str(column) for column in table.columns], stored["columns"])
                    data = json.loads(table.to_json(orient="split", double_precision=15))["data"]
                    # Nonlinear optimizer rounding depends on the platform. Table layout and text stay exact.
                    self.assertEqual(len(data), len(stored["data"]))
                    for actual, expected_row in zip(data, stored["data"], strict=True):
                        for value, reference_value in zip(actual, expected_row, strict=True):
                            if isinstance(reference_value, float):
                                np.testing.assert_allclose(value, reference_value, rtol=1e-6, atol=1e-8, err_msg=sheet)
                            else:
                                self.assertEqual(value, reference_value, sheet)
                axis = result.figure.axes[0]
                self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], expected["legend"])
                self.assertEqual(axis.get_title(), expected["title"])


if __name__ == "__main__":
    unittest.main()
