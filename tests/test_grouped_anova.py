from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from analisi import grouped_anova as grouped
from analisi.grouped_anova_smoke import archived_chain
from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.field_error import FieldError
from analisi.stats import factorial_anova
from analisi.workbench import analyse


def example():
    worksheet = pd.DataFrame({
        "Labels": ["Warm", "Cold", "Empty"],
        "Pump [1]": [8., 4., np.nan],
        "Pump [2]": [10., 6., np.nan],
        "Other [1]": [4., 3., np.nan],
        "Other [2]": [6., 4., np.nan],
    })
    options = {grouped.ROWS: "Labels", grouped.VALUES: list(worksheet)[1:],
               grouped.ROW_NAME: "Temperature", grouped.COLUMN_NAME: "Treatment"}
    return worksheet, options


class GroupedAnovaTests(unittest.TestCase):
    def test_native_dispatch_matches_explicit_observations(self):
        worksheet, options = example()
        long = pd.DataFrame({
            "Duration": [8., 10., 4., 6., 4., 6., 3., 4.],
            "Temperature": ["Warm", "Warm", "Cold", "Cold"] * 2,
            "Treatment": ["Pump"] * 4 + ["Other"] * 4,
        })
        factors = ["Temperature", "Treatment"]
        for term, order in ((False, 1), (True, 2)):
            with self.subTest(interaction=term):
                actual = analyse(grouped.METHOD, worksheet, {**options, grouped.INTERACTION: term})
                expected = factorial_anova(long, "Duration", factors, order)
                pd.testing.assert_frame_equal(actual.tables["ANOVA (type III)"], expected)

    def test_invalid_row_label_and_missing_replicates(self):
        worksheet, options = example()
        worksheet.loc[1, "Labels"] = ""
        with self.assertRaises(FieldError) as error:
            grouped.grouped_inputs(worksheet, options)
        self.assertEqual(error.exception.field, grouped.ROWS)
        worksheet.loc[1, "Labels"] = "Cold"
        worksheet.loc[1, "Other [2]"] = np.nan
        data, response, factors = grouped.grouped_inputs(worksheet, options)
        self.assertEqual(len(data), 7)
        self.assertEqual(factors, ["Temperature", "Treatment"])
        self.assertTrue(data[response].notna().all())

    def test_explicit_worksheet_series_define_column_groups(self):
        worksheet, options = example()
        worksheet.columns = ["Labels", "a", "b", "c", "d"]
        worksheet.attrs["worksheet_roles"] = {"x": [], "y": [["a", "b"], ["c", "d"]]}
        data, _, factors = grouped.grouped_inputs(worksheet, {**options, grouped.VALUES: list(worksheet)[1:]})
        self.assertEqual(data[factors[-1]].tolist(), ["a"] * 4 + ["c"] * 4)



class GroupedAnovaImportTests(unittest.TestCase):
    def test_result_source_survives_project_roundtrip(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "synthetic.prismt"
            dest = Path(temp) / "saved.alab"
            archived_chain(source)
            project = {name: Dataset(frame) for name, frame in load_tables(source, restore_prism=True).items()}
            save_project(dest, project)
            loaded = load_project(dest)
        worksheet = loaded["Signals"]
        self.assertEqual([method for method, _ in worksheet.analyses], ["Extract and rearrange", grouped.METHOD])
        self.assertEqual(worksheet.analysis_sources[1].analysis_id, worksheet.analysis_ids[0])
        self.assertEqual(worksheet.analysis_sources[1].table, "Rearranged data")
        self.assertEqual(len(loaded), 2)
        self.assertFalse(loaded["Prism result · extract · Results"].analyses)

    def test_subset_of_saved_column_groups_uses_snapshot(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "synthetic.prismt"
            archived_chain(source, valid=False)
            project = load_tables(source, restore_prism=True)
        worksheet = Dataset(project["Signals"])
        self.assertEqual([method for method, _ in worksheet.analyses], ["Extract and rearrange"])
        self.assertIn("Prism result · extract · Results", project)
