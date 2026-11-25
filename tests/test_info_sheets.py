import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from zipfile import ZipFile

import pandas as pd

from analisi.data import Dataset, info_references, load_project, load_tables, load_workspace, save_project
from analisi.i18n import tr
from analisi.info import MAX_INFO_NOTES, NOTE_BOLD, InfoSheet, info_contexts
from analisi.info_widget import InfoEditor
from test_legacy_binary import document, group, record


class InfoSheetTests(unittest.TestCase):
    def test_project_roundtrip_keeps_order_blank_values_scope_and_notes(self):
        sheets = [
            InfoSheet("Study", (("Experiment ID", "007"), ("Dilution", "2,5"), ("Protocol", "")),
                      "Prima riga\nμL e °C\n"),
            InfoSheet("Run A", (("Dilution", "4"),), "Replicates", table="Assay"),
        ]
        tables = {"Assay": Dataset(pd.DataFrame({"X": [2, 3]}), info=info_contexts(sheets)["Assay"])}
        tables["Assay"].set_formula("Adjusted", '=COL("X") * INFO("Dilution")')
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project.alab"
            save_project(path, tables, info_sheets=sheets)
            self.assertEqual(len(load_workspace(path)), 2)
            with self.assertRaisesRegex(ValueError, "Missing or ambiguous Info constant"):
                save_project(path, tables, info_sheets=())
            save_project(path, load_project(path))
            restored, layouts, restored_sheets = load_workspace(path, include_info=True)
        self.assertEqual(restored_sheets, sheets)
        self.assertEqual(layouts, [])
        self.assertEqual(restored["Assay"].frame()["Adjusted"].tolist(), [8.0, 12.0])

    def test_info_only_project_and_invalid_links(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project.alab"
            sheet = InfoSheet("Study", notes="Project without measurements")
            save_project(path, {}, info_sheets=[sheet])
            self.assertEqual(load_workspace(path, include_info=True), ({}, [], [sheet]))
            with self.assertRaisesRegex(ValueError, "unknown data table"):
                save_project(path, {}, info_sheets=[InfoSheet("Run", table="Missing")])
            self.assertEqual(load_workspace(path, include_info=True)[2], [sheet])

    def test_rich_notes_roundtrip_and_load_plain_v2(self):
        notes = "First 🧪\nSecond µL"
        styles = ((0, 5, 1), (6, 7, 3), (8, 14, 4))
        sheet = InfoSheet("Study", notes=notes, note_styles=styles)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project.alab"
            save_project(path, {}, info_sheets=[sheet])
            self.assertEqual(load_workspace(path, include_info=True)[2], [sheet])
            original = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(original["version"], 2)
            del original["info_sheets"][0]["note_styles"]
            path.write_text(json.dumps(original), encoding="utf-8")
            [plain] = load_workspace(path, include_info=True)[2]
            self.assertEqual((plain.notes, plain.note_styles), (notes, ()))

    def test_rich_notes_validate_character_ranges_and_styles(self):
        sheet = InfoSheet("Study", notes="😀µ", note_styles=[[0, 1, 3], [1, 2, 3]])
        self.assertEqual(sheet.note_styles, ((0, 2, 3),))
        for styles in (((0, 3, 1),), ((0, 1, 8),), ((0, 0, 2),), ((0, 1, True),),
                       ((0, 2, 1), (1, 2, 2)), ((1, 2, 1), (0, 1, 2)), None):
            with self.subTest(styles=styles), self.assertRaisesRegex(ValueError, "note formatting"):
                InfoSheet("Study", notes="😀µ", note_styles=styles)

    def test_note_editor_styles_selection_and_undo_preserves_unicode(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        revised, errors = [], []
        original = InfoSheet("Study", notes="A🧪 B\nµL")
        noop = lambda *_args: None
        editor = InfoEditor(root, original, revised.append, errors.append, noop, noop, noop, None)
        editor.pack(fill="both", expand=True)
        root.update()
        notes = editor.notes
        notes.tag_add("sel", "1.0", "end")
        editor.toggle_note_style(1)
        self.assertEqual(editor.sheet.note_styles, ((0, 7, 1),))
        notes.tag_remove("sel", "1.0", "end")
        notes.tag_add("sel", "2.0", "2.1")
        editor.toggle_note_style(2)
        editor.toggle_note_style(4)
        self.assertEqual(editor.sheet.note_styles, ((0, 5, 1), (5, 6, 7), (6, 7, 1)))
        self.assertEqual(notes.get("1.0", "end-1c"), original.notes)
        notes.delete("2.0", "2.1")
        root.update()
        self.assertEqual((editor.sheet.notes, editor.sheet.note_styles), ("A🧪 B\nL", ((0, 6, 1),)))
        notes.event_generate("<<Undo>>")
        self.assertEqual(editor.sheet.note_styles, ((0, 5, 1), (5, 6, 7), (6, 7, 1)))
        self.assertEqual(editor.sheet.notes, original.notes)
        notes.event_generate("<<Undo>>")
        self.assertEqual(editor.sheet.note_styles, ((0, 5, 1), (5, 6, 3), (6, 7, 1)))
        notes.event_generate("<<Redo>>")
        self.assertEqual(editor.sheet.note_styles, ((0, 5, 1), (5, 6, 7), (6, 7, 1)))
        self.assertEqual(revised[-1], editor.sheet)
        self.assertEqual(errors, [])

    def test_classic_note_import_validates_before_inserting(self):
        from unittest.mock import patch
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        errors = []
        noop = lambda *_: None
        editor = InfoEditor(root, InfoSheet("Study", notes="AB"), noop, errors.append, noop, noop, noop, None)
        editor.notes.insert("end-1c", "🧪")
        with TemporaryDirectory() as folder, patch("analisi.info.MAX_INFO_NOTES", 8):
            path = Path(folder) / "append.txt"
            with patch("analisi.info_widget.filedialog.askopenfilename", return_value=str(path)):
                path.write_text("1234", encoding="utf-8")
                editor.import_notes()
                self.assertEqual(editor.notes.get("1.0", "end-1c"), "AB🧪")
                self.assertEqual(len(errors), 1)
                path.write_bytes(b"\xef\xbb\xbfX\r\nY")
                editor.import_notes()
                self.assertEqual(editor.sheet.notes, "AB🧪\n\nX\nY")

    def test_global_numeric_constants_and_ambiguous_names(self):
        sheets = [InfoSheet("Study", (("Scale", "2,5"), ("Code", "007")))]
        dataset = Dataset(pd.DataFrame({"X": [2, 4]}), info=info_contexts(sheets)[None])
        dataset.set_formula("Adjusted", '=X * INFO("scale")')
        dataset.set_formula("Identifier", '=INFO("Code")')
        self.assertEqual(dataset.frame()["Adjusted"].tolist(), [5.0, 10.0])
        self.assertEqual(dataset.frame()["Identifier"].tolist(), ["007", "007"])
        sheets.append(InfoSheet("Another", (("Scale", "9"),)))
        dataset.info = info_contexts(sheets)[None]
        with self.assertRaisesRegex(ValueError, "Ambiguous Info constant"):
            dataset.frame()

    def test_info_references_and_unicode_validation(self):
        self.assertEqual(info_references('=info(" Scale ") + INFO("Offset")'), {"scale", "offset"})
        self.assertEqual(info_references('="INFO(Scale)"'), set())
        with self.assertRaises(ValueError):
            InfoSheet("Study", (("Invalid", "\ud800"),))

    def test_xml_info_only_preserves_sequence_and_multiline_notes(self):
        long_note = "x" * (MAX_INFO_NOTES + 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pzfx"
            path.write_text(
                '<GraphPadPrismFile xmlns="http://graphpad.com/prism/Prism.htm">'
                '<InfoSequence><Ref ID="B"/><Ref ID="A"/></InfoSequence>'
                '<Info ID="A"><Title>Run A</Title><Notes>Readout μM\nSecond line</Notes>'
                '<Constant><Name>Experiment ID</Name><Value>007</Value></Constant></Info>'
                f'<Info ID="B"><Title>Run B</Title><Notes>{long_note}</Notes>'
                '<Constant><Name>Scale</Name><Value>03</Value></Constant></Info></GraphPadPrismFile>',
                encoding="utf-8",
            )
            result, warnings = [], []
            self.assertEqual(load_tables(path, info_sheets=result, import_warnings=warnings), {})
            self.assertEqual([sheet.title for sheet in result], ["Run B", "Run A"])
            self.assertEqual(result[0].fields, (("Scale", "03"),))
            self.assertEqual(result[0].notes, "")
            self.assertEqual(result[1].fields, (("Experiment ID", "007"),))
            self.assertEqual(result[1].notes, "Readout μM\nSecond line")
            self.assertEqual(warnings, [tr("import.skipped_info_note", name="Run B")])

    def test_zip_info_recovers_text_and_supported_emphasis(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.prism"
            with ZipFile(path, "w") as archive:
                archive.writestr("document.json", json.dumps({"sheets": {"info": ["first"]}}))
                archive.writestr("info/first/sheet.json", json.dumps({
                    "@class": "InfoSheet", "uid": "first", "title": "Project info",
                    "notesText": {"string": "Temperature 37 °C",
                                  "formatting": [{"range": "0~10", "attributes": {"fontWeight": "bold"}}]},
                    "constants": [{"name": "Experiment Date", "value": {"string": "1/25/2026", "version": 1}}],
                }))
            result = []
            self.assertEqual(load_tables(path, info_sheets=result), {})
            self.assertEqual(result[0].fields, (("Experiment Date", "1/25/2026"),))
            self.assertEqual(result[0].notes, "Temperature 37 °C")
            self.assertEqual(result[0].note_styles, ((0, 11, NOTE_BOLD),))

    def test_pzf_info_order_and_internal_backing_id_is_not_a_user_link(self):
        def binary_sheet(uid, title, value):
            return group(
                0x38, struct.pack("<H", uid), record(9, title + b"\0"),
                record(0x6D, struct.pack("<ii12x", 17, 1)),
                record(0x6E, b"Project\0"), record(0x6F, value + b"\0"),
            )

        content = bytearray(document([], binary_sheet(2, b"First", b"Temperature"),
                                     binary_sheet(4, b"Second", b"Trait \xb5M")))
        start = 8 + len(record(0x8001, bytes(12))) + struct.calcsize("<HI")
        struct.pack_into("<I", content, start + 56, 2)
        struct.pack_into("<2i", content, start + 8060, 4, 2)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pzf"
            path.write_bytes(content)
            result = []
            self.assertEqual(load_tables(path, info_sheets=result), {})
            self.assertEqual([sheet.title for sheet in result], ["Second", "First"])
            self.assertEqual(result[0].fields, (("Project", "Trait µM"),))
            self.assertIsNone(result[0].table)

    def test_binary_info_note_recovers_text_and_ignores_unrelated_text_objects(self):
        def note(payload, length):
            header = struct.pack("<5H8x", 0xFFFF, 9, 1, length, 2)
            return group(0x2B, header, record(0x2C, payload), record(0x2D, bytes(32)))

        def info_sheet(uid, title, *notes):
            return group(
                0x38, struct.pack("<H", uid), record(9, title + b"\0"), *notes,
                record(0x6D, struct.pack("<ii12x", -1, 1)),
                record(0x6E, b"Project\0"), record(0x6F, b"Assay\0"),
            )

        payload = b"  Temperature 37 \xb0C\r\r\nVolume\t5 \xb5L\r"
        content = bytearray(document(
            [],
            info_sheet(0, b"Readout", note(payload, len(payload)),
                       group(0x96, b"", note(b"Floating note", 13))),
            info_sheet(1, b"Malformed", note(b"Invalid", 1)),
            info_sheet(2, b"Ambiguous", note(b"First", 5), note(b"Second", 6)),
        ))
        start = 8 + len(record(0x8001, bytes(12))) + struct.calcsize("<HI")
        struct.pack_into("<I", content, start + 56, 3)
        struct.pack_into("<3i", content, start + 8060, 0, 1, 2)
        for suffix in (".pzf", ".pzt"):
            with self.subTest(suffix=suffix), TemporaryDirectory() as directory:
                path = Path(directory) / f"fixture{suffix}"
                path.write_bytes(content)
                result, warnings = [], []
                load_tables(path, info_sheets=result, import_warnings=warnings)
                self.assertEqual([sheet.title for sheet in result], ["Readout", "Malformed", "Ambiguous"])
                self.assertEqual(result[0].notes, "  Temperature 37 °C\n\nVolume\t5 µL\n")
                self.assertEqual(warnings, [tr("import.skipped_info_note", name=title)
                                            for title in ("Malformed", "Ambiguous")])
                for sheet in result[1:]:
                    self.assertEqual(sheet.notes, "")
                    self.assertEqual(sheet.fields, (("Project", "Assay"),))
