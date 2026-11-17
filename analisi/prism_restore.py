"""Restore verified native recipes and materialize saved Prism views."""
import csv
from uuid import uuid4
import re

import numpy as np
import pandas as pd

from .data import EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_EMF, EDITABLE_PRISM_STACKS, EDITABLE_PRISM_XY, MAX_CELLS
from .prism_import import _identifier, _json_object, _store_table, _zip_table
from .prism_recipes import restore_recipe

SAVED_XY = "Imported Prism XY graph"
SAVED_BINARY_GRAPH = "Imported Prism original graph"
SAVED_BINARY_LAYOUT = "Imported Prism layout"
SAVED_EDITABLE_GRAPH = "Imported Prism editable graph"
SAVED_BINARY_RESULT = "Imported Prism saved results"
BINARY_GRAPH_COLLECTION = "Prism graph collection"
BINARY_LAYOUT_COLLECTION = "Prism layout collection"
PRISM_GRAPH_LINK = "Prism original graph link"
PRISM_GRAPH_STYLE = "Prism original graph style"
PRISM_LAYOUT_PANELS = "Prism layout panels"
MAX_LAYOUT_PANEL_DATA = 2 * 1024 * 1024
PRISM_PREVIEW = "Prism graph preview"
PRISM_RESULT_SHEET = "Prism result sheet"
PRISM_TITLE = "Prism sheet title"
PRISM_NOTES = "Prism import notes"


def _list(value):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("Unsupported Prism sheet list.")
    return value


def _saved_xy(graph, owners, remaining_cells):
    datasets = graph.get("inputDataSets")
    if not isinstance(datasets, list) or not datasets or len(datasets) > 100 or len(set(datasets)) != len(datasets):
        return None
    parts, labels, rows = [], set(), 0
    has_replicates = False
    for i, uid in enumerate(datasets):
        matches = owners.get(uid, ())
        if len(matches) != 1:
            return None
        frame, geometry = matches[0]
        mapping = frame.attrs["prism_columns"]
        xcols = mapping.get(frame.attrs["prism_x"], [])
        columns = mapping[uid]
        if len(xcols) != 1 or not columns:
            return None
        mode = frame.attrs["prism_y_format"]
        errors = columns[1:3] if mode == "y_plus_minus" else []
        has_replicates |= mode == "y_replicates"
        if mode != "y_replicates":
            columns = columns[:1]
        x = frame[xcols[0]]
        if not pd.api.types.is_numeric_dtype(x):
            return None
        name = re.sub(r" \[(?:\d+|Mean|Center)\]$", "", columns[0])
        for column in columns:
            if not pd.api.types.is_numeric_dtype(frame[column]):
                return None
        xs = np.repeat(x.to_numpy(dtype=float, na_value=np.nan), len(columns))
        ys = frame[columns].to_numpy(dtype=float, na_value=np.nan).ravel()
        keep = np.isfinite(xs) & np.isfinite(ys)
        if not keep.any():
            return None
        rows += int(keep.sum())
        if rows * 7 > remaining_cells:
            return None
        part = pd.DataFrame({"X": xs[keep], "Y": ys[keep], "Series": name,
                             "Dataset": i + 1, "Geometry": geometry})
        if len(errors) == 2 and all(pd.api.types.is_numeric_dtype(frame[key]) for key in errors):
            for role, column in zip(("Y plus", "Y minus"), errors, strict=True):
                part[role] = frame[column].to_numpy(dtype=float, na_value=np.nan)[keep]
        parts.append(part)
        labels.add(xcols[0])
    points = pd.concat(parts, ignore_index=True)
    points.attrs["table_format"] = "Prism graph snapshot"
    note = ("Saved Prism XY coordinates. Replicates are shown individually with Trama formatting."
            if has_replicates else "Saved Prism XY coordinates. The plot uses Trama formatting.")
    points.attrs["prism_recipes"] = [(SAVED_XY, {
        PRISM_TITLE: graph["title"], "X label": next(iter(labels)) if len(labels) == 1 else "X",
        PRISM_NOTES: note,
    })]
    return points


def restore_sheets(archive, names, sheets, sources, tables, cells):
    """Add non-executable snapshots and supported native analysis recipes."""
    warnings = []
    owners = {}
    for source in sources.values():
        if source.attrs["prism_x"]:
            for uid in source.attrs["prism_y"]:
                owners.setdefault(uid, []).append((source, "points"))

    def add(name, frame):
        nonlocal cells
        if len(tables) >= 256 or cells + frame.size > MAX_CELLS:
            return False
        cells += frame.size
        _store_table(tables, name, frame)
        return True

    for entry in _list(sheets.get("analyses", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            path = f"analyses/{uid}/"
            sheet = _json_object(archive, path + "sheet.json")
            label = sheet.get("title") or uid
            if not isinstance(label, str):
                raise ValueError("Invalid analysis title.")
            params_path, results_path = path + "parameters.json", path + "results.json"
            params = _json_object(archive, params_path) if params_path in names else {}
            results = _json_object(archive, results_path) if results_path in names else None
            recipe = restore_recipe(sheet, params, sources, results)
            if recipe:
                source, method, options = recipe
                restored = sources[source].attrs.setdefault("prism_recipes", [])
                if len(restored) < 256:
                    restored.append((method, {**options, PRISM_TITLE: label[:160]}))
            else:
                warnings.append(f"Recalculation unavailable for {label}.")
            for record in _list(sheet.get("resultSheets", [])):
                if not isinstance(record, dict):
                    continue
                restore_view(archive, names, path, record, label, sheet, add, owners, MAX_CELLS - cells)
        except (KeyError, TypeError, ValueError, csv.Error):
            warnings.append(f"Some saved analysis content could not be read for {label}.")
    for entry in _list(sheets.get("graphs", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            graph = _json_object(archive, f"graphs/{uid}/sheet.json")
            label = graph.get("title") or uid
            if not isinstance(label, str):
                raise ValueError("Invalid graph title.")
            points = _saved_xy({**graph, "title": label[:160]}, owners, MAX_CELLS - cells)
            if points is None or not add(f"Prism graph · {label}", points):
                warnings.append(f"Graph unavailable for {label}.")
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Graph unavailable for {label}.")
    if warnings:
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            "Prism import · " + " ".join(warnings[:4]) +
            (f" ({len(warnings) - 4} more notices.)" if len(warnings) > 4 else ""))


def restore_binary_views(data, sources, tables, cells, fonts, document_title):
    from .prism_binary_editable import read_editable_graphs
    from .prism_binary_graphs import read_binary_graphs
    from .prism_binary_layouts import read_binary_layouts
    from .prism_binary_results import restore_binary_results
    from .prism_emf_edit import CURVE, POINTS
    from .prism_layout_edit import PRISM_EDITABLE_PANELS
    from .prism_pdf_stacks import STACK_KIND

    source_names = set(tables)
    cells = restore_binary_results(data, sources, tables, cells, fonts)
    for title, frame in tables.items():
        if title not in source_names:
            saved = frame.attrs["prism_binary_result"]
            sheet = saved["sheet_title"].partition(":")[2].strip() or "Saved results"
            frame.attrs["prism_recipes"] = [(SAVED_BINARY_RESULT, {
                PRISM_TITLE: title.removeprefix("Prism result · ")[:240],
                PRISM_NOTES: "Original saved Prism result. Use Result as Data to make an editable copy.",
                PRISM_RESULT_SHEET: sheet,
                "Prism result provenance": saved,
            })]
    try:
        graphs, unavailable = read_binary_graphs(data)
    except ValueError as error:
        graphs, unavailable = [], [str(error)]
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        import_id = uuid4().hex
        graph_links = {graph["id"]: f'{import_id}:{graph["id"]}' for graph in graphs}
        views = [(SAVED_BINARY_GRAPH, {
            PRISM_TITLE: graph["title"],
            PRISM_NOTES: ("Original graph drawing saved by Prism. Export as "
                          f'{graph["preview"]["format"].upper()} to preserve the vector image.'),
            PRISM_PREVIEW: graph["preview"],
            PRISM_GRAPH_LINK: graph_links[graph["id"]],
        }) for graph in graphs]
        _store_collection(tables, document_title, "graphs", BINARY_GRAPH_COLLECTION, views)
        cells += 1
    elif graphs:
        graphs = []
        unavailable += ["The project has reached its table or cell limit."]
    if tables and unavailable:
        count = len(unavailable)
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            f"Unavailable Prism graph previews ({count}) · " + ", ".join(unavailable[:4]))
    cells, layouts = _restore_binary_layouts(data, document_title, graphs, tables, cells, read_binary_layouts)
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        result_frames = {frame.attrs["prism_binary_result"]["sheet_id"]: frame for frame in tables.values()
                         if "prism_binary_result" in frame.attrs}
        try:
            cached_curves = {panel["graph_id"] for _, options in layouts
                             for panel in options.get(PRISM_EDITABLE_PANELS, ())}
            editable = read_editable_graphs(data, sources, result_frames, MAX_CELLS - cells,
                                            cached_curves=cached_curves)
        except ValueError:
            editable = {}
        linked = {}
        for graph in graphs:
            uid = graph["id"]
            if uid not in editable:
                continue
            frame, style = editable[uid]
            if len(tables) >= 256 or cells + frame.size > MAX_CELLS:
                break
            kind = style.get("kind")
            if kind == STACK_KIND:
                if graph["preview"]["format"] != "pdf":
                    continue
                table_format = EDITABLE_PRISM_STACKS
                notes = ("Edit the percentages in the graph data sheet. The editable view retains the saved drawing. "
                         "The original view provides the original vector PDF.")
            elif kind == "columns":
                table_format = EDITABLE_PRISM_COLUMNS
                notes = "Edit means and displayed errors in the graph data sheet. Saved formatting and annotations are retained."
            elif kind in (CURVE, POINTS):
                if graph["preview"]["format"] != "emf":
                    continue
                table_format = EDITABLE_PRISM_EMF
                notes = ("Edit coordinates and any displayed error distances in the graph data sheet. "
                         "The editable view retains the saved drawing. The original graph remains available.")
                if style.get("fixed_overlays"):
                    notes += " The overlaid observations retain their saved positions."
                if style.get("cached_curve"):
                    notes += " The starting coordinates are approximate values recovered from the saved curve."
            else:
                table_format = EDITABLE_PRISM_XY
                notes = "Editable XY graph with recovered Prism formatting. Original drawing remains available."
            frame.attrs["table_format"] = table_format
            frame.attrs["prism_recipes"] = [(SAVED_EDITABLE_GRAPH, {
                PRISM_TITLE: graph["title"] + " · Editable",
                PRISM_NOTES: notes,
                PRISM_GRAPH_STYLE: style,
                PRISM_GRAPH_LINK: graph_links[uid],
                **({PRISM_PREVIEW: graph["preview"]} if table_format != EDITABLE_PRISM_XY else {}),
            })]
            _store_table(tables, f'Prism graph data · {graph["title"]}', frame)
            cells += frame.size
            if table_format in (EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_EMF):
                linked[uid] = (frame, style)
        _link_layout_panel_data(layouts, graph_links, linked)


def _store_collection(tables, title, label, table_format, views):
    carrier = pd.DataFrame({"Prism project": [title]})
    carrier.attrs.update(table_format=table_format, prism_recipes=views)
    _store_table(tables, f"Prism {label} · {title}", carrier)


def _restore_binary_layouts(data, title, graphs, tables, cells, reader):
    from .prism_layout_edit import PRISM_EDITABLE_PANELS, editable_panels

    try:
        layouts, unavailable = reader(data)
    except ValueError as error:
        layouts, unavailable = [], [str(error)]
    graph_previews = {graph["id"]: graph["preview"] for graph in graphs}
    graph_titles = {graph["id"]: graph["title"] for graph in graphs}
    views, panel_bytes = [], 0
    for layout in layouts:
        options = {PRISM_TITLE: layout["title"]}
        if layout.get("preview"):
            options[PRISM_PREVIEW] = layout["preview"]
            options[PRISM_NOTES] = "Original page saved by Prism. Export as EMF to retain the vector drawing."
            panels = editable_panels(layout["preview"], layout["placements"], graph_titles,
                                     placements_complete=layout["placements_complete"])
            if panels:
                options[PRISM_EDITABLE_PANELS] = panels
        elif layout.get("placements_complete") and 1 <= len(layout.get("placements", ())) <= 24:
            panels = []
            for placement in layout["placements"]:
                graph_id = placement["graph_id"]
                if graph_id is not None and graph_id not in graph_previews:
                    break
                panels.append({"bounds": placement["bounds"], "preview": graph_previews.get(graph_id)})
            if len(panels) != len(layout["placements"]) or not any(panel["preview"] for panel in panels):
                unavailable.append(layout["title"])
                continue
            size = sum(len(panel["preview"]["data"]) for panel in panels if panel["preview"])
            if panel_bytes + size > MAX_LAYOUT_PANEL_DATA:
                unavailable.append(layout["title"])
                continue
            panel_bytes += size
            options[PRISM_LAYOUT_PANELS] = panels
            options[PRISM_NOTES] = "Page reconstructed from the original graph positions and saved drawings."
        else:
            unavailable.append(layout["title"])
            continue
        views.append((SAVED_BINARY_LAYOUT, options))
    if views and len(tables) < 256 and cells < MAX_CELLS:
        _store_collection(tables, title, "layouts", BINARY_LAYOUT_COLLECTION, views)
        cells += 1
    elif views:
        unavailable.append("The project has reached its table or cell limit.")
        views = []
    if tables and unavailable:
        titles = list(dict.fromkeys(unavailable))
        next(iter(tables.values())).attrs.setdefault("import_warnings", []).append(
            f"Unavailable Prism layouts ({len(titles)}) · " + ", ".join(titles[:4]))
    return cells, views


def _link_layout_panel_data(layouts, graph_links, linked):
    from .prism_layout_edit import (PRISM_EDITABLE_PANELS, PRISM_PANEL_DATA, edit_panel_artwork,
                                    layout_panel_artwork)

    for _, options in layouts:
        panels = options.get(PRISM_EDITABLE_PANELS)
        if not panels or not any(panel["graph_id"] in linked for panel in panels):
            continue
        artwork = layout_panel_artwork(options[PRISM_PREVIEW], panels)
        links = {}
        for panel in panels:
            panel_id, uid = panel["id"], panel["graph_id"]
            if panel_id not in artwork or uid not in linked:
                continue
            frame, style = linked[uid]
            try:
                edit_panel_artwork(frame, style, artwork[panel_id])
            except ValueError:
                continue
            links[panel_id] = graph_links[uid]
        if links:
            options[PRISM_PANEL_DATA] = links


def restore_view(archive, names, path, record, analysis_title, analysis, add, owners, remaining_cells):
    view_id = _identifier(record.get("uid"))
    view_path = f"{path}result_sheets/{view_id}.json"
    if view_path not in names:
        return
    view = _json_object(archive, view_path)
    if view.get("isInternal") or not view.get("dataSheet"):
        return
    uid = _identifier(view["dataSheet"])
    sheet = _json_object(archive, f"data/sheets/{uid}/sheet.json")
    frame = _zip_table(archive, names, sheet["table"], remaining_cells, result=True)
    if frame is None or frame.empty:
        return
    name = view.get("name") or record.get("title") or view_id
    if not view.get("isVisible") and not frame.attrs["prism_x"]:
        return
    frame.attrs["table_format"] = "Prism result snapshot"
    if not add(f"Prism result · {analysis_title} · {name}", frame):
        return
    if frame.attrs["prism_x"]:
        geometry = "line" if name == "Curve" else "points"
        if analysis.get("analysisClass") == "SURVIVAL" and name == "Survival proportions":
            geometry = "step"
        for dataset in frame.attrs["prism_y"]:
            owners.setdefault(dataset, []).append((frame, geometry))
