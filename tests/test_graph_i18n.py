"""Italian in Format Graph and the Inspector: catalog, canonical choices and literal user text."""
import ast
from copy import deepcopy
import gc
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from analisi import i18n
from analisi.i18n import CATALOGS, active_language, placeholders, set_language, translate, translate_message

DATA = Path(__file__).resolve().parent / "data" / "i18n"
ROOT = Path(__file__).resolve().parents[1]


class LanguageMixin:
    def use(self, code):
        previous = active_language()
        set_language(code)
        self.addCleanup(set_language, previous)


class GraphCatalog(LanguageMixin, unittest.TestCase):
    def test_package_fixture(self):
        fixture = json.loads((DATA / "graph.json").read_text(encoding="utf-8"))
        keys = [row[0] for row in fixture["labels"]]
        self.assertEqual(len(keys), len(set(keys)))
        for key, english, italian in fixture["labels"]:
            self.assertEqual(translate("en", key), english, key)
            self.assertEqual(translate("it", key), italian, key)

    def test_graph_keys_have_both_languages_and_matching_placeholders(self):
        graph = [key for key in CATALOGS["en"] if key.startswith("graph.")]
        self.assertGreater(len(graph), 100)
        for key in graph:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_engine_messages_still_exist_in_the_validator(self):
        # The Italian text is found through the English one: keep the catalog in step with presentation.py.
        tree = ast.parse((ROOT / "analisi" / "presentation.py").read_text(encoding="utf-8"))
        source = "\n".join(node.value for node in ast.walk(tree)
                           if isinstance(node, ast.Constant) and isinstance(node.value, str))
        # The stacked-bar message names the scale through a placeholder of its own.
        source = source.replace(" axis cannot use a \n scale.", " axis cannot use a logarithmic scale.")
        source += source.replace("logarithmic scale.", "probability scale.")
        for key, text in CATALOGS["en"].items():
            if key.startswith("graph.error.") and key not in {"graph.error.float", "graph.error.int"}:
                fragments = [part for index, part in enumerate(i18n._PLACEHOLDER.split(text)) if index % 2 == 0]
                for fragment in filter(None, fragments):
                    self.assertIn(fragment, source, key)

    def test_messages_are_translated_with_literal_values(self):
        self.use("it")
        self.assertEqual(translate_message(ValueError("Choose a valid legend position.")),
                         "Scegli una posizione della legenda valida.")
        name = "Misure {A} – città & $x$"
        self.assertEqual(translate_message(f"This setting is not available for {name}."),
                         f"Questa impostazione non è disponibile per {name}.")
        self.assertEqual(translate_message("A probability axis accepts data from 0 to 100."),
                         "Un asse di probabilità accetta dati da 0 a 100.")
        self.assertEqual(translate_message("Something new from Matplotlib."), "Something new from Matplotlib.")

    def test_english_messages_are_untouched(self):
        self.use("en")
        self.assertEqual(translate_message("Choose a valid legend position."), "Choose a valid legend position.")


class TkCase(LanguageMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Finish disposal of earlier Tcl widgets on the Tk owner thread.
        gc.collect()
        try:
            import tkinter as tk
            cls.root = tk.Tk()
        except Exception as error:  # tkinter missing or no display
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.root = None
        gc.collect()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class ChoiceBindingTests(TkCase):
    def test_same_caption_in_two_controls_resolves_to_each_canonical_value(self):
        import tkinter as tk
        from tkinter import ttk
        from analisi.graph_dialog import RIGHT_SCALE_LABELS, SCALE_LABELS, ChoiceBinding

        self.use("it")
        left, right = tk.StringVar(self.root, "linear"), tk.StringVar(self.root, "Linear")
        seen = []
        left.trace_add("write", lambda *_: seen.append(left.get()))
        boxes = []
        for variable, values, labels in ((left, ("linear", "log"), SCALE_LABELS),
                                         (right, ("Linear", "Log"), RIGHT_SCALE_LABELS)):
            box = ttk.Combobox(self.root, state="readonly")
            self.addCleanup(box.destroy)
            ChoiceBinding(box, variable, values, labels)
            boxes.append(box)
        self.assertEqual([box.get() for box in boxes], ["Lineare", "Lineare"])
        for box in boxes:
            self.assertEqual(box.cget("values"), ("Lineare", "Logaritmica"))
            box.current(1)
        self.assertEqual((left.get(), right.get()), ("log", "Log"))
        self.assertEqual(seen, ["log"], "callbacks see only the canonical value")
        right.set("Linear")
        self.assertEqual(boxes[1].get(), "Lineare")

    def test_literal_and_empty_values_are_shown_as_they_are(self):
        import tkinter as tk
        from tkinter import ttk
        from analisi.graph_dialog import SIDE_LABELS, ChoiceBinding

        self.use("it")
        variable = tk.StringVar(self.root, "")
        box = ttk.Combobox(self.root, state="readonly")
        self.addCleanup(box.destroy)
        ChoiceBinding(box, variable, ("Left", "Right"), SIDE_LABELS)
        self.assertEqual(box.get(), "")
        variable.set("Destra")  # not a canonical value: stays literal, never mapped back
        self.assertEqual((box.get(), variable.get()), ("Destra", "Destra"))


class FormatGraphTests(TkCase):
    def run_dialog(self, axes, style, drive):
        from analisi.graph_dialog import GraphFormatDialog
        errors = []

        def step():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, GraphFormatDialog))
            try:
                drive(dialog)
            except Exception as error:  # reported after the modal loop returns
                errors.append(error)
                dialog.cancel()

        self.root.after(150, step)
        dialog = GraphFormatDialog(self.root, axes, style)
        if errors:
            raise errors[0]
        return dialog

    @staticmethod
    def axes():
        from matplotlib.figure import Figure
        axes = Figure().add_subplot()
        axes.plot([1, 2, 4], [2, 4, 7], label="Right")
        axes.plot([1, 2, 4], [3, 5, 6], label="Default")
        axes.legend()
        return axes

    def combo(self, dialog, label):
        from tkinter import ttk
        return next(w for w in descendants(dialog) if isinstance(w, ttk.Combobox) and label in w.cget("values"))

    def test_italian_choices_return_canonical_scale_and_legend(self):
        self.use("it")
        title = "Titolo {A} – città & $"

        def drive(dialog):
            self.assertEqual(dialog.title(), "Formato grafico")
            scale = self.combo(dialog, "Logaritmica")
            scale.current(scale.cget("values").index("Logaritmica"))
            scale.event_generate("<<ComboboxSelected>>")
            self.assertEqual(dialog.inputs["xscale"].get(), "log")
            disabled = [key for key, entry in self._axis_entries(dialog, "x").items() if entry.instate(["disabled"])]
            self.assertEqual(sorted(disabled), ["start", "step"], "log disables the incompatible tick fields")
            legend = self.combo(dialog, "in alto a destra")
            legend.current(legend.cget("values").index("in alto a destra"))
            dialog.inputs["title"].set(title)
            self.assertEqual(list(dialog.series_selector.cget("values")),
                             ["Linea · Right (1)", "Linea · Default (1)"], "series names stay literal")
            dialog.ok()

        dialog = self.run_dialog(self.axes(), {}, drive)
        self.assertEqual(dialog.result["xscale"], "log")
        self.assertEqual(dialog.result["legend"], "upper right")
        self.assertEqual(dialog.result["title"], title)

    def _axis_entries(self, dialog, dimension):
        from tkinter import ttk
        entries = {}
        for key, variable in dialog.axis_fields[dimension].items():
            entries[key] = next(w for w in descendants(dialog) if isinstance(w, ttk.Entry)
                                and not isinstance(w, ttk.Combobox) and w.cget("textvariable") == str(variable))
        return entries

    def test_saved_style_round_trips_unchanged_in_both_languages(self):
        saved = {"title": "Città {A} & $", "xscale": "log", "legend": "lower left", "frame": "box",
                 "grid": True, "grid_minor": False,
                 "series": {"line:1:Right": {"line_style": "dashed", "marker": "s"}}}
        for code in ("en", "it"):
            with self.subTest(code=code):
                self.use(code)
                dialog = self.run_dialog(self.axes(), deepcopy(saved), lambda dialog: dialog.ok())
                result = dialog.result
                for key in ("title", "xscale", "legend", "frame"):
                    self.assertEqual(result[key], saved[key], key)
                self.assertEqual(result["series"]["line:1:Right"], {"line_style": "dashed", "marker": "s"})

    def test_english_keeps_its_labels(self):
        self.use("en")

        def drive(dialog):
            self.assertEqual(dialog.title(), "Format Graph")
            legend = self.combo(dialog, "upper right")
            self.assertEqual(legend.cget("values")[0], "Analysis default")
            self.assertIn("Logarithmic", self.combo(dialog, "Linear").cget("values"))
            dialog.cancel()

        self.run_dialog(self.axes(), {}, drive)

    def test_validation_message_is_shown_in_italian(self):
        self.use("it")

        def drive(dialog):
            dialog.axis_fields["x"]["min"].set("5")
            with patch("tkinter.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            title, message = error.call_args.args
            self.assertEqual(title, "Controlla lo stile del grafico")
            self.assertEqual(message, "Inserisci entrambi i limiti dell'asse, oppure lasciali vuoti per "
                                      "l'intervallo automatico.")
            dialog.cancel()

        self.run_dialog(self.axes(), {}, drive)


class InspectorTests(TkCase):
    def open(self, style=None):
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from analisi.graph_inspector import GraphInspector
        from analisi.presentation import apply_style

        figure = FormatGraphTests.axes().figure
        figure.axes[0].set_title("Città {A} & $")
        self.run = SimpleNamespace(style=deepcopy(style) if style else None, result=SimpleNamespace(style_warning=None))
        self.committed = []
        if style:
            apply_style(figure, style)
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(figure, master=holder)
        panel = GraphInspector(holder, self.run, canvas, None, confirmed=lambda: self.run.style,
                               commit=self.committed.append, closed=lambda: None)
        self.addCleanup(panel.dispose)
        return panel

    def test_italian_panel_previews_canonical_values_and_cancel_restores(self):
        self.use("it")
        panel = self.open({"legend": "lower left"})
        self.assertEqual((panel.apply_button.cget("text"), panel.cancel_button.cget("text")), ("Applica", "Annulla"))
        self.assertFalse(panel.has_draft, "opening in Italian must not create a draft")
        legend = panel.choices["legend"].combobox
        self.assertEqual(legend.get(), "in basso a sinistra")
        legend.current(legend.cget("values").index("in alto a destra"))
        panel._now("legend")
        scale = panel.choices["yscale"].combobox
        scale.current(scale.cget("values").index("Logaritmica"))
        panel._now("yscale")
        self.assertEqual((panel.draft["legend"], panel.draft["yscale"]), ("upper right", "log"))
        panel.discard()
        self.assertEqual(panel.draft, {"legend": "lower left"})
        self.assertEqual(legend.get(), "in basso a sinistra")
        self.assertFalse(panel.has_draft)

    def test_marker_choices_follow_the_element_and_stay_canonical(self):
        self.use("it")
        panel = self.open()
        marker = panel.choices["element:marker"]
        self.assertIn("Nessun simbolo", marker.combobox.cget("values"), "line series may hide symbols")
        marker.combobox.current(marker.combobox.cget("values").index("Rombo"))
        panel._now("element:marker")
        key = panel.current["key"]
        self.assertEqual(panel.draft["series"][key]["marker"], "D")
        self.assertTrue(panel.apply())
        self.assertEqual(self.committed[-1]["series"][key], {"marker": "D"})

    def test_field_problems_are_in_italian(self):
        self.use("it")
        panel = self.open()
        panel.vars["xmin"].set("1")
        panel._now("xrange")
        self.assertEqual(panel.errors["xrange"],
                         "Inserisci entrambi i limiti, oppure lasciali vuoti per l'intervallo automatico.")
        self.assertFalse(panel.apply())
        self.assertEqual(panel.status.cget("text"), "Correggi i campi evidenziati, oppure premi Annulla.")

    def test_italian_xy_series_choices_store_canonical_codes_in_inspector(self):
        import pandas as pd
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from analisi.graph_inspector import GraphInspector
        from analisi.xy_series import XY_METHOD, xy_series

        self.use("it")
        frame = pd.DataFrame({"X": [1.0, 2.0, 3.0], "Controllo": [2.0, 4.0, 6.0]})
        result = xy_series(frame, {"X": "X", "Y columns": ["Controllo"],
                                   "Series style": {"Controllo": "Line and points"}})
        run = SimpleNamespace(method=XY_METHOD, style=None, result=SimpleNamespace(style_warning=None))
        committed = []
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(result.figure, master=holder)
        panel = GraphInspector(holder, run, canvas, None, confirmed=lambda: run.style,
                               commit=committed.append, closed=lambda: None)
        self.addCleanup(panel.dispose)
        marker = panel.choices["element:marker"]
        line_style = panel.choices["element:line_style"]
        self.assertIn("Nessun simbolo", marker.combobox.cget("values"))
        marker.combobox.current(marker.combobox.cget("values").index("Quadrato"))
        panel._now("element:marker")
        line_style.combobox.current(line_style.combobox.cget("values").index("tratteggiata"))
        panel._now("element:line_style")
        self.assertTrue(panel.apply())
        self.assertEqual(committed[-1]["series"]["xy:1:Controllo"], {"marker": "s", "line_style": "dashed"})

    def test_parts_style_dialog_translations_and_bar_explode_hiding(self):
        import pandas as pd
        from analisi.i18n import tr
        from analisi.parts_style_dialog import PartsStyleDialog

        self.use("it")
        self.assertEqual(tr("parts.style.title"), "Stili dei segmenti")
        self.assertEqual(tr("parts.style.edit_button"), "Modifica segmenti…")
        frame = pd.DataFrame({"Part": ["A", "B"], "Count": [10, 20]})
        observed = {}

        def drive():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, PartsStyleDialog))
            observed["title"] = dialog.title()
            observed["explode_manager"] = dialog.explode_entry.winfo_manager()
            dialog.color.set("#112233")
            dialog.visible.set(False)
            dialog.ok()

        self.root.after(150, drive)
        dialog = PartsStyleDialog(self.root, frame, {"Values": "Count", "Row titles": "Part",
                                                     "Graph style": "Horizontal slices"},
                                  {"row:1": {"explode": 0.2}})
        self.assertEqual(observed["title"], "Stili dei segmenti")
        self.assertEqual(observed["explode_manager"], "")
        self.assertEqual(dialog.result, {"row:1": {"color": "#112233", "visible": False, "explode": 0.2}})


if __name__ == "__main__":
    unittest.main()
