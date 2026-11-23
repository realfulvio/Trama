"""The state of the Repeat analysis on other sheets… assistant, shared by the Tk and Qt windows.

The windows only draw it: this module keeps the choices (recipe, sheets, columns), proposes columns with the
same name only, explains every refusal with the engine's codes and builds the plan. It never creates a window and
never changes the project; when a calculation fails the window reopens the assistant on the same object, so the
user finds the same choices again.
"""
from .family_workflow import display_name
from .repeat_analysis import (describe_repeat, destination_problem, plan_repeat, propose_columns, target_problems)
from .repeat_analysis_text import error_text, method_name, skipped_text, t

LISTED = 40  # Lines of a section shown in a preview; the rest is counted.


class RepeatAssistant:
    """Choices of one repetition. Raises RepeatError at creation when the selected analysis cannot travel."""

    def __init__(self, tables, origin):
        self.tables = tables
        self.origin = tuple(origin)
        self.full = describe_repeat(tables, self.origin, follow=True)
        self.single = describe_repeat(tables, self.origin, follow=False)
        self.follow = len(self.full.steps) > 1
        self.selected = []
        self.columns = {}
        self.page = 0
        self.current = None  # the sheet whose columns are shown

    # -- recipe -------------------------------------------------------------------------------
    @property
    def recipe(self):
        return self.full if self.follow else self.single

    @property
    def has_followers(self):
        return len(self.full.steps) > 1

    def set_follow(self, value):
        self.follow = bool(value) and self.has_followers

    def name(self, table, slot):
        return display_name(self.tables[table], table, slot)[1]

    def source_text(self):
        title, slot = self.origin
        return t("source", sheet=title, name=self.name(title, slot))

    def method_text(self):
        return t("method", method=method_name(self.recipe.steps[0].method))

    def summary(self):
        """``(tag, text)`` lines: what travels, what feeds what, what stays behind."""
        recipe = self.recipe
        steps = recipe.steps
        lines = [("heading", t("summary"))]
        for index, step in enumerate(steps):
            name = self.name(step.table, step.slot)
            if step.parent is None:
                lines.append(("item", "• " + t("first", name=name)))
            else:
                parent = steps[step.parent]
                lines.append(("item", "• " + t("feeds", child=name, table=step.source_table,
                                                parent=self.name(parent.table, parent.slot))))
        lines.append(("note", t("required", columns=", ".join(recipe.columns))))
        if self.follow and recipe.skipped:
            lines.append(("heading", t("skipped")))
            for item in recipe.skipped[:LISTED]:
                lines.append(("item", "• " + f"{self.name(item.table, item.slot)} — " + skipped_text(item)))
        elif not self.has_followers:
            lines.append(("note", t("follow_none")))
        return lines

    def usage(self, requirement):
        """Who reads a recipe column, for the column table: ``Transform (Variables), Linear regression (X)``."""
        steps = self.recipe.steps
        parts = []
        for index, field_name in requirement.fields:
            if index < len(steps):
                parts.append(f"{method_name(steps[index].method)} ({method_name(field_name)})")
        kind = t("numbers") if requirement.numeric else t("any")
        return f"{', '.join(dict.fromkeys(parts))} · {kind}"

    # -- sheets -------------------------------------------------------------------------------
    def sheets(self):
        """Every data sheet with the reason it can never receive the recipe (None when it can)."""
        return [(title, destination_problem(self.tables, self.recipe, title)) for title in self.tables]

    def available(self, title):
        return [str(name) for name in self.tables[title].columns]

    def choose(self, title, on=True):
        if on:
            if title not in self.selected and destination_problem(self.tables, self.recipe, title) is None:
                self.selected.append(title)
                proposal = propose_columns(self.recipe, self.tables[title])
                self.columns.setdefault(title, {}).update({key: value for key, value in proposal.items()
                                                           if key not in self.columns.get(title, {})})
            if title in self.selected:
                self.current = title
        elif title in self.selected:
            self.selected.remove(title)
            if self.current == title:
                self.current = self.selected[0] if self.selected else None

    def set_column(self, title, column, chosen):
        columns = self.columns.setdefault(title, {})
        if chosen:
            columns[column] = chosen
        else:
            columns.pop(column, None)

    def targets(self):
        return {title: {key: value for key, value in self.columns.get(title, {}).items()
                        if key in self.recipe.columns} for title in self.selected}

    def problems(self, title=None):
        titles = [title] if title is not None else list(self.selected)
        targets = self.targets()
        found = []
        for name in titles:
            found.extend(target_problems(self.tables, self.recipe, name, targets.get(name, {})))
        return found

    def problem_texts(self, title=None):
        return list(dict.fromkeys(error_text(problem) for problem in self.problems(title)))

    def ready(self):
        return bool(self.selected) and not self.problems()

    def plan(self):
        return plan_repeat(self.tables, self.origin, self.targets(), follow=self.follow)

    # -- preview ------------------------------------------------------------------------------
    def preview(self, plan):
        """``(tag, text)`` lines of what will be added, per destination, with its new names."""
        lines = [("counts", t("preview_counts", analyses=plan.analysis_count, sheets=len(plan.targets)))]
        steps = plan.recipe.steps
        for target in plan.targets:
            columns = ", ".join(f"{key} → {value}" if key != value else key for key, value in target.columns.items())
            lines.append(("heading", t("preview_sheet", sheet=target.title, columns=columns)))
            names = []
            for index, step in enumerate(steps):
                source = step.source_table if step.parent is not None else None
                names.append(target.labels[index] or f"{step.method} of {source or target.title}")
            for index, step in enumerate(steps[:LISTED]):
                if step.parent is None:
                    lines.append(("item", "• " + t("preview_new", name=names[index])))
                else:
                    lines.append(("item", "• " + t("preview_reads", name=names[index], table=step.source_table,
                                                    parent=names[step.parent])))
        lines.append(("note", t("preview_keeps")))
        return lines


# ---------------------------------------------------------------------------
# The windows' side of the transaction


def prepare_job(tables, plan):
    """On the window thread: the staged map, the analysed frame of every destination and the project state.

    Staging copies metadata only and the frames are taken here, so the worker never reads the live project."""
    from .repeat_analysis import project_state, stage_repeat

    staged = stage_repeat(tables, plan)
    inputs = {target.title: tables[target.title].frame(mask_excluded=True) for target in plan.targets}
    titles = {plan.recipe.origin[0], *(target.title for target in plan.targets)}
    return staged, inputs, project_state(tables, titles)


def still_current(tables, plan, state):
    """True when nothing the repetition reads or writes changed since ``prepare_job``."""
    from .repeat_analysis import project_state

    titles = {plan.recipe.origin[0], *(target.title for target in plan.targets)}
    return project_state(tables, titles) == state


def apply_repeat(tables, runs, runs_for, staged, plan, calculated):
    """Add the calculated copies to the live project, all or nothing. Returns the new runs in plan order.

    ``runs_for`` is the window's ``runs_for(title, dataset)``; only the added slots receive new Run objects, with
    the results calculated on the worker. On any failure every destination is restored."""
    saved = {}
    added = []
    runs_before = len(runs)
    try:
        for target in plan.targets:
            live, twin = tables[target.title], staged[target.title]
            saved[target.title] = (list(live.analyses), dict(live.analysis_ids), dict(live.analysis_sources),
                                   dict(live.analysis_labels), dict(live.graph_styles))
            if len(live.analyses) != target.base:
                raise ValueError("The project changed during the calculation.")
            for slot in target.slots:
                live.analyses.append(twin.analyses[slot])
                live.analysis_ids[slot] = twin.analysis_ids[slot]
                if slot in twin.analysis_sources:
                    live.analysis_sources[slot] = twin.analysis_sources[slot]
                if slot in twin.analysis_labels:
                    live.analysis_labels[slot] = twin.analysis_labels[slot]
                if slot in twin.graph_styles:
                    live.graph_styles[slot] = twin.graph_styles[slot]
            fresh = [run for run in runs_for(target.title, live) if run.slot >= target.base]
            for run in fresh:
                run.result = calculated.results[target.title, run.slot]
                run.calculation_error = None
            runs.extend(fresh)
            added.extend(fresh)
    except Exception:
        del runs[runs_before:]
        for title, (analyses, ids, sources, labels, styles) in saved.items():
            live = tables[title]
            live.analyses[:] = analyses
            live.analysis_ids, live.analysis_sources = ids, sources
            live.analysis_labels, live.graph_styles = labels, styles
        raise
    return added
