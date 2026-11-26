"""File → Update from file… and File → Source link… on Qt: worksheets linked to the CSV or TSV file they came from.

The engine (``analisi.source_link``) reads and compares on the window's worker, with its progress and Cancel; this
module asks where the file is when it moved, shows the preview (rows added, modified, removed, reordered, project
edits kept, conflicts and their decision, what a removal takes away) and applies the plan as one worksheet edit.
Nothing is read automatically and nothing but a local file is ever opened.
"""
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from analisi import source_link as engine
from analisi.i18n import active_language
from analisi.source_link import (ADDED, CONFLICT, DELETED, DELETED_CONFLICT, FILE, LOCAL, MODIFIED, PROJECT,
                                 REMOVED_CONFLICT, UNCHANGED, Message, UpdateCancelled, locate)
from analisi.text_import import DECIMAL_MARKS, DELIMITERS

from . import theme

MAX_ROWS_SHOWN = 1000
FILE_FILTER = "*.csv *.tsv *.txt"

_ITALIAN = {
    "Update from file…": "Aggiorna da file…",
    "Source link…": "Collegamento sorgente…",
    "Update from file": "Aggiorna da file",
    "Source link": "Collegamento sorgente",
    "Read the linked CSV or TSV file again and review the changes before applying them":
        "Rileggi il file CSV o TSV collegato e controlla le modifiche prima di applicarle",
    "Show, change or remove the file this worksheet is linked to":
        "Mostra, cambia o rimuovi il file a cui è collegato questo foglio",
    "This worksheet is not linked to a file.": "Questo foglio non è collegato a un file.",
    "Select a worksheet linked to a file. Import a CSV or TSV file with “Link to the source file”, or use "
    "File → Source link….": "Seleziona un foglio collegato a un file. Importa un file CSV o TSV con «Collega al file "
                            "sorgente», oppure usa File → Collegamento sorgente….",
    "The linked file was not found:\n{path}\n\nLocate it? Trama never takes another file by itself.":
        "Il file collegato non si trova:\n{path}\n\nVuoi individuarlo? Trama non prende mai da solo un altro file.",
    "Locate…": "Individua…", "Locate the linked file": "Individua il file collegato",
    "Choose the source file": "Scegli il file sorgente", "Delimited text": "Testo delimitato",
    "Update cancelled: nothing changed.": "Aggiornamento annullato: nessuna modifica.",
    "Reading {name}…": "Lettura di {name}…",
    "{name} could not be read. Nothing changed. {error}": "Impossibile leggere {name}. Nessuna modifica. {error}",
    "Updated from {name}: {summary}.": "Aggiornato da {name}: {summary}.",
    "Nothing to change: the worksheet already matches {name}.":
        "Nessuna modifica: il foglio corrisponde già a {name}.",
    "Unlinked from {name}: the cells and the results stay.": "Scollegato da {name}: celle e risultati restano.",
    "{count} rows in the file": "{count} righe nel file", "{count} added": "{count} aggiunte",
    "{count} modified": "{count} modificate", "{count} removed": "{count} rimosse",
    "{count} unchanged": "{count} invariate", "{count} moved": "{count} spostate",
    "Moved": "Spostata", "{state}, moved": "{state}, spostata",
    "{count} project edits kept": "{count} modifiche del progetto tenute",
    "{count} conflicts": "{count} conflitti", "{count} replaced": "{count} sostituite",
    "File": "File", "Folder of the project": "Cartella del progetto",
    "Apply is not available:": "Applica non è disponibile:",
    "Use this file: {path}": "Usa questo file: {path}",
    "The saved path no longer exists. This file has the same place relative to the project; tick to use it.":
        "Il percorso salvato non esiste più. Questo file sta nella stessa posizione rispetto al progetto; spunta per "
        "usarlo.",
    "File chosen by you: {path}": "File scelto da te: {path}",
    "Changed in the project and in the file ({count})": "Cambiate nel progetto e nel file ({count})",
    "Decide for each row, or for all at once and then change single rows. Apply waits until every row is decided.":
        "Decidi riga per riga, oppure per tutte insieme e poi cambia le singole righe. Applica aspetta che ogni riga "
        "sia decisa.",
    "Keep the project for all": "Mantieni il progetto per tutte", "Use the file for all": "Usa il file per tutte",
    "Keep the &project": "Mantieni il &progetto", "Use the &file": "Usa il &file",
    "&Next to decide": "&Successiva da decidere",
    "Differences (worksheet → file)": "Differenze (foglio → file)", "Decision": "Decisione",
    "Changed in both": "Cambiata da entrambe le parti", "To decide": "Da decidere",
    "Project": "Progetto",
    "Keeps the worksheet values": "conserva i valori del foglio", "Takes the file values": "prende i valori del file",
    "The row stays deleted": "la riga resta eliminata", "Restores the row": "ripristina la riga",
    "Stays at the bottom as a project row": "resta in fondo come riga del progetto",
    "Removes the row": "rimuove la riga",
    "same values, other exclusions": "stessi valori, esclusioni diverse",
    "deleted here · file: {values}": "eliminata qui · file: {values}",
    "worksheet: {values} · not in the file": "foglio: {values} · non più nel file",
    "{open} of {count} still to decide": "{open} di {count} ancora da decidere",
    "All {count} decided.": "Tutte le {count} decise.",
    "{state}: to decide": "{state}: da decidere", "{state}: keep the project": "{state}: mantieni il progetto",
    "{state}: use the file": "{state}: usa il file",
    "{count} conflict(s) still need a decision: keep the project or use the file.":
        "{count} conflitti attendono una decisione: mantieni il progetto o usa il file.",
    "The decisions do not match this preview. Update again.":
        "Le decisioni non corrispondono a questa anteprima. Aggiorna di nuovo.",
    "{count} row(s) of the project that are not in the file stay at the bottom of the worksheet.":
        "{count} righe del progetto che non sono nel file restano in fondo al foglio.",
    "Replace all rows of the worksheet": "Sostituisci tutte le righe del foglio",
    "Every row gets a new identity: what refers to the current rows is lost.":
        "Ogni riga prende una nuova identità: quello che si riferisce alle righe attuali va perso.",
    "The removed rows take with them: {items}.": "Le righe rimosse portano via: {items}.",
    "Replacing the rows loses: {items}.": "Sostituire le righe fa perdere: {items}.",
    "{count} excluded cell(s)": "{count} celle escluse", "{count} cell background(s)": "{count} sfondi di cella",
    "{count} row height(s)": "{count} altezze di riga", "{count} row(s) with text styles": "{count} righe con stili "
                                                                                             "di testo",
    "{count} styled or labelled point(s) on graphs": "{count} punti formattati o etichettati nei grafici",
    "{count} value(s) in project columns": "{count} valori nelle colonne del progetto",
    "State": "Stato", "Key": "Chiave", "Row": "Riga",
    "Cells show the worksheet value → the file value; Row is the place in the worksheet → in the file.":
        "Le celle mostrano il valore del foglio → quello del file; Riga è la posizione nel foglio → nel file.",
    "Added": "Aggiunta", "Modified": "Modificata", "Removed": "Rimossa", "Conflict": "Conflitto",
    "Project edit kept": "Modifica del progetto tenuta", "Deleted in the project": "Eliminata nel progetto",
    "Deleted in the project, changed in the file": "Eliminata nel progetto, cambiata nel file",
    "Edited in the project, removed from the file": "Modificata nel progetto, rimossa dal file",
    "No differences.": "Nessuna differenza.",
    "Showing the first {shown} of {count} changes.": "Mostrate le prime {shown} di {count} modifiche.",
    "Apply": "Applica", "Cancel": "Annulla", "Close": "Chiudi",
    "The file changed while this preview was open. Nothing was changed: close and update again.":
        "Il file è cambiato mentre l'anteprima era aperta. Nessuna modifica: chiudi e aggiorna di nuovo.",
    "Worksheet": "Foglio", "State of the file": "Stato del file", "Found": "Trovato",
    "Not found": "Non trovato", "Found next to the project (to confirm): {path}":
        "Trovato accanto al progetto (da confermare): {path}",
    "Relative to the project": "Rispetto al progetto", "Read as": "Letto come",
    "Key column": "Colonna chiave", "Imported columns": "Colonne importate",
    "Project columns": "Colonne del progetto", "Last confirmed version": "Ultima versione confermata",
    "none: rows matched by content": "nessuna: righe abbinate per contenuto", "none": "nessuna",
    "{rows} rows · {size} bytes · SHA-256 {sha}": "{rows} righe · {size} byte · SHA-256 {sha}",
    "UTF-8 · delimiter {delimiter} · decimals {decimal} · header {header} · rows {rows}":
        "UTF-8 · separatore {delimiter} · decimali {decimal} · intestazione {header} · righe {rows}",
    "yes": "sì", "no": "no", "{first}–all": "{first}–tutte", "{first}–{last}": "{first}–{last}",
    ", every {step}": ", ogni {step}", "missing code {code}": "codice mancante {code}",
    "trailing * excludes": "* finale esclude",
    "The worksheet keeps its last confirmed copy, so the project works offline. Update from file… reads the file "
    "again only when you ask and shows the changes first.":
        "Il foglio conserva l'ultima copia confermata, quindi il progetto funziona anche senza il file. Aggiorna "
        "da file… rilegge il file solo quando lo chiedi e mostra prima le modifiche.",
    "This worksheet is not linked to a file. Link to a file… reads a CSV or TSV file into it: rows are matched by a "
    "key column, otherwise by content, and every change is shown before it is applied.":
        "Questo foglio non è collegato a un file. Collega a un file… legge un file CSV o TSV nel foglio: le righe "
        "sono abbinate con una colonna chiave, altrimenti per contenuto, e ogni modifica è mostrata prima di "
        "applicarla.",
    "Change source…": "Cambia sorgente…", "Link to a file…": "Collega a un file…", "Unlink": "Scollega",
    "Unlink “{title}” from {name}? The cells and the results stay as they are; Undo links it again.":
        "Scollegare «{title}» da {name}? Celle e risultati restano come sono; Annulla lo ricollega.",
    "Comma": "Virgola", "Semicolon": "Punto e virgola", "Tab": "Tabulazione", "Automatic": "Automatico",
    "Dot": "Punto",
    # Engine messages (analisi.source_link).
    "The linked file was not found: {path}": "Il file collegato non si trova: {path}",
    "Choose a file on this computer or on a network folder.": "Scegli un file su questo computer o in una cartella "
                                                              "di rete.",
    "The file changed while it was being read. Try again when it is complete.":
        "Il file è cambiato durante la lettura. Riprova quando è completo.",
    "The key column {name} is empty in row(s) {rows}.": "La colonna chiave {name} è vuota nelle righe {rows}.",
    "The key column {name} repeats {keys}.": "La colonna chiave {name} ripete {keys}.",
    "The key {key} is in more than one row of the worksheet (rows {rows}).":
        "La chiave {key} è in più righe del foglio (righe {rows}).",
    "The file has only {count} columns: column {position} is missing.":
        "Il file ha solo {count} colonne: manca la colonna {position}.",
    "The file no longer has the column {name}.": "Il file non ha più la colonna {name}.",
    "The file has the column {name} more than once.": "Il file ha la colonna {name} più di una volta.",
    "The imported column {name} is no longer in the worksheet.": "La colonna importata {name} non è più nel foglio.",
    "The worksheet column {name} is calculated: it cannot receive the file.":
        "La colonna {name} del foglio è calcolata: non può ricevere il file.",
    "The file has columns that are not linked: {names}. Change source… reads them.":
        "Il file ha colonne non collegate: {names}. Cambia sorgente… le legge.",
    "The column {name} now holds text in the file (row {row}: {value}).":
        "La colonna {name} ora contiene testo nel file (riga {row}: {value}).",
    "The column {name} holds {local} values in the worksheet and {incoming} values in the file.":
        "La colonna {name} contiene valori {local} nel foglio e {incoming} nel file.",
    "numeric": "numerici", "text": "di testo", "logical": "logici",
    "The rows take the order of the file.": "Le righe prendono l'ordine del file.",
    "{count} row(s) deleted in the project stay deleted.": "{count} righe eliminate nel progetto restano eliminate.",
    "New columns from the file: {names}.": "Colonne nuove dal file: {names}.",
    "These columns are no longer read from the file and stay as project columns: {names}.":
        "Queste colonne non sono più lette dal file e restano come colonne del progetto: {names}.",
    "Without a key column the rows of the file cannot be matched one by one with the worksheet (rows were changed "
    "or removed in the file). Choose a key with Change source…, or replace all rows.":
        "Senza una colonna chiave le righe del file non si possono abbinare una per una con il foglio (nel file "
        "sono state cambiate o rimosse righe). Scegli una chiave con Cambia sorgente…, oppure sostituisci tutte le "
        "righe.",
    "The worksheet changed after the file was read. Update again.":
        "Il foglio è cambiato dopo la lettura del file. Aggiorna di nuovo.",
    "The imported columns do not match the file.": "Le colonne importate non corrispondono al file.",
}
_PRIORITY = {CONFLICT: 0, DELETED_CONFLICT: 0, MODIFIED: 1, ADDED: 1, LOCAL: 2}
_STATES = {ADDED: "Added", MODIFIED: "Modified", CONFLICT: "Conflict", LOCAL: "Project edit kept",
           DELETED_CONFLICT: "Deleted in the project, changed in the file"}


def t(text, **values):
    if active_language() == "it":
        text = _ITALIAN.get(text, text)
    return text.format(**values) if values else text


def translate(item):
    """An engine message, or the text of an error, in the active language."""
    if isinstance(item, Message):
        values = {name: t(value) if value in ("numeric", "text", "logical") else value
                  for name, value in item.values}
        return t(item.template).format(**values)
    text = str(item)
    if active_language() == "it" and text in _ITALIAN:
        return _ITALIAN[text]
    for template in ("The linked file was not found: {path}",):
        head = template.split("{")[0]
        if text.startswith(head) and active_language() == "it":
            return t(template, path=text[len(head):])
    from .text_import import translate_error
    return translate_error(text)


def _banner(text, name="infoBanner"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def references_text(counts):
    labels = (("excluded", "{count} excluded cell(s)"), ("backgrounds", "{count} cell background(s)"),
              ("heights", "{count} row height(s)"), ("text", "{count} row(s) with text styles"),
              ("points", "{count} styled or labelled point(s) on graphs"),
              ("values", "{count} value(s) in project columns"))
    return ", ".join(t(label, count=f"{counts[name]:,}") for name, label in labels if counts.get(name))


def summary(plan, *, replace_rows=False):
    parts = [t("{count} rows in the file", count=f"{len(plan.source_rows):,}")]
    if replace_rows:
        parts.append(t("{count} replaced", count=f"{len(plan.source_rows):,}"))
        return " · ".join(parts)
    removed = sum(1 for _, kind in plan.removed if kind != REMOVED_CONFLICT)
    for count, label in ((plan.count(ADDED), "{count} added"), (plan.count(MODIFIED), "{count} modified"),
                         (removed, "{count} removed"), (len(plan.moved()), "{count} moved"),
                         (plan.count(UNCHANGED), "{count} unchanged"),
                         (plan.count(LOCAL), "{count} project edits kept"), (plan.conflicts, "{count} conflicts")):
        if count or label in ("{count} added", "{count} modified", "{count} removed"):
            parts.append(t(label, count=f"{count:,}"))
    return " · ".join(parts)


class UpdatePreviewDialog(QDialog):
    """The changes reading the file would make, the decisions they need, and Apply."""

    def __init__(self, parent, project, title, plan):
        super().__init__(parent)
        self.project, self.title, self.plan = project, title, plan
        self.stale = False
        self.setWindowTitle(t("Update from file"))
        outer = theme.scroll_body(self)
        heading = QLabel(f"{t('Update from file')} · {plan.path.name}")
        heading.setObjectName("dialogTitle")
        outer.addWidget(heading)
        path = QLabel(f"{t('File')}: {plan.path}  →  {t('Worksheet')}: {title}")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(path)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.blocked = _banner("")
        outer.addWidget(self.blocked)
        notices = [translate(notice) for notice in plan.notices]
        if plan.located:
            notices.append(t("File chosen by you: {path}", path=plan.path))
        removed = [position for position, kind in plan.removed if kind != REMOVED_CONFLICT]
        if removed and not plan.problems and plan.identity_problem is None:
            if items := references_text(project.source_references(title, removed)):
                notices.append(t("The removed rows take with them: {items}.", items=items))
        self.notices = _banner("\n".join(f"• {text}" for text in notices))
        self.notices.setVisible(bool(notices))
        outer.addWidget(self.notices)

        self.use_file = None
        if plan.found_elsewhere:
            self.use_file = QCheckBox(t("Use this file: {path}", path=plan.path))
            self.use_file.setToolTip(t("The saved path no longer exists. This file has the same place relative to "
                                       "the project; tick to use it."))
            outer.addWidget(self.use_file)
            self.use_file.toggled.connect(self._sync)

        self.conflicts = None
        if plan.conflict_items and not plan.problems:
            self.conflicts = ConflictPanel(self, plan)
            self.conflicts.changed.connect(self._decided)
            outer.addWidget(self.conflicts, 1)

        self.replace = None
        if plan.identity_problem is not None and not plan.problems:
            self.replace = QCheckBox(t("Replace all rows of the worksheet"))
            outer.addWidget(self.replace)
            lost = references_text(project.source_references(title, range(len(plan.raw))))
            detail = t("Every row gets a new identity: what refers to the current rows is lost.")
            if lost:
                detail += " " + t("Replacing the rows loses: {items}.", items=lost)
            self.replace_note = QLabel(detail)
            self.replace_note.setWordWrap(True)
            outer.addWidget(self.replace_note)
            self.replace.toggled.connect(self._sync)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setTabKeyNavigation(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(110)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(160)
        outer.addWidget(self.table, 1)
        self.shown = QLabel()
        outer.addWidget(self.shown)
        self._fill()
        if plan.frame is None:  # Nothing to compare: the problems only, without empty space between them.
            outer.addStretch(1)

        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton(t("Apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setDefault(True)
        buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)
        for widget in self.findChildren(QWidget):  # Tabbing past Cancel must not leave Enter on Cancel.
            if widget.parent() is not buttons and widget.focusPolicy() != Qt.FocusPolicy.NoFocus:
                widget.installEventFilter(self)
        self._sync()
        theme.fit_dialog(self, *((980, 660) if plan.frame is not None else (760, 380)))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            self.apply_button.setDefault(True)  # Enter is Apply again once the focus is back in the preview.
        return super().eventFilter(watched, event)

    # -- decisions -----------------------------------------------------------------------------------------------
    def decisions(self):
        """``{conflict identity: PROJECT | FILE}`` chosen so far (open conflicts are left out)."""
        return {} if self.conflicts is None else dict(self.conflicts.decisions)

    def _decided(self, identities):
        self._label_conflicts(identities)
        self._sync()

    def replace_rows(self):
        return self.replace is not None and self.replace.isChecked()

    def problem(self):
        """Why Apply is off, or None."""
        if self.stale:
            return t("The file changed while this preview was open. Nothing was changed: close and update again.")
        if self.plan.problems:
            return "\n".join(f"• {translate(problem)}" for problem in self.plan.problems)
        if (problem := engine.can_apply(self.plan, decisions=self.decisions(), replace_rows=self.replace_rows())):
            return f"• {translate(problem)}"
        if self.use_file is not None and not self.use_file.isChecked():
            return "• " + t("The saved path no longer exists. This file has the same place relative to the "
                            "project; tick to use it.")
        return None

    def _sync(self, *_):
        problem = self.problem()
        self.blocked.setText(f"{t('Apply is not available:')}\n{problem}" if problem else "")
        self.blocked.setVisible(bool(problem))
        self.apply_button.setEnabled(problem is None)
        self.summary.setText(summary(self.plan, replace_rows=self.replace_rows()))
        self.summary.setVisible(self.plan.frame is not None)  # Without a reading there is nothing to count.

    def accept(self):
        if self.problem() is not None:
            return
        if not engine.same_file(self.plan.path, self.plan.stamp, self.plan.sha256):  # Nothing is applied from a file that is no longer the one shown.
            self.stale = True
            self._sync()
            return
        super().accept()

    # -- the table of changes -------------------------------------------------------------------------------------
    def _entries(self):
        """The rows that change, decisions first (conflicts), then changed values, project edits and moves, so a
        long reorder never hides a modified row past the rows drawn."""
        plan = self.plan
        moved = plan.moved()
        entries = []
        for row, state in enumerate(plan.states.tolist()):
            if state == DELETED or (state == UNCHANGED and row not in moved):
                continue
            entries.append((_PRIORITY.get(state, 3), (state, row in moved), row, int(plan.match[row])))
        for position, kind in plan.removed:
            entries.append((0 if kind == REMOVED_CONFLICT else 1, ("removed", kind), None, position))
        entries.sort(key=lambda entry: entry[0])  # Stable: file order inside each group.
        return [entry[1:] for entry in entries]

    def _fill(self):
        plan = self.plan
        if plan.frame is None:
            self.table.setVisible(False)
            self.shown.setVisible(False)
            return
        names = [name for name in plan.names if name is not None]
        numeric = [pd.api.types.is_numeric_dtype(plan.frame[name]) and not pd.api.types.is_bool_dtype(plan.frame[name])
                   for name in names]
        self.table.setColumnCount(2 + len(names))
        self.table.setHorizontalHeaderLabels([t("State"), t("Row"), *names])
        for column, right in enumerate([False, True, *numeric]):
            header = self.table.horizontalHeaderItem(column)
            header.setTextAlignment((Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft)
                                    | Qt.AlignmentFlag.AlignVCenter)
        entries = self._entries()
        shown = entries[:MAX_ROWS_SHOWN]
        self.table.setRowCount(len(shown))
        raw = plan.raw
        by_row = {item.row: item for item in plan.conflict_items if item.row >= 0}
        by_position = {item.position: item for item in plan.conflict_items if item.kind == REMOVED_CONFLICT}
        self._conflict_lines = {}
        for line, (state, row, position) in enumerate(shown):
            if state[0] == "removed":
                label = t("Edited in the project, removed from the file" if state[1] == REMOVED_CONFLICT
                          else "Removed")
            elif state[0] == UNCHANGED:
                label = t("Moved")
            else:
                label = t(_STATES[state[0]])
                if state[1]:
                    label = t("{state}, moved", state=label)
            before = engine.values_text(raw, position, names) if position is not None and position >= 0 else None
            after = engine.values_text(plan.frame, row, names) if row is not None else None
            if row is None:  # Removed: its place in the worksheet.
                place = f"{position + 1:,}"
            elif position is None or position < 0 or position == row:
                place = f"{row + 1:,}"
            else:
                place = f"{position + 1:,} → {row + 1:,}"
            cells = [label, place]
            for index in range(len(names)):
                old = before[index] if before is not None else None
                new = after[index] if after is not None else None
                if old is None:
                    cells.append(new)
                elif new is None or old == new:
                    cells.append(old)
                else:
                    cells.append(f"{old} → {new}")
            conflict = by_position.get(position) if row is None else by_row.get(row)
            if conflict is not None:
                self._conflict_lines[conflict.identity] = (line, label)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 1 or (column >= 2 and numeric[column - 2]):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(line, column, item)
        if not entries:
            self.shown.setText(t("No differences."))
        else:
            text = t("Cells show the worksheet value → the file value; Row is the place in the worksheet → in the "
                     "file.")
            if len(entries) > len(shown):
                text += " " + t("Showing the first {shown} of {count} changes.", shown=f"{len(shown):,}",
                                count=f"{len(entries):,}")
            self.shown.setText(text)
        self.shown.setWordWrap(True)
        self.shown.setVisible(True)
        self._label_conflicts()
        self._fit_state_column()

    def _label_conflicts(self, identities=None):
        """The State of a conflict in the table of changes says its decision, or that it is still open."""
        decisions, lines = self.decisions(), getattr(self, "_conflict_lines", {})
        for identity in lines if identities is None else identities:
            if identity not in lines:  # Past the rows drawn: the conflict list shows it.
                continue
            line, label = lines[identity]
            self.table.item(line, 0).setText(self._state_text(label, decisions.get(identity)))

    @staticmethod
    def _state_text(label, decided):
        return t("{state}: to decide", state=label) if decided is None else t(
            "{state}: keep the project" if decided == PROJECT else "{state}: use the file", state=label)

    def _fit_state_column(self):
        """Wide enough for every state and every decision it can take, so a decision never cuts the text."""
        metrics = self.table.fontMetrics()
        texts = {self.table.item(line, 0).text() for line in range(self.table.rowCount())}
        texts |= {self._state_text(label, decided) for _, label in getattr(self, "_conflict_lines", {}).values()
                  for decided in (PROJECT, FILE)}
        width = max((metrics.horizontalAdvance(text) for text in texts), default=0) + 24
        self.table.setColumnWidth(0, max(110, min(width, 380)))

_KINDS = {CONFLICT: "Changed in both", DELETED_CONFLICT: "Deleted in the project, changed in the file",
          REMOVED_CONFLICT: "Edited in the project, removed from the file"}
# What each decision does to the row, by kind of conflict: the panel says it before Apply.
_EFFECTS = {(CONFLICT, PROJECT): "Keeps the worksheet values", (CONFLICT, FILE): "Takes the file values",
            (DELETED_CONFLICT, PROJECT): "The row stays deleted", (DELETED_CONFLICT, FILE): "Restores the row",
            (REMOVED_CONFLICT, PROJECT): "Stays at the bottom as a project row",
            (REMOVED_CONFLICT, FILE): "Removes the row"}


class ConflictPanel(QGroupBox):
    """Every conflict of a preview, one line each, with its key, what happened on each side and its decision.

    Decide for the selected lines (Keep the project / Use the file) or for all at once; a decision for all only
    fills the lines, which stay editable one by one. Nothing is decided by default and Next open finds the lines
    still to decide. Decisions belong to the conflict identity of this preview, not to a line of the view."""

    changed = Signal(list)  # The identities just decided.

    def __init__(self, parent, plan):
        super().__init__(parent)
        self.plan, self.items, self.decisions = plan, list(plan.conflict_items), {}
        self.setTitle(t("Changed in the project and in the file ({count})", count=f"{len(self.items):,}"))
        box = QVBoxLayout(self)
        note = QLabel(t("Decide for each row, or for all at once and then change single rows. Apply waits until "
                        "every row is decided."))
        note.setWordWrap(True)
        box.addWidget(note)
        bar = QHBoxLayout()
        self.all_project = self._button("Keep the project for all", lambda: self.decide_all(PROJECT), bar)
        self.all_file = self._button("Use the file for all", lambda: self.decide_all(FILE), bar)
        bar.addStretch(1)
        self.keep = self._button("Keep the &project", lambda: self.decide_selected(PROJECT), bar)
        self.take = self._button("Use the &file", lambda: self.decide_selected(FILE), bar)
        self.next_open = self._button("&Next to decide", self.select_next_open, bar)
        box.addLayout(bar)
        self.state = QLabel()
        box.addWidget(self.state)
        self.table = QTableWidget(len(self.items), 4)
        self.table.setObjectName("sourceConflicts")
        self.table.setHorizontalHeaderLabels([t("Key") if plan.key_name is not None else t("Row"), t("Conflict"),
                                              t("Differences (worksheet → file)"), t("Decision")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setTabKeyNavigation(False)  # Tab leaves the list; the arrows move inside it.
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((80, 300, 220)):  # The kinds of conflict read whole at 1024×768.
            self.table.setColumnWidth(column, width)
        self.table.setMinimumHeight(120)
        self.table.itemSelectionChanged.connect(self._selection)
        box.addWidget(self.table, 1)
        names = [name for name in plan.names if name is not None]
        for line, item in enumerate(self.items):
            cells = [self._key(item, names), t(_KINDS[item.kind]), self._differences(item, names), ""]
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self.table.setItem(line, column, cell)
            self._show(line)
        self._selection()
        self._count()

    def _button(self, text, handler, bar):
        button = QPushButton(t(text))
        button.setAutoDefault(False)  # Enter stays on Apply.
        button.clicked.connect(handler)
        bar.addWidget(button)
        return button

    def _key(self, item, names):
        plan = self.plan
        if plan.key_name is None:
            return str((item.row if item.row >= 0 else item.position) + 1)
        frame, row = (plan.frame, item.row) if item.row >= 0 else (plan.raw, item.position)
        return engine.values_text(frame, row, [plan.key_name])[0]

    def _differences(self, item, names):
        plan = self.plan
        others = [name for name in names if name != plan.key_name] or names
        if item.kind == CONFLICT:
            before = engine.values_text(plan.raw, item.position, others)
            after = engine.values_text(plan.frame, item.row, others)
            return " · ".join(f"{name}: {old} → {new}" for name, old, new in zip(others, before, after)
                              if old != new) or t("same values, other exclusions")
        if item.kind == DELETED_CONFLICT:
            values = engine.values_text(plan.frame, item.row, others)
            return t("deleted here · file: {values}", values=" · ".join(
                f"{name} {value}" for name, value in zip(others, values)))
        values = engine.values_text(plan.raw, item.position, others)
        return t("worksheet: {values} · not in the file", values=" · ".join(
            f"{name} {value}" for name, value in zip(others, values)))

    def _show(self, line):
        item = self.items[line]
        decided = self.decisions.get(item.identity)
        cell = self.table.item(line, 3)
        if decided is None:
            cell.setText(t("To decide"))
        else:
            side = t("Project") if decided == PROJECT else t("File")
            cell.setText(f"{side}: {t(_EFFECTS[item.kind, decided])}")
        font = cell.font()
        font.setBold(decided is None)  # The lines still open stand out without a colour of their own.
        cell.setFont(font)
        cell.setToolTip(cell.text())

    def _count(self):
        open_ = sum(1 for item in self.items if item.identity not in self.decisions)
        self.state.setText(t("{open} of {count} still to decide", open=f"{open_:,}", count=f"{len(self.items):,}")
                           if open_ else t("All {count} decided.", count=f"{len(self.items):,}"))
        self.next_open.setEnabled(bool(open_))

    def _selection(self):
        chosen = bool(self.table.selectionModel().selectedRows())
        self.keep.setEnabled(chosen)
        self.take.setEnabled(chosen)

    def selected_lines(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def decide(self, lines, value):
        lines = list(lines)
        for line in lines:
            self.decisions[self.items[line].identity] = value
            self._show(line)
        self._count()
        self.changed.emit([self.items[line].identity for line in lines])

    def decide_selected(self, value):
        self.decide(self.selected_lines(), value)

    def decide_all(self, value):
        self.decide(range(len(self.items)), value)

    def select_next_open(self):
        """Select the next line still to decide after the current one (wrapping), and show it."""
        lines = [line for line, item in enumerate(self.items) if item.identity not in self.decisions]
        if not lines:
            return
        current = self.table.currentRow()
        line = next((line for line in lines if line > current), lines[0])
        self.table.clearSelection()
        self.table.selectRow(line)
        self.table.setCurrentCell(line, 0)
        self.table.scrollToItem(self.table.item(line, 0))
        self.table.setFocus()


def _options_text(link):
    options = link.options
    delimiter = next((name for name, char in DELIMITERS.items() if char == link.delimiter), link.delimiter)
    rows = (t("{first}–all", first=options.first_row) if options.last_row is None
            else t("{first}–{last}", first=options.first_row, last=options.last_row))
    if options.skip_rows:
        rows += t(", every {step}", step=options.skip_rows + 1)
    text = t("UTF-8 · delimiter {delimiter} · decimals {decimal} · header {header} · rows {rows}",
             delimiter=t(delimiter), decimal=t(options.decimal) if options.decimal in DECIMAL_MARKS else
             options.decimal, header=t("yes" if options.header else "no"), rows=rows)
    if options.missing_code:
        text += " · " + t("missing code {code}", code=options.missing_code)
    if options.mark_excluded:
        text += " · " + t("trailing * excludes")
    return text


class SourceLinkDialog(QDialog):
    """File → Source link…: where the file is, how it is read, the key and the columns; Update, Change, Unlink."""

    def __init__(self, parent, project, title):
        super().__init__(parent)
        self.action = None
        self.setWindowTitle(t("Source link"))
        dataset = project.tables[title]
        link = dataset.source_link
        outer = theme.scroll_body(self)
        heading = QLabel(f"{t('Source link')} · {title}")
        heading.setObjectName("dialogTitle")
        outer.addWidget(heading)
        buttons = QDialogButtonBox()
        if link is None:
            outer.addWidget(_banner(t("This worksheet is not linked to a file. Link to a file… reads a CSV or TSV "
                                      "file into it: rows are matched by a key column, otherwise by content, and "
                                      "every change is shown before it is applied.")))
            self._button(buttons, "Link to a file…", "change")
        else:
            outer.addWidget(_banner(t("The worksheet keeps its last confirmed copy, so the project works offline. "
                                      "Update from file… reads the file again only when you ask and shows the "
                                      "changes first.")))
            form = QFormLayout()
            outer.addLayout(form)
            found, elsewhere = locate(link, project.path)
            state = (t("Found") if found is not None and not elsewhere else
                     t("Found next to the project (to confirm): {path}", path=found) if found is not None else
                     t("Not found"))
            imported = link.imported_names(dataset.raw)
            key = link.key_column(dataset.raw)
            rows = [(t("File"), link.path), (t("State of the file"), state)]
            if link.relative:
                rows.append((t("Relative to the project"), link.relative))
            rows += [(t("Read as"), _options_text(link)),
                     (t("Key column"), key if key is not None else t("none: rows matched by content")),
                     (t("Imported columns"), ", ".join(imported) or t("none")),
                     (t("Project columns"), ", ".join(name for name in dataset.columns if name not in imported)
                      or t("none")),
                     (t("Last confirmed version"), t("{rows} rows · {size} bytes · SHA-256 {sha}",
                                                     rows=f"{link.rows:,}", size=f"{link.size:,}",
                                                     sha=f"{link.sha256[:16]}…"))]
            for label, value in rows:
                text = QLabel(str(value))
                text.setWordWrap(True)
                text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow(label, text)
            self._button(buttons, "Update from file…", "update")
            self._button(buttons, "Change source…", "change")
            self._button(buttons, "Unlink", "unlink")
        outer.addStretch(1)
        close = buttons.addButton(t("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)
        theme.fit_dialog(self, 760, max(300, min(520, self.sizeHint().height())))

    def _button(self, buttons, text, action):
        button = QPushButton(t(text))
        button.setAutoDefault(False)
        button.setObjectName(f"sourceLink_{action}")
        buttons.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        button.clicked.connect(lambda: self._choose(action))
        return button

    def _choose(self, action):
        self.action = action
        self.accept()


# == commands ==========================================================================================================
def _active(window):
    title = window._active_table()
    if title is None or title not in window.project.tables:
        return None
    return title


def update_from_file(window):
    """File → Update from file…"""
    if window.busy():
        return
    title = _active(window)
    link = window.project.tables[title].source_link if title is not None else None
    if link is None:
        window.status(t("This worksheet is not linked to a file."))
        return
    path, elsewhere = locate(link, window.project.path)
    located = False
    if path is None:
        box = QMessageBox(QMessageBox.Icon.Question, t("Update from file"),
                          t("The linked file was not found:\n{path}\n\nLocate it? Trama never takes another file by "
                            "itself.", path=link.path), parent=window)
        find = box.addButton(t("Locate…"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(find)
        box.exec()
        if box.clickedButton() is not find:
            window.status(t("Update cancelled: nothing changed."))
            return
        chosen = choose_file(window, t("Locate the linked file"), Path(link.path).parent)
        if chosen is None:
            window.status(t("Update cancelled: nothing changed."))
            return
        path, elsewhere, located = chosen, False, True
    start_plan(window, title, link, path, found_elsewhere=elsewhere, located=located)


def choose_file(window, caption, folder=None):
    start = str(folder) if folder is not None and Path(folder).is_dir() else ""
    chosen, _ = QFileDialog.getOpenFileName(window, caption, start, f"{t('Delimited text')} ({FILE_FILTER})")
    return Path(chosen) if chosen else None


def start_plan(window, title, link, path, *, relink=None, found_elsewhere=False, located=False):
    """Read and compare on the worker; then the preview. Nothing changes until Apply."""
    from .project import CalculationControl
    project = window.project
    try:
        raw, excluded = project.source_sheet(title)
        path = engine.local_path(path)
    except ValueError as error:
        window.error(translate(error))
        return
    control = CalculationControl()

    def job():
        return engine.plan_update(link, raw, excluded, path, relink=relink, found_elsewhere=found_elsewhere,
                                  located=located, cancel=control.cancel.is_set, progress=control.report)

    def done(future, cancelled):
        if cancelled or window.project is not project:
            window.status(t("Update cancelled: nothing changed."))
            return
        try:
            plan = future.result()
        except UpdateCancelled:
            window.status(t("Update cancelled: nothing changed."))
            return
        except (ValueError, OSError) as error:  # Unreadable file: nothing changed; say why.
            text = t("{name} could not be read. Nothing changed. {error}", name=path.name, error=translate(error))
            window.status(text)
            window.error(text)
            return
        preview(window, project, title, plan)

    window._start(window.worker.submit(job), control, done, t("Reading {name}…", name=path.name))


def preview(window, project, title, plan):
    dialog = UpdatePreviewDialog(window, project, title, plan)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    decisions, replace_rows = dialog.decisions(), dialog.replace_rows()
    dialog.deleteLater()
    if not accepted or window.project is not project:
        window.status(t("Update cancelled: nothing changed."))
        return
    outcome = {}

    def change():
        try:
            outcome["affected"] = project.update_from_source(title, plan, decisions=decisions,
                                                             replace_rows=replace_rows)
        except ValueError as error:
            raise ValueError(translate(error)) from error
        return outcome["affected"]

    window._apply_edit(title, change)
    if "affected" not in outcome:
        return  # The edit was refused and the window said why.
    if outcome["affected"] is None:
        window.status(t("Nothing to change: the worksheet already matches {name}.", name=plan.path.name))
        window.update_actions()
        return
    text = t("Updated from {name}: {summary}.", name=plan.path.name, summary=summary(plan, replace_rows=replace_rows))
    job = window.job
    if job is None:
        window.status(text)
    else:  # The analyses that read the worksheet recalculate once: say what changed when they are done.
        done = job.done

        def finished(future, cancelled):
            done(future, cancelled)
            if not cancelled:
                window.status(text)

        job.done = finished
    window.update_actions()


def change_source(window, title=None):
    """Change source… (or Link to a file… for a worksheet without a link): read a file chosen now into the
    worksheet with import options chosen now, and review the changes."""
    if window.busy():
        return
    title = title or _active(window)
    if title is None:
        return
    link = window.project.tables[title].source_link
    path = choose_file(window, t("Choose the source file"), Path(link.path).parent if link is not None else None)
    if path is None:
        return
    from .text_import import TextImportDialog
    try:
        dialog = TextImportDialog(window, path, preset=link, relink=True)
    except ValueError as error:
        window.error(t("{name} could not be read. Nothing changed. {error}", name=path.name, error=translate(error)))
        return
    accepted = dialog.exec() == QDialog.DialogCode.Accepted and dialog.link_spec is not None
    spec, names = dialog.link_spec, dialog.names
    dialog.deleteLater()
    if not accepted:
        window.status(t("Update cancelled: nothing changed."))
        return
    relink = engine.Relink(spec.delimiter, spec.options, spec.sources, tuple(names), spec.key)
    start_plan(window, title, link, path, relink=relink, located=True)


def manage(window):
    """File → Source link…"""
    if window.busy():
        return
    title = _active(window)
    if title is None:
        return
    dialog = SourceLinkDialog(window, window.project, title)
    dialog.exec()
    action = dialog.action
    dialog.deleteLater()
    if action == "update":
        update_from_file(window)
    elif action == "change":
        change_source(window, title)
    elif action == "unlink":
        unlink(window, title)


def unlink(window, title, *, confirm=True):
    link = window.project.tables[title].source_link
    if link is None:
        return
    if confirm:
        answer = QMessageBox.question(window, t("Source link"),
                                      t("Unlink “{title}” from {name}? The cells and the results stay as they are; "
                                        "Undo links it again.", title=title, name=link.name))
        if answer != QMessageBox.StandardButton.Yes:
            return
    try:
        window.project.unlink_source(title)
    except ValueError as error:
        window.error(translate(error))
        return
    window.update_title()
    window.update_actions()
    window.status(t("Unlinked from {name}: the cells and the results stay.", name=link.name))
