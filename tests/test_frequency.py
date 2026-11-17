"""Frequency edges, exact cumulative frequencies, and omissions."""
import unittest

import numpy as np
import pandas as pd

from analisi.frequency import CUMULATIVE, EXACT, POOLED, ROW_MEAN, frequency, style_after_parameter_change
from analisi.presentation import apply_style
from analisi.probability_scale import PERCENT_SCALE


class FrequencyTests(unittest.TestCase):
    def test_border_values_go_to_the_higher_bin(self):
        frame = pd.DataFrame({"x": [3.5, np.nextafter(4.5, 0), 4.5, 5.5, 6.5]})
        tables = frequency(frame, {"Variables": ["x"], "Bin width (blank = automatic)": "1",
                                  "First bin center (blank = automatic)": "4"}).tables
        self.assertEqual(tables["Frequencies"]["Counts"].tolist(), [2, 1, 1, 1])

    def test_relative_cumulative_with_common_bins_and_range(self):
        frame = pd.DataFrame({"a": [0., 1., 2., 3.], "b": [1., 2., 4., None]})
        report = frequency(frame, {"Variables": ["a", "b"], "Distribution": CUMULATIVE, "Units": "Fractions",
                                    "Bin width (blank = automatic)": "1", "First bin center (blank = automatic)": "1,5",
                                    "Maximum value (blank = no limit)": "2"})
        self.assertEqual(report.tables["Frequencies"]["Fractions"].tolist(), [.5, 1., .5, 1.])
        self.assertEqual(report.tables["Observation counts"]["Omitted"].tolist(), [2, 1])

    def test_exact_cumulative_aggregates_ties(self):
        frame = pd.DataFrame({"x": [6., 4., 6., None, 1., 1.]})
        report = frequency(frame, {"Variables": ["x"], "Distribution": EXACT, "Units": "Percentages",
                                    "Bin width (blank = automatic)": "unused"})
        table = report.tables["Frequencies"]
        self.assertEqual(table["Value"].tolist(), [1., 4., 6.])
        self.assertEqual(table["Percentages"].tolist(), [40., 60., 100.])

    def test_replicate_pool_and_row_means_keep_worksheet_groups(self):
        frame = pd.DataFrame({"Time": [0, 1, 2, 3], "A [1]": [1, None, 5, None],
                              "A [2]": [3, 4, None, None], "B": [2, 3, None, None]})
        frame.attrs["worksheet_roles"] = {"x": ["Time"], "y": [["A [1]", "A [2]"], ["B"]]}
        base = {"Variables": ["A [1]", "A [2]", "B"], "Distribution": EXACT}
        means = frequency(frame, {**base, "Replicates": ROW_MEAN}).tables
        pool = frequency(frame, {**base, "Replicates": POOLED}).tables
        self.assertEqual(means["Frequencies"].query('Variable == "A"')["Value"].tolist(), [2, 4, 5])
        self.assertEqual(pool["Frequencies"].query('Variable == "A"')["Value"].tolist(), [1, 3, 4, 5])
        self.assertEqual(means["Observation counts"]["Observed"].tolist(), [3, 2])
        self.assertEqual(pool["Observation counts"]["Observed"].tolist(), [4, 2])

    def test_probability_axis_preserves_exact_frequencies_and_endpoints(self):
        frame = pd.DataFrame({"A": [1, 2, 3, 4, 5]})
        base = {"Variables": ["A"], "Distribution": EXACT, "Units": "Percentages"}
        result = frequency(frame, {**base, "Y scale": "Gaussian probability"})
        linear = frequency(frame, base)
        pd.testing.assert_frame_equal(result.tables["Frequencies"], linear.tables["Frequencies"])
        self.assertEqual(result.tables["Frequencies"]["Percentages"].iloc[-1], 100)
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_yscale(), PERCENT_SCALE)
        transform = axes.yaxis.get_transform()
        expected = np.array([-1., 0., 1.])
        probabilities = np.array([15.865525393145708, 50., 84.1344746068543])
        np.testing.assert_allclose(transform.transform(probabilities), expected, atol=1e-14)
        np.testing.assert_allclose(transform.inverted().transform(expected), probabilities)
        self.assertTrue(np.isnan(transform.transform([0, 100])).all())
        apply_style(result.figure, {"title": "Normal probability", "yscale": PERCENT_SCALE,
                                    "axis": {"y": {"min": 1, "max": 99}}})
        self.assertEqual(axes.get_ylim(), (1, 99))
        with self.assertRaisesRegex(ValueError, "strictly between"):
            apply_style(result.figure, {"yscale": PERCENT_SCALE, "axis": {"y": {"min": 0, "max": 100}}})
        with self.assertRaisesRegex(ValueError, "cumulative fractions"):
            frequency(frame, {"Variables": ["A"], "Y scale": "Gaussian probability"})

    def test_probability_option_supersedes_previous_axis_format(self):
        before = {"Variables": ["A"], "Distribution": EXACT, "Units": "Percentages"}
        after = {**before, "Y scale": "Gaussian probability"}
        style = {"title": "Measurements", "ylabel": "Percentages", "yscale": "linear",
                 "axis": {"x": {"min": 0, "max": 7}, "y": {"min": 0, "max": 100}}}
        amended = style_after_parameter_change(style, before, after)
        self.assertEqual(amended, {"title": "Measurements", "axis": {"x": {"min": 0, "max": 7}}})
        result = frequency(pd.DataFrame({"A": [1, 2, 3]}), after)
        apply_style(result.figure, amended)
        self.assertEqual(result.figure.axes[0].get_yscale(), PERCENT_SCALE)
        self.assertEqual(result.figure.axes[0].get_ylabel(), "Percentages · Normal probability")

    def test_xy_histogram_styles_have_numeric_centers(self):
        frame = pd.DataFrame({"A": [0, .25, 1.25, 2]})
        base = {"Variables": ["A"], "Bin width (blank = automatic)": "1",
                "First bin center (blank = automatic)": ".5"}
        points = frequency(frame, {**base, "Graph style": "XY points"})
        spikes = frequency(frame, {**base, "Graph style": "XY spikes"})
        np.testing.assert_equal(points.figure.axes[0].lines[0].get_xdata(), [.5, 1.5, 2.5])
        np.testing.assert_equal(spikes.figure.axes[0].collections[0].get_segments()[0], [[.5, 0], [.5, 2]])
        pd.testing.assert_frame_equal(points.tables["Frequencies"], spikes.tables["Frequencies"])

    def test_documented_nice_width_for_integer_data_and_invalid_range(self):
        frame = pd.DataFrame({"x": np.arange(100)})
        tables = frequency(frame, {"Variables": ["x"]}).tables
        self.assertEqual(tables["Settings"].loc["Bin width", "Value"], 10.)
        self.assertEqual(tables["Frequencies"]["Counts"].tolist(), [10] * 10)
        with self.assertRaisesRegex(ValueError, "wider bin"):
            frequency(frame, {"Variables": ["x"], "Bin width (blank = automatic)": ".01"})
