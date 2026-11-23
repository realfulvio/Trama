"""Unit, validation and regression tests for Padé (1,1) standard-curve calibration."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import nonlinear_calibration as cal
from analisi import pade_calibration as pade
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, active_language, placeholders, set_language, translate_message
from analisi.workbench import analyse

METHOD = "Interpolate a standard curve"
MODEL = pade.MODEL


def _pade_y(z, a0, a1, b1):
    z = np.asarray(z, dtype=float)
    return (a0 + a1 * z) / (1.0 + b1 * z)


def _frame(observations, query_col, queries, *, row_titles=None, index=None):
    rows = [{"X": x, "Y": y} for x, y in observations]
    rows.extend({query_col: value} for value in queries)
    frame = pd.DataFrame(rows)
    if row_titles is not None:
        frame.insert(0, "Row titles", row_titles)
    if index is not None:
        frame.index = index
    return frame


def _run(frame, direction, query_col, **overrides):
    options = {
        "X": "X",
        "Y": "Y",
        "Curve": "Nonlinear",
        "Model": MODEL,
        "Direction": direction,
        "Uncertainty": "None",
        ("Unknown X" if direction == "Y from X" else "Unknown responses"): query_col,
        **overrides,
    }
    return analyse(METHOD, frame, options)


class PadeCalibrationEngineTests(unittest.TestCase):
    def test_increasing_exact_forward_and_inverse_with_endpoints_and_row_titles(self):
        # True model: A0 = 2, A1 = 12, B1 = 2 on [10, 30]
        xs = np.linspace(10.0, 30.0, 9)
        zs = (xs - 10.0) / 20.0
        ys = _pade_y(zs, 2.0, 12.0, 2.0)
        obs = list(zip(xs.tolist(), ys.tolist()))

        # Forward: endpoints, interior, outside low and outside high
        q_z = [0.0, 0.375, 1.0, -0.25, 1.25]
        q_x = [10.0 + 20.0 * v for v in q_z]
        titles = [f"Std {i}" for i in range(len(obs))] + [f"Sample {i}" for i in range(len(q_x))]
        idx = list(range(100, 100 + len(titles)))
        frame_fwd = _frame(obs, "Query X", q_x, row_titles=titles, index=idx)
        res_fwd = _run(frame_fwd, "Y from X", "Query X")

        pred = res_fwd.tables[cal.PREDICTIONS]
        self.assertEqual(list(pred.columns),
                         ["Source row", "Row title", "X", "Predicted Y", "Status", "Y lower", "Y upper"])
        self.assertEqual(pred["Source row"].tolist(), idx[len(obs):])
        self.assertEqual(pred["Row title"].tolist(), [f"Sample {i}" for i in range(len(q_x))])
        self.assertEqual(pred["Status"].tolist(), [cal.IN_RANGE] * 3 + [cal.OUTSIDE_CALIBRATION] * 2)
        np.testing.assert_allclose(pred["Predicted Y"].iloc[:3], _pade_y(q_z[:3], 2.0, 12.0, 2.0),
                                   rtol=1e-10, atol=1e-10)
        self.assertTrue(pred["Predicted Y"].iloc[3:].isna().all())
        self.assertTrue(pred[["Y lower", "Y upper"]].isna().all().all())
        self.assertNotIn(cal.BANDS, res_fwd.tables)

        params = res_fwd.tables["Calibration parameters"]
        self.assertEqual(list(params.index), ["A0", "A1", "B1"])
        np.testing.assert_allclose(params["Estimate"].to_numpy(dtype=float), [2.0, 12.0, 2.0],
                                   rtol=1e-9, atol=1e-9)

        diag = res_fwd.tables["Fit diagnostics"]["Value"]
        self.assertEqual(diag["N"], 9)
        self.assertEqual(diag["df"], 6)
        self.assertLess(float(diag["Residual SS (Y)"]), 1e-20)
        self.assertEqual(float(diag["X origin (X min)"]), 10.0)
        self.assertEqual(float(diag["X scale (X max - X min)"]), 20.0)
        self.assertEqual(float(diag["Minimum denominator"]), 1.0)

        # Inverse: exact endpoints, tiny rounding outside endpoints, interior, clearly outside
        q_y = [float(ys[0]), float(ys[0] - 1e-12), float(_pade_y(0.375, 2.0, 12.0, 2.0)),
               float(ys[-1]), float(ys[-1] + 1e-12), float(ys[0] - 0.5), float(ys[-1] + 0.5)]
        frame_inv = _frame(obs, "Query Y", q_y)
        res_inv = _run(frame_inv, "X from Y", "Query Y")
        inv = res_inv.tables[cal.INTERPOLATED]
        self.assertEqual(inv["Status"].tolist(),
                         [cal.IN_RANGE] * 5 + [cal.OUT_OF_RANGE, cal.OUT_OF_RANGE])
        np.testing.assert_allclose(inv["Interpolated X"].iloc[:5], [10.0, 10.0, 17.5, 30.0, 30.0],
                                   rtol=1e-9, atol=1e-9)
        self.assertTrue(inv["Interpolated X"].iloc[5:].isna().all())
        self.assertTrue((inv["Domain low"] == 10.0).all())
        self.assertTrue((inv["Domain high"] == 30.0).all())

    def test_decreasing_curve_and_negative_b1(self):
        # True model: A0 = 8, A1 = -7, B1 = -0.65 on [-5, 5]
        xs = np.linspace(-5.0, 5.0, 9)
        zs = (xs + 5.0) / 10.0
        ys = _pade_y(zs, 8.0, -7.0, -0.65)
        obs = list(zip(xs.tolist(), ys.tolist()))

        # Inverse checks decreasing endpoints (ys[0]=8 is max, ys[-1]=2.857... is min)
        q_y = [float(ys[0]), float(ys[0] + 1e-12), float(_pade_y(0.5, 8.0, -7.0, -0.65)),
               float(ys[-1]), float(ys[-1] - 1e-12), float(ys[-1] - 0.3), float(ys[0] + 0.3)]
        frame = _frame(obs, "Query Y", q_y)
        res = _run(frame, "X from Y", "Query Y")
        inv = res.tables[cal.INTERPOLATED]
        self.assertEqual(inv["Status"].tolist(), [cal.IN_RANGE] * 5 + [cal.OUT_OF_RANGE] * 2)
        np.testing.assert_allclose(inv["Interpolated X"].iloc[:5], [-5.0, -5.0, 0.0, 5.0, 5.0],
                                   rtol=1e-9, atol=1e-9)
        self.assertTrue(inv["Interpolated X"].iloc[5:].isna().all())
        diag = res.tables["Fit diagnostics"]["Value"]
        np.testing.assert_allclose(float(diag["Minimum denominator"]), 0.35, rtol=1e-9, atol=1e-9)

    def test_shifted_by_one_billion_preserves_coefficients_and_predictions(self):
        xs_base = np.linspace(10.0, 30.0, 9)
        zs = (xs_base - 10.0) / 20.0
        ys = _pade_y(zs, 2.0, 12.0, 2.0)
        shift = 1_000_000_000.0
        xs_shifted = xs_base + shift

        res_base = _run(_frame(list(zip(xs_base, ys)), "Q", [10.0, 17.5, 30.0]), "Y from X", "Q")
        res_shifted = _run(_frame(list(zip(xs_shifted, ys)), "Q", [10.0 + shift, 17.5 + shift, 30.0 + shift]),
                           "Y from X", "Q")

        np.testing.assert_allclose(
            res_shifted.tables["Calibration parameters"]["Estimate"],
            res_base.tables["Calibration parameters"]["Estimate"],
            rtol=1e-9, atol=1e-9,
        )
        np.testing.assert_allclose(
            res_shifted.tables[cal.PREDICTIONS]["Predicted Y"],
            res_base.tables[cal.PREDICTIONS]["Predicted Y"],
            rtol=1e-9, atol=1e-9,
        )
        diag = res_shifted.tables["Fit diagnostics"]["Value"]
        self.assertEqual(float(diag["X origin (X min)"]), shift + 10.0)
        self.assertEqual(float(diag["X scale (X max - X min)"]), 20.0)

        # Inverse on shifted X preserves X - xmin
        q_y = [float(ys[0]), float(_pade_y(0.375, 2.0, 12.0, 2.0)), float(ys[-1])]
        inv_shifted = _run(_frame(list(zip(xs_shifted, ys)), "QY", q_y), "X from Y", "QY").tables[cal.INTERPOLATED]
        np.testing.assert_allclose(inv_shifted["Interpolated X"] - (shift + 10.0), [0.0, 7.5, 20.0],
                                   rtol=1e-7, atol=1e-6)

    def test_noisy_replicates_and_incomplete_pairs_minimize_y_ss(self):
        # Dataset with replicates and incomplete rows; query column must not enter the fit.
        obs = [
            (10.0, 2.5), (12.5, 3.0042), (15.0, 3.3701), (17.5, 3.6204),
            (20.0, 3.8128), (22.5, 3.9806), (25.0, 4.0907), (27.5, 4.2030),
            (30.0, 4.2837), (15.0, 3.3671), (22.5, 3.9646),
            (12.5, None), (None, 99.0),
        ]
        res1 = _run(_frame(obs, "Q", [3.5, 1.0]), "X from Y", "Q")
        res2 = _run(_frame(obs, "Q", [3.9, 100.0, 3.2]), "X from Y", "Q")
        # Query column does not affect estimated parameters or diagnostics.
        np.testing.assert_allclose(
            res1.tables["Calibration parameters"]["Estimate"],
            res2.tables["Calibration parameters"]["Estimate"],
            rtol=0, atol=1e-15,
        )
        diag = res1.tables["Fit diagnostics"]["Value"]
        self.assertEqual(diag["N"], 11)
        self.assertEqual(diag["Distinct X"], 9)
        self.assertEqual(diag["df"], 8)
        # Replicates stay separate and Y-residual SS is strictly better than linear OLS (B1=0).
        coeffs = res1.tables["Calibration parameters"]["Estimate"].to_numpy(dtype=float)
        clean = [(x, y) for x, y in obs if x is not None and y is not None]
        z = np.array([(x - 10.0) / 20.0 for x, _ in clean])
        y = np.array([y for _, y in clean])
        ss_fit = float(np.sum((y - _pade_y(z, *coeffs)) ** 2))
        ss_ols = float(np.sum((y - np.polyval(np.polyfit(z, y, 1), z)) ** 2))
        np.testing.assert_allclose(float(diag["Residual SS (Y)"]), ss_fit, rtol=1e-12, atol=1e-15)
        self.assertLess(ss_fit, ss_ols)

    def test_denominator_bound_prevents_pole_inside_domain(self):
        # Steep blow-up toward z = 1 that pushes B1 directly against the -1 + 1e-6 boundary.
        z = np.array([0.0, 0.25, 0.5, 0.75, 0.9, 0.98, 1.0])
        y = np.array([1.0, 1.4, 2.2, 4.5, 12.0, 80.0, 5000.0])
        frame = _frame(list(zip(z, y)), "Q", [0.0, 0.5, 1.0])
        res = _run(frame, "Y from X", "Q")
        b1 = float(res.tables["Calibration parameters"].at["B1", "Estimate"])
        self.assertGreaterEqual(1.0 + b1, pade.DENOMINATOR_MIN)
        self.assertGreaterEqual(float(res.tables["Fit diagnostics"].at["Minimum denominator", "Value"]),
                                pade.DENOMINATOR_MIN)
        # Sampled curve on the figure is finite everywhere in [0, 1].
        line = res.figure.axes[0].lines[0]
        self.assertGreaterEqual(len(line.get_xdata()), 100)
        self.assertTrue(np.isfinite(line.get_xdata()).all())
        self.assertTrue(np.isfinite(line.get_ydata()).all())
        self.assertTrue(np.isfinite(res.tables[cal.PREDICTIONS]["Predicted Y"]).all())

    def test_minimal_valid_dataset_four_observations_three_distinct_x(self):
        obs = [(0.0, 1.0), (0.0, 1.05), (5.0, 3.0), (10.0, 4.0)]
        res = _run(_frame(obs, "Q", [0.0, 5.0, 10.0]), "Y from X", "Q")
        diag = res.tables["Fit diagnostics"]["Value"]
        self.assertEqual(diag["N"], 4)
        self.assertEqual(diag["Distinct X"], 3)
        self.assertEqual(diag["df"], 1)
        self.assertTrue(np.isfinite(res.tables[cal.PREDICTIONS]["Predicted Y"]).all())

    def test_flat_fit_marks_not_identifiable_with_empty_x(self):
        # Construct a finite fitted PadeFit whose curve is numerically flat, verifying Not identifiable.
        obs = [(0.0, 2.0), (1.0, 2.5), (2.0, 3.0), (3.0, 3.5)]
        frame = _frame(obs, "Q", [2.0, 2.5, 3.0])
        real_fit = pade.fit_pade(frame, "X", "Y")
        flat_coeffs = (5.0, 5.0 * 0.5, 0.5)  # A1 - A0*B1 = 0 -> identically constant 5.0
        flat_curve = np.column_stack((real_fit.curve[:, 0], np.full(len(real_fit.curve), 5.0)))
        flat_fit = pade.PadeFit(
            a0=flat_coeffs[0], a1=flat_coeffs[1], b1=flat_coeffs[2],
            x_min=real_fit.x_min, x_max=real_fit.x_max, x_scale=real_fit.x_scale,
            n=real_fit.n, distinct_x=real_fit.distinct_x, df=real_fit.df,
            residual_ss=real_fit.residual_ss, residual_sd=real_fit.residual_sd, r_squared=0.0,
            min_denominator=1.0, y_at_min=5.0, y_at_max=5.0,
            identifiable=pade.is_identifiable(flat_coeffs, np.array([2.0, 2.5, 3.0, 3.5])),
            parameters=pd.DataFrame({"Estimate": list(flat_coeffs)}, index=list(pade.PARAMETERS)),
            diagnostics=dict(real_fit.diagnostics),
            curve=flat_curve,
        )
        self.assertFalse(flat_fit.identifiable)
        with patch.object(pade, "fit_pade", return_value=flat_fit):
            res = _run(frame, "X from Y", "Q")
        inv = res.tables[cal.INTERPOLATED]
        self.assertEqual(inv["Status"].tolist(), [cal.NOT_IDENTIFIABLE] * 3)
        self.assertTrue(inv["Interpolated X"].isna().all())

        # Also test a nearly flat curve (variation below tolerance relative to response scale).
        near_flat = (100.0, 100.0 * 0.2 + 1e-9, 0.2)
        self.assertFalse(pade.is_identifiable(near_flat, np.array([100.0, 100.0, 100.0, 100.0])))

    def test_validation_errors_assign_expected_fields(self):
        # Fewer than 4 observations
        with self.assertRaises(FieldError) as raised:
            _run(_frame([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)], "Q", [2.0]), "X from Y", "Q")
        self.assertEqual(raised.exception.field, "X")

        # Fewer than 3 distinct X values (4 observations, only 2 X)
        with self.assertRaises(FieldError) as raised:
            _run(_frame([(1.0, 2.0), (1.0, 3.0), (2.0, 4.0), (2.0, 5.0)], "Q", [3.0]), "X from Y", "Q")
        self.assertEqual(raised.exception.field, "X")

        # Degenerate X interval (all X identical)
        with self.assertRaises(FieldError) as raised:
            _run(_frame([(5.0, 1.0), (5.0, 2.0), (5.0, 3.0), (5.0, 4.0)], "Q", [5.0]), "Y from X", "Q")
        self.assertEqual(raised.exception.field, "X")

        # Constant Y
        with self.assertRaises(FieldError) as raised:
            _run(_frame([(0.0, 7.0), (1.0, 7.0), (2.0, 7.0), (3.0, 7.0)], "Q", [7.0]), "X from Y", "Q")
        self.assertEqual(raised.exception.field, "Y")

        # Same column for X and Y
        frame = _frame([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)], "Q", [2.0])
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"X": "X", "Y": "X", "Curve": "Nonlinear", "Model": MODEL,
                                    "Direction": "Y from X", "Unknown X": "Q", "Uncertainty": "None"})
        self.assertEqual(raised.exception.field, "Y")

    def test_uncertainty_rejected_and_inactive_level_and_replicates_ignored(self):
        obs = [(0.0, 2.0), (2.0, 3.2), (5.0, 4.0), (10.0, 4.5)]
        frame_inv = _frame(obs, "QY", [3.0]).assign(K="not-an-int")
        frame_fwd = _frame(obs, "QX", [3.0]).assign(K="not-an-int")

        for direction, frame, qcol in (("X from Y", frame_inv, "QY"), ("Y from X", frame_fwd, "QX")):
            for kind in ("Mean response", "Prediction"):
                with self.subTest(direction=direction, kind=kind):
                    with self.assertRaises(FieldError) as raised:
                        _run(frame, direction, qcol, Uncertainty=kind, **{
                            cal.LEVEL: 500, cal.COUNT: "K",
                        })
                    self.assertEqual(raised.exception.field, cal.UNCERTAINTY)

            # With Uncertainty=None, stale/invalid level and replicate column are ignored.
            res = _run(frame, direction, qcol, Uncertainty="None", **{
                cal.LEVEL: 500, cal.COUNT: "K",
            })
            self.assertIn("Calibration parameters", res.tables)

    def test_visibility_hides_intervals_for_pade_and_keeps_legacy_calls(self):
        for direction in cal.DIRECTIONS:
            vis = cal.calibration_visibility(direction, "Nonlinear", "Prediction", MODEL)
            self.assertFalse(vis[cal.UNCERTAINTY], direction)
            self.assertFalse(vis[cal.LEVEL], direction)
            self.assertFalse(vis[cal.COUNT], direction)
            self.assertTrue(vis["Model"], direction)
        # Historical calls without model stay unchanged.
        self.assertTrue(cal.calibration_visibility("Y from X", "Nonlinear", "Mean response")[cal.UNCERTAINTY])
        self.assertFalse(cal.calibration_visibility("X from Y", "Nonlinear", "Prediction")[cal.UNCERTAINTY])

    def test_existing_calibration_models_regression(self):
        # Legacy linear recipe (no Direction, no Curve, no Uncertainty)
        lin = pd.DataFrame({"X": [0., 1., 2., 3., np.nan], "Y": [1., 3., 5., 7., np.nan],
                            "Req": [np.nan, np.nan, np.nan, np.nan, 4.]})
        res_lin = analyse(METHOD, lin, {"X": "X", "Y": "Y", "Unknown responses": "Req"})
        np.testing.assert_allclose(res_lin.tables[cal.INTERPOLATED]["Interpolated X"], [1.5], atol=1e-12)

        # One-phase decay forward with Mean response band and inverse
        x_d = np.array([0., 0.5, 1., 2., 3., 4., 5., 6.])
        y_d = 2.0 + 8.0 * np.exp(-0.7 * x_d) + np.array([0.05, -0.04, 0.03, -0.02, 0.04, -0.03, 0.02, -0.02])
        df_d = pd.DataFrame({"X": x_d, "Y": y_d, "QX": [1.5, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
                             "QY": [5.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]})
        res_d_fwd = analyse(METHOD, df_d, {"X": "X", "Y": "Y", "Direction": "Y from X", "Unknown X": "QX",
                                           "Curve": "Nonlinear", "Model": "One-phase decay",
                                           "Uncertainty": "Mean response", "Confidence level (%)": 95.0})
        self.assertIn(cal.BANDS, res_d_fwd.tables)
        self.assertEqual(res_d_fwd.tables[cal.PREDICTIONS].at[0, "Status"], cal.IN_RANGE)
        res_d_inv = analyse(METHOD, df_d, {"X": "X", "Y": "Y", "Direction": "X from Y", "Unknown responses": "QY",
                                           "Curve": "Nonlinear", "Model": "One-phase decay"})
        self.assertEqual(res_d_inv.tables[cal.INTERPOLATED].at[0, "Status"], cal.IN_RANGE)

        # 4PL (Stimulation, variable slope)
        x_4 = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y_4 = np.where(x_4 == 0.0, 2.0, 2.0 + 16.0 / (1.0 + (4.0 / np.where(x_4 == 0.0, 1.0, x_4)) ** 2.0))
        df_4 = pd.DataFrame({"X": x_4, "Y": y_4, "QY": [10.0] + [np.nan] * 7})
        res_4 = analyse(METHOD, df_4, {"X": "X", "Y": "Y", "Direction": "X from Y", "Unknown responses": "QY",
                                       "Curve": "Nonlinear", "Model": "Stimulation (variable slope)"})
        np.testing.assert_allclose(res_4.tables[cal.INTERPOLATED]["Interpolated X"], [4.0], atol=1e-4)

    def test_pade_i18n_catalog_parity_and_translation(self):
        en_keys = {key for key in CATALOGS["en"] if key.startswith("calib.pade.")}
        it_keys = {key for key in CATALOGS["it"] if key.startswith("calib.pade.")}
        self.assertEqual(en_keys, it_keys)
        self.assertTrue(en_keys)
        for key in en_keys:
            self.assertTrue(CATALOGS["en"][key], key)
            self.assertTrue(CATALOGS["it"][key], key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        previous = active_language()
        set_language("it")
        try:
            msg = translate_message(f"Intervals are not available for {MODEL}. Choose None.", "calib.pade.")
            self.assertIn(MODEL, msg)
            self.assertNotIn("Intervals are not available", msg)
            msg2 = translate_message("Response values have zero variation.", "calib.pade.")
            self.assertIn("variazione nulla", msg2)
        finally:
            set_language(previous)


if __name__ == "__main__":
    unittest.main()
