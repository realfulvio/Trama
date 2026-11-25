"""The Qt window end to end, offscreen: open, edit, analyse, graph, save, reopen, export.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
from base64 import b64encode
from math import ceil
from pathlib import Path
from struct import pack
import tempfile
import time
import unittest

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import tr

ROOT = Path(__file__).resolve().parent.parent


def _vector_record(data, fmt="emf"):
    return {"format": fmt, "data": b64encode(data).decode("ascii")}


def _emf_drawing(records, count=1):
    header = pack("<II8i4sIII", 1, 108, 0, 0, 120, 80,
                  0, 0, 5080, 3387, b" EMF", 0x10000, 128 + len(records), count + 2)
    return header.ljust(108, b"\0") + records + pack("<5I", 14, 20, 0, 0, 20)


def _emf_layout(first=(10, 10, 100, 60), second=(120, 80, 100, 60)):
    inner = _emf_drawing(pack("<II4i", 43, 24, 4, 6, 12, 18))
    image_size = len(inner) + 28
    obj = pack("<HH6I", 0x4008, 0x0501, image_size, image_size - 12,
               0xDBC01001, 2, 4, len(inner)) + inner
    draw = pack("<HH4I4f", 0x401A, 0x4001, 44, 32, 0xFFFFFFFF, 2, 0, 0, 120, 80)
    commands = obj + draw + pack("<4h", *first) + draw + pack("<4h", *second)
    return _emf_drawing(pack("<III4s", 70, 16 + len(commands), 4 + len(commands), b"EMF+") + commands)


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        # A failed calculation reopens the dialog; in a test it must fail instead of waiting for a click.
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def test_curve_pipeline_shows_only_applicable_fields_and_saves_canonical_values(self):
        from PySide6.QtWidgets import QLabel
        from analisi import curve_pipeline as cp
        from analisi.curve_pipeline_dialog import NOTE_KEYS
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog

        self.addCleanup(set_language, active_language())
        set_language("it")
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4], "Y": [1, 2, 3, 4, 5]})
        dialog = AnalysisDialog(self.window, frame, only=cp.CURVE_METHOD)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        def choose(field, value):
            widget = dialog.controls[field][1]
            widget.setCurrentIndex(widget.findData(value))

        def shown_notes():
            return [note.text() for note in dialog.findChildren(QLabel)
                    if not note.isHidden() and note.text() in {tr(key) for key in NOTE_KEYS}]

        choose("X", "X")
        choose("Y", "Y")
        dialog.controls["LOWESS fraction"][1].setText("0,6")
        self.assertEqual(dialog.options(), {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": 0.6})
        self.assertEqual(shown_notes(), [])

        choose("Method", cp.PIPELINE)
        self.assertEqual(shown_notes(), [tr(NOTE_KEYS[0])])
        choose(cp.OPERATION, cp.CUMULATIVE)
        choose(cp.SMOOTHING, cp.SAVITZKY_GOLAY)
        dialog.controls[cp.BASELINE][1].setText("1,25")
        self.assertEqual(shown_notes(), [tr(key) for key in NOTE_KEYS])
        self.assertEqual(set(dialog.options()), {"X", "Y", "Method", *cp.PIPELINE_FIELDS})
        choose("Method", "LOWESS")
        self.assertEqual(dialog.options()["LOWESS fraction"], 0.6)
        choose("Method", cp.PIPELINE)
        dialog.run_button.click()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        method, options = dialog.result
        self.assertEqual(method, cp.CURVE_METHOD)
        self.assertEqual(options[cp.BASELINE], 1.25)
        self.assertEqual(options[cp.SMOOTHING], cp.SAVITZKY_GOLAY)

    def test_analysis_column_search_finds_literal_names_and_preserves_checked_factors(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel, QLineEdit
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.strings import qt

        data = {"Response": [1., 2., 4., 8.], "Group": ["A", "B"] * 2,
                "Dòse [$]": ["Low", "Low", "High", "High"]}
        data.update({f"Batch {i}": ["M", "N"] * 2 for i in range(12)})
        dialog = AnalysisDialog(self.window, pd.DataFrame(data), only="Multifactor ANOVA",
                                current=("Multifactor ANOVA", {"Response": "Response", "Factors": ["Group", "Dòse [$]"]}))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        search = dialog.findChild(QLineEdit, "analysisColumnSearch")
        self.assertIsNotNone(search)
        self.assertTrue(search.isClearButtonEnabled())
        before = dialog.options()
        factors = dialog.controls["Factors"][1]
        height = factors.maximumHeight()
        search.setText("dose [$]")
        visible = [factors.item(i).text() for i in range(factors.count()) if not factors.item(i).isHidden()]
        self.assertEqual(visible, ["Dòse [$]"])
        self.assertLess(factors.maximumHeight(), height)
        caption = dialog.rows["Factors"][0].text()
        hidden = qt("qt.filtered_selection", fields=f"{caption} (1)")
        self.assertIn(hidden, [label.text() for label in dialog.findChildren(QLabel) if label.isVisible()])
        self.assertEqual(dialog.options(), before)
        search.setFocus()
        QTest.keyClick(search, Qt.Key.Key_Return)
        self.assertIs(dialog.focusWidget(), factors)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(factors.currentItem().text(), "Dòse [$]")
        search.clear()
        self.assertTrue(all(not factors.item(i).isHidden() for i in range(factors.count())))
        self.assertEqual(factors.maximumHeight(), height)

    def test_paired_proportions_accepts_both_input_formats_and_reopens_the_recipe(self):
        from unittest.mock import patch
        from analisi import paired_proportions as paired
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        counts = [[2, 5], [1, 3]]
        observations = [(before, after) for before in range(2) for after in range(2)
                        for _ in range(counts[before][after])]
        titles = self.window.project.add_tables({
            "Observations": pd.DataFrame(observations, columns=["Before", "After"]),
            "Matrix": pd.DataFrame({"Negative": [2, 1], "Positive": [5, 3]}),
        })

        def accept(dialog):
            dialog.show()
            self.app.processEvents()
            field = dialog.controls[paired.FORMAT][1]
            is_matrix = self.window.selected == ("data", titles[1])
            if is_matrix:
                field.setCurrentIndex(field.findData(paired.COUNT_MATRIX))
                self.assertEqual(field.currentText(), "Matrice dei conteggi")
                self.assertTrue(set(paired.OBSERVATION_FIELDS).isdisjoint(dialog.options()))
            else:
                self.assertEqual(field.currentText(), "Osservazioni")
                self.assertTrue(set(paired.MATRIX_FIELDS).isdisjoint(dialog.options()))
                if dialog.error_field is None:
                    self.assertEqual(dialog.options()[paired.POSITIVE], "1")
                    dialog.controls[paired.POSITIVE][1].setText("0")
                else:
                    self.assertEqual(dialog.error_field, paired.POSITIVE)
                    self.assertIs(dialog.focusWidget(), dialog.controls[paired.POSITIVE][1])
                    self.assertIn("Valore positivo", dialog.banner.text())
                    self.assertEqual(dialog.options()[paired.POSITIVE], "0")
                    dialog.controls[paired.POSITIVE][1].setText("1")
            dialog.controls[paired.GRAPH][1].setChecked(True)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return dialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", accept):
            for title in titles:
                self.window.show_sheet("data", title)
                self.window.analyze(method=paired.PAIRED_PROPORTIONS)
                self.wait()

        recipes = [run.options for run in self.window.project.runs]
        self.assertEqual([recipe[paired.FORMAT] for recipe in recipes], [paired.OBSERVATIONS, paired.COUNT_MATRIX])
        for run in self.window.project.runs:
            self.assertEqual(run.result.tables[paired.REPORT_SHEET].at["p", "Value"], 0.21875)
            self.assertEqual(run.result.tables[paired.COUNTS_SHEET].values.tolist(), counts)
            self.assertIsNotNone(run.result.figure)
        path = self.folder / "paired.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        for index, run in enumerate(self.window.project.runs):
            self.window.open_sheet(("result", index))
            self.wait()
            self.assertEqual(run.options, recipes[index])
            self.assertEqual(run.result.tables[paired.REPORT_SHEET].at["p", "Value"], 0.21875)

    def test_power_planning_from_an_empty_project(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog
        from analisi import power_plan as power
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        action = self.window.actions["power"]
        self.assertTrue(action.isEnabled())

        with patch.object(AnalysisDialog, "exec", return_value=AnalysisDialog.DialogCode.Rejected):
            action.trigger()
        self.assertFalse(self.window.project.tables)
        self.assertFalse(self.window.project.dirty)

        def plan(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertEqual([dialog.tabs.tabText(i) for i in range(3)], ["Disegno", "Effetto", "Curva"])
            for key, value in ((power.DESIGN, "Independent t"), (power.EFFECT_INPUT, power.MEANS)):
                box = dialog.controls[key][1]
                box.setCurrentIndex(box.findData(value))
            for key, text in ((power.MEAN_A, "5"), (power.MEAN_B, "7"), (power.COMMON_SD, "4,0"),
                              (power.TARGET, "0,8"), (power.SIZE, "unused"), (power.ALLOCATION, "2/3")):
                dialog.controls[key][1].setText(text)
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, power.ALLOCATION)
            self.assertIs(dialog.focusWidget(), dialog.controls[power.ALLOCATION][1])
            self.assertIn("Allocazione A:B", dialog.banner.text())
            dialog.controls[power.ALLOCATION][1].setText("4:6")
            dialog.controls[power.SHOW_CURVE][1].setChecked(True)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", plan):
            action.trigger()
            self.wait()
        self.assertEqual(len(self.window.project.tables), 1)
        run, = self.window.project.runs
        self.assertEqual(run.options[power.ALLOCATION], "2:3")
        self.assertEqual(run.options[power.TARGET], .8)
        self.assertNotIn(power.SIZE, run.options)
        expected = (54, 81, 135, .8066126132756494)  # Frozen independent oracle for the 2:3 design.
        report = run.result.tables[power.METHOD]["Value"]
        for label, value in zip(("N A", "N B", "Total N", "Power"), expected):
            self.assertAlmostEqual(report[label], value, places=10)
        self.assertIn(power.CURVE_SHEET, run.result.tables)
        recipe = run.options.copy()
        path = self.folder / "power.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        run, = self.window.project.runs
        self.assertEqual(run.options, recipe)
        matches = self.window.navigator.findItems(run.name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        self.assertIn(("graph", 0), [item.data(0, Qt.ItemDataRole.UserRole) for item in matches])
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertEqual(run.result.tables[power.METHOD]["Value"].tolist(), report.tolist())
        svg = self.folder / "power.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        self.assertIn("<svg", svg.read_text(encoding="utf-8"))

    def test_power_planning_accepts_multiline_means(self):
        from analisi import power_plan as power
        from trama_qt.analysis_dialog import AnalysisDialog

        dialog = AnalysisDialog(self.window, pd.DataFrame(), current=(power.METHOD, {}), only=power.METHOD)
        self.addCleanup(dialog.deleteLater)
        for key, value in ((power.DESIGN, "One-way ANOVA"), (power.EFFECT_INPUT, power.MEANS)):
            box = dialog.controls[key][1]
            box.setCurrentIndex(box.findData(value))
        dialog.controls[power.GROUP_MEANS][1].setPlainText("12\n13,5\n15\n16")
        dialog.controls[power.COMMON_SD][1].setText("5")
        dialog.controls[power.TARGET][1].setText("0,85")
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        self.assertEqual(dialog.result[1][power.GROUP_MEANS], "12; 13.5; 15; 16")
        self.assertNotIn(power.GROUPS, dialog.result[1])

    def test_cox_diagnostics_produce_the_chosen_graph_and_preserve_the_exact_ties_boundary(self):
        import json
        from unittest.mock import patch
        from analisi import cox_exact, cox_fit_diagnostics as dx, cox_outputs as cox
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "cox-fit-diagnostics"
        self.window.open_path(source / "followup.csv")

        def accept(dialog):
            dialog.show()
            self.app.processEvents()

            def choose(name, value):
                box = dialog.controls[name][1]
                position = box.findData(value)
                self.assertGreaterEqual(position, 0, (name, value))
                box.setCurrentIndex(position)

            for name, roles in (("Predictors", ("Dose", "Arm")), ("Categorical predictors", ("Arm",))):
                box = dialog.controls[name][1]
                for index in range(box.count()):
                    item = box.item(index)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in roles else Qt.CheckState.Unchecked)
            choose(cox.GRAPH, dx.SCALED_GRAPH)
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, cox.GRAPH)
            self.assertEqual(dialog.tabs.tabText(dialog.tabs.currentIndex()), "Diagnostica")
            self.assertIn("residui di schoenfeld", dialog.banner.text().lower())
            dialog.controls[dx.SCALED][1].setChecked(True)
            dialog.controls[dx.COX_SNELL][1].setChecked(True)
            choose(cox_exact.TIES, cox_exact.EXACT)
            dialog.run_button.click()
            self.assertEqual(dialog.error_field, dx.SCALED)
            self.assertIs(dialog.focusWidget(), dialog.controls[dx.SCALED][1])
            choose(cox_exact.TIES, "Efron")
            choose(cox.GRAPH_TERM, "Arm [B]")
            choose(dx.X_AXIS, dx.SOURCE_ROW)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", accept):
            self.window.analyze(method=cox.METHOD)
            self.wait()
        run, = self.window.project.runs
        frozen = json.loads((source / "expected.json").read_text(encoding="utf-8"))["Efron"]
        for sheet, key in ((dx.SCALED_SHEET, "scaled"), (dx.SNELL_SHEET, "snell"), (dx.SNELL_HAZARD_SHEET, "hazard")):
            table = run.result.tables[sheet]
            pd.testing.assert_frame_equal(table, pd.DataFrame(frozen[key]).astype(table.dtypes.to_dict()),
                                          rtol=2e-8, atol=5e-11)
        axes, = run.result.figure.axes
        self.assertEqual(axes.get_xlabel(), dx.SOURCE_ROW)
        self.assertTrue(axes.get_title().endswith(": Arm [B]"))
        path = self.folder / "cox.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        restored, = self.window.project.runs
        self.assertEqual(restored.options, run.options)
        self.window.open_sheet(("graph", 0))
        self.wait()
        pd.testing.assert_frame_equal(restored.result.tables[dx.SCALED_SHEET], run.result.tables[dx.SCALED_SHEET],
                                      check_exact=True)

    def test_tolerance_interval_workflow_matches_the_reference_and_round_trips(self):
        import json
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog
        from analisi import tolerance_intervals as tolerance
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "tolerance_093"
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        self.window.open_path(source / "measurements.csv")

        def setup_normal(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertEqual([dialog.tabs.tabText(i) for i in range(2)], ["Dati", "Intervallo"])
            variables = dialog.controls[tolerance.VARIABLES][1]
            self.assertTrue(all(variables.item(i).checkState() == Qt.CheckState.Unchecked
                                for i in range(variables.count())))
            dialog.run_button.click()
            self.assertEqual(dialog.error_field, tolerance.VARIABLES)
            signal, = variables.findItems("Signal", Qt.MatchFlag.MatchExactly)
            signal.setCheckState(Qt.CheckState.Checked)
            grouping = dialog.controls[tolerance.GROUP][1]
            grouping.setCurrentIndex(grouping.findData("Group"))
            coverage = dialog.controls[tolerance.COVERAGE][1]
            coverage.setText("100")
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, tolerance.COVERAGE)
            self.assertIs(dialog.focusWidget(), coverage)
            self.assertIn("Copertura della popolazione", dialog.banner.text())
            coverage.setText("90,0")
            dialog.controls[tolerance.SHOW_GRAPH][1].setChecked(True)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", setup_normal):
            self.window.analyze(method=tolerance.TOLERANCE)
            self.wait()
        run, = self.window.project.runs
        normal = run.result.tables[tolerance.TOLERANCE].set_index("Group")
        for lot in ("Lot A", "Lot B"):
            self.assertAlmostEqual(normal.loc[lot, "Lower"], expected[lot]["normal"]["two_lower"], places=9)
            self.assertAlmostEqual(normal.loc[lot, "Upper"], expected[lot]["normal"]["two_upper"], places=9)
        self.assertEqual(run.options[tolerance.COVERAGE], 90.0)

        def setup_rank(dialog):
            self.assertEqual(dialog.options(), run.options)
            distribution = dialog.controls[tolerance.DISTRIBUTION][1]
            distribution.setCurrentIndex(distribution.findData(tolerance.DISTRIBUTION_FREE))
            self.assertEqual(distribution.currentText(), "Senza distribuzione")
            sides = dialog.controls[tolerance.SIDES][1]
            sides.setCurrentIndex(sides.findData(tolerance.LOWER))
            dialog.accept()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", setup_rank):
            self.window.change_parameters()
            self.wait()
        changed, = self.window.project.runs
        self.assertEqual(changed.uid, run.uid)
        self.assertEqual(changed.options[tolerance.DISTRIBUTION], tolerance.DISTRIBUTION_FREE)
        ranks = changed.result.tables[tolerance.TOLERANCE].set_index("Group")
        self.assertEqual(ranks.loc["Lot A", "Lower rank"], expected["Lot A"]["rank"]["Lower"]["interval"]["Lower rank"])
        self.assertAlmostEqual(ranks.loc["Lot A", "Lower"], expected["Lot A"]["rank"]["Lower"]["interval"]["Lower"])
        self.assertEqual(ranks.loc["Lot B", "Status"], tolerance.INSUFFICIENT)
        self.assertTrue(pd.isna(ranks.loc["Lot B", "Lower"]))
        self.assertAlmostEqual(ranks.loc["Lot B", "Maximum confidence (%)"], expected["Lot B"]["rank"]["Lower"]["max"])

        path = self.folder / "tolerance.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        restored, = self.window.project.runs
        self.assertEqual(restored.options, changed.options)
        matches = self.window.navigator.findItems(restored.name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        self.assertIn(("graph", 0), [item.data(0, Qt.ItemDataRole.UserRole) for item in matches])
        self.window.open_sheet(("graph", 0))
        self.wait()
        pd.testing.assert_frame_equal(restored.result.tables[tolerance.TOLERANCE].set_index("Group"), ranks,
                                      check_exact=True)
        svg = self.folder / "tolerance.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        self.assertIn(tolerance.GID_LIMIT, svg.read_text(encoding="utf-8"))

        self.window.show_sheet("data", restored.title)
        model = self.window.sheet.model()
        signal_column = self.window.project.tables[restored.title].raw.columns.get_loc("Signal")
        self.assertTrue(model.setData(model.index(0, signal_column), "1000"))
        self.app.processEvents()
        self.wait()
        updated = restored.result.tables[tolerance.TOLERANCE].set_index("Group")
        self.assertEqual(updated.loc["Lot A", "Lower"], 3.0)
        self.assertEqual(updated.loc["Lot B", "Status"], tolerance.INSUFFICIENT)

    def test_weibull_profiles_times_and_recovery_keep_the_confirmed_recipe(self):
        import json
        from unittest.mock import patch
        from analisi import weibull_aft as aft
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "weibull_aft"
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))["fixed"]
        self.window.open_path(source / "follow-up.csv")

        def plan(dialog):
            dialog.show()
            self.app.processEvents()

            def control(name):
                return dialog.controls[name][1]

            self.assertEqual([dialog.tabs.tabText(i) for i in range(3)],
                             ["Dati", "Modello", "Sopravvivenza prevista"])
            event = control(aft.EVENT)
            event.setCurrentIndex(event.findData("Status"))
            control("Event value").setText("event")
            control("Censor value").setText("censored")
            predictor, = control(aft.PREDICTORS).findItems("Treatment", Qt.MatchFlag.MatchExactly)
            predictor.setCheckState(Qt.CheckState.Checked)
            self.assertIn(aft.SHAPE, dialog.hidden)
            mode = control(aft.SHAPE_MODE)
            mode.setCurrentIndex(mode.findData(aft.FIXED))
            control(aft.SHAPE).setText("1,5")
            dialog.focus_field(aft.PROFILES)
            editor = control(aft.PROFILES)
            self.assertEqual(editor.fields, ("Treatment",))
            for index, label in enumerate(("Control $", "Treatment $")):
                editor.add.click()
                editor.table.setCurrentCell(index, 1)
                editor.table.item(index, 0).setText(label)
                editor.table.item(index, 1).setText(str(index))
            control(aft.SHOW_GRAPH).setChecked(True)
            control(aft.TIMES).setPlainText("0\n4\n3")
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, aft.TIMES)
            self.assertIs(dialog.focusWidget(), control(aft.TIMES))
            control(aft.TIMES).setPlainText("0\n2\n4\n8")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", plan):
            self.window.analyze(method=aft.METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("result", 0))
        self.assertEqual(run.options[aft.TIMES], [0.0, 2.0, 4.0, 8.0])
        curves = run.result.tables[aft.CURVES_SHEET]
        self.assertEqual(curves["Profile"].drop_duplicates().tolist(), ["Control $", "Treatment $"])
        for got, wanted in zip(curves["Survival"], sum(expected["survival"], [])):
            self.assertAlmostEqual(got, wanted, places=10)
        self.assertAlmostEqual(run.result.tables[aft.COEFFICIENTS_SHEET].at["Treatment", "Time ratio"], 2.0)

        self.window.open_sheet(("graph", 0))

        def cancel_graph_settings(dialog):
            self.assertEqual(dialog.tabs.tabText(dialog.tabs.currentIndex()), "Sopravvivenza prevista")
            self.assertEqual(dialog.options(), run.options)
            return AnalysisDialog.DialogCode.Rejected

        with patch.object(AnalysisDialog, "exec", cancel_graph_settings):
            self.window.change_parameters()
        self.assertIs(self.window.project.runs[0], run)
        path = self.folder / "weibull.alab"
        self.window.project.save(path)
        self.window.open_path(path)
        restored, = self.window.project.runs
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertEqual(restored.options, run.options)
        pd.testing.assert_frame_equal(restored.result.tables[aft.CURVES_SHEET], curves, check_exact=True)

        recovered = []

        def retain_result(dialog):
            self.assertEqual(dialog.error_field, aft.TIME)
            self.assertIn("riga", dialog.banner.text().lower())
            self.assertIsNotNone(restored.calculation_error)
            recovered.append(dialog.error_field)
            return AnalysisDialog.DialogCode.Rejected

        def set_time(value):
            self.window.show_sheet("data", restored.title)
            model = self.window.sheet.model()
            self.assertTrue(model.setData(model.index(0, 0), value))
            self.app.processEvents()
            self.wait()

        with patch.object(AnalysisDialog, "exec", retain_result):
            set_time("0")
        self.assertEqual(recovered, [aft.TIME])
        pd.testing.assert_frame_equal(restored.result.tables[aft.CURVES_SHEET], curves, check_exact=True)
        set_time("1.1")
        self.assertIsNone(restored.calculation_error)
        pd.testing.assert_frame_equal(restored.result.tables[aft.CURVES_SHEET], curves, check_exact=True)

    def test_weibull_profile_editor_keeps_numeric_looking_category_labels_literal(self):
        from trama_qt.weibull_options import Profiles

        records = [{"Name": "First arm", "Values": {"Arm": "01"}}]
        editor = Profiles(pd.DataFrame({"Arm": ["01", "1"]}), records)
        self.addCleanup(editor.deleteLater)
        editor.change_predictors(["Arm"], ["Arm"])
        self.assertEqual(editor.values(), records)
        choice = editor.table.cellWidget(0, 1)
        self.assertEqual(choice.currentText(), "01")
        self.assertGreaterEqual(choice.findText("1"), 0)

    def test_ordinal_order_profiles_and_recovery_use_literal_categories(self):
        import json
        from unittest.mock import patch
        from analisi import ordinal_logit as ordinal
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "ordinal_logit"
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        self.window.open_path(source / "stages.csv")

        def configure(dialog):
            dialog.show()
            self.app.processEvents()
            controls = {name: widget for name, (_, widget) in dialog.controls.items()}
            response = controls[ordinal.RESPONSE]
            response.setCurrentIndex(response.findData("Stage"))
            predictor, = controls[ordinal.PREDICTORS].findItems("Treatment", Qt.MatchFlag.MatchExactly)
            predictor.setCheckState(Qt.CheckState.Checked)
            order = controls[ordinal.ORDER]
            self.assertEqual(order.values(), ["High", "Low", "Medium"])
            order.list.setCurrentRow(0)
            order.down.click()
            order.down.click()
            self.assertEqual(order.values(), ["Low", "Medium", "High"])

            controls[ordinal.GRAPH].setChecked(True)
            dialog.run_button.click()
            profiles = controls[ordinal.PROFILES]
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, ordinal.PROFILES)
            self.assertIs(dialog.focusWidget(), profiles.table)
            self.assertEqual(dialog.tabs.tabText(dialog.tabs.currentIndex()), "Profili")
            self.assertIn("almeno un profilo", dialog.banner.text())
            for index, name in enumerate(("Controllo $", "Trattato $")):
                profiles.add.click()
                profiles.table.setCurrentCell(index, 1)
                profiles.table.item(index, 0).setText(name)
                profiles.table.item(index, 1).setText(f"{index},0")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", configure):
            self.window.analyze(method=ordinal.ORDINAL_LOGIT)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("result", 0))
        tables = run.result.tables
        probabilities = tables["Profile probabilities"]
        self.assertAlmostEqual(tables["Coefficients"].at["Treatment", "Estimate"], expected["coeff"], places=5)
        for got, wanted in zip(tables["Thresholds"]["Estimate"], expected["thresholds"]):
            self.assertAlmostEqual(got, wanted, places=5)
        self.assertEqual(probabilities["Profile"].tolist(), ["Controllo $", "Trattato $"])
        for index, wanted in enumerate(expected["probabilities"]):
            got = probabilities.loc[index, ["P(Low)", "P(Medium)", "P(High)"]]
            for actual, value in zip(got, wanted):
                self.assertAlmostEqual(actual, value, places=5)
        self.assertTrue(any(artist.get_gid() == "ordinal-logit-profile-1-category-1"
                            for artist in run.result.figure.axes[0].patches))

        path = self.folder / "ordinal.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        restored, = self.window.project.runs
        self.assertEqual(restored.options, run.options)
        pd.testing.assert_frame_equal(restored.result.tables["Profile probabilities"], probabilities, check_exact=True)

        recovered = []

        def cancel_order_change(dialog):
            dialog.show()
            self.app.processEvents()
            order = dialog.controls[ordinal.ORDER][1]
            self.assertEqual(dialog.error_field, ordinal.ORDER)
            self.assertIs(dialog.focusWidget(), order.list)
            self.assertEqual(order.values(), ["Low", "Medium", "High"])
            self.assertIn("Critical", order.note.text())
            recovered.append(dialog.error_field)
            return AnalysisDialog.DialogCode.Rejected

        def set_stage(value):
            self.window.show_sheet("data", restored.title)
            model = self.window.sheet.model()
            self.assertTrue(model.setData(model.index(0, 0), value))
            self.app.processEvents()
            self.wait()

        with patch.object(AnalysisDialog, "exec", cancel_order_change):
            set_stage("Critical")
        self.assertEqual(recovered, [ordinal.ORDER])
        pd.testing.assert_frame_equal(restored.result.tables["Profile probabilities"], probabilities, check_exact=True)
        set_stage("Low")
        self.assertIsNone(restored.calculation_error)
        pd.testing.assert_frame_equal(restored.result.tables["Profile probabilities"], probabilities, check_exact=True)

    def test_rmst_validates_followup_preserves_result_and_reopens_graph(self):
        import json
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog, QLabel
        from analisi import rmst
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "rmst" / "fixtures"
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        self.window.open_path(source / "cohorts.csv")

        def configure(dialog):
            dialog.show()
            self.app.processEvents()
            controls = {name: widget for name, (_, widget) in dialog.controls.items()}
            self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
                             ["Dati", "Codici e stima"])
            self.assertIn(rmst.REFERENCE, dialog.hidden)
            group = controls[rmst.GROUP]
            group.setCurrentIndex(group.findData("Group"))
            self.assertNotIn(rmst.REFERENCE, dialog.hidden)
            reference = controls[rmst.REFERENCE]
            self.assertEqual([reference.itemData(i) for i in range(reference.count())], ["Reference", "Series $B"])
            self.assertIn("Orizzonte massimo utilizzabile: 8.", [label.text() for label in dialog.findChildren(QLabel)])
            self.assertEqual(controls[rmst.EVENT_CODE].text(), "1")
            self.assertEqual(controls[rmst.CENSOR_CODE].text(), "0")
            horizon = controls[rmst.HORIZON]
            horizon.setText("8,5")
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, rmst.HORIZON)
            self.assertIs(dialog.focusWidget(), horizon)
            self.assertIn("8,5", dialog.banner.text())
            self.assertIn("Reference", dialog.banner.text())
            horizon.setText("6,5")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", configure):
            self.window.analyze(method=rmst.METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("result", 0))
        self.assertEqual(run.options[rmst.HORIZON], 6.5)
        self.assertEqual(run.options[rmst.REFERENCE], "Reference")
        estimates = run.result.tables[rmst.RMST_SHEET]
        self.assertEqual(estimates["Group"].tolist(), ["Reference", "Series $B"])
        for label, wanted in expected["arms"].items():
            actual = estimates.set_index("Group").loc[label]
            for metric in ("RMST", "SE", "CI lower", "CI upper"):
                self.assertAlmostEqual(actual[metric], wanted[metric], places=12)
        contrasts = run.result.tables[rmst.COMPARISON_SHEET].set_index("Contrast")
        for contrast, wanted in expected["contrasts"].items():
            for metric in ("Estimate", "p"):
                self.assertAlmostEqual(contrasts.loc[contrast, metric], wanted[metric], places=12)

        path = self.folder / "rmst.alab"
        self.window.project.save(path)
        self.window.open_path(path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        restored, = self.window.project.runs
        self.assertEqual(restored.options, run.options)
        self.assertEqual(self.window.selected, ("graph", 0))
        svg = self.folder / "rmst.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        exported = svg.read_text(encoding="utf-8")
        for gid in ("rmst-curve-0", "rmst-curve-1", "rmst-area-0", "rmst-area-1", "rmst-horizon"):
            self.assertIn(f'id="{gid}"', exported)

        def graph_settings(dialog):
            self.assertEqual(dialog.tabs.tabText(dialog.tabs.currentIndex()), "Codici e stima")
            self.assertEqual(dialog.controls[rmst.HORIZON][1].text(), "6,5")
            return AnalysisDialog.DialogCode.Rejected

        with patch.object(AnalysisDialog, "exec", graph_settings):
            self.window.change_parameters()

        recovered = []

        def cancel_recovery(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.error_field, rmst.HORIZON)
            self.assertIs(dialog.focusWidget(), dialog.controls[rmst.HORIZON][1])
            self.assertIn("Orizzonte massimo utilizzabile: 6.", [label.text() for label in dialog.findChildren(QLabel)])
            self.assertEqual(dialog.options()[rmst.HORIZON], 6.5)
            recovered.append(dialog.error_field)
            return AnalysisDialog.DialogCode.Rejected

        self.window.show_sheet("data", restored.title)
        model = self.window.sheet.model()
        with patch.object(AnalysisDialog, "exec", cancel_recovery):
            self.assertTrue(model.setData(model.index(10, 0), "5"))
            self.app.processEvents()
            self.wait()
        self.assertEqual(recovered, [rmst.HORIZON])
        self.assertIsNotNone(restored.calculation_error)
        pd.testing.assert_frame_equal(restored.result.tables[rmst.RMST_SHEET], estimates, check_exact=True)

        def correct_horizon(dialog):
            dialog.controls[rmst.HORIZON][1].setText("5,5")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        self.window.open_sheet(("result", 0))
        with patch.object(AnalysisDialog, "exec", correct_horizon):
            self.window.change_parameters()
            self.wait()
        corrected, = self.window.project.runs
        self.assertIsNone(corrected.calculation_error)
        self.assertEqual(corrected.options[rmst.HORIZON], 5.5)
        self.assertEqual(corrected.result.tables[rmst.RMST_SHEET]["Horizon"].tolist(), [5.5, 5.5])

    def test_rmst_one_cohort_preserves_disabled_graph_and_omits_reference(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        from analisi import rmst
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.window._ask = MainWindow._ask.__get__(self.window)
        self.window.open_path(ROOT / "tests" / "data" / "rmst" / "fixtures" / "cohorts.csv")

        def one_cohort(dialog):
            dialog.controls[rmst.HORIZON][1].setText("5")
            dialog.controls[rmst.SHOW_GRAPH][1].setChecked(False)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", one_cohort):
            self.window.analyze(method=rmst.METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertNotIn(rmst.REFERENCE, run.options)
        self.assertNotIn(rmst.COMPARISON_SHEET, run.result.tables)
        self.assertIsNone(run.result.figure)
        project = self.folder / "one-cohort.alab"
        self.window.project.save(project)
        self.window.open_path(project)
        items = QTreeWidgetItemIterator(self.window.navigator)
        refs = []
        while item := items.value():
            refs.append(item.data(0, Qt.ItemDataRole.UserRole))
            items += 1
        self.assertIn(("result", 0), refs)
        self.assertNotIn(("graph", 0), refs)

    def test_kappa_preserves_order_and_bootstrap_fields_and_round_trips(self):
        import json
        from threading import Event
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog
        from analisi import cohen_kappa as kappa
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = ROOT / "tests" / "data" / "cohen_kappa"
        golden = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        self.window.open_path(source / "ratings.csv")

        def configure(dialog):
            dialog.show()
            self.app.processEvents()
            controls = {name: widget for name, (_, widget) in dialog.controls.items()}
            self.assertEqual(controls[kappa.FIRST].currentData(), "Rater A")
            self.assertEqual(controls[kappa.SECOND].currentData(), "Rater B")
            self.assertEqual([dialog.tabs.tabText(i) for i in range(2)], ["Valutazioni", "Intervallo e grafico"])

            weighting = controls[kappa.WEIGHTING]
            weighting.setCurrentIndex(weighting.findData(kappa.QUADRATIC))
            self.assertEqual(weighting.currentText(), "Quadratico")
            order = controls[kappa.ORDER]
            dialog.run_button.click()
            self.assertEqual(dialog.error_field, kappa.ORDER)
            self.assertIs(dialog.focusWidget(), order.list)
            order.buttons["propose"].click()
            self.assertEqual(order.values(), ["Mild", "Moderate $", "Severe"])
            order.buttons["down"].click()
            self.assertEqual(order.values(), ["Moderate $", "Mild", "Severe"])
            order.buttons["restore"].click()
            self.assertEqual(order.values(), [])
            order.buttons["propose"].click()

            interval = controls[kappa.INTERVAL]
            interval.setCurrentIndex(interval.findData(kappa.BOOTSTRAP))
            controls[kappa.RESAMPLES].setText("198")
            controls[kappa.LEVEL].setText("95,0")
            controls[kappa.SEED].setText(str(2 ** 64 - 1))
            dialog.run_button.click()
            self.assertEqual(dialog.error_field, kappa.RESAMPLES)
            self.assertIs(dialog.focusWidget(), controls[kappa.RESAMPLES])
            interval.setCurrentIndex(interval.findData(kappa.NO_INTERVAL))
            self.assertIn(kappa.RESAMPLES, dialog.hidden)
            self.assertEqual(dialog.options()[kappa.RESAMPLES], 198)
            self.assertEqual(dialog.options()[kappa.SEED], 2 ** 64 - 1)
            interval.setCurrentIndex(interval.findData(kappa.BOOTSTRAP))
            self.assertEqual(controls[kappa.RESAMPLES].text(), "198")
            controls[kappa.RESAMPLES].setText("199")
            controls[kappa.SEED].setText("2701")
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", configure):
            self.window.analyze(method=kappa.METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("result", 0))
        agreement = run.result.tables[kappa.AGREEMENT]
        row = agreement.iloc[0]
        self.assertAlmostEqual(row["Kappa"], golden["scores"]["Quadratic"])
        self.assertEqual(row["Complete pairs"], 30)
        self.assertEqual(row["Incomplete pairs"], 2)
        for key, want in golden["bootstrap"].items():
            self.assertAlmostEqual(row[key], want, places=14)

        path = self.folder / "kappa.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        restored, = self.window.project.runs
        self.assertEqual(restored.options, run.options)
        pd.testing.assert_frame_equal(restored.result.tables[kappa.AGREEMENT], agreement, check_exact=True)
        svg = self.folder / "kappa.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        exported = svg.read_text(encoding="utf-8")
        self.assertIn('id="kappa-counts"', exported)
        self.assertIn('id="kappa-diagonal-1"', exported)
        self.assertNotIn("<image", exported)

        entered_bootstrap = Event()
        bootstrap = kappa.bootstrap

        def wait_for_cancel(counts, weights, resamples, seed, cancel):
            entered_bootstrap.set()
            self.assertTrue(cancel.wait(8))
            return bootstrap(counts, weights, resamples, seed, cancel)

        with patch.object(kappa, "bootstrap", wait_for_cancel):
            self.window.recalculate()
            self.assertTrue(entered_bootstrap.wait(8))
            self.assertTrue(self.window.cancel_button.isVisible())
            self.window.cancel_button.click()
            self.wait()
        pd.testing.assert_frame_equal(restored.result.tables[kappa.AGREEMENT], agreement, check_exact=True)

        recovered = []

        def cancel_recovery(dialog):
            dialog.show()
            self.app.processEvents()
            order = dialog.controls[kappa.ORDER][1]
            self.assertEqual(dialog.error_field, kappa.ORDER)
            self.assertIs(dialog.focusWidget(), order.list)
            self.assertEqual(order.values(), ["Mild", "Moderate $", "Severe"])
            self.assertIn("Another category", order.note.text())
            recovered.append(dialog.error_field)
            return AnalysisDialog.DialogCode.Rejected

        self.window.show_sheet("data", restored.title)
        model = self.window.sheet.model()
        with patch.object(AnalysisDialog, "exec", cancel_recovery):
            self.assertTrue(model.setData(model.index(0, 0), "Another category"))
            self.app.processEvents()
            self.wait()
        self.assertEqual(recovered, [kappa.ORDER])
        self.assertIsNotNone(restored.calculation_error)
        pd.testing.assert_frame_equal(restored.result.tables[kappa.AGREEMENT], agreement, check_exact=True)

    def test_mean_permutation_previews_exact_and_preserves_unsigned_seed(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog, QLabel
        from analisi import mean_permutation as mp
        from analisi.i18n import active_language, set_language
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        self.window.open_path(ROOT / "tests" / "data" / "mean_permutation" / "independent.csv")

        def exact(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertEqual([dialog.tabs.tabText(index) for index in range(2)], ["Dati", "Test"])
            controls = {field: widget for field, (_, widget) in dialog.controls.items()}
            self.assertEqual(controls[mp.FIRST].currentData(), "First")
            self.assertEqual(controls[mp.SECOND].currentData(), "Second")
            self.assertTrue(any("126" in label.text() for label in dialog.findChildren(QLabel)))
            controls[mp.SEED].setText("invalid")
            mode = controls[mp.MODE]
            mode.setCurrentIndex(mode.findData(mp.EXACT))
            self.assertEqual(mode.currentText(), "Esatto")
            self.assertIn(mp.SEED, dialog.hidden)
            self.assertIn(mp.RESAMPLES, dialog.hidden)
            self.assertNotIn(mp.SEED, dialog.options())
            controls[mp.KEEP_DRAWS].setChecked(True)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", exact):
            self.window.analyze(method=mp.METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("result", 0))
        row = run.result.tables[mp.RESULTS_SHEET].iloc[0]
        self.assertEqual(row["Mode used"], mp.EXACT)
        self.assertEqual(row["Mean difference"], 1.75)
        self.assertEqual((row["Tail count"], row["Draws"]), (57, 126))
        self.assertAlmostEqual(row["p"], 57 / 126, places=14)
        self.assertEqual(len(run.result.tables[mp.DRAWS_SHEET]), 126)
        self.window.open_sheet(("graph", 0))
        self.wait()
        svg = self.folder / "permutation.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        self.assertIn('id="permutation-observed"', svg.read_text(encoding="utf-8"))

        def monte_carlo(dialog):
            dialog.show()
            self.app.processEvents()
            controls = {field: widget for field, (_, widget) in dialog.controls.items()}
            mode = controls[mp.MODE]
            mode.setCurrentIndex(mode.findData(mp.MONTE_CARLO))
            self.assertNotIn(mp.RESAMPLES, dialog.hidden)
            controls[mp.RESAMPLES].setText("199")
            seed = controls[mp.SEED]
            seed.setText(str(2 ** 64))
            dialog.run_button.click()
            self.assertEqual(dialog.error_field, mp.SEED)
            self.assertIs(dialog.focusWidget(), seed)
            self.assertIsNone(dialog.result)
            seed.setText(str(2 ** 64 - 1))
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", monte_carlo):
            self.window.change_parameters()
            self.wait()
        sampled, = self.window.project.runs
        self.assertEqual(sampled.uid, run.uid)
        self.assertEqual(sampled.options[mp.SEED], 2 ** 64 - 1)
        sampled_results = sampled.result.tables[mp.RESULTS_SHEET]
        sampled_row = sampled_results.iloc[0]
        self.assertEqual(sampled_row["Mode used"], mp.MONTE_CARLO)
        self.assertEqual(sampled_row["Draws"], 199)
        self.assertAlmostEqual(sampled_row["p"], (sampled_row["Tail count"] + 1) / 200)
        project = self.folder / "permutation.alab"
        self.window.project.save(project)
        set_language("en")
        self.window.open_path(project)
        self.window.open_sheet(("graph", 0))
        self.wait()
        restored, = self.window.project.runs
        self.assertEqual(restored.options, sampled.options)
        pd.testing.assert_frame_equal(restored.result.tables[mp.RESULTS_SHEET], sampled_results, check_exact=True)
        pd.testing.assert_frame_equal(restored.result.tables[mp.DRAWS_SHEET],
                                      sampled.result.tables[mp.DRAWS_SHEET], check_exact=True)

    def test_change_category_order_in_the_classic_menu(self):
        from unittest.mock import patch

        from analisi.category_order import WORKSHEET_ORDERS
        from trama_qt.category_order import CategoryOrderDialog
        from trama_qt.classic_bar import MENUS

        window = self.window
        title, = window.project.add_tables({"Samples": pd.DataFrame({"Group": ["A", "B", "A"]})})
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        data = window.project.tables[title]
        self.assertIn("category_order", dict(MENUS)["Change"])
        action = window.actions["category_order"]
        self.assertTrue(action.isEnabled())

        def move(dialog, result):
            dialog.down.click()
            self.assertEqual(dialog.levels.item(0).text(), "B")
            return result

        accepted, rejected = CategoryOrderDialog.DialogCode.Accepted, CategoryOrderDialog.DialogCode.Rejected
        with patch.object(CategoryOrderDialog, "exec", lambda dialog: move(dialog, rejected)):
            action.trigger()
        self.assertNotIn(WORKSHEET_ORDERS, data.raw.attrs)
        with patch.object(CategoryOrderDialog, "exec", lambda dialog: move(dialog, accepted)):
            action.trigger()
        self.assertEqual(data.raw.attrs[WORKSHEET_ORDERS]["Group"], ["str:B", "str:A"])
        window.actions["undo"].trigger()
        self.assertNotIn(WORKSHEET_ORDERS, data.raw.attrs)

    def test_paper_preview_scales_the_text_with_the_page(self):
        from matplotlib.figure import Figure
        from trama_qt.window import Page

        paper = (8.5, 11.0)
        figure = Figure(figsize=paper)
        title = figure.add_subplot().set_title("Saved page title", fontsize=24)
        page = Page("Layout")
        self.addCleanup(page.close)
        canvas = self.window._canvas(page, figure, toolbar=False, paper=paper)
        page.show()
        ratios = []
        widths = []
        for height in (620, 340):
            page.resize(740, height)
            self.app.processEvents()
            canvas.draw()
            self.assertEqual(tuple(figure.get_size_inches()), paper)
            height_pixels, width_pixels, _channels = canvas.buffer_rgba().shape
            self.assertGreaterEqual(width_pixels, ceil(canvas.width() * canvas.device_pixel_ratio))
            self.assertGreaterEqual(height_pixels, ceil(canvas.height() * canvas.device_pixel_ratio))
            widths.append(canvas.width())
            ratios.append(title.get_window_extent(canvas.get_renderer()).height / figure.bbox.height)
        self.assertLess(widths[1], widths[0] * 0.65)
        self.assertAlmostEqual(ratios[0], ratios[1], delta=0.005)

    def test_imported_page_is_readable_and_can_show_the_entire_paper(self):
        from matplotlib.figure import Figure
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QScrollArea
        from trama_qt.strings import qt
        from trama_qt.window import Page

        paper = (8.5, 11.0)
        figure = Figure(figsize=paper)
        figure.add_subplot().plot([0, 1], [1, 2])
        page = Page("Imported layout")
        self.addCleanup(page.close)
        canvas = self.window._canvas(page, figure, paper=paper, imported_layout=True)
        page.resize(750, 430)
        page.show()
        self.app.processEvents()

        preview = page.findChild(QScrollArea)
        scroll = preview.verticalScrollBar()
        width_at_open = canvas.width()
        self.assertGreaterEqual(width_at_open, preview.viewport().width() - 2)
        self.assertGreater(scroll.maximum(), 0)
        self.assertAlmostEqual(canvas.width() / canvas.height(), paper[0] / paper[1], delta=0.01)
        wheel = QWheelEvent(QPointF(25, 30), QPointF(25, 30), QPoint(), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(canvas, wheel)
        self.assertGreater(scroll.value(), 0)

        fit = next(action for action in self.window.plot_tools.actions() if action.text() == qt("qt.fit_entire_page"))
        fit.trigger()
        self.app.processEvents()
        self.assertEqual(scroll.maximum(), 0)
        self.assertLess(canvas.width(), width_at_open)
        self.assertLessEqual(canvas.height(), preview.viewport().height())
        self.assertEqual(tuple(figure.get_size_inches()), paper)
        fit.trigger()
        self.app.processEvents()
        self.assertEqual(canvas.width(), width_at_open)
        self.assertGreater(scroll.maximum(), 0)
        self.assertEqual(tuple(figure.get_size_inches()), paper)

    def run_method(self, method, options):
        title = self.window.selected[1] if self.window.selected[0] == "data" else self.window.project.runs[
            self.window.selected[1]].title
        frame = self.window.project.tables[title].frame(mask_excluded=True)
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(self.window, frame, current=(method, {}))
        for name, value in options.items():  # Tick the columns a user would tick.
            kind, control = dialog.controls[name]
            if isinstance(value, list) and hasattr(control, "item"):
                for row in range(control.count()):
                    item = control.item(row)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        values = dialog.options()  # The dialog defaults, as a user pressing Run would send them.
        dialog.deleteLater()
        values.update(options)
        candidate = self.window.project.candidate(title, method, values)
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        return self.window.project.runs[-1]

    def reopen(self, path):
        """Read a saved project back from disk. Opening a file that is already open only shows its tab, so the
        project closes first (it was just saved) and opens again in the tab left empty."""
        self.assertTrue(self.window.close_project())
        self.assertTrue(self.window.project.is_empty())
        self.window.open_path(path)
        self.app.processEvents()
        self.assertEqual(Path(self.window.project.path), Path(path))

    def open_example(self):
        path = self.folder / "groups.csv"
        pd.DataFrame({"Control": [4.1, 5.0, 4.7, 5.3, 4.9], "Treated": [5.9, 6.3, 6.1, 5.7, 6.6]}).to_csv(
            path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        self.assertEqual(self.window.selected, ("data", "groups"))

    def test_edit_analyse_graph_save_reopen_export(self):
        window = self.window
        self.open_example()
        model = window.sheet.model()
        self.assertTrue(model.setData(model.index(0, 0), "4.4"))
        self.app.processEvents()
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.4)
        window.undo()
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.1)
        window.undo(redo=True)
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.4)

        run = self.run_method("Descriptive statistics", {"Variables": ["Control", "Treated"]})
        self.assertIsNotNone(run.result)
        self.assertEqual(window.selected[0], "result")
        self.assertIsNotNone(window.result_tabs)
        self.assertGreater(window.result_tabs.count(), 0)

        # Editing the source recalculates the linked result.
        window.show_sheet("data", "groups")
        model = window.sheet.model()
        model.setData(model.index(1, 0), "9")
        self.app.processEvents()
        self.wait()
        self.assertIsNone(window.project.runs[0].calculation_error)

        window.show_sheet("data", "groups")
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertIsNotNone(graph.result.figure)
        self.assertEqual(window.selected[0], "graph")
        self.assertTrue(window.page.canvases)

        saved = self.folder / "project.alab"
        window.project.save(saved)
        window.refresh()
        self.assertFalse(window.project.dirty)
        self.reopen(saved)
        self.app.processEvents()
        self.assertIn("groups", window.project.tables)
        self.assertEqual(window.project.tables["groups"].raw.iat[1, 0], 9.0)
        self.assertGreaterEqual(len(window.project.runs), 1)
        # Opened results are recalculated on first view.
        window.open_sheet(("result", 0))
        self.wait()
        self.assertIsNotNone(window.project.runs[0].result)

        from trama_qt.window import export_graph, safe_csv
        table = next(iter(window.project.runs[0].result.tables.values()))
        safe_csv(self.folder / "table.csv", table, index=True)
        self.assertTrue((self.folder / "table.csv").stat().st_size > 0)
        if graph is not None:
            index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
            window.open_sheet(("graph", index))
            self.wait()
            figure = window.project.runs[index].result.figure
            canvas = figure.canvas
            export_graph(figure, self.folder / "graph.svg")
            self.assertIs(figure.canvas, canvas)
            self.assertTrue((self.folder / "graph.svg").read_text(encoding="utf-8").lstrip().startswith("<?xml"))

    def test_quick_export_fits_a_wide_canvas_to_the_size_limit(self):
        from xml.etree import ElementTree

        from matplotlib.figure import Figure
        from trama_qt.window import export_graph

        figure = Figure(figsize=(22.88, 10.86))
        figure.add_subplot().plot([1, 2], [3, 5])
        canvas = figure.canvas
        destination = self.folder / "wide.svg"

        export_graph(figure, destination)

        attributes = ElementTree.parse(destination).getroot().attrib
        width, height = (float(attributes[axis].removesuffix("pt")) for axis in ("width", "height"))
        self.assertAlmostEqual(width * 25.4 / 72, 500.0, places=5)
        self.assertAlmostEqual(width / height, 22.88 / 10.86, places=6)
        self.assertEqual(tuple(figure.get_size_inches()), (22.88, 10.86))
        self.assertIs(figure.canvas, canvas)

    def format_with(self, run, change):
        from trama_qt.graph_format import GraphFormatDialog
        style, xy = self.window.project.format_inputs(run)
        dialog = GraphFormatDialog(self.window, run.result.figure.axes[0], style, xy=xy)
        change(dialog)
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        self.window.project.apply_format(run, dialog.result, xy_update=dialog.xy_update, xy_result=dialog.xy_result)
        dialog.deleteLater()
        return dialog.result

    def test_format_graph_round_trip(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertTrue(window.actions["format_graph"].isEnabled())

        def change(dialog):
            dialog.texts["title"].setText("Formatted")
            dialog.fonts["title_size"].setText("15")
            dialog.axis_fields["y"]["min"].setText("0")
            dialog.axis_fields["y"]["max"].setText("10")
            dialog.references.setPlainText("Y, 5, limit")

        style = self.format_with(graph, change)
        self.assertEqual(style["title"], "Formatted")
        axes = graph.result.figure.axes[0]
        self.assertEqual(axes.get_title(), "Formatted")
        self.assertEqual(axes.get_ylim(), (0.0, 10.0))
        self.assertTrue(window.project.dirty)

        # A bad value stays in the dialog with a message instead of reaching the graph.
        from trama_qt.graph_format import GraphFormatDialog
        current, xy = window.project.format_inputs(graph)
        dialog = GraphFormatDialog(window, axes, current, xy=xy)
        dialog.axis_fields["y"]["min"].setText("abc")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.text())
        dialog.deleteLater()

        saved = self.folder / "styled.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        reopened = window.project.runs[index]
        self.assertEqual(reopened.style["title"], "Formatted")
        self.assertEqual(reopened.result.figure.axes[0].get_title(), "Formatted")

    def test_inspector_preview_apply_and_cancel(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.toggle_inspector()
        inspector = window.inspector
        self.assertIs(graph.result.figure.canvas, inspector.canvas)
        self.assertIsNotNone(inspector)
        axes = graph.result.figure.axes[0]
        inspector.widgets["title"].setText("Anteprima")
        inspector._now("title")
        self.assertEqual(axes.get_title(), "Anteprima")  # Previewed on the live figure...
        self.assertNotEqual((graph.style or {}).get("title"), "Anteprima")  # ...not yet confirmed.
        inspector.widgets["ymin"].setText("1")
        inspector._now("yrange")
        self.assertIn("yrange", inspector.errors)  # Both limits are needed.
        inspector.widgets["ymax"].setText("9")
        inspector._now("yrange")
        self.assertNotIn("yrange", inspector.errors)
        self.assertEqual(axes.get_ylim(), (1.0, 9.0))
        self.assertTrue(inspector.apply())
        self.assertEqual(graph.style["title"], "Anteprima")
        self.assertEqual(window.project.tables["groups"].graph_styles[graph.slot]["title"], "Anteprima")

        inspector.widgets["title"].setText("Bozza")
        inspector._now("title")
        self.assertTrue(inspector.has_draft)
        inspector.cancel()  # Closing restores the confirmed style.
        self.assertIsNone(window.inspector)
        self.assertEqual(axes.get_title(), "Anteprima")

        # Leaving the graph with a draft also restores the confirmed style; the panel comes back on the graph.
        window.toggle_inspector()
        window.inspector.widgets["title"].setText("Bozza")
        window.inspector._now("title")
        window.show_sheet("data", "groups")
        self.assertEqual(axes.get_title(), "Anteprima")
        window.inspector_wanted = True
        window.show_sheet("graph", window.project.runs.index(graph))
        self.assertIsNotNone(window.inspector)

    def test_worksheet_preview_keeps_the_grid_and_commits_only_on_apply(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        figure = graph.result.figure
        title = figure.axes[0].get_title()
        window.open_sheet(("data", graph.title))
        canvas = figure.canvas
        sheet = window.sheet
        workspace = window.page.worksheet_preview
        action = window.actions["worksheet_preview"]
        self.assertIn(action, window.command_menus["View"].actions())
        self.assertIsNone(workspace.canvas)

        workspace.preview_box.click()
        self.app.processEvents()
        self.assertTrue(action.isChecked())
        self.assertTrue(workspace.heading.isVisible())
        self.assertEqual(workspace.title_label.text(), graph.title)
        self.assertTrue(workspace.link_buttons["graph"].menu().actions())
        self.assertLess(workspace.format_box.mapTo(workspace, workspace.format_box.rect().topLeft()).y(),
                        workspace.grid.mapTo(workspace, workspace.grid.rect().topLeft()).y())
        self.assertIs(window.sheet, sheet)
        self.assertIs(figure.canvas, canvas)
        self.assertIsNot(workspace.canvas.figure, figure)
        workspace.format_box.click()
        inspector = window.inspector
        inspector.widgets["title"].setText("Confirmed on Apply")
        inspector._now("title")
        self.assertEqual(workspace.canvas.figure.axes[0].get_title(), "Confirmed on Apply")
        self.assertEqual(figure.axes[0].get_title(), title)
        self.assertTrue(inspector.apply())
        self.assertEqual(figure.axes[0].get_title(), "Confirmed on Apply")
        self.assertEqual(window.project.tables[graph.title].graph_styles[graph.slot]["title"], "Confirmed on Apply")

        inspector.widgets["title"].setText("Discard this")
        inspector._now("title")
        inspector.cancel()
        self.assertFalse(workspace.format_box.isChecked())
        self.assertEqual(workspace.canvas.figure.axes[0].get_title(), "Confirmed on Apply")

        self.assertTrue(window.edit_cell(graph.title, 0, 0, "20"))
        self.wait()
        self.assertIs(window.sheet, sheet)
        self.assertIsNot(graph.result.figure, figure)
        self.assertIs(workspace.result, graph.result)
        self.assertEqual(workspace.canvas.figure.axes[0].get_title(), "Confirmed on Apply")
        workspace.link_buttons["graph"].menu().actions()[0].trigger()
        self.assertEqual(window.selected, ("graph", window.project.runs.index(graph)))
        self.assertIsNone(workspace.canvas)

    def test_worksheet_preview_never_starts_an_uncalculated_graph(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        graph.result = None
        window.open_sheet(("data", graph.title))
        window.actions["worksheet_preview"].trigger()
        workspace = window.page.worksheet_preview
        self.assertIsNone(window.job)
        self.assertIsNone(graph.result)
        self.assertIsNone(workspace.canvas)
        self.assertTrue(workspace.calculate.isEnabled())
        workspace.calculate.click()
        self.wait()
        self.assertEqual(window.selected, ("data", graph.title))
        self.assertIs(workspace.result, graph.result)
        self.assertIsNotNone(workspace.canvas)

    def test_annotations(self):
        from trama_qt.annotations import AnnotationEditor, GraphAnnotationsDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        axes = graph.result.figure.axes[0]
        editor = AnnotationEditor(window, axes)
        editor.accept()
        self.assertIsNone(editor.result)  # Empty text.
        editor.text.setPlainText("p < 0,05")
        editor.arrow.setChecked(True)
        editor.target[0].setText("0,5")
        editor.accept()
        self.assertEqual(editor.result["target"], [0.5, 0.5])
        dialog = GraphAnnotationsDialog(window, axes, [])
        dialog.records.append(editor.result)
        dialog.fill(0)
        dialog.accept()
        style = dict(graph.style or {}, annotations=dialog.result)
        window.project.apply_format(graph, style)
        self.assertIn("p < 0,05", [text.get_text() for text in axes.texts])
        saved = self.folder / "notes.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        self.assertEqual(window.project.runs[index].style["annotations"][0]["text"], "p < 0,05")

    def test_axis_guides_and_bands(self):
        from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
        from trama_qt.axis_guides import AxisBandsDialog, AxisGuidesDialog, BandEditor, GuideEditor
        from trama_qt.graph_format import GraphFormatDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        axes = graph.result.figure.axes[0]
        guide = GuideEditor(window, axes)
        self.assertEqual(guide.fields["axis"].value(), "y")  # X is categorical.
        guide.fields["value"].setText("abc")
        guide.accept()
        self.assertIsNone(guide.result)
        self.assertTrue(guide.problem.text())
        guide.fields["value"].setText("2,5")
        guide.fields["label"].setText("soglia")
        guide.accept()
        self.assertEqual(guide.result["value"], 2.5)
        band = BandEditor(window, axes)
        band.fields["lower"].setText("4")
        band.fields["upper"].setText("1")
        band.accept()
        self.assertIsNone(band.result)  # Lower above upper.
        band.fields["upper"].setText("6")
        band.accept()
        self.assertEqual((band.result["lower"], band.result["upper"]), (4.0, 6.0))

        current, xy = window.project.format_inputs(graph)
        dialog = GraphFormatDialog(window, axes, current, xy=xy)
        guides = AxisGuidesDialog(dialog, axes, [], {"y": "linear"})
        guides.records.append(guide.result)
        guides.fill(0)
        guides.duplicate()
        self.assertEqual(len(guides.records), 2)
        guides.remove()
        guides.accept()
        bands = AxisBandsDialog(dialog, axes, [band.result])
        bands.accept()
        dialog.guide_records[AXIS_GUIDES], dialog.guide_records[AXIS_BANDS] = guides.result, bands.result
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        window.project.apply_format(graph, dialog.result)
        saved = self.folder / "guides.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        style = window.project.runs[index].style
        self.assertEqual(style[AXIS_GUIDES][0]["label"], "soglia")
        self.assertEqual(style[AXIS_BANDS][0]["upper"], 6.0)

    def test_shapes(self):
        from analisi.graph_shapes import SHAPES
        from trama_qt.shapes import GraphShapesDialog, ShapeEditor
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertTrue(window.actions["shapes"].isEnabled())
        axes = graph.result.figure.axes[0]
        editor = ShapeEditor(window, axes)
        self.assertFalse(editor.fields["fill"].isEnabled())  # A line has no interior.
        editor.fields["x2"].setText("0,2")
        editor.fields["y2"].setText("0,3")
        editor.accept()
        self.assertIsNone(editor.result)  # Zero-length line.
        self.assertTrue(editor.problem.text())
        editor.fields["kind"].set("rectangle")
        self.assertTrue(editor.fields["fill"].isEnabled())
        editor.fields["x2"].setText("0,6")
        editor.fields["y2"].setText("0,8")
        editor.fields["fill"].setText("#ffeeaa")
        editor.fields["hatch"].set("diagonal")
        editor.accept()
        rectangle = editor.result
        self.assertEqual(rectangle["points"], [[0.2, 0.3], [0.6, 0.8]])
        dialog = GraphShapesDialog(window, axes, [rectangle])
        dialog.duplicate()
        dialog.move(-1)
        self.assertEqual(len(dialog.records), 2)
        dialog.remove()
        dialog.accept()
        window.project.apply_format(graph, dict(graph.style or {}, shapes=dialog.result))
        saved = self.folder / "shapes.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        self.assertEqual(window.project.runs[index].style[SHAPES][0]["hatch"], "diagonal")

    def test_pairwise_comparisons_and_letters(self):
        from unittest import mock
        from analisi import pairwise_graph as pg
        from trama_qt.pairwise import PairwiseDialog
        window = self.window
        self.open_example()
        self.run_method("Paired t-test (columns)", {"First": "Control", "Second": "Treated"})
        window.open_sheet(("data", "groups"))
        self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        index = len(window.project.runs) - 1
        window.open_sheet(("graph", index))
        self.wait()
        self.assertTrue(window.actions["pairwise"].isEnabled())
        seen = {}

        def run_dialog(dialog):
            seen["rows"] = len(dialog.rows)
            dialog.cutoff.setText("2")
            dialog.filter.set(pg.AT_OR_BELOW)
            dialog.accept()
            seen["problem"] = dialog.problem.text()
            dialog.cutoff.setText("0,05")
            dialog.filter.set(pg.NO_FILTER)
            dialog.label.set(pg.P_VALUE)
            dialog.accept()
            return PairwiseDialog.DialogCode.Accepted

        with mock.patch.object(PairwiseDialog, "exec", run_dialog):
            window.pairwise_comparisons()
            self.wait()
        self.assertEqual(seen["rows"], 1)
        self.assertTrue(seen["problem"])  # Cutoff above 1.
        run = window.project.runs[index]
        self.assertEqual(run.options[pg.SECTION]["Label"], pg.P_VALUE)
        self.assertTrue(pg.drawn_brackets(run.result.figure))

        def letters(dialog):
            self.assertEqual(dialog.display.value(), pg.LETTERS)
            dialog.accept()
            return PairwiseDialog.DialogCode.Accepted

        window.open_sheet(("graph", index))
        with mock.patch.object(PairwiseDialog, "exec", letters):
            window.pairwise_comparisons(letters=True)
            self.wait()
        run = window.project.runs[index]
        self.assertEqual(run.options[pg.SECTION]["Display"], pg.LETTERS)
        self.assertTrue(pg.drawn_letters(run.result.figure))

    def test_duplicate_and_save_family(self):
        from unittest import mock
        from trama_qt.family import FamilyDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("data", "groups"))
        self.assertTrue(window.actions["duplicate_family"].isEnabled())
        seen = {}

        def duplicate(dialog):
            seen["preview"] = dialog.preview.toPlainText()
            dialog.name.setText("groups")
            dialog.accept()
            seen["problem"] = dialog.problem.text()  # The name is taken.
            dialog.name.setText("Repeat")
            dialog.accept()
            return FamilyDialog.DialogCode.Accepted

        with mock.patch.object(FamilyDialog, "exec", duplicate):
            window.duplicate_family()
            self.wait()
        self.assertIn("Column graph", seen["preview"])
        self.assertTrue(seen["problem"])
        self.assertIn("Repeat", window.project.tables)
        self.assertEqual([run.method for run in window.project.runs if run.title == "Repeat"], ["Column graph"])
        self.assertEqual(window.selected, ("data", "Repeat"))
        self.assertTrue(window.project.dirty)

        target = self.folder / "family.alab"
        window.open_sheet(("graph", window.project.runs.index(graph)))
        self.wait()
        with mock.patch.object(FamilyDialog, "exec", lambda dialog: dialog.accept() or FamilyDialog.DialogCode.Accepted), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window.save_family_as()
            self.wait()
        self.assertTrue(target.exists())
        from analisi.data import load_workspace
        tables, _, _ = load_workspace(target, include_info=True)
        self.assertEqual(list(tables), ["groups"])

    def test_duplicate_graph_with_empty_responses_opens_its_data_for_reuse(self):
        from unittest.mock import patch
        from trama_qt.family import FamilyDialog

        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("graph", window.project.runs.index(graph)))
        source = window.project.tables["groups"]

        def duplicate(dialog):
            dialog.name.setText("Repeat ")
            self.assertFalse(any(option.isChecked() for option in dialog.blank_options.values()))
            dialog.blank_options["values"].setChecked(True)
            dialog.blank_options["graph_titles"].setChecked(True)
            dialog.accept()
            return FamilyDialog.DialogCode.Accepted

        with patch.object(FamilyDialog, "exec", duplicate):
            window.actions["duplicate_family"].trigger()
            self.wait()
        copied = window.project.tables["Repeat groups"]
        self.assertEqual(window.selected, ("data", "Repeat groups"))
        self.assertTrue(copied.raw.isna().all().all())
        self.assertTrue(source.raw.notna().any().any())
        self.assertEqual(copied.analyses, source.analyses)
        self.assertEqual(copied.graph_styles[0]["title"], "")

    def test_variable_properties_validates_edits_and_survives_undo_and_save(self):
        from unittest.mock import patch
        import pandas as pd
        from analisi.data import load_workspace, save_project
        from analisi.variable_types import VARIABLE_TYPES
        from trama_qt.variables import VariablesDialog

        window = self.window
        frame = pd.DataFrame({"ID": ["001", "002"], "Measurement": ["1,25", "2,50"], "Group": ["A", "B"]})
        window.project.add_tables({"Variables": frame})
        window.open_sheet(("data", "Variables"))
        self.assertIn(window.actions["variable_properties"], window.command_menus["Change"].actions())

        def apply(dialog):
            dialog.table.item(0, 0).setText("Group")
            dialog.accept()
            self.assertTrue(dialog.problem.text())
            self.assertFalse(window.project.tables["Variables"].raw.attrs.get(VARIABLE_TYPES))
            dialog.table.item(0, 0).setText("Code")
            dialog.types[1].setCurrentIndex(dialog.types[1].findData("numeric"))
            dialog.types[2].setCurrentIndex(dialog.types[2].findData("categorical"))
            dialog.accept()
            return VariablesDialog.DialogCode.Accepted

        with patch.object(VariablesDialog, "exec", apply):
            window.actions["variable_properties"].trigger()
        dataset = window.project.tables["Variables"]
        self.assertEqual(list(dataset.raw["Measurement"]), [1.25, 2.50])
        self.assertEqual(list(dataset.raw["Code"]), ["001", "002"])
        self.assertEqual(dataset.raw.attrs[VARIABLE_TYPES], {"Measurement": "numeric", "Group": "categorical"})
        window.actions["undo"].trigger()
        self.assertEqual(list(dataset.raw), ["ID", "Measurement", "Group"])
        self.assertNotIn(VARIABLE_TYPES, dataset.raw.attrs)
        window.actions["redo"].trigger()
        path = self.folder / "variables.alab"
        save_project(path, window.project.tables)
        tables, _ = load_workspace(path)
        self.assertEqual(tables["Variables"].raw.attrs[VARIABLE_TYPES], dataset.raw.attrs[VARIABLE_TYPES])

    def test_explicit_numeric_type_survives_empty_paste_and_protects_formula_references(self):
        import pandas as pd
        from analisi.data import Dataset
        from trama_qt.project import Project

        project = Project()
        dataset = Dataset(pd.DataFrame({"Input": pd.Series([pd.NA], dtype="Float64")}),
                          formulas={"Output": '=COL("Input") * 2'})
        project.tables["Typed"] = dataset
        with self.assertRaisesRegex(ValueError, "Input"):
            project.change_variables("Typed", {"Input": ("Renamed", "numeric")})
        project.change_variables("Typed", {"Input": ("Input", "numeric")})
        with self.assertRaisesRegex(ValueError, "Input"):
            project.paste("Typed", 0, 0, [["abc"]])
        self.assertTrue(dataset.raw["Input"].isna().all())
        project.paste("Typed", 0, 0, [["2,5"]])
        self.assertEqual(dataset.frame()["Output"].iloc[0], 5)

    def test_edit_menu_copies_the_visible_result_table(self):
        window = self.window
        self.open_example()
        self.run_method("Descriptive statistics", {"Variables": ["Control", "Treated"]})
        view = window.result_tabs.currentWidget()
        view.setCurrentIndex(view.model().index(0, 0))
        action = window.actions["copy"]
        self.assertTrue(action.isEnabled())
        self.assertIn(action, window.command_menus["Edit"].actions())
        action.trigger()
        self.assertTrue(self.app.clipboard().text())

    def test_info_sheet_editing(self):
        from unittest import mock
        from analisi.info import NOTE_BOLD
        from trama_qt.info_editor import InfoDetails
        window = self.window
        self.open_example()

        def details(dialog):
            dialog.title.setText("Esperimento")
            dialog.scope.setCurrentIndex(1)  # The groups table.
            dialog.accept()
            return InfoDetails.DialogCode.Accepted

        with mock.patch.object(InfoDetails, "exec", details):
            window.new_info()
        self.assertEqual(window.selected[0], "info")
        uid = window.selected[1]
        editor = window.info_editor
        editor.add_row()
        row = len(editor.sheet.fields) - 1
        editor.table.item(row, 0).setText("Dose")
        editor.table.item(row, 1).setText("10")
        self.assertEqual(window.project.tables["groups"].info.get("dose"), "10")
        editor.notes.setPlainText("Nota importante")
        cursor = editor.notes.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(15, cursor.MoveMode.KeepAnchor)
        editor.notes.setTextCursor(cursor)
        editor.toggle_style(NOTE_BOLD)
        window.open_sheet(("data", "groups"))  # Leaving the sheet stores the notes.
        sheet = window.project.info_sheets[uid]
        self.assertEqual((sheet.notes, sheet.note_styles), ("Nota importante", ((5, 15, NOTE_BOLD),)))
        saved = self.folder / "info.alab"
        window.project.save(saved)
        self.reopen(saved)
        sheet = next(iter(window.project.info_sheets.values()))
        self.assertEqual((sheet.title, sheet.table), ("Esperimento", "groups"))
        self.assertIn(("Dose", "10"), sheet.fields)
        self.assertEqual(sheet.note_styles, ((5, 15, NOTE_BOLD),))
        window.open_sheet(("info", sheet.uid))
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            window.remove_info()
        self.assertFalse(window.project.info_sheets)

    def test_info_multiline_styles_survive_navigation_and_can_be_toggled(self):
        from PySide6.QtGui import QTextCursor
        from analisi.info import InfoSheet, NOTE_BOLD, NOTE_ITALIC, NOTE_UNDERLINE

        self.open_example()
        window = self.window
        text = "\nA🧪\n\nB\n"
        styles = ((0, 1, NOTE_ITALIC), (3, 5, NOTE_UNDERLINE), (6, 7, NOTE_ITALIC))
        sheet = InfoSheet("Multiline notes", notes=text, note_styles=styles)
        window.project.update_info_sheets({sheet.uid: sheet})
        saved = self.folder / "multiline-notes.alab"
        window.project.save(saved)
        self.reopen(saved)
        window.open_sheet(("info", sheet.uid))
        reopened_notes = window.info_editor.read_notes()
        window.open_sheet(("data", "groups"))
        self.assertEqual(reopened_notes, (text, styles))
        self.assertFalse(window.project.dirty)

        window.open_sheet(("info", sheet.uid))
        editor = window.info_editor
        cursor = editor.notes.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.notes.setTextCursor(cursor)
        editor.toggle_style(NOTE_BOLD)
        expected = ((0, 1, NOTE_BOLD | NOTE_ITALIC), (1, 3, NOTE_BOLD),
                    (3, 5, NOTE_BOLD | NOTE_UNDERLINE), (5, 6, NOTE_BOLD),
                    (6, 7, NOTE_BOLD | NOTE_ITALIC))
        self.assertEqual(editor.read_notes(), (text, expected))
        editor.toggle_style(NOTE_BOLD)
        window.open_sheet(("data", "groups"))
        window.project.save(saved)
        self.reopen(saved)
        self.assertEqual(window.project.info_sheets[sheet.uid], sheet)

    def test_info_import_keeps_pending_typing_and_undo_after_rejection(self):
        from unittest.mock import patch
        from analisi.info import InfoSheet, NOTE_BOLD

        self.open_example()
        sheet = InfoSheet("Study", notes="AB", note_styles=((0, 1, NOTE_BOLD),))
        self.window.project.update_info_sheets({sheet.uid: sheet})
        self.window.open_sheet(("info", sheet.uid))
        editor = self.window.info_editor
        errors = []
        editor.error = errors.append
        cursor = editor.notes.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("🧪")
        path = self.folder / "append.txt"
        with patch("analisi.info.MAX_INFO_NOTES", 8), patch(
                "trama_qt.info_editor.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            for invalid in (b"1234", b"a\x00b"):
                path.write_bytes(invalid)
                editor.import_notes()
                self.assertEqual(editor.read_notes(), ("AB🧪", sheet.note_styles))
                self.assertTrue(editor.notes.document().isUndoAvailable())
            self.assertEqual(len(errors), 2)
            path.write_bytes(b"\xef\xbb\xbfX\r\nY")
            editor.import_notes()
        self.assertEqual(editor.sheet.notes, "AB🧪\n\nX\nY")
        self.assertEqual(editor.sheet.note_styles, sheet.note_styles)
        self.window.actions["undo"].trigger()
        self.assertEqual(editor.sheet.notes, "AB🧪")
        self.assertEqual(editor.read_notes(), ("AB🧪", sheet.note_styles))

    def test_info_undo_keeps_note_edits_separate_from_worksheet_history(self):
        from PySide6.QtGui import QTextCursor
        from analisi.info import InfoSheet, NOTE_UNDERLINE

        self.open_example()
        window = self.window
        window.edit_cell("groups", 0, 0, "8")
        sheet = InfoSheet("Study", notes="Dose 🧪\nReadout")
        window.project.update_info_sheets({sheet.uid: sheet})
        window.open_sheet(("info", sheet.uid))
        editor = window.info_editor
        self.assertFalse(window.actions["undo"].isEnabled())
        cursor = editor.notes.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("!")
        cursor.select(QTextCursor.SelectionType.Document)
        editor.notes.setTextCursor(cursor)
        editor.toggle_style(NOTE_UNDERLINE)
        styled = (sheet.notes + "!", ((0, len(sheet.notes) + 1, NOTE_UNDERLINE),))
        self.assertEqual(editor.read_notes(), styled)
        for action, expected in (("undo", (sheet.notes + "!", ())), ("undo", (sheet.notes, ())),
                                 ("redo", (sheet.notes + "!", ())), ("redo", styled)):
            self.assertTrue(window.actions[action].isEnabled())
            window.actions[action].trigger()
            self.assertEqual(editor.read_notes(), expected)
            self.assertEqual(window.selected, ("info", sheet.uid))
            self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 8)
        window.open_sheet(("data", "groups"))
        window.undo()
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.1)
        self.assertEqual(window.project.info_sheets[sheet.uid].note_styles, styled[1])

    def test_format_xy_graph_recipe(self):
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})

        def change(dialog):
            dialog.selector.setCurrentIndex(0)
            dialog.draw.set("Line and points")
            dialog.right["title"].setText("Right")

        self.format_with(graph, change)
        self.assertEqual(graph.options["Series style"], {"Treated": "Line and points"})
        self.assertEqual(window.project.tables["groups"].analyses[graph.slot][1]["Series style"],
                         {"Treated": "Line and points"})

    def test_xy_mixed_graph_editors_preserve_geometry_and_recipe(self):
        from unittest.mock import patch
        from matplotlib.container import BarContainer
        from PySide6.QtWidgets import QFileDialog
        from analisi.i18n import active_language, set_language
        from analisi.presentation import xy_artists, xy_gid
        from analisi.xy_series import BAR_WIDTH, BARS, STEP, XY_METHOD
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.window._ask = MainWindow._ask.__get__(self.window)
        source = self.folder / "Measurements.csv"
        pd.DataFrame({"X": [1, 2, 3, 4], "Repeated X": [1, 1, 3, 4],
                      "Left $": [2, 3, None, -1], "Right": [5, 7, 6, 4],
                      "Trend": [3, 4, None, 2]}).to_csv(source, index=False)
        self.window.open_path(source)

        def choose_data(dialog):
            controls = {name: widget for name, (_, widget) in dialog.controls.items()}
            x = controls["X"]
            x.setCurrentIndex(x.findData("X"))
            ys = controls["Y columns"]
            for i in range(ys.count()):
                item = ys.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.text() in ("Left $", "Right", "Trend")
                                   else Qt.CheckState.Unchecked)
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", choose_data):
            self.window.analyze(method=XY_METHOD)
            self.wait()
        run, = self.window.project.runs
        self.assertEqual(self.window.selected, ("graph", 0))

        def format_mixed(dialog):
            dialog.show()
            dialog.tabs.setCurrentIndex(2)
            self.app.processEvents()
            self.assertTrue(dialog.bar_width.isHidden())
            dialog.series_fields["marker_color"].setText("#222222")
            dialog.draw.set(BARS)
            self.assertEqual(dialog.draw.currentText(), "Barre")
            self.assertFalse(dialog.bar_width.isHidden())
            self.assertTrue(dialog.series_fields["visible"].isEnabled())
            self.assertFalse(dialog.series_fields["marker_color"].isEnabled())
            dialog.series_fields["visible"].setChecked(False)
            dialog.selector.setCurrentIndex(1)
            dialog.draw.set(BARS)
            dialog.side.set("Right")
            dialog.selector.setCurrentIndex(2)
            dialog.draw.set(STEP)
            self.assertEqual(dialog.draw.currentText(), "Gradini")
            self.assertTrue(dialog.series_fields["width"].isEnabled())
            self.assertFalse(dialog.series_fields["marker"].isEnabled())
            dialog.bar_width.setText("0")
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIs(dialog.focusWidget(), dialog.bar_width)
            self.assertIn("larghezza", dialog.banner.text().lower())
            dialog.bar_width.setText("1,2")

            dialog.right["scale"].set("Log")
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIs(dialog.focusWidget(), dialog.right["scale"])
            dialog.right["scale"].set("Linear")
            dialog.scales["y"].set("log")
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIs(dialog.focusWidget(), dialog.scales["y"])
            dialog.scales["y"].set("linear")
            dialog.scales["x"].set("log")
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIs(dialog.focusWidget(), dialog.scales["x"])
            dialog.scales["x"].set("linear")
            dialog.accept()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return GraphFormatDialog.DialogCode.Accepted

        with patch.object(GraphFormatDialog, "exec", format_mixed):
            self.window.format_graph()
        self.assertEqual(run.options[BAR_WIDTH], 1.2)
        self.assertEqual(run.options["Series style"], {"Left $": BARS, "Right": BARS, "Trend": STEP})
        self.assertEqual(run.style["series"]["xy:1:Left $"]["marker_color"], "#222222")

        def artists(current):
            return {xy_gid(artist): artist for artist in xy_artists(current.result.figure.axes[0])}

        drawn = artists(run)
        left, right = drawn["xy:1:Left $"], drawn["xy:1:Right"]
        self.assertIsInstance(left, BarContainer)
        self.assertEqual(drawn["xy:1:Trend"].get_drawstyle(), "steps-post")
        self.assertFalse(any(rect.get_visible() for rect in left.patches))
        self.assertEqual(len(left.patches), 3)
        for bar, center in ((left.patches[0], .7), (right.patches[0], 1.3)):
            self.assertAlmostEqual(bar.get_width(), .6)
            self.assertAlmostEqual(bar.get_x() + bar.get_width() / 2, center)
        self.assertIs(right.patches[0].axes, run.result.figure.axes[1])

        self.window.toggle_inspector()
        inspector = self.window.inspector
        self.assertIsNotNone(inspector)
        inspector.selector.setCurrentIndex(0)
        self.assertTrue(inspector.fields["visible"].isEnabled())
        self.assertFalse(inspector.fields["marker"].isEnabled())
        inspector.fields["visible"].setChecked(True)
        self.assertTrue(all(rect.get_visible() for rect in left.patches))
        inspector.discard()
        self.assertFalse(any(rect.get_visible() for rect in left.patches))
        inspector.fields["visible"].setChecked(True)
        self.assertTrue(inspector.apply())
        self.assertTrue(all(rect.get_visible() for rect in left.patches))

        def change_columns(dialog):
            dialog.show()
            self.app.processEvents()
            x = dialog.controls["X"][1]
            x.setCurrentIndex(x.findData("Repeated X"))
            dialog.run_button.click()
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.error_field, "Y columns")
            self.assertIs(dialog.focusWidget(), dialog.controls["Y columns"][1])
            self.assertIn("ripete X", dialog.banner.text())
            x.setCurrentIndex(x.findData("X"))
            dialog.run_button.click()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", change_columns):
            self.window.change_parameters()
            self.wait()
        updated, = self.window.project.runs
        self.assertEqual(updated.options[BAR_WIDTH], 1.2)
        self.assertEqual(updated.options["Series style"], run.options["Series style"])

        path = self.folder / "mixed.alab"
        self.window.project.save(path)
        set_language("en")
        self.window.open_path(path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        restored, = self.window.project.runs
        self.assertEqual(restored.options, updated.options)
        self.assertEqual(artists(restored)["xy:1:Trend"].get_drawstyle(), "steps-post")
        svg = self.folder / "mixed.svg"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg), "SVG (*.svg)")):
            self.window.export()
        text = svg.read_text(encoding="utf-8")
        self.assertIn('id="xybar:Right:0"', text)
        self.assertNotIn("<image", text)

    def test_axis_breaks_on_xy_graph(self):
        from analisi.axis_breaks import AXIS_BREAKS, segment_axes
        from trama_qt.axis_breaks import AxisBreaksDialog
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})
        axes = graph.result.figure.axes[0]
        dialog = AxisBreaksDialog(window, axes, {})
        self.assertFalse(dialog.gap.isEnabled())
        dialog.axis.set("y")
        dialog.count.set("2")
        for (row, name), text in {(0, "low"): "5,5", (0, "high"): "6", (0, "share"): "50",
                                  (1, "low"): "6,2", (1, "high"): "6,8", (1, "share"): "40"}.items():
            dialog.cells[(row, name)].setText(text)
        dialog.accept()
        self.assertIsNone(dialog.result)  # Shares add up to 90.
        self.assertTrue(dialog.problem.text())
        dialog.cells[(1, "share")].setText("50")
        dialog.cells[(0, "major_step")].setText("0,2")
        dialog.cells[(0, "major_origin")].setText("5,6")
        minor = dialog.cells[(0, "minor_ticks")]
        minor.setText("1,5")
        dialog.show()
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), minor)
        minor.setText("1")
        dialog.accept()
        record = dialog.result
        self.assertEqual(record["axis"], "y")

        record["segments"][0]["tick_labels"] = [[5.6, "Blank"]]
        reopened_editor = AxisBreaksDialog(window, axes, record)
        self.assertEqual(reopened_editor.read_record(), record)
        reopened_editor.reject()

        def change(format_dialog):
            self.assertIsNotNone(format_dialog.breaks_summary)
            format_dialog.axis_breaks = record
            format_dialog._break_states()
            self.assertFalse(format_dialog.axis_fields["y"]["min"].isEnabled())

        style = self.format_with(graph, change)
        self.assertEqual(style[AXIS_BREAKS]["segments"][1]["low"], 6.2)
        saved = self.folder / "breaks.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "XY series")
        window.open_sheet(("graph", index))
        self.wait()
        restored = window.project.runs[index]
        self.assertEqual(restored.style[AXIS_BREAKS], record)
        first, _ = segment_axes(restored.result.figure)
        self.assertEqual(first.get_yticks().round(4).tolist(), [5.6, 5.8, 6.0])
        self.assertEqual(first.yaxis.get_minorticklocs().round(4).tolist(), [5.5, 5.7, 5.9])

    def test_legend_formatting(self):
        from analisi.graph_legend import LEGEND_OPTIONS_KEY
        from trama_qt.legend import LegendEditor
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})
        figure = graph.result.figure
        editor = LegendEditor(window, figure, {})
        self.assertFalse(editor.non_native)
        editor.title.setText("Gruppi")
        editor.columns.setText("abc")
        editor.accept()
        self.assertIsNone(editor.result)
        self.assertTrue(editor.problem.text())
        editor.columns.setText("1")
        editor.frame.set("hidden")
        editor.accept()
        options = editor.result
        self.assertEqual(options["title"], "Gruppi")
        self.assertIs(options["frame"], False)

        def change(dialog):
            dialog.legend_options = options

        style = self.format_with(graph, change)
        self.assertEqual(style[LEGEND_OPTIONS_KEY]["title"], "Gruppi")
        legend = graph.result.figure.axes[0].get_legend() or graph.result.figure.legends[0]
        self.assertEqual(legend.get_title().get_text(), "Gruppi")

    def test_export_with_options(self):
        from unittest import mock
        from PIL import Image
        from trama_qt import export_options
        from trama_qt.export_options import ExportOptionsDialog
        self.addCleanup(lambda: (export_options.SESSION.clear(),
                                 export_options.SESSION.update(preset="Screen", **export_options.fe.PRESETS["Screen"])))
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("graph", window.project.runs.index(graph)))
        self.wait()
        self.assertTrue(window.actions["export_options"].isEnabled())
        seen = {}

        def png(dialog):
            dialog.format.setCurrentText("PNG")
            dialog.width.setText("abc")
            dialog.accept()
            seen["problem"] = dialog.summary.text()
            dialog.width.setText("85")
            dialog.dpi.setText("200")
            seen["preset"] = dialog.preset.currentData()
            seen["summary"] = dialog.summary.text()
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        target = self.folder / "graph"
        with mock.patch.object(ExportOptionsDialog, "exec", png), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window.export_with_options()
        self.assertTrue(seen["problem"])
        self.assertEqual(seen["preset"], "Custom")
        self.assertIn("669", seen["summary"])
        with Image.open(self.folder / "graph.png") as image:
            self.assertEqual(image.size[0], 669)
        self.assertEqual(export_options.SESSION["width_mm"], 85)

        # The next dialog starts from the session's choices; SVG text as paths.
        def svg(dialog):
            seen["width"] = dialog.width.text()
            dialog.format.setCurrentText("SVG")
            dialog.svg_text.setCurrentIndex(1)
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        with mock.patch.object(ExportOptionsDialog, "exec", svg), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName",
                           return_value=(str(self.folder / "graph.svg"), "")):
            window.export_with_options()
        self.assertEqual(seen["width"], "85")
        text = (self.folder / "graph.svg").read_text(encoding="utf-8")
        self.assertIn("<path", text)
        self.assertNotIn("<text", text)
        self.assertEqual(export_options.SESSION["svg_text"], "paths")  # The next dialog starts from Paths.
        dialog = ExportOptionsDialog(window, (4, 3))
        self.assertEqual(dialog.svg_text.currentData(), "paths")
        dialog.deleteLater()

        # A layout: vector PDF at a chosen width.
        window.show_sheet("data", "groups")
        self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        key = window.project.put_layout(Layout("Figura", 2, [run.reference for run in window.project.runs],
                                               AUTO_PAPER, WHITE))
        window.open_sheet(("layout", key))
        self.wait()

        def pdf(dialog):
            seen["layout_note"] = dialog.note.text()
            dialog.format.setCurrentText("PDF")
            dialog.width.setText("180")
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        with mock.patch.object(ExportOptionsDialog, "exec", pdf), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName",
                           return_value=(str(self.folder / "layout.pdf"), "")):
            window.export_with_options()
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(str(self.folder / "layout.pdf"))[0]
        self.assertAlmostEqual(page.get_width() / 72 * 25.4, 180, delta=0.5)

    def test_analysis_chains(self):
        from unittest import mock
        from analisi.analysis_chain import ResultSource
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.analysis_source import AnalysisSourceDialog
        window = self.window
        ask = type(window)._ask.__get__(window)  # The dialog opens; a failed calculation still fails the test.
        window._ask = lambda *args, error=None, **kwargs: (self.fail(f"calculation failed: {error}") if error
                                                          else ask(*args, **kwargs))
        path = self.folder / "chain.csv"
        pd.DataFrame({"X": [0.0, 1.0, 2.0, 3.0], "Y": [1.0, 3.0, 5.0, 7.0]}).to_csv(path, index=False)
        window.open_path(path)
        self.app.processEvents()
        self.run_method("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"})
        window.open_sheet(("result", 0))
        self.assertTrue(window.actions["analyze_result"].isEnabled())
        self.assertFalse(window.actions["source_analysis"].isEnabled())

        def pick(method, values):
            def run(dialog):
                if dialog.method != method:
                    dialog.method = method
                    dialog.configure_fields()
                for name, value in values.items():
                    kind, control = dialog.controls[name]
                    if isinstance(value, list):
                        for row in range(control.count()):
                            item = control.item(row)
                            item.setCheckState(Qt.CheckState.Checked if item.text() in value
                                               else Qt.CheckState.Unchecked)
                    else:
                        position = control.findData(value)
                        control.setCurrentIndex(position if position >= 0 else control.findText(value))
                dialog.accept()
                return AnalysisDialog.DialogCode.Accepted if dialog.result else AnalysisDialog.DialogCode.Rejected
            return mock.patch.object(AnalysisDialog, "exec", run)

        with pick("Normalize", {"Variables": ["X", "Y"], "Method": "Subtract first value"}):
            window.analyze_result_table()
            self.wait()
        runs = window.project.runs
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[1].source, ResultSource(runs[0].uid, "Transformed"))
        window.open_sheet(("result", 1))
        self.assertTrue(window.actions["source_analysis"].isEnabled())
        with pick("Linear regression", {"X": "X", "Y": "Y"}):
            window.analyze_result_table()
            self.wait()
        self.assertEqual(runs[2].source, ResultSource(runs[1].uid, "Normalized"))
        self.assertAlmostEqual(runs[2].result.tables["Regression"].loc["Slope", "Value"], 2.0)

        # The navigator nests each linked result under its source.
        def item_for(ref):
            found = []

            def walk(item):
                if item.data(0, Qt.ItemDataRole.UserRole) == ref:
                    found.append(item)
                for child in range(item.childCount()):
                    walk(item.child(child))
            for top in range(window.navigator.topLevelItemCount()):
                walk(window.navigator.topLevelItem(top))
            return found[0]
        self.assertEqual(item_for(("result", 1)).parent().data(0, Qt.ItemDataRole.UserRole), ("result", 0))

        window.open_sheet(("result", 2))
        window.source_analysis()
        self.assertEqual(window.selected, ("result", 1))
        self.assertEqual(window.result_tabs.tabText(window.result_tabs.currentIndex()), "Normalized")

        # Change input result: a cycle is refused in the dialog; the Transform table is accepted.
        window.open_sheet(("result", 0))
        seen = {}

        def cycle(dialog):
            dialog.source.setCurrentIndex(next(i for i, other in enumerate(dialog.parents)
                                               if other is not None and other.uid == runs[2].uid))
            dialog.accept()
            seen["cycle"] = dialog.problem.text()
            return AnalysisSourceDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisSourceDialog, "exec", cycle):
            window.change_input_result()
        self.assertIn(tr("chain.error.cycle"), seen["cycle"])
        self.assertIsNone(runs[0].source)

        def transform(dialog):
            dialog.source.setCurrentIndex(next(i for i, other in enumerate(dialog.parents)
                                               if other is not None and other.uid == runs[0].uid))
            dialog.accept()
            return AnalysisSourceDialog.DialogCode.Accepted

        window.open_sheet(("result", 2))
        with mock.patch.object(AnalysisSourceDialog, "exec", transform), pick("Linear regression", {}):
            window.change_input_result()
            self.wait()
        runs = window.project.runs
        self.assertEqual(runs[2].source, ResultSource(runs[0].uid, "Transformed"))
        self.assertAlmostEqual(runs[2].result.tables["Regression"].loc["Slope", "Value"], 2.0)

        saved = self.folder / "chain.alab"
        window.project.save(saved)
        self.reopen(saved)
        runs = window.project.runs
        self.assertEqual(runs[1].source, ResultSource(runs[0].uid, "Transformed"))
        self.assertEqual(runs[2].source, ResultSource(runs[0].uid, "Transformed"))

    def test_text_import_wizard(self):
        from unittest import mock
        from trama_qt.text_import import TextImportDialog
        window = self.window
        path = self.folder / "misure.txt"
        path.write_text("ID;Dose;Risposta;Note\n1;0,5;10,2;a\n2;1,0;-99;b\n3;1,5;12,9*;c\n4;2,0;14,1;d\n"
                        "5;2,5;15,0;e\n", encoding="utf-8")
        seen = {}

        def choose(dialog):
            seen["first"] = dialog.summary.text()
            dialog.bounds["first_column"].setText("x")
            dialog.refresh_preview()
            seen["problem"] = dialog.summary.text()
            dialog.accept()
            seen["refused"] = dialog.result is None
            dialog.bounds["first_column"].setText("2")
            dialog.bounds["last_column"].setText("3")
            dialog.bounds["last_row"].setText("4")
            dialog.missing.setText("-99")
            dialog.mark_excluded.setChecked(True)
            dialog.refresh_preview()
            seen["preview"] = [dialog.table.horizontalHeaderItem(column).text()
                               for column in range(dialog.table.columnCount())]
            seen["marked"] = dialog.table.item(2, 1).text()
            dialog.accept()
            return TextImportDialog.DialogCode.Accepted

        with mock.patch.object(TextImportDialog, "exec", choose):
            window.open_path(path, import_data=True)
        self.assertIn("5", seen["first"])
        self.assertTrue(seen["problem"])
        self.assertTrue(seen["refused"])
        self.assertEqual(seen["preview"], ["Dose", "Risposta"])
        self.assertEqual(seen["marked"], "* 12.9")
        self.assertEqual(window.selected, ("data", "misure"))
        dataset = window.project.tables["misure"]
        frame = dataset.frame()
        self.assertEqual(list(frame.columns), ["Dose", "Risposta"])
        self.assertEqual(len(frame), 4)
        self.assertAlmostEqual(frame["Dose"].iloc[1], 1.0)
        self.assertTrue(pd.isna(frame["Risposta"].iloc[1]))
        self.assertTrue(pd.isna(dataset.frame(mask_excluded=True)["Risposta"].iloc[2]))

        # Cancel adds nothing.
        with mock.patch.object(TextImportDialog, "exec", lambda dialog: TextImportDialog.DialogCode.Rejected):
            window.open_path(path, import_data=True)
        self.assertEqual(list(window.project.tables), ["misure"])

    def test_recovered_theoretical_graph_exposes_saved_equations(self):
        from analisi.legacy_restore import SAVED_XY
        from analisi.legacy_xml_generated import XML_GENERATED_XY

        frame = pd.DataFrame({"X": [0, 1], "Y1": [2, 4]})
        frame.attrs["legacy_recipes"] = [(SAVED_XY, {XML_GENERATED_XY: {
            "aspect": 1, "title": "Recovered graph", "x": "X", "series": [{"column": "Y1", "color": "#366999"}],
            "axes": [{"bounds": bound, "label": name, "ticks": bound, "minor": [], "grid": False}
                     for name, bound in (("X", [0, 1]), ("Y", [0, 5]))],
            "notes": [], "arrows": [],
            "equations": [{"column": "Y1", "equation": "Y=S*(1+X)", "parameters": {"S": 2}}],
        }})]
        self.window.project.add_tables({"Graph values": frame})
        self.window.refresh()
        self.window.open_sheet(("graph", 0))
        self.wait()
        results = self.window.actions["analysis_tables"]
        self.assertTrue(results.isEnabled())
        results.trigger()
        self.assertEqual(self.window.selected, ("result", 0))
        tabs = self.window.result_tabs
        self.assertEqual([tabs.tabText(index) for index in range(tabs.count())],
                         ["Saved XY coordinates", "Saved equations"])
        self.assertEqual(self.window.project.runs[0].result.tables["Saved equations"]["Parameters"].tolist(),
                         ["S=2"])

    def test_imported_graph_and_layout_link_to_editable_data(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QComboBox, QPushButton
        from analisi.data import Dataset, save_project
        from analisi.i18n import ui
        from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_DATA
        from analisi.legacy_restore import (
            BINARY_GRAPH_COLLECTION, BINARY_LAYOUT_COLLECTION, LEGACY_GRAPH_LINK, LEGACY_GRAPH_STYLE,
            SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_EDITABLE_GRAPH,
        )
        from analisi.workbench import Result

        path = self.folder / "legacy.alab"
        save_project(path, {
            "Original": Dataset(pd.DataFrame({"Drawing": [1]}), table_format=BINARY_GRAPH_COLLECTION,
                                analyses=[(SAVED_BINARY_GRAPH, {LEGACY_GRAPH_LINK: "graph-a"}),
                                          (SAVED_BINARY_GRAPH, {LEGACY_GRAPH_LINK: "unmatched"})]),
            "Coordinates": Dataset(pd.DataFrame({"Y": [6.], "Lower error": [1.]}), analyses=[
                (SAVED_EDITABLE_GRAPH, {LEGACY_GRAPH_LINK: "graph-a", LEGACY_GRAPH_STYLE: {}})]),
            "Page": Dataset(pd.DataFrame({"Drawing": [1]}), table_format=BINARY_LAYOUT_COLLECTION, analyses=[
                (SAVED_BINARY_LAYOUT, {LEGACY_PANEL_DATA: {"1": "graph-a", "2": "unmatched"},
                                       LEGACY_EDITABLE_PANELS: [{"id": "1", "title": "Panel A"}]})]),
        })
        window = self.window
        panel_errors = []

        def render(run, frame, control=None, layout_data=None, pairwise=None):
            if run.method == SAVED_BINARY_LAYOUT:
                panel_errors.append(layout_data["1"][0]["Lower error"].iat[0])
            return Result({})

        def click(caption):
            button = next(button for button in window.page.findChildren(QPushButton) if button.text() == ui(caption))
            button.click()
            self.wait()

        with patch("trama_qt.project.compute", side_effect=render):
            window.open_path(path)
            window.open_sheet(("graph", 0))
            self.wait()
            click("Open editable graph")
            self.assertEqual(window.selected, ("graph", 2))
            self.assertFalse(window.actions["change"].isEnabled())
            click("View original")
            self.assertEqual(window.selected, ("graph", 0))
            click("Open editable graph")
            click("Edit graph data")
            self.assertEqual(window.selected, ("data", "Coordinates"))
            window.open_sheet(("graph", 1))
            self.wait()
            self.assertNotIn(ui("Open editable graph"), [item.text() for item in window.page.findChildren(QPushButton)])
            window.open_sheet(("saved-layout", 3))
            self.wait()
            choice = window.page.findChild(QComboBox)
            self.assertEqual((choice.count(), choice.currentText()), (1, "1 · Panel A"))
            click("Edit panel data…")
            self.assertEqual(window.selected, ("data", "Coordinates"))
            self.assertTrue(window.edit_cell("Coordinates", 0, 1, "2.5"))
            self.wait()
            window.undo()
            self.wait()
        self.assertEqual(panel_errors, [1., 2.5, 1.])

    def test_export_imported_original_vectors_without_rendering(self):
        from io import BytesIO
        from unittest.mock import patch

        from matplotlib.figure import Figure
        from PySide6.QtWidgets import QFileDialog
        from analisi.legacy_restore import LEGACY_PREVIEW, SAVED_BINARY_GRAPH
        from trama_qt.project import Run

        original_emf = _emf_drawing(pack("<II4i", 43, 24, 4, 6, 12, 18))
        pdf = BytesIO()
        figure = Figure(figsize=(2, 1))
        figure.add_subplot().plot([0, 1], [0, 1])
        figure.savefig(pdf, format="pdf")
        window = self.window
        window.selected = ("graph", 0)
        for fmt, data in (("emf", original_emf), ("pdf", pdf.getvalue())):
            with self.subTest(fmt=fmt):
                run = Run(SAVED_BINARY_GRAPH, "Drawing", {LEGACY_PREVIEW: _vector_record(data, fmt)})
                window.project.runs = [run]
                target = self.folder / "Original"
                with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")) as dialog:
                    window.export()
                self.assertTrue(dialog.call_args.args[3].startswith(f"{fmt.upper()} "))
                self.assertEqual(target.with_suffix(f".{fmt}").read_bytes(), data)

    def test_export_edited_imported_xy_keeps_vector_error_bars(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QFileDialog
        from analisi.data import Dataset, EDITABLE_LEGACY_EMF
        from analisi.legacy_emf_edit import POINTS
        from analisi.legacy_restore import LEGACY_GRAPH_STYLE, LEGACY_PREVIEW, SAVED_EDITABLE_GRAPH
        from trama_qt.project import Run

        def line(x, y, xx, yy):
            return pack("<II2iII2i", 27, 16, x, y, 54, 16, xx, yy)

        marker = pack("<II4i", 42, 24, 35, 35, 45, 45)
        unchanged = line(30, 20, 50, 20) + line(10, 15, 90, 15)
        original = _emf_drawing(marker + line(40, 20, 40, 50) + line(30, 50, 50, 50) + unchanged, 9)
        edited = _emf_drawing(marker + line(40, 20, 40, 60) + line(30, 60, 50, 60) + unchanged, 9)
        axes = {"bounds": [0., 10.], "unit": .1, "scale": "linear"}
        style = {"kind": POINTS, "chart": [0, 0, 100, 100], "axes": [axes, axes],
                 "source": [[4., 6., 2., 1.]]}
        run = Run(SAVED_EDITABLE_GRAPH, "XY", {LEGACY_GRAPH_STYLE: style, LEGACY_PREVIEW: _vector_record(original)})
        frame = pd.DataFrame({"X": [4.], "Y": [6.], "Upper error": [2.], "Lower error": [2.], "Series": ["A"]})
        window = self.window
        window.project.tables["XY"] = Dataset(frame, table_format=EDITABLE_LEGACY_EMF)
        window.project.runs = [run]
        window.selected = ("graph", 0)
        target = self.folder / "Adjusted.emf"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            window.export()
        self.assertEqual(target.read_bytes(), edited)
        self.assertEqual(run.options[LEGACY_PREVIEW], _vector_record(original))

    def test_export_imported_layout_preserves_original_and_current_emf(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QFileDialog, QPushButton
        from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_EDITS
        from analisi.legacy_restore import LEGACY_PREVIEW, SAVED_BINARY_LAYOUT
        from analisi.workbench import Result
        from trama_qt.project import Run

        original = _emf_layout()
        edited = _emf_layout(first=(14, 18, 76, 42))
        run = Run(SAVED_BINARY_LAYOUT, "Page", {
            LEGACY_PREVIEW: _vector_record(original),
            LEGACY_EDITABLE_PANELS: [{"id": "1", "bounds": [10, 10, 110, 70]},
                                    {"id": "2", "bounds": [120, 80, 220, 140]}],
            LEGACY_PANEL_EDITS: {"1": [14, 18, 90, 60]},
        }, result=Result({}))
        window = self.window
        window.project.runs = [run]
        window.show_sheet("saved-layout", 0)
        button = next((button for button in window.page.findChildren(QPushButton)
                       if button.text() == tr("layout.export_current_emf")), None)
        self.assertIsNotNone(button, "The layout must offer its current drawing separately")
        current = self.folder / "Current"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(current), "")):
            button.click()
        self.assertEqual(current.with_suffix(".emf").read_bytes(), edited)
        archive = self.folder / "Original.emf"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(archive), "")):
            window.export()
        self.assertEqual(archive.read_bytes(), original)

    def test_edit_imported_panel_geometry_and_reopen(self):
        from unittest.mock import patch

        from PIL import Image
        from PySide6.QtWidgets import QDialog, QPushButton
        from analisi.data import Dataset, save_project
        from analisi.legacy_binary_graphs import validate_binary_graph
        from analisi.legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_EDITS
        from analisi.legacy_restore import BINARY_LAYOUT_COLLECTION, LEGACY_PREVIEW, SAVED_BINARY_LAYOUT

        original = _emf_layout()
        earlier = [120, 81, 219, 139]
        expected_prior = _emf_layout(second=(120, 81, 99, 58))
        expected_edited = _emf_layout((14, 18, 76, 42), (120, 81, 99, 58))
        edits = {"2": earlier}
        options = {LEGACY_PREVIEW: _vector_record(original), LEGACY_PANEL_EDITS: edits,
                   LEGACY_EDITABLE_PANELS: [{"id": "1", "title": "First", "bounds": [10, 10, 110, 70]},
                                           {"id": "2", "title": "Second", "bounds": [120, 80, 220, 140]}]}
        seed = self.folder / "original.alab"
        save_project(seed, {"Page": Dataset(pd.DataFrame({"Drawing": [1]}), table_format=BINARY_LAYOUT_COLLECTION,
                                           analyses=[(SAVED_BINARY_LAYOUT, options)])})
        rendered = []

        def render(preview, *, layout=False, crop=True):
            rendered.append(validate_binary_graph(preview, layout=layout))
            return Image.new("RGB", (20, 16))

        window = self.window

        def edit(action):
            button = window.page.findChild(QPushButton, "importedPanelGeometry")
            self.assertIsNotNone(button, "Editable saved layouts need a position and size command")
            with patch.object(QDialog, "exec", action):
                button.click()
            self.wait()

        def cancel(dialog):
            dialog.fields[0].setText("12")
            dialog.reject()
            return QDialog.DialogCode.Rejected

        def move(dialog):
            dialog.selector.setCurrentIndex(1)
            self.assertEqual([field.text() for field in dialog.fields], ["120", "81", "99", "58"])
            dialog.selector.setCurrentIndex(0)
            dialog.fields[2].setText("zero")
            dialog.accept()
            self.assertTrue(dialog.problem.text())
            self.assertIsNone(dialog.result)
            dialog.fields[2].setText("0")
            dialog.accept()
            self.assertTrue(dialog.problem.text())
            self.assertIsNone(dialog.result)
            for field, value in zip(dialog.fields, (14, 18, 76, 42), strict=True):
                field.setText(str(value))
            dialog.accept()
            self.assertEqual(dialog.result, {"1": [14, 18, 90, 60], "2": earlier})
            return QDialog.DialogCode.Accepted

        def restore(dialog):
            self.assertEqual([field.text() for field in dialog.fields], ["14", "18", "76", "42"])
            dialog.restore.click()
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch("analisi.legacy_binary_graphs.render_binary_graph", side_effect=render):
            window.open_path(seed)
            window.open_sheet(("saved-layout", 0))
            self.wait()
            before = window.project.runs[0]
            self.assertEqual(rendered[-1], expected_prior)
            edit(cancel)
            self.assertIs(window.project.runs[0], before)
            self.assertFalse(window.project.dirty)
            edit(move)
            run = window.project.runs[0]
            self.assertEqual(window.selected, ("saved-layout", 0))
            self.assertEqual(run.uid, before.uid)
            self.assertEqual(rendered[-1], expected_edited)
            self.assertTrue(window.project.dirty)
            self.assertEqual(run.options[LEGACY_PREVIEW], options[LEGACY_PREVIEW])
            saved = self.folder / "edited.alab"
            window.project.save(saved)
            window.open_path(saved)
            window.open_sheet(("saved-layout", 0))
            self.wait()
            self.assertEqual(rendered[-1], expected_edited)
            edit(restore)
            self.assertEqual(window.project.runs[0].options[LEGACY_PANEL_EDITS], edits)
            self.assertEqual(rendered[-1], expected_prior)

    def test_layout_compose_edit_reopen(self):
        from trama_qt.layout_dialog import LayoutDialog
        window = self.window
        self.open_example()
        self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.show_sheet("data", "groups")
        self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        candidates = window.project.layout_candidates()
        self.assertEqual(len(candidates), 2)
        dialog = LayoutDialog(window, candidates)
        dialog.accept()
        self.assertIsNone(dialog.result)  # No panels yet.
        self.assertTrue(dialog.problem.text())
        dialog.available.selectAll()
        dialog.add_selected()
        dialog.panels.setCurrentRow(1)
        dialog.move_selected(-1)
        dialog.name.setText("Figura 1")
        dialog.accept()
        layout = dialog.result
        self.assertEqual(layout.panels, [candidates[1].reference, candidates[0].reference])
        key = window.project.put_layout(layout)
        window.open_sheet(("layout", key))
        self.wait()
        self.assertEqual(window.selected, ("layout", key))
        self.assertTrue(window.page.canvases)
        self.assertTrue(window.actions["edit_layout"].isEnabled())

        saved = self.folder / "layout.alab"
        window.project.save(saved)
        self.reopen(saved)
        self.assertEqual([item.name for item in window.project.layouts], ["Figura 1"])
        window.open_sheet(("layout", 0))
        self.wait()
        self.assertIsNotNone(window.project.layout_figure(window.project.layouts[0]))

        # Layout export (vector PDF/SVG, raster PNG) and the multi-page PDF of graphs and layouts.
        layout = window.project.layouts[0]
        for name in ("layout.pdf", "layout.svg", "layout.png"):
            window.project.export_layout(layout, self.folder / name)
            self.assertGreater((self.folder / name).stat().st_size, 1000, name)
        from trama_qt.pdf_bundle import PdfBundleDialog, bundle_sheets
        for index in range(len(window.project.runs)):
            window.open_sheet(("graph", index))
            self.wait()
        entries, notes = bundle_sheets(window.project, range(len(window.project.runs)), ())
        self.assertEqual([entry.kind for entry in entries], ["Graph", "Graph", "Layout"])
        dialog = PdfBundleDialog(window, entries, notes)
        dialog.width.setText("abc")
        dialog.accept()
        self.assertIsNone(dialog.result)
        dialog.width.setText("120")
        dialog.list.item(0).setSelected(False)
        dialog.accept()
        self.assertEqual(dialog.result["refs"], [entries[1].ref, entries[2].ref])
        pages = window.project.export_pdf_pages(dialog.result["refs"], self.folder / "bundle.pdf",
                                                dialog.result["settings"], ["a", "b"])
        self.assertEqual(pages, 2)
        import pypdfium2 as pdfium
        self.assertEqual(len(pdfium.PdfDocument(str(self.folder / "bundle.pdf"))), 2)

    def test_layout_panel_arrangement_undo_and_exports(self):
        from unittest.mock import patch
        from analisi.presentation import Layout
        from trama_qt.gallery_catalog import describe
        from trama_qt.gallery_thumbs import render
        from trama_qt.layout_dialog import LayoutDialog

        window = self.window
        self.open_example()
        first = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.show_sheet("data", "groups")
        second = self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        second.result.figure.set_size_inches(4, 6, forward=False)
        original = Layout("Panel layout", 2, [first.reference, second.reference, second.reference, first.reference])
        ref = ("layout", window.project.put_layout(original))
        window.open_sheet(ref)
        self.wait()
        before = describe(window.project, ref).sig

        def edit(dialog):
            dialog.resize(480, 490)
            dialog.show()
            self.app.processEvents()
            for field, mode in ((dialog.panel_size, "both"), (dialog.axis_alignment, "both")):
                self.assertTrue(field.isVisible())
                self.assertLessEqual(field.mapTo(dialog, field.rect().bottomRight()).x(), dialog.width())
                field.setCurrentIndex(field.findData(mode))
            dialog.accept()
            self.assertIsNotNone(dialog.result)
            return LayoutDialog.DialogCode.Accepted

        with patch.object(LayoutDialog, "exec", edit):
            window.actions["edit_layout"].trigger()
        layout = window.project.layouts[0]
        self.assertEqual((layout.panel_size, layout.axis_alignment), ("both", "both"))
        entry = describe(window.project, ref)
        self.assertNotEqual(entry.sig, before)
        thumbnail = render(entry, window.project, (160, 120))
        while True:
            try:
                next(thumbnail)
            except StopIteration as finished:
                self.assertFalse(finished.value.isNull())
                break

        figure = window.layout_figure
        self.assertEqual(len(figure.axes), 4)
        self.assertEqual(len({tuple(round(value, 8) for value in axis.get_position().size) for axis in figure.axes}), 1)
        window.actions["undo"].trigger()
        self.assertEqual(window.project.layouts[0], original)
        window.actions["redo"].trigger()
        self.assertEqual(window.project.layouts[0], layout)

        path = self.folder / "arranged.alab"
        window.project.save(path)
        self.reopen(path)
        window.open_sheet(ref)
        self.wait()
        self.assertEqual(window.project.layouts[0], layout)
        for kind in ("svg", "pdf", "png", "tiff"):
            target = self.folder / f"arranged.{kind}"
            window.project.export_layout(layout, target)
            self.assertGreater(target.stat().st_size, 1000)
        self.assertNotIn("<image", (self.folder / "arranged.svg").read_text(encoding="utf-8"))

    def test_keep_calculated_values_targets_the_clicked_heading_and_supports_undo(self):
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QMenu
        from analisi.i18n import tr

        window = self.window
        title = window.project.add_tables({"Study": pd.DataFrame({"Dose": [2, 4], "Result": [None, None]})})[0]
        dataset = window.project.tables[title]
        dataset.set_worksheet_formula(1, "=Dose * 2")
        window.open_sheet(("data", title))
        view = window.sheet
        view.setCurrentIndex(view.model().index(0, 0))
        heading = view.horizontalHeader()
        popup = []

        def close_menu():
            menu = next((child for child in view.findChildren(QMenu) if child.isVisible()), None)
            if menu is not None:
                popup.extend(menu.actions())
                menu.close()

        timer = QTimer(heading)
        timer.setSingleShot(True)
        timer.timeout.connect(close_menu)
        timer.start(10)
        heading.customContextMenuRequested.emit(QPoint(heading.sectionViewportPosition(1) + 10, 4))
        timer.stop()
        self.assertEqual([action.text() for action in popup], [tr("worksheet.formula.freeze")])
        popup[0].trigger()
        self.assertEqual(dataset.formulas, {})
        self.assertEqual(dataset.raw["Result"].tolist(), [4, 8])
        window.undo()
        self.assertIn("Result", dataset.formulas)
        self.assertNotIn("Result", dataset.raw)
        window.undo(redo=True)
        self.assertEqual(dataset.raw["Result"].tolist(), [4, 8])

    def test_insert_delete_rename_and_exclude(self):
        window = self.window
        self.open_example()
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.insert_row()
        self.assertEqual(len(window.project.tables["groups"].raw), 6)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.delete_rows()
        self.assertEqual(len(window.project.tables["groups"].raw), 5)
        window.sheet.setCurrentIndex(window.sheet.model().index(2, 1))
        window.toggle_exclusion()
        self.assertIn((2, 1), window.project.tables["groups"].excluded)
        window.project.rename_column("groups", 1, "Drug")
        self.assertEqual(list(window.project.tables["groups"].raw.columns), ["Control", "Drug"])

    def test_formula_columns_and_cell_editing(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication as _App
        window = self.window
        self.open_example()
        self.assertTrue(window.actions["formula"].isEnabled())

        window.actions["formula"].trigger()
        panel = window.formula_editor
        self.assertTrue(window.sheet.isVisible())
        self.assertTrue(panel.isVisible())
        panel.name.setText("Double")
        panel.expression.setPlainText("=Control *")
        panel.apply_button.click()
        self.assertTrue(panel.problem.text())
        self.assertIs(window.formula_editor, panel)
        panel.expression.setPlainText("=Control * 2")
        self.assertEqual(window.sheet.formula_columns, (0,))
        panel.apply_button.click()
        self.assertIsNone(window.formula_editor)
        self.assertEqual(window.sheet.formula_columns, ())
        dataset = window.project.tables["groups"]
        self.assertEqual(dataset.formulas, {"Double": "=Control * 2"})
        self.assertAlmostEqual(dataset.frame()["Double"].iloc[0], 8.2)

        # A double click on the calculated column's header opens its formula to change.
        window.rename_column(2)
        panel = window.formula_editor
        self.assertEqual((panel.name.text(), panel.expression.toPlainText()), ("Double", "=Control * 2"))
        panel.expression.setPlainText("=Control * 3")
        panel.apply_button.click()
        self.assertAlmostEqual(window.project.tables["groups"].frame()["Double"].iloc[0], 12.3)
        window.undo()
        self.assertEqual(window.project.tables["groups"].formulas["Double"], "=Control * 2")

        # F2, a value and Enter write the cell and move down one row.
        sheet = window.sheet
        sheet.setFocus()
        sheet.setCurrentIndex(sheet.model().index(0, 0))
        QTest.keyClick(sheet, Qt.Key.Key_F2)
        editor = _App.focusWidget()
        editor.setText("9")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.wait()
        self.assertAlmostEqual(window.project.tables["groups"].raw.iloc[0, 0], 9.0)
        self.assertEqual(window.sheet.currentIndex().row(), 1)

    def test_formula_typed_into_empty_variable_stays_in_its_column(self):
        window = self.window
        frame = pd.DataFrame({"Input": [2., 4.], "Output": [None, None], "Other": [1., 3.]})
        window.project.add_tables({"Study": frame})
        window.open_sheet(("data", "Study"))
        dataset = window.project.tables["Study"]
        window.edit_cell("Study", 0, 1, "=A * 2 + C")
        self.wait()
        self.assertIn("Output", dataset.formulas)
        self.assertEqual(list(dataset.frame()), ["Input", "Output", "Other"])
        self.assertEqual(dataset.frame()["Output"].tolist(), [5., 11.])
        window.edit_cell("Study", 0, 2, "10")
        self.wait()
        self.assertEqual(dataset.frame()["Output"].tolist(), [14., 11.])
        window.undo()
        window.undo()
        self.assertFalse(dataset.formulas)
        self.assertTrue(dataset.raw["Output"].isna().all())
        window.undo(redo=True)
        self.assertEqual(dataset.frame()["Output"].tolist(), [5., 11.])

    def test_formula_reference_inserts_a_search_result_without_closing_the_editor(self):
        from PySide6.QtTest import QTest
        from analisi.data import Dataset
        from trama_qt.formula import FormulaEditor

        name = "Dòse [μM] 'étape' \"A\""
        dataset = Dataset(pd.DataFrame({"Observed": [2., 4.], name: [8., 10.],
                                        "Derived dose": [None, None]}))
        dialog = FormulaEditor(dataset, column=2)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        dialog.reference_search.setText("dose [μm]")
        self.assertEqual(dialog.reference_results.count(), 1)
        dialog.expression.setPlainText("=2 * placeholder")
        cursor = dialog.expression.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(len("=2 * placeholder"), cursor.MoveMode.KeepAnchor)
        dialog.expression.setTextCursor(cursor)
        QTest.keyClick(dialog.reference_search, Qt.Key.Key_Return)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.expression.toPlainText().startswith("=2 * COL("))
        validated = dialog.validated_formula()
        self.assertIsNotNone(validated)
        self.assertFalse(dataset.formulas)
        dataset.set_worksheet_formula(2, validated[1])
        self.assertEqual(dataset.frame()["Derived dose"].tolist(), [16., 20.])

    def test_formula_errors_stay_next_to_the_expression(self):
        from analisi.data import Dataset
        from trama_qt.formula import FormulaEditor

        dataset = Dataset(pd.DataFrame({"Observed": [0., 1.]}))
        dialog = FormulaEditor(dataset, "Density")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        dialog.expression.setPlainText("=1 +")
        self.assertIsNone(dialog.validated_formula())
        self.app.processEvents()
        self.assertTrue(dialog.problem.isVisible())
        self.assertLess(dialog.expression.y(), dialog.problem.y())
        self.assertLess(dialog.problem.y(), dialog.reference_results.y())
        self.assertIs(dialog.focusWidget(), dialog.expression)
        dialog.expression.setPlainText("=2")
        self.assertFalse(dialog.problem.isVisible())

    def test_formula_reference_search_accepts_clear_and_arrow_navigation(self):
        from PySide6.QtTest import QTest
        from analisi.data import Dataset
        from trama_qt.formula import FormulaEditor

        dataset = Dataset(pd.DataFrame({"Dose low": [0., 1.], "Dose high": [3., 4.]}))
        dialog = FormulaEditor(dataset, "Density")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        dialog.reference_search.setText("dose")
        self.assertTrue(dialog.reference_search.isClearButtonEnabled())
        self.assertEqual(dialog.reference_results.count(), 2)
        QTest.keyClick(dialog.reference_search, Qt.Key.Key_Down)
        self.assertEqual(dialog.reference_results.currentRow(), 1)
        QTest.keyClick(dialog.reference_search, Qt.Key.Key_Return)
        self.assertIn("Dose high", dialog.expression.toPlainText())
        self.assertTrue(dialog.isVisible())

    def test_formula_function_reference_uses_engine_signature_and_leaves_caret_inside(self):
        from PySide6.QtTest import QTest
        from analisi.data import Dataset
        from trama_qt.formula import FormulaEditor

        dataset = Dataset(pd.DataFrame({"Observed": [0., 1.]}))
        dialog = FormulaEditor(dataset, "Density")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        dialog.reference_group.setCurrentIndex(1)
        dialog.reference_search.setText("_WINDOW_STATISTIC")
        self.assertFalse(dialog.reference_insert.isEnabled())
        dialog.reference_search.setText("normpdf")
        self.assertEqual(dialog.reference_detail.text().split(" · ")[0], "NORMPDF(x, mean, sd)")
        dialog.expression.setPlainText("=")
        dialog.expression.moveCursor(dialog.expression.textCursor().MoveOperation.End)
        QTest.keyClick(dialog.reference_results, Qt.Key.Key_Return)
        self.assertEqual(dialog.expression.toPlainText(), "=NORMPDF()")
        self.assertEqual(dialog.expression.textCursor().position(), len("=NORMPDF("))
        dialog.reference_group.setCurrentIndex(0)
        dialog.reference_search.setText("A")
        dialog.reference_insert.click()
        dataset.set_formula(*dialog.validated_formula())
        self.assertAlmostEqual(dataset.frame()["Density"].iloc[0], 0.3989422804014327)

    def test_formula_function_help_prioritizes_an_exact_name_and_matches_engine_examples(self):
        from analisi.data import Dataset
        from analisi.i18n import active_language, set_language
        from trama_qt.formula import FUNCTION_EXAMPLES, FormulaEditor

        self.addCleanup(set_language, active_language())
        set_language("it")
        dataset = Dataset(pd.DataFrame({"Observed": [0., 1.]}))
        dataset.set_formula("Example", "=0")
        panel = FormulaEditor(dataset, "Example")
        self.addCleanup(panel.deleteLater)
        panel.reference_group.setCurrentIndex(1)
        panel.reference_search.setText("cos")
        self.assertEqual(panel.matches[0].name, "COS")
        self.assertTrue(panel.reference_detail.text().startswith("COS(x)"))
        self.assertIn("radianti", panel.reference_detail.text())
        for name, (_, _, formula, result) in FUNCTION_EXAMPLES.items():
            with self.subTest(name=name):
                panel.reference_search.setText(name.lower())
                self.assertIn(f"Esempio · {formula} → {result}", panel.reference_detail.text())
                panel.expression.setPlainText(formula)
                self.assertEqual(panel.validated_formula(), ("Example", formula))
                dataset.set_formula("Example", formula)
                self.assertAlmostEqual(dataset.frame()["Example"].iloc[0], float(result))

    def test_equals_shortcut_confirms_replacement_and_keeps_errors_in_the_panel(self):
        from PySide6.QtTest import QTest

        window = self.window
        window.project.add_tables({"Study": pd.DataFrame({"Dose": [2., 4.], "Response": [9., 7.]})})
        window.open_sheet(("data", "Study"))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.activateWindow()
        self.app.processEvents()
        window.sheet.setFocus()
        dataset = window.project.tables["Study"]
        QTest.keyClick(window.sheet, Qt.Key.Key_Equal)
        panel = window.formula_editor
        self.assertEqual(panel.column, 1)
        self.assertTrue(panel.replace_values)
        panel.expression.setPlainText("=A * 3")
        self.assertEqual(window.sheet.formula_columns, (0,))
        panel.cancel_button.click()
        self.assertIsNone(window.formula_editor)
        self.assertEqual(window.sheet.formula_columns, ())
        self.assertEqual(dataset.raw["Response"].tolist(), [9., 7.])
        self.assertFalse(dataset.formulas)

        QTest.keyClick(window.sheet, Qt.Key.Key_Equal)
        panel = window.formula_editor
        panel.expression.setPlainText("=A * 3")
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), panel.expression)
        QTest.keyClick(panel.expression, Qt.Key.Key_Escape)
        self.assertIsNone(window.formula_editor)
        self.assertFalse(dataset.formulas)

        QTest.keyClick(window.sheet, Qt.Key.Key_Equal)
        panel = window.formula_editor
        panel.expression.setPlainText("=B + 1")
        panel.apply_button.click()
        self.assertIn("cannot depend on itself", panel.problem.text())
        self.assertIs(window.formula_editor, panel)
        self.assertEqual(dataset.raw["Response"].tolist(), [9., 7.])
        panel.expression.setPlainText("=A * 2")
        panel.apply_button.click()
        self.assertIsNone(window.formula_editor)
        self.assertEqual(dataset.frame()["Response"].tolist(), [4., 8.])
        window.undo()
        self.assertEqual(dataset.raw["Response"].tolist(), [9., 7.])

    def test_formula_panel_cannot_apply_to_a_renamed_column_or_another_sheet(self):
        window = self.window
        window.project.add_tables({"Study": pd.DataFrame({"Dose": [2.], "Response": [None]}),
                                   "Other": pd.DataFrame({"Dose": [4.], "Response": [None]})})
        window.open_sheet(("data", "Study"))
        dataset = window.project.tables["Study"]
        window.edit_formula_in_column(1)
        panel = window.formula_editor
        panel.expression.setPlainText("=A * 3")
        window.open_sheet(("data", "Study"))
        self.assertIs(window.formula_editor, panel)
        window._apply_edit("Study", lambda: window.project.rename_column("Study", 0, "Mass"))
        self.assertEqual(window.sheet.formula_columns, ())
        panel.apply_button.click()
        self.assertTrue(panel.problem.text())
        self.assertFalse(dataset.formulas)
        window.open_sheet(("data", "Other"))
        self.assertIsNone(window.formula_editor)
        panel.apply_requested.emit()
        self.assertFalse(window.project.tables["Other"].formulas)

    def test_interleaved_formula_has_read_only_cells_and_keeps_source_actions_aligned(self):
        from analisi.grid_data import clipboard_rows

        window = self.window
        frame = pd.DataFrame({"Mass": [1., 3.], "Double": [2., 6.], "Dose": [9., 5.]})
        frame.attrs["legacy_formulas"] = {"Double": "Mass * 2"}
        window.project.add_tables({"Study": frame})
        window.open_sheet(("data", "Study"))
        dataset = window.project.tables["Study"]
        model = window.sheet.model()
        self.assertIn("ƒx   Double", model.headerData(1, Qt.Orientation.Horizontal))
        self.assertFalse(model.flags(model.index(0, 1)) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.flags(model.index(0, 2)) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(model.setData(model.index(0, 1), "16"))
        model.setData(model.index(0, 2), "16")
        self.wait()
        self.assertEqual(dataset.frame().iloc[0].tolist(), [1., 2., 16.])

        window.sheet.setCurrentIndex(window.sheet.model().index(0, 2))
        window.toggle_exclusion()
        self.assertEqual(dataset.excluded, {(0, 1)})
        self.assertTrue(window.sheet.copy())
        self.assertEqual(clipboard_rows(self.app.clipboard().text()), [[""]])
        window.clear_cells((0, 2, 0, 2))
        self.assertTrue(pd.isna(dataset.raw.iat[0, 1]))
        self.assertFalse(dataset.excluded)
        window.undo()
        self.assertEqual(dataset.worksheet_excluded, {(0, 2)})

        window.project.insert_column("Study", 2, "Inserted")
        self.assertEqual(dataset.columns, ("Mass", "Double", "Inserted", "Dose"))
        self.assertEqual(dataset.worksheet_excluded, {(0, 3)})
        window.project.rename_column("Study", 2, "New name")
        self.assertEqual(dataset.columns, ("Mass", "Double", "New name", "Dose"))
        window.project.delete_columns("Study", [1, 2])
        self.assertEqual(dataset.columns, ("Mass", "Double", "Dose"))
        window.undo()
        self.assertEqual(dataset.columns, ("Mass", "Double", "New name", "Dose"))
        window.undo(redo=True)
        self.assertEqual(dataset.columns, ("Mass", "Double", "Dose"))

    def test_desktop_smoke(self):
        """python -m trama_qt --smoke, in English on the test screen: every dialog fits and nothing is clipped."""
        from trama_qt.smoke import run
        folder = self.folder / "smoke"
        status = run(folder, languages=("en",))
        self.assertEqual(status, "PASS", (folder / "report.txt").read_text(encoding="utf-8"))
        self.assertGreater(len(list(folder.glob("en-*.png"))), 25)

    def test_every_dialog_builds_and_reads_its_defaults(self):
        from analisi.workbench import METHODS
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.DataFrame({"X": [1.0, 2, 3, 4, 5, 6], "Y": [2.0, 4, 5, 4, 6, 8],
                              "Group": ["a", "a", "b", "b", "c", "c"], "Time": [1.0, 2, 3, 4, 5, 6],
                              "Event": [1, 0, 1, 1, 0, 1]})
        failures = []
        for method in METHODS:
            try:
                dialog = AnalysisDialog(None, frame, current=(method, {}))
                self.assertEqual(dialog.method, method)
                try:
                    dialog.options()
                except ValueError:
                    pass  # A missing required column is reported to the user, not a crash.
                dialog.deleteLater()
            except Exception as error:  # noqa: BLE001
                failures.append(f"{method}: {type(error).__name__}: {error}")
        self.app.processEvents()
        self.assertEqual(failures, [])

    def test_nonlinear_log_ic50_follows_the_model_and_the_saved_choice(self):
        from analisi.parameter_intervals import REPORT_LOG_IC50
        from trama_qt.analysis_dialog import AnalysisDialog

        model_name = "Normalized inhibition (variable slope)"
        recipe = {"X": "X", "Y columns": ["Y"], "Model": model_name, REPORT_LOG_IC50: True}
        frame = pd.DataFrame({"X": [1., 2., 4.], "Y": [90., 70., 30.]})
        dialog = AnalysisDialog(self.window, frame, current=("Nonlinear regression", recipe))
        self.addCleanup(dialog.deleteLater)
        model = dialog.controls["Model"][1]
        report = dialog.controls[REPORT_LOG_IC50][1]

        self.assertIs(dialog.options()[REPORT_LOG_IC50], True)
        model.setCurrentIndex(model.findData("Straight line"))
        self.assertIn(REPORT_LOG_IC50, dialog.hidden)
        self.assertNotIn(REPORT_LOG_IC50, dialog.options())
        model.setCurrentIndex(model.findData(model_name))
        self.assertNotIn(REPORT_LOG_IC50, dialog.hidden)
        report.setChecked(False)
        self.assertNotIn(REPORT_LOG_IC50, dialog.options())

    def test_standard_curve_dialog_keeps_only_the_selected_direction_fields(self):
        from analisi import nonlinear_calibration as cal
        from trama_qt.analysis_dialog import AnalysisDialog

        method = "Interpolate a standard curve"
        frame = pd.DataFrame({"X": range(-5, 3), "Y": range(8), "Input X": range(8), "Input Y": range(8)})
        recipe = {"X": "X", "Y": "Y", "Curve": "Nonlinear", "Model": cal.CONCENTRATION_5PL,
                  cal.DIRECTION: "Y from X", cal.UNKNOWN_X: "Input X", cal.UNKNOWN_RESPONSES: "Input Y",
                  cal.UNCERTAINTY: "Prediction"}
        dialog = AnalysisDialog(self.window, frame, current=(method, recipe), only=method)
        self.addCleanup(dialog.deleteLater)
        self.assertNotIn(cal.UNKNOWN_RESPONSES, dialog.options())
        self.assertIn(cal.LEVEL, dialog.options())
        dialog.accept()
        self.assertEqual(dialog.error_field, "Model")  # Concentration X cannot contain negative standards.
        self.assertIsNone(dialog.result)
        direction = dialog.controls[cal.DIRECTION][1]
        direction.setCurrentIndex(direction.findData("X from Y"))
        model = dialog.controls["Model"][1]
        model.setCurrentIndex(model.findData(cal.LOG10_5PL))
        self.assertNotIn(cal.LEVEL, dialog.hidden)
        dialog.accept()
        name, result = dialog.result
        self.assertEqual(name, method)
        self.assertEqual(result["Model"], cal.LOG10_5PL)
        self.assertEqual(result[cal.UNKNOWN_RESPONSES], "Input Y")
        self.assertEqual(result[cal.UNCERTAINTY], "Prediction")
        self.assertEqual(result[cal.LEVEL], 95)
        self.assertIsNone(result[cal.COUNT])
        self.assertNotIn(cal.UNKNOWN_X, result)

    def test_file_menu_uses_only_the_qt_interface(self):
        self.assertNotIn("classic", self.window.actions)

    def test_home_creates_typed_worksheets_and_the_picker_follows_selection(self):
        from trama_qt.table_setup import TableSetup

        window = self.window
        setup = window.page.findChild(TableSetup)
        self.assertIsNotNone(setup)
        self.assertEqual(setup.types.count(), 8)
        setup.encoding.setCurrentIndex(1)
        setup.series.setValue(3)
        setup.replicates.setValue(4)
        template, sample = setup.selection()
        self.assertFalse(sample)
        self.assertEqual(len(template.columns), 14)
        window.create_worksheet(template, sample)
        first = window.selected
        self.assertEqual(window.project.tables[first[1]].table_format, "XY with replicates")
        self.assertEqual(window.sheet.currentIndex().column(), 1)

        window.show_home()
        setup = window.page.findChild(TableSetup)
        setup.types.setCurrentRow(7)
        setup.sample.setChecked(True)
        window.create_worksheet(*setup.selection())
        second = window.selected
        self.assertEqual(window.project.tables[second[1]].table_format, "nested")
        self.assertEqual(tuple(window.sheet_picker.currentData()), second)
        window.sheet_previous.click()
        self.assertEqual(window.selected, first)
        window.sheet_next.click()
        self.assertEqual(window.selected, second)

    def test_home_options_and_examples_match_the_table_being_created(self):
        from analisi.table_templates import GROUPED_FORMATS, TEMPLATES, XY_FORMATS
        from trama_qt.table_setup import TableSetup

        setup = self.window.page.findChild(TableSetup)
        for index, template in enumerate(TEMPLATES):
            with self.subTest(kind=template.kind):
                setup.types.setCurrentRow(index)
                setup.empty.setChecked(True)
                self.assertFalse(setup.selection()[1])
                self.assertIsNone(setup.preview.item(0, 0))
                self.assertTrue(setup.replicates.isHidden())
                setup.sample.setChecked(True)
                self.assertEqual(setup.selection(), (template, True))
                self.assertIsNotNone(setup.preview.item(0, 0))
                self.assertTrue(setup.encoding.isHidden())
                self.assertEqual(setup.create_label, tr("setup.create_example"))
        setup.types.setCurrentRow(0)
        setup.examples.setCurrentIndex(2)
        self.assertEqual(setup.selection(), (list(XY_FORMATS.values())[2], True))
        setup.empty.setChecked(True)
        setup.encoding.setCurrentIndex(1)
        self.assertFalse(setup.replicates.isHidden())
        setup.types.setCurrentRow(2)
        setup.sample.setChecked(True)
        self.assertEqual(setup.examples.count(), len(GROUPED_FORMATS))

    def test_home_recent_projects_are_saved_and_open_through_the_menu(self):
        from unittest.mock import patch
        from trama_qt.project import Project
        from trama_qt.sessions import recent_projects
        from trama_qt.table_setup import TableSetup

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "Recent & test.alab"
            project = Project()
            project.add_tables({"Measurements": pd.DataFrame({"X": [1., 2.], "Y": [3., 4.]})})
            project.save(path)
            window = self.window
            with patch("trama_qt.sessions.config_path", return_value=root / "prefs.json"):
                window.open_path(path)
                self.assertEqual(recent_projects(), (path,))
                self.assertEqual(window.selected, ("data", "Measurements"))
                self.assertTrue(window.close_project())
                menu = window.page.findChild(TableSetup).recent.menu()
                menu.aboutToShow.emit()
                actions = menu.actions()
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0].toolTip(), str(path))
                actions[0].trigger()
                self.assertEqual(window.selected, ("data", "Measurements"))
                self.assertEqual(recent_projects(), (path,))

    def test_classic_toolbar_fits_all_buttons_at_1024_pixels(self):
        window = self.window
        window.resize(1024, 720)
        self.open_example()
        self.app.processEvents()
        buttons = window.toolbar.buttons.values()
        self.assertEqual(len(buttons), 39)  # 29 and the ten buttons of the Text group
        self.assertFalse(window.toolbar.overflow.isVisible())
        actions = [button.defaultAction() for button in buttons]
        self.assertEqual(actions.count(window.actions["formula"]), 1)
        self.assertIn(window.actions["formula"], window.command_menus["Insert"].actions())
        for button in buttons:
            self.assertTrue(button.isVisible(), button.accessibleName())
            self.assertFalse(button.icon().isNull(), button.accessibleName())
            self.assertLessEqual(button.mapTo(window.toolbar, button.rect().bottomRight()).x(),
                                 window.toolbar.width(), button.accessibleName())

    def test_classic_toolbar_overflow_keeps_all_commands_reachable_without_overlap(self):
        from PySide6.QtCore import QPoint

        window = self.window
        self.open_example()
        window.resize(643, 460)
        self.app.processEvents()
        bar = window.toolbar
        self.assertTrue(bar.overflow.isVisible())
        visible = [button for button in bar.buttons.values() if button.isVisible()]
        self.assertIn(bar.buttons["analyze"], visible)
        listed = [action for group in bar.overflow.menu().actions() for action in group.menu().actions()]
        self.assertCountEqual([button.defaultAction() for button in visible] + listed,
                              [button.defaultAction() for button in bar.buttons.values()])
        bounds = []
        for button in [*visible, bar.overflow]:
            rect = button.rect().translated(button.mapTo(bar, QPoint()))
            self.assertLess(rect.right(), bar.width(), button.accessibleName())
            self.assertTrue(all(not rect.intersects(other) for other in bounds), button.accessibleName())
            bounds.append(rect)
        window.resize(1024, 720)
        self.app.processEvents()
        self.assertFalse(bar.overflow.isVisible())
        self.assertTrue(all(button.isVisible() for button in bar.buttons.values()))

    def test_result_selector_preserves_the_active_table_as_the_window_resizes(self):
        from analisi.reporting import Result
        from trama_qt.project import Run
        from trama_qt.result_tabs import ResultTabs

        self.open_example()
        window = self.window
        tables = {name: pd.DataFrame({"n": [index]}) for index, name in enumerate(
            ("Summary", "Group comparisons", "Residuals", "Model coefficients", "Notes"))}
        run = Run("Descriptive statistics", "groups", {}, Result(tables))
        window.project.runs.append(run)
        window.open_sheet(("result", 0))
        navigation = window.page.findChild(ResultTabs)
        tabs = window.result_tabs
        window.resize(1280, 740)
        self.app.processEvents()
        self.assertTrue(tabs.tabBar().isVisible())
        self.assertFalse(navigation.choice.isVisible())
        tabs.setCurrentIndex(2)
        window.resize(630, 460)
        self.app.processEvents()
        self.assertFalse(tabs.tabBar().isVisible())
        self.assertTrue(navigation.choice.isVisible())
        self.assertEqual(navigation.choice.currentText(), "Residuals")
        self.assertEqual([navigation.choice.itemText(index) for index in range(tabs.count())], list(tables))
        navigation.choice.setCurrentIndex(4)
        self.assertIs(tabs.currentWidget().model().frame, tables["Notes"])
        window.resize(1280, 740)
        self.app.processEvents()
        self.assertTrue(tabs.tabBar().isVisible())
        self.assertFalse(navigation.choice.isVisible())
        self.assertEqual(tabs.currentIndex(), 4)
        self.assertIsNone(window.job)

    def test_classic_graph_controls_and_canvas_navigation(self):
        from PySide6.QtWidgets import QToolButton
        from analisi.i18n import tr

        window = self.window
        title, = window.project.add_tables({"Dose": pd.DataFrame({"Dose": [1., 2., 3.], "Response": [2., 5., 6.]})})
        window.open_sheet(("data", title))
        run = self.run_method("Linear regression", {"X": "Dose", "Y": "Response"})
        index = window.project.runs.index(run)
        window.open_sheet(("graph", index))
        self.app.processEvents()
        commands = {button.defaultAction() for button in window.page.actions_row.parentWidget().findChildren(QToolButton)}
        self.assertEqual(commands, {window.actions[name] for name in ("annotations", "draw", "linked_table", "inspector")})
        self.assertEqual(set(window.plot_tools._actions), {"home", "back", "forward", "pan", "zoom"})
        self.assertGreater(window.plot_tools.y(), window.page.canvases[0].parentWidget().y())
        self.assertTrue(window.actions["plot_margins"].isEnabled())
        self.assertNotIn(window.actions["export"], window.plot_tools.actions())
        self.assertIs(window.toolbar.buttons["export"].defaultAction(), window.actions["export"])
        for key in ("format_graph", "inspector", "export", "analysis_tables", "change", "recalculate"):
            self.assertTrue(window.actions[key].isEnabled(), key)
        window.search.setText(tr("command.analysis_results"))
        window.search.returnPressed.emit()
        self.assertEqual(window.selected, ("result", index))
        window.actions["analysis_graph"].trigger()
        self.assertEqual(window.selected, ("graph", index))

    def test_search_distinguishes_graph_and_family_results_in_both_languages(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.window import MainWindow
        from unittest.mock import patch

        self.addCleanup(set_language, active_language())
        for language in ("en", "it"):
            with self.subTest(language=language):
                set_language(language)
                window = MainWindow()
                try:
                    actions = window.actions
                    labels = [action.text().replace("&", "").strip().casefold()
                              for action in actions.values() if action.text()]
                    self.assertCountEqual(labels, set(labels))
                    with patch.object(window, "browse_family") as family, patch.object(window, "switch_run_view") as view:
                        for key, target in (("analysis_tables", view), ("family_results", family)):
                            action = actions[key]
                            action.setEnabled(True)
                            self.assertIn(action.text(), window.completer.model().stringList())
                            window.search.setText(action.text())
                            window.search.returnPressed.emit()
                            target.assert_called_once_with("result")
                        self.assertEqual(view.call_count, 1)
                finally:
                    window.close()
                    window.deleteLater()

    def test_classic_menus_preserve_the_desktop_commands(self):
        from analisi.i18n import ui

        window = self.window
        window.resize(760, 650)
        window.new_table()
        self.assertEqual([action.text() for action in window.menuBar().actions()][:-1],
                         [ui(key) for key in ("File", "Edit", "View", "Insert", "Analyze",
                                              "Change", "Arrange", "Family", "Tools")])
        self.assertEqual(window.menuBar().actions()[-1].text(), tr("theme.settings"))
        for menu, names in {
            "File": ("exit", "open", "save", "export_batch", "export_report", "new_from_template", "import_excel"),
            "Edit": ("paste_special", "paste_transpose", "paste_table", "clear_cells", "sheet_delete"),
            "Insert": ("new_table", "new_info", "annotations", "shapes"),
            "Analyze": ("correlation_matrix", "load_example", "source_analysis", "recalculate"),
            "Change": ("info_properties", "format_graph", "graph_style_presets"),
            "Arrange": ("arrange_shapes", "edit_layout"),
            "Family": ("family_data", "family_info", "family_results", "family_graphs", "family_gallery"),
            "Tools": ("power", "simulate", "monte_carlo", "transpose_xy", "plot_function"),
            "View": ("combined_navigator", "previous_sheet", "next_sheet"),
        }.items():
            with self.subTest(menu=menu):
                self.assertTrue(set(window.actions[name] for name in names).issubset(window.command_menus[menu].actions()))

    def test_classic_home_data_info_and_layout_keep_their_controls(self):
        from PySide6.QtWidgets import QPushButton, QToolButton
        from analisi.info import InfoSheet
        from analisi.presentation import Layout
        from trama_qt.table_setup import TableSetup

        window = self.window
        self.assertFalse(window.toolbar.isVisible())
        self.assertFalse(window.nav_card.isVisible())
        self.assertIn(tr("setup.create_blank"), {button.text() for button in window.page.findChildren(QPushButton)})
        chooser = window.page.findChild(TableSetup)
        window.actions["load_example"].trigger()
        self.assertTrue(chooser.selection()[1])
        window.create_worksheet(*chooser.selection())
        self.app.processEvents()
        _, title = window.selected
        self.assertTrue(window.toolbar.isVisible())
        self.assertTrue(window.nav_card.isVisible())
        self.assertFalse(any(button.isVisible() for button in window.page.findChildren(QPushButton)))
        self.assertTrue(window.page.worksheet_preview.preview_box.isVisible())

        sheet = InfoSheet.new("Measurements", title)
        window.project.update_info_sheets({sheet.uid: sheet})
        window.open_sheet(("info", sheet.uid))
        props = window.actions["info_properties"]
        self.assertTrue(props.isEnabled())
        self.assertIn(props, window.command_menus["Change"].actions())
        self.assertTrue(window.actions["sheet_delete"].isEnabled())
        self.assertFalse(window.actions["sheet_move_up"].isEnabled())
        self.assertFalse(window.actions["sheet_move_down"].isEnabled())

        window.open_sheet(("data", title))
        run = self.run_method("XY series", {"X": "X", "Y columns": ["Control"]})
        window.project.layouts.append(Layout("Figure with panel", 1, [run.reference]))
        window.open_sheet(("layout", 0))
        commands = {button.defaultAction() for button in window.page.actions_row.parentWidget().findChildren(QToolButton)}
        self.assertIn(window.actions["edit_layout"], commands)
        for key in ("edit_layout", "export", "recalculate"):
            self.assertTrue(window.actions[key].isEnabled(), key)

    def test_classic_shortcuts_for_exclusion_export_and_sheet_history(self):
        from unittest.mock import patch
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QFileDialog

        window = self.window
        self.open_example()
        first = window.selected
        dataset = window.project.tables[first[1]]
        window.activateWindow()
        window.sheet.setFocus()
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        self.app.processEvents()

        destination = self.folder / "shortcut.csv"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")) as chooser:
            QTest.keyClick(window.sheet, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dataset.excluded, {(0, 0)})
            chooser.assert_not_called()
            QTest.keyClick(window.sheet, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
            self.assertFalse(dataset.excluded)
            QTest.keyClick(window.sheet, Qt.Key.Key_E,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            chooser.assert_called_once()
        pd.testing.assert_frame_equal(pd.read_csv(destination), dataset.raw, check_dtype=False)

        title, = window.project.add_tables({"Second sheet": pd.DataFrame({"Response": [1.]})})
        second = ("data", title)
        window.open_sheet(second)
        self.app.processEvents()
        QTest.keyClick(window.sheet, Qt.Key.Key_PageUp, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.selected, first)
        QTest.keyClick(window.sheet, Qt.Key.Key_PageDown, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.selected, second)

    def test_clipboard_ribbon_commands_change_the_real_worksheet(self):
        from unittest.mock import patch
        from PySide6.QtGui import QGuiApplication
        from trama_qt.sheet import PasteSpecialDialog

        window = self.window
        clipboard = QGuiApplication.clipboard()
        clipboard.setText("Header A\tHeader B\n1\t2\n3\t4")
        window.actions["paste_table"].trigger()
        dataset = window.project.tables[window.selected[1]]
        self.assertEqual(list(dataset.raw.columns), ["Header A", "Header B"])
        self.assertEqual(dataset.raw.values.tolist(), [[1, 2], [3, 4]])

        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        clipboard.setText("11\t12\n13\t14")
        window.actions["paste_transpose"].trigger()
        self.assertEqual(dataset.raw.values.tolist(), [[11, 13], [12, 14]])
        self.assertTrue(window.actions["undo"].isEnabled())
        window.actions["undo"].trigger()
        self.assertEqual(dataset.raw.values.tolist(), [[1, 2], [3, 4]])

        def choose_rows(dialog):
            dialog.bounds[2].setValue(1)
            dialog.accept()
            return PasteSpecialDialog.DialogCode.Accepted

        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        clipboard.setText("21\t22\n23\t24\n25\t26")
        with patch.object(PasteSpecialDialog, "exec", choose_rows):
            window.actions["paste_special"].trigger()
        self.assertEqual(dataset.raw.values.tolist(), [[21, 22], [25, 26]])
        window.actions["clear_cells"].trigger()
        self.assertTrue(pd.isna(dataset.raw.iat[0, 0]))

    def test_worksheet_cut_keeps_data_if_the_clipboard_write_fails(self):
        from unittest.mock import Mock, patch
        from PySide6.QtGui import QGuiApplication
        from trama_qt.strings import qt

        window = self.window
        title, = window.project.add_tables({"Samples": pd.DataFrame({"Reading": [47, 53]})})
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        before = window.project.tables[title].raw.copy()
        clipboard = Mock()
        clipboard.text.return_value = "Unrelated clipboard text"
        with patch("trama_qt.sheet.QGuiApplication.clipboard", return_value=clipboard), patch.object(window, "error") as error:
            window.toolbar.buttons["cut"].click()
        pd.testing.assert_frame_equal(window.project.tables[title].raw, before)
        self.assertFalse(window.project.history.can_apply())
        error.assert_called_once_with(qt("qt.cell_clipboard_failed"))

        window.toolbar.buttons["cut"].click()
        self.assertEqual(QGuiApplication.clipboard().text().strip(), "47")
        self.assertTrue(pd.isna(window.project.tables[title].raw.iat[0, 0]))
        window.actions["undo"].trigger()
        pd.testing.assert_frame_equal(window.project.tables[title].raw, before)

    def test_windows_worksheet_cut_retries_a_busy_clipboard(self):
        from unittest.mock import Mock, patch
        from PySide6.QtGui import QGuiApplication
        from trama_qt.strings import qt

        window = self.window
        title, = window.project.add_tables({"Samples": pd.DataFrame({"Reading": [47, 53]})})
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        dataset = window.project.tables[title]
        before = dataset.raw.copy()
        clipboard = Mock()
        clipboard.ownsClipboard.side_effect = [False, False, False, True]

        def verify_before_clearing():
            pd.testing.assert_frame_equal(dataset.raw, before)
            return clipboard.setText.call_args.args[0]

        clipboard.text.side_effect = verify_before_clearing
        with (patch.object(QGuiApplication, "platformName", return_value="windows"),
              patch.object(QGuiApplication, "clipboard", return_value=clipboard),
              patch.object(window, "error") as error):
            window.toolbar.buttons["cut"].click()
            error.assert_called_once_with(qt("qt.cell_clipboard_failed"))
            pd.testing.assert_frame_equal(dataset.raw, before)
            self.assertFalse(window.project.history.can_apply())
            clipboard.text.assert_not_called()
            error.reset_mock()

            window.toolbar.buttons["cut"].click()
            error.assert_not_called()
            self.assertTrue(pd.isna(dataset.raw.iat[0, 0]))

        self.assertEqual(clipboard.setText.call_count, 4)
        clipboard.text.assert_called_once()
        window.actions["undo"].trigger()
        pd.testing.assert_frame_equal(dataset.raw, before)

    def test_tools_run_standalone_simulation_and_plot_from_empty_project(self):
        from unittest.mock import patch
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        window = self.window
        window._ask = MainWindow._ask.__get__(window)
        empty = window.sessions.active

        def accept(dialog):
            self.assertFalse(dialog.banner.text(), dialog.banner.text())
            dialog.accept()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", accept):
            window.actions["simulate"].trigger()
            self.wait()
            self.assertEqual(window.selected[0], "data")
            self.assertFalse(window.project.tables[window.selected[1]].raw.empty)
            self.assertFalse(window.project.runs)
            window.new_project()
            self.assertIsNot(window.sessions.active, empty)
            self.assertFalse(window.project.tables)
            window.actions["plot_function"].trigger()
            self.wait()
            self.assertEqual(window.selected[0], "graph")
            self.assertIsNotNone(window.project.runs[0].result.figure)

    def test_tools_transpose_y_sets_and_configure_monte_carlo(self):
        from unittest.mock import patch
        from analisi import monte_carlo, transpose_xy
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import MainWindow

        window = self.window
        window._ask = MainWindow._ask.__get__(window)
        title, = window.project.add_tables({"Series": pd.DataFrame({"X": [2., 3.], "Y": [5., 7.]})})
        window.show_sheet("data", title)

        def accept(dialog):
            self.assertFalse(dialog.banner.text(), dialog.banner.text())
            if dialog.method == transpose_xy.TRANSPOSE_XY:
                editor = dialog.controls[transpose_xy.Y_SETS][1]
                self.assertEqual(editor.values(), [{"name": "Y", "mode": "Single", "columns": ["Y"]}])
                editor.table.item(0, 0).setText("Reversed")
            else:
                self.assertEqual(dialog.method, monte_carlo.MONTE_CARLO)
                self.assertIn(monte_carlo.X_COLUMN, dialog.hidden)
                dialog.controls[monte_carlo.REPLICATES][1].setText("20")
            dialog.accept()
            self.assertIsNotNone(dialog.result, dialog.banner.text())
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", accept):
            window.actions["transpose_xy"].trigger()
            self.wait()
            table = window.project.runs[-1].result.tables[transpose_xy.TABLE]
            self.assertEqual(table["X"].tolist(), [5., 7.])
            self.assertEqual(table["Reversed"].tolist(), [2., 3.])
            window.actions["monte_carlo"].trigger()
            self.wait()
            run = window.project.runs[-1]
            self.assertEqual(run.method, monte_carlo.MONTE_CARLO)
            self.assertEqual(len(run.result.tables[monte_carlo.REPLICATE_SHEET]), 20)

    def test_family_navigation_and_combined_tree_keep_real_sheet_links(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt
        from trama_qt.family import FamilySheetsDialog

        window = self.window
        self.open_example()
        run = self.run_method("Descriptive statistics", {"Variables": ["Control"]})
        result = ("result", window.project.runs.index(run))
        data = ("data", "groups")
        window.open_sheet(data)
        self.assertTrue(window.actions["combined_navigator"].isChecked())
        window.actions["combined_navigator"].trigger()
        self.assertFalse(window.actions["combined_navigator"].isChecked())
        window.actions["combined_navigator"].trigger()
        self.assertTrue(window.actions["combined_navigator"].isChecked())
        item = window.navigator.currentItem()
        self.assertIn(result, [tuple(item.child(i).data(0, Qt.ItemDataRole.UserRole))
                               for i in range(item.childCount())])
        window.actions["family_results"].trigger()
        self.assertEqual(window.selected, result)
        window.actions["family_data"].trigger()
        self.assertEqual(window.selected, data)

        def choose(dialog):
            refs = [tuple(dialog.entries.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(dialog.entries.count())]
            self.assertIn(data, refs)
            dialog.entries.setCurrentRow(refs.index(result))
            dialog.accept()
            return FamilySheetsDialog.DialogCode.Accepted

        with patch.object(FamilySheetsDialog, "exec", choose):
            window.actions["family_gallery"].trigger()
        self.assertEqual(window.selected, result)

    def test_arrange_shapes_previews_and_commits_with_one_undo_step(self):
        from copy import deepcopy
        from unittest.mock import patch
        from uuid import uuid4
        from analisi.graph_shapes import SHAPES
        from trama_qt.shape_arrange import ArrangeShapesDialog
        from trama_qt.shapes import DEFAULT_SHAPE

        window = self.window
        self.open_example()
        run = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("graph", window.project.runs.index(run)))
        shapes = [{**DEFAULT_SHAPE, "id": str(uuid4()), "points": [[left, .2], [left + .1, .4]]}
                  for left in (.1, .4)]
        window.commit_style(run, {**(run.style or {}), SHAPES: shapes})
        window.update_actions()
        self.assertTrue(window.actions["arrange_shapes"].isEnabled())
        original = deepcopy(run.style[SHAPES])

        def choose(dialog, accept):
            dialog.shapes.selectAll()
            field = dialog.modes["horizontal"]
            field.setCurrentIndex(field.findData("left"))
            dialog.preview_selection()
            self.assertEqual(run.style[SHAPES], original)
            if accept:
                dialog.accept()
            else:
                dialog.reject()
            return dialog.result()

        with patch.object(ArrangeShapesDialog, "exec", lambda dialog: choose(dialog, False)):
            window.actions["arrange_shapes"].trigger()
        self.assertEqual(run.style[SHAPES], original)
        with patch.object(ArrangeShapesDialog, "exec", lambda dialog: choose(dialog, True)):
            window.actions["arrange_shapes"].trigger()
        self.assertAlmostEqual(run.style[SHAPES][1]["points"][0][0], .1)
        window.actions["undo"].trigger()
        self.assertEqual(run.style[SHAPES], original)

    # -- look and feel -----------------------------------------------------------------------------
    def test_theme_defaults_to_light_and_respects_a_saved_choice(self):
        from unittest.mock import MagicMock, patch
        from trama_qt import theme

        settings = MagicMock()
        settings.value.side_effect = lambda key, default: default
        with patch.dict("os.environ", {"TRAMA_THEME": ""}), patch.object(theme, "QSettings", return_value=settings):
            self.assertEqual(theme.saved_mode(), "light")
            settings.value.side_effect = None
            for value, expected in (("system", "system"), ("dark", "dark"), ("invalid", "light")):
                settings.value.return_value = value
                self.assertEqual(theme.saved_mode(), expected)
            with patch.dict("os.environ", {"TRAMA_THEME": "dark"}):
                self.assertEqual(theme.saved_mode(), "dark")

    def test_theme_switch_keeps_the_existing_qt_style(self):
        from unittest.mock import patch
        from trama_qt import theme

        self.addCleanup(lambda: theme.apply(self.app))
        with patch.object(self.app, "setStyle", wraps=self.app.setStyle) as set_style:
            theme.apply(self.app, dark=True)
            theme.apply(self.app, dark=False)
            set_style.assert_not_called()

    def test_light_dark_and_system_themes(self):
        from trama_qt import theme
        window = self.window
        self.addCleanup(lambda: (theme.STATE.update(mode="system"), theme.apply(self.app)))
        theme.set_mode("dark", self.app, remember=False)
        self.app.processEvents()
        self.assertTrue(theme.STATE["dark"])
        self.assertEqual(theme.T["bg"], theme.DARK["bg"])
        self.assertIn(theme.DARK["bg"], self.app.styleSheet())
        self.assertTrue(window.actions["theme_dark"].isChecked())
        self.assertFalse(window.actions["theme_light"].isChecked())
        heading = window.navigator.topLevelItem(0)
        self.assertEqual(heading.foreground(0).color().name().upper(), theme.DARK["text2"].upper())
        theme.set_mode("light", self.app, remember=False)
        self.assertEqual(theme.T["bg"], theme.LIGHT["bg"])
        self.assertTrue(window.actions["theme_light"].isChecked())
        theme.STATE["mode"] = "system"  # The offscreen platform reports no dark scheme.
        theme.apply(self.app)
        self.assertEqual(theme.STATE["dark"], theme.system_dark(self.app))

    def test_icons_are_drawn_from_svg_at_any_scale_and_follow_the_theme(self):
        from PySide6.QtCore import QSize
        from trama_qt import theme
        self.addCleanup(lambda: theme.apply(self.app))
        icon = theme.icon("sigma", "text2")
        for ratio in (1.0, 1.5, 2.0):
            pixmap = icon.pixmap(QSize(18, 18), ratio)
            self.assertEqual(pixmap.width(), round(18 * ratio))
            self.assertEqual(pixmap.devicePixelRatio(), ratio)

        def ink(pixmap):
            image = pixmap.toImage()
            return max(((image.pixelColor(x, y).alpha(), image.pixelColor(x, y).name())
                        for x in range(image.width()) for y in range(image.height())))

        theme.apply(self.app, dark=False)
        light = ink(icon.pixmap(QSize(24, 24), 1.0))
        theme.apply(self.app, dark=True)
        dark = ink(icon.pixmap(QSize(24, 24), 1.0))
        self.assertGreater(light[0], 200)
        self.assertNotEqual(light[1], dark[1])

    def test_classic_modal_dialog_leaves_the_background_clear(self):
        from PySide6.QtWidgets import QDialog
        from trama_qt.theme import GlassVeil

        dialog = QDialog(self.window)
        dialog.setModal(True)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(self.window.findChildren(GlassVeil))
        dialog.close()

    def test_navigator_keeps_folded_folders_per_project(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMenu

        self.open_example()
        window = self.window
        self.run_method("Descriptive statistics", {"Variables": ["Control"]})
        first = window.sessions.active
        window.project.dirty = False

        def combined():
            return next(window.navigator.topLevelItem(index) for index in range(window.navigator.topLevelItemCount())
                        if window.navigator.topLevelItem(index).text(0) == tr("nav.data_results"))

        branch = combined().child(0)
        self.assertGreater(branch.childCount(), 0)
        branch.setExpanded(False)
        window.refresh()
        self.assertTrue(combined().isExpanded())
        self.assertFalse(combined().child(0).isExpanded())

        def action(key):
            window._navigator_menu(QPoint(-1, -1))
            menu = self.app.activePopupWidget()
            self.assertIsInstance(menu, QMenu)
            next(item for item in menu.actions() if item.text() == tr(key)).trigger()
            menu.close()

        action("nav.collapse_all")
        window.refresh()
        self.assertFalse(combined().isExpanded())
        window.new_project()
        title, = window.project.add_tables({"Other": pd.DataFrame({"Reading": [1., 2.]})})
        window.open_sheet(("data", title))
        self.assertTrue(combined().isExpanded())
        window.switch_project(first)
        self.assertFalse(combined().isExpanded())
        self.assertFalse(window.project.dirty)
        action("nav.expand_all")
        window.refresh()
        self.assertTrue(combined().isExpanded())
        self.assertTrue(combined().child(0).isExpanded())
        self.assertFalse(window.project.dirty)

    def test_classic_navigator_toggles_and_restores_its_width(self):
        window = self.window
        self.open_example()
        self.app.processEvents()
        width = window.body.sizes()[0]
        self.assertGreater(width, 0)
        window.toggle_navigator()
        self.assertFalse(window.nav_card.isVisible())
        window.toggle_navigator()
        self.app.processEvents()
        self.assertTrue(window.nav_card.isVisible())
        self.assertEqual(window.body.sizes()[0], width)

    def test_worksheet_uses_tabular_figures(self):
        from PySide6.QtGui import QFont
        self.window.new_table()
        self.app.processEvents()
        font = self.window.sheet.font()
        if hasattr(font, "featureValue"):
            self.assertEqual(font.featureValue(QFont.Tag("tnum")), 1)


if __name__ == "__main__":
    unittest.main()
