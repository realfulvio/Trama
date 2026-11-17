"""Oracles for filtered delimited-file imports."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.text_import import ImportOptions, TextImport, read_text_file


class TextImportTests(unittest.TestCase):
    def test_ranges_decimation_exclusions_and_locale_before_inference(self):
        source = TextImport.parse(
            'ID;Comment;Score;Skip;Control\n'
            'skip;ignored;bad;bad;bad\n'
            '002;"two\nlines";1,25*;ignore;999\n'
            'skip;ignored;bad;bad;bad\n'
            '004;ignored;4,125;ignore;2,5\n'
            'skip;ignored;bad;bad;bad\n', '.csv', 'Semicolon')
        options = ImportOptions(first_row=2, last_row=4, skip_rows=1, skip_columns=1,
                                missing_code="999", mark_excluded=True)
        frame = source.table(options)
        self.assertEqual(frame.columns.tolist(), ["ID", "Score", "Control"])
        self.assertEqual(frame["ID"].tolist(), ["002", "004"])
        self.assertEqual(frame["Score"].tolist(), [1.25, 4.125])
        self.assertTrue(pd.isna(frame.at[0, "Control"]))
        data = Dataset(frame)
        self.assertEqual(data.excluded, {(0, 1)})
        self.assertTrue(pd.isna(data.frame(mask_excluded=True).at[0, "Score"]))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "filtered.alab"
            save_project(path, {"Filtered": data})
            restored = load_project(path)["Filtered"]
            self.assertEqual(restored.excluded, {(0, 1)})
            self.assertEqual(restored.raw.at[0, "Score"], 1.25)

    def test_headerless_ragged_tab_preserves_column_numbers_and_blanks(self):
        source = TextImport.parse("001\t1,5\tA\n002\t\n", ".tsv", "Tab")
        frame = source.table(ImportOptions(header=False, first_column=2, decimal="Comma"))
        self.assertEqual(frame.columns.tolist(), ["Column 2", "Column 3"])
        self.assertEqual(frame.iat[0, 0], 1.5)
        self.assertTrue(pd.isna(frame.iat[1, 0]) and pd.isna(frame.iat[1, 1]))

    def test_header_only_and_preview(self):
        source = TextImport.parse('A;B\n', '.csv', 'Semicolon')
        self.assertEqual(source.table(ImportOptions()).shape, (0, 2))
        source = TextImport.parse("A\tB\n" + "001\t2\n" * 20, ".tsv", "Tab")
        plan = source.plan(ImportOptions(first_row=2, skip_rows=1))
        self.assertEqual((len(plan.rows), len(plan.columns)), (10, 2))
        self.assertEqual(source.table(ImportOptions(first_row=2, skip_rows=1), limit=(3, 1)).shape, (3, 1))

    def test_invalid_ranges_and_bad_quoting_are_rejected(self):
        source = TextImport.parse('A,B\n1,2\n', '.csv', 'Comma')
        for options, name in [(ImportOptions(last_row=2), "row"), (ImportOptions(skip_columns=-1), "column"),
                              (ImportOptions(first_column=2, last_column=1), "column")]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, name):
                source.table(options)
        with self.assertRaisesRegex(ValueError, "quoted"):
            TextImport.parse('A,B\n"unterminated,2\n', '.csv', 'Comma')

    def test_utf8_bom_and_quoted_delimiter(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_bytes('Name;Value\r\n"é;β";1,2\r\n'.encode('utf-8-sig'))
            source = TextImport.parse(read_text_file(path), path.suffix, "Semicolon")
            frame = source.table(ImportOptions())
            self.assertEqual(frame.iloc[0].tolist(), ["é;β", 1.2])
