"""Linked tables: records, source resolution and its explicit states, drawing and the project round trip.

The numbers are the ones of ``casi.json``: the slope of the regression of ``Misure`` is 2 and becomes 2.6 when
B4 goes from 7 to 9; a linked table follows it, a copy keeps 2.
"""
import json
import re
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd
from matplotlib.figure import Figure

from analisi import linked_tables as lt
from analisi.figure_export import export_pdf_bundle
from analisi.i18n import active_language, set_language
from analisi.linked_tables import FrameSource, Problem, Resolved, TableSpec
from analisi.presentation import Layout, validated_style
from trama_qt.project import Project, TableLookup, compute

SAMPLE = {"version": 2, "tables": [{
    "title": "Misure", "columns": ["X", "Risposta"], "kinds": ["numeric", "numeric"],
    "rows": [[0, 1], [1, 3], [2, 5], [3, 7]], "formulas": [], "analyses": [
        ["Linear regression", {"X": "X", "Y": "Risposta"}]], "excluded": [], "table_format": "xy",
    "graph_styles": {}}], "layouts": [{"name": "Risultati in figura", "columns": 1, "panels": [["Misure", 0]],
                                       "paper": "A4 landscape", "background": "#ffffff"}]}
SVG = "{http://www.w3.org/2000/svg}"


def written(folder, document=None):
    path = Path(folder) / "testo-e-tabelle.alab"
    path.write_text(json.dumps(document or SAMPLE), encoding="utf-8")
    return path


def opened(folder, path=None):
    project = Project()
    project.load(path or written(folder))
    calculate(project)
    return project


def calculate(project):
    """What the window does after an open or an edit: every analysis calculated on its own sheet."""
    for index, run in enumerate(project.runs):
        project.add_result(run, compute(run, project.tables[run.title].frame(mask_excluded=True)), index)


def source(project, table="Regression"):
    return next(choice for choice in project.table_source_choices()
                if choice["kind"] == "result" and choice["table"] == table)


def slope_record(project, **options):
    run = project.runs[0]
    row = list(run.result.tables["Regression"].index).index("Slope")
    return project.table_record(source(project), (row, 0, row, 0), **options)


def put_on_graph(project, *records, run=None):
    run = run or project.runs[0]
    style = deepcopy(run.style or {})
    style[lt.TABLES] = list(records)
    project.apply_format(run, style)


def cells(project):
    return [(owner[0], record["mode"], resolved.state, resolved.cells) for owner, record, resolved
            in project.linked_table_report()]


def pdf_words(path, page=0):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(path)) as document:
        sheet = document[page]
        try:
            return sheet.get_textpage().get_text_range().split()
        finally:
            sheet.close()


class RecordTests(unittest.TestCase):
    RECORD = {"id": "6f1c0c0e-7c5e-4d0c-8a53-2f6a3f2b9c10", "mode": "linked", "position": [.1, .2], "size": 9,
              "headers": "both", "orientation": "normal", "grid": True,
              "source": {"kind": "sheet", "sheet": "Misure", "rows": ["base:1", "base:2"], "columns": ["X"]}}

    def test_a_record_is_validated_into_an_independent_copy(self):
        record = lt.validate_table(self.RECORD)
        self.assertEqual(record["size"], 9.0)
        record["source"]["rows"].append("base:3")
        self.assertEqual(self.RECORD["source"]["rows"], ["base:1", "base:2"])
        self.assertEqual(lt.validate_tables([self.RECORD, {**self.RECORD, "id": lt.new_id()}])[1]["mode"], "linked")

    def test_malformed_records_are_refused(self):
        def bad(**changes):
            record = {**deepcopy(self.RECORD), **changes}
            with self.assertRaises(ValueError, msg=str(changes)):
                lt.validate_table(record)

        bad(id="not-a-uuid")
        bad(mode="live")
        bad(position=[1.5, 0])
        bad(position=[0, float("nan")])
        bad(size=3)
        bad(size=True)
        bad(headers="top")
        bad(orientation="rotated")
        bad(grid="yes")
        bad(font="Comic Sans")
        bad(extra=1)
        bad(source={"kind": "sheet", "sheet": "Misure", "rows": ["7"], "columns": ["X"]})
        bad(source={"kind": "sheet", "sheet": "Misure", "rows": ["base:1", "base:1"], "columns": ["X"]})
        bad(source={"kind": "sheet", "sheet": "", "rows": ["base:1"], "columns": ["X"]})
        bad(source={"kind": "result", "analysis": "a", "table": "T", "rows": [-1], "columns": ["V"],
                    "by": "position", "rows_total": 3})
        bad(source={"kind": "result", "analysis": "a", "table": "T", "rows": [0], "columns": ["V"],
                    "by": "position"})
        bad(values={"rows": [], "columns": [], "cells": []})
        with self.assertRaises(ValueError):
            lt.validate_table({key: value for key, value in self.RECORD.items() if key != "source"})
        with self.assertRaises(ValueError):
            lt.validate_tables([self.RECORD, self.RECORD])
        with self.assertRaises(ValueError):
            lt.validate_tables([{**self.RECORD, "id": lt.new_id()} for _ in range(lt.MAX_TABLES + 1)])

    def test_a_copy_holds_values_and_no_source(self):
        copy = {key: value for key, value in self.RECORD.items() if key != "source"}
        copy.update(mode="copy", values={"rows": ["1"], "columns": ["V"], "cells": [["2"]]})
        self.assertEqual(lt.validate_table(copy)["values"]["cells"], [["2"]])
        with self.assertRaises(ValueError):
            lt.validate_table({**copy, "source": self.RECORD["source"]})
        with self.assertRaises(ValueError):
            lt.validate_table({**copy, "values": {"rows": ["1"], "columns": ["V"], "cells": [["2", "3"]]}})

    def test_the_range_is_measured_before_anything_is_read(self):
        for rows, columns in ((0, 1), (1, 0), (lt.MAX_ROWS + 1, 1), (1, lt.MAX_COLUMNS + 1), (40, 16)):
            with self.assertRaises(ValueError, msg=(rows, columns)):
                lt.check_size(rows, columns)
        lt.check_size(lt.MAX_ROWS, 10)
        lt.check_size(1, 1)
        huge = {**self.RECORD, "source": {**self.RECORD["source"], "rows": [f"base:{n}" for n in range(1, 5001)]}}
        with self.assertRaises(ValueError) as caught:
            lt.validate_table(huge)
        self.assertIn("up to 60 rows", str(caught.exception))

    def test_graph_styles_and_layouts_validate_their_tables(self):
        style = validated_style({lt.TABLES: [self.RECORD]})
        self.assertEqual(len(style[lt.TABLES]), 1)
        with self.assertRaises(ValueError):
            validated_style({lt.TABLES: [{**self.RECORD, "mode": "live"}]})
        layout = Layout("L", 1, [("Misure", 0)], tables=[self.RECORD])
        self.assertEqual(layout.tables[0]["id"], self.RECORD["id"])
        with self.assertRaises(ValueError):
            Layout("L", 1, [("Misure", 0)], tables=[{**self.RECORD, "grid": 1}])

    def test_remapping_and_renaming_only_touch_what_they_name(self):
        records = [self.RECORD]
        self.assertIs(lt.rename_sheet(records, "Altro", "X"), records)
        renamed = lt.rename_sheet(records, "Misure", "Prove")
        self.assertEqual(renamed[0]["source"]["sheet"], "Prove")
        self.assertEqual(records[0]["source"]["sheet"], "Misure")
        result = {**self.RECORD, "source": {"kind": "result", "analysis": "old", "table": "T", "rows": ["a"],
                                            "columns": ["V"], "by": "keys"}}
        moved = lt.remap_sources([result, self.RECORD], {"old": "new"}, {"Misure": "Copia"})
        self.assertEqual((moved[0]["source"]["analysis"], moved[1]["source"]["sheet"]), ("new", "Copia"))
        self.assertIs(lt.remap_sources([result], {"other": "x"}, {}) [0], result)


class FakeLookup:
    def __init__(self, sheets=None, results=None):
        self._sheets, self._results = sheets or {}, results or {}

    def sheet(self, title):
        return self._sheets.get(title, Problem("missing", f"no sheet {title}"))

    def result(self, analysis, table):
        return self._results.get((analysis, table), Problem("missing", "no result"))


def frame_source(frame, spans=None, labelled=False):
    return FrameSource(frame, lambda row, column: str(frame.iat[row, column]), spans=spans,
                       row_label=lambda row: str(frame.index[row]), labelled=labelled)


class ResolutionTests(unittest.TestCase):
    def sheet_record(self, rows, columns):
        return lt.validate_table({"id": lt.new_id(), "mode": "linked", "position": [0, 0], "size": 9,
                                  "headers": "both", "orientation": "normal", "grid": True,
                                  "source": {"kind": "sheet", "sheet": "S", "rows": rows, "columns": columns}})

    def result_record(self, rows, columns, **extra):
        by = "keys" if all(isinstance(row, str) for row in rows) else "position"
        source = {"kind": "result", "analysis": "A", "table": "T", "rows": rows, "columns": columns, "by": by}
        if by == "position":
            source["rows_total"] = extra.get("total", 3)
        return lt.validate_table({"id": lt.new_id(), "mode": "linked", "position": [0, 0], "size": 9,
                                  "headers": "both", "orientation": "normal", "grid": True, "source": source})

    def test_a_sheet_range_is_found_by_row_identity_and_column_name(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})
        spans = (("base", 1, 3),)
        record = self.sheet_record(["base:2", "base:3"], ["Y"])
        found = lt.resolve(record, FakeLookup(sheets={"S": frame_source(frame, spans)}))
        self.assertEqual((found.state, found.cells), ("ok", (("5",), ("6",))))
        # Two rows were inserted above: the identities moved, so did the rows the table reads.
        spans = (("base", 1, 1), ("new", 1, 2), ("base", 2, 2))
        frame = pd.DataFrame({"X": [1, 0, 0, 2, 3], "Y": [4, 0, 0, 5, 6]})
        found = lt.resolve(record, FakeLookup(sheets={"S": frame_source(frame, spans)}))
        self.assertEqual(found.cells, (("5",), ("6",)))
        self.assertEqual(found.row_labels, ("4", "5"))

    def test_every_way_the_source_can_go_is_an_explicit_state(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})
        spans = (("base", 1, 3),)
        record = self.sheet_record(["base:2"], ["Y"])

        def state(record, lookup):
            return lt.resolve(record, lookup).state

        self.assertEqual(state(record, FakeLookup()), "missing")                       # the sheet is gone
        self.assertEqual(state(record, FakeLookup(sheets={"S": Problem("error", "boom")})), "error")
        gone = (("base", 1, 1), ("base", 3, 1))
        self.assertEqual(state(record, FakeLookup(sheets={"S": frame_source(frame.iloc[[0, 2]], gone)})),
                         "missing")                                                    # the row was deleted
        self.assertEqual(state(self.sheet_record(["base:2"], ["Z"]),
                               FakeLookup(sheets={"S": frame_source(frame, spans)})), "missing")  # the column
        twin = pd.DataFrame([[1, 4, 7]], columns=["X", "Y", "Y"])
        self.assertEqual(state(self.sheet_record(["base:1"], ["Y"]),
                               FakeLookup(sheets={"S": frame_source(twin, (("base", 1, 1),))})), "ambiguous")
        self.assertEqual(state(record, FakeLookup(sheets={"S": frame_source(frame.iloc[0:0], ())})), "empty")

    def test_a_result_is_read_by_keys_and_never_by_the_nearest_row(self):
        frame = pd.DataFrame({"Value": [1.0, 2.0, 3.0]}, index=["N", "Slope", "Intercept"])
        record = self.result_record(["Slope"], ["Value"])
        look = FakeLookup(results={("A", "T"): frame_source(frame, labelled=True)})
        self.assertEqual(lt.resolve(record, look).cells, (("2.0",),))
        reordered = frame.iloc[[2, 1, 0]]
        look = FakeLookup(results={("A", "T"): frame_source(reordered, labelled=True)})
        self.assertEqual(lt.resolve(record, look).cells, (("2.0",),))  # still the row called Slope
        gone = frame.drop("Slope")
        self.assertEqual(lt.resolve(record, FakeLookup(results={("A", "T"): frame_source(gone, labelled=True)})).state,
                         "missing")
        twice = pd.DataFrame({"Value": [1.0, 2.0, 5.0]}, index=["N", "Slope", "Slope"])
        self.assertEqual(lt.resolve(record, FakeLookup(results={("A", "T"): frame_source(twice, labelled=True)})).state,
                         "ambiguous")
        renamed = frame.rename(columns={"Value": "Estimate"})
        self.assertEqual(lt.resolve(record, FakeLookup(results={("A", "T"): frame_source(renamed, labelled=True)})).state,
                         "missing")
        self.assertEqual(lt.resolve(record, FakeLookup(results={("A", "T"): Problem("pending", "")})).state, "pending")
        self.assertEqual(lt.resolve(record, FakeLookup()).state, "missing")

    def test_unlabelled_rows_are_read_by_position_and_a_changed_shape_is_reported(self):
        frame = pd.DataFrame({"Value": [1.0, 2.0, 3.0]})
        record = self.result_record([1], ["Value"], total=3)
        look = FakeLookup(results={("A", "T"): frame_source(frame)})
        self.assertEqual(lt.resolve(record, look).cells, (("2.0",),))
        longer = pd.concat([frame, frame], ignore_index=True)
        self.assertEqual(lt.resolve(record, FakeLookup(results={("A", "T"): frame_source(longer)})).state, "changed")

    def test_transposition_headers_and_copies(self):
        frame = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        record = self.sheet_record(["base:1", "base:2"], ["A", "B"])
        found = lt.resolve(record, FakeLookup(sheets={"S": frame_source(frame, (("base", 1, 2),))}))
        spec = TableSpec({**record, "orientation": "transposed"}, found)
        grid, problem = lt._lines(spec)
        self.assertIsNone(problem)
        self.assertEqual([[text for _, text in line] for line in grid],
                         [["", "1", "2"], ["A", "1", "2"], ["B", "3", "4"]])
        copy = lt.validate_table({**{k: v for k, v in record.items() if k != "source"}, "mode": "copy",
                                  "values": {"rows": ["1"], "columns": ["V"], "cells": [["7"]]}})
        self.assertEqual(lt.resolve(copy, None).cells, (("7",),))   # a copy never looks anything up


class DrawingTests(unittest.TestCase):
    def draw(self, **changes):
        figure = Figure(figsize=(6, 4))
        record = lt.validate_table({"id": lt.new_id(), "mode": "copy", "position": [.1, .2], "size": 10,
                                    "headers": "both", "orientation": "normal", "grid": True,
                                    "values": {"rows": ["a", "b"], "columns": ["x", "y"],
                                               "cells": [["1", "2.5"], ["3", "text"]]}, **changes})
        artists = lt.draw_tables(figure, [TableSpec(record, lt.resolve(record, None))])
        return figure, artists[0]

    def test_one_container_per_table_with_bounded_children(self):
        figure, artist = self.draw()
        self.assertEqual(len(figure.artists), 1)
        self.assertEqual(artist.get_gid(), f"{lt.GID}{artist.spec.record['id']}")
        self.assertLess(len(artist._children), 40)
        self.assertEqual(figure.axes, [])
        figure.canvas.draw()

    def test_a_table_is_moved_back_onto_the_page_instead_of_being_cut(self):
        def corner(figure, artist):
            """Top left of the table in pixels from the top left of the page."""
            x, y = artist._children[0].get_transform().transform((0, 0))
            return x, figure.bbox.y1 - y

        figure, artist = self.draw(position=[.98, .97])
        left, top = corner(figure, artist)
        width, height = (value / 72 * figure.dpi for value in artist.size_points)
        self.assertGreaterEqual(left, 0)
        self.assertLessEqual(left + width, figure.bbox.x1 + .01)
        self.assertLessEqual(top + height, figure.bbox.y1 + .01)
        self.assertLess(left, .98 * figure.bbox.x1)               # it moved
        # A table that fits keeps exactly the position that was asked for.
        figure, artist = self.draw(position=[.1, .2])
        left, top = corner(figure, artist)
        self.assertAlmostEqual(left / figure.dpi, .1 * 6, places=4)
        self.assertAlmostEqual(top / figure.dpi, .2 * 4, places=4)

    def test_the_largest_table_stays_small(self):
        figure = Figure(figsize=(6, 4))
        rows = [str(row) for row in range(lt.MAX_ROWS)]
        columns = [f"c{column}" for column in range(lt.MAX_CELLS // lt.MAX_ROWS)]
        values = {"rows": rows, "columns": columns, "cells": [["1"] * len(columns) for _ in rows]}
        record = lt.validate_table({"id": lt.new_id(), "mode": "copy", "position": [0, 0], "size": 6,
                                    "headers": "both", "orientation": "normal", "grid": True, "values": values})
        artist = lt.draw_tables(figure, [TableSpec(record, lt.resolve(record, None))])[0]
        self.assertLessEqual(len(artist._children), 3 + lt.MAX_CELLS + lt.MAX_ROWS + lt.MAX_COLUMNS + 2 * 70)

    def test_an_unreadable_source_is_drawn_as_its_state(self):
        for language, caption in (("en", "Source not available"), ("it", "Origine non disponibile")):
            self.addCleanup(set_language, active_language())
            set_language(language)
            figure = Figure(figsize=(6, 4))
            record = lt.validate_table({"id": lt.new_id(), "mode": "linked", "position": [.1, .2], "size": 10,
                                        "headers": "none", "orientation": "normal", "grid": True,
                                        "origin": "Regression of Misure: Slope / Value",
                                        "source": {"kind": "sheet", "sheet": "X", "rows": ["base:1"],
                                                   "columns": ["A"]}})
            spec = TableSpec(record, Resolved("missing", "The worksheet is gone."))
            artist = lt.draw_tables(figure, [spec])[0]
            texts = [child.get_text() for child in artist._children if hasattr(child, "get_text")]
            self.assertEqual(texts[0], caption)
            self.assertIn("The worksheet is gone.", texts)
            figure.canvas.draw()

    def test_sync_redraws_only_when_the_values_change(self):
        figure = Figure(figsize=(6, 4))
        record = lt.validate_table({"id": lt.new_id(), "mode": "copy", "position": [0, 0], "size": 10,
                                    "headers": "none", "orientation": "normal", "grid": True,
                                    "values": {"rows": ["a"], "columns": ["x"], "cells": [["1"]]}})
        spec = TableSpec(record, lt.resolve(record, None))
        self.assertTrue(lt.sync_tables(figure, [spec]))
        first = figure.artists[0]
        self.assertFalse(lt.sync_tables(figure, [spec]))
        self.assertIs(figure.artists[0], first)
        moved = TableSpec({**record, "position": [.5, .5]}, spec.resolved)
        self.assertTrue(lt.sync_tables(figure, [moved]))
        self.assertEqual(len(figure.artists), 1)
        self.assertTrue(lt.sync_tables(figure, []))
        self.assertEqual(figure.artists, [])
        self.assertFalse(lt.sync_tables(figure, []))

    def test_the_table_keeps_its_size_when_the_figure_is_resized(self):
        figure, artist = self.draw()
        figure.canvas.draw()
        width = max(child.get_window_extent().width for child in artist._children if hasattr(child, "get_text")
                    and child.get_text())
        figure.set_size_inches(12, 8)
        figure.canvas.draw()
        again = max(child.get_window_extent().width for child in artist._children if hasattr(child, "get_text")
                    and child.get_text())
        self.assertAlmostEqual(width, again, delta=1.0)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.project = opened(self.folder)

    def edit_b4(self, value="9"):
        for run in self.project.edit_cell("Misure", 3, 1, value) or ():
            pass
        calculate(self.project)

    def figure_texts(self, figure):
        return [child.get_text() for artist in figure.artists if isinstance(artist, lt.LinkedTableArtist)
                for child in artist._children if hasattr(child, "get_text") and child.get_text()]

    def test_the_slope_follows_the_data_and_the_copy_does_not(self):
        linked, copy = slope_record(self.project), slope_record(self.project, mode="copy")
        self.assertEqual(linked["source"]["rows"], ["Slope"])
        self.assertEqual(copy["values"]["cells"], [["2"]])
        put_on_graph(self.project, linked, copy)
        figure = self.project.runs[0].result.figure
        self.assertEqual(self.figure_texts(figure), ["2", "2"])
        self.edit_b4()
        figure = self.project.runs[0].result.figure          # the recalculation made a new figure
        self.assertEqual(self.figure_texts(figure), ["2.6", "2"])
        self.assertEqual(cells(self.project), [("graph", "linked", "ok", (("2.6",),)),
                                               ("graph", "copy", "ok", (("2",),))])

    def test_nothing_is_calculated_by_the_table(self):
        put_on_graph(self.project, slope_record(self.project))
        before = self.project.runs[0].result
        with patch("trama_qt.project.analyse", side_effect=AssertionError("a table ran an analysis")), \
                patch("trama_qt.project.compute", side_effect=AssertionError("a table ran an analysis")):
            self.project.update_linked_tables()
            self.project.table_specs(self.project.runs[0].style[lt.TABLES])
            self.project.linked_table_report()
        self.assertIs(self.project.runs[0].result, before)

    def test_a_graph_table_reaches_the_layout_and_every_export(self):
        put_on_graph(self.project, slope_record(self.project), slope_record(self.project, mode="copy",
                                                                            position=(.55, .3)))
        layout = replace(self.project.layouts[0], tables=[slope_record(self.project, position=(.05, .9))])
        self.project.put_layout(layout, 0)
        self.edit_b4()
        layout = self.project.layouts[0]
        figure = self.project.layout_figure(layout)
        page_tables = [a for a in figure.artists if isinstance(a, lt.LinkedTableArtist)]
        self.assertEqual(len(page_tables), 1)
        self.assertEqual([c.get_text() for c in page_tables[0]._children if hasattr(c, "get_text") and c.get_text()],
                         ["2.6"])
        out = self.folder
        self.project.export_layout(layout, out / "layout.png", {"format": "png", "dpi": 100})
        self.project.export_layout(layout, out / "layout.pdf", {"format": "pdf"})
        self.project.export_layout(layout, out / "layout.svg", {"format": "svg", "svg_text": "text"})
        pages = self.project.export_pdf_pages([("layout", 0), ("graph", 0)], out / "many.pdf", {"format": "pdf"},
                                              ["Layout", "Graph"])
        self.assertEqual(pages, 2)
        # Linked 2.6 and the copy 2 on the graph inside the layout, plus 2.6 on the page: the same everywhere.
        for path, page in ((out / "layout.pdf", 0), (out / "many.pdf", 0)):
            words = pdf_words(path, page)
            self.assertEqual(words.count("2.6"), 2, f"{path.name}: {words}")
            self.assertIn("Risultati", " ".join(words))
        graph_words = pdf_words(out / "many.pdf", 1)
        self.assertEqual(graph_words.count("2.6"), 1)
        root = ET.parse(out / "layout.svg").getroot()
        tables = [g for g in root.iter(SVG + "g") if (g.get("id") or "").startswith("panel1-tramastat-table-")]
        self.assertEqual(len(tables), 2)                         # the two tables of the graph, once each
        page = next(g for g in root.iter(SVG + "g") if g.get("id") == "layout-tables")
        self.assertEqual(["".join(t.itertext()) for t in page.iter(SVG + "text")], ["2.6"])
        self.assertEqual(sum(1 for t in root.iter(SVG + "text") if "".join(t.itertext()) == "2.6"), 2)
        self.assertTrue(list(page.iter(SVG + "path")), "the rules of the table are vectors")
        self.assertGreater((out / "layout.png").stat().st_size, 1000)

    def test_a_table_in_the_layout_space_changes_no_panel(self):
        without = self.project.layout_pdf_page(self.project.layouts[0])
        self.project.put_layout(replace(self.project.layouts[0], tables=[slope_record(self.project)]), 0)
        with_table = self.project.layout_pdf_page(self.project.layouts[0])
        self.assertEqual([p.box for p in without.placements], [p.box for p in with_table.placements])
        self.assertEqual(len(without.tables), 0)
        self.assertEqual(len(with_table.tables), 1)
        for run in self.project.runs:
            self.assertEqual(len(run.result.figure.artists), 0)

    def test_save_reopen_keeps_both_modes_and_the_identity_of_the_analysis(self):
        put_on_graph(self.project, slope_record(self.project), slope_record(self.project, mode="copy"))
        self.project.put_layout(replace(self.project.layouts[0], tables=[slope_record(self.project)]), 0)
        path = self.folder / "con-tabelle.alab"
        self.project.save(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["tables"][0]["analysis_ids"], {"0": self.project.runs[0].uid})
        self.assertEqual(len(document["layouts"][0]["tables"]), 1)
        again = opened(self.folder, path)
        self.assertEqual(again.runs[0].uid, self.project.runs[0].uid)
        self.assertEqual(cells(again), [("graph", "linked", "ok", (("2",),)), ("graph", "copy", "ok", (("2",),)),
                                        ("layout", "linked", "ok", (("2",),))])
        self.assertEqual(again.layouts[0].tables, self.project.layouts[0].tables)
        # Reopened, edited and recalculated: the linked tables move, the copy does not.
        for run in again.edit_cell("Misure", 3, 1, "9") or ():
            pass
        calculate(again)
        self.assertEqual([(m, c) for _, m, _, c in cells(again)],
                         [("linked", (("2.6",),)), ("copy", (("2",),)), ("linked", (("2.6",),))])

    def test_projects_without_tables_open_and_save_as_before(self):
        path = self.folder / "senza.alab"
        self.project.save(path)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("linked_tables", text)
        document = json.loads(text)
        self.assertNotIn("tables", document["layouts"][0])
        self.assertNotIn("analysis_ids", document["tables"][0])   # nothing is pinned without a linked table

    def test_a_removed_source_is_a_state_and_the_copy_is_intact(self):
        self.project.add_result(*self._second_analysis())
        run = self.project.runs[1]
        self.assertEqual(run.method, "Descriptive statistics")
        table = next(iter(run.result.tables))
        choice = next(c for c in self.project.table_source_choices()
                      if c["kind"] == "result" and c["analysis"] == run.uid and c["table"] == table)
        linked = self.project.table_record(choice, (0, 0, 0, 0), mode="linked")
        copy = self.project.table_record(choice, (0, 0, 0, 0), mode="copy", position=(.5, .5))
        put_on_graph(self.project, linked, copy, run=self.project.runs[0])
        self.assertEqual({state for _, _, state, _ in cells(self.project)}, {"ok"})
        value = cells(self.project)[0][3]
        # The analysis goes away, and a new one of the same kind takes its place: the table does not move to it.
        self.project.delete_sheet(("result", 1))
        self.assertEqual([(m, s) for _, m, s, _ in cells(self.project)], [("linked", "missing"), ("copy", "ok")])
        self.assertEqual(cells(self.project)[1][3], value)
        self.project.add_result(*self._second_analysis())
        self.assertNotEqual(self.project.runs[1].uid, run.uid)
        self.assertEqual([s for _, _, s, _ in cells(self.project)], ["missing", "ok"])
        texts = self.figure_texts(self.project.runs[0].result.figure)
        self.assertIn("Source not available", texts)
        # Save and reopen: the state is the same, the copy still holds its numbers.
        path = self.folder / "mancante.alab"
        self.project.save(path)
        again = opened(self.folder, path)
        self.assertEqual([(m, s) for _, m, s, _ in cells(again)], [("linked", "missing"), ("copy", "ok")])
        self.assertEqual(cells(again)[1][3], value)

    def _second_analysis(self):
        from trama_qt.project import Run
        run = Run("Descriptive statistics", "Misure", {"Variables": ["Risposta"]})
        frame = self.project.tables["Misure"].frame(mask_excluded=True)
        return run, compute(run, frame)

    def test_a_failed_calculation_is_an_explicit_state_and_recovers(self):
        put_on_graph(self.project, slope_record(self.project))
        self.project.runs[0].calculation_error = "The fit did not converge."
        self.project.update_linked_tables()
        self.assertEqual(cells(self.project)[0][2], "error")
        self.assertIn("Source has an error", self.figure_texts(self.project.runs[0].result.figure))
        self.project.runs[0].calculation_error = None
        self.project.update_linked_tables()
        self.assertEqual(cells(self.project)[0], ("graph", "linked", "ok", (("2",),)))

    def test_an_analysis_not_calculated_yet_is_pending(self):
        put_on_graph(self.project, slope_record(self.project))
        self.project.runs[0].result = None
        self.assertEqual(cells(self.project)[0][2], "pending")

    def test_worksheet_cells_follow_edits_row_changes_formats_and_renames(self):
        sheet = next(c for c in self.project.table_source_choices() if c["kind"] == "sheet")
        record = self.project.table_record(sheet, (1, 1, 2, 1), mode="linked", headers="column")
        self.assertEqual(record["source"]["rows"], ["base:2", "base:3"])
        put_on_graph(self.project, record)
        self.assertEqual(cells(self.project)[0][3], (("3",), ("5",)))
        self.project.edit_cell("Misure", 1, 1, "30")
        self.assertEqual(cells(self.project)[0][3], (("30",), ("5",)))
        self.project.insert_rows("Misure", 0, 2)               # two rows above: the table keeps its rows
        self.assertEqual(cells(self.project)[0][3], (("30",), ("5",)))
        self.project.set_table_number_format("Misure", ["Risposta"], {"mode": "fixed", "digits": 2})
        self.assertEqual(cells(self.project)[0][3], (("30.00",), ("5.00",)))
        self.project.rename_sheet(("data", "Misure"), "Prove")
        self.assertEqual(self.project.runs[0].style[lt.TABLES][0]["source"]["sheet"], "Prove")
        self.assertEqual(cells(self.project)[0][2], "ok")
        self.project.rename_column("Prove", 1, "Segnale")      # a renamed column is not guessed: explicit state
        self.assertEqual(cells(self.project)[0][2], "missing")
        self.project.undo()
        self.assertEqual(cells(self.project)[0][2], "ok")
        self.project.delete_rows("Prove", [3])                 # the row of the table (was row 2 + 2 inserted)
        self.assertEqual(cells(self.project)[0][2], "missing")
        self.project.undo()
        self.assertEqual(cells(self.project)[0][2], "ok")

    def test_links_follow_reordered_rows_but_never_reuse_a_deleted_sheet_name(self):
        project = self.project
        project.add_tables({"Fonte": pd.DataFrame({"Dato": [11, 22, 33]})})
        choice = next(choice for choice in project.table_source_choices() if choice.get("sheet") == "Fonte")
        linked = project.table_record(choice, (1, 0, 1, 0))
        copied = project.table_record(choice, (1, 0, 1, 0), mode="copy")
        put_on_graph(project, linked, copied)
        project.put_layout(replace(project.layouts[0], tables=[linked]), 0)
        project.move_rows("Fonte", 1, 2, 0)
        self.assertEqual([value for _, _, _, value in cells(project)], [(("22",),)] * 3)

        project.delete_sheet(("data", "Fonte"))
        project.add_tables({"Fonte": pd.DataFrame({"Dato": [101, 202, 303]})})
        expected = [("linked", "missing", ()), ("copy", "ok", (("22",),)), ("linked", "missing", ())]
        self.assertEqual([(mode, state, value) for _, mode, state, value in cells(project)], expected)
        project.undo()
        self.assertEqual([(mode, state, value) for _, mode, state, value in cells(project)], expected[:2])
        project.undo(redo=True)
        self.assertEqual([(mode, state, value) for _, mode, state, value in cells(project)], expected)
        saved = self.folder / "riusato.alab"
        project.save(saved)
        again = opened(self.folder, saved)
        self.assertEqual([(mode, state, value) for _, mode, state, value in cells(again)], expected)

    def test_a_malformed_table_in_a_file_makes_it_refuse_to_open(self):
        put_on_graph(self.project, slope_record(self.project))
        self.project.put_layout(replace(self.project.layouts[0], tables=[slope_record(self.project)]), 0)
        path = self.folder / "valida.alab"
        self.project.save(path)
        good = json.loads(path.read_text(encoding="utf-8"))

        def refused(change, name):
            document = deepcopy(good)
            change(document)
            broken = self.folder / name
            broken.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError, msg=name):
                Project().load(broken)

        refused(lambda d: d["tables"][0]["graph_styles"]["0"][lt.TABLES][0].update(position=[2, 0]), "posizione.alab")
        refused(lambda d: d["tables"][0]["graph_styles"]["0"][lt.TABLES][0].update(mode="live"), "modalita.alab")
        refused(lambda d: d["tables"][0]["graph_styles"]["0"][lt.TABLES][0].update(id="no"), "id.alab")
        refused(lambda d: d["layouts"][0]["tables"][0]["source"].update(rows=[f"base:{i}" for i in range(1, 99)])
                if d["layouts"][0]["tables"][0]["source"]["kind"] == "sheet"
                else d["layouts"][0]["tables"][0]["source"].update(rows=[str(i) for i in range(99)]), "righe.alab")
        refused(lambda d: d["layouts"][0].update(tables=d["layouts"][0]["tables"] * (lt.MAX_TABLES + 1)),
                "troppe.alab")
        refused(lambda d: d["layouts"][0]["tables"][0].update(extra=1), "chiave.alab")
        Project().load(path)    # the untouched file still opens

    def test_a_frozen_graph_cannot_get_new_tables_but_keeps_reading_its_sources(self):
        put_on_graph(self.project, slope_record(self.project))
        self.project.set_sheet_frozen(("graph", 0), True)
        self.assertIsNotNone(self.project.graph_format_problem(self.project.runs[0]))
        self.assertEqual(cells(self.project), [("graph", "linked", "ok", (("2",),))])
        self.project.set_sheet_frozen(("graph", 0), False)
        self.assertIsNone(self.project.graph_format_problem(self.project.runs[0]))

    def test_undo_and_redo_of_adding_formatting_and_removing(self):
        project = self.project
        run = project.runs[0]
        history = project.history

        def commit(records):
            style = deepcopy(run.style or {})
            before = deepcopy(style)
            style[lt.TABLES] = records
            if not records:
                style.pop(lt.TABLES)
            project.apply_format(run, style)
            history.record_style_batch("Linked tables", {run.uid: before}, {run.uid: deepcopy(style)})

        record = slope_record(project)
        commit([record])
        self.assertEqual(len(run.result.figure.artists), 1)
        commit([{**record, "size": 14.0, "grid": False}])
        self.assertEqual(run.style[lt.TABLES][0]["size"], 14.0)
        project.undo()
        self.assertEqual(run.style[lt.TABLES][0]["size"], 9.0)     # formatting is one undoable step
        project.undo()
        self.assertNotIn(lt.TABLES, run.style or {})
        self.assertEqual(len(run.result.figure.artists), 0)
        project.undo(redo=True)
        project.undo(redo=True)
        self.assertEqual(run.style[lt.TABLES][0]["size"], 14.0)
        commit([])                                             # removal is one undoable step too
        self.assertEqual(len(run.result.figure.artists), 0)
        project.undo()
        self.assertEqual(len(run.result.figure.artists), 1)
        layout = project.layouts[0]
        project.put_layout(replace(layout, tables=[slope_record(project)]), 0)
        project.undo()
        self.assertEqual(project.layouts[0].tables, [])
        project.undo(redo=True)
        self.assertEqual(len(project.layouts[0].tables), 1)

    def test_a_big_range_is_refused_before_a_cell_is_read(self):
        big = pd.DataFrame({"A": range(50000), "B": range(50000)})
        self.project.add_tables({"Grande": big})
        sheet = next(c for c in self.project.table_source_choices() if c.get("sheet") == "Grande")
        with patch.object(TableLookup, "sheet", side_effect=AssertionError("a cell was read")):
            with self.assertRaises(ValueError) as caught:
                self.project.table_record(sheet, (0, 0, 49999, 0))
            self.assertIn("up to 60 rows", str(caught.exception))
            with self.assertRaises(ValueError):
                self.project.table_record(sheet, (0, 0, 0, 40))
        record = self.project.table_record(sheet, (0, 0, 59, 1))
        self.assertEqual(len(record["source"]["rows"]), 60)

    def test_ambiguous_columns_and_empty_sources_cannot_be_picked(self):
        twin = pd.DataFrame([[1, 2, 3]], columns=["A", "A", "B"])
        self.project.add_tables({"Doppia": twin})
        sheet = next(c for c in self.project.table_source_choices() if c.get("sheet") == "Doppia")
        with self.assertRaises(ValueError):
            self.project.table_record(sheet, (0, 0, 0, 1))
        self.assertEqual(self.project.table_record(sheet, (0, 2, 0, 2))["source"]["columns"], ["B"])
        with self.assertRaises(ValueError):
            self.project.table_record(sheet, (0, 0, 5, 0))

    def test_duplicating_a_graph_copies_its_tables_deterministically(self):
        put_on_graph(self.project, slope_record(self.project))
        kind, index = self.project.duplicate_sheet(("graph", 0))
        twin = self.project.runs[index]
        self.assertEqual(twin.style[lt.TABLES], self.project.runs[0].style[lt.TABLES])
        self.assertIsNot(twin.style[lt.TABLES][0], self.project.runs[0].style[lt.TABLES][0])
        # Both read the analysis they were made for: the copy of the graph does not move the table to the copy.
        self.assertEqual(twin.style[lt.TABLES][0]["source"]["analysis"], self.project.runs[0].uid)

    def test_repeating_an_analysis_on_another_sheet_leaves_the_tables_behind(self):
        from analisi.repeat_analysis import remap_style
        put_on_graph(self.project, slope_record(self.project))
        self.assertNotIn(lt.TABLES, remap_style(self.project.runs[0].style, {}) or {})

    def test_templates_list_linked_tables_as_omitted_drawings(self):
        from analisi.analysis_templates import plan_template
        put_on_graph(self.project, slope_record(self.project))
        self.project.put_layout(replace(self.project.layouts[0], tables=[slope_record(self.project)]), 0)
        plan = plan_template(self.project.tables, self.project.layouts, ())
        codes = [(o.code, o.count) for o in plan.omissions]
        self.assertIn(("linked_tables", 1), codes)
        self.assertEqual(sum(1 for code, _ in codes if code == "linked_tables"), 2)
        self.assertIsNotNone(plan.template)
        for spec in plan.template.tables:
            for analysis in spec.analyses:
                self.assertNotIn(lt.TABLES, analysis.style or {})

    def test_a_family_copy_reads_the_copies_made_with_it(self):
        from analisi.family_workflow import duplicate_family, plan_family
        put_on_graph(self.project, slope_record(self.project))
        self.project.put_layout(replace(self.project.layouts[0], tables=[slope_record(self.project)]), 0)
        self.project.sync_links(persist=True)
        bundle = duplicate_family(self.project.tables, self.project.layouts, tuple(self.project.info_sheets.values()),
                                  ("data", "Misure"), name="Copia")
        title = bundle.table_names["Misure"]
        new = bundle.tables[title]
        copied_style = next(iter(new.graph_styles.values()))
        self.assertEqual(copied_style[lt.TABLES][0]["source"]["analysis"], next(iter(new.analysis_ids.values())))
        self.assertNotEqual(copied_style[lt.TABLES][0]["source"]["analysis"], self.project.runs[0].uid)
        self.assertEqual(bundle.layouts[0].tables[0]["source"]["analysis"], next(iter(new.analysis_ids.values())))


if __name__ == "__main__":
    unittest.main()
