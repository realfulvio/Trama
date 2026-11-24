"""Unit and contract tests for Raincloud plot (and Box / violin plot non-regression)."""
from pathlib import Path
import unittest
from unittest.mock import patch

from matplotlib.collections import PathCollection
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from analisi import distribution_graphs as dg
from analisi import raincloud_plot as rc
from analisi.category_order import WORKSHEET_ORDERS
from analisi.presentation import apply_style, graph_groups, validate_graph_style
from analisi.processing import FieldError
from analisi.workbench import GROUPS, analyse


FIXTURE = Path(__file__).resolve().parent / "data" / "raincloud_plot" / "raincloud.csv"


def _run(frame, **options):
    opts = {
        rc.RESPONSE: "Misura",
        rc.GROUP: "Gruppo",
        rc.ORIENTATION: rc.VERTICAL,
        rc.SHOW_DENSITY: True,
        rc.SHOW_BOX: True,
        rc.SHOW_POINTS: True,
        rc.BANDWIDTH_MULTIPLIER: 1.0,
        **options,
    }
    return analyse(rc.METHOD, frame, opts)


class RaincloudPlotTests(unittest.TestCase):
    def test_catalogue_presence(self):
        self.assertIn(rc.METHOD, GROUPS["Graphing"])

    def test_fixture_summary_discarded_and_literal_labels(self):
        frame = pd.read_csv(FIXTURE)
        res = _run(frame)
        self.assertIn(rc.SUMMARY_SHEET, res.tables)
        self.assertIn(rc.DENSITY_SHEET, res.tables)
        self.assertIn(rc.SETTINGS_SHEET, res.tables)

        summary = res.tables[rc.SUMMARY_SHEET]
        self.assertEqual(list(summary.columns), rc.SUMMARY_COLUMNS)
        rows = list(summary.itertuples(index=False, name=None))
        self.assertEqual(len(rows), 4)
        expected = [
            ("Control $", 5, 1.0, 1.5, 2.0, 5.0, 7.0, 1.0, 7.0),
            ("Trattamento", 6, -1.0, -0.25, 1.0, 2.75, 8.0, -1.0, 1.0),
            ("Costante", 4, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0),
            ("Singolo", 1, 9.0, np.nan, 9.0, np.nan, 9.0, 9.0, 9.0),
        ]
        for actual, exp in zip(rows, expected, strict=True):
            self.assertEqual(actual[:2], exp[:2])
            for a_val, e_val in zip(actual[2:], exp[2:], strict=True):
                if np.isnan(e_val):
                    self.assertTrue(pd.isna(a_val))
                else:
                    self.assertAlmostEqual(float(a_val), e_val, places=12)

        # Discarded count: 3 rows ("bad", blank response, missing group).
        settings = res.tables[rc.SETTINGS_SHEET]["Value"]
        self.assertEqual(int(settings["Observations used"]), 16)
        self.assertEqual(int(settings["Rows discarded"]), 3)

        # Singleton ("Singolo") and constant ("Costante") produce no density rows.
        density = res.tables[rc.DENSITY_SHEET]
        self.assertEqual(list(density.columns), rc.DENSITY_COLUMNS)
        self.assertEqual(set(density["Group"]), {"Control $", "Trattamento"})

        # Literal dollar sign on tick label.
        ax = res.figure.axes[0]
        ticks = ax.get_xticklabels()
        self.assertEqual([t.get_text() for t in ticks], ["Control $", "Trattamento", "Costante", "Singolo"])
        self.assertFalse(ticks[0].get_parse_math())

    def test_ungrouped_single_distribution(self):
        frame = pd.DataFrame({"val": [1.0, 2.0, 3.0, 4.0, 10.0, np.nan]})
        res = _run(frame, Response="val", Group=None)
        summary = res.tables[rc.SUMMARY_SHEET]
        self.assertEqual(len(summary), 1)
        row = summary.iloc[0]
        self.assertEqual(row["Group"], "All")
        self.assertEqual(int(row["N"]), 5)
        self.assertAlmostEqual(float(row["Q1"]), 1.5)
        self.assertAlmostEqual(float(row["Median"]), 3.0)
        self.assertAlmostEqual(float(row["Q3"]), 7.0)
        self.assertEqual(int(res.tables[rc.SETTINGS_SHEET]["Value"]["Rows discarded"]), 1)

    def test_orientation_and_component_invariance(self):
        frame = pd.read_csv(FIXTURE)
        base_res = _run(frame, Orientation=rc.VERTICAL)
        horiz_res = _run(frame, Orientation=rc.HORIZONTAL)

        pd.testing.assert_frame_equal(
            base_res.tables[rc.SUMMARY_SHEET],
            horiz_res.tables[rc.SUMMARY_SHEET],
        )
        pd.testing.assert_frame_equal(
            base_res.tables[rc.DENSITY_SHEET],
            horiz_res.tables[rc.DENSITY_SHEET],
        )
        ax_h = horiz_res.figure.axes[0]
        self.assertEqual([t.get_text() for t in ax_h.get_yticklabels()], ["Control $", "Trattamento", "Costante", "Singolo"])
        self.assertEqual(ax_h._tramastat_numeric_axes, ("x",))
        self.assertEqual(ax_h._tramastat_categorical_axes, ("y",))

        # All 7 non-empty component combinations work and preserve summary stats.
        for d in (False, True):
            for b in (False, True):
                for p in (False, True):
                    if not (d or b or p):
                        continue
                    opts = {
                        rc.SHOW_DENSITY: d,
                        rc.SHOW_BOX: b,
                        rc.SHOW_POINTS: p,
                        rc.BANDWIDTH_MULTIPLIER: -3.0 if not d else 1.0,
                    }
                    r = _run(frame, **opts)
                    pd.testing.assert_frame_equal(r.tables[rc.SUMMARY_SHEET], base_res.tables[rc.SUMMARY_SHEET])
                    if d:
                        self.assertIn(rc.DENSITY_SHEET, r.tables)
                    else:
                        self.assertNotIn(rc.DENSITY_SHEET, r.tables)

    def test_geometry_separation_determinism_and_no_subsampling(self):
        frame = pd.read_csv(FIXTURE)
        res1 = _run(frame, Orientation=rc.VERTICAL)
        res2 = _run(frame, Orientation=rc.VERTICAL)
        ax1 = res1.figure.axes[0]
        ax2 = res2.figure.axes[0]

        groups1 = graph_groups(ax1)
        groups2 = graph_groups(ax2)
        self.assertEqual([g.key for g in groups1], [
            "raincloud:str:Control $",
            "raincloud:str:Trattamento",
            "raincloud:str:Costante",
            "raincloud:str:Singolo",
        ])

        expected_counts = [5, 6, 4, 1]
        for idx, (g1, g2, exp_n) in enumerate(zip(groups1, groups2, expected_counts, strict=True)):
            pos = float(idx + 1)
            fills = [art for art, role in g1.artists if role == "fill" and not isinstance(art, Rectangle)]
            boxes = [art for art, role in g1.artists if isinstance(art, Rectangle)]
            scatters = [art for art, role in g1.artists if isinstance(art, PathCollection)]

            self.assertEqual(len(scatters), 1)
            offsets1 = np.asarray(scatters[0].get_offsets(), dtype=float)
            self.assertEqual(len(offsets1), exp_n)
            self.assertTrue(np.isfinite(offsets1).all())
            # Rain stays strictly on the negative side of category center.
            self.assertTrue((offsets1[:, 0] < pos).all())
            self.assertTrue((offsets1[:, 0] >= pos - 0.40).all())

            # Determinism across runs.
            scatters2 = [art for art, role in g2.artists if isinstance(art, PathCollection)]
            np.testing.assert_allclose(offsets1, np.asarray(scatters2[0].get_offsets(), dtype=float))

            # Half-violin stays strictly on the positive side of category center; skipped for constant/singleton.
            if exp_n >= 5:
                self.assertEqual(len(fills), 1)
                verts = np.concatenate([p.vertices for p in fills[0].get_paths()])
                self.assertTrue((verts[:, 0] > pos).all())
                self.assertTrue((verts[:, 0] <= pos + 0.42).all())
            else:
                self.assertEqual(len(fills), 0)

            # Compact box is centered on pos within [pos - 0.05, pos + 0.05].
            if exp_n >= 4:
                self.assertEqual(len(boxes), 1)
                x0 = boxes[0].get_x()
                w = boxes[0].get_width()
                self.assertGreaterEqual(x0, pos - 0.05)
                self.assertLessEqual(x0 + w, pos + 0.05)

    def test_validation_and_kde_budget(self):
        frame = pd.read_csv(FIXTURE)
        with self.assertRaises(FieldError) as ctx:
            _run(frame, **{rc.SHOW_DENSITY: False, rc.SHOW_BOX: False, rc.SHOW_POINTS: False})
        self.assertEqual(ctx.exception.field, rc.SHOW_DENSITY)

        with self.assertRaises(FieldError) as ctx:
            _run(frame, **{rc.GROUP: "Misura"})
        self.assertEqual(ctx.exception.field, rc.GROUP)

        with self.assertRaises(FieldError) as ctx:
            _run(frame, **{rc.BANDWIDTH_MULTIPLIER: 0.0})
        self.assertEqual(ctx.exception.field, rc.BANDWIDTH_MULTIPLIER)

        with self.assertRaises(FieldError) as ctx:
            _run(pd.DataFrame({"Gruppo": ["A", "B"], "Misura": ["bad", ""]}))
        self.assertEqual(ctx.exception.field, rc.RESPONSE)

        with patch.object(dg, "MAX_KDE_EVALUATIONS", 1000):
            with self.assertRaises(FieldError) as ctx:
                _run(frame)
            self.assertEqual(ctx.exception.field, rc.BANDWIDTH_MULTIPLIER)
            self.assertIn("Show density", str(ctx.exception))

    def test_category_order_typed_identities_and_style_preservation(self):
        frame = pd.DataFrame({
            "G": pd.Series([1, "1", "Control $", 1, "1", "Control $"], dtype=object),
            "Y": [10.0, 20.0, 30.0, 12.0, 22.0, 34.0],
        })
        res_default = _run(frame, Response="Y", Group="G")
        keys_default = [g.key for g in graph_groups(res_default.figure.axes[0])]
        self.assertEqual(keys_default, ["raincloud:int:1", "raincloud:str:1", "raincloud:str:Control $"])

        style = {"groups": {"raincloud:str:Control $": {"color": "#cc3311", "visible": True}}}
        validate_graph_style(res_default.figure.axes[0], style)
        apply_style(res_default.figure, style)

        reordered = frame.copy()
        reordered.attrs[WORKSHEET_ORDERS] = {"G": ["str:Control $", "str:1", "int:1"]}
        res_reordered = _run(reordered, Response="Y", Group="G")
        keys_reordered = [g.key for g in graph_groups(res_reordered.figure.axes[0])]
        self.assertEqual(keys_reordered, ["raincloud:str:Control $", "raincloud:str:1", "raincloud:int:1"])

        apply_style(res_reordered.figure, style)
        ctrl = graph_groups(res_reordered.figure.axes[0])[0]
        self.assertEqual(ctrl.key, "raincloud:str:Control $")
        scatter = next(a for a, role in ctrl.artists if role == "point")
        fc = scatter.get_facecolor()[0]
        self.assertAlmostEqual(float(fc[0]), 0xCC / 255.0, places=2)

    def test_box_violin_plot_regression_unchanged(self):
        frame = pd.DataFrame({
            "G": ["A"] * 6 + ["B"] * 5,
            "Y": [1.0, 2.0, 2.0, 3.0, 7.0, 15.0, -1.0, 0.0, 1.0, 1.0, 8.0],
        })
        box_res = analyse("Box / violin plot", frame, {"Input": "Single response", "Response": "Y", "Group": "G", "Style": "Box"})
        violin_res = analyse("Box / violin plot", frame, {"Input": "Single response", "Response": "Y", "Group": "G", "Style": "Violin"})
        self.assertEqual(list(box_res.tables["Group summary"]["N"]), [6, 5])
        self.assertEqual(list(violin_res.tables["Group summary"]["N"]), [6, 5])
        self.assertIn("Violin density", violin_res.tables)
        self.assertEqual([g.key for g in graph_groups(box_res.figure.axes[0])], ["box:category:str:A", "box:category:str:B"])
        self.assertEqual([g.key for g in graph_groups(violin_res.figure.axes[0])], ["violin:category:str:A", "violin:category:str:B"])


if __name__ == "__main__":
    unittest.main()
