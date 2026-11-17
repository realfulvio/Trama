"""Brown–Forsythe (median Levene) and Bartlett after ordinary one-way ANOVA."""
from pathlib import Path
from unittest.mock import patch
import json
import unittest

import numpy as np
import pandas as pd
from numpy.testing import assert_allclose
from scipy import stats

from analisi.additional import inference
from analisi.field_error import FieldError
from analisi.i18n import active_language, set_language
from analisi.variance_assumptions import (ALPHA, BARTLETT, BARTLETT_NAME, BROWN, BROWN_NAME, GROUPS,
                                          KEEP, REJECT, SHEET, UNAVAILABLE, format_variance_error, sheets)
from analisi.workbench import analyse

ROOT = Path(__file__).resolve().parent / "data" / "variance_assumptions"
EXPECTED = json.loads((ROOT / "expected.json").read_text(encoding="utf-8"))


def fixture(name):
    return pd.read_csv(ROOT / name, index_col="Source row")


def options(**extra):
    base = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "None",
            BROWN: True, BARTLETT: True, ALPHA: 0.05}
    base.update(extra)
    return base


def check(actual, expected):
    assert_allclose(actual, expected, rtol=2e-9, atol=2e-10, equal_nan=True)


class VarianceAssumptionTests(unittest.TestCase):
    def test_dispatcher_matches_scipy_and_sizes(self):
        for name, expected in EXPECTED.items():
            result = analyse("One-way ANOVA", fixture(name + ".csv"), options())
            table = result.tables[SHEET]
            self.assertEqual(table["Test"].tolist(), [BROWN_NAME, BARTLETT_NAME])
            self.assertEqual(list(table.columns),
                             ["Test", "Statistic", "df1", "df2", "p", "Alpha", "Decision", "Reason"])
            check(table.iloc[0][["Statistic", "p"]].to_numpy(float), expected["brown_forsythe"])
            check(table.iloc[1][["Statistic", "p"]].to_numpy(float), expected["bartlett"])
            check(result.tables[GROUPS]["N"], expected["sizes"])
            self.assertEqual(table["Decision"].tolist(), [REJECT, REJECT])
            self.assertEqual(table["Reason"].tolist(), ["", ""])
            self.assertTrue(pd.isna(table.iloc[1]["df2"]))
            self.assertIsNone(result.figure)

    def test_independent_formula_and_scipy(self):
        frame = fixture("heterogeneous.csv")
        groups = [part.Y.to_numpy(float) for _, part in frame.groupby("Group", sort=False)]
        deviations = [np.abs(values - np.median(values)) for values in groups]
        count = sum(map(len, deviations))
        grand = sum(float(np.sum(values)) for values in deviations) / count
        numerator = sum(len(values) * (values.mean() - grand) ** 2 for values in deviations)
        denominator = sum(float(np.sum((values - values.mean()) ** 2)) for values in deviations)
        statistic = (count - len(groups)) * numerator / ((len(groups) - 1) * denominator)
        check(statistic, stats.levene(*groups, center="median").statistic)
        table = analyse("One-way ANOVA", frame, options()).tables[SHEET]
        check(table.iloc[0][["Statistic", "p"]].to_numpy(float), list(stats.levene(*groups, center="median"))[:2])
        check(table.iloc[1][["Statistic", "p"]].to_numpy(float), list(stats.bartlett(*groups))[:2])

    def test_scale_and_translation_leave_the_statistics(self):
        frame = fixture("heterogeneous.csv")
        base = analyse("One-way ANOVA", frame, options()).tables[SHEET]
        for factor in (1e-150, 1e150):
            scaled = frame.copy()
            scaled["Y"] *= factor
            other = analyse("One-way ANOVA", scaled, options()).tables[SHEET]
            check(other[["Statistic", "p"]], base[["Statistic", "p"]])
        shifted = frame.copy()
        shifted["Y"] += 1e6
        check(analyse("One-way ANOVA", shifted, options()).tables[SHEET][["Statistic", "p"]],
              base[["Statistic", "p"]])

    def test_alpha_changes_only_the_decision(self):
        frame = fixture("heterogeneous.csv")
        strict = analyse("One-way ANOVA", frame, options(**{ALPHA: 0.01})).tables[SHEET]
        loose = analyse("One-way ANOVA", frame, options()).tables[SHEET]
        check(strict[["Statistic", "p", "df1"]], loose[["Statistic", "p", "df1"]])
        self.assertEqual(strict["Decision"].tolist(), [KEEP, REJECT])
        self.assertEqual(strict["Alpha"].tolist(), [0.01, 0.01])

    def test_disabled_and_missing_keys_match_the_legacy_sheets(self):
        frame = fixture("heterogeneous.csv")
        legacy = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Tukey"}
        off = {**legacy, BROWN: False, BARTLETT: False, ALPHA: "stale"}
        before = analyse("One-way ANOVA", frame, legacy)
        after = analyse("One-way ANOVA", frame, off)
        self.assertEqual(list(before.tables), list(after.tables))
        for name in before.tables:
            pd.testing.assert_frame_equal(before.tables[name], after.tables[name])
        self.assertIsNone(after.figure)

    def test_welch_ignores_hidden_keys(self):
        frame = fixture("heterogeneous.csv")
        result = analyse("One-way ANOVA", frame, options(**{"Method": "Welch", ALPHA: "stale"}))
        self.assertNotIn(SHEET, result.tables)
        self.assertEqual(result.tables["ANOVA"]["Method"].iloc[0], "Welch one-way ANOVA")

    def test_zero_variance_blocks_bartlett_only(self):
        frame = fixture("heterogeneous.csv")
        frame.loc[frame.Group == "A", "Y"] = 3.0
        table = analyse("One-way ANOVA", frame, options()).tables[SHEET]
        bartlett = table[table.Test == BARTLETT_NAME].iloc[0]
        brown = table[table.Test == BROWN_NAME].iloc[0]
        self.assertTrue(pd.isna(bartlett["p"]))
        self.assertIn("A", bartlett["Reason"])
        self.assertEqual(bartlett["Decision"], UNAVAILABLE)
        self.assertTrue(np.isfinite(brown["p"]))
        self.assertEqual(brown["Reason"], "")
        self.assertEqual(brown["Decision"], REJECT)

    def test_constant_deviations_block_brown_forsythe_only(self):
        frame = pd.DataFrame({"Group": ["A", "A", "B", "B"], "Y": [0.0, 2.0, 5.0, 9.0]})
        table = analyse("One-way ANOVA", frame, options()).tables[SHEET]
        brown = table[table.Test == BROWN_NAME].iloc[0]
        bartlett = table[table.Test == BARTLETT_NAME].iloc[0]
        self.assertTrue(pd.isna(brown["p"]))
        self.assertIn("absolute deviations", brown["Reason"])
        self.assertTrue(np.isfinite(bartlett["p"]))
        self.assertEqual(bartlett["Reason"], "")

    def test_small_group_names_every_short_group_and_keeps_anova(self):
        frame = pd.DataFrame({"Group": [10, 10, 2, "b"], "Y": [1.0, 3.0, 4.0, 9.0]})
        original = frame.copy()
        result = analyse("One-way ANOVA", frame, options())
        pd.testing.assert_frame_equal(frame, original)
        self.assertIn("ANOVA", result.tables)
        table = result.tables[SHEET]
        self.assertEqual(table["Decision"].tolist(), [UNAVAILABLE, UNAVAILABLE])
        for reason in table["Reason"]:
            self.assertIn("2, b", reason)
            self.assertNotIn("10", reason)
        self.assertEqual(result.tables[GROUPS]["Group"].tolist(), [10, 2, "b"])
        self.assertEqual(result.tables[GROUPS]["N"].tolist(), [2, 1, 1])

    def test_one_selected_test_omits_the_other(self):
        table = analyse("One-way ANOVA", fixture("heterogeneous.csv"),
                        options(**{BARTLETT: False})).tables[SHEET]
        self.assertEqual(table["Test"].tolist(), [BROWN_NAME])

    def test_bad_alpha_and_flag_name_their_field(self):
        frame = fixture("heterogeneous.csv")
        with self.assertRaises(FieldError) as caught:
            analyse("One-way ANOVA", frame, options(**{ALPHA: 0}))
        self.assertEqual(caught.exception.field, ALPHA)
        self.assertIn("greater than 0", str(caught.exception))
        for value in (1, np.nan, np.inf, "stale", True):
            with self.assertRaises(FieldError) as caught:
                analyse("One-way ANOVA", frame, options(**{ALPHA: value}))
            self.assertEqual(caught.exception.field, ALPHA)
        with self.assertRaises(FieldError) as caught:
            analyse("One-way ANOVA", frame, options(**{BROWN: "yes"}))
        self.assertEqual(caught.exception.field, BROWN)
        self.assertEqual(str(caught.exception), "Choose yes or no.")

    def test_default_alpha_and_no_second_anova(self):
        frame = fixture("heterogeneous.csv")
        chosen = options()
        del chosen[ALPHA]
        table = analyse("One-way ANOVA", frame, chosen).tables[SHEET]
        self.assertEqual(table["Alpha"].tolist(), [0.05, 0.05])
        with patch("analisi.additional.inference.one_way_anova", wraps=inference.one_way_anova) as spy:
            analyse("One-way ANOVA", frame, options())
            analyse("One-way ANOVA", frame, options(**{BROWN: False, BARTLETT: False}))
        self.assertEqual(spy.call_count, 2)

    def test_dropping_a_row_changes_the_group_size(self):
        frame = fixture("heterogeneous.csv").drop(index=11)
        groups = analyse("One-way ANOVA", frame, options()).tables[GROUPS]
        self.assertEqual(groups["N"].tolist(), [5, 7, 5])
        self.assertEqual(groups["Group"].tolist(), ["A", "B", "C"])

    def test_direct_sheets_do_not_require_the_dialog(self):
        frame = fixture("missing.csv")
        produced = sheets(frame, "Y", "Group", options())
        self.assertEqual(produced[GROUPS]["N"].tolist(), EXPECTED["missing"]["sizes"])

    def test_italian_reason_keeps_the_group_name(self):
        frame = fixture("heterogeneous.csv")
        frame.loc[frame.Group == "A", "Y"] = 3.0
        previous = active_language()
        set_language("it")
        try:
            reason = analyse("One-way ANOVA", frame, options()).tables[SHEET]
            text = reason[reason.Test == BARTLETT_NAME]["Reason"].iloc[0]
        finally:
            set_language(previous)
        self.assertIn("A", text)
        self.assertIn("varianza", text)
        self.assertNotIn("zero variance", text)

    def test_formatted_error_names_the_translated_field(self):
        english = format_variance_error(FieldError(ALPHA, "Alpha must be a number between 0 and 1."))
        self.assertEqual(english, "Variance test alpha: Alpha must be a number between 0 and 1.")
        self.assertIsNone(format_variance_error(FieldError("Alpha", "Alpha must be a number between 0 and 1.")))
        previous = active_language()
        set_language("it")
        try:
            italian = format_variance_error(FieldError(BROWN, "Choose yes or no."))
        finally:
            set_language(previous)
        self.assertTrue(italian.startswith("Test di Brown–Forsythe sulle varianze: "))
        self.assertIn("Scegli sì o no.", italian)
