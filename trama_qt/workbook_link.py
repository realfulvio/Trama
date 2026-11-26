"""Import one sheet of an .xlsx workbook into a worksheet and, optionally, link the worksheet to it.

File → Import data… on an .xlsx file, and Link to a file… / Change source… (File → Source link…) on a workbook,
open this dialog: the sheet by its exact name, the header row or reading the columns by position, a preview with
the names the columns take in Trama and, for a link, the key column. The workbook is read from the bytes digested
for the link, read-only, with the results Excel stored for its formulas (``analisi.xlsx_source``).
File → Import Excel workbook… still imports several sheets at once, without a link.
"""
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from analisi import source_link as engine, xlsx_source
from analisi.i18n import active_language
from analisi.source_link import LinkSpec, header_sources, key_problem
from analisi.xlsx_exchange import MAX_EXCEL_ROWS
from analisi.xlsx_source import WORKBOOK, WorkbookOptions

from . import theme

PREVIEW_ROWS = 12
_ITALIAN = {
    "Import Excel sheet": "Importa foglio Excel",
    "One sheet becomes one worksheet. To import several sheets at once without a link, use File → Import Excel "
    "workbook….": "Un foglio diventa un foglio di lavoro. Per importare più fogli insieme senza collegamento usa "
                  "File → Importa cartella Excel….",
    "Source": "Origine", "Sheet": "Foglio", "Header row": "Riga d'intestazione",
    "No header: read the columns by position": "Senza intestazione: leggi le colonne per posizione",
    "Link": "Collegamento", "Link to the source file": "Collega al file sorgente", "Key column": "Colonna chiave",
    "(none)": "(nessuna)",
    "The worksheet keeps the imported copy. File → Update from file… reads this sheet of the workbook again, found "
    "by its name, and shows the changes before applying them. A key column keeps each row's identity (styles, "
    "exclusions, labelled points) when rows move or change.":
        "Il foglio di lavoro conserva la copia importata. File → Aggiorna da file… rilegge questo foglio della "
        "cartella, trovato per nome, e mostra le modifiche prima di applicarle. Una colonna chiave mantiene "
        "l'identità di ogni riga (stili, esclusioni, punti etichettati) quando le righe si spostano o cambiano.",
    "Preview": "Anteprima", "Import": "Importa", "Read into the worksheet": "Leggi nel foglio", "Cancel": "Annulla",
    "{rows} rows × {columns} columns": "{rows} righe × {columns} colonne",
    "Showing the first {rows} rows.": "Mostrate le prime {rows} righe.",
    "Rows above the header are left out.": "Le righe sopra l'intestazione vengono scartate.",
    "Dates and times arrive as ISO text (2026-11-26); TRUE/FALSE as logical values.":
        "Date e ore arrivano come testo ISO (2026-11-26); VERO/FALSO come valori logici.",
    "Cell(s) {cells}: formulas without a stored result stay empty.":
        "Celle {cells}: le formule senza risultato memorizzato restano vuote.",
    "Cell(s) {cells}: Excel error values stay empty.": "Celle {cells}: i valori di errore di Excel restano vuoti.",
    "Cell(s) {cells}: formulas linked to other workbooks keep their stored result; the links are not updated.":
        "Celle {cells}: le formule collegate ad altre cartelle mantengono il risultato memorizzato; i collegamenti "
        "non vengono aggiornati.",
    "Import is not available:": "Importa non è disponibile:",
    "Choose a worksheet that holds values.": "Scegli un foglio che contenga valori.",
    "The workbook has no worksheet.": "La cartella non ha fogli di lavoro.",
}


def t(text, **values):
    if active_language() == "it":
        text = _ITALIAN.get(text, text)
    return text.format(**values) if values else text


def _translate(error):
    from .excel_workbook import translate as excel_translate
    from .source_link import translate
    text = translate(error)
    return excel_translate(text) if text == str(error) else text


def cell_text(value):
    """Every stored digit of a cell, as the worksheet shows it."""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return "TRUE" if value else "FALSE"
    return str(value)


class WorkbookImportDialog(QDialog):
    """``result`` is the imported frame after Import (every column of the sheet), ``sheet`` its sheet name,
    ``link_spec`` the link to create (or None). ``preset`` (a workbook ``SourceLink``) starts from its choices;
    ``relink`` is Change source…: the frame is not kept here (the worker reads the file again) and ``names`` lists
    the worksheet names of the columns. Reading the workbook may raise ValueError."""

    def __init__(self, parent, path, *, preset=None, relink=False):
        super().__init__(parent)
        self.setWindowTitle(t("Import Excel sheet"))
        self.path, self.relink = Path(path), relink
        self.result = self.link_spec = self.sheet = None
        self.names = []
        source = engine.read_file(self.path, text=False)
        self.content, self.size, self.sha256 = source.content, source.size, source.sha256
        self.sheets = xlsx_source.sheet_names(self.content)
        if not self.sheets:
            raise ValueError(t("The workbook has no worksheet."))
        self.loaded, self.table, self.error = {}, None, None
        preset = preset if preset is not None and preset.kind == WORKBOOK else None
        self.preset_key = preset.key if preset is not None else None

        outer = theme.scroll_body(self)
        title = QLabel(self.path.name)
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        if not relink:
            hint = QLabel(t("One sheet becomes one worksheet. To import several sheets at once without a link, use "
                            "File → Import Excel workbook…."))
            hint.setWordWrap(True)
            outer.addWidget(hint)
        panes = QHBoxLayout()
        outer.addLayout(panes, 1)
        settings = QVBoxLayout()
        panes.addLayout(settings)

        group = QGroupBox(t("Source"))
        form = QFormLayout(group)
        self.sheet_box = QComboBox()
        self.sheet_box.setObjectName("workbookSheet")
        for name in self.sheets:
            self.sheet_box.addItem(name, name)
        form.addRow(t("Sheet"), self.sheet_box)
        self.header = QSpinBox()
        self.header.setObjectName("workbookHeader")
        self.header.setRange(1, MAX_EXCEL_ROWS)
        form.addRow(t("Header row"), self.header)
        self.by_position = QCheckBox(t("No header: read the columns by position"))
        self.by_position.setObjectName("workbookByPosition")
        form.addRow(self.by_position)
        settings.addWidget(group)

        group = QGroupBox(t("Link"))
        column = QVBoxLayout(group)
        form = QFormLayout()
        column.addLayout(form)
        self.link = QCheckBox(t("Link to the source file"))
        self.link.setObjectName("linkSource")
        form.addRow(self.link)
        self.key = QComboBox()
        self.key.setObjectName("linkKey")
        self.key.addItem(t("(none)"), None)
        form.addRow(t("Key column"), self.key)
        note = QLabel(t("The worksheet keeps the imported copy. File → Update from file… reads this sheet of the "
                        "workbook again, found by its name, and shows the changes before applying them. A key column "
                        "keeps each row's identity (styles, exclusions, labelled points) when rows move or change."))
        note.setWordWrap(True)
        note.setMaximumWidth(340)
        column.addWidget(note)  # Outside the form: a wrapped label in a form row can be clipped at 150 %.
        self.key.setEnabled(False)
        if relink:
            self.link.setChecked(True)
            self.link.setEnabled(False)
            self.key.setEnabled(True)
        settings.addWidget(group)
        settings.addStretch(1)

        group = QGroupBox(t("Preview"))
        preview = QVBoxLayout(group)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        preview.addWidget(self.summary)
        self.grid = QTableWidget()
        self.grid.setObjectName("workbookPreview")
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.grid.setTabKeyNavigation(False)
        self.grid.setAlternatingRowColors(True)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.grid.horizontalHeader().setDefaultSectionSize(96)
        preview.addWidget(self.grid, 1)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview.addWidget(self.notes)
        self.blocked = QLabel()
        self.blocked.setObjectName("errorBanner")
        self.blocked.setWordWrap(True)
        preview.addWidget(self.blocked)
        panes.addWidget(group, 1)

        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton(t("Read into the worksheet" if relink else "Import"),
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setDefault(True)
        buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)

        if preset is not None:
            if preset.options.sheet in self.sheets:
                self.sheet_box.setCurrentIndex(self.sheets.index(preset.options.sheet))
            self.by_position.setChecked(preset.options.header is None)
            self.header.setValue(preset.options.header or 1)
        self.header.setEnabled(not self.by_position.isChecked())
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.refresh_preview)
        self.sheet_box.currentIndexChanged.connect(self.refresh_preview)
        self.header.valueChanged.connect(self.timer.start)
        self.by_position.toggled.connect(self._position_toggled)
        self.link.toggled.connect(self._link_toggled)
        self.key.currentIndexChanged.connect(self._sync)
        self.refresh_preview()
        hint_size = self.sizeHint()
        theme.fit_dialog(self, max(860, hint_size.width()), max(540, hint_size.height()))

    # -- choices --------------------------------------------------------------------------------------------------
    def options(self):
        return WorkbookOptions(self.sheet_box.currentData(),
                               None if self.by_position.isChecked() else self.header.value())

    def set_choice(self, sheet, header=1):
        """Choose ``sheet`` and the header row ``header`` (``None``: by position); the preview follows."""
        self.sheet_box.setCurrentIndex(self.sheets.index(sheet))
        self.by_position.setChecked(header is None)
        if header is not None:
            self.header.setValue(header)
        self.refresh_preview()

    def set_key(self, name):
        self.key.setCurrentIndex(max(0, self.key.findData(name)))

    def _position_toggled(self, checked):
        self.header.setEnabled(not checked)
        self.refresh_preview()

    def _link_toggled(self, checked):
        self.key.setEnabled(checked)
        self._sync()

    def _loaded(self, sheet):
        if sheet not in self.loaded:
            try:
                self.loaded[sheet] = xlsx_source.load_sheet(self.content, sheet)
            except ValueError as error:
                self.loaded[sheet] = error
        return self.loaded[sheet]

    def refresh_preview(self, *_):
        self.timer.stop()
        options = self.options()
        self.table = self.error = None
        loaded = self._loaded(options.sheet)
        try:
            if isinstance(loaded, Exception):
                raise loaded
            self.table = loaded.table(options.header)
        except ValueError as error:
            self.error = _translate(error)
        self._fill()
        self._key_choices()
        self._sync()

    def _fill(self):
        self.grid.clear()
        table = self.table
        if table is None:
            self.grid.setRowCount(0)
            self.grid.setColumnCount(0)
            self.summary.setText("")
            self.notes.setVisible(False)
            return
        frame = table.frame
        shown = frame.iloc[:PREVIEW_ROWS]
        self.grid.setColumnCount(len(frame.columns))
        self.grid.setRowCount(len(shown))
        self.grid.setHorizontalHeaderLabels([str(name) for name in frame.columns])
        numeric = [pd.api.types.is_numeric_dtype(frame[name]) and not pd.api.types.is_bool_dtype(frame[name])
                   for name in frame.columns]
        for column, right in enumerate(numeric):
            if right:
                self.grid.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignRight
                                                                        | Qt.AlignmentFlag.AlignVCenter)
        for row, values in enumerate(shown.itertuples(index=False, name=None)):
            for column, value in enumerate(values):
                item = QTableWidgetItem(cell_text(value))
                if numeric[column]:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.grid.setItem(row, column, item)
        text = t("{rows} rows × {columns} columns", rows=f"{len(frame):,}", columns=f"{len(frame.columns):,}")
        if len(frame) > len(shown):
            text += "  ·  " + t("Showing the first {rows} rows.", rows=f"{len(shown):,}")
        self.summary.setText(text)
        notes = []
        if table.header_row and table.header_row > 1:
            notes.append(t("Rows above the header are left out."))
        notes.append(t("Dates and times arrive as ISO text (2026-11-26); TRUE/FALSE as logical values."))
        from analisi.source_link import _shown
        first = table.header_row or 1
        formulas = [ref for row, _, ref, kind in table.blocked if kind == "formula" and row >= first]
        errors = [ref for row, _, ref, kind in table.blocked if kind == "error" and row >= first]
        if formulas:
            notes.append(t("Cell(s) {cells}: formulas without a stored result stay empty.", cells=_shown(formulas)))
        if errors:
            notes.append(t("Cell(s) {cells}: Excel error values stay empty.", cells=_shown(errors)))
        if table.external:
            notes.append(t("Cell(s) {cells}: formulas linked to other workbooks keep their stored result; the links "
                           "are not updated.", cells=_shown(table.external)))
        self.notes.setText("\n".join(notes))
        self.notes.setVisible(True)

    def _key_choices(self):
        names = [] if self.table is None else [str(name) for name in self.table.frame.columns]
        wanted = self.key.currentData()
        if self.preset_key is not None and self.table is not None:  # The key of a link, by its source.
            sources = header_sources(self.table.header, range(self.table.width))
            wanted = names[sources.index(self.preset_key)] if self.preset_key in sources else None
            self.preset_key = None
        self.key.blockSignals(True)
        self.key.clear()
        self.key.addItem(t("(none)"), None)
        for name in names:
            self.key.addItem(name, name)
        self.key.setCurrentIndex(max(0, self.key.findData(wanted)))
        self.key.blockSignals(False)

    def problem(self):
        """Why Import is off, or None."""
        if self.error is not None:
            return self.error
        if self.table is None:
            return t("Choose a worksheet that holds values.")
        if self.link.isChecked():
            problems = self.table.cell_problems(range(self.table.width))
            key = self.key.currentData()
            if key is not None and (found := key_problem(self.table.frame, key)) is not None:
                problems.append(found)
            if problems:
                return "\n".join(_translate(item) for item in problems)
        return None

    def _sync(self, *_):
        problem = self.problem()
        self.blocked.setText(f"{t('Import is not available:')}\n{problem}" if problem else "")
        self.blocked.setVisible(bool(problem))
        self.import_button.setEnabled(problem is None)

    def accept(self):
        if self.problem() is not None:
            self._sync()
            return
        table, options = self.table, self.options()
        names = [str(name) for name in table.frame.columns]
        positions = list(range(table.width))
        self.sheet = options.sheet
        if self.relink:
            self.names = self.result = names
        else:
            self.result = table.table(positions)
        if self.link.isChecked():
            sources = header_sources(table.header, positions)
            key = self.key.currentData()
            self.link_spec = LinkSpec(self.path, self.size, self.sha256, "", options, sources,
                                      sources[names.index(key)] if key is not None else None, kind=WORKBOOK)
        super().accept()
