"""Axis guides (extra ticks, labels, grid lines) and shaded bands on Qt.

Same records and validation as ``analisi.axis_guides``; the captions are the catalog keys of the classic
dialog (``analisi.axis_guides_dialog`` needs Tk, so its label tables are repeated here).
"""
from copy import deepcopy
from math import isfinite

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from analisi.axis_guides import (BAND_HATCHES, DEFAULT_BAND_ALPHA, DEFAULT_GUIDE_COLOR, DEFAULT_GUIDE_SIDE,
                                 DEFAULT_GUIDE_STYLE, DEFAULT_GUIDE_WIDTH, GUIDE_AXES, GUIDE_SIDES, GUIDE_STYLES,
                                 MAX_BANDS, MAX_GUIDES_TOTAL, axis_supports_guides, is_native_plot_axes,
                                 new_guide_id, normalise_bands, normalise_guides, validate_axis_guides_domain)
from analisi.data import decimal_comma
from analisi.i18n import tr, translate_message

from .graph_format import Choice, _color_button

AXIS_LABELS = {"x": "axis_guides.axis.x", "y": "axis_guides.axis.y"}
STYLE_LABELS = {"-": "axis_guides.style.solid", "--": "axis_guides.style.dashed", ":": "axis_guides.style.dotted",
                "-.": "axis_guides.style.dash_dot"}
SIDE_LABELS = {"primary": "axis_guides.side.primary", "opposite": "axis_guides.side.opposite"}
HATCH_LABELS = {"": "axis_guides.hatch.none", "/": "axis_guides.hatch.slash", "\\": "axis_guides.hatch.backslash",
                "|": "axis_guides.hatch.pipe", "-": "axis_guides.hatch.dash", "+": "axis_guides.hatch.plus",
                "x": "axis_guides.hatch.cross", ".": "axis_guides.hatch.dot", "o": "axis_guides.hatch.circle"}


def translate_guide_error(error):
    text = str(error)
    translated = translate_message(text, "axis_guides.error.")
    return translated if translated != text else translate_message(text, "graph.error.")


def _num(value):
    return f"{float(value):g}"


def _float(text, message):
    cleaned = text.strip()
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if not cleaned or "_" in cleaned or not isfinite(value):
        raise ValueError(message)
    return value


def _scale(axes, overrides, dimension):
    return (overrides or {}).get(dimension) or getattr(axes, dimension + "axis").get_scale()


def _scales(axes, overrides):
    return {"xscale": _scale(axes, overrides, "x"), "yscale": _scale(axes, overrides, "y")}


def _default_axis(axes, overrides):
    for dimension in GUIDE_AXES:
        if axis_supports_guides(axes, dimension, (overrides or {}).get(dimension)):
            return dimension
    return "y"


class _RecordEditor(QDialog):
    """A form for one guide or band; ``result`` is the canonical record after OK."""

    def __init__(self, parent, axes, title, overrides):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.axes, self.overrides, self.result = axes, overrides, None
        self.form = QFormLayout(self)
        self.fields = {}

    def choice(self, key, values, labels, value):
        self.fields[key] = Choice(values, labels, value)
        self.form.addRow(tr(f"axis_guides.field.{key}"), self.fields[key])

    def entry(self, key, value):
        self.fields[key] = QLineEdit(value)
        self.form.addRow(tr(f"axis_guides.field.{key}"), self.fields[key])

    def color(self, key, value):
        self.fields[key] = QLineEdit(value)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.fields[key], 1)
        line.addWidget(_color_button(self.fields[key]))
        self.form.addRow(tr(f"axis_guides.field.{key}"), row)

    def check(self, key, value):
        self.fields[key] = QCheckBox(tr(f"axis_guides.field.{key}"))
        self.fields[key].setChecked(bool(value))
        self.form.addRow(self.fields[key])

    def finish(self):
        hint = QLabel(tr("axis_guides.note.decimal_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.form.addRow(hint)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        self.form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("axis_guides.btn.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("axis_guides.btn.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)

    def text(self, key):
        return self.fields[key].text()

    def accept(self):
        try:
            self.result = self.read_record()
        except ValueError as error:
            self.problem.setText(translate_guide_error(error))
            self.problem.setVisible(True)
            return
        super().accept()


class GuideEditor(_RecordEditor):
    def __init__(self, parent, axes, record=None, overrides=None):
        super().__init__(parent, axes, tr("axis_guides.guide.edit_title" if record else "axis_guides.guide.add_title"),
                         overrides)
        axis = _default_axis(axes, overrides)
        self.record = deepcopy(record) if record else {
            "id": new_guide_id(), "axis": axis, "value": 1.0 if _scale(axes, overrides, axis) == "log" else 0.0,
            "tick": False, "line": True, "label": "", "color": DEFAULT_GUIDE_COLOR, "width": DEFAULT_GUIDE_WIDTH,
            "style": DEFAULT_GUIDE_STYLE, "visible": True}
        r = self.record
        self.choice("axis", GUIDE_AXES, AXIS_LABELS, r["axis"])
        self.entry("value", _num(r["value"]))
        for key, default in (("tick", False), ("line", True), ("visible", True)):
            self.check(key, r.get(key, default))
        self.entry("label", r.get("label", ""))
        self.color("color", r.get("color", DEFAULT_GUIDE_COLOR))
        self.entry("width", _num(r.get("width", DEFAULT_GUIDE_WIDTH)))
        self.choice("style", GUIDE_STYLES, STYLE_LABELS, r.get("style", DEFAULT_GUIDE_STYLE))
        self.choice("side", GUIDE_SIDES, SIDE_LABELS, r.get("side", DEFAULT_GUIDE_SIDE))
        self.color("label_color", r.get("label_color", ""))
        self.entry("font_size", "" if r.get("font_size") is None else _num(r["font_size"]))
        self.finish()

    def read_record(self):
        raw = {"id": self.record["id"], "axis": self.fields["axis"].value(),
               "value": _float(self.text("value"), tr("axis_guides.error.guide_value")),
               "tick": self.fields["tick"].isChecked(), "line": self.fields["line"].isChecked(),
               "visible": self.fields["visible"].isChecked(), "label": self.text("label"),
               "color": self.text("color").strip(),
               "width": _float(self.text("width"), tr("axis_guides.error.guide_width")),
               "style": self.fields["style"].value()}
        side = self.fields["side"].value()
        if side != DEFAULT_GUIDE_SIDE or "side" in self.record:
            raw["side"] = side
        if self.text("label_color").strip():
            raw["label_color"] = self.text("label_color").strip()
        if self.text("font_size").strip():
            raw["font_size"] = _float(self.text("font_size"), tr("axis_guides.error.guide_font_size"))
        record = normalise_guides([raw])[0]
        validate_axis_guides_domain(self.axes, [record], (), **_scales(self.axes, self.overrides))
        return record


class BandEditor(_RecordEditor):
    def __init__(self, parent, axes, record=None, overrides=None):
        super().__init__(parent, axes, tr("axis_guides.band.edit_title" if record else "axis_guides.band.add_title"),
                         overrides)
        axis = _default_axis(axes, overrides)
        log = _scale(axes, overrides, axis) == "log"
        self.record = deepcopy(record) if record else {
            "id": new_guide_id(), "axis": axis, "lower": 1.0 if log else 0.0, "upper": 10.0 if log else 1.0,
            "color": "#ccddee", "alpha": DEFAULT_BAND_ALPHA, "hatch": "", "visible": True}
        r = self.record
        self.choice("axis", GUIDE_AXES, AXIS_LABELS, r["axis"])
        self.entry("lower", _num(r["lower"]))
        self.entry("upper", _num(r["upper"]))
        self.color("color", r["color"])
        self.entry("alpha", _num(r.get("alpha", DEFAULT_BAND_ALPHA)))
        self.choice("hatch", BAND_HATCHES, HATCH_LABELS, r.get("hatch", ""))
        self.check("visible", r.get("visible", True))
        self.finish()

    def read_record(self):
        bounds = tr("axis_guides.error.band_bounds")
        raw = {"id": self.record["id"], "axis": self.fields["axis"].value(),
               "lower": _float(self.text("lower"), bounds), "upper": _float(self.text("upper"), bounds),
               "color": self.text("color").strip(),
               "alpha": _float(self.text("alpha"), tr("axis_guides.error.band_alpha")),
               "hatch": self.fields["hatch"].value(), "visible": self.fields["visible"].isChecked()}
        record = normalise_bands([raw])[0]
        validate_axis_guides_domain(self.axes, (), [record], **_scales(self.axes, self.overrides))
        return record


class _ListDialog(QDialog):
    """The guides or bands of one graph; ``result`` is the validated list after Apply."""

    limit, editor, columns, title = 0, None, (), ""

    def __init__(self, parent, axes, records, overrides=None):
        super().__init__(parent)
        self.setWindowTitle(tr(self.title))
        self.axes, self.overrides = axes, dict(overrides or {})
        self.records, self.result = deepcopy(list(records or [])), None
        outer = QVBoxLayout(self)
        supported, note = self._support()
        self.supported = supported
        if note:
            label = QLabel(note)
            label.setObjectName("muted" if supported else "errorBanner")
            label.setWordWrap(True)
            outer.addWidget(label)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels([tr(key) for key in self.columns])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        self.table.itemSelectionChanged.connect(self._buttons)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, handler in (("add", self.add), ("edit", self.edit), ("duplicate", self.duplicate),
                             ("remove", self.remove)):
            button = QPushButton(tr(f"axis_guides.btn.{key}"))
            button.clicked.connect(handler)
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        outer.addLayout(row)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("axis_guides.btn.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("axis_guides.btn.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.fill(0 if self.records else None)
        self.resize(640, 380)

    def _support(self):
        if not is_native_plot_axes(self.axes):
            return False, tr("axis_guides.note.unsupported_both")
        x_ok = axis_supports_guides(self.axes, "x", self.overrides.get("x"))
        y_ok = axis_supports_guides(self.axes, "y", self.overrides.get("y"))
        if not x_ok and not y_ok:
            return False, tr("axis_guides.note.unsupported_both")
        if not x_ok:
            return True, tr("axis_guides.note.unsupported_one", axis="X", other="Y")
        if not y_ok:
            return True, tr("axis_guides.note.unsupported_one", axis="Y", other="X")
        return True, ""

    def fill(self, selected=None):
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            for column, text in enumerate(self.row(record)):
                self.table.setItem(index, column, QTableWidgetItem(str(text)))
        if selected is not None and self.records:
            self.table.selectRow(max(0, min(selected, len(self.records) - 1)))
        self.problem.setVisible(False)
        self._buttons()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _buttons(self):
        chosen, full = self.selected() is not None, len(self.records) >= self.limit
        states = {"add": self.supported and not full, "edit": self.supported and chosen,
                  "duplicate": self.supported and chosen and not full, "remove": chosen}
        for key, enabled in states.items():
            self.buttons[key].setEnabled(enabled)

    def _open(self, record=None):
        dialog = self.editor(self, self.axes, record, self.overrides)
        return dialog.result if dialog.exec() == QDialog.DialogCode.Accepted else None

    def add(self):
        if self.supported and len(self.records) < self.limit:
            record = self._open()
            if record is not None:
                self.records.append(record)
                self.fill(len(self.records) - 1)

    def edit(self):
        index = self.selected()
        if index is not None and self.supported:
            record = self._open(self.records[index])
            if record is not None:
                self.records[index] = record
                self.fill(index)

    def duplicate(self):
        index = self.selected()
        if index is not None and len(self.records) < self.limit:
            copied = deepcopy(self.records[index])
            copied["id"] = new_guide_id()
            self.records.insert(index + 1, copied)
            self.fill(index + 1)

    def remove(self):
        index = self.selected()
        if index is not None:
            del self.records[index]
            self.fill(index)

    def accept(self):
        try:
            self.result = self.validate(self.records)
        except ValueError as error:
            self.problem.setText(translate_guide_error(error))
            self.problem.setVisible(True)
            return
        super().accept()


def _yes(value):
    return tr("axis_guides.yes") if value else tr("axis_guides.no")


class AxisGuidesDialog(_ListDialog):
    limit, editor, title = MAX_GUIDES_TOTAL, GuideEditor, "axis_guides.guides.title"
    columns = ("axis_guides.col.axis", "axis_guides.col.value", "axis_guides.col.tick", "axis_guides.col.line",
               "axis_guides.col.label", "axis_guides.col.side", "axis_guides.col.visible")

    @staticmethod
    def row(record):
        return (record["axis"].upper(), _num(record["value"]), _yes(record.get("tick", False)),
                _yes(record.get("line", True)), record.get("label", ""),
                tr(SIDE_LABELS[record.get("side", DEFAULT_GUIDE_SIDE)]), _yes(record.get("visible", True)))

    def validate(self, records):
        records = normalise_guides(records)
        validate_axis_guides_domain(self.axes, records, (), **_scales(self.axes, self.overrides))
        return records


class AxisBandsDialog(_ListDialog):
    limit, editor, title = MAX_BANDS, BandEditor, "axis_guides.bands.title"
    columns = ("axis_guides.col.axis", "axis_guides.col.lower", "axis_guides.col.upper", "axis_guides.col.color",
               "axis_guides.col.alpha", "axis_guides.col.hatch", "axis_guides.col.visible")

    @staticmethod
    def row(record):
        return (record["axis"].upper(), _num(record["lower"]), _num(record["upper"]), record["color"],
                _num(record.get("alpha", DEFAULT_BAND_ALPHA)),
                tr(HATCH_LABELS.get(record.get("hatch", ""), "axis_guides.hatch.none")),
                _yes(record.get("visible", True)))

    def validate(self, records):
        records = normalise_bands(records)
        validate_axis_guides_domain(self.axes, (), records, **_scales(self.axes, self.overrides))
        return records
