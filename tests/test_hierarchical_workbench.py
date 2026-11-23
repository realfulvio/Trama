import unittest

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from scipy.cluster.hierarchy import leaves_list

from analisi.hierarchical_style import apply_hierarchical_style

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

    def test_styled_tree_labels_follow_the_merge_table_even_after_subsampling(self):
        frame = pd.DataFrame({"Label": ["near A", "far A", "near B", "far B", "isolated"],
                              "X": [0., 9., .1, 9.15, 25.]})
        for interval in (1, 2):
            for orientation in ("Horizontal", "Vertical"):
                with self.subTest(interval=interval, orientation=orientation):
                    result = hierarchical_result(frame, {
                        "Variables": ["X"], "Observation labels": "Label",
                        "Label interval (0 = automatic)": interval, "Dendrogram orientation": orientation})
                    order = leaves_list(result.tables["Merges"].to_numpy())
                    expected = frame["Label"].iloc[order].tolist()
                    axis = result.figure.axes[0]
                    ticks = axis.get_yticklabels if orientation == "Horizontal" else axis.get_xticklabels
                    self.assertEqual([tick.get_text() for tick in ticks()], expected[::interval])
                    apply_hierarchical_style(result.figure, {"row": {"labels": {"interval": 1}}})
                    self.assertEqual([tick.get_text() for tick in ticks()], expected)

    def test_elbow_uses_within_cluster_sums_on_the_fitted_tree(self):
        data = pd.DataFrame({"X": [0., 1., 3.]})
        options = {"Variables": ["X"], "Clusters": 1, "Graph output": "Elbow plot"}
        for offset in (0., 2.**40):
            with self.subTest(offset=offset):
                result = hierarchical_result(data + offset, options)
                table = result.tables["Elbow data"]
                self.assertEqual(table["Number of clusters"].tolist(), [1, 2])
                np.testing.assert_allclose(table["WCSS"], [14/3, .5], rtol=0, atol=1e-14)
                line, = result.figure.axes[0].lines
                np.testing.assert_array_equal(line.get_xdata(), [1, 2])
                np.testing.assert_allclose(line.get_ydata(), [14/3, .5], rtol=0, atol=1e-14)

    def test_optional_elbow_data_reports_rows_and_columns_with_existing_graph(self):
        options = {**self.options, "Direction": "Rows and columns", "Elbow data": True}
        result = hierarchical_result(self.frame, options)
        row = result.tables["Row Elbow data"]
        col = result.tables["Column Elbow data"]
        for axis, values, output in [("rows", self.frame.iloc[:, 1:].to_numpy(), row),
                                     ("columns", self.frame.iloc[:, 1:].to_numpy().T, col)]:
            self.assertEqual(len(output), len(values) - 1)
            expected = np.square(values - values.mean(axis=0)).sum()
            self.assertAlmostEqual(output["WCSS"].iloc[0], expected)
            self.assertTrue(np.all(np.diff(output["WCSS"]) <= 0))
        self.assertEqual(result.figure.axes[0].get_title(), "Dendrogram of rows")

    @staticmethod
    def _silhouette_oracle(tree, distances):
        n = len(distances)
        groups = {i: [i] for i in range(n)}
        scores = [np.nan] * (n - 1)
        for node, (a, b, _, _) in enumerate(tree, n):
            groups[node] = groups.pop(int(a)) + groups.pop(int(b))
            if len(groups) < 2:
                break
            values = []
            for group, members in groups.items():
                for index in members:
                    if len(members) == 1:
                        values.append(0.)
                        continue
                    a = distances[index, members].sum() / (len(members) - 1)
                    b = min(distances[index, rivals].mean() for key, rivals in groups.items() if key != group)
                    values.append((b - a) / max(a, b) if a or b else 0.)
            scores[len(groups) - 1] = np.mean(values)
        return scores

    def test_hierarchy_silhouette_data_uses_both_fitted_axes_and_the_selected_distance(self):
        from scipy.spatial.distance import pdist, squareform

        frame = pd.DataFrame({
            "A": [1., 1., 2., 4., 7., 8., 10., np.nan],
            "B": [2., 1., 3., 6., 6., 9., 5., 8.],
            "C": [10., 6., 0., 5., 9., 2., 8., 6.],
            "D": [7., 2., 4., 4., 5., 3., 4., 5.],
        })
        options = {"Variables": list(frame), "Direction": "Rows and columns", "Linkage": "complete",
                   "Scale columns": "Center", "Distance": "cityblock", "Scaled data": True}
        base = hierarchical_result(frame, options)
        result = hierarchical_result(frame, {**options, "Silhouette data": True})
        for name, old in base.tables.items():
            pd.testing.assert_frame_equal(result.tables[name], old)
        values = base.tables["Scaled data"].to_numpy()
        for axis, points in (("Row", values), ("Column", values.T)):
            tree = result.tables[f"{axis} Merges"].to_numpy()
            expected = self._silhouette_oracle(tree, squareform(pdist(points, "cityblock")))
            table = result.tables[f"{axis} Silhouette data"]
            np.testing.assert_array_equal(table["Number of clusters"], np.arange(1, len(points)))
            np.testing.assert_allclose(table["Mean silhouette"], expected, rtol=0, atol=2e-15)
        self.assertEqual(result.figure.axes[0].get_title(), "Dendrogram of rows")

    def test_hierarchy_silhouette_plot_can_link_to_merges_without_refitting(self):
        from unittest.mock import patch
        from analisi.analysis_chain import result_frame
        from analisi.workbench import analyse

        options = {**self.options, "Direction": "Rows and columns", "Distance": "cityblock",
                   "Column clusters": 2}
        source = hierarchical_result(self.frame, options)
        output = {"Graph output": "Silhouette plot"}
        primary = hierarchical_result(self.frame, {**options, **output})
        with patch("analisi.hierarchical_workbench.hierarchical", side_effect=AssertionError("unexpected fit")):
            linked = analyse("Hierarchy graph", result_frame(source, "Row Merges"),
                             {**output, "Hierarchy axis": "Columns"})
        self.assertEqual(len(primary.figure.axes), 2)
        axis, = linked.figure.axes
        line = axis.lines[0]
        np.testing.assert_array_equal(line.get_xdata(), primary.tables["Column Silhouette data"]["Number of clusters"])
        np.testing.assert_allclose(line.get_ydata(), primary.tables["Column Silhouette data"]["Mean silhouette"])
        self.assertTrue(all(k == int(k) for k in axis.get_xticks()))

    def test_hierarchy_silhouette_undefined_single_cluster_and_zero_distances(self):
        for values in ([0., 2.], [1., 1., 1., 1.]):
            with self.subTest(values=values):
                result = hierarchical_result(pd.DataFrame({"A": values}),
                                             {"Variables": ["A"], "Graph output": "Silhouette plot"})
                scores = result.tables["Silhouette data"]["Mean silhouette"].to_numpy()
                self.assertTrue(np.isnan(scores[0]))
                np.testing.assert_array_equal(scores[1:], np.zeros(len(values) - 2))

    def test_hierarchy_silhouette_ratios_do_not_overflow(self):
        points = pd.DataFrame({"X": [0., 9e307, 1.7e308]})
        result = hierarchical_result(points, {"Variables": ["X"], "Distance": "cityblock", "Linkage": "single",
                                              "Graph output": "Silhouette plot"})
        self.assertAlmostEqual(result.tables["Silhouette data"].iat[1, 1], (2 - 8/9 - 8/17) / 3)

    def test_hierarchy_silhouette_can_be_cancelled_between_cuts(self):
        from analisi.monte_carlo import MonteCarloCancelled

        class Interrupt:
            remaining = 7

            def is_set(self):
                self.remaining -= 1
                return self.remaining <= 0

        with self.assertRaises(MonteCarloCancelled):
            hierarchical_result(pd.DataFrame({"X": np.arange(20.)}),
                                {"Variables": ["X"], "Silhouette data": True}, cancel=Interrupt())

    @staticmethod
    def _gap_oracle(tree, points):
        groups = {i: [i] for i in range(len(points))}
        wcss = []
        for node, (a, b, _, _) in enumerate(tree, len(points)):
            groups[node] = groups.pop(int(a)) + groups.pop(int(b))
            wcss.append(sum(
                np.square(block - block.mean(axis=0)).sum()
                for block in (points[members] for members in groups.values())
            ))
        return np.log(wcss[::-1])

    def test_gap_on_both_axes_matches_direct_centroid_dispersion(self):
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import pdist

        options = {**self.options, "Direction": "Rows and columns", "Linkage": "complete",
                   "Scale columns": "Center", "Distance": "cityblock", "Scaled data": True}
        base = hierarchical_result(self.frame, options)
        result = hierarchical_result(self.frame, {**options, "Gap data": True,
                                                 "Gap reference datasets": 7, "Gap seed": 91})
        for name, old in base.tables.items():
            pd.testing.assert_frame_equal(result.tables[name], old)
        values = base.tables["Scaled data"].to_numpy()
        for axis, points in (("Row", values), ("Column", values.T)):
            tree = result.tables[f"{axis} Merges"].to_numpy()
            observed = self._gap_oracle(tree, points)
            references = []
            for index in range(7):
                reference = np.random.default_rng([91, index]).uniform(
                    points.min(axis=0), points.max(axis=0), points.shape)
                references.append(self._gap_oracle(linkage(pdist(reference, "cityblock"), "complete"), reference))
            mean = np.mean(references, axis=0)
            gap = mean - observed
            se = np.std(references, axis=0) * np.sqrt(1 + 1/7)
            recommended = next((i for i in range(len(gap) - 1) if gap[i] >= gap[i + 1] - se[i + 1]),
                               len(gap) - 1)
            table = result.tables[f"{axis} Gap data"]
            np.testing.assert_array_equal(table["Number of clusters"], np.arange(1, len(points)))
            np.testing.assert_allclose(table["Log W observed"], observed, rtol=0, atol=8e-15)
            np.testing.assert_allclose(table["Mean log W reference"], mean, rtol=0, atol=8e-15)
            np.testing.assert_allclose(table["Gap"], gap, rtol=0, atol=8e-15)
            np.testing.assert_allclose(table["Gap SE"], se, rtol=0, atol=8e-15)
            np.testing.assert_array_equal(table["Recommended"], np.arange(len(gap)) == recommended)
        self.assertEqual(result.figure.axes[0].get_title(), "Dendrogram of rows")

    def test_gap_linked_plot_reuses_parent_settings_and_observed_merges(self):
        from unittest.mock import patch
        from analisi.analysis_chain import result_frame
        from analisi.workbench import analyse

        options = {**self.options, "Direction": "Rows and columns", "Gap reference datasets": 5, "Gap seed": 3}
        source = hierarchical_result(self.frame, options)
        output = {"Graph output": "Gap plot"}
        primary = hierarchical_result(self.frame, {**options, **output})
        with patch("analisi.hierarchical_workbench.hierarchical", side_effect=AssertionError("unexpected fit")):
            linked = analyse("Hierarchy graph", result_frame(source, "Row Merges"),
                             {**output, "Hierarchy axis": "Columns"})
        self.assertEqual(len(primary.figure.axes), 2)
        axis, = linked.figure.axes
        table = primary.tables["Column Gap data"]
        np.testing.assert_array_equal(axis.lines[0].get_xdata(), table["Number of clusters"])
        np.testing.assert_array_equal(axis.lines[0].get_ydata(), table["Gap"])
        self.assertTrue(all(k == int(k) for k in axis.get_xticks()))

    def test_gap_handles_zero_dispersion_and_unrepresentable_sums_of_squares(self):
        options = {"Variables": ["X"], "Distance": "cityblock", "Linkage": "single",
                   "Graph output": "Gap plot", "Gap reference datasets": 5}
        result = hierarchical_result(pd.DataFrame({"X": [1., 1., 1.]}), options)
        self.assertTrue(result.tables["Gap data"]["Gap"].isna().all())
        self.assertFalse(result.tables["Gap data"]["Recommended"].any())
        ordinary = hierarchical_result(pd.DataFrame({"X": [0., 0.9, 1.7]}), options).tables["Gap data"]
        large = hierarchical_result(pd.DataFrame({"X": [0., 9e307, 1.7e308]}), options).tables["Gap data"]
        np.testing.assert_allclose(large["Gap"], ordinary["Gap"], rtol=0, atol=1e-14)
        np.testing.assert_allclose(large["Log W observed"] - ordinary["Log W observed"], 2*np.log(1e308),
                                   rtol=0, atol=3e-13)

    def test_gap_validation_and_cancellation_during_reference_fits(self):
        from unittest.mock import patch
        from threading import Event
        from analisi.field_error import FieldError
        from analisi.hierarchical_gap import _reference_wcss
        from analisi.monte_carlo import MonteCarloCancelled

        options = {**self.options, "Gap data": True, "Gap reference datasets": 5}
        for field, value in (("Gap reference datasets", 4), ("Gap seed", -1)):
            with self.subTest(field=field), self.assertRaises(FieldError) as failure:
                hierarchical_result(self.frame, {**options, field: value})
            self.assertEqual(failure.exception.field, field)
        cancel = Event()

        def run_one(job, flag):
            result = _reference_wcss(job, flag)
            cancel.set()
            return result

        with (patch("analisi.parallel.process_count", return_value=1),
              patch("analisi.hierarchical_gap._reference_wcss", side_effect=run_one)):
            with self.assertRaises(MonteCarloCancelled):
                hierarchical_result(self.frame, options, cancel=cancel)

    def test_clustered_data_plots_original_coordinates_for_both_directions(self):
        frame = self.frame.rename(columns={"A": "Dose $"}).assign(C=[100., 110., 130., 600.])
        options = {**self.options, "Variables": ["Dose $", "B", "C"], "Direction": "Rows and columns",
                   "Scale columns": "Standardize", "Scale rows": "Center",
                   "Scaled data": True, "Graph output": "Clustered data plot"}
        result = hierarchical_result(frame, options)
        for key, axis, labels in zip(("Row", "Column"), result.figure.axes,
                                     [("Dose $", "B"), ("one", "two")], strict=True):
            raw = result.tables[f"{key} Assignments"]
            self.assertEqual((axis.get_xlabel(), axis.get_ylabel()), labels)
            self.assertFalse(axis.xaxis.label.get_parse_math())
            for group, collection in enumerate(axis.collections, 1):
                expected = raw.loc[raw["Cluster"] == group].iloc[:, :2].to_numpy()
                np.testing.assert_array_equal(collection.get_offsets(), expected)
                self.assertEqual(collection.get_label(), f"Cluster {group}")

    def test_clustered_data_link_uses_existing_cut_and_skips_an_uncut_direction(self):
        from unittest.mock import patch
        from analisi.analysis_chain import result_frame
        from analisi.field_error import FieldError
        from analisi.workbench import analyse

        options = {**self.options, "Direction": "Rows and columns", "Row cut": "No cut",
                   "Column cut": "Cut height", "Column cut height": 2.}
        source = hierarchical_result(self.frame, options)
        merges = result_frame(source, "Row Merges")
        plot = {"Graph output": "Clustered data plot"}
        with patch("analisi.hierarchical_workbench.hierarchical", side_effect=AssertionError("unexpected fit")):
            linked = analyse("Hierarchy graph", merges, plot)
            with self.assertRaises(FieldError) as error:
                analyse("Hierarchy graph", merges, {**plot, "Hierarchy axis": "Rows"})
        self.assertEqual(error.exception.field, "Hierarchy axis")
        axis, = linked.figure.axes
        self.assertIn("columns", axis.get_title())
        expected = source.tables["Column Assignments"]
        groups = list(axis.collections)
        self.assertEqual(len(groups), expected["Cluster"].nunique())
        for group, collection in enumerate(groups, 1):
            values = expected.loc[expected["Cluster"] == group].iloc[:, :2].to_numpy()
            np.testing.assert_array_equal(collection.get_offsets(), values)

    def test_clustered_data_single_measure_and_uncut_validation(self):
        from analisi.field_error import FieldError

        points = pd.DataFrame({"Reading": [0., 1., 9., 10.]})
        options = {"Variables": ["Reading"], "Scale columns": "Standardize",
                   "Row cut": "Count", "Clusters": 2, "Graph output": "Clustered data plot"}
        axis, = hierarchical_result(points, options).figure.axes
        self.assertEqual((axis.get_xlabel(), axis.get_ylabel()), ("Cluster", "Reading"))
        np.testing.assert_array_equal(axis.collections[0].get_offsets(), [[1., 0.], [1., 1.]])
        np.testing.assert_array_equal(axis.collections[1].get_offsets(), [[2., 9.], [2., 10.]])
        with self.assertRaises(FieldError) as error:
            hierarchical_result(points, {**options, "Row cut": "No cut"})
        self.assertEqual(error.exception.field, "Graph output")

    def test_clustered_data_with_many_groups_keeps_color_scale_vectorial(self):
        from io import StringIO

        points = pd.DataFrame({"X": np.arange(30.), "Y": np.arange(30.) ** 2})
        options = {"Variables": list(points), "Clusters": 24, "Graph output": "Clustered data plot"}
        figure = hierarchical_result(points, options).figure
        plot, color_scale = figure.axes
        self.assertEqual(len(plot.collections[0].get_offsets()), len(points))
        self.assertEqual(color_scale.get_ylabel(), "Cluster")
        svg = StringIO()
        figure.savefig(svg, format="svg")
        self.assertNotIn("<image", svg.getvalue())

    def test_finite_elbow_data_near_largest_float(self):
        data = pd.DataFrame({"X": [0., 1.4e154]})
        result = hierarchical_result(data, {"Variables": ["X"], "Distance": "cityblock", "Elbow data": True})
        self.assertAlmostEqual(result.tables["Elbow data"]["WCSS"].iloc[0] / 1e307, 9.8)

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
