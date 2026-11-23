"""Bounded in-session undo and redo for source worksheet edits."""

from copy import copy
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, eq=False)
class WorksheetState:
    raw: pd.DataFrame
    formulas: dict
    excluded: set
    view: tuple | None = None
    column_order: tuple | None = None

    @classmethod
    def capture(cls, dataset, view=None):
        # Worksheet editing replaces these objects on commit. Retaining them
        # preserves exact cell types, metadata and exclusion flags.
        return cls(dataset.raw, dataset.formulas, dataset.excluded, view, dataset.column_order)

    def changed(self, other):
        return (self.raw is not other.raw or self.formulas is not other.formulas
                or self.excluded is not other.excluded or self.column_order != other.column_order)

    def restore(self, dataset):
        candidate = copy(dataset)
        candidate.raw, candidate.formulas, candidate.excluded = self.raw, self.formulas, self.excluded
        candidate.column_order = self.column_order
        if candidate.formulas:
            # The current Info values may differ from those at edit time.
            candidate.frame()
        dataset.raw, dataset.formulas, dataset.excluded = self.raw, self.formulas, self.excluded
        dataset.column_order = self.column_order


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
            for state in states:
                key = id(state.raw)
                if key not in sizes:
                    sizes[key] = self.frame_sizes.get(key)
                    if sizes[key] is None:
                        sizes[key] = int(state.raw.memory_usage(deep=True).sum())
                exclusions[id(state.excluded)] = len(state.excluded) * 72
            self.frame_sizes = sizes
            if len(self.changes) == 1 or (len(self.changes) <= 24 and
                                         sum(sizes.values()) + sum(exclusions.values()) <= self.memory_budget):
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
