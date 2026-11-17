import unittest

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from scipy.stats import norm

from analisi import stats
from analisi.curve_models import MODELS
from analisi.global_fit import global_nonlinear


class EquationExtensionTests(unittest.TestCase):
    def test_beta_growth_recovers_peak_and_relative_inflection_time(self):
        t = np.linspace(0., 13.5, 101)
        peak, te, tm = 11., 9., 4.5
        y = peak * (13.5 - t) / 4.5 * (t / 9.)**2
        fit = stats.nonlinear(pd.DataFrame({"t": t, "y": y}), "t", "y", "Beta growth and decline")["All"]
        np.testing.assert_allclose(fit.parameters["Estimate"], [peak, te, tm / te], rtol=1e-7)
        model = MODELS["Beta growth and decline"]
        np.testing.assert_allclose(model.equation(np.array([0., te, 13.5]), *fit.parameters["Estimate"]),
                                   [0., peak, 0.], atol=1e-7)

    def test_absolute_ic50_uses_the_control_baseline_and_the_fitted_top(self):
        concentrations = np.geomspace(.001, 1e4, 99)
        baseline, top, bottom = 13., 100., 25.
        relative, steepness = 2.8, 1.3
        y = bottom + (top - bottom) / (1 + (concentrations / relative)**steepness)
        fifty = (top + baseline) / 2
        absolute = relative * ((top - fifty) / (fifty - bottom))**(1 / steepness)
        for suffix, x, ic50 in (("concentration X", concentrations, absolute),
                                ("log10 X", np.log10(concentrations), np.log10(absolute))):
            with self.subTest(x=suffix):
                name = f"Absolute IC50 ({suffix})"
                frame = pd.DataFrame({"x": x, "y": y, "series": "A"})
                result = global_nonlinear(frame, "x", "y", name, "series", fixed={"Baseline": baseline})
                estimates = result.groups["A"].parameters["Estimate"]
                np.testing.assert_allclose(estimates, [top - baseline, fifty - bottom, ic50, steepness, baseline],
                                           rtol=1e-7)
                np.testing.assert_allclose(MODELS[name].equation(np.array([ic50]), *estimates), [fifty])

    def test_ligand_depletion_recovers_competitive_affinity_from_mass_balance(self):
        hot, hot_kd, activity, volume = 2600., .8, 1.5, 1.
        bmax, log_ki, ns = 4800., -8., .1
        x = np.linspace(-11., -3., 81)

        def binding(dose):
            apparent = 1000 * hot_kd * activity * volume * (1 + 10**(dose - log_ki))

            def balance(bound):
                free = hot - bound
                return bmax * free / (free + apparent) + ns * free - bound

            return brentq(balance, 0., hot)

        frame = pd.DataFrame({"x": x, "y": [binding(dose) for dose in x], "series": "A"})
        fixed = {"Hot (cpm)": hot, "Hot Kd (nM)": hot_kd, "Specific activity": activity, "Volume": volume}
        fit = global_nonlinear(frame, "x", "y", "One-site competition with depletion", "series", fixed=fixed)
        np.testing.assert_allclose(fit.groups["A"].parameters["Estimate"],
                                   [bmax, log_ki, ns, hot, hot_kd, activity, volume], rtol=1e-7)
        predicted = MODELS["One-site competition with depletion"].equation(
            np.array([1000.]), bmax, log_ki, ns, hot, hot_kd, activity, volume)
        np.testing.assert_allclose(predicted, [hot * ns / (1 + ns)])

    def test_competitive_binding_kinetics_fits_a_shared_mass_action_model(self):
        t = np.r_[0., np.geomspace(.02, 80., 60)]
        bmax, k1, k2, k3, k4, hot = 140., 2.8e7, .11, 6.3e7, .054, 5.
        frames, constraints = [], {}
        for cold in (0., 3., 20.):
            association_hot, association_cold = k1 * hot / 1e9, k3 * cold / 1e9

            def law(_, occupancies):
                bound_hot, bound_cold = occupancies
                free = 1. - bound_hot - bound_cold
                return association_hot * free - k2 * bound_hot, association_cold * free - k4 * bound_cold

            occupancy = solve_ivp(law, (0., t[-1]), (0., 0.), t_eval=t, rtol=1e-11, atol=1e-13).y[0]
            frames.append(pd.DataFrame({"t": t, "y": bmax * occupancy, "series": cold}))
            constraints[cold] = {"Cold (nM)": {"fixed": cold}}
        name = "Kinetics of competitive binding"
        fit = global_nonlinear(
            pd.concat(frames, ignore_index=True), "t", "y", name, "series", shared=("Bmax", "K3", "K4"),
            fixed={"K1": k1, "K2": k2, "Hot (nM)": hot}, series_constraints=constraints)
        np.testing.assert_allclose(fit.parameters["Estimate"].iloc[:3], [bmax, k3, k4], rtol=1e-7)
        # The repeated-root case has a nonzero association curve with no competitor.
        expected = bmax * .14 / .25 * (1 - np.exp(-.25 * t))
        calculated = MODELS[name].equation(t, bmax, k3, .25, k1, k2, hot, 0.)
        np.testing.assert_allclose(calculated, expected, rtol=1e-12)

    def test_classic_equations_expose_spans_area_and_angular_frequency(self):
        t = np.linspace(0., 25., 151)
        x = np.linspace(-5., 8., 120)
        cases = (
            ("Classic two-phase decay", t, 2 + 7*np.exp(-1.1*t) + 4*np.exp(-.14*t), [2, 7, 4, 1.1, .14]),
            ("Classic one-phase association", t, 8 * (1 - np.exp(-.6*t)), [8, .6]),
            ("Classic two-phase association", t, 3 * (1 - np.exp(-1.1*t)) + 7 * (1 - np.exp(-.14*t)),
             [3, 7, 1.1, .14]),
            ("Classic sine wave (angular frequency)", t, 5 + 2 * np.sin(1.3 * t + .28), [5, 2, 1.3, .28]),
            ("Classic Gaussian (area)", x, 23 * norm.pdf(x, loc=1.5, scale=1.3), [23, 1.5, 1.3]),
        )
        for name, xx, yy, expected in cases:
            with self.subTest(model=name):
                fit = stats.nonlinear(pd.DataFrame({"x": xx, "y": yy}), "x", "y", name)["All"]
                np.testing.assert_allclose(fit.parameters["Estimate"], expected, rtol=1e-7)


if __name__ == "__main__":
    unittest.main()
