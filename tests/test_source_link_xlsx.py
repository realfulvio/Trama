"""Worksheets linked to one sheet of an .xlsx workbook (analisi.xlsx_source with analisi.source_link and the Project
commands that apply it): the sheet chosen by its exact name, the header row or reading by position, the key, the
three-way comparison and its conflicts, the saved record and its compatibility, renamed and reordered sheets,
formulas without a stored result, the types of the cells, Cancel, and that the workbook is only read.
The Qt dialogs are tested in test_qt_source_link_xlsx.py."""
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import numpy as np
from openpyxl import Workbook

from analisi import source_link as engine, xlsx_source
from analisi.source_link import (ADDED, CONFLICT, FILE, LOCAL, MODIFIED, PROJECT, REMOVED, UNCHANGED, LinkSpec,
                                 UpdateCancelled, header_sources, link_record, read_link_record)
from analisi.xlsx_source import WorkbookOptions

DATA = Path(__file__).resolve().parent / "data" / "source_link_xlsx"


def _project():
    from trama_qt.project import Project
    return Project()


def link_workbook(path, sheet="Misure", *, header=1, key="ID", project=None):
    """Import the sheet ``sheet`` of ``path`` into a new worksheet linked to it, as the import dialog does."""
    data = Path(path).read_bytes()
    options = WorkbookOptions(sheet, header)
    table = xlsx_source.read_sheet(data, options)
    positions = list(range(table.width))
    sources = header_sources(table.header, positions)
    names = list(table.frame.columns)
    spec = LinkSpec(Path(path), len(data), hashlib.sha256(data).hexdigest(), "", options, sources,
                    sources[names.index(key)] if key is not None else None, kind=xlsx_source.WORKBOOK)
    project = project or _project()
    title = project.add_tables({sheet: table.table(positions)})[0]
    project.attach_source(title, spec)
    return project, title


def plan_for(project, title, path=None, **options):
    dataset = project.tables[title]
    raw, excluded = project.source_sheet(title)
    return engine.plan_update(dataset.source_link, raw, excluded, path or Path(dataset.source_link.path), **options)


def column(project, title, name):
    return project.tables[title].raw[name].tolist()


def expected(name):
    with (DATA / name).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows[0], [[row[0], int(row[1]), int(row[2])] for row in rows[1:]]


def rows_of(project, title):
    raw = project.tables[title].raw
    return [[identity, int(dose), int(response)]
            for identity, dose, response in zip(raw["ID"], raw["Dose"], raw["Response"])]


def write_book(path, sheets):
    """``sheets``: [(name, rows)] in workbook order."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets:
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    book.save(path)
    return path


def slope(project, title):
    frame = project.tables[title].frame()
    return float(np.polyfit(frame["Dose"].astype(float), frame["Response"].astype(float), 1)[0])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), Path(path).stat().st_mtime_ns


class WorkbookLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.book = self.folder / "misure.xlsx"
        self.use("iniziale.xlsx")

    def use(self, fixture):
        shutil.copyfile(DATA / fixture, self.book)

    def edit_b(self, project, title, value="50"):
        project.edit_cell(title, column(project, title, "ID").index("B"), 2, value)

    # -- the case of the package --------------------------------------------------------------------------------
    def test_links_the_named_sheet_not_the_decoy(self):
        project, title = link_workbook(self.book)
        link = project.tables[title].source_link
        self.assertEqual(link.kind, "xlsx")
        self.assertEqual(link.sheet, "Misure")
        self.assertEqual(link.key, "ID")
        self.assertEqual(column(project, title, "ID"), ["A", "B", "C", "D"])
        self.assertAlmostEqual(slope(project, title), 2.0, places=12)
        again = plan_for(project, title)
        self.assertTrue(again.unchanged_file)
        self.assertEqual(again.count(UNCHANGED), 4)
        self.assertIsNone(project.update_from_source(title, again))

    def test_conflict_keep_the_project_then_undo_redo_save_and_reopen(self):
        project, title = link_workbook(self.book)
        self.edit_b(project, title)
        self.use("aggiornato.xlsx")
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        self.assertEqual([plan.frame["ID"][row] for row in range(len(plan.frame))], ["C", "B", "E", "D"])
        states = dict(zip(plan.frame["ID"], plan.states.tolist()))
        self.assertEqual(states, {"C": MODIFIED, "B": CONFLICT, "E": ADDED, "D": UNCHANGED})
        self.assertEqual(plan.removed, [(0, REMOVED)])  # A
        self.assertEqual(len(plan.conflict_items), 1)
        self.assertIsNotNone(engine.can_apply(plan))  # B waits for a decision.
        decision = {plan.conflict_items[0].identity: PROJECT}
        project.update_from_source(title, plan, decisions=decision)
        header, rows = expected("atteso-progetto.csv")
        self.assertEqual(list(project.tables[title].raw.columns), header)
        self.assertEqual(rows_of(project, title), rows)
        project.undo()
        self.assertEqual(column(project, title, "ID"), ["A", "B", "C", "D"])
        self.assertEqual(column(project, title, "Response"), [3, 50, 7, 9])
        project.undo(redo=True)
        self.assertEqual(rows_of(project, title), rows)
        project.save(self.folder / "studio.alab")
        stored = json.loads((self.folder / "studio.alab").read_text(encoding="utf-8"))
        table = next(sheet for sheet in stored["tables"] if sheet["title"] == title)
        self.assertNotIn("source_link", table)  # Versions that know only CSV links ignore the workbook key.
        record = table["source_link_workbook"]
        self.assertEqual((record["sheet"], record["header"], record["relative"]), ("Misure", 1, "misure.xlsx"))
        reopened = _project()
        reopened.load(self.folder / "studio.alab")
        link = reopened.tables[title].source_link
        self.assertEqual((link.kind, link.sheet, link.sha256), ("xlsx", "Misure", plan.sha256))
        self.assertEqual(rows_of(reopened, title), rows)
        again = plan_for(reopened, title)  # B keeps the project value: it stays a project edit.
        self.assertEqual((again.count(UNCHANGED), again.count(LOCAL)), (3, 1))

    def test_conflict_use_the_file(self):
        project, title = link_workbook(self.book)
        self.edit_b(project, title)
        self.use("aggiornato.xlsx")
        plan = plan_for(project, title)
        project.update_from_source(title, plan, choice=FILE)
        header, rows = expected("atteso-excel.csv")
        self.assertEqual(rows_of(project, title), rows)
        self.assertEqual(header, list(project.tables[title].raw.columns))
        self.assertAlmostEqual(slope(project, title),
                               float(np.polyfit([3, 2, 5, 4], [8, 6, 11, 9], 1)[0]), places=12)

    def test_duplicate_key_blocks_and_changes_nothing(self):
        project, title = link_workbook(self.book)
        before, link = project.tables[title].raw.copy(), project.tables[title].source_link
        self.use("duplicato.xlsx")
        plan = plan_for(project, title)
        self.assertEqual([str(item) for item in plan.problems], ["The key column ID repeats B."])
        self.assertIsNotNone(engine.can_apply(plan))
        self.assertTrue(project.tables[title].raw.equals(before))
        self.assertIs(project.tables[title].source_link, link)

    def test_formula_without_a_stored_result_blocks_with_sheet_and_cell(self):
        project, title = link_workbook(self.book)
        self.use("formula-senza-cache.xlsx")
        plan = plan_for(project, title)
        self.assertEqual(len(plan.problems), 1)
        text = str(plan.problems[0])
        self.assertIn("Sheet Misure", text)
        self.assertIn("C2", text)
        self.assertIsNone(plan.frame)
        self.assertIsNotNone(engine.can_apply(plan))

    def test_renamed_sheet_offers_an_explicit_choice_and_keeps_the_new_name(self):
        project, title = link_workbook(self.book)
        self.edit_b(project, title)
        self.use("rinominato.xlsx")
        plan = plan_for(project, title)
        self.assertEqual(plan.missing_sheet, "Misure")
        self.assertEqual(plan.sheets, ("Misure 2027", "Riepilogo"))
        self.assertIsNone(plan.frame)
        self.assertIn("Misure 2027", str(plan.problems[0]))
        self.assertIsNotNone(engine.can_apply(plan))
        chosen = plan_for(project, title, sheet="Misure 2027")
        self.assertEqual(chosen.problems, [])
        self.assertEqual(chosen.options.sheet, "Misure 2027")
        states = dict(zip(chosen.frame["ID"], chosen.states.tolist()))
        # Compared with the confirmed version, not with the worksheet: B, edited on both sides, is a conflict.
        self.assertEqual(states, {"C": MODIFIED, "B": CONFLICT, "E": ADDED, "D": UNCHANGED})
        project.update_from_source(title, chosen, choice=PROJECT)
        self.assertEqual(project.tables[title].source_link.sheet, "Misure 2027")
        self.assertEqual(rows_of(project, title), expected("atteso-progetto.csv")[1])
        project.save(self.folder / "studio.alab")
        reopened = _project()
        reopened.load(self.folder / "studio.alab")
        self.assertEqual(reopened.tables[title].source_link.sheet, "Misure 2027")
        project.undo()
        self.assertEqual(project.tables[title].source_link.sheet, "Misure")

    def test_sheet_moved_among_the_others_changes_nothing(self):
        rows = [["ID", "Dose", "Response"], ["A", 1, 3], ["B", 2, 5]]
        decoy = [["ID", "Dose", "Response"], ["A", 9, 9], ["B", 9, 9]]
        write_book(self.book, [("Riepilogo", decoy), ("Misure", rows)])
        project, title = link_workbook(self.book)
        write_book(self.book, [("Misure", rows), ("Altro", [["x"]]), ("Riepilogo", decoy)])
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.count(UNCHANGED), 2)
        self.assertFalse(plan.unchanged_file)

    def test_reading_by_position_without_header(self):
        write_book(self.book, [("Dati", [["A", 1, 3.5], ["B", 2, 5.25]])])
        project, title = link_workbook(self.book, "Dati", header=None, key="Column 1")
        link = project.tables[title].source_link
        self.assertEqual([source for source, _ in link.columns], [0, 1, 2])
        self.assertEqual(link.key, 0)
        write_book(self.book, [("Dati", [["B", 2, 6.125], ["A", 1, 3.5]])])
        plan = plan_for(project, title)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.count(MODIFIED), 1)
        project.update_from_source(title, plan)
        self.assertEqual(column(project, title, "Column 1"), ["B", "A"])
        self.assertEqual(column(project, title, "Column 3"), [6.125, 3.5])  # Every digit kept.

    def test_header_row_below_title_rows(self):
        write_book(self.book, [("Misure", [["Studio sintetico"], [], ["ID", "Dose", "Response"], ["A", 1, 3]])])
        project, title = link_workbook(self.book, header=3)
        self.assertEqual(list(project.tables[title].raw.columns), ["ID", "Dose", "Response"])
        write_book(self.book, [("Misure", [["Studio sintetico"], [], ["ID", "Dose", "Response"], ["A", 1, 4]])])
        plan = plan_for(project, title)
        self.assertEqual(plan.count(MODIFIED), 1)

    # -- cell types -----------------------------------------------------------------------------------------------
    def test_numbers_text_empty_booleans_and_dates(self):
        day = dt.datetime(2026, 11, 26)
        write_book(self.book, [("Tipi", [["ID", "N", "T", "E", "L", "D"],
                                         ["a", 1, "007", None, True, day],
                                         ["b", 2.5, "x", 4, False, day + dt.timedelta(days=1)]])])
        project, title = link_workbook(self.book, "Tipi")
        raw = project.tables[title].raw
        self.assertEqual(raw["T"].tolist(), ["007", "x"])  # Text stays literal.
        self.assertTrue(raw["E"].isna().iloc[0])  # An empty cell is a missing value.
        self.assertEqual(raw["L"].tolist(), [True, False])
        self.assertEqual(raw["D"].tolist(), ["2026-11-26", "2026-11-27"])  # Dates arrive as ISO text.
        self.assertEqual(plan_for(project, title).count(UNCHANGED), 2)
        # Integers written as decimals are the same numbers: nothing to change.
        write_book(self.book, [("Tipi", [["ID", "N", "T", "E", "L", "D"],
                                         ["a", 1.0, "007", None, True, day],
                                         ["b", 2.5, "x", 4.0, False, day + dt.timedelta(days=1)]])])
        self.assertEqual(plan_for(project, title).count(UNCHANGED), 2)
        # Saved and reopened, the comparison still holds.
        project.save(self.folder / "tipi.alab")
        reopened = _project()
        reopened.load(self.folder / "tipi.alab")
        self.assertEqual(plan_for(reopened, title).count(UNCHANGED), 2)

    def test_text_in_a_numeric_column_blocks(self):
        write_book(self.book, [("Misure", [["ID", "Dose", "Response"], ["A", 1, 3], ["B", 2, 5]])])
        project, title = link_workbook(self.book)
        write_book(self.book, [("Misure", [["ID", "Dose", "Response"], ["A", 1, 3], ["B", 2, "n.d."]])])
        plan = plan_for(project, title)
        self.assertEqual([str(item) for item in plan.problems],
                         ["The column Response now holds text in the file (row 2: n.d.)."])

    def test_missing_key_blocks(self):
        write_book(self.book, [("Misure", [["ID", "Dose", "Response"], ["A", 1, 3], ["B", 2, 5]])])
        project, title = link_workbook(self.book)
        write_book(self.book, [("Misure", [["ID", "Dose", "Response"], ["A", 1, 3], [None, 2, 5]])])
        self.assertEqual([str(item) for item in plan_for(project, title).problems],
                         ["The key column ID is empty in row(s) 2."])

    # -- records and compatibility -------------------------------------------------------------------------------
    def test_record_round_trip_and_damaged_records_are_refused(self):
        project, title = link_workbook(self.book)
        link = project.tables[title].source_link
        record = link_record(link)
        self.assertNotIn("delimiter", record)
        again = read_link_record(json.loads(json.dumps(record)), kind="xlsx")
        self.assertTrue(engine.same_link(again, link))
        self.assertEqual(engine.record_key(link), "source_link_workbook")
        for change in ({"sheet": ""}, {"sheet": "x" * 32}, {"header": 0}, {"header": "1"}, {"delimiter": ","},
                       {"format": 2}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    read_link_record({**record, **change}, kind="xlsx")
        with self.assertRaises(ValueError):  # A workbook record is never read as a CSV link.
            read_link_record(record)
        no_header = read_link_record({**record, "header": None}, kind="xlsx")
        self.assertIsNone(no_header.options.header)

    def test_both_keys_in_one_worksheet_are_refused(self):
        project, title = link_workbook(self.book)
        project.save(self.folder / "studio.alab")
        stored = json.loads((self.folder / "studio.alab").read_text(encoding="utf-8"))
        table = next(sheet for sheet in stored["tables"] if sheet["title"] == title)
        table["source_link"] = dict(table["source_link_workbook"])
        (self.folder / "doppio.alab").write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaises(ValueError):
            _project().load(self.folder / "doppio.alab")

    def test_project_without_the_workbook_key_opens_with_the_last_copy(self):
        """What a version that does not know the workbook key does: the worksheet keeps its cells, unlinked."""
        project, title = link_workbook(self.book)
        self.edit_b(project, title)
        project.save(self.folder / "studio.alab")
        stored = json.loads((self.folder / "studio.alab").read_text(encoding="utf-8"))
        for table in stored["tables"]:
            table.pop("source_link_workbook", None)
        (self.folder / "vecchio.alab").write_text(json.dumps(stored), encoding="utf-8")
        reopened = _project()
        reopened.load(self.folder / "vecchio.alab")
        self.assertIsNone(reopened.tables[title].source_link)
        self.assertEqual(column(reopened, title, "Response"), [3, 50, 7, 9])

    def test_moved_with_the_project_is_offered_and_offline_keeps_the_copy(self):
        folder = self.folder / "Studio"
        folder.mkdir()
        book = folder / "misure.xlsx"
        shutil.copyfile(DATA / "iniziale.xlsx", book)
        project, title = link_workbook(book)
        project.save(folder / "studio.alab")
        moved = folder.rename(self.folder / "Studio spostato")
        reopened = _project()
        reopened.load(moved / "studio.alab")
        link = reopened.tables[title].source_link
        self.assertEqual(engine.locate(link, reopened.path), ((moved / "misure.xlsx").resolve(), True))
        (moved / "misure.xlsx").unlink()  # Offline: the worksheet keeps the last confirmed copy.
        self.assertEqual(engine.locate(link, reopened.path), (None, False))
        self.assertEqual(column(reopened, title, "ID"), ["A", "B", "C", "D"])
        with self.assertRaisesRegex(ValueError, "not found"):
            plan_for(reopened, title)

    def test_change_source_from_csv_to_a_workbook_sheet(self):
        from analisi.text_import import ImportOptions, TextImport, read_text_bytes
        text_path = self.folder / "misure.csv"
        text_path.write_text("ID,Dose,Response\nA,1,3\nB,2,5\nC,3,7\nD,4,9\n", encoding="utf-8")
        data, content = read_text_bytes(text_path)
        text = TextImport.parse(content, ".csv", "Automatic")
        options = ImportOptions()
        spec = LinkSpec(text_path, len(data), hashlib.sha256(data).hexdigest(), text.delimiter, options,
                        engine.column_sources(text, options, text.plan(options).columns), "ID")
        project = _project()
        title = project.add_tables({"misure": text.table(options)})[0]
        project.attach_source(title, spec)
        table = xlsx_source.read_sheet(self.book.read_bytes(), WorkbookOptions("Misure", 1))
        relink = engine.Relink("", WorkbookOptions("Misure", 1), tuple(header_sources(table.header, range(3))),
                               tuple(table.frame.columns), "ID", kind="xlsx")
        plan = plan_for(project, title, self.book, relink=relink)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.count(UNCHANGED), 4)
        project.update_from_source(title, plan)
        link = project.tables[title].source_link
        self.assertEqual((link.kind, link.sheet, link.delimiter), ("xlsx", "Misure", ""))
        project.undo()
        self.assertEqual(project.tables[title].source_link.kind, "text")

    def test_the_example_project_reopens_next_to_its_workbook(self):
        example = Path(__file__).resolve().parent.parent / "docs" / "examples" / "source-link-xlsx"
        copy = shutil.copytree(example, self.folder / "esempio")
        project = _project()
        project.load(copy / "Excel-collegato.alab")
        link = project.tables["Misure"].source_link
        self.assertEqual((link.kind, link.sheet, link.key), ("xlsx", "Misure", "ID"))
        found, elsewhere = engine.locate(link, project.path)
        if Path(link.path).is_file():  # The checkout where the example was saved: the absolute path comes first.
            self.assertEqual((found, elsewhere), (Path(link.path), False))
        else:
            self.assertEqual((found, elsewhere), ((copy / "misure.xlsx").resolve(), True))
        self.assertEqual(link.relative, "misure.xlsx")
        raw, excluded = project.source_sheet("Misure")
        plan = engine.plan_update(link, raw, excluded, found, found_elsewhere=True)
        self.assertEqual(plan.count(UNCHANGED), 4)

    # -- reading ------------------------------------------------------------------------------------------------
    def test_workbook_is_only_read(self):
        project, title = link_workbook(self.book)
        self.use("aggiornato.xlsx")
        os.utime(self.book, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        before = digest(self.book)
        plan = plan_for(project, title)
        project.update_from_source(title, plan, choice=FILE)
        project.save(self.folder / "studio.alab")
        self.assertEqual(digest(self.book), before)

    def test_cancel_while_reading(self):
        project, title = link_workbook(self.book)
        with self.assertRaises(UpdateCancelled):
            plan_for(project, title, cancel=lambda: True)

    def test_changed_between_preview_and_confirm_is_detected(self):
        project, title = link_workbook(self.book)
        self.use("aggiornato.xlsx")
        plan = plan_for(project, title)
        self.assertTrue(engine.same_file(plan.path, plan.stamp, plan.sha256))
        self.use("duplicato.xlsx")
        self.assertFalse(engine.same_file(plan.path, plan.stamp, plan.sha256))

    def test_macro_and_damaged_workbooks_are_refused(self):
        project, title = link_workbook(self.book)
        with zipfile.ZipFile(self.book, "a") as archive:
            archive.writestr("xl/vbaProject.bin", b"x")
        with self.assertRaisesRegex(ValueError, "Macro"):
            plan_for(project, title)
        self.book.write_bytes(b"not a zip")
        with self.assertRaisesRegex(ValueError, "not a valid .xlsx"):
            plan_for(project, title)


if __name__ == "__main__":
    unittest.main()
