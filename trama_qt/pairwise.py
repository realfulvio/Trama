"""Insert → Pairwise Comparisons… / Compact Letter Display… on Qt.

Same recipe section as the classic dialog (``analisi.pairwise_dialog``, which needs Tk): the graph keeps its
comparisons in ``options[pairwise_graph.SECTION]`` and draws them when it is calculated.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from matplotlib.colors import is_color_like

from analisi import compact_letters as cl
from analisi import pairwise_graph as pg
from analisi.i18n import active_language, tr, ui

from . import theme
from .graph_format import _color_button

_ITALIAN = {
    "Source": "Analisi sorgente", "All comparisons": "Tutti i confronti", "Labels": "Etichette", "Stars": "Asterischi",
    "At or below cutoff": "Fino alla soglia", "Cutoff": "Soglia", "Brackets": "Parentesi",
    "Compact letters": "Lettere compatte", "Identifiers": "Identificatori", "Placement": "Posizione",
    "Lowercase": "Minuscole", "Uppercase": "Maiuscole", "Numbers": "Numeri", "Individual": "Singola",
    "Aligned": "Allineata", "Line and text color": "Colore di linee e testo", "Pair": "Coppia",
    "Preview": "Anteprima", "(not shown)": "(non mostrato)",
    "Labels use the P value of the paired t-test.": "Le etichette usano il valore P del t-test appaiato.",
    pg.ADJUSTED_NOTE: "Le etichette usano i valori P aggiustati della sorgente (colonna Adjusted p).",
    "Stars: * P ≤ 0.05, ** P ≤ 0.01, *** P ≤ 0.001, **** P ≤ 0.0001, ns otherwise. The cutoff filters on the "
    "unrounded P value and does not change the stars.":
        "Asterischi: * P ≤ 0,05, ** P ≤ 0,01, *** P ≤ 0,001, **** P ≤ 0,0001, ns altrimenti. La soglia filtra sul "
        "valore P non arrotondato e non cambia gli asterischi.",
    "Every pair of the shown groups needs a P value from the source; the bracket pair selection and cutoff are "
    "not used.": "Ogni coppia dei gruppi mostrati richiede un valore P dalla sorgente; la selezione delle coppie e "
                 "la soglia delle parentesi non si usano.",
    "The source has no valid P values for this graph.": "La sorgente non ha valori P validi per questo grafico.",
    "No compatible source analysis remains. Remove the comparisons or cancel.":
        "Non resta nessuna analisi sorgente compatibile. Rimuovi i confronti o annulla.",
    "Enter a cutoff greater than 0 and at most 1.": "Inserisci una soglia maggiore di 0 e al massimo 1.",
    "Enter a valid color, for example #303640.": "Inserisci un colore valido, per esempio #303640.",
    "Enter an alpha greater than 0 and less than 1.": "Inserisci un alfa maggiore di 0 e minore di 1.",
}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


def _radios(values, captions, current):
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    group = QButtonGroup(row)
    buttons = {}
    for value, caption in zip(values, captions):
        buttons[value] = QRadioButton(t(caption))
        buttons[value].setChecked(value == current)
        group.addButton(buttons[value])
        line.addWidget(buttons[value])
    line.addStretch(1)
    row.buttons = buttons
    row.value = lambda: next(value for value, button in buttons.items() if button.isChecked())
    row.set = lambda value: buttons[value].setChecked(True)
    return row


def _number(text):
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


class PairwiseDialog(QDialog):
    """``sources`` lists ``(slot, method, caption)``; ``load_rows(slot)`` returns the source rows or raises.

    ``result`` is ``("apply", record)`` or ``("remove", None)`` after OK; Cancel leaves it None.
    """

    def __init__(self, parent, sources, current, anchors, load_rows, display=None):
        super().__init__(parent)
        self.setWindowTitle(tr("command.compact_letters" if display == pg.LETTERS else "command.pairwise").rstrip("…"))
        self.sources, self.current, self.anchors, self.load_rows = list(sources), current or {}, anchors, load_rows
        self.rows, self.checked, self.result = [], set(), None
        current = self.current
        outer = theme.scroll_body(self)  # Scrolls on short screens (150%).
        box = QGroupBox(t("Source"))
        column = QVBoxLayout(box)
        self.source = QComboBox()
        self.source.addItems([caption for _, _, caption in self.sources])
        column.addWidget(self.source)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        column.addWidget(self.note)
        outer.addWidget(box)
        box = QGroupBox(t("Display"))
        initial = display or (pg.LETTERS if current.get("display") == "letters" else pg.BRACKETS)
        self.display = _radios(pg.DISPLAYS, pg.DISPLAYS, initial)
        QVBoxLayout(box).addWidget(self.display)
        outer.addWidget(box)

        self.pairs_box = QGroupBox(t("Pairs"))
        column = QVBoxLayout(self.pairs_box)
        self.selection = _radios((pg.ALL, pg.SELECTED), ("All comparisons", "Selected pairs"),
                                 current.get("selection", pg.ALL))
        column.addWidget(self.selection)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([t("Pair"), "P"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self._ticked)
        column.addWidget(self.table)
        outer.addWidget(self.pairs_box, 1)

        self.labels_box = QGroupBox(t("Labels"))
        form = QFormLayout(self.labels_box)
        self.label = _radios((pg.STARS, pg.P_VALUE), ("Stars", "P value"),
                             pg.P_VALUE if current.get("label") == "p" else pg.STARS)
        form.addRow(t("Label"), self.label)
        self.filter = _radios(pg.FILTERS, ("All", "At or below cutoff"), current.get("filter", pg.NO_FILTER))
        form.addRow(t("Show"), self.filter)
        self.cutoff = QLineEdit(f"{current.get('stored_cutoff', pg.DEFAULT_CUTOFF):g}")
        self.cutoff.setMaximumWidth(100)
        form.addRow(t("Cutoff"), self.cutoff)
        hint = QLabel(t("Stars: * P ≤ 0.05, ** P ≤ 0.01, *** P ≤ 0.001, **** P ≤ 0.0001, ns otherwise. The cutoff "
                        "filters on the unrounded P value and does not change the stars."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        outer.addWidget(self.labels_box)

        self.letters_box = QGroupBox(t("Compact letters"))
        form = QFormLayout(self.letters_box)
        self.alpha = QLineEdit(f"{current.get('alpha', cl.DEFAULT_ALPHA):g}")
        self.alpha.setMaximumWidth(100)
        form.addRow(t("Alpha"), self.alpha)
        names = {value: name for name, value in pg.IDENTIFIER_NAMES.items()}
        self.identifiers = QComboBox()
        for name in pg.IDENTIFIER_NAMES:
            self.identifiers.addItem(t(name), name)
        self.identifiers.setCurrentIndex(self.identifiers.findData(names[current.get("identifiers", "lower")]))
        form.addRow(t("Identifiers"), self.identifiers)
        places = {value: name for name, value in pg.PLACEMENT_NAMES.items()}
        self.placement = _radios(tuple(pg.PLACEMENT_NAMES), tuple(pg.PLACEMENT_NAMES),
                                 places[current.get("placement", "individual")])
        form.addRow(t("Placement"), self.placement)
        self.size = QLineEdit(f"{current.get('size', pg.DEFAULT_LETTER_SIZE):g}")
        self.size.setMaximumWidth(100)
        form.addRow(t("Text size (pt)"), self.size)
        hint = QLabel(t("Every pair of the shown groups needs a P value from the source; the bracket pair "
                        "selection and cutoff are not used."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        form.addRow(self.preview)
        outer.addWidget(self.letters_box)

        row = QHBoxLayout()
        row.addWidget(QLabel(t("Line and text color")))
        self.color = QLineEdit(current.get("color", pg.DEFAULT_COLOR))
        self.color.setMaximumWidth(120)
        row.addWidget(self.color)
        row.addWidget(_color_button(self.color))
        row.addStretch(1)
        outer.addLayout(row)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        remove = buttons.addButton(t("Remove"), QDialogButtonBox.ButtonRole.DestructiveRole)
        remove.clicked.connect(self.remove)
        buttons.addButton(t("Apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout().addWidget(buttons)

        for button in self.filter.buttons.values():
            button.toggled.connect(self._sync_cutoff)
        for button in self.display.buttons.values():
            button.toggled.connect(self._sync_display)
        self.alpha.textChanged.connect(self._preview)
        self.identifiers.currentIndexChanged.connect(self._preview)
        if current.get("pairs"):
            self.checked = {frozenset(pair) for pair in current["pairs"]}
        self.initial_pairs = current.get("selection") == pg.SELECTED
        slots = [slot for slot, _, _ in self.sources]
        if self.sources:
            self.source.setCurrentIndex(slots.index(current["slot"]) if current.get("slot") in slots else 0)
            self._load()
        else:
            self._show(t("No compatible source analysis remains. Remove the comparisons or cancel."))
        self.source.currentIndexChanged.connect(self._load)
        self._sync_cutoff()
        self._sync_display()
        size = self.sizeHint()
        self.resize(max(560, size.width()), max(640, size.height()))

    def _show(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    # -- pairs --------------------------------------------------------------------------------------------
    def _name(self, key):
        anchor = self.anchors.get(key)
        return anchor.get("name", key) if anchor else f"{key} {t('(not shown)')}"

    def _load(self, *_):
        self.rows = []
        slot, method, _ = self.sources[self.source.currentIndex()]
        self.note.setText(t(pg.ADJUSTED_NOTE if method in pg.ADJUSTED_SHEETS else
                            "Labels use the P value of the paired t-test."))
        try:
            rows = self.load_rows(slot)
        except Exception as error:
            rows = []
            self._show(f"{ui('The source could not be calculated.')} {error}")
        else:
            self._show("" if rows else t("The source has no valid P values for this graph."))
        seen = set()
        for row in rows:
            pair = frozenset((row["left"], row["right"]))
            if pair not in seen:
                seen.add(pair)
                self.rows.append(row)
        if not self.initial_pairs:
            self.checked = {frozenset((row["left"], row["right"])) for row in self.rows}
        self.initial_pairs = False
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            item = QTableWidgetItem(f"{self._name(row['left'])}  vs  {self._name(row['right'])}")
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            pair = frozenset((row["left"], row["right"]))
            item.setCheckState(Qt.CheckState.Checked if pair in self.checked else Qt.CheckState.Unchecked)
            self.table.setItem(index, 0, item)
            p = QTableWidgetItem(f"{row['p']:.4g}")
            p.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(index, 1, p)
        self.table.blockSignals(False)
        self._preview()

    def _ticked(self, item):
        if item.column() != 0:
            return
        row = self.rows[item.row()]
        pair = frozenset((row["left"], row["right"]))
        if item.checkState() == Qt.CheckState.Checked:
            self.checked.add(pair)
        else:
            self.checked.discard(pair)
        self.selection.set(pg.SELECTED)

    def set_checked(self, pairs):
        """Tick exactly these pairs (by key), as a user would."""
        wanted = {frozenset(pair) for pair in pairs}
        for index, row in enumerate(self.rows):
            state = Qt.CheckState.Checked if frozenset((row["left"], row["right"])) in wanted else Qt.CheckState.Unchecked
            if self.table.item(index, 0).checkState() != state:
                self.table.item(index, 0).setCheckState(state)

    # -- display ------------------------------------------------------------------------------------------
    def _sync_display(self, *_):
        letters = self.display.value() == pg.LETTERS
        self.letters_box.setVisible(letters)
        self.pairs_box.setVisible(not letters)
        self.labels_box.setVisible(not letters)
        self._preview()

    def _sync_cutoff(self, *_):
        self.cutoff.setEnabled(self.filter.value() == pg.AT_OR_BELOW)

    def _letter_choices(self):
        alpha, size = _number(self.alpha.text()), _number(self.size.text())
        if alpha is None or not 0 < alpha < 1:
            raise ValueError(t("Enter an alpha greater than 0 and less than 1."))
        if size is None or not pg.LETTER_SIZES[0] <= size <= pg.LETTER_SIZES[1]:
            raise ValueError(ui(f"Enter a text size from {pg.LETTER_SIZES[0]} to {pg.LETTER_SIZES[1]} points."))
        return alpha, self.identifiers.currentData(), self.placement.value(), int(size) if size.is_integer() else size

    def letters(self):
        alpha, identifiers, _, _ = self._letter_choices()
        groups, letters = pg.assign_letters(self.anchors, self.rows, {"alpha": alpha,
                                                                     "identifiers": pg.IDENTIFIER_NAMES[identifiers]})
        return [(key, " ".join(letters[key])) for key in groups]

    def _preview(self, *_):
        if self.display.value() != pg.LETTERS or not self.rows:
            self.preview.setText("")
            return
        try:
            shown = self.letters()
        except ValueError as error:
            self.preview.setText(ui(str(error)))
            return
        self.preview.setText(f"{t('Preview')}:  " + "   ".join(f"{self._name(key)} = {text}" for key, text in shown))

    # -- result -------------------------------------------------------------------------------------------
    def record(self):
        if not self.sources:
            raise ValueError(ui("Choose a compatible source analysis."))
        slot, method, _ = self.sources[self.source.currentIndex()]
        letters = self.display.value() == pg.LETTERS
        cutoff = _number(self.cutoff.text())
        if cutoff is None or not 0 < cutoff <= 1:
            if not letters:
                raise ValueError(t("Enter a cutoff greater than 0 and at most 1."))
            cutoff = self.current.get("stored_cutoff", pg.DEFAULT_CUTOFF)
        color = self.color.text().strip()
        if not color or len(color) > 40 or not is_color_like(color):
            raise ValueError(t("Enter a valid color, for example #303640."))
        if letters:
            alpha, identifiers, placement, size = self._letter_choices()
        else:
            alpha = self.current.get("alpha", cl.DEFAULT_ALPHA)
            identifiers = {v: k for k, v in pg.IDENTIFIER_NAMES.items()}[self.current.get("identifiers", "lower")]
            placement = {v: k for k, v in pg.PLACEMENT_NAMES.items()}[self.current.get("placement", "individual")]
            size = self.current.get("size", pg.DEFAULT_LETTER_SIZE)
        if isinstance(size, float) and size.is_integer():
            size = int(size)
        selection = self.selection.value()
        pairs = ([[row["left"], row["right"]] for row in self.rows
                  if frozenset((row["left"], row["right"])) in self.checked] if selection == pg.SELECTED else [])
        record = pg.section_record(slot, method, selection=selection, pairs=pairs, label=self.label.value(),
                                   filtering=self.filter.value(), cutoff=cutoff, color=color,
                                   display=self.display.value(), alpha=alpha, identifiers=identifiers,
                                   placement=placement, size=size)
        if letters:
            if not self.rows:
                raise ValueError(t("The source has no valid P values for this graph."))
            self.letters()
            return record
        settings, _ = pg.read_section({pg.SECTION: record})
        count = pg.effective_count(self.anchors, self.rows, pg.plan_settings(settings))
        if count > pg.MAX_BRACKETS:
            raise ValueError(ui(f"{count} pairs would be drawn. Select at most {pg.MAX_BRACKETS} pairs, or show "
                                "only P values at or below the cutoff."))
        return record

    def remove(self):
        self.result = "remove", None
        super().accept()

    def accept(self):
        try:
            self.result = "apply", self.record()
        except ValueError as error:
            self.result = None
            self._show(ui(str(error)))
            return
        super().accept()
