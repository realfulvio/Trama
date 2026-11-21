import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import warnings
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.workbench import analyse


def write_archive(path, table, sets, text, dimensions=None):
    with ZipFile(path, "w") as archive:
        archive.writestr("document.json", '{"sheets":{"data":["sheet"]}}')
        archive.writestr("data/sheets/sheet/sheet.json", json.dumps({"title": "Experiment", "table": table}))
        for uid, metadata in sets.items():
            archive.writestr(f"data/sets/{uid}.json", json.dumps(metadata))
        archive.writestr("data/tables/table/data.csv", text)
        if dimensions is not None:
            rows, cols = dimensions
            archive.writestr("data/tables/table/content.json", json.dumps(
                {"numberOfRows": rows, "numberOfColumns": cols, "version": 1}))


class PrismImportTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.path = Path(workspace.name)

    def test_zip_pzt_keeps_summary_columns_separate_from_replicates(self):
        source = self.path / "summary.pzt"
        write_archive(source, {"uid": "table", "format": "xy", "xDataSet": "x", "xDataSetFormat": "y_error",
                               "dataFormat": "y_sd_n", "dataSets": ["y"]},
                      {"x": {"title": "Time"}, "y": {"title": "Signal"}}, "1,0.1,3,0.5,4\n", (1, 5))
        frame = load_tables(source)["Experiment"]
        self.assertEqual(list(frame), ["Time", "Time [Error]", "Signal [Mean]", "Signal [SD]", "Signal [N]"])
        self.assertEqual(frame.iloc[0].tolist(), [1, .1, 3, .5, 4])

    def test_native_recipe_recalculates_and_survives_saving_with_forward_references(self):
        source = self.path / "formulas.prism"
        table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["x", "a", "b"]}

        def calculated(title, recipe):
            return {"title": title, "valuesStorageData": {"@class": "TransformDataSource", "transform": recipe}}

        write_archive(source, table, {"x": {"title": "Source dose"}, "a": calculated("Squared dose", "C^2"),
                                      "b": calculated("Offset dose", "A+2")}, "2,,\n5,,\n", (2, 3))
        frame = load_tables(source)["Experiment"]
        self.assertEqual(frame["Squared dose"].tolist(), [16, 49])
        data = Dataset(frame)
        self.assertEqual(list(data.raw), ["Source dose"])
        self.assertEqual(list(data.formulas), ["Squared dose", "Offset dose"])
        self.assertEqual(list(data.frame()), list(frame))
        self.assertEqual(data.frame()["Squared dose"].tolist(), [16, 49])
        data.raw.iat[0, 0] = 8
        native = self.path / "saved.alab"
        save_project(native, {"Experiment": data})
        reopened = load_project(native)["Experiment"]
        self.assertEqual(reopened.frame()["Squared dose"].tolist(), [100, 49])
        self.assertEqual(list(reopened.frame()), list(frame))

    def test_unsupported_or_cyclic_formulas_preserve_cached_cells(self):
        source = self.path / "formulas.prism"
        table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                 "dataSets": ["a", "b", "c", "d", "e"]}
        sets = {"a": {"title": "Value"}}
        for uid, expression in (("b", "C+1"), ("c", "B-1"), ("d", "UNSUPPORTED(A)"), ("e", "D+1")):
            sets[uid] = {"title": uid, "valuesStorageData": {"@class": "TransformDataSource", "transform": expression}}
        write_archive(source, table, sets, "2,4,3,5,6\n", (1, 5))
        frame = load_tables(source)["Experiment"]
        self.assertEqual(frame.iloc[0].tolist(), [2, 4, 3, 5, 6])
        self.assertFalse(Dataset(frame).formulas)
        self.assertIn("b, c, d, e", frame.attrs["import_warnings"][0])

    def test_zip_recalculates_logarithms_and_angle_functions(self):
        source = self.path / "functions.prismt"
        formulas = {"natural": "ln(A)", "decimal": "LOG(A)", "binary": "LOG2(A)",
                    "cosine": "COS(RAD(B))", "quadrant": "DEG(ARCTAN2(B, A))"}
        sets = {"a": {"title": "Signal"}, "b": {"title": "Angle"}}
        sets.update({name: {"title": name, "valuesStorageData": {"@class": "TransformDataSource",
                                                                   "transform": expression}}
                     for name, expression in formulas.items()})
        write_archive(source, {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                               "dataSets": list(sets)}, sets,
                      "1,0,999,999,999,999,999\n8,60,999,999,999,999,999\n-1,1,999,999,999,999,999\n", (3, 7))
        data = Dataset(load_tables(source)["Experiment"])
        self.assertEqual(list(data.raw), ["Signal", "Angle"])
        self.assertEqual(set(data.formulas), set(formulas))
        rows = data.frame()
        np.testing.assert_allclose(rows["natural"], [0, np.log(8), np.nan])
        np.testing.assert_allclose(rows["decimal"], [0, np.log10(8), np.nan])
        np.testing.assert_allclose(rows["binary"], [0, 3, np.nan])
        np.testing.assert_allclose(rows["cosine"].iloc[:2], [1, .5])
        self.assertAlmostEqual(rows["quadrant"].iloc[2], 135)

        data.raw.loc[0, ["Signal", "Angle"]] = [100, 180]
        native = self.path / "saved.alab"
        save_project(native, {"Experiment": data})
        restored = load_project(native)["Experiment"]
        self.assertEqual(restored.formulas, data.formulas)
        self.assertEqual(restored.frame()["decimal"].iloc[0], 2)
        self.assertEqual(restored.frame()["cosine"].iloc[0], -1)

    def test_zip_restores_center_standardization_and_rank_as_formulas(self):
        source = self.path / "statistics.prismt"
        sets = {"a": {"title": "Signal"}}
        for column, expression in (("Centered", "center(A)"), ("Standardized", "STANDARDIZE(A)"),
                                   ("Ranked", "RANK(A)"), ("Z", "ZSCORE(A)")):
            sets[column] = {"title": column, "valuesStorageData": {"@class": "TransformDataSource",
                                                                  "transform": expression}}
        write_archive(source, {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                               "dataSets": list(sets)}, sets,
                      "3,99,99,99,99\n1,99,99,99,99\n3,99,99,99,99\n7,99,99,99,99\n", (4, 5))
        data = Dataset(load_tables(source)["Experiment"])
        self.assertEqual(set(data.formulas), {"Centered", "Standardized", "Ranked", "Z"})
        np.testing.assert_allclose(data.frame()["Ranked"], [2.5, 1, 2.5, 4])
        data.raw.loc[0, "Signal"] = 12
        project = self.path / "statistics.alab"
        save_project(project, {"Experiment": data})
        reopened = load_project(project)["Experiment"]
        np.testing.assert_allclose(reopened.frame()["Ranked"], [4, 1, 2, 3])
        np.testing.assert_allclose(reopened.frame()["Centered"], [6.25, -4.75, -2.75, 1.25])
        np.testing.assert_allclose(reopened.frame()["Standardized"], reopened.frame()["Z"])

    def test_zip_restores_scalar_transforms_with_domains(self):
        source = self.path / "transforms.prismt"
        sets = {"a": {"title": "Fraction"}}
        for name, expression in (("Rounded", "CEIL(A)"), ("Hyperbolic", "ARCTANH(A)"), ("Odds", "LOGIT(A)")):
            sets[name] = {"title": name, "valuesStorageData": {"@class": "TransformDataSource",
                                                             "transform": expression}}
        write_archive(source, {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                               "dataSets": list(sets)}, sets,
                      ".25,99,99,99\n.5,99,99,99\n1,99,99,99\n-.25,99,99,99\n", (4, 4))
        data = Dataset(load_tables(source)["Experiment"])
        self.assertEqual(set(data.formulas), {"Rounded", "Hyperbolic", "Odds"})
        np.testing.assert_allclose(data.frame()["Rounded"], [1, 1, 1, 0])
        np.testing.assert_allclose(data.frame()["Odds"], [-np.log(3), 0, np.nan, np.nan])
        data.raw.loc[2, "Fraction"] = .75
        self.assertAlmostEqual(data.frame()["Odds"].iloc[2], np.log(3))

    def test_zip_restores_special_functions_and_recomputes_after_an_edit(self):
        path = self.path / "special.prismt"
        table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                 "dataSets": ["a", "b", "c"]}
        sets = {"a": {"title": "Dose"}}
        for uid, title, expression in (("b", "Gamma", "GAMMA(A)"), ("c", "Tail", "IGAMMAC(1,A)")):
            sets[uid] = {"title": title, "valuesStorageData": {
                "@class": "TransformDataSource", "transform": expression}}
        write_archive(path, table, sets, "1,0,0\n4,0,0\n-1,0,0\n", (3, 3))
        data = Dataset(load_tables(path)["Experiment"])
        self.assertEqual(set(data.formulas), {"Gamma", "Tail"})
        np.testing.assert_allclose(data.frame()["Gamma"], [1, 6, np.nan])
        data.raw.at[1, "Dose"] = 5
        destination = self.path / "native.alab"
        save_project(destination, {"Experiment": data})
        reopened = load_project(destination)["Experiment"].frame()
        np.testing.assert_allclose(reopened["Gamma"], [1, 24, np.nan])
        np.testing.assert_allclose(reopened["Tail"], [np.exp(-1), np.exp(-5), np.nan])

    def test_zip_restores_distribution_functions_with_optional_arguments(self):
        path = self.path / "probability.prismt"
        table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                 "dataSets": ["a", "b", "c"]}
        sets = {"a": {"title": "Dose"}}
        for uid, title, expression in (("b", "Cumulative", "NORMDIST(A)"),
                                       ("c", "Upper", 'ZDIST(A,"right")')):
            sets[uid] = {"title": title, "valuesStorageData": {
                "@class": "TransformDataSource", "transform": expression}}
        write_archive(path, table, sets, "0,9,9\n2,9,9\n", (2, 3))
        data = Dataset(load_tables(path)["Experiment"])
        self.assertEqual(set(data.formulas), {"Cumulative", "Upper"})
        np.testing.assert_allclose(data.frame()[["Cumulative", "Upper"]].sum(axis=1), [1, 1])
        data.raw.at[1, "Dose"] = 0
        np.testing.assert_allclose(data.frame()["Upper"], [.5, .5])

    def test_zip_arithmetic_formulas_stay_live_after_edits_and_reopening(self):
        source = self.path / "arithmetic.prismt"
        sets = {"a": {"title": "Source dose"}, "b": {"title": "Replicate"}}
        for name, expression in (("rounded", "ROUND(A,1)"), ("remainder", "B mod 3"),
                                 ("factorial", "FACT(B)"), ("row_total", "SUM(A,B,1)")):
            sets[name] = {"title": name, "valuesStorageData": {"@class": "TransformDataSource",
                                                              "transform": expression}}
        write_archive(source, {"uid": "table", "format": "multivariable", "dataFormat": "y_single",
                               "dataSets": list(sets)}, sets,
                      "2.25,4,99,99,99,99\n-2.25,5,99,99,99,99\n", (2, 6))
        data = Dataset(load_tables(source)["Experiment"])
        self.assertEqual(set(data.formulas), set(sets) - {"a", "b"})
        np.testing.assert_allclose(data.frame()["rounded"], [2.3, -2.3])
        np.testing.assert_allclose(data.frame()["remainder"], [1, 2])

        data.raw.at[0, "Replicate"] = 6
        project = self.path / "arithmetic.alab"
        save_project(project, {"Experiment": data})
        reopened = load_project(project)["Experiment"]
        self.assertEqual(reopened.formulas, data.formulas)
        np.testing.assert_allclose(reopened.frame()["factorial"], [720, 120])
        np.testing.assert_allclose(reopened.frame()["row_total"], [9.25, 3.75])

    def test_zip_restores_presence_formula_for_mixed_cells(self):
        path = self.path / "presence.prismt"
        table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["a", "b"]}
        sets = {"a": {"title": "Label"}, "b": {"title": "Available", "valuesStorageData": {
            "@class": "TransformDataSource", "transform": "IS_DEFINED(A)"}}}
        write_archive(path, table, sets, "Alpha,0\n,0\n0,0\n", (3, 2))
        data = Dataset(load_tables(path)["Experiment"])
        self.assertIn("Available", data.formulas)
        self.assertEqual(data.frame()["Available"].tolist(), [True, False, True])
        data.raw.at[1, "Label"] = "Beta"
        self.assertTrue(data.frame().at[1, "Available"])

    def test_legacy_wrapper_uses_sheet_sequence_dates_and_upper_lower_endpoints(self):
        source = self.path / "example.xml"
        source.write_text(
            '<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
            '<GraphPadPrismFile xmlns="http://graphpad.com/prism/Prism.htm"><TableSequence><Ref ID="B"/>'
            '<Ref ID="A"/></TableSequence><Table ID="A"><YColumn><Subcolumn><d>8</d></Subcolumn></YColumn></Table>'
            '<Table ID="B" XFormat="date" YFormat="upper-lower-limits" TableType="XY"><Title>Dates</Title>'
            '<XColumn><Subcolumn><d>12</d></Subcolumn></XColumn><XAdvancedColumn><Subcolumn>'
            '<d>2-Jan-2022</d></Subcolumn></XAdvancedColumn><YColumn><Title>Signal</Title>'
            '<Subcolumn><d Excluded="1">5</d></Subcolumn><Subcolumn><d>7</d></Subcolumn>'
            '<Subcolumn><d>2</d></Subcolumn></YColumn></Table></GraphPadPrismFile>'
            '<xsl:template match="/"><xsl:value-of select="document(\'file:///no-read\')"/></xsl:template>'
            '</xsl:stylesheet>', encoding="utf-8")
        tables = load_tables(source)
        self.assertEqual(list(tables), ["Dates", "A"])
        frame = tables["Dates"]
        self.assertEqual(list(frame), ["X", "X [Date]", "Signal [Center]", "Signal [Upper]", "Signal [Lower]"])
        self.assertEqual(frame.iloc[0].tolist(), [12, "2-Jan-2022", 5, 7, 2])
        self.assertTrue(pd.isna(Dataset(frame).frame(mask_excluded=True)["Signal [Center]"].iloc[0]))
        graph = analyse("XY error bars", frame, {"X": "X", "Y": "Signal [Center]",
                        "Y lower error": "Signal [Lower]", "Y upper error": "Signal [Upper]",
                        "Y error values": "Endpoints"})
        _, _, whiskers = graph.figure.axes[0].containers[0].lines
        self.assertEqual(whiskers[0].get_segments()[0].tolist(), [[12, 2], [12, 7]])

    def test_inconsistent_or_duplicate_zip_entries_are_rejected(self):
        source = self.path / "broken.prism"
        table = {"uid": "table", "format": "column", "dataFormat": "y_single", "dataSets": ["y"]}
        write_archive(source, table, {"y": {"title": "Signal"}}, "3\n", (2, 1))
        with self.assertRaisesRegex(ValueError, "row count"):
            load_tables(source)
        with warnings.catch_warnings(), ZipFile(source, "a") as archive:
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("document.json", '{}')
        with self.assertRaisesRegex(ValueError, "duplicate archive entries"):
            load_tables(source)

    def test_a_data_set_cannot_be_both_x_and_y(self):
        source = self.path / "ambiguous.prism"
        write_archive(source, {"uid": "table", "format": "xy", "dataFormat": "y_single",
                               "xDataSet": "same", "dataSets": ["same"]},
                      {"same": {"title": "Value"}}, "10,100\n20,150\n", (2, 2))
        with self.assertRaisesRegex(ValueError, "multiple column roles"):
            load_tables(source, restore_prism=True)

    def test_proprietary_binary_fails_with_actionable_conversion(self):
        source = self.path / "old.pzf"
        source.write_bytes(b"PCFFGRAF" + b"\0" * 32)
        with self.assertRaisesRegex(ValueError, r"binary project.*\.prism or \.pzfx"):
            load_tables(source)
