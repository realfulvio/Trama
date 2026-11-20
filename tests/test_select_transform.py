"""Test multiple-variable filtering and calculated output from source data."""
import unittest

import numpy as np
import pandas as pd

from analisi.select_transform import select_transform


class SelectTransformTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame({
            "ID": ["01", "02", "03", "04", "05", "06", "07"],
            "Arm": ["C", "T", "T", None, "C", "C", " "],
            "Age": pd.Series([22, 51, 44, 70, 40, 53, None], dtype="Int64"),
            "BMI": [32., 25., 28.5, 29., 26., 24.9, 30.],
            "Glucose": [95., 126., 100., 113., 120., 101., 132.],
        })

    def output(self, **options):
        return select_transform(self.data, options).tables["Selected data"]

    def test_project_candidate_keeps_a_replayable_random_transform(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from trama_qt.project import Project, compute
        from analisi.select_transform import CALCULATED, SELECT_TRANSFORM

        project = Project()
        title, = project.add_tables({"Trial": self.data})
        options = {"Variables": ["ID"], CALCULATED: [{"name": "Noise", "expression": "GAUSS(0, 1)"}]}
        run = project.candidate(title, SELECT_TRANSFORM, options)
        self.assertTrue(run.options[CALCULATED][0]["expression"].startswith("=WITH_SEED("))
        self.assertEqual(options[CALCULATED][0]["expression"], "GAUSS(0, 1)")
        first = compute(run, project.input_frame(run))
        project.add_result(run, first)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "seeded.alab"
            project.save(path)
            reopened = Project()
            reopened.load(path)
        next_run, = reopened.runs
        self.assertEqual(run.options, next_run.options)
        after = compute(next_run, reopened.input_frame(next_run))
        np.testing.assert_array_equal(first.tables["Selected data"]["Noise"], after.tables["Selected data"]["Noise"])

    def test_multiple_conditions_and_formulas_keep_source_order(self):
        before = self.data.copy()
        result = self.output(
            Variables=["ID", "BMI"],
            **{"First row": "2", "Last row": "6",
               "Row filters": [
                   {"column": "Age", "operator": ">", "target": "Number", "value": "40"},
                   {"column": "BMI", "operator": ">=", "target": "Number", "value": "25,0"},
                   {"column": "Arm", "operator": "=", "target": "Text", "value": "T"},
               ],
               "Calculated variables": [
                   {"name": "Status", "expression": 'IF(Glucose>=126,"High",IF(Glucose<=100,"Low","Middle"))'},
                   {"name": "Centered BMI", "expression": "BMI-MEAN(BMI)"},
                   {"name": "Offset", "expression": 'COL("Centered BMI")+1'},
               ]},
        )
        self.assertEqual(list(result.columns), ["ID", "BMI", "Status", "Centered BMI", "Offset"])
        self.assertEqual(result["ID"].tolist(), ["02", "03"])
        self.assertEqual(result["Status"].tolist(), ["High", "Low"])
        np.testing.assert_allclose(result["Offset"], [-.75, 2.75])
        self.assertEqual(result.attrs["table_format"], "multivariable")
        pd.testing.assert_frame_equal(self.data, before)

    def test_column_and_missing_comparisons(self):
        rules = [
            {"column": "Arm", "operator": "Is not missing"},
            {"column": "Age", "operator": ">", "target": "Column", "value": "BMI"},
        ]
        self.assertEqual(self.output(**{"Row filters": rules})["ID"].tolist(), ["02", "03", "05", "06"])
        rules = [{"column": "Arm", "operator": "Is missing"}]
        self.assertEqual(self.output(**{"Row filters": rules})["ID"].tolist(), ["04", "07"])
        rules = [{"column": "Arm", "operator": "!=", "target": "Text", "value": "T"}]
        self.assertEqual(self.output(**{"Row filters": rules})["ID"].tolist(), ["01", "05", "06"])

    def test_integer_filter_uses_exact_comparisons(self):
        self.data = pd.DataFrame({"n": pd.Series([2**53, 2**53 + 1, 2**53 + 2, None], dtype="Int64"),
                                  "as float": [float(2**53), float(2**53), float(2**53 + 2), np.nan]})
        literal = [{"column": "n", "operator": "=", "target": "Number", "value": str(2**53 + 1)}]
        self.assertEqual(self.output(**{"Row filters": literal})["n"].tolist(), [2**53 + 1])
        compare = [{"column": "n", "operator": ">", "target": "Column", "value": "as float"}]
        self.assertEqual(self.output(**{"Row filters": compare})["n"].tolist(), [2**53 + 1])

    def test_empty_and_formula_only_outputs(self):
        rule = {"column": "Age", "operator": ">", "target": "Number", "value": "110"}
        output = self.output(Variables=[], **{"Row filters": [rule], "Calculated variables": [
            {"name": "Scaled", "expression": "Age / 10"},
        ]})
        self.assertEqual(output.shape, (0, 1))
        self.assertEqual(list(output.columns), ["Scaled"])
        self.assertEqual(self.output(**{"First row": "6", "Last row": "20"})["ID"].tolist(), ["06", "07"])

    def test_invalid_options_leave_input_unchanged(self):
        before = self.data.copy()
        for options, message in [
            ({"First row": "0"}, "First row"),
            ({"First row": "6", "Last row": "3"}, "Last row"),
            ({"Variables": []}, "Choose at least"),
            ({"Variables": ["Age", "Age"]}, "distinct"),
            ({"Calculated variables": [{"name": "Age", "expression": "Age*2"}]}, "already exists"),
            ({"Calculated variables": [{"name": "Danger", "expression": '__import__("os")'}]}, "Danger"),
            ({"Row filters": [{"column": "Age", "operator": ">", "target": "Number", "value": "NaN"}]}, "finite number"),
            ({"Row filters": [{"column": "Age", "operator": "=", "target": "Column", "value": "Arm"}]}, "same type"),
        ]:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    self.output(**options)
        pd.testing.assert_frame_equal(self.data, before)
