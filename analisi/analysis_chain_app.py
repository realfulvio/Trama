"""Desktop integration for worker-evaluated, persistent result dependencies."""
from copy import copy, deepcopy
from types import SimpleNamespace

from .analysis_chain import AnalysisGraph, ChainCancelled, evaluate_graph, result_frame
from .i18n import tr


class AnalysisChainMixin:
    def populate_chain_results(self, parent, data_entries, result_entries, matches, *, source_ids=False):
        """Insert source analyses before their children, independently of recipe order."""
        by_id = {run.uid: (run, index) for index, run in enumerate(self.runs)}
        names = {self.runs[ref[1]].uid: name for name, ref in result_entries}
        needed = {self.runs[ref[1]].uid for name, ref in result_entries if matches(name, ref)}
        pending = list(needed)
        while pending:
            source = by_id[pending.pop()][0].source
            if source is not None and source.analysis_id not in needed:
                needed.add(source.analysis_id)
                pending.append(source.analysis_id)
        visible_titles = {by_id[key][0].title for key in needed}
        visible_titles.update(title for title, ref in data_entries if matches(title, ref))
        roots, nodes = {}, {}
        for title in self.tables:
            if title not in visible_titles:
                continue
            options = {'iid': f'source:{title}'} if source_ids else {}
            roots[title] = self.add_sheet_node(parent, title, ('data', title), open=True, **options)
        for identifier in self.analysis_graph().order:
            if identifier not in needed:
                continue
            run, index = by_id[identifier]
            owner = nodes.get(run.source.analysis_id) if run.source is not None else None
            owner = owner or roots.get(run.title, parent)
            name = names.get(identifier, run.name)
            nodes[identifier] = self.add_sheet_node(owner, self.navigator_label(name, ('result', index)),
                                                    ('result', index), open=True)
        return roots, nodes

    def analyze_result_table(self):
        if self.pending is not None:
            self.error(tr('chain.wait'))
            return
        if not self.selected or self.selected[0] != 'result':
            self.error(tr('chain.select_result'))
            return
        if not self.require_current_calculation():
            return
        run = self.runs[self.selected[1]]
        if run.result is None or not hasattr(self, 'result_tabs'):
            self.error(tr('chain.calculate_source'))
            return
        table = list(run.result.tables)[self.result_tabs.index('current')]
        try:
            frame = result_frame(run.result, table)
        except ValueError as error:
            self.error(error)
            return
        dialog = self.chain_analysis_dialog(frame)
        if dialog.result:
            from .analysis_chain import ResultSource
            self.submit_new_analysis(run.title, frame, dialog, source=ResultSource(run.uid, table))

    def source_analysis(self):
        if not self.selected or self.selected[0] not in {'result', 'graph'}:
            return
        run = self.runs[self.selected[1]]
        if run.source is None:
            self.show('data', run.title)
            return
        index = next((i for i, parent in enumerate(self.runs) if parent.uid == run.source.analysis_id), None)
        if index is None:
            self.error(tr('chain.missing_source'))
            return
        self.show('result', index)
        parent = self.runs[index]
        if parent.result is not None and run.source.table in parent.result.tables:
            self.result_tabs.select(list(parent.result.tables).index(run.source.table))

    def change_input_result(self):
        from .analysis_source_dialog import AnalysisSourceDialog
        if self.pending is not None:
            self.error(tr('chain.wait'))
            return
        if not self.selected or self.selected[0] not in {'result', 'graph'}:
            self.error(tr('chain.select_result'))
            return
        index = self.selected[1]
        run = self.runs[index]

        def validate(source):
            candidate = copy(run)
            candidate.source = source
            self.analysis_graph(replacement=(index, candidate))

        choice = AnalysisSourceDialog(self.root, run, self.runs, validate)
        if choice.result is None:
            return
        source, = choice.result
        if source == run.source:
            return
        candidate = copy(run)
        candidate.source = source
        try:
            frame = self.input_frame(candidate)
        except ValueError as error:
            self.error(error)
            return
        dialog = self.chain_analysis_dialog(frame, current=(run.method, run.options), only=run.method)
        if dialog.result:
            self.submit_edit(index, frame, dialog, source=source, change_source=True)

    def sync_analysis_links(self, *, persist=False):
        linked = {run.uid for run in self.runs if run.source is not None}
        parents = {run.source.analysis_id for run in self.runs if run.source is not None}
        self._chain_node_ids = linked | parents
        if persist:
            for run in self.runs:
                if run.slot < 0:
                    continue
                dataset = self.tables[run.title]
                if linked or run.slot in dataset.analysis_ids:
                    dataset.analysis_ids[run.slot] = run.uid
                if run.source is not None:
                    dataset.analysis_sources[run.slot] = run.source
                else:
                    dataset.analysis_sources.pop(run.slot, None)
                if run.label is not None:
                    dataset.analysis_labels[run.slot] = run.label
                else:
                    dataset.analysis_labels.pop(run.slot, None)

    def analysis_graph(self, *, replacement=None, additional=None):
        from .pairwise_graph import read_section
        runs = list(self.runs)
        if replacement is not None:
            runs[replacement[0]] = replacement[1]
        if additional is not None:
            runs.append(additional)
        references = {run.reference: run.uid for run in runs}
        dependencies = {}
        for run in runs:
            settings, _ = read_section(run.options)
            reference = (run.title, settings['slot']) if settings else None
            if reference in references:
                dependencies[run.uid] = [references[reference]]
        return AnalysisGraph([(run.uid, run.source) for run in runs], dependencies=dependencies)

    def input_frame(self, run):
        if run.source is None:
            return self.tables[run.title].frame(mask_excluded=True)
        parent = next((other for other in self.runs if other.uid == run.source.analysis_id), None)
        if parent is None:
            raise ValueError(tr('chain.missing_source'))
        if parent.calculation_error or parent.result is None:
            raise ValueError(tr('chain.calculate_source'))
        return result_frame(parent.result, run.source.table)

    def chain_dependents(self, run):
        return [other for other in self.runs
                if other.source is not None and other.source.analysis_id == run.uid]

    def refresh_chain_calculations(self, affected, *, after=None, inputs_changed=True):
        """Return False when the original, unlinked refresh path is appropriate."""
        self.sync_analysis_links()
        seeds = {run.uid for run, _ in affected}
        busy = self.pending is not None and self.pending is getattr(self, '_chain_future', None)
        if not seeds.intersection(self._chain_node_ids) and not busy:
            return False
        if self.pending is not None:
            if self.pending is not getattr(self, '_chain_future', None):
                raise ValueError(tr('chain.wait'))
            self._chain_generation += 1
            self._chain_queue.update(seeds)
            # The old worker uses immutable input snapshots. Its callback will
            # discard that revision and calculate the newest queued data.
            self.calculation.cancel.set()
            return True

        graph = self.analysis_graph()
        unavailable = {run.uid for run in self.runs if run.result is None or run.calculation_error}
        selected = graph.affected(seeds, unavailable=unavailable)
        live = {run.uid: run for run in self.runs}
        cached = {run.uid: run.result for run in self.runs
                  if run.result is not None and not run.calculation_error and run.uid not in selected}
        clones, pairwise, roots, previous_errors = {}, {}, {}, {}
        frames = {}
        for identifier in selected:
            run = live[identifier]
            previous_errors[identifier] = run.calculation_error
            candidate = clones[identifier] = copy(run)
            candidate.options, candidate.style = deepcopy(run.options), deepcopy(run.style)
            pairwise[identifier] = self.pairwise_snapshot(run)
            if run.source is None:
                if run.title not in frames:
                    frames[run.title] = self.tables[run.title].frame(mask_excluded=True)
                roots[identifier] = frames[run.title]
            run.calculation_error = tr('chain.pending')

        control = self.make_chain_control()
        control.report(0, len(selected))
        node_control = SimpleNamespace(cancel=control.cancel, report=lambda *_: None)
        fresh = dict(cached)
        references = {run.reference: run.uid for run in self.runs}

        def calculate(identifier, frame):
            snapshot = pairwise[identifier]
            if snapshot and (source := references.get(snapshot.get('key'))) in fresh:
                snapshot = {**snapshot, 'tables': fresh[source].tables}
            return self.compute(clones[identifier], frame.copy(deep=True), control=node_control,
                                pairwise=snapshot)

        def work():
            return evaluate_graph(graph, selected, roots, cached, calculate, cancel=control.cancel,
                                  progress=control.report, on_result=lambda key, value: fresh.__setitem__(key, value))

        generation = self._chain_generation = getattr(self, '_chain_generation', 0) + 1
        self._chain_queue = set()
        project_key = self.active_project
        project = self.projects[project_key]
        future = self._chain_future = self.worker.submit(work)
        self.pending = future
        self.begin_calculation(control)
        self.update_worksheet_history_buttons()
        self.sync_inspector()

        def finished():
            if self.pending is not future:
                return
            if not future.done():
                self.show_calculation_progress(tr('chain.progress'))
                self.root.after(60, finished)
                return
            self.pending = self._chain_future = None
            self.end_calculation()
            if self.active_project != project_key or self.projects.get(project_key) is not project:
                return
            if generation != self._chain_generation:
                queued = self._chain_queue | seeds
                self._chain_queue = set()
                self.refresh_chain_calculations([(live[key], None) for key in queued if key in live], after=after)
                return
            errors = []
            try:
                outcomes = future.result()
            except ChainCancelled:
                for identifier in selected:
                    live[identifier].calculation_error = (
                        tr('chain.cancelled_stale') if inputs_changed
                        else previous_errors[identifier])
                self.status.set(tr('chain.cancelled'))
            except Exception as error:
                for identifier in selected:
                    live[identifier].calculation_error = str(error)
                errors.append(str(error))
            else:
                for identifier, outcome in outcomes.items():
                    run = live[identifier]
                    if outcome.error is None:
                        run.result, run.calculation_error = outcome.result, None
                    else:
                        run.calculation_error = str(outcome.error)
                        errors.append(str(outcome.error))
                self.status.set(tr('chain.failed', count=len(errors)) if errors
                                else tr('chain.updated', count=len(outcomes)))
            self.refresh_navigator()
            if self.modern_workspace is not None:
                self.modern_workspace.refresh()
            if self.selected and self.selected[0] in {'result', 'graph', 'layout'} and self.gallery is None:
                self.show(*self.selected)
            self.update_worksheet_history_buttons()
            self.sync_inspector()
            if after is not None and not control.cancel.is_set():
                after()

        self.root.after(60, finished)
        return True
