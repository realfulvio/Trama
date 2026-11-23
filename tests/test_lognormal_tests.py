"""Lognormal t-tests: direct cases beyond the packaged fixtures (source rows, masking, invalid cells, graphs)."""
import unittest
from decimal import Decimal, localcontext
from math import log

import numpy as np
import pandas as pd
from scipy import stats

from analisi import lognormal_tests as ratio
from analisi.field_error import FieldError
from analisi.lognormal_tests import (BASE_E, FIRST_OVER_SECOND, GREATER, LOGNORMAL, NO_GRAPH, ONE_SAMPLE, PAIRED,
                                     LOG_OBSERVATIONS, LOG_RATIOS, RATIO_ESTIMATION, SECOND_OVER_FIRST, STUDENT,
                                     WELCH, lognormal_test, visibility)
from analisi.workbench import GROUPS, METHODS, analyse

BEFORE = [3., 5, 8, 11, 15]
AFTER = [6.3, 9.6, 17.2, 20.9, 32.0]


def options(**changes):
    base = {"First": "Before", "Second": "After", "Design": PAIRED, "Report ratio": FIRST_OVER_SECOND,
            "Null ratio": 1.0, "Hypothetical geometric mean": 1.0, "Confidence level (%)": 95.0,
            "Alternative": "Two-sided", "Log base": "10", "Graph": RATIO_ESTIMATION, "Pairing correlation": True}
    base.update(changes)
    return base


def frame(index=None, **columns):
    return pd.DataFrame(columns or {"Before": BEFORE, "After": AFTER}, index=index)


def row(result):
    return result.tables["Lognormal test"].iloc[0]


def decimal_log_inference(first, second, null=1.0, reverse=False):
    """Independent high-precision oracle on the actual, rounded input floats."""
    with localcontext() as context:
        context.prec = 80
        log_null = Decimal.from_float(float(null)).ln()
        sign = -1 if reverse else 1
        differences = [sign * (Decimal.from_float(float(a)) / Decimal.from_float(float(b))).ln() - log_null
                       for a, b in zip(first, second)]
        count = Decimal(len(differences))
        mean = sum(differences) / count
        variance = sum((value - mean)**2 for value in differences) / (count - 1)
        se = (variance / count).sqrt()
        return float(mean), float(se), float(mean / se)


class Catalog(unittest.TestCase):
    def test_registered_in_group_comparison_with_canonical_defaults(self):
        self.assertIn(LOGNORMAL, GROUPS["Group Comparison"])
        spec = METHODS[LOGNORMAL]
        self.assertEqual(spec["Design"][0], "Paired")
        self.assertEqual(spec["Log base"], ("10", "e"))
        self.assertEqual(spec["Graph"][0], "Ratio estimation")
        self.assertIs(spec["Pairing correlation"], True)
        self.assertEqual((spec["Null ratio"], spec["Hypothetical geometric mean"], spec["Confidence level (%)"]),
                         (1.0, 1.0, 95.0))

    def test_visibility_follows_the_design(self):
        for design, expected in (("Paired", (True, False, True)), ("One-sample", (False, True, False))):
            fields = visibility(design)
            self.assertEqual(tuple(fields[name] for name in (ratio.SECOND, ratio.REFERENCE, ratio.PAIRING)), expected)
        self.assertFalse(visibility("Welch")["Pairing correlation"])
        self.assertFalse(visibility("One-sample", ratio.GROUPED)[ratio.INPUT])
        self.assertFalse(visibility("Welch", ratio.GROUPED)[ratio.SUBJECT])
        paired = visibility("Paired", ratio.GROUPED)
        self.assertTrue(all(paired[name] for name in (*ratio.GROUP_FIELDS, ratio.FIRST_GROUP)))
        self.assertFalse(paired[ratio.FIRST] or paired[ratio.SECOND])


class GroupedSamples(unittest.TestCase):
    def setUp(self):
        self.first = "  Control $"
        self.wide = frame()
        self.long = (self.wide.rename(columns={"Before": self.first}).assign(ID=list("abcde"))
                     .melt(id_vars="ID", var_name="Visit", value_name="Value"))
        self.grouped = options(**{ratio.INPUT: ratio.GROUPED, ratio.RESPONSE: "Value", ratio.GROUP: "Visit",
                                  ratio.SUBJECT: "ID", ratio.FIRST_GROUP: self.first, ratio.GRAPH: NO_GRAPH})

    def test_paired_matches_subject_and_reports_both_source_rows(self):
        expected = lognormal_test(self.wide, options(Graph=NO_GRAPH))
        reordered = self.long.iloc[[6, 8, 5, 9, 7, 0, 1, 2, 3, 4]]
        result = analyse(LOGNORMAL, reordered, self.grouped)
        pd.testing.assert_frame_equal(result.tables[ratio.TEST_SHEET], expected.tables[ratio.TEST_SHEET])
        pairs = result.tables[ratio.RATIOS_SHEET]
        self.assertEqual(pairs["Subject"].tolist(), list("abcde"))
        self.assertEqual(pairs["First source row"].tolist(), list(range(5)))
        self.assertEqual(pairs["Second source row"].tolist(), list(range(5, 10)))
        self.assertEqual(result.tables[ratio.OBSERVATIONS_SHEET]["Sample"].tolist(), [self.first] * 5 + ["After"] * 5)

    def test_independent_layouts_match_wide_and_keep_ratio_direction(self):
        for design in (WELCH, STUDENT):
            with self.subTest(design=design):
                settings = {**self.grouped, ratio.DESIGN: design, ratio.SUBJECT: "Unused"}
                expected = lognormal_test(self.wide, options(Design=design, Graph=NO_GRAPH))
                shuffled = pd.concat([self.long.iloc[5:], self.long.iloc[:5]])
                actual = lognormal_test(shuffled, settings)
                pd.testing.assert_frame_equal(actual.tables[ratio.TEST_SHEET], expected.tables[ratio.TEST_SHEET])
                reversed_result = lognormal_test(shuffled, {**settings, ratio.FIRST_GROUP: "After"})
                self.assertAlmostEqual(row(reversed_result)["Geometric ratio"], 1 / row(actual)["Geometric ratio"])

    def test_complete_pairs_before_positive_check(self):
        data = pd.concat([self.long, pd.DataFrame({"ID": ["z"], "Visit": [self.first], "Value": [-1.]})],
                         ignore_index=True)
        self.assertEqual(row(lognormal_test(data, self.grouped))["N first"], 5)
        with self.assertRaises(FieldError) as raised:
            lognormal_test(data, {**self.grouped, ratio.DESIGN: WELCH})
        self.assertEqual(raised.exception.field, ratio.RESPONSE)
        self.assertIn("Source row 10", str(raised.exception))

    def test_group_and_subject_errors_have_field_names(self):
        cases = [(self.long, {ratio.FIRST_GROUP: "Gone"}, ratio.FIRST_GROUP),
                 (self.long, {ratio.SUBJECT: "Visit"}, ratio.SUBJECT),
                 (pd.concat([self.long, self.long.iloc[:1]]), {}, ratio.SUBJECT),
                 (self.long.assign(Visit=[1] * 5 + ["1"] * 5), {}, ratio.GROUP)]
        for frame_, overrides, field in cases:
            with self.subTest(field=field), self.assertRaises(FieldError) as raised:
                lognormal_test(frame_, {**self.grouped, **overrides})
            self.assertEqual(raised.exception.field, field)


class Numbers(unittest.TestCase):
    def test_paired_matches_a_t_test_on_the_log_differences(self):
        d = np.log10(BEFORE) - np.log10(AFTER)
        expected = stats.ttest_1samp(d, 0)
        r = row(analyse(LOGNORMAL, frame(), options()))
        self.assertAlmostEqual(r["t"], expected.statistic, places=9)
        self.assertAlmostEqual(r["p"], expected.pvalue, places=12)
        self.assertAlmostEqual(r["Geometric ratio"], 10 ** d.mean(), places=12)
        self.assertEqual((r["N first"], r["N second"], r["df"], r["Status"], r["Reason"]), (5, 5, 4, "OK", ""))
        self.assertAlmostEqual(r["Mean log ratio"], d.mean(), places=12)

    def test_log_base_changes_only_the_log_columns(self):
        ten = row(analyse(LOGNORMAL, frame(), options()))
        natural = row(analyse(LOGNORMAL, frame(), options(**{"Log base": BASE_E})))
        for key in ("Mean log ratio", "SE log ratio", "Log lower", "Log upper"):
            self.assertAlmostEqual(natural[key] / ten[key], log(10), places=12)
        for key in ("t", "df", "p", "Geometric ratio", "Lower", "Upper"):
            self.assertEqual(natural[key], ten[key])

    def test_reversing_the_ratio_flips_the_sign_of_the_log_ratio_and_t_only(self):
        a = row(analyse(LOGNORMAL, frame(), options()))
        b = row(analyse(LOGNORMAL, frame(), options(**{"Report ratio": SECOND_OVER_FIRST})))
        self.assertAlmostEqual(b["Mean log ratio"], -a["Mean log ratio"], places=14)
        self.assertAlmostEqual(b["t"], -a["t"], places=12)
        self.assertEqual((b["SE log ratio"], b["df"], b["p"]), (a["SE log ratio"], a["df"], a["p"]))
        self.assertAlmostEqual(b["Lower"], 1 / a["Upper"], places=12)
        self.assertEqual((b["N first"], b["N second"]), (5, 5))     # physical columns, not the orientation

    def test_one_sided_p_keeps_the_two_sided_interval(self):
        two = row(analyse(LOGNORMAL, frame(), options()))
        greater = row(analyse(LOGNORMAL, frame(), options(Alternative=GREATER)))
        self.assertEqual((greater["Lower"], greater["Upper"]), (two["Lower"], two["Upper"]))
        self.assertAlmostEqual(greater["p"], stats.t.sf(greater["t"], 4), places=12)

    def test_null_ratio_moves_t_and_p_but_not_the_estimate_or_interval(self):
        a = row(analyse(LOGNORMAL, frame(), options()))
        b = row(analyse(LOGNORMAL, frame(), options(**{"Null ratio": 0.5})))
        self.assertEqual((a["Geometric ratio"], a["Lower"], a["Upper"]), (b["Geometric ratio"], b["Lower"], b["Upper"]))
        self.assertAlmostEqual(b["t"], (a["Mean log ratio"] * log(10) - log(0.5)) / (a["SE log ratio"] * log(10)),
                               places=10)

    def test_one_sample_against_a_hypothetical_geometric_mean(self):
        r = row(analyse(LOGNORMAL, frame(), options(Design=ONE_SAMPLE, **{"Hypothetical geometric mean": 5.0})))
        logs = np.log(BEFORE)
        expected = stats.ttest_1samp(logs, log(5.0))
        self.assertAlmostEqual(r["t"], expected.statistic, places=10)
        self.assertAlmostEqual(r["Geometric ratio"], np.exp(logs.mean()) / 5.0, places=12)
        self.assertEqual((r["N first"], r["N second"], r["df"]), (5, 0, 4))

    def test_welch_and_student_drop_missing_cells_separately(self):
        data = frame(Before=[3., 5, 8, 11, 15, 2, np.nan], After=[6.3, 9.6, np.nan, 20.9, 32.0, np.nan, 7.0])
        welch = row(analyse(LOGNORMAL, data, options(Design=WELCH)))
        student = row(analyse(LOGNORMAL, data, options(Design=STUDENT)))
        a, b = np.log([3., 5, 8, 11, 15, 2]), np.log([6.3, 9.6, 20.9, 32.0, 7.0])
        self.assertEqual((welch["N first"], welch["N second"]), (6, 5))
        self.assertAlmostEqual(welch["t"], stats.ttest_ind(a, b, equal_var=False).statistic, places=10)
        self.assertAlmostEqual(student["t"], stats.ttest_ind(a, b).statistic, places=10)
        self.assertEqual(student["df"], 9)

    def test_ratio_that_would_overflow_is_missing_while_the_logs_stay_finite(self):
        data = frame(Before=[1e300, 2e300, 4e300], After=[1e-300, 1e-300, 1e-300])
        result = analyse(LOGNORMAL, data, options())
        r = row(result)
        self.assertEqual(r["Status"], "Ratio overflow")
        self.assertTrue(np.isnan(r["Geometric ratio"]) and np.isnan(r["Lower"]) and np.isnan(r["Upper"]))
        self.assertTrue(np.isfinite([r["Mean log ratio"], r["Log lower"], r["Log upper"], r["t"], r["p"]]).all())
        self.assertTrue(r["Reason"].strip())
        ratios = result.tables["Paired ratios"]
        self.assertTrue(ratios["Ratio"].isna().all() and np.isfinite(ratios["Log ratio"]).all())
        self.assertTrue(result.figure is not None)
        texts = [t.get_text() for t in result.figure.axes[0].texts]
        self.assertTrue(any("outside the numeric range" in text for text in texts), texts)

    def test_constant_up_to_rounding_is_degenerate_but_measurable_variation_is_not(self):
        before = np.array([0.1, 0.7, 1.3, 2.9, 5.1])
        flat = row(analyse(LOGNORMAL, frame(Before=before, After=before * 3.0), options()))
        self.assertEqual(flat["Status"], "Inference unavailable")
        self.assertTrue(np.isnan([flat["t"], flat["p"], flat["Lower"], flat["Upper"]]).all())
        self.assertAlmostEqual(flat["Geometric ratio"], 1 / 3, places=12)
        self.assertEqual(flat["df"], 4)
        wobble = row(analyse(LOGNORMAL, frame(Before=before, After=before * 3.0 * (1 + 1e-6 * np.arange(5))),
                             options()))
        self.assertEqual(wobble["Status"], "OK")
        self.assertGreater(wobble["SE log ratio"], 0)

    def test_tiny_one_sample_spread_survives_a_common_change_of_units(self):
        values = np.array([1 + 1e-13, 1 + 2e-13, 1 + 4e-13, 1 + 8e-13])
        results = []
        for scale in (1.0, 1e150, 1e-150):
            with self.subTest(scale=scale):
                observed = scale * values
                result = analyse(LOGNORMAL, frame(Before=observed), options(
                    Design=ONE_SAMPLE, Graph=NO_GRAPH, **{"Hypothetical geometric mean": scale, "Log base": BASE_E}))
                actual = row(result)
                mean, se, statistic = decimal_log_inference(observed, np.full(len(values), scale))
                self.assertEqual(actual["Status"], "OK")
                np.testing.assert_allclose(actual[["Mean log ratio", "SE log ratio", "t"]].to_numpy(dtype=float),
                                           [mean, se, statistic], rtol=1e-10, atol=0)
                self.assertTrue(np.isfinite(actual[["p", "Lower", "Upper"]].to_numpy(dtype=float)).all())
                # The observations table continues to show the ordinary logarithm in the chosen base.
                np.testing.assert_array_equal(result.tables["Log observations"]["Log value"], np.log(observed))
                results.append(actual)
        np.testing.assert_allclose([result["SE log ratio"] for result in results], results[0]["SE log ratio"],
                                   rtol=0.002, atol=0)

    def test_tiny_paired_ratio_spread_survives_a_common_change_of_units(self):
        before = np.array([0.1, 0.7, 1.3, 2.9, 5.1])
        after = before * 3.0 * (1 + np.array([-3., -1., 0., 2., 4.]) * 1e-13)
        results = []
        for scale in (1.0, 1e150, 1e-150):
            with self.subTest(scale=scale):
                a, b = before * scale, after * scale
                actual = row(analyse(LOGNORMAL, frame(Before=a, After=b), options(
                    Graph=NO_GRAPH, **{"Log base": BASE_E})))
                mean, se, statistic = decimal_log_inference(a, b)
                self.assertEqual(actual["Status"], "OK")
                self.assertAlmostEqual(actual["Mean log ratio"], mean, places=14)
                np.testing.assert_allclose([actual["SE log ratio"], actual["t"]], [se, statistic],
                                           rtol=0.003, atol=0)
                self.assertTrue(np.isfinite(actual[["Lower", "Upper"]].to_numpy(dtype=float)).all())
                results.append(actual)
        np.testing.assert_allclose([result["SE log ratio"] for result in results], results[0]["SE log ratio"],
                                   rtol=0.003, atol=0)

    def test_rounded_constant_ratios_stay_degenerate_in_extreme_units(self):
        before = np.array([0.1, 0.7, 1.3, 2.9, 5.1])
        for scale in (1.0, 1e150, 1e-150):
            with self.subTest(scale=scale):
                actual = row(analyse(LOGNORMAL, frame(Before=before * scale, After=(before * 3.0) * scale),
                                     options(Graph=NO_GRAPH)))
                self.assertEqual(actual["Status"], "Inference unavailable")
                self.assertEqual(actual["SE log ratio"], 0.0)

    def test_tiny_difference_from_an_extreme_null_ratio_keeps_its_significance(self):
        before = 1e300 * np.array([1 + 1e-13, 1 + 2e-13, 1 + 4e-13, 1 + 8e-13])
        after = np.ones(4)
        for design in (PAIRED, ONE_SAMPLE):
            for reverse, null in ((False, 1e300), (True, 1e-300)):
                with self.subTest(design=design, reverse=reverse):
                    actual = row(analyse(LOGNORMAL, frame(Before=before, After=after), options(
                        Design=design, Graph=NO_GRAPH, **{"Null ratio": null,
                            "Report ratio": SECOND_OVER_FIRST if reverse else FIRST_OVER_SECOND})))
                    _, se, statistic = decimal_log_inference(before, after, null, reverse)
                    self.assertEqual(actual["Status"], "OK")
                    np.testing.assert_allclose([actual["SE log ratio"] * log(10), actual["t"]],
                                               [se, statistic], rtol=0.002, atol=0)
                    self.assertAlmostEqual(actual["p"], 2 * stats.t.sf(abs(statistic), 3), delta=0.0001)

    def test_welch_with_two_constant_samples_has_no_degrees_of_freedom(self):
        r = row(analyse(LOGNORMAL, frame(Before=[2., 2, 2], After=[5., 5, 5]), options(Design=WELCH)))
        self.assertEqual(r["Status"], "Inference unavailable")
        self.assertTrue(np.isnan(r["df"]))
        r = row(analyse(LOGNORMAL, frame(Before=[2., 2, 2], After=[5., 5, 5]), options(Design=STUDENT)))
        self.assertEqual(r["df"], 4)


class Rows(unittest.TestCase):
    def test_source_rows_keep_the_index_received(self):
        data = frame(index=[101, 105, 109, 110, 140])
        result = analyse(LOGNORMAL, data, options())
        self.assertEqual(result.tables["Paired ratios"]["Source row"].tolist(), [101, 105, 109, 110, 140])
        observations = result.tables["Log observations"]
        self.assertEqual(list(observations.columns), ["Source row", "Sample", "Value", "Log value"])
        self.assertEqual(observations["Source row"].tolist(), [101, 105, 109, 110, 140] * 2)
        self.assertEqual(observations["Sample"].tolist(), ["Before"] * 5 + ["After"] * 5)
        np.testing.assert_allclose(observations["Log value"].iloc[:5], np.log10(BEFORE))

    def test_excluded_and_orphan_rows_do_not_enter_a_paired_analysis(self):
        data = frame(Before=[3., 5, 8, 11, 15, np.nan, 0.0], After=[6.3, 9.6, 17.2, 20.9, 32.0, 7.0, np.nan],
                     index=[7, 8, 9, 10, 11, 12, 13])
        result = analyse(LOGNORMAL, data, options())
        self.assertEqual(result.tables["Paired ratios"]["Source row"].tolist(), [7, 8, 9, 10, 11])
        self.assertEqual(row(result)["N first"], 5)
        # Masking one cell removes its pair and the result is recomputed on the rest.
        masked = data.copy()
        masked.loc[9, "After"] = np.nan
        after = row(analyse(LOGNORMAL, masked, options()))
        self.assertEqual(after["N first"], 4)
        d = np.log10([3., 5, 11, 15]) - np.log10([6.3, 9.6, 20.9, 32.0])
        self.assertAlmostEqual(after["Mean log ratio"], d.mean(), places=12)

    def test_one_complete_pair_or_one_observation_is_not_enough(self):
        for data, changes, field in ((frame(Before=[1., np.nan], After=[2., 3.]), {}, "First"),
                                     (frame(Before=[1., 2, 3], After=[2., np.nan, np.nan]), {"Design": WELCH}, "Second"),
                                     (frame(Before=[1., np.nan, np.nan]), {"Design": ONE_SAMPLE}, "First")):
            with self.assertRaises(FieldError) as caught:
                analyse(LOGNORMAL, data, options(**changes))
            self.assertEqual(caught.exception.field, field)

    def test_invalid_cells_name_the_column_of_their_role(self):
        data = frame(Before=[3., 5, 0.0, 11], After=[6.3, 9.6, 17.2, 20.9])
        with self.assertRaises(FieldError) as caught:
            analyse(LOGNORMAL, data, options())
        self.assertEqual(caught.exception.field, "First")
        self.assertIn("Source row 2", str(caught.exception))
        for bad in (-1.0, np.inf, "abc"):
            data = frame(Before=[3., 5, 8, 11], After=[6.3, 9.6, bad, 20.9])
            with self.assertRaises(FieldError) as caught:
                analyse(LOGNORMAL, data, options())
            self.assertEqual(caught.exception.field, "Second")
        # A zero on a row without the other measurement never enters a paired analysis.
        self.assertEqual(row(analyse(LOGNORMAL, frame(Before=[3., 5, 8, 0.0], After=[6.3, 9.6, 17.2, np.nan]),
                                     options()))["N first"], 3)

    def test_text_on_a_row_that_is_not_used_is_ignored_but_a_used_row_is_rejected(self):
        data = frame(Before=[3., 5, 8, "x"], After=[6.3, 9.6, 17.2, np.nan])
        self.assertEqual(row(analyse(LOGNORMAL, data, options()))["N first"], 3)
        with self.assertRaises(FieldError) as caught:
            analyse(LOGNORMAL, frame(Before=[3., 5, 8, "x"], After=[6.3, 9.6, 17.2, 1.0]), options())
        self.assertEqual(caught.exception.field, "First")

    def test_hidden_fields_are_not_validated(self):
        # One-sample ignores Second and Pairing correlation; Paired ignores the hypothetical geometric mean.
        row(analyse(LOGNORMAL, frame(), options(Design=ONE_SAMPLE, Second="nothing", **{"Pairing correlation": "x"})))
        row(analyse(LOGNORMAL, frame(), options(**{"Hypothetical geometric mean": -3.0})))
        row(analyse(LOGNORMAL, frame(), {"First": "Before", "Second": "After"}))     # defaults for every other key


class Validation(unittest.TestCase):
    def test_each_option_names_its_own_field(self):
        cases = [({"Design": "Mixed"}, "Design"), ({"Report ratio": "A / B"}, "Report ratio"),
                 ({"Null ratio": True}, "Null ratio"), ({"Null ratio": np.inf}, "Null ratio"),
                 ({"Null ratio": "1"}, "Null ratio"), ({"Confidence level (%)": 100.0}, "Confidence level (%)"),
                 ({"Confidence level (%)": True}, "Confidence level (%)"),
                 ({"Confidence level (%)": float("nan")}, "Confidence level (%)"),
                 ({"Alternative": "Both"}, "Alternative"), ({"Log base": 10}, "Log base"), ({"Log base": "2"}, "Log base"),
                 ({"Graph": "Histogram"}, "Graph"), ({"Pairing correlation": "yes"}, "Pairing correlation"),
                 ({"Design": ONE_SAMPLE, "Hypothetical geometric mean": True}, "Hypothetical geometric mean"),
                 ({"Design": ONE_SAMPLE, "Hypothetical geometric mean": 0.0}, "Hypothetical geometric mean"),
                 ({"First": "Missing"}, "First"), ({"Second": "Before"}, "Second"), ({"Second": None}, "Second"),
                 ({"Design": STUDENT, "Graph": LOG_RATIOS}, "Graph")]
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError) as caught:
                    analyse(LOGNORMAL, frame(), options(**changes))
                self.assertEqual(getattr(caught.exception, "field", None), field, str(caught.exception))

    def test_duplicate_column_names_are_rejected(self):
        data = pd.DataFrame([[1., 2], [2., 3], [3., 5]], columns=["Before", "Before"])
        with self.assertRaises(FieldError):
            analyse(LOGNORMAL, data, options())


class Tables(unittest.TestCase):
    def test_sheets_and_settings(self):
        result = analyse(LOGNORMAL, frame(), options())
        self.assertEqual(list(result.tables), ["Lognormal test", "Log observations", "Paired ratios", "Settings"])
        test = result.tables["Lognormal test"]
        self.assertEqual(list(test.columns), ["N first", "N second", "Mean log ratio", "SE log ratio", "Log lower",
                                              "Log upper", "t", "df", "p", "Geometric ratio", "Lower", "Upper",
                                              "Status", "Reason"])
        ratios = result.tables["Paired ratios"]
        self.assertEqual(list(ratios.columns), ["Source row", "First", "Second", "Log ratio", "Ratio"])
        np.testing.assert_allclose(ratios["Ratio"], np.array(BEFORE) / np.array(AFTER))
        np.testing.assert_allclose(ratios["Log ratio"], np.log10(BEFORE) - np.log10(AFTER))
        settings = result.tables["Settings"]["Value"]
        for key, value in {"Design": "Paired", "First": "Before", "Second": "After", "Report ratio": "First / Second",
                           "Ratio definition": "Before / After", "Null ratio": 1.0, "Log base": "10",
                           "Confidence level (%)": 95.0, "Alternative": "Two-sided",
                           "Hypothetical geometric mean": "Not used", "Pairing correlation": "On"}.items():
            self.assertEqual(settings[key], value, key)
        r = np.corrcoef(np.log(BEFORE), np.log(AFTER))[0, 1]
        self.assertAlmostEqual(settings["Pearson r (log values)"], r, places=12)
        self.assertAlmostEqual(settings["Pearson P (two-sided)"], stats.pearsonr(np.log(BEFORE), np.log(AFTER)).pvalue)

    def test_unpaired_designs_have_no_paired_sheet(self):
        for design in (WELCH, STUDENT, ONE_SAMPLE):
            self.assertNotIn("Paired ratios", analyse(LOGNORMAL, frame(), options(Design=design)).tables)
        self.assertEqual(analyse(LOGNORMAL, frame(), options(Design=ONE_SAMPLE)).tables["Settings"]["Value"][
            "Second"], "Not used")

    def test_pairing_correlation_reports_why_it_cannot_be_estimated(self):
        data = frame(Before=[2., 3], After=[4., 6])
        note = analyse(LOGNORMAL, data, options()).tables["Settings"]["Value"]
        self.assertTrue(np.isnan(note["Pearson r (log values)"]))
        self.assertIn("three", note["Pairing correlation note"])
        constant = analyse(LOGNORMAL, frame(Before=[2., 2, 2, 2], After=[1., 2, 3, 5]), options())
        self.assertIn("constant", constant.tables["Settings"]["Value"]["Pairing correlation note"])
        off = analyse(LOGNORMAL, frame(), options(**{"Pairing correlation": False})).tables["Settings"]["Value"]
        self.assertEqual(off["Pairing correlation"], "Off")
        self.assertNotIn("Pearson r (log values)", off.index)


class Graphs(unittest.TestCase):
    def test_every_graph_choice_draws_or_omits_the_figure(self):
        for design in (PAIRED, WELCH, STUDENT, ONE_SAMPLE):
            for graph in (RATIO_ESTIMATION, LOG_OBSERVATIONS, LOG_RATIOS, NO_GRAPH):
                if graph == LOG_RATIOS and design in (WELCH, STUDENT):
                    continue
                with self.subTest(design=design, graph=graph):
                    result = analyse(LOGNORMAL, frame(), options(Design=design, Graph=graph))
                    self.assertEqual(result.figure is None, graph == NO_GRAPH)

    def test_titles_and_axes_state_the_base_and_the_orientation(self):
        figure = analyse(LOGNORMAL, frame(), options()).figure
        axes = figure.axes[0]
        self.assertIn("log10", axes.get_title())
        self.assertIn("Before / After", axes.get_title())
        self.assertEqual(axes.get_xscale(), "log")
        reference = [line for line in axes.lines if line.get_gid() == "lognormal:reference"]
        self.assertEqual([line.get_xdata()[0] for line in reference], [1.0])
        figure = analyse(LOGNORMAL, frame(), options(**{"Log base": BASE_E, "Report ratio": SECOND_OVER_FIRST,
                                                        "Graph": LOG_RATIOS})).figure
        axes = figure.axes[0]
        self.assertIn("ln", axes.get_title())
        self.assertIn("After / Before", axes.get_ylabel())
        # The null ratio is the horizontal reference on the chosen log scale.
        line = next(line for line in axes.lines if line.get_gid() == "lognormal:reference")
        self.assertAlmostEqual(line.get_ydata()[0], 0.0)

    def test_log_observations_join_the_pairs_by_row(self):
        axes = analyse(LOGNORMAL, frame(), options(Graph=LOG_OBSERVATIONS)).figure.axes[0]
        pairs = [line for line in axes.lines if str(line.get_gid()).startswith("lognormal:pair:")]
        self.assertEqual(len(pairs), 5)
        np.testing.assert_allclose([line.get_ydata()[0] for line in pairs], np.log10(BEFORE))
        np.testing.assert_allclose([line.get_ydata()[1] for line in pairs], np.log10(AFTER))

    def test_inference_unavailable_still_draws_the_point(self):
        before = np.array([0.1, 0.7, 1.3])
        figure = analyse(LOGNORMAL, frame(Before=before, After=before * 2), options()).figure
        axes = figure.axes[0]
        self.assertTrue(any(c.get_gid() == "lognormal:estimate" for c in axes.collections + axes.lines))


class Contract(unittest.TestCase):
    def test_direct_call_matches_the_dispatcher(self):
        a = lognormal_test(frame(), options()).tables["Lognormal test"]
        b = analyse(LOGNORMAL, frame(), options()).tables["Lognormal test"]
        pd.testing.assert_frame_equal(a, b)


if __name__ == "__main__":
    unittest.main()
