"""File → Export multiple figures… on Qt: one PNG, SVG or PDF file per graph or layout.

The dialog lists the graphs and layouts of the active project in navigator order, reads the same
settings as Export with options, shows each file name before writing and then writes the files one
at a time from the Qt event loop (``trama_qt.batch_export.BatchExport``), with progress, Cancel
between files and a summary. Files go only into the chosen folder and never replace anything.
"""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from analisi import figure_export as fe
from analisi.data import decimal_comma
from analisi.i18n import active_language, ui

from . import batch_export as bx
from .export_options import SESSION
from .pdf_bundle import bundle_sheets
from .theme import fit_dialog

FORMAT_LABELS = (("PNG", "png"), ("SVG", "svg"), ("PDF", "pdf"))

_TEXT = {
    "title": ("Export multiple figures", "Esporta più figure"),
    "command": ("Export multiple figures…", "Esporta più figure…"),
    "figures": ("Graphs and layouts", "Grafici e layout"),
    "all": ("All", "Tutti"), "none": ("None", "Nessuno"),
    "col_figure": ("Figure", "Figura"), "col_file": ("File name", "Nome del file"),
    "col_size": ("Size or reason", "Dimensione o motivo"), "col_outcome": ("Outcome", "Esito"),
    "options": ("Options", "Opzioni"), "format": ("Format", "Formato"), "width": ("Width (mm)", "Larghezza (mm)"),
    "svg_text": ("SVG text", "Testo SVG"), "text": ("Text", "Testo"), "paths": ("Paths", "Tracciati"),
    "transparent": ("Transparent background", "Sfondo trasparente"),
    "width_hint": ("Empty width keeps each figure at its own size; a width keeps each aspect ratio.",
                   "Senza larghezza ogni figura mantiene la sua dimensione; una larghezza ne mantiene le proporzioni."),
    "folder": ("Folder", "Cartella"), "choose": ("Choose…", "Scegli…"),
    "choose_title": ("Choose the folder for the figures", "Scegli la cartella per le figure"),
    "export": ("Export", "Esporta"), "close": ("Close", "Chiudi"), "cancel": ("Cancel", "Annulla"),
    "graph": ("Graph", "Grafico"), "layout": ("Layout", "Layout"),
    "not_calculated": ("Not calculated: open or recalculate it first.",
                       "Non calcolato: aprilo o ricalcolalo prima."),
    "failed": ("Calculation error: {error}", "Errore di calcolo: {error}"),
    "panels": ("Recalculate the layout panels first.", "Ricalcola prima i pannelli del layout."),
    "imported": ("Imported: keeps its original export.", "Importato: conserva la propria esportazione originale."),
    "select": ("Select at least one figure.", "Seleziona almeno una figura."),
    "no_folder": ("Choose a folder for the files.", "Scegli una cartella per i file."),
    "missing_folder": ("The folder {folder} does not exist.", "La cartella {folder} non esiste."),
    "unreadable_folder": ("The folder {folder} cannot be read: {error}",
                          "Non è possibile leggere la cartella {folder}: {error}"),
    "invalid_width": ("Width must be a number in millimetres.", "La larghezza deve essere un numero in millimetri."),
    "invalid_dpi": ("DPI must be a whole number.", "I DPI devono essere un numero intero."),
    "figure_problem": ("“{name}”: {error}", "“{name}”: {error}"),
    "ready": ("{count} of {total} figures selected · one {format} file each, nothing is overwritten.",
              "{count} di {total} figure selezionate · un file {format} per figura, nessun file viene sovrascritto."),
    "running": ("Exporting {current} of {total}: {name}", "Esportazione {current} di {total}: {name}"),
    "cancelling": ("Stopping after the current file…", "Interruzione dopo il file in corso…"),
    "finished": ("Export finished.", "Esportazione completata."),
    "stopped": ("Export stopped: the files already written are kept.",
                "Esportazione interrotta: i file già scritti restano nella cartella."),
    "done": ("Exported", "Esportato"), "skipped": ("Skipped", "Saltato"), "error": ("Error", "Errore"),
    "cancelled": ("Cancelled", "Annullato"), "waiting": ("Waiting", "In attesa"),
    "conflict": ("a file with this name appeared in the folder; nothing was replaced",
                 "nella cartella è comparso un file con questo nome; nessun file è stato sostituito"),
    "folder_lost": ("the folder is not writable", "la cartella non è scrivibile"),
    "summary": ("{done} exported · {skipped} skipped · {errors} errors · {cancelled} cancelled · {folder}",
                "{done} esportati · {skipped} saltati · {errors} errori · {cancelled} annullati · {folder}"),
    "status": ("Exported {done} of {total} figures to {folder}.", "Esportate {done} figure su {total} in {folder}."),
    "empty": ("There is no graph or layout in this project.", "Il progetto non contiene grafici o layout."),
}


def text(key, **values):
    english, italian = _TEXT[key]
    value = italian if active_language() == "it" else english
    return value.format(**values) if values else value


@dataclass(frozen=True)
class BatchRow:
    """One graph or layout of the navigator; ``ready`` rows can be exported, the others say why not."""
    ref: tuple
    kind: str  # "Graph" or "Layout"
    name: str
    label: str
    size: tuple = None
    ready: bool = False
    reason: str = ""


def navigator_graphs(project):
    """The run indexes listed under Graphs in the navigator, in the same order (see ``MainWindow.refresh``)."""
    from analisi.paired_graphs import paired_plot_options
    from analisi.rank_graphs import rank_plot_options
    from analisi.workbench import GRAPH_METHODS

    from .project import run_view
    return [index for index, run in enumerate(project.runs)
            if not project.sheet_state(("graph", index)).get("hidden")
            and (run_view(run.method) == "graph" or run.method in GRAPH_METHODS
                 or (run.result is None and (paired_plot_options(run.method, run.options)
                                             or rank_plot_options(run.method, run.options)))
                 or (run.result is not None and run.result.figure is not None and run_view(run.method) == "result"))]


def batch_rows(project, imported_methods):
    """Every graph and layout in navigator order; the ready ones are those ``bundle_sheets`` accepts."""
    from .project import run_view
    graphs = navigator_graphs(project)
    ready = {entry.ref: entry for entry in bundle_sheets(project, graphs, imported_methods)[0]}
    raw = []
    for index in graphs:
        run = project.runs[index]
        entry = ready.get(("graph", index))
        name = project.sheet_title(("graph", index))
        if entry is not None:
            raw.append(("Graph", name, entry.ref, entry.size, ""))
        elif run.method in imported_methods:
            raw.append(("Graph", name, ("graph", index), None, text("imported")))
        elif run.calculation_error:
            raw.append(("Graph", name, ("graph", index), None, text("failed", error=run.calculation_error)))
        else:
            raw.append(("Graph", name, ("graph", index), None, text("not_calculated")))
    for index, layout in enumerate(project.layouts):
        entry = ready.get(("layout", index))
        raw.append(("Layout", layout.name, ("layout", index), entry.size if entry else None,
                    "" if entry else text("panels")))
    for index, run in enumerate(project.runs):
        ref = ("saved-layout", index)
        if run_view(run.method) == "saved-layout" and not project.sheet_state(ref).get("hidden"):
            raw.append(("Layout", project.sheet_title(ref), ref, None, text("imported")))
    rows, counts = [], {}
    for kind, name, ref, size, reason in raw:
        label = f"{text('graph') if kind == 'Graph' else text('layout')} · {name}"
        counts[label] = counts.get(label, 0) + 1
        if counts[label] > 1:
            label = f"{label} ({counts[label]})"
        rows.append(BatchRow(ref, kind, name, label, size, not reason, reason))
    return rows


def render_for(project, ref, settings):
    """The existing exporter for one figure: ``export_figure`` for a graph, ``Project.export_layout`` for a layout."""
    kind, key = ref
    if kind == "layout":
        layout = project.layouts[key]
        return lambda path: project.export_layout(layout, path, dict(settings))
    figure = project.runs[key].result.figure
    return lambda path: fe.export_figure(figure, path, dict(settings))


class BatchExportDialog(QDialog):
    """Selection, options and name preview, then progress and the summary in the same window.

    ``outcomes`` holds one ``batch_export.Outcome`` per exported figure once the batch has run.
    """

    def __init__(self, parent, project, rows, folder=""):
        super().__init__(parent)
        self.setWindowTitle(text("title"))
        self.project, self.rows = project, list(rows)
        self.batch, self.outcomes, self.names, self.running = None, None, {}, False
        outer = QVBoxLayout(self)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.pages.addWidget(self._setup_page(folder))
        self.pages.addWidget(self._run_page())
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.export_button = QPushButton(text("export"))
        self.export_button.setObjectName("primary")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.start_export)
        self.close_button = QPushButton(text("cancel"))
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.export_button)
        footer.addWidget(self.close_button)
        outer.addLayout(footer)
        self.refresh()
        fit_dialog(self, 760, 600)

    # -- setup ------------------------------------------------------------------------------------
    def _setup_page(self, folder):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        figures = QGroupBox(text("figures"))
        box = QVBoxLayout(figures)
        self.tree = QTreeWidget()
        self.tree.setObjectName("batchFigures")
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setHeaderLabels([text("col_figure"), text("col_file"), text("col_size")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row in self.rows:
            item = QTreeWidgetItem([row.label, "—", row.reason])
            if row.ready:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setToolTip(0, row.reason)
                item.setToolTip(2, row.reason)
            self.tree.addTopLevelItem(item)
        box.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        for key, state in (("all", True), ("none", False)):
            button = QPushButton(text(key))
            button.clicked.connect(lambda _=False, state=state: self.check_all(state))
            buttons.addWidget(button)
        buttons.addStretch(1)
        box.addLayout(buttons)
        layout.addWidget(figures, 1)

        options = QGroupBox(text("options"))
        form = QFormLayout(options)
        self.format = QComboBox()
        for label, value in FORMAT_LABELS:
            self.format.addItem(label, value)
        start = SESSION.get("format", "png")
        self.format.setCurrentIndex(max(0, self.format.findData(start if start in bx.FORMATS else "png")))
        form.addRow(text("format"), self.format)
        self.width = QLineEdit("" if SESSION.get("width_mm") is None else f"{SESSION['width_mm']:g}")
        self.width.setMaximumWidth(140)
        form.addRow(text("width"), self.width)
        self.dpi = QLineEdit(f"{SESSION.get('dpi', fe.DEFAULT_DPI):g}")
        self.dpi.setMaximumWidth(140)
        form.addRow("DPI", self.dpi)
        self.svg_text = QComboBox()
        self.svg_text.addItem(text("text"), "text")
        self.svg_text.addItem(text("paths"), "paths")
        self.svg_text.setCurrentIndex(1 if SESSION.get("svg_text") == "paths" else 0)
        form.addRow(text("svg_text"), self.svg_text)
        self.transparent = QCheckBox(text("transparent"))
        self.transparent.setChecked(bool(SESSION.get("transparent", False)))
        form.addRow("", self.transparent)
        hint = QLabel(text("width_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        place = QHBoxLayout()
        self.folder = QLineEdit(str(folder or ""))
        self.folder.setReadOnly(True)
        self.folder.setAccessibleName(text("folder"))
        place.addWidget(self.folder, 1)
        choose = QPushButton(text("choose"))
        choose.clicked.connect(self.choose_folder)
        place.addWidget(choose)
        form.addRow(text("folder"), place)
        self.form = form
        layout.addWidget(options)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.tree.itemChanged.connect(lambda *_: self.refresh())
        for signal in (self.format.currentIndexChanged, self.width.textChanged, self.dpi.textChanged,
                       self.svg_text.currentIndexChanged, self.transparent.toggled):
            signal.connect(self.refresh)
        return page

    def _run_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)  # The line above says "n of N"; the bar only shows the advance.
        layout.addWidget(self.progress)
        self.results = QTreeWidget()
        self.results.setObjectName("batchResults")
        self.results.setRootIsDecorated(False)
        self.results.setHeaderLabels([text("col_figure"), text("col_file"), text("col_outcome")])
        self.results.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.results.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.results, 1)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        self.totals.setObjectName("batchSummary")
        layout.addWidget(self.totals)
        return page

    def _show(self, widget, visible):
        widget.setVisible(visible)
        label = self.form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def check_all(self, state):
        self.tree.blockSignals(True)
        for position, row in enumerate(self.rows):
            if row.ready:
                self.tree.topLevelItem(position).setCheckState(
                    0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.refresh()

    def chosen(self):
        return [row for position, row in enumerate(self.rows) if row.ready
                and self.tree.topLevelItem(position).checkState(0) == Qt.CheckState.Checked]

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, text("choose_title"), self.folder.text())
        if folder:
            self.folder.setText(folder)
            self.refresh()
        return bool(folder)

    def fmt(self):
        return self.format.currentData()

    def settings(self):
        """The same settings, parsing and messages as Export with options."""
        fmt = self.fmt()
        settings = {"format": fmt, "transparent": self.transparent.isChecked()}
        value = self.width.text().strip()
        try:
            settings["width_mm"] = float(decimal_comma(value)) if value else None
        except ValueError:
            raise ValueError(text("invalid_width")) from None
        if fmt == "png":
            try:
                settings["dpi"] = float(decimal_comma(self.dpi.text().strip()))
            except ValueError:
                raise ValueError(text("invalid_dpi")) from None
        if fmt == "svg":
            settings["svg_text"] = self.svg_text.currentData()
        return settings

    def occupied(self):
        """Names already in the folder, or a problem that keeps Export disabled."""
        folder = self.folder.text().strip()
        if not folder:
            return [], text("no_folder")
        if not Path(folder).is_dir():
            return [], text("missing_folder", folder=folder)
        try:
            return bx.folder_names(folder), None
        except OSError as error:
            return [], text("unreadable_folder", folder=folder, error=error.strerror or error)

    def check(self):
        """Plans for the chosen figures, or the first problem. Names are planned even without a folder."""
        chosen = self.chosen()
        occupied, folder_problem = self.occupied()
        self.names = dict(zip((row.ref for row in chosen),
                              bx.plan_filenames([row.name for row in chosen], self.fmt(), occupied)))
        if not chosen:
            return {}, text("select")
        try:
            settings = self.settings()
        except ValueError as error:
            return {}, str(error)
        plans = {}
        for row in chosen:
            try:
                plans[row.ref] = fe.plan_export(row.size, settings)
            except ValueError as error:
                return plans, text("figure_problem", name=row.label, error=ui(str(error)))
        return plans, folder_problem

    def refresh(self, *_):
        fmt = self.fmt()
        self._show(self.dpi, fmt == "png")
        self._show(self.svg_text, fmt == "svg")
        plans, problem = self.check()
        self.tree.blockSignals(True)
        for position, row in enumerate(self.rows):
            item = self.tree.topLevelItem(position)
            if not row.ready:
                continue
            plan = plans.get(row.ref)
            item.setText(1, self.names.get(row.ref, "—"))
            item.setText(2, f"{plan['width_mm']:.1f} × {plan['height_mm']:.1f} mm" if plan else "")
        self.tree.blockSignals(False)
        self.tree.resizeColumnToContents(1)
        if problem:
            self.summary.setObjectName("errorBanner")
            self.summary.setText(problem)
        else:
            self.summary.setObjectName("")
            self.summary.setText(text("ready", count=len(self.chosen()), total=sum(row.ready for row in self.rows),
                                      format=fmt.upper()))
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.export_button.setEnabled(bool(self.chosen()) and (problem is None or problem == text("no_folder")))

    # -- run ----------------------------------------------------------------------------------------
    def start_export(self):
        if self.running or self.batch is not None:
            return
        if not self.folder.text().strip():
            self.choose_folder()  # The names are shown again before anything is written.
            return
        plans, problem = self.check()
        if problem:
            self.refresh()
            return
        chosen = self.chosen()
        settings = self.settings()
        items = [bx.BatchItem(row.label, self.names[row.ref], render_for(self.project, row.ref, settings))
                 for row in chosen]
        self.batch = bx.BatchExport(Path(self.folder.text().strip()), self.fmt(), items)
        self.running = True
        self.results.clear()
        for item in items:
            self.results.addTopLevelItem(QTreeWidgetItem([item.label, item.filename, text("waiting")]))
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.pages.setCurrentIndex(1)
        self.export_button.setVisible(False)
        self.close_button.setText(text("cancel"))
        self._announce()
        QTimer.singleShot(0, self, self._advance)

    def _announce(self):
        batch = self.batch
        if batch.cancel_requested:
            self.state.setText(text("cancelling"))
        elif not batch.finished:
            self.state.setText(text("running", current=batch.position + 1, total=len(batch.items),
                                    name=batch.items[batch.position].label))

    def _advance(self):
        """One figure per turn of the event loop, always on the GUI thread."""
        batch = self.batch
        more = batch.step()
        self._show_outcomes()
        if more:
            self._announce()
            QTimer.singleShot(0, self, self._advance)
        else:
            self._finish()

    def _show_outcomes(self):
        self.progress.setValue(self.batch.position)
        for position, outcome in enumerate(self.batch.outcomes):
            if outcome.status:
                item = self.results.topLevelItem(position)
                item.setText(2, self.describe(outcome))
                item.setToolTip(2, self.describe(outcome))

    def describe(self, outcome):
        label = text(outcome.status)
        if outcome.status == bx.SKIPPED:
            return f"{label}: {text('conflict') if outcome.reason == 'conflict' else text('folder_lost')}"
        if outcome.status == bx.ERROR:
            return f"{label}: {ui(outcome.reason)}"
        return label

    def _finish(self):
        batch = self.batch
        batch.cleanup()
        self.running = False
        self.outcomes = list(batch.outcomes)
        counts = batch.counts()
        self.state.setText(text("finished") if counts[bx.CANCELLED] == 0 and not batch.stopped else text("stopped"))
        self.totals.setText(text("summary", done=counts[bx.DONE], skipped=counts[bx.SKIPPED],
                                 errors=counts[bx.ERROR], cancelled=counts[bx.CANCELLED], folder=batch.folder))
        self.close_button.setText(text("close"))

    def counts(self):
        return self.batch.counts() if self.batch is not None else None

    def reject(self):
        """Esc or Cancel while writing stops after the current file instead of closing the window."""
        if self.running:
            self.batch.cancel()
            self._announce()
            return
        super().reject()
