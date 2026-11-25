"""Labels of the observations: engine, text rules, limit, identity of the observations and of the columns, exports
(no Qt)."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re
import unittest
from unittest import mock

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analisi import observation_labels as ol
from analisi import point_style as ps
from analisi import worksheet_column_identity as wci
from analisi.i18n import set_language
from analisi.observation_label_text import EN, IT
from analisi.presentation import (apply_style, capture_defaults, compose_layout, graph_series, validate_graph_style,
                                  validated_style)
from analisi.workbench import analyse
from analisi.xy_series import xy_series

CASES = json.loads((Path(__file__).resolve().parent / "data" / "observation_labels" / "casi.json").read_text("utf-8"))
SCATTER = "Scatter / confidence ellipse"
COLOR = "#aa2288"
CONTROL, TREATED = "scatter:1:Controllo", "scatter:1:Trattamento"


def worksheet(**changes):
    """The worksheet of the package: duplicate points, a missing Y, an empty label and an excluded label."""
    data = {"Row title": ["Riga $α", "Riga $α", "Terza", "Senza Y", "Quinta", "Sesta"],
            "X": [1, 1, 2, 3, 4, 5], "Y": [2, 2, 4, np.nan, 5, 8],
            "Gruppo": ["Controllo"] * 4 + ["Trattamento"] * 2,
            "Etichetta": ["Campione $1", "Campione $2", "Caffè", "Nessun punto", pd.NA, pd.NA]}
    data.update(changes)
    frame = pd.DataFrame(data)
    frame.attrs[wci.COLUMN_IDS] = wci.current_ids(frame)
    return frame


def scatter(frame=None):
    frame = worksheet() if frame is None else frame
    figure = analyse(SCATTER, frame, {"X": "X", "Y": "Y", "Group": "Gruppo"}).figure
    capture_defaults(figure)
    return figure


def xy(frame=None, style="Line and points"):
    frame = worksheet() if frame is None else frame
    figure = xy_series(frame, {"X": "X", "Y columns": ["Y"], "Series style": {"Y": style}}).figure
    capture_defaults(figure)
    return figure


def series_of(figure, key):
    return {item.key: item for item in graph_series(figure.axes[0])}[key]


def source(figure, name="Etichetta", key=CONTROL):
    frame = ps.point_map(series_of(figure, key).artist).data
    return ol.column_origin(frame, name)


def labelled(figure, key=CONTROL, **fields):
    """A label record for series ``key`` reading the column Etichetta."""
    return {"series": key, "from": source(figure, key=key), **fields}


def override(figure, key, row, show):
    pmap = ps.point_map(series_of(figure, key).artist)
    index = int(np.flatnonzero(pmap.rows == row)[0])
    return {"source": ps.source_record(pmap, index), "show": show}


def texts(figure, key=None):
    return [text for series, text in ol.label_texts(figure) if key in (None, series)]


def png(figure, dpi=100):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    return buffer.getvalue()


def pixels_of(data, color, tolerance=0.02):
    """How many pixels have (nearly) ``color``; small text is antialiased, so a text asks for a wider tolerance."""
    image = plt.imread(BytesIO(data))
    target = np.array(matplotlib.colors.to_rgb(color))
    return int(np.sum(np.all(np.abs(image[..., :3] - target) < tolerance, axis=-1)))


def state(figure):
    """What labels must never change: legend, limits, series, the artists of the axes other than the labels."""
    axes = figure.axes[0]
    legend = axes.get_legend()
    return {"legend": [text.get_text() for text in legend.get_texts()] if legend else None,
            "xlim": axes.get_xlim(), "ylim": axes.get_ylim(),
            "series": [item.key for item in graph_series(axes)],
            "children": sorted(type(child).__name__ for child in axes.get_children()
                               if not str(child.get_gid() or "").startswith(ol.GID_PREFIX))}


class ColumnIdentityTests(unittest.TestCase):
    def test_an_unedited_worksheet_has_positional_identities(self):
        frame = pd.DataFrame({"A": [1], "B": [2]})
        self.assertEqual(wci.current_ids(frame), {"A": "base:1", "B": "base:2"})

    def test_a_calculated_column_and_a_derived_frame_are_named(self):
        frame = pd.DataFrame({"A": [1]})
        self.assertEqual(wci.current_ids(frame, ["Double"]), {"A": "base:1", "Double": "formula:Double"})
        self.assertEqual(wci.frame_ids(frame), {"A": "name:A"})  # a result, not a worksheet

    def test_rename_keeps_the_identity_and_a_new_column_never_takes_an_old_one(self):
        frame = pd.DataFrame({"A": [1], "B": [2]})
        renamed = frame.rename(columns={"A": "Z"})
        renamed.attrs[wci.COLUMN_IDS] = wci.after_rename(frame, {"A": "Z"})
        self.assertEqual(wci.current_ids(renamed), {"Z": "base:1", "B": "base:2"})
        without = renamed.drop(columns=["Z"])
        without.attrs[wci.COLUMN_IDS] = wci.after_deletion(renamed, ["Z"])
        self.assertEqual(wci.current_ids(without), {"B": "base:2"})
        recreated = without.assign(Z=[3])
        recreated.attrs[wci.COLUMN_IDS] = wci.after_insertion(without, "Z")
        new = wci.current_ids(recreated)["Z"]
        self.assertNotEqual(new, "base:1")
        self.assertTrue(wci.valid_token(new))
        store = pd.DataFrame({"A": [1]})
        wci.store(store, {"A": "base:1", "Gone": "base:7"})
        self.assertEqual(store.attrs[wci.COLUMN_IDS], {"A": "base:1"})
        wci.store(store, {})
        self.assertNotIn(wci.COLUMN_IDS, store.attrs)

    def test_saved_identities_are_validated(self):
        columns = ["A", "B"]
        self.assertEqual(wci.saved_ids({"A": "base:1"}, columns), {"A": "base:1"})
        for bad in ({"C": "base:1"}, {"A": "base:1", "B": "base:1"}, {"A": "nonsense"}, ["A"], {"A": "base:0"}):
            with self.assertRaises(ValueError):
                wci.saved_ids(bad, columns)
        self.assertEqual(wci.kept_ids({"A": "base:1", "Gone": "base:9"}, columns), {"A": "base:1"})

    def test_references_of_a_style(self):
        for token in ("base:3", "a" * 32 + ":1", "formula:X", "name:Y"):
            self.assertTrue(wci.valid_reference(token), token)
        for token in ("", "base:", "other:1", None, 3, "x" * 2000):
            self.assertFalse(wci.valid_reference(token), token)


class ValidationTests(unittest.TestCase):
    def test_a_well_formed_list_is_accepted_in_a_graph_style(self):
        figure = scatter()
        style = {ol.LABELS: [labelled(figure, show=False, color=COLOR, position="left", size=9, limit=5)]}
        self.assertEqual(validated_style(deepcopy(style)), style)
        validate_graph_style(figure.axes[0], style)

    def test_malformed_records_are_refused_with_exact_messages(self):
        figure = scatter()
        good = labelled(figure)
        cases = [
            ("Invalid label setting.", [{"series": CONTROL}]),
            ("Invalid label setting.", [dict(good, extra=1)]),
            ("Invalid label setting.", ["text"]),
            ("Labels are available in XY series and scatter plots only.", [dict(good, series="bar:1:Y")]),
            ("A series has two label settings.", [good, good]),
            ("Invalid label source.", [dict(good, **{"from": {"kind": "other"}})]),
            ("Invalid label source.", [dict(good, **{"from": {"kind": "column", "name": ""}})]),
            ("Invalid label source.", [dict(good, **{"from": {"kind": "column", "name": "A", "id": "x"}})]),
            ("Invalid label visibility.", [dict(good, show=1)]),
            ("Enter a valid label color, for example #2866ae.", [dict(good, color="nonsense")]),
            ("Choose where the label goes: above, below, left or right.", [dict(good, position="center")]),
            ("Enter a label size between 4 and 72 points.", [dict(good, size=3)]),
            ("Enter a label size between 4 and 72 points.", [dict(good, size=float("nan"))]),
            ("Enter a limit of 1 to 1000 labels.", [dict(good, limit=0)]),
            ("Enter a limit of 1 to 1000 labels.", [dict(good, limit=1001)]),
            ("Enter a limit of 1 to 1000 labels.", [dict(good, limit=2.5)]),
            ("Invalid label of an observation.", [dict(good, observations=[{"show": True}])]),
            ("Invalid label of an observation.", [dict(good, observations="x")]),
            ("An observation has two label settings.",
             [dict(good, observations=[override(figure, CONTROL, 1, True), override(figure, CONTROL, 1, False)])]),
        ]
        for message, records in cases:
            with self.subTest(message=message), self.assertRaises(ValueError) as caught:
                ol.validate_labels(records)
            self.assertEqual(str(caught.exception), message)
        with self.assertRaises(ValueError):
            ol.validate_labels("nothing")

    def test_limits_of_the_list(self):
        figure = scatter()
        good = labelled(figure)
        many = [dict(good, series=f"scatter:{number}:S") for number in range(1, ol.MAX_LABEL_SERIES + 2)]
        with self.assertRaises(ValueError):
            ol.validate_labels(many)
        item = override(figure, CONTROL, 1, True)
        crowd = []
        for row in range(ol.MAX_OVERRIDES + 1):
            source_record = dict(item["source"], row=row + 1, rows=1000, copy=1, copies=1, x=float(row))
            source_record.pop("row_token", None)
            crowd.append({"source": source_record, "show": True})
        with self.assertRaises(ValueError):
            ol.validate_labels([dict(good, observations=crowd)])

    def test_every_engine_message_has_an_italian_text(self):
        figure = scatter()
        good = labelled(figure)
        messages = {"Label up to 64 series.", "Invalid label setting.",
                    "Labels are available in XY series and scatter plots only.", "A series has two label settings.",
                    "Invalid label source.", "Invalid label visibility.",
                    "Enter a valid label color, for example #2866ae.",
                    "Choose where the label goes: above, below, left or right.",
                    "Enter a label size between 4 and 72 points.", "Enter a limit of 1 to 1000 labels.",
                    "Invalid label of an observation.", "Set the labels of up to 256 individual observations.",
                    "An observation has two label settings."}
        self.assertTrue(good)
        set_language("it")
        try:
            for message in messages:
                self.assertNotEqual(ol.translate_label_error(ValueError(message)), message, message)
            self.assertEqual(ol.translate_label_error(ValueError("something else")), "something else")
        finally:
            set_language("en")

    def test_catalogs_have_the_same_keys_and_placeholders(self):
        self.assertEqual(EN.keys(), IT.keys())
        for key in EN:
            self.assertEqual(set(re.findall(r"{(\w+)}", EN[key])), set(re.findall(r"{(\w+)}", IT[key])), key)


class TextRuleTests(unittest.TestCase):
    def test_the_labels_of_the_package(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure), labelled(figure, TREATED)]})
        self.assertEqual(texts(figure, CONTROL), CASES["visible_labels_with_column"])
        self.assertEqual(texts(figure, TREATED), [])  # row 5 is empty, row 6 is excluded
        control, treated = ol.label_statuses(figure)
        self.assertEqual((control.state, control.shown, control.omitted), ("ok", 3, 0))
        self.assertEqual((treated.state, treated.shown, treated.candidates), ("ok", 0, 0))
        self.assertEqual(len(ol.label_layers(figure)), 1)  # a series with nothing to draw adds no artist

    def test_text_is_literal(self):
        figure = scatter(worksheet(Etichetta=["$x^2$", r"\alpha $", "Caffè ☕ ≤ 5", "-", pd.NA, pd.NA]))
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertEqual(texts(figure), ["$x^2$", r"\alpha $", "Caffè ☕ ≤ 5"])
        layer = ol.label_layers(figure)[0]
        self.assertTrue(all(not text.get_parse_math() and not text.get_usetex() for text in layer.texts))
        png(figure)  # drawing never raises a math error

    def test_row_title_and_numeric_columns(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [{"series": CONTROL, "from": {"kind": ol.ROW_TITLE}}]})
        self.assertEqual(texts(figure), ["Riga $α", "Riga $α", "Terza"])
        number = {"series": CONTROL, "from": ol.column_origin(ps.point_map(series_of(figure, CONTROL).artist).data, "X")}
        apply_style(figure, {ol.LABELS: [number]})
        self.assertEqual(texts(figure), ["1", "1", "2"])
        figure = scatter(worksheet(Etichetta=[0.1 + 0.2, 2.50, 1e-9, np.inf, np.nan, 3.0]))
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertEqual(texts(figure), ["0.3", "2.5", "1e-09"])  # an infinite or missing number gives nothing

    def test_empty_blank_missing_and_undrawn_make_no_label(self):
        figure = scatter(worksheet(Etichetta=["", "   ", pd.NA, "Nessun punto", "Quinta", "Sesta"]))
        apply_style(figure, {ol.LABELS: [labelled(figure), labelled(figure, TREATED)]})
        self.assertEqual(texts(figure, CONTROL), [])  # row 4 is not drawn: it has no Y
        self.assertEqual(texts(figure, TREATED), ["Quinta", "Sesta"])

    def test_a_very_long_text_is_cut(self):
        figure = scatter(worksheet(Etichetta=["x" * 500, "b", "c", "d", "e", "f"]))
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertEqual(len(texts(figure)[0]), ol.MAX_TEXT)
        self.assertTrue(texts(figure)[0].endswith("…"))
        self.assertEqual(ol.label_text("a\x00b\ud800"), "ab")

    def test_series_look(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure, color=COLOR, size=11, position="right")]})
        layer = ol.label_layers(figure)[0]
        self.assertEqual({matplotlib.colors.to_hex(text.get_color()) for text in layer.texts}, {COLOR})
        self.assertEqual({text.get_fontsize() for text in layer.texts}, {11.0})
        self.assertEqual({(text.get_ha(), text.get_va()) for text in layer.texts}, {("left", "center")})
        apply_style(figure, {ol.LABELS: [labelled(figure, show=False)]})
        self.assertEqual(texts(figure), [])  # the series is hidden on purpose
        self.assertEqual(ol.label_statuses(figure)[0].state, "ok")


class OverrideAndLimitTests(unittest.TestCase):
    def test_hiding_one_of_two_identical_points_keeps_the_other(self):
        figure = scatter()
        record = labelled(figure, observations=[override(figure, CONTROL, 2, False)])
        apply_style(figure, {ol.LABELS: [record]})
        self.assertEqual(texts(figure), ["Campione $1", "Caffè"], CASES["duplicate"])
        record = labelled(figure, observations=[override(figure, CONTROL, 1, False)])
        apply_style(figure, {ol.LABELS: [record]})
        self.assertEqual(texts(figure), ["Campione $2", "Caffè"])

    def test_an_override_keeps_to_its_point_in_the_list_of_statuses(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure, observations=[override(figure, CONTROL, 3, False)])]})
        (status,) = ol.label_statuses(figure)
        self.assertEqual([(point.state, point.row) for point in status.observations], [("ok", 3)])
        self.assertEqual(texts(figure), ["Campione $1", "Campione $2"])

    def test_the_limit_and_its_priority(self):
        count = 12
        frame = pd.DataFrame({"X": np.arange(count, dtype=float), "Y": np.arange(count, dtype=float) % 5,
                              "G": ["S"] * count, "L": [f"L{number}" for number in range(1, count + 1)]})
        frame.attrs[wci.COLUMN_IDS] = wci.current_ids(frame)
        figure = analyse(SCATTER, frame, {"X": "X", "Y": "Y", "Group": "G"}).figure
        capture_defaults(figure)
        key = "scatter:1:S"
        origin = ol.column_origin(frame, "L")
        record = {"series": key, "from": origin, "limit": 5,
                  "observations": [override(figure, key, 11, True), override(figure, key, 12, True),
                                   override(figure, key, 1, False), override(figure, key, 2, False)]}
        apply_style(figure, {ol.LABELS: [record]})
        # The overrides that show come first, then the others in worksheet order; rows 1 and 2 never count.
        self.assertEqual(texts(figure), ["L3", "L4", "L5", "L11", "L12"])
        (status,) = ol.label_statuses(figure)
        self.assertEqual((status.candidates, status.shown, status.omitted, status.limit), (10, 5, 5, 5))
        apply_style(figure, {ol.LABELS: [dict(record, limit=1)]})
        self.assertEqual(texts(figure), ["L11"])  # the explicit choices first, in worksheet order
        apply_style(figure, {ol.LABELS: [{"series": key, "from": origin}]})
        self.assertEqual(len(texts(figure)), count)

    def test_default_limit_is_250_and_reports_the_rest(self):
        count = 300
        frame = pd.DataFrame({"X": np.arange(count, dtype=float), "Y": np.sin(np.arange(count)), "G": ["S"] * count,
                              "L": [str(number) for number in range(count)]})
        frame.attrs[wci.COLUMN_IDS] = wci.current_ids(frame)
        figure = analyse(SCATTER, frame, {"X": "X", "Y": "Y", "Group": "G"}).figure
        capture_defaults(figure)
        apply_style(figure, {ol.LABELS: [{"series": "scatter:1:S", "from": ol.column_origin(frame, "L")}]})
        (status,) = ol.label_statuses(figure)
        self.assertEqual((ol.DEFAULT_LIMIT, status.shown, status.omitted, status.candidates), (250, 250, 50, 300))
        self.assertEqual(texts(figure), [str(number) for number in range(250)])

    def test_a_series_without_a_record_is_never_read(self):
        figure = scatter()
        records = [labelled(figure)]
        calls = []
        real = ol._text_mask
        with mock.patch.object(ol, "_text_mask", side_effect=lambda values: calls.append(len(values)) or real(values)):
            apply_style(figure, {ol.LABELS: records})
            self.assertEqual(calls, [3])  # one pass over the vertices of the labelled series only
            for _ in range(3):  # redrawing needs no pass over the data
                png(figure)
                figure.canvas.draw()
            self.assertEqual(calls, [3])
            apply_style(figure, {})
            apply_style(figure, {"title": "No labels"})
            self.assertEqual(calls, [3])  # without records nothing is looked at
        self.assertEqual(ol.label_layers(figure), [])

    def test_labels_outside_the_axes_are_not_drawn(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure)], "axis": {"x": {"min": 0.5, "max": 1.5}}})
        (layer,) = ol.label_layers(figure)
        figure.canvas.draw()
        self.assertEqual(list(layer.inside()), [True, True, False])
        self.assertEqual(figure.axes[0].get_xlim(), (0.5, 1.5))  # the labels never move the limits


class SourceTests(unittest.TestCase):
    def test_a_deleted_column_leaves_the_source_missing_even_when_the_name_comes_back(self):
        frame = worksheet()
        figure = scatter(frame)
        record = labelled(figure)
        recreated = frame.drop(columns=["Etichetta"]).assign(Etichetta=["Nuovo $1", "Nuovo $2", "Nuovo", "x", "y", "z"])
        recreated.attrs[wci.COLUMN_IDS] = wci.after_insertion(frame.drop(columns=["Etichetta"]), "Etichetta")
        again = scatter(recreated)
        apply_style(again, {ol.LABELS: [record]})
        (status,) = ol.label_statuses(again)
        self.assertEqual((status.state, status.reason), ("suspended", "missing"), CASES["remove_label_column"])
        self.assertEqual(texts(again), [])
        # Choosing the column again is explicit
        apply_style(again, {ol.LABELS: [dict(record, **{"from": source(again)})]})
        self.assertEqual(texts(again), ["Nuovo $1", "Nuovo $2", "Nuovo"])

    def test_a_renamed_column_is_followed(self):
        frame = worksheet()
        record = labelled(scatter(frame))
        renamed = frame.rename(columns={"Etichetta": "Nome"})
        renamed.attrs[wci.COLUMN_IDS] = wci.after_rename(frame, {"Etichetta": "Nome"})
        figure = scatter(renamed)
        apply_style(figure, {ol.LABELS: [record]})
        self.assertEqual(texts(figure), CASES["visible_labels_with_column"])
        self.assertEqual(ol.label_statuses(figure)[0].column, "Nome")

    def test_a_source_without_identity_is_found_by_name(self):
        figure = scatter()
        record = {"series": CONTROL, "from": {"kind": "column", "name": "Etichetta"}}
        apply_style(figure, {ol.LABELS: [record]})
        self.assertEqual(texts(figure), CASES["visible_labels_with_column"])
        apply_style(figure, {ol.LABELS: [{"series": CONTROL, "from": {"kind": "column", "name": "Nowhere"}}]})
        self.assertEqual(ol.label_statuses(figure)[0].reason, "missing")

    def test_no_row_title_column(self):
        figure = scatter(worksheet().drop(columns=["Row title"]))
        apply_style(figure, {ol.LABELS: [{"series": CONTROL, "from": {"kind": ol.ROW_TITLE}}]})
        self.assertEqual(ol.label_statuses(figure)[0].reason, "no_title")

    def test_the_choices_of_the_inspector(self):
        choices = ol.source_choices(worksheet())
        self.assertEqual([caption for _, caption in choices], ["Row title", "X", "Y", "Gruppo", "Etichetta"])
        self.assertEqual(choices[0][0], {"kind": ol.ROW_TITLE})
        self.assertEqual(choices[-1][0], {"kind": "column", "name": "Etichetta", "id": "base:5"})

    def test_a_graph_without_its_worksheet_says_so(self):
        figure = scatter()
        series_of(figure, CONTROL).artist._tramastat_points = ps.PointMap(
            *(getattr(ps.point_map(series_of(figure, CONTROL).artist), name) for name in
              ("rows", "x", "y", "drawn", "recipe", "sheet_rows")))
        apply_style(figure, {ol.LABELS: [{"series": CONTROL, "from": {"kind": ol.ROW_TITLE}}]})
        self.assertEqual(ol.label_statuses(figure)[0].reason, "no_data")


class SupportTests(unittest.TestCase):
    def test_xy_series_with_symbols(self):
        figure = xy()
        key = "xy:1:Y"
        apply_style(figure, {ol.LABELS: [{"series": key, "from": source(figure, key=key)}]})
        self.assertEqual(texts(figure), CASES["visible_labels_with_column"])  # row 4 has no Y, rows 5-6 no text
        self.assertEqual(ol.label_statuses(figure)[0].state, "ok")

    def test_a_series_drawn_without_symbols_or_missing_is_suspended_with_a_reason(self):
        figure = xy(style="Line")
        key = "xy:1:Y"
        record = {"series": key, "from": source(figure, key=key)}
        apply_style(figure, {ol.LABELS: [record, {"series": "xy:9:Other", "from": record["from"]}]})
        reasons = [status.reason for status in ol.label_statuses(figure)]
        self.assertEqual(reasons, ["no_symbols", "no_series"])
        self.assertEqual(ol.label_layers(figure), [])
        self.assertIn("without symbols", ol.reason_text(ol.label_statuses(figure)[0], record))

    def test_axis_breaks_suspend_the_labels(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertEqual(len(texts(figure)), 3)
        statuses = ol._apply_record(figure, series_of(figure, CONTROL), labelled(figure), True, ol._State(), None)
        self.assertEqual(statuses.reason, "breaks")

    def test_style_apply_is_idempotent(self):
        figure = scatter()
        style = {ol.LABELS: [labelled(figure, observations=[override(figure, CONTROL, 2, False)])]}
        apply_style(figure, style)
        first = (state(figure), texts(figure), len(figure.axes[0].get_children()))
        for _ in range(3):
            apply_style(figure, deepcopy(style))
        self.assertEqual((state(figure), texts(figure), len(figure.axes[0].get_children())), first)
        self.assertEqual(len(ol.label_layers(figure)), 1)
        apply_style(figure, {})
        self.assertEqual(ol.label_layers(figure), [])
        self.assertEqual(len(figure.axes[0].get_children()), first[2] - 1)

    def test_legend_axes_and_series_do_not_change(self):
        figure = scatter()
        before = state(figure)
        picture = png(figure)
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertEqual(state(figure), before)
        self.assertNotEqual(png(figure), picture)
        apply_style(figure, {})
        self.assertEqual(png(figure), picture)  # taking the labels away restores the graph exactly

    def test_a_hidden_series_hides_its_labels(self):
        figure = scatter()
        apply_style(figure, {ol.LABELS: [labelled(figure, color=COLOR)]})
        (layer,) = ol.label_layers(figure)
        shown = pixels_of(png(figure, 150), COLOR, 0.15)
        series_of(figure, CONTROL).artist.set_visible(False)  # the layer follows its series at every drawing
        self.assertEqual(pixels_of(png(figure, 150), COLOR, 0.15), 0)
        series_of(figure, CONTROL).artist.set_visible(True)
        self.assertEqual(pixels_of(png(figure, 150), COLOR, 0.15), shown)
        self.assertTrue(layer.get_visible())


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.figure = scatter()
        self.plain = png(self.figure, 150)
        apply_style(self.figure, {ol.LABELS: [labelled(self.figure, color=COLOR, size=12)]})

    def test_png_carries_the_labels(self):
        self.assertEqual(pixels_of(self.plain, COLOR, 0.15), 0)
        self.assertGreater(pixels_of(png(self.figure, 150), COLOR, 0.15), 40)

    def test_vector_exports_carry_the_labels(self):
        with matplotlib.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
            buffer = BytesIO()
            self.figure.savefig(buffer, format="svg")
            svg = buffer.getvalue().decode("utf-8")
            pdf = BytesIO()
            self.figure.savefig(pdf, format="pdf")
        self.assertIn("Campione $1", svg)
        self.assertIn("Caffè", svg)
        self.assertIn(COLOR, svg)
        self.assertIn(ol.GID_PREFIX + CONTROL, svg)
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))
        plain = BytesIO()
        scatter().savefig(plain, format="pdf")
        self.assertNotEqual(pdf.getvalue(), plain.getvalue())
        outlined = BytesIO()
        with matplotlib.rc_context({"svg.fonttype": "path"}):
            self.figure.savefig(outlined, format="svg")
        self.assertIn(COLOR, outlined.getvalue().decode("utf-8"))

    def test_a_layout_embeds_the_labels(self):
        layout = png(compose_layout("Layout", 1, [self.figure]), 150)
        bare = png(compose_layout("Layout", 1, [scatter()]), 150)
        self.assertGreater(pixels_of(layout, COLOR, 0.15), 20)
        self.assertEqual(pixels_of(bare, COLOR, 0.15), 0)

    def test_the_selection_ring_is_not_in_an_export(self):
        before = png(self.figure, 150)
        ps.show_indicator(series_of(self.figure, CONTROL), 0)
        self.assertEqual(self.figure.axes[0].get_children().count(getattr(self.figure.axes[0], ps.INDICATOR_ATTR)), 1)
        self.assertEqual(png(self.figure, 150), before)
        ps.clear_indicator(self.figure)

    def test_the_graph_keeps_its_labels_at_another_size(self):
        small = png(self.figure, 60)
        large = png(self.figure, 300)
        self.assertGreater(pixels_of(small, COLOR, 0.15), 5)
        self.assertGreater(pixels_of(large, COLOR, 0.15), pixels_of(small, COLOR, 0.15))


class StyleHelperTests(unittest.TestCase):
    def test_with_series_removes_defaults_and_empty_records(self):
        figure = scatter()
        origin = source(figure)
        records = ol.with_series([], CONTROL, **{"from": origin, "show": True, "position": "above", "size": 8.0,
                                                 "limit": ol.DEFAULT_LIMIT, "color": None})
        self.assertEqual(records, [{"series": CONTROL, "from": origin}])
        records = ol.with_series(records, CONTROL, position="left", show=False)
        self.assertEqual(records[0]["position"], "left")
        self.assertEqual(ol.with_series(records, CONTROL, **{"from": None}), [])
        self.assertEqual(ol.with_series([], CONTROL, position="left"), [])  # nothing without a source

    def test_overrides_are_added_changed_and_removed(self):
        figure = scatter()
        series = series_of(figure, CONTROL)
        pmap = ps.point_map(series.artist)
        records = [labelled(figure)]
        records = ol.with_override(records, None, CONTROL, pmap, 0, False)
        self.assertEqual([item["show"] for item in records[0]["observations"]], [False])
        apply_style(figure, {ol.LABELS: records})
        status = ol.label_statuses(figure)[0]
        self.assertEqual(ol.override_of(records[0], status, 0), False)
        self.assertIsNone(ol.override_of(records[0], status, 1))
        records = ol.with_override(records, status, CONTROL, pmap, 0, True)
        self.assertEqual([item["show"] for item in records[0]["observations"]], [True])
        records = ol.with_override(records, status, CONTROL, pmap, 0, None)
        self.assertNotIn("observations", records[0])
        again = ol.with_override(records, status, CONTROL, pmap, 1, False)
        self.assertEqual(ol.without_override(again, CONTROL, 0)[0].get("observations"), None)

    def test_text_at_and_status_line(self):
        figure = scatter()
        series = series_of(figure, CONTROL)
        self.assertEqual(ol.text_at(series, labelled(figure), 2), "Caffè")
        self.assertEqual(ol.text_at(series, {"series": CONTROL, "from": {"kind": "column", "name": "Nowhere"}}, 0), "")
        record = {"series": CONTROL, "from": {"kind": "column", "name": "Nowhere"}}
        apply_style(figure, {ol.LABELS: [record]})
        self.assertIn("suspended", ol.label_status_line(figure, [record]))
        self.assertIn("Nowhere", ol.label_status_line(figure, [record]))
        apply_style(figure, {ol.LABELS: [labelled(figure)]})
        self.assertIsNone(ol.label_status_line(figure, [labelled(figure)]))

    def test_remap_for_another_sheet_keeps_columns_and_drops_rows(self):
        figure = scatter()
        record = labelled(figure, observations=[override(figure, CONTROL, 1, False)], color=COLOR)
        remapped = ol.remap_labels([record], {"Etichetta": "Nome", "Gruppo": "Classe"})
        self.assertEqual(remapped, [{"series": CONTROL, "from": {"kind": "column", "name": "Nome"}, "color": COLOR}])
        keyed = {"series": "xy:1:Y", "from": {"kind": ol.ROW_TITLE}}
        self.assertEqual(ol.remap_labels([keyed], {"Y": "Z"})[0]["series"], "xy:1:Z")
        self.assertEqual(ol.strip_labels({ol.LABELS: [record], "title": "T"}), {"title": "T"})


if __name__ == "__main__":
    unittest.main()
