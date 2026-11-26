"""Legend formatting on Qt: title, columns, order, frame and entry labels (same options as ``analisi.graph_legend``)."""
from copy import deepcopy
from math import isfinite

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from analisi.data import decimal_comma
from analisi.graph_legend import (MAX_LEGEND_BORDER_WIDTH, MAX_LEGEND_COLUMNS, MAX_LEGEND_TEXT_LENGTH,
                                  collect_legend_entries, is_non_native_figure, legend_entry_key,
                                  validate_legend_options, visible_legends)
from analisi.i18n import tr, translate_message

from .graph_format import Choice, _color_button
from .theme import fit_dialog

FRAME_DEFAULT, FRAME_SHOWN, FRAME_HIDDEN = "Analysis default", "shown", "hidden"
FRAME_LABELS = {FRAME_DEFAULT: "legend_editor.frame.default", FRAME_SHOWN: "legend_editor.frame.shown",
                FRAME_HIDDEN: "legend_editor.frame.hidden"}


def translate_legend_error(error):
    text = str(error)
    translated = translate_message(text, "legend_editor.error.")
    return translated if translated != text else translate_message(text, "graph.error.")


def legend_summary(options):
    return tr("legend_editor.summary_custom") if options else tr("legend_editor.summary_none")


def legend_at(event):
    """Return the clicked legend and the key of the clicked text, if any."""
    canvas = event.canvas
    renderer = getattr(canvas, "renderer", None)
    if renderer is None:
        return None
    point = event.x, event.y
    for legend in reversed(visible_legends(canvas.figure)):
        if legend.get_window_extent(renderer).contains(*point):
            for label in legend.get_texts():
                if label.get_visible() and label.get_window_extent(renderer).contains(*point):
                    return legend, legend_entry_key(canvas.figure, legend, label)
            return legend, None
    return None


def _optional(text, low, high, message, integer=False):
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        value = int(cleaned) if integer else float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if "_" in cleaned or not isfinite(value) or not low <= value <= high:
        raise ValueError(message)
    return value


class LegendEditor(QDialog):
    """``result`` is the canonical ``legend_options`` dictionary after Apply (``{}`` for the defaults)."""

    def __init__(self, parent, figure, options=None, *, entry=None):
        super().__init__(parent)
        self.setWindowTitle(tr("legend_editor.dialog_title"))
        self.initial, self.result = deepcopy(options or {}), None
        self.non_native = is_non_native_figure(figure)
        self.entries = [] if self.non_native else collect_legend_entries(figure)
        self.default_title = ""
        if self.entries:
            legend = self.entries[0].legend
            snapshot = getattr(legend, "_tramastat_legend_snapshot", None)
            self.default_title = snapshot.get("title", "") if snapshot is not None else legend.get_title().get_text()
        self.title_overridden = "title" in self.initial
        keys = {entry.key for entry in self.entries}
        self.hidden_labels = {key: value for key, value in self.initial.get("labels", {}).items() if key not in keys}

        outer = QVBoxLayout(self)
        if self.non_native:
            note = QLabel(tr("legend_editor.hint.non_native"))
            note.setObjectName("errorBanner")
            note.setWordWrap(True)
            outer.addWidget(note)
        body = QWidget()
        column = QVBoxLayout(body)
        general = QGroupBox(tr("legend_editor.section.general"))
        form = QFormLayout(general)
        self.title = QLineEdit(self.initial.get("title", self.default_title))
        form.addRow(tr("legend_editor.field.title"), self.title)
        self.columns = QLineEdit(str(self.initial.get("columns", "")))
        form.addRow(tr("legend_editor.field.columns"), self.columns)
        self.reverse = QCheckBox(tr("legend_editor.field.reverse"))
        self.reverse.setChecked(bool(self.initial.get("reverse", False)))
        form.addRow(self.reverse)
        column.addWidget(general)

        frame = QGroupBox(tr("legend_editor.section.frame"))
        form = QFormLayout(frame)
        initial = FRAME_DEFAULT if "frame" not in self.initial else FRAME_SHOWN if self.initial["frame"] else FRAME_HIDDEN
        self.frame = Choice(tuple(FRAME_LABELS), FRAME_LABELS, initial)
        form.addRow(tr("legend_editor.field.frame"), self.frame)
        self.colors = {}
        for key in ("facecolor", "edgecolor"):
            self.colors[key] = QLineEdit(self.initial.get(key, ""))
            row = QHBoxLayout()
            row.addWidget(self.colors[key], 1)
            row.addWidget(_color_button(self.colors[key]))
            form.addRow(tr(f"legend_editor.field.{key}"), row)
        self.width = QLineEdit("" if "width" not in self.initial else f"{self.initial['width']:g}")
        form.addRow(tr("legend_editor.field.width"), self.width)
        self.alpha = QLineEdit("" if "alpha" not in self.initial else f"{self.initial['alpha']:g}")
        form.addRow(tr("legend_editor.field.alpha"), self.alpha)
        column.addWidget(frame)

        entries = QGroupBox(tr("legend_editor.section.entries"))
        form = QFormLayout(entries)
        self.labels = {}
        for item in self.entries:
            field = self.labels[item.key] = QLineEdit(self.initial.get("labels", {}).get(item.key, ""))
            field.setPlaceholderText(item.label)
            form.addRow(item.display_name, field)
        if not self.entries:
            hint = QLabel(tr("legend_editor.hint.no_legend"))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            form.addRow(hint)
        column.addWidget(entries)
        hint = QLabel(tr("legend_editor.hint.literal"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        column.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("legend_editor.btn.reset"), QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(
            self.reset_fields)
        apply = buttons.addButton(tr("legend_editor.btn.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setEnabled(not self.non_native)
        buttons.addButton(tr("legend_editor.btn.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        apply.setDefault(True)
        apply.setAutoDefault(True)
        fit_dialog(self, 520, 560)
        if hasattr(parent, "show_shortcuts"):
            QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        field = self.labels.get(entry, self.title)
        field.setFocus()
        field.selectAll()
        QTimer.singleShot(0, self, lambda: scroll.ensureWidgetVisible(field))

    def read_options(self):
        if self.non_native:
            raise ValueError(tr("legend_editor.error.non_native"))
        options = {}
        title = self.title.text()
        if len(title) > MAX_LEGEND_TEXT_LENGTH:
            raise ValueError(tr("legend_editor.error.title"))
        if title != self.default_title or self.title_overridden:
            options["title"] = title
        columns = _optional(self.columns.text(), 1, MAX_LEGEND_COLUMNS, tr("legend_editor.error.columns"), True)
        if columns is not None:
            options["columns"] = columns
        if self.frame.value() != FRAME_DEFAULT:
            options["frame"] = self.frame.value() == FRAME_SHOWN
        for key, field in self.colors.items():
            if field.text().strip():
                options[key] = field.text().strip()
        width = _optional(self.width.text(), 0.0, MAX_LEGEND_BORDER_WIDTH, tr("legend_editor.error.width"))
        if width is not None:
            options["width"] = width
        alpha = _optional(self.alpha.text(), 0.0, 1.0, tr("legend_editor.error.alpha"))
        if alpha is not None:
            options["alpha"] = alpha
        if self.reverse.isChecked():
            options["reverse"] = True
        labels = dict(self.hidden_labels)
        for key, field in self.labels.items():
            value = field.text()
            if not value:
                continue
            if len(value) > MAX_LEGEND_TEXT_LENGTH or value.startswith("_"):
                raise ValueError(tr("legend_editor.error.entry_label"))
            labels[key] = value
        if labels:
            options["labels"] = labels
        return validate_legend_options(options)

    def reset_fields(self):
        self.title_overridden, self.hidden_labels = False, {}
        self.title.setText(self.default_title)
        for field in (self.columns, self.width, self.alpha, *self.colors.values(), *self.labels.values()):
            field.clear()
        self.frame.set(FRAME_DEFAULT)
        self.reverse.setChecked(False)
        self.problem.setVisible(False)

    def accept(self):
        try:
            self.result = self.read_options()
        except ValueError as error:
            self.result = None
            self.problem.setText(translate_legend_error(error))
            self.problem.setVisible(True)
            return
        super().accept()
