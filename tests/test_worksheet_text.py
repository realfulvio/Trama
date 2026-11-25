"""Text presentation of cells (``analisi.worksheet_text``) and of annotations (``analisi.text_markup``)."""
from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import pypdfium2 as pdfium

from analisi.data import Dataset, load_project, save_project
from analisi.figure_export import export_figure
from analisi.graph_annotations import TextUnderline, validate_annotation
from analisi.presentation import apply_style
from analisi.text_markup import (SUBSCRIPT, SUPERSCRIPT, apply_script, check_renders, displayed, mathtext,
                                 script_state, validate_spans)
from analisi.worksheet_history import WorksheetHistory, WorksheetState
from analisi.worksheet_text import (INHERITED, MIXED, UNIFORM, TextStyles, read_text_styles, validated_style)


def table(rows=6):
    return Dataset(pd.DataFrame({"A": range(rows), "B": [x * 0.5 for x in range(rows)], "C": list("abcdef"[:rows])}))


class TextStylesTests(unittest.TestCase):
    def test_a_selection_is_a_few_runs_not_a_dictionary_of_cells(self):
        styles = TextStyles().apply(["A", "B"], 0, 50_000, {"bold": True, "size": 12})
        self.assertEqual(styles.run_count(), 2)
        self.assertEqual(styles.style_at("A", 49_999), {"size": 12, "bold": True})
        self.assertEqual(styles.style_at("A", 50_000), {})
        self.assertEqual(styles.style_at("C", 0), {})

    def test_a_change_merges_into_runs_and_splits_them(self):
        styles = TextStyles().apply(["A"], 0, 10, {"bold": True})
        styles = styles.apply(["A"], 3, 6, {"color": "#AA0000"})
        self.assertEqual(styles.records(), [["A", 0, 3, {"bold": True}],
                                            ["A", 3, 6, {"color": "#aa0000", "bold": True}],
                                            ["A", 6, 10, {"bold": True}]])
        back = styles.apply(["A"], 3, 6, {"color": None})
        self.assertEqual(back.records(), [["A", 0, 10, {"bold": True}]])

    def test_inherited_uniform_and_mixed(self):
        styles = TextStyles().apply(["A"], 0, 4, {"bold": True, "align": "center"})
        states = styles.states(["A"], 0, 4)
        self.assertEqual((states["bold"].kind, states["bold"].value), (UNIFORM, True))
        self.assertEqual(states["italic"].kind, INHERITED)
        self.assertEqual(styles.states(["A"], 0, 6)["bold"].kind, MIXED)  # two rows have no style
        self.assertEqual(styles.states(["A", "B"], 0, 4)["align"].kind, MIXED)
        self.assertEqual(styles.states(["B"], 0, 4)["align"].kind, INHERITED)
        other = styles.apply(["A"], 0, 2, {"align": "right"})
        self.assertEqual(other.states(["A"], 0, 4)["align"].kind, MIXED)
        self.assertEqual(other.states(["A"], 0, 2)["align"].value, "right")

    def test_restore_text_removes_only_text_attributes(self):
        styles = TextStyles().apply(["A"], 0, 5, {"bold": True, "font": "Courier New", "size": 14})
        self.assertFalse(styles.clear(["A"], 0, 5))
        self.assertEqual(styles.clear(["A"], 2, 3).records(),
                         [["A", 0, 2, {"font": "Courier New", "size": 14, "bold": True}],
                          ["A", 3, 5, {"font": "Courier New", "size": 14, "bold": True}]])

    def test_nothing_changes_returns_the_same_store(self):
        styles = TextStyles().apply(["A"], 0, 5, {"bold": True})
        self.assertIs(styles.apply(["A"], 1, 3, {"bold": True}), styles)
        self.assertIs(styles.clear(["B"], 0, 5), styles)

    def test_values_are_validated(self):
        for bad in ({"size": 5}, {"size": 73}, {"size": float("nan")}, {"size": True}, {"color": "red"},
                    {"color": "#12345"}, {"bold": 1}, {"align": "justify"}, {"font": ""}, {"font": "x" * 200},
                    {"font": "bad\u0001"}, {"other": 1}, {}):
            with self.assertRaises(ValueError, msg=bad):
                validated_style(bad)
            if bad:
                with self.assertRaises(ValueError, msg=bad):
                    TextStyles().apply(["A"], 0, 2, bad)
        self.assertEqual(validated_style({"size": 10.26, "color": "#ABCDEF"}), {"size": 10.5, "color": "#abcdef"})

    def test_rows_inserted_and_deleted_carry_the_runs(self):
        styles = TextStyles().apply(["A"], 2, 6, {"bold": True})
        inserted = styles.insert_rows(4, 2)
        self.assertEqual(inserted.records(), [["A", 2, 4, {"bold": True}], ["A", 6, 8, {"bold": True}]])
        self.assertEqual(styles.insert_rows(0, 3).records(), [["A", 5, 9, {"bold": True}]])
        self.assertEqual(styles.insert_rows(6, 3).records(), [["A", 2, 6, {"bold": True}]])
        self.assertEqual(styles.delete_rows([0, 3]).records(), [["A", 1, 4, {"bold": True}]])
        self.assertEqual(styles.delete_rows([2, 3, 4, 5]).records(), [])
        self.assertIs(styles.delete_rows([]), styles)

    def test_columns_renamed_and_dropped(self):
        styles = TextStyles().apply(["A", "B"], 0, 3, {"italic": True})
        self.assertEqual(styles.rename("A", "Z").records(order=["Z", "B"])[0][0], "Z")
        self.assertEqual(sorted(styles.rename_many({"A": "B", "B": "A"}).runs), ["A", "B"])
        self.assertEqual(sorted(styles.drop(["A"]).runs), ["B"])
        self.assertEqual(styles.clip(2).records(), [["A", 0, 2, {"italic": True}], ["B", 0, 2, {"italic": True}]])

    def test_saved_runs_are_read_back_and_malformed_ones_refused(self):
        styles = TextStyles().apply(["A", "B"], 1, 5, {"bold": True, "color": "#112233"})
        records = styles.records(["A", "B"])
        self.assertEqual(read_text_styles(json.loads(json.dumps(records)), 6, {"A", "B"}), styles)
        for bad in ("x", [[]], [["Z", 0, 1, {"bold": True}]], [["A", 0, 9, {"bold": True}]],
                    [["A", 3, 3, {"bold": True}]], [["A", -1, 2, {"bold": True}]], [["A", 0, 2, {}]],
                    [["A", 0, 2, {"bold": "yes"}]], [["A", 0, 3, {"bold": True}], ["A", 2, 4, {"bold": True}]],
                    [["A", 0, 1, {"bold": True}]] * 2, [["A", True, 2, {"bold": True}]], 5, None):
            with self.assertRaises(ValueError, msg=bad):
                read_text_styles(bad, 6, {"A", "B"})
        self.assertEqual(read_text_styles([["A", 0, 2, {"bold": True}], ["A", 2, 4, {"bold": True}]], 6, {"A"}).records(),
                         [["A", 0, 4, {"bold": True}]])


class DatasetTextTests(unittest.TestCase):
    def test_columns_and_displayed_frame_agree(self):
        data = table()
        data.set_formula("D", "=A*2")
        self.assertEqual(list(data.columns), list(data.frame().columns))

    def test_style_leaves_the_numbers_alone(self):
        data = table()
        before = data.frame().copy()
        data.set_text_style((0, 0, 5, 1), {"bold": True, "size": 14, "color": "#aa0000"})
        pd.testing.assert_frame_equal(data.frame(), before)
        self.assertEqual(data.text_styles.run_count(), 2)
        data.clear_text_style((0, 0, 5, 1))
        self.assertFalse(data.text_styles)

    def test_only_existing_rows_and_columns_take_a_style(self):
        data = table(3)
        data.set_text_style((0, 1, 99, 99), {"italic": True})
        self.assertEqual(data.text_styles.records(data.columns), [["B", 0, 3, {"italic": True}],
                                                                  ["C", 0, 3, {"italic": True}]])

    def test_result_style_restores_and_drops_empty_sheets(self):
        data = table()
        data.set_result_text_style(0, "Fit", (0, 1, 3, 2), (5, 4), {"bold": True})
        self.assertEqual(data.result_text_styles[0]["Fit"].records(), [[1, 0, 4, {"bold": True}],
                                                                       [2, 0, 4, {"bold": True}]])
        data.set_result_text_style(0, "Fit", (0, 1, 3, 2), (5, 4), None)
        self.assertEqual(data.result_text_styles, {})

    def test_project_file_round_trip(self):
        data = table()
        data.set_text_style((1, 0, 3, 2), {"font": "Courier New", "underline": True, "align": "center"})
        data.set_result_text_style(0, "Fit", (0, 0, 1, 1), (4, 3), {"color": "#00ff00"})
        data.analyses = [("Descriptive statistics", {})]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "text.alab"
            save_project(path, {"T": data})
            restored = load_project(path)["T"]
        self.assertEqual(restored.text_styles, data.text_styles)
        self.assertEqual(restored.result_text_styles, data.result_text_styles)
        self.assertEqual(restored.text_styles.style_at("B", 2), {"font": "Courier New", "underline": True,
                                                                 "align": "center"})

    def test_a_file_without_text_styles_has_no_new_keys(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "plain.alab"
            save_project(path, {"T": table()})
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("text_styles", text)

    def test_a_file_with_invalid_text_styles_is_refused(self):
        data = table()
        data.set_text_style((0, 0, 1, 0), {"bold": True})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "good.alab"
            save_project(path, {"T": data})
            document = json.loads(path.read_text(encoding="utf-8"))
            record = next(iter(document["tables"].values())) if isinstance(document["tables"], dict) \
                else document["tables"][0]
            self.assertIn("text_styles", record)
            for bad in ([["Missing", 0, 1, {"bold": True}]], [["A", 0, 99, {"bold": True}]],
                        [["A", 0, 1, {"size": 3}]], "text"):
                record["text_styles"] = bad
                broken = Path(folder) / "bad.alab"
                broken.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ValueError, msg=bad):
                    load_project(broken)

    def test_undo_and_redo_share_the_store_and_are_one_step(self):
        data = table()
        tables = {"T": data}
        history = WorksheetHistory()
        before = WorksheetState.capture(data)
        data.set_text_style((0, 0, 5, 2), {"bold": True})
        data.set_text_style((0, 0, 5, 2), {"color": "#112233"})
        history.record("T", "Text format", before, WorksheetState.capture(data))
        self.assertEqual(len(history.changes), 1)
        history.apply(tables)
        self.assertFalse(data.text_styles)
        history.apply(tables, redo=True)
        self.assertEqual(data.text_styles.style_at("A", 0), {"color": "#112233", "bold": True})

    def test_the_style_is_not_a_data_change(self):
        data = table()
        before = WorksheetState.capture(data)
        data.set_text_style((0, 0, 2, 0), {"bold": True})
        after = WorksheetState.capture(data)
        self.assertTrue(before.changed(after))
        self.assertFalse(before.data_changed(after))
        self.assertIsNot(copy(data).text_styles, None)


class ScriptMarkupTests(unittest.TestCase):
    def test_spans_are_validated_merged_and_bounded(self):
        self.assertEqual(validate_spans("CO2 x", [[2, 3, SUBSCRIPT]]), [[2, 3, SUBSCRIPT]])
        self.assertEqual(validate_spans("abcd", [[0, 2, SUBSCRIPT], [2, 4, SUBSCRIPT]]), [[0, 4, SUBSCRIPT]])
        for bad in ([[3, 2, SUBSCRIPT]], [[0, 9, SUBSCRIPT]], [[0, 2, 9]], [[0, 2, SUBSCRIPT], [1, 3, SUPERSCRIPT]],
                    [[0, 1.5, SUBSCRIPT]], "x", [[0, 1]], [[True, 2, SUBSCRIPT]], [[0, 2, SUBSCRIPT]] * 201):
            with self.assertRaises(ValueError, msg=bad):
                validate_spans("abcd", bad)
        with self.assertRaises(ValueError):
            validate_spans("ab\ncd", [[1, 4, SUBSCRIPT]])  # a span never crosses a line break

    def test_apply_script_replaces_clears_and_formats_each_line(self):
        spans = apply_script("CO2 e 10-3", [], 2, 3, SUBSCRIPT)
        spans = apply_script("CO2 e 10-3", spans, 8, 10, SUPERSCRIPT)
        self.assertEqual(spans, [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]])
        self.assertEqual(apply_script("CO2 e 10-3", spans, 2, 3, None), [[8, 10, SUPERSCRIPT]])
        self.assertEqual(apply_script("CO2 e 10-3", spans, 0, 10, None), [])
        self.assertEqual(apply_script("ab\ncd", [], 0, 5, SUBSCRIPT), [[0, 2, SUBSCRIPT], [3, 5, SUBSCRIPT]])
        with self.assertRaises(ValueError):
            apply_script("ab", [], 0, 2, 4)

    def test_script_state(self):
        spans = [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]]
        self.assertEqual(script_state(spans, 0, 2)[0], INHERITED)
        self.assertEqual(script_state(spans, 2, 3), (UNIFORM, SUBSCRIPT))
        self.assertEqual(script_state(spans, 0, 10)[0], MIXED)
        self.assertEqual(script_state(spans, 2, 4)[0], MIXED)
        self.assertEqual(script_state(spans, 5, 5)[0], INHERITED)

    def test_the_math_string_spells_out_what_mathtext_would_read(self):
        text = "CO2 {x} 100% 10-3 $"
        spans = validate_spans(text, [[2, 3, SUBSCRIPT], [13, 15, SUPERSCRIPT]])
        string = mathtext(text, spans)
        self.assertTrue(string.startswith("CO$_{"))
        self.assertIn(r"\$", string)
        check_renders(text, spans)
        self.assertEqual(displayed("plain", []), "plain")
        self.assertEqual(displayed("CO2", [[2, 3, SUBSCRIPT]]), mathtext("CO2", [[2, 3, SUBSCRIPT]]))

    def test_annotation_records_reject_formatting_that_cannot_be_drawn(self):
        base = {"text": "CO2", "units": "axes", "position": [.1, .5], "color": "#174e78", "size": 11,
                "align": "left"}
        validate_annotation({**base, "spans": [[2, 3, SUBSCRIPT]], "bold": True, "italic": False, "font": "DejaVu Sans"})
        for extra in ({"spans": [[2, 9, SUBSCRIPT]]}, {"bold": 1}, {"font": ""}, {"font": "x" * 300},
                      {"underline": "yes"}, {"spans": "x"}, {"unknown": 1}):
            with self.assertRaises(ValueError, msg=extra):
                validate_annotation({**base, **extra})


class AnnotationRenderingTests(unittest.TestCase):
    RECORD = {"text": "CO2 e 10-3\nsecond line", "units": "axes", "position": [.1, .5], "color": "#174e78",
              "size": 13, "align": "left", "spans": [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]], "bold": True,
              "italic": True, "underline": True, "font": "DejaVu Sans"}

    def figure(self, record=None):
        figure = Figure(figsize=(4, 3))
        FigureCanvasAgg(figure)
        axes = figure.add_subplot()
        axes.plot([1, 2, 3], [2, 4, 8])
        apply_style(figure, {"annotations": [record or self.RECORD]})
        return figure, axes

    def test_text_is_drawn_with_scripts_but_the_record_stays_plain(self):
        figure, axes = self.figure()
        artist = axes.texts[0]
        self.assertTrue(artist.get_text().startswith("CO$_{"))
        self.assertIn(r"\mathbfit{2}", artist.get_text())
        self.assertEqual(self.RECORD["text"], "CO2 e 10-3\nsecond line")
        self.assertEqual(artist.get_fontfamily(), ["DejaVu Sans"])
        self.assertEqual((artist.get_fontweight(), artist.get_fontstyle()), ("bold", "italic"))
        self.assertEqual(sum(isinstance(item, TextUnderline) for item in axes.get_children()), 1)
        figure.canvas.draw()
        self.assertGreater(artist.get_window_extent(figure.canvas.get_renderer()).width, 10)

    def test_a_redraw_never_leaves_a_second_copy(self):
        figure, axes = self.figure()
        apply_style(figure, {"annotations": [self.RECORD]})
        apply_style(figure, {"annotations": [self.RECORD]})
        self.assertEqual(len(axes.texts), 1)
        self.assertEqual(sum(isinstance(item, TextUnderline) for item in axes.get_children()), 1)
        apply_style(figure, {})
        self.assertEqual(len(axes.texts), 0)
        self.assertEqual(sum(isinstance(item, TextUnderline) for item in axes.get_children()), 0)

    def test_png_pdf_and_svg_keep_the_effective_formatting(self):
        figure, _axes = self.figure()
        with TemporaryDirectory() as folder:
            png = Path(folder) / "scripts.png"
            export_figure(figure, png, {"format": "png", "dpi": 150})
            self.assertGreater(png.stat().st_size, 1000)
            pdf = Path(folder) / "scripts.pdf"
            export_figure(figure, pdf, {"format": "pdf"})
            with pdfium.PdfDocument(pdf) as document:
                text = document[0].get_textpage().get_text_range()
            self.assertIn("CO", text)
            self.assertIn("second line", text)
            svg = Path(folder) / "scripts.svg"
            export_figure(figure, svg, {"format": "svg", "svg_text": "text"})
            source = svg.read_text(encoding="utf-8")
            self.assertIn("second line", source)
            self.assertIn("<path", source)  # the underline is a vector line, not a bitmap
            self.assertNotIn("<image", source)

    def test_plain_annotation_is_unchanged_by_the_new_fields(self):
        record = {"text": "p < 0.05", "units": "axes", "position": [.2, .2], "color": "#000000", "size": 10,
                  "align": "left"}
        figure, axes = self.figure(record)
        artist = axes.texts[0]
        self.assertEqual(artist.get_text(), "p < 0.05")
        self.assertEqual(sum(isinstance(item, TextUnderline) for item in axes.get_children()), 0)
        self.assertEqual((artist.get_fontweight(), artist.get_fontstyle()), ("normal", "normal"))


if __name__ == "__main__":
    unittest.main()
