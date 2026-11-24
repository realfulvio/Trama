"""Unit, contract, edge-case, benchmark, and Parts-of-whole non-regression tests for Pareto plot."""
from io import BytesIO
from pathlib import Path
import time
import unittest

from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from analisi import pareto_plot as pp
from analisi.data import Dataset
from analisi.linked_axes import linked_axes_conflicts, supported_dimensions
from analisi.presentation import apply_style, graph_groups, validate_graph_style
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, analyse


FIXTURE = Path(__file__).resolve().parent / "data" / "pareto_plot" / "pareto.csv"


def _run(frame, **options):
    opts = {pp.CATEGORY: "Categoria", **options}
    return analyse(pp.METHOD, frame, opts)


class ParetoPlotTests(unittest.TestCase):
    def test_catalogue_presence_and_no_linked_axes(self):
        self.assertIn(pp.METHOD, GROUPS["Graphing"])
        self.assertIn(pp.METHOD, GRAPH_METHODS)
        frame = pd.read_csv(FIXTURE)
        res = _run(frame, Weight="Peso", Threshold=80)
        ax0, ax1 = res.figure.axes
        self.assertEqual(len(res.figure.axes), 2)
        self.assertEqual(ax1.get_ylim(), (0.0, 100.0))
        self.assertEqual(supported_dimensions(ax0), ())
        conflicts = linked_axes_conflicts(ax0)
        self.assertIn("x", conflicts)
        self.assertIn("y", conflicts)

    def test_fixture_weighted_and_counts_and_settings(self):
        frame = pd.read_csv(FIXTURE)
        before = frame.copy(deep=True)
        res = _run(frame, Weight="Peso", Threshold=80)
        # Source frame must never be mutated/rewritten.
        pd.testing.assert_frame_equal(frame, before)

        table = res.tables[pp.CATEGORIES_SHEET]
        self.assertEqual(list(table.columns), pp.CATEGORIES_COLUMNS)
        self.assertEqual(table["Category"].tolist(), ["B", "A", "C", "Zero"])
        self.assertEqual(table["Amount"].tolist(), [6.0, 3.0, 3.0, 0.0])
        self.assertEqual(table["Percent"].tolist(), [50.0, 25.0, 25.0, 0.0])
        self.assertEqual(table["Cumulative percent"].tolist(), [50.0, 75.0, 100.0, 100.0])

        settings = res.tables[pp.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Mode"], "Weighted sum")
        self.assertEqual(float(settings["Total"]), 12.0)
        self.assertEqual(float(settings["Threshold (%)"]), 80.0)
        self.assertEqual(settings["Threshold category"], "C")
        self.assertEqual(int(settings["Observations used"]), 5)
        self.assertEqual(int(settings["Rows discarded"]), 0)

        # Count mode: omitted Weight, None Weight, empty string Weight.
        for w_opt in ({}, {pp.WEIGHT: None}, {pp.WEIGHT: ""}):
            counts_res = analyse(pp.METHOD, frame, {pp.CATEGORY: "Categoria", pp.THRESHOLD: "", **w_opt})
            ct = counts_res.tables[pp.CATEGORIES_SHEET]
            self.assertEqual(ct["Category"].tolist(), ["B", "A", "C", "Zero"])
            self.assertEqual(ct["Amount"].tolist(), [2, 1, 1, 1])
            self.assertEqual(ct["Percent"].tolist(), [40.0, 20.0, 20.0, 20.0])
            self.assertEqual(ct["Cumulative percent"].tolist(), [40.0, 60.0, 80.0, 100.0])
            self.assertEqual(ct["Cumulative percent"].iat[-1], 100.0)
            st = counts_res.tables[pp.SETTINGS_SHEET]["Value"]
            self.assertEqual(st["Mode"], "Counts")
            self.assertEqual(st["Threshold (%)"], "Disabled")
            self.assertEqual(st["Threshold category"], "None")

    def test_fractional_weights_and_exact_100_final_cumulative(self):
        frame = pd.DataFrame({
            "Cat": ["X", "Y", "Z", "X"],
            "W": ["0,5", "1,0", "1,0", "0,5"],
        })
        res = analyse(pp.METHOD, frame, {"Category": "Cat", "Weight": "W", "Threshold": "66,5"})
        table = res.tables[pp.CATEGORIES_SHEET]
        self.assertEqual(table["Category"].tolist(), ["X", "Y", "Z"])
        self.assertEqual(table["Amount"].tolist(), [1.0, 1.0, 1.0])
        self.assertAlmostEqual(table["Percent"].iloc[0], 100.0 / 3.0, places=12)
        self.assertAlmostEqual(table["Cumulative percent"].iloc[1], 200.0 / 3.0, places=12)
        # Final cumulative percent is exact 100.0 without floating-point drift.
        self.assertEqual(table["Cumulative percent"].iat[-1], 100.0)
        self.assertEqual(res.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"], "Y")

    def test_typed_identities_and_literal_labels(self):
        frame = pd.DataFrame({
            "Cat": pd.Series([1, "1", 1.0, True, "Control $", "1"], dtype=object),
            "W": [3.0, 2.0, 1.0, 0.5, 4.0, 2.0],
        })
        res = analyse(pp.METHOD, frame, {"Category": "Cat", "Weight": "W", "Threshold": 80})
        table = res.tables[pp.CATEGORIES_SHEET]
        # Sums: "1" -> 4.0 (first seen index 1), "Control $" -> 4.0 (index 4), int 1 -> 3.0, float 1.0 -> 1.0, bool True -> 0.5
        cats = table["Category"].tolist()
        self.assertEqual(len(cats), 5)
        self.assertEqual(cats[0], "1")
        self.assertIs(type(cats[0]), str)
        self.assertEqual(cats[1], "Control $")
        self.assertEqual(cats[2], 1)
        self.assertIs(type(cats[2]), int)
        self.assertEqual(cats[3], 1.0)
        self.assertIs(type(cats[3]), float)
        self.assertIs(cats[4], True)

        ax = res.figure.axes[0]
        ticks = ax.get_xticklabels()
        self.assertEqual([t.get_text() for t in ticks], ["1", "Control $", "1", "1.0", "True"])
        self.assertTrue(all(not t.get_parse_math() for t in ticks))

        keys = [g.key for g in graph_groups(ax)]
        self.assertEqual(
            keys[:5],
            [
                "pareto:cat:str:1",
                "pareto:cat:str:Control $",
                "pareto:cat:int:1",
                "pareto:cat:float:1.0",
                "pareto:cat:bool:True",
            ],
        )

    def test_ties_preserve_first_occurrence(self):
        frame = pd.DataFrame({
            "C": ["Gamma", "Alpha", "Beta", "Alpha", "Gamma", "Beta"],
            "W": [2.0, 1.0, 3.0, 2.0, 1.0, 0.0],
        })
        res = analyse(pp.METHOD, frame, {"Category": "C", "Weight": "W"})
        # All three sum to 3.0 -> must preserve first occurrence: Gamma, Alpha, Beta.
        self.assertEqual(res.tables[pp.CATEGORIES_SHEET]["Category"].tolist(), ["Gamma", "Alpha", "Beta"])

    def test_invalid_weights_raise_field_error_on_weight(self):
        cases = [
            pd.DataFrame({"C": ["A", "B"], "W": [1.0, -0.1]}),
            pd.DataFrame({"C": ["A", "B"], "W": [True, False]}),
            pd.DataFrame({"C": ["A", "B"], "W": pd.Series([True, pd.NA], dtype="boolean")}),
            pd.DataFrame({"C": ["A", "B"], "W": pd.Series([1.0, True], dtype=object)}),
            pd.DataFrame({"C": ["A", "B"], "W": ["1", "bad"]}),
            pd.DataFrame({"C": ["A", "B"], "W": ["1", "True"]}),
            pd.DataFrame({"C": ["A", "B"], "W": [1.0, np.inf]}),
            pd.DataFrame({"C": ["A", "B"], "W": [1.0, -np.inf]}),
            pd.DataFrame({"C": ["A", "B"], "W": ["1", "inf"]}),
            pd.DataFrame({"C": ["A", "B"], "W": ["1", "nan"]}),
            pd.DataFrame({"C": ["A", "B"], "W": [1 + 2j, 3 + 0j]}),
            pd.DataFrame({"C": ["A", "B"], "W": [0.0, 0.0]}),
            pd.DataFrame({"C": ["A", "B"], "W": [1e308, 1e308]}),
        ]
        for idx, frame in enumerate(cases):
            with self.subTest(case=idx):
                with self.assertRaises(FieldError) as ctx:
                    analyse(pp.METHOD, frame, {"Category": "C", "Weight": "W"})
                self.assertEqual(ctx.exception.field, pp.WEIGHT)

    def test_discarded_categories_and_weights(self):
        frame = pd.DataFrame({
            "C": ["A", None, "", "   ", "B", "A", "C"],
            "W": [2.0, 99.0, 50.0, 10.0, np.nan, 3.0, ""],
        })
        res = analyse(pp.METHOD, frame, {"Category": "C", "Weight": "W"})
        table = res.tables[pp.CATEGORIES_SHEET]
        self.assertEqual(table["Category"].tolist(), ["A"])
        self.assertEqual(table["Amount"].tolist(), [5.0])
        self.assertEqual(table["Cumulative percent"].tolist(), [100.0])
        st = res.tables[pp.SETTINGS_SHEET]["Value"]
        self.assertEqual(int(st["Observations used"]), 2)
        self.assertEqual(int(st["Rows discarded"]), 5)
        self.assertEqual(int(st["Discarded (missing category)"]), 3)
        self.assertEqual(int(st["Discarded (missing weight)"]), 2)

        # All categories missing -> Category error.
        with self.assertRaises(FieldError) as ctx:
            analyse(pp.METHOD, pd.DataFrame({"C": [None, "", "  "], "W": [1, 2, 3]}), {"Category": "C", "Weight": "W"})
        self.assertEqual(ctx.exception.field, pp.CATEGORY)

        # Present categories but all weights missing -> Weight error.
        with self.assertRaises(FieldError) as ctx:
            analyse(pp.METHOD, pd.DataFrame({"C": ["A", "B"], "W": [np.nan, None]}), {"Category": "C", "Weight": "W"})
        self.assertEqual(ctx.exception.field, pp.WEIGHT)

    def test_threshold_validation_and_disable(self):
        frame = pd.read_csv(FIXTURE)
        for bad in (0, 0.0, -5, 100, 100.0, 120, True, False, "abc", "0", "100", np.nan, np.inf):
            with self.subTest(bad=bad):
                with self.assertRaises(FieldError) as ctx:
                    _run(frame, Weight="Peso", Threshold=bad)
                self.assertEqual(ctx.exception.field, pp.THRESHOLD)

        # Distinct columns error.
        with self.assertRaises(FieldError) as ctx:
            _run(frame, Weight="Categoria")
        self.assertEqual(ctx.exception.field, pp.WEIGHT)

        # Disabled threshold has no threshold line group and only 1 line (cumulative) on right axis.
        res_off = _run(frame, Weight="Peso", Threshold="")
        keys_off = [g.key for g in graph_groups(res_off.figure.axes[0])]
        self.assertNotIn("pareto:line:threshold", keys_off)
        self.assertEqual(len(res_off.figure.axes[1].lines), 1)

        # Enabled threshold adds threshold line group and highlights the reaching category.
        res_on = _run(frame, Weight="Peso", Threshold=50)
        keys_on = [g.key for g in graph_groups(res_on.figure.axes[0])]
        self.assertIn("pareto:line:threshold", keys_on)
        self.assertEqual(res_on.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"], "B")

    def test_threshold_just_above_a_cumulative_percentage_chooses_the_next_bar(self):
        frame = pd.DataFrame({"Type": ["A", "A", "A", "A", "B"]})
        result = analyse(pp.METHOD, frame, {pp.CATEGORY: "Type", pp.THRESHOLD: np.nextafter(80.0, np.inf)})
        self.assertEqual(result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"], "B")

    def test_extreme_finite_weights_render_with_the_original_amounts_in_the_report(self):
        for weights, exponent in (([1.7e308, 1e305], 308), ([3e-320, 1e-320], -320)):
            with self.subTest(weights=weights):
                frame = pd.DataFrame({"Type": ["A", "B"], "W": weights})
                result = analyse(pp.METHOD, frame, {pp.CATEGORY: "Type", pp.WEIGHT: "W"})
                table = result.tables[pp.CATEGORIES_SHEET]
                self.assertEqual(table["Amount"].tolist(), weights)
                self.assertEqual(float(table["Cumulative percent"].iloc[-1]), 100.0)
                axes = result.figure.axes[0]
                self.assertIn(f"×10^{exponent}", axes.get_ylabel())
                self.assertEqual(axes.get_ylim()[0], 0.0)
                self.assertGreater(axes.patches[0].get_height(), 1.0)
                output = BytesIO()
                result.figure.savefig(output, format="png")
                self.assertGreater(len(output.getvalue()), 1000)

    def test_worksheet_exclusions_respected(self):
        raw = pd.read_csv(FIXTURE)
        ds = Dataset(raw)
        # Exclude row 0's Peso (B, 4) -> B drops from 6 to 2; A=3, C=3, B=2, Zero=0.
        ds.excluded.add((0, 1))
        frame = ds.frame(mask_excluded=True)
        res = _run(frame, Weight="Peso", Threshold=80)
        table = res.tables[pp.CATEGORIES_SHEET]
        self.assertEqual(table["Category"].tolist(), ["A", "C", "B", "Zero"])
        self.assertEqual(table["Amount"].tolist(), [3.0, 3.0, 2.0, 0.0])
        st = res.tables[pp.SETTINGS_SHEET]["Value"]
        self.assertEqual(int(st["Discarded (missing weight)"]), 1)
        self.assertEqual(int(st["Rows discarded"]), 1)

        # Also exclude row 1's Categoria (A) -> C=3, B=2, Zero=0.
        ds.excluded.add((1, 0))
        res2 = _run(ds.frame(mask_excluded=True), Weight="Peso", Threshold=80)
        self.assertEqual(res2.tables[pp.CATEGORIES_SHEET]["Category"].tolist(), ["C", "B", "Zero"])
        st2 = res2.tables[pp.SETTINGS_SHEET]["Value"]
        self.assertEqual(int(st2["Discarded (missing category)"]), 1)
        self.assertEqual(int(st2["Discarded (missing weight)"]), 1)

    def test_stable_order_and_style_follows_category_on_recalculation(self):
        frame = pd.read_csv(FIXTURE)
        res1 = _run(frame, Weight="Peso", Threshold=80)
        res2 = _run(frame, Weight="Peso", Threshold=80)
        pd.testing.assert_frame_equal(res1.tables[pp.CATEGORIES_SHEET], res2.tables[pp.CATEGORIES_SHEET])

        # Custom color on category "A" stays attached to "A" even when "A" moves to rank 0.
        style = {"groups": {"pareto:cat:str:A": {"color": "#2b8a73"}}}
        validate_graph_style(res1.figure.axes[0], style)
        apply_style(res1.figure, style)

        edited = frame.copy()
        edited.loc[1, "Peso"] = 10  # A jumps from 3 to 10 (now #1).
        res_edited = _run(edited, Weight="Peso", Threshold=80)
        self.assertEqual(res_edited.tables[pp.CATEGORIES_SHEET]["Category"].tolist(), ["A", "B", "C", "Zero"])
        apply_style(res_edited.figure, style)

        grp_a = graph_groups(res_edited.figure.axes[0])[0]
        self.assertEqual(grp_a.key, "pareto:cat:str:A")
        patch_a = grp_a.artists[0][0]
        self.assertIsInstance(patch_a, Rectangle)
        fc = patch_a.get_facecolor()
        self.assertAlmostEqual(float(fc[0]), 0x2B / 255.0, places=2)
        self.assertAlmostEqual(float(fc[1]), 0x8A / 255.0, places=2)
        self.assertAlmostEqual(float(fc[2]), 0x73 / 255.0, places=2)
        self.assertEqual(res_edited.figure.axes[1].get_ylim(), (0.0, 100.0))

    def test_benchmark_50k_rows_30_categories_and_artist_budget(self):
        rng = np.random.default_rng(42)
        n_rows = 50_000
        n_cats = 30
        cat_names = [f"Cat_{i:02d}" for i in range(n_cats)]
        probs = np.geomspace(1.0, 0.05, n_cats)
        probs /= probs.sum()
        frame = pd.DataFrame({
            "Categoria": rng.choice(cat_names, size=n_rows, p=probs),
            "Peso": rng.uniform(0.5, 5.0, size=n_rows),
        })
        t0 = time.perf_counter()
        res = _run(frame, Weight="Peso", Threshold=80)
        elapsed = time.perf_counter() - t0

        table = res.tables[pp.CATEGORIES_SHEET]
        self.assertEqual(len(table), n_cats)
        self.assertEqual(table["Cumulative percent"].iat[-1], 100.0)
        # Must use one/few artists per category, never per observation.
        ax0, ax1 = res.figure.axes
        self.assertEqual(len(ax0.patches), n_cats)
        self.assertLessEqual(len(ax1.lines), 4)
        self.assertLess(elapsed, 5.0, f"50k x 30 benchmark too slow: {elapsed:.3f}s")

    def test_parts_of_whole_unchanged(self):
        frame = pd.DataFrame({"Part": ["Alpha", "Beta", "Gamma"], "Val": [50.0, 30.0, 20.0]})
        for style in ("Donut", "Pie", "Vertical slices", "Dot plot"):
            res = analyse("Parts of whole graph", frame, {"Values": "Val", "Row titles": "Part", "Graph style": style})
            comp = res.tables["Composition"]
            self.assertEqual(comp["Category"].tolist(), ["Alpha", "Beta", "Gamma"])
            self.assertEqual(comp["Percent"].tolist(), [50.0, 30.0, 20.0])
            self.assertEqual(float(res.tables["Total"]["Value"]["Total"]), 100.0)
            self.assertEqual(len(res.figure.axes), 1)


if __name__ == "__main__":
    unittest.main()
