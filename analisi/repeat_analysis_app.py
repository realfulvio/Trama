"""Desktop integration of Analysis → Repeat analysis on other sheets… in the classic Tk window.

The engine (``repeat_analysis``) decides what travels and builds the copies, the assistant state
(``repeat_analysis_assistant``) keeps the choices and ``repeat_analysis_dialog`` draws them. This mixin calculates
every copy on the worker with progress and Cancel, and adds the copies on the Tk thread only when all of them
were calculated and the project did not change meanwhile. When a copy cannot be calculated the same assistant
opens again with its choices and the reason. The App provides ``repeat_compute`` (its Run and ``compute``).
"""
import gc

from .analysis_chain import ChainCancelled
from .repeat_analysis import RepeatError, calculate_repeat
from .repeat_analysis_assistant import RepeatAssistant, apply_repeat, prepare_job, still_current
from .repeat_analysis_dialog import RepeatDialog
from .repeat_analysis_text import error_text, method_name, t


class RepeatAnalysisMixin:
    def repeat_analysis(self, assistant=None, *, notice=None):
        if assistant is None:
            if self.pending is None and self.current_grid is not None:
                self.current_grid.commit_edit()
            if self.pending is not None:
                self.error(t("wait"))
                return
            if not self.selected or self.selected[0] not in {"result", "graph"}:
                self.error(t("select"))
                return
            if self.current_info is not None:
                self.current_info.notes_changed()
            if not self.settle_graph_draft("repeating the analysis"):
                return
            self.sync_analysis_links(persist=True)
            run = self.runs[self.selected[1]]
            if run.slot < 0:
                self.error(t("select"))
                return
            try:
                assistant = RepeatAssistant(self.tables, run.reference)
            except RepeatError as error:
                self.error(error_text(error))
                return
            if not any(problem is None for _, problem in assistant.sheets()):
                self.error(t("no_sheets"))
                return
        dialog = RepeatDialog(self.root, assistant, notice=notice)
        plan = dialog.result
        del dialog
        # The closed window is cyclic garbage holding Tk variables: free it here, on the Tk thread, so that a
        # collection on the worker never touches Tk.
        gc.collect()
        if plan is not None:  # The confirmed plan.
            self.start_repeat_job(assistant, plan)

    def start_repeat_job(self, assistant, plan):
        tables = self.tables
        try:
            staged, inputs, state = prepare_job(tables, plan)
        except (RepeatError, ValueError) as error:
            assistant.page = 1
            message = error_text(error)
            self.root.after_idle(lambda: self.repeat_analysis(assistant, notice=message))
            return
        project_key = self.active_project
        project = self.projects[project_key]
        control = self.make_chain_control()

        def job():
            return calculate_repeat(staged, plan, inputs, compute=self.repeat_compute, cancel=control.cancel,
                                    progress=control.report)

        future = self.pending = self.worker.submit(job)
        self.begin_calculation(control)
        self.status.set(t("running", sheets=len(plan.targets)))
        self.update_worksheet_history_buttons()

        def poll():
            if not future.done():
                self.root.after(60, poll)
                return
            self.pending = None
            self.end_calculation()
            try:
                self.finish_repeat(future, control, assistant, plan, staged, state, project_key, project)
            finally:
                self.update_worksheet_history_buttons()
                self.sync_inspector()
                if self.modern_workspace is not None:
                    self.modern_workspace.refresh()

        self.root.after(60, poll)

    def finish_repeat(self, future, control, assistant, plan, staged, state, project_key, project):
        try:
            calculated = future.result()
        except ChainCancelled:
            self.status.set(t("cancelled"))
            return
        except RepeatError as error:
            message = t("failed", sheet=error.sheet or "", method=method_name(error.method or ""),
                        reason=error.detail.get("reason", str(error)))
            self.status.set(message)
            if self.active_project == project_key and self.projects.get(project_key) is project:
                assistant.page = 1
                self.root.after_idle(lambda: self.repeat_analysis(assistant, notice=message))
            return
        except Exception as error:
            self.status.set(str(error))
            self.error(error)
            return
        if control.cancel.is_set():
            self.status.set(t("cancelled"))
            return
        if self.active_project != project_key or self.projects.get(project_key) is not project:
            return  # The project was closed or another one is shown: nothing is added anywhere.
        if not still_current(self.tables, plan, state):
            self.status.set(t("changed"))
            self.error(t("changed"))
            return
        try:
            added = apply_repeat(self.tables, self.runs, self.runs_for, staged, plan, calculated)
        except Exception as error:
            self.status.set(str(error))
            self.error(error)
            return
        self.dirty = True
        self.sync_analysis_links(persist=True)
        self.refresh_navigator()
        first = added[0]
        result = first.result
        kind = "graph" if result is not None and result.figure is not None and not result.tables else "result"
        self.open_sheet((kind, self.runs.index(first)))
        message = t("done", analyses=len(added), sheets=len(plan.targets))
        if calculated.styles_dropped:
            message += " " + t("style_dropped", count=len(calculated.styles_dropped))
        self.status.set(message)
