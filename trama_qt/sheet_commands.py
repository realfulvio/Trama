"""Project operations addressed to an individual sheet in the navigator."""
from copy import copy, deepcopy
from dataclasses import replace
from uuid import uuid4

from analisi import worksheet_join
from analisi.data import info_references
from analisi.info import InfoSheet, info_contexts
from analisi.legacy_layout_edit import LEGACY_PANEL_DATA
from analisi.legacy_restore import LEGACY_GRAPH_LINK
from analisi.pairwise_graph import SECTION as PAIRWISE_SECTION, read_section
from analisi.sheet_metadata import HIGHLIGHTS, RUN_KINDS, validate_sheet_title
from analisi.worksheet_history import WorksheetChange

from .strings import qt


SLOT_RECORDS = ("graph_styles", "result_backgrounds", "result_number_formats", "result_text_styles", "analysis_ids",
                "analysis_sources", "analysis_labels")


class SheetCommands:
    def sheet_identity(self, ref):
        kind, key = ref
        return kind, self.runs[key].uid if kind in RUN_KINDS else key

    def sheet_key(self, ref):
        return "{}:{}".format(*self.sheet_identity(ref))

    def sheet_state(self, ref):
        return self.sheet_metadata.get("sheets", {}).get(self.sheet_key(ref), {})

    def set_sheet_state(self, ref, **updates):
        records = self.sheet_metadata.setdefault("sheets", {})
        key = self.sheet_key(ref)
        current = records.get(key, {})
        revised = current | updates
        revised = {field: value for field, value in revised.items() if value is not None}
        if revised != current:
            if revised:
                records[key] = revised
            else:
                records.pop(key, None)
            self.dirty = True

    def frozen(self, run):
        return run.uid in self.sheet_metadata.get("frozen_runs", {})

    def sheet_locked(self, ref):
        kind, key = ref
        return self.frozen(self.runs[key]) if kind in RUN_KINDS else bool(self.sheet_state(ref).get("locked"))

    def set_sheet_frozen(self, ref, frozen):
        kind, key = ref
        if kind == "data":
            if self.sheet_locked(ref) == frozen:
                return []
            dataset = self.tables[key]
            if frozen:
                names = {name for formula in dataset.formulas.values() for name in info_references(formula)}
                constants = {name: dataset.info[name] for name in names if name in dataset.info}
                self.set_sheet_state(ref, locked=True, info=constants if names else None)
                if names:
                    dataset.info = constants
            else:
                contexts = info_contexts(self.info_sheets.values())
                context = contexts.get(key, contexts[None])
                changed = dataset.info != context
                if changed and dataset.formulas:
                    candidate = copy(dataset)
                    candidate.info = context
                    candidate.frame()
                self.set_sheet_state(ref, locked=None, info=None)
                dataset.info = context
                if changed:
                    return self.readers([key])
            return []
        if kind not in RUN_KINDS:
            return []
        run = self.runs[key]
        if self.frozen(run) == frozen:
            return []
        stored = self.sheet_metadata.setdefault("frozen_runs", {})
        if frozen:
            from .frozen_output import MAX_SNAPSHOT_BYTES, capture
            import json

            if run.result is None or run.calculation_error:
                raise ValueError(qt("qt.sheet_freeze_unavailable"))
            record, size = capture(run.result)
            current_size = sum(len(json.dumps(existing, ensure_ascii=False).encode("utf-8"))
                               for existing in stored.values())
            if current_size + size > MAX_SNAPSHOT_BYTES:
                raise ValueError(qt("qt.sheet_freeze_size"))
            if run.result.figure is not None:
                from base64 import b64decode
                run.result.figure._trama_frozen_pdf = b64decode(record["pdf"])
            stored[run.uid] = record
        else:
            del stored[run.uid]
            if run.result is not None and run.result.figure is not None:
                try:
                    del run.result.figure._trama_frozen_pdf
                except AttributeError:
                    pass
        self.dirty = True
        return [] if frozen else [run]

    def sheet_title(self, ref):
        kind, key = ref
        if kind == "data":
            return key
        if kind == "info":
            return self.info_sheets[key].title
        if kind == "layout":
            return self.layouts[key].name
        return self.sheet_state(ref).get("name", self.runs[key].name)

    def ordered_sheets(self, entries):
        positions = self.sheet_metadata.get("sheets", {})
        if not positions:
            return entries
        return sorted(entries, key=lambda entry: positions.get(self.sheet_key(entry[1]), {}).get("position", 200_000))

    def move_sheet(self, ref, group, step):
        keys = list(group)
        row = keys.index(ref)
        target = row + step
        if 0 <= target < len(keys):
            keys[row], keys[target] = keys[target], keys[row]
            for position, key in enumerate(keys):
                self.set_sheet_state(key, position=position)

    def highlight_sheet(self, ref, color):
        if color is not None and color not in HIGHLIGHTS:
            raise ValueError("Invalid sheet highlight.")
        self.set_sheet_state(ref, highlight=color)

    def rename_sheet(self, ref, name):
        kind, key = ref
        name = validate_sheet_title(name)
        if name == self.sheet_title(ref):
            return ref
        if kind == "data":
            return kind, self._rename_data(key, name)
        if kind == "info":
            self.change_info(replace(self.info_sheets[key], title=name))
        elif kind == "layout":
            self.put_layout(replace(self.layouts[key], name=name), key)
        else:
            self.set_sheet_state(ref, name=name)
        return ref

    def _rename_data(self, title, name):
        if name in self.tables:
            raise ValueError(qt("qt.sheet_name_used", name=name))
        self.tables = {name if key == title else key: dataset for key, dataset in self.tables.items()}
        self.info_sheets = {uid: replace(sheet, table=name) if sheet.table == title else sheet
                            for uid, sheet in self.info_sheets.items()}
        def rename_panel_sources(layout):
            panels = [(name if owner == title else owner, slot) for owner, slot in layout.panels]
            return replace(layout, panels=panels) if panels != layout.panels else layout

        self.layouts = [rename_panel_sources(layout) for layout in self.layouts]
        for run in self.runs:
            if run.title == title:
                run.title = name
            if run.method == worksheet_join.METHOD and worksheet_join.right_title(run.options) == title:
                run.options = {**run.options, worksheet_join.RIGHT_SHEET: name}
                self.tables[run.title].analyses[run.slot] = run.method, run.options
        from .project import LayoutChange

        for index, change in enumerate(self.history.changes):
            if isinstance(change, WorksheetChange) and change.title == title:
                self.history.changes[index] = replace(change, title=name)
            elif isinstance(change, LayoutChange):
                self.history.changes[index] = replace(change, before=rename_panel_sources(change.before),
                                                      after=rename_panel_sources(change.after))
        records = self.sheet_metadata.get("sheets", {})
        if (state := records.pop(f"data:{title}", None)) is not None:
            records[f"data:{name}"] = state
        self.dirty = True
        return name

    def duplicate_sheet(self, ref):
        kind, key = ref
        names = self.tables if kind == "data" else self._sheet_names(kind)
        base = qt("qt.sheet_copy", name=self.sheet_title(ref)[:145])
        name = self.unique_title(base, occupied=names)
        if kind == "data":
            if len(self.tables) >= 256:
                raise ValueError("A project supports up to 256 data tables.")
            twin = deepcopy(self.tables[key])
            twin.analyses = []
            for field in SLOT_RECORDS:
                setattr(twin, field, {})
            references = {field for formula in twin.formulas.values() for field in info_references(formula)}
            constants = [(field, value) for sheet in self.info_sheets.values() if sheet.table == key
                         and sheet.use_constants for field, value in sheet.fields if field.strip().casefold() in references]
            if self.sheet_locked(ref) and references:
                constants = [(field, value) for field, value in twin.info.items() if value is not None]
            sheets = self.info_sheets
            if constants:
                if len(sheets) >= 500:
                    raise ValueError("A project supports up to 500 Info sheets.")
                linked = InfoSheet(qt("qt.sheet_notes_title", name=name[:145]), fields=tuple(constants), table=name)
                sheets = sheets | {linked.uid: linked}
            contexts = info_contexts(sheets.values())
            twin.info = contexts.get(name, contexts[None])
            if twin.formulas:
                twin.frame()
            self.tables[name] = twin
            self.info_sheets = sheets
            self.dirty = True
            return kind, name
        if kind == "info":
            original = self.info_sheets[key]
            # Constants are shared within a scope. A copy would make the original constant names ambiguous.
            twin = replace(original, uid=uuid4().hex, title=name, use_constants=False)
            self.update_info_sheets(self.info_sheets | {twin.uid: twin})
            return kind, twin.uid
        if kind == "layout":
            return kind, self.put_layout(replace(self.layouts[key], name=name, panels=list(self.layouts[key].panels)))
        return self._duplicate_run_sheet(ref, name)

    def _sheet_names(self, kind):
        if kind == "info":
            return {sheet.title for sheet in self.info_sheets.values()}
        if kind == "layout":
            return {layout.name for layout in self.layouts}
        return {self.sheet_title((kind, index)) for index in range(len(self.runs))}

    def _duplicate_run_sheet(self, ref, name):
        kind, index = ref
        run = self.runs[index]
        options = deepcopy(run.options)
        options.pop(LEGACY_GRAPH_LINK, None)
        twin = self.candidate(run.title, run.method, options, source=run.source)
        twin.label, twin.style = name, deepcopy(run.style)
        frozen = self.sheet_metadata.get("frozen_runs", {})
        copied_result = None
        if run.uid in frozen:
            from .frozen_output import MAX_SNAPSHOT_BYTES, restore
            import json

            record = frozen[run.uid]
            size = sum(len(json.dumps(item, ensure_ascii=False).encode("utf-8")) for item in (*frozen.values(), record))
            if size > MAX_SNAPSHOT_BYTES:
                raise ValueError(qt("qt.sheet_freeze_size"))
            copied_result = restore(record)
        new_index, _ = self.add_result(twin, copied_result)
        if copied_result is not None:
            frozen[twin.uid] = frozen[run.uid]
        dataset = self.tables[run.title]
        if twin.style is not None:
            dataset.graph_styles[twin.slot] = twin.style
        for field in ("result_backgrounds", "result_number_formats", "result_text_styles"):
            entries = getattr(dataset, field)
            if run.slot in entries:
                entries[twin.slot] = deepcopy(entries[run.slot])
        other = {"graph": "result", "result": "graph"}.get(kind)
        if other:
            self.set_sheet_state((other, new_index), hidden=True)
        return kind, new_index

    def sheet_delete_problem(self, ref, *, peer_visible=False):
        kind, key = ref
        if kind == "data":
            if any(run.title == key for run in self.runs) or self.readers([key]):
                return qt("qt.sheet_delete_data_dependency")
            if any(sheet.table == key for sheet in self.info_sheets.values()):
                return qt("qt.sheet_delete_info_dependency")
        if kind in {"graph", "result", "saved-layout"}:
            run = self.runs[key]
            if kind == "graph" and any(run.reference in layout.panels for layout in self.layouts):
                return qt("qt.sheet_delete_layout_dependency")
            if (kind == "result" or not peer_visible) and self.analysis_graph().children[run.uid]:
                return qt("qt.sheet_delete_analysis_dependency")
            if not peer_visible:
                link = run.options.get(LEGACY_GRAPH_LINK)
                if link and any(link in (other.options.get(LEGACY_PANEL_DATA) or {}).values() for other in self.runs):
                    return qt("qt.sheet_delete_layout_dependency")
        return None

    def delete_sheet(self, ref, *, peer_visible=False):
        problem = self.sheet_delete_problem(ref, peer_visible=peer_visible)
        if problem:
            raise ValueError(problem)
        kind, key = ref
        records = self.sheet_metadata.get("sheets", {})
        project_key = self.sheet_key(ref)
        stale = []
        # Notes are real Info sheets. When an owning view is removed, keep its text in Info.
        for uid, note in self.info_sheets.copy().items():
            if note.worksheet == project_key:
                self.info_sheets[uid] = replace(note, worksheet=None, floating=False)
            elif kind == "layout" and note.worksheet and note.worksheet.startswith("layout:"):
                position = int(note.worksheet.split(":", 1)[1])
                if position > key:
                    self.info_sheets[uid] = replace(note, worksheet=f"layout:{position - 1}")
        if kind == "data":
            del self.tables[key]
            self._remove_history(lambda edit: isinstance(edit, WorksheetChange) and edit.title == key)
        elif kind == "info":
            stale = self.update_info_sheets({uid: sheet for uid, sheet in self.info_sheets.items() if uid != key})
        elif kind == "layout":
            from .project import LayoutChange

            del self.layouts[key]
            self._remove_history(lambda edit: isinstance(edit, LayoutChange) and edit.index == key)
            self.history.changes = [replace(edit, index=edit.index - 1)
                                    if isinstance(edit, LayoutChange) and edit.index > key else edit
                                    for edit in self.history.changes]
            records.pop(project_key, None)
            for index in range(key, len(self.layouts)):
                state = records.pop(f"layout:{index + 1}", None)
                if state:
                    records[f"layout:{index}"] = state
            self.dirty = True
            return []
        elif peer_visible:
            self.set_sheet_state(ref, hidden=True)
            return []
        else:
            removed = self.runs[key]
            self._delete_run(removed)
            for view in RUN_KINDS:
                records.pop(f"{view}:{removed.uid}", None)
        records.pop(project_key, None)
        self.dirty = True
        return stale

    def _remove_history(self, predicate):
        history = self.history
        history.position -= sum(predicate(edit) for edit in history.changes[:history.position])
        history.changes = [edit for edit in history.changes if not predicate(edit)]

    def _delete_run(self, removed):
        dataset = self.tables[removed.title]
        slot = removed.slot
        self.runs.remove(removed)
        self.sheet_metadata.get("frozen_runs", {}).pop(removed.uid, None)
        dataset.analyses.pop(slot)
        for field in SLOT_RECORDS:
            entries = getattr(dataset, field)
            setattr(dataset, field, {index - (index > slot): value for index, value in entries.items() if index != slot})
        for run in self.runs:
            if run.title != removed.title:
                continue
            if run.slot > slot:
                run.slot -= 1
            section, _ = read_section(run.options)
            if section and section["slot"] > slot:
                run.options = {**run.options, PAIRWISE_SECTION: {**section, "slot": section["slot"] - 1}}
                dataset.analyses[run.slot] = run.method, run.options
        from .project import LayoutChange, StyleBatchChange

        def shift_panels(layout):
            panels = [(title, index - (title == removed.title and index > slot)) for title, index in layout.panels]
            return replace(layout, panels=panels) if panels != layout.panels else layout

        def refers_to_deleted_sheet(edit):
            if isinstance(edit, WorksheetChange):
                return edit.title == removed.title
            if isinstance(edit, StyleBatchChange):
                return removed.uid in edit.before
            return isinstance(edit, LayoutChange) and any(
                removed.reference in layout.panels for layout in (edit.before, edit.after))

        self.layouts = [shift_panels(layout) for layout in self.layouts]
        self._remove_history(refers_to_deleted_sheet)
        self.history.changes = [replace(edit, before=shift_panels(edit.before), after=shift_panels(edit.after))
                                if isinstance(edit, LayoutChange) else edit for edit in self.history.changes]
