"""Desktop integration of Duplicate family… and Save family as….

The engine (``family_workflow``) decides what a family contains and builds the copy; this mixin asks for
the name, runs the heavy part on the worker, and applies the finished bundle on the Tk thread only.
Nothing is added to the project before the whole candidate is valid, and a cancelled or failed job
leaves the project as it was.
"""
from pathlib import Path
from tkinter import filedialog, messagebox

from .analysis_chain import ChainCancelled
from .family_workflow import (FamilyError, display_name, duplicate_family, export_plan, family_graph,
                              plan_family, preview_family, same_file, save_family)
from .family_workflow_dialog import FamilyDialog, family_error_text
from .i18n import tr

LISTED = 12  # names shown per section of the preview; the rest is counted


class FamilyWorkflowMixin:
    # ------------------------------------------------------------------ selection

    def family_ref(self, ref=None):
        """The canonical reference the engine understands for a sheet of the navigator, or None."""
        ref = ref if ref is not None else self.selected
        if not ref:
            return None
        kind, key = ref
        if kind == "data" and key in self.tables:
            return "data", key
        if kind in {"result", "graph", "saved-layout"} and type(key) is int and 0 <= key < len(self.runs):
            run = self.runs[key]
            return (kind, run.reference) if run.slot >= 0 else None
        if kind == "layout" and type(key) is int and 0 <= key < len(self.layouts):
            return "layout", key
        if kind == "info" and key in self.info_sheets:
            return "info", key
        return None

    def prepare_family(self, action):
        """Bring the stored project up to date and refuse while the worker is busy."""
        if self.pending is None and self.current_grid is not None:
            self.current_grid.commit_edit()
        if self.pending is not None:
            self.error(tr("family.wait"))
            return False
        if self.current_info is not None:
            self.current_info.notes_changed()
        if not self.settle_graph_draft(action):
            return False
        self.sync_analysis_links(persist=True)
        return True

    def family_problem(self, error):
        """A selection that cannot be a family is explained; any other refusal is an error."""
        text = family_error_text(error)
        if error.code == "global-info":
            messagebox.showinfo("Trama", text, parent=self.root)
        else:
            self.error(text)

    # ------------------------------------------------------------------ preview

    def family_lines(self, plan, preview, *, export):
        """The preview of a family as ``(tag, text)`` lines."""
        tables, layouts = self.tables, self.layouts
        infos = {sheet.uid: sheet for sheet in self.info_sheets.values()}
        names = preview.table_names if preview is not None else {title: title for title in plan.tables}
        lines = [("heading", tr("family.contents_export" if export else "family.contents_copy"))]
        infos_count = len(plan.infos) + (len(plan.global_infos) if export else 0)
        if preview is not None and not export:
            infos_count += len(preview.snapshot_titles)
        elif plan.snapshot and not export:
            infos_count += len(plan.tables)
        lines.append(("counts", tr("family.counts", tables=len(plan.tables), analyses=plan.analysis_count,
                                   layouts=len(plan.layouts), infos=infos_count)))

        def section(key, entries):
            if not entries:
                return
            lines.append(("heading", tr(key)))
            lines.extend(("item", "• " + text) for text in entries[:LISTED])
            if len(entries) > LISTED:
                lines.append(("item", tr("family.more", count=len(entries) - LISTED)))

        def renamed(old, new):
            return old if old == new else f"{old} → {new}"

        section("family.section.tables", [renamed(title, names[title]) for title in plan.tables])
        analyses = []
        for title in plan.tables:
            dataset = tables[title]
            for slot in plan.slots[title]:
                label = preview.labels.get((title, slot)) if preview is not None else None
                analyses.append(f"{names[title]}: {label or display_name(dataset, title, slot)[1]}")
        section("family.section.analyses", analyses)
        section("family.section.layouts", [
            renamed(layouts[index].name, preview.layout_names.get(index, layouts[index].name) if preview else
                    layouts[index].name) for index in plan.layouts])
        titles = [renamed(infos[uid].title, preview.info_titles.get(uid, infos[uid].title) if preview else
                          infos[uid].title) for uid in plan.infos]
        if preview is not None and not export:
            titles.extend(preview.snapshot_titles.values())
        section("family.section.infos", titles)
        if export:
            section("family.section.constants", [
                f"{infos[uid].title}: " + ", ".join(label for label, _ in infos[uid].fields)
                for uid in plan.global_infos])
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
        return lines

    def family_describer(self, selected, *, export):
        """``describe(text, include)`` for the dialog: the refusal of the engine and the preview lines.
        The dependency graph is built once; the preview never copies a table."""
        tables, layouts, infos = self.tables, self.layouts, tuple(self.info_sheets.values())
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
            return error, (self.family_lines(plan, preview, export=export) if plan is not None else [])
        return describe

    # ------------------------------------------------------------------ commands

    def duplicate_family(self, ref=None):
        selected = self.family_ref(ref)
        if selected is None:
            self.error(tr("family.select"))
            return
        if not self.prepare_family("duplicating the family"):
            return
        describe = self.family_describer(selected, export=False)
        kind, key = selected
        if kind == "data":
            initial, number = tr("family.default_name", title=key), 2
            base = initial
            while initial in self.tables:
                initial, number = f"{base} ({number})", number + 1
        else:
            initial = tr("family.default_prefix")
        error, _ = describe(initial, True)
        if error is not None and error.field != "name":
            self.family_problem(error)
            return
        dialog = FamilyDialog(self.root, "duplicate", kind, describe, initial=initial)
        if dialog.result is None:
            return
        name, include = dialog.result
        tables, layouts, infos = self.tables, self.layouts, tuple(self.info_sheets.values())
        control = self.make_chain_control()

        def job():
            return duplicate_family(tables, layouts, infos, selected, name=name, include_layouts=include,
                                    cancel=control.cancel)

        self.start_family_job(job, control, running=tr("family.copying"), cancelled=tr("family.cancelled"),
                              failed="family.failed", finish=self.apply_family, discard_when_cancelled=True)

    def save_family_as(self, ref=None):
        selected = self.family_ref(ref)
        if selected is None:
            self.error(tr("family.select"))
            return
        if not self.prepare_family("saving the family"):
            return
        describe = self.family_describer(selected, export=True)
        error, _ = describe("", True)
        if error is not None:
            self.family_problem(error)
            return
        dialog = FamilyDialog(self.root, "save", selected[0], describe)
        if dialog.result is None:
            return
        _, include = dialog.result
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".alab",
                                            initialfile=tr("family.default_file"),
                                            filetypes=[(tr("prompt.project_filetype"), "*.alab")])
        if not path:
            return
        path = Path(path)
        try:
            if path.suffix.lower() != ".alab":
                self.error(tr("error.alab_name"))
                return
            if self.path is not None and same_file(path, self.path):
                raise FamilyError("current-path", "Choose a new file: the current project cannot be replaced.")
            if self.open_project_for_path(path) is not None:
                self.error(tr("error.open_elsewhere"))
                return
        except FamilyError as refused:
            self.family_problem(refused)
            return
        tables, layouts, infos = self.tables, self.layouts, tuple(self.info_sheets.values())
        source = self.path
        control = self.make_chain_control()

        def job():
            return save_family(path, tables, layouts, infos, selected, include_layouts=include,
                               source_path=source, cancel=control.cancel)

        self.start_family_job(job, control, running=tr("family.saving"), cancelled=tr("family.save_cancelled"),
                              failed="family.save_failed", finish=lambda bundle: self.family_saved(path, bundle),
                              discard_when_cancelled=False)

    # ------------------------------------------------------------------ worker

    def start_family_job(self, job, control, *, running, cancelled, failed, finish, discard_when_cancelled):
        """Run ``job`` on the worker. The result is applied on the Tk thread by ``finish`` unless the user
        cancelled (a copy is then discarded whole) or the project changed in the meantime."""
        project_key = self.active_project
        project = self.projects[project_key]
        future = self.pending = self.worker.submit(job)
        self.begin_calculation(control)
        self.status.set(running)
        self.update_worksheet_history_buttons()
        self.sync_inspector()
        if self.modern_workspace is not None:
            self.modern_workspace.refresh()

        def poll():
            if not future.done():
                self.root.after(60, poll)
                return
            self.pending = None
            self.end_calculation()
            try:
                try:
                    outcome = future.result()
                except ChainCancelled:
                    self.status.set(cancelled)
                    return
                if discard_when_cancelled and control.cancel.is_set():
                    self.status.set(cancelled)
                    return
                if self.active_project != project_key or self.projects.get(project_key) is not project:
                    return
                finish(outcome)
            except Exception as error:
                message = tr(failed, error=family_error_text(error) if isinstance(error, FamilyError) else error)
                self.status.set(message)
                self.error(message)
            finally:
                self.update_worksheet_history_buttons()
                self.sync_inspector()
                if self.modern_workspace is not None:
                    self.modern_workspace.refresh()

        self.root.after(60, poll)

    # ------------------------------------------------------------------ applying

    def apply_family(self, bundle):
        """Add a finished copy to the project (Tk thread). All or nothing: any failure restores the project."""
        for title in bundle.tables:
            if title in self.tables:
                raise ValueError(f'A data table named "{title}" already exists.')
        runs_before, layouts_before = len(self.runs), len(self.layouts)
        infos_before, dirty_before = self.info_sheets, self.dirty
        try:
            self.tables.update(bundle.tables)
            for title, dataset in bundle.tables.items():
                self.runs.extend(self.runs_for(title, dataset))
            self.layouts.extend(bundle.layouts)
            if bundle.infos:
                self.update_info_sheets({**self.info_sheets, **{sheet.uid: sheet for sheet in bundle.infos}})
            self.dirty = True
        except Exception:
            for title in bundle.tables:
                self.tables.pop(title, None)
            del self.runs[runs_before:]
            del self.layouts[layouts_before:]
            self.info_sheets = infos_before
            self.dirty = dirty_before
            raise
        self.sync_analysis_links()
        self.refresh_navigator()
        self.open_sheet(self.family_focus(bundle, layouts_before))
        self.status.set(tr("family.duplicated", tables=len(bundle.tables), analyses=bundle.analysis_count,
                           layouts=len(bundle.layouts), infos=len(bundle.infos)))

    def family_focus(self, bundle, layouts_before):
        """The navigator reference of the copy of the sheet the user started from."""
        kind, key = bundle.focus
        if kind in {"result", "graph", "saved-layout"}:
            index = next((i for i, run in enumerate(self.runs) if run.reference == key), None)
            if index is not None:
                return kind, index
        elif kind == "layout":
            return kind, layouts_before + key
        elif kind == "info" and key in self.info_sheets:
            return kind, key
        elif kind == "data":
            return kind, key
        return "data", next(iter(bundle.tables))

    def family_saved(self, path, bundle):
        """A family was written; the current project, its path, selection and history are untouched."""
        self.status.set(tr("family.saved", name=path.name, tables=len(bundle.tables), analyses=bundle.analysis_count,
                           layouts=len(bundle.layouts), infos=len(bundle.infos)))
