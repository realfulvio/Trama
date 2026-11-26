"""Prepare graph artwork and editable copies without changing either open project."""

from pathlib import Path

from analisi.analysis_chain import ChainCancelled
from analisi.family_workflow import copy_graph_family
from analisi.layout_graph_link import LayoutGraphLink
from analisi.linked_tables import TABLES, source_analyses

from .gallery_catalog import graph_runs
from .project import PROJECT_SUFFIXES, Project


def read_source(path, snapshot=None):
    source = Project()
    if snapshot is None:
        path = Path(path)
        if path.suffix.lower() not in PROJECT_SUFFIXES:
            raise ValueError("Choose a project file.")
        source.load(path)
    else:
        from .frozen_output import restore

        source.tables = snapshot.tables
        source.layouts = snapshot.layouts
        source.info_sheets = {sheet.uid: sheet for sheet in snapshot.info_sheets}
        source.sheet_metadata = snapshot.sheet_metadata
        source.runs = [run for title, dataset in source.tables.items() for run in source.runs_for(title, dataset)]
        for run in source.runs:
            frozen = source.sheet_metadata.get("frozen_runs", {}).get(run.uid)
            if frozen is not None:
                run.result = restore(frozen)
    return source, [run for _, run in graph_runs(source)]


def _calculate(project, runs, control):
    if control.cancel.is_set():
        raise ChainCancelled
    job = project.plan_refresh(runs)
    job.control = control
    if job.selected:
        errors = project.apply_refresh(job, project.run_refresh(job))
        if errors:
            raise ValueError(errors[0])


def prepare_preview(source, run, control):
    overlays = source_analyses((run.style or {}).get(TABLES, ()))
    seeds = [candidate for candidate in source.runs
             if (candidate is run or candidate.uid in overlays)
             and (candidate.result is None or candidate.calculation_error)]
    if seeds:
        _calculate(source, seeds, control)
    if run.result is None or run.result.figure is None:
        raise ValueError("The chosen analysis has no graph.")
    return run.result.figure


def prepare_family(source, graph, destination, prefix, control):
    bundle = copy_graph_family(source.tables, source.info_sheets.values(), graph, destination,
                               prefix=prefix, cancel=control.cancel)
    staged = Project()
    focus = staged.apply_family(bundle)
    _calculate(staged, staged.runs, control)
    run = staged.runs[focus[1]]
    if run.result is None or run.result.figure is None:
        raise ValueError("The copied analysis has no graph.")
    return bundle, tuple(staged.runs), run


def linked_run(source, link):
    """Resolve saved identities first. An older project can identify a graph by its unique sheet and recipe name."""
    if link.identity is not None:
        candidates = [run for run in source.runs if run.uid == link.identity]
    else:
        candidates = [run for run in source.runs if (run.title, run.method, run.label)
                      == (link.title, link.method, link.label)]
    if len(candidates) != 1:
        raise ValueError("The linked graph was removed, renamed, or is no longer unique.")
    return candidates[0]


def make_graph_link(source, path, selected):
    run = next(run for run in source.runs if run.reference == selected)
    identity = source.tables[run.title].analysis_ids.get(run.slot)
    link = LayoutGraphLink(str(Path(path).absolute()), run.title, run.slot, run.method, run.label, identity)
    linked_run(source, link)
    return link
