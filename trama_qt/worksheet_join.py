"""Join worksheets by key in the Qt analysis dialog.

The left worksheet is the input of the analysis. The editor offers the other native data sheets of the
project on the right (``AnalysisDialog(join_sources=...)``), one row per key pair with the left and the right
column side by side, and the join type and cardinality with their notes. The recipe keeps the canonical
English values of ``analisi.worksheet_join``; only the captions are translated.

A right worksheet that is no longer in the project stays selected as "(missing)": the dialog never picks a
replacement on its own, and the engine error asks the user to link another sheet.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget)

from analisi import worksheet_join as wj
from analisi.field_error import FieldError
from analisi.i18n import tr
from analisi.worksheet_join_labels import CARDINALITY_KEYS, FIELD_KEYS, TYPE_KEYS, message

from . import theme

_PAIR = re.compile(r"Pair (\d+):")


def _note(text):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _choices(values, keys, current):
    box = QComboBox()
    for value in values:
        box.addItem(tr(keys[value]), value)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box


class KeyPairs(QWidget):
    """One row per key pair: caption, left column, right column, remove."""

    def __init__(self, left_columns, parent=None):
        super().__init__(parent)
        self.left_columns = [str(name) for name in left_columns]
        self.right_columns = []
        self.pairs = []  # (caption, left combo, right combo, remove button)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        for column, key in ((1, "join.caption.left_column"), (2, "join.caption.right_column")):
            header = QLabel(tr(key))
            header.setObjectName("muted")
            self.grid.addWidget(header, 0, column)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        self.add_button = QPushButton(theme.icon("plus"), tr("join.caption.add"))
        self.add_button.setObjectName("joinAddPair")
        self.add_button.clicked.connect(lambda: self.add_pair(focus=True))

    # -- rows ---------------------------------------------------------------------------------------
    @staticmethod
    def _fill(box, columns, value):
        box.blockSignals(True)
        box.clear()
        for name in columns:
            box.addItem(name, name)
        position = box.findData(value) if value is not None else -1
        if position < 0 and value not in (None, ""):
            box.addItem(tr("join.caption.missing_column", column=value), value)
            position = box.count() - 1
        box.setCurrentIndex(max(position, 0) if box.count() else -1)
        box.blockSignals(False)

    def _right_default(self, left):
        if left in self.right_columns:
            return left
        used = {box.currentData() for _, _, box, _ in self.pairs}
        return next((name for name in self.right_columns if name not in used),
                    self.right_columns[0] if self.right_columns else None)

    def add_pair(self, left=None, right=None, *, focus=False):
        if len(self.pairs) >= wj.MAX_KEYS:
            return
        if left is None:
            used = {box.currentData() for _, box, _, _ in self.pairs}
            left = next((name for name in self.left_columns if name not in used),
                        self.left_columns[0] if self.left_columns else None)
        if right is None:
            right = self._right_default(left)
        row = len(self.pairs) + 1
        caption = QLabel(tr("join.caption.pair", number=row))
        left_box, right_box = QComboBox(), QComboBox()
        for box in (left_box, right_box):
            box.setMinimumContentsLength(14)
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        left_box.setObjectName(f"joinLeftKey{row}")
        right_box.setObjectName(f"joinRightKey{row}")
        left_box.setAccessibleName(f"{tr('join.caption.pair', number=row)} · {tr('join.caption.left_column')}")
        right_box.setAccessibleName(f"{tr('join.caption.pair', number=row)} · {tr('join.caption.right_column')}")
        self._fill(left_box, self.left_columns, left)
        self._fill(right_box, self.right_columns, right)
        remove = QToolButton()
        remove.setIcon(theme.icon("x"))
        remove.setAutoRaise(True)
        remove.setToolTip(tr("join.caption.remove", number=row))
        remove.setAccessibleName(tr("join.caption.remove", number=row))
        pair = (caption, left_box, right_box, remove)
        remove.clicked.connect(lambda: self.remove_pair(pair))
        self.pairs.append(pair)
        self._layout()
        if focus:
            left_box.setFocus()

    def remove_pair(self, pair):
        if len(self.pairs) <= 1 or pair not in self.pairs:
            return
        self.pairs.remove(pair)
        for widget in pair:
            self.grid.removeWidget(widget)
            widget.deleteLater()
        self._layout()

    def _layout(self):
        for index, (caption, left_box, right_box, remove) in enumerate(self.pairs, 1):
            caption.setText(tr("join.caption.pair", number=index))
            remove.setToolTip(tr("join.caption.remove", number=index))
            remove.setEnabled(len(self.pairs) > 1)
            self.grid.addWidget(caption, index, 0)
            self.grid.addWidget(left_box, index, 1)
            self.grid.addWidget(right_box, index, 2)
            self.grid.addWidget(remove, index, 3)
            for widget in (caption, left_box, right_box, remove):
                widget.setVisible(True)  # A layout shows a new child only later, from the event loop.
        self.grid.removeWidget(self.add_button)
        self.grid.addWidget(self.add_button, len(self.pairs) + 1, 1, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self.add_button.setEnabled(len(self.pairs) < wj.MAX_KEYS)

    def set_right_columns(self, columns):
        """A new right worksheet: keep each right key that it has, otherwise propose a column, and show the
        columns of the new sheet."""
        self.right_columns = [str(name) for name in columns]
        for _, left_box, right_box, _ in self.pairs:
            current = right_box.currentData()
            value = current if current in self.right_columns else self._right_default(left_box.currentData())
            self._fill(right_box, self.right_columns, value)

    def values(self):
        return ([box.currentData() for _, box, _, _ in self.pairs],
                [box.currentData() for _, _, box, _ in self.pairs])

    def focus_pair(self, pair, side):
        if not self.pairs:
            return False
        _, left_box, right_box, _ = self.pairs[max(0, min(pair, len(self.pairs) - 1))]
        (right_box if side == "right" else left_box).setFocus()
        return True


class JoinEditor:
    """Binds the join fields of an AnalysisDialog: pages, values, cheap checks, focus and messages."""

    def __init__(self, dialog, pages, saved):
        self.dialog = dialog
        self.sources = dict(dialog.join_sources or {})
        variables, options = pages["variables"], pages["options"]
        left = dialog.join_left or ""
        variables.addRow(_note(tr("join.note.left", sheet=left)))

        self.sheet = QComboBox()
        self.sheet.setObjectName("joinRightSheet")
        self.sheet.setMinimumContentsLength(18)
        for title in self.sources:
            self.sheet.addItem(title, title)
        wanted = saved.get(wj.RIGHT_SHEET)
        if isinstance(wanted, str) and wanted and wanted not in self.sources:
            # Never relink silently: the missing title stays visible until the user picks a sheet.
            self.sheet.addItem(tr("join.caption.missing_sheet", sheet=wanted), wanted)
        position = self.sheet.findData(wanted) if wanted else -1
        self.sheet.setCurrentIndex(max(position, 0) if self.sheet.count() else -1)
        sheet_caption = QLabel(tr(FIELD_KEYS[wj.RIGHT_SHEET]))
        variables.addRow(sheet_caption, self.sheet)
        if not self.sources:
            variables.addRow(_note(tr("join.note.no_sheet")))

        keys_caption = QLabel(tr("join.caption.keys"))
        keys_caption.setObjectName("sectionTitle")
        variables.addRow(keys_caption)
        self.pairs = KeyPairs(dialog.data.columns)
        self.pairs.set_right_columns(self.sources.get(self.sheet.currentData(), ()))
        left_keys, right_keys = saved.get(wj.LEFT_KEYS), saved.get(wj.RIGHT_KEYS)
        if isinstance(left_keys, list) and isinstance(right_keys, list) and left_keys:
            for left_key, right_key in zip(left_keys, right_keys + [None] * (len(left_keys) - len(right_keys))):
                self.pairs.add_pair(str(left_key), None if right_key is None else str(right_key))
        else:
            self.pairs.add_pair()
        variables.addRow(self.pairs)
        variables.addRow(_note(tr("join.note.keys")))
        self.sheet.currentIndexChanged.connect(self._sheet_changed)

        self.kind = _choices(wj.TYPES, TYPE_KEYS, saved.get(wj.JOIN_TYPE, wj.DEFAULT_TYPE))
        self.kind.setObjectName("joinType")
        self.rule = _choices(wj.CARDINALITIES, CARDINALITY_KEYS, saved.get(wj.CARDINALITY, wj.DEFAULT_CARDINALITY))
        self.rule.setObjectName("joinCardinality")
        type_caption, rule_caption = QLabel(tr(FIELD_KEYS[wj.JOIN_TYPE])), QLabel(tr(FIELD_KEYS[wj.CARDINALITY]))
        options.addRow(type_caption, self.kind)
        options.addRow(_note(tr("join.note.type")))
        options.addRow(rule_caption, self.rule)
        options.addRow(_note(tr("join.note.cardinality")))
        options.addRow(_note(tr("join.note.results")))
        self.forms = {wj.RIGHT_SHEET: (variables, self.sheet), wj.LEFT_KEYS: (variables, self.pairs),
                      wj.RIGHT_KEYS: (variables, self.pairs), wj.JOIN_TYPE: (options, self.kind),
                      wj.CARDINALITY: (options, self.rule)}
        for caption in (sheet_caption, type_caption, rule_caption):
            caption.setWordWrap(True)
            caption.setMinimumWidth(150)
            caption.setMaximumWidth(230)

    def _sheet_changed(self, _index=None):
        self.pairs.set_right_columns(self.sources.get(self.sheet.currentData(), ()))

    # -- values -------------------------------------------------------------------------------------
    def options(self):
        left, right = self.pairs.values()
        return {wj.RIGHT_SHEET: self.sheet.currentData() or "", wj.LEFT_KEYS: left, wj.RIGHT_KEYS: right,
                wj.JOIN_TYPE: self.kind.currentData(), wj.CARDINALITY: self.rule.currentData()}

    def check(self, options):
        """The checks that need no data: a sheet of this project, 1–4 distinct pairs of existing columns."""
        title = options[wj.RIGHT_SHEET]
        if title not in self.sources:
            raise wj.missing_source(title or None)
        wj.validate(options, self.dialog.data.columns, self.sources[title])

    # -- errors -------------------------------------------------------------------------------------
    def focus(self, field, error=None):
        target = self.forms.get(field)
        if target is None:
            return False
        form, widget = target
        tabs = self.dialog.tabs
        for index in range(tabs.count()):
            scroll = tabs.widget(index)
            if scroll.widget().layout() is form:
                tabs.setCurrentIndex(index)
                scroll.ensureWidgetVisible(widget)
                break
        if widget is self.pairs:
            pair = getattr(error, "pair", None)
            if pair is None:
                match = _PAIR.search(str(error or ""))
                pair = int(match.group(1)) - 1 if match else 0
            return self.pairs.focus_pair(pair, "right" if field == wj.RIGHT_KEYS else "left")
        widget.setFocus()
        return True


def attach(dialog, pages, saved):
    """The join editor when the dialog shows Join worksheets by key, else None."""
    if dialog.method != wj.METHOD:
        return None
    return JoinEditor(dialog, pages, saved)


__all__ = ["JoinEditor", "KeyPairs", "attach", "message", "FieldError"]
