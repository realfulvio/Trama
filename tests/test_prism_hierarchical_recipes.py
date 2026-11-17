"""Synthetic compatibility contracts for editable hierarchical ZIP imports."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_recipes import restore_recipe
from analisi.workbench import analyse
from tests.test_prism_recipes import source, var


def fixture():
    frame = pd.DataFrame({"Label": ["a", "b", "c", "d"], "A": [1., 4., 9., 2.],
                          "B": [3., 6., 4., 5.], "C": [2., 5., 5., 8.]})
    content = {
        "data": {"inputType": "ROWS_COLUMNS", "variables": [var(c) for c in "ABC"],
                 "label": {"type": "VARIABLE", "variable": var("label")}},
        "calc": {"columnTransform": "NONE", "rowTransform": "CENTER",
                 "distance": {"type": "EUCLIDIAN", "value": 2.0}, "linkage": "COMPLETE"},
        "defineClusters": {"rows": {"method": "NONE", "clusterCount": 2, "cutoffHeight": 1.},
                           "columns": {"method": "NUMBER_OF_CLUSTERS", "clusterCount": 2,
                                       "cutoffHeight": 1.}},
        "report": {"standardizedData": True, "distanceMatrix": True, "mergeMap": False,
                   "copheneticDistanceMatrix": False, "copheneticCorrelation": False,
                   "outputFullMatrix": False},
        "graph": {"plots": ["HEATMAP"]},
    }
    return source("HIERARCHICAL_CLUSTERING", "0.0.0", content, frame,
                  {**{c: [c] for c in "ABC"}, "label": ["Label"]})


def write_project(path):
    """Write only synthetic content, including an independently saved result view."""
    sheet, parameters, sources = fixture()
    frame = sources["source"]
    with ZipFile(path, "w") as archive:
        def write(name, obj):
            archive.writestr(name, json.dumps(obj))
        write("document.json", {"sheets": {"data": ["source"], "analyses": ["tree"]}})
        write("data/sheets/source/sheet.json", {"title": "Expression", "table": {
            "uid": "matrix", "format": "multivariable", "dataFormat": "y_single",
            "dataSets": ["label", "A", "B", "C"]}})
        for uid, name in [("label", "Label"), *[(c, c) for c in "ABC"]]:
            write(f"data/sets/{uid}.json", {"title": name})
        archive.writestr("data/tables/matrix/data.csv", frame.to_csv(index=False, header=False))
        write("analyses/tree/sheet.json", {**sheet, "title": "Imported clustering",
              "resultSheets": [{"uid": "cached"}]})
        write("analyses/tree/parameters.json", parameters)
        write("analyses/tree/result_sheets/cached.json", {"name": "Original values", "dataSheet": "cached-sheet",
                                                        "isVisible": True})
        write("data/sheets/cached-sheet/sheet.json", {"table": {
            "uid": "cached-table", "format": "view", "dataFormat": "y_single", "dataSets": ["cached-y"]}})
        write("data/sets/cached-y.json", {"title": "Archived"})
        archive.writestr("data/tables/cached-table/data.csv", "101\n202\n")


class HierarchicalRecipeTests(unittest.TestCase):
    def converted(self, args=None):
        args = fixture() if args is None else args
        found = restore_recipe(*args)
        self.assertIsNotNone(found, "The supported hierarchical recipe must be editable.")
        _, method, options = found
        return args[2]["source"], method, options

    def test_dual_axis_centering_reports_and_exact_small_tree(self):
        frame, method, options = self.converted()
        self.assertEqual(options["Direction"], "Rows and columns")
        self.assertEqual(options["Scale rows"], "Center")
        self.assertEqual(options["Scale columns"], "None")
        self.assertEqual(options["Row cut"], "No cut")
        self.assertEqual(options["Column cut"], "Count")
        self.assertEqual(options["Column clusters"], 2)
        self.assertEqual(options["Graph output"], "Heat map")
        self.assertEqual(options["Matrix format"], "Lower triangle")
        result = analyse(method, frame, options)
        expected = [[-1, 1, 0], [-1, 1, 0], [3, -2, -1], [-3, 0, 3]]
        np.testing.assert_allclose(result.tables["Scaled data"], expected)
        self.assertNotIn("Row Assignments", result.tables)
        self.assertEqual(result.tables["Column Assignments"]["Cluster"].tolist(), [1, 2, 2])
        np.testing.assert_allclose(result.tables["Row Merges"]["Distance"], [0, np.sqrt(14), np.sqrt(56)])
        np.testing.assert_allclose(result.tables["Column Merges"]["Distance"], [np.sqrt(12), np.sqrt(54)])
        distance = result.tables["Column Distance matrix"]
        np.testing.assert_allclose([distance.iat[1, 0], distance.iat[2, 0], distance.iat[2, 1]],
                                   np.sqrt([42, 54, 12]))
        self.assertTrue(np.isnan(distance.iat[0, 1]))
        self.assertEqual(len(result.figure.axes), 4)

    def test_column_only_and_no_cut_ignore_inactive_count(self):
        args = fixture()
        content = args[1]["content"]
        content["data"]["inputType"] = "COLUMNS"
        content["defineClusters"]["rows"] = {"method": "NONE", "clusterCount": -10}
        content["defineClusters"]["columns"] = {"method": "NONE", "clusterCount": "unused"}
        frame, method, options = self.converted(args)
        self.assertEqual(options["Direction"], "Columns")
        result = analyse(method, frame, options)
        self.assertNotIn("Assignments", result.tables)
        self.assertEqual(len(result.tables["Merges"]), 2)

    def test_saved_merge_map_restores_named_children_for_both_directions(self):
        args = fixture()
        args[1]["content"]["report"]["mergeMap"] = True
        frame, method, options = self.converted(args)
        result = analyse(method, frame, options)
        self.assertTrue(options["Merge map"])
        rows = result.tables["Row Merge map"]
        self.assertEqual(list(rows.columns), ["Merge order", "Node 1", "Node 2", "Cophenetic distance"])
        self.assertEqual(rows["Merge order"].tolist(), [1, 2, 3])
        self.assertEqual(rows[["Node 1", "Node 2"]].values.tolist(),
                         [["a", "b"], ["Cluster 1", "d"], ["c", "Cluster 2"]])
        np.testing.assert_allclose(rows["Cophenetic distance"], np.sqrt([0, 14, 56]))

        columns = result.tables["Column Merge map"]
        self.assertEqual(columns[["Node 1", "Node 2"]].values.tolist(), [["B", "C"], ["A", "Cluster 1"]])
        np.testing.assert_allclose(columns["Cophenetic distance"], np.sqrt([12, 54]))
        legacy = analyse(method, frame, {k: v for k, v in options.items() if k != "Merge map"})
        self.assertNotIn("Row Merge map", legacy.tables)
        pd.testing.assert_frame_equal(legacy.tables["Row Merges"], result.tables["Row Merges"])

    def test_source_exclusion_recalculates_merge_map_with_remaining_labels(self):
        args = fixture()
        args[1]["content"]["report"]["mergeMap"] = True
        frame, method, options = self.converted(args)
        frame.loc[1, "A"] = np.nan
        rows = analyse(method, frame, options).tables["Row Merge map"]
        self.assertEqual(rows["Merge order"].tolist(), [1, 2])
        self.assertEqual(rows[["Node 1", "Node 2"]].values.tolist(),
                         [["a", "d"], ["c", "Cluster 1"]])

    def test_row_only_reports_and_legacy_dendrogram_priority(self):
        args = fixture()
        content = args[1]["content"]
        content["data"]["inputType"] = "ROWS"
        content["calc"]["rowTransform"] = "NONE"
        content["calc"]["columnTransform"] = "STANDARDIZE"
        content["defineClusters"]["rows"] = {"method": "NUMBER_OF_CLUSTERS", "clusterCount": 3}
        content["defineClusters"]["columns"] = {"method": "NONE"}
        content["report"].update({"standardizedData": False, "copheneticDistanceMatrix": True,
                                  "copheneticCorrelation": True, "outputFullMatrix": True})
        content["graph"]["plots"] = ["DENDROGRAM", "HEATMAP", "ELBOW_PLOT"]
        frame, method, options = self.converted(args)
        self.assertTrue(options["Standardize"])
        self.assertEqual(options["Graph output"], "Dendrogram")
        result = analyse(method, frame, options)
        self.assertTrue(options["Elbow data"])
        self.assertEqual(result.tables["Elbow data"]["Number of clusters"].tolist(), [1, 2, 3])
        self.assertNotIn("Scaled data", result.tables)
        self.assertIn("Cophenetic correlation", result.tables)
        self.assertFalse(result.tables["Cophenetic distances"].isna().any().any())

    def test_saved_elbow_only_restores_the_plot(self):
        args = fixture()
        args[1]["content"]["graph"]["plots"] = ["ELBOW_PLOT"]
        frame, method, options = self.converted(args)
        self.assertEqual(options["Graph output"], "Elbow plot")
        result = analyse(method, frame, options)
        self.assertEqual(len(result.figure.axes), 2)
        self.assertEqual(result.tables["Row Elbow data"]["Number of clusters"].tolist(), [1, 2, 3])

    def test_missing_rows_keep_uid_roles_and_allow_original_label_column(self):
        args = fixture()
        frame = args[2]["source"]
        frame.loc[1, "B"] = np.nan
        frame.columns = ["Label", "Same", "Same (2)", "C"]
        frame.attrs["prism_columns"].update({"A": ["Same"], "B": ["Same (2)"]})
        frame, method, options = self.converted(args)
        self.assertEqual(options["Variables"], ["Same", "Same (2)", "C"])
        result = analyse(method, frame, options)
        self.assertEqual(result.tables["Scaled data"].index.tolist(), [0, 2, 3])

    def test_unsupported_or_malformed_metadata_keeps_cached_fallback(self):
        paths = [
            (("data", "inputType"), "UNKNOWN"),
            (("calc", "rowTransform"), "LOG"),
            (("calc", "columnTransform"), "LOG"),
            (("calc", "linkage"), "UNRECOGNIZED"),
            (("calc", "distance", "type"), "UNRECOGNIZED"),
            (("defineClusters", "columns", "method"), "UNVERIFIED_CUT"),
            (("defineClusters", "columns", "clusterCount"), True),
            (("defineClusters", "columns", "clusterCount"), 4),
            (("defineClusters", "columns", "clusterCount"), float("nan")),
            (("report", "distanceMatrix"), "false"),
            (("report", "mergeMap"), "false"),
            (("graph", "plots"), ["UNRECOGNIZED"]),
        ]
        for path, value in paths:
            with self.subTest(path=path, value=value):
                args = fixture()
                obj = args[1]["content"]
                for key in path[:-1]:
                    obj = obj[key]
                obj[path[-1]] = value
                self.assertIsNone(restore_recipe(*args))

    def test_restore_edit_and_roundtrip_leave_archived_table_unchanged(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"import.prism"
            write_project(path)
            tables = load_tables(path, restore_prism=True)
            dataset = Dataset(tables["Expression"])
            self.assertEqual(len(dataset.analyses), 1)
            method, options = dataset.analyses[0]
            original_options = deepcopy(options)
            original = analyse(method, dataset.frame(), options).tables["Scaled data"].copy()
            cached_name = next(name for name in tables if name.startswith("Prism result"))
            archived = tables[cached_name].copy(deep=True)
            dataset.raw.loc[0, "A"] = 7
            changed = analyse(method, dataset.frame(), options).tables["Scaled data"]
            self.assertFalse(original.equals(changed))
            dataset.excluded.add((1, 2))
            omitted = analyse(method, dataset.frame(mask_excluded=True), options).tables["Scaled data"]
            self.assertEqual(omitted.index.tolist(), [0, 2, 3])
            saved = Path(directory)/"restored.alab"
            projects = {name: dataset if name == "Expression" else Dataset(table) for name, table in tables.items()}
            save_project(saved, projects)
            reopened = load_project(saved)
            self.assertEqual(reopened["Expression"].analyses[0][1], original_options)
            pd.testing.assert_frame_equal(reopened[cached_name].raw, archived)
            actual = analyse(method, reopened["Expression"].frame(mask_excluded=True), options).tables["Scaled data"]
            pd.testing.assert_frame_equal(actual, omitted)


if __name__ == "__main__":
    unittest.main()
