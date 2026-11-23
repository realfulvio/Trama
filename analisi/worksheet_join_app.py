"""Resolve the right worksheet of a join in either desktop interface."""
from . import worksheet_join
from .legacy_restore import BINARY_GRAPH_COLLECTION, BINARY_LAYOUT_COLLECTION, SAVED_BINARY_RESULT


def stored_legacy_view(dataset):
    return (dataset.table_format in {BINARY_GRAPH_COLLECTION, BINARY_LAYOUT_COLLECTION}
            or any(method == SAVED_BINARY_RESULT for method, _ in dataset.analyses))


class WorksheetJoinSources:
    def join_sources(self, title, source=None):
        """The worksheets a join of ``title`` can read on the right, with their columns: the native data
        sheets of this project except the left one (a join of a result table may read its own data sheet)."""
        return {name: [*dataset.raw.columns, *dataset.formulas] for name, dataset in self.tables.items()
                if not stored_legacy_view(dataset) and (source is not None or name != title)}

    def join_problem(self, run):
        """Why the right worksheet of a join cannot be read, as a FieldError on Join right sheet, or None.
        The exact title is the identity of the sheet: a missing one is never replaced by another."""
        title = worksheet_join.right_title(run.options)
        if title is None or title not in self.tables:
            return worksheet_join.missing_source(title)
        if stored_legacy_view(self.tables[title]):
            return worksheet_join.view_source(title)
        if run.source is None and title == run.title:
            return worksheet_join.same_source(title)
        return None

    def join_data(self, run):
        """The evaluated right worksheet of a join (excluded cells blank), read on the window thread so the
        worker gets a consistent copy; the FieldError of a source that cannot be read; None for other runs."""
        if run.method != worksheet_join.METHOD:
            return None
        problem = self.join_problem(run)
        if problem is not None:
            return problem
        return self.tables[worksheet_join.right_title(run.options)].frame(mask_excluded=True)
