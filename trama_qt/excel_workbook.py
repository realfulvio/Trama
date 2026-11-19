"""File → Import Excel workbook… and File → Export Excel workbook… on Qt.

Import: choose the sheets of an .xlsx (in workbook order, with their state and indicative size), a header row
for each one (or none) with a preview in Excel coordinates, then one atomic addition to the project. Export:
choose data sheets and single result tables, put them in order, see the final Excel names, and write one
verified workbook. Reading, validation and writing run on the window's worker with its progress and Cancel;
``analisi.xlsx_exchange`` does the work and never touches Qt.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from analisi.i18n import active_language
from analisi.xlsx_exchange import (ExchangeCancelled, MAX_EXCEL_ROWS, WorkbookReader, excel_sheet_names,
                                   materialize_index, prepare_workbook)

from . import theme

PREVIEW_ROWS = 12
PREVIEW_COLUMNS = 12
MAX_TABLES = 256

_ITALIAN = {
    "Import Excel workbook…": "Importa cartella Excel…",
    "Export Excel workbook…": "Esporta cartella Excel…",
    "Import Excel workbook": "Importa cartella Excel",
    "Export Excel workbook": "Esporta cartella Excel",
    "Choose the sheets to import and the header row of each one. Nothing is added until every sheet has been "
    "read.": "Scegli i fogli da importare e la riga d'intestazione di ciascuno. Non viene aggiunto nulla finché "
             "tutti i fogli non sono stati letti.",
    "Sheets": "Fogli", "Sheet": "Foglio", "State": "Stato", "Size": "Dimensioni",
    "visible": "visibile", "hidden": "nascosto", "veryHidden": "molto nascosto",
    "empty": "vuoto", "chart sheet": "foglio grafico",
    "This sheet has no values to import.": "Questo foglio non ha valori da importare.",
    "A chart sheet holds no cells to import.": "Un foglio grafico non ha celle da importare.",
    "Preview": "Anteprima", "Header row": "Riga d'intestazione", "No headers": "Senza intestazioni",
    "Names in Trama: {names}": "Nomi in Trama: {names}",
    "Rows above the header are left out.": "Le righe sopra l'intestazione vengono scartate.",
    "Import": "Importa", "Cancel": "Annulla", "Export": "Esporta",
    "Choose at least one sheet.": "Scegli almeno un foglio.",
    "A project holds at most {limit} data tables: choose no more than {room} sheets.":
        "Un progetto contiene al massimo {limit} tabelle dati: scegli al massimo {room} fogli.",
    "Fix the header row of {sheet} first.": "Correggi prima la riga d'intestazione di {sheet}.",
    "{count} sheets chosen": "{count} fogli scelti", "1 sheet chosen": "1 foglio scelto",
    "Reading the Excel workbook…": "Lettura della cartella Excel…",
    "Import cancelled: no sheet was added.": "Importazione annullata: nessun foglio aggiunto.",
    "Imported {count} sheet(s) from {name}.": "Importati {count} fogli da {name}.",
    "Imported with notes": "Importazione con avvisi",
    "{name} could not be imported. {error}": "Impossibile importare {name}. {error}",
    "Choose the data sheets and result tables to export and their order. Excel names are final.":
        "Scegli i fogli dati e le tabelle risultato da esportare e il loro ordine. I nomi Excel sono quelli "
        "definitivi.",
    "Name": "Nome", "Type": "Tipo", "Excel name": "Nome Excel",
    "Data sheet": "Foglio dati", "Result table": "Tabella risultato", "Move up": "Su", "Move down": "Giù",
    "Not calculated with the current data.": "Non calcolata con i dati attuali.",
    "Not current: {error}": "Non aggiornata: {error}",
    "Too many rows for an Excel sheet.": "Troppe righe per un foglio Excel.",
    "Nothing to export: the project has no data sheets or calculated result tables.":
        "Niente da esportare: il progetto non ha fogli dati né tabelle risultato calcolate.",
    "Choose at least one sheet or result table.": "Scegli almeno un foglio o una tabella risultato.",
    "Choose a file name ending in .xlsx.": "Scegli un nome di file che termini con .xlsx.",
    "{name} already exists. Replace it?": "{name} esiste già. Sostituirlo?",
    "Replace workbook": "Sostituisci cartella",
    "Writing the Excel workbook…": "Scrittura della cartella Excel…",
    "Export cancelled: no file was changed.": "Esportazione annullata: nessun file modificato.",
    "Exported {count} sheet(s) to {name}.": "Esportati {count} fogli in {name}.",
    "{name} could not be written. {error}": "Impossibile scrivere {name}. {error}",
    "Excel workbook": "Cartella di lavoro Excel",
    "The file was not replaced.": "Il file non è stato sostituito.",
}
_MESSAGES = [  # Engine messages (English) and their Italian form.
    (r'Worksheet "(.+)": the header row (\d+) is past the last row with values \((\d+)\)\.',
     'Foglio "{0}": la riga d\'intestazione {1} è oltre l\'ultima riga con valori ({2}).'),
    (r'Worksheet "(.+)": the header row (\d+) is past the rows read\.',
     'Foglio "{0}": la riga d\'intestazione {1} è oltre le righe lette.'),
    (r'Worksheet "(.+)" has no values to import\.', 'Il foglio "{0}" non ha valori da importare.'),
    (r'Worksheet "(.+)" has more than (\d+) columns\.', 'Il foglio "{0}" ha più di {1} colonne.'),
    (r'Worksheet "(.+)" exceeds the table size limit\.', 'Il foglio "{0}" supera il limite di dimensione delle '
                                                         'tabelle.'),
    (r'Worksheet "(.+)" could not be read\.', 'Impossibile leggere il foglio "{0}".'),
    (r'The workbook has no sheet named "(.+)"\.', 'La cartella non ha un foglio di nome "{0}".'),
    (r'"(.+)" is a chart sheet and holds no cells to import\.',
     '"{0}" è un foglio grafico e non ha celle da importare.'),
    (r"The file is not a valid \.xlsx workbook\.", "Il file non è una cartella .xlsx valida."),
    (r"The workbook exceeds 32 MiB\.", "La cartella supera 32 MiB."),
    (r"The workbook exceeds the decompressed size limit\.", "La cartella supera il limite di dimensione "
                                                            "decompressa."),
    (r"Only \.xlsx workbooks can be read: macro-enabled and binary Excel formats are not supported\.",
     "Si possono leggere solo cartelle .xlsx: i formati Excel con macro e binari non sono supportati."),
    (r"Macro-enabled workbooks are not supported\. Save it as \.xlsx without macros\.",
     "Le cartelle con macro non sono supportate. Salvala come .xlsx senza macro."),
    (r"Choose an \.xlsx workbook\.", "Scegli una cartella .xlsx."),
    (r"Formulas without a stored result stay empty — (.+)",
     "Le formule senza risultato memorizzato restano vuote — {0}"),
    (r"Excel error values stay empty — (.+)", "I valori di errore di Excel restano vuoti — {0}"),
    (r"Formulas linked to other workbooks keep their stored result — (.+)",
     "Le formule collegate ad altre cartelle mantengono il risultato memorizzato — {0}"),
    (r'Sheet "(.+)" \(Excel "(.+)"\), row (\d+), column "(.*)": (.+)\. Correct the data and export again\.',
     'Foglio "{0}" (Excel "{1}"), riga {2}, colonna "{3}": {4}. Correggi i dati ed esporta di nuovo.'),
    (r'Sheet "(.+)" \(Excel "(.+)"\), row (\d+), column "(.*)": (.+)\. Store it as text or round it, then '
     r'export again\.',
     'Foglio "{0}" (Excel "{1}"), riga {2}, colonna "{3}": {4}. Memorizzalo come testo o arrotondalo, poi '
     'esporta di nuovo.'),
    (r'Sheet "(.+)" \(Excel "(.+)"\), header of column (\d+): (.+)\. Correct the data and export again\.',
     'Foglio "{0}" (Excel "{1}"), intestazione della colonna {2}: {3}. Correggi i dati ed esporta di nuovo.'),
    (r'"(.+)" has ([\d,]+) rows: an Excel sheet holds at most ([\d,]+) below the header\. Split or filter the '
     r'data\.', '"{0}" ha {1} righe: un foglio Excel ne contiene al massimo {2} sotto l\'intestazione. Dividi o '
                'filtra i dati.'),
    (r"The exported workbook could not be opened again; nothing was replaced\.",
     "Impossibile riaprire la cartella esportata; nulla è stato sostituito."),
]
_REASONS = {  # Engine reasons inside the export messages.
    "infinite values cannot be stored in Excel": "i valori infiniti non si possono memorizzare in Excel",
    "the text contains control characters Excel cannot store":
        "il testo contiene caratteri di controllo che Excel non può memorizzare",
    "the text contains characters that cannot be written": "il testo contiene caratteri non scrivibili",
}


def t(text):
    return _ITALIAN.get(text, text) if active_language() == "it" else text


def translate(message):
    """An engine message in the active language (English stays as it is)."""
    message = str(message)
    if active_language() != "it":
        return message
    for pattern, italian in _MESSAGES:
        if match := re.fullmatch(pattern, message, flags=re.DOTALL):
            parts = [_REASONS.get(part, part) for part in match.groups()]
            for index, part in enumerate(parts):
                if found := re.fullmatch(r"the integer (-?\d+) has more than (\d+) digits and Excel would round it",
                                         part):
                    parts[index] = f"l'intero {found[1]} ha più di {found[2]} cifre ed Excel lo arrotonderebbe"
                elif found := re.fullmatch(r"a text of ([\d,]+) characters exceeds Excel's ([\d,]+)", part):
                    parts[index] = f"un testo di {found[1]} caratteri supera i {found[2]} di Excel"
            return italian.format(*parts)
    return _ITALIAN.get(message, message)


def confirm(parent, title, text):
    """Yes/No; the smoke and the tests replace it."""
    answer = QMessageBox.question(parent, title, text,
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def inform(parent, title, text):
    QMessageBox.information(parent, title, text)


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return repr(value) if not value.is_integer() else f"{value:.1f}"
    return str(value)


def _table(columns):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    return table


# == import ==========================================================================================
class ExcelImportDialog(QDialog):
    """``result`` is ``{sheet: header row or None}`` in workbook order after Import."""

    def __init__(self, parent, reader, path, *, room=MAX_TABLES):
        super().__init__(parent)
        self.setWindowTitle(t("Import Excel workbook"))
        self.reader, self.path, self.room = reader, Path(path), room
        self.result = None
        self.sheets = reader.sheets()
        self.headers = {item.name: 1 for item in self.sheets}
        self.errors = {}
        self.current = None
        outer = theme.scroll_body(self)
        title = QLabel(self.path.name)
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        hint = QLabel(t("Choose the sheets to import and the header row of each one. Nothing is added until every "
                        "sheet has been read."))
        hint.setWordWrap(True)
        outer.addWidget(hint)
        panes = QHBoxLayout()
        outer.addLayout(panes, 1)

        group = QGroupBox(t("Sheets"))
        column = QVBoxLayout(group)
        self.list = _table([t("Sheet"), t("State"), t("Size")])
        self.list.setAccessibleName(t("Sheets"))
        self.list.setRowCount(len(self.sheets))
        for row, info in enumerate(self.sheets):
            item = QTableWidgetItem(info.name)
            item.setToolTip(info.name)
            if info.importable:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if info.state == "visible" else Qt.CheckState.Unchecked)
            else:
                item.setFlags(Qt.ItemFlag.ItemIsSelectable)
                reason = "A chart sheet holds no cells to import." if info.kind != "worksheet" \
                    else "This sheet has no values to import."
                item.setToolTip(f"{info.name}\n{t(reason)}")
            self.list.setItem(row, 0, item)
            state = t(info.state)
            if not info.importable:
                state += " · " + t("empty" if info.kind == "worksheet" else "chart sheet")
            self.list.setItem(row, 1, QTableWidgetItem(state))
            size = f"≈ {info.rows:,} × {info.columns:,}" if info.rows and info.columns else "—"
            self.list.setItem(row, 2, QTableWidgetItem(size))
        header = self.list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.list.setMinimumWidth(300)
        column.addWidget(self.list, 1)
        self.chosen = QLabel()
        column.addWidget(self.chosen)
        panes.addWidget(group, 2)

        group = QGroupBox(t("Preview"))
        column = QVBoxLayout(group)
        controls = QHBoxLayout()
        label = QLabel(t("Header row"))
        controls.addWidget(label)
        self.header = QSpinBox()
        self.header.setRange(1, MAX_EXCEL_ROWS)
        self.header.setAccessibleName(t("Header row"))
        label.setBuddy(self.header)
        controls.addWidget(self.header)
        self.no_header = QCheckBox(t("No headers"))
        controls.addWidget(self.no_header)
        controls.addStretch(1)
        column.addLayout(controls)
        self.names = QLabel()
        self.names.setWordWrap(True)
        self.names.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.names)
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.grid.horizontalHeader().setDefaultSectionSize(92)
        self.grid.setAccessibleName(t("Preview"))
        column.addWidget(self.grid, 1)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        column.addWidget(self.notes)
        panes.addWidget(group, 3)

        self.buttons = QDialogButtonBox()
        self.import_button = self.buttons.addButton(t("Import"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setDefault(True)
        self.buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout().addWidget(self.buttons)

        self.list.currentCellChanged.connect(lambda row, *_: self.show_sheet(row))
        self.list.itemChanged.connect(lambda _item: self.update_state())
        self.header.valueChanged.connect(self._header_changed)
        self.no_header.toggled.connect(self._header_changed)
        first = next((row for row, info in enumerate(self.sheets) if info.importable), 0)
        self.list.setCurrentCell(first, 0)
        self.show_sheet(first)
        self.update_state()
        hint = self.sizeHint()
        self.resize(max(900, hint.width()), max(560, hint.height()))

    # -- state ---------------------------------------------------------------------------------------
    def checked(self):
        return [info.name for row, info in enumerate(self.sheets)
                if info.importable and self.list.item(row, 0).checkState() == Qt.CheckState.Checked]

    def set_checked(self, name, checked=True):
        for row, info in enumerate(self.sheets):
            if info.name == name:
                self.list.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def select(self, name):
        for row, info in enumerate(self.sheets):
            if info.name == name:
                self.list.setCurrentCell(row, 0)

    def set_header(self, name, header):
        """``header`` is a 1-based row or ``None`` (no headers) for sheet ``name``."""
        self.select(name)
        self.no_header.setChecked(header is None)
        if header is not None:
            self.header.setValue(header)
        self._header_changed()

    def show_sheet(self, row):
        if not 0 <= row < len(self.sheets):
            return
        info = self.sheets[row]
        self.current = info.name
        usable = info.importable
        for widget in (self.header, self.no_header):
            widget.blockSignals(True)
        value = self.headers.get(info.name, 1)
        self.no_header.setChecked(value is None)
        self.header.setValue(value or 1)
        self.header.setEnabled(usable and value is not None)
        self.no_header.setEnabled(usable)
        for widget in (self.header, self.no_header):
            widget.blockSignals(False)
        self.refresh_preview()

    def _header_changed(self, *_):
        if self.current is None:
            return
        info = next(item for item in self.sheets if item.name == self.current)
        if not info.importable:
            return
        self.header.setEnabled(not self.no_header.isChecked())
        self.headers[self.current] = None if self.no_header.isChecked() else self.header.value()
        self.refresh_preview()

    def refresh_preview(self):
        name = self.current
        info = next((item for item in self.sheets if item.name == name), None)
        self.grid.clear()
        self.grid.setRowCount(0)
        self.grid.setColumnCount(0)
        if info is None or not info.importable:
            reason = "A chart sheet holds no cells to import." if info is not None and info.kind != "worksheet" \
                else "This sheet has no values to import."
            self._note(t(reason), error=False)
            self.names.setText("")
            return
        header = self.headers.get(name, 1)
        try:
            preview = self.reader.preview(name, header, rows=PREVIEW_ROWS, columns=PREVIEW_COLUMNS)
        except ValueError as error:
            self.errors[name] = translate(error)
            self._note(self.errors[name], error=True)
            self.names.setText("")
            self.update_state()
            return
        self.grid.setColumnCount(len(preview.letters))
        self.grid.setHorizontalHeaderLabels(preview.letters)
        self.grid.setRowCount(len(preview.grid))
        self.grid.setVerticalHeaderLabels([str(preview.first_row + index) for index in range(len(preview.grid))])
        muted = theme.color("text3")
        for row, values in enumerate(preview.grid):
            number = preview.first_row + row
            for column, value in enumerate(values):
                item = QTableWidgetItem(_cell_text(value))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if header is not None and number < header:
                    item.setForeground(muted)
                elif header is not None and number == header:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.grid.setItem(row, column, item)
        if preview.error:
            self.errors[name] = translate(preview.error)
            self._note(self.errors[name], error=True)
            self.names.setText("")
        else:
            self.errors.pop(name, None)
            shown = preview.names[:PREVIEW_COLUMNS]
            more = f" … (+{len(preview.names) - len(shown)})" if len(preview.names) > len(shown) else ""
            self.names.setText(t("Names in Trama: {names}").format(names=", ".join(shown) + more))
            notes = [translate(note) for note in preview.warnings]
            if header and header > 1:
                notes.insert(0, t("Rows above the header are left out."))
            self._note("\n".join(notes), error=False)
        self.update_state()

    def _note(self, text, *, error):
        self.notes.setObjectName("errorBanner" if error else "")
        self.notes.setText(text)
        self.notes.setVisible(bool(text))
        self.notes.style().polish(self.notes)

    def update_state(self):
        chosen = self.checked()
        self.chosen.setText(t("1 sheet chosen") if len(chosen) == 1
                            else t("{count} sheets chosen").format(count=len(chosen)))
        blocked = [name for name in chosen if name in self.errors]
        self.import_button.setEnabled(bool(chosen) and not blocked and len(chosen) <= self.room)

    def problem(self):
        """Why Import cannot run now, or ``None``."""
        chosen = self.checked()
        if not chosen:
            return t("Choose at least one sheet.")
        if len(chosen) > self.room:
            return t("A project holds at most {limit} data tables: choose no more than {room} sheets.").format(
                limit=MAX_TABLES, room=self.room)
        for name in chosen:
            if name in self.errors:
                return t("Fix the header row of {sheet} first.").format(sheet=name)
        return None

    def accept(self):
        problem = self.problem()
        if problem:
            self._note(problem, error=True)
            return
        self.result = {name: self.headers.get(name, 1) for name in self.checked()}
        super().accept()


def import_workbook(window, path=None):
    """File → Import Excel workbook…: choose a file, the sheets and header rows, then read on the worker."""
    if window.busy():
        return
    if path is None:
        path, _ = QFileDialog.getOpenFileName(window, t("Import Excel workbook"), "",
                                              f"{t('Excel workbook')} (*.xlsx)")
        if not path:
            return
    path = Path(path)
    try:
        reader = WorkbookReader(path)
    except ValueError as error:
        window.error(t("{name} could not be imported. {error}").format(name=path.name, error=translate(error)))
        return
    try:
        dialog = ExcelImportDialog(window, reader, path, room=MAX_TABLES - len(window.project.tables))
        accepted = dialog.exec() == QDialog.DialogCode.Accepted and dialog.result
        selections = dialog.result
        dialog.deleteLater()
    except Exception:
        reader.close()
        raise
    if not accepted:
        reader.close()
        return
    from .project import CalculationControl
    project, control, warnings = window.project, CalculationControl(), []

    def job():
        try:
            return reader.read(selections, warnings=warnings, progress=control.report, cancel=control.cancel)
        finally:
            reader.close()

    def done(future, cancelled):
        try:
            tables = future.result()
        except ExchangeCancelled:
            window.status(t("Import cancelled: no sheet was added."))
            return
        except Exception as error:  # noqa: BLE001 - nothing was added; say why.
            message = t("{name} could not be imported. {error}").format(name=path.name, error=translate(error))
            window.status(message)
            window.error(message)
            return
        if cancelled or window.project is not project:
            window.status(t("Import cancelled: no sheet was added."))
            return
        try:
            titles = project.add_tables(tables)
        except ValueError as error:
            message = t("{name} could not be imported. {error}").format(name=path.name, error=translate(error))
            window.status(message)
            window.error(message)
            return
        window.status(t("Imported {count} sheet(s) from {name}.").format(count=len(titles), name=path.name))
        window.show_sheet("data", titles[0])
        if warnings:
            inform(window, t("Imported with notes"), "\n".join(translate(note) for note in warnings))

    window._start(window.worker.submit(job), control, done, t("Reading the Excel workbook…"))


# == export ==========================================================================================
@dataclass
class ExportItem:
    key: tuple  # ("data", title) or ("result", run index, table name)
    label: str
    kind: str  # "data" or "result"
    reason: str | None = None  # Why it cannot be chosen.


def export_items(project):
    """Every data sheet, then every result table of every analysis, with the reason when one is unavailable.
    Reads the state as it is: nothing is recalculated."""
    from .window import preferred_view
    items = [ExportItem(("data", title), title, "data") for title in project.tables]
    for item in items:
        if len(project.tables[item.key[1]].raw) + 1 > MAX_EXCEL_ROWS:
            item.reason = t("Too many rows for an Excel sheet.")
    for index, run in enumerate(project.runs):
        tables = getattr(run.result, "tables", None) if run.result is not None else None
        if tables:
            reason = t("Not current: {error}").format(error=run.calculation_error) if run.calculation_error else None
            items.extend(ExportItem(("result", index, name), f"{run.name} · {name}", "result", reason)
                         for name in tables)
        elif run.result is None and preferred_view(run, None) == "result":  # An analysis without results: listed.
            reason = (t("Not current: {error}").format(error=run.calculation_error) if run.calculation_error
                      else t("Not calculated with the current data."))
            items.append(ExportItem(("result", index, None), run.name, "result", reason))
    return items


def default_keys(window, items):
    """The sheet or result table on screen, when it can be exported."""
    selected = window.selected
    if not selected:
        return []
    kind, key = selected
    wanted = None
    if kind == "data":
        wanted = ("data", key)
    elif kind == "result":
        run = window.project.runs[key]
        tables = list(getattr(run.result, "tables", None) or {}) if run.result is not None else []
        position = window.result_tabs.currentIndex() if window.result_tabs is not None else 0
        if tables:
            wanted = ("result", key, tables[max(0, min(position, len(tables) - 1))])
    return [item.key for item in items if item.key == wanted and item.reason is None]


class ExcelExportDialog(QDialog):
    """``result`` lists the chosen keys in order after Export."""

    def __init__(self, parent, items, *, chosen=()):
        super().__init__(parent)
        self.setWindowTitle(t("Export Excel workbook"))
        self.items = list(items)
        self.result = None
        outer = theme.scroll_body(self)
        title = QLabel(t("Export Excel workbook"))
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        hint = QLabel(t("Choose the data sheets and result tables to export and their order. Excel names are "
                        "final."))
        hint.setWordWrap(True)
        outer.addWidget(hint)
        row = QHBoxLayout()
        outer.addLayout(row, 1)
        self.table = _table([t("Name"), t("Type"), t("Excel name")])
        self.table.setAccessibleName(t("Export Excel workbook"))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 220)
        row.addWidget(self.table, 1)
        side = QVBoxLayout()
        self.up = QPushButton(t("Move up"))
        self.up.setIcon(theme.icon("chevron-up"))
        self.down = QPushButton(t("Move down"))
        self.down.setIcon(theme.icon("chevron-down"))
        self.up.setToolTip(f"{t('Move up')} (Alt+↑)")
        self.down.setToolTip(f"{t('Move down')} (Alt+↓)")
        side.addWidget(self.up)
        side.addWidget(self.down)
        side.addStretch(1)
        row.addLayout(side)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        outer.addWidget(self.notes)
        self.buttons = QDialogButtonBox()
        self.export_button = self.buttons.addButton(t("Export"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.export_button.setDefault(True)
        self.buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout().addWidget(self.buttons)

        chosen = list(chosen)
        ordered = [item for key in chosen for item in self.items if item.key == key]
        ordered += [item for item in self.items if item.key not in chosen]
        self._fill(ordered, set(chosen))
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        QShortcut(QKeySequence("Alt+Up"), self, activated=lambda: self.move(-1))
        QShortcut(QKeySequence("Alt+Down"), self, activated=lambda: self.move(1))
        self.table.itemChanged.connect(lambda _item: self.update_names())
        self.table.currentCellChanged.connect(lambda *_: self._sync_buttons())
        self.table.setCurrentCell(0, 0)
        self.update_names()
        hint = self.sizeHint()
        self.resize(max(760, hint.width()), max(480, hint.height()))

    def _fill(self, ordered, checked):
        self.table.blockSignals(True)
        self.order = list(ordered)
        self.table.setRowCount(len(self.order))
        muted = theme.color("text3")
        for row, item in enumerate(self.order):
            name = QTableWidgetItem(item.label)
            name.setData(Qt.ItemDataRole.UserRole, item.key)
            if item.reason:
                name.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                name.setForeground(muted)
                name.setToolTip(f"{item.label}\n{item.reason}")
            else:
                name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                name.setCheckState(Qt.CheckState.Checked if item.key in checked else Qt.CheckState.Unchecked)
                name.setToolTip(item.label)
            self.table.setItem(row, 0, name)
            kind = QTableWidgetItem(t("Data sheet") if item.kind == "data" else t("Result table"))
            self.table.setItem(row, 1, kind)
            excel = QTableWidgetItem(item.reason or "")
            if item.reason:
                excel.setForeground(muted)
                excel.setToolTip(item.reason)
            self.table.setItem(row, 2, excel)
        self.table.blockSignals(False)

    def chosen(self):
        return [item.key for row, item in enumerate(self.order)
                if not item.reason and self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def set_checked(self, key, checked=True):
        for row, item in enumerate(self.order):
            if item.key == key and not item.reason:
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def excel_names(self):
        keys = self.chosen()
        labels = [next(item.label for item in self.order if item.key == key) for key in keys]
        return dict(zip(keys, excel_sheet_names(labels)))

    def update_names(self):
        names = self.excel_names()
        self.table.blockSignals(True)
        for row, item in enumerate(self.order):
            if item.reason:
                continue
            self.table.item(row, 2).setText(names.get(item.key, ""))
        self.table.blockSignals(False)
        self.export_button.setEnabled(bool(names))
        self.notes.setText("" if names else t("Choose at least one sheet or result table."))
        self._sync_buttons()

    def _sync_buttons(self):
        row = self.table.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.table.rowCount() - 1)

    def move(self, step):
        row = self.table.currentRow()
        target = row + step
        if not (0 <= row < len(self.order) and 0 <= target < len(self.order)):
            return
        checked = set(self.chosen())
        self.order[row], self.order[target] = self.order[target], self.order[row]
        self._fill(self.order, checked)
        self.table.setCurrentCell(target, 0)
        self.update_names()

    def move_key(self, key, position):
        """Put ``key`` at row ``position`` (smoke and tests: the same path as the buttons)."""
        row = next(index for index, item in enumerate(self.order) if item.key == key)
        self.table.setCurrentCell(row, 0)
        while row != position:
            self.move(-1 if position < row else 1)
            row += -1 if position < row else 1

    def accept(self):
        keys = self.chosen()
        if not keys:
            self.notes.setText(t("Choose at least one sheet or result table."))
            return
        self.result = keys
        super().accept()


def _frames(project, items, keys):
    """``[(desired name, DataFrame)]`` for the chosen keys: data as the CSV export sees it (Trama formulas
    calculated, exclusions masked), result tables with their index as columns."""
    labels = {item.key: item.label for item in items}
    entries = []
    for key in keys:
        if key[0] == "data":
            frame = project.tables[key[1]].frame(mask_excluded=True)
        else:
            run = project.runs[key[1]]
            frame = materialize_index(run.result.tables[key[2]])
        entries.append((labels[key], frame))
    return entries


def export_workbook(window, path=None):
    """File → Export Excel workbook…: choose and order the sheets, a file, then write on the worker."""
    if window.busy() or not window.settle_graph_draft():
        return
    project = window.project
    items = export_items(project)
    if not any(item.reason is None for item in items):
        window.error(t("Nothing to export: the project has no data sheets or calculated result tables."))
        return
    dialog = ExcelExportDialog(window, items, chosen=default_keys(window, items))
    accepted = dialog.exec() == QDialog.DialogCode.Accepted and dialog.result
    keys = dialog.result
    dialog.deleteLater()
    if not accepted:
        return
    if path is None:
        suggested = f"{project.title}.xlsx"
        path, _ = QFileDialog.getSaveFileName(window, t("Export Excel workbook"), suggested,
                                              f"{t('Excel workbook')} (*.xlsx)",
                                              options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(".xlsx")
    if path.suffix.lower() != ".xlsx":
        window.error(t("Choose a file name ending in .xlsx."))
        return
    overwrite = False
    if path.exists():
        if not confirm(window, t("Replace workbook"), t("{name} already exists. Replace it?").format(name=path.name)):
            return
        overwrite = True
    try:
        entries = _frames(project, items, keys)
    except (ValueError, TypeError) as error:
        window.error(t("{name} could not be written. {error}").format(name=path.name, error=translate(error)))
        return
    from .project import CalculationControl
    control = CalculationControl()

    def job():
        return prepare_workbook(path, entries, progress=control.report, cancel=control.cancel)

    def done(future, cancelled):
        try:
            prepared = future.result()
        except ExchangeCancelled:
            window.status(t("Export cancelled: no file was changed."))
            return
        except Exception as error:  # noqa: BLE001 - nothing was published; say why.
            message = t("{name} could not be written. {error}").format(name=path.name, error=translate(error))
            window.status(message)
            window.error(message)
            return
        if cancelled:
            prepared.discard()
            window.status(t("Export cancelled: no file was changed."))
            return
        replace = overwrite
        if not replace and path.exists():  # It appeared while the workbook was being written.
            replace = confirm(window, t("Replace workbook"),
                              t("{name} already exists. Replace it?").format(name=path.name))
            if not replace:
                prepared.discard()
                window.status(t("The file was not replaced."))
                return
        try:
            names = prepared.publish(overwrite=replace)
        except OSError as error:
            message = t("{name} could not be written. {error}").format(name=path.name, error=error)
            window.status(message)
            window.error(message)
            return
        window.status(t("Exported {count} sheet(s) to {name}.").format(count=len(names), name=path.name))

    window._start(window.worker.submit(job), control, done, t("Writing the Excel workbook…"))
