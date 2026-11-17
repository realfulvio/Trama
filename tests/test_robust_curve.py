"""Robust curve fit (0.73): engine, options, budgets, pilot scale, tables, catalog and the packaged contract.

The expected numbers are the frozen values of the independent reference oracle in ``tests/data/robust_curve_073``
(``expected/results.json``); this module never recomputes them with the code under test.
"""
import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n, robust_curve
from analisi.field_error import FieldError
from analisi.robust_curve import Ordinary, ROBUST_CURVE
from analisi.robust_curve_dialog import describe_error, field_caption
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "robust_curve_073"
CASES = {case["name"]: case for case in json.loads((DATA / "fixtures" / "cases.json").read_text(encoding="utf-8"))}
EXPECTED = json.loads((DATA / "expected" / "results.json").read_text(encoding="utf-8"))
LINE = CASES["line-Cauchy-1.0"]
TOLERANCE = {"rtol": 3e-5, "atol": 2e-7}


def frame_of(case):
    frame = pd.DataFrame(case["data"])
    if "index" in case:
        frame.index = case["index"]
    return frame


def run(options=None, case=LINE):
    return analyse(ROBUST_CURVE, frame_of(case), {**case["options"], **(options or {})})


class ContractTests(unittest.TestCase):
    """The packaged, unmodified verifier runs against this checkout."""

    @staticmethod
    def load_verifier():
        path = DATA / "verify.py"
        sys.path.insert(0, str(DATA))
        try:
            spec = importlib.util.spec_from_file_location("robust_verify_073", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(DATA))
        return module

    def test_every_oracle_case_passes(self):
        verifier = self.load_verifier()
        reports = verifier.run(str(Path(__file__).resolve().parent.parent))
        failures = [report for report in reports if report["status"] != "PASS"]
        self.assertFalse(failures, failures)
        self.assertEqual(len(reports), 35)


class OracleTests(unittest.TestCase):
    def test_each_case_matches_the_frozen_oracle(self):
        for name, case in CASES.items():
            if name not in EXPECTED:
                continue
            with self.subTest(name):
                result = run(case=case)
                want = EXPECTED[name]
                parameters = result.tables["Robust parameters"]["Estimate"].to_numpy(float)
                np.testing.assert_allclose(parameters, want["parameters"], **TOLERANCE)
                residuals = result.tables["Robust residuals"]
                np.testing.assert_allclose(residuals["Influence weight"], want["weights"], **TOLERANCE)
                np.testing.assert_allclose(residuals["Residual"], want["residuals"], **TOLERANCE)
                np.testing.assert_allclose(residuals["Predicted"], want["predicted"], **TOLERANCE)
                self.assertEqual(residuals["Source row"].tolist(), want["source_rows"])
                self.assertEqual(residuals["Source index"].tolist(), want.get("source_index", residuals["Source index"].tolist()))
                fit = result.tables["Robust fit"].iloc[0]
                np.testing.assert_allclose(fit["Residual scale"], want["scale"], **TOLERANCE)
                np.testing.assert_allclose(fit["Robust objective"], want["objective"], **TOLERANCE)
                self.assertEqual(fit["Scale source"], want["scale_source"])


class TableTests(unittest.TestCase):
    def test_four_tables_in_order_and_the_curve_grid(self):
        result = run()
        self.assertEqual(list(result.tables), ["Robust parameters", "Robust fit", "Robust residuals", "Robust curve"])
        curve = result.tables["Robust curve"]
        self.assertEqual(len(curve), 201)
        self.assertEqual((curve["X"].iloc[0], curve["X"].iloc[-1]), (0, 8))
        self.assertEqual(list(result.tables["Robust residuals"].columns), [
            "Series", "Group", "Source row", "Source index", "X", "Observed", "Predicted", "Residual",
            "Standardized residual", "Influence weight", "Low weight"])

    def test_source_row_is_the_position_and_source_index_keeps_duplicate_labels(self):
        residuals = run().tables["Robust residuals"]
        self.assertEqual(residuals["Source row"].tolist(), list(range(9)))
        self.assertEqual(residuals["Source index"].tolist(), LINE["index"])

    def test_missing_pairs_are_dropped_with_their_lineage(self):
        case = CASES["missing-lineage"]
        residuals = run(case=case).tables["Robust residuals"]
        self.assertEqual(len(residuals), 8)
        self.assertNotIn(2, residuals["Source row"].tolist())
        self.assertNotIn(3, residuals["Source row"].tolist())

    def test_the_worksheet_is_not_modified(self):
        frame = frame_of(LINE)
        before = frame.copy(deep=True)
        analyse(ROBUST_CURVE, frame, copy.deepcopy(LINE["options"]))
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(frame.attrs, {})

    def test_graph_display_changes_only_the_figure(self):
        results = {display: run({"Graph display": display}) for display in ("Curve", "Residuals", "Weights")}
        base = results["Curve"].tables
        for display, result in results.items():
            for name, frame in base.items():
                pd.testing.assert_frame_equal(result.tables[name], frame)
        labels = {display: result.figure.axes[0].get_ylabel() for display, result in results.items()}
        self.assertEqual(labels, {"Curve": "Y", "Residuals": "Residual", "Weights": "Influence weight"})
        self.assertEqual(results["Weights"].figure.axes[0].get_ylim(), (0.0, 1.05))

    def test_the_figure_is_literal_and_names_every_series(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 5], "$a$": [1, 2, 3, 4.2, 5, 6.1], "_b": [2, 1, 4, 3, 6, 5]})
        result = analyse(ROBUST_CURVE, frame, {"X": "X", "Y columns": ["$a$", "_b"], "Model": "Straight line"})
        axes = result.figure.axes[0]
        names = [text.get_text() for text in axes.get_legend().get_texts()]
        self.assertTrue({"$a$", "_b"} <= set(names), names)
        for text in [axes.title, axes.xaxis.label, axes.yaxis.label, *axes.get_legend().get_texts()]:
            self.assertFalse(text.get_parse_math())

    def test_compare_adds_the_ordinary_table(self):
        result = run({"Compare ordinary fit": True})
        table = result.tables["Ordinary comparison"]
        self.assertEqual(list(result.tables)[-1], "Ordinary comparison")
        self.assertEqual(table["Parameter"].tolist(), ["Intercept", "Slope"])
        self.assertTrue((table["Ordinary status"] == "Converged").all())
        # The ordinary slope is pulled toward the outlier; the robust one is not.
        self.assertGreater(table["Ordinary estimate"].iloc[1], table["Robust estimate"].iloc[1] + 0.5)


class GroupTests(unittest.TestCase):
    def test_two_y_columns_and_groups_give_four_independent_fits(self):
        x = list(range(9)) * 2
        y = LINE["data"]["Y"] + [value + 5 for value in LINE["data"]["Y"]]
        frame = pd.DataFrame({"X": x, "Y": y, "Z": [v * 2 for v in y], "G": ["a"] * 9 + ["b"] * 9})
        options = {"X": "X", "Y columns": ["Y", "Z"], "Group": "G", "Model": "Straight line", "Loss": "Cauchy",
                   "Scale method": "Fixed", "Residual scale": 1.0, "Initial parameters": {}}
        result = analyse(ROBUST_CURVE, frame, options)
        fits = result.tables["Robust fit"]
        self.assertEqual(fits["N"].tolist(), [9, 9, 9, 9])
        self.assertEqual(list(zip(fits["Series"], fits["Group"])), [("Y", "a"), ("Y", "b"), ("Z", "a"), ("Z", "b")])
        residuals = result.tables["Robust residuals"]
        self.assertEqual(residuals["Source row"].tolist()[9:18], list(range(9, 18)))
        self.assertEqual(len(result.tables["Robust curve"]), 4 * 201)

    def test_numeric_group_levels_stay_numbers(self):
        frame = pd.DataFrame({"X": list(range(6)) * 2, "Y": [1, 2, 3, 4, 5, 6.2, 2, 3, 4, 5, 6.1, 7], "G": [1] * 6 + [2] * 6})
        result = analyse(ROBUST_CURVE, frame, {"X": "X", "Y columns": ["Y"], "Group": "G", "Model": "Straight line"})
        self.assertEqual(result.tables["Robust fit"]["Group"].tolist(), [1, 2])


class OptionTests(unittest.TestCase):
    def refused(self, patch_options, field, contains):
        with self.assertRaises(FieldError) as raised:
            run(patch_options)
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        self.assertIn(contains, str(raised.exception))

    def test_every_option_names_its_field(self):
        for patch_options, field, contains in (
                ({"X": None}, "X", "Choose a column"),
                ({"X": "Nope"}, "X", "Choose an existing column"),
                ({"Y columns": []}, "Y columns", "at least one"),
                ({"Y columns": ["Y", "Y"]}, "Y columns", "distinct"),
                ({"Y columns": ["X"]}, "Y columns", "different"),
                ({"Group": "Y"}, "Group", "must differ"),
                ({"Model": "Nope"}, "Model", "supported model"),
                ({"Loss": "L2"}, "Loss", "Cauchy, Huber or Soft L1"),
                ({"Scale method": "MAD"}, "Scale method", "Fixed or Pilot MAD"),
                ({"Residual scale": 0}, "Residual scale", "greater than 0"),
                ({"Residual scale": -1}, "Residual scale", "greater than 0"),
                ({"Residual scale": float("inf")}, "Residual scale", "greater than 0"),
                ({"Residual scale": True}, "Residual scale", "greater than 0"),
                ({"Residual scale": "1"}, "Residual scale", "greater than 0"),
                ({"Maximum evaluations": 49}, "Maximum evaluations", "from 50 to 100000"),
                ({"Maximum evaluations": 100_001}, "Maximum evaluations", "from 50 to 100000"),
                ({"Maximum evaluations": True}, "Maximum evaluations", "whole number"),
                ({"Maximum evaluations": 60.5}, "Maximum evaluations", "whole number"),
                ({"Low weight threshold": 0}, "Low weight threshold", "less than 1"),
                ({"Low weight threshold": 1}, "Low weight threshold", "less than 1"),
                ({"Compare ordinary fit": "yes"}, "Compare ordinary fit", "true or false"),
                ({"Graph display": "Map"}, "Graph display", "Curve, Residuals or Weights"),
                ({"Initial parameters": {"Intercept": 1}}, "Initial parameters", "every parameter"),
                ({"Initial parameters": {"Intercept": 1, "Slope": 2, "Extra": 3}}, "Initial parameters", "unknown"),
                ({"Initial parameters": {"Intercept": float("nan"), "Slope": 1}}, "Initial parameters", "finite"),
                ({"Initial parameters": {"Intercept": True, "Slope": 1}}, "Initial parameters", "finite"),
                ({"Initial parameters": [1, 2]}, "Initial parameters", "names and values")):
            with self.subTest(patch_options):
                self.refused(patch_options, field, contains)

    def test_defaults_and_foreign_keys(self):
        options = {"X": "X", "Y columns": ["Y"], "Weighting": "1/Y", "Equation": "A+B*X"}
        result = analyse(ROBUST_CURVE, frame_of(LINE), options)
        fit = result.tables["Robust fit"].iloc[0]
        self.assertEqual((fit["Loss"], fit["Scale source"], fit["Residual scale"]), ("Cauchy", "Fixed", 1.0))

    def test_the_fixed_scale_is_ignored_under_pilot_mad(self):
        a = run({"Scale method": "Pilot MAD", "Residual scale": "garbage"})
        b = run({"Scale method": "Pilot MAD", "Residual scale": 7.0})
        pd.testing.assert_frame_equal(a.tables["Robust fit"], b.tables["Robust fit"])

    def test_the_catalog_excludes_fixed_and_shared_models(self):
        from analisi import stats
        self.assertEqual(robust_curve.MODELS[0], "Straight line")
        for name in robust_curve.MODELS:
            spec = stats.MODELS[name]
            self.assertFalse(spec.required_fixed or spec.required_shared, name)
        self.assertGreater(len(robust_curve.MODELS), 10)

    def test_budgets(self):
        many = pd.DataFrame({"X": np.arange(100_001.0), "Y": np.arange(100_001.0)})
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, many, {"X": "X", "Y columns": ["Y"]})
        self.assertIn("100,000", str(raised.exception))
        wide = pd.DataFrame({"X": np.arange(10.0), **{f"Y{i}": np.arange(10.0) + i for i in range(25)}})
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, wide, {"X": "X", "Y columns": [f"Y{i}" for i in range(25)]})
        self.assertIn("up to 24", str(raised.exception))

    def test_data_errors_cite_the_source_row(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [1, 2, "x", 4, 5]})
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, frame, {"X": "X", "Y columns": ["Y"]})
        self.assertIn("source row 2", str(raised.exception))
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [1, 2, np.inf, 4, 5]})
        with self.assertRaises(FieldError):
            analyse(ROBUST_CURVE, frame, {"X": "X", "Y columns": ["Y"]})
        few = pd.DataFrame({"X": [0.0, 1.0], "Y": [1.0, 2.0]})
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, few, {"X": "X", "Y columns": ["Y"]})
        self.assertEqual(raised.exception.field, "Model")

    def test_the_domain_error_names_x_and_the_source_row(self):
        frame = pd.DataFrame({"X": [0.0, 1, 2, 3, 4, 5], "Y": [10, 6, 4, 3, 2.5, 2.2]})
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, frame, {"X": "X", "Y columns": ["Y"], "Model": "Log-log line"})
        self.assertEqual(raised.exception.field, "X")
        self.assertIn("requires positive X values", str(raised.exception))
        self.assertIn("source row 0", str(raised.exception))

    def test_a_start_outside_the_limits_names_the_initial_parameters(self):
        frame = pd.DataFrame({"X": [0.1, 0.5, 1, 2, 4, 8], "Y": [9.0, 7, 5, 3.5, 2.4, 1.7]})
        options = {"X": "X", "Y columns": ["Y"], "Model": "One-phase decay",
                   "Initial parameters": {"Plateau": 1.0, "Span": 8.0, "Rate": -5.0}}
        with self.assertRaises(FieldError) as raised:
            analyse(ROBUST_CURVE, frame, options)
        self.assertEqual(raised.exception.field, "Initial parameters")
        self.assertEqual(getattr(raised.exception, "parameter", None), "Rate")

    def test_proposed_initial_never_raises(self):
        frame = frame_of(LINE)
        proposal = robust_curve.proposed_initial(frame, {"X": "X", "Y columns": ["Y"], "Model": "Straight line"})
        self.assertEqual(set(proposal), {"Intercept", "Slope"})
        self.assertEqual(robust_curve.proposed_initial(frame, {"X": None, "Y columns": []}), {})

    def test_check_options_runs_no_fit(self):
        with patch.object(robust_curve, "_solve_fit", side_effect=AssertionError("fit")):
            robust_curve.check_options(frame_of(LINE), LINE["options"])


class PilotTests(unittest.TestCase):
    HORIZONTAL = {"X": "X", "Y columns": ["Y"], "Model": "Horizontal line", "Loss": "Cauchy",
                  "Scale method": "Pilot MAD", "Initial parameters": {"Mean": 2.0}}

    def test_mad_scale_uses_the_documented_constant(self):
        fit = run(case=CASES["pilot-mad"]).tables["Robust fit"].iloc[0]
        self.assertEqual(fit["Scale source"], "Pilot MAD")
        self.assertGreater(fit["Residual scale"], 0)

    def test_quantile_fallback_when_the_mad_is_zero(self):
        frame = pd.DataFrame({"X": range(10), "Y": [2.0] * 9 + [9.0]})
        fit = analyse(ROBUST_CURVE, frame, {**self.HORIZONTAL, "Initial parameters": {"Mean": 2.0}}).tables[
            "Robust fit"].iloc[0]
        self.assertEqual(fit["Scale source"], "Absolute residual quantile fallback")
        self.assertGreater(fit["Residual scale"], 0)

    def test_positive_fallback_when_most_pilot_residuals_are_zero(self):
        frame = pd.DataFrame({"X": range(10), "Y": [2.0] * 8 + [3.0, 5.0]})
        crafted = Ordinary(True, np.array([2.0]), 10.0, evaluations=1)
        with patch.object(robust_curve, "_ordinary", return_value=crafted):
            fit = analyse(ROBUST_CURVE, frame, self.HORIZONTAL).tables["Robust fit"].iloc[0]
        self.assertEqual(fit["Scale source"], "Positive residual fallback")
        self.assertEqual(fit["Residual scale"], 2.0)

    def test_exact_pilot(self):
        result = run(case=CASES["exact-pilot"])
        fit = result.tables["Robust fit"].iloc[0]
        self.assertEqual((fit["Status"], fit["Residual scale"], fit["Robust objective"]), ("Exact pilot", 0.0, 0.0))
        self.assertTrue((result.tables["Robust residuals"]["Influence weight"] == 1).all())

    def test_a_failing_pilot_is_an_error_not_an_ordinary_fit(self):
        broken = Ordinary(False, reason="x", code="converge")
        with patch.object(robust_curve, "_ordinary", return_value=broken):
            with self.assertRaises(FieldError) as raised:
                run({"Scale method": "Pilot MAD"})
        self.assertEqual(raised.exception.field, "Maximum evaluations")
        self.assertIn("ordinary pilot fit did not converge", str(raised.exception))

    def test_tiny_and_huge_units_give_the_same_weights(self):
        base = run().tables["Robust residuals"]["Influence weight"].to_numpy(float)
        for name in ("line-units-1e-09", "line-units-1000000000.0"):
            with self.subTest(name):
                case = CASES[name]
                weights = run(case=case).tables["Robust residuals"]["Influence weight"].to_numpy(float)
                self.assertEqual(len(weights), len(base))
                self.assertTrue(np.all(weights >= 0) and np.all(weights <= 1))


class CatalogTests(unittest.TestCase):
    def test_the_method_is_registered_where_it_belongs(self):
        self.assertIn(ROBUST_CURVE, METHODS)
        self.assertIn(ROBUST_CURVE, GROUPS["Regression and Curves"])
        self.assertIn(ROBUST_CURVE, GRAPH_METHODS)
        self.assertEqual(list(METHODS[ROBUST_CURVE]), [
            "X", "Y columns", "Group", "Model", "Loss", "Scale method", "Residual scale", "Initial parameters",
            "Maximum evaluations", "Low weight threshold", "Compare ordinary fit", "Graph display"])

    def test_a_legacy_recipe_is_unchanged(self):
        result = analyse("Nonlinear regression", frame_of(LINE), {
            "X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line",
            "Weighting": "Unweighted"})
        self.assertNotIn("Robust parameters", result.tables)

    def test_production_code_does_not_read_the_package_files(self):
        for path in (Path(robust_curve.__file__), Path(robust_curve.__file__).with_name("robust_curve_dialog.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("reference_oracle", "robust_curve_073", "expected/results", "open("):
                self.assertNotIn(forbidden, text, (path.name, forbidden))


class MessageTests(unittest.TestCase):
    """Every engine message has an exact English catalog entry and an Italian translation."""

    CASES = (
        ({"X": None}, "X"), ({"Y columns": []}, "Y columns"), ({"Y columns": ["Y", "Y"]}, "Y columns"),
        ({"Group": "Y"}, "Group"), ({"Residual scale": 0}, "Residual scale"),
        ({"Maximum evaluations": 49}, "Maximum evaluations"), ({"Low weight threshold": 1}, "Low weight threshold"),
        ({"Initial parameters": {"Intercept": 1}}, "Initial parameters"), ({"Loss": "L2"}, "Loss"),
        ({"Graph display": "Map"}, "Graph display"), ({"Model": "Nope"}, "Model"),
    )

    def setUp(self):
        self.language = i18n.active_language()

    def tearDown(self):
        i18n.set_language(self.language)

    def test_messages_are_translated_and_keep_their_field(self):
        for patch_options, field in self.CASES:
            with self.subTest(field):
                with self.assertRaises(FieldError) as raised:
                    run(patch_options)
                i18n.set_language("en")
                english = describe_error(raised.exception, raised.exception.field)
                i18n.set_language("it")
                italian = describe_error(raised.exception, raised.exception.field)
                self.assertNotEqual(english, italian)
                self.assertNotIn("{", italian)
                self.assertIn(field_caption(field), italian)

    def test_every_error_key_exists_in_both_languages(self):
        keys = [key for key in i18n.CATALOGS["en"] if key.startswith("analysis.robust_curve.")]
        self.assertGreater(len(keys), 60)
        for key in keys:
            self.assertIn(key, i18n.CATALOGS["it"], key)
            placeholders = lambda text: sorted(part.split("}")[0] for part in text.split("{")[1:])
            self.assertEqual(placeholders(i18n.CATALOGS["en"][key]), placeholders(i18n.CATALOGS["it"][key]), key)


if __name__ == "__main__":
    unittest.main()
