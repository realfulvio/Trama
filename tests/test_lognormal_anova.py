"""Lognormal one-way ANOVA: logs, geometric summaries, ratio orientation, and an unchanged Normal path."""
import unittest
from math import log

import numpy as np
import pandas as pd
from scipy import stats

from analisi import inference, trend_anova, unequal_anova, variance_assumptions
from analisi.field_error import FieldError
from analisi.lognormal_anova import (
    AVAILABLE, DISTRIBUTION, FIRST_OVER_SECOND, LOGNORMAL, NORMAL, RATIO_DIRECTION, SECOND_OVER_FIRST,
    SETTINGS, SUMMARY, UNREPRESENTABLE, format_error,
)
from analisi.trend_anova import TREND
from analisi.workbench import analyse

LEVEL = unequal_anova.LEVEL
FAMILY, CONTROL, PAIRS = unequal_anova.FAMILY, unequal_anova.CONTROL, unequal_anova.PAIRS
ALL, VERSUS, SELECTED = unequal_anova.ALL_PAIRS, unequal_anova.VERSUS_CONTROL, unequal_anova.PAIRS


def frame_a():
    # Blocked groups: A is 1, 2, 4; B is 8, 16, 32; C is 64, 128, 256.
    return pd.DataFrame({
        "Y": [1, 2, 4, 8, 16, 32, 64, 128, 256],
        "Group": ["A", "A", "A", "B", "B", "B", "C", "C", "C"],
    })


def frame_b():
    return pd.DataFrame({
        "Y": [1, 2, 4, 8, 2, 8, 32, 4, 8, 16, 32, 64],
        "Group": ["A"] * 4 + ["B"] * 3 + ["C"] * 5,
    })


def options(**updates):
    base = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "None",
            DISTRIBUTION: LOGNORMAL, LEVEL: 95, RATIO_DIRECTION: SECOND_OVER_FIRST}
    base.update(updates)
    return base


def logs_of(frame):
    """Independent natural logs, not the centered helper under test."""
    logged = frame.copy()
    logged["Y"] = np.log(frame["Y"].to_numpy(dtype=float))
    return logged


def engine(frame, *, logged=True, **updates):
    """The shared ANOVA engine. ``logged`` is the independent log reference; Normal recipes pass the raw frame."""
    recipe = options(**updates)
    label = recipe["Post-hoc"]
    key = {"None": None, "Tukey": "tukey", "Dunnett": "dunnett", "Games–Howell": "games-howell",
           "Tamhane T2": "tamhane", "Dunnett T3": "dunnett-t3", "Holm": "holm", "Bonferroni": "bonferroni",
           "FDR (Benjamini–Hochberg)": "fdr_bh"}[label]
    data = logs_of(frame) if logged else frame
    return inference.one_way_anova(
        data, "Y", "Group", method=unequal_anova.METHOD_KEYS[recipe["Method"]],
        posthoc=key, level=recipe[LEVEL], family=recipe)


class LognormalAnovaTests(unittest.TestCase):
    def test_ordinary_matches_closed_form_and_log_sums_of_squares(self):
        result = analyse("One-way ANOVA", frame_a(), options())
        row = result.tables["ANOVA"].iloc[0]
        np.testing.assert_allclose([row["F"], row["F df1"], row["F df2"], row["p"]], [27, 2, 6, 0.001])
        ln2 = log(2)
        np.testing.assert_allclose(result.tables["ANOVA"].loc["Group", "SS"], 54 * ln2 * ln2)
        np.testing.assert_allclose(result.tables["ANOVA"].loc["Residual", "SS"], 6 * ln2 * ln2)
        self.assertEqual(result.tables["ANOVA"]["Scale"].iloc[0], "Natural logarithms")
        summary = result.tables[SUMMARY]
        self.assertEqual(summary["Group"].tolist(), ["A", "B", "C"])
        np.testing.assert_allclose(summary["Geometric mean"], [2, 16, 128])
        np.testing.assert_allclose(summary["Geometric SD"], [2, 2, 2])
        np.testing.assert_allclose(np.exp(summary["Log mean"]), summary["Geometric mean"])
        self.assertIn("Value", result.tables[SETTINGS].columns)
        self.assertEqual(result.tables[SETTINGS].loc["Distribution", "Value"], LOGNORMAL)
        self.assertIsNone(result.figure)

    def test_group_order_is_first_appearance(self):
        frame = pd.DataFrame({"Y": [64, 128, 256, 1, 2, 4], "Group": ["C", "C", "C", "A", "A", "A"]})
        summary = analyse("One-way ANOVA", frame, options()).tables[SUMMARY]
        self.assertEqual(summary["Group"].tolist(), ["C", "A"])

    def test_welch_brown_and_joint_match_the_log_engine(self):
        for method, row in (("Welch", 0), ("Welch and Brown–Forsythe", 0)):
            got = analyse("One-way ANOVA", frame_b(), options(Method=method)).tables["ANOVA"]
            ref = engine(frame_b(), Method=method)["ANOVA"].loc[:, ["F", "F df1", "F df2", "p"]]
            # Welch is the first row. The joint sheet adds the original F* underneath.
            np.testing.assert_allclose(got.iloc[row][["F", "F df1", "F df2", "p"]].astype(float),
                                       ref.iloc[row].astype(float))
        joint = analyse("One-way ANOVA", frame_b(), options(Method="Welch and Brown–Forsythe")).tables["ANOVA"]
        ref = engine(frame_b(), Method="Welch and Brown–Forsythe")["ANOVA"]
        self.assertEqual(len(joint), 2)
        np.testing.assert_allclose(joint.iloc[1][["F", "F df1", "F df2", "p"]].astype(float),
                                   ref.iloc[1][["F", "F df1", "F df2", "p"]].astype(float))
        self.assertIn("Brown–Forsythe", joint.iloc[1]["Method"])

    def test_posthoc_p_values_match_independent_logs_and_reciprocal_bounds(self):
        designs = (
            ("Ordinary", "Tukey", {}),
            ("Ordinary", "Dunnett", {FAMILY: VERSUS, CONTROL: "A"}),
            ("Ordinary", "Holm", {}),
            ("Ordinary", "Bonferroni", {}),
            ("Ordinary", "FDR (Benjamini–Hochberg)", {}),
            ("Welch", "Games–Howell", {}),
            ("Welch", "Tamhane T2", {}),
            ("Welch", "Dunnett T3", {}),
            ("Welch and Brown–Forsythe", "Games–Howell", {FAMILY: ALL}),
            ("Welch", "Tamhane T2", {FAMILY: VERSUS, CONTROL: "A"}),
            ("Welch", "Dunnett T3", {FAMILY: SELECTED, PAIRS: [("A", "C"), ("B", "C")]}),
            ("Ordinary", "Tukey", {}),
        )
        self.assertGreaterEqual(len(designs), 11)
        for method, posthoc, family in designs:
            recipe = options(Method=method, **{"Post-hoc": posthoc}, **family)
            got = analyse("One-way ANOVA", frame_b(), recipe).tables["Multiple comparisons"]
            ref = engine(frame_b(), Method=method, **{"Post-hoc": posthoc}, **family)["Multiple comparisons"].reset_index()
            np.testing.assert_allclose(got["Adjusted p"], ref["Adjusted p"], rtol=1e-8, atol=1e-12)
            np.testing.assert_allclose(got["Log difference"], ref["Difference"], rtol=1e-8, atol=1e-12)
            flipped = analyse("One-way ANOVA", frame_b(), {**recipe, RATIO_DIRECTION: FIRST_OVER_SECOND})
            other = flipped.tables["Multiple comparisons"]
            np.testing.assert_allclose(got["Adjusted p"], other["Adjusted p"])
            np.testing.assert_allclose(got["Ratio"].to_numpy() * other["Ratio"].to_numpy(), np.ones(len(got)))
            if posthoc in {"Holm", "Bonferroni", "FDR (Benjamini–Hochberg)"}:
                self.assertTrue(got["Ratio CI low"].isna().all())
                self.assertTrue(got["Ratio CI high"].isna().all())
                self.assertNotIn("CI low", got.columns)
                self.assertTrue(got["Ratio reason"].str.contains("does not produce an interval").all())
                self.assertFalse(got["Ratio reason"].str.contains("Simultaneous").any())
                np.testing.assert_allclose(got["p"], ref["p"])
            else:
                np.testing.assert_allclose(
                    got["Ratio CI low"].to_numpy() * other["Ratio CI high"].to_numpy(), np.ones(len(got)))
                self.assertTrue((got["Ratio status"] == AVAILABLE).all())

    def test_tukey_and_games_howell_honor_90_and_99_and_can_cover_one(self):
        close = pd.DataFrame({"Y": [1.0, 1.1, 0.9, 1.2, 1.05, 0.95, 2.0, 2.2, 1.8],
                              "Group": ["A", "A", "A", "B", "B", "B", "C", "C", "C"]})
        for method, posthoc in (("Ordinary", "Tukey"), ("Welch", "Games–Howell")):
            narrow = analyse("One-way ANOVA", frame_a(), options(
                Method=method, **{"Post-hoc": posthoc, LEVEL: 90})).tables["Multiple comparisons"]
            wide = analyse("One-way ANOVA", frame_a(), options(
                Method=method, **{"Post-hoc": posthoc, LEVEL: 99})).tables["Multiple comparisons"]
            ref = engine(frame_a(), Method=method, **{"Post-hoc": posthoc})["Multiple comparisons"].reset_index()
            np.testing.assert_allclose(narrow["Adjusted p"], ref["Adjusted p"], rtol=1e-8, atol=1e-12)
            count = frame_a()["Group"].nunique()
            for level, table in ((90, narrow), (99, wide)):
                critical = stats.studentized_range.ppf(level / 100, count, ref["df"].to_numpy(dtype=float))
                half = critical * ref["SE"].to_numpy(dtype=float) / np.sqrt(2)
                # Default direction is Second / First, so the ratio interval flips the contrast.
                low = np.exp(-(ref["Difference"].to_numpy(dtype=float) + half))
                high = np.exp(-(ref["Difference"].to_numpy(dtype=float) - half))
                np.testing.assert_allclose(table["Ratio CI low"], np.minimum(low, high), rtol=1e-7, atol=1e-12)
                np.testing.assert_allclose(table["Ratio CI high"], np.maximum(low, high), rtol=1e-7, atol=1e-12)
            self.assertTrue((narrow["Ratio CI high"] - narrow["Ratio CI low"]
                             < wide["Ratio CI high"] - wide["Ratio CI low"]).all())
            covered = analyse("One-way ANOVA", close, options(
                Method=method, **{"Post-hoc": posthoc, LEVEL: 95, RATIO_DIRECTION: FIRST_OVER_SECOND}))
            rows = covered.tables["Multiple comparisons"]
            self.assertTrue(((rows["Ratio CI low"] < 1) & (rows["Ratio CI high"] > 1)).any())

    def test_domain_edges_keep_the_source_and_name_the_field(self):
        original = frame_a()
        before = original.copy(deep=True)
        zero = original.copy()
        zero.loc[0, "Y"] = 0
        with self.assertRaises(FieldError) as raised:
            analyse("One-way ANOVA", zero, options())
        self.assertEqual(raised.exception.field, "Response")
        pd.testing.assert_frame_equal(zero, zero.copy())
        pd.testing.assert_frame_equal(original, before)
        unused = pd.concat([original, pd.DataFrame({"Y": [0.0], "Group": [None]})], ignore_index=True)
        snapshot = unused.copy(deep=True)
        np.testing.assert_allclose(analyse("One-way ANOVA", unused, options()).tables["ANOVA"].iloc[0]["F"], 27)
        pd.testing.assert_frame_equal(unused, snapshot)
        masked = original.copy()
        masked.loc[0, "Y"] = np.nan
        self.assertEqual(analyse("One-way ANOVA", masked, options()).tables[SUMMARY]["N"].tolist(), [2, 3, 3])

    def test_typed_labels_constant_groups_singleton_and_tiny_effects(self):
        typed = frame_a().copy()
        labels = {"A": 1, "B": "1", "C": True}
        typed["Group"] = pd.Series([labels[value] for value in typed["Group"]], dtype=object)
        summary = analyse("One-way ANOVA", typed, options()).tables[SUMMARY]
        self.assertEqual(len({(type(value).__name__, str(value)) for value in summary["Group"]}), 3)
        # Every observation equal: the shared engine rejects a residual sum of squares of zero.
        # Distinct constant groups are not that case. Their log residual is float dust, and the
        # existing check is exactly ``residual_ss <= 0``, the same as independent logs.
        flat = pd.DataFrame({"Y": [4, 4, 4, 4], "Group": ["A", "A", "B", "B"]})
        with self.assertRaises(ValueError):
            analyse("One-way ANOVA", flat, options())
        mixed = pd.DataFrame({"Y": [2, 2, 2, 4, 8, 10], "Group": ["A", "A", "A", "B", "B", "B"]})
        ordinary = analyse("One-way ANOVA", mixed, options())
        self.assertEqual(ordinary.tables[SUMMARY].loc[0, "Geometric SD"], 1)
        with self.assertRaises(FieldError) as welch_error:
            analyse("One-way ANOVA", mixed, options(Method="Welch"))
        self.assertEqual(welch_error.exception.field, "Response")
        singleton = pd.DataFrame({"Y": [2, 4, 8, 16], "Group": ["A", "B", "B", "B"]})
        one = analyse("One-way ANOVA", singleton, options())
        self.assertEqual(one.tables[SUMMARY]["N"].tolist(), [1, 3])
        self.assertTrue(np.isnan(one.tables[SUMMARY].loc[0, "Geometric SD"]))
        with self.assertRaises(FieldError):
            analyse("One-way ANOVA", singleton, options(Method="Welch"))
        close = pd.DataFrame({
            "Y": [1, 1 + 1e-8, 1 + 2e-8, 2, 2 + 1e-8, 2 + 2e-8],
            "Group": ["A", "A", "A", "B", "B", "B"],
        })
        statistic = analyse("One-way ANOVA", close, options()).tables["ANOVA"].iloc[0]["F"]
        self.assertTrue(np.isfinite(statistic) and statistic > 10)

    def test_extreme_scales_keep_ratios_and_disclose_unrepresentable_ones(self):
        base = analyse("One-way ANOVA", frame_a(), options(**{"Post-hoc": "Tukey"}))
        ratios = base.tables["Multiple comparisons"]["Ratio"].to_numpy()
        for factor in (1e-200, 1e200):
            scaled = frame_a()
            scaled["Y"] = scaled["Y"] * factor
            got = analyse("One-way ANOVA", scaled, options(**{"Post-hoc": "Tukey"}))
            np.testing.assert_allclose(got.tables["ANOVA"].iloc[0][["F", "p"]].astype(float), [27, 0.001])
            np.testing.assert_allclose(got.tables["Multiple comparisons"]["Ratio"], ratios)
        huge = pd.DataFrame({"Y": [1e-300, 2e-300, 4e-300, 1e300, 2e300, 4e300], "Group": ["A"] * 3 + ["B"] * 3})
        for direction in DIRECTIONS:
            row = analyse("One-way ANOVA", huge, options(**{
                "Post-hoc": "Tukey", RATIO_DIRECTION: direction})).tables["Multiple comparisons"].iloc[0]
            self.assertTrue(np.isfinite(row["Log ratio"]))
            self.assertTrue(pd.isna(row["Ratio"]))
            self.assertEqual(row["Ratio status"], UNREPRESENTABLE)
            self.assertIn("Ratio", row["Ratio reason"])
            self.assertNotEqual(row["Ratio"], 0)
        # 1e300 / 1e-300 is 1e600. Build the threshold as 600*ln(10): float(1e600) is already infinity.
        np.testing.assert_allclose(abs(analyse(
            "One-way ANOVA", huge, options(**{"Post-hoc": "Tukey"})).tables["Multiple comparisons"].iloc[0]["Log ratio"]),
            600 * log(10), rtol=1e-8)

    def test_representable_subnormal_means_and_ratio_intervals_are_retained(self):
        # IEEE subnormals are positive finite values, not underflow to zero.
        scaled = frame_a()
        scaled["Y"] = scaled["Y"] * 1e-310
        result = analyse("One-way ANOVA", scaled, options())
        means = result.tables[SUMMARY]["Geometric mean"].to_numpy()
        self.assertTrue(np.isfinite(means).all())
        np.testing.assert_allclose(means / 1e-310, [2, 16, 128], rtol=1e-10)
        frame = pd.DataFrame({"Y": [1, 2, 4, 1e-310, 2e-310, 4e-310],
                              "Group": ["A"] * 3 + ["B"] * 3})
        row = analyse("One-way ANOVA", frame, options(**{
            "Post-hoc": "Tukey"})).tables["Multiple comparisons"].iloc[0]
        self.assertEqual(row["Ratio status"], AVAILABLE)
        self.assertAlmostEqual(row["Ratio"] / 1e-310, 1, places=10)
        self.assertGreater(row["Ratio CI low"], 0)
        self.assertLess(row["Ratio CI low"], row["Ratio"])
        self.assertGreater(row["Ratio CI high"], row["Ratio"])

    def test_variance_checks_use_logs_and_trend_or_repeated_measures_are_refused(self):
        recipe = options(**{"Brown–Forsythe variance test": True, "Bartlett variance test": True})
        tables = analyse("One-way ANOVA", frame_b(), recipe).tables
        logged = logs_of(frame_b())
        reference = variance_assumptions.sheets(logged, "Y", "Group", recipe)
        np.testing.assert_allclose(tables["Variance assumptions"]["Statistic"], reference["Variance assumptions"]["Statistic"])
        self.assertIn("natural logarithms", tables["Variance assumptions"]["Note"].iloc[0])
        self.assertNotIn("F*", tables["Variance assumptions"]["Test"].iloc[0])
        self.assertIn("Log SD", tables["Variance groups"].columns)
        with self.assertRaises(FieldError) as trend_error:
            analyse("One-way ANOVA", frame_a(), options(**{TREND: True, "Trend group order": [
                {"kind": "text", "value": "A"}, {"kind": "text", "value": "B"}, {"kind": "text", "value": "C"}]}))
        self.assertEqual(trend_error.exception.field, TREND)
        self.assertIn("not available", format_error(trend_error.exception))
        legacy = FieldError(TREND, "Il trend lineare richiede un'ANOVA ordinaria su gruppi indipendenti.")
        self.assertIsNone(format_error(legacy))
        normal = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "None",
                  TREND: True, "Trend group order": [
                      {"kind": "text", "value": name} for name in ("A", "B", "C")]}
        kept = analyse("One-way ANOVA", frame_a(), normal)
        explicit = analyse("One-way ANOVA", frame_a(), {**normal, DISTRIBUTION: NORMAL, RATIO_DIRECTION: "garbage"})
        self.assertEqual(list(kept.tables), list(explicit.tables))
        for name in kept.tables:
            pd.testing.assert_frame_equal(kept.tables[name], explicit.tables[name])
        self.assertIn(trend_anova.SHEET, kept.tables)
        with self.assertRaises(FieldError) as repeated:
            analyse("Repeated measures ANOVA", frame_a(), {
                "Response": "Y", "Factors": ["Group"], "Subject": "Group",
                "Sphericity correction": "None", DISTRIBUTION: LOGNORMAL})
        self.assertEqual(repeated.exception.field, DISTRIBUTION)

    def test_at_least_twenty_normal_recipes_match_the_base_engine(self):
        frame = frame_b()
        recipes = []
        for method, posthoc, extra in (
            ("Ordinary", "None", {}),
            ("Ordinary", "Tukey", {}),
            ("Ordinary", "Dunnett", {FAMILY: VERSUS, CONTROL: "A"}),
            ("Ordinary", "Holm", {}),
            ("Ordinary", "Bonferroni", {}),
            ("Ordinary", "FDR (Benjamini–Hochberg)", {}),
            ("Welch", "None", {}),
            ("Welch", "Games–Howell", {}),
            ("Welch", "Tamhane T2", {}),
            ("Welch", "Dunnett T3", {}),
            ("Welch", "Holm", {LEVEL: 90}),
            ("Welch", "Games–Howell", {FAMILY: VERSUS, CONTROL: "B"}),
            ("Welch", "Tamhane T2", {FAMILY: SELECTED, PAIRS: [("A", "B")]}),
            ("Welch and Brown–Forsythe", "None", {}),
            ("Welch and Brown–Forsythe", "Games–Howell", {}),
            ("Welch and Brown–Forsythe", "Dunnett T3", {FAMILY: ALL, LEVEL: 99}),
            ("Ordinary", "Tukey", {LEVEL: 99, RATIO_DIRECTION: "garbage"}),
            ("Ordinary", "None", {DISTRIBUTION: NORMAL}),
            ("Welch", "Bonferroni", {DISTRIBUTION: NORMAL, RATIO_DIRECTION: SECOND_OVER_FIRST}),
            ("Ordinary", "Dunnett", {FAMILY: VERSUS, CONTROL: "C", LEVEL: 80}),
            ("Welch", "Dunnett T3", {FAMILY: SELECTED, PAIRS: [("C", "A"), ("C", "B")], LEVEL: 90}),
        ):
            recipe = {"Response": "Y", "Group": "Group", "Method": method, "Post-hoc": posthoc, **extra}
            recipes.append(recipe)
        self.assertGreaterEqual(len(recipes), 20)
        for recipe in recipes:
            got = analyse("One-way ANOVA", frame, recipe)
            self.assertNotIn(SUMMARY, got.tables)
            ref = engine(frame, logged=False, **{DISTRIBUTION: NORMAL, **recipe})
            pd.testing.assert_frame_equal(got.tables["ANOVA"], ref["ANOVA"])
            if "Multiple comparisons" in ref:
                pd.testing.assert_frame_equal(got.tables["Multiple comparisons"], ref["Multiple comparisons"])


DIRECTIONS = (FIRST_OVER_SECOND, SECOND_OVER_FIRST)


if __name__ == "__main__":
    unittest.main()
