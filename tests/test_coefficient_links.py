"""Linked coefficients (C = factor × source + offset) in Fit custom equation and Global fit custom equation."""
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi import coefficient_links as links
from analisi.custom_fit import custom_fit, resolve as resolve_single
from analisi.data import load_project
from analisi.field_error import FieldError
from analisi.global_custom_fit import global_custom_fit
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "coefficient_links"
CURVES = pd.read_csv(DATA / "curve.csv")
EXPECTED = json.loads((DATA / "atteso.json").read_text())
EQUATION = "B + A*X + C*X^2"


def record(name, start=1.0, lower=None, upper=None, fixed=False, shared=None, link=None):
    found = {"name": name, "start": start, "lower": lower, "upper": upper, "fixed": fixed}
    if shared is not None:
        found["shared"] = shared
    if link is not None:
        found["link"] = dict(zip(("source", "factor", "offset"), link))
    return found


def global_options(parameters, equation=EQUATION, **extra):
    return {"X": "x", "Y": "y", "Group": "serie", "Equation": equation, "Parameters": parameters,
            "Series constraints": [], **extra}


def single_options(parameters, equation=EQUATION, **extra):
    return {"X": "x", "Y": "y", "Equation": equation, "Parameters": parameters, **extra}


GLOBAL = [record("A", shared=True), record("B", shared=False), record("C", 3.0, shared=True, link=("A", 2.0, 1.0))]
SINGLE = [record("A"), record("B"), record("C", 3.0, link=("A", 2.0, 1.0))]
UNO = CURVES[CURVES["serie"] == "Uno"].reset_index(drop=True)


def close(test, actual, expected, tol):
    test.assertTrue(np.allclose(actual, expected, rtol=tol, atol=tol), f"{actual} != {expected}")


class OracleTests(unittest.TestCase):
    """The three cases of atteso.json, from the analysis action itself."""

    def check(self, case, parameters, summary, predictions, se_tol=1e-5):
        expected = EXPECTED[case]
        close(self, parameters["A"]["Estimate"], expected["A"], 1e-6)
        close(self, parameters["C"]["Estimate"], expected["C"], 1e-6)
        close(self, summary["rss"], expected["rss"], 1e-6)
        self.assertEqual(summary["df"], expected["df"])
        self.assertEqual(summary["free"], expected["free"])
        close(self, parameters["A"]["SE"], expected["se_A"], se_tol)
        close(self, parameters["C"]["SE"], expected["se_C"], se_tol)
        close(self, parameters["C"]["CI"], expected["ci_C"], se_tol)
        close(self, predictions, expected["predictions"], 1e-6)

    def global_case(self, case, **extra):
        result = analyse("Global fit custom equation", CURVES, global_options(GLOBAL, **extra))
        table = result.tables["Parameters"]
        rows = {name: table[(table["Parameter"] == name) & table["Group"].isna()].iloc[0] for name in ("A", "C")}
        parameters = {name: {"Estimate": row["Estimate"], "SE": row["SE"], "CI": [row["CI low"], row["CI high"]]}
                      for name, row in rows.items()}
        summary = result.tables["Global fit"]["Value"]
        for group, value in EXPECTED[case]["B"].items():
            estimate = table[(table["Parameter"] == "B") & (table["Group"] == group)]["Estimate"].iloc[0]
            close(self, estimate, value, 1e-6)
        self.check(case, parameters, {"rss": summary["Weighted residual SS"], "df": summary["DF residual"],
                                      "free": summary["Free parameters"]},
                   result.tables["Residuals"]["Predicted"].to_numpy())
        return result

    def test_global_unweighted(self):
        result = self.global_case("globale")
        table = result.tables["Parameters"]
        linked = table[table["Parameter"] == "C"].iloc[0]
        self.assertEqual((linked["Status"], linked["Scope"], linked["Relation"]), ("Linked", "Shared", "C = 2*A + 1"))
        summary = result.tables["Global fit"]["Value"]
        self.assertEqual(summary["Linked parameters"], 1)
        self.assertEqual(summary["Dependency order"], "A → C")
        # The covariance sheet carries the linked coefficient: Cov(C, ·) = 2 Cov(A, ·).
        covariance = result.tables["Covariance"]
        a, c = ("Shared", None, "A"), ("Shared", None, "C")
        close(self, covariance.loc[c, c], 4 * covariance.loc[a, a], 1e-12)
        close(self, covariance.loc[c, a], 2 * covariance.loc[a, a], 1e-12)

    def test_global_weighted(self):
        self.global_case("pesato", Weighting="Inverse variance (column)", **{"SD column": "sd"})

    def test_single_series(self):
        result = analyse("Fit custom equation", UNO, single_options(SINGLE))
        table = result.tables["Parameters: All"]
        parameters = {name: {"Estimate": table.loc[name, "Estimate"], "SE": table.loc[name, "SE"],
                             "CI": [table.loc[name, "CI lower"], table.loc[name, "CI upper"]]} for name in "AC"}
        summary = result.tables["Fit: All"]["Value"]
        close(self, table.loc["B", "Estimate"], EXPECTED["singolo"]["B"]["Uno"], 1e-6)
        self.check("singolo", parameters, {"rss": summary["Weighted residual SS"], "df": summary["df"],
                                           "free": summary["Free parameters"]},
                   result.tables["Residuals: All"]["Predicted"].to_numpy())
        self.assertEqual(table.loc["C", "Status"], "Linked")
        self.assertEqual(summary["Links"], "C = 2*A + 1")

    def test_global_response_band_follows_the_link(self):
        """The confidence band of the curve equals the band of the explicit linear model."""
        result = global_custom_fit(CURVES, global_options(GLOBAL, **{"Curve band": "Confidence"}))
        band = result.tables["Curve bands"]
        band = band[band["Group"] == "Uno"].iloc[:5]
        x, y = CURVES["x"].to_numpy(), CURVES["y"].to_numpy()
        design = np.column_stack([x + 2 * x * x, CURVES["serie"] == "Uno", CURVES["serie"] == "Due"]).astype(float)
        beta = np.linalg.lstsq(design, y - x * x, rcond=None)[0]
        residual = y - x * x - design @ beta
        covariance = np.linalg.inv(design.T @ design) * (residual @ residual / 7)
        grid = band["X"].to_numpy()
        gradient = np.column_stack([grid + 2 * grid * grid, np.ones(len(grid)), np.zeros(len(grid))])
        close(self, band["SE mean"].to_numpy(), np.sqrt(np.einsum("ij,jk,ik->i", gradient, covariance, gradient)),
              1e-5)


class RuleTests(unittest.TestCase):
    def test_local_starts_are_checked_after_each_series_override(self):
        parameters = [record("A", start=0, shared=False), record("B", shared=True),
                      record("C", lower=2, shared=False, link=("A", 1, 0))]
        overrides = [{"series": group, "parameters": {"A": {"initial": 3}}} for group in ("Due", "Uno")]
        options = global_options(parameters, **{"Series constraints": overrides})
        table = global_custom_fit(CURVES, options).tables["Parameters"]
        self.assertTrue((table.loc[table["Parameter"] == "C", "Estimate"] >= 2).all())
        with self.assertRaises(FieldError) as raised:
            global_custom_fit(CURVES, {**options, "Series constraints": overrides[:1]})
        self.assertEqual(raised.exception.field, "Series constraints")
        self.assertIn("Uno", str(raised.exception))

    def test_unrepresentable_composition_is_reported_before_fitting(self):
        for first, second, offset in ((1e-220, 1e-150, 0), (1e240, 1e160, 0), (1, 2, 1e308)):
            with self.subTest(first=first, second=second, offset=offset):
                parameters = [record("A"), record("B", link=("A", first, offset)),
                              record("C", link=("B", second, 0))]
                with self.assertRaises(FieldError) as raised:
                    resolve_single(UNO, single_options(parameters))
                self.assertEqual(raised.exception.field, "Parameters")
                self.assertIn("C", str(raised.exception))

    def test_integer_link_constants_are_validated_in_the_precision_used_by_the_fit(self):
        self.assertEqual(links.read_link({"link": {"source": "A", "offset": 10**30}}, "C").offset, 1e30)
        with self.assertRaises(FieldError):
            links.read_link({"link": {"source": "A", "offset": 10**400}}, "C")

    def test_negative_factor_carries_reversed_limits(self):
        parameters = [record("A", -1.0), record("B"), record("C", 3.0, 1.0, 5.0, link=("A", -2.0, 1.0))]
        s = resolve_single(UNO, single_options(parameters))
        a = next(c for c in s.coefficients if c.name == "A")
        self.assertEqual((a.lower, a.upper), (-2.0, 0.0))
        for method in ("Symmetric (Wald)", "Profile likelihood"):
            table = custom_fit(UNO, single_options(parameters, **{"Parameter intervals": method})).tables[
                "Parameters: All"]
            self.assertTrue(-2 < table.loc["A", "Estimate"] < 0)
            close(self, table.loc["C", "Estimate"], -2 * table.loc["A", "Estimate"] + 1, 1e-12)
            close(self, table.loc["C", "SE"], 2 * table.loc["A", "SE"], 1e-12)
            # A negative factor swaps the ends of the interval.
            close(self, table.loc["C", "CI lower"], -2 * table.loc["A", "CI upper"] + 1, 1e-9)
            close(self, table.loc["C", "CI upper"], -2 * table.loc["A", "CI lower"] + 1, 1e-9)

    def test_target_at_its_limit_suppresses_the_inference(self):
        parameters = [record("A", 1.0), record("B"), record("C", 3.0, None, 3.5, link=("A", 2.0, 1.0))]
        result = custom_fit(UNO, single_options(parameters))
        table = result.tables["Parameters: All"]
        # The data want A = 1.5 (C = 4): C stops at 3.5, so A stops at 1.25; no SE for either.
        self.assertEqual(table.loc["A", "Status"], "At bound")
        close(self, table.loc["A", "Estimate"], 1.25, 1e-7)
        close(self, table.loc["C", "Estimate"], 3.5, 1e-7)
        self.assertTrue(np.isnan(table.loc["C", "SE"]))
        self.assertIn("C follows A, which is at a limit", result.tables["Fit: All"].loc["Note", "Value"])
        profile = custom_fit(UNO, single_options(parameters, **{"Parameter intervals": "Profile likelihood"}))
        status = profile.tables["Parameter CI status: All"]
        self.assertEqual(status.loc["C", "Upper status"], "Parameter bound")
        close(self, profile.tables["Parameters: All"].loc["C", "CI upper"], 3.5, 1e-9)

    def test_incompatible_limit(self):
        with self.assertRaises(FieldError) as raised:
            resolve_single(UNO, single_options([record("A", 0.0, -1.0, 1.0), record("B"),
                                                record("C", 3.0, 10.0, 20.0, link=("A", -2.0, 1.0))]))
        self.assertIn("leave no admissible value for A", str(raised.exception))
        self.assertEqual(raised.exception.field, "Parameters")

    def test_start_outside_the_carried_range(self):
        with self.assertRaises(FieldError) as raised:
            resolve_single(UNO, single_options([record("A", 1.0), record("B"),
                                                record("C", 3.0, 1.0, 5.0, link=("A", -2.0, 1.0))]))
        self.assertIn("A: the starting value 1 lies outside the range allowed by the links of C (-2 to 0)",
                      str(raised.exception))

    def test_chain_with_d_in_the_equation(self):
        """D = 3 - C/2 with C = 2A + 1 is D = 2.5 - A: same SE as A, reversed profile limits."""
        parameters = [record("A", shared=True), record("B", shared=False),
                      record("C", 3.0, shared=True, link=("A", 2.0, 1.0)),
                      record("D", 1.0, shared=True, link=("C", -0.5, 3.0))]
        equation = "B + A*X/2 + (2.5 - D)*X/2 + C*X^2"
        for method in ("Symmetric (Wald)", "Profile likelihood"):
            result = global_custom_fit(CURVES, global_options(parameters, equation, **{"Parameter intervals": method}))
            table = result.tables["Parameters"].set_index("Parameter")
            close(self, table.loc["D", "Estimate"], 2.5 - EXPECTED["globale"]["A"], 1e-6)
            close(self, table.loc["D", "SE"], EXPECTED["globale"]["se_A"], 1e-5)
            close(self, table.loc["D", "CI low"], 2.5 - table.loc["A", "CI high"], 1e-6)
            close(self, table.loc["D", "CI high"], 2.5 - table.loc["A", "CI low"], 1e-6)
            close(self, table.loc["C", "Estimate"], EXPECTED["globale"]["C"], 1e-6)
            self.assertEqual(table.loc["D", "Relation"], "D = -0.5*C + 3 (D = -A + 2.5)")
            self.assertEqual(result.tables["Global fit"].loc["Dependency order", "Value"], "A → C → D")
            self.assertEqual(result.tables["Global fit"].loc["Free parameters", "Value"], 3)
            if method == "Profile likelihood":
                status = result.tables["Parameter CI status"]
                self.assertTrue(status.loc[status["Parameter"] == "D", "Lower reason"].iloc[0].startswith(
                    "Mapped from the profile of A"))

    def test_cycle_names_its_path(self):
        with self.assertRaises(FieldError) as raised:
            resolve_single(UNO, single_options([record("A", link=("C", 0.5, -0.5)), record("B"),
                                                record("C", link=("A", 2.0, 1.0))]))
        self.assertEqual(str(raised.exception), "The links form a cycle: A → C → A. Remove one of the links.")

    def test_missing_source_and_conflicts(self):
        cases = (
            ([record("A"), record("B"), record("C", link=("Z", 2.0, 1.0))], "the link source Z is not a coefficient"),
            ([record("A"), record("B"), record("C", fixed=True, link=("A", 2.0, 1.0))], "both Fixed and Linked"),
            ([record("A"), record("B"), record("C", link=("A", float("nan"), 1.0))], "factor of the link"),
            ([record("A"), record("B"), record("C", 2.0, 0.0, 1.0, link=("A", 0.0, 3.0))], "gives C = 3, outside"),
            ([record("A", 2.0, fixed=True), record("B"), record("C", 2.0, 0.0, 1.0, link=("A", 2.0, 1.0))],
             "gives C = 5, outside"),
        )
        for parameters, words in cases:
            with self.subTest(words=words), self.assertRaises(FieldError) as raised:
                resolve_single(UNO, single_options(parameters))
            self.assertIn(words, str(raised.exception))

    def test_link_does_not_change_the_grammar(self):
        """A link source that is not a coefficient is never read as code; the equation stays the same."""
        with self.assertRaises(FieldError):
            resolve_single(UNO, single_options([record("A"), record("B"),
                                                record("C", link=("__import__('os')", 1.0, 0.0))]))

    def test_shared_target_with_local_source_is_invalid(self):
        parameters = [record("A", shared=False), record("B", shared=False),
                      record("C", shared=True, link=("A", 2.0, 1.0))]
        with self.assertRaises(FieldError) as raised:
            global_custom_fit(CURVES, global_options(parameters))
        self.assertIn("estimated separately in series 'Uno'", str(raised.exception))
        self.assertEqual(raised.exception.field, "Parameters")

    def test_local_target_follows_the_local_source_of_its_series(self):
        parameters = [record("A", shared=True), record("B", shared=False),
                      record("C", 3.0, shared=False, link=("A", 2.0, 1.0)),
                      record("F", 0.0, shared=False, link=("B", 0.0, 0.0))]
        result = global_custom_fit(CURVES, global_options(parameters, "B + A*X + C*X^2 + F"))
        table = result.tables["Parameters"]
        linked = table[table["Status"] == "Linked"]
        self.assertEqual(sorted(zip(linked["Parameter"], linked["Group"])),
                         [("C", "Due"), ("C", "Uno"), ("F", "Due"), ("F", "Uno")])
        self.assertTrue(linked[linked["Parameter"] == "F"]["SE"].isna().all())

    def test_series_overrides_on_a_linked_coefficient(self):
        fixed = {"series": "Uno", "parameters": {"C": {"fixed": 4.0}}}
        with self.assertRaises(FieldError) as raised:
            global_custom_fit(CURVES, {**global_options(GLOBAL), "Series constraints": [fixed]})
        self.assertTrue(str(raised.exception).startswith("Series 'Uno', C: a linked coefficient"))
        self.assertEqual(raised.exception.field, "Series constraints")
        # A limit of one series restricts the shared root for every series: C ≤ 3.5 means A ≤ 1.25.
        upper = {"series": "Uno", "parameters": {"C": {"upper": 3.5}}}
        result = global_custom_fit(CURVES, {**global_options(GLOBAL), "Series constraints": [upper]})
        table = result.tables["Parameters"].set_index("Parameter")
        close(self, table.loc["A", "Estimate"], 1.25, 1e-6)
        self.assertEqual(table.loc["A", "Status"], "At bound")
        incompatible = {"series": "Due", "parameters": {"C": {"lower": 10.0, "upper": 20.0}},}
        bounded = [record("A", 1.0, 0.0, 2.0, shared=True), *GLOBAL[1:]]
        with self.assertRaises(FieldError) as raised:
            global_custom_fit(CURVES, {**global_options(bounded), "Series constraints": [incompatible]})
        self.assertTrue(str(raised.exception).startswith("Series 'Due', C: its limits"))

    def test_every_coefficient_fixed_through_the_links(self):
        parameters = [record("A", 1.5, fixed=True, shared=False), record("B", 3.0, fixed=True, shared=False),
                      record("C", 1.0, shared=True, link=("A", 2.0, 1.0))]
        result = global_custom_fit(CURVES, global_options(parameters))
        summary = result.tables["Global fit"]["Value"]
        self.assertEqual(summary["Free parameters"], 0)
        self.assertIn("Every coefficient is fixed", summary["Inference"])
        table = result.tables["Parameters"].set_index("Parameter")
        self.assertEqual(table.loc["C", "Estimate"], 4.0)
        self.assertTrue(np.isnan(table.loc["C", "SE"]))
        single = custom_fit(UNO, single_options([{k: v for k, v in r.items() if k != "shared"} for r in parameters]))
        self.assertEqual(single.tables["Fit: All"].loc["Free parameters", "Value"], 0)
        self.assertEqual(single.tables["Parameters: All"].loc["C", "Estimate"], 4.0)

    def test_condition_through_a_link(self):
        parameters = [record("A"), record("B"), record("T", 0.0, link=("A", 1.0, 0.0))]
        options = single_options(parameters, "if(X > T, B + A*X, B)", **{"Equation syntax": "Conditional"})
        with self.assertRaises(FieldError) as raised:
            resolve_single(UNO, options)
        self.assertIn("T (through A) appears in a condition", str(raised.exception))
        options["Parameters"] = [record("A"), record("B"), record("K", 0.0, fixed=True),
                                 record("T", 0.0, link=("K", 1.0, 0.0))]
        options["Equation"] = "if(X > T, B + A*X, B) + 0*K"
        resolve_single(UNO, options)  # a fixed root makes the threshold known

    def test_removing_the_link_frees_the_coefficient(self):
        linked = custom_fit(UNO, single_options(SINGLE)).tables["Parameters: All"]
        free = [record("A"), record("B"), record("C", float(linked.loc["C", "Estimate"]))]
        table = custom_fit(UNO, single_options(free)).tables["Parameters: All"]
        self.assertEqual(table.loc["C", "Status"], "Free")
        self.assertNotIn("Relation", table.columns)
        self.assertEqual(custom_fit(UNO, single_options(free)).tables["Fit: All"].loc["Free parameters", "Value"], 3)


class RecipeTests(unittest.TestCase):
    def test_previous_project_reads_and_runs_unchanged(self):
        legacy = Path(__file__).resolve().parent / "data" / "global_custom" / "legacy-global-and-custom.alab"
        for table in load_project(legacy).values():
            frame = table.frame(mask_excluded=True)
            for method, options in table.analyses:
                if method != "Fit custom equation":
                    continue
                self.assertFalse(any("link" in r for r in options["Parameters"]))
                result = analyse(method, frame, options)
                for name, sheet in result.tables.items():
                    if name.startswith("Parameters"):
                        self.assertEqual(list(sheet.columns), ["Estimate", "SE", "CI lower", "CI upper", "Status"])
                    if name.startswith("Fit:"):
                        self.assertNotIn("Linked parameters", sheet.index)

    def test_examples_reopen(self):
        from tests.coefficient_links_measure import measure  # noqa: PLC0415 - the adapter of the fixture
        for reopen in (False, True):
            measured = measure(reopen)
            for case, expected in EXPECTED.items():
                close(self, measured[case]["A"], expected["A"], 1e-6)
                close(self, measured[case]["se_C"], expected["se_C"], 1e-5)

    def test_plan_texts(self):
        plan = links.Plan(resolve_single(UNO, single_options([
            record("A", -1.0), record("B"), record("C", link=("A", 2.0, 1.0)), record("D", link=("C", -0.5, 3.0)),
            record("E", link=("B", -1.0, 0.0))], "B + A*X + C*X^2 + D + E")).coefficients)
        self.assertEqual(plan.dependency_text(), "A → C → D; B → E")
        self.assertEqual(plan.formula("E"), "E = -B")
        self.assertEqual(links.affine_text("C", 0.1, -1e-17, "A"), "C = 0.1*A - 1e-17")


if __name__ == "__main__":
    unittest.main()


class DuplicateTests(unittest.TestCase):
    def test_duplicated_family_keeps_independent_links(self):
        from analisi.family_workflow import duplicate_family
        examples = Path(__file__).resolve().parent.parent / "docs" / "examples"
        tables = load_project(examples / "Coefficienti-collegati-globale.alab")
        bundle = duplicate_family(tables, (), (), ("data", "Curve collegate"), name="Copia")
        copy = list(bundle.tables.values())[0] if isinstance(bundle.tables, dict) else bundle.tables[0]
        original = tables["Curve collegate"].analyses[0][1]["Parameters"][2]["link"]
        duplicated = copy.analyses[0][1]["Parameters"][2]["link"]
        self.assertEqual(duplicated, original)
        duplicated["factor"] = 3.0
        self.assertEqual(original["factor"], 2.0)
        result = analyse(copy.analyses[0][0], copy.frame(mask_excluded=True), copy.analyses[0][1])
        self.assertEqual(result.tables["Global fit"].loc["Links", "Value"], "C = 3*A + 1")
