"""Cohen's kappa in the workbench: registration, the dispatcher, the figure and the dialog helpers."""
import io
from pathlib import Path
import unittest

from matplotlib.collections import QuadMesh
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from analisi import cohen_kappa_workbench as workbench
from analisi.cohen_kappa import (AGREEMENT, BOOTSTRAP, COUNTS, FIRST, INTERVAL, LEVEL, ORDER, RESAMPLES, SECOND,
                                 SEED, SHOW_GRAPH, WEIGHTING)
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "cohen_kappa"
RATINGS = pd.read_csv(DATA / "ratings.csv")
LEVELS = ["Mild", "Moderate $", "Severe"]
BASE = {FIRST: "Rater A", SECOND: "Rater B", ORDER: LEVELS}
METHOD = workbench.COHEN_KAPPA


def mesh_of(axes):
    return next(item for item in axes.collections if item.get_gid() == workbench.GID_COUNTS)


class RegistrationTests(unittest.TestCase):
    def test_the_method_is_registered_in_the_menu_and_as_a_native_graph(self):
        self.assertEqual(METHOD, "Cohen's kappa")
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GROUPS["Group Comparison"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(list(METHODS[METHOD]), [FIRST, SECOND, WEIGHTING, ORDER, INTERVAL, LEVEL, RESAMPLES, SEED,
                                                 SHOW_GRAPH])
        self.assertEqual(METHODS[METHOD][WEIGHTING], ("Unweighted", "Linear", "Quadratic"))
        self.assertEqual(METHODS[METHOD][INTERVAL], ("None", BOOTSTRAP))
        self.assertEqual(METHODS[METHOD][ORDER], workbench.ORDER_LIST)
        self.assertEqual((METHODS[METHOD][LEVEL], METHODS[METHOD][RESAMPLES], METHODS[METHOD][SEED]), (95.0, 1999, 0))
        self.assertIs(METHODS[METHOD][SHOW_GRAPH], True)
        self.assertEqual(set(workbench.RATING_FIELDS) | set(workbench.INTERVAL_FIELDS), set(METHODS[METHOD]))

    def test_the_dispatcher_runs_the_engine_and_draws_on_request(self):
        result = analyse(METHOD, RATINGS, BASE)
        self.assertEqual(list(result.tables), ["Agreement", "Counts", "Expected counts", "Category totals", "Settings"])
        self.assertIsNotNone(result.figure)
        self.assertIsNone(analyse(METHOD, RATINGS, {**BASE, SHOW_GRAPH: False}).figure)

    def test_bootstrap_fields_and_the_cancel_button(self):
        self.assertEqual(workbench.visibility("None"), {LEVEL: False, RESAMPLES: False, SEED: False})
        self.assertEqual(workbench.visibility(BOOTSTRAP), {LEVEL: True, RESAMPLES: True, SEED: True})
        self.assertTrue(workbench.cancellable(METHOD, {INTERVAL: BOOTSTRAP}))
        self.assertFalse(workbench.cancellable(METHOD, {INTERVAL: "None"}))
        self.assertFalse(workbench.cancellable(METHOD, {}))
        self.assertFalse(workbench.cancellable("Bland–Altman", {INTERVAL: BOOTSTRAP}))
        self.assertFalse(workbench.cancellable(METHOD, None))

    def test_check_options_does_not_run_the_bootstrap(self):
        plan = workbench.check_options(RATINGS, {**BASE, INTERVAL: BOOTSTRAP, RESAMPLES: 20_000})
        self.assertEqual(plan.counts.tolist(), [[8, 2, 1], [1, 7, 2], [0, 3, 6]])


class FigureTests(unittest.TestCase):
    def test_the_matrix_is_the_counts_sheet(self):
        for order in (LEVELS, LEVELS[::-1], ["Moderate $", "Severe", "Mild"]):
            result = analyse(METHOD, RATINGS, {**BASE, ORDER: order, WEIGHTING: "Quadratic"})
            sheet = result.tables[COUNTS]
            axes = result.figure.axes[0]
            mesh = mesh_of(axes)
            self.assertIsInstance(mesh, QuadMesh)
            np.testing.assert_array_equal(np.asarray(mesh.get_array()).reshape(3, 3), sheet.to_numpy())
            self.assertEqual([t.get_text() for t in axes.get_xticklabels()], list(sheet.columns))
            self.assertEqual([t.get_text() for t in axes.get_yticklabels()], list(sheet.index))
            self.assertEqual(axes.get_ylim(), (3.0, 0.0))  # the first category on top, as in the sheet
            self.assertEqual(axes.get_xlabel(), "Rater B")
            self.assertEqual(axes.get_ylabel(), "Rater A")
            texts = {t.get_gid(): t.get_text() for t in axes.texts}
            for (row, column), value in np.ndenumerate(sheet.to_numpy()):
                self.assertEqual(texts[f"kappa-count-{row + 1}-{column + 1}"], str(value))
            outlines = [p for p in axes.patches if isinstance(p, Rectangle) and str(p.get_gid()).startswith("kappa-")]
            self.assertEqual([p.get_gid() for p in outlines], [f"kappa-diagonal-{i}" for i in (1, 2, 3)])
            self.assertEqual([p.get_xy() for p in outlines], [(0, 0), (1, 1), (2, 2)])
            self.assertFalse(getattr(axes, "_tramastat_non_native", False))
            self.assertEqual(axes._tramastat_categorical_axes, ("x", "y"))

    def test_swapped_columns_draw_the_transposed_matrix(self):
        left = mesh_of(analyse(METHOD, RATINGS, BASE).figure.axes[0])
        right = mesh_of(analyse(METHOD, RATINGS, {**BASE, FIRST: "Rater B", SECOND: "Rater A"}).figure.axes[0])
        np.testing.assert_array_equal(np.asarray(left.get_array()).reshape(3, 3).T,
                                      np.asarray(right.get_array()).reshape(3, 3))

    def test_titles_and_literal_text(self):
        figure = analyse(METHOD, RATINGS, {**BASE, WEIGHTING: "Linear"}).figure
        axes = figure.axes[0]
        self.assertEqual(axes.get_title(), "Linear kappa = 0.615")
        self.assertFalse(axes.title.get_parse_math())
        self.assertTrue(all(not t.get_parse_math() for t in axes.get_xticklabels()))
        single = pd.DataFrame({"A": ["x"] * 3, "B": ["x"] * 3})
        title = analyse(METHOD, single, {FIRST: "A", SECOND: "B"}).figure.axes[0].get_title()
        self.assertEqual(title, "Unweighted kappa undefined (a single category)")

    def test_the_svg_is_vector_and_keeps_the_ids(self):
        figure = analyse(METHOD, RATINGS, BASE).figure
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg")
        svg = buffer.getvalue()
        self.assertIn('id="kappa-counts"', svg)
        self.assertIn('id="kappa-diagonal-2"', svg)
        self.assertNotIn("<image", svg)
        self.assertIn("Moderate $", svg)

    def test_twenty_categories_stay_readable(self):
        labels = [f"Category number {i:02d}" for i in range(20)]
        rng = np.random.default_rng(4)
        first = rng.integers(0, 20, 800)
        frame = pd.DataFrame({"A": [labels[i] for i in first],
                              "B": [labels[min(19, i + int(rng.integers(0, 2)))] for i in first]})
        figure = analyse(METHOD, frame, {FIRST: "A", SECOND: "B", WEIGHTING: "Linear", ORDER: labels}).figure
        axes = figure.axes[0]
        self.assertEqual(len(axes.get_xticklabels()), 20)
        self.assertEqual(axes.get_xticklabels()[0].get_rotation(), 40.0)
        self.assertLessEqual(axes.texts[0].get_fontsize(), 7.0)
        width, height = figure.get_size_inches()
        self.assertGreaterEqual(height, 10.5)
        self.assertGreater(width, height)


if __name__ == "__main__":
    unittest.main()
