"""Planned contrasts of the Multifactor ANOVA dialog in Qt (0.96).

``ContrastPanel`` sits at the bottom of the Options page of Multifactor ANOVA: one line that sums up
the contrasts of the draft and the button **Planned contrasts…**. The button opens ``ContrastEditor``
on a copy of that draft:

* the factors of the contrasts (ticked model factors, in the order of the list), the correction and
  the alpha of the pointwise t intervals, with a note on what the correction changes;
* the list of contrasts with Add, Duplicate, Up, Down and Remove;
* for the contrast chosen in the list: its name, a table with one level picker per factor and the
  coefficient of each weight, Add weight and Remove weight, and the live sum of the coefficients.

OK checks the draft with the engine's own checks (``analisi.anova_planned_contrasts``), shows the
error under the field it is about and puts the cursor on the row; nothing is kept until the draft is
valid. The panel holds the confirmed draft, and the analysis dialog writes it into the recipe only when
the user presses Run: Cancel there leaves the recipe as it was.

Names, factor names and levels are shown as plain text and saved exactly as typed or as the model
reads them. A level that the data no longer has (a value edited or a row excluded) stays visible with
``(not in the data)`` until the user picks another level or removes the weight.
"""
from copy import deepcopy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from analisi import anova_planned_contrasts as engine
from analisi.anova_contrast_editor import clean_state, coefficient_text, parse_coefficient
from analisi.anova_planned_contrasts import (ALPHA, CONTRASTS, CORRECTION, CORRECTIONS, FACTORS,
                                             KEYS, MAX_NAME, ContrastError)
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr

from .theme import fit_dialog

COLUMN = "Coefficient"


def _plain(widget, wrap=True):
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    return widget


def _note(name="muted"):
    note = _plain(QLabel())
    note.setObjectName(name)
    note.setVisible(False)
    return note


def _say(widget, text):
    widget.setText(text)
    widget.setVisible(bool(text))


def _mnemonic_free(text):
    return text.replace("&", "&&")


def _button(text, command):
    button = QPushButton(text)
    button.setAutoDefault(False)
    button.clicked.connect(command)
    return button


class ContrastEditor(QDialog):
    """The editor of **Planned contrasts…**, working on a copy of the panel's draft.

    ``context`` is a callable returning ``(model factors, levels by factor, check)``: the factors of the
    model as the analysis dialog stands, the levels each one has in the rows the fit will use, and a
    callable that runs the data checks of the engine (category collisions).
    """

    def __init__(self, parent, state, context, *, error=None):
        super().__init__(parent)
        self.setWindowTitle(tr("anova.contrasts.title"))
        self.setObjectName("plannedContrastEditor")
        self.result_state = None
        self.model, self.levels, self.data_check = context()
        state = deepcopy(state)
        self.correction_value = state[CORRECTION]
        # Draft: factor order, and per contrast its name and weights with levels keyed by factor name.
        self.order = list(dict.fromkeys([*state[FACTORS], *self.model]))
        # A new draft starts with every model factor ticked; a saved one keeps its own choice.
        self.ticked = set(state[FACTORS]) if state[FACTORS] or state[CONTRASTS] else set(self.model)
        self.items = []
        for record in state[CONTRASTS]:
            weights = [{"levels": dict(zip(state[FACTORS], weight["levels"])),
                        "coefficient": coefficient_text(weight["coefficient"])} for weight in record["weights"]]
            self.items.append({"name": record["name"], "weights": weights})
        self.current = 0 if self.items else -1
        self._building = False
        fit_dialog(self, 900, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(8)
        intro = _plain(QLabel(tr("anova.contrasts.help")))
        intro.setObjectName("muted")
        outer.addWidget(intro)

        top = QHBoxLayout()
        top.setSpacing(16)
        factors_box = QVBoxLayout()
        factors_caption = _plain(QLabel(tr("anova.contrasts.factors")))
        factors_caption.setObjectName("sectionTitle")
        factors_box.addWidget(factors_caption)
        self.factor_list = QListWidget()
        self.factor_list.setObjectName("plannedContrastFactors")
        self.factor_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.factor_list.itemChanged.connect(self._factor_toggled)
        factors_caption.setBuddy(self.factor_list)
        factors_box.addWidget(self.factor_list)
        self.factor_help = _plain(QLabel(tr("anova.contrasts.factors.help")))
        self.factor_help.setObjectName("muted")
        factors_box.addWidget(self.factor_help)
        self.factor_note = _note("notice")
        factors_box.addWidget(self.factor_note)
        self.factor_error = _note("errorBanner")
        factors_box.addWidget(self.factor_error)
        top.addLayout(factors_box, 1)

        settings = QFormLayout()
        settings.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.correction = QComboBox()
        for choice in CORRECTIONS:
            self.correction.addItem(tr(engine.CHOICE_KEYS[choice]), choice)
        position = self.correction.findData(self.correction_value)
        self.correction.setCurrentIndex(max(position, 0))
        settings.addRow(_plain(QLabel(tr("anova.contrasts.correction")), False), self.correction)
        self.alpha = QLineEdit(coefficient_text(state[ALPHA]))
        self.alpha.setMaximumWidth(120)
        settings.addRow(_plain(QLabel(tr("anova.contrasts.alpha")), False), self.alpha)
        self.alpha_error = _note("errorBanner")
        settings.addRow(self.alpha_error)
        self.ci_note = _plain(QLabel(tr("anova.contrasts.ci_note")))
        self.ci_note.setObjectName("muted")
        settings.addRow(self.ci_note)
        holder = QWidget()
        holder.setLayout(settings)
        top.addWidget(holder, 1)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        list_caption = _plain(QLabel(tr("anova.contrasts.list")))
        list_caption.setObjectName("sectionTitle")
        left_layout.addWidget(list_caption)
        self.contrast_list = QListWidget()
        self.contrast_list.setObjectName("plannedContrastList")
        self.contrast_list.currentRowChanged.connect(self._picked)
        list_caption.setBuddy(self.contrast_list)
        left_layout.addWidget(self.contrast_list, 1)
        tools = QGridLayout()
        self.add_button = _button(tr("anova.contrasts.add"), self.add_contrast)
        self.duplicate_button = _button(tr("anova.contrasts.duplicate"), self.duplicate)
        self.up_button = _button(tr("anova.contrasts.up"), lambda: self.move(-1))
        self.down_button = _button(tr("anova.contrasts.down"), lambda: self.move(1))
        self.remove_button = _button(tr("anova.contrasts.remove"), self.remove)
        for index, button in enumerate((self.add_button, self.duplicate_button, self.remove_button,
                                        self.up_button, self.down_button)):
            tools.addWidget(button, index // 3, index % 3)
        left_layout.addLayout(tools)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        name_row = QHBoxLayout()
        name_caption = _plain(QLabel(tr("anova.contrasts.name")), False)
        name_row.addWidget(name_caption)
        self.name = QLineEdit()
        self.name.setObjectName("plannedContrastName")
        self.name.setMaxLength(MAX_NAME + 40)  # longer names are reported, not cut silently
        self.name.textEdited.connect(self._renamed)
        name_caption.setBuddy(self.name)
        name_row.addWidget(self.name, 1)
        right_layout.addLayout(name_row)
        self.name_error = _note("errorBanner")
        right_layout.addWidget(self.name_error)
        weights_caption = _plain(QLabel(tr("anova.contrasts.weights")))
        weights_caption.setObjectName("sectionTitle")
        right_layout.addWidget(weights_caption)
        self.table = QTableWidget(0, 0)
        self.table.setObjectName("plannedContrastWeights")
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._coefficient_edited)
        weights_caption.setBuddy(self.table)
        right_layout.addWidget(self.table, 1)
        weight_tools = QHBoxLayout()
        self.add_weight_button = _button(tr("anova.contrasts.add_weight"), self.add_weight)
        self.remove_weight_button = _button(tr("anova.contrasts.remove_weight"), self.remove_weight)
        weight_tools.addWidget(self.add_weight_button)
        weight_tools.addWidget(self.remove_weight_button)
        weight_tools.addStretch(1)
        self.sum_label = _plain(QLabel(), False)
        self.sum_label.setObjectName("plannedContrastSum")
        weight_tools.addWidget(self.sum_label)
        right_layout.addLayout(weight_tools)
        self.coefficient_help = _plain(QLabel(tr("anova.contrasts.coefficient.help")))
        self.coefficient_help.setObjectName("muted")
        right_layout.addWidget(self.coefficient_help)
        self.level_note = _note("notice")
        right_layout.addWidget(self.level_note)
        self.weights_error = _note("errorBanner")
        self.weights_error.setObjectName("errorBanner")
        right_layout.addWidget(self.weights_error)
        self.empty_note = _note()
        right_layout.addWidget(self.empty_note)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 620])
        outer.addWidget(splitter, 1)

        buttons = QDialogButtonBox()
        self.ok_button = buttons.addButton(tr("interface.OK"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.setDefault(True)
        buttons.addButton(tr("interface.Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.fill_factors()
        self.fill_list()
        if error:
            # Reopened after a failed run: find the row again with the same checks; else show the message.
            if not self.validate(show=True):
                return
            self.show_problem(str(error))

    # -- factors ----------------------------------------------------------------------------------
    def factors(self):
        """Ticked factors in the order of the list."""
        return [name for name in self.order if name in self.ticked]

    def fill_factors(self):
        self._building = True
        self.factor_list.clear()
        for name in self.order:
            inside = name in self.model
            if not inside and name not in self.ticked:
                continue
            item = QListWidgetItem(name if inside else tr("anova.contrasts.factor_absent", factor=name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in self.ticked else Qt.CheckState.Unchecked)
            self.factor_list.addItem(item)
        rows = max(2, min(6, self.factor_list.count()))
        height = self.factor_list.sizeHintForRow(0) if self.factor_list.count() else 22
        self.factor_list.setFixedHeight(rows * height + 2 * self.factor_list.frameWidth() + 4)
        self._building = False
        absent = [name for name in self.factors() if name not in self.model]
        _say(self.factor_note, tr("anova.contrasts.note.factors", factors=", ".join(absent)) if absent else
             ("" if self.factors() else tr("anova.contrasts.no_factors")))

    def _factor_toggled(self, item):
        if self._building:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.ticked.add(name)
        else:
            self.ticked.discard(name)
        _say(self.factor_error, "")
        QTimer.singleShot(0, self, self._after_factors)

    def _after_factors(self):
        self.fill_factors()
        self.show_contrast()

    def set_factor(self, name, checked):
        """Tick or untick a factor, as a click on its box does."""
        for row in range(self.factor_list.count()):
            item = self.factor_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self._after_factors()
                return True
        return False

    # -- contrast list ------------------------------------------------------------------------------
    def fill_list(self, select=None):
        if select is not None:
            self.current = select
        self.contrast_list.blockSignals(True)
        self.contrast_list.clear()
        for item in self.items:
            self.contrast_list.addItem(QListWidgetItem(item["name"] or "—"))
        if self.items:
            self.current = max(0, min(self.current, len(self.items) - 1))
            self.contrast_list.setCurrentRow(self.current)
        else:
            self.current = -1
        self.contrast_list.blockSignals(False)
        self.show_contrast()

    def _picked(self, row):
        if row != self.current and 0 <= row < len(self.items):
            self.current = row
            self.clear_errors()
            self.show_contrast()

    def _unique(self, name):
        taken = {item["name"] for item in self.items}
        candidate, number = name[:MAX_NAME], 2
        while candidate in taken:
            suffix = f" {number}"
            candidate = name[:MAX_NAME - len(suffix)] + suffix
            number += 1
        return candidate

    def _cells(self):
        """Every cell of the ticked factors (levels in the model's order), as dicts."""
        cells = [{}]
        for name in self.factors():
            cells = [{**cell, name: level} for cell in cells for level in self.levels.get(name, ())]
            if len(cells) > engine.MAX_CELLS:
                break
        return cells

    def add_contrast(self):
        number = len(self.items) + 1
        name = self._unique(tr("anova.contrasts.new_name", number=number))
        cells = self._cells()
        weights = []
        if len(cells) >= 2 and self.factors():
            weights = [{"levels": dict(cells[0]), "coefficient": "1"},
                       {"levels": dict(cells[1]), "coefficient": "-1"}]
        self.items.append({"name": name, "weights": weights})
        self.fill_list(select=len(self.items) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def duplicate(self):
        if not 0 <= self.current < len(self.items):
            return
        source = deepcopy(self.items[self.current])
        source["name"] = self._unique(tr("anova.contrasts.copy_name", name=source["name"]))
        self.items.insert(self.current + 1, source)
        self.fill_list(select=self.current + 1)

    def move(self, step):
        target = self.current + step
        if not 0 <= self.current < len(self.items) or not 0 <= target < len(self.items):
            return
        self.items[self.current], self.items[target] = self.items[target], self.items[self.current]
        self.fill_list(select=target)
        self.contrast_list.setFocus()

    def remove(self):
        if not 0 <= self.current < len(self.items):
            return
        del self.items[self.current]
        self.fill_list(select=min(self.current, len(self.items) - 1))

    def select(self, index):
        self.contrast_list.setCurrentRow(index)

    # -- one contrast -------------------------------------------------------------------------------
    def contrast(self):
        return self.items[self.current] if 0 <= self.current < len(self.items) else None

    def _renamed(self, text):
        item = self.contrast()
        if item is None:
            return
        item["name"] = text
        row = self.contrast_list.item(self.current)
        if row is not None:
            row.setText(text or "—")

    def show_contrast(self):
        """Put the chosen contrast in the name field and the weights table."""
        item = self.contrast()
        has = item is not None
        for widget in (self.name, self.table, self.add_weight_button, self.remove_weight_button,
                       self.duplicate_button, self.remove_button):
            widget.setEnabled(has)
        self.up_button.setEnabled(has and self.current > 0)
        self.down_button.setEnabled(has and self.current < len(self.items) - 1)
        _say(self.empty_note, "" if has else tr("anova.contrasts.empty"))
        self.name.setText(item["name"] if has else "")
        factors = self.factors()
        self._building = True
        self.table.setRowCount(0)
        self.table.clear()
        self.table.setColumnCount(len(factors) + 1)
        self.table.setHorizontalHeaderLabels([*factors, tr("anova.contrasts.coefficient")])
        weights = item["weights"] if has else []
        self.table.setRowCount(len(weights))
        absent = []
        for row, weight in enumerate(weights):
            for column, factor in enumerate(factors):
                picker = QComboBox()
                picker.setObjectName("plannedContrastLevel")
                level = weight["levels"].get(factor)
                for value in self.levels.get(factor, ()):
                    picker.addItem(value, value)
                if level is not None and picker.findData(level) < 0:
                    picker.addItem(tr("anova.contrasts.level_absent", level=level), level)
                    absent.append(f"{factor} = {level}")
                if level is None:
                    picker.addItem("", None)
                picker.setCurrentIndex(max(picker.findData(level), 0))
                if level is None:
                    picker.setCurrentIndex(picker.count() - 1)
                picker.currentIndexChanged.connect(
                    lambda _index, row=row, factor=factor, picker=picker: self._level_picked(row, factor, picker))
                self.table.setCellWidget(row, column, picker)
            cell = QTableWidgetItem(weight["coefficient"] if isinstance(weight["coefficient"], str)
                                    else coefficient_text(weight["coefficient"]))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, len(factors), cell)
        self._building = False
        _say(self.level_note, tr("anova.contrasts.note.levels", levels="; ".join(dict.fromkeys(absent)))
             if absent else "")
        self.update_sum()

    def _level_picked(self, row, factor, picker):
        item = self.contrast()
        if self._building or item is None or row >= len(item["weights"]):
            return
        level = picker.currentData()
        if level is None:
            item["weights"][row]["levels"].pop(factor, None)
        else:
            item["weights"][row]["levels"][factor] = level
        if picker.findData(level) >= 0 and level in self.levels.get(factor, ()):
            # A corrected level drops the "(not in the data)" entry and its note at the next display.
            QTimer.singleShot(0, self, self._refresh_levels)

    def _refresh_levels(self):
        row = self.table.currentRow()
        self.show_contrast()
        if row >= 0:
            self.table.selectRow(row)

    def _coefficient_edited(self, cell):
        item = self.contrast()
        if self._building or item is None or cell.column() != len(self.factors()):
            return
        if cell.row() < len(item["weights"]):
            item["weights"][cell.row()]["coefficient"] = cell.text()
        self.update_sum()

    def set_level(self, row, factor, level):
        column = self.factors().index(factor)
        picker = self.table.cellWidget(row, column)
        picker.setCurrentIndex(picker.findData(level))

    def set_coefficient(self, row, text):
        self.table.item(row, len(self.factors())).setText(text)

    def add_weight(self):
        item = self.contrast()
        if item is None:
            return
        used = [tuple(weight["levels"].get(name) for name in self.factors()) for weight in item["weights"]]
        cells = self._cells()
        free = next((cell for cell in cells if tuple(cell.get(name) for name in self.factors()) not in used),
                    cells[0] if cells else {})
        item["weights"].append({"levels": dict(free), "coefficient": ""})
        self.show_contrast()
        row = len(item["weights"]) - 1
        self.table.setCurrentCell(row, len(self.factors()))
        self.table.editItem(self.table.item(row, len(self.factors())))

    def remove_weight(self):
        item = self.contrast()
        row = self.table.currentRow()
        if item is None or not 0 <= row < len(item["weights"]):
            return
        del item["weights"][row]
        self.show_contrast()
        if item["weights"]:
            self.table.selectRow(min(row, len(item["weights"]) - 1))

    def update_sum(self):
        item = self.contrast()
        if item is None or not item["weights"]:
            _say(self.sum_label, "")
            return
        try:
            values = [float(parse_coefficient(weight["coefficient"] if isinstance(weight["coefficient"], str)
                                              else coefficient_text(weight["coefficient"])))
                      for weight in item["weights"]]
            total, scale = math.fsum(values), math.fsum(abs(value) for value in values)
        except (ValueError, ZeroDivisionError, OverflowError):
            _say(self.sum_label, tr("anova.contrasts.sum.unknown"))
            return
        if math.isfinite(total) and abs(total) <= engine.SUM_TOLERANCE * scale:
            _say(self.sum_label, tr("anova.contrasts.sum.ok"))
        else:
            shown = f"{total:.6g}"
            _say(self.sum_label, tr("anova.contrasts.sum.bad",
                                    total=shown.replace(".", ",") if active_language() == "it" else shown))

    # -- result -------------------------------------------------------------------------------------
    def state(self):
        """The draft as recipe values. A coefficient that does not parse raises a ContrastError on its row."""
        factors = self.factors()
        contrasts = []
        for index, item in enumerate(self.items):
            weights = []
            for row, weight in enumerate(item["weights"]):
                text = weight["coefficient"]
                try:
                    value = parse_coefficient(text if isinstance(text, str) else coefficient_text(text))
                except (ValueError, ZeroDivisionError, OverflowError):
                    raise ContrastError(CONTRASTS, engine.ERRORS["coefficient"].format(
                        name=f"“{item['name']}”", row=row + 1), contrast=index, weight=row,
                        part="coefficient") from None
                weights.append({"levels": [weight["levels"].get(name) for name in factors], "coefficient": value})
            contrasts.append({"name": item["name"], "weights": weights})
        text = self.alpha.text().strip()
        try:
            alpha = float(decimal_comma(text))
        except ValueError:
            alpha = text
        return {FACTORS: factors, CONTRASTS: contrasts, CORRECTION: self.correction.currentData(), ALPHA: alpha}

    def check(self, state):
        """The engine's checks on the draft: request, data (collisions, grid, levels)."""
        if not state[CONTRASTS]:
            return  # no contrast: the recipe gets none of the four keys
        request = engine.check_request(state, self.model)
        self.data_check(self.model)
        engine.check_levels(request[1], request[0], self.levels, self.model)

    def clear_errors(self):
        for label in (self.factor_error, self.alpha_error, self.name_error, self.weights_error):
            _say(label, "")

    def validate(self, show=True):
        """True when the draft passes the engine's checks; otherwise show and focus the problem."""
        try:
            state = self.state()
            self.check(state)
        except FieldError as error:
            if show:
                self.show_error(error)
            return False
        self.clear_errors()
        return True

    def show_problem(self, message):
        _say(self.weights_error if self.items else self.factor_error, message)

    def show_error(self, error):
        self.clear_errors()
        message = engine.localized(error)  # the field is the place shown: no caption
        field = getattr(error, "field", None)
        if field == FACTORS:
            _say(self.factor_error, message)
            self.factor_list.setFocus()
            return
        if field in (ALPHA, CORRECTION):
            _say(self.alpha_error, message)
            (self.alpha if field == ALPHA else self.correction).setFocus()
            return
        contrast = getattr(error, "contrast", None)
        if contrast is not None and 0 <= contrast < len(self.items) and contrast != self.current:
            self.contrast_list.setCurrentRow(contrast)
        part, row = getattr(error, "part", None), getattr(error, "weight", None)
        if part == "name":
            _say(self.name_error, message)
            self.name.setFocus()
            self.name.selectAll()
            return
        _say(self.weights_error, message)
        if row is not None and 0 <= row < self.table.rowCount():
            column = len(self.factors()) if part == "coefficient" else 0
            self.table.setCurrentCell(row, column)
            self.table.selectRow(row)
            widget = self.table.cellWidget(row, column)
            (widget or self.table).setFocus()
            if part == "coefficient":
                self.table.editItem(self.table.item(row, column))
        elif part == "weights" or contrast is not None:
            self.add_weight_button.setFocus()
        else:
            self.contrast_list.setFocus()

    def accept(self):
        if not self.validate(show=True):
            return
        self.result_state = self.state()
        super().accept()


class ContrastPanel(QWidget):
    """Summary and **Planned contrasts…** button on the Options page of Multifactor ANOVA.

    ``context`` is set by ``trama_qt.anova_model.AnovaFields``: it returns the model factors as the dialog
    stands, their levels in the rows the fit will use, and the engine's data check.
    """

    def __init__(self, saved=None, parent=None):
        super().__init__(parent)
        self.setObjectName("plannedContrastPanel")
        saved = dict(saved or {})
        self.state = clean_state(saved)
        self.pending = None
        self.context = lambda: ([], {}, lambda _model: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary = _plain(QLabel())
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.notice = _note("notice")
        layout.addWidget(self.notice)
        self.problem = _note("errorBanner")
        layout.addWidget(self.problem)
        self.button = _button(tr("anova.contrasts.button"), self.open_editor)
        self.button.setObjectName("plannedContrastButton")
        self.button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.button)
        self.setFocusProxy(self.button)
        self.refresh()

    def values(self):
        """The four recipe keys, or nothing when there is no contrast (older recipes stay as they were)."""
        if not self.state[CONTRASTS]:
            return {}
        return {key: deepcopy(self.state[key]) for key in KEYS}

    def refresh(self):
        contrasts, factors = self.state[CONTRASTS], self.state[FACTORS]
        if not contrasts:
            _say(self.summary, tr("anova.contrasts.summary.none"))
        else:
            alpha = self.state[ALPHA]
            level = (f"{100 * (1 - alpha):g}" if isinstance(alpha, (int, float)) and not isinstance(alpha, bool)
                     else "?")
            if active_language() == "it":
                level = level.replace(".", ",")
            correction = self.state[CORRECTION]
            key = engine.CHOICE_KEYS.get(correction)
            values = {"factors": " × ".join(factors), "level": level,
                      "correction": tr(key) if key else str(correction)}
            text = (tr("anova.contrasts.summary.one", **values) if len(contrasts) == 1
                    else tr("anova.contrasts.summary", count=len(contrasts), **values))
            _say(self.summary, text)
        _say(self.notice, tr("anova.contrasts.note.panel") if self.stale() else "")

    def stale(self):
        """True when a factor or a level of the draft is not in the model or the data as they stand."""
        if not self.state[CONTRASTS]:
            return False
        try:
            model, levels, _check = self.context()
        except Exception:  # the dialog's fields are not a valid selection yet
            return False
        factors = self.state[FACTORS]
        if any(name not in model for name in factors):
            return True
        for record in self.state[CONTRASTS]:
            for weight in record["weights"]:
                for name, level in zip(factors, weight["levels"]):
                    if level not in levels.get(name, ()):
                        return True
        return False

    def open_editor(self):
        editor = ContrastEditor(self.window(), self.state, self.context, error=self.pending)
        if editor.exec() == QDialog.DialogCode.Accepted and editor.result_state is not None:
            self.accept_state(editor.result_state)
        return editor

    def accept_state(self, state):
        self.state = clean_state(state)
        self.pending = None
        _say(self.problem, "")
        self.refresh()

    def focus_problem(self, error=None):
        """An error on one of the four fields: show it here and put the focus on the button."""
        if error is not None:
            self.pending = str(error)
            _say(self.problem, engine.localized(error))
        self.button.setFocus(Qt.FocusReason.OtherFocusReason)
        return True


__all__ = ["ContrastEditor", "ContrastPanel", "coefficient_text", "parse_coefficient"]
