import unittest
from struct import pack

import numpy as np
import pandas as pd

from analisi import plot_function as plotting
from analisi.legacy_binary_simulation import _simulation_options, _matches_drawing
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
