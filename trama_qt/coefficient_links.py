"""Qt pieces for linked coefficients (``C = factor × source + offset``) in the two custom-equation editors.

The recipe keeps plain data on the linked coefficient: ``"link": {"source", "factor", "offset"}``. The rules
(cycles, missing sources, limits carried onto the root, scope in a global fit) stay in
:mod:`analisi.coefficient_links` and the two engines; this module only edits the fields, shows the resolved
formula and the limits that the fit will use before Run, and keeps the links in step when a coefficient is
renamed or removed.
"""
import math
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QHeaderView, QLabel, QStyledItemDelegate, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from analisi import coefficient_links as links
from analisi.custom_fit import coefficients_from as single_coefficients, link_coefficients
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr, translate_message

ERROR_PREFIX = "links.error."
_SERIES = re.compile(r"(?P<series>Series (?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")), (?P<rest>.*)\Z", re.DOTALL)


# -- numbers and messages -----------------------------------------------------------------------------------
def shown(value):
    """Every stored digit of a number, without a trailing ``.0``; blank for ``None``."""
    return "" if value is None else links.number_text(value)


def number(text, default=None):
    """A finite float from a cell (decimal comma accepted), ``default`` for a blank cell, else ``ValueError``."""
    text = (text or "").strip()
    if not text:
        return default
    value = float(decimal_comma(text))
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def translate(message):
    """A link message of the engines in the active language, or ``None`` when it is not one."""
    message = str(message)
    prefix, rest = "", message
    match = _SERIES.match(message)
    if match:
        prefix, rest = match["series"] + ", ", match["rest"]
    if not _ours(rest):
        return None
    translated = translate_message(rest, ERROR_PREFIX)
    if active_language() == "it":
        prefix = prefix.replace("Series ", "Serie ", 1)
        translated = translated.replace(" (through ", " (tramite ")
        translated = re.sub(r"\(([^()]*?) to ([^()]*?)\)", r"(da \1 a \2)", translated)
    return prefix + translated


def _ours(message):
    """True when the English message comes from the link rules (checked against the catalog patterns)."""
    from analisi.i18n import _message_patterns
    return any(pattern.match(message) for _key, pattern in _message_patterns(ERROR_PREFIX))


def describe_error(error, fallback):
    """The banner text of a custom-equation dialog: a link message translated here, else ``fallback``."""
    return translate(error) or fallback(error)


# -- the source column --------------------------------------------------------------------------------------
class SourceDelegate(QStyledItemDelegate):
    """A combo box with "(not linked)" and the other coefficients of the list."""

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.names = names  # callable: row -> candidate names

    def createEditor(self, parent, _option, index):
        box = QComboBox(parent)
        box.addItem(tr("links.none"), "")
        for name in self.names(index.row()):
            box.addItem(name, name)
        box.activated.connect(lambda _=None, box=box: self.commitData.emit(box))
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.DisplayRole) or "")))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData() or "", Qt.ItemDataRole.DisplayRole)


def link_of(name, source, factor, offset, problem=None):
    """The recipe link from three cells, or ``None`` for a blank source. ``problem(column_key)`` marks a cell."""
    source = (source or "").strip()
    if not source:
        return None
    values = {}
    for key, raw, default in (("factor", factor, 1.0), ("offset", offset, 0.0)):
        try:
            values[key] = number(raw, default)
        except ValueError:
            if problem is not None:
                problem(key)
            raise FieldError("Parameters", f"{name}: the {key} of the link must be a finite number.") from None
    return {"source": source, "factor": values["factor"], "offset": values["offset"]}


def derived_starts(records):
    """``{name: start}`` of every linked coefficient from the starting values of the list (empty on a problem)."""
    try:
        coefficients = single_coefficients([_single(record) for record in records])
        plan = links.Plan(coefficients)
    except (ValueError, OverflowError, TypeError, KeyError):
        return {}
    values = plan.apply({c.name: c.start for c in coefficients})
    return {name: values[name] for name in plan.order}


def _single(record):
    return {key: record.get(key) for key in ("name", "start", "lower", "upper", "fixed", "link")}


def preview(records):
    """Lines that describe the links of ``records`` as the fit will use them, or ``(None, message)``.

    Works for both engines: only names, starts, limits, Fixed and the links are read.
    """
    if not any(isinstance(record, dict) and record.get("link") for record in records):
        return [], None
    try:
        coefficients = single_coefficients([_single(record) for record in records])
        local_names = {record["name"] for record in records if record.get("shared") is False}
        effective, plan = link_coefficients(coefficients, local_names=local_names)
    except (ValueError, OverflowError) as error:
        return None, str(error)
    starts = plan.apply({c.name: c.start for c in coefficients})
    original = {c.name: c for c in coefficients}
    lines = []
    for target in plan.order:
        root, factor, offset = plan.root(target)
        formula = plan.formula(target)
        if factor == 0 or original[root].fixed:
            lines.append(f"{formula} · {tr('links.constant', name=target, value=shown(starts[target]))}")
        else:
            key = "links.default_start" if root in local_names else "links.start"
            lines.append(f"{formula} · {tr(key, name=target, value=shown(starts[target]))}")
    lines.append(tr("links.order", order=plan.dependency_text()))
    for c in effective:
        before = original[c.name]
        if (c.lower, c.upper) != (before.lower, before.upper):
            lines.append(tr("links.limits", name=c.name, low="−∞" if c.lower is None else shown(c.lower),
                            high="+∞" if c.upper is None else shown(c.upper)))
    return lines, None


class PreviewLabels(QWidget):
    """The resolved formulas and the effective limits, or the link problem, under a coefficient table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setAccessibleName(tr("links.title"))
        layout.addWidget(self.summary)
        self.problem = QLabel()
        self.problem.setObjectName("notice")
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        self.problem.hide()
        self.summary.hide()

    def show_records(self, records, extra=()):
        lines, problem = preview(records)
        notes = [note for note in extra if note]
        if lines:
            self.summary.setText("\n".join([tr("links.title") + ":", *lines]))
        self.summary.setVisible(bool(lines))
        messages = []
        if problem:
            from .global_fit import translate_error
            messages.append(tr("links.problem", message=translate_error(problem)))
        messages.extend(notes)
        self.problem.setText(" ".join(messages))
        self.problem.setVisible(bool(messages))

    def texts(self):
        return (self.summary.text() if not self.summary.isHidden() else "",
                self.problem.text() if not self.problem.isHidden() else "")


def follow_rename(records_rows, old, new):
    """Point the sources that named ``old`` at ``new``. ``records_rows``: list of mutable row dicts."""
    changed = 0
    for row in records_rows:
        if row.get("source") == old:
            row["source"] = new
            changed += 1
    return changed


# -- Fit custom equation: the coefficient table with link columns -------------------------------------------
class SingleParameterEditor(QWidget):
    """Name, start, lower, upper, Fixed, and Linked to / Factor / Offset of each coefficient."""

    NAME, START, LOWER, UPPER, FIXED, SOURCE, FACTOR, OFFSET = range(8)

    def __init__(self, records, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTableWidget
        from .labels import field_label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("customCoefficients")
        self.table.setAccessibleName(field_label("Parameters"))
        self.table.setHorizontalHeaderLabels([
            *(field_label(name) for name in ("Name", "Start", "Lower", "Upper", "Fixed")),
            tr("links.source"), tr("links.factor"), tr("links.offset")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(170)
        self.table.setItemDelegateForColumn(self.SOURCE, SourceDelegate(self._candidates, self.table))
        layout.addWidget(self.table, 1)
        self.preview = PreviewLabels()
        layout.addWidget(self.preview)
        help_label = QLabel(tr("links.help"))
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.problem = None
        self.notes = []
        self._busy = False
        for record in records if isinstance(records, (list, tuple)) else ():
            if isinstance(record, dict):
                self.add(record)
        self.add({})
        self.table.itemChanged.connect(self._changed)
        self.refresh()

    # rows
    def add(self, record):
        self._busy = True
        row = self.table.rowCount()
        self.table.insertRow(row)
        link = record.get("link") if isinstance(record.get("link"), dict) else {}
        values = (record.get("name"), record.get("start"), record.get("lower"), record.get("upper"))
        for column, value in enumerate(values):
            text = value if isinstance(value, str) else shown(value) if value is not None else ""
            item = QTableWidgetItem(text)
            if column == self.NAME:
                item.setData(Qt.ItemDataRole.UserRole, text)
            self.table.setItem(row, column, item)
        fixed = QTableWidgetItem()
        fixed.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        fixed.setCheckState(Qt.CheckState.Checked if record.get("fixed") else Qt.CheckState.Unchecked)
        self.table.setItem(row, self.FIXED, fixed)
        source = link.get("source") or ""
        self.table.setItem(row, self.SOURCE, QTableWidgetItem(str(source)))
        self.table.setItem(row, self.FACTOR, QTableWidgetItem(shown(link.get("factor")) if source else ""))
        self.table.setItem(row, self.OFFSET, QTableWidgetItem(shown(link.get("offset")) if source else ""))
        self._busy = False
        return row

    def cell(self, row, column):
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    def names(self):
        return [self.cell(row, self.NAME).strip() for row in range(self.table.rowCount())
                if self.cell(row, self.NAME).strip()]

    def _candidates(self, row):
        own = self.cell(row, self.NAME).strip()
        return [name for name in self.names() if name != own]

    def set_link(self, row, source, factor="", offset=""):
        """Type a link into one row (used by tests and the smoke)."""
        self.table.item(row, self.SOURCE).setText(source)
        self.table.item(row, self.FACTOR).setText(factor)
        self.table.item(row, self.OFFSET).setText(offset)

    # editing
    def _changed(self, item):
        if self._busy:
            return
        self._busy = True
        try:
            self.notes = []
            row, column = item.row(), item.column()
            if column == self.NAME:
                self._renamed(row, item)
                if row == self.table.rowCount() - 1 and item.text().strip():
                    self.table.blockSignals(True)
                    self.add({})
                    self.table.blockSignals(False)
            elif column == self.SOURCE:
                if item.text().strip():
                    self.table.item(row, self.FIXED).setCheckState(Qt.CheckState.Unchecked)
                    for key in (self.FACTOR, self.OFFSET):
                        if not self.cell(row, key).strip():
                            self.table.item(row, key).setText("1" if key == self.FACTOR else "0")
                else:
                    for key in (self.FACTOR, self.OFFSET):
                        self.table.item(row, key).setText("")
            elif column == self.FIXED and item.checkState() == Qt.CheckState.Checked:
                if self.cell(row, self.SOURCE).strip():
                    self.table.item(row, self.SOURCE).setText("")
                    for key in (self.FACTOR, self.OFFSET):
                        self.table.item(row, key).setText("")
        finally:
            self._busy = False
        self.refresh()

    def _renamed(self, row, item):
        old, new = item.data(Qt.ItemDataRole.UserRole) or "", item.text().strip()
        item.setData(Qt.ItemDataRole.UserRole, new)
        if not old or old == new:
            return
        dependents = [other for other in range(self.table.rowCount())
                      if other != row and self.cell(other, self.SOURCE).strip() == old]
        if not dependents:
            return
        if new:
            for other in dependents:
                self.table.item(other, self.SOURCE).setText(new)
            self.notes.append(tr("links.renamed", new=new, old=old))
        else:
            self._unlink(dependents)

    def _unlink(self, rows):
        """The source is gone: each dependent is free again, starting from the value it had through its link."""
        names = []
        for other in rows:
            self.table.item(other, self.SOURCE).setText("")
            for key in (self.FACTOR, self.OFFSET):
                self.table.item(other, key).setText("")
            names.append(self.cell(other, self.NAME).strip())
        self.notes.append(tr("links.removed_parent", names=", ".join(name for name in names if name)))

    def remove_row(self, row):
        """Remove a coefficient; the links that used it as source are removed too."""
        name = self.cell(row, self.NAME).strip()
        self.table.blockSignals(True)
        self.notes = []
        dependents = [other for other in range(self.table.rowCount())
                      if other != row and name and self.cell(other, self.SOURCE).strip() == name]
        self._busy = True
        if dependents:
            self._unlink(dependents)
        self._busy = False
        self.table.removeRow(row)
        self.table.blockSignals(False)
        self.refresh()

    def refresh(self):
        """Linked rows show the starting value they take from the link (read-only); the preview follows."""
        records = self.rows()
        starts = derived_starts(records)
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            name = self.cell(row, self.NAME).strip()
            item = self.table.item(row, self.START)
            if item is None:
                continue
            linked = bool(self.cell(row, self.SOURCE).strip())
            flags = item.flags()
            font = item.font()
            font.setItalic(linked)
            item.setFont(font)
            if linked:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
                if name in starts:
                    item.setText(shown(starts[name]))
            else:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
        self.table.blockSignals(False)
        self.preview.show_records(records, self.notes)

    def rows(self):
        """Records as far as they read; a number that does not read stays text (the engine names it)."""
        found = []
        for row in range(self.table.rowCount()):
            name = self.cell(row, self.NAME).strip()
            if not name:
                continue
            record = {"name": name, "fixed": self.table.item(row, self.FIXED).checkState() == Qt.CheckState.Checked}
            for key, column in (("start", self.START), ("lower", self.LOWER), ("upper", self.UPPER)):
                try:
                    record[key] = number(self.cell(row, column), 1.0 if key == "start" else None)
                except ValueError:
                    record[key] = self.cell(row, column)
            try:
                link = link_of(name, self.cell(row, self.SOURCE), self.cell(row, self.FACTOR),
                               self.cell(row, self.OFFSET))
            except FieldError:
                link = {"source": self.cell(row, self.SOURCE).strip(), "factor": self.cell(row, self.FACTOR),
                        "offset": self.cell(row, self.OFFSET)}
            if link:
                record["link"] = link
            found.append(record)
        return found

    def values(self):
        """The canonical records. A link without a source is not written, so old recipes stay identical."""
        records = []
        for row in range(self.table.rowCount()):
            name = self.cell(row, self.NAME).strip()
            if not name:
                continue
            numbers = {}
            for key, column in (("start", self.START), ("lower", self.LOWER), ("upper", self.UPPER)):
                try:
                    numbers[key] = number(self.cell(row, column))
                except ValueError:
                    self.problem = (row, column)
                    raise FieldError("Parameters", f"{self.cell(row, column).strip()} is not a number.") from None
            record = {"name": name, "start": 1.0 if numbers["start"] is None else numbers["start"],
                      "lower": numbers["lower"], "upper": numbers["upper"],
                      "fixed": self.table.item(row, self.FIXED).checkState() == Qt.CheckState.Checked}
            link = link_of(name, self.cell(row, self.SOURCE), self.cell(row, self.FACTOR), self.cell(row, self.OFFSET),
                           lambda key, row=row: setattr(self, "problem",
                                                        (row, self.FACTOR if key == "factor" else self.OFFSET)))
            if link is not None:
                record["link"] = link
            records.append(record)
        self.problem = None
        return records

    def focus_problem(self, error=None):
        if self.problem is not None:
            row, column = self.problem
        else:
            match = re.match(r"(?:Series '[^']*', |The links form a cycle: )?(?P<name>[A-Za-z][A-Za-z0-9_]*)",
                             str(error or ""))
            names = [self.cell(row, self.NAME).strip() for row in range(self.table.rowCount())]
            if not match or match["name"] not in names:
                self.table.setFocus()
                return True
            row = names.index(match["name"])
            lowered = str(error).lower()
            column = (self.SOURCE if "link" in lowered or "cycle" in lowered else
                      self.LOWER if "lower" in lowered else self.UPPER if "upper" in lowered else self.START)
        self.table.setCurrentCell(row, column)
        self.table.setFocus()
        return True


def bold(item, on):
    font = item.font()
    font.setWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
    item.setFont(font)


def check_single(options):
    """Dialog check of Fit custom equation: only the links, so a recipe without links behaves as before."""
    records = options.get("Parameters") or ()
    if any(isinstance(record, dict) and record.get("link") for record in records):
        from analisi.custom_equations import syntax_of
        from analisi.custom_fit import SYNTAX
        link_coefficients(single_coefficients(records, syntax_of(options.get(SYNTAX))))
