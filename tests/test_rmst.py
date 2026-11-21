"""Restricted mean survival time: the engine against exact fractions, survRM2 and the edge cases of the packet."""
import copy
import importlib.util
import json
import math
from fractions import Fraction
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi import rmst as engine
from analisi.field_error import FieldError
from analisi.rmst import (COMPARISON_SHEET, RMST_SHEET, SETTINGS_SHEET, STEPS_SHEET, Estimate, contrasts,
                          integrate, Cohort)
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "rmst"
METHOD = "Restricted mean survival time"
BASE = {"Time": "Time", "Status": "Event", "Group": "Group", "Reference group": "Reference", "Horizon": 6.5}


def load_oracle():
    spec = importlib.util.spec_from_file_location("rmst_packet_oracle", DATA / "oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = load_oracle()


def cohorts():
    return pd.read_csv(DATA / "fixtures" / "cohorts.csv")


def run(frame=None, **overrides):
    return analyse(METHOD, cohorts() if frame is None else frame, {**BASE, **overrides})


def one(times, events, horizon, **options):
    frame = pd.DataFrame({"Time": times, "Event": events})
    return analyse(METHOD, frame, {"Time": "Time", "Status": "Event", "Horizon": horizon, "Show graph": False,
                                   **options})


def exact(times, events, horizon):
    """Exact mean and variance by the oracle (full covariance of the rectangles, rational arithmetic)."""
    found = ORACLE.readable_rows(list(zip(times, events)), horizon)
    return Fraction(found["exact_mean"]), Fraction(found["exact_variance"]), found


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.golden = json.loads((DATA / "fixtures" / "expected.json").read_text(encoding="utf-8"))

    def test_frozen_oracle_still_reproduces_the_packet_numbers(self):
        actual = ORACLE.fixture_expectations()
        for name in ("Difference", "Ratio"):
            # erfc can round differently between the Windows and Linux math libraries.
            target = self.golden["contrasts"][name]["p"]
            with self.subTest(contrast=name):
                self.assertAlmostEqual(actual["contrasts"][name]["p"], target, delta=2 * math.ulp(target))
            actual["contrasts"][name]["p"] = target
        self.assertEqual(actual, self.golden)

    def test_hand_values_of_the_main_sample(self):
        result = run()
        table = result.tables[RMST_SHEET].set_index("Group")
        self.assertAlmostEqual(table.loc["Reference", "RMST"], 77 / 18, places=14)
        self.assertAlmostEqual(table.loc["Series $B", "RMST"], 5.0, places=14)
        self.assertAlmostEqual(table.loc["Reference", "SE"] ** 2, 559 / 648, places=13)
        self.assertAlmostEqual(table.loc["Series $B", "SE"] ** 2, 205 / 216, places=13)
        comparison = result.tables[COMPARISON_SHEET].set_index("Contrast")
        self.assertAlmostEqual(comparison.loc["Difference", "Estimate"], 13 / 18, places=14)
        self.assertAlmostEqual(comparison.loc["Ratio", "Estimate"], 90 / 77, places=14)

    def test_sheets_have_the_required_columns_in_order(self):
        result = run()
        self.assertEqual(list(result.tables), [RMST_SHEET, COMPARISON_SHEET, STEPS_SHEET, SETTINGS_SHEET])
        self.assertEqual(list(result.tables[RMST_SHEET]), ["Group", "N", "Events through horizon", "Max follow-up",
                                                           "Horizon", "RMST", "SE", "CI lower", "CI upper", "Status"])
        self.assertEqual(list(result.tables[COMPARISON_SHEET]), [
            "Contrast", "Compared group", "Reference group", "Estimate", "Inference SE", "Scale", "CI lower",
            "CI upper", "p", "Status"])
        self.assertEqual(list(result.tables[STEPS_SHEET]), ["Group", "Left", "Right", "Survival", "Area"])
        self.assertEqual(list(result.tables[SETTINGS_SHEET]), ["Value"])
        comparison = result.tables[COMPARISON_SHEET]
        self.assertEqual(list(comparison["Contrast"]), ["Difference", "Ratio"])
        self.assertEqual(list(comparison["Scale"]), ["Identity", "Log"])
        for column in ("RMST", "SE", "CI lower", "CI upper", "Max follow-up", "Horizon"):
            self.assertEqual(result.tables[RMST_SHEET][column].dtype, np.float64)
        settings = result.tables[SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Horizon"], 6.5)
        self.assertEqual(settings["Confidence level (%)"], 95.0)
        self.assertEqual((settings["Event code"], settings["Censor code"]), ("1", "0"))
        self.assertEqual(settings["Incomplete rows"], 0)
        self.assertIn("Asymptotic", settings["Confidence intervals"])

    def test_steps_cut_only_at_event_times_inside_the_horizon(self):
        steps = run().tables[STEPS_SHEET]
        reference = steps[steps["Group"] == "Reference"]
        # The censoring at 2 shares its time with an event; the censorings at 6 and 8 add no cut.
        self.assertEqual(reference[["Left", "Right"]].to_numpy().tolist(), [[0, 1], [1, 2], [2, 4], [4, 6.5]])
        self.assertTrue(np.allclose(steps["Area"], (steps["Right"] - steps["Left"]) * steps["Survival"],
                                    rtol=0, atol=1e-15))

    def test_groups_keep_literal_names_and_the_reference_comes_first(self):
        frame = cohorts().replace({"Group": {"Reference": "$x_1$"}})
        result = run(frame, **{"Reference group": "Series $B"})
        self.assertEqual(list(result.tables[RMST_SHEET]["Group"]), ["Series $B", "$x_1$"])
        legend = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(legend[:2], ["Series $B", "$x_1$"])
        self.assertFalse(any(text.get_parse_math() for text in result.figure.axes[0].get_legend().get_texts()))


class SurvRM2Tests(unittest.TestCase):
    """survRM2::rmst2 1.0.4 (R 4.3.3) on three synthetic samples: stored outputs, R is not needed to run them."""

    def test_estimates_intervals_and_p_values_match_survrm2(self):
        expected = json.loads((DATA / "survrm2" / "expected-survrm2.json").read_text(encoding="utf-8"))
        for name in ("continuous", "ties", "zero"):
            case = expected[name]
            with self.subTest(name):
                frame = pd.read_csv(DATA / "survrm2" / f"{name}.csv")
                result = run(frame, **{"Reference group": case["reference"], "Horizon": float(case["tau"])})
                table = result.tables[RMST_SHEET].set_index("Group")
                for label, key in ((case["reference"], "reference_rmst"), (case["compared"], "compared_rmst")):
                    found = table.loc[label, ["RMST", "SE", "CI lower", "CI upper"]].to_numpy(dtype=float)
                    np.testing.assert_allclose(found, case[key], rtol=1e-12)
                rows = result.tables[COMPARISON_SHEET].set_index("Contrast")
                for contrast, key in (("Difference", "difference"), ("Ratio", "ratio")):
                    found = rows.loc[contrast, ["Estimate", "CI lower", "CI upper", "p"]].to_numpy(dtype=float)
                    np.testing.assert_allclose(found, case[key], rtol=1e-11)


class EngineTests(unittest.TestCase):
    def check_against_oracle(self, times, events, horizon):
        mean, variance, found = exact(times, events, horizon)
        result = one(times, events, horizon)
        row = result.tables[RMST_SHEET].iloc[0]
        self.assertTrue(math.isclose(row["RMST"], float(mean), rel_tol=1e-13, abs_tol=1e-15), (row["RMST"], mean))
        self.assertTrue(math.isclose(row["SE"], math.sqrt(float(variance)), rel_tol=1e-12, abs_tol=1e-15))
        self.assertEqual(int(row["Events through horizon"]), found["Events through horizon"])
        steps = result.tables[STEPS_SHEET][["Left", "Right", "Survival", "Area"]].to_numpy().tolist()
        np.testing.assert_allclose(steps, found["steps"], rtol=1e-13, atol=1e-15)
        return result

    def test_random_small_samples_match_the_quadratic_oracle(self):
        rng = np.random.default_rng(19093)
        for trial in range(40):
            n = int(rng.integers(1, 25))
            times = rng.integers(0, 12, n).tolist()
            events = rng.integers(0, 2, n).tolist()
            longest = max(times)
            if longest == 0:
                continue
            horizon = float(rng.choice([longest, rng.uniform(0.1, longest), int(rng.integers(1, longest + 1))]))
            with self.subTest(trial=trial, horizon=horizon):
                self.check_against_oracle(times, events, horizon)

    def test_events_at_zero_lower_the_curve_at_the_origin(self):
        result = self.check_against_oracle([0, 0, 2], [1, 1, 0], 2)
        self.assertAlmostEqual(result.tables[RMST_SHEET].iloc[0]["RMST"], 2 / 3, places=15)
        self.assertEqual(result.tables[STEPS_SHEET].iloc[0]["Survival"], 1 / 3)

    def test_an_event_at_the_horizon_counts_but_adds_no_area(self):
        result = self.check_against_oracle([1, 2, 3], [1, 1, 1], 3)
        row = result.tables[RMST_SHEET].iloc[0]
        self.assertEqual(row["Events through horizon"], 3)
        self.assertAlmostEqual(row["RMST"], 2.0, places=15)
        self.assertAlmostEqual(row["SE"] ** 2, 2 / 9, places=15)
        plotted = one([1, 2, 3], [1, 1, 1], 3, **{"Show graph": True}).figure.axes[0]
        curve = next(line for line in plotted.lines if line.get_gid() == "rmst-curve-0")
        self.assertEqual(list(curve.get_xdata()), [0, 1, 2, 3])
        self.assertEqual(curve.get_ydata()[-1], 0.0)

    def test_tied_event_and_censoring_share_the_risk_set(self):
        # At time 2 one event and one censoring: n = 4 counts the censored subject.
        self.check_against_oracle([1, 2, 2, 3, 5], [0, 1, 0, 1, 0], 4.5)
        self.check_against_oracle([2, 2, 2, 2, 4], [1, 0, 1, 0, 1], 4)

    def test_every_subject_failing_at_once_gives_zero_further_area_and_contribution(self):
        result = self.check_against_oracle([1, 3, 3], [0, 1, 1], 3)
        self.assertAlmostEqual(result.tables[RMST_SHEET].iloc[0]["RMST"], 3.0, places=15)
        self.assertEqual(result.tables[RMST_SHEET].iloc[0]["SE"], 0.0)

    def test_a_cohort_without_events_has_zero_variance_and_blank_limits(self):
        result = one([1, 3, 5], [0, 0, 0], 5)
        row = result.tables[RMST_SHEET].iloc[0]
        self.assertEqual((row["RMST"], row["SE"], row["Status"]), (5.0, 0.0, "Zero variance"))
        self.assertTrue(math.isnan(row["CI lower"]) and math.isnan(row["CI upper"]))
        self.assertEqual(result.tables[STEPS_SHEET][["Left", "Right", "Survival", "Area"]].to_numpy().tolist(),
                         [[0.0, 5.0, 1.0, 5.0]])
        self.assertNotIn(COMPARISON_SHEET, result.tables)
        self.assertIsNone(result.figure)
        self.assertEqual(list(result.tables[RMST_SHEET]["Group"]), ["All"])

    def test_two_groups_one_without_events_give_identity_difference_and_log_ratio(self):
        frame = pd.DataFrame({"Time": [1, 3, 5, 1, 2, 5], "Event": [0, 0, 0, 1, 0, 1],
                              "Group": ["Safe", "Safe", "Safe", "Risk", "Risk", "Risk"]})
        result = run(frame, **{"Reference group": "Safe", "Horizon": 5})
        rows = result.tables[COMPARISON_SHEET].set_index("Contrast")
        self.assertEqual(rows.loc["Difference", "Status"], "OK")
        self.assertEqual(rows.loc["Ratio", "Status"], "OK")
        risk = result.tables[RMST_SHEET].set_index("Group").loc["Risk"]
        self.assertAlmostEqual(rows.loc["Ratio", "Inference SE"], risk["SE"] / risk["RMST"], places=15)

    def test_unit_changes_scale_times_and_keep_ratios_and_p_values(self):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame({"Time": rng.exponential(4, 300).round(3), "Event": rng.integers(0, 2, 300),
                              "Group": rng.choice(["A", "B"], 300)})
        horizon = float(frame.groupby("Group")["Time"].max().min())
        base = run(frame, **{"Reference group": "A", "Horizon": horizon})
        for factor in (1e-9, 1 / 60, 60.0, 3.6e6, 1e12):
            with self.subTest(factor=factor):
                scaled = run(frame.assign(Time=frame["Time"] * factor),
                             **{"Reference group": "A", "Horizon": horizon * factor})
                for column in ("RMST", "SE", "CI lower", "CI upper", "Max follow-up"):
                    np.testing.assert_allclose(scaled.tables[RMST_SHEET][column],
                                               base.tables[RMST_SHEET][column] * factor, rtol=1e-11)
                rows, ref = scaled.tables[COMPARISON_SHEET], base.tables[COMPARISON_SHEET]
                np.testing.assert_allclose(rows["Estimate"], ref["Estimate"] * [factor, 1], rtol=1e-11)
                np.testing.assert_allclose(rows["p"], ref["p"], rtol=1e-11)
                np.testing.assert_allclose(rows["Inference SE"], ref["Inference SE"] * [factor, 1], rtol=1e-11)

    def test_extreme_time_units_keep_the_variance_finite(self):
        for factor in (1e-300, 1e300):
            result = one(np.array([1., 2, 3, 4, 6]) * factor, [1, 0, 1, 1, 0], 5 * factor)
            row = result.tables[RMST_SHEET].iloc[0]
            self.assertTrue(np.isfinite([row["RMST"], row["SE"], row["CI lower"], row["CI upper"]]).all())

    def test_row_order_and_source_are_irrelevant_and_untouched(self):
        frame = cohorts()
        for seed in range(5):
            shuffled = frame.sample(frac=1, random_state=seed).reset_index(drop=True)
            copy_ = shuffled.copy(deep=True)
            options = copy.deepcopy(BASE)
            result = analyse(METHOD, shuffled, options)
            pd.testing.assert_frame_equal(shuffled, copy_)
            self.assertEqual(options, BASE)
            for name in (RMST_SHEET, COMPARISON_SHEET, STEPS_SHEET):
                pd.testing.assert_frame_equal(result.tables[name], run().tables[name])

    def test_incomplete_rows_are_dropped_once_and_counted(self):
        frame = cohorts()
        frame.loc[12] = [np.nan, np.nan, np.nan]  # every role missing: one incomplete row, not three
        frame.loc[13] = [4, np.nan, "Reference"]
        frame.loc[14] = [4, 1, np.nan]
        result = run(frame)
        self.assertEqual(result.tables[SETTINGS_SHEET]["Value"]["Incomplete rows"], 3)
        self.assertEqual(result.tables[SETTINGS_SHEET]["Value"]["Complete rows"], 12)
        pd.testing.assert_frame_equal(result.tables[RMST_SHEET], run().tables[RMST_SHEET])

    def test_a_missing_group_only_matters_when_group_is_selected(self):
        frame = cohorts().assign(Other=[None] * 12)
        result = analyse(METHOD, frame, {"Time": "Time", "Status": "Event", "Horizon": 6.5, "Group": ""})
        self.assertEqual(result.tables[RMST_SHEET]["N"].tolist(), [12])
        self.assertEqual(result.tables[SETTINGS_SHEET]["Value"]["Incomplete rows"], 0)

    def test_text_codes_and_the_confidence_level(self):
        frame = pd.read_csv(DATA / "fixtures" / "text-status.csv")
        result = analyse(METHOD, frame, {"Time": "Time", "Status": "Status", "Group": "Cohort",
                                         "Reference group": "Ref", "Event code": "event", "Censor code": "lost",
                                         "Confidence level (%)": 90.0, "Horizon": 4.0})
        golden = json.loads((DATA / "fixtures" / "expected.json").read_text(encoding="utf-8"))["text_arms"]
        table = result.tables[RMST_SHEET].set_index("Group")
        for label, expected in golden.items():
            for column in ("RMST", "SE", "CI lower", "CI upper"):
                self.assertAlmostEqual(table.loc[label, column], expected[column], places=13)
        self.assertEqual(result.tables[SETTINGS_SHEET]["Value"]["Incomplete rows"], 3)

    def test_integer_codes_may_be_written_with_spaces_or_a_trailing_point_zero(self):
        a = run(**{"Event code": " 1 ", "Censor code": "0.0"}).tables[RMST_SHEET]
        pd.testing.assert_frame_equal(a, run().tables[RMST_SHEET])

    def test_numeric_group_labels_and_reference_written_as_a_number(self):
        frame = cohorts().assign(Group=cohorts()["Group"].map({"Reference": 0.0, "Series $B": 1.0}))
        result = run(frame, **{"Reference group": "1"})
        self.assertEqual(list(result.tables[RMST_SHEET]["Group"]), ["1", "0"])
        same = run(frame, **{"Reference group": 1})
        pd.testing.assert_frame_equal(same.tables[RMST_SHEET], result.tables[RMST_SHEET])

    def test_horizon_equal_to_the_shortest_follow_up_is_accepted(self):
        result = run(Horizon=8)
        self.assertEqual(result.tables[RMST_SHEET]["Horizon"].tolist(), [8.0, 8.0])
        self.assertEqual(result.tables[SETTINGS_SHEET]["Value"]["Largest usable horizon"], 8.0)

    def test_the_limit_applies_when_the_curve_reaches_zero(self):
        with self.assertRaises(FieldError) as raised:
            one([1, 2, 3], [1, 1, 1], 3.5)
        self.assertEqual(raised.exception.field, "Horizon")
        self.assertIn("3", str(raised.exception))

    def test_horizon_error_names_the_limiting_group_and_its_follow_up(self):
        with self.assertRaises(FieldError) as raised:
            run(Horizon=8.5)
        self.assertEqual(raised.exception.field, "Horizon")
        self.assertEqual(str(raised.exception), "Horizon 8.5 is beyond the follow-up. Group Reference is observed up "
                                                "to 8: use a horizon greater than 0 and no larger than that.")

    def test_field_errors(self):
        frame = cohorts()
        cases = [
            ("Horizon", {"Horizon": None}), ("Horizon", {"Horizon": ""}), ("Horizon", {"Horizon": "6.5"}),
            ("Horizon", {"Horizon": 0}), ("Horizon", {"Horizon": -1}), ("Horizon", {"Horizon": math.inf}),
            ("Horizon", {"Horizon": float("nan")}), ("Horizon", {"Horizon": True}),
            ("Confidence level (%)", {"Confidence level (%)": 0}),
            ("Confidence level (%)", {"Confidence level (%)": "95"}),
            ("Confidence level (%)", {"Confidence level (%)": 100}),
            ("Show graph", {"Show graph": "yes"}),
            ("Event code", {"Event code": ""}), ("Event code", {"Event code": True}),
            ("Event code", {"Event code": "1.5"}), ("Censor code", {"Censor code": "x"}),
            ("Censor code", {"Censor code": "1"}), ("Censor code", {"Censor code": " 1.0"}),
            ("Time", {"Time": ""}), ("Time", {"Time": "Missing"}), ("Status", {"Status": "Time"}),
            ("Group", {"Group": "Time"}), ("Group", {"Group": "Event"}),
            ("Reference group", {"Reference group": ""}), ("Reference group", {"Reference group": None}),
            ("Reference group", {"Reference group": "reference"}), ("Reference group", {"Reference group": ["x"]}),
        ]
        for field, options in cases:
            with self.subTest(options=options):
                with self.assertRaises(FieldError) as raised:
                    run(frame, **options)
                self.assertEqual(raised.exception.field, field)

    def test_worksheet_errors(self):
        frame = cohorts()
        cases = [
            ("Time", frame.assign(Time=frame["Time"].astype(object).where(frame.index != 3, "soon"))),
            ("Time", frame.assign(Time=frame["Time"].where(frame.index != 3, -1))),
            ("Time", frame.assign(Time=frame["Time"].astype(float).where(frame.index != 3, math.inf))),
            ("Time", frame.assign(Time=frame["Time"] > 3)),
            ("Status", frame.assign(Event=frame["Event"] == 1)),
            ("Status", frame.assign(Event=frame["Event"].astype(object).where(frame.index != 0, "x"))),
            ("Status", frame.assign(Event=frame["Event"].where(frame.index != 0, 2))),
            ("Group", frame.assign(Group="Only")),
            ("Group", frame.assign(Group=["A", "B", "C"] * 4)),
            ("Group", frame.assign(Group=[1, "1"] * 6)),
            ("Group", frame.assign(Group=np.nan)),
        ]
        for field, data in cases:
            with self.subTest(field=field, frame=data.head(4).to_dict("list")):
                with self.assertRaises(FieldError) as raised:
                    run(data)
                self.assertEqual(raised.exception.field, field)

    def test_row_budget(self):
        frame = pd.DataFrame({"Time": np.arange(engine.MAX_ROWS + 1) % 97 + 1., "Event": 1})
        with self.assertRaises(FieldError) as raised:
            one(frame["Time"], frame["Event"], 5)
        self.assertEqual(raised.exception.field, "Time")
        self.assertIn("50,000", str(raised.exception))
        one(frame["Time"][:engine.MAX_ROWS], frame["Event"][:engine.MAX_ROWS], 5)

    def test_check_options_reads_no_more_than_the_dialog_needs(self):
        plan = engine.check_options(cohorts(), BASE)
        self.assertEqual(plan.limit, 8.0)
        self.assertEqual([cohort.label for cohort in plan.dataset.cohorts], ["Reference", "Series $B"])
        self.assertEqual(engine.horizon_limit(cohorts(), {**BASE, "Horizon": ""}), 8.0)
        self.assertIsNone(engine.horizon_limit(cohorts(), {**BASE, "Time": "Missing"}))
        self.assertEqual(engine.group_levels(cohorts(), BASE), ["Reference", "Series $B"])
        self.assertEqual(engine.group_levels(cohorts(), {**BASE, "Group": ""}), [])


class ContrastTests(unittest.TestCase):
    @staticmethod
    def estimate(rmst, se):
        empty = np.array([])
        return Estimate("x", 3, 1, 5.0, rmst, se, empty, empty, empty, empty, 1.0)

    def test_zero_standard_errors_keep_estimates_and_blank_inference(self):
        rows = contrasts(self.estimate(5.0, 0.0), self.estimate(4.0, 0.0), 1.96)
        difference, ratio = rows["Difference"], rows["Ratio"]
        self.assertEqual((difference["Estimate"], difference["Inference SE"], difference["Status"]),
                         (1.0, 0.0, "Zero variance"))
        self.assertTrue(all(math.isnan(difference[key]) for key in ("CI lower", "CI upper", "p")))
        self.assertEqual((ratio["Estimate"], ratio["Inference SE"], ratio["Status"]), (1.25, 0.0, "Zero variance"))
        self.assertTrue(all(math.isnan(ratio[key]) for key in ("CI lower", "CI upper", "p")))

    def test_a_zero_denominator_leaves_the_ratio_undefined(self):
        ratio = contrasts(self.estimate(5.0, 1.0), self.estimate(0.0, 0.0), 1.96)["Ratio"]
        self.assertEqual(ratio["Status"], "Undefined ratio")
        self.assertTrue(all(math.isnan(ratio[key]) for key in ("Estimate", "Inference SE", "CI lower", "CI upper", "p")))

    def test_an_unrepresentable_ratio_is_undefined(self):
        ratio = contrasts(self.estimate(1e308, 1.0), self.estimate(1e-308, 1.0), 1.96)["Ratio"]
        self.assertEqual(ratio["Status"], "Undefined ratio")
        self.assertTrue(math.isnan(ratio["Estimate"]))

    def test_a_zero_numerator_keeps_the_ratio_without_log_inference(self):
        ratio = contrasts(self.estimate(0.0, 0.0), self.estimate(2.0, 0.5), 1.96)["Ratio"]
        self.assertEqual((ratio["Estimate"], ratio["Status"]), (0.0, "Log inference unavailable"))
        self.assertTrue(all(math.isnan(ratio[key]) for key in ("Inference SE", "CI lower", "CI upper", "p")))

    def test_reversing_the_reference_negates_the_difference_and_inverts_the_ratio(self):
        a, b = run(), run(**{"Reference group": "Series $B"})
        ra = a.tables[COMPARISON_SHEET].set_index("Contrast")
        rb = b.tables[COMPARISON_SHEET].set_index("Contrast")
        self.assertAlmostEqual(ra.loc["Difference", "Estimate"], -rb.loc["Difference", "Estimate"], places=14)
        self.assertAlmostEqual(ra.loc["Ratio", "Estimate"], 1 / rb.loc["Ratio", "Estimate"], places=14)
        self.assertAlmostEqual(ra.loc["Ratio", "CI lower"], 1 / rb.loc["Ratio", "CI upper"], places=13)
        self.assertAlmostEqual(ra.loc["Ratio", "p"], rb.loc["Ratio", "p"], places=14)
        self.assertEqual(rb.loc["Ratio", ["Compared group", "Reference group"]].tolist(), ["Reference", "Series $B"])

    def test_wald_intervals_are_not_truncated(self):
        result = one([0.1, 0.2, 10], [1, 1, 0], 10, **{"Confidence level (%)": 99.9})
        row = result.tables[RMST_SHEET].iloc[0]
        self.assertLess(row["CI lower"], 0)


class FigureTests(unittest.TestCase):
    def test_native_figure_ids_limits_and_area(self):
        result = run()
        axes, = result.figure.axes
        by_id = {artist.get_gid(): artist for artist in axes.get_children() if artist.get_gid()}
        self.assertEqual(set(by_id) >= {"rmst-curve-0", "rmst-curve-1", "rmst-area-0", "rmst-area-1",
                                        "rmst-horizon"}, True)
        self.assertEqual(tuple(axes.get_xlim()), (0.0, 6.5))
        self.assertEqual(tuple(axes.get_ylim()), (0.0, 1.0))
        self.assertEqual(list(by_id["rmst-horizon"].get_xdata()), [6.5, 6.5])
        # The shaded polygon spans exactly the integrated area of each group.
        table = result.tables[RMST_SHEET].set_index("Group")
        for index, label in enumerate(("Reference", "Series $B")):
            path = by_id[f"rmst-area-{index}"].get_paths()[0]
            x, y = path.vertices[:, 0], path.vertices[:, 1]
            area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
            self.assertAlmostEqual(area, table.loc[label, "RMST"], places=12)
            self.assertEqual(by_id[f"rmst-curve-{index}"].get_label(), label)
            self.assertLess(by_id[f"rmst-area-{index}"].get_alpha(), 0.5)

    def test_one_group_draws_only_index_zero(self):
        frame = pd.read_csv(DATA / "fixtures" / "degenerate.csv")
        frame = frame[frame["Group"] == "Terminal event"]
        result = analyse(METHOD, frame, {"Time": "Time", "Status": "Event", "Horizon": 3})
        ids = {artist.get_gid() for artist in result.figure.axes[0].get_children() if artist.get_gid()}
        self.assertEqual(ids & {"rmst-curve-1", "rmst-area-1"}, set())
        self.assertTrue({"rmst-curve-0", "rmst-area-0", "rmst-horizon"} <= ids)

    def test_vector_ids_reach_svg_and_pdf_has_no_raster(self):
        import io
        result = run()
        buffer = io.BytesIO()
        result.figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().decode("utf-8")
        for gid in ("rmst-curve-0", "rmst-curve-1", "rmst-area-0", "rmst-area-1", "rmst-horizon"):
            self.assertIn(f'id="{gid}"', svg)
        self.assertNotIn("<image", svg)
        buffer = io.BytesIO()
        result.figure.savefig(buffer, format="pdf")
        self.assertNotIn(b"/Subtype /Image", buffer.getvalue())

    def test_show_graph_off_returns_the_same_sheets_and_no_figure(self):
        with_graph, without = run(), run(**{"Show graph": False})
        self.assertIsNone(without.figure)
        self.assertEqual(list(with_graph.tables), list(without.tables))
        for name in with_graph.tables:
            pd.testing.assert_frame_equal(with_graph.tables[name], without.tables[name])


class RegistrationTests(unittest.TestCase):
    def test_menu_dispatcher_and_graph_registration(self):
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GROUPS["Survival Analysis"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(GROUPS["Survival Analysis"][:3], ("Kaplan–Meier survival", "Cox regression",
                                                           "Competing risks"))

    def test_legacy_kaplan_meier_report_is_unchanged(self):
        legacy = json.loads((DATA / "fixtures" / "legacy-km.json").read_text(encoding="utf-8"))
        result = analyse("Kaplan–Meier survival", cohorts(), {"Time": "Time", "Event": "Event", "Group": "Group"})
        tables = {name: json.loads(sheet.to_json(orient="split", double_precision=15))
                  for name, sheet in result.tables.items()}
        self.assertEqual(set(tables), set(legacy["tables"]))
        for name, sheet in tables.items():
            self.assertEqual(sheet, legacy["tables"][name], name)
        lines = [{"label": line.get_label(), "x": list(map(float, line.get_xdata())),
                  "y": list(map(float, line.get_ydata()))} for line in result.figure.axes[0].lines]
        self.assertEqual(len(lines), len(legacy["main_axes"]))
        for got, want in zip(lines, legacy["main_axes"]):
            self.assertEqual(got["label"], want["label"])
            np.testing.assert_allclose(got["x"], want["x"])
            np.testing.assert_allclose(got["y"], want["y"])


if __name__ == "__main__":
    unittest.main()
