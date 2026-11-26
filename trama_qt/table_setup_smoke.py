"""Desktop smoke for the Classic Qt welcome page."""

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QPushButton

from analisi.data import load_project
from analisi.i18n import set_language, tr
from analisi.table_templates import TEMPLATES, XY_FORMATS
from . import theme
from .smoke import LANGUAGES, Smoke
from .table_setup import TableSetup
from .window import MainWindow
from .shortcuts_dialog import ShortcutsDialog
from .worksheet_titles import TableFormatDialog


def run(folder):
    smoke = Smoke(Path(folder).resolve())
    for mode in ("light", "dark"):
        theme.set_mode(mode, smoke.app, remember=False)
        for language in LANGUAGES:
            set_language(language)
            theme.install_qt_translations(smoke.app, language)
            smoke.language = f"{language}-{mode}"
            window = smoke.window = MainWindow()
            window.error = lambda error: smoke.problem(str(error))
            available = smoke.screen_rect(window)
            window.resize(min(1024, available.width()), min(740, available.height()))
            window.show()
            smoke.app.processEvents()
            theme.keep_on_screen(window)
            try:
                exercise(smoke, window)
            except Exception as error:
                smoke.problem(repr(error))
            finally:
                window.project.dirty = False
                window.close()
                window.deleteLater()
                smoke.app.processEvents()
    return smoke.report()


def exercise(smoke, window):
    setup = window.page.findChild(TableSetup)
    assert setup.types.count() == len(TEMPLATES)
    for index, template in enumerate(TEMPLATES):
        setup.types.setCurrentRow(index)
        assert setup.selection()[0].kind == template.kind
        assert setup.preview.item(0, 0) is None
        setup.sample.setChecked(True)
        assert setup.selection() == (template, True)
        assert setup.preview.item(0, 0) is not None
        setup.empty.setChecked(True)
    setup.types.setCurrentRow(0)
    assert setup.replicates.isHidden()
    smoke.shot(window, "startup-blank")
    setup.encoding.setCurrentIndex(1)
    setup.series.setValue(3)
    setup.replicates.setValue(4)
    assert not setup.replicates.isHidden()
    assert len(setup.selection()[0].columns) == 14
    smoke.shot(window, "startup-replicates")

    setup.sample.setChecked(True)
    setup.examples.setCurrentIndex(2)
    assert setup.selection()[0].kind == "XY with precomputed error"
    assert setup.encoding.isHidden() and setup.preview.item(0, 0) is not None
    smoke.shot(window, "startup-example")
    button = next(button for button in setup.findChildren(QPushButton) if button.text() == tr("setup.create_example"))
    button.click()
    kind, title = window.selected
    assert kind == "data"
    assert window.project.tables[title].table_format == "XY with precomputed error"
    path = Path(smoke.folder) / f"{smoke.language}-example.alab"
    window.project.save(path)
    assert window.save()
    assert window.close_project()

    setup = window.page.findChild(TableSetup)
    smoke.app.processEvents()
    smoke.shot(window, "startup-recent")
    card = next(button for button in setup.findChildren(QPushButton, "setupRecent") if button.toolTip() == str(path))
    card.click()
    assert window.project.path == path and window.selected == ("data", title)
    exercise_existing_replicates(smoke, window)


def exercise_existing_replicates(smoke, window):
    window.create_worksheet(XY_FORMATS["Replicates in side-by-side subcolumns"], sample=True)
    _, title = window.selected
    dataset = window.project.tables[title]
    existing = dataset.columns
    failures = []

    def step():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, TableFormatDialog), "The table format dialog did not open."
            assert dialog.replicate_count.value() == 2, "Expected two original replicates."
            dialog.tabs.tabBar().setFocus()
            QTest.keyClick(dialog.tabs.tabBar(), Qt.Key.Key_Tab)
            assert dialog.focusWidget() is not dialog.tabs.tabBar(), "Tab did not move focus."
            help_opened = []

            def close_help():
                helper = smoke.app.activeModalWidget()
                if isinstance(helper, ShortcutsDialog):
                    help_opened.append(True)
                    helper.reject()

            QTimer.singleShot(100, close_help)
            QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_F1)
            assert help_opened, "F1 did not open the shortcuts."
            dialog.replicate_count.setValue(4)
            smoke.shot(dialog, "resize-replicates")
            ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
            ok.setFocus()
            QTest.keyClick(ok, Qt.Key.Key_Return)
        except Exception as error:
            failures.append(error)
            if dialog is not None:
                dialog.reject()

    QTimer.singleShot(120, step)
    window.actions["format_data_table"].trigger()
    assert not failures, failures
    assert len(dataset.columns) == len(existing) + 4
    assert dataset.raw["Control [4]"].isna().all()
    assert dataset.raw["Treatment [4]"].isna().all()
    smoke.shot(window, "resized-worksheet")
    path = Path(smoke.folder) / f"{smoke.language}-replicates.alab"
    window.project.save(path)
    assert load_project(path)[title].columns == dataset.columns
    window.undo()
    assert dataset.columns == existing
    window.undo(redo=True)
    assert len(dataset.columns) == len(existing) + 4
