"""Compatibility checks for saved, recalculable PCA recipes in ZIP projects."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from analisi.analysis_chain import evaluate_graph
from analisi.data import Dataset, load_project, load_tables, save_project, validate_analysis_links
from analisi.kmeans_options import SELECTION
from analisi.prism_recipes import restore_recipe
from analisi.prism_pca_smoke import INPUT, SOURCE_NAME, sample, write_project
from analisi.workbench import analyse
from tests.test_prism_recipes import source


METHOD = "Principal component analysis"
def fixture():
    frame, content = sample()
    return source("PCA", "0.0.0", content, frame, INPUT)


class PrismPCARecipeTests(unittest.TestCase):
    def test_clustered_data_input_uses_the_live_assignment_table_and_survives_roundtrip(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "chain.prismt"
            write_project(archive, clustered=True)
            data = {title: Dataset(frame) for title, frame in load_tables(archive, restore_prism=True).items()}
            raw = data["Raw"]
            self.assertEqual([method for method, _ in raw.analyses], [SELECTION, METHOD])
            parent, child = (raw.analysis_ids[slot] for slot in range(2))
            self.assertEqual(raw.analysis_sources[1].analysis_id, parent)
            self.assertEqual(raw.analysis_sources[1].table, "Assignments by k")
            self.assertEqual(raw.analyses[1][1]["Color groups by"], "Cluster (k=2)")
            snapshot = data["Prism result · Saved assignments · Clustered data"]
            self.assertFalse(snapshot.analyses)
            self.assertIn("2 clusters", snapshot.frame())
            out = Path(directory) / "roundtrip.alab"
            save_project(out, data)
            reopened = load_project(out)
            self.assertEqual(reopened["Raw"].analysis_sources, raw.analysis_sources)
            graph = validate_analysis_links(reopened)
            self.assertEqual(graph.affected([parent]), [parent, child])

            def compute():
                source = reopened["Raw"]
                recipes = dict(zip((parent, child), source.analyses, strict=True))
                values = evaluate_graph(graph, graph.order, {parent: source.frame()}, {},
                                        lambda identifier, frame: analyse(recipes[identifier][0], frame, recipes[identifier][1]))
                self.assertIsNone(values[child].error)
                return values[child].result.tables["Explained variance"].iloc[0]["Eigenvalue"]

            first = compute()
            reopened["Raw"].raw.iat[0, 0] = 20.0
            self.assertNotEqual(compute(), first)

    def test_clustered_view_with_different_row_order_stays_a_pca_snapshot(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "reordered.prismt"
            write_project(archive, clustered=True, reorder_rows=True)
            data = {title: Dataset(frame) for title, frame in load_tables(archive, restore_prism=True).items()}
            self.assertEqual([method for method, _ in data["Raw"].analyses], [SELECTION])
            snapshot = data["Prism result · Saved assignments · Clustered data"]
            self.assertEqual(snapshot.analyses[0][0], METHOD)
            self.assertFalse(snapshot.analysis_sources)

    def test_primary_input_resolves_columns_by_identity_and_keeps_options(self):
        recipe = restore_recipe(*fixture())
        self.assertIsNotNone(recipe)
        uid, method, options = recipe
        self.assertEqual((uid, method), ("source", METHOD))
        self.assertEqual(options["Variables"], ["Signal", "Signal (2)", "Baseline"])
        self.assertEqual(options["Color groups by"], "Cohort")
        self.assertEqual(options["Graph display"], "Scores")
        self.assertEqual(options["Selection"], "Parallel analysis")
        self.assertEqual(options["Parallel seed"], 2718)
        self.assertEqual(options["Parallel simulations"], 120)
        self.assertEqual(options["Parallel percentile (%)"], 95.0)
        self.assertTrue(options["Report transformed data"])
        self.assertTrue(options["Variable contributions"])
        self.assertTrue(options["Report variable matrix"])
        self.assertFalse(options["Observation contributions"])

    def test_saved_result_input_roundtrips_and_recalculates_after_edit(self):
        name = SOURCE_NAME
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pca.prism"
            write_project(path)
            data = {title: Dataset(frame) for title, frame in load_tables(path, restore_prism=True).items()}
            self.assertFalse(data["Raw"].analyses)
            self.assertEqual(data[name].analyses[0][0], METHOD)
            self.assertEqual(data[name].table_format, "Prism result snapshot")
            out = Path(directory) / "roundtrip.alab"
            save_project(out, data)
            restored = load_project(out)[name]
            self.assertEqual(restored.analyses, data[name].analyses)
            method, options = restored.analyses[0]
            before = analyse(method, restored.frame(mask_excluded=True), options)
            self.assertEqual(len(before.tables["PC graph coordinates"]), 8)
            self.assertEqual(set(before.tables["PC graph coordinates"]["Color group"]), {"First", "Second"})
            self.assertEqual(before.tables["PCA selection settings"].iloc[0]["Seed"], 2718)
            restored.raw.iloc[0, 0] = 3.0
            after = analyse(method, restored.frame(mask_excluded=True), options)
            self.assertNotEqual(before.tables["Explained variance"].iloc[0]["Eigenvalue"],
                                after.tables["Explained variance"].iloc[0]["Eigenvalue"])

    def test_unsupported_settings_keep_the_archive_without_native_recipe(self):
        cases = (
            ("calc", "transform", "UNRECOGNIZED"),
            ("calc", "parallelAnalysis", {"percentileLevel": 95., "simulationCount": 120}),
            ("calc", "regression", {"run": True}),
            ("graph", "loadingPlot", True),
            ("report", "transformedData", "true"),
        )
        for section, field, value in cases:
            with self.subTest(section=section, field=field):
                sheet, parameters, sources = fixture()
                params = deepcopy(parameters)
                params["content"][section][field] = value
                self.assertIsNone(restore_recipe(sheet, params, sources))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cached-view.prism"
            write_project(path, cached_format="view")
            data = load_tables(path, restore_prism=True)
            archived = data[SOURCE_NAME]
            self.assertNotIn("prism_recipes", archived.attrs)
            self.assertEqual(len(archived), 8)
