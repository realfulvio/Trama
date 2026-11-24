"""Duplicate family… and Save family as… on Qt.

The engine (``analisi.family_workflow``) decides what a family contains and builds the copy; this module asks
for the name and shows the preview, as the classic dialog does (``analisi.family_workflow_dialog`` needs Tk).
"""
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QTextBrowser, QVBoxLayout)

from analisi.family_workflow import FamilyBlanks, FamilyError, display_name, export_plan, family_graph, plan_family, preview_family
from analisi.i18n import tr

LISTED = 12  # Names shown per section of the preview; the rest is counted.


def family_error_text(error):
    """The message of a FamilyError in the active language; unknown codes keep the English text."""
    key = f"family.error.{error.code}"
    if error.code == "name-empty":
        key += f".{error.detail.get('mode', 'name')}"
    detail = dict(error.detail)
    if "limit" in detail:
        detail["limit"] = f"{detail['limit']:,}"
    text = tr(key, **detail)
    return str(error) if text == key else text


def family_ref(project, ref):
    """The reference the engine understands for a navigator sheet, or None."""
    if not ref:
        return None
    kind, key = ref
    if kind == "data" and key in project.tables:
        return "data", key
    if kind in {"result", "graph", "saved-layout"} and type(key) is int and 0 <= key < len(project.runs):
        run = project.runs[key]
        return (kind, run.reference) if run.slot >= 0 else None
    if kind == "layout" and type(key) is int and 0 <= key < len(project.layouts):
        return "layout", key
    if kind == "info" and key in project.info_sheets:
        note = project.info_sheets[key]
        if note.worksheet:
            owner, identifier = note.worksheet.split(":", 1)
            if owner == "layout":
                return family_ref(project, (owner, int(identifier)))
            if owner in {"graph", "result", "saved-layout"}:
                for index, run in enumerate(project.runs):
                    if run.uid == identifier:
                        return family_ref(project, (owner, index))
        return "info", key
    return None


def family_lines(project, plan, preview, *, export):
    """The preview of a family as ``(tag, text)`` lines (same content as the classic window)."""
    tables, layouts = project.tables, project.layouts
    infos = {sheet.uid: sheet for sheet in project.info_sheets.values()}
    names = preview.table_names if preview is not None else {title: title for title in plan.tables}
    lines = [("heading", tr("family.contents_export" if export else "family.contents_copy"))]
    infos_count = len(plan.infos) + (len(plan.global_infos) if export else 0)
    if preview is not None and not export:
        infos_count += len(preview.snapshot_titles)
    elif plan.snapshot and not export:
        infos_count += len(plan.tables)
    lines.append(("counts", tr("family.counts", tables=len(plan.tables), analyses=plan.analysis_count,
                               layouts=len(plan.layouts), infos=infos_count)))
    if plan.shared_panels and not export:
        lines.append(("note", tr("family.note.shared_panels", count=plan.shared_panels)))
    if not export and plan.snapshot:
        lines.append(("note", tr("family.note.snapshot")))
    elif not export and plan.global_infos:
        lines.append(("note", tr("family.note.global_info")))
    if export:
        lines.append(("note", tr("family.note.export_standalone")))
        if plan.layouts:
            lines.append(("note", tr("family.note.export_layouts")))

    def section(key, entries):
        if entries:
            lines.append(("heading", tr(key)))
            lines.extend(("item", "• " + text) for text in entries[:LISTED])
            if len(entries) > LISTED:
                lines.append(("item", tr("family.more", count=len(entries) - LISTED)))

    def renamed(old, new):
        return old if old == new else f"{old} → {new}"

    section("family.section.tables", [renamed(title, names[title]) for title in plan.tables])
    analyses = []
    for title in plan.tables:
        for slot in plan.slots[title]:
            label = preview.labels.get((title, slot)) if preview is not None else None
            analyses.append(f"{names[title]}: {label or display_name(tables[title], title, slot)[1]}")
    section("family.section.analyses", analyses)
    section("family.section.layouts", [
        renamed(layouts[index].name, preview.layout_names.get(index, layouts[index].name) if preview
                else layouts[index].name) for index in plan.layouts])
    titles = [renamed(infos[uid].title, preview.info_titles.get(uid, infos[uid].title) if preview else infos[uid].title)
              for uid in plan.infos]
    if preview is not None and not export:
        titles.extend(preview.snapshot_titles.values())
    section("family.section.infos", titles)
    if export:
        section("family.section.constants", [f"{infos[uid].title}: " + ", ".join(label for label, _ in infos[uid].fields)
                                             for uid in plan.global_infos])
    return lines


def family_describer(project, selected, *, export):
    """``describe(text, include)`` → ``(error, lines)``; the dependency graph is built once."""
    tables, layouts, infos = project.tables, project.layouts, tuple(project.info_sheets.values())
    graph = family_graph(tables)

    def describe(text, include):
        plan = preview = error = None
        try:
            if export:
                plan = export_plan(tables, layouts, infos, selected, include_layouts=include, graph=graph)
            else:
                preview = preview_family(tables, layouts, infos, selected, name=text, include_layouts=include,
                                         graph=graph)
                plan = preview.plan
        except FamilyError as refused:
            error = refused
            try:
                plan = plan_family(tables, layouts, infos, selected, include_layouts=include, graph=graph)
            except FamilyError:
                plan = None
        return error, (family_lines(project, plan, preview, export=export) if plan is not None else [])
    return describe


_STYLE = {"heading": "font-weight:600; margin-top:6px", "counts": "font-weight:600",
          "item": "margin-left:14px", "note": "color:#176676; margin-top:4px"}


def family_blank_choices(project, selected):
    tables, layouts = project.tables, project.layouts
    infos = tuple(project.info_sheets.values())
    graph = family_graph(tables)

    def choices(include):
        try:
            plan = plan_family(tables, layouts, infos, selected, include_layouts=include, graph=graph)
        except FamilyError:
            return set()
        available = {key for key in ("x", "values", "row_titles")
                     if any(FamilyBlanks(**{key: True}).columns(tables[title]) for title in plan.tables)}
        if plan.analysis_count:
            available.add("graph_titles")
        return available

    return choices


class FamilyDialog(QDialog):
    """``mode`` is "duplicate" or "save"; ``result`` is ``(text, include_layouts)`` after OK."""

    def __init__(self, parent, mode, kind, describe, *, initial="", blank_choices=None):
        super().__init__(parent)
        self.setWindowTitle(tr("family.duplicate_title" if mode == "duplicate" else "family.save_title"))
        self.mode, self.describe, self.result = mode, describe, None
        outer = QVBoxLayout(self)
        self.name = None
        if mode == "duplicate":
            outer.addWidget(QLabel(tr("family.name_label" if kind == "data" else "family.prefix_label")))
            self.name = QLineEdit(initial)
            outer.addWidget(self.name)
            if kind != "data":
                hint = QLabel(tr("family.prefix_hint"))
                hint.setObjectName("muted")
                hint.setWordWrap(True)
                outer.addWidget(hint)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        self.include = QCheckBox(tr("family.include_layouts"))
        self.include.setChecked(True)
        forced, irrelevant = mode == "duplicate" and kind == "layout", kind == "saved-layout"
        if forced or irrelevant:
            self.include.setChecked(forced)
            self.include.setEnabled(False)
        outer.addWidget(self.include)
        if forced or irrelevant:
            note = QLabel(tr("family.layout_required" if forced else "family.layout_not_applicable"))
            note.setObjectName("muted")
            note.setWordWrap(True)
            outer.addWidget(note)
        self.blank_options = {}
        if blank_choices is not None:
            for key in ("x", "values", "row_titles", "graph_titles"):
                option = self.blank_options[key] = QCheckBox(tr(f"family.blank.{key}"))
                outer.addWidget(option)

            def show_available():
                available = blank_choices(self.include.isChecked())
                for key, option in self.blank_options.items():
                    option.setVisible(key in available)
                    option.setEnabled(key in available)
                    if key not in available:
                        option.setChecked(False)

            self.include.toggled.connect(show_available)
            show_available()
        self.preview = QTextBrowser()
        outer.addWidget(self.preview, 1)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("family.duplicate_button" if mode == "duplicate" else "family.choose_file"),
                          QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("family.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if self.name is not None:
            self.name.textChanged.connect(self.refresh)
        self.include.toggled.connect(self.refresh)
        self.refresh()
        self.resize(620, 520)

    def blanks(self):
        return FamilyBlanks(**{key: option.isChecked() for key, option in self.blank_options.items()})

    def text(self):
        return self.name.text() if self.name is not None else ""

    def _problem(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def refresh(self, *_):
        error, lines = self.describe(self.text(), self.include.isChecked())
        self._problem(family_error_text(error) if error is not None and error.field == "name" else "")
        if error is not None and error.field != "name":
            lines = [("note", family_error_text(error))]
        self.preview.setHtml("".join(f'<div style="{_STYLE[tag]}">{escape(line)}</div>' for tag, line in lines))

    def accept(self):
        error, _ = self.describe(self.text(), self.include.isChecked())
        if error is not None:
            self._problem(family_error_text(error))
            if self.name is not None and error.field == "name":
                self.name.setFocus()
                self.name.selectAll()
            return
        self.result = self.text(), self.include.isChecked()
        super().accept()


class FamilySheetsDialog(QDialog):
    """Navigate the sheets selected by the same dependency plan as Duplicate and Save family."""

    def __init__(self, parent, captions, refs, *, current):
        super().__init__(parent)
        self.setWindowTitle(tr("command.family_gallery"))
        self.resize(470, 330)
        self.selected = None
        layout = QVBoxLayout(self)
        self.entries = QListWidget(self)
        self.entries.setAccessibleName(tr("bar.linked_sheets"))
        for caption, ref in zip(captions, refs, strict=True):
            item = QListWidgetItem(caption, self.entries)
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setToolTip(caption)
            if ref == current:
                self.entries.setCurrentItem(item)
        if self.entries.currentRow() < 0:
            self.entries.setCurrentRow(0)
        self.entries.itemActivated.connect(lambda item: self.accept())
        layout.addWidget(self.entries)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Open).setText(tr("ribbon.open"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.entries.setFocus()

    def accept(self):
        item = self.entries.currentItem()
        if item is not None:
            self.selected = tuple(item.data(Qt.ItemDataRole.UserRole))
            super().accept()
