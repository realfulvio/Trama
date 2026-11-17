"""Unit tests for native legend validation, idempotent application, and snapshot isolation."""
from copy import deepcopy
from io import BytesIO
import json
import math
import unittest

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.lines import Line2D

from analisi.graph_legend import (
    LEGEND_OPTIONS_KEY,
    apply_legend_options,
    capture_legend_snapshots,
    collect_legend_entries,
    is_non_native_figure,
    restore_legend_snapshots,
    typed_group_token,
    validate_legend_options,
)


def _axes_fixture():
    fig = Figure(figsize=(5, 4), dpi=100)
    ax = fig.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], label="A")
    ax.plot([0.0, 1.0], [1.0, 0.0], label="B")
    ax.legend()
    return fig, ax


def _figure_fixture():
    fig = Figure(figsize=(5, 4), dpi=100, layout="constrained")
    ax = fig.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], label="A")
    ax.plot([0.0, 1.0], [1.0, 0.0], label="B")
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=2)
    return fig, ax


class ValidateLegendOptionsTests(unittest.TestCase):
    def test_valid_canonical_options_and_immutability(self):
        raw = {
            "title": "Literal {A} $B$ \\alpha μg/mL",
            "columns": 2,
            "frame": True,
            "facecolor": "#112233",
            "edgecolor": "navy",
            "width": 2,
            "alpha": 0.35,
            "reverse": True,
            "labels": {"line:1:A": "Series $1$", "group:int:1": "One (int)", "group:str:1": "One (str)"},
        }
        snapshot = json.dumps(raw, sort_keys=True)
        canonical = validate_legend_options(raw)
        self.assertEqual(json.dumps(raw, sort_keys=True), snapshot)
        self.assertIsNot(canonical, raw)
        self.assertIsNot(canonical["labels"], raw["labels"])
        self.assertEqual(canonical["width"], 2.0)
        self.assertIsInstance(canonical["width"], float)
        self.assertEqual(canonical["alpha"], 0.35)
        self.assertIsInstance(canonical["alpha"], float)
        self.assertEqual(canonical["columns"], 2)

    def test_boundary_values_accepted(self):
        self.assertEqual(validate_legend_options({}), {})
        ok = validate_legend_options({
            "title": "x" * 160,
            "columns": 1,
            "frame": False,
            "facecolor": "none",
            "edgecolor": (0.1, 0.2, 0.3),
            "width": 0,
            "alpha": 0,
            "reverse": False,
        })
        self.assertEqual(ok["columns"], 1)
        self.assertEqual(ok["width"], 0.0)
        self.assertEqual(ok["alpha"], 0.0)
        ok_max = validate_legend_options({"columns": 8, "width": 10.0, "alpha": 1.0, "title": ""})
        self.assertEqual(ok_max["columns"], 8)
        self.assertEqual(ok_max["width"], 10.0)
        self.assertEqual(ok_max["alpha"], 1.0)

    def test_rejects_invalid_inputs(self):
        bad_cases = [
            None,
            [],
            "title",
            {"unknown": 1},
            {"title": 123},
            {"title": "x" * 161},
            {"columns": 0},
            {"columns": 9},
            {"columns": True},
            {"columns": False},
            {"columns": 2.0},
            {"columns": "2"},
            {"frame": 1},
            {"frame": "true"},
            {"reverse": 0},
            {"reverse": "false"},
            {"facecolor": "not-a-color"},
            {"facecolor": 123},
            {"facecolor": ""},
            {"edgecolor": "invalid-hex-#12"},
            {"width": -0.01},
            {"width": 10.01},
            {"width": math.nan},
            {"width": math.inf},
            {"width": -math.inf},
            {"width": True},
            {"alpha": -0.01},
            {"alpha": 1.01},
            {"alpha": math.nan},
            {"alpha": math.inf},
            {"alpha": True},
            {"labels": ["not", "dict"]},
            {"labels": {"bad_key": "A"}},
            {"labels": {"": "A"}},
            {"labels": {"line:1:A": ""}},
            {"labels": {"line:1:A": "_hidden"}},
            {"labels": {"line:1:A": "x" * 161}},
            {"labels": {"line:1:A": 42}},
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    validate_legend_options(case)


class ApplyLegendOptionsTests(unittest.TestCase):
    def test_axes_and_figure_legend_idempotent_without_mutating_data(self):
        for builder, is_fig in ((_axes_fixture, False), (_figure_fixture, True)):
            with self.subTest(figure_level=is_fig):
                fig, ax = builder()
                before_xy = [line.get_xydata().copy() for line in ax.lines]
                before_colors = [line.get_color() for line in ax.lines]
                before_visible = [line.get_visible() for line in ax.lines]
                opts = {
                    "title": "Literal {A} $B$ €",
                    "columns": 2,
                    "frame": True,
                    "facecolor": "#112233",
                    "edgecolor": "#445566",
                    "width": 2.5,
                    "alpha": 0.35,
                    "reverse": True,
                    "labels": {"line:1:A": "First $100", "line:1:B": "Second {B}"},
                }
                orig_json = json.dumps(opts, sort_keys=True)
                apply_legend_options(fig, opts)
                apply_legend_options(fig, opts)
                self.assertEqual(json.dumps(opts, sort_keys=True), orig_json)

                legend = fig.legends[0] if is_fig else ax.get_legend()
                self.assertIsNotNone(legend)
                self.assertEqual(len(fig.legends), 1 if is_fig else 0)
                self.assertEqual(legend.get_title().get_text(), opts["title"])
                self.assertFalse(legend.get_title().get_parse_math())
                self.assertEqual(legend._ncols, 2)
                self.assertEqual([t.get_text() for t in legend.get_texts()], ["Second {B}", "First $100"])
                self.assertTrue(all(not t.get_parse_math() for t in legend.get_texts()))
                self.assertTrue(legend.get_frame_on())
                self.assertAlmostEqual(legend.get_frame().get_alpha(), 0.35)
                self.assertAlmostEqual(legend.get_frame().get_linewidth(), 2.5)
                # Data lines must remain completely untouched (including no alpha attenuation).
                for line, xy, color, vis in zip(ax.lines, before_xy, before_colors, before_visible):
                    self.assertTrue((line.get_xydata() == xy).all())
                    self.assertEqual(line.get_color(), color)
                    self.assertEqual(line.get_visible(), vis)
                    self.assertIsNone(line.get_alpha())
                FigureCanvasAgg(fig).draw()

    def test_hide_frame_preserves_colors_width_and_series_visibility(self):
        fig, ax = _axes_fixture()
        apply_legend_options(fig, {
            "frame": False,
            "facecolor": "#abcdef",
            "edgecolor": "#123456",
            "width": 3.0,
            "alpha": 0.4,
        })
        legend = ax.get_legend()
        self.assertFalse(legend.get_frame_on())
        self.assertAlmostEqual(legend.get_frame().get_linewidth(), 3.0)
        self.assertAlmostEqual(legend.get_frame().get_alpha(), 0.4)
        self.assertTrue(all(line.get_visible() for line in ax.lines))

    def test_invalid_options_do_not_mutate_legend(self):
        fig, ax = _axes_fixture()
        legend = ax.get_legend()
        texts = [t.get_text() for t in legend.get_texts()]
        with self.assertRaises(ValueError):
            apply_legend_options(fig, {"title": "Changed", "columns": 0})
        self.assertIs(ax.get_legend(), legend)
        self.assertEqual([t.get_text() for t in legend.get_texts()], texts)
        self.assertEqual(legend.get_title().get_text(), "")

    def test_absent_legend_never_invents_one(self):
        fig = Figure()
        ax = fig.subplots()
        ax.plot([0, 1], [0, 1])
        apply_legend_options(fig, {"columns": 2, "title": "Should not appear"})
        self.assertIsNone(ax.get_legend())
        self.assertEqual(fig.legends, [])

    def test_multiple_intentional_legends_preserved(self):
        fig = Figure()
        ax = fig.subplots()
        ax.scatter([1, 2], [3, 4], label="Group 1")
        ax.scatter([2, 3], [4, 5], label="Group 2")
        main = ax.legend(title="Groups")
        proxy = [Line2D([], [], marker="o", linestyle="none")]
        extra = Legend(ax, proxy, ["Size 10"], title="Size", frameon=False, loc="lower right")
        extra.set_gid("bubble-size-legend")
        ax.add_artist(extra)

        apply_legend_options(fig, {"columns": 2, "reverse": True, "frame": True})
        self.assertIs(ax.get_legend(), main)
        self.assertIn(extra, ax.artists)
        self.assertEqual([t.get_text() for t in main.get_texts()], ["Group 2", "Group 1"])
        self.assertEqual([t.get_text() for t in extra.get_texts()], ["Size 10"])
        self.assertTrue(main.get_frame_on())
        self.assertTrue(extra.get_frame_on())

    def test_distinct_identities_with_identical_visible_text(self):
        fig = Figure()
        ax = fig.subplots()
        s1 = ax.scatter([0, 1], [1, 2], label="1")
        s1._tramastat_legend_key = f"group:{typed_group_token(1)}"
        s2 = ax.scatter([0, 1], [2, 3], label="1")
        s2._tramastat_legend_key = f"group:{typed_group_token('1')}"
        ax.legend()

        entries = collect_legend_entries(fig)
        keys = [entry.key for entry in entries]
        self.assertEqual(keys, ["group:int:1", "group:str:1"])
        self.assertEqual(len(set(keys)), 2)

        apply_legend_options(fig, {
            "reverse": True,
            "labels": {"group:int:1": "Numeric 1", "group:str:1": "Text '1'"},
        })
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Text '1'", "Numeric 1"])

        # Removing reverse restores order while keeping independent labels.
        apply_legend_options(fig, {
            "labels": {"group:int:1": "Numeric 1"},
        })
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Numeric 1", "1"])

    def test_snapshot_restore_and_deepcopy_isolation(self):
        fig, ax = _axes_fixture()
        capture_legend_snapshots(fig)
        apply_legend_options(fig, {"title": "Edited", "columns": 2, "reverse": True, "alpha": 0.2})

        preview = deepcopy(fig)
        self.assertIsNot(preview.axes[0].get_legend(), ax.get_legend())
        self.assertIsNot(
            preview.axes[0].get_legend()._tramastat_legend_snapshot,
            ax.get_legend()._tramastat_legend_snapshot,
        )
        # Mutating preview must not affect original figure.
        apply_legend_options(preview, {"title": "Preview Only", "reverse": False})
        self.assertEqual(ax.get_legend().get_title().get_text(), "Edited")
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["B", "A"])

        # Restoring snapshot on original restores pristine state.
        restore_legend_snapshots(fig)
        self.assertEqual(ax.get_legend().get_title().get_text(), "")
        self.assertEqual(ax.get_legend()._ncols, 1)
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["A", "B"])

    def test_non_native_raster_figure_rejected(self):
        fig = Figure()
        ax = fig.add_axes((0, 0, 1, 1))
        ax._tramastat_non_native = True
        self.assertTrue(is_non_native_figure(fig))
        with self.assertRaises(ValueError):
            apply_legend_options(fig, {"title": "Blocked"})

    def test_vector_exports_keep_literal_text(self):
        fig, _ = _axes_fixture()
        apply_legend_options(fig, {
            "title": "Title {A} $B$",
            "reverse": True,
            "columns": 2,
            "labels": {"line:1:A": "Alpha $x$"},
        })
        for fmt in ("png", "svg", "pdf"):
            buf = BytesIO()
            fig.savefig(buf, format=fmt)
            self.assertGreater(buf.tell(), 0)
        svg = BytesIO()
        fig.savefig(svg, format="svg")
        svg_text = svg.getvalue().decode("utf-8")
        self.assertIn("Title {A} $B$", svg_text)
        self.assertIn("Alpha $x$", svg_text)


if __name__ == "__main__":
    unittest.main()
