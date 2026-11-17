"""Real Tk widgets of the graph shapes editor: choices, errors, preview transactions and window size."""
from copy import deepcopy
import tkinter as tk
import unittest
import uuid

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.graph_shape_dialog import GraphShapesDialog, ShapeEditor, _resolve_choice, _ShapeFieldError
from analisi.graph_shapes import KINDS, LAYERS, LINE_STYLES, SHAPES, UNITS, validate_shapes
from analisi.i18n import active_language, set_language, tr
from analisi.presentation import apply_style

LINE = {"id": "00000000-0000-4000-8000-000000000011", "kind": "line", "units": "axes",
        "points": [[.1, .2], [.9, .8]], "stroke": "#c62b37", "width": 2.0, "line_style": "solid",
        "fill": None, "alpha": 1.0, "layer": "above"}
BOX = {"id": "00000000-0000-4000-8000-000000000012", "kind": "rectangle", "units": "data",
       "points": [[2.0, 3.0], [6.0, 7.0]], "stroke": "#216a94", "width": 1.5, "line_style": "dashed",
       "fill": "#dce8f5", "alpha": .5, "layer": "below"}


def figure(yscale="linear"):
    fig = Figure(figsize=(4, 3), dpi=100)
    FigureCanvasAgg(fig)
    axes = fig.add_axes([.2, .2, .6, .6])
    axes.plot([1, 2, 4, 6], [2, 4, 7, 8])
    axes.set_xlim(0, 10)
    axes.set_ylim(.5, 10)
    axes.set_yscale(yscale)
    return fig, axes


class ShapeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:  # pragma: no cover - headless machines without a display
            raise unittest.SkipTest(f"Tk display unavailable: {error}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def use(self, code):
        previous = active_language()
        set_language(code)
        self.addCleanup(set_language, previous)

    def modal(self, factory, action, *, parent=None):
        """Open a modal dialog, run ``action`` inside its event loop and return (dialog, action result)."""
        seen = {}
        parent = parent or self.root

        def drive():
            dialog = seen.get("dialog")
            if dialog is None or not dialog.winfo_exists():
                found = [child for child in parent.winfo_children() if isinstance(child, (ShapeEditor, GraphShapesDialog))
                         and child.winfo_exists() and child is not parent]
                if not found:
                    parent.after(20, drive)
                    return
                dialog = found[-1]
            dialog.update_idletasks()
            try:
                seen["result"] = action(dialog)
            except Exception as error:  # re-raised once the modal loop ends
                seen["error"] = error
            finally:
                if dialog.winfo_exists():
                    dialog.cancel()

        parent.after(50, drive)
        dialog = factory()
        if "error" in seen:
            raise seen["error"]
        return dialog, seen.get("result")

    # ShapeEditor ----------------------------------------------------------------------------------------------
    def test_italian_choices_resolve_to_canonical_values(self):
        self.use("it")
        _, axes = figure()

        def action(editor):
            self.assertEqual(editor.widgets["kind"].get(), "Linea")
            # A real selection through the combobox.
            box = editor.widgets["kind"]
            box.current(box.cget("values").index("Rettangolo"))
            box.event_generate("<<ComboboxSelected>>")
            self.assertEqual(editor.fields["kind"].get(), "rectangle")
            # A translated label written straight into the canonical variable is resolved by this control only.
            editor.fields["units"].set("Dati (asse Y sinistro)")
            editor.fields["layer"].set("Sotto i dati")
            editor.fields["line_style"].set("Tratteggiata")
            for name, value in zip(("x1", "y1", "x2", "y2"), ("6,5", "7", "2", "3,25")):
                editor.fields[name].set(value)
            editor.fields["fill"].set("#eeeeee")
            editor.fields["alpha"].set("0,4")
            record = editor.read_record()
            self.assertEqual(record["kind"], "rectangle")
            self.assertEqual(record["units"], "data")
            self.assertEqual(record["layer"], "below")
            self.assertEqual(record["line_style"], "dashed")
            self.assertEqual(record["points"], [[2.0, 3.25], [6.5, 7.0]])
            self.assertEqual(record["alpha"], .4)
            for key, values in (("kind", KINDS), ("units", UNITS), ("line_style", LINE_STYLES), ("layer", LAYERS)):
                self.assertIn(record[key], values, key)
            editor.fields["kind"].set("Foo")
            with self.assertRaises(_ShapeFieldError) as caught:
                editor.read_record()
            self.assertEqual(caught.exception.field, "kind")
            return record

        dialog, record = self.modal(lambda: ShapeEditor(self.root, axes), action)
        self.assertIsNone(dialog.result)
        self.assertEqual(validate_shapes([record]), [record])

    def test_resolve_choice_uses_only_its_own_control(self):
        self.use("it")
        _, axes = figure()

        def action(editor):
            self.assertEqual(_resolve_choice(editor.bindings["layer"], "Sopra i dati", "layer"), "above")
            self.assertEqual(_resolve_choice(editor.bindings["layer"], "above", "layer"), "above")
            # A label of another control is not a valid layer.
            with self.assertRaises(_ShapeFieldError):
                _resolve_choice(editor.bindings["layer"], "Linea", "layer")

        self.modal(lambda: ShapeEditor(self.root, axes), action)

    def test_line_has_no_fill_and_rectangle_keeps_it(self):
        _, axes = figure()
        record = dict(deepcopy(BOX), units="axes", points=[[.2, .3], [.7, .8]])

        def action(editor):
            self.assertIn("!disabled", editor.widgets["fill"].state() or ("!disabled",))
            editor.fields["kind"].set("line")
            self.assertIn("disabled", editor.widgets["fill"].state())
            line = editor.read_record()
            self.assertIsNone(line["fill"])
            self.assertEqual(line["points"], [[.2, .3], [.7, .8]])
            editor.fields["kind"].set("ellipse")
            self.assertEqual(editor.read_record()["fill"], "#dce8f5")
            editor.fields["fill"].set("")
            self.assertIsNone(editor.read_record()["fill"])
            self.assertTrue(editor.validate())

        dialog, _ = self.modal(lambda: ShapeEditor(self.root, axes, record), action)
        self.assertEqual(record["kind"], "rectangle")  # the caller's record is a copy

    def test_invalid_field_keeps_window_value_and_focus(self):
        self.use("en")
        _, axes = figure()

        def action(editor):
            editor.fields["width"].set("13")
            editor.ok()
            self.assertTrue(editor.winfo_exists())
            editor.update()
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.width"))
            self.assertIs(editor.focus_lastfor(), editor.widgets["width"])
            self.assertEqual(editor.fields["width"].get(), "13")
            editor.fields["width"].set("2,5")
            editor.fields["x2"].set("1.5")
            self.assertFalse(editor.validate())
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.fractions"))
            editor.update()
            self.assertIs(editor.focus_lastfor(), editor.widgets["x2"])
            editor.fields["x2"].set("abc")
            self.assertFalse(editor.validate())
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.coordinates"))
            editor.fields["x2"].set("0,2")
            editor.fields["y2"].set("0,3")
            self.assertFalse(editor.validate())
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.line_zero"))
            editor.fields["y2"].set("0,9")
            editor.fields["stroke"].set("not-a-colour")
            self.assertFalse(editor.validate())
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.stroke"))
            editor.fields["stroke"].set("#123456")
            editor.ok()

        dialog, _ = self.modal(lambda: ShapeEditor(self.root, axes), action)
        self.assertEqual(dialog.result["width"], 2.5)
        self.assertEqual(dialog.result["points"], [[.2, .3], [.2, .9]])
        uuid.UUID(dialog.result["id"])

    def test_data_coordinates_outside_log_domain_are_refused(self):
        _, axes = figure("log")

        def action(editor):
            editor.fields["units"].set("data")
            for name, value in zip(("x1", "y1", "x2", "y2"), ("1", "-1", "4", "5")):
                editor.fields[name].set(value)
            self.assertFalse(editor.validate())
            self.assertEqual(editor.problem.cget("text"), tr("shape.error.axis_domain"))
            editor.fields["y1"].set("2")
            self.assertTrue(editor.validate())

        self.modal(lambda: ShapeEditor(self.root, axes), action)

    def test_editor_fits_1024_by_768_with_buttons_visible(self):
        _, axes = figure()

        def action(editor):
            editor.update()
            self.assertLessEqual(editor.winfo_height(), 768)
            self.assertLessEqual(editor.winfo_width(), 1024)
            bottom = editor.winfo_rooty() + editor.winfo_height()
            for button in (editor.preview_button, editor.ok_button, editor.cancel_button):
                self.assertTrue(button.winfo_viewable())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), bottom)
            # Shrinking the window shrinks the scrolling body, never the buttons.
            editor.geometry(f"{editor.winfo_width()}x260")
            editor.update()
            self.assertLessEqual(editor.ok_button.winfo_rooty() + editor.ok_button.winfo_height(),
                                 editor.winfo_rooty() + editor.winfo_height())
            editor.widgets["layer"].focus_set()
            editor.update()
            first, last = editor.scrolled.canvas.yview()
            self.assertGreater(last, first)

        self.modal(lambda: ShapeEditor(self.root, axes), action)

    # GraphShapesDialog ----------------------------------------------------------------------------------------
    def test_list_actions_preview_cancel_and_apply(self):
        self.use("en")
        fig, axes = figure()
        confirmed = [deepcopy(LINE), deepcopy(BOX)]
        original = deepcopy(confirmed)
        calls = []

        def preview(records):
            calls.append(deepcopy(records))
            apply_style(fig, {} if records is None else {SHAPES: records})
            return None

        def action(dialog):
            self.assertEqual(dialog.tree.get_children(), ("0", "1"))
            self.assertEqual(dialog.tree.item("1")["values"][1], "Rectangle")
            dialog.tree.selection_set("0")
            dialog.update_buttons()
            dialog.duplicate()
            self.assertEqual(len(dialog.records), 3)
            self.assertNotEqual(dialog.records[1]["id"], LINE["id"])
            self.assertEqual({**dialog.records[1], "id": LINE["id"]}, LINE)
            ids = [record["id"] for record in dialog.records]
            dialog.tree.selection_set("2")
            dialog.move(-1)
            self.assertEqual([record["id"] for record in dialog.records], [ids[0], ids[2], ids[1]])
            self.assertEqual(dialog.tree.selection(), ("1",))
            dialog.move(1)
            self.assertEqual([record["id"] for record in dialog.records], ids)
            dialog.preview()
            self.assertEqual(len(axes._tramastat_shapes), 3)
            dialog.tree.selection_set("1")
            dialog.remove()
            # An active preview follows the draft.
            self.assertEqual(len(axes._tramastat_shapes), 2)
            self.assertEqual(confirmed, original)
            dialog.clear()
            self.assertEqual(dialog.records, [])
            self.assertEqual(len(axes._tramastat_shapes), 0)

        dialog, _ = self.modal(lambda: GraphShapesDialog(self.root, axes, confirmed, preview=preview), action)
        self.assertIsNone(dialog.result)
        self.assertIsNone(calls[-1])  # Cancel restored the confirmed graph
        self.assertEqual(confirmed, original)

        def apply(dialog):
            dialog.tree.selection_set("1")
            dialog.move(-1)
            dialog.ok()

        calls.clear()
        dialog, _ = self.modal(lambda: GraphShapesDialog(self.root, axes, confirmed, preview=preview), apply)
        self.assertEqual(dialog.result, [BOX, LINE])
        self.assertEqual(calls, [])  # Apply without a preview never drew a candidate
        self.assertEqual(confirmed, original)

    def test_child_preview_and_child_cancel_restore_parent_preview(self):
        fig, axes = figure()
        apply_style(fig, {SHAPES: [deepcopy(LINE)]})
        calls = []

        def preview(records):
            calls.append(deepcopy(records))
            apply_style(fig, {SHAPES: [deepcopy(LINE)] if records is None else records})
            return None

        def parent_action(dialog):
            def child(editor):
                editor.fields["kind"].set("ellipse")
                editor.fields["fill"].set("#ffcc00")
                self.assertTrue(editor.preview())
                self.assertEqual(len(axes._tramastat_shapes), 2)
                self.assertEqual(calls[-1][-1]["kind"], "ellipse")

            self.modal(lambda: dialog.add() or dialog, child, parent=dialog)
            # The child was cancelled: its candidate disappears and the draft is unchanged.
            self.assertEqual(len(dialog.records), 1)
            self.assertIsNone(calls[-1])
            self.assertEqual(len(axes._tramastat_shapes), 1)

        dialog, _ = self.modal(lambda: GraphShapesDialog(self.root, axes, [LINE], preview=preview), parent_action)
        self.assertIsNone(dialog.result)

    def test_limit_of_one_hundred_shapes(self):
        _, axes = figure()
        records = []
        for index in range(100):
            record = deepcopy(LINE)
            record["id"] = str(uuid.UUID(int=index + 1, version=4))
            records.append(record)

        def action(dialog):
            dialog.tree.selection_set("0")
            dialog.update_buttons()
            self.assertIn("disabled", dialog.buttons["add"].state())
            self.assertIn("disabled", dialog.buttons["duplicate"].state())
            dialog.duplicate()
            self.assertEqual(len(dialog.records), 100)
            self.assertEqual(dialog.message.cget("text"), tr("shape.error.limit"))

        self.modal(lambda: GraphShapesDialog(self.root, axes, records), action)


class SharedBehaviourTests(unittest.TestCase):
    def test_reopened_integer_columns_stay_integer(self):
        import tempfile
        from pathlib import Path

        dataset = Dataset(pd.DataFrame({"ID": [1, 2, 3], "Y": [1.5, 2.0, 3.25]}))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "types.alab"
            save_project(path, {"Types": dataset})
            restored = load_project(path)["Types"]
        self.assertEqual(str(restored.raw["ID"].dtype), "Int64")

    def test_probability_axis_still_rejects_data_outside_its_range_with_shapes(self):
        fig, _ = figure()
        with self.assertRaisesRegex(ValueError, "probability axis accepts data"):
            apply_style(fig, {"yscale": "probability", SHAPES: [deepcopy(LINE)]})


if __name__ == "__main__":
    unittest.main()
