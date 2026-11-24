"""Qt integration of single-point formatting: Inspector section, preview/Apply/Cancel, recalculation, .alab,
family copies, exports (EN and IT)."""
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "QtAgg")

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QApplication

from analisi import point_style as ps
from analisi.family_workflow import duplicate_family
from analisi.i18n import set_language
from analisi.presentation import graph_series
from trama_qt import theme
from trama_qt.inspector import GraphInspector
from trama_qt.project import Project, compute
from trama_qt.window import export_graph

DATA = Path(__file__).resolve().parent / "data" / "point_style" / "casi.csv"
SCATTER = "Scatter / confidence ellipse"
RECIPE = {"X": "X", "Y": "Y", "Group": "Group"}
COLOR = "#ac4320"
KEY = "scatter:1:C"


def new_project(recipe=RECIPE, method=SCATTER, path=DATA):
    project = Project()
    title = project.load(path)[0]
    run = project.candidate(title, method, dict(recipe))
    result = compute(run, project.tables[title].frame(mask_excluded=True))
    index, _ = project.add_result(run, result)
    return project, title, project.runs[index]


def recalc(project, runs):
    job = project.plan_refresh(runs)
    project.apply_refresh(job, project.run_refresh(job))


def overlays(figure, key=None):
    prefix = ps.GID_PREFIX + (key + ":" if key else "")
    return [child for child in figure.axes[0].get_children() if str(child.get_gid() or "").startswith(prefix)]


def hidden(artist):
    return list(np.flatnonzero(np.isnan(np.asarray(artist.get_offsets(), dtype=float)).any(axis=1)))


def png(figure, dpi=100):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    return buffer.getvalue()


class Panel:
    """An Inspector on a run, with the commits it makes recorded."""

    def __init__(self, test, run, project=None):
        self.run, self.project, self.commits = run, project, []
        self.canvas = FigureCanvasQTAgg(run.result.figure)
        self.canvas.resize(800, 600)
        self.canvas.draw()
        self.inspector = GraphInspector(run, self.canvas, confirmed=lambda: run.style or {},
                                        commit=self._commit, closed=lambda: None)
        test.addCleanup(self.close)
        self.points = self.inspector.points

    def _commit(self, style):
        self.commits.append(deepcopy(style))
        if self.project is not None:
            self.project.commit_style(self.run, style)  # what the window does: run, worksheet style, warning
        else:
            self.run.style = style

    def close(self):
        self.inspector.dispose()
        self.inspector.deleteLater()

    def row(self, number):
        """Select the observation of worksheet row ``number`` from the list."""
        model = self.points.model
        for position in range(model.rowCount()):
            if f"Row {number} " in model.data(model.index(position)) or f"Riga {number} " in model.data(
                    model.index(position)):
                self.points.view.setCurrentIndex(model.index(position))
                return position
        raise AssertionError(f"row {number} not listed")

    def click(self, x, y):
        axes = self.inspector.axes
        px, py = axes.transData.transform((x, y))
        event = MouseEvent("button_press_event", self.canvas, px, py, button=1)
        self.canvas.callbacks.process("button_press_event", event)

    def type_color(self, text):
        self.points.color.setText(text)
        self.points.color.editingFinished.emit()

    def set_size(self, text):
        self.points.size.setText(text)
        self.points.size.editingFinished.emit()

    def series(self, key=KEY):
        return {item.key: item for item in graph_series(self.inspector.axes)}[key]

    def extras(self, key=None):
        """The marker lines that draw the formatted points."""
        return overlays(self.inspector.figure, key)

    def colors(self):
        """The hex color of every formatted point that is drawn."""
        return [matplotlib.colors.to_hex(line.get_markerfacecolor()) for line in self.extras()]


class PointInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-point-tests"])
        theme.apply(cls.app)

    def setUp(self):
        set_language("en")
        self.project, self.title, self.run = new_project()
        self.panel = Panel(self, self.run, self.project)

    def tearDown(self):
        set_language("en")

    def test_section_lists_the_observations_of_the_selected_series(self):
        points = self.panel.points
        self.assertEqual(points.series.key, KEY)
        self.assertEqual(points.model.rowCount(), 3)  # row 4 has no Y
        self.assertEqual(points.info.text(), "No point selected.")
        self.assertFalse(points.color.row.isEnabled())
        self.assertFalse(points.reset_point_button.isEnabled())
        self.assertFalse(points.reason.isVisible())
        self.assertEqual(points.model.data(points.model.index(2)), "Row 3 · X = 2 · Y = 4")

    def test_selecting_a_row_shows_series_row_and_coordinates_and_ring(self):
        self.panel.row(2)
        points = self.panel.points
        self.assertIn("row 2 · X = 1 · Y = 2", points.info.text())
        self.assertTrue(points.color.row.isEnabled())
        ring = getattr(self.panel.inspector.axes, ps.INDICATOR_ATTR)
        self.assertEqual((list(ring.get_xdata()), list(ring.get_ydata())), [([1.0], [2.0])][0])
        self.assertEqual(ring.get_gid(), ps.INDICATOR_GID)

    def test_a_click_on_overlapping_points_offers_every_row(self):
        self.panel.click(1, 2)
        points = self.panel.points
        self.assertEqual(len(points.candidates), 2)
        self.assertFalse(points.near.isHidden())
        self.assertFalse(points.near_label.isHidden())
        self.assertEqual(points.near.count(), 2)
        self.assertIn("row 1", points.info.text())
        points.near.setCurrentIndex(1)
        self.assertIn("row 2", points.info.text())
        self.assertEqual(points.near.count(), 2)  # the choice stays on offer
        self.panel.type_color(COLOR)
        records = self.panel.inspector.draft[ps.POINTS]
        self.assertEqual([item["source"]["row"] for item in records], [2])

    def test_click_far_from_any_point_picks_nothing(self):
        self.panel.click(3.5, 1)
        self.assertIsNone(self.panel.points.vertex)

    def test_preview_apply_once_and_cancel(self):
        panel, inspector = self.panel, self.panel.inspector
        before = png(inspector.figure)
        panel.row(2)
        panel.type_color(COLOR)
        panel.points.marker.set("Square")
        panel.set_size("9")
        self.assertEqual(panel.commits, [])  # a preview is never saved
        self.assertIsNone(self.run.style)
        self.assertTrue(inspector.has_draft)
        self.assertEqual(panel.colors(), [COLOR])
        self.assertEqual(hidden(panel.series().artist), [1])
        (extra,) = panel.extras()
        self.assertEqual((extra.get_marker(), extra.get_markersize()), ("s", 9.0))
        (record,) = inspector.draft[ps.POINTS]
        self.assertEqual((record["color"], record["marker"], record["marker_size"]), (COLOR, "s", 9.0))
        # Cancel with nothing confirmed gives back the original rendering and the original style
        inspector.discard()
        self.assertEqual(panel.extras(), [])
        self.assertEqual(png(inspector.figure), before)
        self.assertEqual((panel.commits, self.run.style), ([], None))
        # the same edit again, then Apply: one commit
        panel.row(2)
        panel.type_color(COLOR)
        panel.points.marker.set("Square")
        panel.set_size("9")
        self.assertTrue(inspector.apply())
        self.assertEqual(len(panel.commits), 1)  # Apply saves once
        self.assertEqual(panel.commits[0][ps.POINTS], [record])
        self.assertFalse(inspector.has_draft)
        self.assertEqual(self.project.tables[self.title].graph_styles[self.run.slot][ps.POINTS], [record])
        # another edit, then Cancel: the confirmed style is back
        panel.type_color("#00aa00")
        self.assertTrue(inspector.has_draft)
        inspector.discard()
        self.assertEqual(self.run.style[ps.POINTS][0]["color"], COLOR)
        self.assertEqual(len(panel.commits), 1)
        self.assertEqual(panel.colors(), [COLOR])

    def test_blank_fields_inherit_and_reset_returns_to_the_series_look(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.row(2)
        panel.type_color(COLOR)
        self.assertEqual(panel.points.marker.value(), "As series")
        self.assertEqual(panel.points.size.text(), "")
        self.assertEqual(panel.points.color.placeholderText(), "#1f77b4")
        record = inspector.draft[ps.POINTS][0]
        self.assertNotIn("marker", record)
        self.assertNotIn("marker_size", record)
        self.assertTrue(panel.points.reset_point_button.isEnabled())
        panel.points.reset_point_button.click()
        self.assertNotIn(ps.POINTS, inspector.draft)
        self.assertEqual(panel.points.color.text(), "")
        self.assertFalse(panel.points.reset_point_button.isEnabled())
        self.assertEqual(panel.extras(), [])
        self.assertEqual(hidden(panel.series().artist), [])
        # blank color, symbol and size remove the record by themselves
        panel.type_color(COLOR)
        panel.type_color("")
        self.assertNotIn(ps.POINTS, inspector.draft)

    def test_invalid_entries_are_flagged_and_not_previewed(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.row(2)
        panel.type_color("nonsense")
        self.assertIn("valid color", inspector.errors["point"])
        self.assertNotIn(ps.POINTS, inspector.draft)
        panel.type_color("")
        panel.set_size("0")
        self.assertIn("symbol sizes", inspector.errors["point"])
        panel.set_size("abc")
        self.assertIn("point", inspector.errors)
        panel.set_size("")
        self.assertNotIn("point", inspector.errors)

    def test_changing_the_series_clears_the_selection_and_the_ring(self):
        panel = self.panel
        panel.row(2)
        panel.inspector.selector.setCurrentIndex(1)
        points = panel.points
        self.assertEqual(points.series.key, "scatter:1:T")
        self.assertIsNone(points.vertex)
        self.assertEqual(points.model.rowCount(), 1)
        self.assertIsNone(getattr(panel.inspector.axes, ps.INDICATOR_ATTR, None))
        self.assertFalse(points.color.row.isEnabled())

    def test_series_settings_still_work_around_a_formatted_point(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.row(2)
        panel.type_color(COLOR)
        inspector.fields["color"].setText("#112233")
        inspector.fields["color"].editingFinished.emit()
        series = panel.series().artist
        self.assertTrue(np.allclose(series.get_facecolor()[0], matplotlib.colors.to_rgba("#112233")))
        self.assertEqual(panel.colors(), [COLOR])  # the formatted point keeps its own color
        handle = inspector.axes.get_legend().legend_handles[0]
        self.assertTrue(np.allclose(handle.get_facecolor()[0], matplotlib.colors.to_rgba("#112233")))
        self.assertEqual([text.get_text() for text in inspector.axes.get_legend().get_texts()], ["C", "T"])
        inspector.discard()
        self.assertEqual(panel.extras(), [])
        self.assertEqual(self.run.style, None)

    def test_a_hidden_series_is_not_picked_and_shows_no_ring(self):
        _project, _title, run = new_project({"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Step"}}, "XY series")
        panel = Panel(self, run)
        self.assertIn("without symbols", panel.points.reason.text())  # visibility belongs to Step and Bars only
        self.assertIsNone(panel.click(2, 4))
        self.assertIsNone(getattr(panel.inspector.axes, ps.INDICATOR_ATTR, None))

    def test_closing_the_panel_with_a_draft_restores_the_confirmed_style_and_removes_the_ring(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.row(2)
        panel.type_color(COLOR)
        self.assertTrue(inspector.has_draft)
        inspector.dispose()
        self.assertIsNone(getattr(inspector.axes, ps.INDICATOR_ATTR, None))
        self.assertEqual(panel.extras(), [])
        self.assertIsNone(self.run.style)
        self.assertEqual(panel.commits, [])

    def test_section_reset_clears_every_point_style(self):
        panel, inspector = self.panel, self.panel.inspector
        for row, color in ((2, COLOR), (3, "#00aa00")):
            panel.row(row)
            panel.type_color(color)
        self.assertEqual(len(inspector.draft[ps.POINTS]), 2)
        self.assertEqual(panel.points.styled.count(), 2)
        inspector.reset_section("points")
        self.assertNotIn(ps.POINTS, inspector.draft)
        self.assertEqual(panel.points.styled.count(), 0)
        self.assertEqual(panel.extras(), [])

    def test_the_formatted_list_marks_the_styled_rows(self):
        panel = self.panel
        panel.row(2)
        panel.type_color(COLOR)
        model = panel.points.model
        self.assertTrue(model.data(model.index(1)).startswith("● "))
        self.assertFalse(model.data(model.index(0)).startswith("●"))
        panel.points.styled.setCurrentRow(0)
        panel.points.reset_selected_button.click()
        self.assertFalse(model.data(model.index(1)).startswith("●"))

    def test_italian_captions(self):
        set_language("it")
        project, _title, run = new_project()
        panel = Panel(self, run)
        points = panel.points
        self.assertEqual(points.info.text(), "Nessun punto selezionato.")
        panel.row(2)
        self.assertIn("riga 2", points.info.text())
        self.assertEqual(points.reset_point_button.text(), "Ripristina questo punto")
        self.assertEqual(points.marker.itemText(0), "Come la serie")
        panel.type_color("nonsense")
        self.assertIn("colore", panel.inspector.errors["point"].lower())
        panel.type_color(COLOR)
        self.assertIn("Riga 2", points.styled.item(0).text())


class SuspendedPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-point-tests"])
        theme.apply(cls.app)

    def setUp(self):
        set_language("en")
        self.project, self.title, self.run = new_project()
        panel = Panel(self, self.run, self.project)
        panel.row(2)
        panel.type_color(COLOR)
        panel.points.marker.set("Square")
        panel.set_size("9")
        panel.inspector.apply()
        panel.inspector.dispose()
        self.styled = deepcopy(self.run.style)

    def tearDown(self):
        set_language("en")

    def insert_identical_row(self):
        runs = self.project.insert_rows(self.title, 0)
        for column, text in enumerate(("1", "2", "C")):
            runs = self.project.edit_cell(self.title, 0, column, text)
        recalc(self.project, runs)
        return self.project.runs[0]

    def test_recalculation_after_an_edit_keeps_the_point_on_its_row(self):
        runs = self.project.edit_cell(self.title, 1, 1, "3")  # row 2: Y 2 -> 3
        recalc(self.project, runs)
        run = self.project.runs[0]
        (status,) = ps.point_statuses(run.result.figure)
        self.assertEqual((status.state, status.row), ("ok", 2))
        self.assertIsNone(run.result.style_warning)
        self.assertEqual([matplotlib.colors.to_hex(line.get_markerfacecolor())
                          for line in overlays(run.result.figure)], [COLOR])

    def test_an_ambiguous_insertion_suspends_the_style_with_a_message(self):
        run = self.insert_identical_row()
        (status,) = ps.point_statuses(run.result.figure)
        self.assertEqual((status.state, status.reason), ("suspended", "ambiguous"))
        self.assertIn("not given to another row", run.result.style_warning)
        self.assertEqual(overlays(run.result.figure), [])  # no row took the style
        self.assertEqual(run.style, self.styled)  # the record is kept: nothing was lost
        # The Inspector lists the suspended record, says why, and can always reset it.
        panel = Panel(self, run, self.project)
        points = panel.points
        self.assertEqual(points.styled.count(), 1)
        self.assertFalse(points.styled.item(0).icon().isNull())
        points.styled.setCurrentRow(0)
        self.assertTrue(points.reset_selected_button.isEnabled())
        self.assertIn("not given to another row", panel.inspector.status.text())
        points.reset_selected_button.click()
        self.assertNotIn(ps.POINTS, panel.inspector.draft)
        self.assertTrue(panel.inspector.apply())
        self.assertNotIn(ps.POINTS, panel.commits[0])
        self.assertEqual(points.styled.count(), 0)

    def test_deleting_an_unrelated_row_keeps_the_point(self):
        runs = self.project.delete_rows(self.title, [2])
        recalc(self.project, runs)
        run = self.project.runs[0]
        self.assertEqual(ps.point_statuses(run.result.figure)[0].state, "ok")

    def test_excluding_the_row_hides_the_style_and_including_it_brings_it_back(self):
        dataset = self.project.tables[self.title]
        dataset.excluded.add((1, 1))  # the Y cell of row 2
        recalc(self.project, self.project.table_runs(self.title))
        run = self.project.runs[0]
        (status,) = ps.point_statuses(run.result.figure)
        self.assertEqual((status.state, status.reason), ("hidden", "not_drawn"))
        self.assertIsNone(run.result.style_warning)
        panel = Panel(self, run)  # the Inspector still lists it, with a reset
        self.assertEqual(panel.points.styled.count(), 1)
        panel.points.styled.setCurrentRow(0)
        self.assertTrue(panel.points.reset_selected_button.isEnabled())
        dataset.excluded.discard((1, 1))
        recalc(self.project, self.project.table_runs(self.title))
        self.assertEqual(ps.point_statuses(self.project.runs[0].result.figure)[0].state, "ok")

    def test_changing_the_recipe_suspends_without_losing_the_record(self):
        cand = self.project.candidate(self.title, SCATTER, {"X": "X", "Y": "Y"}, index=0)
        cand.style = deepcopy(self.styled)
        result = compute(cand, self.project.tables[self.title].frame(mask_excluded=True))
        self.project.add_result(cand, result, index=0)
        run = self.project.runs[0]
        (status,) = ps.point_statuses(run.result.figure)
        self.assertEqual(status.state, "suspended")
        self.assertTrue(run.result.style_warning)

    def test_reopening_and_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "points.alab"
            self.project.save(path)
            reopened = Project()
            reopened.load(path)
            run = reopened.runs[0]
            self.assertEqual(run.style[ps.POINTS], self.styled[ps.POINTS])
            result = compute(run, reopened.tables[run.title].frame(mask_excluded=True))
            self.assertEqual(ps.point_statuses(result.figure)[0].state, "ok")
            self.assertEqual(png(result.figure), png(self.run.result.figure))
            # a file saved before the feature has no points and keeps its look
            old = deepcopy(self.styled)
            old.pop(ps.POINTS)
            old_project, _title, old_run = new_project()
            old_project.commit_style(old_run, {"title": "Before"})
            old_path = Path(tmp) / "old.alab"
            old_project.save(old_path)
            again = Project()
            again.load(old_path)
            self.assertEqual(again.runs[0].style, {"title": "Before"})
            self.assertEqual(ps.points_of_style(again.runs[0].style), [])

    def test_family_copy_keeps_the_point_styles_and_never_moves_them(self):
        bundle = duplicate_family(self.project.tables, self.project.layouts, self.project.info_sheets.values(),
                                  ("data", self.title), name="Repeat")
        copy = bundle.tables["Repeat"]
        slot = self.run.slot
        self.assertEqual(copy.graph_styles[slot][ps.POINTS], self.styled[ps.POINTS])
        self.assertIsNot(copy.graph_styles[slot], self.project.tables[self.title].graph_styles[slot])
        copy.graph_styles[slot][ps.POINTS][0]["color"] = "#00aa00"  # a copy is independent of the original
        self.assertEqual(self.project.tables[self.title].graph_styles[slot][ps.POINTS][0]["color"], COLOR)
        apply = self.project.apply_family(bundle)
        copied = next(run for run in self.project.runs if run.title == "Repeat")
        result = compute(copied, self.project.tables["Repeat"].frame(mask_excluded=True))
        (status,) = ps.point_statuses(result.figure)
        self.assertEqual(status.state, "ok")
        self.assertIsNotNone(apply)

    def test_exports_and_layout_keep_the_color_and_skip_the_ring(self):
        run = self.project.runs[0]
        panel = Panel(self, run)
        panel.row(2)
        figure = run.result.figure
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {}
            for suffix in ("png", "svg", "pdf"):
                target = Path(tmp) / f"figure.{suffix}"
                export_graph(figure, target)
                outputs[suffix] = target.read_bytes()
            self.assertIn(COLOR.encode(), outputs["svg"])
            self.assertNotIn(ps.INDICATOR_COLOR.encode(), outputs["svg"])
            ps.clear_indicator(figure)
            target = Path(tmp) / "plain.png"
            export_graph(figure, target)
            self.assertEqual(target.read_bytes(), outputs["png"])  # the ring was not in the export
        from analisi.presentation import compose_layout

        panel.row(2)
        layout = png(compose_layout("Layout", 1, [figure]), 150)
        ps.clear_indicator(figure)
        self.assertEqual(png(compose_layout("Layout", 1, [figure]), 150), layout)
        pixels = plt.imread(BytesIO(layout))
        wanted = np.array(matplotlib.colors.to_rgb(COLOR))
        self.assertGreater(int(np.sum(np.all(np.abs(pixels[..., :3] - wanted) < 0.02, axis=-1))), 5)


class UnsupportedFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-point-tests"])
        theme.apply(cls.app)

    def tearDown(self):
        set_language("en")

    def test_a_histogram_says_why_at_the_section(self):
        for language, fragment in (("en", "XY series and scatter plots only"), ("it", "serie XY")):
            set_language(language)
            _project, _title, run = new_project({"Response": "Y", "Bins": 3}, "Histogram")
            panel = Panel(self, run)
            points = panel.points
            self.assertFalse(points.reason.isHidden())
            self.assertIn(fragment, points.reason.text())
            self.assertFalse(points.view.isEnabled())
            self.assertFalse(points.color.row.isEnabled())

    def test_a_series_without_symbols_says_why(self):
        recipe = {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line"}}
        _project, _title, run = new_project(recipe, "XY series")
        panel = Panel(self, run)
        self.assertIn("without symbols", panel.points.reason.text())
        self.assertFalse(panel.points.view.isEnabled())
        self.assertEqual(panel.points.model.rowCount(), 0)


class XYSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-point-tests"])
        theme.apply(cls.app)

    def test_xy_series_with_line_and_points(self):
        recipe = {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line and points"}}
        _project, _title, run = new_project(recipe, "XY series")
        panel = Panel(self, run)
        points = panel.points
        self.assertEqual(points.series.key, "xy:1:Y")
        self.assertEqual(points.model.rowCount(), 4)  # row 4 has no Y: one vertex, no point
        panel.click(2, 4)
        self.assertIn("row 3", points.info.text())
        panel.type_color(COLOR)
        series = points.series
        self.assertEqual(series.artist.get_color(), "#1f77b4")  # the line keeps its stroke
        mask = np.asarray(series.artist.get_markevery())
        self.assertEqual(list(np.flatnonzero(~mask)), [2])
        self.assertTrue(panel.inspector.apply())
        self.assertEqual(len(panel.commits[0][ps.POINTS]), 1)
        self.assertEqual([text.get_text() for text in panel.inspector.axes.get_legend().get_texts()], ["Y"])


if __name__ == "__main__":
    unittest.main()
