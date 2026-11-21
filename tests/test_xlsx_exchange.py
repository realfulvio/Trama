"""Excel workbook exchange (analisi.xlsx_exchange): sheet inspection, header rows, typed values, limits and an
atomic, literal export. No Qt needed."""
import datetime as dt
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from zipfile import ZipFile

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference

from analisi import xlsx_exchange as xx
from analisi.data import load_tables

DATA = Path(__file__).resolve().parent / "data" / "xlsx_exchange"
FIXTURE = DATA / "quaderno-multifoglio.xlsx"


def workbook(path, sheets, *, states=None):
    """Write ``{name: rows}`` with openpyxl (formulas are stored without a cached result)."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
        if states and name in states:
            sheet.sheet_state = states[name]
    book.save(path)
    return path


class Temporary(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()


class Inspect(Temporary):
    def test_fixture_order_state_and_size(self):
        found = xx.inspect_workbook(FIXTURE)
        self.assertEqual([(item.name, item.state) for item in found],
                         [("Campioni α", "visible"), ("Controlli", "visible"), ("Appunti", "hidden"),
                          ("Vuoto", "visible")])
        self.assertEqual((found[0].rows, found[0].columns), (5, 8))
        self.assertEqual([item.importable for item in found], [True, True, True, False])

    def test_very_hidden_and_chart_sheets_are_listed(self):
        path = self.dir / "states.xlsx"
        book = Workbook()
        book.active.title = "Dati"
        book.active.append([1])
        secret = book.create_sheet("Segreto")
        secret.append(["x"])
        secret.sheet_state = "veryHidden"
        chart = BarChart()
        chart.add_data(Reference(book.active, min_col=1, min_row=1, max_row=1))
        book.create_chartsheet("Grafico").add_chart(chart)
        book.save(path)
        found = {item.name: item for item in xx.inspect_workbook(path)}
        self.assertEqual(found["Segreto"].state, "veryHidden")
        self.assertTrue(found["Segreto"].importable)
        self.assertEqual(found["Grafico"].kind, "chartsheet")
        self.assertFalse(found["Grafico"].importable)
        with self.assertRaises(ValueError):
            xx.read_workbook(path, {"Grafico": 1})

    def test_unreadable_and_unsupported_files(self):
        with self.assertRaises(ValueError) as caught:
            xx.inspect_workbook(DATA / "rotto.xlsx")
        self.assertIsNotNone(caught.exception.__cause__)  # The original error stays available for the log.
        for suffix in (".xlsm", ".xls", ".xlsb", ".csv"):
            path = self.dir / f"file{suffix}"
            path.write_bytes(FIXTURE.read_bytes())
            with self.assertRaises(ValueError):
                xx.inspect_workbook(path)
        macro = self.dir / "macro.xlsx"
        with ZipFile(FIXTURE) as source, ZipFile(macro, "w") as target:
            for item in source.infolist():
                target.writestr(item, source.read(item))
            target.writestr("xl/vbaProject.bin", b"\0")
        with self.assertRaises(ValueError):
            xx.inspect_workbook(macro)
        with self.assertRaises(ValueError):
            xx.inspect_workbook(self.dir / "missing.xlsx")


class Read(Temporary):
    def test_header_rows_and_order(self):
        tables = xx.read_workbook(FIXTURE, {"Controlli": 2, "Campioni α": 1})
        self.assertEqual(list(tables), ["Controlli", "Campioni α"])
        self.assertEqual(tables["Controlli"].to_dict("list"), {"ID esterno": ["001", "002"], "Risposta": [0, 13.5]})
        sample = tables["Campioni α"]
        self.assertEqual(list(sample.columns),
                         ["ID", "Dose", "Dose (2)", "Column 4", "Attivo", "Data", "Calcolo", "Nota"])
        self.assertEqual(sample.shape, (4, 8))
        self.assertTrue(sample.iloc[2].isna().all())  # The empty row in the middle stays.

    def test_values_keep_their_type(self):
        warnings = []
        table = xx.read_workbook(FIXTURE, {"Campioni α": 1}, warnings=warnings)["Campioni α"]
        self.assertEqual(str(table["ID"].dtype), "string")
        self.assertEqual(list(table["ID"].dropna()), ["0007", "0042", "0009"])
        self.assertEqual(str(table["Attivo"].dtype), "boolean")
        self.assertEqual(table.loc[0, "Data"], "2026-04-06T12:30:00")
        self.assertEqual(table.loc[0, "Calcolo"], 5)
        self.assertTrue(pd.isna(table.loc[1, "Calcolo"]))
        self.assertEqual(list(table.loc[:1, "Nota"]), ["=letterale", "@codice"])
        self.assertEqual(table.loc[0, "Column 4"], 0)
        self.assertTrue(pd.isna(table.loc[1, "Column 4"]))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Campioni α: G3", warnings[0])

    def test_no_header_includes_the_first_row(self):
        table = xx.read_workbook(FIXTURE, {"Controlli": None})["Controlli"]
        self.assertEqual(list(table.columns), ["Column 1", "Column 2"])
        self.assertEqual(table.iloc[0, 0], "Titolo della scheda")
        self.assertEqual(table.shape, (4, 2))
        self.assertEqual(table.dtypes.iloc[1], object)  # Text "Risposta" and numbers: a literal mix.
        self.assertEqual(list(table.iloc[1:, 1]), ["Risposta", 0, 13.5])

    def test_header_without_data_and_trailing_rows(self):
        path = workbook(self.dir / "head.xlsx", {"Solo": [["A", "B"]],
                                                 "Code": [["X"], [1], [None], [2], [None], [None]]})
        tables = xx.read_workbook(path, {"Solo": 1, "Code": 1})
        self.assertEqual(list(tables["Solo"].columns), ["A", "B"])
        self.assertEqual(len(tables["Solo"]), 0)
        self.assertEqual(len(tables["Code"]), 3)  # Trailing empty rows go, the inner one stays.
        with self.assertRaises(ValueError):
            xx.read_workbook(path, {"Solo": 2})

    def test_dates_times_mixed_and_errors(self):
        path = self.dir / "types.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Tipi"
        sheet.append(["Giorno", "Ora", "Misto", "Testo numero", "Errore", dt.date(2026, 1, 2)])
        sheet.append([dt.datetime(2026, 1, 2), dt.time(8, 15), 1, "12", "x", 1])
        sheet.append([dt.datetime(2026, 1, 3), dt.time(9, 0, 30), "a", "13", "y", 2])
        sheet["E3"].value = "#DIV/0!"
        sheet["E3"].data_type = "e"
        book.save(path)
        warnings = []
        table = xx.read_workbook(path, {"Tipi": 1}, warnings=warnings)["Tipi"]
        self.assertEqual(list(table["Giorno"]), ["2026-01-02", "2026-01-03"])  # Only dates: no time part.
        self.assertEqual(list(table["Ora"]), ["08:15:00", "09:00:30"])
        self.assertEqual(list(table["Misto"]), [1, "a"])
        self.assertEqual(list(table["Testo numero"]), ["12", "13"])
        self.assertTrue(pd.isna(table.loc[1, "Errore"]))
        self.assertIn("2026-01-02", table.columns)
        self.assertTrue(any("Tipi: E3" in note for note in warnings))

    def test_uncached_formula_written_by_openpyxl(self):
        path = workbook(self.dir / "formula.xlsx", {"F": [["A", "B"], [1, "=A2*2"]]})
        warnings = []
        table = xx.read_workbook(path, {"F": 1}, warnings=warnings)["F"]
        self.assertTrue(pd.isna(table.loc[0, "B"]))
        self.assertIn("F: B2", warnings[0])

    def test_invalid_selections(self):
        for selection in ({}, {"Campioni α": 1, "Controlli": 99}, {"Sconosciuto": 1}, {"Vuoto": 1},
                          {"Controlli": 0}, {"Controlli": True}, {"Controlli": "2"}, {"Controlli": -1}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                xx.read_workbook(FIXTURE, selection)
        with self.assertRaises(ValueError):
            xx.read_workbook(FIXTURE, [("Controlli", 1)])

    def test_limits_are_checked_while_reading(self):
        path = workbook(self.dir / "wide.xlsx", {"W": [list(range(xx.MAX_COLUMNS + 1))]})
        with self.assertRaises(ValueError):
            xx.read_workbook(path, {"W": 1})
        path = workbook(self.dir / "tall.xlsx", {"T": [["a", "b"]] + [[1, 2]] * 60})
        with mock.patch.object(xx, "MAX_CELLS", 100), self.assertRaises(ValueError):
            xx.read_workbook(path, {"T": 1})
        with mock.patch.object(xx, "MAX_ENTRY", 100), self.assertRaises(ValueError):
            xx.inspect_workbook(path)
        with mock.patch.object(xx, "MAX_UNPACKED", 100), self.assertRaises(ValueError):
            xx.inspect_workbook(path)

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(xx.ExchangeCancelled):
            xx.read_workbook(FIXTURE, {"Controlli": 2}, cancel=cancel)

    def test_preview_matches_import(self):
        with xx.WorkbookReader(FIXTURE) as reader:
            preview = reader.preview("Campioni α", 1)
            self.assertEqual(preview.letters[:3], ["A", "B", "C"])
            self.assertEqual(preview.grid[1][:2], ["0007", 2])
            self.assertEqual(preview.grid[1][5], "2026-04-06T12:30:00")
            self.assertIsNone(preview.grid[2][6])  # G3: formula without a stored result.
            self.assertEqual(preview.names, list(reader.read({"Campioni α": 1})["Campioni α"].columns))
            self.assertTrue(preview.warnings)
            past = reader.preview("Controlli", 9)
            self.assertIn("past the last row", past.error)
            self.assertEqual(reader.preview("Controlli", None).names, ["Column 1", "Column 2"])

    def test_legacy_reader_unchanged(self):
        tables = load_tables(FIXTURE)
        self.assertEqual(list(tables), ["Campioni α", "Controlli", "Appunti"])
        self.assertEqual(tables["Campioni α"].iloc[0, 0], "0007")


class Names(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(xx.excel_sheet_names(["A/B", "a:b", "History"]), ["A_B", "a_b (2)", "History (2)"])
        self.assertEqual(xx.excel_sheet_names(["", "''", "'x'", "[a]*?\\b\x01"]), ["Sheet", "Sheet (2)", "x",
                                                                                     "_a____b_"])
        long = xx.excel_sheet_names(["N" * 40, "N" * 40, "N" * 40])
        self.assertEqual(long, ["N" * 31, "N" * 27 + " (2)", "N" * 27 + " (3)"])
        emoji = xx.excel_sheet_names(["😀" * 20])[0]
        self.assertEqual(len(emoji.encode("utf-16-le")) // 2, 30)  # Emoji count twice, never split.
        self.assertEqual(xx.excel_sheet_names(["a" * 30 + "'b"])[0], "a" * 30)


class Write(Temporary):
    def frame(self):
        return pd.DataFrame({"=Titolo": ["=4+5", "0007", "#N/A"], "Numero": [0, 3.125, None],
                             "Intero": pd.array([1, None, 3], dtype="Int64"),
                             "Bool": pd.array([True, False, None], dtype="boolean"),
                             "Quando": [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-02 10:30"), pd.NaT],
                             "Misto": [1, "x", None]})

    def test_literal_typed_cells(self):
        path = self.dir / "out.xlsx"
        names = xx.write_workbook(path, [("Dati", self.frame())])
        self.assertEqual(names, ["Dati"])
        book = load_workbook(path)
        sheet = book["Dati"]
        for coordinate, expected in {"A1": "=Titolo", "A2": "=4+5", "A3": "0007", "A4": "#N/A"}.items():
            self.assertEqual((sheet[coordinate].data_type, sheet[coordinate].value), ("s", expected))
        self.assertEqual([sheet["B2"].value, sheet["B3"].value, sheet["B4"].value], [0, 3.125, None])
        self.assertEqual([sheet["C2"].value, sheet["C3"].value], [1, None])
        self.assertEqual(sheet["D2"].data_type, "b")
        self.assertEqual([sheet["E2"].value, sheet["E3"].value], ["2026-01-02", "2026-01-02T10:30:00"])
        self.assertEqual([sheet["F2"].value, sheet["F3"].value], [1, "x"])
        self.assertFalse(any(cell.data_type == "f" for row in sheet.iter_rows() for cell in row))
        book.close()
        with ZipFile(path) as archive:
            self.assertIn(b'<dimension ref="A1:F4"', archive.read("xl/worksheets/sheet1.xml"))
        again = xx.read_workbook(path, {"Dati": 1})["Dati"]
        self.assertEqual(list(again["=Titolo"]), ["=4+5", "0007", "#N/A"])

    def test_results_with_index(self):
        result = pd.DataFrame({"Mean": [1.5, 2.0]}, index=pd.MultiIndex.from_tuples(
            [("A", 1), ("B", 2)], names=["Group", None]))
        table = xx.materialize_index(result)
        self.assertEqual(list(table.columns), ["Group", "Level 2", "Mean"])
        path = self.dir / "results.xlsx"
        xx.write_workbook(path, [("Risultato", table)])
        self.assertEqual(list(xx.read_workbook(path, {"Risultato": 1})["Risultato"]["Group"]), ["A", "B"])
        single = xx.materialize_index(pd.DataFrame({"Row": [1]}, index=pd.Index(["r"])))
        self.assertEqual(list(single.columns), ["Row (2)", "Row"])  # The table's own column keeps its name.

    def test_invalid_values_name_sheet_and_row(self):
        path = self.dir / "bad.xlsx"
        for bad, fragment in ((10 ** 15 + 1, "15 digits"), (float("inf"), "infinite"),
                              ("a" * 32768, "32,767"), ("abc\x00", "control")):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                xx.write_workbook(path, [("Buono", pd.DataFrame({"A": [1]})),
                                         ("Cattivo", pd.DataFrame({"A": [1, bad]}))])
            self.assertIn('"Cattivo"', str(caught.exception))
            self.assertIn("row 3", str(caught.exception))
            self.assertIn(fragment, str(caught.exception))
        self.assertFalse(path.exists())
        with self.assertRaises(ValueError):
            xx.write_workbook(path, [("Righe", pd.DataFrame({"A": range(xx.MAX_EXCEL_ROWS)}))])
        with self.assertRaises(ValueError):
            xx.write_workbook(self.dir / "out.csv", [("A", pd.DataFrame({"A": [1]}))])
        with self.assertRaises(ValueError):
            xx.write_workbook(path, [])

    def test_atomic_overwrite_and_cancel(self):
        path = self.dir / "existing.xlsx"
        xx.write_workbook(path, [("Prova", pd.DataFrame({"A": [42]}))])
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            xx.write_workbook(path, [("Prova", pd.DataFrame({"A": [1]}))])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(xx.ExchangeCancelled):
            xx.write_workbook(path, [("Prova", pd.DataFrame({"A": [1]}))], overwrite=True, cancel=cancel)
        self.assertEqual(path.read_bytes(), original)
        prepared = xx.prepare_workbook(path, [("Nuovo", pd.DataFrame({"A": [7]}))])
        self.assertTrue(prepared.temporary.exists())
        self.assertEqual(path.read_bytes(), original)  # Nothing changes before publishing.
        with self.assertRaises(FileExistsError):
            prepared.publish(overwrite=False)
        self.assertFalse(prepared.temporary.exists())
        self.assertEqual(path.read_bytes(), original)
        xx.write_workbook(path, [("Nuovo", pd.DataFrame({"A": [7]}))], overwrite=True)
        self.assertEqual(load_workbook(path).sheetnames, ["Nuovo"])
        self.assertEqual(sorted(item.name for item in self.dir.iterdir()), ["existing.xlsx"])

    def test_blocked_destination_keeps_previous_file(self):
        path = self.dir / "locked.xlsx"
        xx.write_workbook(path, [("Prova", pd.DataFrame({"A": [42]}))])
        original = path.read_bytes()
        with mock.patch.object(xx.os, "replace", side_effect=PermissionError("locked")), \
                self.assertRaises(PermissionError):
            xx.write_workbook(path, [("Prova", pd.DataFrame({"A": [1]}))], overwrite=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([item.name for item in self.dir.iterdir()], ["locked.xlsx"])
        with self.assertRaises(OSError):
            xx.write_workbook(self.dir / "missing" / "x.xlsx", [("A", pd.DataFrame({"A": [1]}))])


if __name__ == "__main__":
    unittest.main()
