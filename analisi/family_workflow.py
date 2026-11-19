"""Independent copies and self-contained exports of experiment families.

A family is the set of sheets that depend on each other: a data table, its analyses, the analyses
that read their results, the comparisons drawn on graphs, the layouts that show them and the Info
sheets that feed their formulas. This module selects a family, copies it into a detached bundle or
writes it as a project of its own. It never creates a window, never touches the arguments and never
keeps a reference to a mutable object of the original project.

Analyses are addressed by ``(table title, slot)``. A copy compacts the slots of the selected
analyses, receives new persistent identities and remaps every reference that goes through a slot or
an identity: result inputs, pairwise comparison sources, graph styles, layout panels and the
identities that tie recovered graphs to the panels of a recovered layout.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from .analysis_chain import ChainCancelled, MAX_ANALYSIS_NODES, ResultSource
from .analysis_labels import clean_label, valid_label
from .data import Dataset, info_references, save_project
from .info import InfoSheet, MAX_INFO_SHEETS, info_contexts
from .pairwise_graph import SECTION, read_section
from .presentation import Layout
from .prism_layout_edit import PRISM_PANEL_DATA
from .prism_restore import (PRISM_GRAPH_LINK, PRISM_TITLE, SAVED_BINARY_LAYOUT, panel_source_style)
from . import worksheet_join

MAX_TABLES = 256
MAX_LAYOUTS = 128
MAX_NAME = 160
MAX_PREFIX = 80
KINDS = ("data", "result", "graph", "layout", "saved-layout", "info")
_REFUSED = {"Cc", "Cs", "Zl", "Zp"}


class FamilyError(ValueError):
    """A family cannot be selected, copied or written. ``code`` names the reason for translation,
    ``field`` is ``"name"`` when the problem belongs to the name or prefix the user typed."""

    def __init__(self, code, message, *, field=None, **detail):
        super().__init__(message)
        self.code, self.field, self.detail = code, field, detail


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise ChainCancelled


# ---------------------------------------------------------------------------
# Names


def _bad_text(text):
    return any(unicodedata.category(character) in _REFUSED for character in text)


def _check_name(text, limit, mode):
    """``mode`` is "name" for the new data table or "prefix" for the literal prefix of the other sheets."""
    if not text.strip():
        raise FamilyError("name-empty", "Enter a name for the new data table." if mode == "name" else "Enter a prefix.",
                          field="name", mode=mode)
    if _bad_text(text):
        raise FamilyError("name-invalid", "Use one line of text without control characters.", field="name")
    if len(text) > limit:
        raise FamilyError("name-long", f"Use at most {limit} characters.", field="name", limit=limit)


def _fit(text, suffix="", limit=MAX_NAME):
    """``text + suffix`` within ``limit``: the text is shortened with an ellipsis, never the suffix."""
    room = limit - len(suffix)
    if len(text) > room:
        text = text[:max(room - 1, 0)] + "…"
    return text + suffix


def _unique(base, taken, limit=MAX_NAME):
    if base not in taken:
        return base
    number = 2
    while (candidate := _fit(base, f" ({number})", limit)) in taken:
        number += 1
    return candidate


def _replace_names(text, mapping):
    """Replace whole-word occurrences of the original table titles in ``text`` in one pass."""
    if not mapping:
        return text
    pattern = re.compile("|".join(r"(?<!\w)" + re.escape(old) + r"(?!\w)"
                                  for old in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda match: mapping[match.group(0)], text)


# ---------------------------------------------------------------------------
# The dependency graph of the project


class _Graph:
    """Analyses as nodes; edges for result inputs and comparison sources (structural) and for the panel
    graphs of recovered layouts (panel edges). Everything is iterative: a chain may be 65,536 long."""

    def __init__(self, tables):
        self.tables = tables
        self.by_id = {}
        for title, dataset in tables.items():
            for slot, identifier in dataset.analysis_ids.items():
                if identifier in self.by_id:
                    raise FamilyError("identity", "Two analyses share one persistent identity.")
                self.by_id[identifier] = (title, slot)
        self.parents, self.children = {}, {}
        self.editable, self.saved_layouts = {}, []
        for title, dataset in tables.items():
            count = len(dataset.analyses)
            for slot, (method, options) in enumerate(dataset.analyses):
                node = (title, slot)
                found = []
                source = dataset.analysis_sources.get(slot)
                if source is not None:
                    parent = self.by_id.get(source.analysis_id)
                    if parent is None:
                        raise FamilyError("missing-source", "An analysis refers to a missing source analysis.",
                                          table=title)
                    found.append(parent)
                settings, _ = read_section(options)
                if settings is not None and settings["slot"] < count and settings["slot"] != slot:
                    found.append((title, settings["slot"]))
                for parent in dict.fromkeys(found):
                    self.parents.setdefault(node, []).append(parent)
                    self.children.setdefault(parent, []).append(node)
                link = options.get(PRISM_GRAPH_LINK)
                if isinstance(link, str) and panel_source_style(method, options) is not None:
                    self.editable.setdefault(link, []).append(node)
                if method == SAVED_BINARY_LAYOUT:
                    self.saved_layouts.append(node)

    def is_saved_layout(self, node):
        title, slot = node
        return self.tables[title].analyses[slot][0] == SAVED_BINARY_LAYOUT

    def panel_sources(self, node, *, strict):
        """Graphs identified by the panel links of a recovered layout. A link shared by two editable
        graphs is ambiguous: refused when the family needs it, ignored when only looking."""
        title, slot = node
        links = self.tables[title].analyses[slot][1].get(PRISM_PANEL_DATA)
        found = []
        if isinstance(links, dict):
            for link in links.values():
                candidates = self.editable.get(link, ()) if isinstance(link, str) else ()
                if len(candidates) == 1:
                    found.append(candidates[0])
                elif len(candidates) > 1 and strict:
                    raise FamilyError("ambiguous-panel", "A recovered layout panel matches more than one graph.",
                                      table=title)
        return list(dict.fromkeys(found))

    def ancestors(self, nodes):
        result, pending = set(nodes), deque(nodes)
        while pending:
            node = pending.popleft()
            parents = list(self.parents.get(node, ()))
            if self.is_saved_layout(node):
                parents.extend(self.panel_sources(node, strict=True))
            for parent in parents:
                if parent not in result:
                    result.add(parent)
                    pending.append(parent)
        return result

    def descendants(self, nodes):
        result, pending = set(nodes), deque(nodes)
        while pending:
            for child in self.children.get(pending.popleft(), ()):
                if child not in result:
                    result.add(child)
                    pending.append(child)
        return result


# ---------------------------------------------------------------------------
# Selection and plan


@dataclass
class FamilyPlan:
    """What a family contains, from metadata only. Nothing is copied to build it."""
    kind: str
    key: object
    export: bool
    include_layouts: bool
    start_table: str | None
    tables: tuple          # original titles, in project order
    slots: dict            # title -> original slots in ascending order
    layouts: tuple         # indexes of native layouts that travel with the family
    infos: tuple           # uids of local Info sheets that travel
    global_infos: tuple    # uids of global Info sheets (shared by a copy, carried by an export)
    snapshot: bool         # a copy replaces the sole global Info by local snapshots
    shared_panels: int     # layout panels that keep referring to the original project
    via_info: str | None = None
    members: frozenset = field(default_factory=frozenset, repr=False)

    @property
    def analysis_count(self):
        return sum(len(slots) for slots in self.slots.values())


def _selection(tables, layouts, infos, selected):
    try:
        kind, key = selected
    except (TypeError, ValueError):
        raise FamilyError("selection", "Select a data table, result, graph, layout or Info sheet.") from None
    if kind == "data" and isinstance(key, str) and key in tables:
        return kind, key, None
    if kind in {"result", "graph", "saved-layout"} and isinstance(key, (tuple, list)) and len(key) == 2:
        title, slot = key
        if title in tables and type(slot) is int and 0 <= slot < len(tables[title].analyses):
            if kind == "saved-layout" and tables[title].analyses[slot][0] != SAVED_BINARY_LAYOUT:
                raise FamilyError("selection", "The selected sheet is not a recovered layout.")
            return kind, (title, slot), None
    elif kind == "layout" and type(key) is int and 0 <= key < len(layouts):
        return kind, key, None
    elif kind == "info":
        sheet = next((sheet for sheet in infos if sheet.uid == key), None)
        if sheet is not None:
            if sheet.table is None:
                raise FamilyError("global-info", "A project-wide Info sheet does not identify one family of data.")
            if sheet.table in tables:
                return kind, sheet.table, sheet.uid
    raise FamilyError("selection", "The selected sheet is not part of this project.")


def family_graph(tables):
    """The dependency graph of ``tables``; pass it as ``graph`` to plan or preview repeatedly."""
    return _Graph(tables)


def plan_family(tables, layouts, infos, selected, *, include_layouts=True, export=False, graph=None):
    """Select the family of ``selected``. ``export`` also pulls in the other panels of the layouts."""
    infos = tuple(infos)
    kind, key, via_info = _selection(tables, layouts, infos, selected)
    graph = graph or _Graph(tables)
    start = None
    if kind in {"data", "info"}:
        start = key
        seeds = {(key, slot) for slot in range(len(tables[key].analyses))}
    elif kind == "layout":
        seeds = set()
        for panel in layouts[key].panels:
            title, slot = panel
            if title not in tables or not 0 <= slot < len(tables[title].analyses):
                raise FamilyError("layout-panel", "A layout panel refers to an analysis that is not in the project.")
            seeds.add((title, slot))
    else:
        seeds = {key}
    members = set(seeds)
    if kind in {"data", "info", "result"}:
        members = graph.descendants(members)
    members = graph.ancestors(members)

    chosen, saved = [], []
    wanted = kind == "layout" or (include_layouts and kind != "saved-layout")
    if kind == "layout":
        chosen = [key]
    elif wanted:
        chosen = [index for index, layout in enumerate(layouts)
                  if any(tuple(panel) in members for panel in layout.panels)]
        saved = [node for node in graph.saved_layouts if node not in members
                 and any(source in members for source in graph.panel_sources(node, strict=False))]
    if export and wanted:
        extra = set(saved)
        for index in chosen:
            for title, slot in map(tuple, layouts[index].panels):
                if title in tables and type(slot) is int and 0 <= slot < len(tables[title].analyses):
                    extra.add((title, slot))
        members = graph.ancestors(members | extra)
    else:
        members |= set(saved)

    by_table = {}
    for title, slot in members:
        by_table.setdefault(title, []).append(slot)
    # A self-contained export also carries the right worksheet of every join, so the joins open on their own.
    # A copy in the same project keeps reading the original right sheet, which is certainly there.
    joined = _join_sources(tables, members) if export else set()
    included = [title for title in tables if title in by_table or title == start or title in joined]
    slots = {title: tuple(sorted(by_table.get(title, ()))) for title in included}

    shared = 0
    if not export:
        for index in chosen:
            if kind != "layout":
                shared += sum(1 for panel in layouts[index].panels if tuple(panel) not in members)
        for node in members:
            if graph.is_saved_layout(node) and node not in seeds:
                shared += sum(1 for source in graph.panel_sources(node, strict=False) if source not in members)

    local = tuple(sheet.uid for sheet in infos if sheet.table in slots)
    global_sheets = [sheet for sheet in infos if sheet.table is None]
    snapshot = False
    if export:
        shared_uids = tuple(_needed_global_infos(tables, infos, slots))
    else:
        snapshot = len(infos) == 1 and infos[0].table is None and set(slots) == set(tables)
        shared_uids = () if snapshot else tuple(sheet.uid for sheet in global_sheets)
    return FamilyPlan(kind, key, export, include_layouts, start, tuple(included), slots, tuple(chosen), local,
                      shared_uids, snapshot, shared, via_info, frozenset(members))


def _needed_global_infos(tables, infos, slots):
    """Global Info sheets that define a constant read by a formula of an included table."""
    local = {}
    for sheet in infos:
        if sheet.table is not None:
            local.setdefault(sheet.table, set()).update(label.strip().casefold() for label, _ in sheet.fields)
    needed = set()
    for title in slots:
        for expression in tables[title].formulas.values():
            try:
                needed.update(info_references(expression) - local.get(title, set()))
            except (SyntaxError, ValueError):
                continue
    return [sheet.uid for sheet in infos if sheet.table is None
            and any(label.strip().casefold() in needed for label, _ in sheet.fields)]


# ---------------------------------------------------------------------------
# Names and budgets of a copy


@dataclass
class FamilyPreview:
    """Everything a copy will be called and add, before anything is copied."""
    plan: FamilyPlan
    mode: str                  # "name": the user named the copy of one data table; "prefix": a literal prefix
    text: str
    table_names: dict          # original title -> new title
    layout_names: dict         # original layout index -> new name
    info_titles: dict          # original Info uid -> new title
    snapshot_titles: dict      # new table title -> title of its local snapshot
    labels: dict               # (original title, slot) -> label given to the copy
    counts: dict

    @property
    def shared_panels(self):
        return self.plan.shared_panels


def display_name(dataset, title, slot):
    method, options = dataset.analyses[slot]
    source = dataset.analysis_sources.get(slot)
    explicit = dataset.analysis_labels.get(slot) or options.get(PRISM_TITLE)
    return explicit, explicit or f"{method} of {source.table if source is not None else title}"


def preview_family(tables, layouts, infos, selected, *, name, include_layouts=True, graph=None):
    """Validate ``name`` and the budgets, then name every sheet of the copy. Raises FamilyError."""
    infos = tuple(infos)
    plan = plan_family(tables, layouts, infos, selected, include_layouts=include_layouts, graph=graph)
    if not isinstance(name, str):
        raise FamilyError("name-empty", "Enter a name.", field="name", mode="prefix")
    named = plan.kind == "data"
    if named:
        text = name.strip()
        _check_name(text, MAX_NAME, "name")
        if text in tables:
            raise FamilyError("name-taken", f'A data table named "{text}" already exists.', field="name", name=text)
    else:
        text = name
        _check_name(text, MAX_PREFIX, "prefix")

    taken = set(tables)
    table_names = {}
    for title in plan.tables:
        if named:
            base = text if title == plan.start_table else _fit(title, f" ({text})")
        else:
            base = text + title
            if len(base) > MAX_NAME:
                raise FamilyError("name-too-long", f'The prefix makes the name of "{title}" too long.',
                                  field="name", table=title)
        table_names[title] = _unique(base, taken)
        taken.add(table_names[title])

    def rename(old):
        return _fit(_replace_names(old, table_names) if named else text + old, limit=MAX_NAME)

    layout_names, used = {}, {layout.name for layout in layouts}
    for index in plan.layouts:
        layout_names[index] = _unique(rename(layouts[index].name), used)
        used.add(layout_names[index])
    by_uid = {sheet.uid: sheet for sheet in infos}
    info_titles, used = {}, {sheet.title for sheet in infos}
    for uid in plan.infos:
        info_titles[uid] = _unique(rename(by_uid[uid].title), used)
        used.add(info_titles[uid])
    snapshot_titles = {}
    if plan.snapshot:
        for title in plan.tables:
            snapshot_titles[table_names[title]] = _fit(rename(infos[0].title), f" · {table_names[title]}")

    labels = {}
    for title, slots in plan.slots.items():
        dataset = tables[title]
        for slot in slots:
            explicit, shown = display_name(dataset, title, slot)
            if not named:
                label = text + shown
            elif explicit:
                label = _replace_names(explicit, table_names)
            else:
                continue
            label = clean_label(label)
            if valid_label(label):
                labels[title, slot] = label

    counts = {"tables": len(plan.tables), "analyses": plan.analysis_count, "layouts": len(plan.layouts),
              "infos": len(plan.infos) + len(snapshot_titles)}
    if len(tables) + counts["tables"] > MAX_TABLES:
        raise FamilyError("budget-tables", f"A project supports up to {MAX_TABLES} data tables.", limit=MAX_TABLES)
    if len(layouts) + counts["layouts"] > MAX_LAYOUTS:
        raise FamilyError("budget-layouts", f"A project supports up to {MAX_LAYOUTS} layouts.", limit=MAX_LAYOUTS)
    if len(infos) + counts["infos"] > MAX_INFO_SHEETS:
        raise FamilyError("budget-infos", f"A project supports up to {MAX_INFO_SHEETS} Info sheets.",
                          limit=MAX_INFO_SHEETS)
    if sum(len(dataset.analyses) for dataset in tables.values()) + counts["analyses"] > MAX_ANALYSIS_NODES:
        raise FamilyError("budget-analyses", f"A project supports up to {MAX_ANALYSIS_NODES:,} analysis nodes.",
                          limit=MAX_ANALYSIS_NODES)
    return FamilyPreview(plan, "name" if named else "prefix", text, table_names, layout_names, info_titles,
                         snapshot_titles, labels, counts)


# ---------------------------------------------------------------------------
# Copying


@dataclass
class FamilyBundle:
    """A detached copy. ``tables``, ``layouts`` and ``infos`` contain only new objects."""
    tables: dict
    layouts: list
    infos: tuple
    table_names: dict          # original title -> new title
    analysis_refs: dict        # (original title, slot) -> (new title, new slot)
    info_ids: dict             # original Info uid -> uid of its copy
    snapshot_ids: dict         # new table title -> uid of its local snapshot of the global Info
    layout_refs: dict          # original layout index -> index in ``layouts``
    shared_panels: int
    focus: tuple               # canonical reference of the copy of the selected sheet
    plan: FamilyPlan = field(repr=False, default=None)

    @property
    def analysis_count(self):
        return sum(len(dataset.analyses) for dataset in self.tables.values())


def _recovered_links(options):
    links = set()
    link = options.get(PRISM_GRAPH_LINK)
    if isinstance(link, str):
        links.add(link)
    return links


def _join_sources(tables, members):
    """Titles of the existing right worksheets read by the joins among ``members``."""
    found = set()
    for title, slot in members:
        method, options = tables[title].analyses[slot]
        right = worksheet_join.right_title(options) if method == worksheet_join.METHOD else None
        if right in tables:
            found.add(right)
    return found


def _remap_options(options, slot_map, old_count, new_count, link_map, table_names=None):
    options = deepcopy(options)
    right = worksheet_join.right_title(options)
    if right is not None and table_names and right in table_names and worksheet_join.LEFT_KEYS in options:
        # The right worksheet of a join travels with the family: the copy reads the copied sheet. A sheet
        # that stays behind keeps its exact title; nothing is relinked by a name that merely collides.
        options[worksheet_join.RIGHT_SHEET] = table_names[right]
    section = options.get(SECTION)
    if isinstance(section, dict):
        settings, _ = read_section(options)
        if settings is not None:
            old = settings["slot"]
            # A reference that was already broken stays broken: it is moved past the end, never onto
            # another analysis, and a valid one follows the compaction of the slots.
            section["Source slot"] = slot_map[old] if old in slot_map else new_count + max(0, old - old_count)
    if link_map:
        link = options.get(PRISM_GRAPH_LINK)
        if isinstance(link, str) and link in link_map:
            options[PRISM_GRAPH_LINK] = link_map[link]
        panels = options.get(PRISM_PANEL_DATA)
        if isinstance(panels, dict):
            options[PRISM_PANEL_DATA] = {panel: link_map.get(link, link) if isinstance(link, str) else link
                                         for panel, link in panels.items()}
    return options


def _copy_raw(dataset):
    raw = dataset.raw.copy(deep=True)
    attrs = deepcopy(dict(dataset.raw.attrs))
    # The explicit arguments carry recipes, formulas and exclusions; leftovers of an import would
    # inject the original recipes into the copy or resurrect cells that were included again.
    for name in ("prism_recipes", "prism_formulas", "excluded"):
        attrs.pop(name, None)
    if "table_format" in attrs:
        attrs["table_format"] = dataset.table_format
    raw.attrs.clear()
    raw.attrs.update(attrs)
    return raw


def _build(tables, layouts, infos, plan, new_names, *, renew, cancel, graph):
    """Materialize ``plan``. ``new_names`` is a FamilyPreview for a copy, or None for an export."""
    infos = tuple(infos)
    table_names = new_names.table_names if new_names else {title: title for title in plan.tables}
    members = plan.members
    slot_maps = {title: {old: new for new, old in enumerate(slots)} for title, slots in plan.slots.items()}

    # Identities: a copy gets fresh ones for every analysis that had one or takes part in a link.
    linked = set()
    for node in members:
        for parent in graph.parents.get(node, ()):
            linked.update((node, parent))
    refs = {(title, old): (table_names[title], new)
            for title, mapping in slot_maps.items() for old, new in mapping.items()}
    identities = {}
    taken = set(graph.by_id)
    for title, slots in plan.slots.items():
        dataset = tables[title]
        for slot in slots:
            old = dataset.analysis_ids.get(slot)
            if old is None and (title, slot) not in linked:
                continue
            if renew:
                fresh = str(uuid4())
                while fresh in taken:
                    fresh = str(uuid4())
                taken.add(fresh)
                identities[title, slot] = fresh
            else:
                identities[title, slot] = old if old is not None else str(uuid4())

    link_map = {}
    if renew:
        for title, slots in plan.slots.items():
            for slot in slots:
                for link in _recovered_links(tables[title].analyses[slot][1]):
                    link_map.setdefault(link, f"{uuid4().hex}:{link.rpartition(':')[2][:64]}")

    built = {}
    for title in plan.tables:
        _cancelled(cancel)
        dataset, slots, mapping = tables[title], plan.slots[title], slot_maps[title]
        old_count, new_count = len(dataset.analyses), len(slots)
        analyses = [(dataset.analyses[slot][0],
                     _remap_options(dataset.analyses[slot][1], mapping, old_count, new_count, link_map,
                                    table_names if dataset.analyses[slot][0] == worksheet_join.METHOD else None))
                    for slot in slots]
        sources = {}
        for slot in slots:
            source = dataset.analysis_sources.get(slot)
            if source is not None:
                parent = graph.by_id[source.analysis_id]
                sources[mapping[slot]] = ResultSource(identities[parent], source.table)
        labels = {}
        for slot in slots:
            label = (new_names.labels.get((title, slot)) if new_names else None) or dataset.analysis_labels.get(slot)
            if label is not None:
                labels[mapping[slot]] = label
        built[title] = Dataset(
            _copy_raw(dataset), formulas=dict(dataset.formulas), analyses=analyses,
            excluded=set(dataset.excluded), table_format=dataset.table_format,
            graph_styles={mapping[slot]: deepcopy(style) for slot, style in dataset.graph_styles.items()
                          if slot in mapping},
            info={}, analysis_ids={mapping[slot]: identities[title, slot] for slot in slots
                                   if (title, slot) in identities},
            analysis_sources={}, analysis_labels=labels)
        # Sources are rebuilt from identities of the copies, so they can only refer to the copies.
        built[title].analysis_sources.update(sources)

    out_tables = {table_names[title]: dataset for title, dataset in built.items()}
    out_layouts, layout_refs = [], {}
    for index in plan.layouts:
        source = layouts[index]
        panels = [refs.get(tuple(panel), tuple(panel)) for panel in source.panels]
        name = new_names.layout_names[index] if new_names else source.name
        layout_refs[index] = len(out_layouts)
        out_layouts.append(Layout(name, source.columns, panels, source.paper, source.background))

    by_uid = {sheet.uid: sheet for sheet in infos}
    out_infos, info_ids, snapshot_ids = [], {}, {}
    used_uids = {sheet.uid for sheet in infos}
    for uid in plan.infos:
        sheet = by_uid[uid]
        if renew:
            new_uid = uuid4().hex
            while new_uid in used_uids:
                new_uid = uuid4().hex
            used_uids.add(new_uid)
            sheet = replace(sheet, title=new_names.info_titles[uid], table=table_names[sheet.table], uid=new_uid)
        info_ids[uid] = sheet.uid
        out_infos.append(sheet)
    if renew and plan.snapshot:
        shared = infos[0]
        for title in plan.tables:
            new_title = table_names[title]
            new_uid = uuid4().hex
            while new_uid in used_uids:
                new_uid = uuid4().hex
            used_uids.add(new_uid)
            out_infos.append(InfoSheet(new_names.snapshot_titles[new_title], shared.fields, shared.notes,
                                       new_title, new_uid, shared.note_styles))
            snapshot_ids[new_title] = new_uid
    if not renew:
        out_infos.extend(by_uid[uid] for uid in plan.global_infos)
        order = {sheet.uid: position for position, sheet in enumerate(infos)}
        out_infos.sort(key=lambda sheet: order[sheet.uid])

    # Info constants are read per table: the copies see the shared (original) sheets and their own.
    context_sheets = [*infos, *out_infos] if renew else out_infos
    contexts = info_contexts(context_sheets)
    for title, dataset in out_tables.items():
        dataset.info = contexts.get(title, contexts[None])
    _cancelled(cancel)

    kind, key = plan.kind, plan.key
    if kind in {"data"}:
        focus = ("data", table_names[key])
    elif kind == "info":
        focus = ("info", info_ids.get(plan.via_info) or snapshot_ids.get(table_names[key]) or "")
    elif kind == "layout":
        focus = ("layout", layout_refs[key])
    else:
        focus = (kind, refs[key])
    return FamilyBundle(out_tables, out_layouts, tuple(out_infos), dict(table_names), refs, info_ids,
                        snapshot_ids, layout_refs, plan.shared_panels, focus, plan)


def duplicate_family(tables, layouts, infos, selected, *, name, include_layouts=True, cancel=None):
    """Copy the family of ``selected`` into a detached bundle without touching the arguments.

    From a data table ``name`` is the new table name; from any other sheet it is a literal prefix.
    Raises FamilyError (a ValueError) before anything is built when a name or a budget is refused.
    """
    infos = tuple(infos)
    graph = _Graph(tables)
    preview = preview_family(tables, layouts, infos, selected, name=name, include_layouts=include_layouts,
                             graph=graph)
    _cancelled(cancel)
    return _build(tables, layouts, infos, preview.plan, preview, renew=True, cancel=cancel, graph=graph)


def same_file(first, second):
    first, second = Path(first), Path(second)
    if first.resolve() == second.resolve():
        return True
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def save_family(path, tables, layouts, infos, selected, *, include_layouts=True, source_path=None, cancel=None):
    """Write the family of ``selected`` as a project that opens on its own.

    The original objects are never changed. ``source_path`` is the file of the current project: it is
    refused, also through links, so a subset can never replace the complete project. A failed write
    keeps any existing file (the project writer replaces it atomically).
    """
    path = Path(path)
    if path.suffix.lower() != ".alab":
        raise FamilyError("file-name", "Choose a file name ending in .alab.")
    if source_path is not None and same_file(path, source_path):
        raise FamilyError("current-path", "Choose a new file: the current project cannot be replaced by a subset.")
    infos = tuple(infos)
    _cancelled(cancel)
    graph = _Graph(tables)
    plan = plan_family(tables, layouts, infos, selected, include_layouts=include_layouts, export=True, graph=graph)
    bundle = _build(tables, layouts, infos, plan, None, renew=False, cancel=cancel, graph=graph)
    _cancelled(cancel)
    save_project(path, bundle.tables, layouts=bundle.layouts, info_sheets=bundle.infos)
    return bundle


def export_plan(tables, layouts, infos, selected, *, include_layouts=True, graph=None):
    """The content of Save family as…, for a preview."""
    return plan_family(tables, layouts, infos, selected, include_layouts=include_layouts, export=True, graph=graph)
