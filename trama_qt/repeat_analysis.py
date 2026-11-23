"""Analysis → Repeat analysis on other sheets… on Qt.

The engine (``analisi.repeat_analysis``) decides what travels and builds the copies; the assistant state
(``analisi.repeat_analysis_assistant``) keeps the choices. This module draws the three steps (recipe, sheets and
columns, preview), runs the calculation of every copy on the worker with progress and Cancel, and adds the copies
to the project only when all of them were calculated and the project did not change meanwhile. When a copy cannot
be calculated the same assistant opens again with its choices and the reason.
"""
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSizePolicy, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from analisi.analysis_chain import ChainCancelled
from analisi.repeat_analysis import RepeatError, calculate_repeat
from analisi.repeat_analysis_assistant import RepeatAssistant, apply_repeat, prepare_job, still_current
from analisi.repeat_analysis_text import error_text, method_name, t

from .project import CalculationControl, Run, compute, run_view
from .theme import fit_dialog

_STYLE = {"heading": "font-weight:600; margin-top:6px", "counts": "font-weight:600",
          "item": "margin-left:14px", "note": "color:#176676; margin-top:6px"}


def _html(lines):
    return "".join(f'<div style="{_STYLE[tag]}">{escape(text)}</div>' for tag, text in lines)


class RepeatDialog(QDialog):
    """Three steps over a :class:`RepeatAssistant`; ``plan`` is set when the user confirms."""

    def __init__(self, parent, assistant, *, notice=None):
        super().__init__(parent)
        self.assistant, self.plan = assistant, None
        self.setWindowTitle(t("title"))
        self.setObjectName("repeatAnalysisDialog")
        outer = QVBoxLayout(self)
        head = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName("dialogTitle")
        head.addWidget(self.heading, 1)
        self.step = QLabel()
        self.step.setObjectName("muted")
        self.step.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        head.addWidget(self.step)
        outer.addLayout(head)
        self.banner = QLabel()
        self.banner.setObjectName("errorBanner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        outer.addWidget(self.banner)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._recipe_page())
        self.pages.addWidget(self._sheets_page())
        self.pages.addWidget(self._preview_page())
        outer.addWidget(self.pages, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.back = QPushButton(t("back"))
        self.next = QPushButton(t("next"))
        self.apply = QPushButton(t("apply"))
        self.cancel = QPushButton(t("cancel"))
        for button in (self.back, self.next, self.apply, self.cancel):
            buttons.addWidget(button)
        self.back.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next.clicked.connect(lambda: self.go(self.pages.currentIndex() + 1))
        self.apply.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        outer.addLayout(buttons)
        fit_dialog(self, 860, 600)
        self.go(assistant.page, notice=notice)

    # -- pages --------------------------------------------------------------------------------
    def _recipe_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.source = QLabel(self.assistant.source_text())
        self.source.setWordWrap(True)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source)
        self.method = QLabel()
        layout.addWidget(self.method)
        self.only = QRadioButton(t("only"))
        self.follow = QRadioButton(t("follow"))
        group = QButtonGroup(page)
        group.addButton(self.only)
        group.addButton(self.follow)
        self.follow.setEnabled(self.assistant.has_followers)
        (self.follow if self.assistant.follow else self.only).setChecked(True)
        self.follow.toggled.connect(self._follow_changed)
        layout.addWidget(self.only)
        layout.addWidget(self.follow)
        self.summary = QTextBrowser()
        self.summary.setAccessibleName(t("summary"))
        layout.addWidget(self.summary, 1)
        return page

    def _sheets_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(t("sheets_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(t("sheet_list")))
        self.sheet_list = QListWidget()
        self.sheet_list.setAccessibleName(t("sheet_list"))
        self.sheet_list.setWordWrap(True)  # A refused sheet shows its whole reason.
        self.sheet_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for title, problem in self.assistant.sheets():
            item = QListWidgetItem(title, self.sheet_list)
            item.setData(Qt.ItemDataRole.UserRole, title)
            if problem is None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if title in self.assistant.selected else Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(f"{title} — {error_text(problem)}")
                item.setToolTip(error_text(problem))
        self.sheet_list.itemChanged.connect(self._sheet_checked)
        self.sheet_list.currentItemChanged.connect(self._sheet_current)
        left_layout.addWidget(self.sheet_list, 1)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_title = QLabel()
        right_layout.addWidget(self.columns_title)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([t("column_recipe"), "", t("used_by")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.table, 1)
        self.sheet_status = QLabel()
        self.sheet_status.setWordWrap(True)
        right_layout.addWidget(self.sheet_status)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        layout.addWidget(split, 1)
        return page

    def _preview_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QTextBrowser()
        self.preview.setAccessibleName(t("page.preview"))
        layout.addWidget(self.preview, 1)
        return page

    # -- behaviour ----------------------------------------------------------------------------
    def _notice(self, text):
        self.banner.setText(text or "")
        self.banner.setVisible(bool(text))

    def _follow_changed(self, checked):
        self.assistant.set_follow(checked)
        self._fill_recipe()

    def _fill_recipe(self):
        self.method.setText(self.assistant.method_text())
        self.summary.setHtml(_html(self.assistant.summary()))

    def _sheet_checked(self, item):
        title = item.data(Qt.ItemDataRole.UserRole)
        self.assistant.choose(title, item.checkState() == Qt.CheckState.Checked)
        if item.checkState() == Qt.CheckState.Checked:
            self.sheet_list.setCurrentItem(item)
        self._fill_columns()

    def _sheet_current(self, item, _previous=None):
        title = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if title in self.assistant.selected:
            self.assistant.current = title
        self._fill_columns()

    def _fill_columns(self):
        assistant = self.assistant
        title = assistant.current if assistant.current in assistant.selected else None
        self.table.setRowCount(0)
        if title is None:
            self.columns_title.setText(t("no_sheet"))
            self.table.setHorizontalHeaderLabels([t("column_recipe"), "", t("used_by")])
            self._fill_status()
            return
        self.columns_title.setText(t("column_target", sheet=title))
        self.table.setHorizontalHeaderLabels([t("column_recipe"), t("column_target", sheet=title), t("used_by")])
        chosen = assistant.columns.get(title, {})
        available = assistant.available(title)
        for row, requirement in enumerate(assistant.recipe.required):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(requirement.column))
            box = QComboBox()
            box.setAccessibleName(t("column_target", sheet=title) + " · " + requirement.column)
            box.addItem(t("choose"), "")
            for name in available:
                box.addItem(name, name)
            index = box.findData(chosen.get(requirement.column, ""))
            box.setCurrentIndex(max(index, 0))
            box.currentIndexChanged.connect(
                lambda _index, box=box, column=requirement.column: self._column_chosen(title, column, box.currentData()))
            self.table.setCellWidget(row, 1, box)
            usage = QTableWidgetItem(assistant.usage(requirement))
            usage.setToolTip(usage.text())
            self.table.setItem(row, 2, usage)
        self._fill_status()

    def _column_chosen(self, title, column, value):
        self.assistant.set_column(title, column, value or None)
        self._fill_status()

    def _fill_status(self):
        assistant = self.assistant
        for row in range(self.sheet_list.count()):
            item = self.sheet_list.item(row)
            title = item.data(Qt.ItemDataRole.UserRole)
            if title in assistant.selected:
                problems = assistant.problem_texts(title)
                item.setToolTip("\n".join(problems) or t("ready"))
        title = assistant.current if assistant.current in assistant.selected else None
        problems = assistant.problem_texts(title) if title is not None else []
        self.sheet_status.setText("\n".join(problems) if problems else (t("ready") if title else ""))
        self.sheet_status.setObjectName("errorText" if problems else "muted")
        self.sheet_status.style().unpolish(self.sheet_status)
        self.sheet_status.style().polish(self.sheet_status)
        self.next.setEnabled(self.pages.currentIndex() != 1 or assistant.ready())

    def go(self, page, *, notice=None):
        page = max(0, min(2, page))
        if page == 2:
            try:
                self.plan = self.assistant.plan()
            except RepeatError as error:
                problems = [error_text(item) for item in (error.problems or (error,))]
                self._notice("\n".join(dict.fromkeys(problems)))
                page = 1
            else:
                self.preview.setHtml(_html(self.assistant.preview(self.plan)))
        self.assistant.page = page
        self.pages.setCurrentIndex(page)
        self.heading.setText(t(("page.recipe", "page.sheets", "page.preview")[page]))
        self.step.setText(t("step", number=page + 1))
        self.step.setMinimumWidth(self.step.sizeHint().width())  # Never squeezed by a long message below.
        if page == 0:
            self._fill_recipe()
        if page == 1:
            current = next((self.sheet_list.item(row) for row in range(self.sheet_list.count())
                            if self.sheet_list.item(row).data(Qt.ItemDataRole.UserRole) == self.assistant.current),
                           None)
            if current is not None:
                self.sheet_list.setCurrentItem(current)
            self._fill_columns()
        if notice is not None:
            self._notice(notice)
        elif page != 1 or not self.banner.text():
            self._notice("")
        self.back.setEnabled(page > 0)
        self.next.setVisible(page < 2)
        self.apply.setVisible(page == 2)
        self.next.setEnabled(page != 1 or self.assistant.ready())
        (self.apply if page == 2 else self.next).setDefault(True)

    def accept(self):
        if self.pages.currentIndex() != 2:
            self.go(self.pages.currentIndex() + 1)
            return
        try:
            self.plan = self.assistant.plan()
        except RepeatError as error:
            self.go(1, notice=error_text(error))
            return
        super().accept()


def repeat_analysis(window, assistant=None, *, notice=None):
    """The command: open the assistant on the selected result or graph, then calculate and add the copies."""
    project = window.project
    if assistant is None:
        if window.busy(warn=False):
            window.error(t("wait"))
            return
        if not window.selected or window.selected[0] not in {"result", "graph"}:
            window.error(t("select"))
            return
        if not window.settle_graph_draft():
            return
        project.sync_links(persist=True)
        run = project.runs[window.selected[1]]
        if run.slot < 0:
            window.error(t("select"))
            return
        try:
            assistant = RepeatAssistant(project.tables, run.reference)
        except RepeatError as error:
            window.error(error_text(error))
            return
        if not any(problem is None for _, problem in assistant.sheets()):
            window.error(t("no_sheets"))
            return
    dialog = RepeatDialog(window, assistant, notice=notice)
    window.repeat_dialog = dialog  # The smoke drives the open assistant.
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.plan is None:
            return
    finally:
        window.repeat_dialog = None
    plan = dialog.plan
    try:
        staged, inputs, state = prepare_job(project.tables, plan)
    except (RepeatError, ValueError) as error:
        assistant.page = 1
        message = error_text(error)
        QTimer.singleShot(0, lambda: repeat_analysis(window, assistant, notice=message))
        return
    revision, control = project.revision, CalculationControl()

    def finish(title, slot, method, options, style, frame, result):
        return compute(Run(method, title, options, slot=slot, style=style), frame, result=result)

    def job():
        return calculate_repeat(staged, plan, inputs, compute=finish, cancel=control.cancel,
                                progress=control.report)

    def done(future, cancelled):
        try:
            calculated = future.result()
        except ChainCancelled:
            window.status(t("cancelled"))
            return
        except RepeatError as error:
            message = t("failed", sheet=error.sheet or "", method=method_name(error.method or ""),
                        reason=error.detail.get("reason", str(error)))
            window.status(message)
            assistant.page = 1
            QTimer.singleShot(0, lambda: repeat_analysis(window, assistant, notice=message))
            return
        except Exception as error:
            window.status(str(error))
            window.error(error)
            return
        if cancelled:
            window.status(t("cancelled"))
            return
        if window.project is not project or project.revision != revision or \
                not still_current(project.tables, plan, state):
            window.status(t("changed"))
            window.error(t("changed"))
            return
        try:
            added = apply_repeat(project.tables, project.runs, project.runs_for, staged, plan, calculated)
        except Exception as error:
            window.status(str(error))
            window.error(error)
            return
        project.dirty = True
        project.sync_links(persist=True)
        message = t("done", analyses=len(added), sheets=len(plan.targets))
        if calculated.styles_dropped:
            message += " " + t("style_dropped", count=len(calculated.styles_dropped))
        first = added[0]
        window.open_sheet((run_view(first.method), project.runs.index(first)))
        window.status(message)

    window._start(window.worker.submit(job), control, done, t("running", sheets=len(plan.targets)))
