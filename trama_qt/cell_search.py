"""Edit → Find in Cells… / Replace in Cells…: one reusable panel for the active data or results sheet.

The panel never creates a Qt index or widget per cell: the scan reads the table behind the view
(``analisi.cell_search``) in short steps driven by a timer, so a long sheet stays responsive and the
scan can be stopped. Moving between matches selects the cell and scrolls it into view.
"""
from dataclasses import dataclass
import time

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from analisi.cell_search import (PREVIEW_ROWS, REASONS, CellScan, SearchOptions, cell_name, plan_replace,
                                 worksheet_texts)
from analisi.i18n import tr, ui

from .models import display
from .strings import qt
from .theme import fit_dialog

SLICE_SECONDS = 0.03  # One timer tick works this long, then the window handles its events.


@dataclass
class Target:
    """The sheet a search runs on: a worksheet or the visible result table."""
    view: object
    project: object
    selected: tuple
    tab: int
    read_only: str | None  # The qt() key that says why replacing is not possible, or None.

    @property
    def identity(self):
        return id(self.project), self.selected, self.tab

    @property
    def key(self):
        return (*self.identity, self.project.revision)


def search_target(window):
    """The active sheet the panel can search, or None (graphs, layouts, info sheets, the gallery)."""
    if window.gallery is not None or not window.selected:
        return None
    if window.selected[0] == "data" and window.sheet is not None:
        from .project import stored_legacy_view

        title = window.selected[1]
        reason = ("qt.find_only_frozen" if window.project.sheet_locked(window.selected)
                  else "qt.find_only_view" if stored_legacy_view(window.project.tables[title]) else None)
        return Target(window.sheet, window.project, window.selected, -1, reason)
    if window.selected[0] == "result" and window.result_tabs is not None:
        view = window.result_tabs.currentWidget()
        if view is not None and hasattr(view.model(), "display_text"):
            return Target(view, window.project, window.selected, window.result_tabs.currentIndex(),
                          "qt.find_only_results")
    return None


def _result_texts(model):
    def texts(column, start, stop):
        rows = []
        for row in range(start, stop):
            shown, stored = model.display_text(row, column), model.plain_text(row, column)
            rows.append((stored, shown) if stored or shown else None)
        return rows
    return texts


def build_scan(target, options, ranges=None, chunk=1024):
    model = target.view.model()
    if target.selected[0] == "data":
        frame = model.frame
        texts = worksheet_texts(frame, options, model.formats, display)
        return CellScan(len(frame), len(frame.columns), texts, options, ranges=ranges, chunk=chunk)
    return CellScan(model.rowCount(), model.columnCount(), _result_texts(model), options, ranges=ranges,
                    chunk=chunk)


def selection_ranges(view):
    """Every selected rectangle (a selection may have several), or the current cell."""
    selection = view.selectionModel()
    ranges = [(item.top(), item.left(), item.bottom(), item.right())
              for item in (selection.selection() if selection is not None else []) if not item.isEmpty()]
    if not ranges and view.currentIndex().isValid():
        current = view.currentIndex()
        ranges = [(current.row(), current.column(), current.row(), current.column())]
    return ranges


class CellSearchPanel(QDialog):
    """Find, Previous/Next with count and position, Replace All with a preview."""

    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self.setObjectName("cellSearchPanel")
        self.setModal(False)
        self.setWindowTitle(qt("qt.find_title"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.query = QLineEdit()
        self.query.setClearButtonEnabled(True)
        self.query.setAccessibleName(qt("qt.find_what").rstrip(":"))
        self.replacement = QLineEdit()
        self.replacement.setClearButtonEnabled(True)
        self.replacement.setAccessibleName(qt("qt.find_replace_with").rstrip(":"))
        self.scope = QComboBox()
        self.scope.addItem(qt("qt.find_scope_sheet"), "sheet")
        self.scope.addItem(qt("qt.find_scope_selection"), "selection")
        form.addRow(qt("qt.find_what"), self.query)
        form.addRow(qt("qt.find_replace_with"), self.replacement)
        form.addRow(qt("qt.find_scope"), self.scope)
        layout.addLayout(form)
        options = QHBoxLayout()
        self.case = QCheckBox(qt("qt.find_case"))
        self.whole = QCheckBox(qt("qt.find_whole"))
        options.addWidget(self.case)
        options.addWidget(self.whole)
        options.addStretch(1)
        layout.addLayout(options)
        hint = QLabel(qt("qt.find_literal"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.notice = QLabel()
        self.notice.setObjectName("infoBanner")
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        self.position = QLabel(" ")
        self.position.setAccessibleName(qt("qt.find_count", total="").strip())
        layout.addWidget(self.position)
        progress = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.stop_button = QPushButton(qt("qt.find_stop"))
        self.stop_button.setAutoDefault(False)
        self.stop_button.clicked.connect(self.stop_scan)
        progress.addWidget(self.progress, 1)
        progress.addWidget(self.stop_button)
        layout.addLayout(progress)
        self.progress.hide()
        self.stop_button.hide()
        buttons = QHBoxLayout()
        self.previous_button = QPushButton(qt("qt.find_previous"))
        self.previous_button.setToolTip(qt("qt.find_previous_tip"))
        self.next_button = QPushButton(qt("qt.find_next"))
        self.next_button.setToolTip(qt("qt.find_next_tip"))
        self.replace_button = QPushButton(qt("qt.find_replace_all"))
        self.close_button = QPushButton(qt("qt.find_close"))
        for button in (self.previous_button, self.replace_button, self.close_button):
            button.setAutoDefault(False)
        self.next_button.setDefault(True)  # Enter in «Find» goes to the next match.
        self.previous_button.clicked.connect(lambda: self.find(-1))
        self.next_button.clicked.connect(lambda: self.find(1))
        self.replace_button.clicked.connect(self.replace_all)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        buttons.addWidget(self.replace_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        for sequence, step in (("F3", 1), ("Shift+F3", -1), ("Shift+Return", -1), ("Shift+Enter", -1)):
            QShortcut(QKeySequence(sequence), self, activated=lambda step=step: self.find(step))
        self.query.textChanged.connect(self._options_changed)  # The replacement text does not change the matches.
        self.case.toggled.connect(self._options_changed)
        self.whole.toggled.connect(self._options_changed)
        self.scope.currentIndexChanged.connect(self._options_changed)
        self.matches = None      # Matches of the last complete scan.
        self.scan = None         # The scan in progress.
        self.index = -1
        self.scanned = None      # (target key, options, ranges) of ``matches``.
        self.ranges = None       # The selection captured when the search started (kept while moving).
        self.ranges_for = None   # Sheet identity the captured selection belongs to.
        self.own_cell = None     # The cell the panel selected last: then the selection is still the scope.
        self._then = None
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._scan_step)
        fit_dialog(self, 470, 300)

    # -- state -------------------------------------------------------------------------------
    def options(self):
        return SearchOptions(self.query.text(), self.case.isChecked(), self.whole.isChecked())

    def present(self, *, replace=False):
        self.refresh_target()
        self.show()
        self.raise_()
        self.activateWindow()
        field = self.replacement if replace and self.replacement.isEnabled() and self.query.text() else self.query
        field.setFocus()
        field.selectAll()

    def refresh_target(self):
        """Enable what the active sheet allows and say why replacing is not possible."""
        target = search_target(self.host)
        reason = qt("qt.find_no_sheet") if target is None else qt(target.read_only) if target.read_only else ""
        self.notice.setText(reason)
        self.notice.setVisible(bool(reason))
        writable = target is not None and target.read_only is None
        idle = self.host.job is None
        self.replacement.setEnabled(writable)
        self.replace_button.setEnabled(writable and idle)
        for button in (self.previous_button, self.next_button):
            button.setEnabled(target is not None)
        return target

    def sheet_changed(self):
        """The window shows another sheet: a scan stops and the next search starts again there."""
        if self.scan is not None:
            self.stop_scan(quiet=True)
        if self.matches is not None or self.index >= 0:
            self.position.setText(qt("qt.find_sheet_changed"))
        self.matches, self.index, self.scanned = None, -1, None
        if self.isVisible():
            self.refresh_target()

    def _options_changed(self, *_):
        if self.scan is not None:
            self.stop_scan(quiet=True)
        self.matches, self.index, self.scanned = None, -1, None
        if self.sender() is self.scope:
            self.ranges = None
        self.position.setText(" ")

    def _scope_ranges(self, target):
        if self.scope.currentData() != "selection":
            return None
        current = target.view.currentIndex()
        here = (current.row(), current.column()) if current.isValid() else None
        if self.ranges is None or self.ranges_for != target.identity or here != self.own_cell:
            self.ranges = selection_ranges(target.view)
            self.ranges_for = target.identity
        return self.ranges

    # -- scanning ------------------------------------------------------------------------------
    def _ensure_scan(self, then):
        """Run ``then(target)`` on fresh matches, scanning first if the sheet or the options changed."""
        target = self.refresh_target()
        if target is None:
            self.position.setText(qt("qt.find_no_sheet"))
            return
        options = self.options()
        if not options.query:
            self.position.setText(qt("qt.find_empty"))
            self.query.setFocus()
            return
        ranges = self._scope_ranges(target)
        if ranges is not None and not ranges:
            self.position.setText(qt("qt.find_no_selection"))
            return
        wanted = (target.key, options, tuple(ranges) if ranges is not None else None)
        if self.matches is not None and self.scanned == wanted:
            then(target)
            return
        if self.scanned is not None and self.scanned[0][:3] != target.key[:3]:
            self.position.setText(qt("qt.find_sheet_changed"))
        self.stop_scan(quiet=True)
        self.matches, self.index = None, -1
        self.scan = build_scan(target, options, ranges)
        self._scan_target, self._scan_wanted, self._then = target, wanted, then
        self.progress.setValue(0)
        self.progress.show()
        self.stop_button.show()
        self._scan_step()
        if self.scan is not None:
            self._timer.start()

    def _scan_step(self):
        scan = self.scan
        if scan is None:
            self._timer.stop()
            return
        current = search_target(self.host)
        if current is None or current.key != self._scan_target.key:
            self.stop_scan(quiet=True)
            self.position.setText(qt("qt.find_sheet_changed"))
            return
        deadline = time.perf_counter() + SLICE_SECONDS
        done = scan.done
        while not done and time.perf_counter() < deadline:
            done = scan.step()
        percent = round(100 * scan.progress)
        self.progress.setValue(percent)
        if not done:
            self.position.setText(qt("qt.find_scanning", percent=percent))
            return
        self._timer.stop()
        self.scan = None
        self.progress.hide()
        self.stop_button.hide()
        self.matches, self.scanned = scan.matches, self._scan_wanted
        then, self._then = self._then, None
        if then is not None:
            then(self._scan_target)

    def stop_scan(self, *, quiet=False):
        if self.scan is None:
            return
        self._timer.stop()
        self.scan, self._then = None, None
        self.progress.hide()
        self.stop_button.hide()
        if not quiet:
            self.position.setText(qt("qt.find_stopped"))

    def run_scan_now(self):
        """Finish a scan in progress at once (tests and Replace All on a short table)."""
        while self.scan is not None:
            self._scan_step()

    # -- moving between matches -------------------------------------------------------------------
    def find(self, step=1):
        self._ensure_scan(lambda target: self._move(target, step))

    def _move(self, target, step):
        matches = self.matches or []
        if not matches:
            self.index = -1
            self.position.setText(qt("qt.find_none"))
            return
        wrapped = False
        if 0 <= self.index < len(matches):
            index = self.index + step
        else:  # First move after a scan: start from the current cell, as in a spreadsheet.
            current = target.view.currentIndex()
            here = (current.row(), current.column()) if current.isValid() else (0, -1)
            include = here != self.own_cell  # A match the panel just showed is not found again.
            if step > 0:
                index = next((position for position, cell in enumerate(matches)
                              if cell > here or (include and cell == here)), len(matches))
            else:
                index = next((position for position in range(len(matches) - 1, -1, -1)
                              if matches[position] < here), -1)
        if index >= len(matches):
            index, wrapped = 0, True
        elif index < 0:
            index, wrapped = len(matches) - 1, True
        self.index = index
        row, column = matches[index]
        self._show_cell(target, row, column)
        text = qt("qt.find_position", index=index + 1, total=len(matches), cell=self._address(target, row, column))
        if wrapped and len(matches) > 1:
            text += "\n" + qt("qt.find_wrapped_end" if step > 0 else "qt.find_wrapped_start")
        self.position.setText(text)

    def _address(self, target, row, column):
        if target.selected[0] == "data":
            return cell_name(row, column)
        model = target.view.model()
        return f"{model.headerData(column, Qt.Orientation.Horizontal)} · {row + 1}"

    def _show_cell(self, target, row, column):
        view = target.view
        index = view.model().index(row, column)
        view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        self.own_cell = (row, column)

    # -- replacing -----------------------------------------------------------------------------------
    def replace_all(self):
        target = self.refresh_target()
        if target is None or target.read_only is not None or self.host.busy():
            return
        self._ensure_scan(self._preview)

    def _preview(self, target):
        dataset = target.project.tables[target.selected[1]]
        plan = plan_replace(dataset, target.view.model().frame, self.matches or [], self.options(),
                            self.replacement.text(), title=target.selected[1], revision=target.project.revision)
        self.position.setText(qt("qt.find_count", total=len(self.matches or [])))
        dialog = ReplacePreviewDialog(self, plan)
        self.preview = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if self.host.replace_in_cells(target, plan):
                    self.matches, self.index, self.scanned = None, -1, None
                    self.position.setText(qt("qt.replaced", count=len(plan.changes)))
        finally:
            self.preview = None
            dialog.deleteLater()

    def closeEvent(self, event):
        self.stop_scan(quiet=True)
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.scan is not None:
            self.stop_scan()
            return
        super().keyPressEvent(event)


def reason_details(skipped):
    return "; ".join(qt(f"qt.replace_reason_{reason}", count=skipped[reason]) for reason in REASONS
                     if skipped.get(reason))


class ReplacePreviewDialog(QDialog):
    """Address, before and after for the first changes, the total and what is left alone (and why)."""

    def __init__(self, parent, plan):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(qt("qt.replace_title"))
        layout = QVBoxLayout(self)
        summary = QLabel(qt("qt.replace_summary", query=plan.options.query, replacement=plan.replacement,
                            changes=len(plan.changes), total=plan.total))
        summary.setWordWrap(True)
        layout.addWidget(summary)
        if len(plan.changes) > PREVIEW_ROWS:
            layout.addWidget(QLabel(qt("qt.replace_shown", shown=PREVIEW_ROWS)))
        self.table = QTableWidget(len(plan.preview), 3)
        self.table.setHorizontalHeaderLabels([qt("qt.replace_cell"), qt("qt.replace_before"),
                                              qt("qt.replace_after")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        empty = qt("qt.replace_empty")
        for line, (row, column, _source, before, after) in enumerate(plan.preview):
            for position, text in enumerate((cell_name(row, column), before, after or empty)):
                self.table.setItem(line, position, QTableWidgetItem(text))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        details = reason_details(plan.skipped)
        self.skipped = QLabel(qt("qt.replace_skipped", details=details) if details else "")
        self.skipped.setObjectName("muted")
        self.skipped.setWordWrap(True)
        self.skipped.setVisible(bool(details))
        layout.addWidget(self.skipped)
        problem = (qt("qt.replace_too_long", cell=plan.too_long) if plan.too_long
                   else qt("qt.replace_refused", error=ui(plan.problem)) if plan.problem
                   else qt("qt.replace_nothing") if not plan.changes else "")
        self.problem = QLabel(problem)
        self.problem.setObjectName("infoBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(bool(problem))
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText(qt("qt.replace_apply"))
        self.apply_button.setEnabled(not problem)
        self.apply_button.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        fit_dialog(self, 640, 460)


__all__ = ["CellSearchPanel", "ReplacePreviewDialog", "search_target", "build_scan"]
