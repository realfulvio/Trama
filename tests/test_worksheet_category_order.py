"""Worksheet-level category order stays linked to graphs through project edits and saving."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from analisi.category_order import WORKSHEET_ORDERS, OrderDraft, set_order
from analisi.data import Dataset, load_workspace, save_project
from analisi.graph_legend import typed_group_token
from analisi.grouped_distributions import CELLS_SHEET, GROUPED_DISTRIBUTIONS
from analisi.workbench import analyse


def frame():
    return pd.DataFrame({
        "Visit": ["Late", "Early", "Late", "Early", "Middle", "Middle"],
        "Treatment": ["Drug", "Drug", "Vehicle", "Vehicle", "Drug", "Vehicle"],
        "Time": [1, 2, 1, 2, 1, 2],
        "Signal": [9, 2, 7, 4, 6, 5],
    })


def ordered(dataset, column, values):
    set_order(dataset, column, list(map(typed_group_token, values)))


def legend(result):
    return [label.get_text() for label in result.figure.axes[0].get_legend().get_texts()]


class WorksheetCategoryOrderTests(unittest.TestCase):
    def test_graph_changes_order_without_moving_observations_between_cells(self):
        dataset = Dataset(frame())
        options = {"Response": "Signal", "Category": "Visit", "Split by": "Treatment", "Style": "Box"}
        baseline = analyse(GROUPED_DISTRIBUTIONS, dataset.frame(), options)
        ordered(dataset, "Visit", ["Early", "Middle", "Late"])
        ordered(dataset, "Treatment", ["Vehicle", "Drug"])
        result = analyse(GROUPED_DISTRIBUTIONS, dataset.frame(), options)
        self.assertEqual([x.get_text() for x in result.figure.axes[0].get_xticklabels()], ["Early", "Middle", "Late"])
        self.assertEqual(legend(result), ["Vehicle", "Drug"])
        keys = ["Category", "Series"]
        values = ["N", "Mean", "Median"]
        pd.testing.assert_frame_equal(
            baseline.tables[CELLS_SHEET].set_index(keys)[values].sort_index(),
            result.tables[CELLS_SHEET].set_index(keys)[values].sort_index(),
        )
        pd.testing.assert_frame_equal(dataset.raw, frame())

    def test_zip_source_order_is_distinct_from_the_observed_order(self):
        from analisi.data import load_tables
        from tests.test_legacy_import import write_archive

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "study.pzt"
            write_archive(source, {
                "uid": "table", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["category", "value"],
            }, {
                "category": {"title": "Label", "dataType": "categorical",
                             "categories": [{"name": "Early"}, {"name": "Late"}]},
                "value": {"title": "Value", "dataType": "numeric"},
            }, "Late,3\nEarly,1\nLate,5\n", (3, 2))
            raw = load_tables(source)["Experiment"]
            self.assertEqual(raw["Label"].tolist(), ["Late", "Early", "Late"])
            self.assertEqual(raw.attrs[WORKSHEET_ORDERS]["Label"], ["str:Early", "str:Late"])

    def test_scatter_appends_unlisted_categories_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            dataset = Dataset(frame())
            ordered(dataset, "Visit", ["Early", "Late", "Absent"])
            path = Path(folder) / "fixture.alab"
            save_project(path, {"Study": dataset})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 5)
            tables, _ = load_workspace(path)
            reopened = tables["Study"]
            self.assertEqual(reopened.raw.attrs[WORKSHEET_ORDERS], dataset.raw.attrs[WORKSHEET_ORDERS])
            result = analyse("Scatter / confidence ellipse", reopened.frame(), {"X": "Time", "Y": "Signal", "Group": "Visit"})
            self.assertEqual(legend(result), ["Early", "Late", "Middle"])
            self.assertEqual([list(item.get_offsets()[:, 1]) for item in result.figure.axes[0].collections],
                             [[2, 4], [9, 7], [6, 5]])
            set_order(reopened, "Visit", [])
            save_project(path, tables)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 2)

    def test_scatter_ellipse_legend_uses_its_own_category_order(self):
        from analisi.ellipse_workbench import HULL, SEPARATE_GROUP

        data = Dataset(pd.DataFrame({"X": [0, 0, 1, 10, 10, 11], "Y": [0, 1, 0, 10, 11, 10],
                                     "Contour": ["Late"] * 3 + ["Early"] * 3}))
        ordered(data, "Contour", ["Early", "Late"])
        result = analyse("Scatter / confidence ellipse", data.frame(), {
            "X": "X", "Y": "Y", "Ellipse": HULL, "Ellipse grouping": SEPARATE_GROUP, "Ellipse group": "Contour",
        })
        self.assertEqual(legend(result), ["Contour · Early", "Contour · Late"])
        self.assertEqual(result.tables["Confidence overlays"]["N"].tolist(), [3, 3])

    def test_draft_does_not_change_raw_data_and_keeps_mixed_types_distinct(self):
        raw = pd.DataFrame({"Group": pd.Series([1, 1.0, "1", True, None], dtype=object)})
        data = Dataset(raw)
        draft = OrderDraft(data, "Group")
        self.assertEqual(len(draft.levels), 4)
        self.assertIsNone(draft.result())
        self.assertEqual(draft.move(3, -1), 2)
        set_order(data, "Group", draft.result())
        self.assertEqual(data.raw.attrs[WORKSHEET_ORDERS]["Group"], ["int:1", "float:1.0", "bool:True", "str:1"])
        self.assertNotIn(WORKSHEET_ORDERS, raw.attrs)
        restored = OrderDraft(data, "Group")
        restored.restore_automatic()
        self.assertEqual(restored.result(), [])

    def test_remove_preserves_other_orders_and_rename_participates_in_undo(self):
        from trama_qt.project import Project

        project = Project()
        title, = project.add_tables({"Study": frame()})
        data = project.tables[title]
        ordered(data, "Visit", ["Early", "Late"])
        ordered(data, "Treatment", ["Vehicle", "Drug"])
        project.rename_column(title, 0, "Visit label")
        self.assertEqual(list(data.raw.attrs[WORKSHEET_ORDERS]), ["Visit label", "Treatment"])
        project.delete_columns(title, [0])
        self.assertEqual(list(data.raw.attrs[WORKSHEET_ORDERS]), ["Treatment"])
        project.undo()
        self.assertEqual(list(data.raw.attrs[WORKSHEET_ORDERS]), ["Visit label", "Treatment"])
        project.undo()
        self.assertEqual(list(data.raw.attrs[WORKSHEET_ORDERS]), ["Visit", "Treatment"])


from tests.test_graph_i18n import TkCase


class CategoryOrderTkTests(TkCase):
    def test_change_menu_applies_one_undoable_order(self):
        from analisi.category_order_dialog import CategoryOrderDialog
        from tramastat import App

        self.use("it")
        self.root.deiconify()
        app = App(self.root, standard_only=True)
        self.addCleanup(app.worker.shutdown)
        app._add_tables({"Study": frame()})
        app.show("data", "Study")
        self.root.update()
        app.current_grid.select_block(0, 0, 0, 0)
        menu, index = app.menu_entries["Change", "Category order…"]
        self.assertEqual(menu.entrycget(index, "label"), "Ordine categorie…")
        real_body = CategoryOrderDialog.body

        def body(dialog, master):
            result = real_body(dialog, master)
            dialog.after(100, lambda: (dialog.down.invoke(), dialog.ok()))
            return result

        with patch.object(CategoryOrderDialog, "body", body):
            menu.invoke(index)
        raw = app.tables["Study"].raw
        self.assertEqual(raw.attrs[WORKSHEET_ORDERS]["Visit"], ["str:Early", "str:Late", "str:Middle"])
        app.apply_worksheet_history()
        self.assertNotIn(WORKSHEET_ORDERS, app.tables["Study"].raw.attrs)
