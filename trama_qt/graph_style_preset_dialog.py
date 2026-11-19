"""Graph → Figure styles…: save the look of a graph as a named style and reuse it on other graphs.

The dialog shows the local style library (``graph_style_presets.PresetLibrary``). Choosing a style previews it
on the graph already on screen with ``apply_style`` — nothing is recalculated. Cancel, Esc or an error bring
back the confirmed figure; Apply hands the complete style to the window, which commits it once with
``MainWindow.commit_style``. Changes to the library (save, import, rename, delete, export) are separate
actions that write the library file at once and never touch the graph.
"""
from copy import deepcopy
from pathlib import Path
import re

from matplotlib.colors import to_hex
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from analisi.i18n import active_language, tr, translate_message
from analisi.presentation import apply_style, validate_graph_style

from . import graph_style_presets as gsp
from . import theme
from .graph_format import FRAME_LABELS, LEGEND_LABELS, choice_text

# Captions of this dialog only (English, Italian). Kept here so the shared catalogs stay untouched.
_TEXT = {
    "action": ("Figure styles…", "Stili di figura…"),
    "title": ("Figure styles", "Stili di figura"),
    "intro": ("Save the colour, fonts, frame, grid and legend of a graph as a named style and reuse it on other "
              "graphs and projects. Titles, axis texts, scales, series, shapes and annotations stay with each "
              "graph.",
              "Salva colore, caratteri, cornice, griglia e legenda di un grafico come stile con nome e riusalo su "
              "altri grafici e progetti. Titoli, testi degli assi, scale, serie, forme e annotazioni restano di "
              "ciascun grafico."),
    "library": ("Styles on this computer", "Stili su questo computer"),
    "empty": ("No saved styles yet. Save the style of this graph or import a style file.",
              "Nessuno stile salvato. Salva lo stile di questo grafico o importa un file di stile."),
    "details": ("Settings in the style", "Impostazioni dello stile"),
    "none_selected": ("Choose a style to see its settings.", "Scegli uno stile per vederne le impostazioni."),
    "preview": ("Preview on the graph", "Anteprima sul grafico"),
    "previewing": ("Previewing “{name}”. Apply keeps it, Cancel restores the graph.",
                   "Anteprima di «{name}». Applica la conferma, Annulla ripristina il grafico."),
    "save_group": ("Save the style of this graph", "Salva lo stile di questo grafico"),
    "name": ("Name", "Nome"),
    "save": ("Save style", "Salva stile"),
    "saved": ("Saved “{name}” in the library.", "«{name}» salvato nella libreria."),
    "import": ("Import…", "Importa…"),
    "export": ("Export…", "Esporta…"),
    "rename": ("Rename…", "Rinomina…"),
    "delete": ("Delete", "Elimina"),
    "apply": ("Apply", "Applica"),
    "cancel": ("Cancel", "Annulla"),
    "replace_title": ("Replace style", "Sostituisci stile"),
    "replace": ("A style called “{name}” already exists. Replace it?",
                "Esiste già uno stile chiamato «{name}». Sostituirlo?"),
    "delete_ask": ("Delete “{name}” from the library? Graphs that already use it keep their look.",
                   "Eliminare «{name}» dalla libreria? I grafici che lo usano già mantengono il loro aspetto."),
    "deleted": ("Deleted “{name}”.", "«{name}» eliminato."),
    "renamed": ("Renamed to “{name}”.", "Rinominato in «{name}»."),
    "imported": ("Imported “{name}”.", "«{name}» importato."),
    "exported": ("Exported “{name}”.", "«{name}» esportato."),
    "new_name": ("New name", "Nuovo nome"),
    "file_filter": ("Trama figure style (*.json)", "Stile di figura Trama (*.json)"),
    "import_title": ("Import figure style", "Importa stile di figura"),
    "export_title": ("Export figure style", "Esporta stile di figura"),
    "damaged": ("{reason}\nFile: {path}", "{reason}\nFile: {path}"),
    "set_aside": ("Set the damaged file aside", "Metti da parte il file danneggiato"),
    "set_aside_ask": ("Rename the damaged library to keep it for recovery and start an empty one?",
                      "Rinominare la libreria danneggiata per conservarla e ripartire da una vuota?"),
    "set_aside_done": ("The damaged library was kept as {name}.",
                       "La libreria danneggiata è stata conservata come {name}."),
    "write_failed": ("The style library could not be saved: {reason}. The file on disk was not changed.",
                     "Non è stato possibile salvare la libreria degli stili: {reason}. Il file su disco non è "
                     "cambiato."),
    "export_failed": ("The style could not be exported: {reason}.",
                      "Non è stato possibile esportare lo stile: {reason}."),
    "graph_invalid": ("This style cannot be used on this graph: {reason}",
                      "Questo stile non si può usare su questo grafico: {reason}"),
    "choose": ("Choose a style to apply.", "Scegli uno stile da applicare."),
    "applied": ("Figure style applied.", "Stile di figura applicato."),
    "changed": ("The graph changed while the figure styles were open. Nothing was applied.",
                "Il grafico è cambiato mentre gli stili di figura erano aperti. Non è stato applicato nulla."),
    "yes": ("on", "sì"),
    "no": ("off", "no"),
    "pt": ("{size} pt", "{size} pt"),
    "field.accent": ("Accent colour", "Colore principale"),
}
# Engine messages of ``graph_style_presets`` (English) shown in Italian.
_MESSAGES_IT = {
    "Enter a style name.": "Inserisci un nome per lo stile.",
    "Style names are limited to 64 characters.": "Il nome dello stile può avere al massimo 64 caratteri.",
    "Style names cannot contain line breaks or control characters.":
        "Il nome dello stile non può contenere a capo o caratteri di controllo.",
    "Style names cannot start or end with spaces.": "Il nome dello stile non può iniziare o finire con spazi.",
    "This is not a Trama figure style.": "Questo non è uno stile di figura di Trama.",
    "This figure style was saved by a newer or unknown version of Trama.":
        "Questo stile di figura è stato salvato da una versione di Trama più recente o sconosciuta.",
    "A figure style can only contain colour, font, frame, grid and legend settings.":
        "Uno stile di figura può contenere solo impostazioni di colore, caratteri, cornice, griglia e legenda.",
    "A figure style needs at least one setting.": "Uno stile di figura deve avere almeno un'impostazione.",
    "The figure style contains a value that cannot be saved.": "Lo stile di figura contiene un valore non salvabile.",
    "This graph uses the analysis defaults: change its colour, fonts, frame, grid or legend first.":
        "Questo grafico usa i valori predefiniti dell'analisi: cambia prima colore, caratteri, cornice, griglia "
        "o legenda.",
    "A figure style file is limited to 64 KiB.": "Un file di stile di figura può pesare al massimo 64 KiB.",
    "The file is not valid JSON (it may be truncated).": "Il file non è un JSON valido (potrebbe essere troncato).",
    "The style library holds at most 100 styles. Delete one first.":
        "La libreria degli stili contiene al massimo 100 stili. Eliminane prima uno.",
    "Set the damaged style library aside before changing it.":
        "Metti da parte la libreria danneggiata prima di modificarla.",
    "The style library is damaged and was not changed":
        "La libreria degli stili è danneggiata e non è stata modificata",
    "The style library could not be read": "Non è stato possibile leggere la libreria degli stili",
    "The file could not be read": "Non è stato possibile leggere il file",
    "Invalid graph style.": "Stile del grafico non valido.",
}
FIELD_CAPTIONS = {"font_family": "graph.field.font_family", "title_size": "graph.field.font_title",
                  "label_size": "graph.field.font_labels", "tick_size": "graph.field.font_ticks",
                  "legend_size": "graph.field.font_legend", "frame": "graph.field.frame",
                  "grid": "graph.field.major_grid", "grid_minor": "graph.field.minor_grid",
                  "legend": "graph.field.legend_position"}
FONT_LABELS = {"sans-serif": ("Sans serif", "Senza grazie"), "serif": ("Serif", "Con grazie"),
               "monospace": ("Monospace", "Monospaziato")}


def t(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


# Reasons a library cannot be read (after "…was not changed: "), shown in Italian.
_REASONS_IT = (
    (re.compile(r"the file is not valid JSON \(line (\d+), column (\d+)\)\.$"),
     "il file non è un JSON valido (riga {0}, colonna {1})."),
    (re.compile(r"the file is not UTF-8 text\.$"), "il file non è testo UTF-8."),
    (re.compile(r"the file is larger than a style library can be\.$"),
     "il file è più grande di quanto possa essere una libreria di stili."),
    (re.compile(r"this is not a Trama style library\.$"), "non è una libreria di stili di Trama."),
    (re.compile(r"the library was saved by a newer or unknown version of Trama\.$"),
     "la libreria è stata salvata da una versione di Trama più recente o sconosciuta."),
    (re.compile(r"a library holds at most (\d+) styles\.$"), "una libreria contiene al massimo {0} stili."),
    (re.compile(r"style (\d+): the name (.*) is used twice\.$"), "stile {0}: il nome {1} è usato due volte."),
    (re.compile(r"style (\d+): (.*)$"), "stile {0}: {1}"),
)


def message(error):
    """An error from the presets module or the renderer, in the active language."""
    text = str(error)
    if active_language() != "it":
        return text
    for english, italian in _MESSAGES_IT.items():
        if text == english:
            return italian
        if text.startswith(english + ": "):
            return f"{italian}: {_reason(text[len(english) + 2:])}"
    return translate_message(text)


def _reason(text):
    for pattern, italian in _REASONS_IT:
        match = pattern.match(text)
        if match:
            groups = list(match.groups())
            if italian.startswith("stile {0}: {1}"):
                groups[1] = message(groups[1])
            return italian.format(*groups)
    return translate_message(text)


def describe(key, value):
    """The caption and the displayed value of one preset field (canonical value → active language)."""
    if key == "accent":
        try:
            shown = to_hex(value, keep_alpha=False).upper()
        except ValueError:
            shown = str(value)
        return t("field.accent"), shown
    caption = tr(FIELD_CAPTIONS[key])
    if key == "font_family":
        english, italian = FONT_LABELS[value]
        return caption, italian if active_language() == "it" else english
    if key.endswith("_size"):
        return caption, t("pt", size=f"{value:g}")
    if key in ("grid", "grid_minor"):
        return caption, t("yes" if value else "no")
    if key == "legend":
        return caption, choice_text(LEGEND_LABELS, value)
    if key == "frame":
        return caption, choice_text(FRAME_LABELS, value)
    return caption, str(value)


class GraphStylePresetDialog(QDialog):
    """``result`` is the complete style to commit after Apply, or None."""

    def __init__(self, parent, figure, canvas, confirmed, library):
        super().__init__(parent)
        self.setObjectName("graphStylePresets")
        self.setWindowTitle(t("title"))
        self.figure, self.canvas = figure, canvas
        self.axes = figure.axes[0]
        self.confirmed = deepcopy(confirmed or {})
        self.library = library
        self.result = None
        self.previewed = None  # Name of the style drawn on the figure, or None for the confirmed one.
        self._build()
        self._load_library()
        theme.fit_dialog(self, 760, 560)

    # -- layout ---------------------------------------------------------------------------------
    def _build(self):
        outer = theme.scroll_body(self)
        intro = QLabel(t("intro"))
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        self.banner = QLabel()
        self.banner.setObjectName("presetStatus")
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.hide()
        outer.addWidget(self.banner)
        self.set_aside_button = QPushButton(t("set_aside"))
        self.set_aside_button.setObjectName("presetSetAside")
        self.set_aside_button.setAutoDefault(False)
        self.set_aside_button.clicked.connect(self.set_aside)
        self.set_aside_button.hide()
        outer.addWidget(self.set_aside_button, 0, Qt.AlignmentFlag.AlignLeft)

        columns = QHBoxLayout()
        outer.addLayout(columns, 1)
        left = QGroupBox(t("library"))
        left_layout = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setObjectName("presetList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(120)
        self.list.currentItemChanged.connect(lambda *_: self._selected())
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        left_layout.addWidget(self.list, 1)
        self.empty = QLabel(t("empty"))
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        left_layout.addWidget(self.empty)
        tools = QHBoxLayout()
        self.buttons = {}
        for key, handler in (("import", self.import_preset), ("export", self.export_preset),
                             ("rename", self.rename_preset), ("delete", self.delete_preset)):
            button = QPushButton(t(key))
            button.setObjectName("preset_" + key)
            button.setAutoDefault(False)
            button.clicked.connect(handler)
            tools.addWidget(button)
            self.buttons[key] = button
        left_layout.addLayout(tools)
        columns.addWidget(left, 1)

        right = QVBoxLayout()
        details = QGroupBox(t("details"))
        self.details = QFormLayout(details)
        self.details.setObjectName("presetDetails")
        right.addWidget(details, 1)
        self.preview = QCheckBox(t("preview"))
        self.preview.setObjectName("presetPreview")
        self.preview.setChecked(True)
        self.preview.toggled.connect(lambda *_: self._selected())
        right.addWidget(self.preview)
        save = QGroupBox(t("save_group"))
        save_layout = QFormLayout(save)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.name.setObjectName("presetName")
        self.name.setMaxLength(gsp.MAX_NAME + 16)  # Spaces around the name are trimmed, not counted.
        self.name.textEdited.connect(lambda *_: self._name_problem(None))
        self.name.returnPressed.connect(self.save_preset)
        line.addWidget(self.name, 1)
        self.buttons["save"] = QPushButton(t("save"))
        self.buttons["save"].setObjectName("preset_save")
        self.buttons["save"].setAutoDefault(False)
        self.buttons["save"].clicked.connect(self.save_preset)
        line.addWidget(self.buttons["save"])
        save_layout.addRow(t("name"), row)
        self.name_error = QLabel()
        self.name_error.setObjectName("presetNameError")
        self.name_error.setWordWrap(True)
        self.name_error.setStyleSheet(f"color: {theme.T['error']};")
        self.name_error.hide()
        save_layout.addRow(self.name_error)
        right.addWidget(save)
        columns.addLayout(right, 1)

        box = QDialogButtonBox()
        self.apply_button = box.addButton(t("apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("presetApply")
        self.apply_button.setDefault(True)
        cancel = box.addButton(t("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setObjectName("presetCancel")
        cancel.setAutoDefault(False)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.layout().addWidget(box)

    def keyPressEvent(self, event):
        # Enter in the name field saves the style; it must not also apply and close the dialog.
        # focusWidget() also holds while the dialog is not the active window (tests, a second monitor).
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.focusWidget() is self.name:
            event.accept()
            return
        super().keyPressEvent(event)

    # -- library --------------------------------------------------------------------------------
    def _load_library(self, select=None):
        try:
            self.library.load()
        except gsp.LibraryError as error:
            self.show_status(t("damaged", reason=message(error), path=str(error.path)), error=True)
            self.set_aside_button.show()
        else:
            self.set_aside_button.hide()
        self._fill(select)

    def _fill(self, select=None):
        current = select or (self.list.currentItem().data(Qt.ItemDataRole.UserRole)
                             if self.list.currentItem() else None)
        self.list.blockSignals(True)
        self.list.clear()
        chosen = None
        for preset in self.library.presets:
            item = QListWidgetItem(preset["name"])
            item.setData(Qt.ItemDataRole.UserRole, preset["name"])
            accent = preset["style"].get("accent")
            if accent is not None:
                item.setIcon(_swatch(accent))
            self.list.addItem(item)
            if current is not None and gsp.name_key(preset["name"]) == gsp.name_key(current):
                chosen = item
        self.list.blockSignals(False)
        self.empty.setVisible(not self.library.presets and self.library.problem is None)
        damaged = self.library.problem is not None
        self.buttons["save"].setEnabled(not damaged)
        self.buttons["import"].setEnabled(not damaged)
        self.name.setEnabled(not damaged)
        if chosen is not None:
            self.list.setCurrentItem(chosen)
        self._selected()

    def current_preset(self):
        item = self.list.currentItem()
        return None if item is None else self.library.get(item.data(Qt.ItemDataRole.UserRole))

    def _selected(self):
        preset = self.current_preset()
        has = preset is not None
        for key in ("export", "rename", "delete"):
            self.buttons[key].setEnabled(has and (key == "export" or self.library.problem is None))
        self.apply_button.setEnabled(has)
        while self.details.rowCount():
            self.details.removeRow(0)
        if not has:
            hint = QLabel(t("none_selected"))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self.details.addRow(hint)
            self._restore()
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
        if self.preview.isChecked():
            self._preview(preset)
        else:
            self._restore()

    # -- preview ----------------------------------------------------------------------------------
    def candidate(self, preset):
        """The complete style this preset gives the graph, checked against the figure on screen."""
        style = gsp.apply_preset(self.confirmed, preset)
        validate_graph_style(self.axes, style)
        return style

    def _preview(self, preset):
        try:
            style = self.candidate(preset)
            apply_style(self.figure, style)
        except ValueError as error:
            self._restore()
            self.show_status(t("graph_invalid", reason=message(error)), error=True)
            return False
        self.previewed = preset["name"]
        self._draw()
        self.show_status(t("previewing", name=preset["name"]))
        return True

    def _restore(self):
        """Draw the confirmed style again (after Cancel, an error or when the preview is turned off)."""
        if self.previewed is None:
            return
        self.previewed = None
        try:
            apply_style(self.figure, deepcopy(self.confirmed))
        except ValueError:
            pass
        self._draw()
        if self.library.problem is None:
            self.show_status("")

    def _draw(self):
        if self.canvas is not None:
            self.canvas.draw_idle()

    def show_status(self, text, *, error=False):
        self.banner.setObjectName("errorBanner" if error else "presetStatus")
        self.banner.setStyleSheet("" if error else "padding: 4px 2px;")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner.setVisible(bool(text))

    def _name_problem(self, text):
        self.name_error.setText(text or "")
        self.name_error.setVisible(bool(text))
        self.name.setProperty("invalid", bool(text))
        self.name.setStyleSheet(f"border: 1px solid {theme.T['error']};" if text else "")

    # -- closing ----------------------------------------------------------------------------------
    def accept(self):
        preset = self.current_preset()
        if preset is None:
            self.show_status(t("choose"), error=True)
            return
        try:
            self.result = self.candidate(preset)
        except ValueError as error:
            self.result = None
            self._restore()
            self.show_status(t("graph_invalid", reason=message(error)), error=True)
            return
        super().accept()

    def reject(self):
        self.result = None
        self._restore()
        super().reject()

    def done(self, code):
        if code != QDialog.DialogCode.Accepted:
            self.result = None
            self._restore()
        super().done(code)

    # -- library actions (each one writes the library on its own) --------------------------------
    def _ask(self, title, text):
        answer = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _store(self, preset):
        """Save ``preset``; an existing name (ignoring case) is replaced only after confirmation."""
        try:
            return self.library.save(preset)
        except FileExistsError as existing:
            if not self._ask(t("replace_title"), t("replace", name=str(existing))):
                return None
            return self.library.save(preset, replace=True)

    def _write(self, action):
        try:
            return action()
        except OSError as error:
            self.show_status(t("write_failed", reason=error.strerror or str(error)), error=True)
        except ValueError as error:
            self.show_status(message(error), error=True)
        return None

    def save_preset(self):
        if self.library.problem is not None:
            return
        try:
            preset = gsp.extract_preset(self.name.text(), self.confirmed)
        except ValueError as error:
            self._name_problem(message(error))
            self.name.setFocus()
            return
        self._name_problem(None)
        saved = self._write(lambda: self._store(preset))
        if saved is None:
            return
        self.name.clear()
        self._fill(saved["name"])
        self.show_status(t("saved", name=saved["name"]))

    def import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, t("import_title"), "", t("file_filter"))
        if path:
            self.import_path(path)

    def import_path(self, path):
        try:
            preset = gsp.read_preset_file(path)
        except ValueError as error:
            self.show_status(message(error), error=True)
            return None
        saved = self._write(lambda: self._store(preset))
        if saved is not None:
            self._fill(saved["name"])
            self.show_status(t("imported", name=saved["name"]))
        return saved

    def export_preset(self):
        preset = self.current_preset()
        if preset is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("export_title"), _file_name(preset["name"]), t("file_filter"))
        if path:
            self.export_path(path)

    def export_path(self, path):
        preset = self.current_preset()
        try:
            gsp.write_preset_file(path, preset)
        except OSError as error:
            self.show_status(t("export_failed", reason=error.strerror or str(error)), error=True)
            return False
        self.show_status(t("exported", name=preset["name"]))
        return True

    def rename_preset(self):
        preset = self.current_preset()
        if preset is None:
            return
        name, ok = QInputDialog.getText(self, t("rename").rstrip("…"), t("new_name"), text=preset["name"])
        if ok:
            self.rename_to(name)

    def rename_to(self, name):
        old = self.current_preset()["name"]
        try:
            name = gsp.clean_name(name)
        except ValueError as error:
            self.show_status(message(error), error=True)
            return False

        def rename():
            try:
                self.library.rename(old, name)
            except FileExistsError as existing:
                if not self._ask(t("replace_title"), t("replace", name=str(existing))):
                    return None
                self.library.rename(old, name, replace=True)
            return name

        if self._write(rename) is None:
            return False
        self.previewed = self.previewed and name
        self._fill(name)
        self.show_status(t("renamed", name=name))
        return True

    def delete_preset(self):
        preset = self.current_preset()
        if preset is None or not self._ask(t("delete"), t("delete_ask", name=preset["name"])):
            return False
        if self._write(lambda: self.library.delete(preset["name"]) or True) is None:
            return False
        self._restore()
        self._fill()
        self.show_status(t("deleted", name=preset["name"]))
        return True

    def set_aside(self):
        if not self._ask(t("set_aside"), t("set_aside_ask")):
            return
        try:
            moved = self.library.set_aside()
        except OSError as error:
            self.show_status(t("write_failed", reason=error.strerror or str(error)), error=True)
            return
        self.set_aside_button.hide()
        self._fill()
        self.show_status(t("set_aside_done", name=moved.name))


def _swatch(color):
    pixmap = QPixmap(14, 14)
    try:
        pixmap.fill(QColor(to_hex(color, keep_alpha=False)))
    except ValueError:
        pixmap.fill(Qt.GlobalColor.transparent)
    return QIcon(pixmap)


def _file_name(name):
    safe = "".join(char if char.isalnum() or char in " -_." else "_" for char in name).strip(" .") or "style"
    return str(Path(safe + ".json"))
