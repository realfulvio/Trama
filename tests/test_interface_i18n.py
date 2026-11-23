"""Real Tk coverage for common captions and canonical analysis recipes."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi.workbench import GROUPS, METHODS
from tests.test_graph_i18n import LanguageMixin, TkCase, descendants
from analisi import ttest_options as tt


class InterfaceCatalogTests(LanguageMixin, unittest.TestCase):
    def test_analysis_groups_and_methods_are_catalogued(self):
        self.use("it")
        unchanged = {"Mann–Whitney", "Kruskal–Wallis", "Friedman", "Bland–Altman", "Kolmogorov–Smirnov"}
        for label in (*GROUPS, *METHODS):
            self.assertIn(label, i18n.KEY_BY_LABEL, label)
            if label not in unchanged:
                self.assertNotEqual(i18n.ui(label), label, label)

    def test_every_analysis_field_has_an_explicit_caption(self):
        for method, fields in METHODS.items():
            for field in fields:
                self.assertIn(field, i18n.KEY_BY_LABEL, (method, field))

    def test_unknown_captions_stay_literal_and_english_is_exact(self):
        for code in ("en", "it"):
            self.use(code)
            self.assertEqual(i18n.ui("My {Mean} experiment"), "My {Mean} experiment")
            self.assertEqual(i18n.ui("Unregistered imported phrase"), "Unregistered imported phrase")
        self.use("en")
        for text in i18n.KEY_BY_LABEL:
            self.assertEqual(i18n.ui(text), text)


class InterfaceDialogTests(TkCase):
    def drive_dialog(self, dialog_class, callback, *args, **kwargs):
        seen = {}

        def drive():
            dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, dialog_class))
            try:
                callback(dialog, seen)
            except BaseException as error:
                seen["error"] = error
            finally:
                dialog.cancel()

        self.root.deiconify()
        self.root.after(100, drive)
        dialog_class(self.root, *args, **kwargs)
        self.root.withdraw()
        if "error" in seen:
            raise seen["error"]
        return seen

    def test_analysis_dialog_translates_only_interface_and_roundtrips_choices(self):
        from tramastat import AnalysisDialog
        data = pd.DataFrame({"Mean": [1., 2., 3., 4.], "Control": ["A", "B", "A", "B"],
                             "ID": [1, 1, 2, 2]})
        saved = {"Design": "Paired", "Response": "Mean", "Group": "Control", "Subject": ""}
        snapshots = {}
        for code in ("en", "it"):
            self.use(code)

            def inspect(dialog, seen):
                labels = {widget.cget("text") for widget in descendants(dialog) if "text" in widget.keys()}
                self.assertIn("Esegui analisi" if code == "it" else "Run Analysis", labels)
                self.assertIn("Annulla" if code == "it" else "Cancel", labels)
                self.assertEqual(dialog.title(), "Analizza dati" if code == "it" else "Analyze Data")
                self.assertEqual(dialog.field_rows["Response"][0].cget("text"), "Risposta" if code == "it" else "Response")
                self.assertEqual(dialog.fields.tab(0, "text"), "Variabili" if code == "it" else "Variables")
                combo = dialog.field_rows["Design"][1]
                self.assertEqual(combo.get(), "Appaiato" if code == "it" else "Paired")
                self.assertEqual(dialog.controls["Design"][1].get(), "Paired")
                combo.current(3)  # Canonical One-sample, despite the translated display.
                self.assertEqual(dialog.controls["Design"][1].get(), "One-sample")
                dialog.controls["Design"][1].set("Paired")
                self.assertEqual(dialog.field_rows["Response"][1].get(), "Mean")
                self.assertEqual(tuple(dialog.field_rows["Response"][1]["values"]), ("Mean", "Control", "ID"))
                self.assertEqual(dialog.field_rows["Group"][1].get(), "Control")
                with patch("tramastat.messagebox.showerror") as error:
                    self.assertFalse(dialog.validate())
                    error.assert_called_once()
                    dialog.controls["Subject"][1].set("ID")
                    self.assertTrue(dialog.validate(), error.call_args)
                seen["result"] = deepcopy(dialog.result)

            snapshots[code] = self.drive_dialog(AnalysisDialog, inspect, data,
                                                  current=("t-test", deepcopy(saved)), only="t-test")["result"]
        self.assertEqual(snapshots["it"], snapshots["en"])
        self.assertEqual(snapshots["it"], ("t-test", {**saved, "Subject": "ID", tt.INPUT: tt.GROUPED,
                                                       tt.ALTERNATIVE: tt.TWO_SIDED, tt.LEVEL: 95.,
                                                       tt.REVERSE: False, tt.DETAILS: False}))
        self.assertEqual(data.columns.tolist(), ["Mean", "Control", "ID"])

    def test_translated_method_search_and_dispatch_keep_canonical_identifier(self):
        from tramastat import AnalysisDialog
        self.use("it")

        def inspect(dialog, _):
            for needle in ("regressione lineare", "linear regression"):
                dialog.query.set(needle)
                methods = list(dialog.method_by_item.values())
                self.assertIn("Linear regression", methods)
            item = next(item for item, method in dialog.method_by_item.items() if method == "Linear regression")
            self.assertEqual(dialog.methods.item(item, "text"), "Regressione lineare")
            dialog.methods.selection_set(item)
            dialog.select_method()
            self.assertEqual(dialog.method, "Linear regression")
            self.assertEqual(dialog.heading.cget("text"), "Regressione lineare")
            self.assertEqual(dialog.controls["X"][1].get(), "Mean")
            dialog.methods.selection_set(dialog.methods.parent(item))
            dialog.select_method()  # A translated group heading is never a method.
            self.assertEqual(dialog.method, "Linear regression")

        self.drive_dialog(AnalysisDialog, inspect, pd.DataFrame({"Mean": [1., 2., 3.], "Control": [2., 4., 6.]}))

    def test_dynamic_fixed_choices_keep_translated_displays_and_canonical_values(self):
        from tramastat import AnalysisDialog
        self.use("it")
        data = pd.DataFrame({"Mean": [1., 2., 3.], "Control": [2., 3., 4.]})

        def grouped(dialog, _):
            dialog.controls["Placement of groups"][1].set("Stacked")
            self.assertEqual(tuple(dialog.field_rows["Graph style"][1]["values"]), ("Barre",))
            self.assertEqual(dialog.controls["Graph style"][1].get(), "Bars")
            dialog.controls["Placement of groups"][1].set("Interleaved")
            dialog.controls["Graph style"][1].set("Individual points")
            self.assertEqual(dialog.field_rows["Graph style"][1].get(), "Punti individuali")

        self.drive_dialog(AnalysisDialog, grouped, data, only="Grouped graph")

        def row_tests(dialog, _):
            dialog.controls["Input format"][1].set("Mean, SD and N")
            combo = dialog.field_rows["Test"][1]
            self.assertEqual(tuple(combo["values"]), ("Test t di Welch", "Test t di Student"))
            combo.current(1)
            self.assertEqual(dialog.controls["Test"][1].get(), "Student t-test")
            dialog.controls["Input format"][1].set("Raw replicates")
            self.assertIn("Test t appaiato", combo["values"])

        self.drive_dialog(AnalysisDialog, row_tests, data, only="Multiple tests (one per row)")

    def test_paste_dialog_common_labels_preserve_address_and_cells(self):
        from tramastat import PasteSpecialDialog
        self.use("it")
        rows = [["Mean", "Control"], ["1.25", "2.50"]]

        def inspect(dialog, seen):
            labels = {widget.cget("text") for widget in descendants(dialog) if "text" in widget.keys()}
            self.assertEqual(dialog.title(), "Incolla speciale")
            self.assertTrue({"Filtra righe", "Prima riga", "Ultima riga", "Righe da saltare", "Incolla", "Annulla"} <= labels)
            self.assertTrue(dialog.validate())
            seen["rows"] = dialog.result

        seen = self.drive_dialog(PasteSpecialDialog, inspect, rows, "Mean")
        self.assertEqual(seen["rows"], rows)

    def test_data_grid_keeps_user_titles_and_column_names_literal(self):
        from tramastat import Grid
        self.use("it")
        data = pd.DataFrame({"Mean": ["Control"], "Control": ["Mean"]})
        data.index.name = "Mean"
        grid = Grid(self.root, data)
        self.addCleanup(grid.destroy)
        self.assertEqual(grid.cells.bands[0][3], "Mean")
        headings = [band[3] for band in grid.cells.bands[1:]]
        self.assertEqual(headings, ["Mean", "Control"])
        self.assertEqual(tuple(grid.cells.cell_text(0, col) for col in (1, 2)), ("Control", "Mean"))
