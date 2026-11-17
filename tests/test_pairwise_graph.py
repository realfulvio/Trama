"""0.56 Pairwise comparisons on graphs: source adapter, bracket lanes and labels.

cases.json and expected.json in data/pairwise_graph are the package fixtures, produced by its independent oracle.
The other tests use real ANOVA, Dunn and paired t-test results to check which column is read.
"""
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi import pairwise_graph as pg
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "pairwise_graph"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def endpoint(label):
    if hasattr(label, "item"):
        label = label.item()
    return f"category:{type(label).__name__}:{label}"


class PlanTests(unittest.TestCase):
    def assertNested(self, actual, expected, path=""):
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys(), path)
            for key, value in expected.items():
                self.assertNested(actual[key], value, f"{path}/{key}")
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), path)
            for index, (value, wanted) in enumerate(zip(actual, expected)):
                self.assertNested(value, wanted, f"{path}/{index}")
        elif type(expected) in (int, float):
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10), (path, actual, expected))
        else:
            self.assertEqual(actual, expected, path)

    def test_package_cases(self):
        for name, case in CASES.items():
            with self.subTest(name):
                brackets, top, warning = pg.plan_brackets(
                    case["anchors"], case["comparisons"], case["settings"], case["y_limits"],
                    yscale=case.get("yscale", "linear"), fixed_y=case.get("fixed_y", False))
                self.assertNested({"brackets": brackets, "top": top, "warning": bool(warning)}, EXPECTED[name], name)

    def test_lanes_recompact_when_a_pair_is_dropped(self):
        case = CASES["lanes-and-star-boundaries"]
        pairs = [["A", "D"], ["C", "D"], ["A", "B"]]
        brackets, _, _ = pg.plan_brackets(case["anchors"], case["comparisons"],
                                          {"label": "stars", "cutoff": None, "pairs": pairs}, (0., 10.))
        self.assertEqual([(b["left"], b["right"], b["lane"]) for b in brackets],
                         [("A", "B", 0), ("C", "D", 0), ("A", "D", 1)])

    def test_numpy_inputs_and_unsupported_scale(self):
        anchors = {"a": {"x": np.int64(0), "top": np.float64(1.)}, "b": {"x": np.int64(1), "top": np.float64(2.)}}
        rows = [{"left": "a", "right": "b", "p": np.float64(.02)}]
        settings = {"label": "stars", "cutoff": None, "pairs": None}
        brackets, top, warning = pg.plan_brackets(anchors, rows, settings, (np.float64(0.), np.float64(4.)))
        self.assertEqual(len(brackets), 1)
        self.assertIsNone(warning)
        self.assertAlmostEqual(brackets[0]["y"], 2 + .08 * 4)
        self.assertEqual(pg.plan_brackets(anchors, rows, settings, (0., 4.), yscale="logit")[0], [])
        self.assertIn("linear or logarithmic", pg.plan_brackets(anchors, rows, settings, (0., 4.), yscale="logit")[2])
        # A huge log height is not representable and the pair stays out of the plan.
        far = {"a": {"x": 0, "top": 1e300}, "b": {"x": 1, "top": 1e307}}
        self.assertEqual(pg.plan_brackets(far, rows, settings, (1., 1e308), yscale="log")[0], [])

    def test_labels(self):
        self.assertEqual([pg.p_label(p, "stars") for p in (.05, .0500001, .01, .001, .0001, 0.)],
                         ["*", "ns", "**", "***", "****", "****"])
        self.assertEqual([pg.p_label(p, "p") for p in (0., .0001, .00009999, .123456)],
                         ["p < 0.0001", "p = 0.0001", "p < 0.0001", "p = 0.1235"])


class SourceTests(unittest.TestCase):
    long = pd.read_csv(DATA / "long.csv")

    def test_one_way_reads_adjusted_p(self):
        options = {"Response": "Response", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Holm"}
        tables = analyse("One-way ANOVA", self.long, options).tables
        sheet = tables["Multiple comparisons"]
        rows = pg.comparison_rows("One-way ANOVA", tables, options, endpoint)
        self.assertEqual([row["p"] for row in rows], sheet["Adjusted p"].tolist())
        self.assertNotEqual([row["p"] for row in rows], sheet["p"].tolist())
        self.assertEqual(rows[0]["left"], "category:str:A")
        fdr = {**options, "Post-hoc": pg.FDR}
        self.assertEqual(pg.comparison_rows("One-way ANOVA", analyse("One-way ANOVA", self.long, fdr).tables,
                                            fdr, endpoint), [])
        # General ANOVA sheets are never read.
        self.assertEqual(pg.comparison_rows("One-way ANOVA", {"ANOVA": sheet}, options, endpoint), [])

    def test_dunn_reads_adjusted_p_even_when_uncorrected(self):
        options = {"Response": "Response", "Group": "Group", "Dunn comparisons": "All pairs",
                   "Dunn adjustment": "Uncorrected"}
        tables = analyse("Kruskal–Wallis", self.long, options).tables
        rows = pg.comparison_rows("Kruskal–Wallis", tables, options, endpoint)
        self.assertEqual([row["p"] for row in rows], tables["Dunn comparisons"]["Adjusted p"].tolist())
        self.assertEqual(len(rows), 6)

    def test_paired_columns_uses_options(self):
        frame = pd.read_csv(DATA / "paired.csv")
        options = {"First": "Before", "Second": "After"}
        tables = analyse("Paired t-test (columns)", frame, options).tables
        rows = pg.comparison_rows("Paired t-test (columns)", tables, options, lambda name: f"column:{name}")
        self.assertEqual(rows, [{"left": "column:Before", "right": "column:After",
                                 "p": float(tables["t-test"].at["p", "Value"])}])
        self.assertEqual(pg.comparison_rows("Paired t-test (columns)", tables, {"First": "Before", "Second": "Before"},
                                            str), [])

    def test_typed_endpoints_and_invalid_values(self):
        records = pd.DataFrame([
            {"First": np.int64(1), "Second": "1", "Adjusted p": .24, "p": .001},
            {"First": "1", "Second": "B", "Adjusted p": None, "p": .01},
            {"First": "B", "Second": 1, "Adjusted p": 1.01, "p": .03},
            {"First": "B", "Second": "C", "Adjusted p": True, "p": .03},
            {"First": "B", "Second": "C", "Adjusted p": 0., "p": 0.},
        ])
        rows = pg.comparison_rows("One-way ANOVA", {"Multiple comparisons": records}, {"Post-hoc": "Tukey"}, endpoint)
        self.assertEqual(rows, [{"left": "category:int:1", "right": "category:str:1", "p": .24},
                                {"left": "category:str:B", "right": "category:str:C", "p": 0.}])
        self.assertEqual(pg.comparison_rows("Mann–Whitney", {"Multiple comparisons": records}, {}, endpoint), [])


if __name__ == "__main__":
    unittest.main()


class RenderTests(unittest.TestCase):
    long = pd.read_csv(DATA / "long.csv")
    box_options = {"Input": "Single response", "Response": "Response", "Group": "Group", "Style": "Box"}
    anova_options = {"Response": "Response", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Tukey"}

    def graph(self, style=None, settings=None, options=None):
        from analisi.presentation import apply_style

        result = analyse("Box / violin plot", self.long, options or self.box_options)
        if style:
            apply_style(result.figure, style)
        tables = analyse("One-way ANOVA", self.long, self.anova_options).tables
        rows = pg.comparison_rows("One-way ANOVA", tables, self.anova_options, pg.endpoint_resolver("Box / violin plot"))
        record = pg.section_record(0, "One-way ANOVA", **(settings or {}))
        parsed, problem = pg.read_section({pg.SECTION: record})
        self.assertIsNone(problem)
        pg.attach(result.figure, rows, parsed)
        return result.figure

    @staticmethod
    def texts(figure):
        return [artist.get_text() for artist in figure.artists if str(artist.get_gid()).startswith("pairwise:label")]

    def test_brackets_follow_style_and_visibility_without_creep(self):
        from analisi.presentation import apply_style, graph_series

        figure = self.graph()
        axes = figure.axes[0]
        self.assertEqual(len(self.texts(figure)), 6)
        self.assertFalse(axes.texts)
        self.assertFalse(any(series.artist in figure.artists for series in graph_series(axes)))
        self.assertEqual(axes.get_legend_handles_labels(), ([], []))
        top = axes.get_ylim()[1]
        for _ in range(3):
            apply_style(figure, {"title": "Again"})
        self.assertEqual(axes.get_ylim()[1], top)
        self.assertEqual(len(figure.artists), 12)
        # Hiding D in the Inspector removes its three pairs and lowers the stack.
        apply_style(figure, {"groups": {"box:category:str:D": {"visible": False}}})
        self.assertEqual(len(self.texts(figure)), 3)
        self.assertLess(axes.get_ylim()[1], top)
        apply_style(figure, {})
        self.assertEqual(len(self.texts(figure)), 6)
        self.assertEqual(axes.get_ylim()[1], top)

    def test_fixed_limits_warn_and_log_axis(self):
        from analisi.presentation import apply_style

        figure = self.graph(settings={"label": "P value"})
        apply_style(figure, {"axis": {"y": {"min": -2., "max": 7.5}}})
        self.assertEqual(figure.axes[0].get_ylim(), (-2., 7.5))
        self.assertLess(len(self.texts(figure)), 6)
        self.assertIn("fixed Y maximum", pg.pairwise_warning(figure))
        positive = self.long.assign(Response=self.long["Response"] + 3)
        result = analyse("Box / violin plot", positive, self.box_options)
        apply_style(result.figure, {"yscale": "log"})
        rows = [{"left": "category:str:A", "right": "category:str:D", "p": .002}]
        pg.attach(result.figure, rows, {"label": "stars", "cutoff": None, "pairs": None, "color": "#303640"})
        self.assertEqual(self.texts(result.figure), ["**"])
        self.assertIsNone(pg.pairwise_warning(result.figure))

    def test_cutoff_pairs_and_svg_once(self):
        from io import BytesIO

        figure = self.graph(settings={"filtering": pg.AT_OR_BELOW, "cutoff": .001})
        drawn = pg.drawn_brackets(figure)
        tables = analyse("One-way ANOVA", self.long, self.anova_options).tables
        wanted = (tables["Multiple comparisons"]["Adjusted p"] <= .001).sum()
        self.assertEqual(len(drawn), wanted)
        figure = self.graph(settings={"selection": pg.SELECTED, "pairs": [["category:str:D", "category:str:A"]],
                                      "color": "#aa0000"})
        self.assertEqual([(b["left"], b["right"]) for b in pg.drawn_brackets(figure)],
                         [("category:str:A", "category:str:D")])
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().decode()
        self.assertEqual(svg.count('id="pairwise:bracket:1"'), 1)
        self.assertNotIn('id="pairwise:bracket:2"', svg)

    def test_section_validation_and_legacy(self):
        self.assertEqual(pg.read_section({}), (None, None))
        for broken in ([], {"Source slot": "0", "Source method": "One-way ANOVA"},
                       {"Source slot": 0, "Source method": "t-test"},
                       {"Source slot": 0, "Source method": "One-way ANOVA", "Cutoff": 0},
                       {"Source slot": 0, "Source method": "One-way ANOVA", "Pairs": [["a", "a"]]},
                       {"Source slot": 0, "Source method": "One-way ANOVA", "Color": "not a color"},
                       {"Source slot": 0, "Source method": "One-way ANOVA", "Extra": 1}):
            settings, problem = pg.read_section({pg.SECTION: broken})
            self.assertIsNone(settings)
            self.assertIn("not valid", problem)
        legacy = analyse("Box / violin plot", self.long, self.box_options)
        self.assertFalse(legacy.figure.artists)
        self.assertFalse(legacy.figure.axes[0].texts)

    def test_sources_and_graphs(self):
        box = self.box_options
        self.assertIsNone(pg.graph_problem("Box / violin plot", box))
        self.assertIsNotNone(pg.graph_problem("Box / violin plot", {**box, "Input": "Separate columns"}))
        self.assertIsNotNone(pg.graph_problem("Grouped graph", {}))
        self.assertIsNotNone(pg.graph_problem("Column graph", {"Graph style": "Before and after"}))
        self.assertIsNone(pg.source_problem("Box / violin plot", box, "One-way ANOVA", self.anova_options))
        self.assertIn("same Response", pg.source_problem("Box / violin plot", {**box, "Group": "Other"},
                                                         "One-way ANOVA", self.anova_options))
        self.assertIn("FDR", pg.source_problem("Box / violin plot", box, "One-way ANOVA",
                                               {**self.anova_options, "Post-hoc": pg.FDR}))
        self.assertIn("Dunn", pg.source_problem("Box / violin plot", box, "Kruskal–Wallis",
                                                {"Response": "Response", "Group": "Group", "Dunn comparisons": "None"}))
        column = {"Variables": ["Before", "After"], "Graph style": "Bars"}
        self.assertIsNone(pg.source_problem("Column graph", column, "Paired t-test (columns)",
                                            {"First": "After", "Second": "Before"}))
        self.assertIsNotNone(pg.source_problem("Column graph", column, "Paired t-test (columns)",
                                               {"First": "After", "Second": "Reference"}))

    def test_column_anchors_use_highest_drawn_element(self):
        frame = pd.read_csv(DATA / "paired.csv")
        for style, overlay, expected in (("Bars", False, None), ("Individual points", False, "max"),
                                         ("Floating range", False, "max"), ("Center and interval", True, "max")):
            options = {"Variables": ["Before", "After"], "Graph style": style, "Interval": "SD",
                       "Overlay observations": overlay}
            if style == "Floating range":
                options.pop("Interval")
            result = analyse("Column graph", frame, options)
            anchors = result.figure.axes[0]._tramastat_pairwise_anchors
            self.assertEqual(list(anchors), ["column:Before", "column:After"])
            data = result.tables["Graph data"].set_index("Group")
            for name in ("Before", "After"):
                top = anchors[f"column:{name}"]["top"]
                if expected == "max":
                    self.assertGreaterEqual(top, frame[name].max())
                else:
                    self.assertAlmostEqual(top, data.at[name, "Upper"])
        paired = analyse("Column graph", frame, {"Variables": ["Before", "After"], "Graph style": "Before and after"})
        self.assertFalse(hasattr(paired.figure.axes[0], "_tramastat_pairwise_anchors"))


class TypedGroupTests(unittest.TestCase):
    def test_numeric_and_text_homonyms_stay_apart(self):
        frame = pd.DataFrame({"Group": [1, 1, 1, 1, "1", "1", "1", "1", "B", "B", "B", "B"],
                              "Response": [1., 1.2, .9, 1.1, 3., 3.1, 2.8, 3.3, 6., 6.2, 5.9, 6.1]})
        box = analyse("Box / violin plot", frame, {"Input": "Single response", "Response": "Response", "Group": "Group"})
        anchors = box.figure.axes[0]._tramastat_pairwise_anchors
        self.assertEqual(list(anchors), ["category:int:1", "category:str:1", "category:str:B"])
        options = {"Response": "Response", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Bonferroni"}
        tables = analyse("One-way ANOVA", frame, options).tables
        rows = pg.comparison_rows("One-way ANOVA", tables, options, pg.endpoint_resolver("Box / violin plot"))
        self.assertEqual({frozenset((row["left"], row["right"])) for row in rows},
                         {frozenset(pair) for pair in (("category:int:1", "category:str:1"),
                                                       ("category:int:1", "category:str:B"),
                                                       ("category:str:1", "category:str:B"))})
        pg.attach(box.figure, rows, {"label": "stars", "cutoff": None, "pairs": None, "color": "#303640"})
        self.assertEqual(len(pg.drawn_brackets(box.figure)), 3)
