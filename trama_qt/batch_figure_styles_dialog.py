"""Change → Apply style to multiple graphs…: apply one saved figure style to chosen graphs in a project.

The dialog reads the local style library (``graph_style_presets.PresetLibrary``) without modifying it:
library editing remains in ``GraphStylePresetDialog``. Target graphs are identified by their stable
``Run.uid``, even when two graphs share the same title. Selecting a style and a candidate graph draws
a mini preview on an independent copy of the figure; Cancel and Esc discard the preview copy without
touching the confirmed graphs.
"""
from copy import deepcopy
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from analisi.i18n import active_language, ui
from analisi.presentation import apply_style, validate_graph_style

from . import graph_style_presets as gsp
from . import theme
from .gallery_catalog import graph_runs
from .gallery_thumbs import figure_image
from .graph_style_preset_dialog import _swatch, describe, message as preset_message
from .project import run_view

# Captions of this dialog only (English, Italian). Kept here so shared catalogs stay untouched.
_TEXT = {
    "action": ("Apply style to multiple graphs…", "Applica stile a più grafici…"),
    "title": ("Apply style to multiple graphs", "Applica stile a più grafici"),
    "intro": ("Apply one saved figure style to several graphs in this project. Titles, axis texts, scales, "
              "series colours, shapes and annotations stay with each graph. Edit the style library in "
              "Figure styles…",
              "Applica uno stile di figura salvato a più grafici del progetto. Titoli, testi degli assi, "
              "scale, colori delle serie, forme e annotazioni restano di ciascun grafico. Per modificare la "
              "libreria usa Stili di figura…"),
    "styles": ("Saved styles", "Stili salvati"),
    "empty_library": ("No saved styles yet. Save or import one in Change → Figure styles… first.",
                      "Nessuno stile salvato. Salvane o importane prima uno da Cambia → Stili di figura…."),
    "details": ("Style settings", "Impostazioni stile"),
    "none_selected": ("Choose a style to see its settings.", "Scegli uno stile per vederne le impostazioni."),
    "graphs": ("Project graphs", "Grafici del progetto"),
    "col_graph": ("Graph", "Grafico"),
    "col_source": ("Source sheet", "Foglio sorgente"),
    "col_status": ("Status", "Stato"),
    "select_all": ("Select all", "Seleziona tutti"),
    "select_none": ("Select none", "Deseleziona tutti"),
    "count": ("{selected} of {eligible} eligible graphs selected",
              "{selected} di {eligible} grafici idonei selezionati"),
    "count_plan": ("{selected} of {eligible} eligible selected · {changed} to update · {unchanged} already up to date",
                   "{selected} di {eligible} idonei selezionati · {changed} da aggiornare · {unchanged} già aggiornati"),
    "preview": ("Mini preview", "Mini anteprima"),
    "preview_of": ("Preview copy: {name} ({source})", "Copia di anteprima: {name} ({source})"),
    "preview_choose": ("Choose a style and a selected graph to see a preview copy.",
                       "Scegli uno stile e un grafico selezionato per vedere una copia di anteprima."),
    "preview_error": ("Preview unavailable: {reason}", "Anteprima non disponibile: {reason}"),
    "status_ready": ("Ready", "Pronto"),
    "status_update": ("Will update", "Da aggiornare"),
    "status_same": ("Already applied", "Già applicato"),
    "reason_pending": ("Waiting for calculation: open the graph or run Recalculate (F9) first.",
                       "In attesa di calcolo: apri il grafico o usa Ricalcola (F9)."),
    "reason_error": ("Calculation error: {error}. Recalculate the graph first.",
                     "Errore di calcolo: {error}. Ricalcola prima il grafico."),
    "reason_no_figure": ("No editable figure available.", "Nessuna figura modificabile disponibile."),
    "no_graphs": ("There are no graphs in this project.", "Il progetto non contiene grafici."),
    "no_eligible": ("No graph is ready to receive a style yet.",
                    "Nessun grafico è ancora pronto per ricevere uno stile."),
    "choose_style": ("Choose a saved style to apply.", "Scegli uno stile salvato da applicare."),
    "choose_graphs": ("Select at least one eligible graph.", "Seleziona almeno un grafico idoneo."),
    "apply": ("Apply", "Applica"),
    "cancel": ("Cancel", "Annulla"),
    "damaged": ("{reason}\nFile: {path}", "{reason}\nFile: {path}"),
    "target_invalid": ("“{name}”: {reason}", "«{name}»: {reason}"),
    "changed": ("One or more graphs changed while the dialog was open. Nothing was applied.",
                "Uno o più grafici sono cambiati mentre il dialogo era aperto. Non è stato applicato nulla."),
    "summary_applied": ("Applied “{name}” to {changed} of {selected} selected graphs.",
                        "Stile «{name}» applicato a {changed} grafici su {selected} selezionati."),
    "summary_applied_partial": ("Applied “{name}” to {changed} of {selected} selected graphs "
                                "({unchanged} already up to date).",
                                "Stile «{name}» applicato a {changed} grafici su {selected} selezionati "
                                "({unchanged} già aggiornati)."),
    "summary_unchanged": ("No changes made: all {selected} selected graphs already use “{name}”.",
                          "Nessuna modifica: tutti i {selected} grafici selezionati usano già «{name}»."),
    "undone": ("Undid figure style on {count} graphs.", "Annullato lo stile di figura su {count} grafici."),
    "redone": ("Reapplied figure style on {count} graphs.", "Ripetuto lo stile di figura su {count} grafici."),
}

_MESSAGES_IT = {
    "A graph was selected more than once.": "Un grafico è stato selezionato più di una volta.",
    "A selected graph is no longer available.": "Un grafico selezionato non è più disponibile.",
    "One or more graphs changed while the dialog was open. Nothing was applied.":
        "Uno o più grafici sono cambiati mentre il dialogo era aperto. Non è stato applicato nulla.",
    "A styled graph is no longer in this project.": "Uno dei grafici stilizzati non è più nel progetto.",
    "Recalculate the graph first.": "Ricalcola prima il grafico.",
}


def t(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


def batch_message(error):
    """Translate engine or batch errors into the active language."""
    text = str(error)
    if active_language() == "it" and text in _MESSAGES_IT:
        return _MESSAGES_IT[text]
    return preset_message(error)


def format_summary(outcome):
    """Human-readable summary for the status bar and dialog reports."""
    selected = len(outcome.selected_uids)
    changed = len(outcome.changed_uids)
    unchanged = len(outcome.unchanged_uids)
    if changed == 0:
        return t("summary_unchanged", name=outcome.preset_name, selected=selected)
    if unchanged > 0:
        return t("summary_applied_partial", name=outcome.preset_name, changed=changed,
                 selected=selected, unchanged=unchanged)
    return t("summary_applied", name=outcome.preset_name, changed=changed, selected=selected)


@dataclass(frozen=True)
class BatchStyleRow:
    """One graph row shown in the batch style dialog, keyed by stable ``Run.uid``."""
    uid: str
    index: int
    name: str
    source: str
    eligible: bool
    reason: str
    run: object


def _source_label(run, by_uid):
    if run.source is not None:
        parent = by_uid.get(run.source.analysis_id)
        if parent is not None:
            return f"{parent.name} · {run.source.table}"
        return run.source.table
    return run.title


def batch_style_rows(project):
    """All graph sheets of ``project`` in navigator order, excluding layouts and figure-less results.

    Eligibility uses the same editability rule as Format Graph (``Project.graph_format_problem``),
    plus rejecting graphs with a calculation error. Static imported previews and uncalculated graphs
    appear disabled with an explicit reason so the user knows why they cannot be selected.
    """
    by_uid = {run.uid: run for run in project.runs}
    rows = []
    for index, run in graph_runs(project):
        if run_view(run.method) == "result" and run.result is not None and run.result.figure is None:
            continue
        source = _source_label(run, by_uid)
        if run.calculation_error:
            eligible, reason = False, t("reason_error", error=run.calculation_error)
        else:
            problem = project.graph_format_problem(run)
            if problem is None:
                eligible, reason = True, ""
            elif problem == ui("Calculate the graph first."):
                if run.result is None:
                    eligible, reason = False, t("reason_pending")
                else:
                    eligible, reason = False, t("reason_no_figure")
            else:
                eligible, reason = False, problem
        rows.append(BatchStyleRow(run.uid, index, run.name, source, eligible, reason, run))
    return rows


class BatchFigureStylesDialog(QDialog):
    """Select a saved style and target graphs; ``result`` is ``(selected_uids, preset)`` or ``None``."""

    def __init__(self, parent, project, rows, library, *, current_uid=None):
        super().__init__(parent)
        self.setObjectName("batchFigureStyles")
        self.setWindowTitle(t("title"))
        self.project = project
        self.rows = list(rows)
        self._rows_by_uid = {row.uid: row for row in self.rows}
        self._items_by_uid = {}
        self.library = library
        self.current_uid = current_uid
        self.result = None
        self._preview_figure = None
        self._preview_uid = None
        self._preview_preset_name = None
        self._build()
        self._populate_graphs()
        self._load_library()
        self._refresh_state()
        theme.fit_dialog(self, 860, 620)

    # -- layout -----------------------------------------------------------------------------------
    def _build(self):
        outer = theme.scroll_body(self)
        intro = QLabel(t("intro"))
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self.banner = QLabel()
        self.banner.setObjectName("batchStyleStatus")
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.hide()
        outer.addWidget(self.banner)

        columns = QHBoxLayout()
        outer.addLayout(columns, 1)

        # Left column: saved styles library (read-only) + style settings
        left = QVBoxLayout()
        styles_box = QGroupBox(t("styles"))
        styles_layout = QVBoxLayout(styles_box)
        self.style_list = QListWidget()
        self.style_list.setObjectName("batchStyleList")
        self.style_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.style_list.setMinimumHeight(110)
        self.style_list.currentItemChanged.connect(lambda *_: self._style_changed())
        styles_layout.addWidget(self.style_list, 1)
        self.empty_library = QLabel(t("empty_library"))
        self.empty_library.setObjectName("muted")
        self.empty_library.setWordWrap(True)
        styles_layout.addWidget(self.empty_library)
        left.addWidget(styles_box, 1)

        details_box = QGroupBox(t("details"))
        self.details = QFormLayout(details_box)
        self.details.setObjectName("batchStyleDetails")
        left.addWidget(details_box)
        columns.addLayout(left, 2)

        # Right column: selectable project graphs + mini preview copy
        right = QVBoxLayout()
        graphs_box = QGroupBox(t("graphs"))
        graphs_layout = QVBoxLayout(graphs_box)
        self.graph_tree = QTreeWidget()
        self.graph_tree.setObjectName("batchGraphList")
        self.graph_tree.setRootIsDecorated(False)
        self.graph_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.graph_tree.setMinimumHeight(150)
        self.graph_tree.setHeaderLabels([t("col_graph"), t("col_source"), t("col_status")])
        header = self.graph_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.graph_tree.itemChanged.connect(lambda *_: self._refresh_state())
        self.graph_tree.currentItemChanged.connect(lambda *_: self._update_preview())
        graphs_layout.addWidget(self.graph_tree, 1)

        controls = QHBoxLayout()
        self.select_all_button = QPushButton(t("select_all"))
        self.select_all_button.setObjectName("batchSelectAll")
        self.select_all_button.setAutoDefault(False)
        self.select_all_button.clicked.connect(lambda: self.set_all_checked(True))
        controls.addWidget(self.select_all_button)
        self.select_none_button = QPushButton(t("select_none"))
        self.select_none_button.setObjectName("batchSelectNone")
        self.select_none_button.setAutoDefault(False)
        self.select_none_button.clicked.connect(lambda: self.set_all_checked(False))
        controls.addWidget(self.select_none_button)
        controls.addStretch(1)
        graphs_layout.addLayout(controls)

        self.selection_count = QLabel()
        self.selection_count.setObjectName("batchSelectionCount")
        self.selection_count.setWordWrap(True)
        graphs_layout.addWidget(self.selection_count)
        right.addWidget(graphs_box, 2)

        preview_box = QGroupBox(t("preview"))
        preview_layout = QVBoxLayout(preview_box)
        self.preview_caption = QLabel(t("preview_choose"))
        self.preview_caption.setObjectName("muted")
        self.preview_caption.setWordWrap(True)
        preview_layout.addWidget(self.preview_caption)
        self.preview_image = QLabel()
        self.preview_image.setObjectName("batchMiniPreview")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumSize(220, 140)
        self.preview_image.setFixedHeight(155)
        preview_layout.addWidget(self.preview_image)
        right.addWidget(preview_box, 1)

        columns.addLayout(right, 3)

        box = QDialogButtonBox()
        self.apply_button = box.addButton(t("apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("batchStyleApply")
        self.apply_button.setDefault(True)
        self.cancel_button = box.addButton(t("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.cancel_button.setObjectName("batchStyleCancel")
        self.cancel_button.setAutoDefault(False)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.layout().addWidget(box)

    # -- library ----------------------------------------------------------------------------------
    def _load_library(self):
        try:
            self.library.load()
        except gsp.LibraryError as error:
            self.show_status(t("damaged", reason=preset_message(error), path=str(error.path)), error=True)
        self.style_list.blockSignals(True)
        self.style_list.clear()
        for preset in self.library.presets:
            item = QListWidgetItem(preset["name"])
            item.setData(Qt.ItemDataRole.UserRole, preset["name"])
            accent = preset["style"].get("accent")
            if accent is not None:
                item.setIcon(_swatch(accent))
            self.style_list.addItem(item)
        if self.style_list.count() > 0:
            self.style_list.setCurrentRow(0)
        self.style_list.blockSignals(False)
        self.empty_library.setVisible(not self.library.presets and self.library.problem is None)
        self._render_details()

    def current_preset(self):
        item = self.style_list.currentItem()
        return None if item is None else self.library.get(item.data(Qt.ItemDataRole.UserRole))

    def _style_changed(self):
        if self.library.problem is None:
            self.show_status("")
        self._render_details()
        self._refresh_state()

    def _render_details(self):
        preset = self.current_preset()
        while self.details.rowCount():
            self.details.removeRow(0)
        if preset is None:
            hint = QLabel(t("none_selected"))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self.details.addRow(hint)
            return
        for key, value in preset["style"].items():
            caption, shown = describe(key, value)
            label = QLabel(shown)
            if key == "accent":
                swatch = QLabel()
                swatch.setPixmap(_swatch(value).pixmap(14, 14))
                cell = QWidget()
                row = QHBoxLayout(cell)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(swatch)
                row.addWidget(label, 1)
                self.details.addRow(caption, cell)
            else:
                self.details.addRow(caption, label)

    # -- graph list -------------------------------------------------------------------------------
    def _populate_graphs(self):
        self.graph_tree.blockSignals(True)
        self.graph_tree.clear()
        self._items_by_uid.clear()
        preselected = None
        for row in self.rows:
            item = QTreeWidgetItem([row.name, row.source, t("status_ready") if row.eligible else row.reason])
            item.setData(0, Qt.ItemDataRole.UserRole, row.uid)
            if row.eligible:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                checked = row.uid == self.current_uid
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                if checked:
                    preselected = item
            else:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                for column in (0, 1, 2):
                    item.setToolTip(column, row.reason)
            self.graph_tree.addTopLevelItem(item)
            self._items_by_uid[row.uid] = item
        self.graph_tree.blockSignals(False)
        if preselected is not None:
            self.graph_tree.setCurrentItem(preselected)

    def set_all_checked(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.graph_tree.blockSignals(True)
        for row in self.rows:
            if row.eligible:
                self._items_by_uid[row.uid].setCheckState(0, state)
        self.graph_tree.blockSignals(False)
        self._refresh_state()

    def set_checked_uids(self, uids):
        wanted = set(uids)
        self.graph_tree.blockSignals(True)
        for row in self.rows:
            if row.eligible:
                state = Qt.CheckState.Checked if row.uid in wanted else Qt.CheckState.Unchecked
                self._items_by_uid[row.uid].setCheckState(0, state)
        self.graph_tree.blockSignals(False)
        self._refresh_state()

    def selected_rows(self):
        return [row for row in self.rows if row.eligible
                and self._items_by_uid[row.uid].checkState(0) == Qt.CheckState.Checked]

    def selected_uids(self):
        return [row.uid for row in self.selected_rows()]

    def _refresh_state(self):
        eligible_rows = [row for row in self.rows if row.eligible]
        chosen_rows = self.selected_rows()
        preset = self.current_preset()
        has_eligible = bool(eligible_rows)
        self.select_all_button.setEnabled(has_eligible and len(chosen_rows) < len(eligible_rows))
        self.select_none_button.setEnabled(bool(chosen_rows))

        planned_all = None
        if preset is not None and eligible_rows:
            styles_by_id = {row.uid: row.run.style for row in eligible_rows}
            try:
                planned_all = gsp.plan_preset_batch(styles_by_id, [row.uid for row in eligible_rows], preset)
            except ValueError:
                planned_all = None
        self.graph_tree.blockSignals(True)
        for row in eligible_rows:
            item = self._items_by_uid[row.uid]
            if planned_all is None:
                status = t("status_ready")
            elif row.uid in planned_all:
                status = t("status_update")
            else:
                status = t("status_same")
            item.setText(2, status)
        self.graph_tree.blockSignals(False)

        if not self.rows:
            self.selection_count.setText(t("no_graphs"))
        elif not eligible_rows:
            self.selection_count.setText(t("no_eligible"))
        elif preset is not None and planned_all is not None and chosen_rows:
            changed = sum(1 for row in chosen_rows if row.uid in planned_all)
            unchanged = len(chosen_rows) - changed
            self.selection_count.setText(t("count_plan", selected=len(chosen_rows), eligible=len(eligible_rows),
                                           changed=changed, unchanged=unchanged))
        else:
            self.selection_count.setText(t("count", selected=len(chosen_rows), eligible=len(eligible_rows)))

        self.apply_button.setEnabled(preset is not None and bool(chosen_rows))
        self._update_preview()

    # -- mini preview on an independent figure copy -----------------------------------------------
    def _preview_target_row(self):
        item = self.graph_tree.currentItem()
        if item is not None:
            uid = item.data(0, Qt.ItemDataRole.UserRole)
            row = self._rows_by_uid.get(uid)
            if row is not None and row.eligible and item.checkState(0) == Qt.CheckState.Checked:
                return row
        chosen = self.selected_rows()
        return chosen[0] if chosen else None

    def _clear_preview(self):
        if self._preview_figure is not None:
            try:
                self._preview_figure.clear()
            except Exception:
                pass
            self._preview_figure = None
        self._preview_uid = None
        self._preview_preset_name = None
        self.preview_image.clear()
        self.preview_image.setPixmap(QPixmap())

    def _update_preview(self):
        preset = self.current_preset()
        row = self._preview_target_row()
        if preset is None or row is None:
            self._clear_preview()
            self.preview_caption.setText(t("preview_choose"))
            return
        if (row.uid, preset["name"]) == (self._preview_uid, self._preview_preset_name) and self._preview_figure is not None:
            return
        self._clear_preview()
        copy_figure = None
        try:
            candidate = gsp.apply_preset(row.run.style, preset)
            copy_figure = deepcopy(row.run.result.figure)
            _detach_copied_overlays(copy_figure)
            validate_graph_style(copy_figure.axes[0], candidate)
            apply_style(copy_figure, candidate)
            ratio = max(1.0, float(self.devicePixelRatioF()))
            box_w = max(240, self.preview_image.width() or 360)
            box_h = max(125, self.preview_image.height() or 145)
            image = figure_image(copy_figure, round(box_w * ratio), round(box_h * ratio))
        except Exception as error:  # noqa: BLE001 - show why the preview copy could not be drawn
            if copy_figure is not None:
                try:
                    copy_figure.clear()
                except Exception:
                    pass
            self._clear_preview()
            self.preview_caption.setText(t("preview_error", reason=batch_message(error)))
            return
        self._preview_figure = copy_figure
        self._preview_uid = row.uid
        self._preview_preset_name = preset["name"]
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        self.preview_image.setPixmap(pixmap)
        self.preview_caption.setText(t("preview_of", name=row.name, source=row.source))

    # -- status and closing -----------------------------------------------------------------------
    def show_status(self, text, *, error=False):
        self.banner.setObjectName("errorBanner" if error else "batchStyleStatus")
        self.banner.setStyleSheet("" if error else "padding: 4px 2px;")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner.setVisible(bool(text))

    def accept(self):
        preset = self.current_preset()
        if preset is None:
            self.show_status(t("choose_style"), error=True)
            return
        chosen = self.selected_rows()
        if not chosen:
            self.show_status(t("choose_graphs"), error=True)
            return
        selected_ids = [row.uid for row in chosen]
        styles_by_id = {row.uid: row.run.style for row in chosen}
        try:
            planned = gsp.plan_preset_batch(styles_by_id, selected_ids, preset)
        except ValueError as error:
            self.show_status(batch_message(error), error=True)
            return
        for uid, candidate in planned.items():
            row = self._rows_by_uid[uid]
            problem = self.project.graph_format_problem(row.run)
            if problem:
                self.show_status(t("target_invalid", name=row.name, reason=problem), error=True)
                return
            try:
                validate_graph_style(row.run.result.figure.axes[0], candidate)
            except ValueError as error:
                self.show_status(t("target_invalid", name=row.name, reason=batch_message(error)), error=True)
                return
        self.result = (selected_ids, preset)
        super().accept()

    def reject(self):
        self.result = None
        self._clear_preview()
        super().reject()

    def done(self, code):
        if code != QDialog.DialogCode.Accepted:
            self.result = None
        self._clear_preview()
        super().done(code)


def _detach_copied_overlays(figure):
    """Remove overlay artist references on a deep-copied figure safely before re-applying style."""
    for axes in getattr(figure, "axes", ()):
        for attr in ("_tramastat_references", "_tramastat_annotations", "_tramastat_shapes"):
            for artist in getattr(axes, attr, ()):
                try:
                    artist.remove()
                except ValueError:
                    children = getattr(axes, "_children", None)
                    if isinstance(children, list) and artist in children:
                        children.remove(artist)
            setattr(axes, attr, ())
