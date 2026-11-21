"""Editing an earlier calculated column may introduce a later dependency."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analisi.analysis_templates import instantiate_template, read_template, write_template
from analisi.data import Dataset, load_project, save_project


class FormulaDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.data = Dataset(pd.DataFrame({"Mass": pd.array([1., 2., 4.], dtype="Float64")}))
        self.data.set_formula("Output", "Mass + 1")
        self.data.set_formula("Scaled", "Mass * 3")
        self.data.set_formula("Offset dose", "Scaled + 1")

    def test_later_dependency_keeps_visible_order_and_propagates_edits_and_exclusions(self):
        data = self.data
        data.set_formula("Output", 'COL("Offset dose") * 2')
        frame = data.frame()
        self.assertEqual(list(frame), ["Mass", "Output", "Scaled", "Offset dose"])
        self.assertEqual(frame["Output"].tolist(), [8., 14., 26.])
        data.raw.iat[0, 0] = 3.
        data.excluded.add((1, 0))
        frame = data.frame()
        self.assertEqual(frame.iat[0, 1], 20.)
        self.assertEqual(frame.iat[1, 0], 2.)
        self.assertTrue(frame.iloc[1, 1:].isna().all())
        self.assertEqual(list(data.formulas), list(frame)[1:])

    def test_cycle_rejects_entire_edit(self):
        data = self.data
        data.set_formula("Output", 'COL("Offset dose") * 2')
        previous = data.formulas.copy()
        for name in ("Output", "Scaled"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                data.set_formula(name, "Output + 1")
        self.assertEqual(previous, data.formulas)
        self.assertEqual(data.frame()["Output"].tolist(), [8., 14., 26.])

    def test_alab_and_template_preserve_results_and_column_order(self):
        data = self.data
        data.set_formula("Output", 'COL("Offset dose") * 2')
        with TemporaryDirectory() as folder:
            project = Path(folder) / "formula.alab"
            save_project(project, {"Study": data})
            # A reader that evaluates stored expressions in sequence still works.
            legacy = Dataset(data.raw.copy())
            for name, expression in json.loads(project.read_text())["tables"][0]["formulas"]:
                legacy.set_formula(name, expression)
                self.assertIn(name, legacy.frame())
            reopened = load_project(project)["Study"]
            pd.testing.assert_frame_equal(data.frame(), reopened.frame())
            self.assertEqual(list(reopened.formulas), list(data.formulas))
            path = Path(folder) / "formula.tramatpl"
            write_template(path, {"Study": reopened})
            mapped = instantiate_template(read_template(path), {"New": pd.DataFrame({"Dose": [3., 8.]})},
                                          {"Study": ("New", {"Mass": "Dose"})})
            sheet = mapped[0]["Study"]
            self.assertEqual(sheet.frame()["Output"].tolist(), [20., 50.])
            self.assertEqual(list(sheet.formulas), list(data.formulas))

    def test_invalid_display_order_is_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.alab"
            save_project(path, {"Study": self.data})
            document = json.loads(path.read_text())
            for order in (["Output", "Output", "Scaled"], ["Mass", "Scaled", "Output"], {"Scaled": 0}):
                with self.subTest(order=order):
                    document["tables"][0]["formula_order"] = order
                    path.write_text(json.dumps(document))
                    with self.assertRaisesRegex(ValueError, "formula column order"):
                        load_project(path)
