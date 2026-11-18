"""Multifactor ANOVA with Type I, Type II and Type III sums of squares: engine, recipes, errors.

Synthetic data only. The expected values come from explicit sum-to-zero contrast blocks and
projections written in this file from the definitions (residual sums of squares of nested
models), independent of the engine's QR coordinates and of statsmodels.
"""
from itertools import combinations, product
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from scipy import stats

from analisi import anova_ss, i18n
from analisi import stats as engine
from analisi.anova_terms import FULL, MODEL_TERMS, SELECTED, TERM_SELECTION, full_terms
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Multifactor ANOVA"
KEY = anova_ss.KEY
SHEET = {"Type I": "ANOVA (type I)", "Type II": "ANOVA (type II)", "Type III": "ANOVA (type III)"}
FACTORS = ["A dose", "B group", "C lot"]


def synthetic(unbalanced=True, seed=92):
    rng = np.random.default_rng(seed)
    rows = []
    for a, b, c in product(("A0", "A1"), ("B0", "B1", "B2"), ("C0", "C1")):
        for _ in range(3):
            mean = 8 + 3 * (a == "A1") + 2 * ("B0", "B1", "B2").index(b) + 4 * (c == "C1") + 2 * (a == "A1") * (b == "B1")
            rows.append((mean + rng.normal(0, 1.1), a, b, c))
    frame = pd.DataFrame(rows, columns=["Response", *FACTORS])
    if unbalanced:
        frame = frame.drop(index=[0, 4, 9, 10, 17, 25, 26, 30]).reset_index(drop=True)
        extra = pd.DataFrame({"Response": [19.0, np.nan, 21.0], "A dose": ["A0", "A1", "A1"],
                              "B group": ["B2", "B1", None], "C lot": ["C1", "C0", "C1"]})
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame


def blocks_of(frame, terms):
    """Complete rows, response, intercept and one explicit sum-coded block per term."""
    names = list(dict.fromkeys(name for term in terms for name in term))
    data = frame[["Response", *names]].dropna()
    y = data["Response"].to_numpy(float)
    contrast = {}
    for name in names:
        membership = np.asarray(pd.get_dummies(data[name]).to_numpy(), dtype=float)
        contrast[name] = membership[:, :-1] - membership[:, -1:]
    blocks = {}
    for term in terms:
        block = np.ones((len(y), 1))
        for name in term:
            block = (block[:, :, None] * contrast[name][:, None, :]).reshape(len(y), -1)
        blocks[tuple(term)] = block
    return y, np.ones((len(y), 1)), blocks


def fit(y, columns):
    design = np.column_stack(columns)
    solution = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ solution
    return float(residual @ residual), int(np.linalg.matrix_rank(design))


def reference(frame, terms, kind):
    """(SS, df) per term from the nested-model definitions. ``terms`` is in model order."""
    terms = [tuple(term) for term in terms]
    y, intercept, blocks = blocks_of(frame, terms)
    out = {}
    for index, term in enumerate(terms):
        if kind == "Type I":
            before = [blocks[other] for other in terms[:index]]
            small = fit(y, [intercept, *before])
            large = fit(y, [intercept, *before, blocks[term]])
        elif kind == "Type II":
            before = [blocks[other] for other in terms if other != term and not set(term) < set(other)]
            small = fit(y, [intercept, *before])
            large = fit(y, [intercept, *before, blocks[term]])
        else:
            others = [blocks[other] for other in terms if other != term]
            small = fit(y, [intercept, *others])
            large = fit(y, [intercept, *blocks.values()])
        out[":".join(term)] = (small[0] - large[0], large[1] - small[1])
    full_rss, full_rank = fit(y, [intercept, *blocks.values()])
    return out, full_rss, len(y) - full_rank, y


def recipe(terms=None, kind=None, order=3, **extra):
    options = {"Response": "Response", "Factors": FACTORS, "Interaction order": order, **extra}
    if kind is not None:
        options[KEY] = kind
    if terms is not None:
        options.update({TERM_SELECTION: SELECTED, MODEL_TERMS: [list(term) for term in terms]})
    return options


MAIN = [("A dose",), ("B group",), ("C lot",)]
PAIRS = list(combinations(FACTORS, 2))
TRIO = [*MAIN, *PAIRS, tuple(FACTORS)]
SELECTIONS = [[("A dose",), ("B group",), ("A dose", "B group")], [*MAIN, ("A dose", "B group")],
              [*MAIN, *PAIRS], TRIO, MAIN, [("B group",), ("C lot",), ("B group", "C lot")]]


class SumsOfSquaresAgainstDefinitions(unittest.TestCase):
    def check(self, frame, terms, kind, factors=FACTORS, **extra):
        expected, error, df, _ = reference(frame, terms, kind)
        run = analyse(METHOD, frame, {**recipe(terms, kind), "Factors": factors, **extra})
        table = run.tables[SHEET[kind]]
        self.assertEqual(list(table.index), [*expected, "Residual"])
        for name, (ss, width) in expected.items():
            statistic = ss / width / (error / df)
            np.testing.assert_allclose(table.loc[name, ["SS", "df", "MS", "F", "p"]].to_numpy(float),
                                       [ss, width, ss / width, statistic, stats.f.sf(statistic, width, df)],
                                       rtol=1e-8, atol=1e-10, err_msg=f"{kind} {name}")
        self.assertEqual(table.loc["Residual", "df"], df)
        np.testing.assert_allclose(table.loc["Residual", "SS"], error, rtol=1e-9)
        return run, table

    def test_selected_terms_match_the_definitions_for_every_type(self):
        for unbalanced in (False, True):
            frame = synthetic(unbalanced)
            for terms in SELECTIONS:
                for kind in anova_ss.CHOICES:
                    with self.subTest(unbalanced=unbalanced, terms=terms, kind=kind):
                        self.check(frame, terms, kind)

    def test_full_hierarchy_matches_the_definitions_for_every_order(self):
        frame = synthetic()
        for order in (1, 2, 3):
            terms = list(full_terms(FACTORS, order))
            for kind in anova_ss.CHOICES:
                with self.subTest(order=order, kind=kind):
                    expected, error, df, _ = reference(frame, terms, kind)
                    run = analyse(METHOD, frame, recipe(None, kind, order))
                    table = run.tables[SHEET[kind]]
                    self.assertEqual(list(table.index), [*expected, "Residual"])
                    for name, (ss, width) in expected.items():
                        np.testing.assert_allclose(table.loc[name, ["SS", "df"]].to_numpy(float), [ss, width],
                                                   rtol=1e-8, atol=1e-10)

    def test_full_hierarchy_and_the_same_selected_terms_agree(self):
        frame = synthetic()
        for kind in anova_ss.CHOICES:
            full = analyse(METHOD, frame, recipe(None, kind, 3)).tables[SHEET[kind]]
            chosen = analyse(METHOD, frame, recipe(TRIO, kind)).tables[SHEET[kind]]
            self.assertEqual(list(full.index), list(chosen.index))
            pd.testing.assert_frame_equal(full, chosen, rtol=1e-9, atol=1e-9)

    def test_the_example_of_the_specification(self):
        # A + B + C + A:B. Type II tests A after B and C (not A:B), and C after A, B and A:B.
        frame = synthetic()
        terms = [*MAIN, ("A dose", "B group")]
        _, table = self.check(frame, terms, "Type II")
        y, intercept, blocks = blocks_of(frame, terms)
        a, b, c, ab = (blocks[term] for term in terms)
        np.testing.assert_allclose(
            table.loc["A dose", "SS"], fit(y, [intercept, b, c])[0] - fit(y, [intercept, b, c, a])[0], rtol=1e-9)
        np.testing.assert_allclose(
            table.loc["C lot", "SS"], fit(y, [intercept, a, b, ab])[0] - fit(y, [intercept, a, b, ab, c])[0], rtol=1e-9)

    def test_type_one_adds_up_to_the_centered_total(self):
        frame = synthetic()
        for terms in SELECTIONS:
            run = analyse(METHOD, frame, recipe(terms, "Type I", **{"Effect sizes": True}))
            table = run.tables[SHEET["Type I"]]
            fit_sheet = run.tables["Model fit"]["Value"]
            total = float(fit_sheet["Total SS (centered)"])
            self.assertAlmostEqual(table.drop(index="Residual")["SS"].sum() + table.loc["Residual", "SS"], total, places=8)
            self.assertAlmostEqual(table["Eta²"].dropna().sum() + table.loc["Residual", "SS"] / total, 1.0, places=10)

    def test_balanced_data_gives_the_same_table_in_all_types(self):
        frame = synthetic(unbalanced=False)
        for terms in SELECTIONS:
            tables = {kind: analyse(METHOD, frame, recipe(terms, kind)).tables[SHEET[kind]] for kind in anova_ss.CHOICES}
            for kind in ("Type I", "Type II"):
                pd.testing.assert_frame_equal(tables[kind], tables["Type III"], rtol=1e-9, atol=1e-9)

    def test_unbalanced_data_separates_the_types(self):
        frame = synthetic()
        tables = {kind: analyse(METHOD, frame, recipe(None, kind, 2)).tables[SHEET[kind]] for kind in anova_ss.CHOICES}
        self.assertFalse(np.isclose(tables["Type I"].loc["B group", "SS"], tables["Type II"].loc["B group", "SS"]))
        # A term of the highest order has no term that contains it, so Type II tests it after all the others.
        for term in ("A dose:B group", "A dose:C lot", "B group:C lot"):
            self.assertAlmostEqual(tables["Type II"].loc[term, "SS"], tables["Type III"].loc[term, "SS"], places=8)
        # The last term of Type I is tested after all the others too; the earlier ones are not.
        self.assertAlmostEqual(tables["Type I"].loc["B group:C lot", "SS"],
                               tables["Type III"].loc["B group:C lot", "SS"], places=8)
        self.assertNotAlmostEqual(tables["Type I"].loc["A dose:B group", "SS"],
                                  tables["Type III"].loc["A dose:B group", "SS"], places=3)


class OrderAndInvariance(unittest.TestCase):
    def test_reordering_factors_changes_type_one_and_leaves_type_two(self):
        frame = synthetic()
        forward = analyse(METHOD, frame, {**recipe(None, "Type I", 2), "Factors": ["A dose", "B group"]})
        reverse = analyse(METHOD, frame, {**recipe(None, "Type I", 2), "Factors": ["B group", "A dose"]})
        first, second = forward.tables[SHEET["Type I"]], reverse.tables[SHEET["Type I"]]
        self.assertEqual(list(first.index), ["A dose", "B group", "A dose:B group", "Residual"])
        self.assertEqual(list(second.index), ["B group", "A dose", "B group:A dose", "Residual"])
        # Same model, so the first factor takes the shared variation in either order.
        self.assertFalse(np.isclose(first.loc["A dose", "SS"], second.loc["A dose", "SS"]))
        self.assertFalse(np.isclose(first.loc["B group", "SS"], second.loc["B group", "SS"]))
        self.assertAlmostEqual(first.loc["A dose:B group", "SS"], second.loc["B group:A dose", "SS"], places=8)
        self.assertAlmostEqual(first["SS"].sum(), second["SS"].sum(), places=8)
        forward = analyse(METHOD, frame, {**recipe(None, "Type II", 2), "Factors": ["A dose", "B group"]})
        reverse = analyse(METHOD, frame, {**recipe(None, "Type II", 2), "Factors": ["B group", "A dose"]})
        first, second = forward.tables[SHEET["Type II"]], reverse.tables[SHEET["Type II"]]
        for a, b in (("A dose", "A dose"), ("B group", "B group"), ("A dose:B group", "B group:A dose")):
            np.testing.assert_allclose(first.loc[a, ["SS", "df", "F", "p"]].to_numpy(float),
                                       second.loc[b, ["SS", "df", "F", "p"]].to_numpy(float), rtol=1e-9)

    def test_the_order_of_a_model_terms_list_does_not_matter(self):
        frame = synthetic()
        one = analyse(METHOD, frame, recipe([("A dose",), ("B group",), ("A dose", "B group")], "Type I"))
        other = analyse(METHOD, frame, recipe([("B group", "A dose"), ("B group",), ("A dose",)], "Type I"))
        pd.testing.assert_frame_equal(one.tables[SHEET["Type I"]], other.tables[SHEET["Type I"]])

    def test_terms_enter_by_size_then_by_factor_position(self):
        frame = synthetic()
        run = analyse(METHOD, frame, {**recipe(TRIO, "Type I"), "Factors": ["C lot", "A dose", "B group"]})
        self.assertEqual(list(run.tables[SHEET["Type I"]].index),
                         ["C lot", "A dose", "B group", "C lot:A dose", "C lot:B group", "A dose:B group",
                          "C lot:A dose:B group", "Residual"])


class SharedFit(unittest.TestCase):
    def test_residual_row_summary_fit_and_posthoc_do_not_depend_on_the_type(self):
        frame = synthetic()
        extra = {"Effect sizes": True, "Alpha": .1, "Compare marginal means by": "A dose"}
        runs = {kind: analyse(METHOD, frame, recipe(None, kind, 2, **extra)) for kind in anova_ss.CHOICES}
        base = runs["Type III"]
        for kind, run in runs.items():
            self.assertEqual(list(run.tables)[0], SHEET[kind])
            pd.testing.assert_frame_equal(run.tables["Model fit"], base.tables["Model fit"])
            pd.testing.assert_frame_equal(run.tables["Multiple comparisons"], base.tables["Multiple comparisons"])
            self.assertEqual(run.tables[SHEET[kind]].loc["Residual"].dropna().to_dict(),
                             base.tables[SHEET["Type III"]].loc["Residual"].dropna().to_dict())
            self.assertEqual(list(run.tables[SHEET[kind]].columns), list(base.tables[SHEET["Type III"]].columns))
            self.assertEqual(run.tables[SHEET[kind]].dtypes.to_dict(), base.tables[SHEET["Type III"]].dtypes.to_dict())

    def test_effect_sizes_use_the_sums_of_squares_of_the_active_type(self):
        frame = synthetic()
        for kind in anova_ss.CHOICES:
            run = analyse(METHOD, frame, recipe(None, kind, 2, **{"Effect sizes": True, "Alpha": .1}))
            table, effects = run.tables[SHEET[kind]], run.tables["Effect sizes"]
            error = table.loc["Residual", "SS"]
            for term in effects.index:
                ss = table.loc[term, "SS"]
                self.assertAlmostEqual(effects.loc[term, "Partial eta squared"], ss / (ss + error))
                self.assertAlmostEqual(effects.loc[term, "Eta squared"], ss / run.tables["Model fit"].loc[
                    "Total SS (centered)", "Value"])
                self.assertEqual(effects.loc[term, "p"], table.loc[term, "p"])

    def test_residual_diagnostics_do_not_depend_on_the_type(self):
        frame = synthetic()
        diag = {"ANOVA residual diagnostics": True}
        base = analyse(METHOD, frame, recipe(None, "Type III", 2, **diag))
        for kind in ("Type I", "Type II"):
            run = analyse(METHOD, frame, recipe(None, kind, 2, **diag))
            for name in run.tables:
                if name != SHEET[kind]:
                    pd.testing.assert_frame_equal(run.tables[name], base.tables[name])

    def test_one_fit_serves_the_table_and_the_diagnostics(self):
        frame = synthetic()
        with mock.patch.object(engine, "_anova_model", wraps=engine._anova_model) as model:
            engine._factorial_anova_components(frame, "Response", FACTORS, 2, sums_of_squares="Type II")
        self.assertEqual(model.call_count, 1)


class LegacyRecipes(unittest.TestCase):
    def test_a_recipe_without_the_key_is_type_three_bit_for_bit(self):
        frame = synthetic()
        legacy = analyse(METHOD, frame, recipe(None, None, 2, **{"Effect sizes": True, "Alpha": .05}))
        explicit = analyse(METHOD, frame, recipe(None, "Type III", 2, **{"Effect sizes": True, "Alpha": .05}))
        self.assertEqual(list(legacy.tables), ["ANOVA (type III)", "Effect sizes", "Model fit"])
        self.assertEqual(list(explicit.tables), list(legacy.tables))
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], explicit.tables[name], check_exact=True)
        direct, fit_ = engine.factorial_anova_fit(frame, "Response", FACTORS, 2)
        pd.testing.assert_frame_equal(direct, legacy.tables["ANOVA (type III)"], check_exact=True)

    def test_empty_values_mean_type_three(self):
        frame = synthetic()
        base = analyse(METHOD, frame, recipe(None, None, 2)).tables["ANOVA (type III)"]
        for value in (None, ""):
            run = analyse(METHOD, frame, {**recipe(None, None, 2), KEY: value})
            pd.testing.assert_frame_equal(run.tables["ANOVA (type III)"], base, check_exact=True)

    def test_public_functions_keep_their_signature_and_default(self):
        frame = synthetic()
        legacy = engine.factorial_anova(frame, "Response", FACTORS, 2)
        pd.testing.assert_frame_equal(legacy, engine.factorial_anova(frame, "Response", FACTORS, 2, sums_of_squares=None))
        typed = engine.factorial_anova(frame, "Response", FACTORS, 2, sums_of_squares="Type I")
        self.assertEqual(list(typed.index), list(legacy.index))
        self.assertFalse(np.allclose(typed["SS"], legacy["SS"]))

    def test_the_option_is_in_the_catalog_after_the_interaction_order(self):
        keys = list(METHODS[METHOD])
        self.assertIn(KEY, keys)
        self.assertLess(keys.index("Interaction order"), keys.index(KEY))
        self.assertLess(keys.index(KEY), keys.index(MODEL_TERMS))
        self.assertEqual(METHODS[METHOD][KEY], ("Type III", "Type I", "Type II"))


class Errors(unittest.TestCase):
    def test_unknown_values_name_the_field(self):
        frame = synthetic()
        for value in ("Type IV", "type i", "III", "Type  I", 1, True, ["Type I"], "Type I "):
            with self.subTest(value=value):
                with self.assertRaises(FieldError) as caught:
                    analyse(METHOD, frame, {**recipe(None, None, 2), KEY: value})
                self.assertEqual(caught.exception.field, KEY)

    def test_the_value_is_checked_before_the_fit(self):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, pd.DataFrame({"Response": [1.0], "A dose": ["x"]}),
                    {"Response": "Response", "Factors": ["A dose"], "Interaction order": 1, KEY: "Type 4"})
        self.assertEqual(caught.exception.field, KEY)

    def test_the_engine_refuses_an_unknown_type(self):
        with self.assertRaises(FieldError) as caught:
            engine.factorial_anova(synthetic(), "Response", FACTORS, 2, sums_of_squares="Type IV")
        self.assertEqual(caught.exception.field, KEY)

    def test_model_errors_do_not_change_with_the_type(self):
        frame = synthetic()
        frame = frame[~((frame["A dose"] == "A1") & (frame["B group"] == "B1"))]
        for kind in anova_ss.CHOICES:
            with self.assertRaisesRegex(ValueError, "rank deficient"):
                analyse(METHOD, frame, recipe(None, kind, 2))
        constant = synthetic().assign(Response=5.0)
        for kind in anova_ss.CHOICES:
            with self.assertRaisesRegex(ValueError, "no measurable residual variance"):
                analyse(METHOD, constant, recipe([("A dose",), ("B group",)], kind, 2))

    def test_a_numerical_inconsistency_is_reported_on_the_field(self):
        frame = synthetic()
        real = anova_ss._coordinates

        def drifting(x, centered, columns):
            coordinates, residual = real(x, centered, columns)
            return coordinates, residual * 0.5

        for kind in ("Type I", "Type II"):
            with mock.patch.object(anova_ss, "_coordinates", drifting):
                with self.assertRaises(FieldError) as caught:
                    analyse(METHOD, frame, recipe(None, kind, 2))
            self.assertEqual(caught.exception.field, KEY)

    def test_dependent_columns_in_a_reduced_model_are_reported_on_the_field(self):
        x = np.column_stack([np.ones(6), np.arange(6.0), np.arange(6.0)])
        with self.assertRaises(FieldError) as caught:
            anova_ss._coordinates(x, np.array([1.0, 3, 2, 5, 4, 6]), [0, 1, 2])
        self.assertEqual(caught.exception.field, KEY)

    def test_translated_sentences(self):
        error = FieldError(KEY, anova_ss.ERRORS["kind"])
        try:
            i18n.set_language("en")
            self.assertEqual(anova_ss.format_error(error),
                             f"Sums of squares: {anova_ss.ERRORS['kind']}")
            i18n.set_language("it")
            self.assertEqual(anova_ss.format_error(error),
                             "Somme dei quadrati: Scegli le somme dei quadrati di Tipo I, Tipo II o Tipo III.")
            self.assertEqual(i18n.ui("Type II"), "Tipo II")
            self.assertEqual(i18n.ui("Type III"), "Tipo III")
            self.assertEqual(i18n.ui(KEY), "Somme dei quadrati")
        finally:
            i18n.set_language("en")
        self.assertIsNone(anova_ss.format_error(FieldError("Alpha", "x")))


class NamesAndNumerics(unittest.TestCase):
    def test_factor_names_with_separators_and_a_shared_prefix(self):
        rng = np.random.default_rng(5)
        names = ["A", "A:B", "A|B c"]
        rows = []
        for levels in product(("x", "y"), ("p", "q", "r"), ("u", "v")):
            for _ in range(2 + len("".join(levels)) % 3):
                rows.append((rng.normal(10, 2) + 2 * (levels[0] == "y") + (levels[1] == "q"), *levels))
        frame = pd.DataFrame(rows, columns=["Y", *names])
        for kind in anova_ss.CHOICES:
            with self.subTest(kind=kind):
                run = analyse(METHOD, frame, {"Response": "Y", "Factors": names, "Interaction order": 1, KEY: kind,
                                              TERM_SELECTION: SELECTED, MODEL_TERMS: [["A"], ["A:B"], ["A|B c"]]})
                table = run.tables[SHEET[kind]]
                # A literal colon in a name is quoted, so no label can be read as an interaction.
                self.assertEqual(list(table.index), ["A", '"A:B"', "A|B c", "Residual"])
                expected = reference(frame.rename(columns={"Y": "Response"}), [("A",), ("A:B",), ("A|B c",)], kind)[0]
                for name, (ss, _) in expected.items():
                    shown = '"A:B"' if name == "A:B" else name
                    self.assertAlmostEqual(table.loc[shown, "SS"], ss, places=7)

    def test_an_offset_response_keeps_the_sums_of_squares(self):
        frame = synthetic()
        shifted = frame.assign(Response=frame["Response"] + 1e6)
        for kind in anova_ss.CHOICES:
            base = analyse(METHOD, frame, recipe(None, kind, 2)).tables[SHEET[kind]]
            moved = analyse(METHOD, shifted, recipe(None, kind, 2)).tables[SHEET[kind]]
            np.testing.assert_allclose(moved["SS"].to_numpy(float), base["SS"].to_numpy(float), rtol=1e-5)

    def test_an_edited_cell_changes_the_table(self):
        frame = synthetic()
        before = analyse(METHOD, frame, recipe(None, "Type II", 2)).tables[SHEET["Type II"]]
        edited = frame.copy()
        edited.loc[3, "Response"] += 7
        after = analyse(METHOD, edited, recipe(None, "Type II", 2)).tables[SHEET["Type II"]]
        self.assertFalse(np.allclose(before["SS"], after["SS"]))
        self.assertEqual(before.loc["Residual", "df"], after.loc["Residual", "df"])


if __name__ == "__main__":
    unittest.main()
