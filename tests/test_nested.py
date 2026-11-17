from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.nested import CONFIRM, NESTED_ANOVA, NESTED_T, SUBCOLUMNS
from analisi.workbench import analyse


class NestedTests(unittest.TestCase):
    @staticmethod
    def _balanced():
        frame = pd.DataFrame({f"{group} [{index + 1}]": np.array([-.5, .5, 1.]) + mean + 2 * index
                              for group, mean in zip("ABC", (0., 1., 5.), strict=True)
                              for index in range(3)})
        frame.attrs["table_format"] = "nested"
        return frame

    def test_balanced_nested_follows_anova_on_cluster_means(self):
        frame = self._balanced()
        reference = stats.f_oneway(*(frame.filter(regex=f"^{label} ").mean(axis=0) for label in "ABC"))
        for method in ("Kenward–Roger", "Satterthwaite", "Legacy"):
            with self.subTest(method=method):
                result = analyse(NESTED_ANOVA, frame, {"Denominator method": method, "Post-hoc": "Bonferroni",
                                                      "Confidence level (%)": 90.})
                tests = result.tables["Fixed effect"].loc["Treatment"]
                self.assertAlmostEqual(tests["F"], reference.statistic, places=8)
                self.assertAlmostEqual(tests["p"], reference.pvalue, places=10)
                self.assertAlmostEqual(tests["F df2"], 6.)
                comparisons = result.tables["Multiple comparisons"]
                self.assertEqual(len(comparisons), 3)
                self.assertIn("CI 90% low", comparisons)
                self.assertTrue((comparisons["Adjusted p"] >= comparisons["p"]).all())

    def test_unbalanced_fit_finds_interior_minimum_after_nearby_maximum(self):
        root = np.sqrt(2.)
        blocks = {"A [1]": [0] * 8, "A [2]": [0] * 8, "A [3]": [0],
                  "B [1]": [-root, root], "B [2]": [-2], "B [3]": [0]}
        frame = pd.DataFrame({name: pd.Series(values) for name, values in blocks.items()})
        frame.attrs["table_format"] = "nested"
        result = analyse(NESTED_T, frame, {})
        # Independent REML fit with statsmodels MixedLM and Powell optimization.
        np.testing.assert_allclose(result.tables["Variance components"]["Variance"],
                                   [.2952472234, .2824934285], rtol=2e-6)
        self.assertAlmostEqual(result.tables["Difference of means"]["Estimate"].iloc[0], -.601758, places=5)

    def test_boundary_kenward_roger_retains_the_random_term(self):
        frame = pd.DataFrame({"A [1]": [-2, 0, 2], "A [2]": [-1, 0, 1],
                              "B [1]": [0, 2, 4], "B [2]": [1, 2, 3]})
        frame.attrs["table_format"] = "nested"
        result = analyse(NESTED_T, frame, {})
        self.assertEqual(result.tables["Variance components"].loc["Nested subcolumn", "Variance"], 0.)
        self.assertTrue(np.isfinite(result.tables["Difference of means"]["df"]).all())
        self.assertIn("zero", result.tables["Model"].loc["Status", "Value"])

    def test_missing_observations_and_exclusions_stay_with_their_subcolumn(self):
        frame = self._balanced().iloc[:, :6].copy()
        frame.iat[1, 0] = np.nan
        dataset = Dataset(frame, excluded={(2, 1)})
        result = analyse(NESTED_T, dataset.frame(mask_excluded=True), {})
        observed = result.tables["Subcolumns"]
        self.assertEqual(observed["N"].tolist(), [2, 2, 3, 3, 3, 3])
        self.assertEqual(result.tables["Model"].loc["Observations used", "Value"], 16)
        difference = result.tables["Difference of means"].iloc[0]
        self.assertAlmostEqual(difference["t"] ** 2, result.tables["Fixed effect"].loc["Treatment", "F"])
        self.assertAlmostEqual(difference["p"], result.tables["Fixed effect"].loc["Treatment", "p"])

    def test_other_worksheet_formats_require_explicit_stacking_confirmation(self):
        frame = self._balanced().iloc[:, :6].copy()
        frame.attrs["table_format"] = "Grouped"
        with self.assertRaisesRegex(ValueError, "Confirm"):
            analyse(NESTED_T, frame, {})
        frame.iat[0, 0] = np.nan
        model = analyse(NESTED_T, frame, {CONFIRM: True, "Denominator method": "Legacy"}).tables["Model"]
        self.assertIn("unequal subcolumn sizes", model.loc["Status", "Value"])

    def test_xml_preserves_same_title_groups_through_save_and_reopen(self):
        def column(subgroups):
            subs = "".join("<Subcolumn>" + "".join(f"<d>{value}</d>" for value in row) + "</Subcolumn>"
                           for row in subgroups)
            return "<YColumn><Title>A</Title>" + subs + "</YColumn>"

        def xml(*groups):
            return ('<GraphPadPrismFile><Table ID="Nested" TableType="TwoWay" ExtTableType="Nested" '
                    'XFormat="none" YFormat="replicates">' + "".join(map(column, groups))
                    + "</Table></GraphPadPrismFile>")

        with TemporaryDirectory() as temporary:
            source, project = Path(temporary) / "nested.xml", Path(temporary) / "nested.alab"
            source.write_text(xml([[0, 1, 2], [4, 5, 6]], [[8, 9, 10], [12, 13, 14], [16, 17, 18]]))
            title, frame = next(iter(load_tables(source).items()))
            roles = frame.attrs["worksheet_roles"]
            self.assertEqual(list(map(len, roles["y"])), [2, 3])
            self.assertIn("A [3]", roles["y"][1])
            save_project(project, {title: Dataset(frame)})
            reopened = load_project(project)[title].frame()
            self.assertEqual(reopened.attrs["worksheet_roles"], roles)
            estimates = analyse(NESTED_T, reopened, {}).tables["Difference of means"]
            self.assertAlmostEqual(estimates["Estimate"].iloc[0], 10.0)

    def test_deselecting_ambiguous_columns_cannot_change_group_identity(self):
        frame = self._balanced().iloc[:, :6].copy()
        frame["A [1] (2)"] = [9., 10., 11.]
        selected = [name for name in frame if name != "A [1] (2)"]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            analyse(NESTED_T, frame, {SUBCOLUMNS: selected})

    def test_rejects_summary_columns_and_malformed_values(self):
        frame = self._balanced().iloc[:, :6].copy()
        with self.assertRaisesRegex(ValueError, "treatment groups"):
            analyse(NESTED_ANOVA, frame, {})
        invalid = frame.assign(**{"A [1]": [0, "error", 1]})
        with self.assertRaisesRegex(ValueError, "finite values"):
            analyse(NESTED_T, invalid, {})
        summarized = frame.rename(columns={"A [1]": "A [Mean]"})
        with self.assertRaisesRegex(ValueError, "stacked subcolumns"):
            analyse(NESTED_T, summarized, {SUBCOLUMNS: summarized.columns.tolist()})
