"""Kaplan–Meier segmented time axis on the Qt window, offscreen."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
except ImportError:  # PySide6 missing, or libEGL/libGL missing on headless machines.
    QApplication = None

from analisi.axis_breaks import AXIS_BREAKS, P_KM_AXIS, P_PANELS, P_PLOT_FRACTIONS, axis_breaks_reason, segment_axes
from analisi.axis_guides import AXIS_GUIDES
from analisi.graph_annotations import ANNOTATIONS
from analisi.i18n import active_language, set_language, tr
from tests import test_qt_shell as shell

KM_DATA = pd.DataFrame({
    "Tempo": [1, 2, 4, 14, 16, 20, 2, 3, 5, 12, 16, 18, 21],
    "Evento": [1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0],
    "Gruppo": ["Controllo"] * 6 + ["Trattamento"] * 7,
})
EXPECTED_TICKS = [0.0, 2.0, 4.0, 12.0, 14.0, 16.0, 18.0, 20.0]
EXPECTED_RISK = {
    "Controllo": [6, 5, 4, 3, 3, 2, 1, 1],
    "Trattamento": [7, 7, 5, 4, 3, 3, 2, 1],
}
EXPECTED_SURV = {
    "Controllo": [1.0, 5 / 6, 5 / 8, 5 / 8, 5 / 8, 5 / 16, 5 / 16, 5 / 16],
    "Trattamento": [1.0, 6 / 7, 6 / 7, 18 / 35, 18 / 35, 18 / 35, 9 / 35, 9 / 35],
}
BREAKS_TWO = {
    "axis": "x", "gap": 0.04,
    "segments": [
        {"low": 0.0, "high": 4.0, "share": 40.0, "major_step": 2.0},
        {"low": 12.0, "high": 20.0, "share": 60.0, "major_step": 2.0},
    ],
}


def _fill_break_dialog(dialog, *, axis="x", gap="0,04", segments=()):
    dialog.axis.set(axis)
    if not axis:
        return
    dialog.count.set(str(len(segments)))
    dialog.gap.setText(str(gap))
    for row, seg in enumerate(segments):
        for key in ("low", "high", "share", "major_step"):
            val = seg.get(key)
            dialog.cells[(row, key)].setText("" if val is None else str(val).replace(".", ","))


def _svg_snapshot(figure):
    import io
    import matplotlib as mpl

    buf = io.BytesIO()
    with mpl.rc_context({"svg.fonttype": "none"}):
        figure.savefig(buf, format="svg")
    root = ET.fromstring(buf.getvalue())
    ids = [el.attrib["id"] for el in root.iter() if "id" in el.attrib]
    labels = {}
    counts = {}
    for el in root.iter():
        gid = el.attrib.get("id", "")
        text = "".join(el.itertext()).strip()
        if gid.startswith("risk-label-"):
            labels[gid] = text
        elif gid.startswith("risk-count-"):
            counts[gid] = text
    return ids, labels, counts


def _eval_step_at_times(line, times):
    xs = np.asarray(line.get_xdata(), dtype=float)
    ys = np.asarray(line.get_ydata(), dtype=float)
    out = []
    for t in times:
        idx = np.searchsorted(xs, t, side="right") - 1
        out.append(float(ys[max(idx, 0)]))
    return out


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtKaplanMeierAxisBreaksTests(unittest.TestCase):
    setUpClass = classmethod(shell.QtShellTests.setUpClass.__func__)
    setUp = shell.QtShellTests.setUp
    _close = shell.QtShellTests._close
    wait = shell.QtShellTests.wait
    run_method = shell.QtShellTests.run_method
    reopen = shell.QtShellTests.reopen
    format_with = shell.QtShellTests.format_with

    def _open_km_sheet(self):
        csv_path = self.folder / "tempi.csv"
        if not csv_path.exists():
            KM_DATA.to_csv(csv_path, index=False)
        self.window.open_path(csv_path)
        self.app.processEvents()
        self.assertEqual(self.window.selected, ("data", "tempi"))

    def _km_sheet_and_run(self, **extra_options):
        if "tempi" not in self.window.project.tables:
            self._open_km_sheet()
        else:
            self.window.show_sheet("data", "tempi")
        options = {
            "Time": "Tempo", "Event columns": ["Evento"], "Grouping variables": ["Gruppo"],
            "Show risk table below graph": True, "Uncertainty": "Pointwise confidence band",
            "Display units": "Fraction", "Observation markers": "Censored observations",
            **extra_options,
        }
        return self.run_method("Kaplan–Meier survival", options)

    def test_format_dialog_preview_cancel_apply_save_reopen_recalc_and_undo(self):
        from trama_qt.axis_breaks import AxisBreaksDialog
        from trama_qt.graph_format import GraphFormatDialog

        window = self.window
        previous_lang = active_language()
        set_language("it")
        self.addCleanup(set_language, previous_lang)

        run = self._km_sheet_and_run()
        self.assertEqual(len(segment_axes(run.result.figure)), 0)

        def drive_preview_then_cancel(dialog):
            axes = run.result.figure.axes[0]
            # First verify only X axis choices and negative limit validation via AxisBreaksDialog directly.
            editor = AxisBreaksDialog(dialog, axes, {}, preview=lambda rec: dialog._preview_axis_breaks(rec, prior={}))
            self.assertEqual([editor.axis.itemData(i) for i in range(editor.axis.count())], ["", "x"])
            _fill_break_dialog(editor, segments=[
                {"low": -1, "high": 4, "share": 40, "major_step": 2},
                {"low": 12, "high": 20, "share": 60, "major_step": 2},
            ])
            editor.accept()
            self.assertIsNone(editor.result)
            self.assertEqual(editor.problem.objectName(), "errorBanner")
            self.assertIs(editor.focusWidget(), editor.cells[(0, "low")])

            # Valid values -> Preview draws 2 panels, Cancel restores single panel.
            _fill_break_dialog(editor, segments=BREAKS_TWO["segments"])
            self.assertTrue(editor.preview())
            self.assertEqual(len(segment_axes(run.result.figure)), 2)
            editor.reject()
            self.assertEqual(segment_axes(run.result.figure), [])

            # Reopen and apply breaks via edit_breaks mock.
            def apply_editor(dlg):
                _fill_break_dialog(dlg, segments=BREAKS_TWO["segments"])
                dlg.accept()
                return QDialog.DialogCode.Accepted

            with mock.patch.object(AxisBreaksDialog, "exec", apply_editor):
                dialog.edit_breaks()
            self.assertEqual(dialog.breaks_summary.text(), tr("axis_breaks.summary", axis="X", count=2))
            self.assertFalse(dialog.axis_fields["x"]["min"].isEnabled())
            self.assertFalse(dialog.scales["x"].isEnabled())

        style = self.format_with(run, drive_preview_then_cancel)
        self.assertEqual(style[AXIS_BREAKS]["segments"][0]["share"], 40.0)
        panels = segment_axes(run.result.figure)
        self.assertEqual(len(panels), 2)
        self.assertEqual([p.get_xlim() for p in panels], [(0.0, 4.0), (12.0, 20.0)])

        # Exact curve values and risk counts at ticks (including jump at 12 and censor at 14).
        lines_p1 = {l.get_label(): l for l in panels[0].lines if l.get_label() in EXPECTED_SURV}
        for name, expected in EXPECTED_SURV.items():
            np.testing.assert_allclose(_eval_step_at_times(lines_p1[name], EXPECTED_TICKS), expected, rtol=1e-12)
        ids, labels, counts = _svg_snapshot(run.result.figure)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(list(labels.values()), ["At risk", "Controllo", "Trattamento"])
        self.assertEqual([int(counts[f"risk-count-1-0-{c}"]) for c in range(8)], EXPECTED_RISK["Controllo"])
        self.assertEqual([int(counts[f"risk-count-1-1-{c}"]) for c in range(8)], EXPECTED_RISK["Trattamento"])

        # Add an unbroken comparison KM run on the same sheet so we can verify sheet parity after edits.
        full_run = self._km_sheet_and_run()

        # Save .alab, reopen, edit an event inside the omitted (4, 12) stretch (t=5, row 8: Evento 1 -> 0).
        alab = self.folder / "km_segmenti.alab"
        window.project.save(alab)
        self.reopen(alab)
        broken_idx = next(i for i, r in enumerate(window.project.runs) if r.style and AXIS_BREAKS in r.style)
        full_idx = next(i for i, r in enumerate(window.project.runs) if r.method == "Kaplan–Meier survival" and i != broken_idx)
        window.open_sheet(("graph", broken_idx))
        self.wait()
        self.assertEqual(len(segment_axes(window.project.runs[broken_idx].result.figure)), 2)

        # Edit row 8 ("Tempo"=5, "Evento"=1 -> 0) through the worksheet edit path (supports Undo/Redo).
        sheet_name = window.project.runs[broken_idx].title
        window.show_sheet("data", sheet_name)
        model = window.sheet.model()
        col_evento = list(window.project.tables[sheet_name].raw.columns).index("Evento")
        idx_cell = model.index(8, col_evento)
        self.assertEqual(str(model.data(idx_cell, Qt.ItemDataRole.DisplayRole)), "1")
        self.assertTrue(model.setData(idx_cell, "0"))
        self.app.processEvents()
        self.wait()
        window.open_sheet(("graph", broken_idx))
        self.wait()
        window.open_sheet(("graph", full_idx))
        self.wait()

        broken_run = window.project.runs[broken_idx]
        unbroken_run = window.project.runs[full_idx]
        # Numerical tables match identically with and without axis breaks.
        for tname in ("Number at risk", "Survival summary", "Curve: Controllo", "Curve: Trattamento", "Log-rank test"):
            pd.testing.assert_frame_equal(broken_run.result.tables[tname], unbroken_run.result.tables[tname])
        # Turning omitted t=5 event into a censor increases late survival probabilities in [12, 20] cleanly.
        b_lines = {l.get_label(): l for l in segment_axes(broken_run.result.figure)[0].lines if l.get_label() in EXPECTED_SURV}
        u_lines = {l.get_label(): l for l in unbroken_run.result.figure.axes[0].lines if l.get_label() in EXPECTED_SURV}
        np.testing.assert_allclose(
            _eval_step_at_times(b_lines["Trattamento"], EXPECTED_TICKS),
            [1.0, 6 / 7, 6 / 7, 9 / 14, 9 / 14, 9 / 14, 9 / 28, 9 / 28],
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            _eval_step_at_times(b_lines["Trattamento"], EXPECTED_TICKS),
            _eval_step_at_times(u_lines["Trattamento"], EXPECTED_TICKS),
            rtol=1e-12,
        )
        # Undo and Redo recalculate consistently.
        window.undo()
        self.wait()
        window.open_sheet(("graph", broken_idx))
        self.wait()
        b_rev = {l.get_label(): l for l in segment_axes(window.project.runs[broken_idx].result.figure)[0].lines
                 if l.get_label() in EXPECTED_SURV}
        np.testing.assert_allclose(_eval_step_at_times(b_rev["Trattamento"], EXPECTED_TICKS), EXPECTED_SURV["Trattamento"], rtol=1e-12)
        window.undo(redo=True)
        self.wait()
        window.open_sheet(("graph", broken_idx))
        self.wait()
        b_redone = {l.get_label(): l for l in segment_axes(window.project.runs[broken_idx].result.figure)[0].lines
                    if l.get_label() in EXPECTED_SURV}
        np.testing.assert_allclose(
            _eval_step_at_times(b_redone["Trattamento"], EXPECTED_TICKS),
            [1.0, 6 / 7, 6 / 7, 9 / 14, 9 / 14, 9 / 14, 9 / 28, 9 / 28],
            rtol=1e-12,
        )
        # Moving t=5 out of the omitted stretch to t=15 also changes visible risk-table counts at t=12, 14.
        col_tempo = list(window.project.tables[sheet_name].raw.columns).index("Tempo")
        window.show_sheet("data", sheet_name)
        self.assertTrue(window.sheet.model().setData(window.sheet.model().index(8, col_tempo), "15"))
        self.app.processEvents()
        self.wait()
        window.open_sheet(("graph", broken_idx))
        self.wait()
        _ids, _labels, moved_counts = _svg_snapshot(window.project.runs[broken_idx].result.figure)
        self.assertEqual([int(moved_counts[f"risk-count-1-1-{c}"]) for c in range(8)], [7, 7, 5, 5, 4, 3, 2, 1])

    def test_inspector_three_segments_shared_boundary_and_removal(self):
        from trama_qt.axis_breaks import AxisBreaksDialog

        window = self.window
        run = self._km_sheet_and_run()
        idx = window.project.runs.index(run)
        window.open_sheet(("graph", idx))
        window.inspector_wanted = True
        window.show_sheet("graph", idx)
        self.wait()
        inspector = window.inspector
        self.assertIsNotNone(inspector)
        self.assertTrue(hasattr(inspector, "breaks_button"))

        three = [
            {"low": 0.0, "high": 4.0, "share": 30.0, "major_step": 2.0},
            {"low": 12.0, "high": 16.0, "share": 35.0, "major_step": 2.0},
            {"low": 18.0, "high": 22.0, "share": 35.0, "major_step": 2.0},
        ]

        def set_three(dialog):
            _fill_break_dialog(dialog, segments=three)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AxisBreaksDialog, "exec", set_three):
            inspector.edit_breaks()
        self.assertEqual(len(segment_axes(run.result.figure)), 3)
        self.assertFalse(inspector.widgets["xmin"].isEnabled())
        self.assertFalse(inspector.widgets["xscale"].isEnabled())

        # Shared boundary via Inspector (0-4 and 4-20) -> Cancel preview restores 3 panels, Apply commits 2.
        shared = [
            {"low": 0.0, "high": 4.0, "share": 35.0, "major_step": 2.0},
            {"low": 4.0, "high": 20.0, "share": 65.0, "major_step": 4.0},
        ]

        def preview_then_cancel(dialog):
            _fill_break_dialog(dialog, segments=shared)
            self.assertTrue(dialog.preview())
            self.assertEqual(len(segment_axes(run.result.figure)), 2)
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with mock.patch.object(AxisBreaksDialog, "exec", preview_then_cancel):
            inspector.edit_breaks()
        self.assertEqual(len(segment_axes(run.result.figure)), 3)

        def set_shared(dialog):
            _fill_break_dialog(dialog, segments=shared)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AxisBreaksDialog, "exec", set_shared):
            inspector.edit_breaks()
        self.assertEqual(len(segment_axes(run.result.figure)), 2)
        self.assertTrue(inspector.apply())
        self.assertEqual(len(run.style[AXIS_BREAKS]["segments"]), 2)

        # Remove breaks -> full axis and X limit/scale fields return.
        def clear_breaks(dialog):
            dialog.axis.set("")
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AxisBreaksDialog, "exec", clear_breaks):
            inspector.edit_breaks()
        self.assertEqual(segment_axes(run.result.figure), [])
        self.assertTrue(inspector.widgets["xmin"].isEnabled())
        self.assertTrue(inspector.widgets["xscale"].isEnabled())
        self.assertTrue(inspector.apply())
        self.assertNotIn(AXIS_BREAKS, run.style)

    def test_percent_hall_wellner_manual_tick_and_layout_vector_svg_verification(self):
        import uuid
        from analisi.figure_export import export_figure, export_pdf_bundle
        from analisi.layout_svg import export_layout_svg
        from analisi.presentation import AUTO_PAPER, Layout, apply_style

        window = self.window
        run = self._km_sheet_and_run(Uncertainty="Hall–Wellner simultaneous band", **{"Display units": "Percent"})
        guide_id = str(uuid.uuid4())
        window.project.apply_format(run, {
            AXIS_BREAKS: deepcopy(BREAKS_TWO),
            AXIS_GUIDES: [{"id": guide_id, "axis": "x", "value": 15.0, "label": "15", "tick": True, "line": True}],
        })
        panels = segment_axes(run.result.figure)
        self.assertEqual(len(panels), 2)
        self.assertIn(15.0, panels[1].get_xticks())

        # Standalone SVG/PDF/PNG + Layout SVG/PDF/PNG exports & cell alignment verification.
        fig_svg = self.folder / "km_pct.svg"
        fig_pdf = self.folder / "km_pct.pdf"
        fig_png = self.folder / "km_pct.png"
        export_figure(run.result.figure, fig_svg, {"format": "svg", "svg_text": "text"})
        export_figure(run.result.figure, fig_pdf, {"format": "pdf"})
        export_figure(run.result.figure, fig_png, {"format": "png", "dpi": 150})
        for p in (fig_svg, fig_pdf, fig_png):
            self.assertGreater(p.stat().st_size, 0)

        root = ET.parse(fig_svg).getroot()
        ids = [el.attrib["id"] for el in root.iter() if "id" in el.attrib]
        self.assertEqual(len(ids), len(set(ids)))

        layout = Layout("Layout KM", 1, [run.reference], paper=AUTO_PAPER)
        lay_svg = self.folder / "layout_km.svg"
        lay_pdf = self.folder / "layout_km.pdf"
        lay_png = self.folder / "layout_km.png"
        window.project.export_layout(layout, lay_svg, {"format": "svg", "svg_text": "text"})
        window.project.export_layout(layout, lay_pdf, {"format": "pdf"})
        window.project.export_layout(layout, lay_png, {"format": "png", "dpi": 120})
        for p in (lay_svg, lay_pdf, lay_png):
            self.assertGreater(p.stat().st_size, 0)
        lroot = ET.parse(lay_svg).getroot()
        lids = [el.attrib["id"] for el in lroot.iter() if "id" in el.attrib]
        self.assertEqual(len(lids), len(set(lids)))
        # Verify Layout SVG keeps unique single-column risk labels and all 18 risk cells (including tick 15).
        lrisk_labels = [el for el in lroot.iter() if "risk-label-" in el.attrib.get("id", "")]
        lrisk_counts = [el for el in lroot.iter() if "risk-count-" in el.attrib.get("id", "")]
        self.assertEqual(len(lrisk_labels), 3)
        self.assertEqual(len(lrisk_counts), 18)

    def test_incompatibilities_keep_saved_breaks_and_show_info_banner(self):
        from trama_qt.graph_format import GraphFormatDialog

        window = self.window
        # 1. Single-panel KM with breaks, then switched to probability Y scale -> kept & #infoBanner shown.
        run = self._km_sheet_and_run()
        window.project.apply_format(run, {AXIS_BREAKS: deepcopy(BREAKS_TWO), "yscale": "probability"})
        self.assertEqual(run.style[AXIS_BREAKS], BREAKS_TWO)
        self.assertEqual(segment_axes(run.result.figure), [])
        self.assertIsNotNone(axis_breaks_reason(run.result.figure))
        style, xy = window.project.format_inputs(run)
        fmt = GraphFormatDialog(window, run.result.figure.axes[0], style, xy=xy)
        self.assertEqual(fmt.breaks_note.objectName(), "infoBanner")
        self.assertFalse(fmt.breaks_note.isHidden())
        self.assertTrue(fmt.breaks_button.isEnabled())
        fmt.reject()

        # Also check Inspector shows #infoBanner cleanly when saved breaks are incompatible (without spurious draft).
        idx = window.project.runs.index(run)
        window.inspector_wanted = True
        window.open_sheet(("graph", idx))
        window.show_sheet("graph", idx)
        self.wait()
        self.assertFalse(window.inspector.has_draft)
        self.assertEqual(window.inspector.breaks_note.objectName(), "infoBanner")
        self.assertFalse(window.inspector.breaks_note.isHidden())
        window.inspector_wanted = False

        # 2. Multi-panel KM (weighted log-rank detail) blocks with P_PANELS and #infoBanner while preserving saved breaks.
        window.show_sheet("data", "tempi")
        wlr = self.run_method("Kaplan–Meier survival", {
            "Time": "Tempo", "Event columns": ["Evento"], "Grouping variables": ["Gruppo"],
            "Curve comparison": "Tarone–Ware", "Weight detail": True, "Show risk table below graph": True,
        })
        window.project.apply_format(wlr, {AXIS_BREAKS: deepcopy(BREAKS_TWO)})
        self.assertEqual(axis_breaks_reason(wlr.result.figure), P_PANELS)
        style, xy = window.project.format_inputs(wlr)
        fmt_wlr = GraphFormatDialog(window, wlr.result.figure.axes[0], style, xy=xy)
        self.assertEqual(fmt_wlr.breaks_note.objectName(), "infoBanner")
        fmt_wlr.reject()

    def test_dialogs_fit_1024x768_keyboard_tab_enter_f1_themes_and_languages(self):
        from trama_qt import theme
        from trama_qt.axis_breaks import AxisBreaksDialog
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.shortcuts_dialog import ShortcutsDialog

        window = self.window
        run = self._km_sheet_and_run()
        axes = run.result.figure.axes[0]
        previous_lang = active_language()
        self.addCleanup(set_language, previous_lang)
        self.addCleanup(theme.apply, self.app, dark=False)

        for lang in ("it", "en"):
            set_language(lang)
            for mode in ("light", "dark"):
                theme.apply(self.app, dark=(mode == "dark"))
                style, xy = window.project.format_inputs(run)
                fmt = GraphFormatDialog(window, axes, style, xy=xy)
                self.assertLessEqual(fmt.width(), 1024)
                self.assertLessEqual(fmt.height(), 768)
                editor = AxisBreaksDialog(fmt, axes, {}, preview=lambda _r: None)
                self.assertLessEqual(editor.width(), 1024)
                self.assertLessEqual(editor.height(), 768)
                self.assertFalse(editor.suggest_button.autoDefault())
                self.assertFalse(editor.preview_button.autoDefault())
                editor.show()
                self.app.processEvents()
                # Tab navigation advances cleanly; Enter on the form submits Apply rather than secondary buttons.
                editor.axis.set("x")
                editor.cells[(0, "low")].setFocus()
                before = editor.focusWidget()
                QTest.keyClick(before, Qt.Key.Key_Tab)
                self.assertIsNot(editor.focusWidget(), before)
                _fill_break_dialog(editor, segments=BREAKS_TWO["segments"])
                QTest.keyClick(editor.cells[(1, "share")], Qt.Key.Key_Return)
                self.assertEqual(editor.result, BREAKS_TWO)
                fmt.reject()

        # F1 opens ShortcutsDialog from MainWindow.
        from PySide6.QtGui import QKeySequence
        self.assertEqual(window.actions["help_shortcuts"].shortcut(), QKeySequence("F1"))
        opened = []
        with mock.patch.object(ShortcutsDialog, "exec", lambda dlg: opened.append(True) or QDialog.DialogCode.Rejected):
            window.actions["help_shortcuts"].trigger()
        self.assertTrue(opened)


if __name__ == "__main__":
    unittest.main()
