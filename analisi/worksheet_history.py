"""Bounded in-session undo and redo for source worksheet edits."""

from copy import copy
from dataclasses import dataclass

import pandas as pd

from .worksheet_text import TextStyles


@dataclass(frozen=True, eq=False)
class WorksheetState:
    raw: pd.DataFrame
    formulas: dict
    excluded: set
    view: tuple | None = None
    column_order: tuple | None = None
    cell_backgrounds: dict | None = None
    result_backgrounds: dict | None = None
    number_formats: dict | None = None
    result_number_formats: dict | None = None
    row_heights: dict | None = None
    text_styles: TextStyles | None = None
    result_text_styles: dict | None = None
    source_link: object = None

    @classmethod
    def capture(cls, dataset, view=None):
        # Worksheet editing replaces these objects on commit. Retaining them
        # preserves exact cell types, metadata and exclusion flags.
        return cls(dataset.raw, dataset.formulas, dataset.excluded, view, dataset.column_order,
                   dataset.cell_backgrounds, dataset.result_backgrounds,
                   dataset.number_formats, dataset.result_number_formats, dataset.row_heights,
                   dataset.text_styles, dataset.result_text_styles, getattr(dataset, "source_link", None))

    def data_changed(self, other):
        return (self.raw is not other.raw or self.formulas is not other.formulas
                or self.excluded is not other.excluded or self.column_order != other.column_order)

    def changed(self, other):
        return (self.data_changed(other) or self.cell_backgrounds is not other.cell_backgrounds
                or self.result_backgrounds is not other.result_backgrounds
                or self.number_formats is not other.number_formats
                or self.result_number_formats is not other.result_number_formats
                or self.row_heights is not other.row_heights
                or self.text_styles is not other.text_styles
                or self.result_text_styles is not other.result_text_styles
                or self.source_link is not other.source_link)

    def restore(self, dataset):
        candidate = copy(dataset)
        candidate.raw, candidate.formulas, candidate.excluded = self.raw, self.formulas, self.excluded
        candidate.column_order = self.column_order
        if self.data_changed(self.capture(dataset)) and candidate.formulas:
            # The current Info values may differ from those at edit time.
            candidate.frame()
        dataset.raw, dataset.formulas, dataset.excluded = self.raw, self.formulas, self.excluded
        dataset.column_order = self.column_order
        dataset.cell_backgrounds = self.cell_backgrounds if self.cell_backgrounds is not None else {}
        dataset.result_backgrounds = self.result_backgrounds if self.result_backgrounds is not None else {}
        dataset.number_formats = self.number_formats if self.number_formats is not None else {}
        dataset.result_number_formats = self.result_number_formats if self.result_number_formats is not None else {}
        dataset.row_heights = self.row_heights if self.row_heights is not None else {}
        dataset.text_styles = self.text_styles if self.text_styles is not None else TextStyles()
        dataset.result_text_styles = self.result_text_styles if self.result_text_styles is not None else {}
        dataset.source_link = self.source_link


@dataclass(frozen=True, eq=False)
class WorksheetChange:
    title: str
    label: str
    before: WorksheetState
    after: WorksheetState


class WorksheetHistory:
    def __init__(self, *, memory_budget=96 * 1024 * 1024):
        self.memory_budget = memory_budget
        self.clear()

    def clear(self):
        self.changes = []
        self.position = 0
        self.frame_sizes = {}

    def can_apply(self, *, redo=False):
        return self.position < len(self.changes) if redo else self.position > 0

    def record(self, title, label, before, after):
        if not before.changed(after):
            return False
        del self.changes[self.position:]
        self.changes.append(WorksheetChange(title, label, before, after))
        self._trim()
        self.position = len(self.changes)
        return True

    def _trim(self):
        # Count shared snapshots once and always retain the most recent edit.
        while True:
            states = [state for change in self.changes for state in (change.before, change.after)]
            sizes = {}
            exclusions = {}
            backgrounds = {}
            for state in states:
                key = id(state.raw)
                if key not in sizes:
                    sizes[key] = self.frame_sizes.get(key)
                    if sizes[key] is None:
                        sizes[key] = int(state.raw.memory_usage(deep=True).sum())
                exclusions[id(state.excluded)] = len(state.excluded) * 72
                if state.cell_backgrounds:
                    backgrounds[id(state.cell_backgrounds)] = len(state.cell_backgrounds) * 112
                if state.row_heights:
                    backgrounds[id(state.row_heights)] = len(state.row_heights) * 64
                for sheets in (state.result_backgrounds or {}).values():
                    for cells in sheets.values():
                        backgrounds[id(cells)] = len(cells) * 112
                if state.number_formats:
                    backgrounds[id(state.number_formats)] = len(state.number_formats) * 160
                for sheets in (state.result_number_formats or {}).values():
                    for formats in sheets.values():
                        backgrounds[id(formats)] = len(formats) * 160
                if state.text_styles:
                    backgrounds[id(state.text_styles)] = state.text_styles.run_count() * 200
                if state.source_link is not None:  # 16 bytes per confirmed file row.
                    backgrounds[id(state.source_link)] = len(state.source_link.digests) + 1024
                for sheets in (state.result_text_styles or {}).values():
                    for styles in sheets.values():
                        backgrounds[id(styles)] = styles.run_count() * 200
            self.frame_sizes = sizes
            if len(self.changes) == 1 or (len(self.changes) <= 24 and
                                         sum(sizes.values()) + sum(exclusions.values()) + sum(backgrounds.values()) <= self.memory_budget):
                return
            del self.changes[0]

    def apply(self, tables, *, redo=False):
        if not self.can_apply(redo=redo):
            return None
        change = self.changes[self.position if redo else self.position - 1]
        dataset = tables.get(change.title)
        if dataset is None:
            raise ValueError("The edited worksheet is no longer in this project.")
        state = change.after if redo else change.before
        state.restore(dataset)
        self.position += 1 if redo else -1
        return change
