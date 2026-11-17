"""Point estimates from one-phase standard curves, inside the observed X range."""
import unittest

import numpy as np
import pandas as pd

from analisi.curve_models import MODELS
from analisi.exploration import interpolate_linear
from analisi.nonlinear_calibration import (IN_RANGE, INVERSE_MODELS, NOT_IDENTIFIABLE, OUT_OF_RANGE,
                                           interpolate_standard_curve)
from analisi.reporting import _report
from analisi.stats import nonlinear


X = np.array([0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
NOISE = np.array([0.15, -0.20, 0.05, 0.10, -0.12, 0.08, -0.05, 0.04])


def decay_response(x, plateau=2.0, span=8.0, rate=0.7):
    return plateau + span * np.exp(-rate * x)


def association_response(x, y0=1.0, plateau=9.0, rate=0.5):
    return y0 + (plateau - y0) * (1.0 - np.exp(-rate * x))


def decay_time(response, plateau=2.0, span=8.0, rate=0.7):
    return -np.log((response - plateau) / span) / rate


def association_time(response, y0=1.0, plateau=9.0, rate=0.5):
    return -np.log(1.0 - (response - y0) / (plateau - y0)) / rate


class NonlinearCalibrationTests(unittest.TestCase):
    def test_exact_decay_inverts_inside_the_observed_interval(self):
        responses = [decay_response(1.25), np.nan, decay_response(4.5), decay_response(0.0), 11.0,
                     decay_response(6.0), np.nan, np.nan]
        titles = ["A", "B", None, "D", "E", "F", "G", "H"]
        frame = pd.DataFrame({"Row titles": titles, "X": X, "Y": decay_response(X), "Unknown": responses},
                             index=np.arange(10, 18))
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", curve="Nonlinear", model="One-phase decay")
        table = result.tables["Interpolated values"]
        self.assertEqual(list(table.columns),
                         ["Source row", "Row title", "Response", "Interpolated X", "Status", "Domain low", "Domain high"])
        self.assertEqual(table["Source row"].tolist(), [10, 12, 13, 14, 15])
        self.assertEqual(table.at[0, "Row title"], "A")
        self.assertTrue(pd.isna(table.at[1, "Row title"]))
        np.testing.assert_allclose(table["Interpolated X"].iloc[:2], [1.25, 4.5], atol=1e-6, rtol=0)
        self.assertEqual(table.at[2, "Interpolated X"], 0.0)
        self.assertEqual(table.at[4, "Interpolated X"], 6.0)
        self.assertTrue(pd.isna(table.at[3, "Interpolated X"]))
        self.assertEqual(table["Status"].tolist(), [IN_RANGE, IN_RANGE, IN_RANGE, OUT_OF_RANGE, IN_RANGE])
        self.assertTrue((table["Domain low"] == 0.0).all())
        self.assertTrue((table["Domain high"] == 6.0).all())
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"], [2.0, 8.0, 0.7],
                                   atol=1e-8, rtol=0)
        self.assertEqual(result.tables["Fit diagnostics"].at["N", "Value"], 8)
        self.assertEqual(result.model, "One-phase decay")
        self.assertEqual(len(result.curve), 300)
        self.assertGreater(np.diff(result.curve[:, 0]).min(), 0)
        self.assertLess(abs(table.at[0, "Interpolated X"] - 1.25), np.diff(result.curve[:, 0]).min() / 50)
        fitted = MODELS["One-phase decay"].equation(result.curve[:, 0], 2.0, 8.0, 0.7)
        np.testing.assert_allclose(result.curve[:, 1], fitted, atol=1e-6, rtol=0)

    def test_exact_association_inverts_interior_endpoints_and_rejects_the_outside(self):
        responses = [association_response(1.25), np.nan, association_response(4.5), association_response(0.0), 0.0]
        responses += [np.nan] * (len(X) - len(responses))
        frame = pd.DataFrame({"X": X, "Y": association_response(X), "Unknown": responses})
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase association")
        table = result.tables["Interpolated values"]
        self.assertNotIn("Row title", table.columns)
        self.assertEqual(table["Source row"].tolist(), [0, 2, 3, 4])
        np.testing.assert_allclose(table.loc[table["Source row"] == 0, "Interpolated X"], [1.25], atol=1e-6, rtol=0)
        np.testing.assert_allclose(table.loc[table["Source row"] == 2, "Interpolated X"], [4.5], atol=1e-6, rtol=0)
        self.assertEqual(table.loc[table["Source row"] == 3, "Interpolated X"].item(), 0.0)
        outside = table.loc[table["Source row"] == 4].iloc[0]
        self.assertTrue(pd.isna(outside["Interpolated X"]))
        self.assertEqual(outside["Status"], OUT_OF_RANGE)
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"], [1.0, 9.0, 0.5],
                                   atol=1e-8, rtol=0)

    def test_both_directions_remain_invertible(self):
        cases = (
            ("One-phase decay", decay_response(X, plateau=10.0, span=-8.0), decay_response,
             {"plateau": 10.0, "span": -8.0}),
            ("One-phase association", association_response(X, y0=9.0, plateau=1.0), association_response,
             {"y0": 9.0, "plateau": 1.0}),
        )
        for model, standards, truth, parameters in cases:
            with self.subTest(model=model, direction="flipped"):
                responses = [truth(1.25, **parameters), np.nan, truth(4.5, **parameters), truth(0.0, **parameters)]
                responses += [np.nan] * (len(X) - len(responses))
                frame = pd.DataFrame({"X": X, "Y": standards, "Unknown": responses})
                table = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", model).tables[
                    "Interpolated values"]
                self.assertEqual(table["Source row"].tolist(), [0, 2, 3])
                np.testing.assert_allclose(table["Interpolated X"], [1.25, 4.5, 0.0], atol=1e-6, rtol=0)
                self.assertEqual(table["Status"].tolist(), [IN_RANGE, IN_RANGE, IN_RANGE])

    def test_original_unknown_order_is_kept_when_a_later_row_comes_first(self):
        responses = [decay_response(4.5), np.nan, decay_response(1.25)] + [np.nan] * 5
        frame = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": responses})
        solved = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay").tables[
            "Interpolated values"]["Interpolated X"]
        np.testing.assert_allclose(solved, [4.5, 1.25], atol=1e-6, rtol=0)

    def test_shuffled_standards_and_a_missing_standard_do_not_reorder_unknowns(self):
        order = [3, 0, 7, 1, 5, 2, 6, 4]
        responses = np.array([decay_response(1.25), np.nan, decay_response(4.5), np.nan, np.nan, np.nan, np.nan, np.nan])
        frame = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": responses}).iloc[order]
        frame.index = np.arange(30, 38)
        missing = frame.index[frame["X"] == 5.0][0]
        frame.loc[missing, "Y"] = np.nan
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        table = result.tables["Interpolated values"]
        self.assertEqual(table["Source row"].tolist(), [31, 35])
        np.testing.assert_allclose(table["Interpolated X"], [1.25, 4.5], atol=1e-6, rtol=0)
        self.assertEqual(result.tables["Fit diagnostics"].at["N", "Value"], 7)
        direct = nonlinear(frame.drop(columns="Unknown"), "X", "Y", "One-phase decay")["All"]
        pd.testing.assert_frame_equal(result.tables["Calibration parameters"], direct.parameters)
        pd.testing.assert_frame_equal(result.tables["Fit diagnostics"], _report(direct.diagnostics))

    def test_unknowns_do_not_change_the_fit(self):
        base = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": decay_response(1.25)})
        other = base.assign(Unknown=4.0)
        first = interpolate_standard_curve(base, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        second = interpolate_standard_curve(other, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        pd.testing.assert_frame_equal(first.tables["Calibration parameters"], second.tables["Calibration parameters"])
        np.testing.assert_allclose(first.curve, second.curve)
        self.assertNotIn("Unknown", nonlinear(base, "X", "Y", "One-phase decay")["All"].data.columns)

    def test_row_title_is_omitted_when_that_name_is_an_axis(self):
        unknowns = [association_response(1.25), *([np.nan] * (len(X) - 1))]
        frame = pd.DataFrame({"Row title": X, "Signal": association_response(X), "Unknown": unknowns})
        table = interpolate_standard_curve(frame, "Row title", "Signal", "Unknown", "Nonlinear",
                                           "One-phase association").tables["Interpolated values"]
        self.assertNotIn("Row title", table.columns)
        np.testing.assert_allclose(table["Interpolated X"], [1.25], atol=1e-6, rtol=0)
        titled = frame.rename(columns={"Row title": "Dose"}).assign(**{"ROW TITLES": ["one"] * len(X)})
        titled = titled[["ROW TITLES", "Dose", "Signal", "Unknown"]]
        titled_table = interpolate_standard_curve(titled, "Dose", "Signal", "Unknown", "Nonlinear",
                                                  "One-phase association").tables["Interpolated values"]
        self.assertEqual(titled_table["Row title"].tolist(), ["one"])

    def test_noisy_root_matches_the_fitted_response_not_the_latent_time(self):
        cases = (
            ("One-phase decay", decay_response(X) + NOISE, decay_time),
            ("One-phase association", association_response(X) + NOISE, association_time),
        )
        for model, standards, latent_time in cases:
            with self.subTest(model=model):
                probe = nonlinear(pd.DataFrame({"X": X, "Y": standards}), "X", "Y", model)["All"]
                names = MODELS[model].parameters
                theta = tuple(float(probe.parameters.at[name, "Estimate"]) for name in names)
                fitted = MODELS[model].equation
                endpoints = fitted(np.array([X.min(), X.max()]), *theta)
                unknown = float(np.mean(endpoints))
                frame = pd.DataFrame({"X": X, "Y": standards, "Unknown": unknown})
                result = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", model)
                solved = float(result.tables["Interpolated values"].at[0, "Interpolated X"])
                estimate = result.tables["Calibration parameters"]["Estimate"]
                predicted = fitted(np.array([solved]), *(float(estimate[name]) for name in names))
                solved_response = float(np.asarray(predicted, dtype=float).reshape(-1)[0])
                self.assertLess(abs(solved_response - unknown), 1e-6)
                self.assertGreater(abs(solved - float(latent_time(unknown))), 1e-3)
                self.assertEqual(result.tables["Interpolated values"].at[0, "Status"], IN_RANGE)

    def test_negative_standards_and_unsupported_models_fail_without_a_concentration(self):
        frame = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": 6.0})
        frame.loc[2, "X"] = -0.2
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        usable = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": 6.0})
        with self.assertRaisesRegex(ValueError, "supported calibration model"):
            interpolate_standard_curve(usable, "X", "Y", "Unknown", "Nonlinear", "Logistic (4 parameters)")
        with self.assertRaisesRegex(ValueError, "linear or nonlinear"):
            interpolate_standard_curve(usable, "X", "Y", "Unknown", curve="Spline")
        self.assertEqual(INVERSE_MODELS[:2], ("One-phase decay", "One-phase association"))
        self.assertIn("Stimulation (variable slope)", INVERSE_MODELS)
        self.assertIn("Inhibition (variable slope, log10 X)", INVERSE_MODELS)

    def test_flat_fit_reports_one_status_and_no_concentration(self):
        standards = 5.0 + 1e-8 * np.exp(-0.7 * X)
        unknowns = [5.0, np.nan, 5.1, np.nan, np.nan, np.nan, np.nan, 4.0]
        frame = pd.DataFrame({"X": X, "Y": standards, "Unknown": unknowns})
        table = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay").tables[
            "Interpolated values"]
        self.assertEqual(table["Source row"].tolist(), [0, 2, 7])
        self.assertTrue((table["Status"] == NOT_IDENTIFIABLE).all())
        self.assertTrue(table["Interpolated X"].isna().all())

    def test_missing_curve_key_matches_linear_interpolation_column_for_column(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [3.0, 5.0, 7.0, 9.0],
                              "u": [4.0, np.nan, 11.0, np.nan]})
        fit, estimates = interpolate_linear(frame, "x", "y", "u")
        result = interpolate_standard_curve(frame, "x", "y", "u", model="One-phase decay")
        explicit = interpolate_standard_curve(frame, "x", "y", "u", curve="Linear", model="Logistic (4 parameters)")
        pd.testing.assert_frame_equal(result.tables["Interpolated values"], estimates)
        pd.testing.assert_frame_equal(result.tables["Linear calibration"], _report(fit))
        pd.testing.assert_frame_equal(explicit.tables["Interpolated values"], estimates)
        self.assertEqual(list(result.tables), ["Interpolated values", "Linear calibration"])
        self.assertNotIn("Status", estimates.columns)
        self.assertNotIn("Domain low", estimates.columns)
        self.assertIsNone(result.curve)
        self.assertIsNone(result.model)
        self.assertEqual(estimates["Outside calibration"].tolist(), [False, True])
        self.assertAlmostEqual(fit["Slope"], 2.0)

    def test_default_nonlinear_model_is_one_phase_decay(self):
        unknowns = [decay_response(1.25), *([np.nan] * (len(X) - 1))]
        frame = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": unknowns})
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", curve="Nonlinear")
        self.assertEqual(result.model, "One-phase decay")
        np.testing.assert_allclose(result.tables["Interpolated values"]["Interpolated X"], [1.25], atol=1e-6, rtol=0)

    def test_no_unknowns_is_an_explicit_failure(self):
        frame = pd.DataFrame({"X": X, "Y": decay_response(X), "Unknown": np.nan})
        with self.assertRaisesRegex(ValueError, "unknown response"):
            interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")

    def test_dispatch_draws_linear_unknowns_and_nonlinear_estimates(self):
        from analisi.additional import EXTRA_METHODS
        from analisi.workbench import analyse

        spec = EXTRA_METHODS["Interpolate a standard curve"]
        self.assertEqual(spec["Curve"][0], "Linear")
        self.assertEqual(spec["Model"], INVERSE_MODELS)
        linear = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [3.0, 5.0, 7.0, 9.0],
                               "u": [4.0, np.nan, 11.0, np.nan]})
        old = {"X": "x", "Y": "y", "Unknown responses": "u"}
        direct_fit, direct_estimates = interpolate_linear(linear, "x", "y", "u")
        dispatched = analyse("Interpolate a standard curve", linear, old)
        pd.testing.assert_frame_equal(dispatched.tables["Interpolated values"], direct_estimates)
        pd.testing.assert_frame_equal(dispatched.tables["Linear calibration"], _report(direct_fit))
        axis = dispatched.figure.axes[0]
        self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()], ["Standards", "Unknowns"])
        self.assertEqual(len(axis.lines[0].get_xdata()), 2)
        self.assertNotIn("Status", dispatched.tables["Interpolated values"].columns)

        responses = [decay_response(1.25), np.nan, decay_response(4.5), 11.0, np.nan, np.nan, np.nan, np.nan]
        curved = pd.DataFrame({"Row titles": list("ABCDEFGH"), "X": X, "Y": decay_response(X), "Unknown": responses})
        options = {"X": "X", "Y": "Y", "Unknown responses": "Unknown", "Curve": "Nonlinear",
                   "Model": "One-phase decay"}
        result = analyse("Interpolate a standard curve", curved, options)
        table = result.tables["Interpolated values"]
        self.assertEqual(list(result.tables), ["Interpolated values", "Calibration parameters", "Fit diagnostics"])
        self.assertEqual(table["Row title"].tolist(), ["A", "C", "D"])
        axis = result.figure.axes[0]
        self.assertEqual([text.get_text() for text in axis.get_legend().get_texts()],
                         ["Standards", "One-phase decay", "Estimates"])
        self.assertGreater(len(axis.lines[0].get_xdata()), len(X))
        self.assertEqual(len(axis.collections[0].get_offsets()), len(X))
        self.assertEqual(len(axis.collections[1].get_offsets()), 2)
        self.assertFalse(np.any(np.isclose(axis.collections[1].get_offsets()[:, 1], 11.0)))

        failed = analyse("Interpolate a standard curve", curved.assign(Unknown=30.0), options)
        failed_axis = failed.figure.axes[0]
        self.assertEqual([text.get_text() for text in failed_axis.get_legend().get_texts()],
                         ["Standards", "One-phase decay"])
        self.assertEqual(len(failed_axis.collections), 1)
        self.assertTrue(failed.tables["Interpolated values"]["Interpolated X"].isna().all())
        self.assertTrue((failed.tables["Interpolated values"]["Status"] == OUT_OF_RANGE).all())


if __name__ == "__main__":
    unittest.main()
