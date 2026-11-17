"""Residual diagnostics for multifactor ANOVA.

The frozen balanced and unbalanced fixtures are the package contract. The other cases
cover scaling, degeneracy, recipe compatibility and the single full fit.
"""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from numpy.testing import assert_allclose
from scipy.stats import t as student_t

from analisi import stats as engine
from analisi.anova_diagnostics import (
    ALPHA, ASSUMPTION_SHEET, ASSUMPTIONS, DIAGNOSTICS, GRAPH, GRAPH_HOMO, GRAPH_QQ, GRAPH_RESIDUALS,
    QQ_LINE, QQ_SHEET, SHEET, SPEARMAN, SUMMARY, assumption_table, ensure_graph_budget,
    observation_diagnostics, qq_coordinates, validate,
)
from analisi.field_error import FieldError
from analisi.normality import ANDERSON, DAGOSTINO, LILLIEFORS, SHAPIRO
from analisi.workbench import ANOVA_ALPHA, ANOVA_EFFECTS, ANOVA_MODEL_FIT, METHODS, analyse

DATA = Path(__file__).with_name("data") / "anova_diagnostics"
EXPECTED = json.loads((DATA / "expected.json").read_text())
METHOD = "Multifactor ANOVA"
ON = {DIAGNOSTICS: True, ASSUMPTIONS: True, ALPHA: 0.05, GRAPH: GRAPH_QQ, QQ_LINE: True}


def fixture(name):
    return pd.read_csv(DATA / f"{name}.csv", index_col="Source row")


def run(frame, **extra):
    options = {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 2, **extra}
    return analyse(METHOD, frame, options)


def _full_fits(frame, extra):
    widths = []
    real = np.linalg.lstsq

    def wrapped(a, b, rcond=None):
        widths.append(np.shape(a)[1])
        return real(a, b, rcond=rcond)

    with patch("numpy.linalg.lstsq", wrapped):
        run(frame, **extra)
    full = max(widths)
    return widths.count(full), full


def _spearman_reference(residual, fitted):
    """Average-rank Pearson correlation, independent of the diagnostic implementation."""
    absolute_ranks = pd.Series(np.abs(np.asarray(residual))).rank(method="average")
    fitted_ranks = pd.Series(np.asarray(fitted)).rank(method="average")
    rho = float(absolute_ranks.corr(fitted_ranks))
    df = len(residual) - 2
    statistic = rho * np.sqrt(df / ((1 - rho) * (1 + rho)))
    return np.array([rho, 2 * student_t.sf(abs(statistic), df)])


class ContractTests(unittest.TestCase):
    def test_frozen_dispatcher(self):
        for name, expected in EXPECTED.items():
            with self.subTest(name=name):
                result = run(fixture(name), **ON)
                table = result.tables[SHEET]
                self.assertEqual(table["Source row"].tolist(), expected["source_rows"])
                for column, key in (
                    ("Fitted", "fitted"), ("Residual", "residual"), ("Leverage", "leverage"),
                    ("Internally studentized residual", "student"), ("Cook's distance", "cook"),
                    ("PRESS residual", "press_residual"),
                ):
                    assert_allclose(table[column], expected[key], rtol=2e-9, atol=2e-10)
                anova = result.tables["ANOVA (type III)"]
                summary = result.tables[SUMMARY]
                self.assertEqual(summary.loc["Residual df", "Value"], anova.loc["Residual", "df"])
                self.assertEqual(summary.loc["Residual SS", "Value"], anova.loc["Residual", "SS"])
                coordinates = result.tables[QQ_SHEET]
                # BLAS roundoff can split mathematical ties differently across platforms.
                # Keep the frozen residual values and verify every plotted row's provenance.
                self.assertCountEqual(coordinates["Source row"].tolist(), expected["qq_rows"])
                source_residual = table.set_index("Source row")["Residual"]
                np.testing.assert_array_equal(coordinates["Residual"],
                                              source_residual.loc[coordinates["Source row"]])
                self.assertTrue((np.diff(coordinates["Residual"]) >= 0).all())
                assert_allclose(coordinates["Residual"], np.sort(expected["residual"]), rtol=2e-9, atol=2e-10)
                assert_allclose(coordinates["Theoretical quantile"], expected["qq_theoretical"], rtol=2e-9, atol=2e-10)
                assumptions = result.tables[ASSUMPTION_SHEET]
                self.assertEqual(assumptions["Test"].tolist(), [SPEARMAN, SHAPIRO, DAGOSTINO, ANDERSON, LILLIEFORS])
                spearman = _spearman_reference(table["Residual"], table["Fitted"])
                for row, key in enumerate(("spearman", "shapiro", "dagostino", "anderson", "lilliefors")):
                    scores = spearman if key == "spearman" else expected[key]
                    assert_allclose(assumptions.iloc[row][["Statistic", "p"]].to_numpy(float), scores,
                                    rtol=2e-9, atol=2e-10)
                self.assertIsNotNone(result.figure)
                self.assertEqual(result.figure.axes[0].get_ylabel(), "Residual (raw response units)")

    def test_geometry_and_one_full_fit(self):
        frame = fixture("balanced")
        plain, _ = _full_fits(frame, {})
        diagnosed, _ = _full_fits(frame, ON)
        compared, _ = _full_fits(frame, {**ON, "Compare marginal means by": "A"})
        self.assertEqual(plain, 1)
        self.assertEqual(diagnosed, 1)
        self.assertGreater(compared, 1)
        result = run(frame, **ON)
        rows = result.tables[SHEET]
        summary = result.tables[SUMMARY]
        assert_allclose(rows["Leverage"].sum(), summary.loc["Model rank", "Value"], atol=1e-8)
        assert_allclose(rows["Residual"].sum(), 0, atol=1e-8)
        assert_allclose(np.dot(rows["Residual"], rows["Residual"]), summary.loc["Residual SS", "Value"], rtol=1e-12)

    def test_historical_sheets_stay(self):
        frame = fixture("balanced")
        options = {ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05, "Compare marginal means by": "A"}
        before = run(frame, **options)
        after = run(frame, **options, **{DIAGNOSTICS: False, ASSUMPTIONS: False, GRAPH: "None", ALPHA: "stale"})
        explicit = run(frame, **{DIAGNOSTICS: False, ASSUMPTIONS: False, GRAPH: "None"})
        self.assertEqual(list(before.tables), ["ANOVA (type III)", ANOVA_EFFECTS, ANOVA_MODEL_FIT, "Multiple comparisons"])
        self.assertEqual(list(before.tables), list(after.tables))
        self.assertIsNone(before.figure)
        self.assertIsNone(after.figure)
        self.assertIsNone(explicit.figure)
        self.assertEqual(list(explicit.tables), ["ANOVA (type III)"])
        for name in before.tables:
            pd.testing.assert_frame_equal(before.tables[name], after.tables[name])

    def test_alpha_changes_only_the_decision(self):
        frame = fixture("balanced")
        loose = run(frame, **{**ON, ALPHA: 0.99, GRAPH: "None"})
        strict = run(frame, **{**ON, ALPHA: 1e-12, GRAPH: "None"})
        self.assertNotIn(QQ_SHEET, loose.tables)
        pd.testing.assert_frame_equal(
            loose.tables[ASSUMPTION_SHEET][["Test", "Statistic", "p"]],
            strict.tables[ASSUMPTION_SHEET][["Test", "Statistic", "p"]])
        self.assertIn("Reject", loose.tables[ASSUMPTION_SHEET]["Decision"].tolist())
        self.assertEqual(set(strict.tables[ASSUMPTION_SHEET]["Decision"]), {"Do not reject"})
        self.assertNotIn(SHEET, run(frame, **{ASSUMPTIONS: True, ALPHA: 0.2}).tables)
        self.assertIn(ASSUMPTION_SHEET, run(frame, **{ASSUMPTIONS: True, ALPHA: 0.2}).tables)

    def test_validation(self):
        frame = fixture("balanced")
        for value in (1, 0, -1, np.nan, np.inf, True, "0.5"):
            with self.subTest(alpha=value):
                with self.assertRaises(FieldError) as caught:
                    run(frame, **{ASSUMPTIONS: True, ALPHA: value})
                self.assertEqual(caught.exception.field, ALPHA)
        with self.assertRaises(FieldError) as caught:
            run(frame, **{DIAGNOSTICS: "yes"})
        self.assertEqual(caught.exception.field, DIAGNOSTICS)
        with self.assertRaises(FieldError) as caught:
            run(frame, **{GRAPH: "Scree"})
        self.assertEqual(caught.exception.field, GRAPH)
        with self.assertRaises(FieldError) as caught:
            run(frame, **{DIAGNOSTICS: False, GRAPH: GRAPH_RESIDUALS})
        self.assertEqual(caught.exception.field, GRAPH)
        self.assertIsNone(run(frame, **{DIAGNOSTICS: False, ASSUMPTIONS: False, GRAPH: "None", ALPHA: "stale"}).figure)
        self.assertEqual(METHODS[METHOD][DIAGNOSTICS], False)
        self.assertEqual(METHODS[METHOD][GRAPH][0], "None")
        self.assertEqual(validate({DIAGNOSTICS: True, GRAPH: GRAPH_QQ})[4], True)

    def test_scale_and_shift(self):
        frame = fixture("unbalanced")
        base = run(frame, **{DIAGNOSTICS: True, GRAPH: GRAPH_RESIDUALS}).tables[SHEET]
        for factor in (1e-8, 1e8):
            scaled = frame.copy()
            scaled["Y"] = scaled["Y"] * factor
            other = run(scaled, **{DIAGNOSTICS: True, GRAPH: GRAPH_RESIDUALS}).tables[SHEET]
            assert_allclose(other["Leverage"], base["Leverage"], rtol=1e-10, atol=1e-12)
            assert_allclose(other["Internally studentized residual"], base["Internally studentized residual"],
                            rtol=1e-8, atol=1e-8)
            assert_allclose(other["Cook's distance"], base["Cook's distance"], rtol=1e-8, atol=1e-8)
            assert_allclose(other["Residual"], base["Residual"] * factor, rtol=1e-8, atol=1e-8)
            assert_allclose(other["PRESS residual"], base["PRESS residual"] * factor, rtol=1e-8, atol=1e-8)
        shifted = frame.copy()
        shifted["Y"] = shifted["Y"] + 1e6
        moved = run(shifted, **{DIAGNOSTICS: True}).tables[SHEET]
        assert_allclose(moved["Residual"], base["Residual"], rtol=1e-8, atol=1e-7)
        assert_allclose(moved["Fitted"], base["Fitted"] + 1e6, rtol=1e-12, atol=1e-6)

    def test_assumptions_remain_defined_for_small_response_scales(self):
        for name in ("balanced", "unbalanced"):
            frame = fixture(name)
            base = run(frame, **ON).tables[SHEET]
            expected = EXPECTED[name]
            scores = np.asarray([expected[key] for key in
                                 ("spearman", "shapiro", "dagostino", "anderson", "lilliefors")])
            scores[0] = _spearman_reference(base["Residual"], base["Fitted"])
            for factor in (1e-30, 1e-100):
                with self.subTest(name=name, factor=factor):
                    # Scaling the same fit preserves ranks, including exact ties.
                    assumptions = assumption_table(base["Residual"] * factor, base["Fitted"] * factor, 0.05)
                    assert_allclose(assumptions[["Statistic", "p"]].to_numpy(float), scores,
                                    rtol=2e-9, atol=2e-10)
                    scaled = frame.copy()
                    scaled["Y"] *= factor
                    result = run(scaled, **ON)
                    assumptions = result.tables[ASSUMPTION_SHEET]
                    self.assertTrue(np.isfinite(assumptions[["Statistic", "p"]].to_numpy(float)).all())
                    # A refit can change roundoff ties in Spearman, while normality is continuous.
                    assert_allclose(assumptions.iloc[1:][["Statistic", "p"]].to_numpy(float), scores[1:],
                                    rtol=2e-9, atol=2e-10)
                    coordinates = result.tables[QQ_SHEET]
                    assert_allclose(coordinates["Residual"] / factor, np.sort(base["Residual"]),
                                    rtol=2e-9, atol=2e-10)
                    self.assertTrue(np.isfinite(result.figure.axes[0].collections[0].get_offsets()).all())

    def test_spearman_constant_fit_is_undefined_at_every_scale(self):
        residual = np.array([1., -3., 2., -7., 4., -6., 5., -8.])
        for value in (0.0, 2.0, 2e-30, 2e-100):
            with self.subTest(value=value):
                row = assumption_table(residual, np.full(len(residual), value), 0.05).iloc[0]
                self.assertEqual(row["Decision"], "NA")
                self.assertTrue(np.isnan(row["Statistic"]))
                self.assertTrue(np.isnan(row["p"]))
                self.assertIn("constant", row["Reason"])

    def test_factor_counts(self):
        rows = []
        for a, b, c, k in (
            ("a", "c", "e", 0), ("a", "c", "f", 1), ("a", "d", "e", 2), ("a", "d", "f", 3),
            ("b", "c", "e", 4), ("b", "c", "f", 5), ("b", "d", "e", 6), ("b", "d", "f", 7),
        ):
            for repeat in range(3):
                rows.append((a, b, c, 10 + k + 0.1 * repeat))
        frame = pd.DataFrame(rows, columns=["A", "B", "C", "Y"], index=range(100, 100 + len(rows) * 3, 3))
        for factors, order in ((["A"], 1), (["A", "B"], 1), (["A", "B"], 2), (["A", "B", "C"], 1),
                               (["A", "B", "C"], 2), (["A", "B", "C"], 3)):
            with self.subTest(factors=factors, order=order):
                result = analyse(METHOD, frame, {"Response": "Y", "Factors": factors, "Interaction order": order,
                                                 **ON, GRAPH: GRAPH_HOMO})
                rows = result.tables[SHEET]
                self.assertEqual(result.tables[SUMMARY].loc["N", "Value"], len(rows))
                assert_allclose(rows["Leverage"].sum(), result.tables[SUMMARY].loc["Model rank", "Value"], atol=1e-8)
                self.assertIn("raw response units", result.figure.axes[0].get_ylabel())
                self.assertEqual(len(result.figure.axes[0].lines), 0)

    def test_holes_and_domains(self):
        frame = pd.DataFrame({
            "A": ["a", "a", "b", "b", "b", "a", "a", "b"],
            "B": ["x", "x", "y", None, "y", "y", "x", "x"],
            "Y": [1.0, np.nan, 4.0, 9.0, 6.0, 3.0, 2.0, 5.0],
        }, index=[4, 9, 2, 30, 11, 15, 18, 7])
        result = run(frame, **{DIAGNOSTICS: True, ASSUMPTIONS: True, ALPHA: 0.05, "Interaction order": 1})
        self.assertEqual(result.tables[SHEET]["Source row"].tolist(), [4, 2, 11, 15, 18, 7])
        small = pd.DataFrame({"A": ["a", "a", "b", "b"], "B": ["x", "y", "x", "y"], "Y": [1.0, 2.0, 5.0, 7.0]})
        assumptions = run(small, **{ASSUMPTIONS: True, ALPHA: 0.05, "Interaction order": 1}).tables[ASSUMPTION_SHEET]
        by_test = assumptions.set_index("Test")
        self.assertTrue(np.isfinite(by_test.loc[SHAPIRO, "p"]))
        for test in (DAGOSTINO, ANDERSON, LILLIEFORS):
            self.assertEqual(by_test.loc[test, "Decision"], "NA")
            self.assertIn("at least", by_test.loc[test, "Reason"])
        flat = pd.DataFrame({"A": ["a", "a", "a", "a", "b", "b", "b", "b"], "Y": [1, 2, 3, 4, 1, 2, 3, 4]})
        spearman = analyse(METHOD, flat, {"Response": "Y", "Factors": ["A"], "Interaction order": 1,
                                           ASSUMPTIONS: True, ALPHA: 0.05}).tables[ASSUMPTION_SHEET]
        row = spearman.iloc[0]
        self.assertEqual(row["Test"], SPEARMAN)
        self.assertEqual(row["Decision"], "NA")
        self.assertIn("constant", row["Reason"])

    def test_qq_ties_and_line(self):
        coordinates = qq_coordinates([10, 2, 30], np.array([1.0, 1.0, 0.0]))
        self.assertEqual(coordinates["Source row"].tolist(), [30, 10, 2])
        assert_allclose(coordinates["Plotting position"], (np.arange(1, 4) - 0.375) / 3.25)
        frame = fixture("balanced")
        drawn = run(frame, **{DIAGNOSTICS: True, GRAPH: GRAPH_QQ, QQ_LINE: True}).figure
        plain = run(frame, **{DIAGNOSTICS: True, GRAPH: GRAPH_QQ, QQ_LINE: False}).figure
        self.assertEqual(len(drawn.axes[0].lines), 1)
        self.assertEqual(len(plain.axes[0].lines), 0)
        self.assertIn("N−1", drawn.axes[0].lines[0].get_label())
        legend = [text.get_text() for text in drawn.axes[0].get_legend().get_texts()]
        self.assertTrue(any("N−1" in label for label in legend))

    def test_graph_budget_precedes_the_fit(self):
        frame = pd.DataFrame({
            "A": np.where(np.arange(60_001) % 2, "a", "b"),
            "B": np.where(np.arange(60_001) % 3, "c", "d"),
            "Y": np.arange(60_001, dtype=float),
        })
        calls = []
        real = np.linalg.lstsq

        def wrapped(a, b, rcond=None):
            calls.append(np.shape(a))
            return real(a, b, rcond=rcond)

        with patch("numpy.linalg.lstsq", wrapped):
            with self.assertRaises(FieldError) as caught:
                run(frame, **{DIAGNOSTICS: True, GRAPH: GRAPH_RESIDUALS})
        self.assertEqual(caught.exception.field, GRAPH)
        self.assertEqual(calls, [])
        with self.assertRaises(FieldError):
            ensure_graph_budget(60_001, GRAPH_QQ)

    def test_direct_helper_degeneracy(self):
        design = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.], [0., 0., 1.]])
        observed = np.array([1., 2., 3., 4.])
        beta = np.linalg.lstsq(design, observed, rcond=None)[0]
        rows, summary = observation_diagnostics([8, 1, 3, 4], observed, design, beta)
        self.assertTrue(np.isnan(rows.loc[0, "Internally studentized residual"]))
        self.assertTrue(np.isnan(rows.loc[0, "Cook's distance"]))
        self.assertTrue(np.isnan(rows.loc[0, "PRESS residual"]))
        self.assertTrue(np.isfinite(rows.loc[2, "PRESS residual"]))
        self.assertFalse(np.isinf(rows.select_dtypes(include=float).to_numpy()).any())
        self.assertIn("Leverage is one", summary["Note"].iloc[0])
        exact = np.array([[1., 0.], [1., 0.], [0., 1.], [0., 1.]])
        coefficients = np.array([5., 7.])
        rows, summary = observation_diagnostics([1, 2, 3, 4], exact @ coefficients, exact, coefficients, sse=0.0, df=2)
        self.assertTrue(np.isnan(rows["Internally studentized residual"]).all())
        self.assertTrue(np.isnan(rows["Cook's distance"]).all())
        assert_allclose(rows["PRESS residual"], 0)
        self.assertIn("residual variance is zero", summary["Note"].iloc[0])
        singular = np.column_stack([np.ones(4), np.ones(4)])
        response = np.arange(1., 5.)
        solution = np.linalg.lstsq(singular, response, rcond=None)[0]
        rows, summary = observation_diagnostics(range(4), response, singular, solution)
        self.assertTrue(np.isfinite(rows["Fitted"]).all())
        self.assertEqual(summary.loc["Model rank", "Value"], 1)
        self.assertIn("Model rank", summary["Note"].iloc[0])
        self.assertFalse(np.isinf(rows.to_numpy(dtype=float, na_value=0)).any())

    def test_public_fit_is_unchanged(self):
        frame = fixture("balanced")
        table, fit = engine.factorial_anova_fit(frame, "Y", ["A", "B"], 2)
        components = engine._factorial_anova_components(frame, "Y", ["A", "B"], 2)
        pd.testing.assert_frame_equal(table, components[0])
        self.assertEqual(fit, components[1])
        self.assertEqual(engine.factorial_anova(frame, "Y", ["A", "B"], 2).loc["Residual", "SS"], fit["SSE"])

    def test_caveat_and_constant_decision_wording(self):
        residual = np.array([1., -1., 0.5, -0.5, 0.2, -0.2, 0.1, -0.1])
        fitted = np.linspace(0, 1, 8)
        table = assumption_table(residual, fitted, 0.05)
        defined = table[table["Decision"] != "NA"]
        self.assertFalse(defined.empty)
        self.assertTrue(defined["Reason"].str.contains("projection matrix").all())
        self.assertNotIn("Reject normality", " ".join(table["Decision"]))

    def test_italian_diagnostic_errors_name_the_translated_field(self):
        from analisi.anova_diagnostics import format_anova_error
        from analisi.i18n import active_language, set_language

        previous = active_language()
        try:
            set_language("en")
            english = format_anova_error(FieldError(ALPHA, "Alpha must be a number between 0 and 1."))
            self.assertEqual(english, "ANOVA diagnostic alpha: Alpha must be a number between 0 and 1.")
            self.assertIsNone(format_anova_error(FieldError("Alpha", "Alpha must be a number between 0 and 1.")))
            set_language("it")
            italian = format_anova_error(FieldError(
                GRAPH, "Turn on ANOVA residual diagnostics before choosing a diagnostic graph."))
            self.assertTrue(italian.startswith("Grafico diagnostico ANOVA: "))
            self.assertIn("prima di scegliere", italian)
            budget = format_anova_error(FieldError(GRAPH, "A diagnostic graph accepts at most 60,000 points."))
            self.assertIn("60,000", budget)
            self.assertIn("Scegli sì o no.", format_anova_error(FieldError(DIAGNOSTICS, "Choose yes or no.")))
        finally:
            set_language(previous)
