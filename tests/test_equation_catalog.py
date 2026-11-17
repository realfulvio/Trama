import unittest

import numpy as np
import pandas as pd
from scipy.stats import norm

from analisi import stats
from analisi.curve_models import MODELS, MODEL_GROUPS
from analisi.global_fit import global_nonlinear


class EquationCatalogTests(unittest.TestCase):
    def test_groups_cover_registry_and_every_model_has_a_finite_start(self):
        ids = [name for models in MODEL_GROUPS.values() for name in models]
        self.assertCountEqual(ids, MODELS)
        for name, model in MODELS.items():
            with self.subTest(model=name):
                x = np.linspace(-5., 4., 61)
                if model.domain in {"nonnegative", "positive"}:
                    x = np.geomspace(.05, 20., 61)
                    if model.domain == "nonnegative":
                        x[0] = 0.
                y = 2 + 3 / (1 + (x - 2)**2) + np.sin(x) / 10
                guess = np.asarray(model.initial(x, y))
                lower, upper = np.broadcast_arrays(*model.bounds, guess)[:2]
                self.assertEqual(guess.shape, (len(model.parameters),))
                self.assertTrue(set(model.required_fixed) <= set(model.parameters))
                self.assertTrue(np.all(lower < upper))
                self.assertTrue(np.isfinite(guess).all())
                self.assertTrue(np.all((lower <= guess) & (guess <= upper)), (guess, model.bounds))
                predicted = model.equation(x, *guess)
                self.assertEqual(predicted.shape, x.shape)
                self.assertTrue(np.isfinite(predicted).all())

    def test_new_models_recover_parameters_from_independent_equations(self):
        t = np.linspace(0., 20., 101)
        x = np.linspace(-5., 8., 121)
        log_dose = np.linspace(-11., -4., 90)
        dose = np.r_[0., np.geomspace(.01, 150., 80)]
        q = np.exp(-.42 * t)
        phase_decay = 2 + 11 * (.37 * np.exp(-1.3 * t) + .63 * np.exp(-.15 * t))
        cases = [
            ("Straight line", x, 2. + 1.7 * x, [2, 1.7]),
            ("Line through origin", x, 1.7 * x, [1.7]),
            ("Horizontal line", x, 1.7 + .02 * np.sin(x - x.mean()), [1.7]),
            ("Semilog line (log X)", t[1:], 2 + 1.8 * np.log10(t[1:]), [2, 1.8]),
            ("Semilog line (log Y)", x, 10**(1.2 + .16 * x), [1.2, .16]),
            ("Log-log line", t[1:], 10**.7 * t[1:]**.61, [.7, .61]),
            ("Segmental linear regression", x, np.where(x < .5, 1 + .2*x, 1.1 + 1.5*(x - .5)),
             [1, .2, 1.5, .5]),
            ("Two-phase decay", t, phase_decay, [13, 2, 37, 1.3, .15]),
            ("Three-phase decay", t, 2 + 12 * (.32*np.exp(-3*t) + .41*np.exp(-.57*t) + .27*np.exp(-.07*t)),
             [14, 2, 32, 27 / .68, 3, .57, .07]),
            ("Two-phase association", t, 1 + 3 * (1 - np.exp(-1.3 * t)) + 6 * (1 - np.exp(-.15 * t)),
             [1, 3, 6, 1.3, .15]),
            ("Gompertz growth", t, 19 * (1.7 / 19)**q, [1.7, 19, .42]),
            ("Logistic growth", t, 19 * 1.7 / ((19 - 1.7) * q + 1.7), [1.7, 19, .42]),
            ("Lorentzian", x, 8 / (1 + ((x - 2.1) / 1.2)**2), [8, 2.1, 1.2]),
            ("Cumulative Gaussian (fraction)", x, norm.cdf(x, loc=1.3, scale=1.5), [1.3, 1.5]),
            ("Cumulative Gaussian (percent)", x, 100 * norm.cdf(x, loc=1.3, scale=1.5), [1.3, 1.5]),
            ("Standard sine wave", t, 3 * np.sin(2 * np.pi * t / 4.7 + .4), [3, 4.7, .4]),
            ("Damped sine wave", t, 3 * np.sin(2 * np.pi * t / 4.7 + .4) * np.exp(-.16 * t),
             [3, 4.7, .4, .16]),
            ("Sine wave with baseline", t, 7 + 3 * np.sin(2 * np.pi * t / 4.7 + .4), [3, 4.7, .4, 7]),
            ("Linear-quadratic cell survival (percent)", t, 100 * np.exp(-.3 * t - .09 * t*t), [.3, .09]),
            ("Stimulation (standard slope, log10 X)", log_dose,
             4 + 90 / (1 + 10**(-7.8 - log_dose)), [4, 94, -7.8]),
            ("Inhibition (variable slope, log10 X)", log_dose,
             4 + 90 / (1 + 10**(1.4*(log_dose + 7.8))), [4, 94, -7.8, -1.4]),
            ("Normalized stimulation (standard slope)", dose, 100 * dose / (dose + 4), [4]),
            ("Normalized inhibition (variable slope)", dose, 100 / (1 + (dose / 5)**1.5), [5, -1.5]),
            ("Normalized inhibition (standard slope, log10 X)", log_dose, 100 / (1 + 10**(log_dose + 8)), [-8]),
            ("Asymmetric dose-response (log10 X)", log_dose,
             4 + 90 / (1 + (2**(1/1.5) - 1) * 10**((-7.8-log_dose)*1.3))**1.5, [4, 94, -7.8, 1.3, 1.5]),
            ("Asymmetric dose-response (concentration X)", dose,
             4 + 90 / (1 + (2**(1/1.5) - 1) * (dose / 3)**1.3)**1.5, [4, 94, 3, -1.3, 1.5]),
            ("Allosteric sigmoidal enzyme kinetics", dose,
             19 * dose**1.7 / (3**1.7 + dose**1.7), [19, 3, 1.7]),
            ("Substrate inhibition", dose, 17 * dose / (3 + dose + dose**2 / 29), [17, 3, 29]),
            ("Specific binding with Hill slope", dose,
             19 * dose**1.7 / (3**1.7 + dose**1.7), [19, 3, 1.7]),
            ("Two-site specific binding", dose, 7*dose/(.4+dose) + 11*dose/(21+dose), [7, .4, 11, 21]),
        ]
        for order in range(1, 7):
            xx = x / 10
            coeff = np.linspace(.6, 2., order + 1)
            yy = sum(a * xx**i for i, a in enumerate(coeff))
            cases.append((f"Polynomial (order {order})", xx, yy, coeff))
        for name, xx, yy, expected in cases:
            with self.subTest(model=name):
                result = stats.nonlinear(pd.DataFrame({"x": xx, "y": yy}), "x", "y", name)["All"]
                np.testing.assert_allclose(result.parameters["Estimate"], expected, atol=3e-5, rtol=3e-5)

    def test_joint_competitive_enzyme_fit_recovers_ki_from_fixed_series_concentrations(self):
        x = np.r_[0., np.geomspace(.04, 60., 35)]
        inhibitor = {"control": 0., "dose 1": 2., "dose 2": 9.}
        frame = pd.concat([
            pd.DataFrame({"x": x, "y": 17 * x / (3 * (1 + i / 4.5) + x), "group": label})
            for label, i in inhibitor.items()
        ])
        options = {label: {"Inhibitor": {"fixed": i}} for label, i in inhibitor.items()}
        result = global_nonlinear(frame, "x", "y", "Competitive enzyme inhibition", "group",
                                  shared=("Vmax", "Km", "Ki"), series_constraints=options)
        np.testing.assert_allclose(result.parameters["Estimate"].to_numpy(), [17., 3., 4.5, 0., 2., 9.], atol=1e-7)

    def test_single_curve_with_required_constants_fits_through_global_api(self):
        x = np.linspace(0., 40., 70)
        bmax, kon, koff, hot = 60., 4e7, .04, 7.
        kd = koff / kon
        occupancy = (hot * 1e-9) / (hot * 1e-9 + kd)
        y = bmax * occupancy * (1 - np.exp(-(kon * hot * 1e-9 + koff) * x))
        frame = pd.DataFrame({"x": x, "y": y, "group": "A"})
        name = "Association kinetics (one ligand concentration)"
        with self.assertRaisesRegex(ValueError, "fixed Koff"):
            global_nonlinear(frame, "x", "y", name, "group", fixed={"Hot (nM)": hot})
        fitted = global_nonlinear(frame, "x", "y", name, "group", fixed={"Koff": koff, "Hot (nM)": hot})
        np.testing.assert_allclose(fitted.groups["A"].parameters["Estimate"], [bmax, kon, koff, hot], rtol=1e-7)

    def test_crossing_coordinates_are_identified_by_joint_lines(self):
        x = np.linspace(-5., 8., 51)
        data = pd.DataFrame({"x": np.tile(x, 2),
                             "y": np.r_[4. + 1.2 * (x - 2.4), 4. - .7 * (x - 2.4)],
                             "group": np.repeat(["A", "B"], len(x))})
        name = "Two intersecting lines"
        with self.assertRaisesRegex(ValueError, "joint estimation"):
            stats.nonlinear(data, "x", "y", name)
        with self.assertRaisesRegex(ValueError, "requires shared"):
            global_nonlinear(data, "x", "y", name, "group")
        fit = global_nonlinear(data, "x", "y", name, "group", shared=("Y cross", "X cross"), compare=True)
        np.testing.assert_allclose(fit.parameters["Estimate"], [4., 2.4, 1.2, -.7], rtol=1e-7)
        self.assertIn("requires shared", fit.comparison_note)

    def test_ecanything_interprets_f_as_percent_of_response_span(self):
        xx = np.linspace(-11., -4., 70)
        yy = 4 + 90 / (1 + 10**((-7.8-xx)*1.3))
        fit = global_nonlinear(
            pd.DataFrame({"x": np.tile(xx, 2), "y": np.tile(yy, 2), "group": np.repeat(["A", "B"], len(xx))}),
            "x", "y", "ECanything (log10 X)", "group", fixed={"F": 80.},
            shared=("Bottom", "Top", "Hill slope", "Log ECF"),
        )
        np.testing.assert_allclose(fit.parameters["Estimate"], [4., 94., -7.8 + np.log10(4)/1.3, 1.3, 80.],
                                   atol=1e-7)


if __name__ == "__main__":
    unittest.main()
