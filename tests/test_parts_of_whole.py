"""Composition geometry and independently computed goodness-of-fit results."""
from io import BytesIO
from math import erfc, exp, pi, sqrt
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset
from analisi.parts_of_whole import EXPECTED, STYLES, goodness_of_fit, parts_graph


class PartsOfWholeTests(unittest.TestCase):
    def test_donut_size_and_zero_legend(self):
        data = pd.DataFrame({"Row title": ["A", "Zero", "B", "Missing"], "Count": [3., 0., 1., None]})
        result = parts_graph(data, {"Values": "Count", "Donut hole (%)": 60.})
        table = result.tables["Composition"]
        self.assertEqual(table["Category"].tolist(), ["A", "Zero", "B"])
        np.testing.assert_array_equal(table["Fraction"], [.75, 0., .25])
        axis, = result.figure.axes
        self.assertEqual(len(axis.patches), 2)
        self.assertEqual([item.width for item in axis.patches], [.4, .4])
        self.assertEqual([item.get_text() for item in axis.get_legend().get_texts()], ["A · 75.0%", "B · 25.0%"])
        self.assertEqual(axis.texts[-1].get_text(), "Total\n4")

    def test_exact_dot_budget_and_vector_export_for_all_styles(self):
        data = pd.DataFrame({"Label": ["A", "B", "C"], "Count": [1, 1, 1]})
        for style in STYLES:
            with self.subTest(style=style):
                result = parts_graph(data, {"Values": "Count", "Row titles": "Label", "Graph style": style,
                                            "Reverse order": True, "Number of dots": 100})
                table = result.tables["Composition"]
                self.assertEqual(table["Category"].tolist(), ["C", "B", "A"])
                if style == "Dot plot":
                    self.assertEqual(table["Dots"].tolist(), [34, 33, 33])
                output = BytesIO()
                result.figure.savefig(output, format="svg")
                self.assertIn(b"<svg", output.getvalue())

    def test_plot_excludes_masked_values_and_checks_range(self):
        data = Dataset(pd.DataFrame({"Count": [1, -2, 3]}), excluded={(1, 0)})
        result = parts_graph(data.frame(mask_excluded=True), {"Values": "Count"})
        self.assertEqual(result.tables["Composition"]["Category"].tolist(), ["Row 1", "Row 3"])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            parts_graph(data.frame(), {"Values": "Count"})
        with self.assertRaisesRegex(ValueError, "positive total"):
            parts_graph(pd.DataFrame({"Count": [0, 0]}), {"Values": "Count"})

    def test_original_mendel_example(self):
        observed = [315, 108, 101, 32]
        expected = [312.75, 104.25, 104.25, 34.75]
        data = pd.DataFrame({"Count": observed, "Model": [9, 3, 3, 1]})
        report = goodness_of_fit(data, {"Observed counts": "Count", "Expected distribution": EXPECTED[1],
                                         "Expected values": "Model"}).tables
        values = report["Test"]["Value"]
        self.assertEqual(values["df"], 3)
        statistic = sum((a - b)**2 / b for a, b in zip(observed, expected, strict=True))
        survival = erfc(sqrt(statistic / 2)) + sqrt(2 * statistic / pi) * exp(-statistic / 2)
        self.assertAlmostEqual(values["Pearson χ²"], statistic)
        self.assertAlmostEqual(values["p"], survival, places=14)
        np.testing.assert_array_equal(report["Categories"]["Expected"], expected)

    def test_expected_count_totals_and_fitted_parameter_budget(self):
        data = pd.DataFrame({"Count": [5, 5], "Model": [6, 5]})
        with self.assertRaisesRegex(ValueError, "must sum"):
            goodness_of_fit(data, {"Observed counts": "Count", "Expected distribution": EXPECTED[2],
                                  "Expected values": "Model"})
        with self.assertRaisesRegex(ValueError, "degrees of freedom"):
            goodness_of_fit(data, {"Observed counts": "Count", "Estimated parameters": 1})
        equal = goodness_of_fit(data, {"Observed counts": "Count"}).tables["Test"]["Value"]
        self.assertEqual(equal["p"], 1.)
