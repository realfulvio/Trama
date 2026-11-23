"""Long and wide reshape through the Classica analysis dialog."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pandas as pd

from analisi import reshape_long_wide as rl
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase


class ReshapeClassicaTests(TkCase):
    frame = pd.DataFrame({
        "Campione $": ["001", "001", "002", "002"],
        "Visita": ["A | inizio", "Fine à", "A | inizio", "Fine à"],
        "Misura": [5, 6, 8, None],
    })

    def drive(self, action, frame=None, options=None, launch=None):
        from tramastat import AnalysisDialog

        errors = []

        def verify(dialog):
            try:
                action(dialog)
            except Exception as error:
                errors.append(error)
            finally:
                if dialog.winfo_exists():
                    dialog.destroy()

        drive_mapped_dialog(self.root, AnalysisDialog, verify, errors)
        if launch is None:
            data = self.frame if frame is None else frame
            current = (rl.METHOD, options) if options is not None else None
            result = AnalysisDialog(self.root, data, current=current).result
        else:
            result = launch()
        if errors:
            raise errors[0]
        return result

    def test_find_the_command_and_preview_a_long_to_wide_result(self):
        self.use("it")

        def create(dialog):
            dialog.query.set("rimodella")
            self.assertIn(rl.METHOD, dialog.method_by_item.values())
            item = next(key for key, name in dialog.method_by_item.items() if name == rl.METHOD)
            dialog.methods.selection_set(item)
            dialog.select_method()
            dialog.reshape.refresh_preview()
            preview = dialog.reshape.preview
            data = [preview.item(row, "values") for row in preview.get_children()]
            self.assertEqual(data, [("001", "5", "6"), ("002", "8", "")])
            self.assertTrue(dialog.validate())

        method, options = self.drive(create)
        self.assertEqual(method, rl.METHOD)
        self.assertEqual(options, {
            "Direction": "Long to wide", "ID columns": ["Campione $"],
            "Name column": "Visita", "Value column": "Misura",
        })
        result = rl.reshape_long_wide(self.frame, options)
        self.assertEqual(list(result.tables[rl.TABLE]), ["Campione $", "A | inizio", "Fine à"])
        self.assertEqual(result.tables[rl.SOURCE_MAP].shape, (4, 4))

    def test_change_directions_and_preserve_order_while_editing(self):
        frame = pd.DataFrame({"ID": ["001", "002"], "Early": [2, 4], "Later": [3, None]})
        saved = {
            rl.DIRECTION: rl.WIDE_TO_LONG, rl.ID_COLUMNS: ["ID"], rl.MEASURE_COLUMNS: ["Later", "Early"],
            rl.OUTPUT_NAMES: "Tempo", rl.OUTPUT_VALUES: "Valore", rl.DROP_MISSING: True,
        }

        def edit(dialog):
            controls = dialog.controls
            direction = controls[rl.DIRECTION][1]
            direction.set(rl.LONG_TO_WIDE)
            self.assertEqual(dialog.field_rows[rl.MEASURE_COLUMNS][1].winfo_manager(), "")
            direction.set(rl.WIDE_TO_LONG)
            measures = controls[rl.MEASURE_COLUMNS][1]
            self.assertEqual(measures.values(), ["Later", "Early"])
            measures.listbox.activate(0)
            measures.move(1)
            self.assertEqual(measures.values(), ["Early", "Later"])
            controls[rl.OUTPUT_NAMES][1].set("Valore")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            self.assertTrue(warning.called)
            self.assertIs(dialog.initial_focus, dialog.field_rows[rl.OUTPUT_VALUES][1])
            controls[rl.OUTPUT_NAMES][1].set("Tempo")
            self.assertTrue(dialog.validate())

        method, options = self.drive(edit, frame=frame, options=saved)
        self.assertEqual(method, rl.METHOD)
        self.assertEqual(options, {**saved, rl.MEASURE_COLUMNS: ["Early", "Later"]})
        result = rl.reshape_long_wide(frame, options).tables[rl.TABLE]
        self.assertEqual(result[["ID", "Tempo", "Valore"]].values.tolist(),
                         [["001", "Early", 2], ["001", "Later", 3], ["002", "Early", 4]])

    def test_create_edit_and_reopen_from_the_classica_window(self):
        from tramastat import App

        self.root.deiconify()
        app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(app.worker.shutdown)
        self.addCleanup(app._clear, "")
        errors = []
        app.error = errors.append
        app._add_tables({"Experiment": self.frame})

        def result():
            deadline = time.monotonic() + 10

            def poll():
                if app.pending is None or time.monotonic() >= deadline:
                    self.root.quit()
                else:
                    self.root.after(10, poll)

            self.root.after(0, poll)
            self.root.mainloop()
            self.assertIsNone(app.pending)
            self.assertFalse(errors, errors)
            run = app.runs[0]
            self.assertIsNotNone(run.result)
            return run

        self.drive(lambda dialog: dialog.ok(), launch=lambda: app.choose_analysis(rl.METHOD))
        first = result()
        self.assertEqual(first.result.tables[rl.TABLE].shape, (2, 3))
        app.show("result", 0)

        def edit(dialog):
            dialog.controls[rl.DIRECTION][1].set(rl.WIDE_TO_LONG)
            ids = dialog.controls[rl.ID_COLUMNS][1]
            ids.listbox.selection_set(ids.columns.index("Visita"))
            ids.listbox.event_generate("<<ListboxSelect>>")
            dialog.controls[rl.DROP_MISSING][1].set(True)
            dialog.ok()

        self.drive(edit, launch=app.edit_analysis)
        self.assertEqual(app.cancel_button.winfo_manager(), "pack")
        app.cancel_button.invoke()
        self.assertIs(result(), first)

        self.drive(edit, launch=app.edit_analysis)
        edited = result()
        self.assertEqual(edited.uid, first.uid)
        self.assertEqual(edited.options[rl.ID_COLUMNS], ["Campione $", "Visita"])
        self.assertEqual(edited.result.tables[rl.TABLE].shape, (3, 4))

        with TemporaryDirectory() as directory:
            file = Path(directory) / "measurements.alab"
            with patch("tramastat.filedialog.asksaveasfilename", return_value=str(file)):
                self.assertTrue(app.save())
            copied = file.with_name("reopen.alab")
            copied.write_bytes(file.read_bytes())
            self.assertTrue(app.open_document(copied))
            app.open_sheet(("result", 0))
            reopened = result()
        self.assertEqual(reopened.options, edited.options)
        table = reopened.result.tables[rl.TABLE]
        # ALAB normalizes the pandas missing-value marker while preserving text and numeric columns.
        pd.testing.assert_frame_equal(table, edited.result.tables[rl.TABLE], check_dtype=False)
        self.assertTrue(pd.api.types.is_string_dtype(table["Campione $"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(table["Value"]))
