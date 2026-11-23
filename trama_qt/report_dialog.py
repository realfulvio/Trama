"""File → Export analysis report…: choose, order and rename the sections of a reproducible report.

The dialog only reads the project (``report_catalog.candidates``). After OK the window asks for the
file, freezes the chosen results on the GUI thread (one section at a time, with Cancel) and writes the
ZIP in the background with ``analisi.report_bundle.export_bundle``. Exporting never marks the project as
modified, never changes the selection and never applies a graph style on its own.
"""
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QApplication)

from analisi._version import VERSION
from analisi.i18n import LANGUAGE_NAMES, active_language
from analisi.report_bundle import (INDEX, MANIFEST, MAX_LABEL, MAX_NOTE, MAX_SECTIONS, MAX_TITLE, PROJECT,
                                   ReportCancelled, export_bundle, section_path)

from . import report_catalog as catalog
from . import theme
from .theme import fit_dialog

_TEXT = {
    "command": ("Export analysis report…", "Esporta report di analisi…"),
    "title": ("Export analysis report", "Esporta report di analisi"),
    "report_title": ("Title", "Titolo"),
    "note": ("Note", "Nota"),
    "language": ("Report language", "Lingua del report"),
    "sections": ("Sections (tick to include, F2 or double click to rename)",
                 "Sezioni (spunta per includere, F2 o doppio clic per rinominare)"),
    "up": ("Move up", "Sposta su"), "down": ("Move down", "Sposta giù"), "rename": ("Rename", "Rinomina"),
    "all": ("Select all", "Seleziona tutto"), "none": ("Select none", "Deseleziona tutto"),
    "project": ("Include a copy of the project (.alab)", "Includi una copia del progetto (.alab)"),
    "project_warning": ("The .alab copy is the complete project: it also contains the original data, the Info "
                        "sheets and the internal references. Leave it off to share only the chosen results.",
                        "La copia .alab è il progetto completo: contiene anche i dati originali, i fogli Info e i "
                        "riferimenti interni. Lasciala spenta per condividere solo i risultati scelti."),
    "contents": ("The report will contain:", "Il report conterrà:"),
    "unavailable": ("not available", "non disponibile"),
    "table": ("Table", "Tabella"), "figure": ("Figure", "Figura"),
    "export": ("Export…", "Esporta…"), "cancel": ("Cancel", "Annulla"),
    "empty_selection": ("Select at least one table, graph or layout.",
                        "Seleziona almeno una tabella, un grafico o un layout."),
    "empty_title": ("Enter a title for the report.", "Inserisci un titolo per il report."),
    "long_title": ("The title can be at most {limit} characters.", "Il titolo può avere al massimo {limit} caratteri."),
    "long_note": ("The note can be at most {limit} characters.", "La nota può avere al massimo {limit} caratteri."),
    "empty_label": ("Section {position} needs a name.", "La sezione {position} deve avere un nome."),
    "long_label": ("The name of section {position} can be at most {limit} characters.",
                   "Il nome della sezione {position} può avere al massimo {limit} caratteri."),
    "too_many": ("A report holds at most {limit} sections.", "Un report contiene al massimo {limit} sezioni."),
    "nothing": ("This project has no calculated result table, graph or layout to put in a report.",
                "Questo progetto non ha tabelle di risultati, grafici o layout calcolati da mettere in un report."),
    "file_filter": ("Trama report (*.zip)", "Report Trama (*.zip)"),
    "replace_title": ("Replace report", "Sostituisci report"),
    "replace": ("{name} already exists. Replace it with the new report?",
                "{name} esiste già. Sostituirlo con il nuovo report?"),
    "changed": ("The chosen results changed after the preview ({name}). Open the report again to see the "
                "current contents.",
                "I risultati scelti sono cambiati dopo l'anteprima ({name}). Riapri il report per vedere il "
                "contenuto attuale."),
    "preparing": ("Preparing the report…", "Preparazione del report…"),
    "writing": ("Writing the report…", "Scrittura del report…"),
    "cancelled": ("Report cancelled: no file was changed.", "Report annullato: nessun file è stato modificato."),
    "done": ("Report exported with {count} sections: {path}", "Report esportato con {count} sezioni: {path}"),
    "done_one": ("Report exported with 1 section: {path}", "Report esportato con 1 sezione: {path}"),
}


def text(key, **values):
    english, italian = _TEXT[key]
    message = italian if active_language() == "it" else english
    return message.format(**values) if values else message


class ReportDialog(QDialog):
    """``result`` after OK: ``title``, ``note``, ``language``, ``include_project`` and ``items`` as a list of
    ``(Item, label)`` in report order."""

    def __init__(self, parent, items, title):
        super().__init__(parent)
        self.setObjectName("reportDialog")
        self.setWindowTitle(text("title"))
        self.items, self.result = list(items), None
        outer = theme.scroll_body(self)
        form = QFormLayout()
        self.title = QLineEdit(title)
        self.title.setObjectName("reportTitle")
        self.title.setAccessibleName(text("report_title"))
        form.addRow(text("report_title"), self.title)
        self.note = QPlainTextEdit()
        self.note.setObjectName("reportNote")
        self.note.setAccessibleName(text("note"))
        self.note.setTabChangesFocus(True)
        self.note.setFixedHeight(self.note.fontMetrics().lineSpacing() * 4 + 16)
        form.addRow(text("note"), self.note)
        self.language = QComboBox()
        self.language.setObjectName("reportLanguage")
        for code, name in LANGUAGE_NAMES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(active_language())))
        form.addRow(text("language"), self.language)
        outer.addLayout(form)

        box = QGroupBox(text("sections"))
        grid = QGridLayout(box)
        self.list = QListWidget()
        self.list.setObjectName("reportSections")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                  | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setAccessibleName(text("sections"))
        self.list.setWordWrap(True)  # The reason of an unavailable row is read in full, not cut at the edge.
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        grid.addWidget(self.list, 0, 0, 6, 1)
        self.buttons = {}
        for row, (key, handler) in enumerate((("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                                              ("rename", self.rename), ("all", lambda: self.check_all(True)),
                                              ("none", lambda: self.check_all(False)))):
            button = QPushButton(text(key))
            button.setObjectName(f"report_{key}")
            button.clicked.connect(handler)
            grid.addWidget(button, row, 1)
            self.buttons[key] = button
        grid.setRowStretch(5, 1)
        outer.addWidget(box, 1)

        self.project = QCheckBox(text("project"))
        self.project.setObjectName("reportProject")
        self.project.setChecked(False)
        outer.addWidget(self.project)
        warning = QLabel(text("project_warning"))
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        outer.addWidget(warning)
        self.summary = QLabel()
        self.summary.setObjectName("reportSummary")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        # The final contents scroll inside a few lines, so Export and Cancel stay on screen with 100 sections.
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("reportContents")
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName(text("contents"))
        self.preview.setFixedHeight(self.preview.fontMetrics().lineSpacing() * 6 + 16)
        outer.addWidget(self.preview)
        self.box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setText(text("export"))
        self.box.button(QDialogButtonBox.StandardButton.Cancel).setText(text("cancel"))
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        self.layout().addWidget(self.box)

        for item in self.items:
            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, item)
            if item.available:
                row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                             | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                row.setCheckState(Qt.CheckState.Checked)
                row.setText(item.label)
                row.setToolTip(f"{text(item.kind)} · {item.method}")
            else:
                row.setFlags(Qt.ItemFlag.ItemIsSelectable)  # Shown with its reason, never checkable.
                row.setText(f"{item.label} — {text('unavailable')}: {item.reason}")
                row.setToolTip(item.reason)
                row.setIcon(theme.icon("triangle-alert", "text2", 16))
                font = row.font()
                font.setItalic(True)
                row.setFont(font)
            self.list.addItem(row)
        self.list.itemChanged.connect(lambda _row: self.refresh())
        self.title.textChanged.connect(self.refresh)
        self.note.textChanged.connect(self.refresh)
        self.project.toggled.connect(self.refresh)
        self.list.currentRowChanged.connect(lambda _row: self._buttons())
        self.refresh()
        fit_dialog(self, 680, 640)

    # -- state ---------------------------------------------------------------------------------
    def rows(self):
        return [self.list.item(position) for position in range(self.list.count())]

    def chosen(self):
        """``(Item, label)`` of the ticked rows, in list order."""
        return [(row.data(Qt.ItemDataRole.UserRole), row.text()) for row in self.rows()
                if row.data(Qt.ItemDataRole.UserRole).available and row.checkState() == Qt.CheckState.Checked]

    def problem(self):
        """The first field error, as ``(message, widget)``, or None."""
        title = self.title.text()
        if not title.strip():
            return text("empty_title"), self.title
        if len(title) > MAX_TITLE:
            return text("long_title", limit=MAX_TITLE), self.title
        if len(self.note.toPlainText()) > MAX_NOTE:
            return text("long_note", limit=MAX_NOTE), self.note
        chosen = self.chosen()
        if not chosen:
            return text("empty_selection"), self.list
        if len(chosen) > MAX_SECTIONS:
            return text("too_many", limit=MAX_SECTIONS), self.list
        for position, (_item, label) in enumerate(chosen, 1):
            if not label.strip():
                return text("empty_label", position=position), self.list
            if len(label) > MAX_LABEL:
                return text("long_label", position=position, limit=MAX_LABEL), self.list
        return None

    def contents(self):
        lines = [INDEX, MANIFEST]
        for position, (item, label) in enumerate(self.chosen(), 1):
            lines.append(f"{section_path(position, item.kind)} — {label}")
        if self.project.isChecked():
            lines.append(PROJECT)
        return lines

    def refresh(self):
        problem = self.problem()
        if problem:
            self.summary.setObjectName("errorBanner")
            self.summary.setText(problem[0])
        else:
            self.summary.setObjectName("reportSummary")
            self.summary.setText(text("contents"))
        self.preview.setPlainText("\n".join(self.contents()))
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self._buttons()

    def _buttons(self):
        position = self.list.currentRow()
        row = self.list.item(position) if position >= 0 else None
        self.buttons["up"].setEnabled(position > 0)
        self.buttons["down"].setEnabled(0 <= position < self.list.count() - 1)
        self.buttons["rename"].setEnabled(row is not None and bool(row.flags() & Qt.ItemFlag.ItemIsEditable))

    # -- commands --------------------------------------------------------------------------------
    def move(self, step):
        position = self.list.currentRow()
        other = position + step
        if position < 0 or not 0 <= other < self.list.count():
            return
        self.list.blockSignals(True)
        row = self.list.takeItem(position)
        self.list.insertItem(other, row)
        self.list.setCurrentRow(other)
        self.list.blockSignals(False)
        self.refresh()

    def rename(self):
        row = self.list.currentItem()
        if row is not None and row.flags() & Qt.ItemFlag.ItemIsEditable:
            self.list.editItem(row)

    def check_all(self, checked):
        self.list.blockSignals(True)
        for row in self.rows():
            if row.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                row.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self.refresh()

    def accept(self):
        problem = self.problem()
        if problem:
            self.refresh()
            problem[1].setFocus()
            return
        self.result = {"title": self.title.text(), "note": self.note.toPlainText(),
                       "language": self.language.currentData(), "include_project": self.project.isChecked(),
                       "items": self.chosen()}
        super().accept()


# == the command =================================================================================
def default_title(project):
    path = project.path or project.origin
    return path.stem if path else project.title


def ask_destination(window, title):
    """The .zip to write, after an explicit confirmation when it already exists; None to stop."""
    name, _ = QFileDialog.getSaveFileName(window, text("title"), f"{title}.zip", text("file_filter"),
                                          options=QFileDialog.Option.DontConfirmOverwrite)
    if not name:
        return None
    path = Path(name)
    if path.suffix.lower() != ".zip":
        path = path.with_name(path.name + ".zip")
    if path.exists():
        answer = QMessageBox.question(window, text("replace_title"), text("replace", name=path.name),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return None
    return path


def freeze(window, project, chosen, include_project):
    """Sections and project bytes, taken in one pass on the GUI thread; None if the user cancelled.

    Raises ValueError when a chosen result changed after the preview.
    """
    steps = len(chosen) + (1 if include_project else 0)
    progress = QProgressDialog(text("preparing"), text("cancel"), 0, steps, window)
    progress.setObjectName("reportProgress")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(400)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    expected = [(item, catalog.signature(project, item)) for item, _label in chosen]
    sections = []
    try:
        with tempfile.TemporaryDirectory(prefix="trama-report-") as folder:
            for step, (item, label) in enumerate(chosen):
                if progress.wasCanceled():
                    return None
                if catalog.signature(project, item) != (item.signature, item.reason):
                    raise ValueError(text("changed", name=item.label))
                sections.append(catalog.section(project, item, label, folder))
                progress.setValue(step + 1)
                QApplication.processEvents()
            project_bytes = None
            if include_project and not progress.wasCanceled():
                project_bytes = catalog.project_copy(project)
                progress.setValue(steps)
            if progress.wasCanceled():
                return None
            if any(catalog.signature(project, item) != state for item, state in expected):
                raise ValueError(text("changed", name=next(item.label for item, state in expected
                                                           if catalog.signature(project, item) != state)))
            return sections, project_bytes
    finally:
        progress.close()
        progress.deleteLater()


def export_report(window):
    """File → Export analysis report… for the active project tab."""
    if window.busy() or not window.settle_graph_draft():
        return
    project = window.project
    items = catalog.candidates(project)
    if not any(item.available for item in items):
        reasons = sorted({item.reason for item in items if item.reason})
        window.error("\n".join([text("nothing"), *reasons[:6]]))
        return
    dialog = ReportDialog(window, items, default_title(project))
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result is None:
        return
    choice = dialog.result
    stale = [item.label for item, _label in choice["items"]
             if catalog.signature(project, item) != (item.signature, item.reason)]
    if stale:
        window.error(text("changed", name=stale[0]))
        return
    path = ask_destination(window, choice["title"])
    if path is None:
        return
    try:
        frozen = freeze(window, project, choice["items"], choice["include_project"])
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        window.error(error)
        return
    if frozen is None:
        window.status(text("cancelled"))
        return
    sections, project_bytes = frozen
    metadata = {"trama_version": VERSION,
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "language": choice["language"]}
    write(window, path, choice["title"], sections, metadata, project_bytes, choice["note"])


def write(window, path, title, sections, metadata, project_bytes, note):
    """Write the frozen report in the background; Cancel calculation stops it before the file is replaced."""
    from .project import CalculationControl

    control = CalculationControl()

    def work():
        return export_bundle(path, title, sections, metadata=metadata, project_bytes=project_bytes, note=note,
                             cancel=control.cancel.is_set)

    def done(future, cancelled):
        try:
            manifest = future.result()
        except ReportCancelled:
            window.status(text("cancelled"))
            return
        except (OSError, ValueError, TypeError) as error:
            window.error(error)
            return
        count = len(manifest["sections"])
        window.status(text("done_one", path=str(path)) if count == 1 else text("done", count=count, path=str(path)))

    window._start(window.worker.submit(work), control, done, text("writing"))
