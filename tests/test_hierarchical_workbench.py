import unittest

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg

from analisi.hierarchical_workbench import _coordinates, hierarchical_result
from analisi.stats import hierarchical


class HierarchicalWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Label": ["one", "two", "three", "four"],
                                   "A": [0., .2, 9., 10.], "B": [0., 0., 9., 9.],
                                   "C": [1., 2., 10., 11.]})
        self.options = {"Variables": ["A", "B", "C"], "Observation labels": "Label",
                        "Clusters": 2, "Standardize": False, "Linkage": "average"}

    def test_cut_colors_and_horizontal_labels_follow_tree_leaves(self):
        options = {**self.options, "Row cut": "Cut height", "Row cut height": 2.,
                   "Dendrogram orientation": "Horizontal", "Label interval (0 = automatic)": 2,
                   "Label type": "Letters"}
        result = hierarchical_result(self.frame, options)
        self.assertEqual(result.tables["Assignments"]["Cluster"].tolist(), [1, 1, 2, 2])
        ax, = result.figure.axes
        self.assertEqual(ax.get_xlabel(), "Merge distance")
        self.assertEqual([tick.get_text() for tick in ax.get_yticklabels()], ["A", "C"])
        self.assertEqual(len(set(map(tuple, ax.collections[0].get_colors()))), 3)
        np.testing.assert_equal(ax.lines[0].get_xdata(), [2, 2])
        self.assertEqual(len(ax.collections[0].get_segments()), 3)

    def test_dual_heatmap_axes_align_and_values_follow_both_leaf_orders(self):
        options = {**self.options, "Direction": "Rows and columns", "Graph output": "Heat map",
                   "Column clusters": 2, "Scale columns": "Center", "Scaled data": True}
        result = hierarchical_result(self.frame, options)
        self.assertIn("Row Assignments", result.tables)
        self.assertIn("Column Merges", result.tables)
        heat, left, top, color = result.figure.axes
        self.assertEqual(heat.get_ylim(), left.get_ylim())
        self.assertEqual(heat.get_xlim(), top.get_xlim())
        self.assertEqual(color.get_ylabel(), "Value")
        variables = self.options["Variables"]
        row = hierarchical(self.frame, variables, 2, column_scale="center")
        column = hierarchical(self.frame, variables, 2, column_scale="center", axis="columns")
        rows = _coordinates(row.tree, row.labels)[0]
        cols = _coordinates(column.tree, column.labels)[0]
        expected = result.tables["Scaled data"].to_numpy()[np.ix_(rows, cols)]
        np.testing.assert_allclose(heat.images[0].get_array(), expected)
        self.assertEqual([tick.get_text() for tick in heat.get_xticklabels()],
                         [variables[i] for i in cols])

    def test_distance_and_cophenetic_diagnostics_match_fixed_coordinates(self):
        frame = pd.DataFrame({"ID": ["dup", "dup", "far"], "X": [0., 2., 10.]})
        result = hierarchical_result(frame, {"Variables": ["X"], "Observation labels": "ID",
                                     "Clusters": 2, "Distance matrix": True, "Cophenetic distances": True,
                                     "Cophenetic correlation": True, "Matrix format": "Lower triangle"})
        d, c = result.tables["Distance matrix"], result.tables["Cophenetic distances"]
        self.assertEqual(len(set(d.columns)), 3)
        self.assertTrue(np.isnan(d.iat[0, 1]))
        np.testing.assert_allclose([d.iat[1, 0], d.iat[2, 0], d.iat[2, 1]], [2, 10, 8])
        np.testing.assert_allclose([c.iat[1, 0], c.iat[2, 0], c.iat[2, 1]], [2, 9, 9])
        self.assertAlmostEqual(result.tables["Cophenetic correlation"].iat[0, 0],
                               np.corrcoef([2, 10, 8], [2, 9, 9])[0, 1])

    def test_no_cut_uses_one_branch_color(self):
        result = hierarchical_result(self.frame, {**self.options, "Row cut": "No cut"})
        self.assertNotIn("Assignments", result.tables)
        self.assertEqual(len(set(map(tuple, result.figure.axes[0].collections[0].get_colors()))), 1)

    def test_blank_observation_label_uses_original_worksheet_row(self):
        frame = pd.DataFrame({"Name": ["Omitted", None, "Sample 3"], "X": [np.nan, 0., 2.]})
        result = hierarchical_result(frame, {"Variables": ["X"], "Observation labels": "Name", "Clusters": 2})
        names = {tick.get_text() for tick in result.figure.axes[0].get_xticklabels()}
        self.assertEqual(names, {"Row 2", "Sample 3"})

    def test_literal_labels_render_in_tree_and_heat_map(self):
        frame = self.frame.rename(columns={"A": r"Label $\bad$"})
        options = {**self.options, "Variables": [r"Label $\bad$", "B", "C"],
                   "Direction": "Rows and columns"}
        frame.loc[0, "Label"] = r"Sample $\bad$"
        for output in ("Dendrogram", "Heat map"):
            with self.subTest(output=output):
                result = hierarchical_result(frame, {**options, "Graph output": output})
                FigureCanvasAgg(result.figure).draw()

    def test_cophenetic_correlation_is_invariant_to_large_distance_scale(self):
        frame = pd.DataFrame({"X": [0., 2e200, 10e200]})
        result = hierarchical_result(frame, {"Variables": ["X"], "Clusters": 2, "Distance": "cityblock",
                                     "Cophenetic correlation": True})
        self.assertAlmostEqual(result.tables["Cophenetic correlation"].iat[0, 0],
                               np.corrcoef([2, 10, 8], [2, 9, 9])[0, 1])

    def test_deep_chain_can_be_rendered_without_recursion(self):
        n = 1800
        tree = np.column_stack((np.r_[0, np.arange(n, 2 * n - 2)], np.arange(1, n),
                                np.arange(1, n), np.arange(2, n + 1)))
        order, paths, colors = _coordinates(tree, None)
        np.testing.assert_equal(order, np.arange(n))
        self.assertEqual(paths.shape, (n - 1, 4, 2))
        self.assertFalse(colors.any())


if __name__ == "__main__":
    unittest.main()
