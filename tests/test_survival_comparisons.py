import io
import unittest

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.duration.survfunc import survdiff

from analisi import survival
from analisi.stats import survival_comparisons, survival_median
from analisi.workbench import analyse, check_survival_options, survival_levels

FIXTURE = """Group,Time,Event
Low,1,1
Low,2,1
Low,2,0
Low,5,1
Mid,2,1
Mid,3,0
Mid,4,1
Mid,7,1
High,2,0
High,4,1
High,6,0
High,8,1
"""
KM = "Kaplan–Meier survival"
BASE = {"Time": "Time", "Event": "Event", "Group": "Group"}


def fixture():
    return pd.read_csv(io.StringIO(FIXTURE))


class EngineTests(unittest.TestCase):
    def test_global_weighted_and_trend_oracles(self):
        results = survival_comparisons(fixture(), "Time", "Event", "Group", gbw=True,
                                       trend_order=["Low", "Mid", "High"])
        gbw = results["gbw"]
        self.assertAlmostEqual(gbw["χ²"], 3.042388077250948, places=12)
        self.assertAlmostEqual(gbw["p"], 0.21845089236116377, places=12)
        self.assertEqual(gbw["df"], 2)
        np.testing.assert_allclose(gbw["score"], [14, 1, -15])
        trend = results["trend"]
        self.assertAlmostEqual(trend["z"], -1.8903730248081347, places=12)
        self.assertAlmostEqual(trend["χ²"], 3.5735101729222567, places=12)
        self.assertAlmostEqual(trend["p"], 0.05870808851267926, places=12)

    def test_weighted_test_matches_statsmodels(self):
        data = fixture()
        expected, _ = survdiff(data["Time"], data["Event"], data["Group"], weight_type="gb")
        got = survival_comparisons(data, "Time", "Event", "Group", gbw=True)["gbw"]["χ²"]
        self.assertAlmostEqual(got, expected, places=10)

    def test_trend_order_reversal_and_row_shuffle(self):
        data = fixture()
        forward = survival_comparisons(data, "Time", "Event", "Group", trend_order=["Low", "Mid", "High"])["trend"]
        reverse = survival_comparisons(data, "Time", "Event", "Group", trend_order=["High", "Mid", "Low"])["trend"]
        self.assertAlmostEqual(reverse["z"], -forward["z"])
        self.assertAlmostEqual(reverse["χ²"], forward["χ²"])
        shuffled = data.sample(frac=1, random_state=3).reset_index(drop=True)
        mixed = survival_comparisons(shuffled, "Time", "Event", "Group", trend_order=["Low", "High", "Mid"])["trend"]
        self.assertAlmostEqual(mixed["z"], -0.558585529567015, places=12)
        self.assertAlmostEqual(mixed["χ²"], 0.3120177938416626, places=12)
        self.assertAlmostEqual(mixed["p"], 0.5764446179557348, places=12)
        # Event and censoring at the same time must not depend on row order.
        swapped = data.iloc[[0, 2, 1, *range(3, 12)]]
        again = survival_comparisons(swapped, "Time", "Event", "Group", gbw=True,
                                     trend_order=["Low", "Mid", "High"])
        self.assertAlmostEqual(again["gbw"]["χ²"], 3.042388077250948, places=12)
        self.assertAlmostEqual(again["trend"]["z"], forward["z"])

    def test_trend_requires_complete_order(self):
        data = fixture()
        for order, text in ((["Low", "Mid"], "not in the trend order"),
                            (["Low", "Mid", "High", "Other"], "missing from this analysis"),
                            (["Low", "Low", "High"], "repeats")):
            note = survival_comparisons(data, "Time", "Event", "Group", trend_order=order)["trend"]
            self.assertFalse(note["available"])
            self.assertIn(text, note["note"])
        two = data[data["Group"] != "Mid"]
        self.assertFalse(survival_comparisons(two, "Time", "Event", "Group",
                                              trend_order=["Low", "High"])["trend"]["available"])

    def test_numeric_looking_group_names_match_as_text(self):
        data = fixture().replace({"Low": 10, "Mid": 2, "High": 1})
        out = survival_comparisons(data, "Time", "Event", "Group", trend_order=["10", "2", "1"])["trend"]
        self.assertAlmostEqual(out["z"], -1.8903730248081347, places=12)

    def test_median_modes_and_intervals(self):
        curves, _ = survival(fixture(), "Time", "Event", "Group")
        got = {label: survival_median(curve) for label, curve in curves.items()}
        self.assertEqual(got, {"Low": (2, 1, 5), "Mid": (4, 2, 7), "High": (8, 4, 8)})
        plateau = pd.DataFrame({"T": [1, 2, 4, 5], "E": [1, 1, 0, 1]})
        curve = survival(plateau, "T", "E")[0]["All"]
        self.assertEqual(survival_median(curve)[0], 2)
        self.assertEqual(survival_median(curve, plateau=True)[0], 3)
        sparse = pd.DataFrame({"T": [1, 2, 3, 4, 5], "E": [1, 0, 0, 0, 0]})
        median, _, upper = survival_median(survival(sparse, "T", "E")[0]["All"])
        self.assertTrue(np.isnan(median) and np.isnan(upper))

    def test_level_changes_band_names_and_width(self):
        data = fixture()
        c95 = survival(data, "Time", "Event", "Group")[0]["Low"]
        c90 = survival(data, "Time", "Event", "Group", level=90.)[0]["Low"]
        self.assertIn("CI 95% low", c95)
        self.assertNotIn("CI 95% low", c90)
        self.assertGreater(c90["CI 90% low"].iloc[0], c95["CI 95% low"].iloc[0])
        with self.assertRaises(ValueError):
            survival(data, "Time", "Event", "Group", level=100.)

    def test_hazard_ratio_oracles_and_reciprocals(self):
        two = fixture()[lambda d: d["Group"].isin(["Low", "High"])]
        rows = survival_comparisons(two, "Time", "Event", "Group", hazard=True,
                                    hazard_numerator="Low")["hazard"]["rows"]
        mh, oe = rows
        self.assertAlmostEqual(mh["Expected numerator"], 1.5119047619047619)
        self.assertAlmostEqual(mh["Expected denominator"], 3.488095238095238)
        np.testing.assert_allclose([mh["HR"], mh["Lower"], mh["Upper"]],
                                   [5.18098150, 0.65987401, 40.67832473], rtol=1e-7)
        np.testing.assert_allclose([oe["HR"], oe["Lower"], oe["Upper"]],
                                   [3.46062992, 0.51325553, 23.33332770], rtol=1e-7)
        for row in rows:
            self.assertAlmostEqual(row["Inverse HR"], 1 / row["HR"])
            self.assertAlmostEqual(row["Inverse lower"], 1 / row["Upper"])
            self.assertAlmostEqual(row["Inverse upper"], 1 / row["Lower"])
        flipped = survival_comparisons(two, "Time", "Event", "Group", hazard=True,
                                       hazard_numerator="High")["hazard"]["rows"]
        self.assertAlmostEqual(flipped[1]["HR"], 1 / oe["HR"])

    def test_hazard_ratio_unavailable_cases(self):
        data = fixture()
        self.assertFalse(survival_comparisons(data, "Time", "Event", "Group", hazard=True)["hazard"]["available"])
        no_events = pd.DataFrame({"Time": [1, 2, 3, 4, 5, 6], "Event": [1, 1, 1, 0, 0, 0],
                                  "Group": list("AAABBB")})
        rows = survival_comparisons(no_events, "Time", "Event", "Group", hazard=True,
                                    hazard_numerator="A")["hazard"]["rows"]
        self.assertEqual([row["Status"] for row in rows], ["Estimated", "Not available"])

    def test_unrepresentable_inverse_hazard_limit(self):
        data = pd.DataFrame({"Time": [1] + [2] * 680, "Event": [1] + [0] * 680, "Group": ["A"] + ["B"] * 680})
        rows = survival_comparisons(data, "Time", "Event", "Group", hazard=True,
                                    hazard_numerator="B")["hazard"]["rows"]
        self.assertEqual(rows[0]["Status"], "Not available")

    def test_censored_only_and_unshared_groups_stay_unavailable_without_failing(self):
        censored = pd.DataFrame({"Time": [1, 2, 3, 4], "Event": [0, 0, 0, 0], "Group": list("AABB")})
        results = survival_comparisons(censored, "Time", "Event", "Group", gbw=True, hazard=True,
                                       trend_order=["A", "B"])
        self.assertTrue(all(not value["available"] for value in results.values()))
        # Group C is only observed before the first event: no joint information.
        apart = pd.DataFrame({"Time": [.1, .2, 1, 2, 3, 4, 5, 6], "Event": [0, 0, 1, 1, 1, 0, 1, 1],
                              "Group": list("CCAAABBB")})
        out = survival_comparisons(apart, "Time", "Event", "Group", gbw=True, trend_order=["C", "A", "B"])
        self.assertFalse(out["gbw"]["available"])
        self.assertFalse(out["trend"]["available"])
        result = analyse(KM, apart, {**BASE, "Gehan–Breslow–Wilcoxon": True, "Pairwise correction": "Holm"})
        self.assertEqual(result.tables["Log-rank test"].at["Status", "Value"], "Not available")
        self.assertEqual(result.tables["Gehan–Breslow–Wilcoxon test"].at["Status", "Value"], "Not available")
        self.assertIn("Curve: C", result.tables)
        self.assertEqual(result.tables["Pairwise log-rank"]["p"].notna().sum(), 1)
        with self.assertRaisesRegex(ValueError, "singular"):
            survival(apart, "Time", "Event", "Group")


class DispatcherTests(unittest.TestCase):
    def options(self, **extra):
        return {**BASE, **extra}

    def test_control_families_apply_holm_sidak_before_significance(self):
        from math import expm1, log1p

        options = {**BASE, "Pairwise correction": "Holm–Šídák", "Pairwise control group": "Mid"}
        got = analyse(KM, fixture(), options).tables["Pairwise log-rank"]
        self.assertEqual(got.index.tolist(), ["Mid / Low", "Mid / High"])
        raw = got["p"].sort_values()
        lower, higher = raw
        correction = -expm1(2 * log1p(-lower))
        expected = pd.Series([correction, max(correction, higher)], index=raw.index)
        np.testing.assert_allclose(got["Adjusted p"], expected.reindex(got.index))
        alpha = (lower + correction) / 2
        raw_display = analyse(KM, fixture(), {**options, "Show adjusted pairwise p": False,
                                             "Pairwise alpha": alpha}).tables["Pairwise log-rank"]
        self.assertNotIn("Adjusted p", raw_display)
        np.testing.assert_allclose(raw_display["p"], got["p"])
        self.assertFalse(bool(raw_display["Significant"].loc[raw.index[0]]))

    def test_unknown_control_is_a_field_error(self):
        from analisi.field_error import FieldError

        with self.assertRaises(FieldError) as context:
            analyse(KM, fixture(), {**BASE, "Pairwise correction": "Holm–Šídák",
                                    "Pairwise control group": "Unknown"})
        self.assertEqual(context.exception.field, "Pairwise control group")

    def test_old_options_keep_log_rank_and_add_median_interval(self):
        result = analyse(KM, fixture(), self.options())
        self.assertEqual(set(result.tables) - {"Curve: Low", "Curve: Mid", "Curve: High"},
                         {"Survival summary", "Number at risk", "Log-rank test"})
        summary = result.tables["Survival summary"]
        self.assertEqual(summary["Median CI lower"].tolist(), [1, 2, 4])
        self.assertEqual(summary["Median CI upper"].tolist(), [5, 7, 8])
        self.assertEqual(summary["Median CI level (%)"].tolist(), [95, 95, 95])
        self.assertIn("CI 95% low", result.tables["Curve: Low"])
        self.assertAlmostEqual(result.tables["Log-rank test"].at["Log-rank χ²", "Value"], 3.5739106864304095)

    def test_additional_sheets(self):
        result = analyse(KM, fixture(), self.options(**{
            "Gehan–Breslow–Wilcoxon": True, "Log-rank trend": True, "Trend group order": ["Low", "Mid", "High"],
            "Hazard ratio": True}))
        self.assertAlmostEqual(result.tables["Gehan–Breslow–Wilcoxon test"].at["p", "Value"],
                               0.21845089236116377)
        trend = result.tables["Log-rank trend"]
        self.assertEqual(trend.at["Group order", "Value"], "Low → Mid → High")
        self.assertAlmostEqual(trend.at["z", "Value"], -1.8903730248081347)
        self.assertEqual(result.tables["Hazard ratio"]["Status"].tolist(), ["Not available"] * 2)

    def test_hazard_ratio_sheet_for_two_groups(self):
        two = fixture()[lambda d: d["Group"] != "Mid"]
        table = analyse(KM, two, self.options(**{"Hazard ratio": True, "Hazard ratio numerator": "Low",
                                                 "Confidence level (%)": 95.})).tables["Hazard ratio"]
        self.assertEqual(table["Orientation"].tolist(), ["Low / High"] * 2)
        self.assertAlmostEqual(table.at["Mantel–Haenszel", "HR"], 5.18098150, places=7)
        self.assertAlmostEqual(table.at["Log-rank O/E", "Inverse HR"], 1 / 3.46062992, places=7)

    def test_level_and_plateau_options(self):
        result = analyse(KM, fixture(), self.options(**{"Confidence level (%)": 90.}))
        self.assertIn("CI 90% low", result.tables["Curve: Low"])
        self.assertEqual(result.tables["Survival summary"]["Median CI level (%)"].tolist(), [90] * 3)
        data = pd.DataFrame({"T": [1, 2, 4, 5], "E": [1, 1, 0, 1]})
        medians = [analyse(KM, data, {"Time": "T", "Event": "E", "Median method": method})
                   .tables["Survival summary"]["Median survival"].iloc[0]
                   for method in ("First time with S ≤ 0.5", "Midpoint of recorded 50% plateau")]
        self.assertEqual(medians, [2, 3])

    def test_incomplete_trend_order_is_an_error(self):
        options = self.options(**{"Log-rank trend": True, "Trend group order": ["Low", "Mid"]})
        with self.assertRaisesRegex(ValueError, "Trend group order.*missing High"):
            analyse(KM, fixture(), options)
        with self.assertRaisesRegex(ValueError, "Trend group order"):
            analyse(KM, fixture(), self.options(**{"Log-rank trend": True}))
        two = fixture()[lambda d: d["Group"] != "Mid"]
        with self.assertRaisesRegex(ValueError, "three groups"):
            analyse(KM, two, self.options(**{"Log-rank trend": True, "Trend group order": ["Low", "High"]}))
        with self.assertRaisesRegex(ValueError, "numerator"):
            analyse(KM, fixture(), self.options(**{"Hazard ratio": True, "Hazard ratio numerator": "Nope"}))

    def test_cumulative_event_percent_inverts_intervals_but_not_inference(self):
        data = fixture()
        ordinary = analyse(KM, data, BASE)
        options = {**BASE, "Curve": "Cumulative events", "Display units": "Percent",
                   "Uncertainty": "Pointwise confidence band", "Observation markers": "All observations"}
        result = analyse(KM, data, options)
        before, after = ordinary.tables["Curve: Low"], result.tables["Curve: Low"]
        np.testing.assert_allclose(after["Cumulative events (%)"], 100 * (1 - before["Survival"]))
        np.testing.assert_allclose(after["CI 95% low"], 100 * (1 - before["CI 95% high"]))
        np.testing.assert_allclose(after["CI 95% high"], 100 * (1 - before["CI 95% low"]))
        pd.testing.assert_frame_equal(result.tables["Survival summary"], ordinary.tables["Survival summary"])
        pd.testing.assert_frame_equal(result.tables["Log-rank test"], ordinary.tables["Log-rank test"])
        axes, = result.figure.axes
        self.assertEqual(axes.lines[0].get_ydata()[0], 0)
        self.assertEqual(axes.lines[0].get_drawstyle(), "steps-post")
        self.assertEqual(len(axes.collections), 3)

    def test_confidence_bars_use_asymmetric_limits_at_events_only(self):
        data = pd.DataFrame({"Time": [1, 1, 2, 3, 5], "Event": [1, 0, 0, 1, 1]})
        for ordinate in ("Survival", "Cumulative events"):
            with self.subTest(ordinate=ordinate):
                result = analyse(KM, data, {"Time": "Time", "Event": "Event", "Curve": ordinate,
                                           "Display units": "Percent", "Uncertainty": "Pointwise confidence bars"})
                curve = result.tables["Curve: All"].set_index("Time")
                axes, = result.figure.axes
                bars, = axes.containers
                segments = np.asarray(bars.lines[2][0].get_segments())
                np.testing.assert_array_equal(segments[:, :, 0], [[1, 1], [3, 3]])
                np.testing.assert_allclose(segments[:, :, 1], curve.loc[[1, 3], ["CI 95% low", "CI 95% high"]])
                self.assertNotIn("Standard error", curve)
                self.assertEqual(axes.lines[0].get_drawstyle(), "steps-post")

    def test_symmetric_interval_and_standard_error_at_a_tied_censor(self):
        data = pd.DataFrame({"Time": [1, 1, 3, 4], "Event": [1, 0, 1, 0]})
        options = {"Time": "Time", "Event": "Event", "Uncertainty": "Standard error bars",
                   "Interval method": "Symmetric Greenwood", "Observation markers": "Final censor only"}
        result = analyse(KM, data, options)
        curve = result.tables["Curve: All"]
        se = .75 / np.sqrt(12)
        self.assertAlmostEqual(curve.at[0, "Standard error"], se)
        self.assertAlmostEqual(curve.at[0, "CI 95% low"], .75 - 1.959963984540054 * se)
        self.assertEqual(curve.at[0, "CI 95% high"], 1.)
        axes, = result.figure.axes
        self.assertEqual(axes.lines[1].get_xdata().tolist(), [4.])
        self.assertEqual(len(axes.containers), 1)
        self.assertEqual(axes.lines[0].get_ydata().tolist(), [1., .75, .375, .375])

    def test_custom_status_codes_match_the_same_complete_cases(self):
        original = fixture()
        expected = analyse(KM, original, BASE).tables
        for event, censor in (("Death", "Alive"), (0, 1), (2, -1), ("01", "00")):
            with self.subTest(event=event, censor=censor):
                encoded = original.assign(Event=original["Event"].map({1: event, 0: censor}))
                actual = analyse(KM, encoded, {**BASE, "Event code": str(event), "Censor code": str(censor)}).tables
                pd.testing.assert_frame_equal(actual["Survival summary"], expected["Survival summary"])
                pd.testing.assert_frame_equal(actual["Log-rank test"], expected["Log-rank test"])
                self.assertEqual(encoded.at[0, "Event"], event)

    def test_undefined_status_policy_is_used_for_trend_and_all_event_columns(self):
        original = fixture()
        encoded = original.assign(Event=original["Event"].map({1: "Death", 0: "Alive"}))
        encoded["Second"] = encoded["Event"]
        encoded.loc[encoded["Group"] == "High", "Second"] = "Unknown"
        options = {"Time": "Time", "Event columns": ["Event", "Second"], "Grouping variables": ["Group"],
                   "Event code": "Death", "Censor code": "Alive", "Log-rank trend": True}
        with self.assertRaisesRegex(ValueError, 'Second.*Unknown'):
            check_survival_options(encoded, options)
        options["Other status values"] = "Treat as missing"
        options["Trend group order"] = survival_levels(encoded, options)
        actual = analyse(KM, encoded, options).tables
        trend = actual["Log-rank trend"].set_index(["Response variable", "Metric"])
        self.assertAlmostEqual(trend.loc[("Event", "z"), "Value"], -1.8903730248081347)
        self.assertEqual(trend.loc[("Second", "Status"), "Value"], "Not available")
        with self.assertRaisesRegex(ValueError, "must be different"):
            check_survival_options(encoded, {**options, "Censor code": "Death"})

    def test_unicode_and_numeric_looking_orders(self):
        data = fixture().replace({"Low": " α 01", "Mid": "10", "High": "2"})
        order = [" α 01", "10", "2"]
        self.assertEqual(survival_levels(data, {**BASE, "Event columns": ["Event"],
                                                "Grouping variables": ["Group"]}), order)
        result = analyse(KM, data, self.options(**{"Log-rank trend": True, "Trend group order": order}))
        self.assertAlmostEqual(result.tables["Log-rank trend"].at["z", "Value"], -1.8903730248081347)
        self.assertEqual(result.tables["Log-rank trend"].at["Group order", "Value"], " α 01 → 10 → 2")

    def test_missing_values_make_trend_unavailable_only_in_that_panel(self):
        data = fixture().assign(Second=[1, 0, 1, 1, 1, 0, 1, 1, np.nan, np.nan, np.nan, np.nan])
        options = {"Time": "Time", "Event columns": ["Event", "Second"], "Grouping variables": ["Group"],
                   "Log-rank trend": True, "Gehan–Breslow–Wilcoxon": True, "Hazard ratio": True}
        names = survival_levels(data, options)
        self.assertEqual(len(names), 3)
        result = analyse(KM, data, {**options, "Trend group order": names})
        trend = result.tables["Log-rank trend"].set_index(["Response variable", "Metric"])
        self.assertAlmostEqual(trend.loc[("Event", "z"), "Value"], -1.8903730248081347)
        self.assertEqual(trend.loc[("Second", "Status"), "Value"], "Not available")
        self.assertIn("missing from this analysis", trend.loc[("Second", "Reason"), "Value"])
        self.assertIn("Gehan–Breslow–Wilcoxon test", result.tables)
        reordered = analyse(KM, data.iloc[::-1], {**options, "Trend group order": names})
        trend = reordered.tables["Log-rank trend"].set_index(["Response variable", "Metric"])
        self.assertAlmostEqual(trend.loc[("Event", "z"), "Value"], -1.8903730248081347)

    def test_censored_only_panel_does_not_block_results(self):
        data = pd.DataFrame({"Time": [1, 2, 3, 4], "Event": [0, 0, 0, 0], "Group": list("AABB")})
        result = analyse(KM, data, {**BASE, "Gehan–Breslow–Wilcoxon": True, "Hazard ratio": True})
        self.assertEqual(result.tables["Gehan–Breslow–Wilcoxon test"].at["Status", "Value"], "Not available")
        self.assertEqual(result.tables["Survival summary"]["Events"].tolist(), [0, 0])
        self.assertIn("Curve: A", result.tables)
        self.assertTrue(result.tables["Survival summary"]["Median survival"].isna().all())

    def test_large_series_is_not_quadratic(self):
        rng = np.random.default_rng(1)
        n = 60000
        data = pd.DataFrame({"Time": rng.exponential(10, n), "Event": rng.integers(0, 2, n),
                             "Group": rng.integers(0, 3, n).astype(str)})
        out = survival_comparisons(data, "Time", "Event", "Group", gbw=True, trend_order=["0", "1", "2"])
        self.assertTrue(out["gbw"]["available"])
        self.assertAlmostEqual(out["gbw"]["p"], stats.chi2.sf(out["gbw"]["χ²"], 2))


if __name__ == "__main__":
    unittest.main()
