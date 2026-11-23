import unittest
from struct import pack

import numpy as np
import pandas as pd

from analisi import plot_function as plotting
from analisi.legacy_binary_simulation import _competition_drawing_grid, _simulation_options, _matches_drawing
from analisi.presentation import apply_style


def _function(equation, parameters):
    function = (71,)
    expression = (71, 72)
    return [
        (0x8047, (), pack("<3I", 1, 0, 1) + bytes(32)),
        (0x8048, function, b""),
        (0x49, expression, equation.encode("ascii") + b"\0"),
        (0x53, expression, "\0".join(parameters).encode("ascii") + b"\0"),
        (0x54, expression, pack(f"<{len(parameters)}d", *parameters.values())),
    ]


class LegacySimulationTests(unittest.TestCase):
    def test_fractional_death_keeps_zero_on_the_table_and_observations_on_the_plot(self):
        x = np.arange(4, dtype=float)
        values = -np.expm1(-x * (.08514 + .1029 * x))
        samples = pd.DataFrame({"X": x, "Simulated": values})
        records = _function("Y=1-exp(-1*(A*X + B*X^2))", {"A": .08514, "B": .1029})
        options = _simulation_options(records, samples)
        options.update({plotting.X_SOURCE: plotting.LINEAR, plotting.X_MIN: 0.,
                        plotting.X_MAX: 3., plotting.SEGMENTS: 3,
                        plotting.OBSERVATION_COLUMNS: ["Dose", "Observed"]})
        source = pd.DataFrame({"Dose": [0., 1., 2.], "Observed": [.004, np.nan, .47]})
        plot = plotting.plot_function(source, options)
        np.testing.assert_allclose(plot.tables[plotting.VALUES]["Simulated"], values)
        axes, = plot.figure.axes
        observations, curve = axes.lines
        np.testing.assert_array_equal(observations.get_ydata(), [.004, .47])
        self.assertEqual(observations.get_linestyle(), "None")
        np.testing.assert_array_equal(curve.get_xdata(), x)
        apply_style(plot.figure, {"yscale": "log", "axis": {"y": {"min": .001, "max": 1.}}})
        self.assertFalse(np.isfinite(axes.yaxis.get_transform().transform([0.]).item()))
        apply_style(plot.figure, {"yscale": "linear"})
        self.assertEqual(curve.get_ydata()[0], 0.)

    def test_inhibition_keeps_the_saved_grid_and_changes_when_a_coefficient_changes(self):
        x = np.array([0., .2, 2., 9.])
        values = 1500. - 1200. * x ** 2.5 / (x ** 2.5 + 2. ** 2.5)
        frame = pd.DataFrame({"X": x, "Signal": values})
        records = _function("Y=Bottom+(Top-Bottom)/(1+(IC50/X)^HillSlope)",
                            {"Bottom": 1500., "Top": 300., "IC50": 2., "HillSlope": 2.5})
        options = _simulation_options(records, frame)
        self.assertEqual(options[plotting.MODEL], "Inhibition (variable slope)")
        self.assertEqual(options[plotting.CURVES][0]["parameters"]["Hill slope"], -2.5)
        plot = plotting.plot_function(frame[["X"]], options)
        result = plot.tables[plotting.VALUES]
        np.testing.assert_array_equal(result["X"], x)
        np.testing.assert_allclose(result["Signal"], values)
        apply_style(plot.figure, {"xscale": "log"})
        axes = plot.figure.axes[0]
        self.assertEqual(axes.get_xscale(), "log")
        self.assertFalse(np.isfinite(axes.xaxis.get_transform().transform([0.])).any())
        apply_style(plot.figure, {"xscale": "linear"})
        np.testing.assert_array_equal(axes.lines[0].get_xdata(), x)
        options[plotting.CURVES][0]["parameters"]["IC50"] = 4.
        changed = plotting.plot_function(frame[["X"]], options).tables[plotting.VALUES]
        self.assertNotEqual(changed.at[2, "Signal"], result.at[2, "Signal"])
        frame.at[2, "Signal"] += 1.
        with self.assertRaises(ValueError):
            _simulation_options(records, frame)

    def test_five_parameter_simulation_preserves_the_midpoint_and_shape(self):
        x = np.array([25., 300., 2000.])
        response = 100. + 900. / (1. + (2. ** .8 - 1.) * (300. / x) ** 6.) ** 1.25
        frame = pd.DataFrame({"Dose": x, "Signal": response})
        records = _function(
            "Denominator = (1+(2^(1/S)-1)*((EC50/X)^HillSlope))^S\r\n"
            "Numerator = Top - Bottom\r\nY = Bottom + (Numerator/Denominator)",
            {"S": 1.25, "EC50": 300., "HillSlope": 6., "Top": 1000., "Bottom": 100.})
        options = _simulation_options(records, frame)
        self.assertEqual(options[plotting.MODEL], "Asymmetric dose-response (concentration X)")
        result = plotting.plot_function(frame[["Dose"]], options).tables[plotting.VALUES]
        self.assertAlmostEqual(result.at[1, "Signal"], 550.)
        records[2] = (0x49, (71, 72), b"Y=X\0")
        with self.assertRaises(ValueError):
            _simulation_options(records, frame)

    def test_competition_ki_requires_the_saved_parameter_table_to_match(self):
        x = np.array([-9., -7., -5., -3.])
        midpoint = -6. + np.log10(2.)
        values = 3000. - 2500. / (1. + 10. ** (x - midpoint))
        frame = pd.DataFrame({"Log concentration": x, "Binding": values.astype(np.float32)})
        records = _function(
            "logEC50=log(10^logKi*(1+HotNM/HotKdNM))\r\nY=(Top-Bottom)/(1+10^(X-LogEC50))+Bottom",
            {"logKi": -6., "HotNM": 1., "HotKdNM": 1., "Top": 500., "Bottom": 3000.},
        )
        options = _simulation_options(records, frame)
        self.assertEqual(options[plotting.MODEL], "One-site competition (log Ki)")
        self.assertEqual(options[plotting.CURVES][0]["parameters"]["Log Ki"], -6.)
        result = plotting.plot_function(frame[["Log concentration"]], options)
        np.testing.assert_allclose(result.tables[plotting.VALUES]["Binding"], values, rtol=1e-14)
        frame.at[1, "Binding"] += 1.
        with self.assertRaises(ValueError):
            _simulation_options(records, frame)

    def test_competition_ic50_reopens_only_a_matching_archived_drawing(self):
        x = np.linspace(-9., -3., 9)
        saved = pd.DataFrame({"X": x, "Binding": 3000. - 2600. / (1. + 10. ** (x + 6.))})
        records = _function("Y=(Top-Bottom)/(1+10^(X-LogIC50))+Bottom",
                            {"Top": 400., "Bottom": 3000., "LogIC50": -6.})
        options = _simulation_options(records, saved)
        self.assertEqual(options[plotting.MODEL], "One-site competition (log IC50)")
        axes = [{"bounds": [-9., -3.], "length": 1800, "unit": 6. / 1680, "scale": "linear"},
                {"bounds": [0., 4000.], "length": 1200, "unit": 4000. / 1080, "scale": "linear"}]
        draw_x = np.linspace(-9., -3., len(saved) - 1)
        draw_y = 400. + 2600. / (1. + 10. ** (draw_x + 6.))
        cache = np.rint(np.column_stack(((draw_x + 9.) / axes[0]["unit"] + 120,
                                        draw_y / axes[1]["unit"] + 120)))
        original = saved.copy()
        grid, recipe = _competition_drawing_grid(saved, cache, axes, options)
        pd.testing.assert_frame_equal(saved, original)
        np.testing.assert_array_equal(grid["X"], draw_x)
        np.testing.assert_allclose(plotting.plot_function(grid, recipe).tables[plotting.VALUES]["Binding"], draw_y)
        self.assertEqual(options[plotting.CURVES][0]["parameters"]["Bottom"], 3000.)
        cache[3, 1] += 20.
        with self.assertRaises(ValueError):
            _competition_drawing_grid(saved, cache, axes, options)

    def test_homologous_competition_retains_both_series_and_their_own_concentrations(self):
        x = np.array([-12., -10., -8., -6.])

        def binding(hot_nm):
            return 500. * hot_nm / (hot_nm + 10. ** (x + 9.) + 1.) + 50. * hot_nm

        frame = pd.DataFrame({"X": x, "1 nM": binding(1.).astype(np.float32),
                              "5 nM": binding(4.).astype(np.float32)})
        equation = ("ColdNM=10^(x+9) ;Cold concentration in nM\r\n"
                    "KdNM=10^(logKD+9) ;Kd  in nM\r\nBottom=NS*HotnM\r\n"
                    "Y=(Bmax*HotnM)/(HotnM + ColdNM + KdNM) + Bottom")
        records = []
        for position, (label, concentration) in enumerate((("1 nM", 1.), ("5 nM", 4.))):
            group = _function(equation, {"logKD": -9., "NS": 50., "HotnM": concentration, "Bmax": 500.})
            group[0] = (0x8047, (), pack("<3I", 1, position, 2) + bytes(32))
            group.extend(((0x8048, (71,), b""), (0x49, (71, 72), label.encode("ascii") + b"\0")))
            records.extend(group)
        options = _simulation_options(records, frame)
        self.assertEqual(options[plotting.MODEL], "Homologous one-site competition")
        self.assertEqual([curve["name"] for curve in options[plotting.CURVES]], ["1 nM", "5 nM"])
        self.assertEqual([curve["parameters"]["Hot (nM)"] for curve in options[plotting.CURVES]], [1., 4.])
        result = plotting.plot_function(frame[["X"]], options).tables[plotting.VALUES]
        np.testing.assert_allclose(result[["1 nM", "5 nM"]], np.column_stack((binding(1.), binding(4.))))
        with self.assertRaises(ValueError):
            _simulation_options(records, frame[["X", "5 nM", "1 nM"]])
        frame.at[0, "5 nM"] += 20.
        with self.assertRaises(ValueError):
            _simulation_options(records, frame)

    def test_two_site_ki_preserves_the_fraction_of_the_high_affinity_site(self):
        x = np.array([-9., -7., -5., -3.])
        high = .3 / (1. + 10. ** (x + 7.) / 2.)
        low = .7 / (1. + 10. ** (x + 5.) / 3.)
        y = 100. * (high + low)
        frame = pd.DataFrame({"X": x, "Binding": y.astype(np.float32)})
        equation = ("logEC50Lo=log(10^logKiLo*(1+HotNM/HotKdNMLo))\r\n"
                    "logEC50Hi=log(10^logKiHi*(1+HotNM/HotKdNMHi))\r\nSpan=Top-Bottom\r\n"
                    "Part1=FractionHi*Span/(1+10^(X-LogEC50Hi))\r\n"
                    "Part2=(1-FractionHi)*Span/(1+10^(X-LogEC50Lo))\r\nY=Bottom+Part1+Part2")
        records = _function(equation, {"logKiLo": -5., "HotNM": 2., "HotKdNMLo": 1., "logKiHi": -7.,
                                       "HotKdNMHi": 2., "Top": 100., "Bottom": 0., "FractionHi": .3})
        options = _simulation_options(records, frame)
        self.assertEqual(options[plotting.MODEL], "Two-site competition (log Ki)")
        recipe, = options[plotting.CURVES]
        self.assertEqual(recipe["parameters"]["Log Ki 1"], -7.)
        self.assertEqual(recipe["parameters"]["Fraction 1"], .3)
        result = plotting.plot_function(frame[["X"]], options)
        np.testing.assert_allclose(result.tables[plotting.VALUES]["Binding"], y, rtol=1e-14)

    def test_empty_legacy_graph_series_requires_the_explicit_marker_and_zero_points(self):
        from analisi.legacy_binary_editable import _scene

        def series(key, dataset, drawing, cache):
            header = pack("<4H", key, 0, dataset, 1) + bytes(50) + pack("<H", drawing) + bytes(84)
            return [(0x8020, (24,), pack("<H", 9) + bytes(28)), (0x8028, (24, 32), header),
                    (0x29, (24, 32, 40), cache)]

        graph = [(0x13, (), bytes(48)), (0x8018, (), bytes(12))]
        points = pack("<I4i", 4, 1, 2, 3, 4)
        graph += series(19, 44, 0x88, points)
        empty = series(39, 65533, 0xA8, bytes(4))
        with self.assertRaises(ValueError):
            _scene(graph + empty, "cp1252")
        _, _, _, drawing = _scene(graph + empty, "cp1252", empty_series=(39,))
        self.assertEqual(list(drawing), [19])
        np.testing.assert_array_equal(drawing[19][1], [[1, 2], [3, 4]])
        with self.assertRaises(ValueError):
            _scene(graph + series(39, 65533, 0xA8, points), "cp1252", empty_series=(39,))

    def test_logarithmic_drawing_requires_the_unplottable_zero_sentinel(self):
        axes = [{"bounds": [-1., 1.], "length": 200, "unit": .01, "scale": "log"},
                {"bounds": [0., 10.], "length": 100, "unit": .1, "scale": "linear"}]
        data = np.array([[0., 2.], [1., 3.], [10., 4.]])
        cache = np.array([[-1, -1], [100, 30], [200, 40]])
        self.assertTrue(_matches_drawing(cache, data, axes))
        bad = cache.copy()
        bad[0] = [0, 0]
        self.assertFalse(_matches_drawing(bad, data, axes))
        bad = cache.copy()
        bad[2, 1] = 45
        self.assertFalse(_matches_drawing(bad, data, axes))
