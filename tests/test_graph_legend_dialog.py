"""Tk GUI and transaction tests for LegendEditorDialog, GraphFormatDialog, and GraphInspector."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image

from analisi import ui_theme
from analisi.graph_dialog import GraphFormatDialog
from analisi.graph_inspector import GraphInspector
from analisi.graph_legend import LEGEND_OPTIONS_KEY, typed_group_token
from analisi.graph_legend_dialog import FRAME_HIDDEN, FRAME_SHOWN, LegendEditorDialog
from analisi.i18n import active_language, set_language
from analisi.presentation import apply_style
from analisi.workbench import _preview_figure


def _find_child(parent, cls):
    for child in parent.winfo_children():
        if isinstance(child, cls):
            return child
        found = _find_child(child, cls)
        if found is not None:
            return found
    return None


def _make_figure():
    fig = Figure(figsize=(5, 4), dpi=100)
    ax = fig.add_subplot()
    s1 = ax.scatter([0.0, 1.0], [1.0, 2.0], label="1")
    s1._tramastat_legend_key = f"group:{typed_group_token(1)}"
    s2 = ax.scatter([0.0, 1.0], [2.0, 3.0], label="1")
    s2._tramastat_legend_key = f"group:{typed_group_token('1')}"
    ax.legend()
    return fig, ax


class LegendDialogGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.root = tk.Tk()
        except Exception as error:
            raise unittest.SkipTest(f"Tk is not available: {error}")
        cls.root.geometry("1024x768+0+0")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def use_lang(self, code):
        prev = active_language()
        set_language(code)
        self.addCleanup(set_language, prev)

    def use_theme(self, theme):
        prev = ui_theme._state.get("theme", "standard")
        ui_theme.configure(self.root, theme)
        self.addCleanup(ui_theme.configure, self.root, prev)

    def _drive_modal(self, parent, cls, fn, errors):
        def step():
            dlg = _find_child(parent, cls)
            if dlg is None:
                errors.append(AssertionError(f"{cls.__name__} did not open"))
                return
            try:
                fn(dlg)
            except Exception as exc:
                errors.append(exc)
                if dlg.winfo_exists():
                    dlg.cancel()

        self.root.after(100, step)

    def _assert_fits_1024x768(self, dlg, buttons):
        dlg.update()
        self.assertLessEqual(dlg.winfo_reqwidth(), 1024)
        self.assertLessEqual(dlg.winfo_reqheight(), 720)
        bottom = dlg.winfo_rooty() + dlg.winfo_height()
        for btn in buttons:
            self.assertTrue(btn.winfo_viewable(), btn)
            self.assertLessEqual(btn.winfo_rooty() + btn.winfo_height(), bottom + 2)

    def test_inline_error_focus_recovery_reset_and_cancel_en_and_it(self):
        for lang, theme in (("en", "standard"), ("it", "modern")):
            with self.subTest(lang=lang, theme=theme):
                self.use_lang(lang)
                self.use_theme(theme)
                fig, ax = _make_figure()
                base = {LEGEND_OPTIONS_KEY: {"title": "Confirmed"}}
                apply_style(fig, base)
                errors = []

                def preview_cb(opts):
                    candidate = {} if opts is None else ({LEGEND_OPTIONS_KEY: opts} if opts else {})
                    if opts is None:
                        apply_style(fig, base)
                    else:
                        apply_style(fig, candidate)

                def drive(dlg):
                    self._assert_fits_1024x768(
                        dlg, (dlg.reset_button, dlg.preview_button, dlg.apply_button, dlg.cancel_button)
                    )
                    # Invalid columns -> inline error near columns, stays open, focuses columns, no mutation.
                    dlg.fields["columns"].set("0")
                    self.assertFalse(dlg.preview())
                    self.assertTrue(dlg.winfo_exists())
                    self.assertIs(dlg.error_widget, dlg.widgets["columns"])
                    self.assertTrue(dlg.error_labels["columns"].winfo_ismapped())
                    self.assertEqual(ax.get_legend().get_title().get_text(), "Confirmed")

                    # Invalid alpha -> inline error near alpha.
                    dlg.fields["columns"].set("2")
                    dlg.fields["alpha"].set("nan")
                    self.assertFalse(dlg.validate())
                    self.assertTrue(dlg.winfo_exists())
                    self.assertIs(dlg.error_widget, dlg.widgets["alpha"])
                    self.assertTrue(dlg.error_labels["alpha"].winfo_ismapped())

                    # Preview 1 -> Preview 2 -> Reset restores pre-preview baseline (empty), NOT Preview 1.
                    dlg.fields["alpha"].set("0,35" if lang == "it" else "0.35")
                    dlg.fields["title"].set("Preview 1")
                    self.assertTrue(dlg.preview())
                    self.assertEqual(ax.get_legend().get_title().get_text(), "Preview 1")

                    dlg.fields["title"].set("Preview 2")
                    dlg.fields["reverse"].set(True)
                    self.assertTrue(dlg.preview())
                    self.assertEqual(ax.get_legend().get_title().get_text(), "Preview 2")

                    dlg.reset_fields()
                    self.assertEqual(dlg.fields["title"].get(), "")
                    self.assertEqual(ax.get_legend().get_title().get_text(), "")
                    self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["1", "1"])

                    # Cancel restores confirmed pre-dialog title.
                    dlg.cancel()

                self._drive_modal(self.root, LegendEditorDialog, drive, errors)
                dlg = LegendEditorDialog(self.root, fig, base[LEGEND_OPTIONS_KEY], preview=preview_cb)
                self.assertEqual(errors, [])
                self.assertIsNone(dlg.result)
                self.assertEqual(ax.get_legend().get_title().get_text(), "Confirmed")

    def test_format_graph_and_inspector_share_editor_and_transactions(self):
        self.use_lang("en")
        self.use_theme("standard")
        fig, ax = _make_figure()
        holder = SimpleNamespace(winfo_children=lambda: [])
        import tkinter as tk
        frame = tk.Frame(self.root)
        self.addCleanup(frame.destroy)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        run = SimpleNamespace(method="Scatter / confidence ellipse", result=SimpleNamespace(figure=fig, style_warning=None), style={})
        committed = []
        inspector = GraphInspector(
            frame,
            run,
            canvas,
            None,
            confirmed=lambda: run.style,
            commit=lambda style: (committed.append(style), setattr(run, "style", style)),
            closed=lambda: None,
        )
        self.addCleanup(inspector.dispose)

        # Open shared LegendEditorDialog from Inspector, apply draft, then Cancel Inspector -> no commit.
        errors = []

        def drive_editor(dlg):
            dlg.fields["title"].set("Literal {A} $B$")
            dlg.fields["columns"].set("2")
            dlg.fields["frame"].set(FRAME_HIDDEN)
            dlg.fields["facecolor"].set("#112233")
            dlg.fields["edgecolor"].set("#445566")
            dlg.fields["width"].set("2.0")
            dlg.fields["alpha"].set("0.5")
            dlg.fields["reverse"].set(True)
            dlg.entry_vars["group:int:1"].set("Numeric $1$")
            dlg.entry_vars["group:str:1"].set("Text {1}")
            dlg.ok()

        self._drive_modal(inspector, LegendEditorDialog, drive_editor, errors)
        inspector.widgets["legend_options"].invoke()
        self.assertEqual(errors, [])
        self.assertEqual(ax.get_legend().get_title().get_text(), "Literal {A} $B$")
        self.assertFalse(ax.get_legend().get_frame_on())
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Text {1}", "Numeric $1$"])
        self.assertEqual(committed, [])

        inspector.discard()
        self.assertEqual(ax.get_legend().get_title().get_text(), "")
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["1", "1"])

        # Apply through Inspector commits legend_options.
        self._drive_modal(inspector, LegendEditorDialog, drive_editor, errors)
        inspector.widgets["legend_options"].invoke()
        self.assertEqual(errors, [])
        self.assertTrue(inspector.apply())
        self.assertEqual(len(committed), 1)
        self.assertEqual(run.style[LEGEND_OPTIONS_KEY]["frame"], False)
        self.assertEqual(run.style[LEGEND_OPTIONS_KEY]["facecolor"], "#112233")

        # Reset page section clears legend_options from draft and restores legend on preview.
        inspector.reset_section("page")
        self.assertNotIn(LEGEND_OPTIONS_KEY, inspector.draft)
        self.assertEqual(ax.get_legend().get_title().get_text(), "")
        inspector.discard()

        # Now test GraphFormatDialog opening the same LegendEditorDialog.
        def drive_format(fdlg):
            def drive_child(ldlg):
                ldlg.fields["title"].set("From Format")
                ldlg.fields["frame"].set(FRAME_SHOWN)
                ldlg.fields["columns"].set("2")
                ldlg.ok()

            self._drive_modal(fdlg, LegendEditorDialog, drive_child, errors)
            fdlg.legend_button.invoke()
            self.assertEqual(errors, [])
            fdlg.ok()

        self._drive_modal(self.root, GraphFormatDialog, drive_format, errors)
        fdlg = GraphFormatDialog(self.root, ax, deepcopy(run.style))
        self.assertEqual(errors, [])
        self.assertIsNotNone(fdlg.result)
        self.assertEqual(fdlg.result[LEGEND_OPTIONS_KEY]["title"], "From Format")
        self.assertEqual(fdlg.result[LEGEND_OPTIONS_KEY]["columns"], 2)

    def test_non_native_raster_dialog_shows_limitation_and_blocks_apply(self):
        self.use_lang("it")
        fig = _preview_figure(Image.new("RGBA", (32, 32), (255, 255, 255, 255)))
        errors = []

        def drive(dlg):
            self.assertTrue(dlg.non_native)
            self.assertIn("disabled", dlg.apply_button.state())
            self.assertIn("disabled", dlg.preview_button.state())
            self.assertFalse(dlg.validate())
            dlg.cancel()

        self._drive_modal(self.root, LegendEditorDialog, drive, errors)
        dlg = LegendEditorDialog(self.root, fig, {})
        self.assertEqual(errors, [])
        self.assertIsNone(dlg.result)


if __name__ == "__main__":
    unittest.main()
