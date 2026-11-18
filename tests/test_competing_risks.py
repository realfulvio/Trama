"""Competing-risks engine: references computed outside Trama, regressions and budgets."""
import json
from pathlib import Path
import threading
import unittest

import numpy as np
import pandas as pd

from analisi import competing_risks as cr
from analisi.field_error import FieldError

DATA = Path(__file__).parent / "data" / "competing_risks"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
RANDOM = json.loads((DATA / "cmprsk-random.json").read_text(encoding="utf-8"))["cases"]


def fixture_frame(name):
    kinds = {"Outcome": str, "Cohort": str} if name == "status-text" else None
    return pd.read_csv(DATA / f"{name}.csv", dtype=kinds)


def prepare_fixture(name):
    options = EXPECTED[name]["options"]
    frame = fixture_frame(name)
    return cr.prepare(frame, options["Time"], options["Status"], options["Group"], options["Censor code"],
                      options["Event codes"])


def prepare(frame, censor="0", events=("1", "2"), group="g"):
    return cr.prepare(frame, "t", "s", group, censor, list(events))


def frame_of(time, status, group=None):
    data = {"t": time, "s": status}
    if group is not None:
        data["g"] = group
    return pd.DataFrame(data)


def textbook_incidence(time, status, causes):
    """Aalen–Johansen written subject by subject, independent of the vectorised engine."""
    times = sorted(set(time))
    survival, incidence = 1.0, [0.0] * causes
    out = []
    for moment in times:
        risk = sum(1 for t in time if t >= moment)
        counts = [sum(1 for t, s in zip(time, status) if t == moment and s == k + 1) for k in range(causes)]
        for k in range(causes):
            incidence[k] += survival * counts[k] / risk
        survival *= 1 - sum(counts) / risk
        out.append((moment, survival, tuple(incidence)))
    return out


class CmprskFixtureTests(unittest.TestCase):
    """The package fixtures and frozen cmprsk 2.2-12 output (see tests/data/competing_risks)."""

    def test_curves_match_the_reference_sheets(self):
        for name, spec in EXPECTED.items():
            with self.subTest(name):
                dataset = prepare_fixture(name)
                self.assertEqual((dataset.groups, dataset.complete, dataset.omitted),
                                 (spec["groups"], spec["used"], spec["omitted"]))
                curves = cr.cumulative_incidence(dataset)
                for index, label in enumerate(dataset.groups):
                    curve = curves[index]
                    rows = sorted(((time, k, i) for k in range(len(dataset.causes)) for i, time in enumerate(curve.times)),
                                  key=lambda row: (row[0], row[1]))
                    reference = spec["steps"][label]
                    self.assertEqual(len(rows), len(reference))
                    for (time, k, i), line in zip(rows, reference):
                        self.assertEqual((time, dataset.causes[k]), (line[0], line[1]))
                        self.assertEqual((curve.at_risk[i], curve.events[k][i], curve.all_events[i], curve.censored[i]),
                                         tuple(line[2:6]))
                        np.testing.assert_allclose([curve.survival[i], curve.incidence[k][i], curve.variance[k][i]],
                                                   line[6:], rtol=1e-12, atol=1e-14)

    def test_gray_omnibus_and_pairs_match_the_reference(self):
        for name, spec in EXPECTED.items():
            with self.subTest(name):
                dataset = prepare_fixture(name)
                tracks = cr.gray_tracks(dataset)
                everyone = list(range(len(dataset.groups)))
                for k, reference in enumerate(spec["omnibus"]):
                    result = cr.gray_test(dataset, k, everyone, tracks)
                    self.assertEqual(result.available, reference is not None, result.reason)
                    if reference is not None:
                        self.assertAlmostEqual(result.statistic, reference[0], places=8)
                        self.assertEqual(result.df, reference[1])
                        self.assertAlmostEqual(result.p, reference[2], places=10)
                    else:
                        self.assertTrue(result.reason)
                for first, second, cause, values, _ in spec["pairs"]:
                    result = cr.gray_test(dataset, [str(c) for c in dataset.causes].index(cause),
                                          [dataset.groups.index(first), dataset.groups.index(second)], tracks)
                    self.assertEqual(result.available, values is not None, result.reason)
                    if values is not None:
                        self.assertAlmostEqual(result.statistic, values[0], places=8)
                        self.assertAlmostEqual(result.p, values[2], places=10)

    def test_holm_over_available_p_values_only(self):
        spec = EXPECTED["cohorts"]
        for cause in ("1", "2"):
            rows = [row for row in spec["pairs"] if row[2] == cause]
            adjusted = cr.holm([row[3][2] for row in rows])
            np.testing.assert_allclose(adjusted, [row[4] for row in rows], rtol=1e-12)
        self.assertEqual(cr.holm([0.04, None, 0.01]), [0.04, None, 0.02])
        self.assertEqual(cr.holm([None, None]), [None, None])
        self.assertEqual(cr.holm([0.9, 0.5]), [1.0, 1.0])

    def test_random_cases_agree_with_cmprsk(self):
        names = {case["name"] for case in RANDOM}
        self.assertTrue({"singular-covariance", "negative-tie-weight", "group-without-the-cause",
                         "group-all-censored"} <= names)
        for case in RANDOM:
            with self.subTest(case["name"]):
                causes = [str(k) for k in range(1, case["causes"] + 1)]
                grouped = len(set(case["group"])) > 1
                frame = pd.DataFrame({"t": case["time"], "s": case["status"], "g": case["group"]})
                dataset = cr.prepare(frame, "t", "s", "g" if grouped else "", "0", causes)
                curves = {c.label: c for c in cr.cumulative_incidence(dataset)}
                for key, reference in case["curves"].items():
                    label, cause = key.split("|")
                    k = int(cause) - 1
                    curve = curves[label if grouped else "All"]
                    if reference is None:
                        np.testing.assert_array_equal(curve.incidence[k], 0)
                        continue
                    steps = np.searchsorted(reference["x"], curve.times, side="right") - 1
                    expected_f = np.where(steps >= 0, np.array(reference["f"])[np.maximum(steps, 0)], 0.0)
                    expected_v = np.where(steps >= 0, np.array(reference["v"])[np.maximum(steps, 0)], 0.0)
                    np.testing.assert_allclose(curve.incidence[k], expected_f, rtol=1e-12, atol=1e-14)
                    np.testing.assert_allclose(curve.variance[k], expected_v, rtol=1e-10, atol=1e-14)
                if not grouped:
                    continue
                tracks = cr.gray_tracks(dataset)
                everyone = list(range(len(dataset.groups)))
                for k, reference in enumerate(case["omnibus"]):
                    result = cr.gray_test(dataset, k, everyone, tracks)
                    self.assertEqual(result.available, reference is not None, (k, result.reason))
                    if reference is not None:
                        self.assertAlmostEqual(result.statistic, reference, delta=1e-7 * max(1.0, reference))
                for reference in case["pairs"]:
                    a, b = dataset.groups.index(reference["first"]), dataset.groups.index(reference["second"])
                    for k, value in enumerate(reference["stat"]):
                        result = cr.gray_test(dataset, k, [a, b], tracks)
                        self.assertEqual(result.available, value is not None, (a, b, k, result.reason))
                        if value is not None:
                            self.assertAlmostEqual(result.statistic, value, delta=1e-7 * max(1.0, value))

    def test_matches_a_subject_by_subject_implementation(self):
        rng = np.random.default_rng(7)
        for _ in range(40):
            n, causes = int(rng.integers(3, 60)), int(rng.integers(1, 4))
            time = [float(x) for x in rng.integers(0, 12, n)]
            status = [int(x) for x in rng.integers(0, causes + 1, n)]
            dataset = prepare(frame_of(time, status), events=[str(k) for k in range(1, causes + 1)], group="")
            curve = cr.cumulative_incidence(dataset)[0]
            for (moment, survival, incidence), at, s, f in zip(
                    textbook_incidence(time, status, causes), curve.times, curve.survival, curve.incidence.T):
                self.assertEqual(moment, at)
                self.assertAlmostEqual(survival, s, places=12)
                np.testing.assert_allclose(incidence, f, atol=1e-12)
            np.testing.assert_allclose(curve.survival + curve.incidence.sum(axis=0), 1.0, atol=1e-12)


class CurveBehaviourTests(unittest.TestCase):
    def test_tied_censoring_stays_in_the_risk_set_and_rows_may_arrive_in_any_order(self):
        frame = frame_of([3, 1, 5, 1, 2, 2, 4, 1], [2, 1, 1, 0, 1, 0, 0, 2])
        shuffled = frame.sample(frac=1, random_state=3).reset_index(drop=True)
        for source in (frame, shuffled):
            curve = cr.cumulative_incidence(prepare(source, group=""))[0]
            np.testing.assert_array_equal(curve.times, [1, 2, 3, 4, 5])
            np.testing.assert_array_equal(curve.at_risk, [8, 5, 3, 2, 1])
            np.testing.assert_array_equal(curve.censored, [1, 1, 0, 1, 0])
        self.assertAlmostEqual(curve.incidence[0][0], 1 / 8)
        self.assertAlmostEqual(curve.incidence[1][0], 1 / 8)

    def test_event_at_time_zero_and_groups_with_different_follow_up(self):
        frame = frame_of([0, 2, 5, 1, 1, 9], [1, 0, 2, 2, 0, 1], ["A", "A", "A", "B", "B", "B"])
        dataset = prepare(frame, events=["1", "2"])
        first, second = cr.cumulative_incidence(dataset)
        self.assertEqual(first.times[0], 0)
        self.assertAlmostEqual(first.incidence[0][0], 1 / 3)
        _, _, beyond = cr.estimate_at(first, 0, [0, 5, 6])
        self.assertEqual(beyond.tolist(), [False, False, True])
        estimate, variance, beyond = cr.estimate_at(second, 1, [0, 1, 4, 9, 10])
        np.testing.assert_allclose(estimate, [0.0, 1 / 3, 1 / 3, 1 / 3, 1 / 3])
        self.assertEqual(variance[0], 0)
        self.assertEqual(beyond.tolist(), [False, False, False, False, True])

    def test_all_censored_and_an_absent_cause_have_zero_curves(self):
        dataset = prepare(frame_of([1, 2, 3], [0, 0, 0]), group="")
        curve = cr.cumulative_incidence(dataset)[0]
        np.testing.assert_array_equal(curve.incidence, 0)
        np.testing.assert_array_equal(curve.variance, 0)
        np.testing.assert_array_equal(curve.survival, 1)
        mixed = prepare(frame_of([1, 2, 3, 4], [1, 0, 1, 0]), group="")
        np.testing.assert_array_equal(cr.cumulative_incidence(mixed)[0].incidence[1], 0)

    def test_one_cause_is_one_minus_the_product_limit(self):
        time = [1, 2, 2, 3, 5, 5, 7, 8]
        status = [1, 0, 1, 1, 0, 1, 1, 0]
        curve = cr.cumulative_incidence(prepare(frame_of(time, status), events=["1"], group=""))[0]
        survival, expected = 1.0, []
        for moment in sorted(set(time)):
            risk = sum(t >= moment for t in time)
            failures = sum(t == moment and s == 1 for t, s in zip(time, status))
            survival *= 1 - failures / risk
            expected.append(1 - survival)
        np.testing.assert_allclose(curve.incidence[0], expected, atol=1e-14)

    def test_requested_times_are_right_continuous_and_may_repeat(self):
        curve = cr.cumulative_incidence(prepare(frame_of([1, 2, 4], [1, 2, 1]), group=""))[0]
        estimate, variance, beyond = cr.estimate_at(curve, 0, [3.5, 0.5, 1, 1, 4, 4.5])
        np.testing.assert_allclose(estimate, [1 / 3, 0, 1 / 3, 1 / 3, 2 / 3, 2 / 3])
        self.assertEqual(variance[1], 0)
        self.assertEqual(beyond.tolist(), [False, False, False, False, False, True])

    def test_intervals_are_truncated_and_empty_where_undefined(self):
        low, high = cr.interval(np.array([0.0, 0.02, 0.5, 1.0, 0.4]), np.array([0.0, 0.01, 0.04, 0.0, 0.0]), 95)
        self.assertTrue(np.isnan(low[[0, 3, 4]]).all() and np.isnan(high[[0, 3, 4]]).all())
        self.assertEqual(low[1], 0.0)
        self.assertAlmostEqual(low[2], 0.5 - 1.959963984540054 * 0.2)
        self.assertAlmostEqual(high[2], 0.5 + 1.959963984540054 * 0.2)
        _, wide = cr.interval(np.array([0.9]), np.array([0.25]), 99)
        self.assertEqual(wide[0], 1.0)

    def test_group_labels_keep_first_appearance_and_integral_numbers_lose_the_decimal_point(self):
        frame = frame_of([1, 2, 3, 4], [1, 0, 2, 1], [2.0, 1.0, 2.0, 1.0])
        self.assertEqual(prepare(frame).groups, ["2", "1"])


class StatusCodingTests(unittest.TestCase):
    def test_text_statuses_are_literal_and_keep_their_spaces(self):
        frame = frame_of([1, 2, 3, 4], ["ok", " ok", "x", "ok"])
        dataset = prepare(frame, censor="ok", events=[" ok", "x"], group="")
        self.assertEqual(dataset.code.tolist(), [0, 1, 2, 0])
        with self.assertRaises(FieldError) as error:
            prepare(frame, censor="ok", events=["x"], group="")
        self.assertEqual(error.exception.field, "Status")
        self.assertIn("Source row 1", str(error.exception))

    def test_numeric_codes_are_exact_integers(self):
        big = 2**60
        frame = frame_of([1, 2, 3], [big, big + 1, 0])
        dataset = prepare(frame, events=[str(big), str(big + 1)], group="")
        self.assertEqual(sorted(dataset.code.tolist()), [0, 1, 2])
        self.assertEqual(dataset.code[np.argsort(dataset.time)].tolist(), [1, 2, 0])
        for events in (["1", "1.0"], ["2", "2.00"]):
            with self.assertRaises(FieldError) as error:
                prepare(frame_of([1, 2], [1, 2]), events=events, group="")
            self.assertEqual(error.exception.field, "Event codes")

    def test_extreme_exponents_are_rejected_before_conversion_to_integer(self):
        for text in ("1e100000000", "-1e100000000"):
            with self.subTest(text=text), self.assertRaisesRegex(FieldError, "64-bit integer range"):
                cr.parse_code(text, "Event codes", numeric=True)

    def test_time_precision_loss_does_not_merge_distinct_observations(self):
        values = [2**53, 2**53 + 1, 2**53 + 2]
        for series in (pd.Series(values), pd.Series(values, dtype=object),
                       pd.Series([str(value) for value in values], dtype=object)):
            with self.subTest(dtype=series.dtype), self.assertRaises(FieldError) as error:
                prepare(frame_of(series, [1, 2, 0]), group="")
            self.assertEqual(error.exception.field, "Time")
        with self.assertRaises(FieldError) as error:
            prepare(frame_of(pd.Series([True, 2, 3], dtype=object), [1, 2, 0]), group="")
        self.assertEqual(error.exception.field, "Time")

    def test_a_float_status_column_accepts_whole_numbers_written_either_way(self):
        frame = frame_of([1.0, 2.0, 3.0], [1.0, 2.0, 0.0])
        self.assertEqual(sorted(prepare(frame, events=["1", "2.0"], group="").code.tolist()), [0, 1, 2])
        with self.assertRaises(FieldError) as error:
            prepare(frame, events=["1.5", "2"], group="")
        self.assertEqual(error.exception.field, "Event codes")

    def test_unusable_status_columns_are_rejected_on_the_status_field(self):
        cases = {"boolean": [True, False, True], "complex": [1 + 0j, 0j, 1 + 0j], "mixed": [1, "a", 0],
                 "object bool": pd.Series([True, 0, 1], dtype=object)}
        for name, values in cases.items():
            with self.subTest(name), self.assertRaises(FieldError) as error:
                prepare(frame_of([1, 2, 3], values), group="")
            self.assertEqual(error.exception.field, "Status")

    def test_status_codes_that_cannot_be_compared_are_refused(self):
        frame = frame_of([1, 2], [1, 0])
        for field, censor, events in (("Event codes", "0", ["1", "99999999999999999999"]), ("Event codes", "0", [""]),
                                      ("Event codes", "0", []), ("Event codes", "0", list("1234567")),
                                      ("Censor code", "1", ["1"]), ("Censor code", "", ["1"]),
                                      ("Censor code", "0", ["0"])):
            with self.subTest(field, censor=censor, events=events), self.assertRaises(FieldError) as error:
                prepare(frame, censor=censor, events=events, group="")
            self.assertEqual(error.exception.field, field)

    def test_cells_missing_from_any_role_are_omitted_before_the_codes_are_read(self):
        frame = frame_of([1, 2, np.nan, 4, 5], [1, 99, 0, None, 2], ["A", None, "A", "B", "B"])
        dataset = prepare(frame, events=["1", "2"])
        self.assertEqual((dataset.complete, dataset.omitted), (2, 3))
        self.assertEqual(dataset.groups, ["A", "B"])

    def test_every_role_is_validated_on_its_own_field(self):
        good = frame_of([1.0, 2.0, 3.0], [1, 0, 2], ["A", "A", "B"])
        cases = [("Time", dict(time="nope")), ("Time", dict(time="")), ("Status", dict(status="nope")),
                 ("Group", dict(group="nope")), ("Status", dict(status="t")), ("Group", dict(group="t"))]
        for field, change in cases:
            arguments = dict(time="t", status="s", group="g", censor="0", events=["1", "2"])
            arguments.update(change)
            with self.subTest(field, change=change), self.assertRaises(FieldError) as error:
                cr.prepare(good, **arguments)
            self.assertEqual(error.exception.field, field)
        negative = good.assign(t=[1.0, -2.0, 3.0])
        with self.assertRaises(FieldError) as error:
            prepare(negative)
        self.assertEqual(error.exception.field, "Time")
        self.assertIn("Source row 1", str(error.exception))
        for bad in (np.inf, "text"):
            with self.assertRaises(FieldError) as error:
                prepare(good.assign(t=[1.0, bad, 3.0]).astype({"t": object}))
            self.assertEqual(error.exception.field, "Time")

    def test_limits_on_rows_groups_and_roles(self):
        many = frame_of(np.arange(13.0), [1] * 13, [f"G{i}" for i in range(13)])
        with self.assertRaises(FieldError) as error:
            prepare(many)
        self.assertEqual(error.exception.field, "Group")
        with self.assertRaises(FieldError) as error:
            cr.prepare(frame_of([1.0, 2.0], [1, 0]), "t", "t", "", "0", ["1"])
        self.assertEqual(error.exception.field, "Status")
        with self.assertRaises(FieldError) as error:
            prepare(frame_of([np.nan], [np.nan]), group="")
        self.assertIn("No complete rows", str(error.exception))
        with self.assertRaises(FieldError):
            prepare(pd.DataFrame({"t": np.zeros(cr.MAX_ROWS + 1), "s": 0}), group="")


class GrayTests(unittest.TestCase):
    def test_no_event_of_the_cause_one_group_and_all_censored_are_unavailable_with_a_reason(self):
        lone = prepare(frame_of([1, 2, 3], [1, 0, 2]), group="")
        self.assertIn("at least two groups", cr.gray_test(lone, 0, [0]).reason)
        frame = frame_of([1, 2, 3, 1, 2, 3], [2, 2, 0, 2, 0, 2], ["A"] * 3 + ["B"] * 3)
        result = cr.gray_test(prepare(frame), 0, [0, 1])
        self.assertFalse(result.available)
        self.assertTrue(result.reason)
        self.assertIsNone(result.p)
        self.assertIsNone(result.statistic)

    def test_singular_covariance_gives_no_p_value(self):
        case = next(case for case in RANDOM if case["name"] == "singular-covariance")
        dataset = cr.prepare(pd.DataFrame({"t": case["time"], "s": case["status"], "g": case["group"]}),
                             "t", "s", "g", "0", [str(k) for k in range(1, case["causes"] + 1)])
        checked = 0
        for k, reference in enumerate(case["omnibus"]):
            result = cr.gray_test(dataset, k, list(range(len(dataset.groups))))
            if reference is None and k + 1 in case["status"]:
                self.assertFalse(result.available)
                self.assertIn("singular", result.reason)
                self.assertIsNone(result.p)
                checked += 1
        self.assertGreater(checked, 0)

    def test_a_group_without_the_cause_or_without_events_is_still_compared_as_cmprsk_does(self):
        case = next(case for case in RANDOM if case["name"] == "group-without-the-cause")
        dataset = cr.prepare(pd.DataFrame({"t": case["time"], "s": case["status"], "g": case["group"]}),
                             "t", "s", "g", "0", ["1", "2"])
        result = cr.gray_test(dataset, 0, [0, 1, 2])
        self.assertTrue(result.available, result.reason)
        self.assertAlmostEqual(result.statistic, case["omnibus"][0], places=8)
        censored = next(case for case in RANDOM if case["name"] == "group-all-censored")
        dataset = cr.prepare(pd.DataFrame({"t": censored["time"], "s": censored["status"], "g": censored["group"]}),
                             "t", "s", "g", "0", ["1", "2"])
        self.assertFalse(cr.gray_test(dataset, 1, [0, 1, 2]).available)

    def test_solver_rejects_rank_deficiency_and_invalid_scores(self):
        full = cr._solve(np.array([1.0, 2.0]), np.array([[2.0, 0.5], [0.5, 3.0]]), 3)
        self.assertTrue(full.available)
        self.assertEqual(full.df, 2)
        self.assertAlmostEqual(full.statistic, float(np.array([1, 2]) @ np.linalg.solve([[2, .5], [.5, 3]], [1, 2])))
        deficient = cr._solve(np.array([1.0, 1.0]), np.array([[1.0, 1.0], [1.0, 1.0]]), 3)
        nearly = cr._solve(np.array([1.0, 1.0]), np.array([[1.0, 1.0 - 1e-13], [1.0 - 1e-13, 1.0]]), 3)
        zero = cr._solve(np.array([0.0, 1.0]), np.array([[0.0, 0.0], [0.0, 1.0]]), 3)
        for result in (deficient, nearly, zero):
            self.assertFalse(result.available)
            self.assertIn("singular", result.reason)
        scaled = cr._solve(np.array([1e-9, 2e-9]), np.array([[2e-18, 5e-19], [5e-19, 3e-18]]), 3)
        self.assertTrue(scaled.available)
        self.assertAlmostEqual(scaled.statistic, full.statistic, places=8)
        # An indefinite matrix is not refused, as in cmprsk, but a negative statistic never becomes a p value.
        self.assertTrue(cr._solve(np.array([1.0, 3.0]), np.array([[1.0, 2.0], [2.0, 1.0]]), 3).available)
        negative = cr._solve(np.array([1.0, -1.0]), np.array([[1.0, 2.0], [2.0, 1.0]]), 3)
        self.assertFalse(negative.available)
        self.assertIn("chi-square", negative.reason)
        # A variance that is rounding noise against what built it is zero.
        noise = cr._solve(np.array([0.0]), np.array([[4.9e-32]]), 2, np.array([1.0]))
        self.assertFalse(noise.available)

    def test_pairwise_work_is_counted_by_comparison(self):
        frame = frame_of([1, 2, 3, 1, 2, 3, 4, 5], [1, 0, 2, 1, 2, 0, 1, 1], ["A", "A", "A", "B", "B", "B", "C", "C"])
        dataset = prepare(frame)
        omnibus = cr.check_gray_budget(dataset, False)
        self.assertEqual(omnibus, 9 * 5 * 2)
        self.assertGreater(cr.check_gray_budget(dataset, True), omnibus)


class CancelAndBudgetTests(unittest.TestCase):
    def test_cancel_stops_the_curves_and_the_tests(self):
        dataset = prepare_fixture("cohorts")
        stop = threading.Event()
        cr.cumulative_incidence(dataset, stop)
        stop.set()
        with self.assertRaises(cr.CompetingRisksCancelled):
            cr.cumulative_incidence(dataset, stop)
        with self.assertRaises(cr.CompetingRisksCancelled):
            cr.gray_test(dataset, 0, [0, 1, 2], cancel=stop)
        with self.assertRaises(cr.CompetingRisksCancelled):
            cr.gray_test(dataset, 0, [0, 1], cr.gray_tracks(dataset), cancel=stop)

    def test_cancel_is_honoured_between_blocks_of_a_long_test(self):
        rng = np.random.default_rng(1)
        n = 6000
        frame = frame_of(rng.random(n) * 100, rng.integers(0, 3, n), rng.integers(0, 3, n))
        dataset = prepare(frame)
        seen = []

        class Watch:
            def is_set(self):
                seen.append(1)
                return len(seen) > 3

        old = cr._CHUNK
        cr._CHUNK = 4000
        try:
            with self.assertRaises(cr.CompetingRisksCancelled):
                cr.gray_test(dataset, 0, [0, 1, 2], cancel=Watch())
        finally:
            cr._CHUNK = old
        self.assertGreater(len(seen), 3)

    def test_curve_sheet_budget_names_the_time_field(self):
        rng = np.random.default_rng(2)
        n = 50_000
        frame = frame_of(rng.random(n), rng.integers(0, 6, n), rng.integers(0, 5, n))
        dataset = prepare(frame, events=list("12345"))
        with self.assertRaises(FieldError) as error:
            cr.check_curve_budget(dataset)
        self.assertEqual(error.exception.field, "Time")
        self.assertGreater(cr.curve_rows(dataset), cr.MAX_CURVE_ROWS)

    def test_gray_budget_points_at_the_field_that_fits_it_back(self):
        rng = np.random.default_rng(3)
        n = 100_000
        base = dict(t=rng.random(n), s=rng.integers(0, 4, n))
        two = dict(t=base["t"], s=rng.integers(0, 3, n))
        many = prepare(pd.DataFrame({**base, "g": rng.integers(0, 12, n)}), events=["1", "2", "3"])
        with self.assertRaises(FieldError) as error:
            cr.check_gray_budget(many, False)
        self.assertEqual(error.exception.field, "Group")
        few = prepare(pd.DataFrame({**base, "g": rng.integers(0, 3, n)}), events=["1", "2", "3"])
        self.assertLessEqual(cr.check_gray_budget(few, False), cr.MAX_GRAY_WORK)
        with self.assertRaises(FieldError) as error:
            cr.check_gray_budget(prepare(pd.DataFrame({**two, "g": rng.integers(0, 12, n)}), events=["1", "2"]), True)
        self.assertEqual(error.exception.field, "Gray tests")


class ScaleTests(unittest.TestCase):
    """The largest allowed input finishes in seconds and never loops over subjects in Python."""

    def test_fifty_thousand_subjects_four_groups_three_causes(self):
        rng = np.random.default_rng(5)
        n = 50_000
        frame = frame_of(rng.exponential(10, n), rng.choice(4, n, p=[.3, .25, .25, .2]), rng.integers(0, 4, n))
        dataset = prepare(frame, events=["1", "2", "3"])
        curves = cr.cumulative_incidence(dataset)
        self.assertEqual(sum(curve.n for curve in curves), n)
        total = curves[0].survival[-1] + curves[0].incidence[:, -1].sum()
        self.assertAlmostEqual(total, 1.0, places=12)

    def test_gray_with_three_groups_and_a_thousand_subjects(self):
        rng = np.random.default_rng(6)
        n = 1000
        frame = frame_of(rng.exponential(10, n), rng.choice(3, n, p=[.3, .4, .3]), rng.integers(0, 3, n))
        dataset = prepare(frame)
        tracks = cr.gray_tracks(dataset)
        for k in range(2):
            result = cr.gray_test(dataset, k, [0, 1, 2], tracks)
            self.assertTrue(result.available, result.reason)
            self.assertTrue(0 <= result.p <= 1)


if __name__ == "__main__":
    unittest.main()
