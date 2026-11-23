"""Linked secondary axes on the Qt window, offscreen: Format Graph, the Inspector and the editor dialog.

Skipped when PySide6 (or the Qt platform libraries) are not installed. Every fixture is synthetic.
"""
import unittest
from unittest import mock

import pandas as pd

try:
    from PySide6.QtCore import Qt
except ImportError:  # PySide6 missing, or the Qt platform libraries on a headless machine
    Qt = None

from analisi.i18n import active_language, set_language, tr
from analisi.linked_axes import GID_PREFIX, linked_children
from tests import test_qt_shell as shell  # the module, so the runner does not collect its tests twice

QApplication = shell.QApplication

LINKED_TOP = {"x": {"multiplier": 2.0, "offset": 1.0, "label": "Twice plus one"}}
LINKED_BOTH = {"x": {"multiplier": 10.0, "offset": 0.0, "label": "Millimetres"},
               "y": {"multiplier": 0.5, "offset": -2.0, "label": "Half minus two"}}


def children(figure):
    """The secondary axes of the first axes of ``figure``, in X then Y order."""
    found = linked_children(figure.axes[0])
    return [found[dimension] for dimension in ("x", "y") if dimension in found]


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtLinkedAxesTests(unittest.TestCase):
    # The window helpers of the shell tests, borrowed so this file does not run those tests again.
    setUpClass = classmethod(shell.QtShellTests.setUpClass.__func__)
    setUp = shell.QtShellTests.setUp
    _close = shell.QtShellTests._close
    wait = shell.QtShellTests.wait
    run_method = shell.QtShellTests.run_method
    reopen = shell.QtShellTests.reopen
    open_example = shell.QtShellTests.open_example
    format_with = shell.QtShellTests.format_with

    def xy_run(self):
        self.open_example()
        return self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})

    def column_run(self):
        self.open_example()
        return self.run_method("Column graph", {"Variables": ["Control", "Treated"]})

    def fill(self, record):
        """A stand-in for the user typing in the editor dialog: fills it from ``record`` and presses Apply."""
        from trama_qt.linked_axes import LinkedAxesDialog

        def run(dialog):
            for dimension in ("x", "y"):
                dialog.boxes[dimension].setChecked(dimension in record)
                item = record.get(dimension)
                if not item:
                    continue
                for name in ("label", "multiplier", "offset"):
                    if dialog.fields[(dimension, name)].isEnabled():
                        dialog.fields[(dimension, name)].setText(str(item[name]))
            dialog.accept()
            return dialog.DialogCode.Accepted if dialog.result is not None else dialog.DialogCode.Rejected

        return mock.patch.object(LinkedAxesDialog, "exec", run)

    def test_format_graph_creates_both_axes_and_saved_project_reopens_them(self):
        window = self.window
        run = self.xy_run()
        from trama_qt.graph_format import GraphFormatDialog
        style, xy = window.project.format_inputs(run)
        dialog = GraphFormatDialog(window, run.result.figure.axes[0], style, xy=xy)
        self.assertTrue(dialog.linked_button.isEnabled())
        self.assertEqual(dialog.linked_summary.text(), tr("linked_axes.summary_none"))
        with self.fill(LINKED_BOTH):
            dialog.edit_linked()
        self.assertEqual(dialog.linked_summary.text(), tr("linked_axes.summary.x") + ", " + tr("linked_axes.summary.y"))
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        window.project.apply_format(run, dialog.result, xy_update=dialog.xy_update, xy_result=dialog.xy_result)
        dialog.deleteLater()

        figure = run.result.figure
        self.assertEqual(sorted(child.get_gid() for child in children(figure)),
                         [GID_PREFIX + "x", GID_PREFIX + "y"])
        self.assertEqual(run.style["linked_axes"], LINKED_BOTH)
        self.assertTrue(window.project.dirty)

        saved = self.folder / "linked.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "XY series")
        window.open_sheet(("graph", index))
        self.wait()
        reopened = window.project.runs[index]
        self.assertEqual(reopened.style["linked_axes"], LINKED_BOTH)
        self.assertEqual(len(children(reopened.result.figure)), 2)

    def test_turning_the_axis_off_removes_it_and_the_record(self):
        run = self.xy_run()
        self.format_with(run, lambda dialog: setattr(dialog, "linked_axes", dict(LINKED_TOP)))
        self.assertEqual(len(children(run.result.figure)), 1)

        def switch_off(dialog):
            with self.fill({}):
                dialog.edit_linked()

        style = self.format_with(run, switch_off)
        self.assertNotIn("linked_axes", style)
        self.assertEqual(children(run.result.figure), [])

    def test_recalculating_after_a_sheet_edit_keeps_the_record_and_one_axis(self):
        window = self.window
        run = self.xy_run()
        self.format_with(run, lambda dialog: setattr(dialog, "linked_axes", dict(LINKED_TOP)))
        window.show_sheet("data", "groups")
        model = window.sheet.model()
        model.setData(model.index(1, 0), "9")
        self.app.processEvents()
        self.wait()
        figure = window.project.runs[window.project.runs.index(run)].result.figure
        self.assertEqual([child.get_gid() for child in children(figure)], [GID_PREFIX + "x"])
        self.assertEqual(window.project.runs[0].style["linked_axes"], LINKED_TOP)

    def test_a_graph_without_a_numeric_axis_is_told_why_and_keeps_the_controls_off(self):
        window = self.window
        run = self.column_run()
        from trama_qt.graph_format import GraphFormatDialog
        style, xy = window.project.format_inputs(run)
        dialog = GraphFormatDialog(window, run.result.figure.axes[0], style, xy=xy)
        # A column graph keeps the categorical X axis out: only the value axis can be linked.
        self.assertTrue(dialog.linked_button.isEnabled())
        self.assertIn(tr("linked_axes.error.categorical", axis="X"), dialog.linked_note.text())
        dialog.deleteLater()

    def test_inspector_previews_applies_and_cancels_the_secondary_axes(self):
        window = self.window
        run = self.xy_run()
        window.toggle_inspector()
        inspector = window.inspector
        figure = run.result.figure
        self.assertEqual(children(figure), [])
        with self.fill(LINKED_TOP):
            inspector.edit_linked()
        self.assertEqual(len(children(figure)), 1)  # Previewed on the live figure...
        self.assertNotIn("linked_axes", run.style or {})  # ...not yet confirmed.
        self.assertTrue(inspector.apply())
        self.assertEqual(run.style["linked_axes"], LINKED_TOP)
        self.assertEqual(window.project.tables["groups"].graph_styles[run.slot]["linked_axes"], LINKED_TOP)

        with self.fill({}):
            inspector.edit_linked()
        self.assertEqual(children(figure), [])
        inspector.cancel()  # Closing restores the confirmed style, secondary axis included.
        self.assertEqual(len(children(figure)), 1)
        self.assertEqual(children(figure)[0].get_gid(), GID_PREFIX + "x")

    def test_reset_section_of_the_axes_removes_the_secondary_axes(self):
        window = self.window
        run = self.xy_run()
        self.format_with(run, lambda dialog: setattr(dialog, "linked_axes", dict(LINKED_TOP)))
        window.toggle_inspector()
        inspector = window.inspector
        self.assertEqual(inspector.draft["linked_axes"], LINKED_TOP)
        inspector.reset_section("axes")
        self.assertNotIn("linked_axes", inspector.draft)
        self.assertEqual(children(run.result.figure), [])
        inspector.cancel()  # The draft is not confirmed: closing restores the saved secondary axis.
        self.assertEqual(len(children(run.result.figure)), 1)

    def test_the_editor_names_the_field_and_keeps_the_dialog_open_on_a_bad_value(self):
        run = self.xy_run()
        from trama_qt.linked_axes import LinkedAxesDialog
        dialog = LinkedAxesDialog(self.window, run.result.figure.axes[0], {})
        dialog.boxes["x"].setChecked(True)
        dialog.fields[("x", "multiplier")].setText("0")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertFalse(dialog.problem.isHidden())
        self.assertEqual(dialog.problem.text(), tr("linked_axes.error.multiplier", axis="X"))
        dialog.fields[("x", "multiplier")].setText("0,5")  # a decimal comma is a number
        dialog.accept()
        self.assertEqual(dialog.result["x"]["multiplier"], 0.5)
        dialog.deleteLater()

    def test_language_follows_the_application_in_the_editor(self):
        self.addCleanup(set_language, active_language())
        run = self.xy_run()
        from trama_qt.linked_axes import LinkedAxesDialog
        set_language("it")
        dialog = LinkedAxesDialog(self.window, run.result.figure.axes[0], {})
        self.assertEqual(dialog.windowTitle(), "Assi secondari sincronizzati")
        dialog.boxes["y"].setChecked(True)
        dialog.fields[("y", "offset")].setText("abc")
        dialog.accept()
        self.assertEqual(dialog.problem.text(), "Asse Y collegato: inserisci uno scostamento finito.")
        dialog.deleteLater()

    def two_series_run(self, sides):
        """An XY graph with series ``a`` and ``b``; ``sides`` places them on the left or the right axis."""
        from trama_qt.analysis_dialog import AnalysisDialog

        path = self.folder / "two.csv"
        pd.DataFrame({"t": [1.0, 2.0, 3.0, 4.0, 5.0], "a": [2.0, 3.1, 4.2, 5.0, 6.3],
                      "b": [10.0, 22.0, 31.0, 39.0, 52.0]}).to_csv(path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        frame = self.window.project.tables["two"].frame(mask_excluded=True)
        dialog = AnalysisDialog(self.window, frame, current=("XY series", {}))
        control = dialog.controls["Y columns"][1]
        for row in range(control.count()):  # tick the columns a user would tick
            item = control.item(row)
            item.setCheckState(Qt.CheckState.Checked if item.text() in ("a", "b") else Qt.CheckState.Unchecked)
        values = dialog.options()
        dialog.deleteLater()
        values.update({"X": "t", "Y columns": ["a", "b"], "Series side": sides})
        self.window.calculate_candidate(self.window.project.candidate("two", "XY series", values), frame, None)
        self.wait()
        return self.window.project.runs[-1]

    def test_an_independent_right_axis_disables_the_right_controls_and_says_why(self):
        from analisi.linked_axes import P_RIGHT
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.linked_axes import LinkedAxesDialog

        run = self.two_series_run({"a": "Left", "b": "Right"})
        self.assertEqual(len(run.result.figure.axes), 2)
        style, xy = self.window.project.format_inputs(run)
        dialog = GraphFormatDialog(self.window, run.result.figure.axes[0], style, xy=xy)
        self.assertTrue(dialog.linked_button.isEnabled())  # the top X axis is still available
        self.assertIn(tr("linked_axes.error.right"), dialog.linked_note.text())
        editor = LinkedAxesDialog(dialog, run.result.figure.axes[0], {}, conflicts=dialog._linked_conflicts())
        self.assertTrue(editor.boxes["x"].isEnabled())
        self.assertFalse(editor.boxes["y"].isEnabled())
        self.assertIn(tr("linked_axes.error.right"), editor.notes["y"].text())
        editor.boxes["y"].setChecked(True)  # a click that cannot switch it on
        self.assertFalse(editor.boxes["y"].isChecked())
        editor.deleteLater()
        # Moving every series to the left in this same dialog frees the right axis at once.
        dialog.xy_side = {"a": "Left", "b": "Left"}
        self.assertNotIn("y", dialog._linked_conflicts())
        self.assertEqual(dialog._linked_conflicts(), {})
        dialog.deleteLater()
        self.assertEqual(P_RIGHT, tr("linked_axes.error.right"))  # English here: the message and the catalog agree

    def test_a_saved_right_axis_that_cannot_show_is_kept_and_named_in_the_graph_note(self):
        run = self.two_series_run({"a": "Left", "b": "Right"})
        style = dict(run.style or {})
        style["linked_axes"] = dict(LINKED_BOTH)
        self.window.project.apply_format(run, style)
        self.assertEqual([child.get_gid() for child in children(run.result.figure)], [GID_PREFIX + "x"])
        self.assertEqual(run.style["linked_axes"], LINKED_BOTH)  # kept, so it returns when the graph allows it
        self.assertIn(tr("linked_axes.error.right"), run.result.style_warning)
        self.window.show_sheet("graph", self.window.project.runs.index(run))
        self.app.processEvents()

    def test_a_graph_that_cannot_take_secondary_axes_offers_no_button_in_the_inspector(self):
        self.open_example()
        run = self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        self.window.toggle_inspector()
        self.assertFalse(self.window.inspector.linked_widgets)
        self.window.inspector.cancel()

    def test_a_logarithmic_axis_fixes_the_offset_at_zero_in_the_editor(self):
        from trama_qt.linked_axes import LinkedAxesDialog

        run = self.xy_run()
        axes = run.result.figure.axes[0]
        editor = LinkedAxesDialog(self.window, axes, {"x": {"multiplier": 2.0, "offset": 5.0, "label": "w"}},
                                  scales={"x": "log"})
        self.assertFalse(editor.fields[("x", "offset")].isEnabled())
        self.assertEqual(editor.fields[("x", "offset")].text(), "0")
        self.assertFalse(editor.notes["x"].isHidden())
        self.assertEqual(editor.notes["x"].text(), tr("linked_axes.hint.log"))
        self.assertEqual(editor.read_record()["x"]["offset"], 0.0)
        editor.deleteLater()

    def test_the_reference_values_stay_positive_on_a_logarithmic_axis(self):
        from trama_qt.linked_axes import reference_values

        run = self.xy_run()
        axes = run.result.figure.axes[0]
        axes.set_xlim(-2.0, 50.0)  # a linear axis that crosses zero: the first tick is not positive
        self.assertLessEqual(reference_values(axes, "x")[0], 0.0)
        first, second = reference_values(axes, "x", logarithmic=True)
        self.assertGreater(first, 0)
        self.assertGreater(second, first)
        axes.set_xlim(-2.0, 0.0)
        self.assertEqual(reference_values(axes, "x", logarithmic=True), (1.0, 10.0))

    def test_formatting_never_repeats_the_calculation(self):
        import analisi.workbench as workbench

        run = self.xy_run()
        with mock.patch.object(workbench, "_analyse", side_effect=AssertionError("the fit was repeated")):
            self.format_with(run, lambda dialog: setattr(dialog, "linked_axes", dict(LINKED_BOTH)))
            self.window.toggle_inspector()
            with self.fill(LINKED_TOP):
                self.window.inspector.edit_linked()
            self.assertTrue(self.window.inspector.apply())
            self.window.inspector.cancel()
        self.assertEqual(run.style["linked_axes"], LINKED_TOP)

    def test_a_project_saved_without_the_section_opens_exactly_as_before(self):
        run = self.column_run()
        self.assertNotIn("linked_axes", run.style or {})
        saved = self.folder / "plain.alab"
        self.window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(self.window.project.runs) if r.method == "Column graph")
        self.window.open_sheet(("graph", index))
        self.wait()
        reopened = self.window.project.runs[index]
        self.assertNotIn("linked_axes", reopened.style or {})
        self.assertEqual(children(reopened.result.figure), [])
        self.assertFalse(getattr(reopened.result, "style_warning", None))

    def test_the_column_graph_offers_the_value_axis_only(self):
        from trama_qt.linked_axes import LinkedAxesDialog

        run = self.column_run()
        axes = run.result.figure.axes[0]
        editor = LinkedAxesDialog(self.window, axes, {})
        self.assertFalse(editor.boxes["x"].isEnabled())
        self.assertTrue(editor.boxes["y"].isEnabled())
        self.assertIn(tr("linked_axes.error.categorical", axis="X"), editor.notes["x"].text())
        editor.deleteLater()
        style = self.format_with(run, lambda dialog: setattr(dialog, "linked_axes", {"y": {
            "multiplier": 1000.0, "offset": 0.0, "label": "mg"}}))
        self.assertEqual(style["linked_axes"]["y"]["label"], "mg")
        self.assertEqual([child.get_gid() for child in children(run.result.figure)], [GID_PREFIX + "y"])


if __name__ == "__main__":
    unittest.main()
