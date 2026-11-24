"""Lines, rectangles and ellipses drawn on a graph, on Qt (same records as ``analisi.graph_shapes``)."""
from copy import deepcopy
import uuid

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from analisi.data import decimal_comma
from analisi.graph_shapes import (ARROW_HEADS, ARROW_SIZE, ARROW_STYLES, HATCHES, KINDS, LAYERS, LINE_STYLES,
                                  MAX_SHAPES, OBJECT_KEYS, UNITS, on_axis_domain, validate_shape)
from analisi.i18n import tr
from analisi.shape_objects import duplicate_object, is_locked, object_key, selected_objects

from . import theme
from .graph_format import Choice, _color_button

DEFAULT_SHAPE = {"kind": "line", "units": "axes", "points": [[.2, .3], [.8, .7]], "stroke": "#216a94",
                 "width": 1.5, "line_style": "solid", "fill": None, "alpha": 1.0, "layer": "above"}
CHOICES = {"kind": KINDS, "units": UNITS, "line_style": LINE_STYLES, "layer": LAYERS,
           "arrow_heads": ARROW_HEADS, "arrow_style": ARROW_STYLES, "hatch": HATCHES}
OPTION_DEFAULTS = {"arrow_heads": "none", "arrow_style": "open", "arrow_size": ARROW_SIZE, "hatch": "none"}
POINTS = ("x1", "y1", "x2", "y2")
# Engine messages (English, from ``validate_shape``) and their catalog keys, as in the classic dialog.
ENGINE_ERRORS = (
    ("pattern color", "shape.error.hatch_color"), ("arrowhead size", "shape.error.arrow_size"),
    ("arrowhead style", "shape.error.arrow_style"), ("for the arrowheads", "shape.error.arrow_heads"),
    ("fill pattern", "shape.error.hatch"), ("arrowhead settings require", "shape.error.kind"),
    ("shape kind", "shape.error.kind"), ("axes or data coordinates", "shape.error.units"),
    ("finite x and y", "shape.error.coordinates"), ("plot fractions", "shape.error.fractions"),
    ("distinct endpoints", "shape.error.line_zero"), ("positive width and height", "shape.error.box_zero"),
    ("stroke color", "shape.error.stroke"), ("stroke width", "shape.error.width"),
    ("line style", "shape.error.line_style"), ("fill", "shape.error.fill"), ("opacity", "shape.error.alpha"),
    ("shape layer", "shape.error.layer"),
)


def _num(value):
    return f"{value:g}"


def _parse(text, key):
    try:
        value = float(decimal_comma(text.strip()))
    except (TypeError, ValueError):
        raise ValueError(tr(key)) from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(tr(key))
    return value


def describe_shape(record):
    (x1, y1), (x2, y2) = record["points"]
    kind = record["kind"]
    if kind == "line" and record.get("arrow_heads", "none") != "none":
        kind = "capped_line" if record.get("arrow_style") == "cap" else "arrow"
    return (tr(f"shape.option.{kind}"), tr(f"shape.option.{record['units']}"), tr(f"shape.option.{record['layer']}"),
            f"({_num(x1)}; {_num(y1)}) – ({_num(x2)}; {_num(y2)})")


class ShapeEditor(QDialog):
    """One shape; ``result`` is the canonical record after OK."""

    def __init__(self, parent, axes, record=None):
        super().__init__(parent)
        self.setWindowTitle(tr("shape.edit" if record else "shape.add").rstrip("…"))
        self.axes, self.result = axes, None
        self.record = deepcopy(record) if record else {"id": str(uuid.uuid4()), **deepcopy(DEFAULT_SHAPE)}
        r = self.record
        outer = theme.scroll_body(self)  # Scrolls on short screens (150%).
        self.fields = {}

        def choice(key):
            self.fields[key] = Choice(CHOICES[key], {value: f"shape.option.{value}" for value in CHOICES[key]},
                                      r.get(key, OPTION_DEFAULTS.get(key)))
            return self.fields[key]

        def colored(key, value):
            self.fields[key] = QLineEdit(value)
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(self.fields[key], 1)
            self.fields[key + "_pick"] = _color_button(self.fields[key])
            line.addWidget(self.fields[key + "_pick"])
            return row

        top = QFormLayout()
        top.addRow(tr("shape.kind"), choice("kind"))
        outer.addLayout(top)
        groups = QGridLayout()
        outer.addLayout(groups)
        stroke = QFormLayout(box := QGroupBox(tr("shape.group.stroke")))
        stroke.addRow(tr("shape.stroke"), colored("stroke", r["stroke"]))
        self.fields["width"] = QLineEdit(_num(r["width"]))
        stroke.addRow(tr("shape.width"), self.fields["width"])
        stroke.addRow(tr("shape.line_style"), choice("line_style"))
        groups.addWidget(box, 0, 0)
        fill = QFormLayout(box := QGroupBox(tr("shape.group.fill")))
        fill.addRow(tr("shape.fill"), colored("fill", r["fill"] or ""))
        fill.addRow(tr("shape.hatch"), choice("hatch"))
        fill.addRow(tr("shape.hatch_color"), colored("hatch_color", r.get("hatch_color", "")))
        hint = QLabel(tr("shape.fill_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        fill.addRow(hint)
        groups.addWidget(box, 0, 1)
        endings = QFormLayout(box := QGroupBox(tr("shape.group.endings")))
        endings.addRow(tr("shape.arrow_heads"), choice("arrow_heads"))
        endings.addRow(tr("shape.arrow_style"), choice("arrow_style"))
        self.fields["arrow_size"] = QLineEdit(_num(r.get("arrow_size", ARROW_SIZE)))
        endings.addRow(tr("shape.arrow_size"), self.fields["arrow_size"])
        groups.addWidget(box, 1, 0)
        order = QFormLayout(box := QGroupBox(tr("shape.group.order")))
        self.fields["alpha"] = QLineEdit(_num(r["alpha"]))
        order.addRow(tr("shape.alpha"), self.fields["alpha"])
        order.addRow(tr("shape.layer"), choice("layer"))
        groups.addWidget(box, 1, 1)
        position = QFormLayout()
        position.addRow(tr("shape.units"), choice("units"))
        hint = QLabel(tr("shape.axis_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        position.addRow(hint)
        (x1, y1), (x2, y2) = r["points"]
        for caption, names, values in (("shape.point1", ("x1", "y1"), (x1, y1)),
                                       ("shape.point2", ("x2", "y2"), (x2, y2))):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            for name, value in zip(names, values):
                self.fields[name] = QLineEdit(_num(value))
                line.addWidget(self.fields[name])
            position.addRow(tr(caption), row)
        outer.addLayout(position)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)
        for key in ("kind", "arrow_heads", "hatch"):
            self.fields[key].currentIndexChanged.connect(self.sync_kind)
        self.sync_kind()

    def sync_kind(self, *_):
        kind, heads = self.fields["kind"].value(), self.fields["arrow_heads"].value()
        box = kind in ("rectangle", "ellipse")
        for key in ("fill", "fill_pick", "hatch"):
            self.fields[key].setEnabled(box)
        for key in ("hatch_color", "hatch_color_pick"):
            self.fields[key].setEnabled(box and self.fields["hatch"].value() != "none")
        self.fields["arrow_heads"].setEnabled(kind == "line")
        for key in ("arrow_style", "arrow_size"):
            self.fields[key].setEnabled(kind == "line" and heads != "none")

    def read_record(self):
        f, old = self.fields, self.record
        values = [_parse(f[name].text(), "shape.error.coordinates") for name in POINTS]
        record = {"id": old["id"], "kind": f["kind"].value(), "units": f["units"].value(),
                  "points": [values[:2], values[2:]], "stroke": f["stroke"].text().strip(),
                  "width": _parse(f["width"].text(), "shape.error.width"), "line_style": f["line_style"].value(),
                  "alpha": _parse(f["alpha"].text(), "shape.error.alpha"), "layer": f["layer"].value()}
        fill = f["fill"].text().strip()
        record["fill"] = None if record["kind"] == "line" or not fill else fill
        if record["kind"] == "line":
            heads = f["arrow_heads"].value()
            options = {"arrow_heads": heads}
            if heads != "none":
                options["arrow_style"] = f["arrow_style"].value()
                options["arrow_size"] = _parse(f["arrow_size"].text(), "shape.error.arrow_size")
            else:  # Disabled fields keep the confirmed settings.
                options.update({key: old[key] for key in ("arrow_style", "arrow_size") if key in old})
            record.update({key: value for key, value in options.items()
                           if key in old or value != OPTION_DEFAULTS[key]})
        else:
            hatch = f["hatch"].value()
            if "hatch" in old or hatch != "none":
                record["hatch"] = hatch
            if hatch == "none":
                if "hatch_color" in old:
                    record["hatch_color"] = old["hatch_color"]
            elif f["hatch_color"].text().strip():
                record["hatch_color"] = f["hatch_color"].text().strip()
        record.update({key: old[key] for key in OBJECT_KEYS if key in old})
        try:
            canonical = validate_shape(record)
        except ValueError as error:
            text = str(error).casefold()
            key = next((key for fragment, key in ENGINE_ERRORS if fragment in text), "shape.error.coordinates")
            raise ValueError(tr(key)) from None
        if not on_axis_domain(self.axes, canonical):
            raise ValueError(tr("shape.error.axis_domain"))
        return canonical

    def accept(self):
        try:
            self.result = self.read_record()
        except ValueError as error:
            self.result = None
            self.problem.setText(str(error))
            self.problem.setVisible(True)
            return
        super().accept()


class GraphShapesDialog(QDialog):
    """``result`` is the new list of shape records after Apply."""

    def __init__(self, parent, axes, records):
        super().__init__(parent)
        self.setWindowTitle(tr("shape.title"))
        self.axes, self.records, self.result = axes, deepcopy(list(records or [])), None
        outer = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr(key) for key in ("shape.kind", "shape.units", "shape.layer",
                                                                  "shape.points")])
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
                             ("remove", self.remove), ("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                             ("clear", self.clear)):
            button = QPushButton(tr(f"shape.{key}"))
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
        buttons.addButton(tr("graph.format.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("setup.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.fill(0 if self.records else None)
        self.resize(680, 380)

    def fill(self, selected=None):
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            for column, text in enumerate(describe_shape(record)):
                item = QTableWidgetItem(text)
                if record.get("group") or record.get("locked"):
                    item.setToolTip(tr("shape.objects.locked" if is_locked(self.members(index))
                                       else "shape.objects.ungroup_first"))
                self.table.setItem(index, column, item)
        if selected is not None and self.records:
            self.table.selectRow(max(0, min(selected, len(self.records) - 1)))
        self.problem.setVisible(False)
        self._buttons()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def members(self, index):
        if index is None:
            return []
        return selected_objects(self.records, [self.records[index]["id"]])[0]

    def can_move(self, index, step):
        if index is None or not 0 <= index + step < len(self.records):
            return False
        return all(len(members) == 1 and not is_locked(members)
                   for members in (self.members(index), self.members(index + step)))

    def _buttons(self):
        index = self.selected()
        members = self.members(index)
        unlocked = bool(members) and not is_locked(members)
        self.buttons["add"].setEnabled(len(self.records) < MAX_SHAPES)
        self.buttons["edit"].setEnabled(unlocked and len(members) == 1)
        self.buttons["remove"].setEnabled(unlocked)
        self.buttons["duplicate"].setEnabled(unlocked and len(self.records) + len(members) <= MAX_SHAPES)
        self.buttons["up"].setEnabled(self.can_move(index, -1))
        self.buttons["down"].setEnabled(self.can_move(index, 1))
        locked = self.locked_objects()
        clear = self.buttons["clear"]
        clear.setText(tr("shape.objects.clear_unlocked" if locked else "shape.clear"))
        clear.setEnabled(any(object_key(record) not in locked for record in self.records))

    def _limit(self, count=1):
        if len(self.records) + count > MAX_SHAPES:
            self.problem.setText(tr("shape.error.limit"))
            self.problem.setVisible(True)
            return True
        return False

    def add(self):
        if self._limit():
            return
        dialog = ShapeEditor(self, self.axes)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)

    def edit(self):
        index = self.selected()
        members = self.members(index)
        if len(members) != 1 or is_locked(members):
            return
        dialog = ShapeEditor(self, self.axes, members[0])
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records[index] = dialog.result
            self.fill(index)

    def duplicate(self):
        index = self.selected()
        members = self.members(index)
        if not members or is_locked(members) or self._limit(len(members)):
            return
        insert_at = self.records.index(members[-1]) + 1
        self.records[insert_at:insert_at] = duplicate_object(members)
        self.fill(insert_at)

    def remove(self):
        index = self.selected()
        members = self.members(index)
        if members and not is_locked(members):
            self.records = [record for record in self.records if record not in members]
            self.fill(index)

    def move(self, step):
        index = self.selected()
        if not self.can_move(index, step):
            return
        self.records[index], self.records[index + step] = self.records[index + step], self.records[index]
        self.fill(index + step)

    def locked_objects(self):
        return {object_key(record) for record in self.records if record.get("locked")}

    def clear(self):
        locked = self.locked_objects()
        self.records = [record for record in self.records if object_key(record) in locked]
        self.fill()

    def accept(self):
        self.result = self.records
        super().accept()
