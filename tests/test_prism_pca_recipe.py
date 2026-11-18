"""Compatibility checks for saved, recalculable PCA recipes in ZIP projects."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_recipes import restore_recipe
from analisi.prism_pca_smoke import INPUT, SOURCE_NAME, sample, write_project
from analisi.workbench import analyse
from tests.test_prism_recipes import source


METHOD = "Principal component analysis"
def fixture():
    frame, content = sample()
    return source("PCA", "0.0.0", content, frame, INPUT)


class PrismPCARecipeTests(unittest.TestCase):
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
