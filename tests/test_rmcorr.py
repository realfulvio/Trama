"""Repeated-measures correlation: frozen references, an independent ANCOVA oracle, row mapping and limits.

The frozen numbers (tests/data/rmcorr/expected.json) come from the delivery package and were computed outside
Trama with SciPy on the centred pairs. The ANCOVA oracle refits Y ~ subject + X by least squares with statsmodels;
Bakdash and Marusich (2017) define r_rm from that model, so it shares no code with the engine.
"""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

from analisi import rmcorr
from analisi.data import Dataset
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "rmcorr"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = rmcorr.RMCORR
BASE = {"Subject": "Participant", "X": "Day", "Y": "Signal", "Confidence interval": "None",
        "Confidence level (%)": 95.0, "Bootstrap replicates": 200, "Seed": 867531, "Show graph": False}
BOOT = BASE | {"Confidence interval": "Subject bootstrap"}


def fixture(name="repeated.csv"):
    return pd.read_csv(DATA / name, keep_default_na=False, dtype={"Participant": str}).replace("", np.nan)


def run(frame=None, **overrides):
    return analyse(METHOD, fixture() if frame is None else frame, BASE | overrides)


def summary(result):
    return result.tables[METHOD].iloc[0]


def ancova(frame, subject="Participant", x="Day", y="Signal"):
    """r_rm, slope, t, p, df and intercepts from the least-squares fit Y ~ subject + X (subjects with ≥ 2 pairs)."""
    data = frame[[subject, x, y]].dropna()
    counts = data[subject].value_counts()
    data = data[data[subject].map(counts) >= 2]
    levels = list(dict.fromkeys(data[subject]))
    design = np.column_stack([(data[subject] == level).to_numpy(float) for level in levels]
                             + [data[x].to_numpy(float)])
    fit = sm.OLS(data[y].to_numpy(float), design).fit()
    slope = fit.params[-1]
    reduced = sm.OLS(data[y].to_numpy(float), design[:, :-1]).fit()
    ss_x = reduced.ssr - fit.ssr
    r = np.sign(slope) * np.sqrt(ss_x / (ss_x + fit.ssr))
    return {"r": r, "slope": slope, "t": fit.tvalues[-1], "p": fit.pvalues[-1], "df": fit.df_resid,
            "intercepts": fit.params[:-1], "levels": levels}


def assert_field(test, field, call, contains=""):
    with test.assertRaises(FieldError) as caught:
        call()
    test.assertEqual(caught.exception.field, field, str(caught.exception))
    test.assertIn(contains, str(caught.exception))
    return str(caught.exception)


class FrozenReferenceTests(unittest.TestCase):
    def test_fixture_matches_the_package_reference(self):
        result = run()
        self.assertEqual(list(result.tables), [METHOD, "Participants", "Pairs"])
        self.assertIsNone(result.figure)
        row = summary(result)
        self.assertEqual(list(result.tables[METHOD].columns), rmcorr.SUMMARY_COLUMNS)
        self.assertEqual((row["N"], row["Subjects"], row["df"]), (11, 3, 7))
        for key in ("Coefficient", "Slope", "t", "p"):
            np.testing.assert_allclose(row[key], EXPECTED[key], rtol=1e-12, atol=1e-15)
        self.assertTrue(pd.isna(row["Lower"]) and pd.isna(row["Upper"]) and pd.isna(row["Bootstrap valid"]))
        self.assertEqual(row["Interval status"], rmcorr.NOT_REQUESTED)
        participants = result.tables["Participants"]
        self.assertEqual(list(participants["Subject"]), ["A", "B", "C", "D"])
        np.testing.assert_allclose(participants["Intercept"].iloc[:3], EXPECTED["Intercepts"], rtol=1e-12)
        self.assertEqual(list(participants["Status"]), ["Used", "Used", "Used", "Singleton"])
        self.assertEqual(list(participants["Pairs used"]), [3, 4, 4, 0])
        self.assertTrue(pd.isna(participants["Intercept"].iloc[3]))

    def test_pooled_pearson_differs_from_the_within_subject_coefficient(self):
        frame = fixture().dropna()
        pooled = stats.pearsonr(frame["Day"].astype(float), frame["Signal"].astype(float)).statistic
        self.assertLess(pooled, 0)
        self.assertGreater(summary(run())["Coefficient"], 0.78)

    def test_independent_ancova_oracle_on_unequal_subjects(self):
        rng = np.random.default_rng(20261118)
        sizes = [2, 3, 5, 8, 4, 2, 6]
        rows = []
        for number, size in enumerate(sizes):
            x = rng.normal(10 * number, 3, size)
            rows += [(f"S{number}", value, 4 * number - 0.6 * value + rng.normal(0, 1)) for value in x]
        frame = pd.DataFrame(rows, columns=["Participant", "Day", "Signal"]).sample(frac=1, random_state=4)
        reference = ancova(frame)
        result = run(frame.reset_index(drop=True))
        row = summary(result)
        np.testing.assert_allclose([row["Coefficient"], row["Slope"], row["t"], row["p"]],
                                   [reference["r"], reference["slope"], reference["t"], reference["p"]], rtol=1e-9)
        self.assertEqual(row["df"], reference["df"])
        participants = result.tables["Participants"].set_index("Subject")
        np.testing.assert_allclose(participants.loc[reference["levels"], "Intercept"], reference["intercepts"],
                                   rtol=1e-9, atol=1e-9)
        pairs = result.tables["Pairs"]
        np.testing.assert_allclose(pairs["Fitted"],
                                   participants.loc[pairs["Subject"], "Intercept"].to_numpy() + row["Slope"] * pairs["X"])

    def test_formula_is_not_pooled_or_mean_correlation(self):
        """A wrong centring (global instead of per subject) would fail this case."""
        frame = pd.DataFrame({"Participant": list("AAABBB"), "Day": [1, 2, 3, 11, 12, 13],
                              "Signal": [10, 9, 8, 30, 29, 28]})
        row = summary(run(frame))
        self.assertEqual(row["Coefficient"], -1.0)
        self.assertEqual(row["t"], -np.inf)
        self.assertEqual(row["p"], 0.0)
        self.assertGreater(stats.pearsonr(frame["Day"], frame["Signal"]).statistic, 0.9)


class RowMappingTests(unittest.TestCase):
    def test_source_rows_are_physical_positions_even_with_a_duplicate_index(self):
        frame = fixture()
        frame.index = [9] * len(frame)
        pairs = run(frame).tables["Pairs"]
        self.assertEqual(list(pairs["Source row"]), list(range(1, 14)))
        self.assertEqual(list(pairs["Status"]), ["Used"] * 11 + ["Missing pair", "Singleton"])
        self.assertTrue(pairs["Fitted"].iloc[11:].isna().all())
        self.assertEqual(list(pairs.columns), rmcorr.PAIR_COLUMNS)

    def test_entirely_empty_rows_are_skipped_but_keep_their_position(self):
        frame = fixture()
        blank = pd.DataFrame({"Participant": [np.nan], "Day": [np.nan], "Signal": [np.nan]})
        frame = pd.concat([frame.iloc[:2], blank, frame.iloc[2:]], ignore_index=True)
        pairs = run(frame).tables["Pairs"]
        self.assertEqual(list(pairs["Source row"]), [1, 2, *range(4, 15)])
        self.assertEqual(len(pairs), 13)

    def test_a_value_without_subject_is_an_error_on_subject(self):
        frame = fixture()
        frame.loc[5, "Participant"] = np.nan
        message = assert_field(self, "Subject", lambda: run(frame), "Row 6")
        self.assertIn("no subject", message)
        frame.loc[5, "Participant"] = "   "
        assert_field(self, "Subject", lambda: run(frame), "Row 6")

    def test_subject_with_no_complete_pairs_is_reported_last(self):
        frame = pd.concat([pd.DataFrame({"Participant": ["E", "E"], "Day": [1.0, np.nan], "Signal": [np.nan, 2.0]}),
                           fixture()], ignore_index=True)
        result = run(frame)
        participants = result.tables["Participants"]
        self.assertEqual(list(participants["Subject"]), ["A", "B", "C", "D", "E"])
        self.assertEqual(participants["Status"].iloc[-1], rmcorr.NO_PAIRS)
        self.assertEqual(list(result.tables["Pairs"]["Status"].iloc[:2]), ["Missing pair", "Missing pair"])

    def test_order_follows_the_first_complete_pair(self):
        frame = pd.DataFrame({"Participant": ["B", "A", "A", "B", "B"], "Day": [1.0, 1, 2, 2, 3],
                              "Signal": [np.nan, 1, 3, 2, 5]})
        participants = run(frame).tables["Participants"]
        self.assertEqual(list(participants["Subject"]), ["A", "B"])

    def test_text_infinite_and_out_of_range_values_name_field_and_row(self):
        for value, contains in (("abc", "not a finite number in row 4"), (np.inf, "not a finite number in row 4"),
                                (2e100, "outside −1e100 to 1e100 in row 4")):
            frame = fixture().astype({"Day": object})
            frame.loc[3, "Day"] = value
            assert_field(self, "X", lambda: run(frame), contains)
        frame = fixture().astype({"Signal": object})
        frame.loc[0, "Signal"] = "1,5"
        assert_field(self, "Y", lambda: run(frame), "row 1")

    def test_numeric_text_and_blank_text_are_read(self):
        frame = fixture().astype({"Day": object})
        frame["Day"] = [str(value) if pd.notna(value) else "  " for value in fixture()["Day"]]
        np.testing.assert_allclose(summary(run(frame))["Coefficient"], EXPECTED["Coefficient"], rtol=1e-12)

    def test_excluded_cells_follow_the_project_mask(self):
        dataset = Dataset(fixture())
        dataset.excluded = {(0, 2), (12, 0), (12, 1), (12, 2)}   # Y of row 1, and the whole singleton row
        pairs = run(dataset.frame(mask_excluded=True)).tables["Pairs"]
        self.assertEqual(pairs["Status"].iloc[0], "Missing pair")
        self.assertEqual(list(pairs["Source row"]), list(range(1, 13)))
        self.assertNotIn("D", set(pairs["Subject"]))

    def test_literal_subject_labels(self):
        frame = fixture("another-subject.csv")
        result = run(frame, **{"Show graph": True})
        self.assertEqual(list(result.tables["Participants"]["Subject"]), ["001", "002", "003"])
        legend = result.figure.axes[0].get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["001", "002", "003"])
        special = fixture().replace({"Participant": {"A": "$x_1$", "B": "_hidden", "C": "{C}"}})
        result = run(special, **{"Show graph": True})
        texts = result.figure.axes[0].get_legend().get_texts()
        self.assertEqual([text.get_text() for text in texts][:3], ["$x_1$", "_hidden", "{C}"])
        self.assertTrue(all(not text.get_parse_math() for text in texts))

    def test_subject_identity_is_typed(self):
        frame = pd.DataFrame({"Participant": [1, 1.0, "1", "1", 2, 2], "Day": [1.0, 2, 1, 3, 1, 2],
                              "Signal": [1.0, 2, 2, 5, 3, 3.5]}, dtype=object)
        participants = run(frame).tables["Participants"]
        self.assertEqual(participants["Subject"].tolist(), [1, "1", 2])
        self.assertEqual(participants["Pairs used"].tolist(), [2, 2, 2])


class NumericTests(unittest.TestCase):
    def test_subject_shifts_and_unit_changes(self):
        reference = summary(run())
        frame = fixture()
        dx = frame["Participant"].map({"A": 1e6, "B": -3e5, "C": 7e4, "D": 94})
        frame["Day"] = frame["Day"].astype(float) * 1000 + dx
        frame["Signal"] = frame["Signal"].astype(float) * 1e6 - 5 * dx
        row = summary(run(frame))
        np.testing.assert_allclose(row["Coefficient"], reference["Coefficient"], rtol=1e-9)
        np.testing.assert_allclose(row["Slope"], reference["Slope"] * 1e3, rtol=1e-9)
        np.testing.assert_allclose(row["p"], reference["p"], rtol=1e-8)

    def test_tiny_and_huge_units_do_not_underflow_or_overflow(self):
        reference = summary(run())
        for factor in (1e-150, 1e90):
            frame = fixture()
            frame["Day"] = frame["Day"].astype(float) * factor
            frame["Signal"] = frame["Signal"].astype(float) * factor
            row = summary(run(frame))
            np.testing.assert_allclose([row["Coefficient"], row["p"]], [reference["Coefficient"], reference["p"]],
                                       rtol=1e-10)

    def test_variation_lost_to_rounding_is_refused(self):
        frame = fixture()
        frame["Day"] = 1e12 + frame["Day"].astype(float) * 1e-4
        assert_field(self, "X", lambda: run(frame), "precision")

    def test_constant_x_within_subjects(self):
        frame = fixture().assign(Day=lambda f: f["Participant"].map({"A": 1, "B": 2, "C": 3, "D": 4}))
        assert_field(self, "X", lambda: run(frame), "does not vary")
        frame = fixture().assign(Signal=lambda f: f["Participant"].map({"A": 1, "B": 2, "C": 3, "D": 4}))
        assert_field(self, "Y", lambda: run(frame), "does not vary")

    def test_one_flat_subject_is_accepted(self):
        frame = fixture()
        frame.loc[frame["Participant"] == "A", "Day"] = 5.0
        reference = ancova(frame)
        row = summary(run(frame))
        np.testing.assert_allclose([row["Coefficient"], row["p"]], [reference["r"], reference["p"]], rtol=1e-9)

    def test_perfect_fit_is_exact_and_drawn_with_finite_coordinates(self):
        frame = fixture("another-subject.csv")
        frame["Participant"] = ["001", "001", "002", "002", "003", "003"]
        result = run(frame, **{"Show graph": True})
        row = summary(result)
        self.assertEqual((row["Coefficient"], row["Slope"], row["t"], row["p"]), (1.0, 2.0, np.inf, 0.0))
        for line in result.figure.axes[0].lines:
            self.assertTrue(np.isfinite(np.asarray(line.get_xydata(), dtype=float)).all())
        from io import BytesIO
        result.figure.savefig(BytesIO(), format="svg")

    def test_two_subjects_are_required(self):
        frame = fixture()
        frame = frame[frame["Participant"].isin(["A", "D"])]
        assert_field(self, "Subject", lambda: run(frame), "were found")

    def test_limits(self):
        many = pd.DataFrame({"Participant": np.repeat(np.arange(501), 2), "Day": np.tile([0.0, 1.0], 501),
                             "Signal": np.random.default_rng(1).normal(size=1002)})
        assert_field(self, "Subject", lambda: run(many), "At most 500")
        big = pd.DataFrame({"Participant": np.repeat(np.arange(100), 501), "Day": np.tile(np.arange(501.0), 100),
                            "Signal": np.random.default_rng(2).normal(size=50_100)})
        assert_field(self, "Y", lambda: run(big), "At most 50,000")
        frame = pd.DataFrame({"Participant": np.repeat(np.arange(300), 2), "Day": np.tile([0.0, 1.0], 300),
                              "Signal": np.random.default_rng(3).normal(size=600)})
        assert_field(self, "Bootstrap replicates",
                     lambda: analyse(METHOD, frame, BOOT | {"Bootstrap replicates": 10_000}), "2,000,000")


class OptionTests(unittest.TestCase):
    def test_roles(self):
        assert_field(self, "Y", lambda: run(Y="Day"), "three different columns")
        assert_field(self, "X", lambda: run(X="Participant"), "three different columns")
        assert_field(self, "Y", lambda: run(Y="Participant"), "three different columns")
        assert_field(self, "Subject", lambda: run(Subject=""), "Choose a column")
        assert_field(self, "X", lambda: run(X="Missing"), "not in the table")

    def test_seed_is_exact_without_float(self):
        for seed in (2**64 - 1, "18446744073709551615", np.uint64(2**64 - 1), 0):
            result = analyse(METHOD, fixture(), BOOT | {"Seed": seed})
            self.assertEqual(summary(result)["Seed"], str(int(seed)))
        for seed in (-1, 2**64, 1.0, True, "1e3", "", None):
            assert_field(self, "Seed", lambda seed=seed: analyse(METHOD, fixture(), BOOT | {"Seed": seed}))
        # Seeds that a float would merge stay distinct streams.
        first = analyse(METHOD, fixture(), BOOT | {"Seed": 2**63 + 1}).tables["Bootstrap"]["Coefficient"]
        second = analyse(METHOD, fixture(), BOOT | {"Seed": 2**63}).tables["Bootstrap"]["Coefficient"]
        self.assertFalse(np.array_equal(first, second))

    def test_replicates_level_and_flags(self):
        for count in (99, 10_001, 150.0, "x"):
            assert_field(self, "Bootstrap replicates",
                         lambda count=count: analyse(METHOD, fixture(), BOOT | {"Bootstrap replicates": count}))
        for level in (0, 100, np.nan, "95", True):
            assert_field(self, "Confidence level (%)",
                         lambda level=level: analyse(METHOD, fixture(), BOOT | {"Confidence level (%)": level}))
        assert_field(self, "Confidence interval", lambda: run(**{"Confidence interval": "Fisher"}))
        assert_field(self, "Show graph", lambda: run(**{"Show graph": "yes"}))

    def test_inactive_bootstrap_fields_are_ignored_without_the_interval(self):
        result = run(**{"Seed": -5, "Bootstrap replicates": 1, "Confidence level (%)": 400})
        self.assertEqual(list(result.tables), [METHOD, "Participants", "Pairs"])

    def test_defaults_of_a_short_recipe(self):
        result = analyse(METHOD, fixture(), {"Subject": "Participant", "X": "Day", "Y": "Signal"})
        self.assertIsNotNone(result.figure)
        self.assertEqual(summary(result)["Interval status"], rmcorr.NOT_REQUESTED)
        self.assertEqual(rmcorr.DEFAULTS, {"Confidence interval": "None", "Confidence level (%)": 95.0,
                                           "Bootstrap replicates": 2000, "Seed": 0, "Show graph": True})


class BootstrapTests(unittest.TestCase):
    @staticmethod
    def literal_bootstrap(seed, replicates, frame=None):
        """Materialised copies and pearsonr, exactly as the package oracle draws them."""
        frame = fixture() if frame is None else frame
        groups = {}
        for subject, x, y in frame[["Participant", "Day", "Signal"]].dropna().itertuples(index=False):
            groups.setdefault(subject, []).append((float(x), float(y)))
        centred = [np.asarray(group) - np.asarray(group).mean(axis=0) for group in groups.values() if len(group) > 1]
        rng = np.random.Generator(np.random.PCG64(seed))
        out = []
        for _ in range(replicates):
            ids = rng.integers(0, len(centred), size=len(centred))
            pairs = np.vstack([centred[i] for i in ids])
            out.append(stats.pearsonr(*pairs.T).statistic)
        return np.asarray(out)

    def test_interval_and_first_replicates(self):
        result = analyse(METHOD, fixture(), BOOT)
        self.assertEqual(list(result.tables), [METHOD, "Participants", "Pairs", "Bootstrap"])
        row = summary(result)
        self.assertEqual(list(result.tables[METHOD].columns), rmcorr.SUMMARY_COLUMNS + rmcorr.BOOTSTRAP_COLUMNS)
        np.testing.assert_allclose([row["Lower"], row["Upper"]], EXPECTED["Interval"], rtol=1e-12)
        self.assertEqual(row["Bootstrap valid"], 200)
        self.assertEqual(row["Interval status"], rmcorr.APPROXIMATE)
        self.assertEqual((row["Confidence level (%)"], row["Bootstrap replicates"], row["Seed"]), (95.0, 200, "867531"))
        values = result.tables["Bootstrap"]
        self.assertEqual(list(values["Replicate"]), list(range(1, 201)))
        np.testing.assert_allclose(values["Coefficient"].iloc[:5], EXPECTED["Bootstrap first five"], rtol=1e-12)
        np.testing.assert_allclose(values["Coefficient"], self.literal_bootstrap(867531, 200), rtol=1e-12)
        again = analyse(METHOD, fixture(), BOOT).tables["Bootstrap"]["Coefficient"]
        np.testing.assert_array_equal(values["Coefficient"], again)

    def test_other_level_uses_linear_percentiles(self):
        result = analyse(METHOD, fixture(), BOOT | {"Confidence level (%)": 80.0, "Seed": 5})
        reference = np.quantile(self.literal_bootstrap(5, 200), [0.1, 0.9], method="linear")
        row = summary(result)
        np.testing.assert_allclose([row["Lower"], row["Upper"]], reference, rtol=1e-12)

    def test_degenerate_replicates_and_the_80_percent_rule(self):
        # Subject F has no X variation: a replicate that draws only F has no coefficient.
        frame = pd.DataFrame({"Participant": list("FFGG"), "Day": [3.0, 3.0, 1.0, 2.0], "Signal": [1.0, 4.0, 2.0, 3.0]})
        frame = pd.concat([frame, pd.DataFrame({"Participant": ["H", "H"], "Day": [5.0, 7.0],
                                                "Signal": [1.0, 2.0]})], ignore_index=True)
        result = analyse(METHOD, frame, BOOT)
        values = result.tables["Bootstrap"]
        degenerate = values["Status"] == rmcorr.DEGENERATE
        self.assertTrue(degenerate.any())
        self.assertTrue(values.loc[degenerate, "Coefficient"].isna().all())
        row = summary(result)
        self.assertEqual(row["Bootstrap valid"], int((~degenerate).sum()))
        self.assertTrue(np.isfinite([row["Lower"], row["Upper"]]).all())
        two = frame[frame["Participant"] != "H"]
        row = summary(analyse(METHOD, two, BOOT | {"Seed": 3}))
        self.assertLess(5 * row["Bootstrap valid"], 4 * 200)
        self.assertTrue(pd.isna(row["Lower"]) and pd.isna(row["Upper"]))
        self.assertIn("at least 80% are required", row["Interval status"])

    def test_interval_rule_at_exactly_80_percent(self):
        values = np.r_[np.linspace(0, 1, 80), np.full(20, np.nan)]
        low, high, count, status = rmcorr.interval(values, 95.0)
        self.assertEqual((count, status), (80, rmcorr.APPROXIMATE))
        low, high, count, status = rmcorr.interval(np.r_[np.linspace(0, 1, 79), np.full(21, np.nan)], 95.0)
        self.assertIsNone(low)
        self.assertIsNone(high)

    def test_copies_are_not_materialised(self):
        with patch.object(np, "vstack", side_effect=AssertionError("materialised")):
            analyse(METHOD, fixture(), BOOT)


class CancellationTests(unittest.TestCase):
    def test_cancel_before_the_first_replicate(self):
        calls = []
        with self.assertRaises(InterruptedError) as caught:
            analyse(METHOD, fixture(), BOOT, cancel=lambda: calls.append(1) or True)
        self.assertIsInstance(caught.exception, MonteCarloCancelled)
        self.assertEqual(len(calls), 1)

    def test_cancel_is_polled_before_every_replicate(self):
        seen = []

        def cancel():
            seen.append(1)
            return len(seen) > 150

        with self.assertRaises(rmcorr.RmcorrCancelled):
            analyse(METHOD, fixture(), BOOT, cancel=cancel)
        self.assertEqual(len(seen), 151)
        seen.clear()
        analyse(METHOD, fixture(), BOOT, cancel=lambda: seen.append(1) and False)
        self.assertEqual(len(seen), 201)

    def test_threading_event_from_the_application(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(rmcorr.RmcorrCancelled):
            analyse(METHOD, fixture(), BOOT, cancel=event)
        event.clear()
        self.assertEqual(summary(analyse(METHOD, fixture(), BOOT, cancel=event))["Bootstrap valid"], 200)

    def test_without_bootstrap_cancel_is_not_needed(self):
        self.assertFalse(rmcorr.cancellable(METHOD, BASE))
        self.assertTrue(rmcorr.cancellable(METHOD, BOOT))
        self.assertFalse(rmcorr.cancellable("Correlation", BOOT))
        run(cancel=None)


class FigureTests(unittest.TestCase):
    def test_parallel_segments_over_each_observed_domain(self):
        result = run(**{"Show graph": True})
        figure = result.figure
        self.assertEqual(len(figure.axes), 1)
        axes = figure.axes[0]
        frame = fixture().dropna()
        lines = {line.get_gid(): line for line in axes.lines}
        for number, (subject, intercept) in enumerate(zip("ABC", EXPECTED["Intercepts"]), 1):
            fit, points = lines[f"rmcorr-fit-{number}"], lines[f"rmcorr-points-{number}"]
            x = frame.loc[frame["Participant"] == subject, "Day"].astype(float)
            np.testing.assert_allclose(fit.get_xdata(), [x.min(), x.max()])
            np.testing.assert_allclose(fit.get_ydata(), intercept + EXPECTED["Slope"] * np.asarray(fit.get_xdata()),
                                       rtol=1e-12)
            self.assertEqual(fit.get_color(), points.get_color())
        self.assertIn("rmcorr-singletons", lines)
        self.assertNotIn("rmcorr-fit-4", lines)
        from io import BytesIO
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        self.assertIn(b'id="rmcorr-fit-3"', buffer.getvalue())

    def test_many_subjects_get_a_short_legend(self):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame({"Participant": np.repeat([f"P{i}" for i in range(60)], 3),
                              "Day": np.tile([1.0, 2.0, 3.0], 60), "Signal": rng.normal(size=180)})
        legend = run(frame, **{"Show graph": True}).figure.axes[0].get_legend()
        self.assertLessEqual(len(legend.get_texts()), 3)
        self.assertIn("60 subjects", legend.get_texts()[0].get_text())
        small = run(**{"Show graph": True}).figure.axes[0].get_legend()
        self.assertEqual([text.get_text() for text in small.get_texts()],
                         ["A", "B", "C", "Single complete pair (not in the fit)"])

    def test_forty_subjects_have_distinct_styles(self):
        styles = {rmcorr.style_of(number) for number in range(rmcorr.LEGEND_LIMIT)}
        self.assertEqual(len(styles), rmcorr.LEGEND_LIMIT)

    def test_style_change_does_not_recalculate(self):
        from analisi.presentation import apply_style
        result = analyse(METHOD, fixture(), BOOT | {"Show graph": True})
        before = result.tables["Bootstrap"].copy()
        with patch.object(rmcorr, "bootstrap", side_effect=AssertionError("recalculated")):
            apply_style(result.figure, {"title": "Within-subject association", "xlabel": "Day (d)"})
        self.assertEqual(result.figure.axes[0].get_title(), "Within-subject association")
        pd.testing.assert_frame_equal(before, result.tables["Bootstrap"])


class CatalogTests(unittest.TestCase):
    def test_registered_near_correlation(self):
        group = GROUPS["Data Exploration and Summary"]
        self.assertEqual(group.index(METHOD), group.index("Correlation matrix") + 1)
        self.assertIs(METHODS[METHOD], rmcorr.OPTIONS)
        self.assertNotIn(METHOD, GRAPH_METHODS)   # optional graph, like Compare models (AICc)

    def test_historical_pearson_and_control_recipes_are_unchanged(self):
        frame = fixture().dropna()
        result = analyse("Correlation", frame, {"X": "Day", "Y": "Signal", "Method": "Pearson"})
        self.assertEqual(list(result.tables), ["Correlation"])
        expected = stats.pearsonr(frame["Day"].astype(float), frame["Signal"].astype(float))
        values = result.tables["Correlation"].iloc[:, 0]
        np.testing.assert_allclose([values["Coefficient"], values["p"]], [expected.statistic, expected.pvalue])
        control = analyse("Correlate against control", frame.assign(Other=frame["Signal"].astype(float) ** 2),
                          {"X": "Day", "Variables": ["Signal", "Other"]})
        self.assertEqual(list(control.tables), ["Correlations", "Pairs", "Settings"])


if __name__ == "__main__":
    unittest.main()
