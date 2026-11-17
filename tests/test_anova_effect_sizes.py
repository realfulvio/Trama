import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.formula.api import ols

from analisi import stats as engine
from analisi.processing import FieldError
from analisi.workbench import (ANOVA_ALPHA, ANOVA_EFFECTS, ANOVA_MODEL_FIT, METHODS, analyse, anova_visibility,
                               check_anova_options)

BALANCED = Path(__file__).with_name("data") / "anova-effect-sizes-balanced.csv"
METHOD = "Multifactor ANOVA"
COLUMNS = ["% total variation", "Eta squared", "Partial eta squared", "Cohen f", "p", "Significant"]


def run(frame, factors=("A", "B"), order=2, response="Y", **extra):
    options = {"Response": response, "Factors": list(factors), "Interaction order": order, **extra}
    return analyse(METHOD, frame, options)


def unbalanced():
    rng = np.random.default_rng(47)
    counts = {("a1", "b1"): 3, ("a1", "b2"): 5, ("a2", "b1"): 4, ("a2", "b2"): 7}
    effects = {("a1", "b1"): 10, ("a1", "b2"): 13, ("a2", "b1"): 15, ("a2", "b2"): 14}
    rows = [(a, b, effects[a, b] + rng.normal(0, 1.5)) for (a, b), n in counts.items() for _ in range(n)]
    return pd.DataFrame(rows, columns=["A", "B", "Y"])


class BalancedFixtureTest(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(BALANCED)

    def test_effect_sizes_and_model_fit(self):
        result = run(self.frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05})
        self.assertEqual(list(result.tables), ["ANOVA (type III)", ANOVA_EFFECTS, ANOVA_MODEL_FIT])
        anova = result.tables["ANOVA (type III)"]
        np.testing.assert_allclose(anova.loc[["A", "B", "A:B"], "SS"], [32, 72, 8])
        np.testing.assert_allclose(anova.loc[["A", "B", "A:B"], "F"], [16, 36, 4])
        effects = result.tables[ANOVA_EFFECTS]
        self.assertEqual(list(effects.columns), COLUMNS)
        self.assertEqual(list(effects.index), ["A", "B", "A:B"])
        self.assertEqual(effects.index.name, "Term")
        np.testing.assert_allclose(effects["p"], [0.01613009, 0.00388254, 0.11611652], atol=5e-9)
        np.testing.assert_allclose(effects["Eta squared"], [32 / 120, 72 / 120, 8 / 120])
        np.testing.assert_allclose(effects["% total variation"], [3200 / 120, 7200 / 120, 800 / 120])
        np.testing.assert_allclose(effects["Partial eta squared"], [.8, .9, .5])
        np.testing.assert_allclose(effects["Cohen f"], [2, 3, 1])
        self.assertEqual(effects["Significant"].tolist(), ["Yes", "Yes", "No"])
        for column in COLUMNS[:-1]:
            self.assertTrue(pd.api.types.is_float_dtype(effects[column]), column)
        fit = result.tables[ANOVA_MODEL_FIT]["Value"]
        self.assertEqual((fit["N"], fit["Residual df"]), (8, 4))
        self.assertAlmostEqual(fit["Total SS (centered)"], 120)
        self.assertAlmostEqual(fit["Residual SS"], 8)
        self.assertAlmostEqual(fit["R²"], 14 / 15)
        self.assertAlmostEqual(fit["Adjusted R²"], 53 / 60)

    def test_alpha_changes_only_significant(self):
        loose = run(self.frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05})
        strict = run(self.frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.01})
        self.assertEqual(strict.tables[ANOVA_EFFECTS]["Significant"].tolist(), ["No", "Yes", "No"])
        pd.testing.assert_frame_equal(loose.tables[ANOVA_EFFECTS][COLUMNS[:-1]],
                                      strict.tables[ANOVA_EFFECTS][COLUMNS[:-1]])
        pd.testing.assert_frame_equal(loose.tables[ANOVA_MODEL_FIT], strict.tables[ANOVA_MODEL_FIT])
        pd.testing.assert_frame_equal(loose.tables["ANOVA (type III)"], strict.tables["ANOVA (type III)"])

    def test_p_equal_to_alpha_is_not_significant(self):
        table, fit = engine.factorial_anova_fit(self.frame, "Y", ["A", "B"], 2)
        effects, _ = engine.anova_effect_sizes(table, fit, alpha=float(table.loc["A", "p"]))
        self.assertEqual(effects.loc["A", "Significant"], "No")

    def test_legacy_recipe_keeps_the_previous_report(self):
        result = run(self.frame)
        self.assertEqual(list(result.tables), ["ANOVA (type III)"])
        pd.testing.assert_frame_equal(result.tables["ANOVA (type III)"],
                                      engine.factorial_anova(self.frame, "Y", ["A", "B"], 2))
        # Alpha is ignored while the option is off, so an old invalid value never blocks the analysis.
        self.assertEqual(list(run(self.frame, **{ANOVA_EFFECTS: False, ANOVA_ALPHA: 5.0}).tables),
                         ["ANOVA (type III)"])

    def test_factorial_anova_still_returns_a_dataframe(self):
        table = engine.factorial_anova(self.frame, "Y", ["A", "B"], 2)
        self.assertIsInstance(table, pd.DataFrame)
        self.assertEqual(list(table.index), ["A", "B", "A:B", "Residual"])

    def test_post_hoc_sheet_is_kept(self):
        result = run(self.frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05, "Compare marginal means by": "A",
                                    "Correction": "Holm"})
        self.assertEqual(list(result.tables),
                         ["ANOVA (type III)", ANOVA_EFFECTS, ANOVA_MODEL_FIT, "Multiple comparisons"])
        baseline = run(self.frame, **{"Compare marginal means by": "A", "Correction": "Holm"})
        pd.testing.assert_frame_equal(result.tables["Multiple comparisons"], baseline.tables["Multiple comparisons"])


class OptionsTest(unittest.TestCase):
    def test_catalog_defaults(self):
        self.assertIs(METHODS[METHOD][ANOVA_EFFECTS], False)
        self.assertEqual(METHODS[METHOD][ANOVA_ALPHA], 0.05)
        self.assertEqual(anova_visibility(False), {ANOVA_ALPHA: False})
        self.assertEqual(anova_visibility(True), {ANOVA_ALPHA: True})

    def test_alpha_validation(self):
        frame = pd.read_csv(BALANCED)
        for value in (0, 1, -0.1, 1.5, float("nan"), float("inf"), True, "0.05", None):
            with self.subTest(value=value):
                with self.assertRaises(FieldError) as caught:
                    check_anova_options({ANOVA_EFFECTS: True, ANOVA_ALPHA: value})
                self.assertEqual(caught.exception.field, ANOVA_ALPHA)
                with self.assertRaises(FieldError):
                    run(frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: value})
        self.assertEqual(check_anova_options({ANOVA_EFFECTS: True, ANOVA_ALPHA: 1e-6}), 1e-6)
        self.assertEqual(check_anova_options({ANOVA_EFFECTS: True, ANOVA_ALPHA: np.float64(0.999)}), 0.999)
        self.assertIsNone(check_anova_options({ANOVA_EFFECTS: False, ANOVA_ALPHA: 7}))
        self.assertIsNone(check_anova_options({}))


class UnbalancedTest(unittest.TestCase):
    def assert_matches_statsmodels(self, frame, response="Y", a="A", b="B"):
        result = run(frame, factors=(a, b), response=response, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05})
        data = frame[[response, a, b]].dropna().rename(columns={response: "y", a: "a", b: "b"})
        model = ols("y ~ C(a, Sum) * C(b, Sum)", data=data).fit()
        reference = sm.stats.anova_lm(model, typ=3)
        ss = reference["sum_sq"].to_numpy()[1:4]
        effects = result.tables[ANOVA_EFFECTS]
        anova = result.tables["ANOVA (type III)"]
        np.testing.assert_allclose(anova["SS"].to_numpy()[:3], ss, rtol=1e-9)
        np.testing.assert_allclose(effects["p"], reference["PR(>F)"].to_numpy()[1:4], rtol=1e-8)
        sst = float(((data["y"] - data["y"].mean()) ** 2).sum())
        sse = float(model.ssr)
        np.testing.assert_allclose(effects["Eta squared"], ss / sst, rtol=1e-9)
        np.testing.assert_allclose(effects["Partial eta squared"], ss / (ss + sse), rtol=1e-9)
        np.testing.assert_allclose(effects["Cohen f"], np.sqrt(ss / sse), rtol=1e-9)
        fit = result.tables[ANOVA_MODEL_FIT]["Value"]
        self.assertEqual(fit["N"], len(data))
        self.assertEqual(fit["Residual df"], model.df_resid)
        self.assertAlmostEqual(fit["Total SS (centered)"], sst, places=9)
        self.assertAlmostEqual(fit["Residual SS"], sse, places=9)
        self.assertAlmostEqual(fit["R²"], model.rsquared, places=12)
        self.assertAlmostEqual(fit["R²"], 1 - sse / sst, places=12)
        self.assertAlmostEqual(fit["Adjusted R²"], model.rsquared_adj, places=12)
        return result

    def test_type_iii_and_r2_match_statsmodels(self):
        result = self.assert_matches_statsmodels(unbalanced())
        # Type III SS overlap in an unbalanced design: they need not add up to SST − SSE.
        effects = result.tables[ANOVA_EFFECTS]
        fit = result.tables[ANOVA_MODEL_FIT]["Value"]
        explained = fit["Total SS (centered)"] - fit["Residual SS"]
        self.assertGreater(abs(effects["Eta squared"].sum() * fit["Total SS (centered)"] - explained), 1e-6)

    def test_unicode_labels(self):
        frame = unbalanced().replace({"a1": "Ünïcødé α", "a2": "β—γ", "b1": "日本", "b2": "Ω"})
        frame = frame.rename(columns={"A": "Génotype", "B": "Sesso ♀♂", "Y": "Peso (µg)"})
        result = self.assert_matches_statsmodels(frame, "Peso (µg)", "Génotype", "Sesso ♀♂")
        self.assertEqual(list(result.tables[ANOVA_EFFECTS].index), ["Génotype", "Sesso ♀♂", "Génotype:Sesso ♀♂"])

    def test_missing_response_and_excluded_cell_use_complete_cases(self):
        frame = unbalanced()
        frame.loc[[2, 9], "Y"] = np.nan
        frame.loc[5, "B"] = np.nan
        result = self.assert_matches_statsmodels(frame)
        self.assertEqual(result.tables[ANOVA_MODEL_FIT]["Value"]["N"], len(frame) - 3)

    def test_shuffled_rows_give_the_same_report(self):
        frame = unbalanced()
        shuffled = frame.sample(frac=1, random_state=3).reset_index(drop=True)
        options = {ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05}
        first, second = run(frame, **options), run(shuffled, **options)
        for name in (ANOVA_EFFECTS, ANOVA_MODEL_FIT):
            pd.testing.assert_frame_equal(first.tables[name], second.tables[name], rtol=1e-10)

    def test_null_term_gives_zero(self):
        frame = pd.DataFrame({"A": ["x"] * 4 + ["y"] * 4, "B": ["p", "p", "q", "q"] * 2,
                              "Y": [5, 7, 5, 7, 9, 11, 9, 11]})
        effects = run(frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05}).tables[ANOVA_EFFECTS]
        for term in ("B", "A:B"):
            for column in COLUMNS[:4]:
                self.assertAlmostEqual(effects.loc[term, column], 0, places=9)
            self.assertEqual(effects.loc[term, "Significant"], "No")
        self.assertGreater(effects.loc["A", "Eta squared"], 0)

    def test_no_residual_variance_keeps_the_existing_error(self):
        frame = pd.DataFrame({"A": ["x", "x", "y", "y"] * 2, "B": ["p", "q"] * 4, "Y": [1, 2, 3, 4] * 2})
        with self.assertRaisesRegex(ValueError, "no measurable residual variance"):
            run(frame, **{ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05})


class ReferenceDossierTest(unittest.TestCase):
    """Published reference rows (three factors, order 2): the effect sizes follow from SS, SSE and SST alone."""

    ROWS = {  # term: (SS, eta², partial eta², Cohen f, p)
        "Genotype": (70.68097222222232, .004389995327775105, .07915604505817377, .29318991177559606,
                     .004699944107772192),
        "Sex": (1642.9511111111115, .10204369683631838, .6664569325392282, 1.4135464547701084,
                8.619663605901319e-33),
        "Diet": (12575.875972222224, .7810876820873324, .9386293990199605, 3.910811542133072, 1.649773990870593e-79),
        "Genotype:Sex": (2.298472222222187, .0001427581143741518, .002787548825057139, .052870984239999336,
                         .8340652161596683),
        "Genotype:Diet": (591.5269444444438, .03673973971664964, .41840156035807097, .848174148372561,
                          1.414813480401587e-14),
        "Sex:Diet": (394.8818055555556, .024526109742266097, .32443605800836367, .6929969566600519,
                     8.478518600820882e-12),
    }

    def test_reference_effect_sizes(self):
        sse, sst = 822.2511111111112, 16100.466388888888888
        table = pd.DataFrame({"SS": [row[0] for row in self.ROWS.values()] + [sse],
                              "p": [row[4] for row in self.ROWS.values()] + [np.nan]},
                             index=pd.Index([*self.ROWS, "Residual"], name="Term"))
        effects, model = engine.anova_effect_sizes(table, {"N": 144, "df": 130, "SST": sst, "SSE": sse}, 0.05)
        expected = np.array([row[1:4] for row in self.ROWS.values()])
        np.testing.assert_allclose(effects[["Eta squared", "Partial eta squared", "Cohen f"]].to_numpy(), expected,
                                   rtol=1e-12)
        self.assertEqual(effects["Significant"].tolist(), ["Yes", "Yes", "Yes", "No", "Yes", "Yes"])
        self.assertAlmostEqual(model["Value"]["R²"], 1 - sse / sst)


class ThreeFactorTest(unittest.TestCase):
    def test_third_order_adds_the_triple_term(self):
        rng = np.random.default_rng(12)
        levels = [(g, s, d) for g in "abc" for s in "MF" for d in ("low", "mid", "high")]
        frame = pd.DataFrame([(g, s, d, rng.normal(20 + len(d), 2)) for g, s, d in levels for _ in range(4)],
                             columns=["Genotype", "Sex", "Diet", "Y"])
        factors = ("Genotype", "Sex", "Diet")
        options = {ANOVA_EFFECTS: True, ANOVA_ALPHA: 0.05}
        second = run(frame, factors=factors, order=2, **options)
        third = run(frame, factors=factors, order=3, **options)
        self.assertEqual(len(second.tables[ANOVA_EFFECTS]), 6)
        self.assertEqual(list(third.tables[ANOVA_EFFECTS].index)[-1], "Genotype:Sex:Diet")
        df2 = second.tables[ANOVA_MODEL_FIT]["Value"]["Residual df"]
        df3 = third.tables[ANOVA_MODEL_FIT]["Value"]["Residual df"]
        self.assertEqual(df2 - df3, 2 * 1 * 2)
        self.assertEqual(df3, len(frame) - 18)
        for result in (second, third):
            fit = result.tables[ANOVA_MODEL_FIT]["Value"]
            self.assertAlmostEqual(fit["R²"], 1 - fit["Residual SS"] / fit["Total SS (centered)"])


if __name__ == "__main__":
    unittest.main()
