"""Qt integration tests for Pareto plot (dialog, Inspector, live edits, .alab reopen, EN/IT, export)."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "QtAgg")

import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi import pareto_plot as pp
from analisi.i18n import set_language
from analisi.presentation import graph_groups
from trama_qt.analysis_dialog import AnalysisDialog
from trama_qt.graph_format import GraphFormatDialog
from trama_qt.inspector import GraphInspector
from trama_qt.project import Project, compute
from trama_qt.window import GRAPHING, export_graph


FIXTURE = Path(__file__).resolve().parent / "data" / "pareto_plot" / "pareto.csv"


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


class QtParetoPlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-pareto-tests"])

    def tearDown(self):
        set_language("en")

    def test_in_graphing_and_new_graph_and_translations(self):
        self.assertIn(pp.METHOD, GRAPHING)
        frame = pd.read_csv(FIXTURE)
        for lang, expected_heading in (("en", "Pareto plot"), ("it", "Grafico di Pareto")):
            set_language(lang)
            dlg = AnalysisDialog(None, frame, only=list(GRAPHING), current=(pp.METHOD, {}))
            self.assertEqual(dlg.heading.text(), expected_heading)
            self.assertEqual(dlg.controls[pp.CATEGORY][1].currentData(), "Categoria")
            self.assertEqual(dlg.controls[pp.THRESHOLD][1].text(), "80")
            dlg.deleteLater()

    def test_dialog_validation_threshold_and_engine_error_translation(self):
        frame = pd.read_csv(FIXTURE)
        set_language("it")
        dlg = AnalysisDialog(None, frame, only=[pp.METHOD], current=(pp.METHOD, {}))
        dlg.show()
        # Invalid threshold 100 -> stays open, error banner in Italian, focuses Threshold.
        dlg.controls[pp.THRESHOLD][1].setText("100")
        dlg.accept()
        self.assertIsNone(dlg.result)
        self.assertTrue(dlg.banner.isVisible())
        self.assertEqual(dlg.error_field, pp.THRESHOLD)
        self.assertIn("soglia", dlg.banner.text().lower())

        # Blank threshold disables reference line cleanly.
        dlg.controls[pp.THRESHOLD][1].setText("")
        dlg.accept()
        self.assertIsNotNone(dlg.result)
        method, recipe = dlg.result
        self.assertEqual(method, pp.METHOD)
        self.assertEqual(recipe[pp.THRESHOLD], "")
        self.assertIsNone(recipe[pp.WEIGHT])
        dlg.deleteLater()

        # Reopening dialog with engine Weight error translates into Italian and focuses Weight.
        dlg_err = AnalysisDialog(
            None, frame, only=[pp.METHOD],
            current=(pp.METHOD, {pp.CATEGORY: "Categoria", pp.WEIGHT: "Peso", pp.THRESHOLD: 80.0}),
            error="Weight values cannot be negative.", error_field=pp.WEIGHT,
        )
        dlg_err.show()
        self.assertTrue(dlg_err.banner.isVisible())
        self.assertEqual(dlg_err.error_field, pp.WEIGHT)
        self.assertIn("negativi", dlg_err.banner.text().lower())
        dlg_err.deleteLater()

    def test_inspector_no_linked_axes_threshold_change_live_edit_alab_and_exports(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project = Project()
            titles = project.load(FIXTURE)
            title = titles[0]
            ds = project.tables[title]
            frame = ds.frame(mask_excluded=True)

            # 1. Create weighted Pareto with Threshold=80.
            recipe = {pp.CATEGORY: "Categoria", pp.WEIGHT: "Peso", pp.THRESHOLD: 80.0}
            run = project.candidate(title, pp.METHOD, recipe)
            result = compute(run, frame)
            idx, _ = project.add_result(run, result)
            run = project.runs[idx]
            self.assertEqual(len(run.result.figure.axes), 2)
            self.assertEqual(run.result.figure.axes[1].get_ylim(), (0.0, 100.0))
            self.assertEqual(run.result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"], "C")

            # 2. Inspector: no linked-axes controls, recolor category "A" without recalculation.
            result_before = run.result
            canvas = FigureCanvasQTAgg(run.result.figure)
            committed = []
            inspector = GraphInspector(
                run, canvas,
                confirmed=lambda: run.style or {},
                commit=lambda style: (committed.append(style), setattr(run, "style", style)),
                closed=lambda: None,
            )
            self.assertEqual(inspector.linked_widgets, [])
            self.assertTrue(inspector.select_group("pareto:cat:str:A"))
            inspector.fields["color"].setText("#2b8a73")
            inspector.fields["color"].editingFinished.emit()
            self.assertTrue(inspector.apply())
            inspector.deleteLater()
            self.assertIs(run.result, result_before)
            self.assertTrue(committed)
            ds.graph_styles[run.slot] = run.style

            # 3. Format Graph keeps secondary axis (0, 100) and group colors.
            fmt = GraphFormatDialog(None, run.result.figure.axes[0], run.style or {})
            fmt.texts["title"].setText("Pareto · Synthetic")
            fmt.accept()
            self.assertIsNotNone(fmt.result)
            run.style = fmt.result
            ds.graph_styles[run.slot] = run.style
            fmt.deleteLater()

            # 4. Change threshold to 50 -> B becomes threshold category.
            edited_recipe = {**recipe, pp.THRESHOLD: 50.0}
            cand = project.candidate(title, pp.METHOD, edited_recipe, index=idx)
            res_50 = compute(cand, frame)
            project.add_result(cand, res_50, index=idx)
            run = project.runs[idx]
            self.assertEqual(run.result.tables[pp.SETTINGS_SHEET]["Value"]["Threshold category"], "B")
            self.assertEqual(run.result.figure.axes[1].get_ylim(), (0.0, 100.0))

            # 5. Modify a frequency/weight in the worksheet without rewriting its order.
            original_order = ds.raw["Categoria"].tolist()
            ds.raw.loc[1, "Peso"] = 10  # A becomes 10 -> moves to rank 0.
            recalc = compute(run, ds.frame(mask_excluded=True))
            run.result = recalc
            self.assertEqual(ds.raw["Categoria"].tolist(), original_order)
            table_after = run.result.tables[pp.CATEGORIES_SHEET]
            self.assertEqual(table_after["Category"].tolist(), ["A", "B", "C", "Zero"])
            self.assertEqual(table_after["Cumulative percent"].iat[-1], 100.0)
            self.assertAlmostEqual(table_after["Cumulative percent"].iloc[0], 10.0 / 19.0 * 100.0, places=10)
            # Color still follows category A at rank 0.
            grp_a = graph_groups(run.result.figure.axes[0])[0]
            self.assertEqual(grp_a.key, "pareto:cat:str:A")
            self.assertAlmostEqual(float(grp_a.artists[0][0].get_facecolor()[0]), 0x2B / 255.0, places=2)

            # 6. Export CSV, PNG, SVG, PDF.
            csv_out = tmp_path / "pareto.csv"
            table_after.to_csv(csv_out, index=False)
            self.assertGreater(csv_out.stat().st_size, 20)
            for ext in ("png", "svg", "pdf"):
                out = tmp_path / f"pareto.{ext}"
                export_graph(run.result.figure, out)
                self.assertTrue(out.exists() and out.stat().st_size > 200, ext)

            # 7. Save .alab and reopen in IT: canonical EN options & style preserved.
            alab = tmp_path / "pareto-synthetic.alab"
            project.save(alab)
            set_language("it")
            reopened = Project()
            reopened.load(alab)
            self.assertEqual(len(reopened.runs), 1)
            re_run = reopened.runs[0]
            self.assertEqual(re_run.method, pp.METHOD)
            self.assertEqual(re_run.options, edited_recipe)
            re_res = compute(re_run, reopened.tables[re_run.title].frame(mask_excluded=True))
            pd.testing.assert_frame_equal(re_res.tables[pp.CATEGORIES_SHEET], table_after)
            self.assertEqual(re_res.figure.axes[1].get_ylim(), (0.0, 100.0))
            grp_a_re = graph_groups(re_res.figure.axes[0])[0]
            self.assertEqual(grp_a_re.key, "pareto:cat:str:A")
            self.assertAlmostEqual(float(grp_a_re.artists[0][0].get_facecolor()[0]), 0x2B / 255.0, places=2)


if __name__ == "__main__":
    unittest.main()
