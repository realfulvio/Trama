import json
import unittest
from itertools import combinations, product
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi import rank_exact, rank_tests
from analisi.processing import FieldError
from analisi.rank_tests import ALTERNATIVE, CONTINUITY, EXACT, NORMAL, P_VALUE, ZERO_DIFFERENCES
from analisi.workbench import METHODS, analyse

DATA = Path(__file__).parent / "data" / "rank_exact"
MW, WX = "Mann–Whitney", "Wilcoxon signed-rank"
ORACLE = json.loads((DATA / "oracle.json").read_text(encoding="utf-8"))


def mann(data, **extra):
    return analyse(MW, data, {"Response": "Y", "Group": "Group", **extra})


def wilcoxon(data, **extra):
    return analyse(WX, data, {"First": "First", "Second": "Second", **extra})


def value(result, name, row):
    return result.tables[name]["Value"][row]


def field_error(action, field):
    with unittest.TestCase().assertRaises(FieldError) as caught:
        action()
    assert caught.exception.field == field, (caught.exception.field, field)
    return str(caught.exception)


class Legacy(unittest.TestCase):
    def snapshot(self, result):
        table = next(iter(result.tables.values()))
        return table.index.tolist(), table["Value"].tolist()

    def test_recipes_without_p_value_keep_the_original_sheet(self):
        data = pd.read_csv(DATA / "mann-1.csv")
        result = mann(data)
        self.assertEqual(list(result.tables), [MW])
        old = json.loads((DATA / "legacy-mann.json").read_text())[0]
        self.assertEqual(result.tables[MW].index.tolist(), old["index"])
        np.testing.assert_allclose(result.tables[MW]["Value"].astype(float), [row[0] for row in old["values"]])
        result = wilcoxon(pd.read_csv(DATA / "wilcoxon-2.csv"))
        self.assertEqual(list(result.tables), [WX])
        old = json.loads((DATA / "legacy-wilcoxon.json").read_text())[0]
        np.testing.assert_allclose(result.tables[WX]["Value"].astype(float), [row[0] for row in old["values"]])

    def test_legacy_all_zero_pairs_still_raise(self):
        with self.assertRaisesRegex(ValueError, "nonzero paired difference"):
            wilcoxon(pd.DataFrame({"First": [0, 1, 2], "Second": [0, 1, 2]}))

    def test_catalog_offers_the_new_options(self):
        self.assertEqual(list(METHODS[MW]), ["Response", "Group", P_VALUE, ALTERNATIVE, CONTINUITY])
        self.assertEqual(list(METHODS[WX]), ["First", "Second", P_VALUE, ALTERNATIVE, CONTINUITY, ZERO_DIFFERENCES])
        self.assertEqual(METHODS[MW][P_VALUE], ("Automatic", "Exact conditional", "Normal approximation"))
        self.assertIs(METHODS[MW][CONTINUITY], True)
        self.assertEqual(METHODS[WX][ZERO_DIFFERENCES], ("Discard", "Pratt"))


class MannWhitneyExact(unittest.TestCase):
    def test_oracle_every_alternative(self):
        for row in ORACLE["mann"]:
            data = pd.read_csv(DATA / row["fixture"])
            for alternative in ("Two-sided", "Less", "Greater"):
                result = mann(data, **{P_VALUE: EXACT, ALTERNATIVE: alternative})
                table = result.tables[MW]["Value"]
                self.assertAlmostEqual(table["p"], row[alternative], places=12, msg=(row["fixture"], alternative))
                self.assertEqual((table["U first"], table["U second"]), (row["U first"], row["U second"]))
                self.assertEqual((table["N first"], table["N second"], table["N"]),
                                 (row["N first"], row["N second"], row["N first"] + row["N second"]))
                self.assertAlmostEqual(table["Rank-biserial"], row["Rank-biserial"], places=12)
                self.assertEqual(table["Statistic"], row["U first"])
                self.assertEqual((table["p method"], table["p method reason"], table[ALTERNATIVE]),
                                 (EXACT, "", alternative))
                self.assertEqual(table[CONTINUITY], "Not applicable")
                np.testing.assert_allclose(result.tables["Ranks"]["Rank"], row["ranks"])

    def test_swapping_the_groups_swaps_the_tails(self):
        data = pd.read_csv(DATA / "mann-2.csv")
        flipped = data.assign(Group=data.Group.map({"A": "B", "B": "A"}))
        # The first group is the first one seen, so reorder rows to keep the same roles reversed.
        reordered = pd.concat([data[data.Group == "B"], data[data.Group == "A"]], ignore_index=True)
        for alternative, opposite in (("Less", "Greater"), ("Greater", "Less"), ("Two-sided", "Two-sided")):
            a = value(mann(data, **{P_VALUE: EXACT, ALTERNATIVE: alternative}), MW, "p")
            b = value(mann(reordered, **{P_VALUE: EXACT, ALTERNATIVE: opposite}), MW, "p")
            self.assertAlmostEqual(a, b, places=12)
        self.assertEqual(value(mann(flipped, **{P_VALUE: EXACT}), MW, "First group"), "B")

    def test_groups_follow_first_appearance_in_the_complete_rows(self):
        data = pd.DataFrame({"Y": [np.nan, 3, 1, 2, 5, 4], "Group": ["A", "B", "B", "A", "A", "B"]})
        table = mann(data, **{P_VALUE: EXACT}).tables[MW]["Value"]
        self.assertEqual((table["First group"], table["Second group"], table["N"]), ("B", "A", 5))

    def test_source_rows_survive_omissions_and_duplicate_indices(self):
        data = pd.DataFrame({"Y": [5.0, np.nan, 1, 2, 2, 7], "Group": ["A", "A", "B", "B", None, "A"]},
                            index=[4, 4, 1, 1, 9, 0])
        ranks = mann(data, **{P_VALUE: EXACT}).tables["Ranks"]
        # Source row keeps the original index labels of the complete rows, duplicates included.
        self.assertEqual(ranks["Source row"].tolist(), data.index[[0, 2, 3, 5]].tolist())
        self.assertEqual(ranks["Source row"].tolist(), [4, 1, 1, 0])
        self.assertEqual(ranks["Group"].tolist(), ["A", "B", "B", "A"])
        self.assertEqual(ranks["Value"].tolist(), [5, 1, 2, 7])
        self.assertEqual(ranks["Rank"].tolist(), [3, 1, 2, 4])

    def test_all_equal_values_have_p_one_beyond_uint64(self):
        data = pd.DataFrame({"Y": [1] * 80, "Group": ["A"] * 40 + ["B"] * 40})
        for alternative in ("Two-sided", "Less", "Greater"):
            table = mann(data, **{P_VALUE: EXACT, ALTERNATIVE: alternative}).tables[MW]["Value"]
            self.assertEqual(table["p"], 1.0)
            self.assertEqual(table["U first"], 800)

    def test_needs_exactly_two_groups(self):
        three = pd.DataFrame({"Y": [1, 2, 3, 4, 5, 6], "Group": list("AABBCC")})
        self.assertIn("exactly two", field_error(lambda: mann(three, **{P_VALUE: EXACT}), "Group"))
        field_error(lambda: mann(pd.DataFrame({"Y": [1, 2], "Group": ["A", "A"]}), **{P_VALUE: EXACT}), "Group")
        field_error(lambda: analyse(MW, three, {"Response": "Y", "Group": "Y", P_VALUE: EXACT}), "Group")


class MannWhitneyNormal(unittest.TestCase):
    def test_matches_scipy_with_and_without_continuity(self):
        rng = np.random.default_rng(23)
        values = rng.integers(0, 8, 21).astype(float)
        groups = np.array(["A"] * 9 + ["B"] * 12)
        data = pd.DataFrame({"Y": values, "Group": groups})
        for alternative in ("two-sided", "less", "greater"):
            for continuity in (True, False):
                expected = stats.mannwhitneyu(values[:9], values[9:], alternative=alternative, method="asymptotic",
                                              use_continuity=continuity)
                table = mann(data, **{P_VALUE: NORMAL, ALTERNATIVE: alternative.capitalize(),
                                      CONTINUITY: continuity}).tables[MW]["Value"]
                self.assertEqual(table["p method"], NORMAL)
                self.assertAlmostEqual(table["p"], expected.pvalue, places=10, msg=(alternative, continuity))
                self.assertEqual(table["Statistic"], expected.statistic)
                self.assertEqual(table[CONTINUITY], continuity)

    def test_zero_variance_reports_p_one_and_a_note(self):
        data = pd.DataFrame({"Y": [2.0] * 6, "Group": list("AAABBB")})
        table = mann(data, **{P_VALUE: NORMAL}).tables[MW]["Value"]
        self.assertEqual(table["p"], 1.0)
        self.assertIn("variance is zero", table["Note"])


class WilcoxonExact(unittest.TestCase):
    def test_oracle_both_zero_policies_and_every_alternative(self):
        for row in ORACLE["wilcoxon"]:
            data = pd.read_csv(DATA / row["fixture"])
            for policy in ("Discard", "Pratt"):
                expected = row[policy]
                for alternative in ("Two-sided", "Less", "Greater"):
                    result = wilcoxon(data, **{P_VALUE: EXACT, ALTERNATIVE: alternative, ZERO_DIFFERENCES: policy})
                    table = result.tables[WX]["Value"]
                    case = (row["fixture"], policy, alternative)
                    self.assertAlmostEqual(table["p"], expected[alternative], places=12, msg=case)
                    self.assertEqual((table["W positive"], table["W negative"]),
                                     (expected["W positive"], expected["W negative"]), case)
                    self.assertEqual((table["Effective N"], table["Zero pairs"], table["Complete pairs"], table["N"]),
                                     (expected["Effective N"], expected["Zero pairs"], len(data), len(data)))
                    if expected["Effective N"]:
                        self.assertAlmostEqual(table["Rank-biserial"], expected["Rank-biserial"], places=12)
                    else:
                        self.assertTrue(np.isnan(table["Rank-biserial"]))
                    statistic = min(table["W positive"], table["W negative"]) if alternative == "Two-sided" \
                        else table["W positive"]
                    self.assertEqual(table["Statistic"], statistic)
                    ranks = result.tables["Ranks"]
                    np.testing.assert_allclose(ranks["Absolute rank"], [np.nan if v is None else v
                                                                        for v in expected["ranks"]])
                    self.assertEqual(ranks["Included"].tolist(), (data.First != data.Second).tolist())
                    self.assertEqual(table[ZERO_DIFFERENCES], policy)

    def test_all_zero_differences(self):
        data = pd.read_csv(DATA / "wilcoxon-4.csv")
        for policy in ("Discard", "Pratt"):
            for method in (EXACT, NORMAL, "Automatic"):
                table = wilcoxon(data, **{P_VALUE: method, ZERO_DIFFERENCES: policy}).tables[WX]["Value"]
                self.assertEqual((table["p"], table["Statistic"], table["Effective N"]), (1.0, 0, 0))
                self.assertTrue(np.isnan(table["Rank-biserial"]))
                self.assertIn("zero difference", table["Note"])

    def test_negating_the_differences_swaps_the_tails(self):
        data = pd.read_csv(DATA / "wilcoxon-2.csv")
        swapped = data.rename(columns={"First": "Second", "Second": "First"})
        for alternative, opposite in (("Less", "Greater"), ("Greater", "Less"), ("Two-sided", "Two-sided")):
            a = value(wilcoxon(data, **{P_VALUE: EXACT, ALTERNATIVE: alternative}), WX, "p")
            b = value(wilcoxon(swapped, **{P_VALUE: EXACT, ALTERNATIVE: opposite}), WX, "p")
            self.assertAlmostEqual(a, b, places=12)

    def test_eighty_equal_positive_differences(self):
        data = pd.DataFrame({"First": [1] * 80, "Second": [0] * 80})
        self.assertEqual(value(wilcoxon(data, **{P_VALUE: EXACT}), WX, "p"), 2.0**-79)
        self.assertEqual(value(wilcoxon(data, **{P_VALUE: EXACT, ALTERNATIVE: "Greater"}), WX, "p"), 2.0**-80)
        self.assertEqual(value(wilcoxon(data, **{P_VALUE: EXACT, ALTERNATIVE: "Less"}), WX, "p"), 1.0)

    def test_floats_that_differ_by_rounding_are_not_zero(self):
        data = pd.DataFrame({"First": [0.3, 0.5, 1.5], "Second": [0.30000000000000004, 0.5, 1.0]})
        result = wilcoxon(data, **{P_VALUE: EXACT})
        table = result.tables[WX]["Value"]
        self.assertEqual((table["Zero pairs"], table["Effective N"]), (1, 2))
        self.assertEqual(result.tables["Ranks"]["Included"].tolist(), [True, False, True])
        self.assertEqual(result.tables["Ranks"]["Absolute rank"].tolist()[0], 1.0)

    def test_incomplete_rows_and_duplicate_indices(self):
        data = pd.DataFrame({"First": [3.0, 5, np.nan, 7, 2], "Second": [1.0, 5, 4, np.nan, 3]}, index=[2, 2, 0, 0, 1])
        result = wilcoxon(data, **{P_VALUE: EXACT})
        ranks = result.tables["Ranks"]
        self.assertEqual(ranks["Source row"].tolist(), data.index[[0, 1, 4]].tolist())
        self.assertEqual(ranks["Source row"].tolist(), [2, 2, 1])
        self.assertEqual(ranks["Absolute rank"].tolist()[0:1], [2.0])
        self.assertTrue(np.isnan(ranks["Absolute rank"].tolist()[1]))
        table = result.tables[WX]["Value"]
        self.assertEqual((table["Complete pairs"], table["Zero pairs"], table["Effective N"]), (3, 1, 2))

    def test_pratt_zeros_keep_their_ranks_but_do_not_count(self):
        data = pd.DataFrame({"First": [1.0, 1, 4, 6], "Second": [1.0, 1, 1, 2]})
        discard = wilcoxon(data, **{P_VALUE: EXACT})
        pratt = wilcoxon(data, **{P_VALUE: EXACT, ZERO_DIFFERENCES: "Pratt"})
        self.assertEqual(discard.tables["Ranks"]["Absolute rank"].tolist()[2:], [1.0, 2.0])
        self.assertTrue(discard.tables["Ranks"]["Absolute rank"].iloc[:2].isna().all())
        self.assertEqual(pratt.tables["Ranks"]["Absolute rank"].tolist(), [1.5, 1.5, 3.0, 4.0])
        self.assertEqual(pratt.tables["Ranks"]["Included"].tolist(), [False, False, True, True])
        self.assertEqual(value(pratt, WX, "W positive"), 7.0)
        self.assertEqual(value(discard, WX, "W positive"), 3.0)


class WilcoxonNormal(unittest.TestCase):
    def test_matches_scipy_with_and_without_continuity(self):
        rng = np.random.default_rng(31)
        first = rng.integers(0, 12, 25).astype(float)
        second = rng.integers(0, 12, 25).astype(float)
        data = pd.DataFrame({"First": first, "Second": second})
        for alternative in ("two-sided", "less", "greater"):
            for continuity in (True, False):
                expected = stats.wilcoxon(first, second, alternative=alternative, method="approx",
                                          correction=continuity, zero_method="wilcox")
                table = wilcoxon(data, **{P_VALUE: NORMAL, ALTERNATIVE: alternative.capitalize(),
                                          CONTINUITY: continuity}).tables[WX]["Value"]
                self.assertAlmostEqual(table["p"], expected.pvalue, places=10, msg=(alternative, continuity))
                self.assertEqual(table["p method"], NORMAL)
                self.assertEqual(table[CONTINUITY], continuity)


class BudgetAndFallback(unittest.TestCase):
    def setUp(self):
        self.budget = pd.read_csv(DATA / "budget.csv")
        self.options = {"First": "First", "Second": "Second"}

    def test_exact_outside_the_budget_is_a_field_error(self):
        message = field_error(lambda: analyse(WX, self.budget, {**self.options, P_VALUE: EXACT}), P_VALUE)
        self.assertIn("limit", message)

    def test_automatic_falls_back_and_says_why(self):
        table = analyse(WX, self.budget, {**self.options, P_VALUE: "Automatic"}).tables[WX]["Value"]
        self.assertEqual(table["p method"], NORMAL)
        self.assertIn("work limit", table["p method reason"])
        self.assertTrue(0 <= table["p"] <= 1)
        self.assertTrue(table[CONTINUITY])
        no_correction = analyse(WX, self.budget, {**self.options, P_VALUE: "Automatic", CONTINUITY: False})
        self.assertEqual(value(no_correction, WX, CONTINUITY), False)

    def test_ties_alone_do_not_force_the_fallback(self):
        data = pd.DataFrame({"Y": [1, 1, 2, 2, 3, 3, 3, 4], "Group": list("AAABBBBA")})
        table = mann(data, **{P_VALUE: "Automatic"}).tables[MW]["Value"]
        self.assertEqual((table["p method"], table["p method reason"]), (EXACT, ""))

    def test_mann_whitney_budget(self):
        rng = np.random.default_rng(2)
        data = pd.DataFrame({"Y": rng.permutation(np.arange(400.0)), "Group": ["A"] * 200 + ["B"] * 200})
        with patch.object(rank_exact, "MAX_TRANSITIONS", 10_000):
            field_error(lambda: mann(data, **{P_VALUE: EXACT}), P_VALUE)
            table = mann(data, **{P_VALUE: "Automatic"}).tables[MW]["Value"]
        self.assertEqual(table["p method"], NORMAL)
        self.assertTrue(table["p method reason"])


class OptionChecks(unittest.TestCase):
    def test_each_bad_option_names_its_field(self):
        data = pd.read_csv(DATA / "mann-1.csv")
        field_error(lambda: mann(data, **{P_VALUE: "Permutation"}), P_VALUE)
        field_error(lambda: mann(data, **{P_VALUE: EXACT, ALTERNATIVE: "Sideways"}), ALTERNATIVE)
        field_error(lambda: mann(data, **{P_VALUE: EXACT, CONTINUITY: "yes"}), CONTINUITY)
        pairs = pd.read_csv(DATA / "wilcoxon-1.csv")
        field_error(lambda: wilcoxon(pairs, **{P_VALUE: EXACT, ZERO_DIFFERENCES: "Keep"}), ZERO_DIFFERENCES)
        field_error(lambda: analyse(WX, pairs, {"First": "First", "Second": "First", P_VALUE: EXACT}), "Second")

    def test_a_missing_option_uses_its_default(self):
        data = pd.read_csv(DATA / "mann-1.csv")
        table = mann(data, **{P_VALUE: "Automatic"}).tables[MW]["Value"]
        self.assertEqual((table[ALTERNATIVE], table["p method"]), ("Two-sided", EXACT))


class Translation(unittest.TestCase):
    def test_new_controls_translate_but_keep_canonical_values(self):
        from analisi.i18n import CATALOGS

        english, italian = CATALOGS["en"], CATALOGS["it"]
        # The English captions and choices are the canonical recipe keys and values themselves.
        for value, key in {**rank_tests.LABEL_KEYS, **rank_tests.CHOICE_KEYS}.items():
            self.assertEqual(english[key], value)
            self.assertIn(key, italian)
        self.assertEqual([italian[rank_tests.LABEL_KEYS[name]] for name in (P_VALUE, ALTERNATIVE, CONTINUITY,
                                                                             ZERO_DIFFERENCES)],
                         ["Valore p", "Ipotesi alternativa", "Correzione di continuità", "Differenze nulle"])
        choices = [*rank_tests.P_METHODS, *rank_tests.ALTERNATIVES, *rank_tests.ZERO_POLICIES]
        self.assertEqual([italian[rank_tests.CHOICE_KEYS[value]] for value in choices],
                         ["Automatico", "Esatto condizionato", "Approssimazione normale", "Bilaterale", "Minore",
                          "Maggiore", "Escludi", "Pratt"])
        self.assertEqual(set(rank_tests.CHOICE_KEYS), set(choices))


if __name__ == "__main__":
    unittest.main()
