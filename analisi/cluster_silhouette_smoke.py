"""Desktop smoke check for Cluster silhouette, kept apart from tramastat.py so other dialogs can change freely.

``tramastat.py --smoke`` calls :func:`check_cluster_silhouette` with its own helpers. Alone:
``TRAMASTAT_SMOKE_ONLY=cluster-silhouette python tramastat.py --smoke DIR``.

It drives the mapped dialog, the Run command and the worker of a real desktop: a plain worksheet, the error and budget
messages, a K-means and a hierarchical result used as input, edits that recalculate the silhouette, a saved and reopened
project, the Cancel command, the exports and the Italian interface. Pictures go to ``DIR/cluster-silhouette``.
"""
from pathlib import Path
import threading
import time
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import cluster_silhouette as module
from .analysis_chain import ResultSource
from .cluster_silhouette import (CLUSTER, CLUSTERS, DISTANCE, GRAPH, LABELS, METHOD, OBSERVATIONS, STANDARDIZE, SUMMARY,
                                 VARIABLES, cluster_silhouette)
from .i18n import active_language, set_language, tr, ui

TITLE = "Partition"
# The package's own fixture, with a literal "$" in an observation label and in a cluster label: a negative silhouette (row 3), a singleton (row 8), a blank
# label, an incomplete row (4), a missing cluster (9) and a constant column.
FIXTURE = pd.DataFrame({
    "Name": ["Original $A", "a2", "", "excluded", "b1", "b2", "b3", "single", "no group"],
    "Group": ["Plate $A", "Plate $A", "Plate $A", "Plate $A", "B", "B", "B", "C", None],
    "X": [0., 0, 6, np.nan, 5, 6, 6, 12, 2],
    "Y": [0., 2, 6, 4, 5, 5, 6, 0, 3],
    "Flat": [3.] * 9,
})
# The first row, in the order the engine and the verifier agree on.
FIRST_SILHOUETTE = 0.326905804553001
BLOBS = pd.DataFrame({
    "X": np.r_[np.random.default_rng(3).normal(0, 1, 300), np.random.default_rng(4).normal(6, 1, 300)],
    "Y": np.r_[np.random.default_rng(5).normal(0, 1, 300), np.random.default_rng(6).normal(6, 1, 300)],
    "Group": ["left"] * 300 + ["right"] * 300,
})
POINTS = pd.DataFrame({"X": [0., 1, 2, 10, 11, 13, 6, 7, 8, np.nan],
                       "Y": [1., 0, 1, 11, 10, 12, 5, 6, 8, 4],
                       "Name": list("abcdefghij")})


def check_cluster_silhouette(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, LayoutDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog, errors, Dataset and save_project."""
    out = Path(directory) / "cluster-silhouette"
    out.mkdir(exist_ok=True)
    language = active_language()
    wait = tools.wait_for_calculation
    errors = tools.errors

    def capture(window, name):
        tools.capture(window, name)
        path = Path(directory) / name
        if path.is_file():
            path.replace(out / name)

    def rejected(dialog, field, expected, changes):
        """Apply the changes, ask for the result and expect an error naming the field; then restore the values."""
        before = {}
        for name, value in changes.items():
            kind, control = dialog.controls[name]
            if name == VARIABLES:
                before[name] = [control.get(i) for i in control.curselection()]
                tools.select_columns(dialog, name, value)
            else:
                before[name] = control.get()
                control.set(value)
        dialog.update()
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, changes
        title, message = report.call_args.args[:2]
        assert expected in message, (expected, message)
        assert ui(field) in message, (field, message)
        for name, value in before.items():
            kind, control = dialog.controls[name]
            if name == VARIABLES:
                tools.select_columns(dialog, name, value)
            else:
                control.set(value)
        dialog.update()
        return message

    def finish():
        wait()
        assert not errors, errors
        assert all(run.calculation_error is None for run in app.runs), [r.calculation_error for r in app.runs]

    def buttons(dialog):
        """Run Analysis and Cancel are fully on the screen."""
        root.update_idletasks()
        wanted = {ui("Run Analysis"), ui("Cancel")}
        found, pending = set(), [dialog]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Button) and widget.cget("text") in wanted:
                found.add(widget.cget("text"))
                assert widget.winfo_viewable()
                assert 0 <= widget.winfo_rootx() < widget.winfo_rootx() + widget.winfo_width() <= root.winfo_screenwidth()
                assert 0 <= widget.winfo_rooty() < widget.winfo_rooty() + widget.winfo_height() <= root.winfo_screenheight()
        assert found == wanted, found

    def note(dialog):
        """The Options tab says that the distance and the scale are not those of the analysis that made the partition."""
        found, pending = [], [dialog]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Label) and widget.cget("text") == tr("silhouette.note"):
                found.append(widget)
        assert len(found) == 1 and found[0].winfo_viewable(), found
        assert found[0].winfo_rootx() + found[0].winfo_reqwidth() <= root.winfo_screenwidth()

    def newest():
        return len(app.runs) - 1

    try:
        set_language("en")
        path = out / "partition.alab"
        tools.save_project(path, {TITLE: tools.Dataset(FIXTURE.copy())})
        app.import_file(path)
        app.show("data", TITLE)

        # ── A plain worksheet: defaults, errors, the first run ────────────────────────────────────────────────
        def plain(dialog):
            tools.pick_method(dialog, METHOD)
            assert dialog.controls[CLUSTER][1].get() == "Group", dialog.controls[CLUSTER][1].get()
            box = dialog.controls[VARIABLES][1]
            assert [box.get(i) for i in box.curselection()] == ["X", "Y", "Flat"]
            assert dialog.controls[DISTANCE][1].get() == "Euclidean"
            assert dialog.controls[STANDARDIZE][1].get() is False and dialog.controls[GRAPH][1].get() is True
            buttons(dialog)
            capture(dialog, "window-silhouette-dialog-en.png")
            rejected(dialog, CLUSTER, "already a variable", {CLUSTER: "X"})
            rejected(dialog, VARIABLES, "at least one", {VARIABLES: []})
            # One cluster only: a constant partition column.
            rejected(dialog, CLUSTER, "Clusters in the partition: 1", {CLUSTER: "Flat", VARIABLES: ["X", "Y"]})
            rejected(dialog, LABELS, "already used", {LABELS: "Group"})
            # Every row has its own label: more clusters than the silhouette accepts.
            rejected(dialog, CLUSTER, "between 2 and 6 clusters", {CLUSTER: "Name", LABELS: ""})
            dialog.controls[LABELS][1].set("Name")
            dialog.fields.select(1)
            dialog.update()
            note(dialog)
            capture(dialog, "window-silhouette-options-en.png")
            dialog.fields.select(0)

        tools.drive_dialog(tools.AnalysisDialog, plain)
        app.choose_analysis()
        finish()
        assert len(app.runs) == 1
        run = app.runs[0]
        assert run.method == METHOD and run.options[CLUSTER] == "Group" and run.options[LABELS] == "Name"
        assert run.options[VARIABLES] == ["X", "Y", "Flat"] and run.options[DISTANCE] == "Euclidean"
        tables = run.result.tables
        assert list(tables) == [OBSERVATIONS, CLUSTERS, SUMMARY], list(tables)
        points = tables[OBSERVATIONS]
        assert points["Source row"].tolist() == [1, 2, 3, 5, 6, 7, 8]
        assert abs(points["Silhouette"].iloc[0] - FIRST_SILHOUETTE) < 1e-12
        assert points["Silhouette"].iloc[2] < -.8, "the negative silhouette is not visible"
        assert points["Silhouette"].iloc[6] == 0 and points["Within mean distance"].isna().iloc[6], "singleton"
        assert points["Observation"].iloc[0] == "Original $A" and points["Observation"].iloc[2] == ""
        summary = tables[SUMMARY]["Value"]
        assert summary["N"] == 7 and summary["Clusters"] == 3 and summary["Dropped rows"] == 2
        assert summary["Distance"] == "Euclidean" and summary["Scale"] == module.ORIGINAL_UNITS
        direct = cluster_silhouette(app.tables[TITLE].frame(mask_excluded=True), run.options)
        pd.testing.assert_frame_equal(points, direct.tables[OBSERVATIONS])

        figure = run.result.figure
        assert figure is not None
        axes = figure.axes[0]
        captions = [text.get_text() for text in axes.get_yticklabels()]
        assert captions == ["Plate \\$A\nn = 3", "B\nn = 3", "C\nn = 1"], captions
        assert any(float(patch.get_width()) < 0 for patch in axes.patches), "no negative bar"
        assert "Silhouette by observation (Euclidean, original units)" in axes.get_title()
        app.show("graph", 0)
        capture(root, "window-silhouette-graph-en.png")
        app.show("result", 0)
        capture(root, "window-silhouette-results-en.png")
        assert tr("silhouette.note") != "silhouette.note"
        # The Graphs list offers the analysis, also before its result is loaded.
        assert ("graph", 0) in [ref for _, ref in next(
            section for section in app.sheet_sections() if section[0] == "Graphs")[1]]

        # ── Manhattan, standardized, without a graph, on a constant column ────────────────────────────────────
        def manhattan(dialog):
            tools.pick_method(dialog, METHOD)
            dialog.controls[DISTANCE][1].set("Manhattan")
            dialog.controls[STANDARDIZE][1].set(True)
            dialog.controls[GRAPH][1].set(False)
            dialog.controls[LABELS][1].set("Name")

        tools.drive_dialog(tools.AnalysisDialog, manhattan)
        app.show("data", TITLE)
        app.choose_analysis()
        finish()
        second = app.runs[newest()]
        assert second.result.figure is None and second.options[GRAPH] is False
        summary = second.result.tables[SUMMARY]["Value"]
        assert summary["Distance"] == "Manhattan" and summary["Scale"] == module.STANDARDIZED_UNITS
        direct = cluster_silhouette(app.tables[TITLE].frame(mask_excluded=True), second.options)
        pd.testing.assert_frame_equal(second.result.tables[OBSERVATIONS], direct.tables[OBSERVATIONS])
        assert np.isfinite(second.result.tables[OBSERVATIONS]["Silhouette"].to_numpy(float)).all()
        # A run without a graph is not listed under Graphs.
        listed = [ref for _, ref in next(section for section in app.sheet_sections() if section[0] == "Graphs")[1]]
        assert ("graph", 1) not in listed and ("graph", 0) in listed, listed

        # Editing the worksheet recalculates the silhouette: row 3 moves toward the rest of its cluster.
        app.show("data", TITLE)
        before = app.runs[0].result.tables[OBSERVATIONS]["Silhouette"].iloc[2]
        app.edit_cell(2, 2, "1")
        finish()
        after = app.runs[0].result.tables[OBSERVATIONS]["Silhouette"].iloc[2]
        assert before < -.8 and after > before + .5, (before, after)
        app.show("data", TITLE)
        app.edit_cell(2, 2, "6")
        finish()
        assert abs(app.runs[0].result.tables[OBSERVATIONS]["Silhouette"].iloc[2] - before) < 1e-12

        # ── Typed identities: the number 1 and the text "1" are two clusters; the sheet keeps the originals ────
        typed = pd.DataFrame({"X": [0., 0.1, 0.2, 5, 5.1, 5.2, 9, 9.1], "Y": [0., 0, 0, 1, 1, 1, 2, 2],
                              "Cluster": pd.Series([1, 1, "1", "1", 2, 2, "2", "2"], dtype=object)})
        path = out / "typed.alab"
        tools.save_project(path, {"Typed": tools.Dataset(typed)})
        app.import_file(path)

        def typed_run(dialog):
            tools.pick_method(dialog, METHOD)
            assert dialog.controls[CLUSTER][1].get() == "Cluster"
            box = dialog.controls[VARIABLES][1]
            assert [box.get(i) for i in box.curselection()] == ["X", "Y"]

        tools.drive_dialog(tools.AnalysisDialog, typed_run)
        app.show("data", "Typed")
        app.choose_analysis()
        finish()
        found = app.runs[newest()].result.tables
        shown = found[CLUSTERS]["Cluster"].tolist()
        assert shown == [1, "1", 2, "2"] and [type(v) for v in shown] == [int, str, int, str], shown
        assert found[SUMMARY]["Value"]["Clusters"] == 4

        # ── An exact tie between rival clusters: the first one in order of appearance is the nearest ──────────
        ties = pd.DataFrame({"Name": ["center1", "center2", "right1", "right2", "left1", "left2"],
                             "Group": ["Center", "Center", "Right", "Right", "Left", "Left"],
                             "X": [0., 0, 2, 3, -2, -3], "Y": [0., 0, 0, 0, 0, 0]})
        path = out / "ties.alab"
        tools.save_project(path, {"Ties": tools.Dataset(ties)})
        app.import_file(path)

        def tied(dialog):
            tools.pick_method(dialog, METHOD)
            assert dialog.controls[CLUSTER][1].get() == "Group"

        tools.drive_dialog(tools.AnalysisDialog, tied)
        app.show("data", "Ties")
        app.choose_analysis()
        finish()
        found = app.runs[newest()].result.tables[OBSERVATIONS]
        assert found["Nearest other cluster"].tolist() == ["Right", "Right", "Center", "Center", "Center", "Center"]
        assert found["Nearest mean distance"].iloc[0] == 2.5 and found["Silhouette"].iloc[0] == 1.0

        # ── Cancel: the worker stops between blocks, nothing is recorded ──────────────────────────────────────
        path = out / "blobs.alab"
        tools.save_project(path, {"Blobs": tools.Dataset(BLOBS.copy())})
        app.import_file(path)
        calls = []
        real = module.cdist

        def slow(*args, **kwargs):
            calls.append(threading.current_thread().name)
            time.sleep(.05)
            return real(*args, **kwargs)

        def blobs(dialog):
            tools.pick_method(dialog, METHOD)

        def wait_for_worker():
            deadline = time.monotonic() + 20
            while not (calls and app.calculation is not None):
                assert time.monotonic() < deadline, "the calculation did not start"
                root.update()
                time.sleep(.02)

        with patch.object(module, "cdist", slow), patch.object(module, "BLOCK_BYTES", 8 * (600 + 4) * 20):
            tools.drive_dialog(tools.AnalysisDialog, blobs)
            app.show("data", "Blobs")
            app.choose_analysis()
            wait_for_worker()
            assert app.cancel_button.winfo_manager(), "Cancel calculation is not shown"
            capture(root, "window-silhouette-running-en.png")
            app.cancel_calculation()
            wait()
            assert not app.cancel_button.winfo_manager()
            assert "cancelled" in app.status.get() and "No study was added" in app.status.get(), app.status.get()
            assert not app.runs and not app.tables["Blobs"].analyses, "a cancelled analysis was recorded"
            assert all(name.startswith("Trama") for name in calls), calls
            stopped = len(calls)
            assert 1 <= stopped < 30, stopped
        calls.clear()
        # The next calculation is unaffected by the cancelled one.
        tools.drive_dialog(tools.AnalysisDialog, blobs)
        app.show("data", "Blobs")
        app.choose_analysis()
        finish()
        big = app.runs[newest()]
        assert big.result.tables[SUMMARY]["Value"]["N"] == 600 and big.result.tables[SUMMARY]["Value"]["Clusters"] == 2
        kept = big.result
        with patch.object(module, "cdist", slow), patch.object(module, "BLOCK_BYTES", 8 * (600 + 4) * 20):
            app.recalculate(newest())
            wait_for_worker()
            app.cancel_calculation()
            wait()
        assert app.runs[newest()].result is kept, "the last completed result was not kept"
        assert "cancelled" in app.status.get() and "kept" in app.status.get(), app.status.get()

        # ── A K-means result as input: Analyze this result… on its Assignments table ──────────────────────────
        path = out / "points.alab"
        tools.save_project(path, {"Points": tools.Dataset(POINTS.copy())})
        app.import_file(path)

        def kmeans(dialog):
            tools.pick_method(dialog, "K-means clustering")
            tools.select_columns(dialog, "Variables", ["X", "Y"])
            dialog.controls["Clusters"][1].set("2")
            dialog.controls["Standardize"][1].set(False)

        tools.drive_dialog(tools.AnalysisDialog, kmeans)
        app.show("data", "Points")
        app.choose_analysis()
        finish()
        assert app.runs[0].method == "K-means clustering"
        app.show("result", 0)
        app.result_tabs.select(list(app.runs[0].result.tables).index("Assignments"))

        def linked(dialog, picture="window-silhouette-linked-dialog-en.png"):
            tools.pick_method(dialog, METHOD)
            assert dialog.controls[CLUSTER][1].get() == "Cluster", dialog.controls[CLUSTER][1].get()
            box = dialog.controls[VARIABLES][1]
            assert [box.get(i) for i in box.curselection()] == ["X", "Y"]
            buttons(dialog)
            capture(dialog, picture)

        tools.drive_dialog(tools.AnalysisDialog, linked)
        app.analyze_result_table()
        finish()
        assert len(app.runs) == 2 and app.runs[1].method == METHOD
        assert app.runs[1].source == ResultSource(app.runs[0].uid, "Assignments")
        identifiers = [item.uid for item in app.runs]

        def expected_linked(index=0, table="Assignments", other=1):
            frame = app.runs[index].result.tables[table]
            return cluster_silhouette(frame, app.runs[other].options).tables[OBSERVATIONS]

        pd.testing.assert_frame_equal(app.runs[1].result.tables[OBSERVATIONS], expected_linked())
        assert app.runs[1].result.tables[SUMMARY]["Value"]["N"] == 9, "the incomplete row is dropped before K-means"
        app.show("graph", 1)
        capture(root, "window-silhouette-linked-graph-en.png")

        # The distance and the scale of the silhouette are its own: K-means standardized, the silhouette did not.
        assert app.runs[1].result.tables[SUMMARY]["Value"]["Scale"] == module.ORIGINAL_UNITS

        # A worksheet edit recalculates K-means first and the silhouette after it, on the worker.
        seen = []
        compute = app.compute

        def spy(run, *args, **kwargs):
            seen.append((run.uid, threading.current_thread().name))
            return compute(run, *args, **kwargs)

        app.show("data", "Points")
        with patch.object(app, "compute", side_effect=spy):
            app.edit_cell(8, 0, "5")
            finish()
        assert [key for key, _ in seen] == identifiers and all(name.startswith("Trama") for _, name in seen), seen
        pd.testing.assert_frame_equal(app.runs[1].result.tables[OBSERVATIONS], expected_linked())
        first = app.runs[1].result.tables[SUMMARY]["Value"]["Mean silhouette"]
        # A different number of clusters upstream gives a different partition and a different silhouette.
        app.runs[0].options["Clusters"] = 3
        app.recalculate(0)
        finish()
        pd.testing.assert_frame_equal(app.runs[1].result.tables[OBSERVATIONS], expected_linked())
        assert app.runs[1].result.tables[SUMMARY]["Value"]["Clusters"] == 3
        assert app.runs[1].result.tables[SUMMARY]["Value"]["Mean silhouette"] != first
        app.runs[0].options["Clusters"] = 2
        app.recalculate(0)
        finish()
        assert app.runs[1].result.tables[SUMMARY]["Value"]["Clusters"] == 2

        # Use Result as Data: an independent copy that no later edit changes.
        app.show("result", 1)
        app.result_tabs.select(0)
        app.use_result_as_data()
        copied = next(title for title in app.tables if title.startswith(OBSERVATIONS))
        independent = app.tables[copied].raw.copy(deep=True)
        assert independent["Cluster"].tolist() == app.runs[1].result.tables[OBSERVATIONS]["Cluster"].tolist()
        app.show("data", "Points")
        app.edit_cell(8, 0, "9")
        finish()
        pd.testing.assert_frame_equal(app.tables[copied].raw, independent)
        app.show("data", "Points")
        app.apply_worksheet_history()
        finish()

        # ── A hierarchical result: its Row Assignments table ──────────────────────────────────────────────────
        def hierarchical(dialog):
            tools.pick_method(dialog, "Hierarchical clustering")
            tools.select_columns(dialog, "Variables", ["X", "Y"])

        tools.drive_dialog(tools.AnalysisDialog, hierarchical)
        app.show("data", "Points")
        app.choose_analysis()
        finish()
        tree = next(i for i, item in enumerate(app.runs) if item.method == "Hierarchical clustering")
        app.show("result", tree)
        table = next(name for name in app.runs[tree].result.tables if name.endswith("Assignments"))
        app.result_tabs.select(list(app.runs[tree].result.tables).index(table))
        tools.drive_dialog(tools.AnalysisDialog,
                           lambda dialog: linked(dialog, "window-silhouette-linked-dialog-hierarchical-en.png"))
        app.analyze_result_table()
        finish()
        child = len(app.runs) - 1
        assert app.runs[child].source == ResultSource(app.runs[tree].uid, table)
        pd.testing.assert_frame_equal(app.runs[child].result.tables[OBSERVATIONS],
                                      expected_linked(tree, table, child))

        # ── Saved and reopened: the linked graph opened before the upstream result ────────────────────────────
        app.path = out / "linked.alab"
        assert app.save()
        saved = {item.uid: item.result.tables[OBSERVATIONS] for item in app.runs if item.method == METHOD}
        app.import_file(out / "linked.alab")
        assert all(item.result is None for item in app.runs)
        app.open_sheet(("graph", 1))
        finish()
        assert app.runs[1].result is not None and app.runs[1].result.figure is not None
        assert app.runs[0].result is not None, "the upstream result was not recalculated first"
        for index, item in enumerate(app.runs):
            if item.method == METHOD:
                if item.result is None:
                    app.open_sheet(("graph", index))
                    finish()
                pd.testing.assert_frame_equal(item.result.tables[OBSERVATIONS], saved[item.uid])

        # ── Stale dependency: the upstream result changes shape; the last good silhouette is kept, not exported ──
        old = app.runs[child].result
        app.runs[tree].options["Row cut"] = "No cut"
        app.recalculate(tree)
        wait()
        assert not errors, errors
        assert app.runs[child].result is old and app.runs[child].calculation_error
        app.show("graph", child)
        with patch.object(app, "error") as error, patch.object(tools.filedialog, "asksaveasfilename") as chooser:
            app.export()
        assert error.called and not chooser.called
        app.runs[tree].options["Row cut"] = "Count"
        app.recalculate(tree)
        finish()
        assert app.runs[child].calculation_error is None

        # ── Exports: the table as CSV, the graph as SVG, PNG and PDF ──────────────────────────────────────────
        app.show("result", child)
        target = out / "silhouettes.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert "Silhouette" in target.read_text(encoding="utf-8")
        for suffix in ("svg", "png", "pdf"):
            app.show("graph", child)
            target = out / f"silhouette.{suffix}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, suffix

        # A layout holding the graph exports a PDF as well.
        def panel(dialog):
            dialog.name.set("Silhouette figure")
            index = next(i for i, item in enumerate(dialog.runs) if item.reference == app.runs[child].reference)
            dialog.list.selection_set(index)
            dialog.add_selected()

        tools.drive_dialog(tools.LayoutDialog, panel)
        app.new_layout()
        assert app.layouts and app.layout_figure is not None
        target = out / "silhouette-layout.pdf"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000
        capture(root, "window-silhouette-layout-en.png")

        # ── Italian interface ─────────────────────────────────────────────────────────────────────────────────
        set_language("it")
        app.import_file(out / "partition.alab")
        app.show("data", TITLE)

        def italian(dialog):
            tools.pick_method(dialog, METHOD)
            assert dialog.heading.cget("text") == "Silhouette dei cluster", dialog.heading.cget("text")
            assert dialog.controls[DISTANCE][1].get() == "Euclidean", "the recipe keeps the canonical choice"
            assert dialog.choice_bindings[DISTANCE].display.get() == "Euclidea"
            buttons(dialog)
            capture(dialog, "window-silhouette-dialog-it.png")
            dialog.fields.select(1)
            dialog.update()
            note(dialog)
            assert "Non dipendono" in tr("silhouette.note")
            capture(dialog, "window-silhouette-options-it.png")
            dialog.fields.select(0)
            message = rejected(dialog, CLUSTER, "è già una variabile", {CLUSTER: "X"})
            assert "Cluster" in message and "Column" not in message, message
            rejected(dialog, CLUSTER, "Cluster nella partizione: 1", {CLUSTER: "Flat", VARIABLES: ["X", "Y"]})

        tools.drive_dialog(tools.AnalysisDialog, italian)
        app.choose_analysis()
        finish()
        assert len(app.runs) == 1 and app.runs[0].options[DISTANCE] == "Euclidean"
        app.show("result", 0)
        capture(root, "window-silhouette-results-it.png")

        assert not errors, errors
    finally:
        set_language(language)
