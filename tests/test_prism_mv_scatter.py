from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd

from analisi.analysis_chain import result_frame
from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.kmeans_archive import ARCHIVE
from analisi.kmeans_options import SELECTION
from analisi.kmeans_reports import ASSIGNMENTS_TABLE
from analisi.prism_mv_scatter import APPEARANCE, CLUSTERED_SCATTER
from analisi.prism_mv_scatter_smoke import COLORS, PLOT, archive_fixture
from analisi.prism_restore import SAVED_XY, _link_clustered_scatter, _link_hierarchy_scatter
from analisi.workbench import analyse

class SavedCategoricalScatterTests(unittest.TestCase):
    def test_view_uses_exact_ids_and_saves_editable_coordinates(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "project.prismt"
            archive_fixture(source)
            self.assertEqual(list(load_tables(source)), ["Original"])
            tables = load_tables(source, restore_prism=True)
            self.assertNotIn("Graph unavailable", tables["Original"].attrs["import_warnings"][0])
            points = Dataset(tables[PLOT])
            path = Path(folder) / "roundtrip.alab"
            save_project(path, {PLOT: points})
            reopened = load_project(path)[PLOT]
            self.assertEqual(reopened.analyses, points.analyses)
            method, options = reopened.analyses[0]
            self.assertEqual(method, SAVED_XY)
            self.assertEqual(options[APPEARANCE]["palette"], COLORS)
            frame = reopened.frame()
            self.assertEqual(frame["Series"].tolist(), ["_Run B", "Run $A", "Run $A"])
            frame.loc[1, "X"] = 4.0
            figure = analyse(method, frame, options).figure
            ax, = figure.axes
            np.testing.assert_allclose(ax.collections[0].get_offsets(), [[4, 6], [5, 2]])
            np.testing.assert_allclose(ax.collections[1].get_offsets(), [[2, 5]])
            for artist, color in zip(ax.collections, COLORS.values(), strict=True):
                np.testing.assert_allclose(artist.get_facecolors()[0], to_rgba(color))
                np.testing.assert_allclose(artist.get_sizes(), [25])
                np.testing.assert_allclose(artist.get_linewidths(), [.4])
            self.assertEqual(ax.get_ylim(), (10, 0))
            self.assertEqual(ax.get_xlim(), (-1, 7))
            self.assertEqual(ax.get_xlabel(), "Dose $")
            np.testing.assert_allclose(ax.get_xticks(), [0, 2, 4, 6])
            np.testing.assert_allclose(ax.get_yticks(), [0, 2.5, 5, 7.5, 10])
            legend = ax.get_legend()
            self.assertEqual([item.get_text() for item in legend.get_texts()], list(COLORS))
            self.assertFalse(legend.get_texts()[0].get_parse_math())
            svg = Path(folder) / "saved.svg"
            figure.savefig(svg)
            self.assertIn("#339966", svg.read_text())

    def test_verified_cluster_labels_bind_to_current_assignments_and_save(self):
        source = pd.DataFrame({"Dose": [0., 1., 4., 5.], "Signal": [1., 2., 6., 7.]})
        source.attrs["prism_recipes"] = [(SELECTION, {
            "Minimum k": 2, "Maximum k": 2, ARCHIVE: {"models": [{"groups": [1, 1, 2, 2]}]},
        })]
        columns = ("Dose", "Signal", "2 clusters")
        # The archive's group numbers were permuted in the presentation.
        cached = source.assign(**{"2 clusters": ["Cluster 2", "Cluster 2", "Cluster 1", "Cluster 1"]})
        axis = {"title": "Original axis", "low": 0, "high": 8, "start": 0, "step": 2, "reversed": False}
        style = {"palette": {"Cluster 1": "#dd770099", "Cluster 2": "#008855bb"},
                 "size": 6, "width": 0, "edge": "#000000ff", "legend": "2 clusters", "x": axis, "y": axis}
        mixed = cached.copy()
        mixed.loc[0, "2 clusters"] = "Cluster 1"
        self.assertFalse(_link_clustered_scatter(source, 0, mixed, columns, style, "Scatter"))
        self.assertFalse(_link_clustered_scatter(source, 0, cached.assign(Dose=9), columns, style, "Scatter"))
        self.assertTrue(_link_clustered_scatter(source, 0, cached, columns, style, "Scatter"))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "linked.alab"
            save_project(path, {"Raw": Dataset(source)})
            reopened = load_project(path)["Raw"]
        method, options = reopened.analyses[1]
        self.assertEqual(method, SAVED_XY)
        link = reopened.analysis_sources[1]
        self.assertEqual((link.analysis_id, link.table), (reopened.analysis_ids[0], ASSIGNMENTS_TABLE))
        self.assertEqual(options[CLUSTERED_SCATTER]["labels"], ["Cluster 2", "Cluster 1"])
        current = source.assign(Dose=[0.25, 1., 4., 5.],
                                **{"Cluster (k=2)": pd.array([2, None, 1, 2], dtype="Int64")})
        result = analyse(method, current, options)
        data = result.tables["Saved XY coordinates"]
        self.assertEqual(data["X"].tolist(), [0.25, 4., 5.])
        self.assertEqual(data["Series"].tolist(), ["Cluster 1", "Cluster 2", "Cluster 1"])
        axes, = result.figure.axes
        np.testing.assert_allclose(axes.collections[0].get_facecolors(), [to_rgba(style["palette"]["Cluster 1"])])
        self.assertEqual(axes.get_xlim(), (0, 8))
        with self.assertRaisesRegex(ValueError, "no longer provides"):
            analyse(method, current.drop(columns="Cluster (k=2)"), options)

    def test_unsupported_graphs_keep_the_original_warning(self):
        for change in (
            {"dataSheet": "missing"},
            {"gdoTypesExt": {"defaults": ["symbols", "confidence ellipses"]}},
            {"xVariables": ["scatter-y"]},
            {"xVariables": ["not-a-dataset"]},
        ):
            with self.subTest(change=change), TemporaryDirectory() as folder:
                source = Path(folder) / "project.prismt"
                archive_fixture(source, change=change)
                views = load_tables(source, restore_prism=True)
                self.assertNotIn(PLOT, views)
                self.assertIn("Graph unavailable for Grouped scatter", views["Original"].attrs["import_warnings"][0])

    def test_hierarchy_scatter_resolves_named_axes_after_transposition_and_edits(self):
        source = pd.DataFrame({"Label": ["First", "Second"], "A": [1., 2.], "B": [2., 3.],
                               "C": [10., 11.], "D": [11., 12.]})
        variables = ["A", "B", "C", "D"]
        options = {"Variables": variables, "Observation labels": "Label", "Direction": "Columns",
                   "Column cut": "Count", "Column clusters": 2, "Scale columns": "None"}
        source.attrs["prism_recipes"] = [("Hierarchical clustering", options)]
        cached = pd.DataFrame({"Observation": variables, "First": [1., 2., 10., 11.],
                               "Second": [2., 3., 11., 12.],
                               "Cluster": ["Cluster 2", "Cluster 2", "Cluster 1", "Cluster 1"]})
        groups = [{"points": [{"idx": i} for i in rows]} for rows in ([2, 3], [0, 1])]
        axis = {"title": "Original axis", "low": 0, "high": 40, "start": 0, "step": 10, "reversed": False}
        style = {"palette": {"Cluster 1": "#dd770099", "Cluster 2": "#008855bb"},
                 "size": 6, "width": 0, "edge": "#000000ff", "legend": "Clusters", "x": axis, "y": axis}
        view = (source, 0), "Column", groups, 7
        axes = "First", "Second", "Cluster"
        self.assertFalse(_link_hierarchy_scatter({"fenID": 9}, view, cached, axes, style, "Scatter"))
        self.assertFalse(_link_hierarchy_scatter({"fenID": 7}, view, cached.assign(First=9), axes, style, "Scatter"))
        self.assertFalse(_link_hierarchy_scatter({"fenID": 7}, view, cached.assign(Cluster="Cluster 1"), axes, style, "Scatter"))
        self.assertTrue(_link_hierarchy_scatter({"fenID": 7}, view, cached, axes, style, "Scatter"))
        method, graph = source.attrs["prism_recipes"][1]
        table = source.attrs["prism_analysis_sources"][1].table
        self.assertEqual(table, "Assignments")
        parent = analyse("Hierarchical clustering", source, options)
        points = analyse(method, result_frame(parent, table), graph).tables["Saved XY coordinates"]
        self.assertEqual(points["X"].tolist(), cached["First"].tolist())
        self.assertEqual(points["Series"].tolist(), cached["Cluster"].tolist())
        self.assertEqual(points["Observation"].tolist(), variables)

        edited = source.iloc[::-1].reset_index(drop=True)
        edited.loc[1, "A"] = 1.25
        parent = analyse("Hierarchical clustering", edited, {**options, "Column clusters": 3})
        points = analyse(method, result_frame(parent, table), graph).tables["Saved XY coordinates"]
        self.assertEqual(points["X"].tolist(), [1.25, 2., 10., 11.])
        self.assertEqual(points["Y"].tolist(), cached["Second"].tolist())
        self.assertIn("Cluster 3", points["Series"].tolist())
