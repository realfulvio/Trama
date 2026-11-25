"""Import text data on Qt: delimiter, decimals, header, row and column ranges, missing code and a live preview.

Same choices as the classic dialog (``analisi.text_import_dialog`` needs Tk); ``analisi.text_import`` parses
and filters the file. *Link to the source file* keeps these choices with the worksheet, with an optional key
column, so that File → Update from file… can read the file again (``analisi.source_link``).
"""
import hashlib
import re

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout)

from analisi.data import _headers
from analisi.i18n import active_language, ui
from analisi.source_link import LinkSpec, column_sources, key_problem
from analisi.text_import import DECIMAL_MARKS, DELIMITERS, ImportOptions, TextImport, read_text_bytes

from . import theme

PREVIEW = (12, 5)  # Rows and columns shown, as in the classic dialog.
_ITALIAN = {
    "Import text data": "Importa dati di testo", "Source": "Origine", "Delimiter": "Separatore",
    "Decimals": "Decimali", "First record is a header": "Il primo record è l'intestazione", "Rows": "Righe",
    "Columns": "Colonne", "First": "Prima", "Last (blank = all)": "Ultima (vuoto = tutte)",
    "Skip after each": "Salta dopo ciascuna", "Values": "Valori", "Missing code": "Codice mancante",
    "Trailing * marks exclusion": "Un * finale esclude il valore", "Filtered preview": "Anteprima filtrata",
    "Import": "Importa", "Cancel": "Annulla", "Automatic": "Automatico", "Comma": "Virgola",
    "Semicolon": "Punto e virgola", "Tab": "Tabulazione", "Dot": "Punto",
    "{rows} rows × {columns} columns": "{rows} righe × {columns} colonne",
    "Showing {rows} × {columns}": "Mostrate {rows} × {columns}",
    "Enter a whole number for {field}.": "Inserisci un numero intero per {field}.",
    "first row": "prima riga", "last row": "ultima riga", "skip rows": "righe da saltare",
    "first column": "prima colonna", "last column": "ultima colonna", "skip columns": "colonne da saltare",
    "The number of rows to skip must be zero or more.": "Le righe da saltare devono essere zero o più.",
    "The number of columns to skip must be zero or more.": "Le colonne da saltare devono essere zero o più.",
    "Choose a delimiter from the list.": "Scegli un separatore dall'elenco.",
    "Choose a decimal separator from the list.": "Scegli un separatore decimale dall'elenco.",
    "Could not read the delimited file. Check the quoted fields.":
        "Impossibile leggere il file delimitato. Controlla i campi tra virgolette.",
    "The file contains no delimited data.": "Il file non contiene dati delimitati.",
    "The text file exceeds the worksheet size limit.": "Il file di testo supera il limite del foglio.",
    "Link": "Collegamento", "Link to the source file": "Collega al file sorgente",
    "Key column": "Colonna chiave", "(none)": "(nessuna)",
    "The worksheet keeps the imported copy. File → Update from file… reads this file again with these choices "
    "and shows the changes before applying them. A key column keeps each row's identity (styles, exclusions, "
    "labelled points) when rows move or change.":
        "Il foglio conserva la copia importata. File → Aggiorna da file… rilegge questo file con queste scelte e "
        "mostra le modifiche prima di applicarle. Una colonna chiave mantiene l'identità di ogni riga (stili, "
        "esclusioni, punti etichettati) quando le righe si spostano o cambiano.",
    "Read into the worksheet": "Leggi nel foglio",
}
_RANGE = re.compile(r"Choose a (row|column) range between 1 and (\d+)\.")
_COLUMNS = re.compile(r"Choose no more than (\d+) columns\.")


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


def translate_error(message):
    """Messages of ``analisi.text_import`` in the active language."""
    if active_language() != "it":
        return message
    if match := _RANGE.fullmatch(message):
        axis = "un intervallo di righe" if match[1] == "row" else "un intervallo di colonne"
        return f"Scegli {axis} tra 1 e {match[2]}."
    if match := _COLUMNS.fullmatch(message):
        return f"Scegli al massimo {match[1]} colonne."
    return t(message)


class TextImportDialog(QDialog):
    """``result`` is the imported frame after Import, ``link_spec`` the link to create (or None). Reading the file
    may raise ValueError.

    ``preset`` (an ``analisi.source_link.SourceLink``) starts from the choices of a link; ``relink`` is Change
    source…: the link is kept, and the frame is not built here (the worker reads the file again)."""

    def __init__(self, parent, path, *, preset=None, relink=False):
        super().__init__(parent)
        self.setWindowTitle(t("Import text data"))
        self.path, self.result, self.link_spec, self.names, self.relink = path, None, None, [], relink
        data, self.content = read_text_bytes(path)
        self.size, self.sha256 = len(data), hashlib.sha256(data).hexdigest()
        self.source = self.parsed_delimiter = None
        self.key_names = []
        outer = theme.scroll_body(self)  # Scrolls on short screens (150%).
        title = QLabel(path.name)
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        panes = QHBoxLayout()
        outer.addLayout(panes, 1)
        settings = QVBoxLayout()
        panes.addLayout(settings)

        group = QGroupBox(t("Source"))
        form = QFormLayout(group)
        self.delimiter = QComboBox()
        for name in DELIMITERS:
            self.delimiter.addItem(t(name), name)
        form.addRow(t("Delimiter"), self.delimiter)
        self.decimal = QComboBox()
        for name in DECIMAL_MARKS:
            self.decimal.addItem(t(name), name)
        form.addRow(t("Decimals"), self.decimal)
        self.header = QCheckBox(t("First record is a header"))
        self.header.setChecked(True)
        form.addRow(self.header)
        settings.addWidget(group)

        self.bounds = {}
        for axis in ("rows", "columns"):
            group = QGroupBox(t(axis.capitalize()))
            form = QFormLayout(group)
            for field, label, default in ((f"first_{axis[:-1]}", "First", "1"),
                                          (f"last_{axis[:-1]}", "Last (blank = all)", ""),
                                          (f"skip_{axis}", "Skip after each", "0")):
                entry = self.bounds[field] = QLineEdit(default)
                entry.setMaximumWidth(90)
                form.addRow(t(label), entry)
            settings.addWidget(group)

        group = QGroupBox(t("Values"))
        form = QFormLayout(group)
        self.missing = QLineEdit()
        self.missing.setMaximumWidth(90)
        form.addRow(t("Missing code"), self.missing)
        self.mark_excluded = QCheckBox(t("Trailing * marks exclusion"))
        form.addRow(self.mark_excluded)
        settings.addWidget(group)

        group = QGroupBox(t("Link"))
        form = QFormLayout(group)
        self.link = QCheckBox(t("Link to the source file"))
        self.link.setObjectName("linkSource")
        form.addRow(self.link)
        self.key = QComboBox()
        self.key.setObjectName("linkKey")
        self.key.addItem(t("(none)"), None)
        form.addRow(t("Key column"), self.key)
        note = QLabel(t("The worksheet keeps the imported copy. File → Update from file… reads this file again with "
                        "these choices and shows the changes before applying them. A key column keeps each row's "
                        "identity (styles, exclusions, labelled points) when rows move or change."))
        note.setWordWrap(True)
        note.setMaximumWidth(300)
        form.addRow(note)
        self.link.toggled.connect(self.key.setEnabled)
        self.key.setEnabled(False)
        if relink:
            self.link.setChecked(True)
            self.link.setEnabled(False)
        settings.addWidget(group)
        settings.addStretch(1)

        group = QGroupBox(t("Filtered preview"))
        preview = QVBoxLayout(group)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        preview.addWidget(self.summary)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(96)
        preview.addWidget(self.table, 1)
        panes.addWidget(group, 1)

        if preset is not None:
            self._preset(preset)
        buttons = QDialogButtonBox()
        buttons.addButton(t("Read into the worksheet" if relink else "Import"),
                          QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.refresh_preview)
        for signal in (self.delimiter.currentIndexChanged, self.decimal.currentIndexChanged, self.header.toggled,
                       self.mark_excluded.toggled, self.missing.textChanged,
                       *(entry.textChanged for entry in self.bounds.values())):
            signal.connect(self.timer.start)
        self.refresh_preview()
        hint = self.sizeHint()  # Tall enough for every setting; a short screen scrolls (theme.keep_on_screen).
        self.resize(max(820, hint.width()), max(520, hint.height()))

    def _preset(self, link):
        """Start from the choices saved with a link."""
        name = next((name for name, char in DELIMITERS.items() if char == link.delimiter), "Automatic")
        self.delimiter.setCurrentIndex(max(0, self.delimiter.findData(name)))
        self.decimal.setCurrentIndex(max(0, self.decimal.findData(link.options.decimal)))
        self.header.setChecked(link.options.header)
        for field, entry in self.bounds.items():
            value = getattr(link.options, field)
            entry.setText("" if value is None else str(value))
        self.missing.setText(link.options.missing_code)
        self.mark_excluded.setChecked(link.options.mark_excluded)
        self.link.setChecked(True)
        self.preset_key = link.key

    def options(self):
        delimiter = self.delimiter.currentData()
        if delimiter != self.parsed_delimiter:
            self.source = TextImport.parse(self.content, self.path.suffix.lower(), delimiter)
            self.parsed_delimiter = delimiter
        bounds = {}
        for field, entry in self.bounds.items():
            text = entry.text().strip()
            try:
                bounds[field] = None if not text and field.startswith("last_") else int(text)
            except ValueError:
                raise ValueError(t("Enter a whole number for {field}.").format(
                    field=t(field.replace("_", " ")))) from None
        return ImportOptions(header=self.header.isChecked(), decimal=self.decimal.currentData(),
                             missing_code=self.missing.text(), mark_excluded=self.mark_excluded.isChecked(), **bounds)

    def _problem(self, error):
        self.summary.setObjectName("errorBanner")
        self.summary.setText(translate_error(str(error)))
        self.summary.style().polish(self.summary)

    def refresh_preview(self):
        self.timer.stop()
        try:
            options = self.options()
            selection = self.source.plan(options)
            frame = self.source.table(options, limit=PREVIEW)
        except ValueError as error:
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._problem(error)
            return
        self._key_choices(options, selection)
        self.table.clear()
        self.table.setColumnCount(len(frame.columns))
        self.table.setRowCount(len(frame))
        self.table.setHorizontalHeaderLabels([str(name) for name in frame.columns])
        excluded = set(frame.attrs.get("excluded", []))
        for row, values in enumerate(frame.itertuples(index=False, name=None)):
            for column, value in enumerate(values):
                text = "" if pd.isna(value) else ("* " if (row, column) in excluded else "") + str(value)
                self.table.setItem(row, column, QTableWidgetItem(text))
        text = t("{rows} rows × {columns} columns").format(rows=f"{len(selection.rows):,}",
                                                           columns=f"{len(selection.columns):,}")
        if frame.shape != (len(selection.rows), len(selection.columns)):
            text += "  ·  " + t("Showing {rows} × {columns}").format(rows=f"{len(frame):,}",
                                                                      columns=f"{len(frame.columns):,}")
        self.summary.setObjectName("")
        self.summary.setText(text)
        self.summary.style().polish(self.summary)

    def _key_choices(self, options, selection):
        """Every chosen column can be the key (the preview shows only the first few)."""
        header = self.source.records[0] if options.header and self.source.records else ()
        names = _headers([header[col] if col < len(header) and header[col].strip() else f"Column {col + 1}"
                          for col in selection.columns])
        wanted = self.key.currentData()
        preset = getattr(self, "preset_key", None)
        if preset is not None:  # The key of a link, by its source: header text or position.
            sources = column_sources(self.source, options, selection.columns)
            wanted = names[sources.index(preset)] if preset in sources else None
            self.preset_key = None
        if names == self.key_names and wanted == self.key.currentData():
            return
        self.key_names = names
        self.key.blockSignals(True)
        self.key.clear()
        self.key.addItem(t("(none)"), None)
        for name in names:
            self.key.addItem(name, name)
        self.key.setCurrentIndex(max(0, self.key.findData(wanted)))
        self.key.blockSignals(False)

    def accept(self):
        try:
            options = self.options()
            selection = self.source.plan(options)
            self._key_choices(options, selection)
            key = self.key.currentData() if self.link.isChecked() else None
            if self.relink:  # The worker reads the file: only the choices are needed here.
                self.names, self.result = list(self.key_names), list(self.key_names)
            else:
                self.result = self.source_table()
                if (problem := key_problem(self.result, key)) is not None:
                    from .source_link import translate
                    raise ValueError(translate(problem))
            if self.link.isChecked():
                sources = column_sources(self.source, options, selection.columns)
                self.link_spec = LinkSpec(self.path, self.size, self.sha256, self.source.delimiter, options, sources,
                                          sources[self.key_names.index(key)] if key is not None else None)
        except ValueError as error:
            self.result = self.link_spec = None
            self._problem(error)
            return
        super().accept()

    def source_table(self):
        options = self.options()
        return self.source.table(options)
