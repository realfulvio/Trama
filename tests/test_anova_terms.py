"""Multifactor ANOVA with a choice of terms (0.83): engine, errors, comparisons and diagnostics.

Synthetic data only. The expected values come from explicit sum-to-zero contrast matrices solved
with QR in this file, independent of the engine, and from the Patsy fit of the Full hierarchy.
"""
from itertools import combinations, product
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import i18n
from analisi.advanced import anova_comparisons
from analisi.anova_terms import (CELLS_FIELD, COMPARE_FIELD, CONTROL_FIELD, FULL, MODEL_TERMS, SELECTED, TERM_SELECTION,
                                 TermDesign, WITHIN_FIELD, active_factors, canonical_terms, format_error, full_terms,
                                 prerequisites, summary)
from analisi.field_error import FieldError
from analisi import stats as engine
from analisi.workbench import analyse

FACTORS = ["A dose", "B group", "C lot"]


def synthetic(unbalanced=False):
    rng = np.random.default_rng(83)
    rows = []
    for a, b, c in product(("A0", "A1"), ("B0", "B1"), ("C0", "C1", "C2")):
        for _ in range(3):
            mean = 10 + 4 * (a == "A1") + 3 * (b == "B1") + 2 * ("C0", "C1", "C2").index(c) + 2 * (a == "A1") * (b == "B1")
            rows.append((mean + rng.normal(0, 1.2), a, b, c))
    frame = pd.DataFrame(rows, columns=["Response", *FACTORS])
    if unbalanced:
        frame = frame.drop(index=[0, 5, 11, 19, 20, 33]).reset_index(drop=True)
        extra = pd.DataFrame({"Response": [25.0, np.nan, 34.0], "A dose": ["A0", "A1", "A1"],
                              "B group": [None, "B1", "B0"], "C lot": ["C1", "C2", None]})
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame


def oracle(frame, terms):
    """N, residual df, SSE and per-term (SS, df, F, p) from explicit contrast blocks and QR."""
    names = list(dict.fromkeys(name for term in terms for name in term))
    data = frame[["Response", *names]].dropna()
    y = data["Response"].to_numpy(float)
    contrast = {}
    for name in names:
        membership = np.asarray(pd.get_dummies(data[name]).to_numpy(), dtype=float)
        contrast[name] = membership[:, :-1] - membership[:, -1:]
    blocks = [np.ones((len(y), 1))]
    for term in terms:
        block = np.ones((len(y), 1))
        for name in term:
            block = (block[:, :, None] * contrast[name][:, None, :]).reshape(len(y), -1)
        blocks.append(block)
    full = np.column_stack(blocks)

    def sse(design):
        q, _ = np.linalg.qr(design)
        left = y - q @ (q.T @ y)
        return float(left @ left)

    error, df = sse(full), len(y) - full.shape[1]
    effects = {}
    for index, term in enumerate(terms, 1):
        ss = sse(np.column_stack([block for j, block in enumerate(blocks) if j != index])) - error
        width = blocks[index].shape[1]
        statistic = ss / width / (error / df)
        effects[":".join(term)] = (ss, width, statistic, stats.f.sf(statistic, width, df))
    return len(y), df, error, effects, full, y


def options(terms, **extra):
    values = {"Response": "Response", "Factors": FACTORS, "Interaction order": 3, TERM_SELECTION: SELECTED,
              MODEL_TERMS: [list(term) for term in terms], "Effect sizes": True, "Alpha": .05}
    values.update(extra)
    return values


MAIN = [("A dose",), ("B group",), ("C lot",)]
FOUR = [*MAIN, ("A dose", "B group")]


class SelectedTermFit(unittest.TestCase):
    def check_against_oracle(self, frame, terms):
        n, df, error, effects, *_ = oracle(frame, terms)
        result = analyse("Multifactor ANOVA", frame, options(terms))
        table = result.tables["ANOVA (type III)"]
        self.assertEqual(set(table.index), {*effects, "Residual"})
        for name, (ss, width, statistic, p) in effects.items():
            np.testing.assert_allclose(table.loc[name, ["SS", "df", "F", "p"]].to_numpy(float),
                                       [ss, width, statistic, p], rtol=1e-8, atol=1e-10)
        fit = result.tables["Model fit"]["Value"]
        np.testing.assert_allclose([fit["N"], fit["Residual df"], fit["Residual SS"]], [n, df, error], rtol=1e-8)
        self.assertEqual(table.loc["Residual", "df"], df)
        return result

    def test_balanced_and_unbalanced_selections_match_the_contrast_oracle(self):
        for unbalanced in (False, True):
            frame = synthetic(unbalanced)
            for terms in (FOUR, [("A dose",), ("C lot",)], [("B group",)], MAIN,
                          [*MAIN, ("A dose", "B group"), ("A dose", "C lot"), ("B group", "C lot")],
                          [*MAIN, *combinations(FACTORS, 2), tuple(FACTORS)],
                          [("A dose",), ("B group",), ("A dose", "B group")]):
                with self.subTest(unbalanced=unbalanced, terms=terms):
                    self.check_against_oracle(frame, [tuple(term) for term in terms])

    def test_row_selection_uses_only_the_factors_of_the_model(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        n_full = oracle(frame, FOUR)[0]
        n_reduced = oracle(frame, reduced)[0]
        # The row with B missing comes back; the rows without Y or without C stay out.
        self.assertEqual(n_reduced, n_full + 1)
        result = analyse("Multifactor ANOVA", frame, options(reduced, **{"ANOVA residual diagnostics": True}))
        rows = result.tables["ANOVA residual diagnostics"]["Source row"].tolist()
        missing_b = int(frame.index[frame["B group"].isna() & frame["Response"].notna() & frame["C lot"].notna()][0])
        self.assertIn(missing_b, rows)
        self.assertEqual(len(rows), n_reduced)

    def test_full_hierarchy_matches_the_patsy_fit_for_every_order(self):
        for unbalanced in (False, True):
            frame = synthetic(unbalanced)
            frame["C lot"] = frame["C lot"].map({"C0": 1, "C1": 2, "C2": 10})
            for order in (1, 2, 3):
                with self.subTest(unbalanced=unbalanced, order=order):
                    legacy, legacy_fit = engine.factorial_anova_fit(frame, "Response", FACTORS, order)
                    chosen, chosen_fit = engine.factorial_anova_fit(
                        frame, "Response", FACTORS, order, terms=full_terms(FACTORS, order))
                    self.assertEqual(list(legacy.index), list(chosen.index))
                    pd.testing.assert_frame_equal(legacy, chosen, rtol=1e-9, atol=1e-9)
                    for key in ("N", "df"):
                        self.assertEqual(legacy_fit[key], chosen_fit[key])
                    for key in ("SST", "SSE"):
                        self.assertAlmostEqual(legacy_fit[key], chosen_fit[key], places=8)

    def test_a_recipe_without_the_new_keys_is_the_full_hierarchy(self):
        frame = synthetic(True)
        base = {"Response": "Response", "Factors": FACTORS, "Interaction order": 2, "Effect sizes": True, "Alpha": .05}
        before = analyse("Multifactor ANOVA", frame, base)
        explicit = analyse("Multifactor ANOVA", frame, {**base, TERM_SELECTION: FULL, MODEL_TERMS: [["A dose"]]})
        self.assertEqual(list(before.tables), list(explicit.tables))
        self.assertNotIn("Model terms", before.tables)
        for name in before.tables:
            pd.testing.assert_frame_equal(before.tables[name], explicit.tables[name], check_exact=True)

    def test_interaction_order_does_not_matter_for_selected_terms(self):
        frame = synthetic()
        results = []
        for extra in ({"Interaction order": 1}, {"Interaction order": 3}, {"Interaction order": 99}):
            results.append(analyse("Multifactor ANOVA", frame, options(FOUR, **extra)).tables["ANOVA (type III)"])
        without = {key: value for key, value in options(FOUR).items() if key != "Interaction order"}
        results.append(analyse("Multifactor ANOVA", frame, without).tables["ANOVA (type III)"])
        for other in results[1:]:
            pd.testing.assert_frame_equal(results[0], other, check_exact=True)

    def test_model_terms_sheet_lists_each_term_with_its_order_and_df(self):
        frame = synthetic()
        result = analyse("Multifactor ANOVA", frame, options(FOUR))
        self.assertEqual(list(result.tables)[:2], ["ANOVA (type III)", "Model terms"])
        sheet = result.tables["Model terms"]
        self.assertEqual(list(sheet.index), ["A dose", "B group", "C lot", "A dose:B group"])
        self.assertEqual(sheet["Order"].tolist(), [1, 1, 1, 2])
        self.assertEqual(sheet["df"].tolist(), [1, 1, 2, 1])
        self.assertEqual(sheet["Effect"].tolist(), ["Main effect"] * 3 + ["Two-way interaction"])
        three = analyse("Multifactor ANOVA", frame, options([*MAIN, *combinations(FACTORS, 2), tuple(FACTORS)]))
        self.assertEqual(three.tables["Model terms"].loc["A dose:B group:C lot", ["Order", "df"]].tolist(), [3, 2])

    def test_effect_sizes_follow_the_selected_fit(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        result = analyse("Multifactor ANOVA", frame, options(reduced))
        effects = result.tables["Effect sizes"]
        self.assertEqual(list(effects.index), ["A dose", "C lot"])
        n, df, error, found, *_ = oracle(frame, reduced)
        total = float(((frame.dropna(subset=["Response", "A dose", "C lot"])["Response"]
                        - frame.dropna(subset=["Response", "A dose", "C lot"])["Response"].mean()) ** 2).sum())
        np.testing.assert_allclose(effects.loc["A dose", "Eta squared"], found["A dose"][0] / total, rtol=1e-9)
        fit = result.tables["Model fit"]["Value"]
        np.testing.assert_allclose(fit["R²"], 1 - error / total, rtol=1e-9)


class SelectionRules(unittest.TestCase):
    def rejected(self, raw, field=MODEL_TERMS, factors=None):
        with self.assertRaises(FieldError) as caught:
            canonical_terms(raw, FACTORS if factors is None else factors)
        self.assertEqual(caught.exception.field, field)
        return str(caught.exception)

    def test_names_are_literal_and_follow_the_order_of_factors(self):
        terms = canonical_terms([["C lot"], ["B group"], ["A dose"], ["C lot", "A dose"], ["B group", "A dose"]], FACTORS)
        self.assertEqual(terms, (("A dose",), ("B group",), ("C lot",), ("A dose", "B group"), ("A dose", "C lot")))
        literal = ["A (x) + 1", "B:c", "C*D"]
        self.assertEqual(canonical_terms([[name] for name in literal], literal),
                         tuple((name,) for name in literal))

    def test_strong_hierarchy_names_what_is_missing(self):
        message = self.rejected([["A dose", "B group"]])
        self.assertIn("A dose:B group", message)
        self.assertIn("A dose, B group", message)
        message = self.rejected([*[[name] for name in FACTORS], ["A dose", "B group", "C lot"]])
        for needed in ("A dose:B group", "A dose:C lot", "B group:C lot"):
            self.assertIn(needed, message)
        self.assertEqual(prerequisites([("A dose", "B group")], FACTORS), [("A dose",), ("B group",)])
        self.assertEqual(prerequisites(FOUR, FACTORS), [])

    def test_list_errors(self):
        self.assertIn("more than once", self.rejected([["A dose"], ["A dose"]]))
        self.assertIn("more than once", self.rejected([["A dose"], ["B group"], ["A dose", "B group"], ["B group", "A dose"]]))
        self.assertIn("repeats", self.rejected([["A dose", "A dose"]]))
        self.assertIn("not among", self.rejected([["A dose"], ["D other"]]))
        self.assertIn("order 3", self.rejected([[name] for name in ("a", "b", "c", "d")] + [["a", "b", "c", "d"]],
                                               factors=["a", "b", "c", "d"]))
        self.assertIn("at least one model term", self.rejected([]))
        self.assertIn("at least one factor", self.rejected([[]]))
        for bad in (None, "A dose", 3, {"A dose": 1}, [["A dose", 3]], ["A dose"], [None]):
            self.assertIn("list of terms", self.rejected(bad), bad)

    def test_factor_count_and_choice(self):
        self.assertEqual(self.rejected([["x"]], field="Factors", factors=[]).split()[0], "Select")
        nine = [f"F{i}" for i in range(9)]
        self.rejected([["F0"]], field="Factors", factors=nine)
        self.rejected([["F0"]], field="Factors", factors=["F0", "F0"])
        for mode in ("Selected", "full hierarchy", 7):
            with self.assertRaises(FieldError) as caught:
                analyse("Multifactor ANOVA", synthetic(), options(FOUR, **{TERM_SELECTION: mode}))
            self.assertEqual(caught.exception.field, TERM_SELECTION)
        eight = [f"F{i}" for i in range(8)]
        self.assertEqual(len(canonical_terms([[name] for name in eight], eight)), 8)

    def test_helpers(self):
        self.assertEqual(active_factors(FACTORS, canonical_terms([["C lot"], ["A dose"]], FACTORS)), ["A dose", "C lot"])
        self.assertEqual(full_terms(["a", "b", "c"], 2), (("a",), ("b",), ("c",), ("a", "b"), ("a", "c"), ("b", "c")))
        self.assertEqual(summary("Y", [("a",), ("a", "b")]), "Y = a + a:b")

    def test_a_term_design_refuses_an_unknown_level(self):
        design = TermDesign(["factor0"], {"factor0": ["x", "y"]}, [("factor0",)], {"factor0": np.array(["x", "y", "x"])})
        self.assertEqual(design.to_numpy().tolist(), [[1., 1.], [1., -1.], [1., 1.]])
        with self.assertRaises(ValueError):
            design.rows(pd.DataFrame({"factor0": ["z"]}))


class ModelErrors(unittest.TestCase):
    def test_a_model_with_an_empty_cell_is_not_identifiable_on_model_terms(self):
        frame = synthetic()
        frame = frame[~((frame["A dose"] == "A1") & (frame["B group"] == "B1"))]
        with self.assertRaises(FieldError) as caught:
            analyse("Multifactor ANOVA", frame, options([("A dose",), ("B group",), ("A dose", "B group")]))
        self.assertEqual(caught.exception.field, MODEL_TERMS)
        self.assertIn("cannot be identified", str(caught.exception))
        # The additive model of the same data is estimable. The Full hierarchy keeps its historical message.
        analyse("Multifactor ANOVA", frame, options([("A dose",), ("B group",)]))
        with self.assertRaises(ValueError) as old:
            analyse("Multifactor ANOVA", frame, {"Response": "Response", "Factors": ["A dose", "B group"],
                                                 "Interaction order": 2})
        self.assertNotIsInstance(old.exception, FieldError)
        self.assertIn("rank deficient", str(old.exception))

    def test_levels_rows_and_size(self):
        frame = synthetic()
        one_level = frame[frame["A dose"] == "A0"]
        with self.assertRaises(FieldError) as caught:
            analyse("Multifactor ANOVA", one_level, options([("A dose",), ("C lot",)]))
        self.assertEqual(caught.exception.field, MODEL_TERMS)
        self.assertIn("A dose", str(caught.exception))
        few = frame.iloc[::6]
        with self.assertRaises(FieldError) as caught:
            analyse("Multifactor ANOVA", few, options(FOUR))
        self.assertEqual(caught.exception.field, MODEL_TERMS)
        self.assertIn("too large", str(caught.exception))
        flat = frame.assign(Response=3.0)
        with self.assertRaises(FieldError) as caught:
            analyse("Multifactor ANOVA", flat, options(FOUR))
        self.assertIn("no measurable residual variance", str(caught.exception))

    def test_a_row_with_a_missing_factor_of_the_model_stays_out(self):
        frame = synthetic()
        frame.loc[0, "C lot"] = None
        used = analyse("Multifactor ANOVA", frame, options([("A dose",), ("B group",)])).tables["Model fit"]["Value"]["N"]
        both = analyse("Multifactor ANOVA", frame, options([("A dose",), ("B group",), ("C lot",)])).tables["Model fit"]["Value"]["N"]
        self.assertEqual((used, both), (36, 35))


class ComparisonsOnTheSelectedModel(unittest.TestCase):
    def estimated_means(self, frame, terms, compare):
        n, df, error, effects, design, y = oracle(frame, terms)
        names = list(dict.fromkeys(name for term in terms for name in term))
        data = frame[["Response", *names]].dropna()
        levels = {name: sorted(data[name].unique()) for name in names}
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        covariance = np.linalg.inv(design.T @ design) * error / df
        grid = pd.DataFrame(list(product(*(levels[name] for name in names))), columns=names)

        def block(name):
            codes = pd.Categorical(grid[name], categories=levels[name]).codes
            onehot = np.eye(len(levels[name]))[codes]
            return onehot[:, :-1] - onehot[:, -1:]

        blocks = [np.ones((len(grid), 1))]
        for term in terms:
            part = np.ones((len(grid), 1))
            for name in term:
                part = (part[:, :, None] * block(name)[:, None, :]).reshape(len(grid), -1)
            blocks.append(part)
        rows = np.column_stack(blocks)
        means = {level: rows[(grid[compare] == level).to_numpy()].mean(axis=0) for level in levels[compare]}
        return means, beta, covariance, df

    def test_marginal_means_use_the_design_of_the_selected_model(self):
        for unbalanced in (False, True):
            frame = synthetic(unbalanced)
            for terms in ([("A dose",), ("C lot",)], FOUR, [("A dose",), ("B group",), ("C lot",)]):
                with self.subTest(unbalanced=unbalanced, terms=terms):
                    means, beta, covariance, df = self.estimated_means(frame, terms, "C lot")
                    result = anova_comparisons(frame, "Response", FACTORS, 3, "C lot", method="none", terms=terms)
                    for (a, b), row in zip(combinations(means, 2), result.itertuples()):
                        difference = means[a] - means[b]
                        estimate = float(difference @ beta)
                        error = float(np.sqrt(difference @ covariance @ difference))
                        self.assertEqual(row.Index, f"{a} − {b}")
                        np.testing.assert_allclose([row.Difference, row.SE, row.df], [estimate, error, df], rtol=1e-8)
                        np.testing.assert_allclose(row.p, 2 * stats.t.sf(abs(estimate / error), df), rtol=1e-8)

    def test_a_term_outside_the_model_does_not_change_the_means(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        direct = anova_comparisons(frame, "Response", FACTORS, 3, "C lot", method="none", terms=reduced)
        again = anova_comparisons(frame, "Response", FACTORS, 3, "C lot", method="none", terms=reduced)
        pd.testing.assert_frame_equal(direct, again, check_exact=True)
        data = frame.dropna(subset=["Response", "A dose", "C lot"])
        alone = anova_comparisons(data[["Response", "A dose", "C lot"]], "Response", ["A dose", "C lot"], 1, "C lot",
                                  method="none")
        pd.testing.assert_frame_equal(direct, alone, rtol=1e-9, atol=1e-9)

    def test_workbench_comparison_on_the_reduced_model(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        result = analyse("Multifactor ANOVA", frame, options(
            reduced, **{COMPARE_FIELD: "C lot", "Correction": "Holm", "Families": "Separate"}))
        direct = anova_comparisons(frame, "Response", FACTORS, 3, "C lot", method="holm", terms=reduced)
        pd.testing.assert_frame_equal(result.tables["Multiple comparisons"], direct, check_exact=True)
        simple = analyse("Multifactor ANOVA", frame, options(
            FOUR, **{COMPARE_FIELD: "A dose", WITHIN_FIELD: ["B group"], "Correction": "Bonferroni"}))
        self.assertTrue(all(name.startswith("B group=") for name in simple.tables["Multiple comparisons"].index))
        cells = analyse("Multifactor ANOVA", frame, options(
            FOUR, **{CELLS_FIELD: ["A dose", "B group"], "Correction": "Bonferroni"}))
        self.assertEqual(len(cells.tables["Multiple comparisons"]), 6)
        balanced = analyse("Multifactor ANOVA", synthetic(), options(
            FOUR, **{CELLS_FIELD: ["A dose", "B group"], "Correction": "Tukey"}))
        self.assertEqual(len(balanced.tables["Multiple comparisons"]), 6)

    def test_marginal_comparisons_helper_follows_the_terms(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        old = engine.marginal_comparisons(frame, "Response", FACTORS, 3, "C lot", terms=reduced)
        new = anova_comparisons(frame, "Response", FACTORS, 3, "C lot", method="holm", terms=reduced)
        np.testing.assert_allclose(old["Difference"], new["Difference"], rtol=1e-9)
        np.testing.assert_allclose(old["SE"], new["SE"], rtol=1e-9)
        with self.assertRaises(ValueError):
            engine.marginal_comparisons(frame, "Response", FACTORS, 3, "B group", terms=reduced)

    def test_a_factor_outside_the_model_names_its_own_control(self):
        frame = synthetic()
        reduced = [("A dose",), ("C lot",)]
        cases = ((COMPARE_FIELD, {COMPARE_FIELD: "B group"}),
                 (CELLS_FIELD, {CELLS_FIELD: ["A dose", "B group"]}),
                 (WITHIN_FIELD, {COMPARE_FIELD: "C lot", WITHIN_FIELD: ["B group"]}),
                 (COMPARE_FIELD, {COMPARE_FIELD: "Not a column"}))
        for field, extra in cases:
            with self.subTest(field=field, extra=extra):
                with self.assertRaises(FieldError) as caught:
                    analyse("Multifactor ANOVA", frame, options(reduced, **extra))
                self.assertEqual(caught.exception.field, field)
                self.assertIn("not in the model terms", str(caught.exception))

    def test_several_missing_factors_are_all_named(self):
        frame = synthetic()
        with self.assertRaises(FieldError) as caught:
            analyse("Multifactor ANOVA", frame, options([("C lot",)], **{CELLS_FIELD: ["A dose", "B group", "C lot"]}))
        self.assertEqual(caught.exception.field, CELLS_FIELD)
        self.assertIn("A dose, B group are not in the model terms", str(caught.exception))
        with self.assertRaises(FieldError) as single:
            analyse("Multifactor ANOVA", frame, options([("C lot",)], **{COMPARE_FIELD: "A dose"}))
        self.assertIn("A dose is not in the model terms", str(single.exception))
        self.assertNotEqual(str(caught.exception), str(single.exception))

    def test_control_level_errors_name_their_control(self):
        frame = synthetic()
        for terms in (FOUR, None):
            extra = {COMPARE_FIELD: "C lot", "Correction": "Dunnett", CONTROL_FIELD: "C9"}
            base = (options(terms, **extra) if terms else
                    {"Response": "Response", "Factors": FACTORS, "Interaction order": 1, **extra})
            with self.assertRaises(FieldError) as caught:
                analyse("Multifactor ANOVA", frame, base)
            self.assertEqual(caught.exception.field, CONTROL_FIELD)
            self.assertIn("does not exist", str(caught.exception))
            base[CONTROL_FIELD] = ""
            with self.assertRaises(FieldError) as caught:
                analyse("Multifactor ANOVA", frame, base)
            self.assertEqual(caught.exception.field, CONTROL_FIELD)
        ok = analyse("Multifactor ANOVA", frame, options(FOUR, **{COMPARE_FIELD: "C lot", "Correction": "Dunnett",
                                                                    CONTROL_FIELD: "C0"}))
        self.assertEqual(len(ok.tables["Multiple comparisons"]), 2)


class DiagnosticsOnTheSelectedModel(unittest.TestCase):
    def test_residual_diagnostics_use_the_selected_design(self):
        frame = synthetic(True)
        reduced = [("A dose",), ("C lot",)]
        extra = {"ANOVA residual diagnostics": True, "ANOVA assumption tests": True, "ANOVA diagnostic graph": "Residuals vs fitted"}
        result = analyse("Multifactor ANOVA", frame, options(reduced, **extra))
        n, df, error, effects, design, y = oracle(frame, reduced)
        sheet = result.tables["ANOVA residual diagnostics"]
        self.assertEqual(len(sheet), n)
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        np.testing.assert_allclose(sheet["Residual"].to_numpy(float), y - design @ beta, atol=1e-9)
        np.testing.assert_allclose(sheet["Fitted"].to_numpy(float), design @ beta, atol=1e-9)
        q, _ = np.linalg.qr(design)
        np.testing.assert_allclose(sheet["Leverage"].to_numpy(float), (q ** 2).sum(axis=1), atol=1e-9)
        self.assertAlmostEqual(float(sheet["Leverage"].sum()), design.shape[1], places=9)
        summary_sheet = result.tables["ANOVA diagnostic summary"]["Value"]
        self.assertEqual(int(summary_sheet["Model rank"]), 4)
        self.assertEqual(int(summary_sheet["Residual df"]), df)
        self.assertAlmostEqual(float(summary_sheet["Residual SS"]), error, places=8)
        self.assertIsNotNone(result.figure)
        self.assertIn("ANOVA assumptions", result.tables)

    def test_the_graph_budget_counts_the_rows_of_the_model(self):
        frame = synthetic(True)
        extra = {"ANOVA residual diagnostics": True, "ANOVA diagnostic graph": "Normal Q–Q"}
        result = analyse("Multifactor ANOVA", frame, options([("A dose",), ("C lot",)], **extra))
        self.assertEqual(len(result.tables["ANOVA Q–Q coordinates"]), oracle(frame, [("A dose",), ("C lot",)])[0])


class Translations(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_error_sentences_are_translated_and_keep_names_literal(self):
        error = FieldError(MODEL_TERMS, "Model term A dose:B group needs B group in the model (strong hierarchy).")
        self.assertEqual(format_error(error), "Model terms: " + str(error))
        i18n.set_language("it")
        shown = format_error(error)
        self.assertTrue(shown.startswith("Termini del modello: "), shown)
        self.assertIn("A dose:B group richiede B group", shown)
        absent = FieldError(COMPARE_FIELD, "A dose, B group are not in the model terms, so they cannot be used here.")
        self.assertIn("A dose, B group non sono nei termini del modello", format_error(absent))
        self.assertIsNone(format_error(FieldError("Alpha", "Alpha must be a number between 0 and 1.")))

    def test_every_sentence_of_the_engine_has_an_italian_version(self):
        from analisi.anova_terms import ERRORS
        for key, text in ERRORS.items():
            english = i18n.CATALOGS["en"]["anova.terms.error." + key]
            italian = i18n.CATALOGS["it"]["anova.terms.error." + key]
            self.assertEqual(english, text, key)
            self.assertNotEqual(english, italian, key)
            self.assertEqual(i18n.placeholders(english), i18n.placeholders(italian), key)
        for key in i18n.CATALOGS["en"]:
            if key.startswith("anova.terms."):
                self.assertEqual(i18n.placeholders(i18n.CATALOGS["en"][key]), i18n.placeholders(i18n.CATALOGS["it"][key]), key)
                self.assertIn(key, i18n.CATALOGS["it"], key)

    def test_captions_and_choices_are_catalogued_for_the_dialog(self):
        for english, italian in (("Term selection", "Selezione dei termini"), ("Model terms", "Termini del modello"),
                                 ("Full hierarchy", "Gerarchia completa"), ("Selected terms", "Termini scelti")):
            i18n.set_language("it")
            self.assertEqual(i18n.ui(english), italian)
            i18n.set_language("en")
            self.assertEqual(i18n.ui(english), english)


if __name__ == "__main__":
    unittest.main()
