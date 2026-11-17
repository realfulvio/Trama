import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import pandas as pd

from analisi.data import Dataset, load_project, load_tables, save_project


class LegacyTests(unittest.TestCase):
    def test_pzfx_preserves_labels_replicates_and_exclusions(self):
        doc = """<?xml version="1.0"?>
        <GraphPadPrismFile xmlns="http://graphpad.com/prism/Prism.htm">
          <Table ID="T" TableType="TwoWay">
            <Title>Experiment</Title>
            <RowTitlesColumn><Subcolumn><d>001</d><d>002</d></Subcolumn></RowTitlesColumn>
            <YColumn Subcolumns="2"><Title>Dose</Title>
              <Subcolumn><d>2</d><d Excluded="1">3</d></Subcolumn>
              <Subcolumn><d>4</d></Subcolumn>
            </YColumn>
          </Table>
        </GraphPadPrismFile>"""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pzfx"
            source.write_text(doc, encoding="utf-8")
            frame = load_tables(source)["Experiment"]
            self.assertEqual(list(frame), ["Row title", "Dose [1]", "Dose [2]"])
            self.assertEqual(frame["Row title"].tolist(), ["001", "002"])
            self.assertEqual(frame.iloc[1, 1], 3)
            self.assertTrue(pd.isna(frame.iloc[1, 2]))
            ds = Dataset(frame)
            self.assertTrue(pd.isna(ds.frame(mask_excluded=True).iloc[1, 1]))
            project = Path(tmp) / "saved.alab"
            save_project(project, {"Experiment": ds})
            restored = load_project(project)["Experiment"]
            self.assertEqual(restored.raw.iloc[1, 1], 3)
            self.assertTrue(pd.isna(restored.frame(mask_excluded=True).iloc[1, 1]))

    def test_prism_grouped_import_keeps_replicate_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grouped.prism"
            with ZipFile(path, "w") as archive:
                archive.writestr("document.json", '{"sheets":{"data":["sheet"]}}')
                archive.writestr("data/sheets/sheet/sheet.json", json.dumps({
                    "title": "Grouped", "table": {
                        "uid": "table", "format": "grouped", "dataFormat": "y_replicates",
                        "rowTitlesDataSet": "rows", "dataSets": ["a", "b"], "replicatesCount": 2,
                    },
                }))
                for uid, name in (("rows", "Rows"), ("a", "A"), ("b", "B")):
                    archive.writestr(f"data/sets/{uid}.json", json.dumps({"title": name}))
                archive.writestr("data/tables/table/data.csv", "001,1,2,3,4\n002,5,6,7,8\n")
            frame = load_tables(path)["Grouped"]
            self.assertEqual(list(frame), ["Rows", "A [1]", "A [2]", "B [1]", "B [2]"])
            self.assertEqual(frame["Rows"].tolist(), ["001", "002"])
            self.assertEqual(frame["B [2]"].tolist(), [4, 8])

    def test_decimal_comma_in_legacy_and_semicolon_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "commas.csv"
            csv_path.write_text("Label;Dose\n001;1,25\n002;2,5e-1\n", encoding="utf-8")
            imported = load_tables(csv_path)["commas"]
            self.assertEqual(imported["Label"].tolist(), ["001", "002"])
            self.assertEqual(imported["Dose"].tolist(), [1.25, .25])
            path = Path(tmp) / "commas.pzfx"
            path.write_text('<GraphPadPrismFile><Table ID="A"><YColumn><Title>Dose</Title>'
                            '<Subcolumn><d>1,25</d><d>2,5e-1</d></Subcolumn>'
                            '</YColumn></Table></GraphPadPrismFile>', encoding="utf-8")
            self.assertEqual(load_tables(path)["A"]["Dose"].tolist(), [1.25, .25])

    def test_pzfx_rejects_doctype(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pzfx"
            path.write_text('<!DOCTYPE t [<!ENTITY a "1">]><GraphPadPrismFile/>')
            with self.assertRaisesRegex(ValueError, "DOCTYPE"):
                load_tables(path)
