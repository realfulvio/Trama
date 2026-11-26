"""Reusable analysis templates on Qt: File → Save as analysis template… and New project from template….

The engine (``analisi.analysis_templates``) decides what a template contains, writes and reads it and builds the
new tables; this module shows the confirmation, the mapping assistant and the progress, and installs the new
project in a tab of its own. Reading the template, reading CSV/TSV files and building the project run off the
window thread; no tab exists until the new project is complete.

The texts live here (``t()``) so that this package does not touch the shared string table.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout)

from analisi.analysis_chain import ChainCancelled
from analisi.analysis_templates import (SUFFIX, TemplateError, ignored_columns, instantiate_template,
                                        mapping_problems, plan_template, read_template, same_file, write_template)
from analisi.data import load_tables
from analisi.i18n import active_language

from . import theme
from .strings import qt
from .theme import fit_dialog

LISTED = 40  # Rows of a section shown in the confirmation; the rest is counted.
TEXT_FILTER = "*.csv *.tsv *.txt"

_TEXT = {
    "save_action": ("Save as analysis template…", "Salva come modello…"),
    "save_tip": ("Saves the method of this project (columns, formulas, analyses, graphs and layouts) without its "
                 "observations.", "Salva il metodo di questo progetto (colonne, formule, analisi, grafici e layout) "
                 "senza le osservazioni."),
    "new_action": ("New project from template…", "Nuovo progetto da modello…"),
    "save_template_short": ("Save template", "Salva modello"),
    "new_from_template_short": ("From template", "Da modello"),
    "new_tip": ("Applies an analysis template to new data in a new project tab.",
                "Applica un modello di analisi a nuovi dati in una nuova scheda di progetto."),
    "save_title": ("Save as analysis template", "Salva come modello di analisi"),
    "new_title": ("New project from template", "Nuovo progetto da modello"),
    "file_filter": ("Trama analysis templates (*.tramatpl)", "Modelli di analisi Trama (*.tramatpl)"),
    "default_file": ("Analysis template.tramatpl", "Modello di analisi.tramatpl"),
    "privacy": ("Titles, analysis options, formulas, column names and graph formats may contain text typed by "
                "whoever prepared this project. Check them before sharing the template.",
                "Titoli, opzioni delle analisi, formule, nomi delle colonne e formati dei grafici possono contenere "
                "testo inserito da chi ha preparato il progetto. Controllali prima di condividere il modello."),
    "file_label": ("Template file", "File del modello"),
    "browse": ("Browse…", "Sfoglia…"),
    "save_button": ("Save template", "Salva modello"),
    "cancel": ("Cancel", "Annulla"),
    "counts": ("{tables} data table(s), {columns} expected column(s), {formulas} formula(s), {analyses} analysis(es), "
               "{links} dependency link(s), {layouts} layout(s).",
               "{tables} tabelle dati, {columns} colonne attese, {formulas} formule, {analyses} analisi, "
               "{links} collegamenti di dipendenza, {layouts} layout."),
    "section.tables": ("Tables and expected columns", "Tabelle e colonne attese"),
    "section.formulas": ("Formulas", "Formule"),
    "section.analyses": ("Analyses", "Analisi"),
    "section.layouts": ("Layouts", "Layout"),
    "section.omitted": ("Left out of the template", "Esclusi dal modello"),
    "section.problems": ("To remove or replace before saving", "Da rimuovere o sostituire prima di salvare"),
    "more": ("… and {count} more", "… e altri {count}"),
    "reads": ("reads {table} of {source}", "legge {table} di {source}"),
    "kind.numeric": ("numbers", "numeri"),
    "kind.text": ("text", "testo"),
    "kind.mixed": ("mixed", "misto"),
    "omit.rows": ("{place}: {count} observation row(s)", "{place}: {count} righe di osservazioni"),
    "omit.excluded": ("{place}: {count} excluded cell(s)", "{place}: {count} celle escluse"),
    "omit.info-sheets": ("{count} Info sheet(s) of the project", "{count} fogli Info del progetto"),
    "omit.shapes": ("{place}: {count} drawn shape(s)", "{place}: {count} forme disegnate"),
    "omit.annotations": ("{place}: {count} free annotation(s)", "{place}: {count} annotazioni libere"),
    "omit.points": ("{place}: {count} formatted point(s)", "{place}: {count} punti formattati"),
    "omit.labels": ("{place}: {count} data label setting(s)", "{place}: {count} impostazioni di etichette dati"),
    "omit.linked_tables": ("{place}: {count} linked table(s)", "{place}: {count} tabelle collegate"),
    "omit.always": ("Results, history, file references and import attributes are never saved.",
                    "Risultati, cronologia, riferimenti a file e attributi delle importazioni non vengono mai salvati."),
    "place.project": ("Project", "Progetto"),
    "place.table": ("Table {table}", "Tabella {table}"),
    "place.formula": ("Formula {name} of {table}", "Formula {name} di {table}"),
    "place.analysis": ("{name} ({table})", "{name} ({table})"),
    "place.layout": ("Layout {name}", "Layout {name}"),
    "problem.empty": ("The project has no data table.", "Il progetto non ha tabelle dati."),
    "problem.too-many": ("The project exceeds the limits of a template.", "Il progetto supera i limiti di un modello."),
    "problem.imported-table": ("This sheet keeps an imported view: copy its data into a new data table first.",
                               "Questo foglio conserva una vista importata: copia prima i dati in una nuova "
                               "tabella dati."),
    "problem.imported-analysis": ("This analysis depends on an imported view or file: remove it or analyse the "
                                  "data again.", "Questa analisi dipende da una vista o da un file importati: "
                                  "rimuovila o ripeti l'analisi sui dati."),
    "problem.imported-layout": ("A panel shows an imported view: replace it with a graph of the data.",
                                "Un pannello mostra una vista importata: sostituiscilo con un grafico dei dati."),
    "problem.unknown-method": ("This analysis is not available in this version of Trama.",
                               "Questa analisi non è disponibile in questa versione di Trama."),
    "problem.invalid-options": ("The saved options of this analysis are not valid.",
                                "Le opzioni salvate di questa analisi non sono valide."),
    "problem.missing-column": ("The analysis uses a column that is not in its table.",
                               "L'analisi usa una colonna che non è nella sua tabella."),
    "problem.broken-source": ("The analysis reads results of an analysis that no longer exists.",
                              "L'analisi legge i risultati di un'analisi che non esiste più."),
    "problem.broken-layout": ("A panel shows a graph that no longer exists.",
                              "Un pannello mostra un grafico che non esiste più."),
    "problem.info-formula": ("The formula reads an Info sheet, which a template does not carry: replace INFO() "
                             "with a value or remove the formula.",
                             "La formula legge un foglio Info, che il modello non porta con sé: sostituisci INFO() "
                             "con un valore o rimuovi la formula."),
    "problem.roles": ("The X and Y roles refer to missing columns.", "I ruoli X e Y citano colonne mancanti."),
    "problem.invalid-style": ("The graph format is not valid.", "Il formato del grafico non è valido."),
    "problem.links": ("The links between analyses are not valid.", "I collegamenti tra analisi non sono validi."),
    "error.file-name": ("Choose a file name ending in .tramatpl.", "Scegli un nome di file che termina con .tramatpl."),
    "error.current-path": ("Choose another file: the open project cannot be replaced by its template.",
                           "Scegli un altro file: il progetto aperto non può essere sostituito dal suo modello."),
    "error.open-file": ("Choose another file: {name} is open as a project.",
                        "Scegli un altro file: {name} è aperto come progetto."),
    "error.blocked": ("The template cannot be saved: {problem}", "Il modello non si può salvare: {problem}"),
    "error.too-large": ("The template is larger than 32 MiB.", "Il modello supera i 32 MiB."),
    "error.io": ("The file cannot be read or written: {error}", "Il file non si può leggere o scrivere: {error}"),
    "error.json": ("{name} is not a Trama analysis template.", "{name} non è un modello di analisi Trama."),
    "error.schema": ("{name} was made by a newer version of Trama.", "{name} è stato creato da una versione più "
                     "recente di Trama."),
    "error.duplicate-key": ("{name} repeats the field “{key}”.", "{name} ripete il campo “{key}”."),
    "error.template": ("{name} is not a valid template: {error}", "{name} non è un modello valido: {error}"),
    "error.no-source": ("Choose the source sheet for {table}.", "Scegli il foglio sorgente per {table}."),
    "error.unmapped": ("Choose the source column for “{column}” in {table}.",
                       "Scegli la colonna sorgente per “{column}” in {table}."),
    "error.missing-column": ("The source has no column “{source}” for “{column}” in {table}.",
                             "La sorgente non ha la colonna “{source}” per “{column}” in {table}."),
    "error.duplicate": ("“{source}” is assigned twice in {table}: choose another column for “{column}”.",
                        "“{source}” è assegnata due volte in {table}: scegli un'altra colonna per “{column}”."),
    "error.not-numeric": ("“{column}” in {table} needs numbers; “{source}” contains text.",
                          "“{column}” in {table} richiede numeri; “{source}” contiene testo."),
    "error.formula": ("A formula of {table} cannot be calculated on the new data: {error}",
                      "Una formula di {table} non si può calcolare sui nuovi dati: {error}"),
    "error.mapping": ("The assignment of {table} is not complete.", "L'assegnazione di {table} non è completa."),
    "error.full": ("Close a project first: at most {count} projects can be open.",
                   "Chiudi prima un progetto: si possono aprire al massimo {count} progetti."),
    "error.read_failed": ("{name} cannot be read: {error}", "Impossibile leggere {name}: {error}"),
    "error.build_failed": ("The new project could not be built: {error}",
                           "Non è stato possibile costruire il nuovo progetto: {error}"),
    "intro": ("Template {name}: assign a source sheet to every table, then a source column to every expected field. "
              "Only exact, unique names are proposed.",
              "Modello {name}: assegna un foglio sorgente a ogni tabella e una colonna sorgente a ogni campo atteso. "
              "Vengono proposti solo nomi esatti e univoci."),
    "sources_hint": ("Sources: the data sheets of the active project and CSV/TSV files added here.",
                     "Sorgenti: i fogli dati del progetto attivo e i file CSV/TSV aggiunti qui."),
    "source_for": ("Source for {table}", "Sorgente per {table}"),
    "choose_source": ("— choose a sheet —", "— scegli un foglio —"),
    "choose_column": ("— not assigned —", "— non assegnata —"),
    "add_files": ("Add CSV/TSV…", "Aggiungi CSV/TSV…"),
    "add_title": ("Add CSV or TSV files as sources", "Aggiungi file CSV o TSV come sorgenti"),
    "reading_files": ("Reading {count} file(s)…", "Lettura di {count} file…"),
    "added_files": ("Added {names}.", "Aggiunti {names}."),
    "column.table": ("Table", "Tabella"),
    "column.field": ("Expected field", "Campo atteso"),
    "column.kind": ("Kind", "Tipo"),
    "column.source": ("Source column", "Colonna sorgente"),
    "summary": ("{done} of {total} fields assigned.", "{done} di {total} campi assegnati."),
    "ignored": ("Ignored in {table} ({source}): {columns}", "Ignorate in {table} ({source}): {columns}"),
    "formulas_note": ("Formulas come from the template and need no assignment: {names}",
                      "Le formule vengono dal modello e non richiedono assegnazione: {names}"),
    "create": ("Create project", "Crea progetto"),
    "reading": ("Reading the template…", "Lettura del modello…"),
    "saving": ("Saving the template…", "Salvataggio del modello…"),
    "saved": ("Template saved: {name} ({tables} table(s), {analyses} analysis(es)). The project is unchanged.",
              "Modello salvato: {name} ({tables} tabelle, {analyses} analisi). Il progetto non è cambiato."),
    "save_cancelled": ("Saving the template was cancelled.", "Salvataggio del modello annullato."),
    "building": ("Building the project…", "Costruzione del progetto…"),
    "build_cancelled": ("The new project was not created (cancelled).", "Il nuovo progetto non è stato creato "
                        "(annullato)."),
    "built": ("New project from {name}: {analyses} analysis(es) calculated on the new data.",
              "Nuovo progetto da {name}: {analyses} analisi calcolate sui nuovi dati."),
    "built_errors": ("The new project was built, but {count} analysis(es) could not be calculated on the new data. "
                     "Correct the data and the results update.\n\n{lines}",
                     "Il nuovo progetto è stato costruito, ma {count} analisi non si possono calcolare sui nuovi "
                     "dati. Correggi i dati e i risultati si aggiornano.\n\n{lines}"),
    "error_line": ("• {name} ({table}){dependency}: {error}", "• {name} ({table}){dependency}: {error}"),
    "depends": (", which reads {parent}", ", che legge {parent}"),
    "no_tables": ("Open or create a data table first.", "Apri o crea prima una tabella dati."),
}


def t(_key, **values):
    english, italian = _TEXT[_key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


# ---------------------------------------------------------------------------
# Messages


def _place_text(place, tables):
    kind = place[0]
    if kind == "table":
        return t("place.table", table=place[1])
    if kind == "formula":
        return t("place.formula", name=place[2], table=place[1])
    if kind == "analysis":
        title, slot = place[1], place[2]
        return t("place.analysis", name=analysis_name(tables, title, slot), table=title)
    if kind == "layout":
        return t("place.layout", name=place[2] if len(place) > 2 else place[1] + 1)
    return t("place.project")


def analysis_name(tables, title, slot):
    dataset = tables.get(title)
    if dataset is None or not 0 <= slot < len(dataset.analyses):
        return f"#{slot + 1}"
    label = dataset.analysis_labels.get(slot)
    if label:
        return label
    method = dataset.analyses[slot][0]
    source = dataset.analysis_sources.get(slot)
    return f"{method} · {source.table}" if source is not None else method


def problem_text(problem, tables):
    key = f"problem.{problem.code}"
    text = t(key) if key in _TEXT else problem.message
    return f"{_place_text(problem.place, tables)}: {text}"


def error_text(error, *, name=""):
    """A TemplateError in the active language; unknown codes keep the engine's English text."""
    detail = {"name": name, "error": str(error), **{key: value for key, value in error.detail.items()
                                                    if isinstance(value, (str, int))}}
    detail.setdefault("table", "")
    detail.setdefault("column", "")
    detail.setdefault("source", "")
    detail.setdefault("key", "")
    if error.code == "blocked" and error.problems:
        return t("error.blocked", problem=error.problems[0].message)
    key = f"error.{error.code}"
    if key in _TEXT:
        try:
            return t(key, **detail)
        except (KeyError, IndexError):
            pass
    if error.field == "file" and name:
        return t("error.template", name=name, error=str(error))
    return str(error)


# ---------------------------------------------------------------------------
# Save as analysis template…


def _kind(kind):
    return t(f"kind.{kind}")


def plan_html(plan, tables, layouts):
    """The confirmation: what travels, what is left out and what blocks, as rich text in the active theme."""
    T = theme.T
    parts = []

    def heading(text):
        parts.append(f'<div style="font-weight:600; margin-top:10px">{escape(text)}</div>')

    def items(lines, colour=None):
        style = "margin-left:14px" + (f"; color:{colour}" if colour else "")
        for line in lines[:LISTED]:
            parts.append(f'<div style="{style}">• {escape(line)}</div>')
        if len(lines) > LISTED:
            parts.append(f'<div style="{style}">{escape(t("more", count=len(lines) - LISTED))}</div>')

    if plan.problems:
        heading(t("section.problems"))
        items([problem_text(problem, tables) for problem in plan.problems], T["error"])
    template = plan.template
    if template is not None:
        columns = sum(len(table.columns) for table in template.tables)
        formulas = sum(len(table.formulas) for table in template.tables)
        parts.append('<div style="font-weight:600">' + escape(t(
            "counts", tables=len(template.tables), columns=columns, formulas=formulas,
            analyses=template.analysis_count, links=template.link_count, layouts=len(template.layouts))) + "</div>")
        heading(t("section.tables"))
        items([f"{table.name}: " + ", ".join(f"{name} ({_kind(kind)})" for name, kind in table.columns)
               for table in template.tables])
        lines = [f"{table.name} · {name}: {expression}" for table in template.tables
                 for name, expression in table.formulas]
        if lines:
            heading(t("section.formulas"))
            items(lines)
        names = {analysis.id: analysis.label or analysis.method for table in template.tables
                 for analysis in table.analyses}
        lines = []
        for table in template.tables:
            for analysis in table.analyses:
                line = f"{table.name} · {analysis.label or analysis.method}"
                if analysis.label:
                    line += f" ({analysis.method})"
                if analysis.source is not None:
                    line += " — " + t("reads", table=analysis.source[1], source=names[analysis.source[0]])
                lines.append(line)
        if lines:
            heading(t("section.analyses"))
            items(lines)
        if template.layouts:
            heading(t("section.layouts"))
            empty = qt("qt.layout_empty_slot")
            items([f"{layout.name}: " + ", ".join(names[panel] if panel is not None else empty
                                                  for panel in layout.panels)
                   for layout in template.layouts])
    heading(t("section.omitted"))
    omitted = []
    for omission in plan.omissions:
        place = _place_text(omission.place, tables) if omission.place[0] != "project" else ""
        omitted.append(t(f"omit.{omission.code}", place=place, count=omission.count))
    omitted.append(t("omit.always"))
    items(omitted, T["text2"])
    return "".join(parts)


class SaveTemplateDialog(QDialog):
    """The confirmation of Save as analysis template…: contents, privacy note, file name. ``path`` after OK."""

    def __init__(self, window, plan):
        super().__init__(window)
        self.setWindowTitle(t("save_title"))
        self.window_, self.plan, self.path = window, plan, None
        project = window.project
        outer = QVBoxLayout(self)
        notice = QLabel(t("privacy"))
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        outer.addWidget(notice)
        self.preview = QTextBrowser()
        self.preview.setObjectName("templatePreview")
        self.preview.setHtml(plan_html(plan, project.tables, project.layouts))
        outer.addWidget(self.preview, 1)
        row = QHBoxLayout()
        label = QLabel(t("file_label"))
        row.addWidget(label)
        folder = (project.path.parent if project.path is not None else Path.home())
        stem = project.path.stem if project.path is not None else Path(t("default_file")).stem
        self.file = QLineEdit(str(folder / f"{stem}{SUFFIX}"))
        self.file.setAccessibleName(t("file_label"))
        label.setBuddy(self.file)
        row.addWidget(self.file, 1)
        browse = QPushButton(t("browse"))
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        outer.addLayout(row)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(t("save_button"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setDefault(True)
        self.save_button.setEnabled(plan.ok)
        buttons.addButton(t("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        fit_dialog(self, 680, 560)

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, t("save_title"), self.file.text(), t("file_filter"))
        if path:
            if not path.lower().endswith(SUFFIX):
                path += SUFFIX
            self.file.setText(path)

    def show_problem(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))
        self.file.setAccessibleDescription(text)
        if text:
            self.file.setFocus()
            self.file.selectAll()

    def check(self):
        """The file problem for the current name, or "" (also refuses an open project, through links)."""
        text = self.file.text().strip()
        if not text.lower().endswith(SUFFIX) or not Path(text).name[:-len(SUFFIX)].strip():
            return t("error.file-name")
        path = Path(text)
        if self.window_.project.path is not None and same_file(path, self.window_.project.path):
            return t("error.current-path")
        for session in self.window_.sessions:
            for own in session.paths():
                if same_file(path, own):
                    return t("error.open-file", name=Path(own).name)
        return ""

    def accept(self):
        if not self.plan.ok:
            return
        problem = self.check()
        if problem:
            self.show_problem(problem)
            return
        self.path = Path(self.file.text().strip())
        super().accept()


def save_template(window):
    """File → Save as analysis template…: confirm, choose the file, write on the worker. The project never changes."""
    from .project import CalculationControl
    if window.busy() or not window.prepare_project_change():
        return
    project = window.project
    if not project.tables:
        window.error(t("no_tables"))
        return
    project.sync_links(persist=True)  # The datasets hold what the runs show (as Save does).
    infos = tuple(project.info_sheets.values())
    plan = plan_template(project.tables, project.layouts, infos)
    dialog = SaveTemplateDialog(window, plan)
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.path is None:
        return
    path = dialog.path
    dirty, tables, layouts, source = project.dirty, project.tables, tuple(project.layouts), project.path
    control = CalculationControl()

    def done(future, cancelled):
        try:
            written = future.result()
        except ChainCancelled:
            window.status(t("save_cancelled"))
            return
        except TemplateError as error:
            message = error_text(error, name=path.name)
            window.status(message)
            window.error(message)
            return
        except OSError as error:
            message = t("error.io", error=error.strerror or error)
            window.status(message)
            window.error(message)
            return
        finally:
            project.dirty = dirty  # Exporting never marks the project as changed.
        window.status(t("saved", name=path.name, tables=len(written.template.tables),
                        analyses=written.template.analysis_count))

    window._start(window.worker.submit(write_template, path, tables, layouts=layouts, info_sheets=infos,
                                       source_path=source, cancel=control.cancel),
                  control, done, t("saving"))


# ---------------------------------------------------------------------------
# New project from template…


def _unique(name, taken):
    if name not in taken:
        return name
    number = 2
    while f"{name} ({number})" in taken:
        number += 1
    return f"{name} ({number})"


class TemplateWizard(QDialog):
    """The assistant of New project from template…: a source per table, a source column per expected field.

    ``sources`` are the data sheets of the active project (name → callable returning a DataFrame, read once);
    files added here are read on a worker thread. After OK: ``mapping`` and ``frames`` (the sources it uses)."""

    def __init__(self, window, template, name, sources, *, can_create=lambda: None):
        super().__init__(window)
        self.setWindowTitle(t("new_title"))
        self.template, self.name, self.can_create = template, name, can_create
        self._loaders = dict(sources)
        self._frames = {}
        self.mapping, self.frames = None, None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Trama-Template")
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        self._filling = False

        outer = QVBoxLayout(self)
        intro = QLabel(t("intro", name=name))
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(intro)
        hint = QLabel(t("sources_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.source_boxes = {}
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for table in template.tables:
            label = QLabel(t("source_for", table=table.name))
            label.setTextFormat(Qt.TextFormat.PlainText)
            box = QComboBox()
            box.setObjectName("templateSource")
            box.setAccessibleName(t("source_for", table=table.name))
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(18)
            label.setBuddy(box)
            form.addRow(label, box)
            box.currentIndexChanged.connect(lambda _index, table=table: self._source_changed(table))
            self.source_boxes[table.name] = box
        outer.addLayout(form)
        files = QHBoxLayout()
        self.add_button = QPushButton(t("add_files"))
        self.add_button.setIcon(theme.icon("file-up"))
        self.add_button.clicked.connect(self.add_files)
        files.addWidget(self.add_button)
        self.file_status = QLabel()
        self.file_status.setObjectName("muted")
        self.file_status.setTextFormat(Qt.TextFormat.PlainText)
        files.addWidget(self.file_status, 1)
        outer.addLayout(files)

        self.grid = QTableWidget(0, 4)
        self.grid.setObjectName("templateMapping")
        self.grid.setHorizontalHeaderLabels([t("column.table"), t("column.field"), t("column.kind"),
                                             t("column.source")])
        self.grid.verticalHeader().setVisible(False)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.grid.horizontalHeader()
        for column, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch)):
            header.setSectionResizeMode(column, mode)
        self.column_boxes = {}
        for table in template.tables:
            for column, kind in table.columns:
                row = self.grid.rowCount()
                self.grid.insertRow(row)
                for position, text in enumerate((table.name, column, _kind(kind))):
                    self.grid.setItem(row, position, QTableWidgetItem(text))
                box = QComboBox()
                box.setObjectName("templateColumn")
                box.setAccessibleName(f"{table.name} · {column}")
                box.currentIndexChanged.connect(self._changed)
                self.grid.setCellWidget(row, 3, box)
                self.column_boxes[table.name, column] = box
        outer.addWidget(self.grid, 1)
        formulas = [f"{table.name} · {name}" for table in template.tables for name, _ in table.formulas]
        if formulas:
            note = QLabel(t("formulas_note", names=", ".join(formulas)))
            note.setObjectName("muted")
            note.setWordWrap(True)
            note.setTextFormat(Qt.TextFormat.PlainText)
            outer.addWidget(note)
        self.summary = QLabel()
        self.summary.setObjectName("templateSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.summary)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setTextFormat(Qt.TextFormat.PlainText)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        self.create_button = buttons.addButton(t("create"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setDefault(True)
        buttons.addButton(t("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._fill_sources()
        for table in template.tables:  # A sheet is proposed only when its name is exactly the table's.
            box = self.source_boxes[table.name]
            if table.name in self._loaders:
                box.setCurrentIndex(box.findData(table.name))
        self._changed()
        fit_dialog(self, 760, 620)

    # -- sources ------------------------------------------------------------------------------------
    def frame(self, name):
        if name not in self._frames:
            self._frames[name] = self._loaders[name]()
        return self._frames[name]

    def _fill_sources(self):
        self._filling = True
        for table in self.template.tables:
            box = self.source_boxes[table.name]
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(t("choose_source"), None)
            for name in self._loaders:
                box.addItem(name, name)
            index = box.findData(current) if current is not None else 0
            box.setCurrentIndex(max(index, 0))
            box.blockSignals(False)
        self._filling = False

    def _source_changed(self, table):
        source = self.source_boxes[table.name].currentData()
        columns = [str(name) for name in self.frame(source).columns] if source is not None else []
        for column in table.column_names:
            box = self.column_boxes[table.name, column]
            box.blockSignals(True)
            box.clear()
            box.addItem(t("choose_column"), None)
            for name in columns:
                box.addItem(name, name)
            if columns.count(column) == 1:  # Only an exact and unique name is proposed.
                box.setCurrentIndex(box.findData(column))
            box.blockSignals(False)
        self._changed()

    def add_files(self):
        if self._pending is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, t("add_title"), "", f"CSV/TSV ({TEXT_FILTER})")
        if not paths:
            return
        paths = [Path(path) for path in paths]
        self._pending = self._pool.submit(_read_files, paths)
        self.file_status.setText(t("reading_files", count=len(paths)))
        self.add_button.setEnabled(False)
        self.create_button.setEnabled(False)
        self._timer.start()

    def _poll(self):
        future = self._pending
        if future is None or not future.done():
            return
        self._timer.stop()
        self._pending = None
        self.add_button.setEnabled(True)
        self.create_button.setEnabled(True)
        try:
            loaded = future.result()
        except Exception as error:  # noqa: BLE001 - shown to the user, nothing changes.
            self.file_status.setText("")
            self._show_problem(str(error))
            return
        added = []
        for name, frame in loaded:
            unique = _unique(name, self._loaders)
            self._loaders[unique] = (lambda frame=frame: frame)
            added.append(unique)
        self.file_status.setText(t("added_files", names=", ".join(added)))
        self._fill_sources()
        self._changed()

    def wait_files(self, timeout=30.0):
        """For tests and the smoke: finish a pending read now."""
        if self._pending is not None:
            self._pending.result(timeout=timeout)
            self._poll()

    # -- mapping ------------------------------------------------------------------------------------
    def current_mapping(self):
        mapping = {}
        for table in self.template.tables:
            source = self.source_boxes[table.name].currentData()
            if source is None:
                continue
            mapping[table.name] = (source, {column: self.column_boxes[table.name, column].currentData()
                                            for column in table.column_names
                                            if self.column_boxes[table.name, column].currentData()})
        return mapping

    def current_sources(self, mapping):
        return {source: self.frame(source) for source, _ in mapping.values()}

    def _changed(self, *_):
        if self._filling:
            return
        mapping = self.current_mapping()
        total = sum(len(table.columns) for table in self.template.tables)
        done = sum(len(columns) for _, columns in mapping.values())
        lines = [t("summary", done=done, total=total)]
        sources = self.current_sources(mapping)
        for table, names in ignored_columns(self.template, sources, mapping).items():
            if names:
                lines.append(t("ignored", table=table, source=mapping[table][0], columns=", ".join(names)))
        self.summary.setText("\n".join(lines))
        self._show_problem("")

    def _show_problem(self, text, widget=None):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))
        for box in [*self.source_boxes.values(), *self.column_boxes.values()]:
            box.setAccessibleDescription(text if box is widget else "")
        if widget is not None:
            row = next((r for r in range(self.grid.rowCount()) if self.grid.cellWidget(r, 3) is widget), None)
            if row is not None:
                self.grid.scrollToItem(self.grid.item(row, 1))
            widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def problems(self):
        mapping = self.current_mapping()
        return mapping, mapping_problems(self.template, self.current_sources(mapping), mapping)

    def accept(self):
        if self._pending is not None:
            return
        mapping, found = self.problems()
        if found:
            error = found[0]
            widget = None
            if isinstance(error.field, tuple):
                widget = self.column_boxes.get(error.field)
            elif isinstance(error.field, str):
                widget = self.source_boxes.get(error.field)
            self._show_problem(error_text(error, name=self.name), widget)
            return
        blocked = self.can_create()  # The destination is checked again just before the confirmation.
        if blocked:
            self._show_problem(blocked)
            return
        self.mapping = deepcopy(mapping)
        self.frames = self.current_sources(mapping)
        super().accept()

    def done(self, result):
        self._timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        super().done(result)


def _read_files(paths):
    """Worker side: read CSV/TSV files with the project's text reader. Returns ``[(name, frame), …]``."""
    result = []
    for path in paths:
        try:
            tables = load_tables(path)
        except (OSError, ValueError, UnicodeError) as error:
            raise ValueError(t("error.read_failed", name=path.name, error=getattr(error, "strerror", None) or error)) \
                from error
        for name, frame in tables.items():
            result.append((name, frame.reset_index(drop=True)))
    return result


def project_sources(project):
    """The data sheets of the active project as sources: name → callable (the copy is taken when chosen)."""
    from .project import stored_legacy_view
    return {title: (lambda dataset=dataset: dataset.frame().reset_index(drop=True))
            for title, dataset in project.tables.items() if not stored_legacy_view(dataset)}


def build_project(number, tables, layouts):
    """A new, changed project without a path, an origin or history, with the runs of the built tables."""
    from .project import Project
    project = Project(number)
    project.tables = dict(tables)
    project.layouts = list(layouts)
    project.runs = [run for title, dataset in project.tables.items() for run in Project.runs_for(title, dataset)]
    project.dirty = True
    return project


def report_errors(window, project, name):
    """After the first calculation of a new project: each analysis that failed, with the analysis it reads."""
    if window.project is not project:
        return
    by_uid = {run.uid: run for run in project.runs}
    lines = []
    for run in project.runs:
        if not run.calculation_error:
            continue
        dependency = ""
        if run.source is not None and run.source.analysis_id in by_uid:
            dependency = t("depends", parent=by_uid[run.source.analysis_id].name)
        lines.append(t("error_line", name=run.name, table=run.title, dependency=dependency,
                       error=run.calculation_error))
    if lines:
        message = t("built_errors", count=len(lines), lines="\n".join(lines[:12]))
        window.status(lines[0].lstrip("• "))
        window.error(message)
    else:
        window.status(t("built", name=name, analyses=len(project.runs)))


def new_from_template(window, path=None):
    """File → New project from template…: read the template, map the new data, build, then calculate."""
    from .project import CalculationControl
    from .sessions import MAX_PROJECT_TABS
    if window.busy():
        return
    reuse = window.project.is_empty()
    if not reuse and window.sessions.full():
        window.error(t("error.full", count=MAX_PROJECT_TABS))
        return
    if not window.prepare_project_change():
        return
    if path is None:
        chosen, _ = QFileDialog.getOpenFileName(window, t("new_title"), "", t("file_filter"))
        if not chosen:
            return
        path = chosen
    path = Path(path)
    control = CalculationControl()

    def read_done(future, cancelled):
        try:
            template = future.result()
        except ChainCancelled:
            return
        except TemplateError as error:
            window.status(error_text(error, name=path.name))
            window.error(error_text(error, name=path.name))
            return
        except OSError as error:
            window.error(t("error.io", error=error.strerror or error))
            return
        if not cancelled:  # The assistant opens once the window has finished with this job.
            QTimer.singleShot(0, window, lambda: _assist(window, template, path))

    window._start(window.worker.submit(read_template, path), control, read_done, t("reading"))


def _destination_problem(window):
    from .sessions import MAX_PROJECT_TABS
    if not window.project.is_empty() and window.sessions.full():
        return t("error.full", count=MAX_PROJECT_TABS)
    return None


def _assist(window, template, path):
    from .project import CalculationControl
    if window.job is not None:
        return
    origin = window.sessions.active
    wizard = TemplateWizard(window, template, path.name, project_sources(window.project),
                            can_create=lambda: _destination_problem(window))
    window.template_wizard = wizard
    try:
        accepted = wizard.exec() == QDialog.DialogCode.Accepted
    finally:
        window.template_wizard = None
    if not accepted or wizard.mapping is None or window.sessions.active is not origin:
        wizard.deleteLater()
        return
    mapping, frames = wizard.mapping, wizard.frames
    wizard.deleteLater()
    avoid = {run.uid for session in window.sessions for run in session.project.runs}
    control = CalculationControl()

    def built(future, cancelled):
        try:
            tables, layouts = future.result()
        except ChainCancelled:
            window.status(t("build_cancelled"))
            return
        except TemplateError as error:
            message = t("error.build_failed", error=error_text(error, name=path.name))
            window.status(message)
            window.error(message)
            return
        except Exception as error:  # noqa: BLE001 - nothing was created; say why.
            message = t("error.build_failed", error=error)
            window.status(message)
            window.error(message)
            return
        if cancelled:
            window.status(t("build_cancelled"))
            return
        problem = _destination_problem(window)
        if problem:
            window.error(problem)
            return
        reuse = window.project.is_empty()
        number = window.project.number if reuse else window.project_number + 1
        project = build_project(number, tables, layouts)
        if reuse:
            window._drop_gallery()
            window.gallery_view = {"kind": None, "text": ""}
            window.dispose_inspector()
            window.info_editor = None
            window.sessions.active.reset(project)
            window._install()
        else:
            window.project_number = number
            window._activate(window.sessions.add(project))
        first = next(iter(project.tables))
        window.show_sheet("data", first)
        window.refresh_runs(list(project.runs))
        if window.job is not None:
            window._deferred.append(lambda: report_errors(window, project, path.name))
        else:
            report_errors(window, project, path.name)

    window._start(window.worker.submit(instantiate_template, template, frames, mapping, avoid=avoid,
                                       cancel=control.cancel),
                  control, built, t("building"))


def sync_actions(window):
    idle = window.job is None
    window.actions["save_template"].setEnabled(idle and bool(window.project.tables))
    window.actions["new_from_template"].setEnabled(idle and (window.project.is_empty() or not window.sessions.full()))
