"""Worksheets linked to a CSV or TSV file (analisi.source_link and the Project commands that apply it): the three-way
comparison, keys, conflicts, rows without a key, the saved record, Undo/Redo, what follows a row identity, and that
the source file is only read. The Qt window is tested in test_qt_source_link.py."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from analisi import source_link as engine
from analisi.source_link import (ADDED, CONFLICT, LOCAL, MODIFIED, REMOVED, UNCHANGED, LinkSpec, UpdateCancelled,
                                 column_sources, link_record, read_link_record)
from analisi.text_import import ImportOptions, TextImport, read_text_bytes

DATA = Path(__file__).resolve().parent / "data" / "source_link"
CASES = json.loads((DATA / "casi.json").read_text(encoding="utf-8"))


def _project():
    from trama_qt.project import Project
    return Project()


def link_file(path, *, key="ID", options=ImportOptions(), project=None):
    """Import ``path`` into a new worksheet linked to it, as the import dialog does."""
    data, content = read_text_bytes(path)
    text = TextImport.parse(content, path.suffix.lower(), "Automatic")
    frame = text.table(options)
    sources = column_sources(text, options, text.plan(options).columns)
    spec = LinkSpec(path, len(data), hashlib.sha256(data).hexdigest(), text.delimiter, options, sources, key)
    project = project or _project()
    title = project.add_tables({path.stem: frame})[0]
    project.attach_source(title, spec)
    return project, title


def plan_for(project, title, path=None):
    dataset = project.tables[title]
    raw, excluded = project.source_sheet(title)
    return engine.plan_update(dataset.source_link, raw, excluded, path or Path(dataset.source_link.path))


def slope(frame):
    return float(np.polyfit(frame["X"].astype(float), frame["Y"].astype(float), 1)[0])


def column(project, title, name):
    return project.tables[title].raw[name].tolist()


class SourceLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def write(self, name, text):
        path = self.folder / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def copy(self, fixture, name="dati.csv"):
        target = self.folder / name
        shutil.copyfile(DATA / fixture, target)
        return target

    # -- the case of the package: reorder, one modified row, one added row -------------------------------------
    def test_update_reorders_modifies_adds_then_undo_and_redo(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        self.assertAlmostEqual(slope(project.tables[title].frame()), CASES["initial_slope"], places=12)
        self.copy("aggiornato.csv")
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.count(ADDED), 1)
        self.assertEqual(plan.count(MODIFIED), 1)
        self.assertEqual(plan.count(UNCHANGED), 2)
        self.assertEqual(plan.removed, [])
        self.assertEqual(plan.conflicts, 0)
        self.assertTrue(plan.reordered())
        self.assertEqual([plan.frame["ID"][row] for row in sorted(plan.moved())], ["C"])
        self.assertIsNone(engine.can_apply(plan))
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "ID"), CASES["updated_order"])
        self.assertAlmostEqual(slope(project.tables[title].frame()), CASES["updated_slope"], places=12)
        self.assertEqual(project.tables[title].source_link.sha256, plan.sha256)
        project.undo()
        self.assertEqual(column(project, title, "ID"), ["A", "B", "C"])
        self.assertEqual(column(project, title, "Y"), [3, 5, 7])
        self.assertAlmostEqual(slope(project.tables[title].frame()), CASES["initial_slope"], places=12)
        self.assertNotEqual(project.tables[title].source_link.sha256, plan.sha256)
        project.undo(redo=True)
        self.assertEqual(column(project, title, "ID"), CASES["updated_order"])
        self.assertAlmostEqual(slope(project.tables[title].frame()), CASES["updated_slope"], places=12)
        # The same file again: nothing to change.
        again = plan_for(project, title)
        self.assertTrue(again.unchanged_file)
        self.assertEqual(again.count(UNCHANGED), 4)
        self.assertIsNone(project.update_from_source(title, again))

    def test_style_and_exclusion_follow_the_key_after_a_reorder(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.set_table_background(title, (1, 0, 1, 2), "#ffcc00")  # Row of B.
        project.toggle_exclusion(title, [(1, 2)])  # Y of B.
        self.copy("aggiornato.csv")
        project.update_from_source(title, plan_for(project, title))
        dataset = project.tables[title]
        row_b = column(project, title, "ID").index("B")
        self.assertEqual(row_b, 2)
        self.assertEqual(dataset.excluded, {(row_b, 2)})
        self.assertEqual({row for row, _ in dataset.cell_backgrounds}, {row_b})
        project.undo()
        self.assertEqual(project.tables[title].excluded, {(1, 2)})
        self.assertEqual({row for row, _ in project.tables[title].cell_backgrounds}, {1})

    def test_duplicate_keys_block_the_update_and_change_nothing(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        before = project.tables[title].raw.copy()
        link = project.tables[title].source_link
        self.copy("duplicato.csv")
        plan = plan_for(project, title)
        self.assertTrue(plan.blocked)
        self.assertEqual([str(problem) for problem in plan.problems], ["The key column ID repeats B."])
        self.assertIsNotNone(engine.can_apply(plan))
        self.assertTrue(project.tables[title].raw.equals(before))
        self.assertIs(project.tables[title].source_link, link)

    def test_empty_key_and_missing_column_are_problems(self):
        path = self.write("dati.csv", "ID,X,Y\nA,1,3\nB,2,5\n")
        project, title = link_file(path)
        self.write("dati.csv", "ID,X,Y\nA,1,3\n,2,5\n")
        self.assertEqual([str(item) for item in plan_for(project, title).problems],
                         ["The key column ID is empty in row(s) 2."])
        self.write("dati.csv", "ID,X,Z\nA,1,3\nB,2,5\n")
        self.assertEqual([str(item) for item in plan_for(project, title).problems],
                         ["The file no longer has the column Y."])
        self.write("dati.csv", "ID,X,Y\nA,1,3\nB,due,5\n")
        self.assertEqual([str(item) for item in plan_for(project, title).problems],
                         ["The column X now holds text in the file (row 2: due)."])

    def test_a_row_changed_in_both_needs_a_decision(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.edit_cell(title, 1, 2, "6")  # B: 5 → 6 in the project.
        project.edit_cell(title, 0, 2, "4")  # A: 3 → 4 in the project only.
        self.copy("aggiornato.csv")  # B: 5 → 9 in the file.
        plan = plan_for(project, title)
        self.assertEqual(plan.count(CONFLICT), 1)
        self.assertEqual(plan.count(LOCAL), 1)
        self.assertEqual(engine.can_apply(plan).template,
                         "Choose how to treat the rows changed both in the project and in the file.")
        self.assertIsNone(engine.can_apply(plan, choice="project"))
        project.update_from_source(title, plan, choice="project")
        values = dict(zip(column(project, title, "ID"), column(project, title, "Y")))
        self.assertEqual(values, {"C": 7, "A": 4, "B": 6, "D": 11})
        project.undo()
        project.update_from_source(title, plan_for(project, title), choice="file")
        values = dict(zip(column(project, title, "ID"), column(project, title, "Y")))
        self.assertEqual(values, {"C": 7, "A": 4, "B": 9, "D": 11})  # A keeps the project edit: not a conflict.
        # Now the project and the confirmed version agree: no conflict is left.
        self.assertEqual(plan_for(project, title).conflicts, 0)

    def test_rows_added_or_deleted_in_the_project(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.insert_rows(title, 3)
        project.edit_cell(title, 3, 0, "P")
        project.edit_cell(title, 3, 1, "9")
        project.delete_rows(title, [0])  # A deleted in the project.
        self.copy("aggiornato.csv")
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "ID"), ["C", "B", "D", "P"])

    def test_removed_rows_and_what_they_take(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.toggle_exclusion(title, [(2, 1)])  # X of C.
        self.write("dati.csv", "ID,X,Y\nA,1,3\nB,2,5\n")
        plan = plan_for(project, title)
        self.assertEqual(plan.removed, [(2, REMOVED)])
        self.assertEqual(project.source_references(title, [2]), {"excluded": 1})
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "ID"), ["A", "B"])
        self.assertEqual(project.tables[title].excluded, set())
        project.undo()
        self.assertEqual(project.tables[title].excluded, {(2, 1)})

    def test_without_a_key_rows_are_matched_only_when_provable(self):
        path = self.write("misure.csv", "X,Y\n1,3\n2,5\n3,7\n")
        project, title = link_file(path, key=None)
        project.toggle_exclusion(title, [(1, 1)])
        self.write("misure.csv", "X,Y\n1,3\n2,5\n3,7\n4,9\n")  # Rows appended: provable.
        plan = plan_for(project, title)
        self.assertIsNone(plan.identity_problem)
        self.assertEqual(plan.count(ADDED), 1)
        project.update_from_source(title, plan)
        self.assertEqual(project.tables[title].excluded, {(1, 1)})
        self.write("misure.csv", "X,Y\n1,3\n2,6\n3,7\n4,9\n")  # A value changed: identity not provable.
        plan = plan_for(project, title)
        self.assertIsNotNone(plan.identity_problem)
        self.assertIsNotNone(engine.can_apply(plan))
        self.assertIsNone(engine.can_apply(plan, replace_rows=True))
        self.assertEqual(project.source_references(title, range(4)), {"excluded": 1})
        project.update_from_source(title, plan, replace_rows=True)
        self.assertEqual(column(project, title, "Y"), [3, 6, 7, 9])
        self.assertEqual(project.tables[title].excluded, set())

    def test_change_source_links_new_columns_by_name(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        wider = self.write("wider.csv", "ID,X,Y,Peso\nA,1,3,10\nB,2,5,20\nC,3,7,30\n")
        data, content = read_text_bytes(wider)
        text = TextImport.parse(content, ".csv", "Automatic")
        options = ImportOptions()
        selection = text.plan(options)
        relink = engine.Relink(text.delimiter, options, column_sources(text, options, selection.columns),
                               ("ID", "X", "Y", "Peso"), "ID")
        raw, excluded = project.source_sheet(title)
        plan = engine.plan_update(project.tables[title].source_link, raw, excluded, wider, relink=relink)
        self.assertEqual(plan.new_columns, ["Peso"])
        self.assertEqual(plan.count(UNCHANGED), 3)
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "Peso"), [10, 20, 30])
        self.assertEqual(Path(project.tables[title].source_link.path).name, "wider.csv")

    def test_trailing_asterisk_marks_follow_the_file(self):
        options = ImportOptions(mark_excluded=True)
        path = self.write("dati.csv", "ID,X,Y\nA,1,3\nB,2,5*\nC,3,7\n")
        project, title = link_file(path, options=options)
        self.assertEqual(project.tables[title].excluded, {(1, 2)})
        self.write("dati.csv", "ID,X,Y\nA,1,3*\nB,2,5\nC,3,7\n")
        plan = plan_for(project, title)
        self.assertEqual(plan.count(MODIFIED), 2)
        project.update_from_source(title, plan)
        self.assertEqual(project.tables[title].excluded, {(0, 2)})

    def test_tsv_with_quoted_fields_and_accents(self):
        path = self.write("città.tsv", 'Codice\t"Città"\tValore\n'
                                       'é1\t"Forlì\tCesena"\t1,5\n'
                                       'é2\t"Sant\'Agata ""sul"" Santerno"\t2,5\n')
        options = ImportOptions(decimal="Comma")
        project, title = link_file(path, key="Codice", options=options)
        link = project.tables[title].source_link
        self.assertEqual(link.delimiter, "\t")
        self.assertEqual(column(project, title, "Città"), ["Forlì\tCesena", 'Sant\'Agata "sul" Santerno'])
        self.write("città.tsv", 'Codice\t"Città"\tValore\n'
                                'é2\t"Sant\'Agata ""sul"" Santerno"\t2,75\n'
                                'é1\t"Forlì\tCesena"\t1,5\n')
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "Codice"), ["é2", "é1"])
        self.assertEqual(column(project, title, "Valore"), [2.75, 1.5])

    def test_cancel_while_reading_changes_nothing(self):
        path = self.write("grande.csv", "ID,X\n" + "".join(f"K{row},{row}\n" for row in range(20000)))
        project, title = link_file(path)
        raw, excluded = project.source_sheet(title)
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 2

        with self.assertRaises(UpdateCancelled):
            engine.plan_update(project.tables[title].source_link, raw, excluded, path, cancel=cancel)
        self.assertIs(project.tables[title].raw, raw)

    def test_a_file_that_settles_is_read_again_and_a_touched_file_is_the_same(self):
        from unittest import mock
        path = self.copy("iniziale.csv")
        original, calls = engine._read_once, []

        def unsettled(*args):
            calls.append(1)
            return None if len(calls) == 1 else original(*args)

        with mock.patch.object(engine, "_read_once", unsettled):
            source = engine.read_file(path)
        self.assertEqual(len(calls), 2)
        with mock.patch.object(engine, "_read_once", lambda *args: None), \
                self.assertRaisesRegex(ValueError, "changed while it was being read"):
            engine.read_file(path)
        # A network folder may report another time for the same bytes: still the same file.
        os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        self.assertTrue(engine.same_file(path, source.stamp, source.sha256))
        self.copy("aggiornato.csv")
        self.assertFalse(engine.same_file(path, source.stamp, source.sha256))

    def test_the_source_file_is_only_read(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        self.copy("aggiornato.csv")
        os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        before = path.read_bytes(), path.stat().st_mtime_ns
        project.update_from_source(title, plan_for(project, title))
        project.save(self.folder / "progetto.alab")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_a_worksheet_edited_after_reading_refuses_the_plan(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        self.copy("aggiornato.csv")
        plan = plan_for(project, title)
        project.edit_cell(title, 0, 1, "5")
        with self.assertRaisesRegex(ValueError, "changed after the file was read"):
            project.update_from_source(title, plan)

    def test_unlink_is_one_undo_step_and_keeps_the_cells(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        raw = project.tables[title].raw
        link = project.tables[title].source_link
        self.assertTrue(project.unlink_source(title))
        self.assertIsNone(project.tables[title].source_link)
        self.assertIs(project.tables[title].raw, raw)
        project.undo()
        self.assertIs(project.tables[title].source_link, link)

    # -- the saved record -------------------------------------------------------------------------------------
    def test_record_survives_save_and_reopen_with_a_relative_path(self):
        project_folder = self.folder / "Analisi"
        project_folder.mkdir()
        path = project_folder / "dati.csv"
        shutil.copyfile(DATA / "iniziale.csv", path)
        project, title = link_file(path)
        project.set_table_background(title, (0, 0, 0, 0), "#ffcc00")
        project.save(project_folder / "studio.alab")
        stored = json.loads((project_folder / "studio.alab").read_text(encoding="utf-8"))
        record = next(sheet for sheet in stored["tables"] if sheet.get("source_link"))["source_link"]
        self.assertEqual(record["relative"], "dati.csv")
        self.assertEqual(record["key"], "ID")
        self.assertEqual(len(record["rows"]["digests"]), len(engine.base64.b64encode(b"x" * 48)))
        # Move the whole folder (the project renamed too): the relative path is offered, never taken silently.
        moved = self.folder / "Analisi spostata"
        project_folder.rename(moved)
        (moved / "studio.alab").rename(moved / "studio rinominato.alab")
        reopened = _project()
        reopened.load(moved / "studio rinominato.alab")
        link = reopened.tables[title].source_link
        self.assertEqual(link.key, "ID")
        found, elsewhere = engine.locate(link, reopened.path)
        self.assertEqual((found, elsewhere), ((moved / "dati.csv").resolve(), True))
        shutil.copyfile(DATA / "aggiornato.csv", moved / "dati.csv")
        raw, excluded = reopened.source_sheet(title)
        plan = engine.plan_update(link, raw, excluded, found, found_elsewhere=True)
        self.assertEqual(plan.count(MODIFIED), 1)
        reopened.update_from_source(title, plan)
        self.assertEqual(column(reopened, title, "ID"), CASES["updated_order"])
        self.assertEqual({row for row, _ in reopened.tables[title].cell_backgrounds}, {1})  # A follows its key.

    def test_missing_file_is_not_searched_for(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.save(self.folder / "studio.alab")
        other = self.folder / "altra"
        other.mkdir()
        shutil.copyfile(path, other / "dati.csv")  # Same name elsewhere: never taken.
        path.unlink()
        self.assertEqual(engine.locate(project.tables[title].source_link, project.path), (None, False))
        with self.assertRaisesRegex(ValueError, "The linked file was not found"):
            plan_for(project, title, path)

    def test_old_project_without_link_and_damaged_records(self):
        path = self.copy("iniziale.csv")
        project, title = link_file(path)
        project.save(self.folder / "studio.alab")
        stored = json.loads((self.folder / "studio.alab").read_text(encoding="utf-8"))
        for sheet in stored["tables"]:
            sheet.pop("source_link", None)
        (self.folder / "vecchio.alab").write_text(json.dumps(stored), encoding="utf-8")
        old = _project()
        old.load(self.folder / "vecchio.alab")
        self.assertIsNone(old.tables[title].source_link)
        record = link_record(project.tables[title].source_link)
        self.assertEqual(read_link_record(json.loads(json.dumps(record))).digests,
                         project.tables[title].source_link.digests)
        for damage in ({"path": "https://example.org/dati.csv"}, {"format": 2}, {"key": "Assente"},
                       {"file": {"size": 1, "sha256": "zz"}}, {"delimiter": "|"},
                       {"rows": {"spans": [], "digests": "AAAA"}}):
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                read_link_record({**record, **damage})
        with self.assertRaises(ValueError):
            engine.local_path("https://example.org/dati.csv")


if __name__ == "__main__":
    unittest.main()
