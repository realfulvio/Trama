"""Light touches to the Classica Qt look: toolbar states, readable disabled icons, navigator icons by kind,
page actions drawn as buttons, informational Inspector notice, analysis dialog search and toolbar fitting."""
import unittest

try:
    from PySide6.QtCore import QEvent, QSize
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QLabel, QToolButton
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _colours(icon, mode=QIcon.Mode.Normal if QApplication else None):
    image = icon.pixmap(QSize(16, 16), mode).toImage()
    return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 200}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ClassicLookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window.resize(1280, 800)
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

    def test_stylesheet_has_toolbar_states_and_readable_group_labels(self):
        from trama_qt import theme
        sheet = theme.stylesheet()
        for rule in ("QFrame#classicToolbar QToolButton:hover", "QFrame#classicToolbar QToolButton:pressed",
                     "QFrame#classicToolbar QToolButton:focus", "QToolButton#pageAction", "QLabel#infoBanner"):
            self.assertIn(rule, sheet)
        self.assertIn(f"QLabel#classicGroup {{ color: {theme.T['group_ink']}; font-size: 9pt; }}", sheet)
        self.assertNotIn("border-radius: 4", sheet)  # still flat and square

    def test_disabled_classic_icons_use_the_darker_off_ink(self):
        from trama_qt import theme
        icon = theme.classic_icon("save")
        self.assertEqual(icon.pixmap(QSize(16, 16), QIcon.Mode.Disabled).isNull(), False)
        self.assertIn(theme.T["icon_off"].lower(), _colours(icon, QIcon.Mode.Disabled))
        self.assertNotIn(theme.T["text3"].lower(), _colours(icon, QIcon.Mode.Disabled))

    def test_navigator_icons_are_coloured_by_kind(self):
        from trama_qt import theme
        window = self.window
        window.project.add_tables({"dati": pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [2.0, 4.0, 7.0]})})
        self.app.processEvents()
        from PySide6.QtWidgets import QTreeWidgetItem
        section = QTreeWidgetItem(["test"])
        data = window._entry(section, "dati", ("data", "dati"), "data")
        self.assertIn(theme.T["kind_data"].lower(), _colours(data.icon(0)))
        self.assertNotIn(theme.T["kind_data"].lower(), _colours(theme.classic_icon("data")))

    def test_page_actions_are_drawn_as_buttons(self):
        from trama_qt.window import Page
        page = Page("x")
        button = page.command(self.window.actions["linked_table"])
        self.assertEqual(button.objectName(), "pageAction")

    def test_analysis_search_has_no_duplicate_caption(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0], "B": [2.0, 3.0, 5.0, 4.0]})
        dialog = AnalysisDialog(None, frame)
        self.addCleanup(dialog.deleteLater)
        placeholder = dialog.query.placeholderText()
        self.assertEqual(dialog.query.accessibleName(), placeholder)
        captions = [label for label in dialog.findChildren(QLabel) if label.text() == placeholder]
        self.assertEqual(captions, [])

    def test_ttest_paired_plot_controls_and_project_roundtrip(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from analisi import ttest_options as tt
        from analisi.paired_graphs import PAIRED_DIFFERENCES, TTEST_CORRELATION, TTEST_DIFFERENCES
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.gallery_catalog import graph_runs
        from trama_qt.project import Project, compute
        from trama_qt.result_tabs import result_labels

        set_language("it")
        source = pd.DataFrame({"Soggetto": list("abc"), "Prima": [2., 4., 8.], "Dopo": [1., 5., 5.]})
        recipe = {
            "Design": "Paired", tt.INPUT: tt.COLUMNS, tt.FIRST: "Prima", tt.SECOND: "Dopo", "Subject": "Soggetto",
        }
        dialog = AnalysisDialog(self.window, source, current=("t-test", recipe), only="t-test")
        self.addCleanup(dialog.deleteLater)
        self.assertNotIn(TTEST_DIFFERENCES, dialog.options())
        self.assertNotIn(TTEST_CORRELATION, dialog.options())
        for field in (TTEST_DIFFERENCES, TTEST_CORRELATION):
            self.assertNotIn(field, dialog.hidden)
            self.assertNotEqual(dialog.rows[field][0].text(), field)
            dialog.controls[field][1].setChecked(True)
        options = dialog.options()
        design = dialog.controls["Design"][1]
        design.setCurrentIndex(design.findData("Welch"))
        self.assertTrue({TTEST_DIFFERENCES, TTEST_CORRELATION}.issubset(dialog.hidden))
        self.assertNotIn(TTEST_DIFFERENCES, dialog.options())
        project = Project()
        project.add_tables({"Misure": source})
        run = project.candidate("Misure", "t-test", options)
        project.add_result(run, compute(run, source))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "paired.alab"
            project.save(path)
            reopened = Project()
            reopened.load(path)
            restored, = reopened.runs
            self.assertEqual(graph_runs(reopened), [(0, restored)])
            result = compute(restored, reopened.tables["Misure"].frame(mask_excluded=True))
            self.assertEqual(len(result.figure.axes), 2)
            self.assertEqual(result.tables[PAIRED_DIFFERENCES]["Difference"].tolist(), [1., -1., 3.])
            self.assertEqual(result_labels("t-test", PAIRED_DIFFERENCES),
                             ("Differenze appaiate", {"Subject": "Soggetto", "Difference": "Differenza"}))

    def test_narrow_toolbar_hides_groups_strictly_by_priority(self):
        from trama_qt.classic_bar import OVERFLOW_ORDER
        toolbar = self.window.toolbar
        for width in (1600, 1280, 1180, 1024, 900, 760, 560):
            self.window.resize(width, 800)
            self.app.processEvents()
            toolbar._fit()
            hidden = [group.name for group in toolbar.groups if not group.widget.isVisibleTo(toolbar)]
            shown = [group.name for group in toolbar.groups if group.widget.isVisibleTo(toolbar)]
            if not hidden:
                continue
            last_hidden = max(OVERFLOW_ORDER.index(name) for name in hidden)
            first_shown = min(OVERFLOW_ORDER.index(name) for name in shown)
            self.assertLess(last_hidden, first_shown, f"{width}px: hidden {hidden}, shown {shown}")


if __name__ == "__main__":
    unittest.main()
