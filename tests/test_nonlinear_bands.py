import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import nonlinear_bands as nb
from analisi import stats as engine
from analisi.curve_models import MODELS
from analisi.fit_weights import INFERENCE_WEIGHTS
from analisi.presentation import apply_style
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse

X = np.array([-2., -1, 0, 1, 2, 3, 4, 5])
Y = np.array([1.2, 2.7, 4.4, 5.3, 6.6, 7.9, 10.3, 11.4])
BASE = {"X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line", "Weighting": "Unweighted"}
MEAN, PRED = nb.BAND_MEAN, nb.BAND_PREDICTION
DECAY_X = np.arange(0, 6.5, .5)
DECAY_Y = 2 + 8 * np.exp(-.7 * DECAY_X) + np.array([.05, -.04, .03, -.05, .02, .04, -.03, .02, -.01, .03, -.02, .01, -.03])


def frame(**columns):
    return pd.DataFrame({"X": X, "Y": Y, **columns})


def run(data=None, **options):
    return analyse("Nonlinear regression", frame() if data is None else data, {**BASE, **options})


def decay(**options):
    return run(pd.DataFrame({"X": DECAY_X, "Y": DECAY_Y}), Model="One-phase decay", **options)


class GradientTests(unittest.TestCase):
    def check(self, model, theta, x, analytic, se=None, atol=1e-8):
        theta = np.asarray(theta, float)
        se = np.abs(theta) * .05 if se is None else np.asarray(se, float)
        numeric = nb.finite_difference_gradient(model, x, theta, se)
        np.testing.assert_allclose(numeric, analytic(x, *theta), rtol=1e-6, atol=atol)

    def test_line_and_decay_match_analytic_derivatives(self):
        x = np.linspace(0, 5, 11)
        self.check("Straight line", [1.5, -.4], x, nb._line)
        self.check("One-phase decay", [2., 8., .7], x, nb._decay)

    def test_four_parameter_logistic_with_very_different_scales(self):
        x = np.linspace(-5, 5, 21)
        low, high, mid, slope = 1e-3, 5e3, .5, 2.

        def analytic(x, low, high, mid, slope):
            s = 1 / (1 + np.exp(-(x - mid) * slope))
            ds = s * (1 - s)
            return np.column_stack([1 - s, s, -(high - low) * slope * ds, (high - low) * (x - mid) * ds])

        self.check("Logistic (4 parameters)", [low, high, mid, slope], x, analytic, se=[2., 80., .05, .1], atol=2e-6)

    def test_zero_coefficient_uses_its_standard_error_as_scale(self):
        x = np.linspace(0, 5, 11)
        numeric = nb.finite_difference_gradient("Straight line", x, [0., 2.], [.3, .1])
        np.testing.assert_allclose(numeric, nb._line(x, 0, 2), atol=1e-7)

    def test_one_sided_step_near_a_limit_stays_admissible(self):
        # Rate is bounded below by the smallest positive float; a value close to it forces the one-sided stencil.
        x = np.linspace(0, 5, 11)
        theta, se = np.array([2., 8., 1e-5]), np.array([.1, .1, 1e-5])
        spec = MODELS["One-phase decay"]
        seen = []
        original = spec.equation

        def guard(values, *params):
            seen.append(params[2])
            return original(values, *params)

        try:
            object.__setattr__(spec, "equation", guard)
            numeric = nb.finite_difference_gradient("One-phase decay", x, theta, se)
        finally:
            object.__setattr__(spec, "equation", original)
        self.assertTrue(all(value > 0 for value in seen))
        np.testing.assert_allclose(numeric, nb._decay(x, *theta), rtol=1e-5, atol=1e-8)

    def test_dispatcher_uses_analytic_where_known_and_finite_differences_elsewhere(self):
        x = np.linspace(0, 5, 7)
        np.testing.assert_array_equal(nb.gradient("Straight line", x, [1., 2.], [.1, .1]), nb._line(x, 1, 2))
        other = nb.gradient("Michaelis–Menten", x[1:], [10., 2.], [1., .2])
        self.assertTrue(np.isfinite(other).all())


class BandTests(unittest.TestCase):
    def test_prediction_is_wider_than_mean_at_equal_x_and_level(self):
        mean = run(Band=MEAN).tables["Band: All"]
        pred = run(Band=PRED).tables["Band: All"]
        np.testing.assert_array_equal(mean.X, pred.X)
        self.assertTrue((pred.Upper - pred.Lower > mean.Upper - mean.Lower).all())
        np.testing.assert_allclose(mean["SE mean"], pred["SE mean"])

    def test_level_changes_only_the_band_and_its_metadata(self):
        a, b = run(Band=MEAN, **{nb.LEVEL: 95}), run(Band=MEAN, **{nb.LEVEL: 80})
        for title in ("Parameters: All", "Fit: All", "Residuals: All"):
            pd.testing.assert_frame_equal(a.tables[title], b.tables[title])
        np.testing.assert_array_equal(a.figure.axes[0].lines[0].get_ydata(), b.figure.axes[0].lines[0].get_ydata())
        wide, narrow = a.tables["Band: All"], b.tables["Band: All"]
        self.assertTrue((wide.Upper - wide.Lower > narrow.Upper - narrow.Lower).all())
        self.assertEqual(a.tables["Band status"].iloc[0][nb.LEVEL], 95)
        self.assertEqual(b.tables["Band status"].iloc[0][nb.LEVEL], 80)

    def test_positive_model_keeps_the_geometric_grid_including_zero(self):
        data = pd.DataFrame({"X": [0, .1, .3, 1, 3, 10, 30, 100], "Y": [.1, .5, 2.1, 5.2, 9.4, 12.1, 12.9, 13.2]})
        result = run(data, Model="Stimulation (standard slope)", Band=MEAN)
        fit = engine.nonlinear(data, "X", "Y", "Stimulation (standard slope)")["All"]
        table = result.tables["Band: All"]
        np.testing.assert_array_equal(table.X, fit.curve[:, 0])
        self.assertEqual(table.X.iloc[0], 0)
        self.assertEqual(result.tables["Band status"].iloc[0]["Status"], "OK")

    def test_mean_band_matches_the_covariance_of_the_fit_without_a_second_scaling(self):
        data = frame()
        fit = engine.nonlinear(data, "X", "Y", "Straight line")["All"]
        table = run(Band=MEAN).tables["Band: All"]
        g = nb._line(table.X.to_numpy(), 0, 0)
        np.testing.assert_allclose(table["SE mean"], np.sqrt(np.einsum("ij,jk,ik->i", g, fit.covariance, g)))

    def test_group_with_unavailable_band_keeps_both_fits_and_separate_reasons(self):
        good = frame().assign(Group="A")
        perfect = pd.DataFrame({"X": X, "Y": 1 + 2 * X, "Group": "B"})
        result = run(pd.concat([good, perfect], ignore_index=True), Band=MEAN, **{"Grouping variables": ["Group"]})
        status = result.tables["Band status"]
        self.assertEqual(status.Status.to_dict(), {"A": "OK", "B": "Not available"})
        self.assertEqual(status.loc["A", "Reason"], "")
        self.assertIn("perfect", status.loc["B", "Reason"])
        self.assertEqual(len(result.tables["Parameters: A"]) + len(result.tables["Parameters: B"]), 4)
        self.assertEqual(len(result.tables["Band: A"]), 300)
        self.assertEqual(len(result.tables["Band: B"]), 0)

    def test_unavailable_band_keeps_its_schema(self):
        result = run(frame().assign(Y=lambda d: 1 + 2 * d.X), Band=MEAN)
        sheet = result.tables["Band: All"]
        self.assertEqual(list(sheet.columns), nb.COLUMNS)
        self.assertEqual(len(sheet), 0)

    def test_degrees_of_freedom_zero_is_unavailable_not_an_error(self):
        data = pd.DataFrame({"X": [0., 1, 2], "Y": [1., 3.1, 4.9]})
        result = run(data, Model="Straight line", Band=MEAN)
        self.assertEqual(result.tables["Band status"].iloc[0]["Status"], "OK")
        fit = engine.nonlinear(data, "X", "Y", "Straight line")["All"]
        fit.diagnostics["df"] = 0
        self.assertFalse(nb.fit_band(fit, "Straight line", "Y", MEAN, 95).ok)

    def test_parameter_on_a_bound_makes_the_band_unavailable(self):
        fit = engine.nonlinear(pd.DataFrame({"X": DECAY_X, "Y": DECAY_Y}), "X", "Y", "One-phase decay")["All"]
        fit.parameters.loc["Rate", "Estimate"] = float(MODELS["One-phase decay"].bounds[0][2])
        band = nb.fit_band(fit, "One-phase decay", "Y", MEAN, 95)
        self.assertFalse(band.ok)
        self.assertIn("Rate", band.reason)

    def test_substantially_negative_variance_is_not_hidden(self):
        fit = engine.nonlinear(frame(), "X", "Y", "Straight line")["All"]
        fit.covariance = np.array([[1., 0.], [0., -1.]])
        self.assertIn("negative", nb.fit_band(fit, "Straight line", "Y", MEAN, 95).reason)

    def test_weighted_mean_uses_the_confirmed_covariance_and_names_the_frozen_weights(self):
        for weighting in ("1/abs(Y)", "1/Y²", "1/abs(Yfit)", "1/Yfit²"):
            with self.subTest(weighting):
                result = run(Band=MEAN, Weighting=weighting)
                fit = engine.nonlinear(frame(), "X", "Y", "Straight line", weighting=weighting)["All"]
                table = result.tables["Band: All"]
                g = nb._line(table.X.to_numpy(), 0, 0)
                np.testing.assert_allclose(table["SE mean"], np.sqrt(np.einsum("ij,jk,ik->i", g, fit.covariance, g)),
                                           rtol=1e-6)
                inference = result.tables["Band status"].iloc[0]["Inference"]
                self.assertIn("mean", inference)
                if "Yfit" in weighting:
                    self.assertIn(INFERENCE_WEIGHTS.lower(), inference)

    def test_incomplete_excluded_duplicate_and_unordered_rows_follow_the_fit_not_the_polyline(self):
        data = pd.DataFrame({"X": [5., 1, np.nan, 3, 3, 0, 2, 4, -1], "Y": [11., 5.2, 3., 7.4, 7.9, 4.1, 6.3, np.nan, 2.6]})
        result = run(data, Band=MEAN)
        table = result.tables["Band: All"]
        used = data.dropna()
        self.assertEqual(len(table), 300)
        self.assertEqual((table.X.iloc[0], table.X.iloc[-1]), (used.X.min(), used.X.max()))
        self.assertTrue((np.diff(table.X) > 0).all())
        fit = engine.nonlinear(data, "X", "Y", "Straight line")["All"]
        np.testing.assert_allclose(table.Predicted, fit.curve[:, 1])

    def test_two_responses_and_two_grouping_variables_keep_unambiguous_sheets(self):
        data = pd.concat([frame().assign(Z=lambda d: d.Y * 2 + 1, A=a, B=b) for a in "pq" for b in "xy"],
                         ignore_index=True)
        result = run(data, Band=MEAN, **{"Y columns": ["Y", "Z"], "Grouping variables": ["A", "B"]})
        band, status = result.tables["Band"], result.tables["Band status"]
        self.assertIn("Response variable", band.columns)
        self.assertEqual(set(band["Response variable"]), {"Y", "Z"})
        self.assertEqual(len(status), 8)
        self.assertEqual(status["Response variable"].value_counts().to_dict(), {"Y": 4, "Z": 4})
        self.assertEqual(len(result.figure.axes), 2)


class OptionTests(unittest.TestCase):
    def test_none_ignores_a_stale_level_and_drawing(self):
        plain = run()
        stale = run(Band="None", **{nb.LEVEL: "bad", nb.DRAWING: "bogus"})
        self.assertEqual(list(plain.tables), list(stale.tables))
        for title in plain.tables:
            pd.testing.assert_frame_equal(plain.tables[title], stale.tables[title])
        self.assertNotIn("Band status", plain.tables)
        self.assertEqual(len(plain.figure.axes[0].collections), len(stale.figure.axes[0].collections))

    def assertField(self, field, **options):
        with self.assertRaises(FieldError) as raised:
            run(**options)
        self.assertEqual(raised.exception.field, field)

    def test_active_band_validates_level_and_choices_on_their_field(self):
        for level in (0, 100, -5, float("nan"), float("inf"), "x", None):
            with self.subTest(level=level):
                self.assertField(nb.LEVEL, Band=MEAN, **{nb.LEVEL: level})
        self.assertField(nb.DRAWING, Band=MEAN, **{nb.DRAWING: "Dots"})
        self.assertField(nb.BAND, Band="Simultaneous")

    def test_weighting_limits_are_reported_on_the_band_field(self):
        with self.assertRaises(FieldError) as raised:
            run(frame(SD=1.), Band=MEAN, Weighting="Inverse variance (column)", **{"SD column": "SD"})
        self.assertEqual(raised.exception.field, nb.BAND)
        for weighting in ("1/abs(Y)", "1/Y²", "1/abs(Yfit)", "1/Yfit²"):
            self.assertField(nb.BAND, Band=PRED, Weighting=weighting)

    def test_new_options_are_listed_for_the_method(self):
        self.assertEqual(list(nb.OPTIONS), ["Band", "Confidence level (%)", "Band drawing"])
        self.assertTrue(set(nb.OPTIONS) <= set(METHODS["Nonlinear regression"]))

    def test_decay_matches_independent_analytic_reference(self):
        table = decay(Band=MEAN).tables["Band: All"]
        fit = engine.nonlinear(pd.DataFrame({"X": DECAY_X, "Y": DECAY_Y}), "X", "Y", "One-phase decay")["All"]
        plateau, span, rate = fit.parameters["Estimate"]
        z = np.exp(-rate * table.X.to_numpy())
        g = np.column_stack([np.ones_like(z), z, -span * table.X.to_numpy() * z])
        v = np.einsum("ij,jk,ik->i", g, fit.covariance, g)
        half = stats.t.ppf(.975, fit.diagnostics["df"]) * np.sqrt(v)
        np.testing.assert_allclose(table.Lower, table.Predicted - half, rtol=1e-9)


class DrawingTests(unittest.TestCase):
    def test_filled_band_is_one_collection_with_a_stable_gid_and_no_legend_entry(self):
        axes = decay(Band=MEAN, **{nb.DRAWING: nb.FILLED}).figure.axes[0]
        bands = [c for c in axes.collections if str(c.get_gid()).startswith(nb.GID)]
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0].get_label(), "_nolegend_")
        self.assertAlmostEqual(bands[0].get_alpha(), nb.FILL_ALPHA)

    def test_line_band_adds_two_limit_curves_and_keeps_the_center_curve(self):
        axes = decay(Band=MEAN, **{nb.DRAWING: nb.LINES}).figure.axes[0]
        edges = [line for line in axes.lines if str(line.get_gid()).startswith(nb.GID)]
        self.assertEqual(len(edges), 2)
        self.assertEqual(len(axes.lines), 3)
        self.assertEqual(len(axes.collections), 1)   # the observations only
        self.assertIsNone(axes.get_legend())

    def test_groups_use_the_color_of_their_own_curve(self):
        data = pd.concat([frame().assign(Group="A"), frame().assign(Y=lambda d: d.Y * 2 + 1, Group="B")])
        axes = run(data, Band=MEAN, **{"Grouping variables": ["Group"]}).figure.axes[0]
        bands = {c.get_gid(): c for c in axes.collections if str(c.get_gid()).startswith(nb.GID)}
        self.assertEqual(len(bands), 2)
        curves = [line for line in axes.lines if not str(line.get_gid()).startswith(nb.GID)]
        for curve, band in zip(curves, bands.values()):
            np.testing.assert_allclose(band.get_facecolor()[0][:3], matplotlib_rgb(curve.get_color()))
        self.assertEqual(len(axes.get_legend().get_texts()), 2)

    def test_formatting_twice_does_not_accumulate_artists(self):
        figure = decay(Band=MEAN).figure
        axes = figure.axes[0]
        style = {"title": "Decay", "grid": True}
        apply_style(figure, style)
        counts = len(axes.collections), len(axes.lines), len(axes.texts)
        gids = sorted(str(c.get_gid()) for c in axes.collections)
        apply_style(figure, style)
        self.assertEqual(counts, (len(axes.collections), len(axes.lines), len(axes.texts)))
        self.assertEqual(gids, sorted(str(c.get_gid()) for c in axes.collections))


def matplotlib_rgb(color):
    from matplotlib.colors import to_rgb
    return to_rgb(color)


if __name__ == "__main__":
    unittest.main()
