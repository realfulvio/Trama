"""Model terms and factor order of the Multifactor ANOVA dialog in Qt (0.95 beta).

The engine (``analisi.anova_terms`` and ``analisi.anova_ss``) already fits Selected terms and Type I, II
and III sums of squares. This module gives the Qt dialog the two editors the classic dialog has:

* ``TermEditor`` is the ``Model terms`` field: main effects, two-way and three-way interactions of the
  ticked Factors as check boxes, the model summary, the lower-order terms an interaction still needs
  with an explicit *Add required terms*, and the terms that a deselected factor (or an orphan name of a
  saved recipe) has made unavailable, with an explicit *Remove unavailable terms*. The draft lives in a
  Python dict keyed by factor sets, never in the widgets, so the literal names reach the recipe
  unchanged and a term survives while its factor is unticked for a moment or the mode goes to Full
  hierarchy and back.
* ``FactorOrder`` sits under ``Sums of squares``: the note of the chosen type and, for Type I, the
  ticked factors with Up and Down (also Ctrl+Up and Ctrl+Down on the list) and the order in which the
  terms enter. The order is a list of names: a factor unticked and ticked again keeps its place, a
  factor ticked for the first time goes last. It becomes the ``Factors`` of the recipe.
* ``AnovaFields`` binds both to the generic fields of ``AnalysisDialog``. It hides Interaction order
  under Selected terms, writes the canonical recipe (the same keys and omissions as the classic dialog),
  runs the cheap checks of the engine before the dialog closes and words their errors in the active
  language. The fit itself stays on the Qt worker.

Every editor starts from copies of the recipe being edited, so Cancel leaves the analysis untouched.
"""
from itertools import combinations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from analisi import anova_marginal_means as marginal
from analisi import anova_planned_contrasts as planned
from analisi.anova_diagnostics import ASSUMPTIONS, TEST_SET
from analisi.anova_contrast_editor import check_contrast_input, contrast_context
from analisi.anova_diagnostics import format_anova_error, graph_choice, ensure_graph_budget
from analisi.anova_diagnostics import validate as validate_diagnostics
from analisi.anova_ss import KEY as SUMS_OF_SQUARES, TYPE_I, TYPE_II, TYPE_III, sums_of_squares
from analisi.anova_terms import (FULL, MAX_FACTORS, MAX_ORDER, MODEL_TERMS, SELECTED, TERM_SELECTION,
                                 active_factors, check_comparison_controls, check_options, full_terms, label,
                                 prerequisites)
from analisi.field_error import FieldError
from analisi.i18n import tr, ui

from .strings import qt

METHOD = "Multifactor ANOVA"
FACTORS = "Factors"
ORDER = "Interaction order"
GROUP_KEYS = {1: "anova.terms.group.main", 2: "anova.terms.group.two", 3: "anova.terms.group.three"}
_COLUMNS = 2  # check boxes per row inside a group


def _plain(widget):
    """Labels show factor names literally: no rich text, so ``<`` or ``&`` in a name stays as typed."""
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
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
    """Button and check box captions treat ``&`` as a shortcut marker; a factor name keeps it."""
    return text.replace("&", "&&")


def _clean(saved):
    """The terms of a saved ``Model terms`` list: factor set → names as saved. Malformed entries are skipped."""
    terms = {}
    if isinstance(saved, (list, tuple)):
        for term in saved:
            if isinstance(term, (list, tuple)) and term and all(isinstance(name, str) for name in term):
                terms.setdefault(frozenset(term), tuple(term))
    return terms


class TermEditor(QWidget):
    """Check boxes for the terms of the model, its summary and the notes of the chosen term selection.

    The dialog sets the callables ``factors`` (ticked names in the order of ``FactorOrder``), ``offered``
    (every name of the Factors list), ``selected`` (Selected terms is on), ``order`` (the text of
    Interaction order) and ``response``. ``changed`` fires after every edit of the draft.
    """

    changed = Signal()

    def __init__(self, saved=None, parent=None):
        super().__init__(parent)
        self.setObjectName("anovaTermEditor")
        self.chosen = _clean(saved)
        self.touched = bool(self.chosen)
        self.factors = lambda: []
        self.offered = lambda: []
        self.selected = lambda: False
        self.order = lambda: 1
        self.response = lambda: ""
        self.boxes = {}
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.tools = QWidget()
        tools = QHBoxLayout(self.tools)
        tools.setContentsMargins(0, 0, 0, 0)
        self.all_button = QPushButton(tr("anova.terms.select_all"))
        self.clear_button = QPushButton(tr("anova.terms.clear"))
        self.add_button = QPushButton(tr("anova.terms.add_required"))
        for button, command in ((self.all_button, self.select_all), (self.clear_button, self.clear),
                                (self.add_button, self.add_required)):
            button.setAutoDefault(False)
            button.clicked.connect(command)
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addWidget(self.tools)
        self.groups = {}
        for size, key in GROUP_KEYS.items():
            box = QGroupBox(tr(key))
            grid = QGridLayout(box)
            grid.setContentsMargins(10, 6, 10, 6)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(4)
            self.groups[size] = box
            layout.addWidget(box)
        self.summary = _plain(QLabel())
        layout.addWidget(self.summary)
        self.outside = _note()
        layout.addWidget(self.outside)
        self.problem = _note("notice")
        layout.addWidget(self.problem)
        self.unavailable_note = _note("notice")
        layout.addWidget(self.unavailable_note)
        self.remove_button = QPushButton(qt("qt.anova.remove_unavailable"))
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(self.remove_unavailable)
        self.remove_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.remove_button)
        self.note = _note()
        layout.addWidget(self.note)
        self.refresh()

    # -- state ------------------------------------------------------------------------------------
    def names(self):
        return [name for name in self.factors() if isinstance(name, str)]

    def too_many(self):
        return len(self.names()) > MAX_FACTORS

    def available(self):
        """Every term the ticked Factors allow, in model order; none beyond the engine's eight factors."""
        names = self.names()
        if not names or self.too_many():
            return []
        return list(full_terms(names, min(MAX_ORDER, len(names))))

    def _order_value(self):
        try:
            value = int(str(self.order()).strip())
        except (TypeError, ValueError):
            return 1
        return max(1, min(MAX_ORDER, value))

    def _full(self):
        names = self.names()
        if not names or self.too_many():
            return []
        return list(full_terms(names, min(self._order_value(), len(names))))

    def _follow_full(self):
        """An untouched editor holds the Full hierarchy of the ticked Factors and Interaction order."""
        if not self.touched:
            self.chosen = {frozenset(term): term for term in self._full()}

    def terms(self):
        """The ticked terms that the current Factors allow, in model order (tuples of names)."""
        self._follow_full()
        return [term for term in self.available() if frozenset(term) in self.chosen]

    def unavailable(self):
        """Draft terms that the current Factors do not allow: ``(set aside, orphan)`` lists of saved names.

        An orphan names a factor that is not even in the Factors list (a column renamed or removed since
        the recipe was saved). The others wait for their factor to be ticked again.
        """
        self._follow_full()
        allowed = {frozenset(term) for term in self.available()}
        offered = set(self.offered())
        aside, orphan = [], []
        for key, names in self.chosen.items():
            if key in allowed:
                continue
            (orphan if any(name not in offered for name in names) else aside).append(names)
        return aside, orphan

    def values(self):
        """``Model terms`` of the recipe: the allowed terms in model order, then any unavailable draft term.

        Unavailable terms are never dropped silently: the engine check names them on Model terms, and
        *Remove unavailable terms* takes them out.
        """
        aside, orphan = self.unavailable()
        return [list(term) for term in self.terms()] + [list(term) for term in (*aside, *orphan)]

    def current_terms(self):
        """The terms of the model as it stands: the ticked terms for Selected terms, else the Full hierarchy."""
        return self.terms() if self.selected() else self._full()

    # -- editing ----------------------------------------------------------------------------------
    def _toggle(self, term, checked):
        if self._building:
            return
        self._follow_full()
        key = frozenset(term)
        if checked:
            self.chosen[key] = term
        else:
            self.chosen.pop(key, None)
        self.touched = True
        self.describe()

    def select_all(self):
        self._follow_full()
        for term in self.available():
            self.chosen.setdefault(frozenset(term), term)
        self.touched = True
        self.refresh()

    def clear(self):
        self._follow_full()
        for term in self.available():
            self.chosen.pop(frozenset(term), None)
        self.touched = True
        self.refresh()

    def add_required(self):
        for term in prerequisites(self.terms(), self.names()):
            self.chosen.setdefault(frozenset(term), term)
        self.touched = True
        self.refresh()
        self._focus_after_edit()

    def remove_unavailable(self):
        aside, orphan = self.unavailable()
        for names in (*aside, *orphan):
            self.chosen.pop(frozenset(names), None)
        self.touched = True
        self.refresh()
        self._focus_after_edit()

    def _focus_after_edit(self):
        """A button that hides itself hands the keyboard focus to the first term, not to nowhere."""
        target = self.focusProxy()
        if target is not None and target.isVisible():
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    # -- display ----------------------------------------------------------------------------------
    def refresh(self):
        """Rebuild the check boxes for the ticked Factors, then show the state of the draft."""
        self._follow_full()
        self._building = True
        try:
            for box in self.boxes.values():
                box.setParent(None)
                box.deleteLater()
            self.boxes = {}
            for size, group in self.groups.items():
                grid = group.layout()
                members = [term for term in self.available() if len(term) == size]
                for index, term in enumerate(members):
                    box = QCheckBox(_mnemonic_free(label(term)), group)
                    box.setToolTip(" × ".join(term))
                    box.setChecked(frozenset(term) in self.chosen)
                    box.toggled.connect(lambda checked, term=term: self._toggle(term, checked))
                    grid.addWidget(box, index // _COLUMNS, index % _COLUMNS)
                    # Shown now, not by the layout's queued show: the page measures the new boxes at once,
                    # so a scrolling page never squeezes them under their height.
                    box.setVisible(True)
                    self.boxes[term] = box
        finally:
            self._building = False
        self.sync()
        self.updateGeometry()

    def sync(self):
        """Show what the mode needs: the term check boxes and tools only for Selected terms."""
        selected = bool(self.selected())
        self.tools.setVisible(selected)
        for size, group in self.groups.items():
            group.setVisible(selected and any(len(term) == size for term in self.boxes))
        self.describe()

    def describe(self):
        names, selected = self.names(), bool(self.selected())
        terms = self.current_terms()
        if not names:
            _say(self.summary, tr("anova.terms.no_factors"))
        elif self.too_many():
            _say(self.summary, tr("anova.terms.error.factors"))
        elif terms:
            model = f"{self.response() or 'Y'} = {' + '.join(label(term) for term in terms)}"
            _say(self.summary, tr("anova.terms.summary", model=model))
        else:
            _say(self.summary, tr("anova.terms.summary_none"))
        used = {name for term in terms for name in term}
        idle = [name for name in names if name not in used]
        _say(self.outside, tr("anova.terms.outside", factors=", ".join(idle)) if selected and idle else "")
        _say(self.problem, self._problems(terms) if selected else "")
        aside, orphan = self.unavailable() if selected else ([], [])
        lines = []
        if aside:
            lines.append(qt("qt.anova.set_aside", terms=", ".join(label(term) for term in aside)))
        if orphan:
            offered = set(self.offered())
            missing = list(dict.fromkeys(name for term in orphan for name in term if name not in offered))
            lines.append(qt("qt.anova.orphan", terms=", ".join(label(term) for term in orphan),
                            factors=", ".join(missing)))
        _say(self.unavailable_note, "\n".join(lines))
        self.remove_button.setVisible(bool(aside or orphan))
        _say(self.note, tr("anova.terms.selected_note" if selected else "anova.terms.full_note"))
        self.all_button.setEnabled(bool(self.available()))
        self.clear_button.setEnabled(any(frozenset(term) in self.chosen for term in self.available()))
        self.add_button.setEnabled(bool(prerequisites(terms, names)) if selected else False)
        self.setFocusProxy(self._focus_target(selected))
        self.changed.emit()

    def _focus_target(self, selected):
        """Where ``focus_field('Model terms')`` lands: the fix for the problem shown, else the first term."""
        if not selected:
            return None
        if self.add_button.isEnabled():
            return self.add_button
        if self.remove_button.isVisibleTo(self):
            return self.remove_button
        for term in self.available():
            if term in self.boxes:
                return self.boxes[term]
        return self.all_button

    @staticmethod
    def _problems(terms):
        have = {frozenset(term) for term in terms}
        lines = []
        for term in terms:
            missing = [label(part) for size in range(1, len(term)) for part in combinations(term, size)
                       if frozenset(part) not in have]
            if missing:
                lines.append(tr("anova.terms.needs", term=label(term), missing=", ".join(missing)))
        return "\n".join(lines)


class FactorOrder(QWidget):
    """The note of the chosen type of sums of squares, the Type I factor order and the order of the terms.

    The dialog sets ``factors`` (ticked names, worksheet order), ``kind`` (the canonical type chosen) and
    ``terms`` (the model terms in model order). ``moved`` fires after the user moves a factor.
    """

    moved = Signal()

    def __init__(self, saved=None, parent=None):
        super().__init__(parent)
        self.setObjectName("anovaFactorOrder")
        self.rank = [name for name in dict.fromkeys(saved or ()) if isinstance(name, str)]
        self.factors = lambda: []
        self.kind = lambda: TYPE_III
        self.terms = lambda: []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(4)
        self.note = _note()
        layout.addWidget(self.note)
        self.box = QWidget()
        box = QGridLayout(self.box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setHorizontalSpacing(8)
        self.caption = _plain(QLabel(tr("anova.ss.order")))
        box.addWidget(self.caption, 0, 0, 1, 2)
        self.list = QListWidget()
        self.list.setObjectName("anovaFactorOrderList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.caption.setBuddy(self.list)
        box.addWidget(self.list, 1, 0)
        buttons = QVBoxLayout()
        self.up = QPushButton(ui("Up"))
        self.down = QPushButton(ui("Down"))
        for button, step in ((self.up, -1), (self.down, 1)):
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, step=step: self.move(step))
            buttons.addWidget(button)
        buttons.addStretch(1)
        box.addLayout(buttons, 1, 1)
        self.list.installEventFilter(self)  # Ctrl+Up and Ctrl+Down move the current factor
        self.help = _plain(QLabel(f"{tr('anova.ss.order.help')} {qt('qt.anova.order_keys')}"))
        self.help.setObjectName("muted")
        box.addWidget(self.help, 2, 0, 1, 2)
        box.setColumnStretch(0, 1)
        layout.addWidget(self.box)
        self.preview = _note()
        layout.addWidget(self.preview)
        self.refresh()

    def eventFilter(self, watched, event):
        if (watched is self.list and event.type() == QEvent.Type.KeyPress
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not self.box.isHidden()):
            self.move(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(watched, event)

    def names(self):
        return [name for name in self.factors() if isinstance(name, str)]

    def arrange(self, names):
        """``names`` (worksheet order) in the order chosen here. A name not seen before goes last."""
        for name in names:
            if name not in self.rank:
                self.rank.append(name)
        return [name for name in self.rank if name in names]

    def ordered(self):
        return self.arrange(self.names())

    def move(self, step):
        row = self.list.currentRow()
        names = self.ordered()
        target = row + step
        if row < 0 or not 0 <= target < len(names):
            return
        a, b = self.rank.index(names[row]), self.rank.index(names[target])
        self.rank[a], self.rank[b] = self.rank[b], self.rank[a]
        self.refresh(selected=target)
        self.moved.emit()
        self.describe()

    def refresh(self, selected=None):
        """Show the ticked factors in the order chosen, the note of the type and the order of the terms."""
        names = self.ordered()
        if selected is None:
            current = self.list.currentItem()
            picked = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
            selected = names.index(picked) if picked in names else (0 if names else None)
        self.list.blockSignals(True)
        self.list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        if selected is not None and names:
            self.list.setCurrentRow(selected)
        self.list.blockSignals(False)
        row = self.list.sizeHintForRow(0) if names else self.list.fontMetrics().height() + 6
        self.list.setFixedHeight(min(MAX_FACTORS, max(2, len(names))) * row + 2 * self.list.frameWidth() + 4)
        self.sync()

    def sync(self):
        """Show what the type needs: the order of Type I, the notes of Type I and of Type II."""
        type_one = self.kind() == TYPE_I and bool(self.names())
        self.box.setVisible(type_one)
        several = len(self.names()) > 1
        self.up.setEnabled(type_one and several)
        self.down.setEnabled(type_one and several)
        self.describe()

    def describe(self):
        kind = self.kind()
        terms = list(self.terms()) if self.names() else []
        if kind == TYPE_I:
            _say(self.note, tr("anova.ss.note.1"))
            _say(self.preview, tr("anova.ss.preview", terms=" → ".join(label(term) for term in terms))
                 if terms else "")
        elif kind == TYPE_II and any(len(term) > 1 for term in terms):
            _say(self.note, tr("anova.ss.note.2"))
            _say(self.preview, "")
        else:
            _say(self.note, "")
            _say(self.preview, "")


class AnovaFields:
    """Binds the two editors to the generic fields of ``AnalysisDialog`` for Multifactor ANOVA."""

    def __init__(self, dialog, saved):
        self.dialog, self.saved = dialog, dict(saved)
        controls = dialog.controls
        self.factor_list = controls[FACTORS][1]
        self.response = controls["Response"][1]
        self.selection = controls[TERM_SELECTION][1]
        self.interaction = controls[ORDER][1]
        self.kind_box = controls[SUMS_OF_SQUARES][1]
        self.editor = controls[MODEL_TERMS][1]
        self.assumptions = controls[ASSUMPTIONS][1]
        self.assumptions.toggled.connect(self.sync_assumption_tests)
        self.sync_assumption_tests(self.assumptions.isChecked())
        self.order = FactorOrder(self.saved.get(FACTORS))
        _caption, widget, form = dialog.rows[SUMS_OF_SQUARES]
        row, _role = form.getWidgetPosition(widget)
        form.insertRow(row + 1, self.order)
        self.form = form

        self.order.factors = self.ticked
        self.order.kind = self.kind
        self.order.terms = self.editor.current_terms
        self.editor.factors = self.order.ordered
        self.editor.offered = self.offered
        self.editor.selected = self.is_selected
        self.editor.order = self.interaction.text
        self.editor.response = self.response.currentText

        self.factor_list.itemChanged.connect(self._factors_changed)
        self.response.currentIndexChanged.connect(lambda _index: self.editor.describe())
        self.selection.currentIndexChanged.connect(lambda _index: self.sync_mode())
        self.interaction.textChanged.connect(lambda _text: self.editor.refresh())
        self.kind_box.currentIndexChanged.connect(lambda _index: self.order.sync())
        self.order.moved.connect(self.editor.refresh)
        self.editor.changed.connect(self.order.describe)
        self.editor.changed.connect(self.relayout)
        self.kind_box.currentIndexChanged.connect(lambda _index: self.relayout())
        self._relayout_pending = False
        # Planned contrasts (0.96): the panel reads the model factors and their levels as the dialog stands.
        self.contrasts = controls[planned.CONTRASTS][1] if planned.CONTRASTS in controls else None
        if self.contrasts is not None:
            self.contrasts.context = self.contrast_context
            for key in (planned.FACTORS, planned.CORRECTION, planned.ALPHA):
                dialog.rows[key] = dialog.rows[planned.CONTRASTS]
            self.editor.changed.connect(self.contrasts.refresh)
            self.response.currentIndexChanged.connect(lambda _index: self.contrasts.refresh())
        # Estimated marginal means: the panel lists the model factors as the dialog stands.
        self.means = controls[marginal.ENABLED][1] if marginal.ENABLED in controls else None
        if self.means is not None:
            self.means.context = self.contrast_context
            for key in (marginal.FACTORS, marginal.OVERALL, marginal.CONFIDENCE):
                dialog.rows[key] = dialog.rows[marginal.ENABLED]
            self.editor.changed.connect(self.means.refresh)
            self.response.currentIndexChanged.connect(lambda _index: self.means.refresh())
            self.order.moved.connect(self.means.refresh)
        self.order.refresh()
        self.editor.refresh()  # the term check boxes follow the order of the recipe being edited
        self.sync_mode()
        if self.means is not None:
            self.means.refresh()

    # -- live state -------------------------------------------------------------------------------
    def ticked(self):
        """The names ticked in Factors, in the order of the worksheet list."""
        items = (self.factor_list.item(row) for row in range(self.factor_list.count()))
        return [item.text() for item in items if item.checkState() == Qt.CheckState.Checked]

    def sync_assumption_tests(self, enabled):
        self.dialog._set_field_visibility({TEST_SET: enabled})

    def offered(self):
        return [self.factor_list.item(row).text() for row in range(self.factor_list.count())]

    def is_selected(self):
        return self.selection.currentData() == SELECTED

    def kind(self):
        value = self.kind_box.currentData()
        return value if value in (TYPE_I, TYPE_II, TYPE_III) else TYPE_III

    def model_factors(self):
        """The factors of the model as the dialog stands, in the order of the recipe's Factors."""
        names = self.order.ordered()
        return active_factors(names, self.editor.terms()) if self.is_selected() else names

    def contrast_context(self):
        """Model factors, their levels in the rows the fit will use, and the engine's data check."""
        model = self.model_factors()
        response = self.response.currentData() or self.response.currentText()
        levels, check = contrast_context(self.dialog.data, response, model)
        return model, levels, check

    def relayout(self):
        """Measure the Options page again once the editors settle.

        Notes appear, wrap and vanish as the choices change. The scrolling page sizes itself by height for
        width; a measure taken in the same event as the change can be short, and the term check boxes would
        then be drawn squeezed. One deferred pass per burst of changes recomputes it.
        """
        if self._relayout_pending:
            return
        self._relayout_pending = True

        def run():
            self._relayout_pending = False
            page = self.form.parentWidget()
            if page is None:
                return
            for widget in (self.editor, self.order):
                widget.updateGeometry()
            self.form.invalidate()
            self.form.activate()  # lay the page out now, so what is drawn next is already measured
            page.updateGeometry()

        QTimer.singleShot(0, self.editor, run)

    def _factors_changed(self, _item=None):
        self.order.refresh()
        self.editor.refresh()

    def sync_mode(self):
        """Interaction order belongs to Full hierarchy; the term check boxes to Selected terms."""
        selected = self.is_selected()
        self.form.setRowVisible(self.interaction, not selected)
        if selected:
            self.dialog.hidden.add(ORDER)
        else:
            self.dialog.hidden.discard(ORDER)
        self.editor.sync()

    # -- recipe -----------------------------------------------------------------------------------
    def canonical(self, options):
        """The recipe as the classic dialog writes it, from the generic values of the dialog.

        ``Factors`` follows the order chosen for Type I. Full hierarchy keeps the recipe free of the 0.83
        keys unless the recipe being edited already had them; Selected terms writes the terms and leaves
        Interaction order out unless the recipe had it. Type III is omitted when the recipe had no
        ``Sums of squares``.
        """
        options = dict(options)
        if FACTORS in options:
            options[FACTORS] = self.order.arrange(list(options[FACTORS]))
        if options.get(TERM_SELECTION) == SELECTED:
            options[MODEL_TERMS] = self.editor.values()
            if ORDER in self.saved:
                try:
                    options[ORDER] = int(self.interaction.text().strip())
                except ValueError:
                    options[ORDER] = self.saved[ORDER]
        else:
            options.pop(MODEL_TERMS, None)
            if TERM_SELECTION not in self.saved:
                options.pop(TERM_SELECTION, None)
        if options.get(SUMS_OF_SQUARES) == TYPE_III and SUMS_OF_SQUARES not in self.saved:
            options.pop(SUMS_OF_SQUARES, None)
        from analisi.workbench import METHODS
        keys = list(METHODS[METHOD])
        return {**{key: options[key] for key in keys if key in options},
                **{key: value for key, value in options.items() if key not in keys}}

    def check(self, options):
        """The cheap checks of the engine, before the dialog closes. The fit runs on the worker."""
        from analisi.workbench import _anova_row_count, check_anova_options
        sums_of_squares(options)
        terms = check_options(options)
        factors = options.get(FACTORS) or []
        if terms is not None:
            check_comparison_controls(options, factors, terms)
        check_anova_options(options)
        model = active_factors(factors, terms) if terms is not None else list(factors)
        check_contrast_input(options, self.dialog.data, model)
        request = marginal.check_options(options, model)
        if request is not None:
            marginal.check_data(request, self.dialog.data, options.get("Response"), model)
        validate_diagnostics(options)
        graph = graph_choice(options)
        if graph != "None":
            used = active_factors(factors, terms) if terms is not None else factors
            count = _anova_row_count(self.dialog.data, options.get("Response"), used)
            if count is not None:
                ensure_graph_budget(count, graph)

    @staticmethod
    def message(error):
        """An engine error in the active language, prefixed by its field caption when the engine words it."""
        if isinstance(error, FieldError):
            return format_anova_error(error) or str(error)
        return str(error)


def attach(dialog, saved):
    """The ANOVA bindings of a dialog showing Multifactor ANOVA; None for any other analysis."""
    if dialog.method != METHOD or MODEL_TERMS not in dialog.controls:
        return None
    return AnovaFields(dialog, saved)


__all__ = ["AnovaFields", "FactorOrder", "TermEditor", "attach", "FULL", "SELECTED"]
