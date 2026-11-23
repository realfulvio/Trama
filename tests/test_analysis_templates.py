"""Analysis templates (``analisi.analysis_templates``): metadata only, strict reading, mapping and new identities.

No Qt. The fixtures in ``tests/data/qt_templates`` are those of the package: the original project holds the
sentinel ``SOLO_ORIGINALE_Ω`` in a raw text column, the new data give slopes 6, 3 and 5.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import pandas as pd

from analisi.analysis_chain import ChainCancelled, ResultSource
from analisi.analysis_templates import (SCHEMA, TemplateError, default_mapping, ignored_columns,
                                        instantiate_template, mapping_problems, plan_template, read_template,
                                        template_payload, write_template)
from analisi.data import Dataset, load_tables, load_workspace, save_project
from analisi.i18n import active_language, set_language
from analisi.info import InfoSheet
from analisi.presentation import Layout

DATA = Path(__file__).resolve().parent / "data" / "qt_templates"
SENTINEL = "SOLO_ORIGINALE_Ω"
SHAPE = {"id": "a0000000-0000-4000-8000-000000000001", "kind": "line", "units": "axes",
         "points": [[.1, .1], [.2, .2]]}
NOTE = {"text": "n", "position": [.5, .5], "units": "axes", "align": "left", "size": 9, "color": "#000000"}


def example():
    tables, layouts = load_workspace(DATA / "progetto-originale.alab")
    sources = {"Campioni nuovi": next(iter(load_tables(DATA / "nuova-calibrazione.csv").values())),
               "Controlli nuovi": next(iter(load_tables(DATA / "nuovo-controllo.csv").values()))}
    mapping = {name: (source, columns) for name, (source, columns)
               in json.loads((DATA / "mappatura.json").read_text(encoding="utf-8")).items()}
    return tables, layouts, sources, mapping


def slopes(tables):
    from trama_qt.project import Project
    project = Project()
    project.tables = tables
    project.runs = [run for title, dataset in tables.items() for run in Project.runs_for(title, dataset)]
    job = project.plan_refresh(project.runs)
    errors = project.apply_refresh(job, project.run_refresh(job))
    return errors, [round(float(run.result.tables["Regression"].loc["Slope", "Value"]), 9)
                    for run in project.runs if run.method == "Linear regression" and run.result is not None]


class TemplateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.tables, self.layouts, self.sources, self.mapping = example()

    def write(self, tables=None, layouts=None, name="procedura.tramatpl", **options):
        path = self.folder / name
        write_template(path, self.tables if tables is None else tables,
                       layouts=self.layouts if layouts is None else layouts, **options)
        return path

    def payload(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def refused(self, path, text, code=None):
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(TemplateError) as caught:
            read_template(path)
        if code is not None:
            self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(caught.exception.field, "file")
        return caught.exception


class WriteTests(TemplateTestCase):
    def test_only_metadata_travels_and_the_project_is_untouched(self):
        before = self.folder / "before.alab"
        save_project(before, self.tables, layouts=self.layouts)
        path = self.write()
        after = self.folder / "after.alab"
        save_project(after, self.tables, layouts=self.layouts)
        self.assertEqual(before.read_bytes(), after.read_bytes())  # Nothing of the project changed.
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
        self.assertIs(type(payload["schema"]), int)
        self.assertEqual(payload["schema"], SCHEMA)
        self.assertNotIn(SENTINEL, text)
        for key in ("rows", "excluded", "info_sheets", "results", "path", "history", "attrs"):
            self.assertNotIn(f'"{key}"', text)
        first = payload["tables"][0]
        self.assertEqual([column["name"] for column in first["columns"]], ["X", "Y", "Badge"])
        self.assertEqual([column["kind"] for column in first["columns"]], ["numeric", "numeric", "text"])
        self.assertEqual(first["formulas"], [["Scaled", "=2*Y+1"]])
        ids = [analysis["id"] for table in payload["tables"] for analysis in table["analyses"]]
        self.assertEqual(ids, ["A1", "A2", "A3", "A4", "A5"])  # Local, never the project's identities.
        self.assertNotIn("00000000-0000-0000-0000-00000000000", text)
        self.assertEqual(first["analyses"][2]["source"], {"id": "A2", "table": "Normalized"})
        self.assertEqual(payload["layouts"][0]["panels"], ["A3", "A5"])

    def test_size_of_the_template_does_not_depend_on_the_rows(self):
        small = self.write(name="small.tramatpl")
        tables = deepcopy(self.tables)
        big = pd.DataFrame({"X": range(50_000), "Y": range(50_000),
                            "Badge": pd.Series(["b"] * 50_000, dtype="string")})
        tables["Analisi α"] = Dataset(big, formulas=dict(tables["Analisi α"].formulas),
                                      analyses=deepcopy(tables["Analisi α"].analyses),
                                      graph_styles=deepcopy(tables["Analisi α"].graph_styles),
                                      analysis_ids=dict(tables["Analisi α"].analysis_ids),
                                      analysis_sources=dict(tables["Analisi α"].analysis_sources),
                                      analysis_labels=dict(tables["Analisi α"].analysis_labels))
        large = self.write(tables, name="large.tramatpl")
        self.assertEqual(small.read_bytes(), large.read_bytes())
        self.assertEqual(plan_template(tables, self.layouts).rows, 50_004)

    def test_the_file_does_not_depend_on_the_language(self):
        previous = active_language()
        self.addCleanup(set_language, previous)
        set_language("en")
        english = self.write(name="en.tramatpl").read_bytes()
        set_language("it")
        self.assertEqual(self.write(name="it.tramatpl").read_bytes(), english)

    def test_the_open_project_cannot_be_replaced_even_through_a_link(self):
        project = self.folder / "Progetto.alab"
        save_project(project, self.tables, layouts=self.layouts)
        original = project.read_bytes()
        alias = self.folder / "alias.tramatpl"
        try:
            alias.symlink_to(project)
        except OSError:
            self.skipTest("symbolic links are not available")
        with self.assertRaises(TemplateError) as caught:
            write_template(alias, self.tables, layouts=self.layouts, source_path=project)
        self.assertEqual((caught.exception.code, caught.exception.field), ("current-path", "file"))
        self.assertEqual(project.read_bytes(), original)
        with self.assertRaises(TemplateError) as caught:
            write_template(self.folder / "Progetto.alab", self.tables)
        self.assertEqual(caught.exception.code, "file-name")

    def test_a_refused_template_keeps_the_existing_file(self):
        path = self.write()
        good = path.read_bytes()
        tables = deepcopy(self.tables)
        tables["Analisi α"].formulas["Scaled2"] = '=Y*INFO("k")'
        with self.assertRaises(TemplateError) as caught:
            write_template(path, tables, layouts=self.layouts)
        self.assertEqual(caught.exception.code, "blocked")
        self.assertEqual(caught.exception.problems[0].place, ("formula", "Analisi α", "Scaled2"))
        self.assertEqual(path.read_bytes(), good)
        self.assertEqual([p.name for p in self.folder.iterdir() if p.name.startswith(".tramatpl-")], [])

    def test_info_sheets_shapes_and_annotations_are_left_out_and_listed(self):
        tables = deepcopy(self.tables)
        tables["Analisi α"].graph_styles[2] = {**tables["Analisi α"].graph_styles[2], "shapes": [SHAPE],
                                               "annotations": [NOTE, NOTE]}
        info = InfoSheet("Note", (("operatore", "Mario"),), table="Analisi α")
        plan = plan_template(tables, self.layouts, (info,))
        self.assertTrue(plan.ok)
        codes = {(omission.code, omission.place, omission.count) for omission in plan.omissions}
        self.assertIn(("info-sheets", ("project",), 1), codes)
        self.assertIn(("shapes", ("analysis", "Analisi α", 2), 1), codes)
        self.assertIn(("annotations", ("analysis", "Analisi α", 2), 2), codes)
        self.assertIn(("excluded", ("table", "Analisi α"), 1), codes)
        path = self.write(tables, info_sheets=(info,))
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Mario", text)
        self.assertNotIn('"shapes"', text)
        self.assertNotIn('"annotations"', text)
        self.assertIn("Controllo $ α", text)  # The rest of the graph format travels.
        self.assertEqual(tables["Analisi α"].graph_styles[2]["shapes"], [SHAPE])  # The source keeps them.

    def test_out_of_scope_items_are_refused_with_their_place(self):
        from analisi.legacy_restore import LEGACY_GRAPH_LINK, SAVED_BINARY_GRAPH
        tables = deepcopy(self.tables)
        tables["Controllo"].analyses.append((SAVED_BINARY_GRAPH, {}))
        tables["Analisi α"].analyses[3] = ("Linear regression", {"X": "X", "Y": "Y", LEGACY_GRAPH_LINK: "x:1"})
        tables["Analisi α"].analyses.append(("Linear regression", {"X": "X", "Y": "Missing"}))
        layouts = [*self.layouts, Layout("Imported", 1, [("Controllo", 1)])]
        plan = plan_template(tables, layouts)
        found = {(problem.code, problem.place) for problem in plan.problems}
        self.assertIn(("imported-analysis", ("analysis", "Controllo", 1)), found)
        self.assertIn(("imported-analysis", ("analysis", "Analisi α", 3)), found)
        self.assertIn(("missing-column", ("analysis", "Analisi α", 4)), found)
        self.assertIn(("imported-layout", ("layout", 1)), found)
        self.assertIsNone(plan.template)

    def test_broken_links_and_imported_tables_are_refused(self):
        tables = deepcopy(self.tables)
        tables["Analisi α"].analysis_sources[3] = ResultSource("12345678-1234-4234-8234-123456789012", "Gone")
        tables["Controllo"].table_format = "Imported editable XY"
        layouts = [Layout("Broken", 1, [("Controllo", 9)])]
        found = {(problem.code, problem.place) for problem in plan_template(tables, layouts).problems}
        self.assertIn(("broken-source", ("analysis", "Analisi α", 3)), found)
        self.assertIn(("imported-table", ("table", "Controllo")), found)
        self.assertIn(("broken-layout", ("layout", 0)), found)
        self.assertIn(("empty", ("project",)), {(p.code, p.place) for p in plan_template({}).problems})


class ReadTests(TemplateTestCase):
    def test_reading_calculates_nothing_and_reads_only_the_file(self):
        path = self.write()
        with mock.patch("analisi.workbench.analyse", side_effect=AssertionError("calculated")), \
                mock.patch("analisi.data.load_tables", side_effect=AssertionError("other file")):
            template = read_template(path)
        self.assertEqual(template.table_names, ("Analisi α", "Controllo"))
        self.assertEqual(template.analysis_count, 5)
        self.assertEqual(template.link_count, 2)
        self.assertEqual(template_payload(template), self.payload(path))

    def test_damaged_files_are_refused(self):
        path = self.write()
        good = path.read_text(encoding="utf-8")
        payload = json.loads(good)
        target = self.folder / "bad.tramatpl"
        self.refused(target, "not json", "json")
        self.refused(target, "[1, 2]", "json")
        self.refused(target, json.dumps({**payload, "schema": 999}), "schema")
        self.refused(target, json.dumps({**payload, "schema": "1"}), "schema")
        self.refused(target, json.dumps({**payload, "schema": True}), "schema")
        self.refused(target, good.replace("{", '{"schema":1,', 1), "duplicate-key")
        self.refused(target, json.dumps({**payload, "extra": 1}), "unknown-field")
        self.refused(target, json.dumps({**payload, "kind": "something else"}), "json")
        self.refused(target, good.replace('"Scaled"', '"X"', 1), "duplicate-column")
        self.refused(target, good.replace('"Transform"', '"No such analysis"', 1), "unknown-method")
        self.refused(target, good.replace('"=2*Y+1"', '"=Y*INFO(\\"k\\")"', 1), "info-formula")
        self.refused(target, good.replace('"=2*Y+1"', '"=2*(Y"', 1), "formula")
        nan = deepcopy(payload)
        nan["tables"][0]["analyses"][3]["options"]["Confidence level (%)"] = 1.0
        self.refused(target, json.dumps(nan).replace("1.0", "NaN"), "number")

    def test_wrong_types_and_missing_or_cyclic_references_are_refused(self):
        payload = self.payload(self.write())
        target = self.folder / "bad.tramatpl"

        def changed(change):
            copy = deepcopy(payload)
            change(copy)
            return json.dumps(copy)

        def cycle(copy):
            copy["tables"][0]["analyses"][0]["source"] = {"id": "A2", "table": "Normalized"}

        self.refused(target, changed(cycle))
        self.refused(target, changed(lambda c: c["tables"][0]["analyses"][1].update(
            source={"id": "A9", "table": "x"})), "missing-reference")
        self.refused(target, changed(lambda c: c["layouts"][0].update(panels=["A9"])), "missing-reference")
        self.refused(target, changed(lambda c: c["tables"][0]["analyses"][0].update(id="B1")), "type")
        self.refused(target, changed(lambda c: c["tables"][1]["analyses"][0].update(id="A1")), "duplicate-id")
        self.refused(target, changed(lambda c: c["tables"][0]["columns"][0].update(kind="date")), "type")
        self.refused(target, changed(lambda c: c["tables"][0].update(columns="X")), "type")
        self.refused(target, changed(lambda c: c["tables"][0]["analyses"][3].update(options=[1])),
                     "invalid-options")
        self.refused(target, changed(lambda c: c["tables"][0]["analyses"][3]["options"].update(Y="Missing")),
                     "missing-column")
        self.refused(target, changed(lambda c: c["tables"][0]["analyses"][2].update(
            style={"shapes": [SHAPE]})), "type")
        self.refused(target, changed(lambda c: c["tables"][0].update(format="Imported editable XY")), "imported-table")
        self.refused(target, changed(lambda c: c["tables"].append(deepcopy(c["tables"][1]))), "duplicate-table")
        self.refused(target, changed(lambda c: c.update(tables=[])))

    def test_a_template_that_is_too_large_is_refused_before_reading(self):
        path = self.write()
        with mock.patch("analisi.analysis_templates.MAX_TEMPLATE_BYTES", 100), \
                mock.patch.object(Path, "open", side_effect=AssertionError("read")):
            with self.assertRaises(TemplateError) as caught:
                read_template(path)
        self.assertEqual(caught.exception.code, "too-large")
        with self.assertRaises(TemplateError) as caught:
            read_template(self.folder / "missing.tramatpl")
        self.assertEqual(caught.exception.code, "io")


class ApplyTests(TemplateTestCase):
    def test_new_data_under_canonical_names_with_new_identities(self):
        template = read_template(self.write())
        frozen = deepcopy(template)
        sources = deepcopy(self.sources)
        tables, layouts = instantiate_template(template, sources, self.mapping)
        self.assertEqual(template, frozen)
        for name, frame in sources.items():
            pd.testing.assert_frame_equal(frame, self.sources[name])
        first = tables["Analisi α"]
        self.assertEqual(list(first.raw.columns), ["X", "Y", "Badge"])
        self.assertEqual(list(first.raw["Badge"]), ["0003", "0004", "0005", "0006"])
        self.assertEqual(list(first.frame()["Scaled"]), [11, 17, 23, 29])
        self.assertEqual((first.excluded, first.analysis_labels), (set(), {2: "Curva corretta $"}))
        self.assertEqual(first.analysis_sources[2].analysis_id, first.analysis_ids[1])
        self.assertEqual(layouts[0].panels, [("Analisi α", 2), ("Controllo", 0)])
        self.assertEqual(slopes(tables), ([], [6.0, 3.0, 5.0]))
        again, _ = instantiate_template(template, sources, self.mapping)
        ids = lambda result: {uid for table in result.values() for uid in table.analysis_ids.values()}  # noqa: E731
        original = ids(self.tables)
        self.assertEqual(len(ids(tables)), 5)
        self.assertFalse(ids(tables) & ids(again) or ids(tables) & original or ids(again) & original)
        avoided, _ = instantiate_template(template, sources, self.mapping, avoid=ids(tables))
        self.assertFalse(ids(avoided) & ids(tables))

    def test_saved_and_reopened_gives_the_same_new_results(self):
        template = read_template(self.write())
        tables, layouts = instantiate_template(template, self.sources, self.mapping)
        path = self.folder / "Istanza.alab"
        save_project(path, tables, layouts=layouts)
        reopened, reopened_layouts = load_workspace(path)
        self.assertEqual(slopes(reopened), ([], [6.0, 3.0, 5.0]))
        self.assertEqual(reopened_layouts[0].panels, [("Analisi α", 2), ("Controllo", 0)])

    def test_different_row_counts_and_column_order(self):
        template = read_template(self.write())
        sources = {"A": pd.DataFrame({"z": ["x"] * 6, "b": [1, 2, 3, 4, 5, 6], "a": [2.0, 4, 6, 8, 10, 12],
                                      "id": pd.Series(list("pqrstu"), dtype="string")}),
                   "B": pd.DataFrame({"s": [1, 2], "t": [1, 2]}, index=[7, 9])}
        mapping = {"Analisi α": ("A", {"X": "b", "Y": "a", "Badge": "id"}), "Controllo": ("B", {"Time": "s",
                                                                                              "Signal": "t"})}
        tables, _ = instantiate_template(template, sources, mapping)
        self.assertEqual(len(tables["Analisi α"].raw), 6)
        self.assertEqual(list(tables["Controllo"].raw.index), [0, 1])  # New rows from 0.
        self.assertEqual(ignored_columns(template, sources, mapping), {"Analisi α": ["z"], "Controllo": []})
        numbers = {"A": sources["A"].assign(b=["1", "2", "3", "4", "5", "6"]), "B": sources["B"]}
        converted, _ = instantiate_template(template, numbers, mapping)
        self.assertTrue(pd.api.types.is_numeric_dtype(converted["Analisi α"].raw["X"]))
        badges = {"A": sources["A"].assign(id=[3, 4, 5, 6, 7, 8]), "B": sources["B"]}
        texts, _ = instantiate_template(template, badges, mapping)
        self.assertEqual(list(texts["Analisi α"].raw["Badge"]), ["3", "4", "5", "6", "7", "8"])

    def test_incomplete_or_ambiguous_mappings_are_refused(self):
        template = read_template(self.write())
        cases = {
            "duplicate": {"X": "Dose", "Y": "Dose", "Badge": "Campione"},
            "unmapped": {"X": "Dose", "Badge": "Campione"},
            "missing-column": {"X": "Dose", "Y": "Mancante", "Badge": "Campione"},
            "not-numeric": {"X": "Dose", "Y": "Extra", "Badge": "Campione"},
            "unknown-column": {"X": "Dose", "Y": "Segnale (mV)", "Badge": "Campione", "Scaled": "Extra"},
        }
        for code, columns in cases.items():
            with self.subTest(code=code):
                mapping = {**self.mapping, "Analisi α": ("Campioni nuovi", columns)}
                with self.assertRaises(TemplateError) as caught:
                    instantiate_template(template, self.sources, mapping)
                self.assertIn(code, {problem.code for problem in caught.exception.problems})
                self.assertIsInstance(caught.exception, ValueError)
        with self.assertRaises(TemplateError) as caught:
            instantiate_template(template, self.sources, {"Analisi α": self.mapping["Analisi α"]})
        self.assertEqual((caught.exception.code, caught.exception.field), ("no-source", "Controllo"))
        with self.assertRaises(TemplateError) as caught:
            instantiate_template(template, self.sources, {**self.mapping, "Altro": self.mapping["Controllo"]})
        self.assertEqual(caught.exception.code, "unknown-table")
        with self.assertRaises(TemplateError):
            instantiate_template(template, {}, self.mapping)
        problems = mapping_problems(template, self.sources, {**self.mapping, "Analisi α": (
            "Campioni nuovi", {"X": "Dose", "Y": "Dose", "Badge": "Campione"})})
        self.assertEqual({problem.field for problem in problems}, {("Analisi α", "X"), ("Analisi α", "Y")})

    def test_proposals_use_only_exact_unique_names(self):
        template = read_template(self.write())
        sources = {"Analisi α": pd.DataFrame({"X": [1], "y": [2], "Badge": ["a"]}),
                   "Controllo ": pd.DataFrame({"Time": [1], "Signal": [2]})}
        proposal = default_mapping(template, sources)
        self.assertEqual(proposal["Analisi α"], ("Analisi α", {"X": "X", "Badge": "Badge"}))  # Not "y" for Y.
        self.assertEqual(proposal["Controllo"], (None, {}))  # A trailing space is another name.

    def test_cancel_stops_the_build(self):
        template = read_template(self.write())
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ChainCancelled):
            instantiate_template(template, self.sources, self.mapping, cancel=cancel)

    def test_a_methodological_error_is_reported_by_the_calculation_not_hidden(self):
        template = read_template(self.write())
        flat = {**self.sources, "Campioni nuovi": self.sources["Campioni nuovi"].assign(Dose=[1, 1, 1, 1])}
        tables, _ = instantiate_template(template, flat, self.mapping)
        errors, values = slopes(tables)
        self.assertTrue(errors)
        self.assertEqual(values, [5.0])  # Only the other table has a result; nothing old is shown.


if __name__ == "__main__":
    unittest.main()
