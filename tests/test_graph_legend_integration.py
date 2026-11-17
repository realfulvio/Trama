"""Integration and persistence tests for legend_options with presentation, .alab, layout, and analyses."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from matplotlib.figure import Figure
import pandas as pd
import pypdfium2 as pdfium

from analisi.data import Dataset, load_workspace, save_project
from analisi.fdr_control import analysis as fdr_analysis
from analisi.graph_legend import LEGEND_OPTIONS_KEY, collect_legend_entries
from analisi.i18n import active_language, set_language
from analisi.normality import normality
from analisi.presentation import apply_style, compose_layout, validated_style
from analisi.workbench import analyse
from analisi.xy_series import XY_METHOD, xy_series


class LegendPresentationIntegrationTests(unittest.TestCase):
    def test_apply_style_composes_legend_size_font_family_and_reset(self):
        fig = Figure(figsize=(5, 4), dpi=100)
        ax = fig.subplots()
        ax.plot([0, 1], [0, 1], label="A")
        ax.plot([0, 1], [1, 0], label="B")
        ax.legend()

        apply_style(fig, {
            "font_family": "serif",
            "legend_size": 14,
            "legend_options": {
                "title": "Literal {A} $B$",
                "columns": 2,
                "frame": True,
                "facecolor": "#f0f4f8",
                "edgecolor": "#123456",
                "width": 2.0,
                "alpha": 0.4,
                "reverse": True,
                "labels": {"line:1:A": "Alpha $x$"},
            },
        })
        leg = ax.get_legend()
        self.assertEqual(leg.get_title().get_text(), "Literal {A} $B$")
        self.assertEqual([t.get_text() for t in leg.get_texts()], ["B", "Alpha $x$"])
        self.assertEqual(leg._ncols, 2)
        self.assertAlmostEqual(leg.get_title().get_fontsize(), 14.0)
        self.assertTrue(all(abs(t.get_fontsize() - 14.0) < 1e-6 for t in leg.get_texts()))

        # Reset to empty style restores original title, order, columns, and frame.
        apply_style(fig, {})
        leg = ax.get_legend()
        self.assertEqual(leg.get_title().get_text(), "")
        self.assertEqual([t.get_text() for t in leg.get_texts()], ["A", "B"])
        self.assertEqual(leg._ncols, 1)

    def test_xy_twin_axes_preserves_right_axis_series_in_legend(self):
        frame = pd.DataFrame({
            "X": [0.0, 1.0, 2.0],
            "LeftCol": [1.0, 2.0, 3.0],
            "RightCol": [10.0, 20.0, 30.0],
        })
        options = {
            "X": "X",
            "Y columns": ["LeftCol", "RightCol"],
            "Series style": {"LeftCol": "Line and points", "RightCol": "Line and points"},
            "Series side": {"LeftCol": "Left", "RightCol": "Right"},
        }
        res = xy_series(frame, options)
        apply_style(res.figure, {
            LEGEND_OPTIONS_KEY: {
                "title": "Left + Right",
                "columns": 2,
                "reverse": True,
                "labels": {"xy:1:RightCol": "Right (mmHg)"},
            },
        })
        leg = res.figure.axes[0].get_legend()
        self.assertEqual(leg.get_title().get_text(), "Left + Right")
        self.assertEqual([t.get_text() for t in leg.get_texts()], ["Right (mmHg)", "LeftCol"])
        self.assertEqual(len(res.figure.axes), 2)

    def test_legacy_qq_and_fdr_unchanged_without_legend_options(self):
        frame = pd.DataFrame({"Value": [1.2, 2.3, 3.1, 4.4, 5.0, 6.2, 7.1]})
        res_legacy = normality(frame, {
            "Variables": ["Value"],
            "Distribution": "Both",
            "Q–Q plot": True,
            "Q–Q variable": "Value",
            "Q–Q reference line": True,
        })
        before_titles = [ax.get_legend().get_title().get_text() for ax in res_legacy.figure.axes]
        before_texts = [[t.get_text() for t in ax.get_legend().get_texts()] for ax in res_legacy.figure.axes]
        before_frame = [ax.get_legend().get_frame_on() for ax in res_legacy.figure.axes]
        apply_style(res_legacy.figure, {"title": "Legacy Q-Q"})
        self.assertEqual([ax.get_legend().get_title().get_text() for ax in res_legacy.figure.axes], before_titles)
        self.assertEqual([[t.get_text() for t in ax.get_legend().get_texts()] for ax in res_legacy.figure.axes],
                         before_texts)
        self.assertEqual([ax.get_legend().get_frame_on() for ax in res_legacy.figure.axes], before_frame)

        # Now apply legend_options to Q-Q and verify formatting + reset.
        apply_style(res_legacy.figure, {
            "title": "Formatted Q-Q",
            LEGEND_OPTIONS_KEY: {"frame": True, "reverse": True, "columns": 2, "title": "QQ Leg"},
        })
        for ax in res_legacy.figure.axes:
            leg = ax.get_legend()
            self.assertTrue(leg.get_frame_on())
            self.assertEqual(leg.get_title().get_text(), "QQ Leg")
            self.assertEqual(leg._ncols, 2)

        # FDR figure-level legend
        fdr_frame = pd.DataFrame({"P": [0.001, 0.01, 0.2, 0.7]})
        fdr_res = fdr_analysis(fdr_frame, {
            "p columns": ["P"],
            "FDR method": "Benjamini–Hochberg",
            "Desired FDR (%)": 5.0,
            "Family scope": "Each column separately",
            "Show diagnostic plot": True,
        })
        orig_fdr = [t.get_text() for t in fdr_res.figure.legends[0].get_texts()]
        apply_style(fdr_res.figure, {"title": "FDR Legacy"})
        self.assertEqual([t.get_text() for t in fdr_res.figure.legends[0].get_texts()], orig_fdr)
        apply_style(fdr_res.figure, {
            LEGEND_OPTIONS_KEY: {"reverse": True, "frame": True, "facecolor": "#eef2f7", "labels": {"fdr:threshold": "Limit"}},
        })
        self.assertEqual([t.get_text() for t in fdr_res.figure.legends[0].get_texts()],
                         list(reversed(["Limit", *orig_fdr[1:]])))

    def test_fdr_entry_keys_stay_stable_across_languages(self):
        prev = active_language()
        self.addCleanup(set_language, prev)
        fdr_frame = pd.DataFrame({"P": [0.001, 0.01, 0.2, 0.7]})
        opts = {
            "p columns": ["P"],
            "FDR method": "Benjamini–Hochberg",
            "Desired FDR (%)": 5.0,
            "Family scope": "Each column separately",
            "Show diagnostic plot": True,
        }
        set_language("en")
        en_keys = [e.key for e in collect_legend_entries(fdr_analysis(fdr_frame, opts).figure)]
        set_language("it")
        it_keys = [e.key for e in collect_legend_entries(fdr_analysis(fdr_frame, opts).figure)]
        self.assertEqual(en_keys, ["fdr:threshold", "fdr:discovery", "fdr:other"])
        self.assertEqual(it_keys, en_keys)

    def test_scatter_groups_int_1_and_str_1_remain_distinct_across_exclusion(self):
        frame = pd.DataFrame({
            "X": [1.0, 2.0, 3.0, 4.0],
            "Y": [2.0, 3.0, 5.0, 6.0],
            "Group": pd.Series([1, 1, "1", "1"], dtype=object),
        })
        ds = Dataset(frame)
        style = {
            LEGEND_OPTIONS_KEY: {
                "reverse": True,
                "labels": {"group:int:1": "Numeric 1", "group:str:1": "String '1'"},
            },
        }
        res_full = analyse("Scatter / confidence ellipse", ds.frame(mask_excluded=True),
                           {"X": "X", "Y": "Y", "Group": "Group"})
        apply_style(res_full.figure, style)
        self.assertEqual([t.get_text() for t in res_full.figure.axes[0].get_legend().get_texts()],
                         ["String '1'", "Numeric 1"])

        # Exclude all rows of numeric 1 -> group:str:1 still keeps its custom label!
        ds.excluded = {(0, 0), (1, 0)}
        res_partial = analyse("Scatter / confidence ellipse", ds.frame(mask_excluded=True),
                              {"X": "X", "Y": "Y", "Group": "Group"})
        apply_style(res_partial.figure, style)
        self.assertEqual([t.get_text() for t in res_partial.figure.axes[0].get_legend().get_texts()],
                         ["String '1'"])

    def test_alab_persistence_validation_and_layout_export(self):
        frame = pd.DataFrame({"X": [0.0, 1.0, 2.0], "A": [1.0, 2.0, 3.0], "B": [3.0, 2.0, 1.0]})
        ds = Dataset(frame)
        ds.analyses.append((XY_METHOD, {
            "X": "X",
            "Y columns": ["A", "B"],
            "Series style": {"A": "Line and points", "B": "Line and points"},
            "Series side": {"A": "Left", "B": "Right"},
        }))
        ds.graph_styles[0] = {
            LEGEND_OPTIONS_KEY: {
                "title": "Saved {Title} $1$",
                "columns": 2,
                "frame": True,
                "facecolor": "#f5f7fa",
                "edgecolor": "#224466",
                "width": 1.8,
                "alpha": 0.65,
                "reverse": True,
                "labels": {"xy:1:A": "Series $A$"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legend-test.alab"
            save_project(path, {"Study": ds})
            tables, _ = load_workspace(path)
            loaded_style = tables["Study"].graph_styles[0]
            self.assertEqual(loaded_style, ds.graph_styles[0])

            res = analyse(XY_METHOD, tables["Study"].frame(mask_excluded=True), tables["Study"].analyses[0][1])
            apply_style(res.figure, loaded_style)
            leg = res.figure.axes[0].get_legend()
            self.assertEqual(leg.get_title().get_text(), "Saved {Title} $1$")
            self.assertEqual([t.get_text() for t in leg.get_texts()], ["B", "Series $A$"])
            self.assertEqual(leg._ncols, 2)
            self.assertTrue(leg.get_frame_on())

            layout_fig = compose_layout("Legend Layout", 1, [res.figure])
            pdf_buf = BytesIO()
            res.figure.savefig(pdf_buf, format="pdf")
            doc = pdfium.PdfDocument(pdf_buf.getvalue())
            try:
                page = doc[0]
                textpage = page.get_textpage()
                pdf_text = textpage.get_text_range()
                textpage.close()
                page.close()
            finally:
                doc.close()
            self.assertIn("Saved {Title} $1$", pdf_text)
            self.assertIn("Series $A$", pdf_text)
            layout_buf = BytesIO()
            layout_fig.savefig(layout_buf, format="png")
            self.assertGreater(layout_buf.tell(), 0)

        with self.assertRaises(ValueError):
            validated_style({LEGEND_OPTIONS_KEY: {"columns": 0}})


if __name__ == "__main__":
    unittest.main()
