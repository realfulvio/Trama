"""Qt integration of the labels of the observations: Inspector section, preview/Apply/Cancel, edits of the worksheet,
columns that are renamed, deleted and created again, .alab, family copies, exports (EN and IT)."""
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

from analisi import observation_labels as ol
from analisi import point_style as ps
from analisi.analysis_templates import plan_template
from analisi.data import Dataset
from analisi.family_workflow import duplicate_family
from analisi.i18n import set_language
from analisi.presentation import apply_style, compose_layout, graph_series
from analisi.repeat_analysis import fit_style, remap_style
from analisi.worksheet_column_identity import COLUMN_IDS, valid_token
from trama_qt import theme
from trama_qt.inspector import GraphInspector
from trama_qt.project import Project, compute, graph_warning
from trama_qt.window import export_graph

ALAB = Path(__file__).resolve().parent / "data" / "observation_labels" / "etichette-osservazioni.alab"
COLOR = "#aa2288"
CONTROL, TREATED, XY = "scatter:1:Controllo", "scatter:1:Trattamento", "xy:1:Y"
VISIBLE = ["Campione $1", "Campione $2", "Caffè"]
LABEL_COLUMN = 4  # Etichetta


def new_project(path=ALAB):
    project = Project()
    title = project.load(path)[0]
    ready(project)
    return project, title


def ready(project):
    for run in project.runs:
        if run.result is None:
            run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))


def recalc(project, runs=None):
    job = project.plan_refresh(project.runs if runs is None else runs)
    project.apply_refresh(job, project.run_refresh(job))


def style_run(project, run, style):
    """What the Inspector does on Apply: the style is drawn, then stored."""
    apply_style(run.result.figure, style)
    project.commit_style(run, style)


def origin(project, title, name="Etichetta"):
    return ol.column_origin(project.tables[title].frame(mask_excluded=True), name)


def texts(run, key=None):
    return [text for series, text in ol.label_texts(run.result.figure) if key in (None, series)]


def png(figure, dpi=100):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    return buffer.getvalue()


def pixels_of(data, color, tolerance=0.15):
    image = plt.imread(BytesIO(data))
    target = np.array(matplotlib.colors.to_rgb(color))
    return int(np.sum(np.all(np.abs(image[..., :3] - target) < tolerance, axis=-1)))


def hide_row(run, key, row, show=False):
    pmap = ps.point_map({item.key: item for item in graph_series(run.result.figure.axes[0])}[key].artist)
    index = int(np.flatnonzero(pmap.rows == row)[0])
    return {"source": ps.source_record(pmap, index), "show": show}


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
        self.points, self.labels = self.inspector.points, self.inspector.labels

    def _commit(self, style):
        self.commits.append(deepcopy(style))
        if self.project is not None:
            self.project.commit_style(self.run, style)  # what the window does: run, worksheet style, warning
        else:
            self.run.style = style

    def close(self):
        self.inspector.dispose()
        self.inspector.deleteLater()

    def source(self, caption):
        """Choose the source of the labels by its caption (the first entry is "No labels")."""
        combo = self.labels.source
        for position in range(combo.count()):
            if combo.itemText(position) == caption:
                combo.setCurrentIndex(position)
                return
        raise AssertionError(f"{caption!r} not in {[combo.itemText(n) for n in range(combo.count())]}")

    def row(self, number):
        model = self.points.model
        for position in range(model.rowCount()):
            text = model.data(model.index(position))
            if f"Row {number} " in text or f"Riga {number} " in text:
                self.points.view.setCurrentIndex(model.index(position))
                return position
        raise AssertionError(f"row {number} not listed")

    def click(self, x, y):
        px, py = self.inspector.axes.transData.transform((x, y))
        event = MouseEvent("button_press_event", self.canvas, px, py, button=1)
        self.canvas.callbacks.process("button_press_event", event)

    def type(self, field, text):
        field.setText(text)
        field.editingFinished.emit()

    def texts(self, key=None):
        return [text for series, text in ol.label_texts(self.inspector.figure) if key in (None, series)]

    def draft_record(self, key=CONTROL):
        records = self.inspector.draft.get(ol.LABELS) or []
        position = ol.find_series_record(records, key)
        return records[position] if position is not None else None


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-label-tests"])
        theme.apply(cls.app)

    def tearDown(self):
        set_language("en")


class LabelInspectorTests(QtCase):
    def setUp(self):
        set_language("en")
        self.project, self.title = new_project()
        self.run = self.project.runs[0]  # the scatter plot
        self.panel = Panel(self, self.run, self.project)

    def test_the_section_offers_the_row_titles_and_every_column(self):
        labels = self.panel.labels
        captions = [labels.source.itemText(number) for number in range(labels.source.count())]
        self.assertEqual(captions, ["No labels", "Row titles", "X", "Y", "Gruppo", "Etichetta"])
        self.assertTrue(labels.source.isEnabled())
        self.assertFalse(labels.color.row.isEnabled())  # nothing to format until there is a source
        self.assertFalse(labels.mode.isEnabled())
        self.assertFalse(labels.reason.isVisible())

    def test_preview_apply_once_and_cancel(self):
        panel, inspector = self.panel, self.panel.inspector
        before = png(inspector.figure)
        panel.source("Etichetta")
        self.assertEqual(panel.texts(), VISIBLE)
        self.assertEqual((panel.commits, self.run.style), ([], None))  # a preview is never saved
        self.assertTrue(inspector.has_draft)
        self.assertEqual(panel.draft_record()["from"], {"kind": "column", "name": "Etichetta", "id": "base:5"})
        self.assertIn("3 labels shown", panel.labels.summary.text())
        inspector.discard()  # Cancel gives back the original rendering
        self.assertEqual(panel.texts(), [])
        self.assertEqual(png(inspector.figure), before)
        panel.source("Etichetta")
        self.assertTrue(inspector.apply())
        self.assertEqual(len(panel.commits), 1)  # Apply saves once
        self.assertFalse(inspector.has_draft)
        saved = self.project.tables[self.title].graph_styles[self.run.slot][ol.LABELS]
        self.assertEqual(saved, panel.commits[0][ol.LABELS])
        panel.labels.position.set("right")
        self.assertTrue(inspector.has_draft)
        inspector.discard()  # the confirmed labels are back
        self.assertEqual(panel.draft_record(), saved[0])
        self.assertEqual(panel.texts(), VISIBLE)
        self.assertEqual(len(panel.commits), 1)

    def test_look_fields_and_blanks_inherit(self):
        panel = self.panel
        panel.source("Etichetta")
        panel.type(panel.labels.color, COLOR)
        panel.labels.position.set("below")
        panel.type(panel.labels.size, "11")
        panel.type(panel.labels.limit, "2")
        record = panel.draft_record()
        self.assertEqual((record["color"], record["position"], record["size"], record["limit"]),
                         (COLOR, "below", 11.0, 2))
        self.assertEqual(panel.texts(), VISIBLE[:2])
        self.assertIn("2 of 3 labels shown: 1 omitted", panel.labels.summary.text())
        panel.labels.show.setChecked(False)
        self.assertEqual(panel.texts(), [])
        self.assertFalse(panel.draft_record()["show"])
        panel.labels.show.setChecked(True)
        for field in (panel.labels.color, panel.labels.size, panel.labels.limit):
            panel.type(field, "")
        panel.labels.position.set("above")
        self.assertEqual(panel.draft_record(), {"series": CONTROL, "from": record["from"]})
        panel.source("No labels")
        self.assertNotIn(ol.LABELS, panel.inspector.draft)
        self.assertEqual(panel.texts(), [])

    def test_invalid_entries_are_flagged_and_not_previewed(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.source("Etichetta")
        panel.type(panel.labels.color, "nonsense")
        self.assertIn("valid label color", inspector.errors["label"])
        self.assertNotEqual(panel.draft_record().get("color"), "nonsense")
        panel.type(panel.labels.color, "")
        panel.type(panel.labels.size, "3")
        self.assertIn("between 4 and 72", inspector.errors["label"])
        panel.type(panel.labels.size, "abc")
        self.assertIn("label", inspector.errors)
        panel.type(panel.labels.size, "")
        panel.type(panel.labels.limit, "0")
        self.assertIn("1 to 1000", inspector.errors["label"])
        panel.type(panel.labels.limit, "2.5")
        self.assertIn("1 to 1000", inspector.errors["label"])
        panel.type(panel.labels.limit, "")
        self.assertNotIn("label", inspector.errors)

    def test_an_observation_can_be_hidden_shown_and_reset(self):
        panel = self.panel
        panel.source("Etichetta")
        panel.row(2)  # the second of two identical points
        self.assertTrue(panel.labels.mode.isEnabled())
        self.assertIn("label: Campione $2", panel.labels.point_info.text())
        panel.labels.mode.set("hide")
        self.assertEqual(panel.texts(), ["Campione $1", "Caffè"])
        (item,) = panel.draft_record()["observations"]
        self.assertEqual((item["show"], item["source"]["row"]), (False, 2))
        self.assertEqual(panel.labels.listing.count(), 1)
        self.assertIn("Row 2", panel.labels.listing.item(0).text())
        panel.row(1)  # the point that stays at the same coordinates is untouched
        self.assertEqual(panel.labels.mode.value(), "follow")
        panel.row(2)
        self.assertEqual(panel.labels.mode.value(), "hide")
        panel.labels.mode.set("show")
        self.assertEqual(panel.texts(), VISIBLE)
        panel.labels.mode.set("follow")
        self.assertNotIn("observations", panel.draft_record())
        panel.labels.mode.set("hide")
        panel.labels.listing.setCurrentRow(0)
        panel.labels.reset_selected_button.click()
        self.assertEqual(panel.texts(), VISIBLE)
        self.assertEqual(panel.labels.listing.count(), 0)

    def test_a_click_on_the_graph_selects_the_observation(self):
        panel = self.panel
        panel.source("Etichetta")
        panel.click(2, 4)
        self.assertIn("Caffè", panel.labels.point_info.text())
        panel.labels.mode.set("hide")
        self.assertEqual(panel.texts(), ["Campione $1", "Campione $2"])
        panel.inspector.selector.setCurrentIndex(1)  # another series: the selection is gone
        self.assertFalse(panel.labels.mode.isEnabled())
        self.assertEqual(panel.labels.source.currentText(), "No labels")

    def test_an_observation_needs_a_source_first(self):
        panel = self.panel
        panel.row(1)
        self.assertFalse(panel.labels.mode.isEnabled())
        self.assertIn("Choose the source", panel.labels.point_info.text())

    def test_an_observation_without_text_says_so(self):
        panel = self.panel
        panel.inspector.selector.setCurrentIndex(1)  # Trattamento: rows 5 and 6 have no label text
        panel.source("Etichetta")
        panel.row(5)
        self.assertIn("no label", panel.labels.point_info.text())
        self.assertIn("No observation of this series has a label", panel.labels.summary.text())
        self.assertEqual(panel.texts(), [])

    def test_the_selected_series_is_the_one_that_gets_the_labels(self):
        panel = self.panel
        panel.inspector.selector.setCurrentIndex(1)
        self.assertEqual(panel.points.series.key, TREATED)
        panel.source("Row titles")
        self.assertEqual(panel.texts(TREATED), ["Quinta", "Sesta"])
        self.assertEqual(panel.texts(CONTROL), [])
        self.assertIsNone(panel.draft_record(CONTROL))

    def test_section_reset_and_closing_the_panel(self):
        panel, inspector = self.panel, self.panel.inspector
        panel.source("Etichetta")
        panel.row(2)
        panel.labels.mode.set("hide")
        inspector.reset_section("labels")
        self.assertNotIn(ol.LABELS, inspector.draft)
        self.assertEqual(panel.texts(), [])
        panel.source("Etichetta")
        self.assertTrue(inspector.has_draft)
        inspector.dispose()
        self.assertEqual(panel.texts(), [])
        self.assertIsNone(self.run.style)
        self.assertEqual(panel.commits, [])

    def test_italian_captions(self):
        set_language("it")
        project, _title = new_project()
        run = project.runs[0]
        panel = Panel(self, run, project)
        labels = panel.labels
        self.assertEqual(labels.source.itemText(0), "Nessuna etichetta")
        self.assertEqual(labels.source.itemText(1), "Titoli delle righe")
        panel.source("Etichetta")
        self.assertIn("3 etichette mostrate", labels.summary.text())
        panel.type(labels.color, "nonsense")
        self.assertIn("colore", panel.inspector.errors["label"].lower())
        panel.type(labels.color, "")
        panel.row(2)
        labels.mode.set("hide")
        self.assertEqual(labels.mode.itemText(1), "Mostra sempre")
        self.assertIn("Riga 2", labels.listing.item(0).text())
        self.assertIn("nascosta", labels.listing.item(0).text())

    def test_a_histogram_and_a_series_without_symbols_say_why(self):
        project = Project()
        title = project.load(ALAB)[0]
        for options, method, fragment in (
                ({"Response": "Y", "Bins": 3}, "Histogram", "XY series and scatter plots only"),
                ({"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line"}}, "XY series", "without symbols")):
            run = project.candidate(title, method, options)
            result = compute(run, project.tables[title].frame(mask_excluded=True))
            project.add_result(run, result)
            panel = Panel(self, run)
            self.assertFalse(panel.labels.reason.isHidden())
            self.assertIn(fragment, panel.labels.reason.text())
            self.assertFalse(panel.labels.source.isEnabled())


class SheetEditTests(QtCase):
    """The labels follow the worksheet: rows moved, deleted and added, columns renamed, deleted and created again."""

    def setUp(self):
        set_language("en")
        self.project, self.title = new_project()
        self.run = self.project.runs[0]
        panel = Panel(self, self.run, self.project)
        panel.source("Etichetta")
        panel.type(panel.labels.color, COLOR)
        panel.row(2)
        panel.labels.mode.set("hide")
        self.assertTrue(panel.inspector.apply())
        panel.close()
        self.styled = deepcopy(self.run.style)

    def current(self, slot=0):
        return self.project.runs[slot]

    def test_the_labels_are_drawn_after_a_recalculation(self):
        recalc(self.project)
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])
        self.assertIsNone(self.current().result.style_warning)

    def test_a_label_follows_its_row_when_the_rows_are_reordered(self):
        recalc(self.project, self.project.move_rows(self.title, 1, 2, 3))  # the hidden row goes after the third
        run = self.current()
        self.assertEqual(texts(run, CONTROL), ["Campione $1", "Caffè"])  # still Campione $2 that is hidden
        (status,) = ol.label_statuses(run.result.figure)
        (point,) = status.observations
        series = {item.key: item for item in graph_series(run.result.figure.axes[0])}[CONTROL]
        titles = self.project.tables[self.title].raw["Etichetta"].tolist()
        self.assertEqual((point.state, titles[int(ps.point_map(series.artist).rows[point.index]) - 1]),
                         ("ok", "Campione $2"))  # the override found its row at the new position
        self.assertIsNone(run.result.style_warning)
        recalc(self.project, self.project.move_rows(self.title, 2, 3, 0))  # and back to the top
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])

    def test_a_new_identical_row_does_not_inherit_the_override_of_a_deleted_one(self):
        recalc(self.project, self.project.delete_rows(self.title, [1]))  # Campione $2 and its override go away
        run = self.current()
        self.assertEqual(texts(run, CONTROL), ["Campione $1", "Caffè"])
        (status,) = ol.label_statuses(run.result.figure)
        self.assertEqual([(point.state, point.reason) for point in status.observations], [("suspended", "not_found")])
        self.assertIn("suspended", run.result.style_warning)
        self.assertEqual(run.style, self.styled)  # nothing was lost
        runs = self.project.insert_rows(self.title, 1)
        for column, text in enumerate(("Nuova", "1", "2", "Controllo", "Campione $2")):
            runs = self.project.edit_cell(self.title, 1, column, text)
        recalc(self.project, runs)
        run = self.current()
        self.assertEqual(texts(run, CONTROL), VISIBLE)  # the new row shows: it did not receive the hiding
        (status,) = ol.label_statuses(run.result.figure)
        self.assertEqual(status.observations[0].state, "suspended")
        panel = Panel(self, run, self.project)  # the Inspector lists it and resets it
        self.assertFalse(panel.labels.listing.item(0).icon().isNull())
        panel.labels.listing.setCurrentRow(0)
        panel.labels.reset_selected_button.click()
        self.assertNotIn("observations", panel.draft_record())
        self.assertTrue(panel.inspector.apply())
        self.assertNotIn("observations", self.project.runs[0].style[ol.LABELS][0])

    def test_a_deleted_column_with_the_same_name_back_is_a_new_column(self):
        recalc(self.project, self.project.delete_columns(self.title, [LABEL_COLUMN]))
        run = self.current()
        (status,) = ol.label_statuses(run.result.figure)
        self.assertEqual((status.state, status.reason), ("suspended", "missing"))
        self.assertEqual(texts(run), [])
        self.assertIn("suspended", run.result.style_warning)
        runs = self.project.insert_column(self.title, LABEL_COLUMN, "Etichetta")
        for row, text in enumerate(("Nuovo $1", "Nuovo $2", "Nuovo", "-", "Quinto", "Sesto")):
            runs = self.project.edit_cell(self.title, row, LABEL_COLUMN, text)
        recalc(self.project, runs)
        run = self.current()
        self.assertEqual(ol.label_statuses(run.result.figure)[0].reason, "missing")  # no automatic relink
        self.assertEqual(texts(run), [])
        panel = Panel(self, run, self.project)  # the choice is explicit
        self.assertIn("column no longer in the worksheet", panel.labels.source.currentText())
        self.assertTrue(panel.labels.reason.isHidden())
        panel.source("Etichetta")
        self.assertEqual(panel.texts(CONTROL), ["Nuovo $1", "Nuovo"])  # row 2 is still hidden on purpose
        self.assertTrue(panel.inspector.apply())
        self.assertEqual(texts(self.current(), CONTROL), ["Nuovo $1", "Nuovo"])
        identity = self.project.runs[0].style[ol.LABELS][0]["from"]["id"]
        self.assertTrue(valid_token(identity))
        self.assertNotEqual(identity, "base:5")

    def test_undo_brings_the_deleted_column_and_its_labels_back(self):
        recalc(self.project, self.project.delete_columns(self.title, [LABEL_COLUMN]))
        self.assertEqual(texts(self.current()), [])
        title, runs = self.project.undo()
        self.assertEqual(title, self.title)
        recalc(self.project, runs)
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])

    def test_a_renamed_column_is_still_the_source(self):
        recalc(self.project, self.project.rename_column(self.title, LABEL_COLUMN, "Nome"))
        run = self.current()
        self.assertEqual(texts(run, CONTROL), ["Campione $1", "Caffè"])
        self.assertEqual(ol.label_statuses(run.result.figure)[0].column, "Nome")
        panel = Panel(self, run, self.project)
        self.assertEqual(panel.labels.source.currentText(), "Nome")
        self.assertEqual(self.project.tables[self.title].raw.attrs[COLUMN_IDS]["Nome"], "base:5")
        self.project.undo()
        recalc(self.project)
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])

    def test_a_calculated_column_is_a_source_and_a_new_column_gets_a_new_identity(self):
        self.project.set_formula(self.title, "Doppio", "X * 2")
        frame = self.project.tables[self.title].frame(mask_excluded=True)
        self.assertEqual(ol.column_origin(frame, "Doppio")["id"], "formula:Doppio")
        recalc(self.project, self.project.insert_column(self.title, 0, "Nuova"))
        ids = self.project.tables[self.title].raw.attrs[COLUMN_IDS]
        self.assertEqual(ids["Etichetta"], "base:5")
        self.assertNotIn(ids["Nuova"], {f"base:{number}" for number in range(1, 8)})
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])

    def test_excluding_the_text_cell_removes_the_label_and_including_it_brings_it_back(self):
        dataset = self.project.tables[self.title]
        dataset.excluded.add((0, LABEL_COLUMN))  # the label of row 1
        recalc(self.project, self.project.table_runs(self.title))
        self.assertEqual(texts(self.current(), CONTROL), ["Caffè"])
        dataset.excluded.discard((0, LABEL_COLUMN))
        dataset.excluded.discard((5, LABEL_COLUMN))  # the label of row 6 was excluded in the file
        recalc(self.project, self.project.table_runs(self.title))
        self.assertEqual(texts(self.current(), CONTROL), ["Campione $1", "Caffè"])

    def test_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.alab"
            recalc(self.project, self.project.rename_column(self.title, LABEL_COLUMN, "Nome"))
            self.project.save(path)
            reopened = Project()
            reopened.load(path)
            ready(reopened)
            run = reopened.runs[0]
            self.assertEqual(run.style[ol.LABELS][0]["observations"][0]["show"], False)
            self.assertEqual(reopened.tables[run.title].raw.attrs[COLUMN_IDS]["Nome"], "base:5")
            self.assertEqual(texts(run, CONTROL), ["Campione $1", "Caffè"])
            self.assertEqual(png(run.result.figure), png(self.current().result.figure))
            self.assertIsNone(run.result.style_warning)

    def test_a_file_saved_before_the_feature_still_opens(self):
        project, title = new_project()
        self.assertIsNone(project.runs[0].style)
        self.assertNotIn(COLUMN_IDS, project.tables[title].raw.attrs)  # positional identities until the first edit
        frame = project.tables[title].frame(mask_excluded=True)
        self.assertEqual(frame.attrs[COLUMN_IDS]["Etichetta"], "base:5")

    def test_family_copy_keeps_the_labels_and_their_source(self):
        bundle = duplicate_family(self.project.tables, self.project.layouts, self.project.info_sheets.values(),
                                  ("data", self.title), name="Copia")
        copy = bundle.tables["Copia"]
        self.assertEqual(copy.graph_styles[self.run.slot][ol.LABELS], self.styled[ol.LABELS])
        self.assertIsNot(copy.graph_styles[self.run.slot], self.project.tables[self.title].graph_styles[self.run.slot])
        self.project.apply_family(bundle)
        copied = next(run for run in self.project.runs if run.title == "Copia")
        copied.result = compute(copied, self.project.tables["Copia"].frame(mask_excluded=True))
        self.assertEqual(texts(copied, CONTROL), ["Campione $1", "Caffè"])

    def test_the_graph_warning_names_a_suspended_source(self):
        recalc(self.project, self.project.delete_columns(self.title, [LABEL_COLUMN]))
        run = self.current()
        self.assertIn("Data labels are suspended", graph_warning(run.result.figure, run.style) or "")


class PresentationFlowTests(QtCase):
    """Repetition, templates and the other presentation flows never carry the identity of a row to another sheet."""

    def setUp(self):
        set_language("en")
        self.project, self.title = new_project()
        self.run = self.project.runs[0]
        self.records = [{"series": CONTROL, "from": origin(self.project, self.title), "color": COLOR,
                         "observations": [hide_row(self.run, CONTROL, 2)]}]

    def test_remap_for_another_sheet_keeps_the_columns_and_drops_the_rows(self):
        style = remap_style({ol.LABELS: self.records, "title": "T"}, {"Etichetta": "Nome"})
        (record,) = style[ol.LABELS]
        self.assertEqual(record["from"], {"kind": "column", "name": "Nome"})
        self.assertNotIn("observations", record)
        self.assertEqual(record["color"], COLOR)

    def test_fit_style_drops_the_labels_of_a_series_the_graph_does_not_have(self):
        figure = self.run.result.figure
        fitted, reduced = fit_style(figure, {ol.LABELS: self.records + [
            {"series": "scatter:9:Nowhere", "from": {"kind": ol.ROW_TITLE}}]})
        self.assertTrue(reduced)
        self.assertEqual([record["series"] for record in fitted[ol.LABELS]], [CONTROL])
        self.assertNotIn("observations", fitted[ol.LABELS][0])
        fitted, reduced = fit_style(figure, {ol.LABELS: [{"series": CONTROL, "from": {"kind": ol.ROW_TITLE}}]})
        self.assertFalse(reduced)
        self.assertEqual(len(fitted[ol.LABELS]), 1)

    def test_a_template_leaves_the_labels_out_and_says_so(self):
        self.project.commit_style(self.run, {ol.LABELS: self.records})
        plan = plan_template(self.project.tables, self.project.layouts)
        self.assertTrue(plan.ok, plan.problems)
        codes = {(omission.code, omission.count) for omission in plan.omissions}
        self.assertIn(("labels", 1), codes)
        for spec in plan.template.tables:
            for analysis in spec.analyses:
                self.assertNotIn(ol.LABELS, analysis.style or {})


class ExportFlowTests(QtCase):
    def setUp(self):
        set_language("en")
        self.project, self.title = new_project()
        self.run = self.project.runs[0]
        records = [{"series": CONTROL, "from": origin(self.project, self.title), "color": COLOR, "size": 12}]
        style_run(self.project, self.run, {ol.LABELS: records})
        recalc(self.project)
        self.run = self.project.runs[0]
        self.figure = self.run.result.figure

    def test_files_carry_the_labels_and_no_selection(self):
        panel = Panel(self, self.run, self.project)
        panel.source("Etichetta")  # nothing changes: it is the saved source
        panel.row(2)  # a ring is on screen
        self.assertIsNotNone(getattr(self.figure.axes[0], ps.INDICATOR_ATTR, None))
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {}
            for suffix in ("png", "svg", "pdf"):
                target = Path(tmp) / f"figure.{suffix}"
                export_graph(self.figure, target)
                outputs[suffix] = target.read_bytes()
            self.assertGreater(pixels_of(outputs["png"], COLOR), 100)
            self.assertIn(COLOR.encode(), outputs["svg"])
            self.assertNotIn(ps.INDICATOR_COLOR.encode(), outputs["svg"])
            self.assertTrue(outputs["pdf"].startswith(b"%PDF"))
            ps.clear_indicator(self.figure)
            target = Path(tmp) / "plain.png"
            export_graph(self.figure, target)
            self.assertEqual(target.read_bytes(), outputs["png"])  # the ring was not in the export

    def test_a_layout_embeds_the_graph_with_its_labels(self):
        layout = png(compose_layout("Layout", 1, [self.figure]), 150)
        self.assertGreater(pixels_of(layout, COLOR), 20)
        panel = Panel(self, self.run, self.project)
        panel.row(2)
        self.assertEqual(png(compose_layout("Layout", 1, [self.figure]), 150), layout)

    def test_the_xy_series_has_labels_too(self):
        run = self.project.runs[1]
        records = [{"series": XY, "from": {"kind": ol.ROW_TITLE}}]
        style_run(self.project, run, {ol.LABELS: records})
        recalc(self.project)
        self.assertEqual(texts(self.project.runs[1], XY), ["Riga $α", "Riga $α", "Terza", "Quinta", "Sesta"])
        self.assertIsNone(self.project.runs[1].result.style_warning)


class DatasetTests(unittest.TestCase):
    def test_the_frame_carries_the_identities_of_its_columns(self):
        import pandas as pd

        dataset = Dataset(raw=pd.DataFrame({"A": [1.0], "B": [2.0]}))
        self.assertEqual(dataset.frame().attrs[COLUMN_IDS], {"A": "base:1", "B": "base:2"})


if __name__ == "__main__":
    unittest.main()
