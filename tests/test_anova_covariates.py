"""Additive covariates in the multifactor ANOVA, checked against the frozen factorial case."""
from pathlib import Path
import json
import time
import unittest

import numpy as np
import pandas as pd

from analisi.anova_covariates import (COVARIATES, COEFFICIENTS, EXPLICIT, JOINT, MEAN_SOURCE, REFERENCES,
                                      REFERENCE_SHEET, CovariateFitCancelled)
from analisi.anova_ss import KEY as SUMS
from analisi.data import Dataset, load_project, save_project
from analisi.field_error import FieldError
from analisi.stats import factorial_anova
from analisi.workbench import analyse


ROOT = Path(__file__).resolve().parent / "data" / "covariate-anova"
METHOD = "Multifactor ANOVA"
FACTORS = ["Dose", "Metodo"]
AT = {"X": 6.0, "Z": 4.0}


def frame():
    return pd.read_csv(ROOT / "fattoriale.csv")


def expected():
    return json.loads((ROOT / "atteso.json").read_text(encoding="utf-8"))


def recipe(covariates, order, references=None, **extra):
    options = {"Response": "Y", "Factors": list(FACTORS), "Interaction order": order,
               COVARIATES: list(covariates),
               REFERENCES: dict(AT if references is None else references)}
    options.update(extra)
    return options


def means(data, covariates, order, factors):
    options = recipe(covariates, order, **{
        "Estimated marginal means": True, "Marginal mean factors": list(factors),
        "Marginal mean confidence": 0.95})
    sheet = analyse(METHOD, data, options).tables["Estimated marginal means"]
    return sheet


def term_name(label):
    if label in ("X", "Z"):
        return label
    if label == "Dose:Metodo":
        return "C(Dose, Sum):C(Metodo, Sum)"
    return f"C({label}, Sum)"


class PackageTests(unittest.TestCase):
    def test_three_models_match_the_frozen_reference(self):
        data, target = frame(), expected()
        specs = (("two_covariates_with_interaction", ["X", "Z"], 2),
                 ("one_covariate_with_interaction", ["X"], 2),
                 ("two_covariates_without_interaction", ["X", "Z"], 1))
        for key, covariates, order in specs:
            with self.subTest(model=key):
                want = target[key]
                result = analyse(METHOD, data, recipe(covariates, order, **{"Effect sizes": True}))
                table = result.tables["ANOVA (type III)"]
                self.assertEqual(int(result.tables["Model fit"].loc["N", "Value"]), want["n"])
                self.assertEqual(int(table.loc["Residual", "df"]), want["residual_df"])
                self.assertAlmostEqual(float(table.loc["Residual", "SS"]), want["rss"], delta=1e-9)
                for label, row in table.drop(index="Residual").iterrows():
                    item = want["type_iii"][term_name(label)]
                    self.assertAlmostEqual(float(row["SS"]), item["sum_sq"], delta=1e-8)
                    self.assertEqual(float(row["df"]), item["df"])
                    np.testing.assert_allclose(float(row["F"]), item["F"], rtol=2e-8, atol=1e-10)
                    np.testing.assert_allclose(float(row["p"]), item["PR(>F)"], rtol=2e-8, atol=1e-10)
                coefficients = result.tables[COEFFICIENTS]
                for name, item in want["covariates"].items():
                    got = coefficients.loc[name]
                    for column, source in (("Estimate", "estimate"), ("SE", "se"),
                                           ("CI low", "low"), ("CI high", "high")):
                        np.testing.assert_allclose(float(got[column]), item[source], rtol=2e-8, atol=1e-10)
                    self.assertEqual(int(got["df"]), want["residual_df"])
                cells = means(data, covariates, order, FACTORS)
                for label, item in want["cell_means"].items():
                    dose, method = label.split(" / ")
                    row = cells[(cells["Dose"] == dose) & (cells["Metodo"] == method)].iloc[0]
                    for column, source in (("Estimate", "estimate"), ("SE", "se"),
                                           ("CI low", "low"), ("CI high", "high")):
                        np.testing.assert_allclose(float(row[column]), item[source], rtol=2e-8, atol=1e-10)
                for factor, block in (("Dose", want["dose_means"]), ("Metodo", want["method_means"])):
                    sheet = means(data, covariates, order, [factor])
                    for level, item in block.items():
                        row = sheet[sheet[factor] == level].iloc[0]
                        np.testing.assert_allclose(float(row["Estimate"]), item["estimate"], rtol=2e-8, atol=1e-10)
                        np.testing.assert_allclose(float(row["SE"]), item["se"], rtol=2e-8, atol=1e-10)
                references = result.tables[REFERENCE_SHEET]
                self.assertEqual(list(references.index), covariates)
                self.assertTrue((references["Source"] == EXPLICIT).all())
                self.assertIn("Dose $", set(cells["Dose"]))
                if len(covariates) == 2:
                    self.assertIn(JOINT, references["Note"].iloc[0])

    def test_the_dose_contrast_uses_the_adjusted_means(self):
        data = frame()
        options = recipe(["X", "Z"], 2, **{"Compare marginal means by": "Dose", "Correction": "None"})
        result = analyse(METHOD, data, options)
        dose = means(data, ["X", "Z"], 2, ["Dose"]).set_index("Dose")
        difference = float(dose.loc["Base", "Estimate"] - dose.loc["Dose $", "Estimate"])
        found = result.tables["Multiple comparisons"].loc["Base − Dose $", "Difference"]
        np.testing.assert_allclose(found, difference, rtol=1e-10, atol=1e-10)

    def test_reordering_rows_or_columns_does_not_change_the_fit(self):
        data = frame()
        original = analyse(METHOD, data, recipe(["X", "Z"], 2)).tables[COEFFICIENTS]
        shuffled = data.sample(frac=1, random_state=3)
        columns = ["Y", "Z", "Metodo", "X", "Dose"]
        moved = analyse(METHOD, shuffled[columns], recipe(["X", "Z"], 2)).tables[COEFFICIENTS]
        pd.testing.assert_frame_equal(original, moved)

    def test_a_missing_response_stays_out_of_every_term(self):
        data = frame()
        data.loc[0, "Y"] = np.nan
        result = analyse(METHOD, data, recipe(["X", "Z"], 2, **{"Effect sizes": True}))
        self.assertEqual(int(result.tables["Model fit"].loc["N", "Value"]), 38)
        self.assertEqual(int(result.tables[REFERENCE_SHEET]["N"].iloc[0]), 38)
        self.assertEqual(int(result.tables["ANOVA (type III)"].loc["Residual", "df"]), 30)

    def test_changing_the_reference_moves_the_means_and_keeps_the_slope(self):
        data = frame()
        first = analyse(METHOD, data, recipe(["X"], 2)).tables[COEFFICIENTS].loc["X", "Estimate"]
        second = analyse(METHOD, data, recipe(["X"], 2, {"X": 0.0})).tables[COEFFICIENTS].loc["X", "Estimate"]
        np.testing.assert_allclose(first, second, rtol=1e-12, atol=1e-12)
        at_six = means(data, ["X"], 2, FACTORS).set_index(["Dose", "Metodo"])
        at_zero = means(data, ["X"], 2, {"X": 0.0} and FACTORS)
        # means() always centres on the package references. Ask for zero directly.
        sheet = analyse(METHOD, data, recipe(["X"], 2, {"X": 0.0}, **{
            "Estimated marginal means": True, "Marginal mean factors": FACTORS,
            "Marginal mean confidence": 0.95})).tables["Estimated marginal means"]
        self.assertGreater(abs(float(sheet.iloc[0]["Estimate"]) - float(at_six.iloc[0]["Estimate"])), 1.0)

    def test_an_omitted_reference_uses_the_mean_of_the_rows_in_the_fit(self):
        data = frame()
        options = recipe(["X", "Z"], 2, {})
        result = analyse(METHOD, data, options)
        references = result.tables[REFERENCE_SHEET]
        self.assertTrue((references["Source"] == MEAN_SOURCE).all())
        used = data[["X", "Z"]].to_numpy()
        np.testing.assert_allclose(references["Reference"].to_numpy(), used.mean(axis=0))

    def test_a_recipe_without_the_option_matches_the_factorial_anova(self):
        data = frame()
        options = {"Response": "Y", "Factors": FACTORS, "Interaction order": 2}
        result = analyse(METHOD, data, options)
        direct = factorial_anova(data, "Y", FACTORS, 2)
        pd.testing.assert_frame_equal(result.tables["ANOVA (type III)"], direct)
        self.assertNotIn(COEFFICIENTS, result.tables)
        self.assertNotIn(REFERENCE_SHEET, result.tables)

    def test_constant_duplicate_empty_cell_and_type_i_are_field_errors(self):
        data = frame()
        constant = data.assign(Flat=1.0)
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, constant, recipe(["Flat"], 2))
        self.assertEqual(caught.exception.field, COVARIATES)
        self.assertIn("constant", str(caught.exception))
        copied = data.assign(X2=data["X"])
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, copied, recipe(["X", "X2"], 2))
        self.assertIn("repeats", str(caught.exception))
        empty = data[~((data["Dose"] == "Base") & (data["Metodo"] == "A"))].copy()
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, empty, recipe(["X"], 2))
        self.assertIn("empty cell", str(caught.exception))
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, data, recipe(["X"], 2, **{SUMS: "Type I"}))
        self.assertEqual(caught.exception.field, SUMS)
        self.assertIn("Type III", str(caught.exception))

    def test_a_dollar_in_a_new_level_stays_literal(self):
        data = frame()
        extra = data.iloc[:1].copy()
        extra["Dose"] = "A$B"
        extra["Y"] = 15.0
        # Give the new level a second method so the interaction cell exists for A and B and C.
        rows = [extra.assign(Metodo=method, Y=15.0 + index) for index, method in enumerate(("A", "B", "C"))]
        widened = pd.concat([data, *rows], ignore_index=True)
        analyse(METHOD, widened, recipe(["X"], 1))
        sheet = means(widened, ["X"], 1, ["Dose"])
        self.assertIn("A$B", set(sheet["Dose"]))

    def test_save_reopen_and_a_changed_response(self):
        data = frame()
        options = recipe(["X", "Z"], 2)
        with self.subTest(project="round trip"):
            import tempfile
            directory = Path(tempfile.mkdtemp())
            path = directory / "covariate.alab"
            save_project(path, {"Fattoriale": Dataset(data, analyses=[(METHOD, options)])})
            loaded = load_project(path)["Fattoriale"]
            self.assertEqual(loaded.analyses[0][1][COVARIATES], ["X", "Z"])
            first = analyse(METHOD, loaded.frame(), loaded.analyses[0][1]).tables[COEFFICIENTS]
            second = analyse(METHOD, data, options).tables[COEFFICIENTS]
            pd.testing.assert_frame_equal(first, second)
            changed = loaded.frame()
            changed.loc[0, "Y"] = float(changed.loc[0, "Y"]) + 1
            moved = analyse(METHOD, changed, loaded.analyses[0][1]).tables[COEFFICIENTS]
            self.assertGreater(abs(float(moved.loc["X", "Estimate"] - first.loc["X", "Estimate"])), 1e-6)

    def test_cancel_and_a_large_table(self):
        data = frame()
        with self.assertRaises(CovariateFitCancelled):
            analyse(METHOD, data, recipe(["X", "Z"], 2), cancel=lambda: True)
        rng = np.random.default_rng(5)
        n = 50_000
        dose = np.arange(n) % 4
        method = (np.arange(n) // 4) % 3
        x = rng.normal(size=n)
        z = rng.normal(size=n)
        y = 2 * dose + method + 1.5 * x - 0.7 * z + rng.normal(scale=0.4, size=n)
        wide = pd.DataFrame({"Y": y, "Dose": dose.astype(str), "Metodo": method.astype(str), "X": x, "Z": z})
        started = time.perf_counter()
        result = analyse(METHOD, wide, recipe(["X", "Z"], 2, {"X": 0.0, "Z": 0.0}))
        elapsed = time.perf_counter() - started
        print(f"Covariate ANOVA 50000x4x3: {elapsed:.3f}s")
        self.assertLess(elapsed, 15)
        self.assertEqual(int(result.tables[REFERENCE_SHEET]["N"].iloc[0]), n)
        self.assertTrue(np.isfinite(result.tables[COEFFICIENTS]["Estimate"]).all())


if __name__ == "__main__":
    unittest.main()
