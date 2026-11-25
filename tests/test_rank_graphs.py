"""Tests for Mann–Whitney and Wilcoxon rank and paired-difference graphs."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from matplotlib.collections import PathCollection
import numpy as np
import pandas as pd

from analisi import Dataset, rank_graphs, rank_tests
from analisi.data import load_workspace, save_project
from analisi.i18n import set_language
from analisi.workbench import METHODS, analyse
from analisi.rank_graphs import (
    RANK_PLOT,
    VISUAL_POINT_LIMIT,
    WILCOXON_DIFFERENCES,
    rank_plot_options,
    rank_test_figure,
    validated_source_positions,
)
from analisi.rank_tests import (
    ALTERNATIVE,
    AUTOMATIC,
    CONTINUITY,
    DISCARD,
    MANN_WHITNEY,
    PRATT,
    P_VALUE,
    WILCOXON,
    ZERO_DIFFERENCES,
)


class RankGraphOptionsTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_plot_options_are_disabled_by_default_and_excluded_from_catalog(self):
        self.assertNotIn(RANK_PLOT, METHODS[MANN_WHITNEY])
        self.assertNotIn(RANK_PLOT, METHODS[WILCOXON])
        self.assertNotIn(WILCOXON_DIFFERENCES, METHODS[WILCOXON])

        self.assertEqual(rank_plot_options(MANN_WHITNEY, {"Response": "y", "Group": "g"}), ())
        self.assertEqual(rank_plot_options(WILCOXON, {"First": "a", "Second": "b", P_VALUE: AUTOMATIC}), ())

        mw_frame = pd.DataFrame({"y": [1.0, 2.0, 5.0, 6.0], "g": ["A", "A", "B", "B"]})
        self.assertIsNone(analyse(MANN_WHITNEY, mw_frame, {"Response": "y", "Group": "g", P_VALUE: AUTOMATIC}).figure)

        wx_frame = pd.DataFrame({"a": [3.0, 5.0, 8.0], "b": [1.0, 2.0, 4.0]})
        self.assertIsNone(
            analyse(WILCOXON, wx_frame, {"First": "a", "Second": "b", P_VALUE: AUTOMATIC}).figure
        )


class RankGraphMathAndLiteralTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_mann_whitney_ties_dollar_labels_and_exact_table_preservation(self):
        frame = pd.DataFrame({
            "Response $": [3.0, 7.0, 3.0, 5.0, 8.0],
            "Group $": ["Dose $", "Dose $", "B", "B", "B"],
        })
        base_opts = {
            "Response": "Response $",
            "Group": "Group $",
            P_VALUE: AUTOMATIC,
            ALTERNATIVE: "Two-sided",
            CONTINUITY: True,
        }
        plain = analyse(MANN_WHITNEY, frame, base_opts)
        with_plot = analyse(MANN_WHITNEY, frame, {**base_opts, RANK_PLOT: True})

        pd.testing.assert_frame_equal(with_plot.tables[MANN_WHITNEY], plain.tables[MANN_WHITNEY])
        pd.testing.assert_frame_equal(with_plot.tables["Ranks"], plain.tables["Ranks"])
        self.assertEqual(with_plot.tables["Ranks"]["Rank"].tolist(), [1.5, 4.0, 1.5, 3.0, 5.0])

        fig = with_plot.figure
        self.assertIsNotNone(fig)
        self.assertEqual(len(fig.axes), 1)
        ax = fig.axes[0]
        self.assertEqual([lbl.get_text() for lbl in ax.get_xticklabels()], ["Dose $", "B"])
        self.assertFalse(ax.title.get_parse_math())
        self.assertFalse(ax.xaxis.label.get_parse_math())
        self.assertFalse(ax.yaxis.label.get_parse_math())
        self.assertTrue(all(not t.get_parse_math() for t in ax.get_xticklabels()))
        self.assertEqual(ax.get_xlabel(), "Group $")

        y_by_group = {}
        for col in ax.collections:
            offsets = col.get_offsets()
            y_by_group[col.get_label()] = sorted(float(v) for v in offsets[:, 1])
        self.assertEqual(y_by_group["Dose $"], [1.5, 4.0])
        self.assertEqual(y_by_group["B"], [1.5, 3.0, 5.0])

        for fmt in ("png", "svg", "pdf"):
            buf = BytesIO()
            fig.savefig(buf, format=fmt)
            self.assertGreater(len(buf.getvalue()), 500, fmt)

    def test_wilcoxon_casi_discard_pratt_reverse_and_two_panel_layout(self):
        frame = pd.DataFrame({
            "First": [5.0, 1.0, 2.0, 8.0, np.nan],
            "Second": [1.0, 5.0, 2.0, 1.0, 9.0],
        })
        discard_base = {
            "First": "First",
            "Second": "Second",
            P_VALUE: AUTOMATIC,
            ALTERNATIVE: "Two-sided",
            CONTINUITY: True,
            ZERO_DIFFERENCES: DISCARD,
        }
        plain = analyse(WILCOXON, frame, discard_base)
        ranks_only = analyse(WILCOXON, frame, {**discard_base, RANK_PLOT: True})
        diffs_only = analyse(WILCOXON, frame, {**discard_base, WILCOXON_DIFFERENCES: True})
        both = analyse(WILCOXON, frame, {**discard_base, RANK_PLOT: True, WILCOXON_DIFFERENCES: True})

        for res in (ranks_only, diffs_only, both):
            pd.testing.assert_frame_equal(res.tables[WILCOXON], plain.tables[WILCOXON])
            pd.testing.assert_frame_equal(res.tables["Ranks"], plain.tables["Ranks"])

        # Ranks only (Discard): signed ranks 1.5, -1.5, 3.0 at pairs 1, 2, 4 (zero at pair 3 omitted)
        ax_rank = ranks_only.figure.axes[0]
        pts_rank = sorted(
            (int(round(x)), float(y))
            for col in ax_rank.collections
            for x, y in col.get_offsets()
        )
        self.assertEqual(pts_rank, [(1, 1.5), (2, -1.5), (4, 3.0)])

        # Differences only: direction First - Second, zero pair included on pair 3
        ax_diff = diffs_only.figure.axes[0]
        pts_diff = sorted(
            (int(round(x)), float(y))
            for col in ax_diff.collections
            for x, y in col.get_offsets()
        )
        self.assertEqual(pts_diff, [(1, 4.0), (2, -4.0), (3, 0.0), (4, 7.0)])
        self.assertEqual(ax_diff.get_ylabel(), "First − Second")

        # Both active -> 1x2 subplots
        self.assertEqual(len(both.figure.axes), 2)

        # Pratt policy: signed ranks 2.5, -2.5, 4.0 plus visually distinct zero at pair 3
        pratt = analyse(
            WILCOXON,
            frame,
            {**discard_base, ZERO_DIFFERENCES: PRATT, RANK_PLOT: True},
        )
        pratt_collections = {col.get_label(): col.get_offsets() for col in pratt.figure.axes[0].collections}
        signed_pts = sorted(
            (int(round(x)), float(y))
            for lbl, arr in pratt_collections.items()
            if lbl != "Zero differences (Pratt)"
            for x, y in arr
        )
        self.assertEqual(signed_pts, [(1, 2.5), (2, -2.5), (4, 4.0)])
        zero_pts = pratt_collections["Zero differences (Pratt)"]
        self.assertEqual(len(zero_pts), 1)
        self.assertEqual((int(round(zero_pts[0, 0])), float(zero_pts[0, 1])), (3, 0.0))

        # Reversing First/Second reverses signed direction and differences
        reversed_res = analyse(
            WILCOXON,
            frame,
            {
                "First": "Second",
                "Second": "First",
                P_VALUE: AUTOMATIC,
                ALTERNATIVE: "Two-sided",
                CONTINUITY: True,
                ZERO_DIFFERENCES: DISCARD,
                RANK_PLOT: True,
                WILCOXON_DIFFERENCES: True,
            },
        )
        rev_ranks = sorted(
            (int(round(x)), float(y))
            for col in reversed_res.figure.axes[0].collections
            for x, y in col.get_offsets()
        )
        rev_diffs = sorted(
            (int(round(x)), float(y))
            for col in reversed_res.figure.axes[1].collections
            for x, y in col.get_offsets()
        )
        self.assertEqual(rev_ranks, [(1, -1.5), (2, 1.5), (4, -3.0)])
        self.assertEqual(rev_diffs, [(1, -4.0), (2, 4.0), (3, 0.0), (4, -7.0)])

    def test_all_zero_differences_renders_cleanly_under_discard_and_pratt(self):
        frame = pd.DataFrame({"First": [3.0, 5.0, 8.0], "Second": [3.0, 5.0, 8.0]})
        for policy in (DISCARD, PRATT):
            res = analyse(
                WILCOXON,
                frame,
                {
                    "First": "First",
                    "Second": "Second",
                    P_VALUE: AUTOMATIC,
                    ZERO_DIFFERENCES: policy,
                    RANK_PLOT: True,
                    WILCOXON_DIFFERENCES: True,
                },
            )
            self.assertEqual(len(res.figure.axes), 2)
            diff_pts = sorted((int(round(x)), float(y)) for x, y in res.figure.axes[1].collections[0].get_offsets())
            self.assertEqual(diff_pts, [(1, 0.0), (2, 0.0), (3, 0.0)])

    def test_source_row_identity_across_gaps_exclusions_and_duplicate_labels(self):
        raw = pd.DataFrame({
            "First": [np.nan, 99.0, 5.0, 10.0, 2.0, 9.0],
            "Second": [1.0, 1.0, 1.0, np.nan, 2.0, 3.0],
        })
        ds = Dataset(raw)
        ds.excluded.add((1, 0))  # exclude row 2 (0-based row 1)
        frame = ds.frame(mask_excluded=True)

        # Complete pairs remain only at 1-based worksheet rows 3, 5, 6
        opts = {
            "First": "First",
            "Second": "Second",
            P_VALUE: AUTOMATIC,
            ZERO_DIFFERENCES: PRATT,
            RANK_PLOT: True,
            WILCOXON_DIFFERENCES: True,
        }
        res = analyse(WILCOXON, frame, opts)
        self.assertEqual(res.table_contexts["Ranks"]["positions"].tolist(), [3, 5, 6])

        rank_positions = sorted(
            int(pos)
            for col in res.figure.axes[0].collections
            if isinstance(col, PathCollection)
            for pos in col._tramastat_points.rows
        )
        diff_positions = sorted(
            int(pos)
            for col in res.figure.axes[1].collections
            if isinstance(col, PathCollection)
            for pos in col._tramastat_points.rows
        )
        self.assertEqual(rank_positions, [3, 5, 6])
        self.assertEqual(diff_positions, [3, 5, 6])

        # Duplicate index labels without validated source_positions must be rejected
        dup_frame = pd.DataFrame({"First": [4.0, 1.0], "Second": [1.0, 2.0]}, index=[0, 0])
        dup_res = rank_tests.rank_test(WILCOXON, dup_frame, {**opts, RANK_PLOT: False, WILCOXON_DIFFERENCES: False})
        with self.assertRaises(ValueError):
            validated_source_positions(dup_frame, dup_res.tables["Ranks"], source_positions=None)
        with self.assertRaises(ValueError):
            rank_test_figure(WILCOXON, dup_res.tables, opts, frame=dup_frame, source_positions=None)

    def test_large_dataset_visual_reduction_declares_limit_without_altering_inference(self):
        rng = np.random.default_rng(123)
        n = 6_000
        mw_frame = pd.DataFrame({
            "Value": np.concatenate([rng.normal(0.0, 1.0, n // 2), rng.normal(1.0, 1.0, n // 2)]),
            "Group": ["A"] * (n // 2) + ["B"] * (n // 2),
        })
        plain = analyse(MANN_WHITNEY, mw_frame, {"Response": "Value", "Group": "Group", P_VALUE: AUTOMATIC})
        plotted = analyse(
            MANN_WHITNEY,
            mw_frame,
            {"Response": "Value", "Group": "Group", P_VALUE: AUTOMATIC, RANK_PLOT: True},
        )
        pd.testing.assert_frame_equal(plotted.tables[MANN_WHITNEY], plain.tables[MANN_WHITNEY])
        self.assertEqual(len(plotted.tables["Ranks"]), n)
        drawn_count = sum(
            len(col.get_offsets())
            for col in plotted.figure.axes[0].collections
            if isinstance(col, PathCollection)
        )
        self.assertLessEqual(drawn_count, VISUAL_POINT_LIMIT)
        self.assertIn("6,000", plotted.figure.get_supxlabel())

    def test_legacy_recipe_preserves_original_table_and_draws_requested_plot(self):
        frame = pd.DataFrame({
            "Response": [3.0, 7.0, 3.0, 5.0, 8.0],
            "Group": ["Dose $", "Dose $", "B", "B", "B"],
        })
        legacy_plain = analyse(MANN_WHITNEY, frame, {"Response": "Response", "Group": "Group"})
        legacy_plot = analyse(MANN_WHITNEY, frame, {"Response": "Response", "Group": "Group", RANK_PLOT: True})

        self.assertEqual(list(legacy_plot.tables.keys()), [MANN_WHITNEY])
        pd.testing.assert_frame_equal(legacy_plot.tables[MANN_WHITNEY], legacy_plain.tables[MANN_WHITNEY])
        self.assertIsNone(legacy_plain.figure)
        self.assertIsNotNone(legacy_plot.figure)

        wx_frame = pd.DataFrame({"First": [5.0, 1.0, 2.0, 8.0], "Second": [1.0, 5.0, 2.0, 1.0]})
        wx_plain = analyse(WILCOXON, wx_frame, {"First": "First", "Second": "Second"})
        wx_plot = analyse(
            WILCOXON,
            wx_frame,
            {"First": "First", "Second": "Second", RANK_PLOT: True, WILCOXON_DIFFERENCES: True},
        )
        self.assertEqual(list(wx_plot.tables.keys()), [WILCOXON])
        pd.testing.assert_frame_equal(wx_plot.tables[WILCOXON], wx_plain.tables[WILCOXON])
        self.assertEqual(len(wx_plot.figure.axes), 2)

    def test_project_roundtrip_and_it_translation(self):
        set_language("it")
        mw = Dataset(
            pd.DataFrame({"Valore $": [3.0, 7.0, 3.0, 5.0, 8.0], "Gruppo $": ["Dose $", "Dose $", "B", "B", "B"]}),
            analyses=[(MANN_WHITNEY, {"Response": "Valore $", "Group": "Gruppo $", P_VALUE: AUTOMATIC, RANK_PLOT: True})],
        )
        wx = Dataset(
            pd.DataFrame({"Prima": [5.0, 1.0, 2.0, 8.0, np.nan], "Seconda": [1.0, 5.0, 2.0, 1.0, 9.0]}),
            analyses=[(
                WILCOXON,
                {
                    "First": "Prima",
                    "Second": "Seconda",
                    P_VALUE: AUTOMATIC,
                    ZERO_DIFFERENCES: PRATT,
                    RANK_PLOT: True,
                    WILCOXON_DIFFERENCES: True,
                },
            )],
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rank-plots.alab"
            save_project(path, {"MW": mw, "Wilcoxon": wx})
            tables, _ = load_workspace(path)

        mw_loaded = tables["MW"]
        wx_loaded = tables["Wilcoxon"]
        self.assertTrue(mw_loaded.analyses[0][1].get(RANK_PLOT))
        self.assertTrue(wx_loaded.analyses[0][1].get(RANK_PLOT))
        self.assertTrue(wx_loaded.analyses[0][1].get(WILCOXON_DIFFERENCES))

        mw_res = analyse(mw_loaded.analyses[0][0], mw_loaded.frame(mask_excluded=True), mw_loaded.analyses[0][1])
        self.assertEqual(mw_res.figure.axes[0].get_ylabel(), "Rango")
        wx_res = analyse(wx_loaded.analyses[0][0], wx_loaded.frame(mask_excluded=True), wx_loaded.analyses[0][1])
        self.assertIn("Pratt", wx_res.figure.axes[0].get_title())
        self.assertIn("Ranghi con segno", wx_res.figure.axes[0].get_title())
        self.assertEqual(wx_res.figure.axes[1].get_title(), "Differenze")


if __name__ == "__main__":
    unittest.main()
