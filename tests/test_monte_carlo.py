"""Monte Carlo study: independent references, repeatable streams, validation and cancellation."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi import monte_carlo as mc
from analisi.data import Dataset, load_project, save_project
from analisi.processing import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "monte_carlo"
ROW = ["Replicate", "Estimate", "Statistic", "p", "CI low", "CI high", "Reject", "Covers truth", "Status"]
SOURCE = pd.DataFrame({"Source": [1]})
WELCH = {"Study": mc.WELCH, "Replicates": 9, "Seed": 42, "Alpha": .1, "Interval level (%)": 90, "N A": 6, "N B": 8,
         "Mean A": 1.5, "Mean B": 3.0, "SD A": .9, "SD B": 1.8, "Null value": 0.}


def study(options, frame=SOURCE):
    return analyse(mc.MONTE_CARLO, frame, options)


def rows(result):
    return list(map(list, result.tables["Replicates"][ROW].itertuples(index=False, name=None)))


def cases():
    for name, spec in json.loads((DATA / "studies.json").read_text(encoding="utf-8")).items():
        frame = pd.read_csv(DATA / spec["worksheet"]) if "worksheet" in spec else SOURCE
        yield name, frame, spec["options"]


class MonteCarloTests(unittest.TestCase):
    def assertSame(self, actual, expected, path="result"):
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys(), path)
            for key in expected:
                self.assertSame(actual[key], expected[key], f"{path}.{key}")
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), path)
            for i, pair in enumerate(zip(actual, expected, strict=True)):
                self.assertSame(*pair, f"{path}[{i}]")
        elif expected is None:
            self.assertTrue(pd.isna(actual), (path, actual))
        elif isinstance(expected, bool):
            self.assertIsInstance(actual, (bool, np.bool_), path)
            self.assertEqual(bool(actual), expected, path)
        elif isinstance(expected, (int, str)):
            self.assertEqual(actual, expected, path)
        else:
            self.assertTrue(np.isclose(actual, expected, rtol=1e-9, atol=1e-11), (path, actual, expected))

    def test_independent_references(self):
        expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
        for name, frame, options in cases():
            with self.subTest(case=name):
                result = study(options, frame)
                self.assertIsNone(result.figure)
                summary, = result.tables["Summary"].to_dict(orient="records")
                self.assertSame({"rows": rows(result), "summary": summary}, expected[name], name)
                replicates = result.tables["Replicates"]
                reasons = replicates.loc[replicates["Status"] == mc.UNDEFINED, "Reason"]
                self.assertTrue(reasons.map(lambda text: bool(text.strip())).all())
                longer = study({**options, "Replicates": options["Replicates"] + 5}, frame)
                self.assertSame(rows(longer)[:options["Replicates"]], rows(result), f"{name}.prefix")

    def test_block_order_does_not_change_replicates(self):
        plan = mc.check_options(SOURCE, {**WELCH, "Replicates": 23})
        ordered = mc.replicate_table(plan, [mc.simulate_block(plan, start, stop) for start, stop in
                                            ((0, 5), (5, 11), (11, 23))])
        parts = {(start, stop): mc.simulate_block(plan, start, stop) for start, stop in ((11, 23), (5, 11), (0, 5))}
        reordered = mc.replicate_table(plan, [parts[key] for key in sorted(parts)])
        pd.testing.assert_frame_equal(ordered, reordered)
        pd.testing.assert_frame_equal(ordered, study({**WELCH, "Replicates": 23}).tables["Replicates"])
        single = mc.replicate_table(plan, [mc.simulate_block(plan, 17, 18)])
        self.assertEqual(single["Estimate"].iloc[0], ordered["Estimate"].iloc[17])

    def test_global_generator_is_untouched(self):
        np.random.seed(7)
        state = np.random.get_state()[1].copy()
        study(WELCH)
        np.testing.assert_array_equal(np.random.get_state()[1], state)

    def test_budget_is_checked_before_values_are_generated(self):
        with patch.object(mc, "_rng", side_effect=AssertionError("generated")), \
                patch.object(mc.np, "empty", side_effect=AssertionError("allocated")):
            with self.assertRaises(FieldError) as raised:
                study({**WELCH, "Replicates": 10_000, "N A": 100, "N B": 101})
            self.assertEqual(raised.exception.field, "Replicates")
            with self.assertRaises(FieldError):
                study({"Study": mc.OLS, "Replicates": 10_000, "N": 201, "Seed": 1})
            with self.assertRaises(FieldError):
                study({"Study": mc.PEARSON, "Replicates": 5_000, "N A": 200, "N B": 201})
        # Exactly at the limit is accepted.
        mc.check_options(SOURCE, {**WELCH, "Replicates": 10_000, "N A": 100, "N B": 100})
        frame = pd.DataFrame({"X": np.arange(201.)})
        with self.assertRaises(FieldError):
            mc.check_options(frame, {"Study": mc.OLS, "X source": mc.WORKSHEET, "X column": "X",
                                     "Replicates": 10_000})

    def test_seed_limits(self):
        for seed in (0, 2**64 - 1, np.uint64(2**64 - 1)):
            self.assertEqual(len(study({**WELCH, "Seed": seed}).tables["Replicates"]), 9)
        for seed in (-1, 2**64, True, 4.0, "42", None):
            with self.subTest(seed=seed), self.assertRaises(FieldError) as raised:
                study({**WELCH, "Seed": seed})
            self.assertEqual(raised.exception.field, "Seed")

    def test_invalid_numbers_name_their_field(self):
        bad = {
            "Replicates": (0, 10_001, 9.0, True, "9"), "Alpha": (0, 1, np.nan, np.inf, True, "0.05"),
            "Interval level (%)": (0, 100, 95e9, np.nan, -5, .95j), "N A": (1, 2.0, False), "SD A": (-1, np.inf, 1e-200),
            "Mean B": (np.nan, 1e101), "Graph": ("Histogram",), "Null value": (np.inf,),
        }
        for name, values in bad.items():
            for value in values:
                with self.subTest(field=name, value=value), self.assertRaises(FieldError) as raised:
                    study({**WELCH, name: value})
                self.assertEqual(raised.exception.field, name)
        pearson = {"Study": mc.PEARSON, "Replicates": 3, "N A": 4, "N B": 4, "Probability A": .2, "Probability B": .4}
        for name, value in (("Probability A", 1.1), ("Probability B", -.1), ("N A", 0), ("N B", 3.5)):
            with self.subTest(field=name), self.assertRaises(FieldError) as raised:
                study({**pearson, name: value})
            self.assertEqual(raised.exception.field, name)
        self.assertEqual(len(study({**pearson, "N A": 1}).tables["Replicates"]), 3)
        ols = {"Study": mc.OLS, "Replicates": 3, "N": 2}
        with self.assertRaises(FieldError) as raised:
            study(ols)
        self.assertEqual(raised.exception.field, "N")
        with self.assertRaises(FieldError) as raised:
            study({**ols, "N": 5, "X minimum": 3, "X maximum": 3})
        self.assertEqual(raised.exception.field, "X maximum")

    def test_only_fields_of_the_design_are_accepted(self):
        for options, name in (({**WELCH, "Probability A": .5}, "Probability A"),
                              ({**WELCH, "Colour": "red"}, "Study"),
                              ({"Study": mc.PEARSON, "Null value": 0}, "Null value"),
                              ({"Study": mc.OLS, "X column": "X"}, "X column"),
                              ({"Study": mc.OLS, "X source": mc.WORKSHEET, "X column": "X", "N": 5}, "N")):
            with self.subTest(field=name), self.assertRaises(FieldError) as raised:
                mc.check_options(pd.DataFrame({"X": [1., 2, 3]}), options)
            self.assertEqual(raised.exception.field, name)
        with self.assertRaises(FieldError) as raised:
            mc.check_options(SOURCE, {**WELCH, "Study": "Bootstrap"})
        self.assertEqual(raised.exception.field, "Study")

    def test_extension_keeps_prefix_after_save_and_reopen(self):
        frame = pd.DataFrame({"X": [2., -1, np.nan, 4, 2, 0]})
        options = {"Study": mc.OLS, "Replicates": 9, "Seed": 2**64 - 1, "X source": mc.WORKSHEET, "X column": "X",
                   "Intercept": 2., "Slope": -1.1, "SD": 2., "Null value": -.3}
        first = study(options, frame)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "study.alab"
            save_project(path, {"Data": Dataset(frame.copy(), analyses=[(mc.MONTE_CARLO, options)])})
            loaded = load_project(path)["Data"]
        (method, saved), = loaded.analyses
        self.assertEqual(saved, options)
        self.assertEqual(saved["Seed"], 2**64 - 1)
        reopened = study(saved, loaded.frame())
        pd.testing.assert_frame_equal(reopened.tables["Replicates"], first.tables["Replicates"])
        longer = study({**saved, "Replicates": 14}, loaded.frame())
        self.assertEqual(len(longer.tables["Replicates"]), 14)
        pd.testing.assert_frame_equal(longer.tables["Replicates"].iloc[:9], first.tables["Replicates"])
        settings = dict(zip(*longer.tables["Settings"].to_dict(orient="list").values(), strict=True))
        self.assertEqual(settings["X column"], "X")
        self.assertEqual(settings["X values ignored"], 1)
        self.assertEqual(settings["Effective N"], 5)
        self.assertEqual(settings["Seed"], str(2**64 - 1))

    def test_changing_the_seed_changes_estimates(self):
        base = study(WELCH).tables["Replicates"]["Estimate"]
        other = study({**WELCH, "Seed": 43}).tables["Replicates"]["Estimate"]
        self.assertTrue((base != other).any())
        pd.testing.assert_series_equal(base, study(WELCH).tables["Replicates"]["Estimate"])

    def test_zero_margins_stay_out_of_denominators(self):
        options = {"Study": mc.PEARSON, "Replicates": 18, "Seed": 14, "N A": 3, "N B": 5,
                   "Probability A": .07, "Probability B": .11}
        result = study(options)
        table, summary = result.tables["Replicates"], result.tables["Summary"].iloc[0]
        undefined = table["Status"] == mc.UNDEFINED
        self.assertTrue(undefined.any() and (~undefined).any())
        self.assertTrue(table.loc[undefined, ["Estimate", "p", "Reject"]].isna().all().all())
        self.assertEqual(summary["Valid"], (~undefined).sum())
        self.assertEqual(summary["Rejection rate"], summary["Rejected"] / summary["Valid"])
        self.assertEqual(summary["Coverage N"], 0)
        self.assertTrue(pd.isna(summary["Coverage rate"]))
        self.assertTrue(table["CI low"].isna().all() and table["Covers truth"].isna().all())

    def test_all_undefined_keeps_rows_and_reasons(self):
        for options in ({"Study": mc.PEARSON, "Replicates": 4, "Seed": 1, "N A": 3, "N B": 5,
                         "Probability A": 0, "Probability B": 0},
                        {**WELCH, "Replicates": 4, "SD A": 0, "SD B": 0},
                        {"Study": mc.OLS, "Replicates": 4, "N": 6, "SD": 0, "Graph": "Estimates"}):
            with self.subTest(study=options["Study"]):
                result = study(options)
                table, summary = result.tables["Replicates"], result.tables["Summary"].iloc[0]
                self.assertEqual(table["Replicate"].tolist(), [1, 2, 3, 4])
                self.assertTrue((table["Status"] == mc.UNDEFINED).all())
                self.assertTrue(table["Reason"].str.len().gt(10).all())
                self.assertEqual((summary["Requested"], summary["Valid"], summary["Undefined"]), (4, 0, 4))
                for name in ("Rejection rate", "Monte Carlo SE", "Rejection Wilson low", "Mean estimate", "RMSE",
                             "Estimate 50%"):
                    self.assertTrue(pd.isna(summary[name]), name)
        self.assertIn("No valid replicates", result.figure.axes[0].texts[0].get_text())

    def test_welch_under_null_rejects_near_alpha(self):
        result = study({"Study": mc.WELCH, "Replicates": 2000, "Seed": 42, "N A": 10, "N B": 10,
                        "Mean A": 0., "Mean B": 0., "SD A": 1., "SD B": 1.})
        rate = result.tables["Summary"].iloc[0]["Rejection rate"]
        self.assertTrue(.025 <= rate <= .075, rate)

    def test_wilson_matches_scipy(self):
        for k, n, level in ((0, 7, 95), (7, 7, 80), (3, 11, 99.5), (500, 1000, 50)):
            ci = stats.binomtest(k, n).proportion_ci(confidence_level=level / 100, method="wilson")
            np.testing.assert_allclose(mc._wilson(k, n, level), (ci.low, ci.high), rtol=1e-12, atol=1e-15)

    def test_graph_choice_does_not_change_tables(self):
        plain = study(WELCH)
        for graph in ("Estimates", "P values"):
            result = study({**WELCH, "Graph": graph})
            self.assertIsNotNone(result.figure)
            for name, table in plain.tables.items():
                if name != "Settings":
                    pd.testing.assert_frame_equal(result.tables[name], table)
        axes = study({**WELCH, "Graph": "P values"}).figure.axes[0]
        self.assertEqual(axes.get_xlim(), (0., 1.))

    def test_worksheet_x_rules(self):
        options = {"Study": mc.OLS, "Replicates": 3, "X source": mc.WORKSHEET, "X column": "X"}
        frame = pd.DataFrame({"X": [1., np.inf, 3, np.nan, 3, 4], "Text": ["1", "two", "3", "", "4", "5"],
                              "Same": [2.] * 6, "Short": [1., np.nan, 2, np.nan, np.nan, np.nan]})
        plan = mc.check_options(frame, options)
        np.testing.assert_array_equal(plan.x, [1., 3, 3, 4])
        self.assertEqual(plan.ignored_x, 2)
        for column in ("Text", "Same", "Short", "Missing"):
            with self.subTest(column=column), self.assertRaises(FieldError) as raised:
                mc.check_options(frame, {**options, "X column": column})
            self.assertEqual(raised.exception.field, "X column")

    def test_unrepresentable_range_is_reported(self):
        with self.assertRaises(FieldError):
            study({**WELCH, "Mean A": 1e100, "SD A": 1e99})
        with self.assertRaises(FieldError):
            study({"Study": mc.OLS, "Replicates": 3, "N": 5, "X minimum": -1e100, "X maximum": 1e100,
                   "Slope": 1e10})

    def test_progress_and_cancellation_between_blocks(self):
        options = {**WELCH, "Replicates": 2000, "N A": 100, "N B": 100}
        seen, cancel = [], threading.Event()

        def progress(done, total):
            seen.append(done)
            self.assertEqual(total, 2000)
            if len(seen) == 2:
                cancel.set()

        with self.assertRaises(mc.MonteCarloCancelled):
            mc.monte_carlo(SOURCE, options, progress=progress, cancel=cancel)
        self.assertEqual(len(seen), 2)
        seen.clear()
        result = mc.monte_carlo(SOURCE, options, progress=lambda done, total: seen.append(done))
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 2000)
        self.assertGreater(len(seen), 2)
        self.assertEqual(len(result.tables["Replicates"]), 2000)
        # A cancelled run leaves no trace on the next one.
        pd.testing.assert_frame_equal(result.tables["Replicates"],
                                      study(options).tables["Replicates"])

    def test_simulate_data_recipes_are_unchanged(self):
        frame = analyse("Simulate data", pd.DataFrame(), {
            "Distribution": "Normal", "N": 5, "Seed": 42, "Mean": 0., "SD": 1., "X minimum": 0., "X maximum": 1.,
            "Intercept": 0., "Slope": 1., "Success probability A": .5, "Success probability B": .5,
        }).tables["Simulated data"]
        np.testing.assert_allclose(frame["Value"], np.random.default_rng(42).normal(0, 1, 5))


if __name__ == "__main__":
    unittest.main()
