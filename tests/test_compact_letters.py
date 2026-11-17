"""0.57 Compact letter display: insert–absorb letters and their placement.

cases.json and expected.json in data/compact_letters are the package fixtures, produced by its independent oracle
(an exhaustive enumeration of maximal cliques on small cases).
"""
from itertools import combinations
import json
import math
import random
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
import pandas as pd

from analisi import compact_letters as cl
from analisi import pairwise_graph as pg
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "compact_letters"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def brute_force(groups, matrix, alpha):
    """Maximal cliques of the non-significance graph by enumeration, as sorted index tuples."""
    found = []
    for size in range(len(groups), 0, -1):
        for clique in combinations(range(len(groups)), size):
            if all(matrix[frozenset((groups[a], groups[b]))] > alpha for a, b in combinations(clique, 2)):
                if not any(set(clique) <= set(prior) for prior in found):
                    found.append(clique)
    return sorted(found)


class LetterTests(unittest.TestCase):
    def assertNested(self, actual, expected, path=""):
        if isinstance(expected, dict):
            self.assertEqual(list(actual), list(expected), path)
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

    def test_package_letters(self):
        for name, case in CASES["letters"].items():
            with self.subTest(name):
                self.assertNested(cl.compact_letters(**case), EXPECTED["letters"][name])

    def test_package_invalid(self):
        for name, case in CASES["invalid"].items():
            with self.subTest(name), self.assertRaises(ValueError) as caught:
                cl.compact_letters(**case)
            self.assertTrue(str(caught.exception))

    def test_package_layout(self):
        for name, case in CASES["layout"].items():
            with self.subTest(name):
                labels, top, warning = cl.plan_letters(**case)
                self.assertNested({"labels": labels, "top": top, "warning": bool(warning)}, EXPECTED["layout"][name])

    def test_nontransitive_case(self):
        rows = [{"left": "A", "right": "B", "p": .4}, {"left": "A", "right": "C", "p": .01},
                {"left": "B", "right": "C", "p": .2}]
        self.assertEqual(cl.compact_letters(["A", "B", "C"], rows), {"A": ["a"], "B": ["a", "b"], "C": ["b"]})
        self.assertEqual(cl.compact_letters(["A", "B", "C"], rows, identifiers="upper"),
                         {"A": ["A"], "B": ["A", "B"], "C": ["B"]})

    def test_random_matrices_match_enumeration(self):
        rng = random.Random(57)
        for _ in range(400):
            groups = [f"G{i}" for i in range(rng.randint(2, 8))]
            density = rng.random()
            matrix = {frozenset(pair): (rng.random() * .05 if rng.random() < density else .05 + rng.random() * .9)
                      for pair in combinations(groups, 2)}
            rows = [{"left": a, "right": b, "p": p} for (a, b), p in
                    ((tuple(sorted(pair)), p) for pair, p in matrix.items())]
            rng.shuffle(rows)
            letters = cl.compact_letters(groups, rows)
            cliques = brute_force(groups, matrix, .05)
            self.assertEqual(sorted({s for values in letters.values() for s in values},
                                    key=lambda s: (len(s), s)), [cl.symbol(i) for i in range(len(cliques))])
            for position, clique in enumerate(cliques):
                self.assertEqual({groups[i] for i in clique},
                                 {g for g, values in letters.items() if cl.symbol(position) in values})

    def test_inputs(self):
        rows = [{"left": "A", "right": "B", "p": np.float64(.3)}, {"left": "A", "right": "B", "p": float("nan")}]
        self.assertEqual(cl.compact_letters(("A", "B"), rows, alpha=np.float64(.1)), {"A": ["a"], "B": ["a"]})
        for alpha in (0, 1, float("nan"), True, "0.05", None):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                cl.compact_letters(["A", "B"], rows, alpha=alpha)
        with self.assertRaises(ValueError):
            cl.compact_letters("AB", rows)
        with self.assertRaisesRegex(ValueError, "every pair"):
            cl.compact_letters(["A", "B", "C"], rows)
        # Only invalid values for a pair make it missing.
        with self.assertRaisesRegex(ValueError, "missing"):
            cl.compact_letters(["A", "B"], [{"left": "A", "right": "B", "p": True}])

    def test_working_set_budget(self):
        # A perfect matching of significant pairs doubles the working sets at each step: 2^15 > 4096.
        groups = [f"G{i:02d}" for i in range(30)]
        significant = {frozenset((groups[2 * i], groups[2 * i + 1])) for i in range(15)}
        rows = [{"left": a, "right": b, "p": .001 if frozenset((a, b)) in significant else .5}
                for a, b in combinations(groups, 2)]
        with self.assertRaisesRegex(ValueError, "working sets|letters"):
            cl.compact_letters(groups, rows)

    def test_symbols(self):
        self.assertEqual([cl.symbol(i) for i in (0, 25, 26, 27, 51, 52, 701, 702)],
                         ["a", "z", "aa", "ab", "az", "ba", "zz", "aaa"])
        self.assertEqual(cl.symbol(26, "upper"), "AA")
        self.assertEqual(cl.symbol(9, "numbers"), "10")

    def test_layout_rules(self):
        anchors = {"A": {"x": 0, "top": 2.}, "B": {"x": 1, "top": 3.}}
        letters = {"A": ["a"], "B": ["a", "b"]}
        labels, top, warning = cl.plan_letters(anchors, letters, (0, 10), yscale="log")
        self.assertEqual((labels, top), ([], 10))
        self.assertIn("logarithmic", warning)
        labels, top, warning = cl.plan_letters({"B": anchors["B"]}, letters, (0, 10))
        self.assertEqual([label["key"] for label in labels], ["B"])
        self.assertTrue(warning)
        self.assertEqual(cl.plan_letters(anchors, {}, (0, 10)), ([], 10, None))
        with self.assertRaises(ValueError):
            cl.plan_letters(anchors, letters, (0, 10), placement="free")


class RealSourceTests(unittest.TestCase):
    def test_sources_give_complete_matrices(self):
        long = pd.read_csv(DATA / "long.csv")
        groups = [f"category:str:{name}" for name in long["Group"].unique()]
        endpoint = lambda label: f"category:str:{label}"
        for method, settings in (("One-way ANOVA", {"Method": "Ordinary", "Post-hoc": "Tukey"}),
                                 ("One-way ANOVA", {"Method": "Ordinary", "Post-hoc": "Holm"}),
                                 ("Kruskal–Wallis", {"Dunn comparisons": "All pairs"})):
            options = {"Response": "Response", "Group": "Group", **settings}
            rows = pg.comparison_rows(method, analyse(method, long, options).tables, options, endpoint)
            letters = cl.compact_letters(groups, rows)
            self.assertEqual(list(letters), groups)
        options = {"Response": "Response", "Group": "Group", "Dunn comparisons": "Versus control",
                   "Control group": "A"}
        rows = pg.comparison_rows("Kruskal–Wallis", analyse("Kruskal–Wallis", long, options).tables, options, endpoint)
        with self.assertRaisesRegex(ValueError, "every pair"):
            cl.compact_letters(groups, rows)
        # With only A and C visible the control comparison is complete.
        self.assertEqual(len(cl.compact_letters(groups[::2], rows)), 2)


class GraphTests(unittest.TestCase):
    """Letters on real box and column graphs: drawing, report, visibility, axes and recipe."""

    @classmethod
    def setUpClass(cls):
        import matplotlib

        matplotlib.use("Agg")
        cls.long = pd.read_csv(DATA / "long.csv")
        cls.box = {"Input": "Single response", "Response": "Response", "Group": "Group", "Style": "Box"}
        cls.source = {"Response": "Response", "Group": "Group", "Method": "Ordinary", "Post-hoc": "Tukey"}
        tables = analyse("One-way ANOVA", cls.long, cls.source).tables
        cls.rows = pg.comparison_rows("One-way ANOVA", tables, cls.source, pg.endpoint_resolver("Box / violin plot"))

    def graph(self, rows=None, frame=None, **record):
        result = analyse("Box / violin plot", self.long if frame is None else frame, self.box)
        settings, problem = pg.read_section({pg.SECTION: pg.section_record(0, "One-way ANOVA", display=pg.LETTERS,
                                                                            **record)})
        self.assertIsNone(problem)
        pg.attach(result.figure, self.rows if rows is None else rows, settings)
        pg.sync_letters_table(result)
        return result

    @staticmethod
    def texts(figure):
        return [artist.get_text() for artist in figure.artists if str(artist.get_gid()).startswith("pairwise:letters")]

    def test_letters_table_style_and_visibility(self):
        from analisi.presentation import apply_style, graph_series

        result = self.graph()
        figure, axes = result.figure, result.figure.axes[0]
        wanted = cl.compact_letters([f"category:str:{g}" for g in "ABCD"], self.rows)
        self.assertEqual(self.texts(figure), [" ".join(wanted[key]) for key in wanted])
        self.assertFalse(axes.texts)
        self.assertFalse(any(series.artist in figure.artists for series in graph_series(axes)))
        self.assertEqual(axes.get_legend_handles_labels(), ([], []))
        table = result.tables[pg.LETTERS_SHEET]
        self.assertEqual(list(table.columns), ["Group", "Group key", "Letters", "Alpha"])
        self.assertEqual(table["Group"].tolist(), list("ABCD"))
        self.assertEqual(list(result.tables), ["Group summary", "Settings", pg.LETTERS_SHEET])
        top = axes.get_ylim()[1]
        for _ in range(3):
            apply_style(figure, {"title": "Again"})
        self.assertEqual(axes.get_ylim()[1], top)
        self.assertEqual(len(figure.artists), 4)
        apply_style(figure, {"groups": {"box:category:str:D": {"visible": False}}})
        self.assertEqual(len(self.texts(figure)), 3)
        self.assertEqual(pg.letters_table(figure)["Group"].tolist(), list("ABC"))
        # The stored report changes only when the caller syncs it (Inspector Apply), not on a preview.
        self.assertEqual(len(result.tables[pg.LETTERS_SHEET]), 4)
        apply_style(figure, {})
        self.assertEqual(len(self.texts(figure)), 4)
        self.assertEqual(axes.get_ylim()[1], top)

    def test_alpha_identifiers_size_and_aligned(self):
        result = self.graph(alpha=1e-9, identifiers="Uppercase", placement="Aligned", size=14)
        letters = cl.compact_letters([f"category:str:{g}" for g in "ABCD"], self.rows, alpha=1e-9, identifiers="upper")
        self.assertEqual(self.texts(result.figure), [" ".join(v) for v in letters.values()])
        artists = [a for a in result.figure.artists]
        self.assertEqual({a.get_position()[1] for a in artists}.__len__(), 1)
        self.assertEqual({a.get_fontsize() for a in artists}, {14})
        self.assertTrue((result.tables[pg.LETTERS_SHEET]["Alpha"] == 1e-9).all())

    def test_incomplete_matrix_shows_base_graph_with_warning(self):
        result = self.graph(rows=self.rows[:5])
        self.assertEqual(self.texts(result.figure), [])
        self.assertIn("every pair", pg.pairwise_warning(result.figure))
        self.assertNotIn(pg.LETTERS_SHEET, result.tables)
        base = analyse("Box / violin plot", self.long, self.box).figure.axes[0].get_ylim()
        np.testing.assert_allclose(result.figure.axes[0].get_ylim(), base)

    def test_fixed_limits_keep_report_and_log_axis(self):
        from analisi.presentation import apply_style

        result = self.graph()
        apply_style(result.figure, {"axis": {"y": {"min": -2., "max": 6.4}}})
        self.assertEqual(result.figure.axes[0].get_ylim(), (-2., 6.4))
        self.assertLess(len(self.texts(result.figure)), 4)
        self.assertIn("fixed Y maximum", pg.pairwise_warning(result.figure))
        self.assertEqual(len(pg.letters_table(result.figure)), 4)
        positive = self.long.assign(Response=self.long["Response"] + 3)
        result = self.graph(frame=positive)
        apply_style(result.figure, {"yscale": "log"})
        self.assertEqual(len(self.texts(result.figure)), 4)
        self.assertIsNone(pg.pairwise_warning(result.figure))

    def test_svg_once_and_overlap_warning(self):
        from io import BytesIO

        result = self.graph()
        buffer = BytesIO()
        result.figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().decode()
        self.assertTrue(all(svg.count(f'id="pairwise:letters:{n}"') == 1 for n in range(1, 5)))
        long = "a b c d e f g h i j k l"
        rows = [{"left": "category:str:A", "right": "category:str:B", "p": .5}]
        frame = self.long[self.long["Group"].isin(["A", "B"])]
        result = analyse("Box / violin plot", frame, self.box)
        result.figure.set_size_inches(2, 3)
        settings, _ = pg.read_section({pg.SECTION: pg.section_record(0, "One-way ANOVA", display=pg.LETTERS,
                                                                      size=18)})
        with unittest.mock.patch.object(cl, "compact_letters", return_value={
                "category:str:A": long.split(), "category:str:B": long.split()}):
            pg.attach(result.figure, rows, settings)
        self.assertIn("overlap", pg.pairwise_warning(result.figure))

    def test_section_fields(self):
        legacy = {"Source slot": 0, "Source method": "One-way ANOVA", "Selection": "All", "Pairs": [],
                  "Label": "Stars", "Filter": "All", "Cutoff": .05, "Color": "#303640"}
        settings, problem = pg.read_section({pg.SECTION: legacy})
        self.assertIsNone(problem)
        self.assertEqual((settings["display"], settings["alpha"], settings["identifiers"], settings["size"]),
                         ("brackets", .05, "lower", 10))
        for field, value in (("Display", "Letters"), ("Alpha", 1), ("Alpha", 0), ("Alpha", True),
                             ("Identifiers", "Roman"), ("Letter placement", "Free"), ("Letter size", 7),
                             ("Letter size", 19), ("Letter size", "10")):
            with self.subTest(field=field, value=value):
                self.assertIsNone(pg.read_section({pg.SECTION: {**legacy, field: value}})[0])
        record = pg.section_record(0, "One-way ANOVA", selection=pg.SELECTED, pairs=[("a", "b")], display=pg.LETTERS)
        self.assertEqual(set(record), pg.FIELDS)
        self.assertEqual(record["Pairs"], [["a", "b"]])
        settings, _ = pg.read_section({pg.SECTION: {**record, "Display": pg.BRACKETS}})
        self.assertEqual(settings["pairs"], [("a", "b")])

    def test_brackets_unchanged_by_letter_fields(self):
        result = analyse("Box / violin plot", self.long, self.box)
        legacy = {"Source slot": 0, "Source method": "One-way ANOVA", "Selection": "All", "Pairs": [],
                  "Label": "Stars", "Filter": "All", "Cutoff": .05, "Color": "#303640"}
        settings, _ = pg.read_section({pg.SECTION: legacy})
        pg.attach(result.figure, self.rows, settings)
        before = (pg.drawn_brackets(result.figure), result.figure.axes[0].get_ylim())
        result = analyse("Box / violin plot", self.long, self.box)
        settings, _ = pg.read_section({pg.SECTION: {**legacy, "Display": pg.BRACKETS, "Alpha": .2}})
        pg.attach(result.figure, self.rows, settings)
        self.assertEqual((pg.drawn_brackets(result.figure), result.figure.axes[0].get_ylim()), before)
        self.assertIsNone(pg.letters_table(result.figure))

    def test_paired_column_graph(self):
        from analisi.category_graphs import COLUMN_GRAPH

        wide = pd.read_csv(DATA / "paired.csv")
        options = {"First": "Before", "Second": "After"}
        tables = analyse("Paired t-test (columns)", wide, options).tables
        rows = pg.comparison_rows("Paired t-test (columns)", tables, options, pg.endpoint_resolver(COLUMN_GRAPH))
        settings, _ = pg.read_section({pg.SECTION: pg.section_record(0, "Paired t-test (columns)",
                                                                      display=pg.LETTERS)})
        graph = {"Variables": ["Before", "After"], "Graph style": "Bars", "Interval": "SEM"}
        result = analyse(COLUMN_GRAPH, wide, graph)
        pg.attach(result.figure, rows, settings)
        expected = "a" if float(tables["t-test"].at["p", "Value"]) > .05 else None
        self.assertEqual(len(self.texts(result.figure)), 2)
        if expected:
            self.assertEqual(self.texts(result.figure), ["a", "a"])
        # A third graphed column has no comparison with the others: no letters, a clear warning.
        result = analyse(COLUMN_GRAPH, wide, {**graph, "Variables": ["Before", "After", "Reference"]})
        pg.attach(result.figure, rows, settings)
        self.assertEqual(self.texts(result.figure), [])
        self.assertIn("every pair", pg.pairwise_warning(result.figure))


if __name__ == "__main__":
    unittest.main()
